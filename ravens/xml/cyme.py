import math
import pathlib

from ast import literal_eval

from rdflib.namespace import Namespace, RDF
from rdflib.term import URIRef
from rdflib import Literal

from ravens.logging import logger
from ravens.data import _DEFAULT_CYME_CIM_NAMESPACE, _DEFAULT_CYME_NAMESPACE
from ravens.xml.graph import RDFGraph

# ohm.m @ 20C
material_resistivity = {"CYMEConductorMaterial.copper": 1.68e-8, "CYMEConductorMaterial.aluminum": 2.82e-8}


class CymeConverter(RDFGraph):
    def __init__(self, profile_path: pathlib.Path | str, cim_namespace: str = _DEFAULT_CYME_CIM_NAMESPACE, cyme_namespace: str = _DEFAULT_CYME_NAMESPACE, prune_remaining_cyme: bool = False):
        super().__init__(profile_path=profile_path, cim_namespace=cim_namespace, uuid_format=lambda x: "_" + x.upper())

        self.cyme = Namespace(cyme_namespace + "#")
        self.graph.bind("cyme", self.cyme, override=True)

        self.to_remove = set()

        # TODO: other load models
        self.load_response_values = {"CYMELoadFormat.kw_kvar": {"name": "Constant kVA", "values": {"pConstantPower": 100.0, "qConstantPower": 100.0}}}
        self.load_response_uris = {}

        self.equip_container_uris = {}

        self.convert_cyme_cable_concentric_neutrals()
        self.convert_cyme_customer_class()
        self.convert_cyme_customer_load()
        self.convert_cyme_customer_load_value()
        self.convert_cyme_structure()
        self.convert_cyme_connection_status()
        self.convert_cimconductingequipment_structure_id()

        self.fix_EnergyConsumerPhase()
        self.fix_WireInfo()
        self.fix_Terminal()
        self.fix_Transformer_Terminal_phases()
        self.fix_Per_Length_Phase_Impedance_indices()

        if prune_remaining_cyme:
            self.remove_cyme_objects()

        self.prune_triples()

    def _combine_phasecodes(self, phase_codes: set[str] | list[str]):
        phase_str = ""
        if any(self.cim[f"PhaseCode.{pc}"] in phase_codes for pc in ["A", "AB", "ABC", "AC", "AN", "ABN", "ACN", "ABCN"]):
            phase_str += "A"
        if any(self.cim[f"PhaseCode.{pc}"] in phase_codes for pc in ["B", "AB", "ABC", "BC", "BN", "ABN", "BCN", "ABCN"]):
            phase_str += "B"
        if any(self.cim[f"PhaseCode.{pc}"] in phase_codes for pc in ["C", "AC", "ABC", "BC", "CN", "ACN", "BCN", "ABCN"]):
            phase_str += "C"

        if (self.cim["PhaseCode.s1"] in phase_codes and self.cim["PhaseCode.s2"]) or (self.cim["PhaseCode.s1N"] in phase_codes and self.cim["PhaseCode.s2N"]) in phase_codes:
            phase_str = "s12"
        elif self.cim["PhaseCode.s1"] in phase_codes or self.cim["PhaseCode.s1N"] in phase_codes:
            phase_str = "s1"
        elif self.cim["PhaseCode.s2"] in phase_codes or self.cim["PhaseCode.s2N"] in phase_codes:
            phase_str = "s2"

        if any(self.cim[f"PhaseCode.{pc}"] in phase_codes for pc in ["AN", "BN", "CN", "ABN", "BCN", "ACN", "ABCN", "s12N", "s1N", "s2N"]):
            phase_str += "N"

        if not phase_str:
            phase_str = "ABC"

        return self.cim[f"PhaseCode.{phase_str}"]

    def prune_triples(self):
        for triple in self.to_remove:
            self.graph.remove(triple)

    def remove_cyme_objects(self):
        for s, o in self.graph.subject_objects(predicate=RDF.type):
            if str(o).startswith(str(self.cyme)):
                for triple in self.graph.triples((s, None, None)):
                    self.to_remove.add(triple)

        for p in self.graph.predicates():
            if str(p).startswith(str(self.cyme)):
                for triple in self.graph.triples((None, p, None)):
                    self.to_remove.add(triple)

    def convert_cyme_cable_concentric_neutrals(self):
        cableinfo_to_replace = set()
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim["CableInfo"]):
            cccn_ref = self.graph.value(subject=s, predicate=self.cyme["CYMECableConstruction.CableConcentricNeutrals"])
            if cccn_ref is not None:
                # Extract the mRID without public_id prefix for naming
                name = str(self.graph.value(subject=s, predicate=self.cim["IdentifiedObject.name"]))
                node = self.build_cim_obj("ConcentricNeutralCableInfo", name=name, skip_mrid=True)

                for p, o in self.graph.predicate_objects(subject=s):
                    self.to_remove.add((s, p, o))
                    if not str(p).startswith(str(self.cyme)) and p != RDF.type:
                        self.add_triple(node, str(p).removeprefix(self.cim), o)

                neutral_radius = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme["CYMECableConcentricNeutrals.wireDiameter"]).value) / 2  # type: ignore
                neutral_gmr = neutral_radius * 0.7788
                rdc20 = material_resistivity.get(str(self.graph.value(subject=cccn_ref, predicate=self.cyme["CYMECableConcentricNeutrals.material"])).removeprefix(self.cyme), 2e-8) / (math.pi * neutral_radius**2)
                neutral_count = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme["CYMECableConcentricNeutrals.numberOfWires"]).value)  # type: ignore
                diameter_over_neutral = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme["CYMECableConcentricNeutrals.outerDiameter"]).value)  # type: ignore

                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRadius", neutral_radius)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandGmr", neutral_gmr)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRDC20", rdc20)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandCount", neutral_count)
                self.add_triple(node, "ConcentricNeutralCableInfo.diameterOverNeutral", diameter_over_neutral)

                cableinfo_to_replace.add((s, node))
                self.to_remove.add((cccn_ref, None, None))
            else:
                for p, o in self.graph.predicate_objects(subject=s):
                    if str(p).startswith(str(self.cyme)):
                        self.to_remove.add((s, p, o))

        for old_o, new_o in cableinfo_to_replace:
            for s, p, _ in list(self.graph.triples((None, None, old_o))):
                self.graph.add((s, p, new_o))
                self.to_remove.add((s, p, old_o))

    def convert_cyme_customer_class(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme["CYMECustomerClass"]):
            self.to_remove.add((s, None, None))
            name = str(self.graph.value(subject=s, predicate=self.cim["IdentifiedObject.name"]))
            node = self.build_cim_obj("LoadGroup", name=name)

            for _s in self.graph.subjects(predicate=self.cyme["CYMECustomerLoad.CustomerClass"], object=s):
                assert self.graph.value(subject=_s, predicate=RDF.type) == self.cyme["CYMECustomerLoad"]
                ec_uri = self.graph.value(subject=_s, predicate=self.cyme["CYMECustomerLoad.EnergyConsumer"])
                self.add_triple(URIRef(str(ec_uri)), "EnergyConsumer.LoadGroup", node)

    def convert_cyme_customer_load(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme["CYMECustomerLoad"]):
            self.to_remove.add((s, None, None))

    def convert_cyme_customer_load_value(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme["CYMECustomerLoadValue"]):
            cust_load = self.graph.value(subject=s, predicate=self.cyme["CYMECustomerLoadValue.CustomerLoad"])
            ec_uri = self.graph.value(subject=cust_load, predicate=self.cyme["CYMECustomerLoad.EnergyConsumer"])

            for k in ["p", "q"]:
                v = self.graph.value(subject=s, predicate=self.cyme[f"CYMECustomerLoadValue.{k}"])

                # obtain previous ec value and modify
                k_old = self.graph.value(subject=ec_uri, predicate=self.cim[f"EnergyConsumer.{k}"])
                if k_old is not None:
                    self.graph.remove((URIRef(str(ec_uri)), self.cim[f"EnergyConsumer.{k}"], None))  # remove the triple to update it with new val
                    v = float(v) + float(k_old)

                if v is not None:
                    self.add_triple(URIRef(str(ec_uri)), f"EnergyConsumer.{k}", v)

            self.add_LoadResponseCharacteristic(URIRef(str(ec_uri)), str(self.graph.value(subject=s, predicate=self.cyme["CYMECustomerLoadValue.loadFormat"])).removeprefix(self.cyme))

            self.to_remove.add((s, None, None))

    def add_LoadResponseCharacteristic(self, subject_uri: URIRef, cyme_load_format: str):
        lrc_values = self.load_response_values.get(cyme_load_format, None)
        if lrc_values is not None:
            if cyme_load_format not in self.load_response_uris:
                node = self.build_cim_obj("LoadResponseCharacteristic", name=lrc_values["name"], skip_mrid=True)
                for k, v in lrc_values["values"].items():
                    self.add_triple(node, f"LoadResponseCharacteristic.{k}", v)

                self.load_response_uris[cyme_load_format] = node

            self.add_triple(subject_uri, "EnergyConsumer.LoadResponse", self.load_response_uris[cyme_load_format])

    def convert_cyme_structure(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme["CYMEStructure"]):
            self.to_remove.add((s, None, None))

    def convert_cyme_connection_status(self):
        for s, p, o in self.graph.triples((None, self.cyme["CYMEConnectionStatus.connectionStatusType"], None)):
            if str(o).endswith("Connected"):
                self.add_triple(URIRef(str(s)), "Equipment.inService", True)
            else:
                self.add_triple(URIRef(str(s)), "Equipment.inService", False)

            self.to_remove.add((s, p, o))

    def convert_cimconductingequipment_structure_id(self):
        for s, p, o in self.graph.triples((None, self.cyme["CIMConductingEquipment.StructureID"], None)):
            if o not in self.equip_container_uris:
                node = self.build_cim_obj("EquipmentContainer", name=str(o), skip_mrid=True)
                self.equip_container_uris[o] = node

            self.add_triple(URIRef((str(s))), "Equipment.EquipmentContainer", self.equip_container_uris[o])
            self.to_remove.add((s, p, o))

    def fix_EnergyConsumerPhase(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim["EnergyConsumerPhase"]):
            for k in ["p", "q"]:
                v = self.graph.value(subject=s, predicate=self.cim[f"EnergyConsumerPhase.{k}Fixed"])
                if v is not None:
                    self.add_triple(URIRef((str(s))), f"EnergyConsumerPhase.{k}", v)
                    self.to_remove.add((s, self.cim[f"EnergyConsumerPhase.{k}Fixed"], v))

    def fix_WireInfo(self):
        for wi in ["WireInfo", "CableInfo", "OverheadWireInfo", "ConcentricNeutralCableInfo", "TapeShieldCableInfo"]:
            for s in self.graph.subjects(predicate=RDF.type, object=self.cim[wi]):
                radius = self.graph.value(subject=s, predicate=self.cim["WireInfo.radius"])
                material = self.graph.value(subject=s, predicate=self.cim["WireInfo.material"])

                if self.graph.value(subject=s, predicate=self.cim["WireInfo.gmr"]) is None:
                    if radius is not None:
                        self.add_triple(URIRef(str(s)), "WireInfo.gmr", literal_eval(radius.value) * 0.7788)  # type: ignore

                if self.graph.value(subject=s, predicate=self.cim["WireInfo.rDC20"]) is None:
                    if radius is not None and material is not None:
                        self.add_triple(URIRef(str(s)), "WireInfo.rDC20", material_resistivity.get(str(material).removeprefix(self.cyme), 2e-8) / (math.pi * literal_eval(radius.value) ** 2))  # type: ignore

    def fix_Terminal(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim["Terminal"]):
            seq = self.graph.value(subject=s, predicate=self.cim["Terminal.sequenceNumber"])
            if seq is not None:
                self.add_triple(URIRef(str(s)), "ACDCTerminal.sequenceNumber", seq)
                self.to_remove.add((s, self.cim["Terminal.sequenceNumber"], seq))

    def fix_Transformer_Terminal_phases(self):
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim["PowerTransformer"]):
            phases_lists = {}
            for tank in self.graph.subjects(object=s, predicate=self.cim["TransformerTank.PowerTransformer"]):
                for tank_end in self.graph.subjects(object=tank, predicate=self.cim["TransformerTankEnd.TransformerTank"]):
                    end_number = int(self.graph.value(subject=tank_end, predicate=self.cim["TransformerEnd.endNumber"]).value)  # type: ignore
                    if end_number not in phases_lists:
                        phases_lists[end_number] = set()

                    phases_lists[end_number].add(self.graph.value(subject=tank_end, predicate=self.cim["TransformerTankEnd.phases"]))

            combined_phases = {en: self._combine_phasecodes(pl) for en, pl in phases_lists.items()}
            if combined_phases:
                for term in self.graph.subjects(object=s, predicate=self.cim["Terminal.ConductingEquipment"]):
                    seq_num = int(self.graph.value(subject=term, predicate=self.cim["ACDCTerminal.sequenceNumber"]).value)  # type: ignore
                    self.graph.remove((term, self.cim["Terminal.phases"], None))
                    self.graph.add((term, self.cim["Terminal.phases"], combined_phases[seq_num]))

    def fix_Per_Length_Phase_Impedance_indices(self):
        """
        Expects `Phase Impedance Data` of following format:
        - Increasing Sequence Numbers
        - Either specifies triangular matrix, or full matrix
        - First sequence number either starts at 1 or connector_count + 1
        """
        for PLPI in self.graph.subjects(predicate=RDF.type, object=self.cim["PerLengthPhaseImpedance"]): 
            conductor_count = int(self.graph.value(subject=PLPI, predicate=self.cim["PerLengthPhaseImpedance.conductorCount"]).value)

            #Scan Sequence List
            sequence_numbers = []
            has_row = []
            has_col = []
            for phase_info in self.graph.subjects(predicate=self.cim["PhaseImpedanceData.PhaseImpedance"], object=PLPI):
                sequence_numbers.append(int(self.graph.value(subject=phase_info, predicate=self.cim["PhaseImpedanceData.sequenceNumber"]).value))
                has_row.append(1 if self.graph.value(subject=phase_info, predicate=self.cim["PhaseImpedanceData.row"]) is not None else 0)
                has_col.append(1 if self.graph.value(subject=phase_info, predicate=self.cim["PhaseImpedanceData.column"]) is not None else 0)
            
            
            #Validate Sequences are in an acceptable format
            #ignore empty phase impedances
            if len(sequence_numbers) == 0: 
                continue

            #ensure that sequence numbers are continuous
            s_sn = sorted(sequence_numbers) 
            if not all(s_sn[i+1] - s_sn[i] == 1 for i in range(len(s_sn) - 1)):
                # Create mapping from old sequence numbers to new contiguous ones
                seq_mapping = {}
                for i, old_seq in enumerate(s_sn):
                    new_seq = s_sn[0] + i  # Start from first value, add index
                    seq_mapping[old_seq] = new_seq
                
                # Update sequence_numbers array with corrected values
                sequence_numbers = [seq_mapping[seq] for seq in sequence_numbers]

            #correct sequence numbers to obey second row indexing
            seq_jump = s_sn[0] != conductor_count+1 #check to see if sequence starts at conductor count + 1 or if it starts at 1
            sequence_numbers = [s+(conductor_count)*seq_jump for s in sequence_numbers]
            if min(sequence_numbers) != conductor_count+1:
                raise ValueError("Initial Phase Impedance sequenceNumber is not of a known acceptable format.")

            
            #handle supported matrix specification methods
            rows = []
            cols = []
            if len(sequence_numbers) == conductor_count*(conductor_count+1)/2: #handle triangular specification
                for sn in sequence_numbers:
                    sn -= conductor_count
                    rows.append(r := (math.isqrt(8 * (sn-1) + 1) - 1) // 2 + 1)
                    cols.append((sn-1) - (r-1) * r // 2 + 1)
            elif len(sequence_numbers) == conductor_count**2: #handle full matrix specification
                for sn in sequence_numbers:
                    cols.append((sn - (conductor_count+1))%conductor_count)
                    rows.append((sn - (conductor_count+1) - cols[-1])/conductor_count + 1)
                    cols[-1] += 1
            else:  
                raise ValueError("Initial Phase Impedance sequenceNumber is not of a known acceptable format.")
                

            #Apply Corrected Row/Cols
            for i, phase_info in enumerate(self.graph.subjects(predicate=self.cim["PhaseImpedanceData.PhaseImpedance"], object=PLPI)):
                self.graph.add((phase_info, self.cim["PhaseImpedanceData.row"], Literal(int(rows[i]))))
                self.graph.add((phase_info, self.cim["PhaseImpedanceData.column"], Literal(int(cols[i]))))


                
                
                


if __name__ == "__main__":
    # TODO: need synthetic feeder exported from CYME for example
    from ravens import RavensData
    file_path = "../extern_data/Delaware_Feeder_161_v7_BESS.xml"
    d = RavensData().import_cyme_cim(file_path)
    d.dump("../extern_data/tmp.json",indent=2)