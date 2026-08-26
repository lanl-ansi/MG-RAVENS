import json
import pathlib
import pytest
from ravens.base import RavensData, ReferenceProxy


@pytest.fixture
def sample_data():
    """Load the sample case3_balanced.json for testing"""
    return RavensData("examples/case3_balanced.json")


@pytest.fixture
def sample_json_path():
    """Path to the sample JSON file"""
    return pathlib.Path("examples/case3_balanced.json")


class TestRavensDataInit:
    """Test RavensData initialization"""

    def test_init_from_file_path_str(self, sample_json_path):
        """Test initialization from string path"""
        data = RavensData(str(sample_json_path))
        assert data.data is not None
        assert len(data.paths) > 0
        assert len(data.iter) > 0

    def test_init_from_file_path_pathlib(self, sample_json_path):
        """Test initialization from pathlib.Path"""
        data = RavensData(sample_json_path)
        assert data.data is not None
        assert len(data.paths) > 0
        assert len(data.iter) > 0

    def test_init_from_dict(self, sample_json_path):
        """Test initialization from dictionary"""
        with open(sample_json_path, "r") as f:
            json_data = json.load(f)

        data = RavensData(json_data)
        assert data.data is not None
        assert len(data.paths) > 0
        assert len(data.iter) > 0

    def test_init_empty(self):
        """Test initialization with no arguments"""
        data = RavensData()
        assert data.data == {}
        assert data.paths == {}
        assert data.iter == {}


class TestRavensDataAccess:
    """Test data access methods"""

    def test_getitem_by_type(self, sample_data):
        """Test accessing objects by type"""
        cnodes = sample_data["ConnectivityNode"]
        assert isinstance(cnodes, dict)
        assert "sourcebus" in cnodes
        assert "primary" in cnodes
        assert "loadbus" in cnodes

    def test_getitem_nested(self, sample_data):
        """Test nested access"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        assert loadbus["IdentifiedObject.name"] == "loadbus"

    def test_contains(self, sample_data):
        """Test __contains__ method"""
        assert "ConnectivityNode" in sample_data
        assert "EnergyConsumer" in sample_data
        assert "NonExistentType" not in sample_data

    def test_keys(self, sample_data):
        """Test keys() method"""
        keys = sample_data.keys()
        assert "ConnectivityNode" in keys
        assert "BaseVoltage" in keys
        assert "OperationalLimitSet" in keys

    def test_iter(self, sample_data):
        """Test iteration over data"""
        items = list(sample_data)
        assert len(items) > 0
        assert all(isinstance(item, str) for item in items)
        assert "ConnectivityNode" in items
        assert "EnergyConsumer" in items

    def test_ref_access(self, sample_data):
        """Test ref() method"""
        loadbus = sample_data.ref("ConnectivityNode::'loadbus'")
        assert loadbus["IdentifiedObject.name"] == "loadbus"


class TestReferenceProxy:
    """Test ReferenceProxy functionality"""

    def test_reference_resolution(self, sample_data):
        """Test that references are resolved to ReferenceProxy objects"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit_ref = loadbus["ConnectivityNode.OperationalLimitSet"]

        assert isinstance(op_limit_ref, ReferenceProxy)

    def test_proxy_getitem(self, sample_data):
        """Test accessing items through proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        assert "IdentifiedObject.name" in op_limit
        assert op_limit["IdentifiedObject.name"] == "OpLimV_380.0-420.00000000000006"

    def test_proxy_setitem(self, sample_data):
        """Test setting items through proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        op_limit["test_field"] = "test_value"
        assert op_limit["test_field"] == "test_value"

    def test_proxy_keys(self, sample_data):
        """Test keys() method on proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        keys = list(op_limit.keys())
        assert "IdentifiedObject.name" in keys
        assert "IdentifiedObject.mRID" in keys

    def test_proxy_values(self, sample_data):
        """Test values() method on proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        values = list(op_limit.values())
        assert len(values) > 0

    def test_proxy_items(self, sample_data):
        """Test items() method on proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        items = list(op_limit.items())
        assert len(items) > 0
        assert all(isinstance(item, tuple) for item in items)

    def test_proxy_iteration(self, sample_data):
        """Test iteration over proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        keys = list(op_limit)
        assert "IdentifiedObject.name" in keys

    def test_proxy_get_ref_string(self, sample_data):
        """Test getting reference string from proxy"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        ref_string = op_limit.get_ref_string()
        assert ref_string == "OperationalLimitSet::'OpLimV_380.0-420.00000000000006'"

    def test_nested_proxy_access(self, sample_data):
        """Test accessing nested proxies"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]
        limit_values = op_limit["OperationalLimitSet.OperationalLimitValue"]

        assert isinstance(limit_values, list)
        assert len(limit_values) > 0


class TestDataModification:
    """Test modifying data through proxies"""

    def test_modify_through_proxy(self, sample_data):
        """Test that modifications through proxy affect the underlying data"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]

        original_name = op_limit["IdentifiedObject.name"]
        op_limit["IdentifiedObject.name"] = "Modified_Name"

        assert op_limit["IdentifiedObject.name"] == "Modified_Name"
        assert op_limit["IdentifiedObject.name"] != original_name

    def test_modify_nested_value(self, sample_data):
        """Test modifying nested values"""
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]
        limit_values = op_limit["OperationalLimitSet.OperationalLimitValue"]

        original_value = limit_values[0]["VoltageLimit.value"]
        limit_values[0]["VoltageLimit.value"] = 385.0

        assert limit_values[0]["VoltageLimit.value"] == 385.0
        assert limit_values[0]["VoltageLimit.value"] != original_value


class TestSerialization:
    """Test data serialization and export"""

    def test_dumps(self, sample_data):
        """Test dumps() method returns valid JSON string"""
        json_str = sample_data.dumps()

        assert isinstance(json_str, str)
        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_dumps_with_indent(self, sample_data):
        """Test dumps() with indentation"""
        json_str = sample_data.dumps(indent=2)

        assert isinstance(json_str, str)
        assert "\n" in json_str  # Should have newlines with indent

    def test_dump_to_file(self, sample_data, tmp_path):
        """Test dump() method writes to file"""
        output_file = tmp_path / "output.json"
        sample_data.dump(output_file, indent=2)

        assert output_file.exists()

        with open(output_file, "r") as f:
            data = json.load(f)

        assert isinstance(data, dict)

    def test_serialization_converts_proxies_to_strings(self, sample_data, tmp_path):
        """Test that ReferenceProxy objects are converted to strings on export"""
        # Modify data through proxy
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]
        op_limit["test_field"] = "test_value"

        # Export to file
        output_file = tmp_path / "output.json"
        sample_data.dump(output_file, indent=2)

        # Load raw JSON
        with open(output_file, "r") as f:
            data = json.load(f)

        # Verify reference is a string, not an object
        ref_value = data["ConnectivityNode"]["loadbus"]["ConnectivityNode.OperationalLimitSet"]
        assert isinstance(ref_value, str)
        assert ref_value == "OperationalLimitSet::'OpLimV_380.0-420.00000000000006'"

    def test_roundtrip(self, sample_data, tmp_path):
        """Test that data can be dumped and reloaded"""
        # Modify some data
        loadbus = sample_data["ConnectivityNode"]["loadbus"]
        op_limit = loadbus["ConnectivityNode.OperationalLimitSet"]
        op_limit["OperationalLimitSet.OperationalLimitValue"][0]["VoltageLimit.value"] = 385.0

        # Export
        output_file = tmp_path / "output.json"
        sample_data.dump(output_file, indent=2)

        # Reload
        reloaded_data = RavensData(output_file)

        # Verify modification persisted
        reloaded_loadbus = reloaded_data["ConnectivityNode"]["loadbus"]
        reloaded_op_limit = reloaded_loadbus["ConnectivityNode.OperationalLimitSet"]
        reloaded_value = reloaded_op_limit["OperationalLimitSet.OperationalLimitValue"][0]["VoltageLimit.value"]

        assert reloaded_value == 385.0


class TestPathBuilding:
    """Test internal path and reference building"""

    def test_paths_populated(self, sample_data):
        """Test that paths dictionary is populated"""
        assert len(sample_data.paths) > 0
        assert "ConnectivityNode::'loadbus'" in sample_data.paths

    def test_unraveled_populated(self, sample_data):
        """Test that unraveled dictionary is populated with mRIDs"""
        assert len(sample_data.unraveled) > 0
        # Check for known mRID
        assert "27271ac1-7114-4d5a-8cba-6ed29bdc42e2" in sample_data.unraveled

    def test_iter_populated(self, sample_data):
        """Test that iter dictionary is properly structured"""
        assert len(sample_data.iter) > 0
        assert "ConnectivityNode" in sample_data.iter
        assert "loadbus" in sample_data.iter["ConnectivityNode"]


class TestSpecificObjects:
    """Test accessing specific objects from case3_balanced.json"""

    def test_energy_consumers(self, sample_data):
        """Test accessing energy consumers"""
        consumers = sample_data["EnergyConsumer"]

        assert "l1" in consumers
        assert "l2" in consumers
        assert "l3" in consumers

        l1 = consumers["l1"]
        assert l1["EnergyConsumer.p"] == 6000.0
        assert l1["EnergyConsumer.q"] == 3000.0

    def test_acline_segments(self, sample_data):
        """Test accessing AC line segments"""
        lines = sample_data["ACLineSegment"]

        assert "ohline" in lines
        assert "quad" in lines

        ohline = lines["ohline"]
        assert ohline["Conductor.length"] == 1.0

    def test_energy_source(self, sample_data):
        """Test accessing energy source"""
        sources = sample_data["EnergySource"]

        assert "source" in sources
        source = sources["source"]

        assert source["EnergySource.nominalVoltage"] == 400.0
        assert source["EnergySource.voltageMagnitude"] == 398.36

    def test_terminal_references(self, sample_data):
        """Test that terminal connectivity node references work"""
        source = sample_data["EnergySource"]["source"]
        terminals = source["ConductingEquipment.Terminals"]

        assert len(terminals) > 0
        terminal = terminals[0]

        # Access the connectivity node through the reference
        cnode = terminal["Terminal.ConnectivityNode"]
        assert isinstance(cnode, ReferenceProxy)
        assert cnode["IdentifiedObject.name"] == "sourcebus"
