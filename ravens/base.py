import json
import pathlib
import re

from uuid import uuid4

from ravens.logging import logger
from ravens.xml import CymeConverter, DssExport, RavensExport, RavensImport


class ReferenceProxy:
    """Proxy object that maintains reference string while allowing direct object access"""

    def __init__(self, ref_string, target_obj, parent_dict, parent_key):
        object.__setattr__(self, "_ref_string", ref_string)
        object.__setattr__(self, "_target", target_obj)
        object.__setattr__(self, "_parent_dict", parent_dict)
        object.__setattr__(self, "_parent_key", parent_key)

    def __getitem__(self, key):
        return self._target[key]

    def __setitem__(self, key, value):
        self._target[key] = value

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __setattr__(self, name, value):
        setattr(self._target, name, value)

    def __dir__(self):
        base_attrs = set(object.__dir__(self))

        if hasattr(self._target, "__dir__"):
            base_attrs.update(dir(self._target))

        if isinstance(self._target, dict):
            base_attrs.update(self._target.keys())

        return sorted(base_attrs)

    def __repr__(self):
        return f"ReferenceProxy({self._ref_string}) -> {self._target}"

    def __str__(self):
        return str(self._target)

    def __iter__(self):
        return iter(self._target)

    def keys(self):
        if isinstance(self._target, dict):
            return self._target.keys()
        raise AttributeError("Target object does not have keys()")

    def values(self):
        if isinstance(self._target, dict):
            return self._target.values()
        raise AttributeError("Target object does not have values()")

    def items(self):
        if isinstance(self._target, dict):
            return self._target.items()
        raise AttributeError("Target object does not have items()")

    def get_ref_string(self):
        return self._ref_string

    def _ipython_key_completions_(self):
        if isinstance(self._target, dict):
            return list(self._target.keys())
        return []


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
                        mrid = str(uuid4())
                    if name is None:
                        name = mrid

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
                                mrid = str(uuid4())
                            if name is None:
                                name = mrid

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

    def _update_refs(self, obj=None, parent_dict=None, parent_key=None):
        """Recursively replace reference strings with ReferenceProxy objects"""
        if obj is None:
            obj = self.data

        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if isinstance(v, str) and re.match(r"(\w+)::'(.+)'", v):
                    if v in self.paths:
                        obj[k] = ReferenceProxy(v, self.paths[v], obj, k)
                        logger.debug(f"Created proxy for {v}")
                    else:
                        logger.warning(f"Reference not found: {v}")
                elif isinstance(v, (dict, list)):
                    self._update_refs(v, obj, k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str) and re.match(r"(\w+)::'(.+)'", item):
                    if item in self.paths:
                        obj[i] = ReferenceProxy(item, self.paths[item], obj, i)
                        logger.debug(f"Created proxy for {item}")
                    else:
                        logger.warning(f"Reference not found: {item}")
                elif isinstance(item, (dict, list)):
                    self._update_refs(item, obj, i)

    def _serialize_refs(self, obj):
        """Convert ReferenceProxy objects back to reference strings"""
        if isinstance(obj, ReferenceProxy):
            return obj.get_ref_string()
        elif isinstance(obj, dict):
            return {k: self._serialize_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_refs(item) for item in obj]
        else:
            return obj

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return "RavensData::'model_name'"

    def __getitem__(self, key):
        return self.iter[key]

    def __contains__(self, key):
        return key in self.iter

    def __iter__(self):
        return iter(self.iter)

    def items(self):
        return self.iter.items()

    def keys(self):
        return self.iter.keys()

    def ref(self, key):
        return self.paths[key]

    def load(self, file_path: pathlib.Path | str):
        with open(file_path, "r") as f:
            self.data = json.load(f)

    def dumps(self, indent: int | None = None):
        """Export data to json string"""
        return json.dumps(self._serialize_refs(self.data), indent=indent)

    def dump(self, file_path: pathlib.Path | str, indent: int | None = None):
        """Export data to json file"""
        with open(file_path, "w") as f:
            json.dump(self._serialize_refs(self.data), f, indent=indent)

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
        """Export data to XML"""
        serialized_data = self._serialize_refs(self.data)
        exporter = RavensExport(serialized_data)

        exporter.save(file_path)


if __name__ == "__main__":
    data = RavensData("examples/case3_balanced.json")

    # Navigate through references
    loadbus = data["ConnectivityNode"]["loadbus"]
    print(f"Loadbus: {loadbus}")

    # Access referenced object directly
    op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]
    print(f"OperationalLimitSet: {op_limit}")
    print(f"OperationalLimitSet keys: {list(op_limit.keys())}")

    # Access nested data in referenced object
    limit_values = op_limit["OperationalLimitSet.OperationalLimitValue"]
    print(f"Limit values count: {len(limit_values)}")

    # Edit the referenced object
    op_limit["OperationalLimitSet.OperationalLimitValue"][0]["VoltageLimit.value"] = 385.0

    # Export - automatically converts back to string references
    data.dump("examples/test_output.json", indent=2)

    print("\nExport complete - check test_output.json")
