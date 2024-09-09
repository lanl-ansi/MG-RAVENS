import math

from copy import deepcopy
from uuid import uuid4

from opendssdirect import dss as odd

from rdflib.exceptions import UniquenessError
from rdflib.namespace import Namespace
from rdflib.term import URIRef, Literal
from rdflib import Graph, RDF


class DssExport(object):
    def __init__(self, dss_file: str):
        self.raw_dss = odd
        self.raw_dss(f'redirect "{dss_file}"')

        self.dss = self.raw_dss.to_altdss()

        self.uuid_map = {}

        self.graph = Graph()
        self.cim = Namespace("http://iec.ch/TC57/CIM100#")
        self.graph.bind("cim", self.cim, override=True)

        self._add_IECVersion()

        self._convert_dss_to_rdf()

    def _convert_dss_to_rdf(self):
        pass
        self._add_ConnectivityNodes()
        self._add_EnergyConsumers()
        self._add_EnergySources()
        self._add_ACLineSegments()
        self._add_SynchronousMachines()

    def _export_rdf_to_xml(self, path: str):
        pass

    def save(self, path: str):
        pass

    @staticmethod
    def _parse_phase_str(bus: str, n_phases: int, kv_base: float = None, is_delta: bool = False) -> str:
        phase_str = ""

        if is_delta:
            if bus.count(".") == 0 or n_phases == 3:
                return "ABC"
            else:
                phases = bus.split(".", 1)[-1]
                if n_phases == 1:
                    if "1.2" in phases or "2.1" in phases:
                        return "A"
                    elif "2.3" in phases or "3.2" in phases:
                        return "B"
                    elif "1.3" in phases or "3.1" in phases:
                        return "C"
                else:
                    if "1.2.3" in phases:
                        return "AB"
                    elif "1.3.2" in phases:
                        return "CB"
                    elif "2.1.3" in phases:
                        return "AC"
                    elif "2.3.1" in phases:
                        return "BC"
                    elif "3.1.2" in phases:
                        return "CA"
                    elif "3.2.1" in phases:
                        return "BA"
        else:
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
                    if "1" in phases:
                        phase_str += "A"
                    if "2" in phases:
                        phase_str += "B"
                    if "3" in phases:
                        phase_str += "C"
                    if "4" in phases:
                        phase_str += "N"

            return phase_str

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
    def _parse_ordered_phase_str(bus: str, n_phases: int, kv_base: float = None) -> str:
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

    def build_cim_obj(self, rdf_type: str, mrid: str = None, name: str = None, skip_mrid: bool = False) -> URIRef:
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

    def _add_Location(self, obj_name: str, x_coords: list[float], y_coords: list[float], coord_system: str = None):
        # TODO: crsUrn
        if f"Location.{obj_name}_Location" not in self.uuid_map:
            node = self.build_cim_obj("Location", name=f"{obj_name}_Location")

            for i, (x, y) in enumerate(zip(x_coords, y_coords)):
                self._add_PositionPoint(node, x, y, i + 1)

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

    def _add_Terminal(self, connecting_node: URIRef, element: object, bus: str = None, n_terminal: int = 1, phases="ABC"):
        node = self.build_cim_obj("Terminal", name=f"{element.Name}_T{n_terminal}")

        self.add_triple(node, "ACDCTerminal.sequenceNumber", n_terminal)
        self.add_triple(node, "Terminal.phases", self.cim[f"PhaseCode.{phases}"])
        self.add_triple(node, "Terminal.ConductingEquipment", connecting_node)

        if bus is not None:
            cn_node = self._add_ConnectivityNode(bus)
            self.add_triple(node, "Terminal.ConnectivityNode", cn_node)

        return node

    def _add_OperationalLimitSet(self, subject_uri: URIRef, limit_type: str, norm_max: float, norm_min: float = None, emerg_max: float = None, emerg_min: float = None):
        emerg = False
        if limit_type == "Voltage":
            emerg = emerg_min is not None and emerg_max is not None

            name = f"OpLimV_{norm_min}-{norm_max}"
            if emerg:
                name += f"_{emerg_min}-{emerg_max}"
        elif limit_type == "Current":
            emerg = emerg_max is not None
            name = f"OpLimI_{norm_max}"
            if emerg:
                name += f"_{emerg_max}"
        else:
            # TODO: ActivePower, ApparentPower Limit Types
            print("OperationalLimitSet with type of '{limit_type}' is not yet supported.")

        if f"OperationalLimitSet.{name}" not in self.uuid_map:
            node = self.build_cim_obj("OperationalLimitSet", name=name)

            if limit_type == "Voltage":
                for limit_direction in ["low", "high"]:
                    limit_type_uri = self._add_OperationalLimitType(limit_direction, 5e9)
                    self._add_VoltageLimit(node, limit_type_uri, f"{name}_RangeA{limit_direction}", (norm_min if limit_direction == "low" else norm_max))

                    if emerg:
                        limit_type_uri = self._add_OperationalLimitType(limit_direction, 60 * 60 * 24.0)
                        self._add_VoltageLimit(node, limit_type_uri, f"{name}_RangeB{limit_direction}", (emerg_min if limit_direction == "low" else emerg_max))
            elif limit_type == "Current":
                limit_type_uri = self._add_OperationalLimitType("absoluteValue", 5e9)
                self._add_CurrentLimit(node, limit_type_uri, f"{name}_Norm", norm_max)
                if emerg:
                    limit_type_uri = self._add_OperationalLimitType("absoluteValue", 60 * 60 * 24.0)
                    self._add_CurrentLimit(node, limit_type_uri, f"{name}_Emerg", emerg_max)

            else:
                # TODO: ActivePower, ApparentPower Limit Types
                return None

            self.uuid_map[f"OperationalLimitSet.{name}"] = str(node)

        self.add_triple(subject_uri, "ACDCTerminal.OperationalLimitSet", URIRef(self.uuid_map[f"OperationalLimitSet.{name}"]))

    def _add_OperationalLimitType(self, limit_direction: str, acceptable_duration: float):
        name = f"{limit_direction}Type_{acceptable_duration}s"

        if f"OperationalLimitType.{name}" not in self.uuid_map:
            node = self.build_cim_obj("OperationalLimitType", name=name)
            self.add_triple(node, "OperationalLimitType.direction", self.cim[f"OperationalLimitDirectionKind.{limit_direction}"])
            self.add_triple(node, "OperationalLimitType.acceptableDuration", acceptable_duration)
            self.uuid_map[f"OperationalLimitType.{name}"] = str(node)

        return URIRef(self.uuid_map[f"OperationalLimitType.{name}"])

    def _add_VoltageLimit(self, limit_set_uri: URIRef, limit_type_uri: URIRef, name: str, value: float):
        if f"VoltageLimit.{name}" not in self.uuid_map:
            node = self.build_cim_obj("VoltageLimit", name=name)
            self.add_triple(node, "VoltageLimit.value", value)
            self.add_triple(node, "OperationalLimit.OperationalLimitType", limit_type_uri)
            self.add_triple(node, "OperationalLimit.OperationalLimitSet", limit_set_uri)
            self.uuid_map[f"VoltageLimit.{name}"] = str(node)

    def _add_CurrentLimit(self, limit_set_uri: URIRef, limit_type_uri: URIRef, name: str, value: float):
        if f"CurrentLimit.{name}" not in self.uuid_map:
            node = self.build_cim_obj("CurrentLimit", name=name)
            self.add_triple(node, "CurrentLimit.value", value)
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

    def _add_EnergySource(self, vsource: object):
        node = self.build_cim_obj("EnergySource", name=vsource.Name)

        self.add_triple(node, "EnergySource.nominalVoltage", vsource.BasekV * 1000.0)
        self.add_triple(node, "EnergySource.voltageMagnitude", vsource.BasekV * 1000.0 * vsource.pu)
        self.add_triple(node, "EnergySource.voltageAngle", math.radians(vsource.Angle))
        self.add_triple(node, "EnergySource.R1", vsource.R1)
        self.add_triple(node, "EnergySource.X1", vsource.X1)
        self.add_triple(node, "EnergySource.R0", vsource.R0)
        self.add_triple(node, "EnergySource.X0", vsource.X0)
        self.add_triple(node, "Equipment.inService", vsource.Enabled)

        self._add_BaseVoltage(node, vsource.Bus1)

        for t, bus in enumerate([vsource.Bus1, vsource.Bus2]):
            busname = self._parse_busname(bus)
            phases = self._parse_phase_str(bus, n_phases=vsource.Phases)
            if phases:
                self._add_Terminal(node, vsource, n_terminal=t + 1, phases=phases)

        phases = self._parse_ordered_phase_str(vsource.Bus1, vsource.Phases)
        if phases != "ABC":
            for phase in phases:
                self._add_EnergySourcePhase()

    def _add_EnergySourcePhase(self):
        # TODO: EnergySourcePhase
        pass

    def _add_ACLineSegments(self):
        for line in self.dss.Line:
            if not line.Enabled:
                continue

            if line.Switch:
                self._add_Switch(line)
            else:
                node = self.build_cim_obj("ACLineSegment", name=line.Name)
                self.add_triple(node, "Conductor.length", line.Length)
                self.add_triple(node, "Equipment.inService", line.Enabled)
                self._add_BaseVoltage(node, line.Bus1)

                # TODO: Line Geometry, parameters defined on Line, etc.
                if line.LineCode is not None:
                    uri = self._add_PerLengthPhaseImedance(line.LineCode)
                    self.add_triple(node, "ACLineSegment.PerLengthImpedance", uri)
                elif line.Geometry is not None:
                    pass
                elif line.Spacing is not None:
                    pass
                else:
                    # no LineCode, Geometry, or Spacing specified
                    pass

                phases = self._parse_ordered_phase_str(line.Bus1, line.Phases)
                if phases == "s12":
                    for seq, phase in enumerate(["s1", "s2"]):
                        self._add_ACLineSegmentPhase(node, line, phase, seq + 1)
                elif phases.startswith("s"):
                    for seq, phase in enumerate([phases]):
                        self._add_ACLineSegmentPhase(node, line, phase, seq + 1)
                else:
                    for seq, phase in enumerate([ph for ph in phases]):
                        self._add_ACLineSegmentPhase(node, line, phase, seq + 1)

                for i, bus in enumerate([line.Bus1, line.Bus2]):
                    terminal_uri = self._add_Terminal(node, line, bus=self._parse_busname(bus), n_terminal=i + 1, phases=self._parse_ordered_phase_str(bus, line.Phases))
                    self._add_OperationalLimitSet(terminal_uri, "Current", norm_max=line.NormAmps, emerg_max=line.EmergAmps)

    def _add_ACLineSegmentPhase(self, aclinesegment_uri: URIRef, line: object, phase: str, sequence: int):
        node = self.build_cim_obj("ACLineSegmentPhase", name=f"{line.Name}_{phase}")
        self.add_triple(node, "ACLineSegmentPhase.phase", self.cim[f"SinglePhaseKind.{phase}"])
        self.add_triple(node, "ACLineSegmentPhase.sequenceNumber", sequence)
        self.add_triple(node, "ACLineSegmentPhase.ACLineSegment", aclinesegment_uri)

    def _add_PerLengthPhaseImedance(self, linecode: object) -> URIRef:
        if f"PerLengthPhaseImpedance.{linecode.Name}" not in self.uuid_map:
            node = self.build_cim_obj("PerLengthPhaseImpedance", name=linecode.Name)
            self.add_triple(node, "PerLengthPhaseImpedance.conductorCount", linecode.NPhases)

            self._add_PhaseImpedanceData(node, linecode)

            self.uuid_map[f"PerLengthPhaseImpedance.{linecode.Name}"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"PerLengthPhaseImpedance.{linecode.Name}"])

    def _add_PhaseImpedanceData(self, phase_impedance_uri: URIRef, linecode: object):
        for col in range(linecode.NPhases):
            for row in range(col, linecode.NPhases):
                node = self.build_cim_obj("PhaseImpedanceData", skip_mrid=True)
                self.add_triple(node, "PhaseImpedanceData.row", row + 1)
                self.add_triple(node, "PhaseImpedanceData.column", col + 1)
                self.add_triple(node, "PhaseImpedanceData.r", linecode.RMatrix[row + col])
                self.add_triple(node, "PhaseImpedanceData.x", linecode.XMatrix[row + col])
                self.add_triple(node, "PhaseImpedanceData.b", linecode.CMatrix[row + col] * 2 * math.pi * linecode.BaseFreq / 1e9)
                self.add_triple(node, "PhaseImpedanceData.PhaseImpedance", phase_impedance_uri)

    def _add_Switch(self, line: object):
        # TODO: Type of switch
        node = self.build_cim_obj("Switch", name=line.Name)
        self.add_triple(node, "Equipment.inService", line.Enabled)

        phases = self._parse_ordered_phase_str(line.Bus1, line.Phases)
        if phases == "s12":
            for seq, phase in enumerate(["s1", "s2"]):
                self._add_SwitchPhase(node, line, phase, seq + 1)
        elif phases.startswith("s"):
            for seq, phase in enumerate([phases]):
                self._add_SwitchPhase(node, line, phase, seq + 1)
        else:
            for seq, phase in enumerate([ph for ph in phases]):
                self._add_SwitchPhase(node, line, phase, seq + 1)

        for i, bus in enumerate([line.Bus1, line.Bus2]):
            self._add_Terminal(node, line, bus=self._parse_busname(bus), n_terminal=i + 1, phases=self._parse_ordered_phase_str(bus, line.Phases))

    def _add_SwitchPhase(self):
        node = self.build_cim_obj("SwitchPhase", name=f"{line.Name}_{phase}")
        self.add_triple(node, "SwitchPhase.phase", self.cim[f"SinglePhaseKind.{phase}"])
        self.add_triple(node, "SwitchPhase.sequenceNumber", sequence)
        self.add_triple(node, "SwitchPhase.Switch", aclinesegment_uri)

    def _add_EnergyConsumers(self):
        for load in self.dss.Load:
            self._add_EnergyConsumer(load)

    def _add_EnergyConsumer(self, load):
        node = self.build_cim_obj("EnergyConsumer", name=load.Name)

        self.add_triple(node, "EnergyConsumer.p", load.kW * 1000.0)
        self.add_triple(node, "EnergyConsumer.q", load.kvar * 1000.0)
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

        phases = self._parse_phase_str(load.Bus1, load.Phases, load.kV, load.Conn != 0)
        self._add_EnergyConsumerPhases(node, load, phases)
        terminal_uri = self._add_Terminal(node, load, bus=self._parse_busname(load.Bus1), phases=phases)

        self._add_OperationalLimitSet(terminal_uri, "Voltage", norm_min=load.VMinpu * base_kv * 1000, norm_max=load.VMaxpu * base_kv * 1000)

        # EnergyConsumerProfile
        self._add_EnergyConnectionProfile(node, load)

    def _add_EnergyConsumerPhases(self, energy_consumer_uri: URIRef, load: object, phases: str):
        if load.Phases == 3:
            return None
        else:
            if phases.startswith("s"):
                if phases == "s12":
                    phases = ["s1", "s2"]
                else:
                    phases = [phases]

            for ph in phases:
                node = self.build_cim_obj("EnergyConsumerPhase", name=f"{load.Name}_{ph}")
                self.add_triple(node, "EnergyConsumerPhase.p", load.kW * 1000.0 / load.Phases)
                self.add_triple(node, "EnergyConsumerPhase.q", load.kvar * 1000.0 / load.Phases)
                self.add_triple(node, "EnergyConsumerPhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "EnergyConsumerPhase.EnergyConsumer", energy_consumer_uri)

    def _add_LoadResponseCharacteristic(self, model):
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

    def _add_EnergyConnectionProfile(self, subject_uri, load):
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
                            loadshape_uris.append(self._add_EnergyConsumerProfile(subject_uri, obj))
            self.uuid_map[f"EnergyConnectionProfile.{ecp_name}"] = str(node)
        else:
            for attr in ["Daily", "Duty", "Yearly", "CVRCurve"]:
                loadshape = getattr(load, attr)
                if loadshape is not None:
                    loadshape_uris.append(URIRef(self.uuid_map[f"EnergyConsumerProfile.{loadshape.Name}"]))

        self.add_triple(URIRef(self.uuid_map[f"EnergyConnectionProfile.{ecp_name}"]), "EnergyConnectionProfile.EnergyConnections", subject_uri)
        for uri in loadshape_uris:
            self.add_triple(subject_uri, "EnergyConsumer.LoadProfile", uri)

    def _add_EnergyConsumerProfile(self, subject_uri, loadshape):
        # TODO: handle irregular time points
        if f"EnergyConsumerProfile.{loadshape.Name}" not in self.uuid_map:
            node = self.build_cim_obj("EnergyConsumerProfile", name=loadshape.Name)

            pmult = loadshape.PMult
            qmult = loadshape.QMult

            if loadshape.UseActual:
                self.add_triple(node, "BasicIntervalSchedule.value1Unit", "W")
                self.add_triple(node, "BasicIntervalSchedule.value2Unit", "var")
                pmult *= 1000
                qmult *= 1000
            else:
                self.add_triple(node, "BasicIntervalSchedule.value1Unit", "none")
                self.add_triple(node, "BasicIntervalSchedule.value2Unit", "none")

            self.add_triple(node, "RegularIntervalSchedule.timeStep", loadshape.SInterval)

            if qmult.size == 0:
                qmult = pmult

            for i, (p, q) in enumerate(zip(pmult, qmult)):
                self._add_RegularTimePoint(node, i, p, q)

            self.uuid_map[f"EnergyConsumerProfile.{loadshape.Name}"] = str(node)

        return URIRef(self.uuid_map[f"EnergyConsumerProfile.{loadshape.Name}"])

    def _add_RegularTimePoint(self, subject_uri: URIRef, sequence: int, value1: float, value2: float):
        node = self.build_cim_obj("RegularTimePoint", skip_mrid=True)
        self.add_triple(node, "RegularTimePoint.sequenceNumber", sequence)
        self.add_triple(node, "RegularTimePoint.value1", value1)
        self.add_triple(node, "RegularTimePoint.value2", value2)
        self.add_triple(node, "RegularTimePoint.IntervalSchedule", subject_uri)

    def _add_SynchronousMachines(self):
        for gen in self.dss.Generator:
            self._add_SynchronousMachine(gen)

    def _add_SynchronousMachine(self, gen: object):
        node = self.build_cim_obj("SynchronousMachine", name=gen.Name)
        self.add_triple(node, "RotatingMachine.p", gen.kW * 1000)
        self.add_triple(node, "RotatingMachine.q", gen.kvar * 1000)
        self.add_triple(node, "RotatingMachine.ratedS", gen.kVA * 1000)
        self.add_triple(node, "RotatingMachine.ratedU", gen.kV * 1000)

        phases = self._parse_phase_str(gen.Bus1, gen.Phases)
        self._add_SynchronousMachinePhases(node, gen, phases)

        terminal_uri = self._add_Terminal(node, gen, bus=self._parse_busname(gen.Bus1), phases=phases)
        base_kv = self._add_BaseVoltage(node, gen.Bus1)
        self._add_OperationalLimitSet(terminal_uri, "Voltage", norm_min=gen.VMinpu * base_kv * 1000, norm_max=gen.VMaxpu * base_kv * 1000)

    def _add_SynchronousMachinePhases(self, subject_uri: URIRef, gen: object, phases: str):
        if gen.Phases == 3:
            return None
        else:
            if phases.startswith("s"):
                if phases == "s12":
                    phases = ["s1", "s2"]
                else:
                    phases = [phases]

            for ph in phases:
                node = self.build_cim_obj("SynchronousMachinePhase", name=f"{gen.Name}_{ph}")
                self.add_triple(node, "SynchronousMachinePhase.p", gen.kW * 1000.0 / gen.Phases)
                self.add_triple(node, "SynchronousMachinePhase.q", gen.kvar * 1000.0 / gen.Phases)
                self.add_triple(node, "SynchronousMachinePhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self.add_triple(node, "SynchronousMachinePhase.SynchronousMachine", subject_uri)


if __name__ == "__main__":
    d = DssExport("examples/case3_balanced.dss")

    d.graph.serialize("out/test_opendss_convert.xml", max_depth=1, format="pretty-xml")
