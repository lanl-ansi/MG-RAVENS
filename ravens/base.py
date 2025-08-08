import json
import pathlib
import re

from uuid import uuid4

from ravens.xml import CymeConverter, DssExport, RavensExport, RavensImport


class RavensData(object):
    def __init__(self, network_profile: pathlib.Path | str | dict | None = None):
        self.data = {}
        self.unraveled = {}
        self.paths = {}
        self.iter = {}

        if isinstance(network_profile, dict):
            self.data = network_profile.copy()
        elif isinstance(network_profile, pathlib.Path) or isinstance(network_profile, str):
            self.load(network_profile)

        self._build_paths()
        self._build_iterates()
        self._update_refs()

    def _build_paths(self):
        self._add_path(self.data)

    def _add_path(self, data: dict):
        for k, v in data.items():
            if isinstance(v, dict):
                cim_obj_type = v.get("Ravens.cimObjectType", None)
                name = v.get("IdentifiedObject.name", None)
                mrid = v.get("IdentifiedObject.mRID", None)
                if cim_obj_type is not None:
                    if mrid is None:
                        mrid = v["IdentifiedObject.mRID"] = str(uuid4())
                    if name is None:
                        name = v["IdentifiedObject.name"] = mrid

                    self.unraveled[mrid] = self.paths[f"{cim_obj_type}::'{name}'"] = v

                self._add_path(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        cim_obj_type = item.get("Ravens.cimObjectType", None)
                        name = item.get("IdentifiedObject.name", None)
                        mrid = item.get("IdentifiedObject.mRID", None)
                        if cim_obj_type is not None:
                            if mrid is None:
                                mrid = item["IdentifiedObject.mRID"] = str(uuid4())
                            if name is None:
                                name = item["IdentifiedObject.name"] = mrid

                            self.unraveled[mrid] = self.paths[f"{cim_obj_type}::'{name}'"] = item

                        self._add_path(item)

    def _build_iterates(self):
        for k, v in self.paths.items():
            m = re.match(r"(\w+)::'(.+)'", k)
            if m:
                uobj = m.group(1)
                obj_id = m.group(2)

                if uobj not in self.iter:
                    self.iter[uobj] = {}

                self.iter[uobj][obj_id] = v

    def _update_refs(self):
        for k, v in self.paths.items():
            for _k, _v in v.items():
                if isinstance(_v, str) and re.match(r"(\w+)::'(.+)'", _v):
                    v[_k] = self.paths[_v]

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return "RavensData::'model_name'"

    def __getitem__(self, key):
        return self.iter[key]

    def __contains__(self, key):
        return key in self.iter

    def __iter__(self):
        return self.iter.items()

    def keys(self):
        return self.iter.keys()

    def ref(self, key):
        return self.paths[key]

    def load(self, file_path: pathlib.Path | str):
        with open(file_path, "r") as f:
            self.data = json.load(f)

    def dump(self, file_path: pathlib.Path | str, indent: int | None = None):
        with open(file_path, "w") as f:
            json.dump(self.data, f, indent=indent)

    @classmethod
    def import_xml(cls, network_profile):
        importer = RavensImport(network_profile)

        return cls(importer.data)

    @classmethod
    def import_dss(cls, network_profile):
        dss_xml = DssExport(network_profile)
        importer = RavensImport(dss_xml)

        return cls(importer.data)

    @classmethod
    def import_cyme_cim(cls, network_profile):
        corrected_cyme = CymeConverter(network_profile)
        importer = RavensImport(corrected_cyme)

        return cls(importer.data)

    def export_cim(self, file_path: pathlib.Path | str):
        exporter = RavensExport(self.data)

        exporter.save(file_path)


if __name__ == "__main__":
    d = RavensData("examples/case3_balanced.json")

    cnodes = d["ConnectivityNode"]
    for k, v in cnodes.items():
        print(k, v)

    sourcebus = d.ref("ConnectivityNode::'sourcebus'")
