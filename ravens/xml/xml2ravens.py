import re
import warnings

from ast import literal_eval
from collections import namedtuple
from copy import deepcopy

from rdflib import Graph
from rdflib.term import URIRef, Literal


Reference = namedtuple("Reference", ["parent", "id"])

# TODO: Pick better prune keys
prune_keys = ["IdentifiedObject.name", "IdentifiedObject.mRID", r"(.+)\.sequenceNumber"]


class PathSegment:
    def __init__(self, position, json_type):
        self.position = position
        self.type = json_type

    def __str__(self):
        return "PathSegment(" + ", ".join([str(i) for i in [self.position, self.type]]) + ")"

    def __repr__(self):
        return self.__str__()


class Path:
    def __init__(self):
        self.path = {}

    def add(self, path_segment):
        self.path[len(self.path)] = path_segment

    def insert(self, path_segment):
        self.path = {**{0: path_segment}, **{k + 1: v for k, v in self.path.items()}}

    def __getitem__(self, i):
        if i < 0:
            return self.path[len(self.path) + i]

        return self.path[i]

    def __iter__(self):
        return iter([self.path[i] for i in range(len(self.path))])

    def __str__(self):
        return "Path(\n\t" + "\n\t".join([str(v) for v in self.path.values()]) + "\n)"

    def __repr__(self):
        return self.__str__()

    def __bool__(self):
        return len(self.path) > 0


class MultiPath:
    def __init__(self):
        self.paths = []

    def add(self, path):
        self.paths.append(path)

    def create(self):
        self.paths.append(Path())
        return len(self.paths) - 1

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        return self.paths[i]

    def __setitem__(self, i, v):
        self.paths[i] = v

    def __str__(self):
        return "MultiPath(\n\t" + "\n\t".join([", ".join([str(i) for i in self.paths])]) + "\n)"

    def __repr__(self):
        return self.__str__()

    def __iter__(self):
        return iter(self.paths)


class ResolvedPathSegment:
    def __init__(self, position, json_type, uri, index):
        self.position = position
        self.type = json_type
        self.uri = uri
        self.index = index

    @property
    def idx(self):
        if isinstance(self.position, int):
            return self.position - 1
        else:
            return self.position

    def __str__(self):
        return "ResolvedPathSegment(" + ", ".join([str(i) for i in [self.position, self.type, self.uri, self.index]]) + ")"

    def __repr__(self):
        return self.__str__()


class ResolvedPath:
    def __init__(self):
        self.path = {}

    def add(self, resolved_path_segment):
        self.path[len(self.path)] = resolved_path_segment

    def __getitem__(self, i):
        if i < 0:
            return self.path[len(self.path) + i]

        return self.path[i]

    def __setitem__(self, i, v):
        if i < 0:
            self.path[len(self.path) + i] = v

        self.path[i] = v

    def __iter__(self):
        return iter([self.path[i] for i in range(len(self.path))])

    def __str__(self):
        return "ResolvedPath(\n\t" + "\n\t".join([str(v) for v in self.path.values()]) + "\n)"

    def __repr__(self):
        return self.__str__()


class MultiResolvedPath:
    def __init__(self):
        self.paths = {}

    def add(self, path):
        self.paths[len(self.paths)] = path

    def create(self):
        self.paths[len(self.paths)] = ResolvedPath()

        return len(self.paths) - 1

    def update(self, path_id, path_segment):
        self.paths[path_id].add(path_segment)

    def keys(self):
        return self.paths.keys()

    def __getitem__(self, i):
        if i < 0:
            return self.paths[len(self.paths) + i]

        return self.paths[i]

    def __str__(self):
        return "MultiResolvedPath(\n\t" + "\n\t".join([", ".join([str(i) for i in self.paths])]) + "\n)"

    def __repr__(self):
        return self.__str__()

    def __iter__(self):
        return iter(self.paths)


class RAVENSData:
    def __init__(self, rdf_graph, template, prune_unncessary=False):
        self.cim_ns = "http://iec.ch/TC57/CIM100"
        self.rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
        self.prune_unncessary = prune_unncessary

        self.untokenized_paths = []
        self.reference_paths = {}
        self.build_paths_from_template(template)

        self.tokenized_paths = {}
        self.tokenize_paths()

        self.rdf = rdf_graph

        self.unique_subject_types = {s: o.split("#")[-1] for s, o in self.rdf.subject_objects(predicate=self.rdf_type)}
        self.paths = {s: [] for s, t in self.unique_subject_types.items()}

        self.build_actual_paths()

        self.data = {}
        self.resolved_path = None
        self.current_resolved_path = None
        self.current_path_index = 0
        self.current_path_id = 0

        self.convert_rdf()

    def build_paths_from_template(self, template, current_path=None):
        if current_path is None:
            current_path = []

        for obj_id, obj in template.get("properties", {}).items():
            try:
                if obj["type"] == "array":
                    self.parse_array(obj_id, obj, current_path=current_path)
                elif obj["type"] == "object":
                    if obj.get("$objectType", None) == "container":
                        _path_info = {"path": obj_id, "id": obj_id, "type": "container", "position": None}
                        self.build_paths_from_template(obj, current_path=current_path + [_path_info])
                    elif obj.get("$objectType", None) == "object":
                        if "oneOf" in obj:
                            for i, item in enumerate(obj["oneOf"]):
                                self.parse_object(obj_id, item.get("$objectId", obj_id), item, current_path)
                        else:
                            self.parse_object(obj_id, obj.get("$objectId", obj_id), obj, current_path)
                    elif obj.get("$objectType", None) == "reference":
                        # nothing to do
                        pass
                    else:
                        raise Exception(f"unrecognized objectType for '{obj_id}': '{obj.get('$objectType', None)}'")
                elif obj["type"] == "string" and obj["$objectType"] == "reference":
                    if obj_id not in self.reference_paths:
                        self.reference_paths[obj_id] = set()

                    if "oneOf" in obj:
                        for item in obj["oneOf"]:
                            _ref = Reference(current_path[-1]["id"], item["$referencePath"].split("/")[-1])
                            self.reference_paths[obj_id].add(_ref)
                    else:
                        _ref = Reference(current_path[-1]["id"], obj["$referencePath"].split("/")[-1])
                        self.reference_paths[obj_id].add(_ref)
                else:
                    # is a primative json type, nothing to do
                    pass
            except Exception as msg:
                raise Exception(f"error on object '{obj_id}': {msg}")

    def parse_object(self, object_path, object_id, obj, current_path, json_type="object", position_key="$primaryObjectHash", position_value=None):
        _path_info = {
            "path": object_path,
            "id": object_id,
            "type": json_type,
            "position": obj.get(position_key, None) if position_key is not None else position_value,
        }

        if obj.get("$objectId", None) is not None:
            self.untokenized_paths.append((obj["$objectId"], current_path + [_path_info]))
        else:
            self.untokenized_paths.append((object_path, current_path + [_path_info]))

        self.build_paths_from_template(obj, current_path=current_path + [_path_info])

    def parse_array(self, obj_id, obj, current_path):
        if obj.get("items", None) is not None:
            if obj["items"]["type"] == "object":
                if "oneOf" in obj["items"]:
                    for i, item in enumerate(obj["items"]["oneOf"]):
                        self.parse_object(
                            obj_id,
                            item.get("$objectId", obj_id),
                            item,
                            current_path=current_path,
                            json_type="array",
                            position_key=None,
                            position_value=obj["items"].get("$arrayPosition", None),
                        )
                else:
                    self.parse_object(
                        obj_id,
                        obj["items"].get("$objectId", obj_id),
                        obj["items"],
                        current_path=current_path,
                        json_type="array",
                        position_key="$arrayPosition",
                    )
            elif obj["items"]["type"] == "array":
                self.parse_array(obj["items"], current_path=current_path + [{"path": ""}])
            else:
                # Nothing to do
                pass
        else:
            raise Exception(f"missing 'items' from object '{obj_id}' of type array")

    def tokenize_paths(self):
        obj_list = [item[0] for item in self.untokenized_paths]

        multi_objs = {k for k in set(obj_list) if obj_list.count(k) > 1}

        multi_obj_parent = {k: {i: self.untokenized_paths[i][1] for i, x in enumerate(obj_list) if x == k} for k in multi_objs}

        for i in range(len(self.untokenized_paths)):
            t, path = self.untokenized_paths[i]
            if t not in self.tokenized_paths:
                if t in multi_obj_parent:
                    self.tokenized_paths[t] = {}
                    touched_objects = set()
                    for _path in multi_obj_parent[t].values():
                        for _p in _path[::-1]:
                            if _p["type"] in ["object", "array"] and _p["id"] != path[-1]["id"] and _p["id"] not in touched_objects:
                                self.tokenized_paths[t][_p["id"]] = deepcopy(_path)
                                touched_objects.add(_p["id"])
                                break
                else:
                    self.tokenized_paths[t] = deepcopy(path)

    def build_actual_paths(self):
        for subject, cim_type in self.unique_subject_types.items():
            if isinstance(self.tokenized_paths.get(cim_type, []), dict):
                self.paths[subject] = MultiPath()
                count = 0
                ctypes = []
                for _o in [o for o in self.rdf.objects(subject=subject)] + [s for s in self.rdf.subjects(object=subject)]:
                    ctype = self.unique_subject_types.get(_o, None)
                    if ctype is not None and ctype in self.tokenized_paths[cim_type]:
                        ctypes.append(ctype)
                        count += 1
                else:
                    if count == 0:
                        warnings.warn(f"Connecting subject not found: {subject}::{cim_type}. This may mean the data is superfluous")
                        continue
                self.paths[subject] = self.find_path(subject, ctype=ctypes[0])
            else:
                self.paths[subject] = self.find_path(subject)

    def find_path(self, subject, ctype=None):
        obj_real_path = MultiPath()
        s2p = {subject: obj_real_path.create()}

        path_prospect = self.tokenized_paths.get(self.unique_subject_types[subject], [])
        if ctype is not None:
            path_prospect = path_prospect[ctype]

        _current_subjects = {subject: None}
        for segment in path_prospect[::-1]:
            _next_subjects = {}
            count = 0
            for _current_subject, _ in _current_subjects.items():
                if segment["id"] != self.unique_subject_types[subject]:
                    if not (segment["position"] is None and (segment["type"] != "array")):
                        for _o in [__o for __o in self.rdf.objects(subject=_current_subject)] + [__s for __s in self.rdf.subjects(object=_current_subject)]:
                            if self.rdf.value(subject=_o, predicate=self.rdf_type) == URIRef(f"{self.cim_ns}#{segment['id']}"):
                                count += 1
                                _next_subjects[_o] = _current_subject

            if count == 0:
                _next_subjects = {subject: subject}

            remove = set()
            for j, (_next_subject, _prev_subject) in enumerate(_next_subjects.items()):
                if j == 0:
                    s2p[_next_subject] = s2p[_prev_subject]
                elif _next_subject not in s2p:
                    s2p[_next_subject] = obj_real_path.create()
                    obj_real_path[s2p[_next_subject]] = deepcopy(obj_real_path[s2p[_prev_subject]])

                positions = self._build_positions(subject, _next_subject, segment)
                if len(positions) == 1 and isinstance(positions[0], URIRef):
                    remove.add(_next_subject)

                for position in positions[::-1]:
                    obj_real_path[s2p[_next_subject]].insert(position)

            for k in remove:
                _next_subjects.pop(k)

            if _next_subjects:
                _current_subjects = _next_subjects
            else:
                break

        if len(obj_real_path) == 1:
            obj_real_path = obj_real_path[0]

        return obj_real_path

    def _build_positions(self, subject, _current_subject, segment):
        positions = []
        if segment["type"] == "container" or (segment["type"] == "object" and segment["position"] is None):
            positions = [PathSegment(segment["path"], "object")]
        elif _current_subject != subject:
            positions = [_current_subject]
        else:
            _position = self.rdf.value(subject=_current_subject, predicate=URIRef(f"{self.cim_ns}#{segment['position']}"))
            positions = [
                PathSegment(segment["path"], segment["type"]),
                PathSegment(
                    str(_position) if (segment["type"] == "object") else (_position if _position is None else int(_position)),
                    segment["type"],
                ),
            ]

        return positions

    def convert_rdf(self):
        for subject in self.unique_subject_types.keys():
            data = self.build_data(subject)

            if self.paths.get(subject, Path()):
                self.resolve_path(subject)

                if isinstance(self.resolved_path, MultiResolvedPath):
                    for path_id in self.resolved_path.keys():
                        self.current_path_id = path_id
                        self.current_resolved_path = self.resolved_path[path_id]
                        self.add_to_data(self.data, data)
                        self.current_path_index = 0
                else:
                    self.current_resolved_path = self.resolved_path
                    self.add_to_data(self.data, data)
                    self.current_path_index = 0  # reset index

                self.resolved_path = None  # reset resolved path
                self.current_resolved_path = None
            else:
                warnings.warn(f"Path for subject not found: {str(subject)}::{self.unique_subject_types[subject]}")
                continue

    def build_data(self, subject):
        data = {"Ravens.CimObjectType": self.rdf.value(subject=subject, predicate=self.rdf_type).split("#")[-1]}
        for p, o in self.rdf.predicate_objects(subject=subject):
            pn = p.split("#")[-1]
            if self.prune_unncessary and any(bool(re.search(k, pn)) for k in prune_keys):
                continue

            if p != self.rdf_type:
                if isinstance(o, Literal):
                    try:
                        value = literal_eval(o.value)
                    except:
                        value = o.value
                elif pn in self.reference_paths:
                    if len(set(r.id for r in self.reference_paths[pn])) == 1:
                        ref = list(self.reference_paths[pn])[0]
                        try:
                            position = URIRef(f"{self.cim_ns}#{self.tokenized_paths[ref.id][-1]['position']}")
                            value = f"{ref.id}::'{self.rdf.value(subject=o, predicate=position)}'"
                        except KeyError:
                            continue
                    else:
                        ref = None
                        for _ref in self.reference_paths[pn]:
                            if self.rdf.value(subject=subject, predicate=self.rdf_type) == f"{self.cim_ns}#{_ref.parent}":
                                ref = _ref
                                break

                        if ref is not None:
                            position = URIRef(f"{self.cim_ns}#{self.tokenized_paths[ref.id][-1]['position']}")
                            value = f"{ref.id}::'{self.rdf.value(subject=o, predicate=position)}'"
                        else:
                            warnings.warn(f"Can't find reference for {o}::{self.unique_subject_types[o]} from {subject}::{self.unique_subject_types[subject]}")
                            continue
                elif isinstance(o, URIRef) and o.startswith(self.cim_ns):
                    value = o.split("#")[-1]
                elif self.prune_unncessary or isinstance(o, URIRef):
                    continue
                else:
                    value = o

                data[pn] = value

        for pn, items in self.reference_paths.items():
            for ref in items:
                if ref.parent == self.rdf.value(subject=subject, predicate=self.rdf_type).split("#")[-1] and pn not in data:
                    for o in self.rdf.objects(subject=subject):
                        _rdf_type = self.rdf.value(subject=o, predicate=self.rdf_type)
                        if _rdf_type is not None and _rdf_type.split("#")[-1] == ref.id:
                            position = URIRef(f"{self.cim_ns}#{self.tokenized_paths[ref.id][-1]['position']}")
                            data[pn] = f"{ref.id}::'{self.rdf.value(subject=o, predicate=position)}'"

        return data

    def resolve_path(self, subject, path_id=None):
        if isinstance(self.paths[subject], MultiPath):
            if self.resolved_path is None:
                self.resolved_path = MultiResolvedPath()

            for unresolved_path in self.paths[subject].paths:
                path_id = self.resolved_path.create()
                for i, item in enumerate(unresolved_path):
                    if isinstance(item, URIRef):
                        self.resolve_path(item, path_id=path_id)
                    else:
                        self.resolved_path.update(path_id, ResolvedPathSegment(item.position, item.type, subject, i))
        else:
            if self.resolved_path is None:
                self.resolved_path = ResolvedPath()

            for i, item in enumerate(self.paths[subject]):
                if isinstance(item, URIRef):
                    self.resolve_path(item, path_id=path_id)
                elif path_id is not None:
                    self.resolved_path.update(path_id, ResolvedPathSegment(item.position, item.type, subject, i))
                else:
                    self.resolved_path.add(ResolvedPathSegment(item.position, item.type, subject, i))

    def add_to_data(self, data, data_to_insert):
        path = self.current_resolved_path[self.current_path_index]

        if path.position is not None:
            if isinstance(path.position, str) and isinstance(data, dict):
                if path.position not in data:
                    data[path.position] = [] if path.type == "array" else {}
            elif isinstance(path.position, int) and isinstance(data, list):
                if len(data) < path.position:
                    data += [{} for i in range(path.position - len(data))]
            else:
                raise Exception(f"This shouldn't happen: {path}")

            if path.type == "array" and path == self.current_resolved_path[-2]:
                _path = self.current_resolved_path[self.current_path_index + 1]
                if _path.position is None and _path.type == "array":
                    data[path.position].append({})
                    _position = len(data[path.position])

                    if isinstance(self.paths[_path.uri], MultiPath):
                        self.paths[_path.uri][self.current_path_id][_path.index].position = _position
                    else:
                        self.paths[_path.uri][_path.index].position = _position

                    self.current_resolved_path[-1].position = _position

                if (isinstance(path.position, int) and path.type == "array") and (isinstance(_path.position, str) and _path.type == "object"):
                    data[path.idx][_path.position] = {**data_to_insert, **data[path.idx].get(_path.position, {})}
                else:
                    if len(data[path.position]) < _path.position:
                        data[path.position] += [{} for i in range(_path.position - len(data[path.position]))]

                    data[path.position][_path.idx] = {**data_to_insert, **data[path.position][_path.idx]}
            elif (
                path.type == "array"
                and self.current_resolved_path[self.current_path_index + 1].position is None
                and self.current_resolved_path[self.current_path_index + 1].type == "array"
            ):
                _path = self.current_resolved_path[self.current_path_index + 1]
                if _path.position is None and _path.type == "array":
                    data[path.position].append({})
                    _position = len(data[path.position])

                    if isinstance(self.paths[_path.uri], MultiPath):
                        self.paths[_path.uri][self.current_path_id][_path.index].position = _position
                    else:
                        self.paths[_path.uri][_path.index].position = _position

                    self.current_resolved_path[self.current_path_index + 1].position = _position
                self.current_path_index += 1
                self.add_to_data(data[path.position], data_to_insert)
            elif path.type == "object" and path == self.current_resolved_path[-1]:
                if isinstance(data[path.position], dict):
                    data[path.position] = {**data_to_insert, **data[path.position]}
                else:
                    data[path.position] = {**data_to_insert}
            else:
                self.current_path_index += 1
                if isinstance(path.position, int):
                    self.add_to_data(data[path.idx], data_to_insert)
                else:
                    self.add_to_data(data[path.idx], data_to_insert)
        elif path.type == "object":
            if path == self.current_resolved_path[-1]:
                data = {**data_to_insert, **data}
            else:
                raise Exception(f"This shouldn't happen: {path}")
        else:
            raise Exception(f"This shouldn't happen: {path}, {self.current_resolved_path}")


if __name__ == "__main__":
    from ravens.cim_tools.template import CIMTemplate
    from rdflib.extras.external_graph_libs import rdflib_to_networkx_multidigraph
    import networkx as nx
    import json

    g = Graph()
    g.parse("examples/case3_balanced.xml", format="application/rdf+xml", publicID="urn:uuid:")
    # g.parse("examples/IEEE13_Assets.xml", format="application/rdf+xml", publicID="urn:uuid:")
    # g.parse("examples/ieee8500u_fuseless_CIM100x.XML", format="application/rdf+xml", publicID="urn:uuid:")

    # rm = set()
    # for s, p, o in g.triples((None, None, None)):
    #     if not isinstance(o, URIRef) or str(o).startswith("http://iec.ch"):
    #         rm.add((s, p, o))

    # for triple in rm:
    #     g.remove(triple)

    G = rdflib_to_networkx_multidigraph(g)
    for i, e in enumerate(G.edges(keys=True)):
        G.edges[e].update({"label": str(e[-1]), "id": str(i)})
    for n in G.nodes:
        G.nodes[n].update({"label": str(n)})

    # nx.write_graphml(G, "out/rdf_graphs/case3_balanced_uriref.graphml", named_key_ids=True, edge_id_from_attribute="id")
    # nx.write_graphml(G, "out/rdf_graphs/ieee13_assets_uriref.graphml", named_key_ids=True, edge_id_from_attribute="id")
    # nx.write_graphml(G, "out/rdf_graphs/ieee8500u_fuseless.graphml", named_key_ids=True, edge_id_from_attribute="id")

    d = RAVENSData(g, CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template, prune_unncessary=False)

    with open("out/test_xml2json_case3.json", "w") as f:
        json.dump(d.data, f, indent=2)

    # with open("out/test_xml2json_ieee13.json", "w") as f:
    #     json.dump(d.data, f, indent=2)

    # with open("out/ieee8500u_fuseless.json", "w") as f:
    #     json.dump(d.data, f, indent=2)

    # g.serialize("out/rdf_graphs/case3_balanced.json", format="json-ld")
