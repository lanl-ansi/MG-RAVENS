import json
from multiprocessing import Value
import pathlib
import re
import traceback

import networkx as nx

from ast import literal_eval
from collections import namedtuple
from copy import deepcopy
from datetime import datetime

from rdflib import Graph
from rdflib.namespace import Namespace, RDF
from rdflib.extras.external_graph_libs import rdflib_to_networkx_multidigraph
from rdflib.term import URIRef, Literal

from ravens import __version__
from ravens.logging import logger
from ravens.data import _DEFAULT_CIM_NAMESPACE
from ravens.schema import SchemaTemplate, RavensSchema

Reference = namedtuple("Reference", ["parent", "id"])

# TODO: Pick better prune keys
prune_keys = ["IdentifiedObject.name", "IdentifiedObject.mRID", r"(.+)\.sequenceNumber"]


def _str_to_bool(s: str) -> bool:
    s = s.strip().lower()
    if s == "true":
        return True
    elif s == "false":
        return False
    else:
        raise ValueError(f"Cannot convert {s} to a boolean.")


class PathSegment:
    def __init__(self, position: int | str | None, json_type: str, zero_index: bool = False):
        self.position: int | str | None = position
        self.type: str = json_type
        self.zero_index: bool = zero_index

    def __str__(self):
        return "PathSegment(" + ", ".join([str(i) for i in [self.position, self.type, self.zero_index]]) + ")"

    def __repr__(self):
        return self.__str__()


class Path:
    def __init__(self):
        self.path: dict[int, PathSegment] = {}

    def add(self, path_segment: PathSegment):
        self.path[len(self.path)] = path_segment

    def insert(self, path_segment: PathSegment):
        self.path = {**{0: path_segment}, **{k + 1: v for k, v in self.path.items()}}

    def popfirst(self):
        path_segment = self.path[0]

        self.path = {i - 1: path for i, path in self.path.items() if i != 0}

    def __getitem__(self, i: int):
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

    def __len__(self) -> int:
        return len(self.path)


class MultiPath:
    def __init__(self):
        self.paths: list[Path] = []

    def add(self, path: Path):
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
    def __init__(self, position: str | int | None, json_type: str, uri: URIRef, index: int, zero_index: bool = False):
        self.position: str | int | None = position
        self.type: str = json_type
        self.uri: URIRef = uri
        self.index: int = index
        self.zero_index: bool = zero_index

    @property
    def idx(self):
        if isinstance(self.position, int):
            if self.zero_index:
                return self.position
            else:
                return self.position - 1
        else:
            return self.position

    def __str__(self) -> str:
        return "ResolvedPathSegment(" + ", ".join([str(i) for i in [self.position, self.type, self.uri, self.index, self.zero_index]]) + ")"

    def __repr__(self) -> str:
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


class RavensImport:
    def __init__(
        self,
        cim_profile_path: pathlib.PosixPath | str | None = None,
        schema_template: SchemaTemplate | None = None,
        prune_unncessary: bool = False,
        cim_namespace: str = _DEFAULT_CIM_NAMESPACE,
        schema: RavensSchema | None = None,
        cim_profile_rdf: Graph | None = None,
    ):
        try:
            if cim_profile_rdf is not None:
                self.graph = cim_profile_rdf
            else:
                g = Graph()
                self.graph = g.parse(cim_profile_path, format="application/rdf+xml", publicID="urn:uuid:")
        except Exception as msg:
            raise Exception(f"At least one of `cim_profile_path` or `cim_profile_rdf` must not be None: {msg}")

        self.cim_ns = Namespace(cim_namespace + "#")
        self.prune_unncessary = prune_unncessary

        self.untokenized_paths = []
        self.reference_paths = {}

        if schema_template is None:
            schema_template = SchemaTemplate()

        if schema is None:
            schema = RavensSchema(schema_template=schema_template)

        self.build_paths_from_template(schema_template.template)

        self.schema = schema

        self.tokenized_paths = {}
        self.tokenize_paths()

        self.unique_subject_types = {s: str(o).split("#")[-1] for s, o in self.graph.subject_objects(predicate=RDF.type)}
        self.paths: dict = {s: [] for s, t in self.unique_subject_types.items()}

        self.object_ids = {}
        self.build_actual_paths()

        self.data: dict = {}
        self.resolved_path: MultiResolvedPath | ResolvedPath | None = None
        self.current_resolved_path: MultiResolvedPath | ResolvedPath | None = None
        self.current_path_index = 0
        self.current_path_id = 0

        try:
            self.convert_rdf()
        except Exception as e:
            traceback.print_exc()

        self._add_ravens_version()

    @staticmethod
    def _convert_with_schema(attr, attr_type: str):
        funcs = {"string": str, "integer": int, "boolean": _str_to_bool, "number": float}
        value = str(attr)
        if attr_type in funcs:
            value = funcs[attr_type](value)

        return value

    @staticmethod
    def _convert_with_literal_eval(attr):
        value = str(attr.value)
        try:
            value = literal_eval(node_or_string=value)
        except:
            pass

        return value

    def _add_ravens_version(self):
        if "Versions" not in self.data:
            self.data["Versions"] = {}

        self.data["Versions"]["RavensVersion"] = {"Ravens.cimObjectType": "RavensVersion", "RavensVersion.date": f"{datetime.date(datetime.now())}", "RavensVersion.version": f"RAVENSv{__version__}"}

    def build_paths_from_template(self, template, current_path=None):
        if current_path is None:
            current_path = []

        for obj_id, obj in template.get("properties", {}).items():
            try:
                if obj.get("type", None) == "array":
                    self.parse_array(obj_id, obj, current_path=current_path)
                elif obj.get("type", None) == "object" or obj.get("$objectType", None) == "object":
                    if obj.get("$objectType", None) == "container":
                        _path_info = {"path": obj_id, "id": obj_id, "type": "container", "position": None}
                        self.build_paths_from_template(obj, current_path=current_path + [_path_info])
                    elif obj.get("$objectType", None) == "object":
                        if "anyOf" in obj:
                            for i, item in enumerate(obj["anyOf"]):
                                self.parse_object(obj_id, item.get("$objectId", obj_id), item, current_path)
                        else:
                            self.parse_object(obj_id, obj.get("$objectId", obj_id), obj, current_path)
                    elif obj.get("$objectType", None) == "reference":
                        # nothing to do
                        pass
                    else:
                        raise Exception(f"unrecognized objectType for '{obj_id}': '{obj.get('$objectType', None)}'")
                elif obj.get("$objectType", None) == "reference":
                    if obj_id not in self.reference_paths:
                        self.reference_paths[obj_id] = set()

                    if "anyOf" in obj:
                        for item in obj["anyOf"]:
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

    def parse_object(self, object_path, object_id, obj, current_path, json_type: str = "object", position_key: str | None = "$primaryObjectHash", position_value=None):
        _path_info = {
            "path": object_path,
            "id": object_id,
            "type": json_type,
            "position": obj.get(position_key, None) if position_key is not None else position_value,
            "position_secondary": obj.get("$secondaryObjectHash", None) if position_key is not None else None,
        }

        if obj.get("$objectId", None) is not None:
            self.untokenized_paths.append((obj["$objectId"], current_path + [_path_info]))
        else:
            self.untokenized_paths.append((object_path, current_path + [_path_info]))

        self.build_paths_from_template(obj, current_path=current_path + [_path_info])

    def parse_array(self, obj_id, obj, current_path):
        if obj.get("items", None) is not None:
            if obj["items"].get("type", None) == "object" or obj["items"].get("$objectType", None) == "object":
                if "anyOf" in obj["items"]:
                    for i, item in enumerate(obj["items"]["anyOf"]):
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
            elif obj["items"].get("type", None) == "array":
                self.parse_array(obj["items"]["$objectId"], obj["items"], current_path=current_path + [{"path": ""}])
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
                for _o in [o for o in self.graph.objects(subject=subject)] + [s for s in self.graph.subjects(object=subject)]:
                    ctype = self.unique_subject_types.get(_o, None)
                    if ctype is not None and ctype in self.tokenized_paths[cim_type]:
                        ctypes.append(ctype)
                        count += 1
                else:
                    if count == 0:
                        logger.warning(f"Connecting subject not found: {subject}::{cim_type}. This may mean the data is superfluous")
                        continue
                self.paths[subject] = self.find_path(subject, ctype=ctypes[0])
            else:
                self.paths[subject] = self.find_path(subject)

    def find_path(self, subject, ctype=None):
        obj_real_path = MultiPath()

        path_prospect = self.tokenized_paths.get(self.unique_subject_types[subject], [])
        if ctype is not None:
            path_prospect = path_prospect[ctype]

        path2sub = _path2sub = {obj_real_path.create(): tuple([subject])}
        sub2path = {v: k for k, v in path2sub.items()}
        for segment in path_prospect[::-1]:
            _next_subjects = {}
            path2sub = deepcopy(_path2sub)
            for idx, subjects in path2sub.items():
                if len(obj_real_path[idx]) > 0 and isinstance(obj_real_path[idx][0], URIRef):
                    continue

                _current_subject = subjects[-1]

                if self.graph.value(_current_subject, RDF.type) == self.cim_ns[segment["id"]]:
                    _next_subjects[_current_subject] = _current_subject
                else:
                    count = 0
                    for _next_subject in list(self.graph.objects(subject=_current_subject)) + list(self.graph.subjects(object=_current_subject)):
                        if self.graph.value(_next_subject, RDF.type) == self.cim_ns[segment["id"]]:
                            _next_subjects[_next_subject] = _current_subject
                            count += 1

                    if count == 0:
                        _next_subjects[_current_subject] = _current_subject

                for i, (_next_subject, _current_subject) in enumerate(_next_subjects.items()):
                    _path = tuple(list(subjects) + [_next_subject])
                    if i == 0:
                        _path2sub[idx] = _path
                        sub2path = {v: k for k, v in _path2sub.items()}
                    else:
                        _path2sub[obj_real_path.create()] = _path
                        sub2path = {v: k for k, v in _path2sub.items()}
                        _tmp = deepcopy(obj_real_path[idx])
                        _tmp.popfirst()
                        obj_real_path[sub2path[_path]] = _tmp

                    positions = self._build_positions(subject, _next_subject, segment)
                    for position in positions[::-1]:
                        obj_real_path[sub2path[_path]].insert(position)

        if len(obj_real_path) == 1:
            obj_real_path = obj_real_path[0]

        return obj_real_path

    def _build_positions(self, subject, _current_subject, segment):
        zero_indexed = self.graph.value(subject=subject, predicate=RDF.type) == self.cim_ns["PositionPoint"]
        positions = []
        if segment["type"] == "container" or (segment["type"] == "object" and segment["position"] is None):
            positions = [PathSegment(segment["path"], "object")]
        elif _current_subject != subject:
            positions = [_current_subject]
        else:
            _position = self.find_position_id(_current_subject, segment["position"], segment["position_secondary"])

            positions = [
                PathSegment(segment["path"], segment["type"]),
                PathSegment(str(_position) if (segment["type"] == "object") else (_position if _position is None else int(_position)), segment["type"], zero_index=zero_indexed),
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
                logger.warning(f"Path for subject not found: {str(subject)}::{self.unique_subject_types[subject]}")
                continue

    def find_position_id(self, subject, position_primary, position_secondary):
        pos_id = self.graph.value(subject=subject, predicate=self.cim_ns[position_primary])
        if position_primary is not None and pos_id is None:
            pos_id = self.graph.value(subject=subject, predicate=self.cim_ns[position_primary])
            if position_secondary is not None and pos_id is None:
                pos_id = str(subject)

        if pos_id is not None:
            self.object_ids[subject] = pos_id

        return pos_id

    def build_data(self, subject):
        data: dict = {"Ravens.cimObjectType": str(self.graph.value(subject=subject, predicate=RDF.type)).split("#")[-1]}
        for p, o in self.graph.predicate_objects(subject=subject):
            pn = str(p).split("#")[-1]
            if self.prune_unncessary and any(bool(re.search(k, pn)) for k in prune_keys):
                continue

            if p != RDF.type:
                value = o

                if isinstance(o, Literal):
                    if self.schema is not None:
                        try:
                            attr_schema = self.schema.schemas[f"{self.schema.base_id_uri}/{data['Ravens.cimObjectType']}.json"]["properties"][pn]
                            if "type" in attr_schema:
                                attr_type = attr_schema["type"]
                            elif "$ref" in attr_schema:
                                attr_schema = self.schema.schemas[attr_schema["$ref"]]
                                attr_type = attr_schema["type"][1]
                            else:
                                raise KeyError

                            try:
                                value = self._convert_with_schema(o.value, attr_type)
                            except ValueError as msg:
                                raise ValueError(f"Expected data of type '{attr_type}' for '{pn}' on '{data['Ravens.cimObjectType']}' object: ''{msg}''")

                        except KeyError:
                            value = str(o.value)
                    else:
                        value = self._convert_with_literal_eval(o.value)
                elif pn in self.reference_paths:
                    if o in self.object_ids:
                        value = f"{str(self.graph.value(subject=o, predicate=RDF.type)).split("#")[-1]}::'{self.object_ids[o]}'"
                    elif len(set(r.id for r in self.reference_paths[pn])) == 1:
                        ref = list(self.reference_paths[pn])[0]
                        try:
                            value = f"{ref.id}::'{self.find_position_id(o, self.tokenized_paths[ref.id][-1]['position'], self.tokenized_paths[ref.id][-1]['position_secondary'])}'"
                        except KeyError:
                            continue
                    else:
                        ref = None
                        for _ref in self.reference_paths[pn]:
                            if self.graph.value(subject=subject, predicate=RDF.type) == self.cim_ns[_ref.parent]:
                                ref = _ref
                                break

                        if ref is not None:
                            value = f"{ref.id}::'{self.find_position_id(o, self.tokenized_paths[ref.id][-1]['position'], self.tokenized_paths[ref.id][-1]['position_secondary'])}'"
                        else:
                            logger.warning(f"Can't find reference for {o}::{self.unique_subject_types[o]} from {subject}::{self.unique_subject_types[subject]}")
                            continue
                elif isinstance(o, URIRef) and o.startswith(self.cim_ns):
                    value = o.split("#")[-1]
                elif self.prune_unncessary or isinstance(o, URIRef):
                    continue

                data[pn] = value

        for pn, items in self.reference_paths.items():
            for ref in items:
                if ref.parent == self.graph.value(subject=subject, predicate=RDF.type).split("#")[-1] and pn not in data:
                    for o in self.graph.objects(subject=subject):
                        _rdf_type = self.graph.value(subject=o, predicate=RDF.type)
                        if _rdf_type is not None and str(_rdf_type).split("#")[-1] == ref.id:
                            data[pn] = f"{ref.id}::'{self.find_position_id(o, self.tokenized_paths[ref.id][-1]['position'], self.tokenized_paths[ref.id][-1]['position_secondary'])}'"

        if "IdentifiedObject.mRID" not in data.keys() and not self.prune_unncessary:
            if f"{self.schema.base_id_uri}/{data['Ravens.cimObjectType']}.json" in self.schema.schemas and "IdentifiedObject.mRID" in self.schema.schemas[f"{self.schema.base_id_uri}/{data['Ravens.cimObjectType']}.json"]["properties"]:
                data["IdentifiedObject.mRID"] = str(subject)

        return data

    def resolve_path(self, subject, path_id=None):
        zero_indexed = self.graph.value(subject=subject, predicate=RDF.type) == self.cim_ns["PositionPoint"]
        if isinstance(self.paths[subject], MultiPath):
            if self.resolved_path is None:
                self.resolved_path = MultiResolvedPath()

            for unresolved_path in self.paths[subject].paths:
                path_id = self.resolved_path.create()
                for i, item in enumerate(unresolved_path):
                    if isinstance(item, URIRef):
                        self.resolve_path(item, path_id=path_id)
                    else:
                        self.resolved_path.update(path_id, ResolvedPathSegment(item.position, item.type, subject, i, zero_index=zero_indexed))
        else:
            if self.resolved_path is None:
                self.resolved_path = ResolvedPath()

            for i, item in enumerate(self.paths[subject]):
                if isinstance(item, URIRef):
                    self.resolve_path(item, path_id=path_id)
                elif path_id is not None:
                    self.resolved_path.update(path_id, ResolvedPathSegment(item.position, item.type, subject, i, zero_index=zero_indexed))
                else:
                    self.resolved_path.add(ResolvedPathSegment(item.position, item.type, subject, i, zero_index=zero_indexed))

    def add_to_data(self, data: dict, data_to_insert):
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
                    if _path.zero_index:
                        _position -= 1

                    if isinstance(self.paths[_path.uri], MultiPath):
                        self.paths[_path.uri][self.current_path_id][_path.index].position = _position
                    else:
                        self.paths[_path.uri][_path.index].position = _position

                    self.current_resolved_path[-1].position = _position

                if (isinstance(path.position, int) and path.type == "array") and (isinstance(_path.position, str) and _path.type == "object"):
                    data[path.idx][_path.position] = {**data_to_insert, **data[path.idx].get(_path.position, {})}
                else:
                    if len(data[path.position]) < _path.position + bool(_path.zero_index):
                        data[path.position] += [{} for i in range(_path.position - len(data[path.position]) + bool(_path.zero_index))]

                    try:
                        data[path.position][_path.idx] = {**data_to_insert, **data[path.position][_path.idx]}
                    except IndexError as e:
                        print(_path, path, data_to_insert, _path.idx, data[path.position])
                        raise e
            elif path.type == "array" and self.current_resolved_path[self.current_path_index + 1].position is None and self.current_resolved_path[self.current_path_index + 1].type == "array":
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

    def export_rdf_graphml(self, file_path: pathlib.PosixPath):
        G = rdflib_to_networkx_multidigraph(self.graph)

        for i, e in enumerate(G.edges(keys=True)):
            G.edges[e].update({"label": str(e[-1]), "id": str(i)})
        for n in G.nodes:
            G.nodes[n].update({"label": str(n)})

        nx.write_graphml(G, file_path, named_key_ids=True, edge_id_from_attribute="id")

    def dump(self, file_path: pathlib.PosixPath | str, indent: int | None = None):
        with open(file_path, "w") as f:
            json.dump(self.data, f, indent=indent)


if __name__ == "__main__":
    d = RavensImport("examples/IEEE13_Assets.xml")
    d.dump("examples/IEEE13_Assets.json", indent=2)
