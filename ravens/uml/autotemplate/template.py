from __future__ import annotations

import json
import copy
from collections import deque
from typing import Any, Dict, List, Set, Tuple, Optional
import networkx as nx



STRUCTURAL_CONTAINERS = {"Root", "Group", "Groups", "Version", "Versions"}

class TemplateGenerator:
    """
    Build an auto_template using only the inheritance graph H (child -> parent).

    Placement rules (H-only, tag-light):
      â€¢ Concrete = nodes tagged 'rootClass' or 'embeddedClass'.
      â€¢ Anchor containers (top-level under Root) = nodes having >= 2 concrete descendants in H.
        (E.g., 'Versions' becomes a container even if its tag says inheritOnly.)
      â€¢ Concrete nodes with no qualifying ancestor anchor -> placed directly under Root.
      â€¢ Under each container anchor, emit its nearest concrete descendants.
      â€¢ A class is defined exactly once; additional appearances are references.
      â€¢ Cross-references are enabled.

    We do not use A at all in this pass and we do not trust notConcrete tags for placement
    (we only read 'rootClass'/'embeddedClass' to know what is "concrete").
    """

    def __init__(
        self,
        *,
        H: nx.DiGraph,
        A: Optional[nx.MultiDiGraph] = None,
        root_name: str = "Root",
        debug: bool = False,
        capture_diagnostics: bool = False,
    ):
           
            if not isinstance(H, nx.DiGraph):
                raise TypeError("H must be a networkx.DiGraph oriented child -> parent.")
            self.H: nx.DiGraph = H
            self.HR: nx.DiGraph = H.reverse(copy=False)
            self.A = A 
            self.debug = bool(debug)
            self.capture_diagnostics = bool(capture_diagnostics)
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
            self._analysis_variable_events: list[dict[str, Any]] = []
            self._analysis_variable_event_keys: set[str] = set()

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

    def _add_analysis_variable_event(self, event: str, **details: Any) -> None:
        if not self.capture_diagnostics:
            return

        payload = {"event": event, **details}
        event_key = json.dumps(payload, sort_keys=True, default=str)
        if event_key in self._analysis_variable_event_keys:
            return
        self._analysis_variable_event_keys.add(event_key)
        self._analysis_variable_events.append(payload)

    def analysis_variable_diagnostics_payload(self) -> dict[str, Any]:
        return {
            "event_count": len(self._analysis_variable_events),
            "analysis_variable_events": self._analysis_variable_events,
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

        analysis_variable_family_id = name_to_id.get("AnalysisVariable")
        operations_variable_family_id = name_to_id.get("OperationsVariable")

        def _ptr_name(ptr: dict | None) -> str:
            if not isinstance(ptr, dict):
                return ""
            return (ptr.get("$objectId") or "").strip()

        def _schema_summary(schema: dict | None) -> dict[str, Any]:
            if not isinstance(schema, dict):
                return {"kind": "none"}
            return {
                "object_id": (schema.get("$objectId") or "").strip() or None,
                "object_type": (schema.get("$objectType") or "").strip() or None,
                "type": (schema.get("type") or "").strip() or None,
                "has_anyof": isinstance(schema.get("anyOf"), list),
                "anyof_size": len(schema.get("anyOf", [])) if isinstance(schema.get("anyOf"), list) else 0,
            }

        def _should_trace_family(family_id: int | None) -> bool:
            if analysis_variable_family_id is None or family_id is None:
                return False
            try:
                return int(family_id) == int(analysis_variable_family_id)
            except Exception:
                return False

        INHERIT_ONLY = {
            "inheritOnlyClass",
            "substitutableInheritOnlyClass",
            "containerInheritOnlyClass",
            "embeddedInheritOnlyClass",
        }
        CONTAINERS = {"containerClass", "containerInheritOnlyClass"}
        NON_SELECTABLE_FAMILY_ROLES = INHERIT_ONLY | CONTAINERS

        ASSOC_LIKE = {"Association", "Aggregation", "Composition"}

        # Never generate dotted properties for these structural wiring nodes.
        # (They are handled elsewhere: Root first-level placement, and your special-diagram logic.)
        STRUCTURAL_CONTAINERS = {"Root", "Group", "Groups", "Version", "Versions"}

        # Deduplicate by (ConnectorID, OwnerName, Label) so multiple diagram instances
        # donâ€™t generate identical properties. If you want *every* diagram-instance emitted,
        # include InstanceID in the signature instead.
        seen_props: set[tuple[int, str, str]] = set()

        def _make_inline_embedded_stub(tid: int) -> dict | None:
            """
            Build a minimal inline object stub for an embedded target.
            """
            tid = int(tid)
            tname = self._name(tid)
            if not tname:
                return None

            obj = {
                "$objectType": "object",
                "$objectId": tname,
                "type": "object",
                "$arrayPosition": None,
                "properties": {},
            }

            # Optional array-position hints for embedded array members
            # (keep this tiny + explicit; add entries as we encounter them).
            EMBEDDED_ARRAY_POSITION = {
                "PositionPoint": "PositionPoint.sequenceNumber",
                "TransformerEnd": "TransformerEnd.endNumber",
                "PowerTransformerEnd": "TransformerEnd.endNumber",
                "TransformerTankEnd": "TransformerEnd.endNumber",
            }
            EMBEDDED_ARRAY_POSITION_BY_PARENT = {
                "TransformerEnd": "TransformerEnd.endNumber",
            }

            if tname in EMBEDDED_ARRAY_POSITION:
                obj["$arrayPosition"] = EMBEDDED_ARRAY_POSITION[tname]
            else:
                try:
                    for parent_id in self.H.successors(tid):
                        pname = self._name(int(parent_id))
                        if pname in EMBEDDED_ARRAY_POSITION_BY_PARENT:
                            obj["$arrayPosition"] = EMBEDDED_ARRAY_POSITION_BY_PARENT[pname]
                            break
                except Exception:
                    pass

            return obj

        def _strip_assoc_hashes(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node.pop("$primaryObjectHash", None)
            node.pop("$secondaryObjectHash", None)
            items = node.get("items")
            if isinstance(items, dict):
                _strip_assoc_hashes(items)
            props = node.get("properties")
            if isinstance(props, dict):
                for child in props.values():
                    if isinstance(child, dict):
                        _strip_assoc_hashes(child)
            anyof = node.get("anyOf")
            if isinstance(anyof, list):
                for ent in anyof:
                    if isinstance(ent, dict):
                        _strip_assoc_hashes(ent)

        def _clone_defined_object_schema(tid: int) -> dict | None:
            tid = int(tid)
            ptr = self.def_ptr.get(tid)
            if isinstance(ptr, dict) and ptr.get("$objectType") in {"object", "container"}:
                cloned = copy.deepcopy(ptr)
                _strip_assoc_hashes(cloned)
                return cloned
            return _make_inline_embedded_stub(tid)

        def _resolve_variant_schema_for_owner(owner_variant_name: str, variant_schemas: dict[str, dict] | None) -> dict | None:
            """
            Only resolve by exact concrete class identity, never by string similarity.
            Generic reuse across nested inline subtrees is handled by family-resolution
            context, not by matching class-name suffixes.
            """
            if not owner_variant_name or not isinstance(variant_schemas, dict) or not variant_schemas:
                return None
            return variant_schemas.get(owner_variant_name)

        def make_polymorphic_ref_schema(target_id: int, *, owner_id: int | None = None) -> dict | None:
            """
            Build schema for an association target.

            Preferred form (when targets are defined somewhere in the template):
              - If target has >=2 variants (base+descendants), emit outer reference wrapper
                {$objectType:"reference",$objectId:<base>, anyOf:[refs...]}.
              - Else emit a single ref.

            Fallbacks:
              - If we cannot build refs AND the *base* target is an inherit-only role,
                emit an inline object wrapper with anyOf of substitutable variants.
              - If we cannot build refs AND the *base* target is an embeddedClass with
                polymorphic descendants, emit inline embedded stubs instead of dropping
                the property. For object-anyOf owners, return a per-owner-variant mapping
                when we can align owner/target variant families by name.
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

            base_role = (self._role(target_id) or "").strip()

            # ---------- preferred: build refs ----------
            if len(variants) >= 2 and base_role != "embeddedClass":
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

                t_role = (self._role(tid) or "").strip()

                # Embedded association targets should stay inline even when the
                # class is also defined elsewhere in the template.
                if t_role == "embeddedClass":
                    return _clone_defined_object_schema(tid)

                # Preferred: real ref to an already-defined target
                ref = self._make_ref(tid)
                if isinstance(ref, dict):
                    ref.pop("$primaryObjectHash", None)
                    ref.pop("$secondaryObjectHash", None)
                    return ref

                # Power-transformer style case:
                # a terminal substitutable leaf whose nearest visible parent is embedded.
                # These do not exist elsewhere as named ref targets, so emit inline stubs
                # instead of dropping the association entirely.
                if t_role == "substitutableClass":
                    try:
                        for parent_id in self.H.successors(tid):
                            if (self._role(int(parent_id)) or "").strip() == "embeddedClass":
                                return _make_inline_embedded_stub(tid)

                        # Inline anyOf-member families under a rootClass wrapper do not
                        # have their own stable reference paths. When a labeled association
                        # targets one of those inline members, point back at the family
                        # wrapper path while preserving member-specific $objectId values so
                        # recipient resolution can choose the appropriate family variant.
                        for parent_id in self.H.successors(tid):
                            parent_ident = int(parent_id)
                            if (self._role(parent_ident) or "").strip() != "rootClass":
                                continue
                            base_ref = self._make_ref(parent_ident)
                            if not isinstance(base_ref, dict):
                                continue

                            variant_refs: dict[str, dict] = {}
                            for family_variant in self._collect_polymorphic_variants(parent_ident):
                                try:
                                    family_variant_id = int(family_variant)
                                except Exception:
                                    continue
                                family_variant_name = (self._name(family_variant_id) or "").strip()
                                family_variant_role = (self._role(family_variant_id) or "").strip()
                                if not family_variant_name or family_variant_role in INHERIT_ONLY or family_variant_role in CONTAINERS:
                                    continue

                                vref = copy.deepcopy(base_ref)
                                vref["$objectId"] = family_variant_name
                                variant_refs[family_variant_name] = vref

                            if variant_refs:
                                default_ref = copy.deepcopy(base_ref)
                                default_ref["$objectId"] = (self._name(tid) or "").strip() or default_ref.get("$objectId")
                                return {
                                    "__variantSchemas__": variant_refs,
                                    "__defaultSchema__": default_ref,
                                    "__contextFamilyId__": parent_ident,
                                }
                    except Exception:
                        pass

                return None

            def _keep_variant(nid: int) -> bool:
                r = self._role(int(nid))
                if r in INHERIT_ONLY:
                    return False
                if r in CONTAINERS:
                    return False
                return True

            # ---------- fallback for polymorphic embedded base: inline stubs ----------
            if base_role == "embeddedClass":
                kept_variants = [int(v) for v in variants if _keep_variant(v)]
                embedded_variants = []
                embedded_by_name: dict[str, dict] = {}
                for v in kept_variants:
                    stub = _clone_defined_object_schema(v)
                    if not isinstance(stub, dict):
                        continue
                    embedded_variants.append(copy.deepcopy(stub))
                    embedded_by_name[self._name(v)] = copy.deepcopy(stub)

                if not embedded_variants:
                    return None

                generic_wrapper = {
                    "$objectType": "object",
                    "$objectId": self._name(target_id),
                    "type": "object",
                    "$arrayPosition": None,
                    "anyOf": copy.deepcopy(embedded_variants),
                }

                # If the owner is an object-anyOf wrapper, try to align each owner variant
                # to a corresponding embedded target variant by replacing the owner's base
                # name with the target base name. This captures patterns like:
                #   ShuntCompensator -> ShuntCompensatorPhase
                #   LinearShuntCompensator -> LinearShuntCompensatorPhase
                if owner_id is not None and int(owner_id) in getattr(self, "_object_anyof_nodes", set()):
                    owner_base_name = self._name(int(owner_id))
                    target_base_name = self._name(target_id)
                    owner_ptr = self.def_ptr.get(int(owner_id))
                    owner_anyof = owner_ptr.get("anyOf", []) if isinstance(owner_ptr, dict) else []
                    if owner_base_name and target_base_name and isinstance(owner_anyof, list):
                        variant_schemas: dict[str, dict] = {}
                        for owner_variant in owner_anyof:
                            if not isinstance(owner_variant, dict):
                                continue
                            owner_variant_name = (owner_variant.get("$objectId") or "").strip()
                            if not owner_variant_name:
                                continue

                            if owner_variant_name != owner_base_name and owner_base_name in owner_variant_name:
                                candidate_name = owner_variant_name.replace(owner_base_name, target_base_name)
                            else:
                                candidate_name = ""

                            chosen = embedded_by_name.get(candidate_name)
                            if isinstance(chosen, dict):
                                variant_schemas[owner_variant_name] = copy.deepcopy(chosen)

                        if variant_schemas:
                            return {
                                "__variantSchemas__": variant_schemas,
                                "__defaultSchema__": copy.deepcopy(generic_wrapper),
                                "__contextFamilyId__": int(target_id),
                            }

                return generic_wrapper

            # ---------- fallback for inherit-only base: inline anyOf ----------
            if base_role not in INHERIT_ONLY:
                return None

            # Build anyOf variant object stubs (excludes inherit-only roles internally)
            anyof_variants = self._make_anyof_variants(target_id, drop_hashes=True)
            if not anyof_variants:
                return None

            if _should_trace_family(target_id):
                self._add_analysis_variable_event(
                    "family_wrapper_emitted",
                    target_id=int(target_id),
                    base_name=self._name(target_id),
                    base_role=base_role,
                    variant_names=[
                        (variant.get("$objectId") or "").strip()
                        for variant in anyof_variants
                        if isinstance(variant, dict) and (variant.get("$objectId") or "").strip()
                    ],
                    variant_roles={
                        (variant.get("$objectId") or "").strip(): self._role(name_to_id[(variant.get("$objectId") or "").strip()])
                        for variant in anyof_variants
                        if isinstance(variant, dict)
                        and (variant.get("$objectId") or "").strip() in name_to_id
                    },
                )

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
            # Keep the base $objectId so downstream schema decomposition can
            # preserve a stable family identity for wrapper-backed arrays.
            return {
                "__variantSchemas__": {
                    str(v.get("$objectId")): copy.deepcopy(v)
                    for v in anyof_variants
                    if isinstance(v, dict) and (v.get("$objectId") or "")
                },
                "__defaultSchema__": {
                    "$objectType": "object",
                    "$objectId": base_name,
                    "type": "object",
                    "$arrayPosition": None,
                    "anyOf": copy.deepcopy(anyof_variants),
                },
                "__contextFamilyId__": int(target_id),
            }

        inline_owner_ptrs = getattr(self, "_inline_owner_ptrs", None)
        if not isinstance(inline_owner_ptrs, dict):
            inline_owner_ptrs = {}
            self._inline_owner_ptrs = inline_owner_ptrs

        inline_owner_ptr_ids = getattr(self, "_inline_owner_ptr_ids", None)
        if not isinstance(inline_owner_ptr_ids, dict):
            inline_owner_ptr_ids = {}
            self._inline_owner_ptr_ids = inline_owner_ptr_ids

        inline_registration_seen_nodes = getattr(self, "_inline_registration_seen_nodes", None)
        if not isinstance(inline_registration_seen_nodes, set):
            inline_registration_seen_nodes = set()
            self._inline_registration_seen_nodes = inline_registration_seen_nodes

        inline_parent_ptr_ids = getattr(self, "_inline_parent_ptr_ids", None)
        if not isinstance(inline_parent_ptr_ids, dict):
            inline_parent_ptr_ids = {}
            self._inline_parent_ptr_ids = inline_parent_ptr_ids

        inline_ptr_registry = getattr(self, "_inline_ptr_registry", None)
        if not isinstance(inline_ptr_registry, dict):
            inline_ptr_registry = {}
            self._inline_ptr_registry = inline_ptr_registry

        resolution_contexts = getattr(self, "_association_resolution_contexts", None)
        if not isinstance(resolution_contexts, dict):
            resolution_contexts = {}
            self._association_resolution_contexts = resolution_contexts

        family_stem_cache: dict[int, dict[int, str]] = {}
        family_selectable_variant_cache: dict[int, list[int]] = {}
        analysis_result_family_id = name_to_id.get("AnalysisResult")
        analysis_result_data_family_id = name_to_id.get("AnalysisResultData")

        def _normalize_mult(raw: Any) -> str:
            if raw is None:
                return ""
            text = str(raw).strip().replace(" ", "")
            return "" if text.casefold() == "nan" else text

        def _is_self_or_descendant(node_id: int | None, ancestor_id: int | None) -> bool:
            if node_id is None or ancestor_id is None:
                return False
            try:
                cur = int(node_id)
                anc = int(ancestor_id)
            except Exception:
                return False
            if cur == anc:
                return True
            seen: set[int] = set()
            stack = [cur]
            while stack:
                cur_id = stack.pop()
                if cur_id in seen:
                    continue
                seen.add(cur_id)
                for parent_id in self.H.successors(cur_id):
                    try:
                        pid = int(parent_id)
                    except Exception:
                        continue
                    if pid == anc:
                        return True
                    if pid not in seen:
                        stack.append(pid)
            return False

        def _longest_common_prefix(names: list[str]) -> str:
            if not names:
                return ""
            prefix = names[0]
            for name in names[1:]:
                limit = min(len(prefix), len(name))
                idx = 0
                while idx < limit and prefix[idx] == name[idx]:
                    idx += 1
                prefix = prefix[:idx]
                if not prefix:
                    break
            return prefix

        def _family_selectable_variant_ids(family_root_id: int | None) -> list[int]:
            if family_root_id is None:
                return []
            try:
                fid = int(family_root_id)
            except Exception:
                return []

            cached = family_selectable_variant_cache.get(fid)
            if cached is not None:
                return cached

            candidate_ids: list[int] = []
            excluded_variants: list[dict[str, Any]] = []
            raw_variant_ids: list[int] = []

            for variant_id in self._collect_polymorphic_variants(fid):
                try:
                    vid = int(variant_id)
                except Exception:
                    continue
                raw_variant_ids.append(vid)
                vrole = (self._role(vid) or "").strip()
                if vrole in NON_SELECTABLE_FAMILY_ROLES or not vrole:
                    if _should_trace_family(fid):
                        excluded_variants.append(
                            {
                                "variant_name": self._name(vid) or None,
                                "variant_role": vrole or None,
                                "reason": "role_filtered" if vrole in NON_SELECTABLE_FAMILY_ROLES else "missing_role",
                            }
                        )
                    continue
                candidate_ids.append(vid)

            candidate_set = set(candidate_ids)
            terminal_ids: list[int] = []
            for vid in candidate_ids:
                has_candidate_descendant = any(
                    int(descendant_id) in candidate_set for descendant_id in nx.descendants(self.HR, vid)
                )
                if not has_candidate_descendant:
                    terminal_ids.append(vid)

            selectable_ids = terminal_ids or candidate_ids
            family_selectable_variant_cache[fid] = selectable_ids

            if _should_trace_family(fid):
                self._add_analysis_variable_event(
                    "family_stem_catalog",
                    family_id=fid,
                    family_name=self._name(fid),
                    eligible_variants=[
                        {
                            "variant_name": self._name(vid) or None,
                            "variant_role": self._role(vid) or None,
                            "terminal": vid in set(terminal_ids),
                        }
                        for vid in selectable_ids
                    ],
                    excluded_variants=excluded_variants,
                    raw_variant_names=[self._name(vid) or None for vid in raw_variant_ids],
                )

            return selectable_ids

        def _family_relative_stem(node_id: int | None, family_root_id: int | None) -> str:
            if node_id is None or family_root_id is None:
                return ""
            try:
                nid = int(node_id)
                fid = int(family_root_id)
            except Exception:
                return ""

            stems = family_stem_cache.get(fid)
            if stems is None:
                variant_ids = _family_selectable_variant_ids(fid)
                variant_names = [self._name(vid) for vid in variant_ids if self._name(vid)]
                prefix = _longest_common_prefix(variant_names)
                stems = {}
                for vid in variant_ids:
                    vname = self._name(vid)
                    if not vname:
                        continue
                    stems[vid] = vname[len(prefix) :] if prefix and len(prefix) < len(vname) else vname
                family_stem_cache[fid] = stems
                if _should_trace_family(fid):
                    self._add_analysis_variable_event(
                        "family_stem_values",
                        family_id=fid,
                        family_name=self._name(fid),
                        stems={
                            self._name(vid) or str(vid): stem or None
                            for vid, stem in stems.items()
                        },
                    )

            return stems.get(nid, "")

        def _context_key(family_id: int | None) -> int | None:
            if family_id is None:
                return None
            try:
                return int(family_id)
            except Exception:
                return None

        def _remember_ptr(ptr: dict | None) -> None:
            if isinstance(ptr, dict):
                inline_ptr_registry[id(ptr)] = ptr

        def _get_resolution_context(ptr: dict | None) -> dict[int, str]:
            if not isinstance(ptr, dict):
                return {}
            _remember_ptr(ptr)
            return resolution_contexts.setdefault(id(ptr), {})

        def _record_resolution_choice(ptr: dict | None, family_id: int | None, variant_name: str | None) -> None:
            key = _context_key(family_id)
            if key is None or not variant_name or not isinstance(ptr, dict):
                return
            _get_resolution_context(ptr)[key] = str(variant_name)
            if _should_trace_family(key):
                self._add_analysis_variable_event(
                    "context_choice_recorded",
                    ptr_object_id=_ptr_name(ptr) or None,
                    ptr_object_type=(ptr.get("$objectType") or "").strip() or None,
                    chosen_variant=str(variant_name),
                )

        def _inherit_resolution_context(dst_ptr: dict | None, src_ptr: dict | None) -> None:
            if not isinstance(dst_ptr, dict) or not isinstance(src_ptr, dict):
                return
            _remember_ptr(dst_ptr)
            _remember_ptr(src_ptr)
            src = resolution_contexts.get(id(src_ptr))
            if not isinstance(src, dict) or not src:
                return
            dst = _get_resolution_context(dst_ptr)
            for fam_key, variant_name in src.items():
                dst.setdefault(int(fam_key), str(variant_name))

        def _remember_inline_parent(child_ptr: dict | None, parent_ptr: dict | None) -> None:
            if not isinstance(child_ptr, dict) or not isinstance(parent_ptr, dict):
                return
            child_ident = id(child_ptr)
            parent_ident = id(parent_ptr)
            if child_ident == parent_ident:
                return
            _remember_ptr(child_ptr)
            _remember_ptr(parent_ptr)
            parents = inline_parent_ptr_ids.setdefault(child_ident, [])
            if parent_ident not in parents:
                parents.append(parent_ident)

        def _iter_context_ptrs(ptr: dict | None):
            if not isinstance(ptr, dict):
                return
            stack = [id(ptr)]
            seen_ids: set[int] = set()
            while stack:
                cur_ident = stack.pop()
                if cur_ident in seen_ids:
                    continue
                seen_ids.add(cur_ident)
                cur_ptr = inline_ptr_registry.get(cur_ident)
                if isinstance(cur_ptr, dict):
                    yield cur_ptr
                for parent_ident in inline_parent_ptr_ids.get(cur_ident, []):
                    if parent_ident not in seen_ids:
                        stack.append(parent_ident)

        def _register_inline_owner(
            target_id: int,
            ptr: dict,
            *,
            source_ptr: dict | None = None,
            family_id: int | None = None,
            variant_name: str | None = None,
        ) -> bool:
            if not isinstance(ptr, dict):
                return False
            if ptr.get("$objectType") != "object":
                return False

            _remember_ptr(ptr)
            _remember_inline_parent(ptr, source_ptr)
            _inherit_resolution_context(ptr, source_ptr)
            _record_resolution_choice(ptr, family_id, variant_name)

            alias_ids: list[int] = [int(target_id)]
            try:
                for parent_id in self.H.successors(int(target_id)):
                    alias_ids.append(int(parent_id))
            except Exception:
                pass

            ptr_ident = id(ptr)
            changed = False
            for alias_id in alias_ids:
                alias_key = int(alias_id)
                seen_ids = inline_owner_ptr_ids.setdefault(alias_key, set())
                if ptr_ident in seen_ids:
                    continue
                seen_ids.add(ptr_ident)
                bucket = inline_owner_ptrs.setdefault(alias_key, [])
                bucket.append(ptr)
                changed = True
            return changed

        def _register_inline_targets_from_schema(
            target_id: int,
            schema: dict | None,
            *,
            source_ptr: dict | None = None,
            family_id: int | None = None,
            variant_name: str | None = None,
        ) -> bool:
            if not isinstance(schema, dict):
                return False

            def _schema_node_id(node: dict, fallback_id: int) -> int:
                obj_id = (node.get("$objectId") or "").strip()
                node_id = name_to_id.get(obj_id)
                try:
                    return int(node_id) if node_id is not None else int(fallback_id)
                except Exception:
                    return int(fallback_id)

            changed = False
            seen_walk: set[int] = set()
            root_ident = id(schema)

            def _walk(node: Any, inherited_ptr: dict | None) -> None:
                nonlocal changed
                if not isinstance(node, dict):
                    return
                node_ident = id(node)
                if node_ident in seen_walk:
                    return
                seen_walk.add(node_ident)

                next_inherited_ptr = inherited_ptr
                should_descend = (node_ident == root_ident)

                if node.get("$objectType") == "object":
                    node_target_id = _schema_node_id(node, target_id)
                    newly_registered = _register_inline_owner(
                        node_target_id,
                        node,
                        source_ptr=inherited_ptr,
                        family_id=family_id,
                        variant_name=variant_name,
                    )
                    changed |= newly_registered
                    next_inherited_ptr = node

                    if node_ident not in inline_registration_seen_nodes:
                        inline_registration_seen_nodes.add(node_ident)
                        should_descend = True
                    elif newly_registered:
                        should_descend = True

                if not should_descend:
                    return

                items = node.get("items")
                if isinstance(items, dict):
                    _walk(items, next_inherited_ptr)

                anyof = node.get("anyOf")
                if isinstance(anyof, list):
                    for ent in anyof:
                        if isinstance(ent, dict):
                            _walk(ent, next_inherited_ptr)

                props = node.get("properties")
                if isinstance(props, dict):
                    for child in props.values():
                        if isinstance(child, dict):
                            _walk(child, next_inherited_ptr)

            _walk(schema, source_ptr)
            return changed

        def _owner_targets(owner_id: int) -> list[dict]:
            owner_id = int(owner_id)
            out: list[dict] = []
            seen_ptr: set[int] = set()

            ptr = self.def_ptr.get(owner_id)
            if isinstance(ptr, dict):
                out.append(ptr)
                seen_ptr.add(id(ptr))

            for ptr in inline_owner_ptrs.get(owner_id, []):
                if not isinstance(ptr, dict):
                    continue
                pid = id(ptr)
                if pid in seen_ptr:
                    continue
                seen_ptr.add(pid)
                out.append(ptr)

            member_name = (self._name(owner_id) or "").strip()
            if member_name:
                for member_lookup in getattr(self, "_object_anyof_member_ptrs", {}).values():
                    if not isinstance(member_lookup, dict):
                        continue
                    ptr = member_lookup.get(member_name)
                    if not isinstance(ptr, dict):
                        continue
                    pid = id(ptr)
                    if pid in seen_ptr:
                        continue
                    seen_ptr.add(pid)
                    out.append(ptr)

            return out

        def _family_schema_leaf(schema: dict | None) -> dict | None:
            if not isinstance(schema, dict):
                return None
            if schema.get("type") == "array":
                items = schema.get("items")
                return items if isinstance(items, dict) else None
            return schema

        def _family_concrete_object_id(schema: dict | None) -> str:
            leaf = _family_schema_leaf(schema)
            if not isinstance(leaf, dict):
                return ""
            if leaf.get("$objectType") != "object":
                return ""
            if isinstance(leaf.get("anyOf"), list):
                return ""
            return (leaf.get("$objectId") or "").strip()

        def _is_unresolved_family_wrapper(schema: dict | None) -> bool:
            leaf = _family_schema_leaf(schema)
            if not isinstance(leaf, dict):
                return False
            if leaf.get("$objectType") != "object":
                return False
            return isinstance(leaf.get("anyOf"), list)

        def _upsert_assoc_property(
            parent_obj: dict,
            key: str,
            prop: dict,
            *,
            family_id: int | None = None,
            chosen_variant_name: str | None = None,
        ) -> tuple[bool, dict | None]:
            props = parent_obj.setdefault("properties", {})
            existing = props.get(key)
            family_key = _context_key(family_id)

            if existing is None:
                props[key] = prop
                return True, props[key]

            if family_key is not None:
                existing_oid = _family_concrete_object_id(existing if isinstance(existing, dict) else None)
                incoming_oid = _family_concrete_object_id(prop)
                existing_is_wrapper = _is_unresolved_family_wrapper(existing if isinstance(existing, dict) else None)
                incoming_is_wrapper = _is_unresolved_family_wrapper(prop)

                if existing_is_wrapper and incoming_oid:
                    props[key] = prop
                    if _should_trace_family(family_key):
                        self._add_analysis_variable_event(
                            "assoc_property_replaced_wrapper",
                            parent_object_id=_ptr_name(parent_obj) or None,
                            property_key=key,
                            chosen_name=chosen_variant_name or incoming_oid,
                            existing_schema=_schema_summary(existing if isinstance(existing, dict) else None),
                            incoming_schema=_schema_summary(prop),
                        )
                    return True, props[key]

                if existing_oid and incoming_is_wrapper:
                    if _should_trace_family(family_key):
                        self._add_analysis_variable_event(
                            "assoc_property_preserved_concrete",
                            parent_object_id=_ptr_name(parent_obj) or None,
                            property_key=key,
                            chosen_name=existing_oid,
                            existing_schema=_schema_summary(existing if isinstance(existing, dict) else None),
                            incoming_schema=_schema_summary(prop),
                        )
                    return False, existing if isinstance(existing, dict) else None

            merged = self._merge_schema(existing, prop)
            if merged != existing:
                props[key] = merged
                return True, props[key]

            return False, existing if isinstance(existing, dict) else None

        def descendant_object_targets(base_id: int) -> list[dict]:
            base_id = int(base_id)
            out: list[dict] = []
            seen_nodes: set[int] = {base_id}
            seen_ptr: set[int] = set()
            q2 = deque([base_id])

            # H is child -> parent, so descendants are predecessors
            while q2:
                cur2 = q2.popleft()
                for child2 in self.H.predecessors(cur2):
                    try:
                        cid2 = int(child2)
                    except Exception:
                        continue
                    if cid2 in seen_nodes:
                        continue
                    seen_nodes.add(cid2)
                    q2.append(cid2)

                    for ptr2 in _owner_targets(cid2):
                        if not isinstance(ptr2, dict):
                            continue
                        if ptr2.get("$objectType") != "object":
                            continue
                        pid = id(ptr2)
                        if pid in seen_ptr:
                            continue
                        seen_ptr.add(pid)
                        out.append(ptr2)
            return out

        def _resolve_variant_name_for_recipient(
            recipient_ptr: dict | None,
            variant_schemas: dict[str, dict] | None,
            family_id: int | None,
        ) -> str | None:
            if not isinstance(variant_schemas, dict) or not variant_schemas:
                return None

            fam_key = _context_key(family_id)
            recipient_name = _ptr_name(recipient_ptr)
            recipient_id = name_to_id.get(recipient_name) if recipient_name else None
            recipient_role = self._role(recipient_id) if recipient_id is not None else ""
            variant_keys = sorted(str(k) for k in variant_schemas.keys())
            context_hits: list[dict[str, Any]] = []

            if fam_key is not None and isinstance(recipient_ptr, dict):
                for ctx_ptr in _iter_context_ptrs(recipient_ptr):
                    ctx = resolution_contexts.get(id(ctx_ptr))
                    chosen_name = ctx.get(fam_key) if isinstance(ctx, dict) else None
                    if _should_trace_family(fam_key) and chosen_name:
                        context_hits.append(
                            {
                                "context_object_id": _ptr_name(ctx_ptr) or None,
                                "choice": str(chosen_name),
                            }
                        )
                    if chosen_name in variant_schemas:
                        if _should_trace_family(fam_key):
                            self._add_analysis_variable_event(
                                "resolve_variant_name",
                                recipient_object_id=recipient_name or None,
                                recipient_role=recipient_role or None,
                                family_id=int(fam_key),
                                family_name=self._name(fam_key),
                                variant_keys=variant_keys,
                                context_hits=context_hits,
                                chosen_name=str(chosen_name),
                                reason="context",
                            )
                        return str(chosen_name)

            if recipient_name in variant_schemas:
                if _should_trace_family(fam_key):
                    self._add_analysis_variable_event(
                        "resolve_variant_name",
                        recipient_object_id=recipient_name or None,
                        recipient_role=recipient_role or None,
                        family_id=int(fam_key),
                        family_name=self._name(fam_key),
                        variant_keys=variant_keys,
                        context_hits=context_hits,
                        chosen_name=recipient_name,
                        reason="direct_object_id",
                    )
                return recipient_name

            if recipient_id is not None and fam_key is not None:
                recipient_parent_ids: list[int] = []
                try:
                    recipient_parent_ids = [int(parent_id) for parent_id in self.H.successors(int(recipient_id))]
                except Exception:
                    recipient_parent_ids = []

                for recipient_family_id in recipient_parent_ids:
                    recipient_stem = _family_relative_stem(recipient_id, recipient_family_id)
                    if not recipient_stem:
                        continue

                    matches: list[str] = []
                    candidate_stems: dict[str, str | None] = {}
                    for candidate_name in variant_schemas:
                        candidate_id = name_to_id.get(candidate_name)
                        candidate_stem = _family_relative_stem(candidate_id, fam_key)
                        if _should_trace_family(fam_key):
                            candidate_stems[str(candidate_name)] = candidate_stem or None
                        if candidate_stem and candidate_stem == recipient_stem:
                            matches.append(candidate_name)

                    if len(matches) == 1:
                        if _should_trace_family(fam_key):
                            self._add_analysis_variable_event(
                                "resolve_variant_name",
                                recipient_object_id=recipient_name or None,
                                recipient_role=recipient_role or None,
                                family_id=int(fam_key),
                                family_name=self._name(fam_key),
                                variant_keys=variant_keys,
                                context_hits=context_hits,
                                recipient_family=self._name(recipient_family_id),
                                recipient_stem=recipient_stem,
                                candidate_stems=candidate_stems,
                                chosen_name=matches[0],
                                reason="family_stem",
                            )
                        return matches[0]
                    if _should_trace_family(fam_key):
                        self._add_analysis_variable_event(
                            "family_stem_attempt",
                            recipient_object_id=recipient_name or None,
                            recipient_role=recipient_role or None,
                            family_id=int(fam_key),
                            family_name=self._name(fam_key),
                            recipient_family=self._name(recipient_family_id),
                            recipient_stem=recipient_stem or None,
                            candidate_stems=candidate_stems,
                            matches=matches,
                        )

            chosen_schema = _resolve_variant_schema_for_owner(recipient_name, variant_schemas)
            if not isinstance(chosen_schema, dict):
                if _should_trace_family(fam_key):
                    recipient_parent_names = []
                    if recipient_id is not None:
                        try:
                            recipient_parent_names = [self._name(int(parent_id)) for parent_id in self.H.successors(int(recipient_id))]
                        except Exception:
                            recipient_parent_names = []
                    self._add_analysis_variable_event(
                        "resolve_variant_name",
                        recipient_object_id=recipient_name or None,
                        recipient_role=recipient_role or None,
                        family_id=int(fam_key),
                        family_name=self._name(fam_key),
                        family_role=self._role(fam_key),
                        variant_keys=variant_keys,
                        context_hits=context_hits,
                        recipient_parents=recipient_parent_names,
                        operations_variable_family=(
                            self._name(operations_variable_family_id) if operations_variable_family_id is not None else None
                        ),
                        chosen_name=None,
                        reason="no_match",
                    )
                return None
            for candidate_name, candidate_schema in variant_schemas.items():
                if candidate_schema is chosen_schema or candidate_schema == chosen_schema:
                    if _should_trace_family(fam_key):
                        self._add_analysis_variable_event(
                            "resolve_variant_name",
                            recipient_object_id=recipient_name or None,
                            recipient_role=recipient_role or None,
                            family_id=int(fam_key),
                            family_name=self._name(fam_key),
                            variant_keys=variant_keys,
                            context_hits=context_hits,
                            chosen_name=str(candidate_name),
                            reason="owner_schema_match",
                        )
                    return str(candidate_name)
            return None

        def _schema_for_recipient(
            recipient_ptr: dict,
            default_schema: dict | None,
            variant_schemas: dict[str, dict] | None,
            family_id: int | None,
        ) -> tuple[dict | None, str | None]:
            chosen_name = _resolve_variant_name_for_recipient(recipient_ptr, variant_schemas, family_id)
            if chosen_name and isinstance(variant_schemas, dict):
                chosen = variant_schemas.get(chosen_name)
                if isinstance(chosen, dict):
                    if _should_trace_family(family_id):
                        self._add_analysis_variable_event(
                            "schema_for_recipient",
                            recipient_object_id=_ptr_name(recipient_ptr) or None,
                            family_id=int(_context_key(family_id)),
                            family_name=self._name(int(_context_key(family_id))),
                            chosen_name=chosen_name,
                            used_default=False,
                            chosen_schema=_schema_summary(chosen),
                        )
                    return chosen, chosen_name
            if isinstance(default_schema, dict):
                if _should_trace_family(family_id):
                    self._add_analysis_variable_event(
                        "schema_fallback_to_default",
                        recipient_object_id=_ptr_name(recipient_ptr) or None,
                        family_id=int(_context_key(family_id)),
                        family_name=self._name(int(_context_key(family_id))),
                        default_schema=_schema_summary(default_schema),
                        variant_keys=sorted(str(k) for k in (variant_schemas or {}).keys()),
                    )
                    self._add_analysis_variable_event(
                        "schema_for_recipient",
                        recipient_object_id=_ptr_name(recipient_ptr) or None,
                        family_id=int(_context_key(family_id)),
                        family_name=self._name(int(_context_key(family_id))),
                        chosen_name=None,
                        used_default=True,
                        default_schema=_schema_summary(default_schema),
                        variant_keys=sorted(str(k) for k in (variant_schemas or {}).keys()),
                    )
                return default_schema, None
            return None, None

        # Associations can reveal new inline owners that themselves own more
        # associations. Iterate to a fixpoint so nested inline stubs (for example
        # PowerTransformer -> TransformerTank -> TransformerTankEnd) are fully
        # populated even when the input edge order is unfavorable.
        max_passes = 4
        for _assoc_pass in range(max_passes):
            pass_changed = False
            seen_props: set[tuple[int, str, str]] = set()

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

                owner_targets = _owner_targets(owner_id)
                if not owner_targets:
                    continue  # owner not emitted/defined anywhere

                ref_schema = make_polymorphic_ref_schema(target_id, owner_id=owner_id)
                if not isinstance(ref_schema, dict):
                    continue

                mult = _normalize_mult(data.get("end_mult"))
                if not mult and _is_self_or_descendant(owner_id, analysis_result_family_id) and _is_self_or_descendant(
                    target_id, analysis_result_data_family_id
                ):
                    mult = "0..*"
                is_single = (mult == "" or mult == "0..1")

                variant_prop_schemas: dict[str, dict] | None = None
                prop_schema: dict | None
                context_family_id = ref_schema.get("__contextFamilyId__") if isinstance(ref_schema, dict) else None

                if "__variantSchemas__" in ref_schema:
                    variant_prop_schemas = {}
                    for vname, vschema in (ref_schema.get("__variantSchemas__") or {}).items():
                        if not isinstance(vschema, dict):
                            continue
                        pschema = copy.deepcopy(vschema) if is_single else {"type": "array", "items": copy.deepcopy(vschema)}
                        pschema.pop("$primaryObjectHash", None)
                        pschema.pop("$secondaryObjectHash", None)
                        if isinstance(pschema.get("items"), dict):
                            pschema["items"].pop("$primaryObjectHash", None)
                            pschema["items"].pop("$secondaryObjectHash", None)
                        variant_prop_schemas[str(vname)] = pschema

                    default_schema = ref_schema.get("__defaultSchema__")
                    if isinstance(default_schema, dict):
                        prop_schema = copy.deepcopy(default_schema) if is_single else {"type": "array", "items": copy.deepcopy(default_schema)}
                        prop_schema.pop("$primaryObjectHash", None)
                        prop_schema.pop("$secondaryObjectHash", None)
                        if isinstance(prop_schema.get("items"), dict):
                            prop_schema["items"].pop("$primaryObjectHash", None)
                            prop_schema["items"].pop("$secondaryObjectHash", None)
                    else:
                        prop_schema = None
                else:
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

                for owner_ptr in owner_targets:
                    is_container_owner = (
                        (isinstance(owner_ptr, dict) and owner_ptr.get("$objectType") == "container")
                        or (self._role(owner_id).strip() == "containerClass")
                    )

                    if is_container_owner:
                        targets = descendant_object_targets(owner_id)
                        if targets:
                            for tptr in targets:
                                chosen_schema, chosen_variant_name = _schema_for_recipient(tptr, prop_schema, variant_prop_schemas, context_family_id)
                                if not isinstance(chosen_schema, dict):
                                    continue
                                _record_resolution_choice(tptr, context_family_id, chosen_variant_name)
                                changed, stored_schema = _upsert_assoc_property(
                                    tptr,
                                    prop_key,
                                    copy.deepcopy(chosen_schema),
                                    family_id=context_family_id,
                                    chosen_variant_name=chosen_variant_name,
                                )
                                pass_changed |= changed
                                pass_changed |= _register_inline_targets_from_schema(
                                    target_id,
                                    stored_schema,
                                    source_ptr=tptr,
                                    family_id=context_family_id,
                                    variant_name=chosen_variant_name,
                                )
                        # If no targets, we intentionally drop the association property rather
                        # than attaching it to the container.
                        continue

                    # HAND convention: if the owner is an object-anyOf wrapper (polymorphic rootClass),
                    # do NOT attach association-backed properties at the wrapper level. Instead,
                    # attach them to each anyOf member object.
                    if owner_id in getattr(self, "_object_anyof_nodes", set()) and owner_ptr is self.def_ptr.get(owner_id):
                        anyof_list = owner_ptr.get("anyOf", [])
                        if isinstance(anyof_list, list):
                            for variant in anyof_list:
                                if not isinstance(variant, dict):
                                    continue
                                chosen_schema, chosen_variant_name = _schema_for_recipient(variant, prop_schema, variant_prop_schemas, context_family_id)
                                if not isinstance(chosen_schema, dict):
                                    continue
                                _record_resolution_choice(variant, context_family_id, chosen_variant_name)
                                changed, stored_schema = _upsert_assoc_property(
                                    variant,
                                    prop_key,
                                    copy.deepcopy(chosen_schema),
                                    family_id=context_family_id,
                                    chosen_variant_name=chosen_variant_name,
                                )
                                pass_changed |= changed
                                pass_changed |= _register_inline_targets_from_schema(
                                    target_id,
                                    stored_schema,
                                    source_ptr=variant,
                                    family_id=context_family_id,
                                    variant_name=chosen_variant_name,
                                )
                        continue

                    # Default: add to owner
                    chosen_for_owner, chosen_variant_name = _schema_for_recipient(owner_ptr, prop_schema, variant_prop_schemas, context_family_id)
                    if isinstance(chosen_for_owner, dict):
                        _record_resolution_choice(owner_ptr, context_family_id, chosen_variant_name)
                        changed, stored_schema = _upsert_assoc_property(
                            owner_ptr,
                            prop_key,
                            copy.deepcopy(chosen_for_owner),
                            family_id=context_family_id,
                            chosen_variant_name=chosen_variant_name,
                        )
                        pass_changed |= changed
                        pass_changed |= _register_inline_targets_from_schema(
                            target_id,
                            stored_schema,
                            source_ptr=owner_ptr,
                            family_id=context_family_id,
                            variant_name=chosen_variant_name,
                        )

                    # Also duplicate into each anyOf variant of the owner (if present)
                    anyof_list = owner_ptr.get("anyOf", [])
                    if isinstance(anyof_list, list):
                        for variant in anyof_list:
                            if not isinstance(variant, dict):
                                continue
                            chosen_schema, chosen_variant_name = _schema_for_recipient(variant, prop_schema, variant_prop_schemas, context_family_id)
                            if not isinstance(chosen_schema, dict):
                                continue
                            _record_resolution_choice(variant, context_family_id, chosen_variant_name)
                            changed, stored_schema = _upsert_assoc_property(
                                variant,
                                prop_key,
                                copy.deepcopy(chosen_schema),
                                family_id=context_family_id,
                                chosen_variant_name=chosen_variant_name,
                            )
                            pass_changed |= changed
                            pass_changed |= _register_inline_targets_from_schema(
                                target_id,
                                stored_schema,
                                source_ptr=variant,
                                family_id=context_family_id,
                                variant_name=chosen_variant_name,
                            )

                    # Apply inherited associations to emitted descendant owners too.
                    for descendant_ptr in descendant_object_targets(owner_id):
                        chosen_schema, chosen_variant_name = _schema_for_recipient(descendant_ptr, prop_schema, variant_prop_schemas, context_family_id)
                        if not isinstance(chosen_schema, dict):
                            continue
                        _record_resolution_choice(descendant_ptr, context_family_id, chosen_variant_name)
                        changed, stored_schema = _upsert_assoc_property(
                            descendant_ptr,
                            prop_key,
                            copy.deepcopy(chosen_schema),
                            family_id=context_family_id,
                            chosen_variant_name=chosen_variant_name,
                        )
                        pass_changed |= changed
                        pass_changed |= _register_inline_targets_from_schema(
                            target_id,
                            stored_schema,
                            source_ptr=descendant_ptr,
                            family_id=context_family_id,
                            variant_name=chosen_variant_name,
                        )

            if not pass_changed:
                break


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

        # Fallback for â€œplain dictsâ€ (e.g., properties-maps): still force trailing keys last if present
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
        3) Cross-references are emitted when an encountered nodeâ€™s owner â‰  the current node.
        4) Top-level keys ordered to match the hand template first, then Aâ€“Z.
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
        self._object_anyof_member_ptrs = {}
        self._object_anyof_member_owner = {}
        self._inline_owner_ptrs = {}

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
                    self._object_anyof_member_ptrs[n] = {
                        (member.get("$objectId") or "").strip(): member
                        for member in variants
                        if isinstance(member, dict) and (member.get("$objectId") or "").strip()
                    }
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

        def bind_anyof_member(wrapper_id: int, member_id: int, *, wrapper_path: tuple | None = None) -> bool:
            wrapper_id = int(wrapper_id)
            member_id = int(member_id)
            member_name = name(member_id)
            wrapper_ptr = self.def_ptr.get(wrapper_id)
            if not isinstance(wrapper_ptr, dict):
                return False

            member_lookup = getattr(self, "_object_anyof_member_ptrs", {}).get(wrapper_id, {})
            member_ptr = member_lookup.get(member_name)
            if not isinstance(member_ptr, dict):
                anyof_list = wrapper_ptr.get("anyOf", [])
                if isinstance(anyof_list, list):
                    for candidate in anyof_list:
                        if not isinstance(candidate, dict):
                            continue
                        if candidate.get("$objectType") != "object":
                            continue
                        if (candidate.get("$objectId") or "").strip() == member_name:
                            member_ptr = candidate
                            break
            if not isinstance(member_ptr, dict):
                return False

            self.def_ptr[member_id] = member_ptr
            if isinstance(wrapper_path, tuple):
                self.path_map[member_id] = wrapper_path + (member_name,)
            self._object_anyof_member_owner[member_id] = wrapper_id
            return True

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
                if self.debug:
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
                        if self.debug:
                            print(
                                f"[AUTO][anchor] -> using base owner for {a_name}: "
                                f"{base} ({name(base)})"
                            )
                    except Exception:
                        pass
                    return base

            # Fallback: Root owns the anchor
            try:
                if self.debug:
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

            variants = self._collect_polymorphic_variants(int(target))
            if len(variants) >= 2:
                items = [self._make_ref(v) for v in variants]
                items = [x for x in items if isinstance(x, dict)]
                if items:
                    self._add_property(
                        at_ptr,
                        self._name(target),
                        {
                            "$objectType": "reference",
                            "$objectId": self._name(target),
                            "anyOf": items,
                        },
                    )
                return

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
                if self.debug:
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
                    # if cur wasnâ€™t defined yet (shouldnâ€™t happen for anchors), skip
                    continue


                # Ensure every defined node also has a usable path. This is critical when
                # we bind HR child nodes to inline anyOf-member dicts (substitution unions):
                # those members are not created via ensure_defined(), so without a path_map
                # entry, later calls that use force_owner=<cur> will fail.
                if isinstance(owner_path, tuple) and cur not in self.path_map:
                    self.path_map[cur] = owner_path

                # Donâ€™t add named children to an object that is represented as anyOf
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
                        bind_anyof_member(cur, child, wrapper_path=owner_path)
                        if rchild != "inheritOnlyClass":
                            q.append((child, self.path_map.get(child, owner_path + (cname,))))
                        continue

                    wrapper_owner = getattr(self, "_object_anyof_member_owner", {}).get(int(cur))
                    if wrapper_owner is not None and bind_anyof_member(
                        wrapper_owner,
                        child,
                        wrapper_path=self.path_map.get(wrapper_owner, owner_path),
                    ):
                        if rchild != "inheritOnlyClass":
                            q.append((child, self.path_map.get(child, owner_path + (cname,))))
                        continue


                    # Determine whether this child should be treated as a container â€œshelfâ€
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

                    # If the current node is an object-anyOf wrapper, donâ€™t add named props
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

    def _order_props_like_hand(self, props: dict) -> dict:
        if not isinstance(props, dict):
            return props
        return {k: props[k] for k in sorted(props, key=str.casefold)}

