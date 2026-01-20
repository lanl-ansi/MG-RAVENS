from __future__ import annotations

import json
import copy
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional, Literal
import networkx as nx

from ravens.data import _TEMPLATE_JSON_PATH, _TEMPLATE_AUTOJSON_PATH

STRUCTURAL_CONTAINERS = {"Root", "Group", "Groups", "Version", "Versions"}

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
                    "description",
                    "anyOf", "properties",
                ],
                "object": [
                    "$objectType", "type", "$objectId", "$arrayPosition",
                    "$primaryObjectHash", "$secondaryObjectHash",
                    "description",
                    "anyOf", "properties",
                ],
                "container": [
                    "$objectType", "type", "description",
                    "anyOf", "properties",
                ],
                "reference": [
                    "$objectType", "type", "$objectId", "$referencePath",
                    "description",
                    "anyOf", "properties",
                ],
            }



    # -------------------- basic helpers --------------------

    def _role(self, n: int) -> str:
        return (self.role_map.get(int(n)) or "").strip()

    def _is_concrete(self, n: int) -> bool:
        r = self._role(n)
        return r in ("rootClass", "embeddedClass")

    def _name(self, n: int) -> str:
        n = int(n)
        nm = ""
        if isinstance(self.A, nx.Graph) and n in self.A:
            nm = (self.A.nodes[n].get("Name") or "").strip()
        if not nm and n in self.H:
            nm = (self.H.nodes[n].get("Name") or "").strip()
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

    def _collect_polymorphic_variants(self, base_id: int) -> list[int]:
        """
        Return [base_id] + all descendants in the generalization graph (HR),
        regardless of role. Role-based filtering happens at the call sites.
        """
        base_id = int(base_id)
        out: list[int] = [base_id]
        if not hasattr(self, "HR") or self.HR is None:
            return out

        seen = {base_id}
        q = deque([base_id])

        while q:
            cur = q.popleft()
            # HR edges: parent -> child (descendants)
            for child in self.HR.successors(cur):
                try:
                    cid = int(child)
                except Exception:
                    continue
                if cid in seen:
                    continue
                seen.add(cid)
                out.append(cid)
                q.append(cid)

        return out

    def _make_ref(self, target: int) -> dict | None:
        """Make a hand-style reference object to an already-defined target."""
        tgt_path = self.path_map.get(target)
        if not tgt_path:
            return None
        root_title = self._root_schema_obj.get("title", "Root")
        ref_path = "/".join(tgt_path[1:]) if (len(tgt_path) >= 1 and tgt_path[0] == root_title) else "/".join(tgt_path)
        return {
            "$objectType": "reference",
            "$objectId": self._name(target),
            "type": "string",
            "$referencePath": ref_path,
        }

    def _merge_schema(self, existing: dict | None, incoming: dict | None) -> dict | None:
        """
        Merge two schema fragments conservatively:
          - Preserve anyOf wrappers (never allow them to be downgraded to non-anyOf).
          - Merge object 'properties' recursively.
          - Merge array 'items' recursively.
          - When unsure, keep the existing schema.
        """
        if existing is None:
            return incoming
        if incoming is None:
            return existing

        if not isinstance(existing, dict) or not isinstance(incoming, dict):
            return existing

        # anyOf handling: do not downgrade
        ex_any = "anyOf" in existing
        in_any = "anyOf" in incoming

        if ex_any and not in_any:
            return existing
        if in_any and not ex_any:
            return incoming

        if ex_any and in_any:
            out = dict(existing)
            # wrapper invariants (we enforce these globally too, but keep it safe here)
            out.pop("type", None)
            out.pop("properties", None)

            ex_list = out.get("anyOf", [])
            in_list = incoming.get("anyOf", [])
            if not isinstance(ex_list, list) or not isinstance(in_list, list):
                return out

            def _k(x: dict) -> tuple:
                if not isinstance(x, dict):
                    return ("<non-dict>", str(x))
                return (
                    x.get("$objectType"),
                    x.get("$objectId"),
                    x.get("$referencePath"),
                    x.get("$arrayPosition"),
                    x.get("type"),
                )

            seen = { _k(x): x for x in ex_list if isinstance(x, dict) }
            merged_list: list = list(ex_list)

            for x in in_list:
                if not isinstance(x, dict):
                    # keep weird entries stable
                    if x not in merged_list:
                        merged_list.append(x)
                    continue

                k = _k(x)
                if k in seen and isinstance(seen[k], dict):
                    # merge member schemas (e.g., member.properties)
                    seen[k] = self._merge_schema(seen[k], x) or seen[k]
                    # update the actual list element reference
                    for i, y in enumerate(merged_list):
                        if isinstance(y, dict) and _k(y) == k:
                            merged_list[i] = seen[k]
                            break
                else:
                    merged_list.append(x)
                    seen[k] = x

            out["anyOf"] = merged_list
            return out

        # array merge
        if existing.get("type") == "array" and incoming.get("type") == "array":
            out = dict(existing)
            if "items" in existing and "items" in incoming:
                out["items"] = self._merge_schema(existing.get("items"), incoming.get("items"))
            # preserve any metadata we might be missing
            for meta in ("$arrayPosition", "$objectType", "$objectId"):
                if meta in incoming and meta not in out:
                    out[meta] = incoming[meta]
            return out

        # object merge (properties)
        if existing.get("type") == "object" and incoming.get("type") == "object":
            out = dict(existing)

            ex_props = existing.get("properties") if isinstance(existing.get("properties"), dict) else {}
            in_props = incoming.get("properties") if isinstance(incoming.get("properties"), dict) else {}

            if ex_props or in_props:
                out_props = dict(ex_props)
                for k, v in in_props.items():
                    out_props[k] = self._merge_schema(out_props.get(k), v)
                out["properties"] = out_props

            # preserve metadata
            for meta in (
                "$objectType",
                "$objectId",
                "$primaryObjectHash",
                "$secondaryObjectHash",
                "$referencePath",
                "$arrayPosition",
            ):
                if meta in incoming and meta not in out:
                    out[meta] = incoming[meta]

            return out

        # default: keep existing
        return existing

    def _add_or_merge_property(self, obj_ptr: dict, prop_key: str, prop_schema: dict) -> None:
        """
        Add a property to obj_ptr['properties'] using merge semantics.
        IMPORTANT: if obj_ptr is an anyOf wrapper, do NOT put properties on the wrapper.
                  Instead, merge the property into each anyOf member (object members only).
        """
        if not isinstance(obj_ptr, dict):
            return

        if "anyOf" in obj_ptr and isinstance(obj_ptr.get("anyOf"), list):
            # wrapper must not have properties; push into members
            for member in obj_ptr["anyOf"]:
                if not isinstance(member, dict):
                    continue
                # Only object members should receive properties
                if member.get("$objectType") != "object":
                    continue
                mprops = member.setdefault("properties", {})
                if not isinstance(mprops, dict):
                    member["properties"] = {}
                    mprops = member["properties"]
                mprops[prop_key] = self._merge_schema(mprops.get(prop_key), prop_schema)
            return

        props = obj_ptr.setdefault("properties", {})
        if not isinstance(props, dict):
            obj_ptr["properties"] = {}
            props = obj_ptr["properties"]

        if prop_key in props:
            props[prop_key] = self._merge_schema(props.get(prop_key), prop_schema)
        else:
            props[prop_key] = prop_schema

    def _emit_association_entries(self) -> None:
        """
        Emit dotted association-backed properties ONLY when there is a visible label
        captured on the A edge (edge_data['label'] is a non-empty string).

        NO fallback to target name. This prevents bogus properties like:
            Versions.IEC61970CIMVersion
        for unlabeled aggregations/compositions.
        """
        A = self.A
        if A is None or not isinstance(A, nx.MultiDiGraph):
            return

        # Name -> node id (robust lookup)
        name_to_id: dict[str, int] = {}
        for G in (A, self.H):
            if not isinstance(G, nx.Graph):
                continue
            for nid, data in G.nodes(data=True):
                nm = (data.get("Name") or "").strip()
                if not nm:
                    continue
                try:
                    nid_i = int(nid)
                except Exception:
                    continue
                name_to_id.setdefault(nm, nid_i)

        ASSOC_LIKE = {"Association", "Aggregation", "Composition"}

        # Never generate dotted properties for these structural wiring nodes.
        # (They are handled elsewhere: Root first-level placement, and your special-diagram logic.)
        STRUCTURAL_CONTAINERS = {"Root", "Group", "Groups", "Version", "Versions"}

        # Deduplicate by (ConnectorID, OwnerName, Label) so multiple diagram instances
        # don’t generate identical properties. If you want *every* diagram-instance emitted,
        # include InstanceID in the signature instead.
        seen_props: set[tuple[int, str, str]] = set()
        def make_polymorphic_ref_schema(target_id: int) -> dict | None:
            """
            Build schema for an association target.

            Preferred form (when targets are defined somewhere in the template):
              - If target has >=2 variants (base+descendants), emit outer reference wrapper
                {$objectType:"reference",$objectId:<base>, anyOf:[refs...]}.
              - Else emit a single ref.

            Fallback (critical for embedded-inherit-only bases like OperationalLimit):
              - If we cannot build refs AND the *base* target is an inherit-only role,
                emit an inline object wrapper with anyOf of substitutable variants.
              - Inject base-owned *association-backed* dotted properties into each variant
                (base-only), e.g. OperationalLimit.OperationalLimitType.
            """
            target_id = int(target_id)

            # ---------- helper: reference or minimal fallback ----------
            def _ref_or_minimal(tid: int) -> dict | None:
                tid = int(tid)
                ref = self._make_ref(tid)
                if isinstance(ref, dict):
                    ref.pop("$primaryObjectHash", None)
                    ref.pop("$secondaryObjectHash", None)
                    return ref
                # Minimal fallback: still point somewhere stable by name
                tname = self._name(tid)
                if not tname:
                    return None
                return {"$objectType": "reference", "$referencePath": tname}

            # ---------- collect polymorphic variants ----------
            try:
                variants = self._collect_polymorphic_variants(target_id)
            except Exception:
                variants = [target_id]
            variants = [int(v) for v in variants if v is not None]

            # ---------- preferred: build refs ----------


            if len(variants) >= 2:


                items: list[dict] = []


                for v in variants:


                    ref = self._make_ref(int(v))


                    if isinstance(ref, dict):


                        # association references never carry hashes


                        ref.pop("$primaryObjectHash", None)


                        ref.pop("$secondaryObjectHash", None)


                        items.append(ref)



                # Only return ref-wrapper if we actually have at least one usable ref


                if items:


                    base_name = self._name(target_id)


                    out = {"$objectType": "reference", "$objectId": base_name, "anyOf": items}


                    out.pop("$primaryObjectHash", None)


                    out.pop("$secondaryObjectHash", None)


                    return out

            # Single target (or polymorphic but no refs found)
            if len(variants) == 1:
                tid = int(variants[0])

                # Preferred: real ref to an already-defined target
                ref = self._make_ref(tid)
                if isinstance(ref, dict):
                    ref.pop("$primaryObjectHash", None)
                    ref.pop("$secondaryObjectHash", None)
                    return ref

                # If the target is an embeddedClass, emit an *inline object* stub
                # (HAND pattern for e.g. Location.PositionPoints -> PositionPoint),
                # rather than silently dropping the property.
                t_role = (self._role(tid) or "").strip()
                if t_role == "embeddedClass":
                    tname = self._name(tid)
                    if not tname:
                        return None

                    obj = {"$objectType": "object", "$objectId": tname, "type": "object", "properties": {}}

                    # Optional array-position hints for embedded array members
                    # (keep this tiny + explicit; add entries as we encounter them).
                    EMBEDDED_ARRAY_POSITION = {
                        "PositionPoint": "PositionPoint.sequenceNumber",
                    }
                    if tname in EMBEDDED_ARRAY_POSITION:
                        obj["$arrayPosition"] = EMBEDDED_ARRAY_POSITION[tname]

                    return obj

                return None

            # ---------- fallback for inherit-only base: inline anyOf ----------
            INHERIT_ONLY = {
                "inheritOnlyClass",
                "substitutableInheritOnlyClass",
                "containerInheritOnlyClass",
                "embeddedInheritOnlyClass",
            }
            base_role = (self._role(target_id) or "").strip()
            if base_role not in INHERIT_ONLY:
                return None

            # Build anyOf variant object stubs (excludes inherit-only roles internally)
            anyof_variants = self._make_anyof_variants(target_id, drop_hashes=True)
            if not anyof_variants:
                return None

            base_name = self._name(target_id)

            # Collect *base-owned* association-backed dotted properties
            # IMPORTANT: only include edges where base is the Start_Object (owner).
            base_assoc_props: dict[str, dict] = {}
            for uu, vv, kk, dd in A.edges(keys=True, data=True):
                ctype2 = str(dd.get("Connector_Type", "")).strip()
                if ctype2 not in ASSOC_LIKE:
                    continue

                owner2 = (dd.get("Start_Object") or "").strip()
                targ2 = (dd.get("End_Object") or "").strip()
                if not owner2 or not targ2:
                    continue
                if owner2 in STRUCTURAL_CONTAINERS or targ2 in STRUCTURAL_CONTAINERS:
                    continue
                if owner2 != base_name:
                    continue

                lab2 = (dd.get("label") or "").strip()
                if not lab2:
                    continue

                tid2 = name_to_id.get(targ2)
                if tid2 is None:
                    continue

                # Use simple reference emission for injected base-only props to avoid
                # deep recursion / anchoring side effects.
                ref2 = _ref_or_minimal(int(tid2))
                if not isinstance(ref2, dict):
                    continue

                mult2 = (dd.get("end_mult") or "").strip().replace(" ", "")
                is_single2 = (mult2 == "" or mult2 == "0..1")
                prop2 = ref2 if is_single2 else {"type": "array", "items": ref2}

                # never carry hashes on association entries
                prop2.pop("$primaryObjectHash", None)
                prop2.pop("$secondaryObjectHash", None)
                if isinstance(prop2.get("items"), dict):
                    prop2["items"].pop("$primaryObjectHash", None)
                    prop2["items"].pop("$secondaryObjectHash", None)

                pkey2 = f"{base_name}.{lab2}"
                base_assoc_props[pkey2] = prop2

            # Inject into each anyOf member (base-only)
            for vobj in anyof_variants:
                if not isinstance(vobj, dict):
                    continue
                vprops = vobj.setdefault("properties", {})
                if not isinstance(vprops, dict):
                    vprops = {}
                    vobj["properties"] = vprops
                for k2, sch2 in base_assoc_props.items():
                    vprops[k2] = sch2

            # Wrapper is an *object* with anyOf variants.
            # DO NOT include $objectId for inherit-only bases (per policy).
            return {"$objectType": "object", "type": "object", "$arrayPosition": None, "anyOf": anyof_variants}

        for u, v, key, data in A.edges(keys=True, data=True):
            ctype = str(data.get("Connector_Type", "")).strip()
            if ctype not in ASSOC_LIKE:
                continue

            owner_name = (data.get("Start_Object") or "").strip()
            target_name = (data.get("End_Object") or "").strip()
            if not owner_name or not target_name:
                continue

            # Skip structural wiring here no matter what
            if owner_name in STRUCTURAL_CONTAINERS or target_name in STRUCTURAL_CONTAINERS:
                continue

            # CRITICAL: only emit if label is present (visible label)
            label = (data.get("label") or "").strip()
            if not label:
                continue

            owner_id = name_to_id.get(owner_name)
            target_id = name_to_id.get(target_name)
            if owner_id is None or target_id is None:
                continue

            owner_ptr = self.def_ptr.get(owner_id)
            if not isinstance(owner_ptr, dict):
                continue  # owner not emitted/defined

            ref_schema = make_polymorphic_ref_schema(target_id)
            if not isinstance(ref_schema, dict):
                continue

            mult = (data.get("end_mult") or "").strip().replace(" ", "")
            is_single = (mult == "" or mult == "0..1")

            prop_schema = ref_schema if is_single else {"type": "array", "items": ref_schema}

            # Ensure association entries never carry hashes
            prop_schema.pop("$primaryObjectHash", None)
            prop_schema.pop("$secondaryObjectHash", None)
            if isinstance(prop_schema.get("items"), dict):
                prop_schema["items"].pop("$primaryObjectHash", None)
                prop_schema["items"].pop("$secondaryObjectHash", None)

            # Dedup
            cid_raw = data.get("ConnectorID")
            try:
                cid = int(cid_raw)
            except Exception:
                cid = -1
            sig = (cid, owner_name, label)
            if sig in seen_props:
                continue
            seen_props.add(sig)

            prop_key = f"{owner_name}.{label}"

            # HAND convention: if the owner is an object-anyOf wrapper (polymorphic rootClass),
            # do NOT attach association-backed properties at the wrapper level. Instead,
            # attach them to each anyOf member object.
            if owner_id in getattr(self, "_object_anyof_nodes", set()):
                anyof_list = owner_ptr.get("anyOf", [])
                if isinstance(anyof_list, list):
                    for variant in anyof_list:
                        if not isinstance(variant, dict):
                            continue
                        self._add_property(variant, prop_key, copy.deepcopy(prop_schema))
                continue

            # Default: add to owner
            self._add_property(owner_ptr, prop_key, prop_schema)

            # Also duplicate into each anyOf variant of the owner (if present)
            anyof_list = owner_ptr.get("anyOf", [])
            if isinstance(anyof_list, list):
                for variant in anyof_list:
                    if not isinstance(variant, dict):
                        continue
                    self._add_property(variant, prop_key, copy.deepcopy(prop_schema))


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

    def _nearest_anchor_ancestor(self, n: int) -> int:
        n = int(n)
        if not isinstance(self._anchor_set, set):
            return self.root_id
        seen = {n}
        q = deque([n])
        while q:
            cur = q.popleft()
            for parent in self.H.successors(cur):  # H: child -> parent
                if parent in seen:
                    continue
                seen.add(parent)
                if parent in self._anchor_set:
                    return int(parent)
                q.append(parent)
        return self.root_id

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

    def _apply_hashes_if_rootclass(self, node_id: int, obj: dict, *, drop_hashes: bool = False) -> None:
        """
        If node_id is tagged rootClass, add the standard object hashes
        (mirrors hand template).

        If drop_hashes=True, ensure hashes are NOT present (used for anyOf members).
        """
        if not isinstance(obj, dict):
            return

        if drop_hashes:
            obj.pop("$primaryObjectHash", None)
            obj.pop("$secondaryObjectHash", None)
            return

        if self._role(int(node_id)) == "rootClass":
            obj["$primaryObjectHash"] = "IdentifiedObject.name"
            obj["$secondaryObjectHash"] = "IdentifiedObject.mRID"

    def _order_fields(self, kind: str, d: dict) -> dict:
        """
        Return a new dict whose keys follow the preferred order for `kind`,
        with any extra keys appended, and with `anyOf` + `properties` ALWAYS last.
        """
        if not isinstance(d, dict):
            return d

        trailing = ("anyOf", "properties")
        order = self._FIELD_ORDER.get(kind, [])

        out = {}

        # 1) keys we know, in fixed order (excluding trailing; we'll force trailing later)
        for k in order:
            if k in trailing:
                continue
            if k in d:
                out[k] = d[k]

        # 2) any extras (in existing order), excluding trailing
        for k in d:
            if k in out or k in trailing:
                continue
            out[k] = d[k]

        # 3) trailing keys in fixed order
        for k in trailing:
            if k in d:
                out[k] = d[k]

        return out

    def _apply_field_order_recursively(self, node, *, is_root: bool = False):
        """
        Walk the entire JSON and reorder keys so that:
        - Root schema uses 'schema' ordering (title/$schema/$id/... first)
        - Objects/containers/references use their kind ordering
        - `anyOf` and `properties` are ALWAYS last keys in any dict
        """
        if isinstance(node, list):
            return [self._apply_field_order_recursively(v) for v in node]

        if not isinstance(node, dict):
            return node

        # Recurse into children first
        new = {}
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                new[k] = self._apply_field_order_recursively(v)
            else:
                new[k] = v

        # Decide kind
        if is_root:
            kind = "schema"
        else:
            ot = new.get("$objectType")
            if ot == "object":
                kind = "object"
            elif ot == "container":
                kind = "container"
            elif ot == "reference":
                kind = "reference"
            else:
                kind = None

        # Apply ordering
        if kind:
            return self._order_fields(kind, new)

        # Fallback for “plain dicts” (e.g., properties-maps): still force trailing keys last if present
        trailing = ("anyOf", "properties")
        out = {k: new[k] for k in new if k not in trailing}
        for k in trailing:
            if k in new:
                out[k] = new[k]
        return out

    def _make_anyof_variants(self, node_id: int, *, drop_hashes: bool = False) -> list[dict]:
        import networkx as nx

        INHERIT_ONLY = {
            "inheritOnlyClass",
            "substitutableInheritOnlyClass",
            "containerInheritOnlyClass",
            "embeddedInheritOnlyClass",
        }
        CONTAINERS = {"containerClass", "containerInheritOnlyClass"}

        def keep(nid: int) -> bool:
            r = self._role(int(nid))
            if r in INHERIT_ONLY:
                return False
            if r in CONTAINERS:
                return False
            return True

        node_id = int(node_id)
        variants = [node_id] + sorted(list(nx.descendants(self.HR, node_id)), key=lambda x: self._name(int(x)))

        out: list[dict] = []
        for vid in variants:
            vid = int(vid)
            if not keep(vid):
                continue

            sch = {
                "$objectType": "object",
                "type": "object",
                "$objectId": self._name(vid),
                "properties": {},
            }

            # anyOf members should NOT carry hashes (parent/wrapper may carry them)
            self._apply_hashes_if_rootclass(vid, sch, drop_hashes=drop_hashes)
            out.append(sch)

        return out
    
    def _strip_hashes_inside_anyof_when_parent_has_hashes(self, node: dict) -> None:
        """
        If a node has an 'anyOf' AND carries hashes itself, remove hashes
        from all child anyOf entries. Recurse throughout the tree.
        """
        if not isinstance(node, dict):
            return

        parent_has_hashes = (
            ("$primaryObjectHash" in node and node["$primaryObjectHash"] is not None) or
            ("$secondaryObjectHash" in node and node["$secondaryObjectHash"] is not None)
        )

        if parent_has_hashes and isinstance(node.get("anyOf"), list):
            for ent in node["anyOf"]:
                if isinstance(ent, dict):
                    ent.pop("$primaryObjectHash", None)
                    ent.pop("$secondaryObjectHash", None)

        props = node.get("properties")
        if isinstance(props, dict):
            for child in props.values():
                self._strip_hashes_inside_anyof_when_parent_has_hashes(child)

        anyof = node.get("anyOf")
        if isinstance(anyof, list):
            for ent in anyof:
                if isinstance(ent, dict):
                    self._strip_hashes_inside_anyof_when_parent_has_hashes(ent)


    # -------------------- build --------------------

    def build(self) -> dict:
        """
        Build auto_template:

        1) Top-level (Root/*): prefer A (Root -> X). Also include H-anchors (>=2 concrete descendants)
        as containers under Root.
        2) Descend H (via HR) from every top-level start (A-first-level and anchors).
        3) Cross-references are emitted when an encountered node’s owner ≠ the current node.
        4) Top-level keys ordered to match the hand template first, then A–Z.
        """
        # # --- ONLY FOR children directly under "Versions" ---
        # def _override_versions_hashes_if_child_of_versions(owner_path: tuple, obj_dict: dict) -> None:
        #     """
        #     If the emitted node is an *object* placed directly under the 'Versions'
        #     container, set $primaryObjectHash to null and remove $secondaryObjectHash.
        #     """
        #     if not isinstance(obj_dict, dict):
        #         return
        #     if not owner_path or owner_path[-1] != "Versions":
        #         return
        #     if obj_dict.get("$objectType") != "object":
        #         return
        #     obj_dict["$primaryObjectHash"] = None
        #     obj_dict.pop("$secondaryObjectHash", None)

        # --- ONLY for objects directly under "Versions" (hash override only) ---
        def _override_versions_object(owner_path: tuple, obj_dict: dict) -> None:
            """
            If an *object* is emitted directly under the 'Versions' container:
            - set $primaryObjectHash to null
            - remove $secondaryObjectHash
            """
            if not isinstance(obj_dict, dict):
                return
            if not owner_path or owner_path[-1] != "Versions":
                return
            if obj_dict.get("$objectType") != "object":
                return
            obj_dict["$primaryObjectHash"] = None
            obj_dict.pop("$secondaryObjectHash", None)


        # --- Decorate the 'Versions' container itself ---
        def _decorate_versions_container(obj_name: str, obj_dict: dict) -> None:
            """
            If the emitted node is the 'Versions' *container*:
            - insert 'description' after 'type' and before 'properties'
            """
            if obj_name != "Versions" or not isinstance(obj_dict, dict):
                return
            if obj_dict.get("$objectType") != "container":
                return
            props = obj_dict.pop("properties", {})
            obj_dict["description"] = "Specify the versions of CIM / RAVENS used in this file"
            obj_dict["properties"] = props

        # ---------- setup ----------
        root_title = (self.A.nodes[self.root_id].get("Name") if isinstance(self.A, nx.Graph) and self.root_id in self.A
                    else self.H.nodes[self.root_id].get("Name")) or "Root"

        # caches
        self._owner_cache = {}
        self.def_ptr = {}
        self.path_map = {}
        self._object_anyof_nodes = set()

        role = lambda n: (self.A.nodes[n].get("ravensRole")
                        if isinstance(self.A, nx.Graph) and n in self.A else self.H.nodes[n].get("ravensRole")) or ""
        name = lambda n: (self.A.nodes[n].get("Name")
                        if isinstance(self.A, nx.Graph) and n in self.A else self.H.nodes[n].get("Name")) or ""

        # compute anchors from H and expose to _ensure_defined
        self._anchor_set = self._compute_anchors()

        schema = {
            "title": root_title,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://raw.githubusercontent.com/lanl-ansi/MG-RAVENS/refs/heads/schema/Root.json",
            "type": "object",
            "properties": {},
        }
        self._root_schema_obj = schema

        # register Root
        self.def_ptr[self.root_id] = schema
        self.path_map[self.root_id] = (root_title,)

        # ---------- 1) top-level from A (Root -> child) ----------
        if isinstance(self.A, nx.DiGraph) and self.root_id in self.A:
            fl = {int(n) for n in self.A.successors(self.root_id)}
            first_level_nodes = sorted(
                [n for n in fl if role(n).strip() != "inheritOnlyClass"],
                key=lambda n: name(n).casefold()
            )
        else:
            first_level_nodes = []

        FIRST_LEVEL_SET = {int(n) for n in first_level_nodes}

        def ensure_defined(n: int, stack_containers: set[int], *, force_owner: Optional[int] = None,
                        at_top_level: bool = False, force_kind: Optional[str] = None):
            n = int(n)
            if n in self.def_ptr:
                return

            # choose owner
            if force_owner is not None:
                owner = int(force_owner)
            else:
                owner = self._nearest_owner_in_stack(n, stack_containers)
                # prevent accidental new top-level unless explicitly in FIRST_LEVEL_SET
                if owner == self.root_id and n not in FIRST_LEVEL_SET and not at_top_level:
                    non_root = [c for c in stack_containers if c != self.root_id]
                    owner = non_root[-1] if non_root else self.root_id

            owner_ptr = self.def_ptr.get(owner)
            owner_path = self.path_map.get(owner)
            if not isinstance(owner_ptr, dict) or not isinstance(owner_path, tuple):
                raise RuntimeError(f"Owner for node {n} is not defined.")

            nm = name(n)
            r  = role(n).strip()

            # --- emission rules ---
            if force_kind == "container":
                node_obj = {"$objectType": "container", "type": "object", "properties": {}}
                _decorate_versions_container(nm, node_obj)

            elif force_kind == "object":
                node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                self._apply_hashes_if_rootclass(n, node_obj)
                _override_versions_object(owner_path, node_obj)

            elif n in getattr(self, "_anchor_set", set()):
                node_obj = {"$objectType": "container", "type": "object", "properties": {}}

            elif r == "inheritOnlyClass":
                # never emit inheritOnly; still record a path for completeness
                self.path_map[n] = owner_path + (nm,)
                self.def_ptr[n] = None
                return

            elif r == "containerClass":
                node_obj = {"$objectType": "container", "type": "object", "properties": {}}
                _decorate_versions_container(nm, node_obj)

            elif r == "rootClass":
                # If this root class is polymorphic, emit metadata + object-anyOf (like hand template),
                # but suppress hashes on the anyOf entries themselves.
                variants = self._make_anyof_variants(n, drop_hashes=True)
                if len(variants) >= 2:
                    node_obj = {
                        "$objectType": "object",
                        "$objectId": nm,
                        "type": "object",
                        "anyOf": variants
                    }
                    self._apply_hashes_if_rootclass(n, node_obj)     # hashes live on the wrapper
                    _override_versions_object(owner_path, node_obj)  # keep the Versions tweak
                    self._object_anyof_nodes.add(n)                  # remember to suppress named children later
                else:
                    node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                    self._apply_hashes_if_rootclass(n, node_obj)
                    _override_versions_object(owner_path, node_obj)

            elif r == "substitutableClass":
                # Substitutable classes themselves are plain objects; parent carries the anyOf.
                node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                self._apply_hashes_if_rootclass(n, node_obj)
                _override_versions_object(owner_path, node_obj)

            else:
                node_obj = {"$objectType": "object", "$objectId": nm, "type": "object", "properties": {}}
                self._apply_hashes_if_rootclass(n, node_obj)
                _override_versions_object(owner_path, node_obj)

            self._add_property(owner_ptr, nm, node_obj)
            self.path_map[n] = owner_path + (nm,)
            self.def_ptr[n] = node_obj

        # For anchors, prefer the unique base-class owner when possible.
        def preferred_anchor_owner(a: int) -> int:
            """
            Decide which node should own an anchor `a`.

            - If `a` has exactly one base class in H and that base is not Root,
            we ensure the base is defined (as a container under Root) and
            then use that base as the owner.
            - Otherwise, fall back to Root.

            Debug prints are included to understand what happens for anchors
            like 'Equipment'.
            """
            a = int(a)
            parents = list(self.H.successors(a))  # H: child -> parent
            base = int(parents[0]) if len(parents) == 1 else None

            # Basic info for debugging
            try:
                a_name = name(a)
                parent_names = [name(p) for p in parents]
                naa = self._nearest_anchor_ancestor(a) if hasattr(self, "_anchor_set") else None
                print(
                    f"[AUTO][anchor] considering {a} ({a_name}); "
                    f"parents={parents} ({parent_names}); "
                    f"nearest_anchor_ancestor={naa}; "
                    f"base={base}"
                )
            except Exception:
                pass

            # If there is a single, non-root base, prefer it as the owner.
            if base is not None and base != self.root_id:
                # If the base is not yet defined, define it as a container under Root
                if base not in self.def_ptr:
                    try:
                        print(
                            f"[AUTO][anchor] base {base} ({name(base)}) not yet defined; "
                            f"defining it under Root before placing {a_name}"
                        )
                    except Exception:
                        pass
                    ensure_defined(
                        base,
                        stack_containers={self.root_id},
                        force_owner=self.root_id,
                        at_top_level=True,
                        force_kind="container",
                    )

                base_ptr = self.def_ptr.get(base)
                if isinstance(base_ptr, dict):
                    try:
                        print(
                            f"[AUTO][anchor] -> using base owner for {a_name}: "
                            f"{base} ({name(base)})"
                        )
                    except Exception:
                        pass
                    return base

            # Fallback: Root owns the anchor
            try:
                print(f"[AUTO][anchor] -> defaulting owner of {name(a)} to Root")
            except Exception:
                pass
            return self.root_id

        def add_xref(at_node: int, target: int):
            if not self.EMIT_CROSS_REFS:
                return
            at_ptr = self.def_ptr.get(at_node)
            if not isinstance(at_ptr, dict):
                return

            # If target participates in a polymorphic family (base + descendants),
            # emit an anyOf of references; otherwise emit a single reference.
            variants = self._collect_polymorphic_variants(int(target))
            # Only use anyOf if there are >= 2 viable variants
            if len(variants) >= 2:
                items = [self._make_ref(v) for v in variants]
                items = [x for x in items if isinstance(x, dict)]
                self._add_property(at_ptr, self._name(target), {"anyOf": items})
                return

            # fallback: single reference
            ref = self._make_ref(int(target))
            if ref:
                self._add_property(at_ptr, self._name(target), ref)

        # Force-create top-level A-derived under Root (even if inheritOnly)
        for n in first_level_nodes:
            ensure_defined(n, stack_containers={self.root_id}, force_owner=self.root_id, at_top_level=True)

        # ---------- only promote *top-level* H-anchors ----------
        anchors = sorted((self._anchor_set - {self.root_id}), key=lambda n: name(n).casefold())
        top_level_anchors = [
            a for a in anchors
            if (self._nearest_anchor_ancestor(a) == self.root_id) and (role(a).strip() != "inheritOnlyClass")
        ]
        for a in top_level_anchors:
            if a in self.def_ptr:
                # Already defined somewhere else (e.g., as a base we just forced into existence)
                continue

            owner_for_anchor = preferred_anchor_owner(a)

            # Debug: show the final decision
            try:
                print(
                    f"[AUTO][anchor] FINAL placement for {name(a)}: "
                    f"owner={owner_for_anchor} ({name(owner_for_anchor)})"
                )
            except Exception:
                pass

            ensure_defined(
                a,
                stack_containers={owner_for_anchor},
                force_owner=owner_for_anchor,
                at_top_level=(owner_for_anchor == self.root_id),
                force_kind="container",
            )

            owner_for_anchor = preferred_anchor_owner(a)
            ensure_defined(
                a,
                stack_containers={owner_for_anchor},
                force_owner=owner_for_anchor,
                at_top_level=(owner_for_anchor == self.root_id),
                force_kind="container",
            )

        # collect starting points for H descent
        walk_anchors = list(dict.fromkeys(list(first_level_nodes) + top_level_anchors))

        # ---------- SPECIAL DIAGRAMS: treat "Versions" and "Group" like mini-Roots ----------
        special_diagrams = ("Versions", "Group")
        for label in special_diagrams:
            sid = self._find_node_by_name(label)
            if sid is None:
                continue
            if sid not in self.def_ptr:
                ensure_defined(sid, stack_containers={self.root_id}, force_owner=self.root_id,
                            at_top_level=True, force_kind="container")
            # Place every node connected to it *in its own diagram* directly under it
            for child in self._diagram_neighbors(sid, label):
                ensure_defined(child, stack_containers={self.root_id, sid}, force_owner=sid)
            if sid not in walk_anchors:
                walk_anchors.append(sid)

        # ---------- 2a) descend H below each top-level start ----------
        visited_down = set()

        def is_container_like(n: int) -> bool:
            r = role(n).strip()
            return (r != "inheritOnlyClass") and ((r == "containerClass") or (n in self._anchor_set))

        for anchor in walk_anchors:
            q = deque([(anchor, self.path_map.get(anchor, ("Root",)))])
            while q:
                cur, owner_path = q.popleft()

                # Where is 'cur' defined and what JSON dict owns its properties?
                owner_ptr = self.def_ptr.get(cur)
                if not isinstance(owner_ptr, dict):
                    # if cur wasn’t defined yet (shouldn’t happen for anchors), skip
                    continue


                # Ensure every defined node also has a usable path. This is critical when
                # we bind HR child nodes to inline anyOf-member dicts (substitution unions):
                # those members are not created via ensure_defined(), so without a path_map
                # entry, later calls that use force_owner=<cur> will fail.
                if isinstance(owner_path, tuple) and cur not in self.path_map:
                    self.path_map[cur] = owner_path

                # Don’t add named children to an object that is represented as anyOf
                skip_named_children = cur in getattr(self, "_object_anyof_nodes", set())

                # Get HR children of 'cur' (i.e., its subclasses)
                children = sorted(self.HR.successors(cur), key=lambda n: name(n).casefold())

                # >>> THIS LOOP MUST BE INSIDE 'while q:' <<<
                for child in children:
                    rchild = role(child).strip()
                    cname = name(child)

                    if skip_named_children:
                        # `cur` is represented as an object-anyOf wrapper (substitution union).
                        # HAND convention: do NOT create named properties for variants on the wrapper.
                        # We still descend through the variant nodes so their embedded children can be emitted.
                        if not isinstance(self.def_ptr.get(int(child)), dict):
                            anyof_list = owner_ptr.get("anyOf", [])
                            if isinstance(anyof_list, list):
                                for member in anyof_list:
                                    if not isinstance(member, dict):
                                        continue
                                    if member.get("$objectType") != "object":
                                        continue
                                    if (member.get("$objectId") or "").strip() == cname:
                                        self.def_ptr[int(child)] = member
                                        # Bind a stable path for this inline anyOf member so it can
                                        # act as a force_owner target for its embedded children.
                                        if isinstance(owner_path, tuple):
                                            self.path_map[int(child)] = owner_path + (cname,)
                                        break
                        if rchild != "inheritOnlyClass":
                            q.append((child, self.path_map.get(child, owner_path + (cname,))))
                        continue


                    # Determine whether this child should be treated as a container “shelf”
                    is_container_like = (
                        (rchild == "containerClass") or
                        (child in self._anchor_set and rchild != "inheritOnlyClass")
                    )

                    # Define child (if needed) under the current owner (cur)
                    if child not in self.def_ptr:
                        ensure_defined(
                            child,
                            stack_containers={cur},
                            force_owner=cur,
                            at_top_level=False,
                            # containers get container kind; others follow their role
                            force_kind="container" if is_container_like else None,
                        )
                    else:
                        # if it is defined elsewhere, add a cross-ref here
                        if self.EMIT_CROSS_REFS:
                            add_xref(cur, child)

                    # If the current node is an object-anyOf wrapper, don’t add named props
                    if skip_named_children:
                        continue

                    # If we just defined a container or object here, descend into any
                    # non-inheritOnly child so we traverse the full depth of H.
                    if rchild != "inheritOnlyClass":
                        q.append((child, self.path_map.get(child, owner_path + (cname,))))

        # ---------- 2b) associations: dotted reference properties on owners ----------
        self._emit_association_entries()

        # ---------- 3) top-level ordering like hand ----------
        schema["properties"] = self._order_props_like_hand(schema.get("properties", {}))

        # enforce: if a node has anyOf AND carries hashes, its anyOf entries must NOT have hashes
        self._strip_hashes_inside_anyof_when_parent_has_hashes(schema)

        # Enforce field order across the tree
        schema = self._apply_field_order_recursively(schema, is_root=True)
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


class TemplateCompare:
    """
    Compare structural aspects of the hand vs auto templates.

    Defaults:
      • Loads hand from ravens.data._TEMPLATE_JSON_PATH
      • Loads auto from ravens.data._TEMPLATE_AUTOJSON_PATH

    You can override either by passing a dict or a path-like.
    """

    def __init__(self,
                 hand: Optional[dict | str | "os.PathLike[str]"] = None,
                 auto: Optional[dict | str | "os.PathLike[str]"] = None,
                 root_title: str = "Root",
                 encoding: str = "utf-8"):
        self.root_title = root_title
        self.encoding = encoding
        self.hand_schema, self.hand_path = self._coerce_schema(hand, default_path=_TEMPLATE_JSON_PATH)
        self.auto_schema, self.auto_path = self._coerce_schema(auto, default_path=_TEMPLATE_AUTOJSON_PATH)

    # ---------- construction helpers ----------

    def _coerce_schema(self, src, default_path):
        """
        Returns (schema_dict, pathlib.Path|None). If src is None, load default_path.
        If src is a path-like/str, load it. If src is a dict, return it as-is.
        """
        if src is None:
            path = Path(default_path)
            data = json.loads(path.read_text(encoding=self.encoding))
            return data, path
        if isinstance(src, dict):
            return src, None
        # path-like
        path = Path(src)
        data = json.loads(path.read_text(encoding=self.encoding))
        return data, path

    # ---------- internals ----------

    def _find_root_obj(self, schema: dict) -> dict:
        """
        Return the object that represents 'Root'.
        Assumes top-level is Root; if not, tries to find an object with title == self.root_title.
        """
        if isinstance(schema, dict):
            # direct match
            if schema.get("title") == self.root_title and isinstance(schema.get("properties"), dict):
                return schema
            # fallback: top-level with properties
            if "properties" in schema and isinstance(schema["properties"], dict):
                return schema
        return schema

    def _root_keys(self, schema: dict) -> set[str]:
        root = self._find_root_obj(schema)
        props = root.get("properties", {})
        if not isinstance(props, dict):
            return set()
        return set(props.keys())

    # ---------- public API ----------

    @classmethod
    def from_paths(cls, hand_path: str, auto_path: str, root_title: str = "Root", encoding: str = "utf-8"):
        return cls(hand=hand_path, auto=auto_path, root_title=root_title, encoding=encoding)

    def compare_root_objects(self) -> dict:
        """
        Compute the three sets: hand_only, auto_only, both.
        """
        h = self._root_keys(self.hand_schema)
        a = self._root_keys(self.auto_schema)
        return {
            "hand_only": sorted(h - a, key=str.casefold),
            "auto_only": sorted(a - h, key=str.casefold),
            "both":      sorted(h & a, key=str.casefold),
        }

    def report(self) -> str:
        """
        Return a printable, multi-line text report.
        """
        cmp = self.compare_root_objects()
        sections = [
            ("Hand only", cmp["hand_only"]),
            ("Auto only", cmp["auto_only"]),
            ("Both",      cmp["both"]),
        ]
        lines = []
        for title, items in sections:
            lines.append(f"{title} ({len(items)}):")
            if items:
                for it in items:
                    lines.append(f"  - {it}")
            else:
                lines.append("  (none)")
            lines.append("")  # blank line
        return "\n".join(lines).rstrip()

    def print_report(self) -> None:
        print(self.report())

    def __str__(self) -> str:
        return self.report()

