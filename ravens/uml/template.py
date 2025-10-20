# template.py
from __future__ import annotations

import json
from typing import Dict, Tuple, Optional, List, Set
import networkx as nx

from ravens.data import _TEMPLATE_JSON_PATH, _TEMPLATE_AUTOJSON_PATH


class TemplateGenerator:
    """
    Root-down, node-driven template generator.

    Key rules
    ---------
    • Walk downward from Root along associations/aggregations ONLY (no Generalization).
    • For each reached class X, walk UP inheritance (Generalization) to find the nearest
      container/root; that ancestor is X's canonical owner in the template.
    • Define each class ONCE at its canonical owner (container/object/substitutable/skip inheritOnly).
    • If X is encountered elsewhere during traversal, add a REFERENCE at that location
      pointing to X's canonical path.
    • Build anyOf for substitutableClass using CONCRETE descendants via inheritance,
      but only include variants that were actually encountered (so they have definitions).
    • No connector tags or multiplicity are used in this pass.
    """

    # ------------------------ init & graphs ------------------------

    def __init__(self, G: nx.MultiDiGraph, uml_data=None, *, root_name: str = "Root"):
        self.G = G
        self.uml_data = uml_data
        self.root_name = root_name

        # Resolve Root node id
        hits = [int(n) for n, d in self.G.nodes(data=True) if d.get("Name") == self.root_name]
        if not hits:
            raise ValueError(f"No node named '{self.root_name}' in G.")
        if len(hits) > 1:
            raise ValueError(f"Multiple nodes named '{self.root_name}' in G.")
        self.root_id = hits[0]

        # Roles (from element tags)
        self.role_map: Dict[int, str] = {
            int(n): (d.get("ravensRole") or "").strip()
            for n, d in self.G.nodes(data=True)
        }

        # Association/Aggregation graph (GA): child -> parent, excluding Generalization
        self.GA = self._build_association_graph()
        self.GR = self.GA  # traverse Root -> neighbors using the undirected view
        self.GH = self._build_inheritance_graph()
        self.HR = self.GH.reverse(copy=False)

        # Caches for canonical placement & JSON assembly
        self._owner_cache: Dict[int, int] = {}             # node -> canonical owner id
        self.def_ptr: Dict[int, Optional[dict]] = {}       # node -> dict of its definition (or placeholder) if emitted
        self.path_map: Dict[int, Tuple[str, ...]] = {}     # node -> tuple of property path segments where it is defined

    def _build_association_graph(self) -> nx.DiGraph:
        """
        Association/Aggregation edges treated as undirected for traversal:
        we add both (u->v) and (v->u). Generalization is excluded here.
        """
        GA = nx.DiGraph()
        GA.add_nodes_from(self.G.nodes(data=True))
        for u, v, d in self.G.edges(data=True):
            if d.get("Connector_Type") == "Generalization":
                continue
            u = int(u); v = int(v)
            GA.add_edge(u, v)
            GA.add_edge(v, u)  # make traversal effectively undirected
        return GA

    def _build_inheritance_graph(self) -> nx.DiGraph:
        """Inheritance connectors only (Generalization). Orientation: child -> parent type."""
        GH = nx.DiGraph()
        GH.add_nodes_from(self.G.nodes())
        for u, v, d in self.G.edges(data=True):
            if d.get("Connector_Type") == "Generalization" and u != v:
                GH.add_edge(int(u), int(v))
        return GH

    # ------------------------ roles & helpers ------------------------

    def _role(self, n: int) -> str:
        return (self.role_map.get(int(n)) or "").strip()

    def _is_container_node(self, n: int) -> bool:
        """
        A node is a container anchor iff it is the actual Root node or tagged containerClass.
        (rootClass is NOT a container anchor.)
        """
        return int(n) == int(self.root_id) or self._role(n) == "containerClass"

    def _is_concrete_node(self, n: int) -> bool:
        """Concrete = emits an object/container (i.e., not inheritOnly or substitutable placeholder)."""
        r = self._role(n)
        return r not in ("inheritOnlyClass", "substitutableClass")

    def _name(self, obj_id: int) -> str:
        return (self.G.nodes[obj_id].get("Name") or "").split(" (")[0]

    @staticmethod
    def _path_str(segments: Tuple[str, ...]) -> str:
        return "/".join(segments or ())

    # ------------------------ canonical owner via GH ------------------------

    def _canonical_owner(self, n: int) -> int:
        """
        Walk UP GH (child -> parent type) to find nearest ancestor that is container/root.
        If none found, fall back to Root.
        """
        n = int(n)
        if n in self._owner_cache:
            return self._owner_cache[n]

        if n == self.root_id:
            self._owner_cache[n] = n
            return n

        # BFS up GH
        from collections import deque

        seen = {n}
        q = deque([(n, 0)])
        candidates: List[Tuple[int, int]] = []  # (ancestor, dist)

        while q:
            cur, dist = q.popleft()
            for parent in self.GH.successors(cur):  # child -> parent type
                if parent in seen:
                    continue
                seen.add(parent)
                if self._is_container_node(parent):
                    candidates.append((int(parent), dist + 1))
                q.append((parent, dist + 1))

        if not candidates:
            owner = self.root_id
        else:
            best_dist = min(d for _, d in candidates)
            best = [a for (a, d) in candidates if d == best_dist]
            best.sort(key=lambda a: (self._name(a) or "").casefold())
            owner = best[0]

        self._owner_cache[n] = owner
        return owner

    # ------------------------ build (Root-down traversal) ------------------------

    def build(self) -> dict:
        """Construct the auto template as a dict."""
        root_title = self._name(self.root_id)
        schema = {
            "title": root_title,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://raw.githubusercontent.com/lanl-ansi/MG-RAVENS/refs/heads/schema/{root_title}.json",
            "type": "object",
            "$primaryObjectHash": "IdentifiedObject.name",
            "$secondaryObjectHash": "IdentifiedObject.mRID",
            "properties": {},
        }

        # Register Root definition & path
        self.def_ptr[self.root_id] = schema
        self.path_map[self.root_id] = (root_title,)

        visited_descend: set[int] = set()
        seen_assoc_pair: set[tuple[int, int]] = set()
        EMIT_CROSS_REFERENCES = False  # turn off for now

        def ensure_defined(n: int, stack_containers: set[int]) -> None:
            """
            Define node n under its owner:
            • Prefer branch-local owner (nearest container on current stack).
            • If none found, fall back to global canonical container ancestor (via GH).
            • If still none, owner = Root.
            Ensures the chosen owner is defined first.

            Top-level rule: if n is a direct child of Root (stack == {Root}) and role is
            inheritOnlyClass, still emit a concrete object at the top level.
            """
            n = int(n)
            if n in self.def_ptr:
                return

            role = self._role(n)

            # --- choose owner ---
            # 1) branch-local
            owner = self._nearest_stack_container_owner(n, stack_containers)

            # 2) global canonical (if branch-local gave Root because nothing matched)
            if owner == self.root_id:
                glob = self._canonical_owner(n)
                if glob != self.root_id:
                    owner = glob

            # safety: avoid self-ownership
            if owner == n:
                owner = self.root_id

            # --- ensure owner is defined first ---
            if owner not in self.def_ptr:
                # Recurse to define the owner (its owner will be resolved similarly)
                # Use the same stack; Root will already be defined.
                ensure_defined(owner, stack_containers)

            owner_ptr = self.def_ptr.get(owner)
            owner_path = self.path_map.get(owner)
            if not isinstance(owner_ptr, dict) or not isinstance(owner_path, tuple):
                raise RuntimeError(f"Owner for node {n} is not defined.")

            name = self._name(n)
            at_top_level = (stack_containers == {self.root_id})

            # --- emission rules ---
            if role == "inheritOnlyClass" and not at_top_level:
                # Not emitted, but record its canonical path for references/anyOf bookkeeping.
                self.path_map[n] = owner_path + (name,)
                self.def_ptr[n] = None
                return

            if role == "substitutableClass":
                placeholder = {"anyOf": []}
                self._add_property(owner_ptr, name, placeholder)
                self.path_map[n] = owner_path + (name,)
                self.def_ptr[n] = placeholder
                return

            if role == "containerClass":
                obj = {"$objectType": "container", "type": "object", "properties": {}}
                self._add_property(owner_ptr, name, obj)
                self.path_map[n] = owner_path + (name,)
                self.def_ptr[n] = obj
                return

            # Default: emit a concrete object (also used for top-level inheritOnlyClass)
            obj = {"$objectType": "object", "type": "object", "$objectId": name, "properties": {}}
            self._add_property(owner_ptr, name, obj)
            self.path_map[n] = owner_path + (name,)
            self.def_ptr[n] = obj

        def add_reference(at_node: int, target: int) -> None:
            """(Disabled by default) Add a reference to target under at_node."""
            if not EMIT_CROSS_REFERENCES:
                return
            at_ptr = self.def_ptr.get(at_node)
            if not isinstance(at_ptr, dict):
                return
            if target not in self.path_map:
                return
            ref = {
                "$objectType": "reference",
                "type": "object",
                "$objectId": self._name(target),
                "$referencePath": self._path_str(self.path_map[target]),
                "properties": {},
            }
            self._add_property(at_ptr, self._name(target), ref)


        def dfs_descend(cur: int, stack_containers: list[int]) -> None:
            """Root-down traversal over undirected associations (GR) with a branch-local container stack."""
            # Ensure current node is defined (especially if it's a container anchoring this branch)
            if cur not in self.def_ptr:
                ensure_defined(cur, set(stack_containers))

            if cur in visited_descend:
                return
            visited_descend.add(cur)

            # Extend the stack with cur if it's a container/root
            next_stack = list(stack_containers)
            if self._role(cur) in ("containerClass", "rootClass"):
                if cur not in next_stack:
                    next_stack.append(cur)

            # Explore association neighbors (undirected), deterministic by name
            for child in sorted(self.GR.successors(cur), key=lambda x: (self._name(x) or "").casefold()):
                pair = (cur, child)
                if pair in seen_assoc_pair:
                    continue
                seen_assoc_pair.add(pair)

                # Define child using branch-local owner
                ensure_defined(child, set(next_stack))

                # Optionally (currently off): add a reference when owner != cur
                owner = self._nearest_stack_container_owner(child, set(next_stack))
                if owner != cur:
                    add_reference(cur, child)

                dfs_descend(child, next_stack)

        # Register Root
        self.def_ptr[self.root_id] = schema
        self.path_map[self.root_id] = (root_title,)

        # Start traversal
        dfs_descend(self.root_id, [self.root_id])

        # anyOf + sort stay the same
        self._emit_substitutable_anyofs()
        self._sort_properties_recursive(schema)
        return schema

    # ------------------------ anyOf emission ------------------------

    def _emit_substitutable_anyofs(self) -> None:
        """
        For each substitutableClass node S that has a placeholder definition,
        collect CONCRETE descendants via inheritance (HR), but only include
        those that were actually defined (so they have $referencePath).
        """
        subs = [n for n in self.G.nodes() if self._role(n) == "substitutableClass"]

        for s in subs:
            placeholder = self.def_ptr.get(s)
            if not (isinstance(placeholder, dict) and "anyOf" in placeholder):
                continue

            # Gather concrete descendants in GH (downward via HR)
            concrete_desc: List[int] = []
            if self.HR.has_node(s):
                for d in nx.descendants(self.HR, s):
                    if self._is_concrete_node(d) and d in self.def_ptr and isinstance(self.def_ptr[d], dict):
                        concrete_desc.append(int(d))

            # Deduplicate by label, stable order
            seen: Set[str] = set()
            opts: List[dict] = []
            for d in sorted(concrete_desc, key=lambda x: (self._name(x) or "").casefold()):
                label = self._name(d)
                if label in seen:
                    continue
                seen.add(label)
                opts.append({
                    "$objectType": "reference",
                    "type": "object",
                    "$objectId": label,
                    "$referencePath": self._path_str(self.path_map.get(d, ())),
                    "properties": {},
                })

            placeholder["anyOf"] = opts

    # ------------------------ JSON utils ------------------------

    @staticmethod
    def _add_property(parent_obj: dict, key: str, prop: dict) -> None:
        """Insert prop under parent_obj['properties'] with collision-safe suffixing."""
        props = parent_obj.setdefault("properties", {})
        k = key
        if k in props:
            i = 2
            while f"{key}_{i}" in props:
                i += 1
            k = f"{key}_{i}"
        props[k] = prop

    def _sort_properties_recursive(self, node: dict) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            ordered = dict(sorted(props.items(), key=lambda kv: kv[0].casefold()))
            node["properties"] = ordered
            for child in ordered.values():
                self._sort_properties_recursive(child)
        if isinstance(node.get("anyOf"), list):
            node["anyOf"] = sorted(node["anyOf"], key=lambda d: (d.get("$objectId") or "").casefold())

    # ------------------------ save & compare helpers ------------------------
    def _nearest_stack_container_owner(self, n: int, stack_containers: set[int]) -> int:
        """
        Choose owner for node n as the nearest CONTAINER ancestor in GH
        that is present in the CURRENT traversal stack. If none, owner = Root.
        """
        from collections import deque

        n = int(n)
        seen = {n}
        q = deque([(n, 0)])
        candidates = []  # (ancestor, dist)

        while q:
            cur, dist = q.popleft()
            for parent in self.GH.successors(cur):  # child -> parent type
                if parent in seen:
                    continue
                seen.add(parent)
                if parent in stack_containers:
                    candidates.append((int(parent), dist + 1))
                q.append((parent, dist + 1))

        if not candidates:
            return self.root_id
        best_dist = min(d for _, d in candidates)
        best = [a for (a, d) in candidates if d == best_dist]
        best.sort(key=lambda a: (self._name(a) or "").casefold())
        return best[0]


    @staticmethod
    def save_auto_template(auto_template: dict) -> None:
        """
        Save auto template aligned to hand template's key order where possible.
        """
        template_hand = json.loads(_TEMPLATE_JSON_PATH.read_text(encoding="utf-8"))
        auto_ordered = TemplateGenerator._reorder_like_template(auto_template, template_hand)
        _TEMPLATE_AUTOJSON_PATH.write_text(json.dumps(auto_ordered, indent=2), encoding="utf-8")

    @staticmethod
    def _reorder_like_template(source: dict, template: dict) -> dict:
        """
        Return a *new* dict where every nested `properties` object is reordered
        to match the template's key order. Extras appended A–Z.
        """
        if not isinstance(source, dict):
            return source
        out = dict(source)
        if "properties" in out and isinstance(out["properties"], dict):
            src_props = out["properties"]
            tmpl_props = template.get("properties", {}) if isinstance(template, dict) else {}
            ordered_keys = list(tmpl_props) + sorted(k for k in src_props if k not in tmpl_props)
            out["properties"] = {
                k: TemplateGenerator._reorder_like_template(src_props[k], tmpl_props.get(k, {}))
                for k in ordered_keys if k in src_props
            }
        for k, v in list(out.items()):
            if isinstance(v, dict) and k != "properties":
                out[k] = TemplateGenerator._reorder_like_template(v, template.get(k, {}) if isinstance(template, dict) else {})
        return out

    @staticmethod
    def compare_templates_relaxed(
        *,
        arrays_compatible: bool = False,
        reference_path_strict: bool = False,
        variant_overlap_threshold: float = 0.5,
        depth: int = 3,
        sample_n: int = 10,
    ) -> dict:
        """
        Relaxed comparator (path/label/anyOf-aware).
        """
        def last_segment(p: str) -> str:
            if not isinstance(p, str) or not p:
                return ""
            return p.strip("/").split("/")[-1]

        def is_array(node: dict) -> bool:
            return isinstance(node, dict) and node.get("type") == "array"

        def unwrap_array(node: dict) -> dict:
            if is_array(node):
                return node.get("items") or {}
            return node

        def node_kind(node: dict) -> str:
            if isinstance(node, dict) and "anyOf" in node and isinstance(node["anyOf"], list):
                return "anyOf"
            if isinstance(node, dict):
                return str(node.get("$objectType") or "object")
            return "object"

        def label_for_node(node: dict, prop_name: str) -> str:
            if not isinstance(node, dict):
                return prop_name
            if node.get("$objectType") == "reference":
                if not reference_path_strict:
                    return last_segment(node.get("$referencePath", "")) or node.get("$objectId") or prop_name
                return node.get("$referencePath") or node.get("$objectId") or prop_name
            return node.get("$objectId") or prop_name

        def variant_labels(node: dict) -> set:
            labels = set()
            if not (isinstance(node, dict) and isinstance(node.get("anyOf"), list)):
                return labels
            for v in node["anyOf"]:
                if not isinstance(v, dict):
                    continue
                if v.get("$objectType") == "reference":
                    lbl = last_segment(v.get("$referencePath", "")) or v.get("$objectId") or v.get("$objectType") or "?"
                else:
                    lbl = v.get("$objectId") or v.get("$objectType") or "?"
                labels.add(str(lbl))
            return labels

        def walk(tpl: dict, *, max_depth: int):
            def _walk(node: dict, prefix: tuple):
                if len(prefix) >= max_depth:
                    return
                if not isinstance(node, dict):
                    return
                arr = is_array(node)
                core = unwrap_array(node)
                if "anyOf" in core and isinstance(core["anyOf"], list):
                    yield prefix, {"type": "array" if arr else core.get("type"), **core}, arr
                    return
                if "$objectType" in core:
                    yield prefix, {"type": "array" if arr else core.get("type"), **core}, arr
                props = core.get("properties")
                if isinstance(props, dict):
                    for k, v in props.items():
                        yield from _walk(v, prefix + (str(k),))
            yield from _walk(tpl, ())

        def flatten_strict(tpl: dict) -> dict:
            out = {}
            for p, node, arr in walk(tpl, max_depth=depth):
                core = unwrap_array(node)
                sig = {
                    "kind": core.get("$objectType"),
                    "objectId": core.get("$objectId"),
                    "primary": core.get("$primaryObjectHash"),
                    "secondary": core.get("$secondaryObjectHash"),
                    "refPath": core.get("$referencePath"),
                    "is_array": bool(arr),
                    "is_anyof": isinstance(core.get("anyOf"), list),
                }
                out["/".join(p)] = sig
            return out

        def flatten_relaxed(tpl: dict) -> dict:
            out = {}
            for p, node, arr in walk(tpl, max_depth=depth):
                core = unwrap_array(node)
                path = "/".join(p)
                prop_name = p[-1] if p else ""
                k = node_kind(core)
                if k == "anyOf":
                    out[path] = {"is_array": bool(arr), "kind": "anyOf", "variants": variant_labels(core)}
                else:
                    out[path] = {"is_array": bool(arr), "kind": k, "label": label_for_node(core, prop_name)}
            return out

        hand = json.loads(_TEMPLATE_JSON_PATH.read_text(encoding="utf-8"))
        auto = json.loads(_TEMPLATE_AUTOJSON_PATH.read_text(encoding="utf-8"))

        strict_hand = flatten_strict(hand)
        strict_auto = flatten_strict(auto)
        relaxed_hand = flatten_relaxed(hand)
        relaxed_auto = flatten_relaxed(auto)

        paths_hand = set(strict_hand.keys())
        paths_auto = set(strict_auto.keys())
        in_both = paths_hand & paths_auto
        changed_strict = {p for p in in_both if strict_hand[p] != strict_auto[p]}
        exact_matches = in_both - changed_strict

        def relaxed_equal(a: dict, b: dict) -> bool:
            if not arrays_compatible and bool(a.get("is_array")) != bool(b.get("is_array")):
                return False
            if a.get("kind") == "anyOf" and b.get("kind") == "anyOf":
                A, B = set(a.get("variants") or ()), set(b.get("variants") or ())
                if not A and not B:
                    return True
                inter = len(A & B)
                uni = len(A | B) or 1
                return (inter / uni) >= variant_overlap_threshold
            if a.get("kind") == "anyOf":
                return (b.get("label", "") in (a.get("variants") or set()))
            if b.get("kind") == "anyOf":
                return (a.get("label", "") in (b.get("variants") or set()))
            return str(a.get("label", "")).strip() == str(b.get("label", "")).strip()

        paths_hand_rel = set(relaxed_hand.keys())
        paths_auto_rel = set(relaxed_auto.keys())
        in_both_rel = paths_hand_rel & paths_auto_rel

        relaxed_matches = set()
        for p in in_both_rel:
            if p in exact_matches:
                continue
            if relaxed_equal(relaxed_hand[p], relaxed_auto[p]):
                relaxed_matches.add(p)

        presence_only = in_both_rel - exact_matches - relaxed_matches
        only_in_hand = sorted(paths_hand_rel - paths_auto_rel)
        only_in_auto = sorted(paths_auto_rel - paths_hand_rel)

        print("=" * 60)
        print(f"🟢  EXACT MATCH: {len(exact_matches)}")
        print(f"🟡  RELAXED MATCH: {len(relaxed_matches)}")
        print(f"⚪  PATH MATCH (presence-only): {len(presence_only)}")
        print(f"➖  Missing in auto : {len(only_in_hand)}")
        print(f"➕  New in auto     : {len(only_in_auto)}")
        print(f"✏️  Changed (strict): {len(changed_strict)}")
        print("=" * 60)

        def sample(paths, label):
            if not paths:
                return
            print(f"\n{label}  ({len(paths)}):")
            for p in list(sorted(paths))[:sample_n]:
                print("   ", p)

        sample(only_in_hand, "➖  only in hand-crafted")
        sample(only_in_auto, "➕  only in auto")
        sample(relaxed_matches, "🟡  relaxed matches (not exact)")
        sample(presence_only, "⚪  path matches (presence-only)")
        sample(changed_strict, "✏️  changed (strict)")

        return {
            "counts": {
                "exact": len(exact_matches),
                "relaxed": len(relaxed_matches),
                "presence_only": len(presence_only),
                "only_in_hand": len(only_in_hand),
                "only_in_auto": len(only_in_auto),
                "changed_strict": len(changed_strict),
                "common_paths": len(in_both_rel),
            },
            "sets": {
                "exact": sorted(exact_matches),
                "relaxed": sorted(relaxed_matches),
                "presence_only": sorted(presence_only),
                "only_in_hand": only_in_hand,
                "only_in_auto": only_in_auto,
                "changed_strict": sorted(changed_strict),
            },
            "strict_signatures": {"hand": strict_hand, "auto": strict_auto},
            "relaxed_signatures": {"hand": relaxed_hand, "auto": relaxed_auto},
        }
