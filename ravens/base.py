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

    def get(self, key, default=None):
        if isinstance(self._target, dict):
            return self._target.get(key, default)
        raise AttributeError("Target object does not have get()")

    def get_ref_string(self):
        return self._ref_string

    def _ipython_key_completions_(self):
        if isinstance(self._target, dict):
            return list(self._target.keys())
        return []


class RavensData(object):
    def __init__(self, network_profile: pathlib.Path | str | dict | None = None, template_path: pathlib.Path | str | None = None):
        self.data = {}
        self.unraveled = {}
        self.paths = {}
        self.iter = {}
        self.containers = {}  # Maps container names to all objects underneath
        self.container_paths = {}  # Maps container names to their path in the tree
        self.type_aliases = {}  # Maps child types to parent types
        self.template_path = template_path

        if isinstance(network_profile, dict):
            self.data = network_profile.copy()
        elif isinstance(network_profile, RavensData):
            self.data = network_profile.data.copy()
        elif isinstance(network_profile, pathlib.Path) or isinstance(network_profile, str):
            self.load(network_profile)

        self._parse_template_for_aliases()

        self._build_paths()
        self._build_containers()
        self._build_iterates()
        self._update_refs()

    def _parse_template_for_aliases(self):
        """Parse the template JSON to discover anyOf type hierarchies"""
        try:
            if self.template_path is not None:
                with open(self.template_path, "r") as f:
                    template = json.load(f)
                self._extract_anyof_types(template)
                logger.info(f"Parsed template and found {len(self.type_aliases)} type aliases")
        except Exception as e:
            logger.warning(f"Could not parse template for type aliases: {e}")

    def _extract_anyof_types(self, data: dict, parent_id: str | None = None):
        """
        Recursively extract anyOf relationships from template.

        When we find an anyOf with items that have $objectType="object" and a
        $primaryObjectHash, we register each child $objectId as discoverable
        under the parent $objectId.
        """
        if not isinstance(data, dict):
            return

        # Check if this level has anyOf
        if "anyOf" in data:
            parent_obj_id = data.get("$objectId", parent_id)
            has_primary_hash = data.get("$primaryObjectHash") is not None

            if parent_obj_id and has_primary_hash:
                # Process each anyOf item
                for item in data["anyOf"]:
                    if isinstance(item, dict):
                        obj_type = item.get("$objectType")
                        child_obj_id = item.get("$objectId")

                        if obj_type == "object" and child_obj_id:
                            self.register_type_alias(child_obj_id, parent_obj_id)
                            logger.debug(f"Found anyOf: {child_obj_id} -> {parent_obj_id}")

        # Recurse through properties
        if "properties" in data:
            for key, value in data["properties"].items():
                if isinstance(value, dict):
                    self._extract_anyof_types(value, data.get("$objectId"))

        # Recurse through items (for arrays)
        if "items" in data:
            if isinstance(data["items"], dict):
                self._extract_anyof_types(data["items"], parent_id)

        # Recurse through anyOf items
        if "anyOf" in data:
            for item in data["anyOf"]:
                if isinstance(item, dict):
                    self._extract_anyof_types(item, parent_id)

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

                    self.unraveled[mrid] = v
                    # Index by both name and mRID for reference resolution
                    self.paths[f"{cim_obj_type}::'{name}'"] = v
                    if name != mrid:
                        self.paths[f"{cim_obj_type}::'{mrid}'"] = v

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

                            self.unraveled[mrid] = item
                            # Index by both name and mRID for reference resolution
                            self.paths[f"{cim_obj_type}::'{name}'"] = item
                            if name != mrid:
                                self.paths[f"{cim_obj_type}::'{mrid}'"] = item

                        self._add_path(item)

    def _any_typed_descendants(self, data: dict) -> bool:
        """Check if this dict or any of its descendants have Ravens.cimObjectType"""
        for k, v in data.items():
            if isinstance(v, dict):
                if "Ravens.cimObjectType" in v:
                    return True
                elif self._any_typed_descendants(v):
                    return True
        return False

    def _collect_objects_from_container(self, container_name: str, data: dict, objects: dict):
        """Recursively collect all objects with Ravens.cimObjectType from a container dict"""
        for k, v in data.items():
            if isinstance(v, dict):
                if "Ravens.cimObjectType" in v:
                    # This is an object with a type - add it
                    obj_name = v.get("IdentifiedObject.name", k)
                    objects[obj_name] = v
                    logger.debug(f"Added {v['Ravens.cimObjectType']}::{obj_name} to container {container_name}")
                else:
                    # No type - keep recursing to find objects
                    self._collect_objects_from_container(container_name, v, objects)

    def _build_containers(self, data=None, path=None):
        """Build containers dict by identifying container nodes and collecting all objects beneath them"""
        if data is None:
            data = self.data
        if path is None:
            path = []

        if isinstance(data, dict):
            has_cim_type = "Ravens.cimObjectType" in data

            if not has_cim_type:
                # Check if any descendants have Ravens.cimObjectType
                has_typed_descendants = False
                for k, v in data.items():
                    if isinstance(v, dict):
                        if "Ravens.cimObjectType" in v:
                            has_typed_descendants = True
                            break
                        # Recurse to check descendants
                        if self._any_typed_descendants(v):
                            has_typed_descendants = True
                            break

                # If this dict doesn't have a type but has descendants with types, it's a container
                if has_typed_descendants and len(path) > 0:
                    container_name = path[-1]
                    if container_name not in self.containers:
                        self.containers[container_name] = {}
                        self.container_paths[container_name] = path.copy()

                    self._collect_objects_from_container(container_name, data, self.containers[container_name])
                    logger.debug(f"Built container: {container_name} with {len(self.containers[container_name])} objects at path {' > '.join(path)}")

            # Recurse into children
            for k, v in data.items():
                if isinstance(v, dict):
                    self._build_containers(v, path + [k])

    def _build_iterates(self):
        """Build iteration dictionaries, handling anyOf type hierarchies"""
        for k, v in self.paths.items():
            m = re.match(r"(\w+)::'(.+)'", k)
            if m:
                obj_type = m.group(1)
                obj_id = m.group(2)

                # Add to primary type
                if obj_type not in self.iter:
                    self.iter[obj_type] = {}
                self.iter[obj_type][obj_id] = v

                # Check if this type has any parent types (from anyOf structures)
                if obj_type in self.type_aliases:
                    for parent_type in self.type_aliases[obj_type]:
                        if parent_type not in self.iter:
                            self.iter[parent_type] = {}
                        self.iter[parent_type][obj_id] = v
                        logger.debug(f"Added {obj_type}::'{obj_id}' to parent type {parent_type}")

    def register_type_alias(self, child_type: str, parent_type: str):
        """Register that child_type should also be discoverable under parent_type"""
        if child_type not in self.type_aliases:
            self.type_aliases[child_type] = set()
        self.type_aliases[child_type].add(parent_type)

    def get_all_of_type(self, obj_type: str) -> dict:
        """
        Get all objects of a specific type, including subtypes from anyOf definitions.

        Args:
            obj_type: The object type to search for

        Returns:
            Dictionary mapping object IDs to objects
        """
        return self.iter.get(obj_type, {})

    def list_available_types(self) -> list[str]:
        """Return a list of all available object types"""
        return sorted(self.iter.keys())

    def list_available_containers(self) -> list[str]:
        """Return a list of all available container names"""
        return sorted(self.containers.keys())

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
        return f"RavensData with {len(self.containers)} collections and {len(self.unraveled)} objects"

    def __str__(self):
        lines = ["RavensData:"]
        lines.append(f"  Collections: {len(self.containers)}")
        lines.append(f"  Objects: {len(self.unraveled)}")
        if self.containers:
            lines.append("  Available collections:")
            for name in sorted(self.containers.keys()):
                lines.append(f"    {name}: {len(self.containers[name])} objects")
        return "\n".join(lines)

    # Containers-first interface (primary access pattern)
    def __getitem__(self, key):
        """Access containers by name (primary interface)"""
        return self.containers[key]

    def __setitem__(self, key, value):
        self.containers[key] = value

    def __contains__(self, key):
        return key in self.containers

    def __iter__(self):
        return iter(self.containers)

    def items(self):
        return self.containers.items()

    def keys(self):
        return self.containers.keys()

    def values(self):
        return self.containers.values()

    def get(self, key, default=None):
        return self.containers.get(key, default)

    def __len__(self):
        return len(self.containers)

    # Enable attribute access for containers
    def __getattr__(self, name):
        # Avoid recursion on special attributes
        if name.startswith("_") or name in ("data", "unraveled", "paths", "iter", "containers", "container_paths", "type_aliases", "template_path"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        if name in self.containers:
            return self.containers[name]
        raise AttributeError(f"No container named '{name}'")

    def __dir__(self):
        # Include container names in dir() for tab completion
        base = set(object.__dir__(self))
        base.update(self.containers.keys())
        return sorted(base)

    def _ipython_key_completions_(self):
        """Enable tab completion in IPython/Jupyter"""
        return list(self.containers.keys())

    def ref(self, key):
        """Access objects by reference string (e.g., 'ConnectivityNode::loadbus')"""
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
    def import_xml(cls, network_profile, template_path: pathlib.Path | str | None = None):
        importer = RavensImport(network_profile)
        return cls(importer.data, template_path=template_path)

    @classmethod
    def import_dss(cls, network_profile, template_path: pathlib.Path | str | None = None):
        dss_xml = DssExport(network_profile)
        importer = RavensImport(dss_xml)
        return cls(importer.data, template_path=template_path)

    @classmethod
    def import_cyme_cim(cls, network_profile, prune_remaining_cyme: bool = True, template_path: pathlib.Path | str | None = None, PEC_corrections:dict[str, str|list]={}):
        """
        convert cyme file to cim making needed modifications to cyme exports.
        - PEC_corrections optionally can be formatted as a dictionary such that 
            - PEC_corrections["unit_type"] = "pv" or "wind" - sets default conversion of rotating machines to solar or wind
            - PEC_corrections["pv"] = [rotating machine names,...] - converts all listed rotating machines to solar
            - PEC_corrections["wind"] = [rotating machine names,...] - converts all listed rotating machines to wind
        
        """
        corrected_cyme = CymeConverter(network_profile, prune_remaining_cyme=prune_remaining_cyme, PEC_corrections=PEC_corrections)
        importer = RavensImport(corrected_cyme)
        return cls(importer.data, template_path=template_path)

    def export_cim(self, file_path: pathlib.Path | str):
        """Export data to XML"""
        serialized_data = self._serialize_refs(self.data)
        exporter = RavensExport(serialized_data)
        exporter.save(file_path)


if __name__ == "__main__":
    from ravens.data import _TEMPLATE_JSON_PATH

    # Load with template to automatically discover type hierarchies
    data = RavensData("examples/case3_balanced.json")

    # Show discovered type aliases
    print("\nDiscovered type aliases:")
    for child, parents in data.type_aliases.items():
        for parent in parents:
            print(f"  {child} -> {parent}")

    # Access containers (primary interface - matches Julia)
    print("\nAvailable containers:")
    for container_name in data.list_available_containers():
        print(f"  {container_name}: {len(data[container_name])} objects")

    # Access specific container
    if "ConnectivityNode" in data:
        conn_nodes = data["ConnectivityNode"]
        print(f"\nConnectivityNode container has {len(conn_nodes)} objects:")
        for name, obj in conn_nodes.items():
            print(f"  - {name}")

    # Access via attribute (also works)
    if hasattr(data, "ConnectivityNode"):
        loadbus = data.ConnectivityNode.get("loadbus")
        if loadbus:
            print(f"\nLoadbus accessed via attribute: {loadbus.get('IdentifiedObject.name')}")

    # Access via reference string (for specific lookups)
    loadbus_ref = data.ref("ConnectivityNode::'loadbus'")
    print(f"\nLoadbus via ref: {loadbus_ref.get('IdentifiedObject.name')}")

    # Get all objects of a specific type (including subtypes)
    all_switches = data.get_all_of_type("Switch")
    print(f"\nFound {len(all_switches)} switches (including subtypes):")
    for switch_id, switch_obj in all_switches.items():
        switch_type = switch_obj.get("Ravens.cimObjectType", "Unknown")
        print(f"  - {switch_id} (type: {switch_type})")

    # List all available types
    print(f"\nAll available types ({len(data.list_available_types())}):")
    for obj_type in data.list_available_types():
        count = len(data.get_all_of_type(obj_type))
        print(f"  - {obj_type}: {count} objects")

    # Export - automatically converts back to string references
    data.dump("examples/test_output.json", indent=2)

    print("\nExport complete - check test_output.json")
