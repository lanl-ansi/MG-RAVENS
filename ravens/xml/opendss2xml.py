import cffi
import ctypes
import math
import pathlib

from uuid import uuid4

from opendssdirect import dss as odd
import altdss

from rdflib.namespace import Namespace
from rdflib.term import URIRef, Literal
from rdflib import Graph, RDF

from ravens.data import _DEFAULT_CIM_NAMESPACE
from ravens.logging import logger


class TestLoadObj(ctypes.Structure):
    _fields_ = [
        ("base_class_padding", ctypes.c_byte * 786),
        ("kWBase", ctypes.c_double),
        ("kvarBase", ctypes.c_double),
        ("kWRef", ctypes.c_double),
        ("kVARref", ctypes.c_double),
    ]


ffi = cffi.FFI()

unit_conversion: dict[str, float] = {"mi": 1609.3, "kft": 304.8, "km": 1000.0, "m": 1.0, "ft": 0.3048, "in": 0.0254, "cm": 0.01, "mm": 0.001}


def interp_phasecode(phasecode: str) -> list[str]:
    _phases: set[str] = set([])
    for p in ["A", "B", "C", "N", "s1", "s2", "s12"]:
        if p in phasecode:
            _phases.add(p)

    phases = list(_phases)
    phases.sort()

    return phases


def parse_phase_str(bus: str, n_phases: int, kv_base: float | None = None, is_delta: bool = False) -> str:
    phase_str = ""

    if is_delta:
        if bus.count(".") == 0 or n_phases == 3:
            phase_str = "ABC"
        else:
            phases = bus.split(".", maxsplit=1)[-1]
            if n_phases == 1:
                if "1.2" in phases or "2.1" in phases:
                    phase_str = "A"
                elif "2.3" in phases or "3.2" in phases:
                    phase_str = "B"
                elif "1.3" in phases or "3.1" in phases:
                    phase_str = "C"
            else:
                if "1.2.3" in phases:
                    phase_str = "AB"
                elif "1.3.2" in phases:
                    phase_str = "CB"
                elif "2.1.3" in phases:
                    phase_str = "AC"
                elif "2.3.1" in phases:
                    phase_str = "BC"
                elif "3.1.2" in phases:
                    phase_str = "CA"
                elif "3.2.1" in phases:
                    phase_str = "BA"
    else:
        is_secondary = False
        if kv_base is not None:
            if (n_phases == 2 and kv_base < 0.25) or (n_phases == 1 and kv_base < 0.13):
                is_secondary = True

        if bus.count(".") == 0:
            return "ABC"
        else:
            phases = bus.split(".", maxsplit=1)[-1]
            if is_secondary:
                if "1" in phases:
                    phase_str = "s1"
                    if "2" in phases:
                        phase_str = "s12"
                elif "2" in phases:
                    phase_str = "s2"
            else:
                if "1" in phases:
                    phase_str += "A"
                if "2" in phases:
                    phase_str += "B"
                if "3" in phases:
                    phase_str += "C"
                if "4" in phases:
                    phase_str += "N"

    return phase_str


def parse_ordered_phase_str(bus: str, n_phases: int, kv_base: float | None = None) -> str:
    phase_str = ""
    is_secondary = False
    if kv_base is not None:
        if (n_phases == 2 and kv_base < 0.25) or (n_phases == 1 and kv_base < 0.13):
            is_secondary = True

    if bus.count(".") == 0:
        return "ABC"
    else:
        phases = bus.split(".", 1)[-1]
        if is_secondary:
            if "1" in phases:
                phase_str = "s1"
                if "2" in phases:
                    phase_str = "s12"
            elif "2" in phases:
                phase_str = "s2"
        else:
            phase_str = ""
            for ph in phases.split("."):
                phase_code = {"1": "A", "2": "B", "3": "C", "4": "N"}.get(ph, None)
                if phase_code is not None:
                    phase_str += phase_code

    return phase_str


class TransformerBank(object):
    def __init__(self, max_wdg: int, local_name: str, uuid: str = str(uuid4())):
        self.local_name = local_name
        self.uuid = uuid
        self.vector_group = ""
        self.max_windings = max_wdg
        self.n_windings = 0
        self.connections = [-1 for i in range(max_wdg)]
        self.b_auto = False
        self.angles = [0 for i in range(max_wdg)]
        self.phase_a = [0 for i in range(max_wdg)]
        self.phase_b = [0 for i in range(max_wdg)]
        self.phase_c = [0 for i in range(max_wdg)]
        self.ground = [0 for i in range(max_wdg)]
        self.terminal_uris: list[URIRef] = []

        self.pd_unit = None

    def add_Transformer(self, tr: altdss.Transformer):
        self.pd_unit = tr
        if tr.Windings > self.n_windings:
            self.n_windings = tr.Windings

        for i in range(tr.Windings):
            phases: str | None = parse_phase_str(tr.Buses[i], n_phases=tr.Phases, kv_base=tr.kVs[i], is_delta=tr.Conns[i] != 0)  # type: ignore
            if phases is not None:
                if "A" in phases:
                    self.phase_a[i] = 1
                if "B" in phases:
                    self.phase_b[i] = 1
                if "C" in phases:
                    self.phase_c[i] = 1

            self.connections[i] = tr.Conns[i]  # type: ignore

            if self.connections[i] == self.connections[0]:
                self.angles[i] = 1

            if tr.RNeut[i] >= 0.0 or tr.XNeut[i] >= 0.0:
                if self.connections[i] < 1:
                    self.ground[i] = 1

    def add_AutoTransformer(self, tr: altdss.AutoTrans):
        self.pd_unit = tr
        self.b_auto = True

        if tr.Windings > self.n_windings:
            self.n_windings = tr.Windings

        for i in range(tr.Windings):
            self.phase_a[i] = self.phase_b[i] = self.phase_c[i] = 1
            self.connections[i] = tr.Conns[i]  # type: ignore
            if i == 1:
                self.ground[i] = 1

    def build_vector_group(self):
        if self.b_auto:
            if self.n_windings < 3:
                self.vector_group = "YNa"
            else:
                self.vector_group = "YNad1"
        else:
            for i in range(self.n_windings):
                if self.phase_a[i] > 0 and self.phase_b[i] > 0 and self.phase_c[i] > 0:
                    if self.connections[i] > 0:
                        self.vector_group += "d"
                    else:
                        self.vector_group += "y"

                    if self.ground[i] > 0:
                        self.vector_group += "n"

                    if self.angles[i] > 0:
                        self.vector_group += str(self.angles[i])
                else:
                    self.vector_group += "i"

        if len(self.vector_group) > 0:
            self.vector_group = self.vector_group[0].upper() + self.vector_group[1::]


class Dummy(object):
    pass


class TransformerInfo:
    def __init__(self, max_wdg: int):
        self.max_wdg = 0
        self.wdg_list: list[Dummy] = []
        self.core_list: list[Dummy] = []
        self.mesh_list: list[Dummy] = []

        self.set_max_wdg(max_wdg)

    def set_max_wdg(self, max_wdg: int):
        if max_wdg > 0:
            self.max_wdg = max_wdg
            self.wdg_list = [Dummy() for i in range(max_wdg)]
            self.core_list = [Dummy() for i in range(max_wdg)]
            self.mesh_list = [Dummy() for i in range(int((max_wdg - 1) * max_wdg / 2))]


class DssExport(object):
    """
    Class for converting a DSS file into CIM XML

    ## Methods

    save

    ## Attributes

    dss
    graph

    Builds initial CIM object with (up to) three RDF triples: RDF.type as given by `rdf_type`,
    IdentifiedObject.name and IdentifiedObject.mRID. Only RDF.type is absolutely required;
    if `name` is None, it will be skipped, and if `skip_mrid` is True, it will not be explicitly
    added, although the object will be assigned a unique identifier (or assigned `mrid` if
    specified).

    ## Parameters

    rdf_type: str
    mrid: str (optional, default: None)
    name: str (optional, default: None)
    skip_mrid (optional, default: False)

    ## Returns

    URIRef

    Adds a RDF Triple (`subject`, `predicate`, `object`) to the RDF Graph, where the `predicate`
    is expected to be in the CIM Namespace, and `obj` will be cast to `Literal` unless it
    is an URIRef.

    ## Parameters

    subject: URIRef
    predicate: str
    obj: any

    ## Returns

    None
    """

    def __init__(self, dss_file: str, cim_namespace: str = _DEFAULT_CIM_NAMESPACE):
        self.raw_dss = odd
        self.raw_dss(f'redirect "{dss_file}"')

        self.dss = self.raw_dss.to_altdss()

        self.uuid_map = {}

        self.terminal_map = {}

        # for capacitor controls
        self.cap_map = {}

        # Transformer specific properties
        self.transformer_info: TransformerInfo | None = None
        self.transformer_banks = {}
        self.xfmrcodes = {}
        self.xfmrcode_uris = {}
        self.transformer_end_uris = {}
        self.transformer_terminal_uris = {}

        self.graph = Graph()
        self.cim = Namespace(cim_namespace + "#")
        self.graph.bind("cim", self.cim, override=True)

        self._add_IECVersion()

        self._convert_dss_to_rdf()

    def _get_kWRef_kVARref(self, load: altdss.Load) -> tuple[float, float]:
        cffi_ptr = load._ptr
        ptr_address = int(ffi.cast("uintptr_t", cffi_ptr))  # type: ignore
        ctypes_ptr = ctypes.c_void_p(ptr_address)

        load_obj = ctypes.cast(ctypes_ptr, ctypes.POINTER(TestLoadObj))

        return load_obj.contents.kWRef, load_obj.contents.kVARref

    def _convert_dss_to_rdf(self):
        self._add_ConnectivityNodes()
        self._add_EnergyConsumers()
        self._add_EnergySources()
        self._add_ACLineSegments_and_Switches()
        self._add_SynchronousMachines()
        self._add_PowerElectronicsConnections()
        self._add_LinearShuntCompensators()
        self._add_Transformers()
        self._add_RegulatingControls()

    def save(self, path: pathlib.PosixPath | str) -> None:
        self.graph.serialize(path, max_depth=1, format="pretty-xml")

    @staticmethod
    def _to_meters(units: str | altdss.LengthUnit) -> float:
        return unit_conversion.get(str(units), 1.0)

    @staticmethod
    def _to_per_meter(units: str | altdss.LengthUnit) -> float:
        return 1.0 / unit_conversion.get(str(units), 1.0)

    @staticmethod
    def _parse_busname(bus: str) -> str:
        return bus.split(".", 1)[0]

    @staticmethod
    def _is_grounded(buses: list[str], is_delta: bool) -> bool:
        is_grounded = False
        if not is_delta:
            for bus in buses:
                if ".0" in bus:
                    is_grounded = True

        return is_grounded

    @staticmethod
    def _fix_phases(phases: str) -> str | list[str]:
        _phases: str | list[str] = phases
        if phases.startswith("s"):
            if phases == "s12":
                _phases = ["s1", "s2"]
            else:
                _phases = [phases]

        return _phases

    def build_cim_obj(self, rdf_type: str, mrid: str | None = None, name: str | None = None, skip_mrid: bool = False) -> URIRef:
        if mrid is None:
            mrid = str(uuid4())
        node = URIRef(mrid)

        self.graph.add((node, RDF.type, self.cim[rdf_type]))
        if not skip_mrid:
            self.graph.add((node, self.cim["IdentifiedObject.mRID"], Literal(mrid)))
        if name is not None:
            self.graph.add((node, self.cim["IdentifiedObject.name"], Literal(name)))

        return node

    def add_triple(self, subject: URIRef, predicate: str, obj):
        if isinstance(obj, bool):
            self.graph.add((subject, self.cim[predicate], Literal(str(obj).lower())))
        elif isinstance(obj, URIRef):
            self.graph.add((subject, self.cim[predicate], obj))
        else:
            self.graph.add((subject, self.cim[predicate], Literal(str(obj))))

    def _add_SvStatus(self, source_node_uri: URIRef, in_service: bool):
        if f"SvStatus.{in_service}" not in self.uuid_map:
            node = self.build_cim_obj("SvStatus", skip_mrid=True)
            self.add_triple(node, "SvStatus.inService", in_service)
            self.add_triple(source_node_uri, "ConductingEquipment.SvStatus", node)

            self.uuid_map[f"SvStatus.{in_service}"] = str(node)
        else:
            self.add_triple(source_node_uri, "ConductingEquipment.SvStatus", URIRef(self.uuid_map[f"SvStatus.{in_service}"]))

    def _add_IECVersion(self):
        node = self.build_cim_obj("IEC61970CIMVersion", skip_mrid=True)
        self.add_triple(node, "IEC61970CIMVersion.version", "IEC61970CIM100")
        self.add_triple(node, "IEC61970CIMVersion.date", "2019-04-01")

    def _add_Location(self, obj_name: str, x_coords: list[float], y_coords: list[float], coord_system: str | None = None):
        # TODO: crsUrn
        if f"Location.{obj_name}_Location" not in self.uuid_map:
            node = self.build_cim_obj("Location", name=f"{obj_name}_Location")

            for i, (x, y) in enumerate(zip(x_coords, y_coords)):
                self._add_PositionPoint(node, x, y, i)

            self.uuid_map[f"Location.{obj_name}_Location"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"Location.{obj_name}_Location"])

    def _add_PositionPoint(self, location_uri: URIRef, x: float, y: float, seq: int):
        node = self.build_cim_obj("PositionPoint", skip_mrid=True)
        self.add_triple(node, "PositionPoint.sequenceNumber", seq)
        self.add_triple(node, "PositionPoint.xPosition", x)
        self.add_triple(node, "PositionPoint.yPosition", y)
        self.add_triple(node, "PositionPoint.Location", location_uri)

    def _add_BaseVoltage(self, source_uri: URIRef, bus: str):
        base_kv = math.sqrt(3) * self.dss.Bus.kVBase()[self.dss.Bus.Name().index(self._parse_busname(bus))]

        if f"BaseVoltage.{base_kv}" not in self.uuid_map:
            node = self.build_cim_obj("BaseVoltage", name=f"BaseV_{base_kv}")
            self.add_triple(node, "BaseVoltage.nominalVoltage", base_kv * 1000)
            self.uuid_map[f"BaseVoltage.{base_kv}"] = str(node)

        self.add_triple(source_uri, "ConductingEquipment.BaseVoltage", URIRef(self.uuid_map[f"BaseVoltage.{base_kv}"]))

        return base_kv

    def _add_ConnectivityNodes(self):
        for bus in self.dss.Bus:
            self._add_ConnectivityNode(bus.Name)
            self._add_Location(bus.Name, [bus.X], [bus.Y])

    def _add_ConnectivityNode(self, bus: str):
        if f"ConnectivityNode.{bus}" not in self.uuid_map:
            obj_uuid = str(uuid4())
            node = self.build_cim_obj("ConnectivityNode", name=bus)
            self.uuid_map[f"ConnectivityNode.{bus}"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"ConnectivityNode.{bus}"])

    def _add_Terminal(self, connecting_node: URIRef, element, bus: str | None = None, n_terminal: int = 1, phases="ABC"):
        _phases = list(phases)
        _phases.sort()
        phases = "".join(_phases)

        node = self.build_cim_obj("Terminal", name=f"{element.Name}_T{n_terminal}")

        self.add_triple(node, "ACDCTerminal.sequenceNumber", n_terminal)
        self.add_triple(node, "Terminal.phases", self.cim[f"PhaseCode.{phases}"])
        self.add_triple(node, "Terminal.ConductingEquipment", connecting_node)

        if bus is not None:
            cn_node = self._add_ConnectivityNode(bus)
            self.add_triple(node, "Terminal.ConnectivityNode", cn_node)

        return node

    def _add_OperationalLimitSet(self, subject_uri: URIRef, limit_type: str, normal_value: float, norm_max: float, norm_min: float = -math.inf, emerg_max: float = math.inf, emerg_min: float = -math.inf, bus: str | None = None):
        emerg = False
        if limit_type == "Voltage":
            emerg = emerg_min > -math.inf and emerg_max < math.inf

            name = f"OpLimV_{norm_min}-{norm_max}"
            if emerg:
                name += f"_{emerg_min}-{emerg_max}"
        elif limit_type == "Current":
            emerg = emerg_max < math.inf
            name = f"OpLimI_{norm_max}"
            if emerg:
                name += f"_{emerg_max}"
        else:
            # TODO: ActivePower, ApparentPower Limit Types
            logger.warning("OperationalLimitSet with type of '{limit_type}' is not yet supported.")
            return None

        if f"OperationalLimitSet.{name}" not in self.uuid_map:
            node = self.build_cim_obj("OperationalLimitSet", name=name)

            if limit_type == "Voltage":
                for limit_direction in ["low", "high"]:
                    limit_type_uri = self._add_OperationalLimitType(limit_direction, 5e9)
                    self._add_VoltageLimit(node, limit_type_uri, f"{name}_RangeA{limit_direction}", (norm_min if limit_direction == "low" else norm_max), normal_value)

                    if emerg:
                        limit_type_uri = self._add_OperationalLimitType(limit_direction, 60 * 60 * 24.0)
                        self._add_VoltageLimit(node, limit_type_uri, f"{name}_RangeB{limit_direction}", (emerg_min if limit_direction == "low" else emerg_max), normal_value)
            elif limit_type == "Current":
                limit_type_uri = self._add_OperationalLimitType("absoluteValue", 5e9)
                self._add_CurrentLimit(node, limit_type_uri, f"{name}_Norm", norm_max, normal_value)
                if emerg:
                    limit_type_uri = self._add_OperationalLimitType("absoluteValue", 60 * 60 * 24.0)
                    self._add_CurrentLimit(node, limit_type_uri, f"{name}_Emerg", emerg_max, normal_value)

            else:
                # TODO: ActivePower, ApparentPower Limit Types
                return None

            self.uuid_map[f"OperationalLimitSet.{name}"] = str(node)

        self.add_triple(subject_uri, "ACDCTerminal.OperationalLimitSet", URIRef(self.uuid_map[f"OperationalLimitSet.{name}"]))

        if bus is not None:
            cn_node = self._add_ConnectivityNode(bus)
            self.add_triple(cn_node, "ConnectivityNode.OperationalLimitSet", URIRef(self.uuid_map[f"OperationalLimitSet.{name}"]))

    def _add_OperationalLimitType(self, limit_direction: str, acceptable_duration: float):
        name = f"{limit_direction}Type_{acceptable_duration}s"

        if f"OperationalLimitType.{name}" not in self.uuid_map:
            node = self.build_cim_obj("OperationalLimitType", name=name)
            self.add_triple(node, "OperationalLimitType.direction", self.cim[f"OperationalLimitDirectionKind.{limit_direction}"])
            self.add_triple(node, "OperationalLimitType.acceptableDuration", acceptable_duration)
            self.uuid_map[f"OperationalLimitType.{name}"] = str(node)

        return URIRef(self.uuid_map[f"OperationalLimitType.{name}"])

    def _add_VoltageLimit(self, limit_set_uri: URIRef, limit_type_uri: URIRef, name: str, value: float, normal_value: float):
        if f"VoltageLimit.{name}" not in self.uuid_map:
            node = self.build_cim_obj("VoltageLimit", name=name)
            self.add_triple(node, "VoltageLimit.value", value)
            self.add_triple(node, "VoltageLimit.normalValue", normal_value)
            self.add_triple(node, "OperationalLimit.OperationalLimitType", limit_type_uri)
            self.add_triple(node, "OperationalLimit.OperationalLimitSet", limit_set_uri)
            self.uuid_map[f"VoltageLimit.{name}"] = str(node)

    def _add_CurrentLimit(self, limit_set_uri: URIRef, limit_type_uri: URIRef, name: str, value: float, normal_value: float):
        if f"CurrentLimit.{name}" not in self.uuid_map:
            node = self.build_cim_obj("CurrentLimit", name=name)
            self.add_triple(node, "CurrentLimit.value", value)
            self.add_triple(node, "CurrentLimit.normalValue", normal_value)
            self.add_triple(node, "OperationalLimit.OperationalLimitType", limit_type_uri)
            self.add_triple(node, "OperationalLimit.OperationalLimitSet", limit_set_uri)
            self.uuid_map[f"CurrentLimit.{name}"] = str(node)

    def _add_ActivePowerLimit(self):
        pass

    def _add_ApparentPowerLimit(self):
        pass

    def _add_EnergySources(self):
        for vsource in self.dss.Vsource:
            self._add_EnergySource(vsource)

    def _add_EnergySource(self, vsource: altdss.Vsource):
        node = self.build_cim_obj("EnergySource", name=vsource.Name)

        self.add_triple(node, "EnergySource.nominalVoltage", vsource.BasekV * 1000.0)
        self.add_triple(node, "EnergySource.voltageMagnitude", vsource.BasekV * 1000.0 * vsource.pu)
        self.add_triple(node, "EnergySource.voltageAngle", math.radians(vsource.Angle))
        self.add_triple(node, "EnergySource.r", vsource.R1)
        self.add_triple(node, "EnergySource.x", vsource.X1)
        self.add_triple(node, "EnergySource.r0", vsource.R0)
        self.add_triple(node, "EnergySource.x0", vsource.X0)
        self.add_triple(node, "Equipment.inService", vsource.Enabled)

        self._add_BaseVoltage(node, vsource.Bus1)

        for t, bus in enumerate([vsource.Bus1, vsource.Bus2]):
            busname = self._parse_busname(bus)
            phases = parse_phase_str(bus, n_phases=vsource.Phases)
            if phases:
                self._add_Terminal(node, vsource, bus=busname, n_terminal=t + 1, phases=phases)

        phases = parse_ordered_phase_str(vsource.Bus1, vsource.Phases)
        if phases != "ABC":
            for phase in phases:
                self._add_EnergySourcePhase()

    def _add_EnergySourcePhase(self):
        # TODO: EnergySourcePhase
        pass

    def _add_ACLineSegments_and_Switches(self):
        for line in self.dss.Line:
            if line.Switch:
                self._add_Switch(line)
            else:
                self._add_ACLineSegment(line)

    def _add_ACLineSegment(self, line: altdss.Line):
        node = self.build_cim_obj("ACLineSegment", name=line.Name)
        self.add_triple(node, "Equipment.inService", line.Enabled)
        self._add_BaseVoltage(node, line.Bus1)

        wires = [None for i in range(line.NumConductors())]
        if line.LineCode is not None:
            units = line.Units_str if line.Units_str != "none" else line.LineCode.Units_str
            self.add_triple(node, "Conductor.length", line.Length * self._to_meters(units))
            uri = self._add_PerLengthPhaseImedance(line.LineCode, units=units)
            self.add_triple(node, "ACLineSegment.PerLengthImpedance", uri)
        elif line.Geometry is not None:
            self.add_triple(node, "Conductor.length", line.Length * self._to_meters(line.Units_str))
            self._add_WireSpacingInfo(node, line.Geometry)
            wires = line.Geometry.Conductors
        elif line.Spacing is not None:
            self.add_triple(node, "Conductor.length", line.Length * self._to_meters(line.Units_str))
            self._add_WireSpacingInfo(node, line.Spacing)
            wires = line.Conductors
        else:
            uri = self._add_PerLengthPhaseImedance(line, name=f"{line.Name}_PUZ", nphases=line.NumPhases())
            self.add_triple(node, "ACLineSegment.PerLengthImpedance", uri)

        phases = parse_ordered_phase_str(line.Bus1, line.Phases)
        if phases == "s12":
            for seq, phase in enumerate(["s1", "s2"]):
                self._add_ACLineSegmentPhase(node, line, phase, seq + 1, wire=wires[seq])
        elif phases.startswith("s"):
            for seq, phase in enumerate([phases]):
                self._add_ACLineSegmentPhase(node, line, phase, seq + 1, wire=wires[seq])
        else:
            for seq, phase in enumerate([ph for ph in phases]):
                self._add_ACLineSegmentPhase(node, line, phase, seq + 1, wire=wires[seq])

        for i, bus in enumerate([line.Bus1, line.Bus2]):
            terminal_uri = self._add_Terminal(node, line, bus=self._parse_busname(bus), n_terminal=i + 1, phases=parse_ordered_phase_str(bus, line.Phases))
            self.terminal_map[(type(line), line.Name, i + 1)] = terminal_uri
            self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=line.NormAmps, norm_max=line.NormAmps, emerg_max=line.EmergAmps)

    def _add_ACLineSegmentPhase(self, aclinesegment_uri: URIRef, line: altdss.Line, phase: str, sequence: int, wire: altdss.WireData | altdss.CNData | altdss.TSData | None = None):
        node = self.build_cim_obj("ACLineSegmentPhase", name=f"{line.Name}_{phase}")
        self.add_triple(node, "ACLineSegmentPhase.phase", self.cim[f"SinglePhaseKind.{phase}"])
        self.add_triple(node, "ACLineSegmentPhase.sequenceNumber", sequence)
        self.add_triple(node, "ACLineSegmentPhase.ACLineSegment", aclinesegment_uri)
        if wire is not None:
            if isinstance(wire, altdss.WireData):
                n = self.build_cim_obj("OverheadWireInfo")
                self._add_WireInfo(n, wire)
                self.add_triple(node, "PowerSystemResource.AssetDatasheet", n)
            elif isinstance(wire, altdss.TSData):
                n = self.build_cim_obj("TapeShieldCableInfo")
                self._add_WireInfo(n, wire)
                self._add_CableInfo(n, wire)
                self._add_TapeShieldCableInfo(n, wire)
                self.add_triple(node, "PowerSystemResource.AssetDatasheet", n)
            elif isinstance(wire, altdss.CNData):
                n = self.build_cim_obj("ConcentricNeutralCableInfo")
                self._add_WireInfo(n, wire)
                self._add_CableInfo(n, wire)
                self._add_ConcentricNeutralCableInfo(n, wire)
                self.add_triple(node, "PowerSystemResource.AssetDatasheet", n)

    def _add_WireSpacingInfo(self, subject: URIRef, linespacing: altdss.LineSpacing):
        node = self.build_cim_obj("WireSpacingInfo", name=linespacing.Name)
        self.add_triple(node, "WireSpacingInfo.usage", self.cim[f"WireUsageKind.distribution"])
        self.add_triple(node, "WireSpacingInfo.phaseWireCount", 1)
        self.add_triple(node, "WireSpacingInfo.phaseWireSpacing", 0.0)
        if getattr(linespacing, "LineType", 0) == 1 or getattr(linespacing, "H", [0.0])[0] > 0.0:
            self.add_triple(node, "WireSpacingInfo.isCable", False)
        else:
            self.add_triple(node, "WireSpacingInfo.isCable", True)

        for i in range(linespacing.NConds):
            wp = self.build_cim_obj("WirePosition", name=f"WP_{linespacing.Name}_{i+1}")
            self.add_triple(wp, "WirePosition.WireSpacingInfo", node)
            self.add_triple(wp, "WirePosition.sequenceNumber", i + 1)
            self.add_triple(wp, "WirePosition.xCoord", linespacing.X[i] * self._to_meters(linespacing.Units_str))
            self.add_triple(wp, "WirePosition.yCoord", linespacing.H[i] * self._to_meters(linespacing.Units_str))

        self.add_triple(subject, "ACLineSegment.WireSpacingInfo", node)

    def _add_CableInfo(self, node: URIRef, cable):
        self.add_triple(node, "WireInfo.insulated", True)
        self.add_triple(node, "WireInfo.insulationThickness", cable.InsLayer * self._to_meters(cable.RadUnits_str))
        self.add_triple(node, "WireInfo.insulationMaterial", self.cim["WireInsulationKind.crosslinkedPolyethylene"])
        self.add_triple(node, "CableInfo.outerJacketKind", self.cim["CableOuterJacketKind.none"])
        self.add_triple(node, "CableInfo.constructionKind", self.cim["CableConstructionKind.stranded"])
        self.add_triple(node, "CableInfo.isStrandFill", False)
        self.add_triple(node, "CableInfo.diameterOverCore", (cable.DiaIns - 2.0 * cable.InsLayer) * self._to_meters(cable.RadUnits_str))
        self.add_triple(node, "CableInfo.diameterOverInsulation", cable.DiaIns * self._to_meters(cable.RadUnits_str))
        self.add_triple(node, "CableInfo.diameterOverJacket", cable.DiaCable * self._to_meters(cable.RadUnits_str))
        self.add_triple(node, "CableInfo.nominalTemperature", 90.0)
        self.add_triple(node, "CableInfo.relativePermittivity", cable.EpsR)

    def _add_TapeShieldCableInfo(self, node: URIRef, tsdata: altdss.TSData):
        self.add_triple(node, "CableInfo.diameterOverScreen", (tsdata.DiaShield - 2.0 * tsdata.TapeLayer) * self._to_meters(tsdata.RadUnits_str))
        self.add_triple(node, "TapeShieldCableInfo.tapeLap", tsdata.TapeLap)
        self.add_triple(node, "TapeShieldCableInfo.tapeThickness", tsdata.TapeLayer * self._to_meters(tsdata.RadUnits_str))
        self.add_triple(node, "CableInfo.shieldMaterial", self.cim["CableShieldMaterialKind.copper"])
        self.add_triple(node, "CableInfo.sheathAsNeutral", True)

    def _add_ConcentricNeutralCableInfo(self, node: URIRef, cndata: altdss.CNData):
        self.add_triple(node, "CableInfo.diameterOverScreen", (cndata.DiaCable - 2.0 * cndata.DiaStrand) * self._to_meters(cndata.RadUnits_str))
        self.add_triple(node, "ConcentricNeutralCableInfo.diameterOverNeutral", cndata.DiaCable * self._to_meters(cndata.RadUnits_str))
        self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRadius", cndata.DiaStrand / 2.0 * self._to_meters(cndata.RadUnits_str))
        self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandGmr", cndata.GMRStrand * self._to_meters(cndata.GMRUnits_str))
        self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRDC20", cndata.RStrand * self._to_per_meter(cndata.RUnits_str))
        self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandCount", cndata.k)

    def _add_WireInfo(self, node: URIRef, wire: altdss.WireData | altdss.TSData | altdss.CNData):
        self.add_triple(node, "WireInfo.sizeDescription", wire.Name)
        material = "other"
        if "aa" in wire.Name.lower():
            material = "aluminum"
        elif "acsr" in wire.Name.lower():
            material = "acsr"
        elif "cu" in wire.Name.lower():
            material = "copper"
        elif "ehs" in wire.Name.lower():
            material = "steel"
        self.add_triple(node, "WireInfo.material", self.cim[f"WireMaterialKind.{material}"])
        self.add_triple(node, "WireInfo.gmr", wire.GMRAC * self._to_meters(wire.GMRUnits_str))
        self.add_triple(node, "WireInfo.radius", wire.Radius * self._to_meters(wire.RadUnits_str))
        self.add_triple(node, "WireInfo.rDC20", wire.RDC * self._to_per_meter(wire.RUnits_str))
        self.add_triple(node, "WireInfo.rAC25", wire.RAC * self._to_per_meter(wire.RUnits_str))
        self.add_triple(node, "WireInfo.rAC50", wire.RAC * self._to_per_meter(wire.RUnits_str))
        self.add_triple(node, "WireInfo.rAC75", wire.RAC * self._to_per_meter(wire.RUnits_str))
        self.add_triple(node, "WireInfo.ratedCurrent", wire.NormAmps)
        self.add_triple(node, "WireInfo.strandCount", 0)
        self.add_triple(node, "WireInfo.coreStrandCount", 0)
        self.add_triple(node, "WireInfo.coreRadius", 0.0)

    def _add_SwitchInfo(self, node: URIRef, line: altdss.Line):
        self.add_triple(node, "SwitchInfo.ratedCurrent", line.NormAmps)
        self.add_triple(node, "SwitchInfo.breakingCapacity", line.EmergAmps)

    def _add_PerLengthPhaseImedance(self, linecode: altdss.LineCode, name: str = "", nphases: int | None = None, units: str = "none") -> URIRef:
        if f"PerLengthPhaseImpedance.{name if name else linecode.Name}" not in self.uuid_map:
            node = self.build_cim_obj("PerLengthPhaseImpedance", name=name if name else linecode.Name)
            self.add_triple(node, "PerLengthPhaseImpedance.conductorCount", nphases if nphases is not None else linecode.NPhases)

            self._add_PhaseImpedanceData(node, linecode, nphases=nphases, units=units)

            self.uuid_map[f"PerLengthPhaseImpedance.{name if name else linecode.Name}"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"PerLengthPhaseImpedance.{name if name else linecode.Name}"])

    def _add_PhaseImpedanceData(self, phase_impedance_uri: URIRef, linecode: altdss.LineCode, nphases: int | None = None, units: str = "none"):
        units = linecode.Units_str if linecode.Units_str != "none" else units
        for col in range(1, (nphases if nphases is not None else linecode.NPhases) + 1):  # iterate over rows (upper triangular only)
            for row in range(col, (nphases if nphases is not None else linecode.NPhases) + 1):
                node = self.build_cim_obj("PhaseImpedanceData", skip_mrid=True)
                self.add_triple(node, "PhaseImpedanceData.row", row)
                self.add_triple(node, "PhaseImpedanceData.column", col)
                # calculate the correct index in RMatrix, XMatrix, CMatrix
                i = (row - 1) * (nphases if nphases is not None else linecode.NPhases) + (col - 1)
                self.add_triple(node, "PhaseImpedanceData.r", linecode.RMatrix[i] * self._to_per_meter(units))
                self.add_triple(node, "PhaseImpedanceData.x", linecode.XMatrix[i] * self._to_per_meter(units))
                self.add_triple(node, "PhaseImpedanceData.b", linecode.CMatrix[i] * 2 * math.pi * linecode.BaseFreq / 1e9 * self._to_per_meter(units))
                self.add_triple(node, "PhaseImpedanceData.PhaseImpedance", phase_impedance_uri)

    def _add_Switch(self, line: altdss.Line):
        # TODO: Type of switch
        node = self.build_cim_obj("Switch", name=line.Name)
        self.add_triple(node, "Equipment.inService", line.Enabled)
        self.add_triple(node, "Switch.open", not line.Enabled)
        self.add_triple(node, "Switch.normalOpen", not line.Enabled)

        # Add SwitchInfo to Switch
        sw_info = self.build_cim_obj("SwitchInfo", name=f"SwInfo_{line.Name}")
        self._add_SwitchInfo(sw_info, line)
        self.add_triple(node, "PowerSystemResource.AssetDatasheet", sw_info)

        phases_side_1 = parse_ordered_phase_str(line.Bus1, line.Phases)
        phases_side_2 = parse_ordered_phase_str(line.Bus2, line.Phases)
        if phases_side_1 == "s12" and phases_side_2 == "s12":
            for seq, phase in enumerate(["s1", "s2"]):
                self._add_SwitchPhase(node, line, phases_side_1, phases_side_2)
        elif phases_side_1.startswith("s") and phases_side_2.startswith("s"):
            for seq, (phase_1, phase_2) in enumerate(zip([phases_side_1], [phases_side_2])):
                self._add_SwitchPhase(node, line, phase_1, phase_2)
        else:
            for seq, (phase_1, phase_2) in enumerate(list(zip(phases_side_1, phases_side_2))):
                self._add_SwitchPhase(node, line, phase_1, phase_2)

        for i, bus in enumerate([line.Bus1, line.Bus2]):
            self._add_Terminal(node, line, bus=self._parse_busname(bus), n_terminal=i + 1, phases=parse_ordered_phase_str(bus, line.Phases))

    def _add_SwitchPhase(self, switch_uri: URIRef, line: altdss.Line, phase_side_1: str, phase_side_2: str):
        node = self.build_cim_obj("SwitchPhase", name=f"{line.Name}_{phase_side_1}{phase_side_2}")
        self.add_triple(node, "SwitchPhase.phaseSide1", self.cim[f"SinglePhaseKind.{phase_side_1}"])
        self.add_triple(node, "SwitchPhase.phaseSide2", self.cim[f"SinglePhaseKind.{phase_side_2}"])
        self.add_triple(node, "SwitchPhase.Switch", switch_uri)

    def _add_EnergyConsumers(self):
        for load in self.dss.Load:
            self._add_EnergyConsumer(load)

    def _add_EnergyConsumer(self, load):
        node = self.build_cim_obj("EnergyConsumer", name=load.Name)

        kW, kvar = self._get_kWRef_kVARref(load)

        self.add_triple(node, "EnergyConsumer.p", kW * 1000.0)
        self.add_triple(node, "EnergyConsumer.q", kvar * 1000.0)
        self.add_triple(node, "EnergyConsumer.customerCount", load.NumCust)
        self.add_triple(node, "EnergyConsumer.grounded", self._is_grounded([load.Bus1], load.Conn != 0))
        self.add_triple(node, "Equipment.inService", load.Enabled)
        base_kv = self._add_BaseVoltage(node, load.Bus1)

        if load.Conn_str == "delta":
            self.add_triple(node, "EnergyConsumer.phaseConnection", self.cim["PhaseShuntConnectionKind.D"])
        elif load.Conn_str == "wye":
            self.add_triple(node, "EnergyConsumer.phaseConnection", self.cim["PhaseShuntConnectionKind.Y"])
        else:
            raise Exception(f"Load.{load.Name}: unrecognized load connection '{load.Conn_str}'")

        lrc_node = self._add_LoadResponseCharacteristic(load.Model)
        if lrc_node is not None:
            self.add_triple(node, "EnergyConsumer.LoadResponse", lrc_node)

        phases = parse_phase_str(load.Bus1, load.Phases, load.kV, load.Conn != 0)
        self._add_EnergyConsumerPhases(node, load, phases, kW, kvar)
        terminal_uri = self._add_Terminal(node, load, bus=self._parse_busname(load.Bus1), phases=phases)

        self._add_OperationalLimitSet(terminal_uri, "Voltage", normal_value=base_kv * 1000, norm_min=load.VMinpu * base_kv * 1000, norm_max=load.VMaxpu * base_kv * 1000, bus=self._parse_busname(load.Bus1))

        # EnergyConsumerSchedule
        self._add_EnergyConnectionProfile(node, load)

    def _add_EnergyConsumerPhases(self, energy_consumer_uri: URIRef, load: altdss.Load, phases: str, kW: float | None = None, kvar: float | None = None):
        kW = load.kW if kW is None else kW
        kvar = load.kvar if kvar is None else kvar

        _phases: str | list[str] = phases

        if load.Phases == 3:
            return None
        else:
            if phases.startswith("s"):
                if phases == "s12":
                    _phases = ["s1", "s2"]
                else:
                    _phases = [phases]

            for ph in _phases:
                node = self.build_cim_obj("EnergyConsumerPhase", name=f"{load.Name}_{ph}")
                self.add_triple(node, "EnergyConsumerPhase.p", kW * 1000.0 / load.Phases)
                self.add_triple(node, "EnergyConsumerPhase.q", kvar * 1000.0 / load.Phases)
                self.add_triple(node, "EnergyConsumerPhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "EnergyConsumerPhase.EnergyConsumer", energy_consumer_uri)

    def _add_LoadResponseCharacteristic(self, model: int):
        if f"LoadResponseCharacteristic.{model}" not in self.uuid_map:
            if model == 1:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Constant kVA")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantPower", 100)
            elif model == 2:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Constant Z")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantImpedance", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            elif model == 3:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Motor")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            elif model == 4:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Mix Motor/Res")
                self.add_triple(node, "LoadResponseCharacteristic.exponentModel", True)
                self.add_triple(node, "LoadResponseCharacteristic.pVoltageExponent", 1)
                self.add_triple(node, "LoadResponseCharacteristic.qVoltageExponent", 2)
            elif model == 5:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Constant I")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantCurrent", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantCurrent", 100)
            elif model == 6:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Variable P, Fixed Q")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantPower", 100)
            elif model == 7:
                node = self.build_cim_obj("LoadResponseCharacteristic", name="Variable P, Fixed X")
                self.add_triple(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self.add_triple(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            else:
                return None

            self.uuid_map[f"LoadResponseCharacteristic.{model}"] = str(node)

            return node

        else:
            return URIRef(self.uuid_map[f"LoadResponseCharacteristic.{model}"])

    def _add_EnergyConnectionProfile(self, subject_uri, load: altdss.Load):
        load_profile_names = ["Daily", "Duty", "Growth", "Yearly", "CVRCurve", "Spectrum"]
        ecp_name = ":".join(["Load"] + [(getattr(load, attr).Name if getattr(load, attr) is not None else "") for attr in load_profile_names])

        loadshape_uris = []
        if f"EnergyConnectionProfile.{ecp_name}" not in self.uuid_map:
            node = self.build_cim_obj("EnergyConnectionProfile", name=ecp_name)
            for attr in load_profile_names:
                obj = getattr(load, attr)
                if obj is not None:
                    if attr == "CVRCurve":
                        self.add_triple(node, "EnergyConnectionProfile.dssLoadCvrCurve", obj.Name)
                    elif attr == "Growth":
                        self.add_triple(node, "EnergyConnectionProfile.dssLoadGrowth", obj.Name)
                    else:
                        self.add_triple(node, f"EnergyConnectionProfile.dss{attr}", obj.Name)
                        if attr in ["Daily", "Yearly", "Duty", "CVRCurve"]:
                            loadshape_uris.append(self._add_EnergyConsumerSchedule(subject_uri, obj))
            self.uuid_map[f"EnergyConnectionProfile.{ecp_name}"] = str(node)
        else:
            for attr in ["Daily", "Duty", "Yearly", "CVRCurve"]:
                loadshape = getattr(load, attr)
                if loadshape is not None:
                    loadshape_uris.append(URIRef(self.uuid_map[f"EnergyConsumerSchedule.{loadshape.Name}"]))

        self.add_triple(URIRef(self.uuid_map[f"EnergyConnectionProfile.{ecp_name}"]), "EnergyConnectionProfile.EnergyConnections", subject_uri)
        for uri in loadshape_uris:
            self.add_triple(subject_uri, "EnergyConsumer.LoadProfile", uri)

    def _add_EnergyConsumerSchedule(self, subject_uri: URIRef, loadshape: altdss.LoadShape):
        # TODO: handle irregular time points
        if f"EnergyConsumerSchedule.{loadshape.Name}" not in self.uuid_map:
            node = self.build_cim_obj("EnergyConsumerSchedule", name=loadshape.Name)

            pmult = loadshape.PMult
            qmult = loadshape.QMult

            if loadshape.UseActual:
                self.add_triple(node, "BasicIntervalSchedule.value1Unit", "UnitSymbol.W")
                self.add_triple(node, "BasicIntervalSchedule.value2Unit", "UnitSymbol.VAr")
                pmult *= 1000
                qmult *= 1000
            else:
                self.add_triple(node, "BasicIntervalSchedule.value1Unit", "UnitSymbol.none")
                self.add_triple(node, "BasicIntervalSchedule.value2Unit", "UnitSymbol.none")

            self.add_triple(node, "EnergyConsumerSchedule.timeStep", loadshape.SInterval)

            if qmult.size == 0:
                qmult = pmult

            for i, (p, q) in enumerate(zip(pmult, qmult)):
                self._add_RegularTimePoint(node, i, p, q)

            self.uuid_map[f"EnergyConsumerSchedule.{loadshape.Name}"] = str(node)

        return URIRef(self.uuid_map[f"EnergyConsumerSchedule.{loadshape.Name}"])

    def _add_RegularTimePoint(self, subject_uri: URIRef, sequence: int, value1: float, value2: float):
        node = self.build_cim_obj("RegularTimePoint", skip_mrid=True)
        self.add_triple(node, "RegularTimePoint.sequenceNumber", sequence + 1)  # adjust/shift sequence number from 0 to 1.
        self.add_triple(node, "RegularTimePoint.value1", value1)
        self.add_triple(node, "RegularTimePoint.value2", value2)
        self.add_triple(node, "RegularTimePoint.IntervalSchedule", subject_uri)

    def _add_LinearShuntCompensators(self):
        for cap in self.dss.Capacitor:
            self._add_LinearShuntCompensator(cap)

    def _add_LinearShuntCompensator(self, cap: altdss.Capacitor):
        node = self.build_cim_obj("LinearShuntCompensator", name=cap.Name)

        b = 0.001 * cap.kvar / cap.kV**2 / cap.NumSteps

        self.add_triple(node, "ShuntCompensator.nomU", cap.kV * 1000.0)
        self.add_triple(node, "LinearShuntCompensator.bPerSection", b[0])
        self.add_triple(node, "LinearShuntCompensator.gPerSection", 0.0)
        if cap.Conn == 0:
            self.add_triple(node, "ShuntCompensator.phaseConnection", self.cim[f"PhaseShuntConnectionKind.Y"])
            self.add_triple(node, "LinearShuntCompensator.b0PerSection", b[0])
        else:
            self.add_triple(node, "ShuntCompensator.phaseConnection", self.cim[f"PhaseShuntConnectionKind.D"])
            self.add_triple(node, "LinearShuntCompensator.grounded", False)
            self.add_triple(node, "LinearShuntCompensator.b0PerSection", 0.0)

        self.add_triple(node, "LinearShuntCompensator.g0PerSection", 0.0)
        self.add_triple(node, "ShuntCompensator.normalSections", cap.NumSteps)
        self.add_triple(node, "ShuntCompensator.maximumSections", cap.NumSteps)
        self.add_triple(node, "Equipment.inService", cap.Enabled)

        delay = 0.0
        for capcontrol in self.dss.CapControl:
            if capcontrol.Capacitor_str == cap.Name:
                delay = capcontrol.Delay
                break

        self.add_triple(node, "ShuntCompensator.aVRDelay", delay)

        self.add_triple(node, "ShuntCompensator.sections", sum([1 if cap.States[i] else 0 for i in range(cap.NumSteps)]))

        terminal_uri = self._add_Terminal(node, cap, bus=self._parse_busname(cap.Bus1), phases=parse_phase_str(cap.Bus1, cap.Phases))
        base_kv = self._add_BaseVoltage(node, cap.Bus1)
        self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=cap.NormAmps, norm_max=cap.NormAmps, emerg_max=cap.EmergAmps)

        self.cap_map[cap.Name] = {"uri": node, "terminal": terminal_uri}
        self.terminal_map[(type(cap), cap.Name, 1)] = terminal_uri
        # TODO, handle multi-terminal capacitors
        self.terminal_map[(type(cap), cap.Name, 2)] = terminal_uri

    def _add_SynchronousMachines(self):
        for gen in self.dss.Generator:
            self._add_SynchronousMachine(gen)

    def _add_SynchronousMachine(self, gen: altdss.Generator):
        node = self.build_cim_obj("SynchronousMachine", name=gen.Name)
        self.add_triple(node, "RotatingMachine.p", -gen.kW * 1000)
        self.add_triple(node, "RotatingMachine.q", -gen.kvar * 1000)
        self.add_triple(node, "RotatingMachine.ratedS", gen.kVA * 1000)
        self.add_triple(node, "RotatingMachine.ratedU", gen.kV * 1000)
        self.add_triple(node, "Equipment.inService", gen.Enabled)
        self.add_triple(node, "RotatingMachine.ratedPowerFactor", gen.PF)
        self.add_triple(node, "SynchronousMachine.maxQ", ((gen.kVA) ** 2 - (gen.kVA * gen.PF) ** 2) ** (1 / 2) * 1000)
        self.add_triple(node, "SynchronousMachine.minQ", -(((gen.kVA) ** 2 - (gen.kVA * gen.PF) ** 2) ** (1 / 2)) * 1000)

        gu_node = self.build_cim_obj("GeneratingUnit", name=f"{gen.Name}_GenUnit")
        self.add_triple(gu_node, "GeneratingUnit.minOperatingP", 0.0)
        self.add_triple(gu_node, "GeneratingUnit.maxOperatingP", gen.kVA * gen.PF * 1000)

        self.add_triple(node, "RotatingMachine.GeneratingUnit", gu_node)

        phases = parse_phase_str(gen.Bus1, gen.Phases)
        self._add_SynchronousMachinePhases(node, gen, phases)

        terminal_uri = self._add_Terminal(node, gen, bus=self._parse_busname(gen.Bus1), phases=phases)
        base_kv = self._add_BaseVoltage(node, gen.Bus1)
        self._add_OperationalLimitSet(terminal_uri, "Voltage", normal_value=base_kv * 1000, norm_min=gen.VMinpu * base_kv * 1000, norm_max=gen.VMaxpu * base_kv * 1000, bus=self._parse_busname(gen.Bus1))

    def _add_SynchronousMachinePhases(self, subject_uri: URIRef, gen: altdss.Generator, phases: str):
        if gen.Phases == 3:
            return None
        else:
            for ph in self._fix_phases(phases):
                node = self.build_cim_obj("SynchronousMachinePhase", name=f"{gen.Name}_{ph}")
                self.add_triple(node, "SynchronousMachinePhase.p", -gen.kW * 1000.0 / gen.Phases)
                self.add_triple(node, "SynchronousMachinePhase.q", -gen.kvar * 1000.0 / gen.Phases)
                self.add_triple(node, "SynchronousMachinePhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "SynchronousMachinePhase.SynchronousMachine", subject_uri)

    def _add_PowerElectronicsConnections(self):
        for pec_type in ["PVSystem", "Storage"]:
            for pec in getattr(self.dss, pec_type):
                pec_node = self.build_cim_obj("PowerElectronicsConnection", name=pec.Name)

                if pec_type == "PVSystem":
                    self._add_PhotoVoltaicUnit(pec_node, pec)
                elif pec_type == "Storage":
                    self._add_BatteryUnit(pec_node, pec)

    def _add_BatteryPhases(self, subject_uri: URIRef, storage: altdss.Storage, phases: str):
        if storage.Phases == 3:
            return None
        else:
            for ph in self._fix_phases(phases):
                node = self.build_cim_obj("PowerElectronicsConnectionPhase", name=f"{storage.Name}_{ph}")
                self.add_triple(node, "PowerElectronicsConnectionPhase.p", -storage.kW * 1000.0 / storage.Phases)
                self.add_triple(node, "PowerElectronicsConnectionPhase.q", -storage.kvar * 1000.0 / storage.Phases)
                self.add_triple(node, "PowerElectronicsConnectionPhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "PowerElectronicsConnectionPhase.PowerElectronicsConnection", subject_uri)

    def _add_PhotoVoltaicPhases(self, subject_uri: URIRef, solar: altdss.PVSystem, phases: str):
        if solar.Phases == 3:
            return None
        else:
            for i, ph in enumerate(self._fix_phases(phases)):
                node = self.build_cim_obj("PowerElectronicsConnectionPhase", name=f"{solar.Name}_{ph}")
                self.add_triple(node, "PowerElectronicsConnectionPhase.p", solar.Powers()[i].real * 1000.0)
                self.add_triple(node, "PowerElectronicsConnectionPhase.q", solar.Powers()[i].imag * 1000.0)
                self.add_triple(node, "PowerElectronicsConnectionPhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "PowerElectronicsConnectionPhase.PowerElectronicsConnection", subject_uri)

    def _add_PhotoVoltaicUnit(self, subject_uri: URIRef, solar: altdss.PVSystem):
        node = self.build_cim_obj("PhotoVoltaicUnit", name=f"{solar.Name}_PVPanels")
        self.add_triple(node, "PowerElectronicsUnit.minP", min(solar.pctCutIn, solar.pctCutOut) / 100.0 * solar.kVA * 1000.0)
        self.add_triple(node, "PowerElectronicsUnit.maxP", solar.Pmpp * 1000.0)

        self.add_triple(subject_uri, "PowerElectronicsConnection.PowerElectronicsUnit", node)

        self.add_triple(subject_uri, "PowerElectronicsConnection.maxIFault", 1 / solar.VMinpu)
        self.add_triple(subject_uri, "PowerElectronicsConnection.p", sum(solar.Powers()).real * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.q", sum(solar.Powers()).imag * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.ratedS", solar.kVA * 1000.0)
        if solar.Phases == 1:
            self.add_triple(subject_uri, "PowerElectronicsConnection.ratedU", solar.kV * 1000.0 * math.sqrt(3))
        else:
            self.add_triple(subject_uri, "PowerElectronicsConnection.ratedU", solar.kV * 1000.0)

        # TODO: PhotoVoltaicUnit Impedance
        # self.add_triple(subject_uri, "PowerElectronicsConnection.r", ...)
        # self.add_triple(subject_uri, "PowerElectronicsConnection.x", ...)

        self.add_triple(subject_uri, "PowerElectronicsConnection.maxQ", solar.kvarMax * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.minQ", -solar.kvarMaxAbs * 1000.0)
        self.add_triple(subject_uri, "Equipment.inService", solar.Enabled)

        self.add_triple(subject_uri, "PowerElectronicsConnection.PowerElectronicsUnit", node)

        phases = parse_phase_str(solar.Bus1, solar.Phases)
        self._add_PhotoVoltaicPhases(subject_uri, solar, phases)

        terminal_uri = self._add_Terminal(subject_uri, solar, bus=self._parse_busname(solar.Bus1), phases=phases)
        base_kv = self._add_BaseVoltage(subject_uri, solar.Bus1)
        self._add_OperationalLimitSet(terminal_uri, "Voltage", normal_value=base_kv * 1000, norm_min=solar.VMinpu * base_kv * 1000, norm_max=solar.VMaxpu * base_kv * 1000)

    def _add_BatteryUnit(self, subject_uri: URIRef, storage: altdss.Storage):
        node = self.build_cim_obj("BatteryUnit", name=f"{storage.Name}_Cells")

        self.add_triple(node, "PowerElectronicsUnit.minP", -storage.kWRated * storage.pctCharge / 100.0 * 1000.0)
        self.add_triple(node, "PowerElectronicsUnit.maxP", storage.kWRated * storage.pctDischarge / 100.0 * 1000.0)

        self.add_triple(node, "BatteryUnit.storedE", storage.kWhStored * 1000.0)
        self.add_triple(node, "BatteryUnit.ratedE", storage.kWhRated * 1000.0)

        bat_eff = self.build_cim_obj("BatteryUnitEfficiency", skip_mrid=True)

        self.add_triple(bat_eff, "BatteryUnitEfficiency.reserveEnergy", storage.pctReserve)
        self.add_triple(bat_eff, "BatteryUnitEfficiency.limitEnergy", storage.pctkWRated)
        self.add_triple(bat_eff, "BatteryUnitEfficiency.efficiencyDischarge", storage.pctEffDischarge)
        self.add_triple(bat_eff, "BatteryUnitEfficiency.efficiencyCharge", storage.pctEffCharge)
        self.add_triple(bat_eff, "BatteryUnitEfficiency.BatteryUnit", node)

        self.add_triple(subject_uri, "PowerElectronicsConnection.maxIFault", 1 / storage.VMinpu)
        self.add_triple(subject_uri, "PowerElectronicsConnection.p", storage.kW * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.q", storage.kvar * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.ratedS", storage.kVA * 1000.0)
        if storage.Phases == 1:
            self.add_triple(subject_uri, "PowerElectronicsConnection.ratedU", storage.kV * 1000.0 * math.sqrt(3))
        else:
            self.add_triple(subject_uri, "PowerElectronicsConnection.ratedU", storage.kV * 1000.0)

        # TODO: BatteryUnit Impedance
        # self.add_triple(subject_uri, "PowerElectronicsConnection.r", ...)
        # self.add_triple(subject_uri, "PowerElectronicsConnection.x", ...)

        self.add_triple(subject_uri, "PowerElectronicsConnection.maxQ", storage.kvarMax * 1000.0)
        self.add_triple(subject_uri, "PowerElectronicsConnection.minQ", -storage.kvarMaxAbs * 1000.0)
        self.add_triple(subject_uri, "Equipment.inService", storage.Enabled)

        self.add_triple(subject_uri, "PowerElectronicsConnection.PowerElectronicsUnit", node)

        phases = parse_phase_str(storage.Bus1, storage.Phases)
        self._add_BatteryPhases(subject_uri, storage, phases)

        terminal_uri = self._add_Terminal(subject_uri, storage, bus=self._parse_busname(storage.Bus1), phases=phases)
        base_kv = self._add_BaseVoltage(subject_uri, storage.Bus1)
        self._add_OperationalLimitSet(terminal_uri, "Voltage", normal_value=base_kv * 1000, norm_min=storage.VMinpu * base_kv * 1000, norm_max=storage.VMaxpu * base_kv * 1000)

    def _add_Transformers(self):
        transformer_wdgs = self.dss.Transformer.Windings.to_list()
        if transformer_wdgs is not None:
            max_wdg = max(transformer_wdgs)
        else:
            max_wdg = 3

        max_wdg = 3 if max_wdg < 3 else max_wdg

        self.transformer_info = TransformerInfo(max_wdg)

        for tr in self.dss.Transformer:
            if tr.XfmrCode is None and tr.NumPhases() != 3:
                code_id = f"CIMXfmrCode_{tr.Name}"
                self.xfmrcodes[code_id] = tr
            elif tr.XfmrCode is not None:
                code_id = tr.XfmrCode_str
                self.xfmrcodes[code_id] = tr.XfmrCode

        for xc_id, xc in self.xfmrcodes.items():
            self.xfmrcode_uris[xc_id] = self._add_TransformerTankInfo(xc, xc_id)

        for tr in self.dss.Transformer:
            if tr.Bank == "":
                bank_id = f"{tr.Name}"
            else:
                bank_id = tr.Bank

            has_tank = True
            if tr.XfmrCode is None and tr.NumPhases() == 3:
                has_tank = False

            if bank_id not in self.transformer_banks:
                self.transformer_banks[bank_id] = TransformerBank(max_wdg, bank_id, str(uuid4()))

            bank = self.transformer_banks[bank_id]
            bank.add_Transformer(tr)
            for i in range(tr.Windings):
                self.transformer_info.wdg_list[i].local_name = f"{tr.Name}_End_{i+1}"  # type: ignore
                self.transformer_info.wdg_list[i].uuid = str(uuid4())  # type: ignore
            self.transformer_info.core_list[0].local_name = f"{tr.Name}_Yc"  # type: ignore
            self.transformer_info.core_list[0].uuid = str(uuid4())  # type: ignore
            for i in range(int((max_wdg - 1) * max_wdg / 2)):
                self.transformer_info.mesh_list[i].local_name = f"{tr.Name}_Zsc_{i+1}"  # type: ignore
                self.transformer_info.mesh_list[i].uuid = str(uuid4())  # type: ignore

            if has_tank:
                tank_uri = self._add_TransformerTank(tr, bank_id)
                self._add_TransformerTankEnd(tank_uri, tr)

            if not has_tank:
                self._add_CoreAdmittance(tr)
                self._add_MeshImpedance(tr)
                self._add_PowerTransformerEnd(tr, bank)

            for tname, term_uri in self.transformer_terminal_uris.items():
                if tname.startswith(f"Transformer={tr.Name}="):
                    bank.terminal_uris.append(term_uri)

        for atr in self.dss.AutoTrans:
            bank_id = f"={atr.Name}" if atr.Bank is None else atr.Bank
            if bank_id not in self.transformer_banks:
                self.transformer_banks[bank_id] = TransformerBank(max_wdg, bank_id, str(uuid4()))

            bank = self.transformer_banks[bank_id]
            bank.add_AutoTransformer(atr)
            for i in range(atr.Windings):
                self.transformer_info.wdg_list[i].local_name = f"{atr.Name}_End_{i+1}"  # type: ignore
                self.transformer_info.wdg_list[i].uuid = str(uuid4())  # type: ignore
            self.transformer_info.core_list[0].local_name = f"{atr.Name}_Yc"  # type: ignore
            self.transformer_info.core_list[0].uuid = str(uuid4())  # type: ignore
            for i in range(int((max_wdg - 1) * max_wdg / 2)):
                self.transformer_info.mesh_list[i].local_name = f"{atr.Name}_Zsc_{i+1}"  # type: ignore
                self.transformer_info.mesh_list[i].uuid = str(uuid4())  # type: ignore

            self._add_CoreAdmittance(atr)
            self._add_MeshImpedance(atr)
            self._add_AutoPowerTransformerEnd(atr, bank)

            for tname, term_uri in self.transformer_terminal_uris.items():
                if tname.startswith(f"AutoTransformer={atr.Name}="):
                    bank.terminal_uris.append(term_uri)

        for bank_id, bank in self.transformer_banks.items():
            bank.build_vector_group()
            self._add_PowerTransformer(bank)

    def _add_PowerTransformer(self, bank: TransformerBank):
        node = self.build_cim_obj("PowerTransformer", mrid=bank.uuid, name=bank.local_name)
        self.add_triple(node, "PowerTransformer.vectorGroup", bank.vector_group)

        seq: dict[int, list] = {i + 1: [] for i in range(bank.n_windings)}
        for term_uri in bank.terminal_uris:
            seq[int(self.graph.value(term_uri, self.cim["ACDCTerminal.sequenceNumber"]))].append(term_uri)  # type: ignore

        for s, uris in seq.items():
            if len(uris) == 1:
                self.add_triple(uris[0], "Terminal.ConductingEquipment", node)
            else:
                phasecode: str = "".join([str(self.graph.value(subject=uri, predicate=self.cim["Terminal.phases"])).split(".")[-1] for uri in uris])
                phases = interp_phasecode(phasecode)

                new_term = self.build_cim_obj("Terminal", name=f"{bank.local_name}_T{s}")
                self.add_triple(new_term, "ACDCTerminal.sequenceNumber", s)
                self.add_triple(new_term, "Terminal.phases", self.cim[f"PhaseCode.{''.join(phases)}"])
                self.add_triple(new_term, "Terminal.ConnectivityNode", self.graph.value(uris[0], self.cim["Terminal.ConnectivityNode"]))
                oplimsets = [self.graph.value(uri, self.cim["ACDCTerminal.OperationalLimitSet"]) for uri in uris]
                for oplimset in oplimsets:
                    if oplimset is not None:
                        self.add_triple(new_term, "ACDCTerminal.OperationalLimitSet", oplimset)
                        break

                self.add_triple(new_term, "Terminal.ConductingEquipment", node)

                # remove old uri
                for uri in uris:
                    self.graph.remove((uri, None, None))

    def _add_PowerTransformerEnd(self, tr: altdss.Transformer, bank: TransformerBank):
        for i in range(tr.Windings):
            node = self.build_cim_obj("PowerTransformerEnd", mrid=self.transformer_info.wdg_list[i].uuid, name=self.transformer_info.wdg_list[i].local_name)  # type: ignore

            self.add_triple(node, "PowerTransformerEnd.PowerTransformer", URIRef(bank.uuid))
            self.add_triple(node, "PowerTransformerEnd.ratedS", 1000.0 * tr.kVAs[i])
            self.add_triple(node, "PowerTransformerEnd.ratedU", 1000.0 * tr.kVs[i])
            zbase = 1000.0 * tr.kVs[i] ** 2 / tr.kVAs[i]
            self.add_triple(node, "PowerTransformerEnd.r", zbase * tr.pctR[i] / 100.0)

            if tr.Conns[i] == 1:  # type: ignore
                self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.D"])
            else:
                if tr.RNeut[i] > 0.0 or tr.XNeut[i] > 0.0:
                    self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.Yn"])
                else:
                    self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.Y"])

            if tr.Conns[i] != tr.Conns[0]:  # type: ignore
                self.add_triple(node, "PowerTransformerEnd.phaseAngleClock", 1)
            else:
                self.add_triple(node, "PowerTransformerEnd.phaseAngleClock", 0)

            j = i * tr.NumConductors() + tr.NumPhases() + 1
            self.raw_dss.Basic.SetActiveClass("Transformer")
            self.raw_dss.ActiveClass.First()
            while self.raw_dss.CktElement.Name() != f"Transformer.{tr.Name}":
                self.raw_dss.ActiveClass.Next()

            if tr.Conns[i] == 0:  # type: ignore
                self.add_triple(node, "TransformerEnd.grounded", False)
            elif self.raw_dss.CktElement.NodeRef()[j] == 0:
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", 0.0)
                self.add_triple(node, "TransformerEnd.xground", 0.0)
            elif tr.RNeut[i] < 0.0:
                self.add_triple(node, "TransformerEnd.grounded", False)
            else:
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", tr.RNeut[i])
                self.add_triple(node, "TransformerEnd.xground", tr.XNeut[i])

            self.add_triple(node, "TransformerEnd.endNumber", i + 1)

            phases = parse_phase_str(tr.Buses[i], tr.Phases)
            terminal_uri = self._add_Terminal(node, tr, bus=self._parse_busname(tr.Buses[i]), phases=phases, n_terminal=i + 1)
            base_kv = self._add_BaseVoltage(node, tr.Buses[i])

            if i + 1 == 1:
                self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=tr.NormAmps, norm_max=tr.NormAmps, emerg_max=tr.EmergAmps)

            self.terminal_map[(type(tr), tr.Name, i + 1)] = terminal_uri
            self.transformer_terminal_uris[f"Transformer={tr.Name}={i+1}"] = terminal_uri
            self.transformer_end_uris[f"Transformer={tr.Name}={i+1}"] = node

    def _add_AutoPowerTransformerEnd(self, tr: altdss.AutoTrans, bank: TransformerBank):
        for i in range(tr.Windings):
            node = self.build_cim_obj("PowerTransformerEnd", self.transformer_info.wdg_list[i].uuid, name=self.transformer_info.wdg_list[i].local_name)  # type: ignore

            self.add_triple(node, "PowerTransformerEnd.PowerTransformer", URIRef(bank.uuid))
            self.add_triple(node, "PowerTransformerEnd.ratedS", 1000.0 * tr.kVAs[i])
            self.add_triple(node, "PowerTransformerEnd.ratedU", 1000.0 * tr.kVs[i])

            zbase = 1000.0 * tr.kVs[i] ** 2 / tr.kVAs[i]
            self.add_triple(node, "PowerTransformerEnd.r", zbase * tr.pctR[i] / 100.0)
            if i + 1 == 1:
                self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.Y"])
                self.add_triple(node, "PowerTransformerEnd.phaseAngleClock", 0)
                self.add_triple(node, "TransformerEnd.grounded", False)
            elif i + 1 == 2:
                self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.A"])
                self.add_triple(node, "PowerTransformerEnd.phaseAngleClock", 0)
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", 0.0)
                self.add_triple(node, "TransformerEnd.xground", 0.0)
            else:
                self.add_triple(node, "PowerTransformerEnd.connectionKind", self.cim["WindingConnection.D"])
                self.add_triple(node, "PowerTransformerEnd.phaseAngleClock", 1)
                self.add_triple(node, "TransformerEnd.grounded", False)

            self.add_triple(node, "TransformerEnd.endNumber", i + 1)

            phases = parse_phase_str(tr.Buses[i], tr.Phases)
            terminal_uri = self._add_Terminal(node, tr, bus=self._parse_busname(tr.Buses[i]), phases=phases, n_terminal=i + 1)
            base_kv = self._add_BaseVoltage(node, tr.Buses[i])

            if i + 1 == 1:
                self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=tr.NormAmps, norm_max=tr.NormAmps, emerg_max=tr.EmergAmps)

            self.transformer_terminal_uris[f"AutoTransformer={tr.Name}={i+1}"] = terminal_uri
            self.transformer_end_uris[f"AutoTransformer={tr.Name}={i+1}"] = node

    def _add_TransformerTank(self, tr: altdss.Transformer, bank_id: str):
        node = self.build_cim_obj("TransformerTank", name=tr.Name)
        xfmrcode_id = f"CIMXfmrCode_{tr.Name}" if tr.XfmrCode is None else tr.XfmrCode_str
        self.add_triple(node, "TransformerTank.TransformerTankInfo", self.xfmrcode_uris[xfmrcode_id])
        self.add_triple(node, "TransformerTank.PowerTransformer", URIRef(self.transformer_banks[bank_id].uuid))

        return node

    def _add_TransformerTankEnd(self, subject_uri: URIRef, tr: altdss.Transformer):
        for i in range(tr.Windings):
            node = self.build_cim_obj("TransformerTankEnd", mrid=self.transformer_info.wdg_list[i].uuid, name=self.transformer_info.wdg_list[i].local_name)  # type: ignore

            j1 = i * tr.NumConductors() + 1
            j2 = j1 + tr.NumPhases()
            reverse_ground = False
            wye_ground = False
            wye_ungrouned = False

            self.raw_dss.Basic.SetActiveClass("Transformer")
            self.raw_dss.ActiveClass.First()
            while self.raw_dss.CktElement.Name() != f"Transformer.{tr.Name}":
                self.raw_dss.ActiveClass.Next()

            if tr.Conns[i] == 1:  # type: ignore
                self.add_triple(node, "TransformerEnd.grounded", False)
            elif self.raw_dss.CktElement.NodeRef()[j2 - 1] == 0:
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", 0.0)
                self.add_triple(node, "TransformerEnd.xground", 0.0)
                wye_ground = True
            elif self.raw_dss.CktElement.NodeRef()[j1 - 1] == 0:
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", 0.0)
                self.add_triple(node, "TransformerEnd.xground", 0.0)
                reverse_ground = True
            elif tr.RNeut[i] < 0.0:
                self.add_triple(node, "TransformerEnd.grounded", False)
                wye_ungrouned = True
            else:
                self.add_triple(node, "TransformerEnd.grounded", True)
                self.add_triple(node, "TransformerEnd.rground", tr.RNeut[i])
                self.add_triple(node, "TransformerEnd.rground", tr.XNeut[i])

            phases = phase_kind = parse_ordered_phase_str(tr.Buses[i], n_phases=tr.NumPhases(), kv_base=tr.kVs[i])
            if phases == "s1":
                phase_kind = "s1N"
            elif phases == "s2":
                phase_kind = "Ns2"
            elif reverse_ground:
                phase_kind = "N" + phases
            elif wye_ground:
                phase_kind = phases + "N"
            elif wye_ungrouned:
                phase_kind = phases + "N"

            self.add_triple(node, "TransformerTankEnd.phases", self.cim[f"PhaseCode.{phase_kind}"])

            self.add_triple(node, "TranformerTankEnd.TransformerTank", subject_uri)

            self.add_triple(node, "TransformerEnd.endNumber", i + 1)

            terminal_uri = self._add_Terminal(node, tr, bus=self._parse_busname(tr.Buses[i]), phases=phase_kind, n_terminal=i + 1)
            base_kv = self._add_BaseVoltage(node, tr.Buses[i])

            if i + 1 == 1:
                self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=tr.NormAmps, norm_max=tr.NormAmps, emerg_max=tr.EmergAmps)

            self.transformer_terminal_uris[f"Transformer={tr.Name}={i+1}"] = terminal_uri
            self.transformer_end_uris[f"Transformer={tr.Name}={i+1}"] = node

    def _add_TransformerEndInfo(self, i: int, xfmrcode: altdss.XfmrCode, subject_uri: URIRef, ratShort: float, ratEmerg: float, Zbase: float):
        node = self.build_cim_obj("TransformerEndInfo", name=f"{xfmrcode.Name}_{i+1}")
        self.add_triple(node, "TransformerEndInfo.TransformerTankInfo", subject_uri)
        self.add_triple(node, "TransformerEndInfo.endNumber", i + 1)
        if xfmrcode.Phases < 3:
            self.add_triple(node, "TransformerEndInfo.connectionKind", self.cim["WindingConnection.I"])

            if i == 2 and xfmrcode.kVs[i] < 0.3:
                self.add_triple(node, "TransformerEndInfo.phaseAngleClock", 6)
            else:
                self.add_triple(node, "TransformerEndInfo.phaseAngleClock", 0)
        else:
            if xfmrcode.Conns[i] == 1:  # type: ignore
                self.add_triple(node, "TransformerEndInfo.connectionKind", self.cim["WindingConnection.D"])
            else:
                if xfmrcode.RNeut[i] > 0.0 or xfmrcode.XNeut[i] > 0.0:
                    self.add_triple(node, "TransformerEndInfo.connectionKind", self.cim["WindingConnection.Yn"])
                else:
                    self.add_triple(node, "TransformerEndInfo.connectionKind", self.cim["WindingConnection.Y"])

            if xfmrcode.Conns[i] != xfmrcode.Conns[0]:  # type: ignore
                self.add_triple(node, "TransformerEndInfo.phaseAngleClock", 1)
            else:
                self.add_triple(node, "TransformerEndInfo.phaseAngleClock", 0)

        self.add_triple(node, "TransformerEndInfo.ratedU", xfmrcode.kVs[i] * 1000)
        self.add_triple(node, "TransformerEndInfo.ratedS", xfmrcode.kVAs[i] * 1000)
        self.add_triple(node, "TransformerEndInfo.shortTermS", xfmrcode.kVAs[i] * 1000 * ratShort)
        self.add_triple(node, "TransformerEndInfo.emergencyS", xfmrcode.kVAs[i] * 1000 * ratEmerg)
        self.add_triple(node, "TransformerEndInfo.r", xfmrcode.pctR[i] / 100.0 * Zbase)
        self.add_triple(node, "TransformerEndInfo.insulationU", 0.0)

        return node

    def _add_TransformerTankInfo(self, xfmrcode: altdss.XfmrCode, xfmrcode_name: str | None = None):
        node = self.build_cim_obj("TransformerTankInfo", name=xfmrcode_name if xfmrcode_name is not None else xfmrcode.Name)
        ratShort = xfmrcode.NormHkVA / xfmrcode.kVAs[0]
        ratEmerg = xfmrcode.EmergHkVA / xfmrcode.kVAs[0]
        transformer_ends = []
        for i in range(xfmrcode.Windings):
            Zbase = xfmrcode.kVs[i] ** 2 * 1000 / xfmrcode.kVAs[0]
            transformer_ends.append(self._add_TransformerEndInfo(i, xfmrcode, node, ratShort, ratEmerg, Zbase))

        self._add_NoLoadTest(xfmrcode, transformer_ends[0], 1)

        seq = 0
        for i in range(xfmrcode.Windings):
            for j in range(i + 1, xfmrcode.Windings):
                seq += 1
                self._add_ShortCircuitTest(xfmrcode, transformer_ends, seq, i, j)

        return node

    def _add_NoLoadTest(self, xfmrcode: altdss.XfmrCode, subject_uri: URIRef, seq: int):
        node = self.build_cim_obj("NoLoadTest", name=f"{xfmrcode.Name}_{seq}_noload")
        self.add_triple(node, "NoLoadTest.EnergisedEnd", subject_uri)
        self.add_triple(node, "NoLoadTest.energisedEndVoltage", xfmrcode.kVs[0] * 1000.0)
        exciting_current = math.sqrt(xfmrcode.pctIMag**2 + xfmrcode.pctNoLoadLoss**2)
        self.add_triple(node, "NoLoadTest.excitingCurrent", exciting_current)
        self.add_triple(node, "NoLoadTest.excitingCurrentZero", exciting_current)
        loss = 0.01 * xfmrcode.pctNoLoadLoss / 100.0 * xfmrcode.kVAs[0]
        self.add_triple(node, "NoLoadTest.loss", loss)
        self.add_triple(node, "NoLoadTest.lossZero", loss)
        self.add_triple(node, "TransformerTest.basePower", xfmrcode.kVAs[0] * 1000.0)
        self.add_triple(node, "TransformerTest.temperature", 50.0)

    def _add_ShortCircuitTest(self, xfmrcode: altdss.XfmrCode, subject_uris: list, seq: int, i: int, j: int):
        node = self.build_cim_obj("ShortCircuitTest", name=f"{xfmrcode.Name}_{seq}_shortcircuit")
        self.add_triple(node, "ShortCircuitTest.EnergisedEnd", subject_uris[i])
        self.add_triple(node, "ShortCircuitTest.GroundedEnds", subject_uris[j])
        self.add_triple(node, "ShortCircuitTest.energisedEndStep", int(xfmrcode.Taps[i]))
        self.add_triple(node, "ShortCircuitTest.groundedEndStep", int(xfmrcode.Taps[j]))

        test_kva = xfmrcode.kVAs[0]
        Zbase = xfmrcode.kVs[i] ** 2 / test_kva * 1000.0
        leakage_impedance = math.sqrt((xfmrcode.pctRs[i] + xfmrcode.pctRs[j]) ** 2 + xfmrcode.XSCArray[seq - 1] ** 2) * Zbase
        self.add_triple(node, "ShortCircuitTest.leakageImpedance", leakage_impedance)
        self.add_triple(node, "ShortCircuitTest.leakageImpedanceZero", leakage_impedance)

        self.add_triple(node, "TransformerTest.basePower", test_kva * 1000.0)
        self.add_triple(node, "TransformerTest.temperature", 50.0)

    def _add_CoreAdmittance(self, tr: altdss.Transformer):
        node = self.build_cim_obj("TransformerCoreAdmittance", mrid=self.transformer_info.core_list[0].uuid, name=self.transformer_info.core_list[0].local_name)  # type: ignore

        zbase = 1000.0 * tr.kVs[0] ** 2 / tr.kVAs[0]

        g = tr.pctNoLoadLoss / 100.0 / zbase
        self.add_triple(node, "TransformerCoreAdmittance.g", g)
        self.add_triple(node, "TransformerCoreAdmittance.g0", g)

        b = -tr.pctIMag / 100.0 / zbase
        self.add_triple(node, "TransformerCoreAdmittance.b", b)
        self.add_triple(node, "TransformerCoreAdmittance.b0", b)
        self.add_triple(node, "TransformerCoreAdmittance.TransformerEnd", URIRef(self.transformer_info.wdg_list[0].uuid))  # type: ignore

    def _add_MeshImpedance(self, tr: altdss.Transformer):
        seq = 0
        for i in range(tr.Windings):
            for k in range(i + 1, tr.Windings):
                node = self.build_cim_obj("TransformerMeshImpedance", mrid=self.transformer_info.mesh_list[seq].uuid, name=self.transformer_info.mesh_list[seq].local_name)  # type: ignore

                zbase = 1000.0 * tr.kVs[i] ** 2 / tr.kVAs[0]

                r = zbase * (tr.pctR[i] / 100.0 + tr.pctRs[k] / 100.0)
                self.add_triple(node, "TransformerMeshImpedance.r", r)
                self.add_triple(node, "TransformerMeshImpedance.r0", r)

                x = zbase * tr.XSCArray[seq]
                self.add_triple(node, "TransformerMeshImpedance.x", x)
                self.add_triple(node, "TransformerMeshImpedance.x0", x)

                self.add_triple(node, "TransformerMeshImpedance.FromTransformerEnd", URIRef(self.transformer_info.wdg_list[i].uuid))  # type: ignore
                self.add_triple(node, "TransformerMeshImpedance.ToTransformerEnd", URIRef(self.transformer_info.wdg_list[k].uuid))  # type: ignore

                seq += 1

    def _add_RegulatingControls(self):
        for reg in self.dss.RegControl:
            v1 = reg.Transformer.kVs[reg.TapWinding - 1] / reg.PTRatio
            tcc_node = self.build_cim_obj("TapChangerControl", name=f"{reg.Name}_Ctrl")

            self.add_triple(tcc_node, "RegulatingControl.mode", self.cim["RegulatingControlModeKind.voltage"])
            self.add_triple(tcc_node, "RegulatingControl.Terminal", self.transformer_terminal_uris[f"Transformer={reg.Transformer.Name}={reg.TapWinding}"])
            self.add_triple(tcc_node, "RegulatingControl.enabled", reg.Enabled)
            self.add_triple(tcc_node, "RegulatingControl.discrete", True)
            self.add_triple(tcc_node, "RegulatingControl.targetValue", reg.VReg)
            self.add_triple(tcc_node, "RegulatingControl.targetDeadband", reg.Band)
            self.add_triple(tcc_node, "TapChangerControl.lineDropCompensation", reg.LDC_Z > 0.0)
            self.add_triple(tcc_node, "TapChangerControl.lineDropR", reg.R)
            self.add_triple(tcc_node, "TapChangerControl.lineDropX", reg.X)
            if reg.Reversible:
                self.add_triple(tcc_node, "TapChangerControl.reversible", True)
                self.add_triple(tcc_node, "TapChangerControl.reverseToNeutral", reg.RevNeutral)
                self.add_triple(tcc_node, "TapChangerControl.reversingDelay", reg.RevDelay)
                self.add_triple(tcc_node, "TapChangerControl.reversingPowerThreshold", reg.RevThreshold)
                self.add_triple(tcc_node, "TapChangerControl.reverseLineDropR", reg.RevR)
                self.add_triple(tcc_node, "TapChangerControl.reverseLineDropX", reg.RevX)
                self.add_triple(tcc_node, "TapChangerControl.reverseTargetValue", reg.RevVReg)
                self.add_triple(tcc_node, "TapChangerControl.reverseTargetDeadband", reg.RevBand)
            else:
                self.add_triple(tcc_node, "TapChangerControl.reversible", False)

            if reg.VLimit > 0.0:
                self.add_triple(tcc_node, "TapChangerControl.maxLimitVoltage", reg.VLimit)
            else:
                self.add_triple(tcc_node, "TapChangerControl.maxLimitVoltage", reg.Transformer.MaxTap[reg.TapWinding - 1] * v1)

            self.add_triple(tcc_node, "TapChangerControl.minLimitVoltage", reg.Transformer.MinTap[reg.TapWinding - 1] * v1)

            rtc_node = self.build_cim_obj("RatioTapChanger", name=f"{reg.Name}")
            self.add_triple(rtc_node, "RatioTapChanger.TransformerEnd", self.transformer_end_uris[f"Transformer={reg.Transformer.Name}={reg.TapWinding}"])
            self.add_triple(rtc_node, "TapChanger.TapChangerControl", tcc_node)
            self.add_triple(rtc_node, "RatioTapChanger.stepVoltageIncrement", 100.0 * reg.Transformer.Taps[reg.TapWinding - 1])
            self.add_triple(rtc_node, "TapChanger.highStep", int(reg.Transformer.NumTaps[reg.TapWinding - 1] / 2))
            self.add_triple(rtc_node, "TapChanger.lowStep", -int(reg.Transformer.NumTaps[reg.TapWinding - 1] / 2))
            self.add_triple(rtc_node, "TapChanger.neutralStep", 0)
            self.add_triple(rtc_node, "TapChanger.normalStep", 0)
            self.add_triple(rtc_node, "TapChanger.neutralU", v1 * reg.PTRatio * 1000.0)
            self.add_triple(rtc_node, "TapChanger.initialDelay", reg.Delay)
            self.add_triple(rtc_node, "TapChanger.subsequentDelay", reg.TapDelay)
            self.add_triple(rtc_node, "TapChanger.ltcFlag", True)
            self.add_triple(rtc_node, "TapChanger.controlEnabled", reg.Enabled)
            self.add_triple(rtc_node, "TapChanger.step", reg.Transformer.Taps[reg.TapWinding - 1])
            self.add_triple(rtc_node, "TapChanger.ptRatio", reg.PTRatio)
            self.add_triple(rtc_node, "TapChanger.ctRatio", reg.CTPrim / 0.2)
            self.add_triple(rtc_node, "TapChanger.ctRating", reg.CTPrim)

            # Add RatioTapChanger reference to specific transformer winding
            self.add_triple(self.transformer_end_uris[f"Transformer={reg.Transformer.Name}={reg.TapWinding}"], "TransformerEnd.RatioTapChanger", rtc_node)

        for capc in self.dss.CapControl:
            node = self.build_cim_obj("RegulatingControl", name=capc.Name)

            self.add_triple(node, "RegulatingControl.RegulatingCondEq", self.cap_map[capc.Capacitor.Name]["uri"])

            element = capc.Element
            terminal: str = ""
            if isinstance(element, altdss.Transformer):
                terminal = element.Buses[capc.Terminal - 1]
            else:
                if capc.Terminal == 1:
                    terminal = element.Bus1
                elif capc.Terminal == 2:
                    terminal = element.Bus2

            phase_idx = 1
            if capc.Type == 0:
                phase_idx = capc.CTPhase
            elif capc.Type == 1:
                phase_idx = capc.PTPhase
            elif capc.Type == 2:
                phase_idx = None

            phases = parse_ordered_phase_str(terminal, element.NumPhases())
            phase = "A"
            if phase_idx is None:
                phase = phases
            else:
                if phases == "s12":
                    phase = ["s1", "s2"][phase_idx - 1]
                elif phases.startswith("s"):
                    phase = [phases][phase_idx - 1]
                else:
                    phase = phases[phase_idx - 1]

            self.add_triple(node, "RegulatingControl.Terminal", self.terminal_map[(type(element), element.Name, capc.Terminal)])

            self.add_triple(node, "RegulatingControl.monitoredPhase", self.cim[f"PhaseCode.{phase}"])
            capc_type = {0: "currentFlow", 1: "voltage", 2: "reactivePower", 3: "timeScheduled", 4: "powerFactor", 5: "userDefined"}.get(capc.Type, 1)
            self.add_triple(node, "RegulatingControl.mode", self.cim[f"RegulatingControlModeKind.{capc_type}"])
            self.add_triple(node, "RegulatingControl.discrete", True)
            self.add_triple(node, "RegulatingControl.enabled", capc.Enabled)
            mult = 1.0
            on = capc.OnSetting
            off = capc.OffSetting
            if capc.Type == 0:
                mult = capc.CTRatio
            elif capc.Type == 1:
                mult = capc.PTRatio
            elif capc.Type == 2:
                mult = 1000.0
            self.add_triple(node, "RegulatingControl.targetValue", mult * 0.5 * (on + off))
            self.add_triple(node, "RegulatingControl.targetDeadband", mult * (off - on))

            # Add Capacitor reference to specific RegulatingControl
            self.add_triple(self.cap_map[capc.Capacitor.Name]["uri"], "RegulatingCondEq.RegulatingControl", node)

    def _add_SeriesCompensators(self):
        for react in self.dss.Reactor:
            self._add_SeriesCompensator(react)

    def _add_SeriesCompensator(self, react: altdss.Reactor):
        node = self.build_cim_obj("SeriesCompensator", name=react.Name)
        self.add_triple(node, "SeriesCompensator.r", react.R)
        self.add_triple(node, "SeriesCompensator.x", react.X)
        self.add_triple(node, "SeriesCompensator.r0", react.R)
        self.add_triple(node, "SeriesCompensator.x0", react.X)

        for i, bus in enumerate([react.Bus1, react.Bus2]):
            terminal_uri = self._add_Terminal(node, react, bus=self._parse_busname(bus), n_terminal=i + 1, phases=parse_ordered_phase_str(bus, react.Phases))
            self._add_OperationalLimitSet(terminal_uri, "Current", normal_value=react.NormAmps, norm_max=react.NormAmps, emerg_max=react.EmergAmps)


if __name__ == "__main__":
    d = DssExport("examples/IEEE13_Assets.dss")
    d.save("examples/IEEE13_Assets.xml")
