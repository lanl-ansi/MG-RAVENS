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
            if (kv_base is not None) and (n_phases == 2 and kv_base < 0.25) or (n_phases == 1 and kv_base < 0.13):
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
        if (kv_base is not None) and (n_phases == 2 and kv_base < 0.25) or (n_phases == 1 and kv_base < 0.13):
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

    def _add_rdf_object(self, rdf_type: str, mrid: str = None, name: str = None, skip_mrid: bool = False) -> URIRef:
        if mrid is None:
            mrid = str(uuid4())
        node = URIRef(mrid)

        self.graph.add((node, RDF.type, self.cim[rdf_type]))
        if not skip_mrid:
            self.graph.add((node, self.cim["IdentifiedObject.mRID"], Literal(mrid)))
        if name is not None:
            self.graph.add((node, self.cim["IdentifiedObject.name"], Literal(name)))

        return node

    def _add_property(self, node: URIRef, property_name: str, property_value):
        if isinstance(property_value, bool):
            self.graph.add((node, self.cim[property_name], Literal(str(property_value).lower())))
        elif isinstance(property_value, URIRef):
            self.graph.add((node, self.cim[property_name], property_value))
        else:
            self.graph.add((node, self.cim[property_name], Literal(str(property_value))))

    def _add_SvStatus(self, source_node_uri: URIRef, in_service: bool):
        if f"SvStatus.{in_service}" not in self.uuid_map:
            node = self._add_rdf_object("SvStatus", skip_mrid=True)
            self._add_property(node, "SvStatus.inService", in_service)
            self._add_property(source_node_uri, "ConductingEquipment.SvStatus", node)

            self.uuid_map[f"SvStatus.{in_service}"] = str(node)
        else:
            self._add_property(source_node_uri, "ConductingEquipment.SvStatus", URIRef(self.uuid_map[f"SvStatus.{in_service}"]))

    def _add_IECVersion(self):
        node = self._add_rdf_object("IEC61970CIMVersion", skip_mrid=True)
        self._add_property(node, "IEC61970CIMVersion.version", "IEC61970CIM100")
        self._add_property(node, "IEC61970CIMVersion.date", "2019-04-01")

    def _add_Location(self, obj_name: str, x_coords: list[float], y_coords: list[float], coord_system: str = None):
        # TODO: crsUrn
        if f"Location.{obj_name}_Location" not in self.uuid_map:
            node = self._add_rdf_object("Location", name=f"Location.{obj_name}_Location")

            for i, (x, y) in enumerate(zip(x_coords, y_coords)):
                self._add_PositionPoint(node, x, y, i + 1)

            self.uuid_map[f"Location.{obj_name}_Location"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"Location.{obj_name}_Location"])

    def _add_PositionPoint(self, location_uri: URIRef, x: float, y: float, seq: int):
        node = self._add_rdf_object("PositionPoint", skip_mrid=True)
        self._add_property(node, "PositionPoint.sequenceNumber", seq)
        self._add_property(node, "PositionPoint.xPosition", x)
        self._add_property(node, "PositionPoint.yPosition", y)
        self._add_property(node, "PositionPoint.Location", location_uri)

    def _add_BaseVoltage(self, source_uri: URIRef, bus: str):
        base_kv = math.sqrt(3) * self.dss.Bus.kVBase()[self.dss.Bus.Name().index(self._parse_busname(bus))]

        if f"BaseVoltage.{base_kv}" not in self.uuid_map:
            node = self._add_rdf_object("BaseVoltage", name=f"BaseV_{base_kv}")
            self._add_property(node, "BaseVoltage.nominalVoltage", base_kv * 1000)
            self.uuid_map[f"BaseVoltage.{base_kv}"] = str(node)

        self._add_property(source_uri, "ConductingEquipment.BaseVoltage", URIRef(self.uuid_map[f"BaseVoltage.{base_kv}"]))

    def _add_ConnectivityNodes(self):
        for bus in self.dss.Bus:
            self._add_ConnectivityNode(bus.Name)
            self._add_Location(bus.Name, [bus.X], [bus.Y])

    def _add_ConnectivityNode(self, bus: str):
        if f"ConnectivityNode.{bus}" not in self.uuid_map:
            obj_uuid = str(uuid4())
            node = self._add_rdf_object("ConnectivityNode", name=bus)
            self.uuid_map[f"ConnectivityNode.{bus}"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"ConnectivityNode.{bus}"])

    def _add_Terminal(self, connecting_node: URIRef, element: object, bus: str = None, n_terminal: int = 1, phases="ABC"):
        node = self._add_rdf_object("Terminal", name=f"{element.Name}_T{n_terminal}")

        self._add_property(node, "ACDCTerminal.sequenceNumber", n_terminal)
        self._add_property(node, "Terminal.phases", self.cim[f"PhaseCode.{phases}"])
        self._add_property(node, "Terminal.ConductingEquipment", connecting_node)

        if bus is not None:
            cn_node = self._add_ConnectivityNode(bus)
            self._add_property(node, "Terminal.ConnectivityNode", cn_node)

    def _add_EnergySources(self):
        for vsource in self.dss.Vsource:
            self._add_EnergySource(vsource)

    def _add_EnergySource(self, vsource: object):
        node = self._add_rdf_object("EnergySource", name=vsource.Name)

        self._add_property(node, "EnergySource.nominalVoltage", vsource.BasekV * 1000.0)
        self._add_property(node, "EnergySource.voltageMagnitude", vsource.BasekV * 1000.0 * vsource.pu)
        self._add_property(node, "EnergySource.voltageAngle", math.radians(vsource.Angle))
        self._add_property(node, "EnergySource.R1", vsource.R1)
        self._add_property(node, "EnergySource.X1", vsource.X1)
        self._add_property(node, "EnergySource.R0", vsource.R0)
        self._add_property(node, "EnergySource.X0", vsource.X0)
        self._add_property(node, "Equipment.inService", vsource.Enabled)

        self._add_BaseVoltage(node, vsource.Bus1)

        for t, bus in enumerate([vsource.Bus1, vsource.Bus2]):
            busname = self._parse_busname(bus)
            phases = self._parse_phase_str(bus, n_phases=vsource.Phases)
            if phases:
                self._add_Terminal(node, vsource, n_terminal=t + 1, phases=phases)

    def _add_EnergySourcePhase(self):
        pass

    def _add_ACLineSegments(self):
        for line in self.dss.Line:
            if not line.Enabled:
                continue

            if line.Switch:
                self._add_Switch(line)
            else:
                node = self._add_rdf_object("ACLineSegment", name=line.Name)
                self._add_property(node, "Conductor.length", line.Length)
                self._add_property(node, "Equipment.inService", line.Enabled)
                self._add_BaseVoltage(node, line.Bus1)

                if line.LineCode is not None:
                    uri = self._add_PerLengthPhaseImedance(line.LineCode)
                    self._add_property(node, "ACLineSegment.PerLengthImpedance", uri)

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
                    self._add_Terminal(node, line, bus=self._parse_busname(bus), n_terminal=i + 1, phases=self._parse_ordered_phase_str(bus, line.Phases))

    def _add_ACLineSegmentPhase(self, aclinesegment_uri: URIRef, line: object, phase: str, sequence: int):
        node = self._add_rdf_object("ACLineSegmentPhase", name=f"{line.Name}_{phase}")
        self._add_property(node, "ACLineSegmentPhase.phase", self.cim[f"SinglePhaseKind.{phase}"])
        self._add_property(node, "ACLineSegmentPhase.sequenceNumber", sequence)
        self._add_property(node, "ACLineSegmentPhase.ACLineSegment", aclinesegment_uri)

    def _add_PerLengthPhaseImedance(self, linecode: object) -> URIRef:
        if f"PerLengthPhaseImpedance.{linecode.Name}" not in self.uuid_map:
            node = self._add_rdf_object("PerLengthPhaseImpedance", name=linecode.Name)
            self._add_property(node, "PerLengthPhaseImpedance.conductorCount", linecode.NPhases)

            self._add_PhaseImpedanceData(node, linecode)

            self.uuid_map[f"PerLengthPhaseImpedance.{linecode.Name}"] = str(node)

            return node
        else:
            return URIRef(self.uuid_map[f"PerLengthPhaseImpedance.{linecode.Name}"])

    def _add_PhaseImpedanceData(self, phase_impedance_uri: URIRef, linecode: object):
        for col in range(linecode.NPhases):
            for row in range(col, linecode.NPhases):
                node = self._add_rdf_object("PhaseImpedanceData", skip_mrid=True)
                self._add_property(node, "PhaseImpedanceData.row", row + 1)
                self._add_property(node, "PhaseImpedanceData.column", col + 1)
                self._add_property(node, "PhaseImpedanceData.r", linecode.RMatrix[row + col])
                self._add_property(node, "PhaseImpedanceData.x", linecode.XMatrix[row + col])
                self._add_property(node, "PhaseImpedanceData.b", linecode.CMatrix[row + col] * 2 * math.pi * linecode.BaseFreq / 1e9)
                self._add_property(node, "PhaseImpedanceData.PhaseImpedance", phase_impedance_uri)

    def _add_Switch(self, line: object):
        node = self._add_rdf_object("Switch", name=line.Name)
        self._add_property(node, "Equipment.inService", line.Enabled)

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
        node = self._add_rdf_object("SwitchPhase", name=f"{line.Name}_{phase}")
        self._add_property(node, "SwitchPhase.phase", self.cim[f"SinglePhaseKind.{phase}"])
        self._add_property(node, "SwitchPhase.sequenceNumber", sequence)
        self._add_property(node, "SwitchPhase.Switch", aclinesegment_uri)

    def _add_EnergyConsumers(self):
        for load in self.dss.Load:

            node = self._add_rdf_object("EnergyConsumer", name=load.Name)

            self._add_property(node, "EnergyConsumer.p", load.kW * 1000.0)
            self._add_property(node, "EnergyConsumer.q", load.kvar * 1000.0)
            self._add_property(node, "EnergyConsumer.customerCount", load.NumCust)
            self._add_property(node, "EnergyConsumer.grounded", self._is_grounded([load.Bus1], load.Conn != 0))
            self._add_property(node, "Equipment.inService", load.Enabled)
            self._add_BaseVoltage(node, load.Bus1)

            if load.Conn != 0:
                self._add_property(node, "EnergyConsumer.phaseConnection", self.cim["PhaseShuntConnectionKind.D"])
            else:
                self._add_property(node, "EnergyConsumer.phaseConnection", self.cim["PhaseShuntConnectionKind.Y"])

            lrc_node = self._add_LoadResponseCharacteristic(load.Model)
            if lrc_node is not None:
                self._add_property(node, "EnergyConsumer.LoadResponse", lrc_node)

            phases = self._parse_phase_str(load.Bus1, load.Phases, load.kV, load.Conn != 0)
            self._add_EnergyConsumerPhases(node, load, phases)
            self._add_Terminal(node, load, bus=self._parse_busname(load.Bus1), phases=phases)

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
                node = self._add_rdf_object("EnergyConsumerPhase", name=f"{load.Name}_{ph}")
                self._add_property(node, "EnergyConsumerPhase.p", load.kW * 1000.0 / load.Phases)
                self._add_property(node, "EnergyConsumerPhase.q", load.kvar * 1000.0 / load.Phases)
                self._add_property(node, "EnergyConsumerPhase.phase", self.cim[f"SinglePhaseKind.{ph}"])
                self._add_property(node, "EnergyConsumerPhase.EnergyConsumer", energy_consumer_uri)

    def _add_LoadResponseCharacteristic(self, model):
        if f"LoadResponseCharacteristic.{model}" not in self.uuid_map:
            if model == 1:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Constant kVA")
                self._add_property(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantPower", 100)
            elif model == 2:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Constant Z")
                self._add_property(node, "LoadResponseCharacteristic.pConstantImpedance", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            elif model == 3:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Motor")
                self._add_property(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            elif model == 4:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Mix Motor/Res")
                self._add_property(node, "LoadResponseCharacteristic.exponentModel", True)
                self._add_property(node, "LoadResponseCharacteristic.pVoltageExponent", 1)
                self._add_property(node, "LoadResponseCharacteristic.qVoltageExponent", 2)
            elif model == 5:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Constant I")
                self._add_property(node, "LoadResponseCharacteristic.pConstantCurrent", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantCurrent", 100)
            elif model == 6:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Variable P, Fixed Q")
                self._add_property(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantPower", 100)
            elif model == 7:
                node = self._add_rdf_object("LoadResponseCharacteristic", name="Variable P, Fixed X")
                self._add_property(node, "LoadResponseCharacteristic.pConstantPower", 100)
                self._add_property(node, "LoadResponseCharacteristic.qConstantImpedance", 100)
            else:
                return None

            self.uuid_map[f"LoadResponseCharacteristic.{model}"] = str(node)

            return node

        else:
            return URIRef(self.uuid_map[f"LoadResponseCharacteristic.{model}"])


if __name__ == "__main__":
    d = DssExport("examples/case3_balanced.dss")

    d.graph.serialize("out/test_opendss_convert.xml", max_depth=1, format="pretty-xml")
