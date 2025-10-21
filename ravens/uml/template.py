from __future__ import annotations

import json
from collections import deque
from typing import Dict, List, Set, Tuple, Optional, Literal
import networkx as nx

from ravens.data import _TEMPLATE_JSON_PATH, _TEMPLATE_AUTOJSON_PATH


class TemplateGenerator:
    """
    Build an auto_template using only the inheritance graph H (child -> parent).

    Placement rules (H-only, tag-light):
      • Concrete = nodes tagged 'rootClass' or 'embeddedClass'.
      • Anchor containers (top-level under Root) = nodes having >= 2 concrete descendants in H.
        (E.g., 'Versions' becomes a container even if its tag says inheritOnly.)
      • Concrete nodes with no qualifying ancestor anchor -> placed directly under Root.
      • Under each container anchor, emit its nearest concrete descendants.
      • A class is defined exactly once; additional appearances are references.
      • Cross-references are enabled.

    We do not use A at all in this pass and we do not trust notConcrete tags for placement
    (we only read 'rootClass'/'embeddedClass' to know what is "concrete").
    """

    def __init__(self, *, H: nx.DiGraph, A: Optional[nx.MultiDiGraph] = None, root_name: str = "Root"):
           
            if not isinstance(H, nx.DiGraph):
                raise TypeError("H must be a networkx.DiGraph oriented child -> parent.")
            self.H: nx.DiGraph = H
            self.HR: nx.DiGraph = H.reverse(copy=False)
            self.A = A 
            self.root_name = root_name

            # Find Root in either graph by Name
            def _find_root_id(G):
                hits = [int(n) for n, d in G.nodes(data=True) if (d.get("Name") or "").strip() == self.root_name]
                return hits[0] if hits else None

            self.root_id = _find_root_id(self.A) or _find_root_id(self.H)
            if self.root_id is None:
                raise ValueError(f"No node named '{self.root_name}' in A or H.")

            # simple name accessor that works off either graph
            self._name = lambda nid: (self.A.nodes[nid].get("Name")
                                    if nid in self.A else self.H.nodes[nid].get("Name")) or ""

            # Role map from node tags (only used to detect concrete)
            self.role_map: Dict[int, str] = {
                int(n): (d.get("ravensRole") or "").strip()
                for n, d in self.H.nodes(data=True)
            }

            # Where a node is defined (object) or only referenced
            self.def_ptr: Dict[int, Optional[dict]] = {}
            self.path_map: Dict[int, Tuple[str, ...]] = {}

            # Cross-refs ON by default
            self.EMIT_CROSS_REFS: bool = True

            self._FIELD_ORDER = {
                            "schema": [
                                "title", "$schema", "$id", "type",
                                "$primaryObjectHash", "$secondaryObjectHash",
                                "properties",
                            ],
                            "object": [
                                "$objectType", "type", "$objectId",
                                "$primaryObjectHash", "$secondaryObjectHash",
                                "properties",
                            ],
                            "container": [
                                "$objectType", "type", "properties",
                            ],
                            "reference": [
                                "$objectType", "type", "$objectId", "$referencePath", "properties",
                            ],
                        }


    # -------------------- basic helpers --------------------

    def _role(self, n: int) -> str:
        return (self.role_map.get(int(n)) or "").strip()

    def _is_concrete(self, n: int) -> bool:
        r = self._role(n)
        return r in ("rootClass", "embeddedClass")

    def _name(self, n: int) -> str:
        nm = (self.H.nodes[int(n)].get("Name") or "").strip()
        return nm.split(" (")[0]  # strip EA suffixes if present

    @staticmethod
    def _path_str(segments: Tuple[str, ...]) -> str:
        return "/".join(segments or ())

    # descendants in HR = walking downward in type hierarchy
    def _concrete_descendants(self, n: int) -> Set[int]:
        if n not in self.HR:
            return set()
        return {d for d in nx.descendants(self.HR, int(n)) if self._is_concrete(d)}

    def _nearest_concrete_descendants(self, n: int) -> Set[int]:
        """
        Among all concrete descendants of n, keep only those that do not have
        another concrete descendant *between* n and themselves (i.e., "closest concretes").
        """
        all_conc = self._concrete_descendants(n)
        if not all_conc:
            return set()
        # distance from n to each concrete (downward in HR)
        # BFS levels: nearest first
        nearest: Set[int] = set()
        from collections import deque
        q = deque([n])
        seen = {n}
        while q:
            cur = q.popleft()
            for child in self.HR.successors(cur):
                if child in seen:
                    continue
                seen.add(child)
                if self._is_concrete(child):
                    nearest.add(child)
                else:
                    q.append(child)
        return nearest
    
    def _find_node_by_name(self, name: str) -> Optional[int]:
        """Return the first node id whose Name == name (checks A first, then H)."""
        for G in (self.A, self.H):
            if not isinstance(G, nx.Graph):
                continue
            hits = [int(n) for n, d in G.nodes(data=True)
                    if (d.get("Name") or "").strip() == name]
            if hits:
                return hits[0]
        return None

    def _diagram_neighbors(self, node_id: int, diagram_name: str) -> list[int]:
        """Neighbors of node_id in A restricted to edges from a specific diagram."""
        if not isinstance(self.A, nx.MultiDiGraph) or node_id not in self.A:
            return []
        dn = (diagram_name or "").strip()

        nbrs: set[int] = set()
        # Successors where the edge's Diagram matches
        for _, v, d in self.A.out_edges(node_id, data=True):
            if (d.get("Diagram") or "").strip() == dn:
                nbrs.add(int(v))
        # Predecessors where the edge's Diagram matches
        for u, _, d in self.A.in_edges(node_id, data=True):
            if (d.get("Diagram") or "").strip() == dn:
                nbrs.add(int(u))

        nbrs.discard(int(node_id))
        def _nm(n: int) -> str:
            return (self.A.nodes[n].get("Name")
                    if n in self.A else self.H.nodes[n].get("Name")) or ""
        return sorted(nbrs, key=lambda n: _nm(n).casefold())


    # -------------------- anchor detection --------------------
    def _compute_anchors(self) -> Set[int]:
        """
        Anchor = any node having >= 2 concrete descendants.
        These will be emitted as top-level containers under Root.
        """
        anchors: Set[int] = set()
        for n in self.H.nodes():
            conc = self._concrete_descendants(n)
            if len(conc) >= 2:
                anchors.add(int(n))
        # Root is implicitly an anchor for anything unclaimed
        anchors.add(self.root_id)
        return anchors

    def _nearest_anchor_for_concrete(self, c: int, anchors: Set[int]) -> int:
        """
        Walk upward (H: child->parent) from concrete c to the nearest ancestor in 'anchors'.
        If none found (shouldn't happen since Root in anchors), return Root.
        """
        q = deque([(int(c), 0)])
        seen = {int(c)}
        best: Optional[Tuple[int, int]] = None  # (anchor, dist)
        while q:
            cur, d = q.popleft()
            for parent in self.H.successors(cur):
                if parent in seen:
                    continue
                seen.add(parent)
                if parent in anchors:
                    if best is None or d + 1 < best[1]:
                        best = (int(parent), d + 1)
                q.append((parent, d + 1))
        return best[0] if best else self.root_id
    
    def _nearest_owner_in_stack(self, n: int, stack_containers: set[int]) -> int:
        """
        Walk *up* H (child -> parent) to find the nearest ancestor that is in stack_containers.
        If none found, return self.root_id.
        """
        from collections import deque
        n = int(n)
        if not stack_containers:
            return self.root_id
        seen = {n}
        q = deque([n])
        while q:
            cur = q.popleft()
            for parent in self.H.successors(cur):  # child -> parent
                if parent in seen:
                    continue
                if parent in stack_containers:
                    return int(parent)  # nearest by BFS
                seen.add(parent)
                q.append(parent)
        return self.root_id

    # -------------------- JSON assembly helpers --------------------
    @staticmethod
    def _add_property(parent_obj: dict, key: str, prop: dict) -> str:
        """Insert prop under parent_obj['properties'] with collision-safe suffixing. Returns final key used."""
        props = parent_obj.setdefault("properties", {})
        k = key
        if k in props:
            i = 2
            while f"{key}_{i}" in props:
                i += 1
            k = f"{key}_{i}"
        props[k] = prop
        return k

    def _ensure_defined(self, node_id: int, owner_ptr: dict, owner_path: Tuple[str, ...]) -> None:
        """Define a node if not already defined under owner_ptr."""
        if node_id in self.def_ptr:
            return
        name = self._name(node_id)

        # Decide kind: anchors -> containers; concretes -> object; otherwise reference-only later
        # We only *define* anchors and concretes. Non-anchors/non-concretes are referenced when needed.
        is_anchor = getattr(self, "_anchor_set", set())
        is_anchor = node_id in is_anchor

        if is_anchor:
            obj = {"$objectType": "container", "type": "object", "properties": {}}
        elif self._is_concrete(node_id):
            obj = {"$objectType": "object", "type": "object", "$objectId": name, "properties": {}}
        else:
            # Not anchor, not concrete: do not define here; it will be referenced when needed.
            self.def_ptr[node_id] = None
            self.path_map[node_id] = owner_path + (name,)
            return

        self._add_property(owner_ptr, name, obj)
        self.def_ptr[node_id] = obj
        self.path_map[node_id] = owner_path + (name,)

    def _add_reference(self, at_owner_id: int, target_id: int) -> None:
        if not self.EMIT_CROSS_REFS:
            return
        at_ptr = self.def_ptr.get(at_owner_id)
        if not isinstance(at_ptr, dict):
            return
        if target_id not in self.path_map:
            return
        label = self._name(target_id)
        ref = {
            "$objectType": "reference",
            "type": "object",
            "$objectId": label,
            "$referencePath": self._path_str(self.path_map[target_id]),
            "properties": {},
        }
        self._add_property(at_ptr, label, ref)

    def _apply_hashes_if_rootclass(self, node_id: int, obj: dict) -> None:
        """
        If node_id is tagged rootClass, add the standard object hashes
        (mirrors hand template).
        """
        if self._role(int(node_id)) == "rootClass":
            obj["$primaryObjectHash"] = "IdentifiedObject.name"
            obj["$secondaryObjectHash"] = "IdentifiedObject.mRID"

    def _order_fields(self, kind: str, d: dict) -> dict:
        """
        Return a new dict whose keys follow the preferred order for `kind`,
        with any extra keys appended in their existing order.
        """
        if not isinstance(d, dict):
            return d
        order = self._FIELD_ORDER.get(kind, [])
        out = {}
        # 1) keys we know, in fixed order
        for k in order:
            if k in d:
                out[k] = d[k]
        # 2) any extras, in existing order
        for k in d:
            if k not in out:
                out[k] = d[k]
        return out

    def _apply_field_order_recursively(self, node: dict) -> dict:
        """
        Walk the entire JSON and reorder keys according to _FIELD_ORDER.
        """
        if not isinstance(node, dict):
            return node

        # Decide kind
        if "anyOf" in node and isinstance(node["anyOf"], list):
            # Recurse into anyOf entries (they are typically 'reference' objects)
            node["anyOf"] = [self._apply_field_order_recursively(v) for v in node["anyOf"]]
            # No special order for the wrapper; just return
            return node

        kind = None
        if node is getattr(self, "_root_schema_obj", None):
            kind = "schema"
        else:
            ot = node.get("$objectType")
            if ot == "object":
                kind = "object"
            elif ot == "container":
                kind = "container"
            elif ot == "reference":
                kind = "reference"

        # Recurse into children first
        props = node.get("properties")
        if isinstance(props, dict):
            node["properties"] = {
                k: self._apply_field_order_recursively(v)
                for k, v in props.items()
            }

        # Reorder this node’s keys if we know its kind
        return self._order_fields(kind, node) if kind else node

    # -------------------- build --------------------

    def build(self) -> dict:
        """
        Build auto_template:

        1) Top-level (Root/*) comes *only* from A: all nodes with a directed edge Root -> X.
        2) Everything else is filled using H traversal (down via HR), with owner selection
        based on the current branch's container stack (no new top-level unless A says so).
        3) Cross-references are emitted when an encountered node’s owner ≠ the current node.
        4) Top-level keys are ordered like the hand template (intersection first), then A–Z.
        """
        # ---------- setup ----------
        EMIT_XREFS = self.EMIT_CROSS_REFS
        root_title = (self.A.nodes[self.root_id].get("Name") if self.root_id in self.A
                    else self.H.nodes[self.root_id].get("Name")) or "Root"

        # caches
        self._owner_cache = {}
        self.def_ptr = {}
        self.path_map = {}
        role = lambda n: (self.A.nodes[n].get("ravensRole")
                        if n in self.A else self.H.nodes[n].get("ravensRole")) or ""
        name = lambda n: (self.A.nodes[n].get("Name")
                        if n in self.A else self.H.nodes[n].get("Name")) or ""

        schema = {
            "title": root_title,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://example.org/schema/{root_title}.json",
            "type": "object",
            "properties": {},
        }
        self._root_schema_obj = schema

        # register Root
        self.def_ptr[self.root_id] = schema
        self.path_map[self.root_id] = (root_title,)

        # ---------- 1) first-level from A (directed Root -> child) ----------
        if self.root_id in self.A:
            first_level_nodes = sorted(set(self.A.successors(self.root_id)),
                                    key=lambda n: name(n).casefold())
        else:
            first_level_nodes = []

        FIRST_LEVEL_SET = {int(n) for n in first_level_nodes}  # guard to prevent new Root/* later

        def ensure_defined(n: int, stack_containers: set[int], *, force_owner: Optional[int] = None, at_top_level: bool = False, force_kind: Optional[str] = None):
            """Define node n under an owner. If force_owner is provided, use that owner."""
            n = int(n)
            if n in self.def_ptr:
                return

            # owner selection
            if force_owner is not None:
                owner = int(force_owner)
            else:
                owner = self._nearest_owner_in_stack(n, stack_containers)
                # Prevent accidental new top-level entries: if owner resolves to Root
                # but n is not an A-derived first-level node, keep it off Root by
                # attaching to the nearest non-root container in the stack (or current anchor).
                if owner == self.root_id and n not in FIRST_LEVEL_SET:
                    # prefer the closest container in the stack (excluding root if possible)
                    non_root = [c for c in stack_containers if c != self.root_id]
                    owner = non_root[-1] if non_root else self.root_id

            owner_ptr = self.def_ptr.get(owner)
            owner_path = self.path_map.get(owner)
            if not isinstance(owner_ptr, dict) or not isinstance(owner_path, tuple):
                raise RuntimeError(f"Owner for node {n} is not defined.")

            nm = name(n)
            r  = role(n).strip()

            # emission rules
            if force_kind == "container":
                node_obj = {"$objectType": "container", "type": "object", "properties": {}}
            elif force_kind == "object":
                node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                self._apply_hashes_if_rootclass(n, node_obj)
            elif r == "substitutableClass":
                node_obj = {"anyOf": []}
            elif r == "containerClass":
                node_obj = {"$objectType": "container", "type": "object", "properties": {}}
            elif r == "inheritOnlyClass" and not at_top_level:
                # not emitted; record its canonical path for referencing
                self.path_map[n] = owner_path + (nm,)
                self.def_ptr[n] = None
                return
            else:
                # default object (also used for top-level inheritOnly)
                node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                self._apply_hashes_if_rootclass(n, node_obj)

            self._add_property(owner_ptr, nm, node_obj)
            self.path_map[n] = owner_path + (nm,)
            self.def_ptr[n] = node_obj

        def add_xref(at_node: int, target: int):
            """Add a reference to 'target' under 'at_node' (if enabled)."""
            if not self.EMIT_CROSS_REFS:
                return
            at_ptr = self.def_ptr.get(at_node)
            if not isinstance(at_ptr, dict):
                return
            tgt_path = self.path_map.get(target)
            if not tgt_path:
                return
            ref = {
                "$objectType": "reference",
                "type": "object",
                "$objectId": name(target),
                "$referencePath": "/".join(tgt_path),
                "properties": {}
            }
            self._add_property(at_ptr, name(target), ref)

        # Force-create top-level from A under Root (even if inheritOnly)
        for n in first_level_nodes:
            ensure_defined(n, stack_containers={self.root_id}, force_owner=self.root_id, at_top_level=True)

        # ---------- SPECIAL DIAGRAMS: treat "Versions" and "Group" like mini-Roots ----------
        special_diagrams = ("Versions", "Group")
        walk_anchors = list(first_level_nodes)  # start with A-derived top-level

        for label in special_diagrams:
            sid = self._find_node_by_name(label)
            if sid is None:
                continue

            # Ensure the special node sits under Root as a CONTAINER (override tag)
            ensure_defined(
                sid,
                stack_containers={self.root_id},
                force_owner=self.root_id,
                at_top_level=True,
                force_kind="container",
            )

            # Place every node connected to it *in its own diagram* directly under it
            for child in self._diagram_neighbors(sid, label):
                ensure_defined(child, stack_containers={self.root_id, sid}, force_owner=sid)

            # Make sure we descend H from this anchor too (even if it wasn't a Root->child in A)
            if sid not in walk_anchors:
                walk_anchors.append(sid)

        # ---------- 2) descend H below each top-level anchor ----------
        visited_down = set()

        for anchor in walk_anchors:
            # stack tracks container anchors along the branch (Root + this anchor to start)
            stack = [self.root_id, anchor] if role(anchor).strip() in ("containerClass", "rootClass", "inheritOnlyClass", "substitutableClass", "") else [self.root_id, anchor]

            q = deque([anchor])
            while q:
                cur = q.popleft()
                if cur in visited_down:
                    continue
                visited_down.add(cur)

                # walk downward in inheritance via HR (parent -> child)
                if cur not in self.HR:
                    continue
                children = sorted(self.HR.successors(cur), key=lambda n: name(n).casefold())
                for child in children:
                    # owner based on current container stack; never create new top-level unless in FIRST_LEVEL_SET
                    ensure_defined(child, stack_containers=set(stack))

                    # add cross-ref if the child wasn't defined under 'cur'
                    if self.EMIT_CROSS_REFS:
                        owner_here = self._nearest_owner_in_stack(child, set(stack))
                        if owner_here != cur and child in self.def_ptr and isinstance(self.def_ptr[child], dict):
                            add_xref(cur, child)

                    # extend stack if this child is a container
                    if role(child).strip() == "containerClass":
                        q.append(child)
                        # branch-local stack extension
                        stack = stack + [child]
                    else:
                        q.append(child)

        # ---------- 3) top-level ordering like hand ----------
        schema["properties"] = self._order_props_like_hand(schema.get("properties", {}))

        # Enforce field order ($hashes before properties, etc.)
        schema = self._apply_field_order_recursively(schema)
        self._last_auto = schema

        return schema

    def _sort_properties(
        self,
        node: dict,
        *,
        template: dict | None = None,
        mode: Literal["hand", "alpha", "none"] = "hand",
    ) -> dict:
        """
        Reorder every nested `properties` dict.

        mode="hand":  follow the hand template's property order; append extras A–Z
        mode="alpha": sort all properties A–Z (no template needed)
        mode="none":  leave insertion order as-is (no changes)

        Returns the *same* dict (mutates in place).
        """
        if not isinstance(node, dict) or mode == "none":
            return node

        def recur(src: dict, tmpl: dict | None) -> dict:
            if not isinstance(src, dict):
                return src

            # Recurse into children first so nested structures are sorted too
            props = src.get("properties")
            if isinstance(props, dict):
                if mode == "hand" and isinstance(tmpl, dict):
                    tmpl_props = tmpl.get("properties", {}) if isinstance(tmpl, dict) else {}
                    # 1) keys in hand order; 2) extras A–Z
                    ordered_keys = list(tmpl_props) + sorted(k for k in props if k not in tmpl_props)
                elif mode == "alpha":
                    ordered_keys = sorted(props)
                    tmpl_props = {}
                else:  # mode == "hand" but no template provided
                    ordered_keys = sorted(props)
                    tmpl_props = {}

                new_props = {}
                for k in ordered_keys:
                    if k not in props:
                        continue
                    child_tmpl = tmpl_props.get(k, {}) if isinstance(tmpl_props, dict) else {}
                    new_props[k] = recur(props[k], child_tmpl)
                src["properties"] = new_props

            # Keep anyOf stable (or sort by label if you prefer):
            if isinstance(src.get("anyOf"), list):
                # keep current order; if you want alpha, uncomment:
                # src["anyOf"] = sorted(src["anyOf"], key=lambda d: (d.get("$objectId") or "").casefold())
                pass

            # Recurse into any other dict fields
            for k, v in list(src.items()):
                if k == "properties":
                    continue
                if isinstance(v, dict):
                    tmpl_child = template.get(k, {}) if (mode == "hand" and isinstance(template, dict)) else None
                    src[k] = recur(v, tmpl_child)

            return src

        return recur(node, template)
    
    def _order_props_like_hand(self, props: dict) -> dict:
        if not isinstance(props, dict):
            return props
        try:
            import json
            from ravens.data import _TEMPLATE_JSON_PATH
            hand = json.loads(_TEMPLATE_JSON_PATH.read_text(encoding="utf-8"))
            hand_props = hand.get("properties", {}) if isinstance(hand, dict) else {}
        except Exception:
            hand_props = {}

        in_both = [k for k in hand_props.keys() if k in props]
        extras = sorted([k for k in props.keys() if k not in hand_props], key=str.casefold)
        ordered_keys = in_both + extras
        return {k: props[k] for k in ordered_keys}


    # -------------------- save helpers --------------------
    def save_auto_template(self, auto_template: Optional[dict] = None) -> None:
        """
        Write the auto template JSON. If `auto_template` is not provided, use the
        most recent `build()` result cached on this instance.
        """
        data = auto_template or getattr(self, "_last_auto", None)
        if not isinstance(data, dict):
            raise ValueError("No auto template provided and nothing cached from build().")
        _TEMPLATE_AUTOJSON_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")