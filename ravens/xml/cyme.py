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
    def __init__(self, profile_path: pathlib.Path | str, cim_namespace: str = _DEFAULT_CYME_CIM_NAMESPACE, cyme_namespace: str = _DEFAULT_CYME_NAMESPACE, prune_remaining_cyme: bool = False, PEC_corrections:dict[str, str|list]={}):
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

        unit_type,pv_set,wind_set = None, set(), set()
        if "unit_type" in PEC_corrections.keys():
            unit_type = PEC_corrections["unit_type"]
        if "pv" in PEC_corrections.keys():
            pv_set = set(PEC_corrections["pv"])
        if "wind" in PEC_corrections.keys():
            wind_set = set(PEC_corrections["wind"])       
        self.replace_rotatingmachine_with_powerelectronicsconnection(unit_type,pv_set,wind_set)

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

    def replace_rotatingmachine_with_powerelectronicsconnection(self,unit_type:str|None=None,pv_set:set=set(),wind_set:set=set()):
        #Replace RotatingMachine objects with PowerElectronicsConnection objects.
        rotating_machines_to_replace = []
        _float = lambda x,default = 0.0: float(x) if x != None else float(default) 
        _bool = lambda x,default = True: bool(x) if x != None else bool(default) 

        rotating_machine_types = ["AsynchronousMachine","SynchronousMachine"]
        
        # Find all RotatingMachine objects
        for rm_type in rotating_machine_types:
            for rm in self.graph.subjects(predicate=RDF.type, object=self.cim[rm_type]):
                # Get properties from RotatingMachine
                try:
                    name = str(self.graph.value(subject=rm, predicate=self.cim["IdentifiedObject.name"]))
                    rated_s = _float(self.graph.value(subject=rm, predicate=self.cim["RotatingMachine.ratedS"]),None)
                    rated_u = _float(self.graph.value(subject=rm, predicate=self.cim["RotatingMachine.ratedU"]),None)
                    rated_pf = _float(self.graph.value(subject=rm, predicate=self.cim["RotatingMachine.ratedPowerFactor"]),1.0)
                    p_value = _float(self.graph.value(subject=rm, predicate=self.cim["RotatingMachine.p"]),0.0)
                    in_service = _bool(self.graph.value(subject=rm, predicate=self.cim["Equipment.inService"]),True)
                except:
                    logger.warning(f"RotatingMachine '{name or "unknown name"}' is missing input parameters, skipping conversion")
                
                # Determine unit type based 
                if (unit_type == "pv" or name in pv_set) and name not in wind_set:
                    peu_type, peu_name = "PhotoVoltaicUnit", f"{name}_PVPanels"
                elif (unit_type == "wind" or name in wind_set) and name not in pv_set:
                    peu_type, peu_name = "PowerElectronicsWindUnit", f"{name}_WindUnit"
                else:
                    continue
                
                
                # Calculate reactive power
                q_value = rated_s * (1.0 - rated_pf)
                
                # Calculate max/min Q
                max_q = math.sqrt((p_value / rated_pf) ** 2 - p_value ** 2)
                min_q = -max_q
                
                # Create PowerElectronicsConnection
                pec_node = self.build_cim_obj("PowerElectronicsConnection", name=name)
                
                # Set PowerElectronicsConnection properties
                self.add_triple(pec_node, "PowerElectronicsConnection.maxIFault", 1.0 / 0.707)
                self.add_triple(pec_node, "PowerElectronicsConnection.p", p_value)
                self.add_triple(pec_node, "PowerElectronicsConnection.q", q_value)
                self.add_triple(pec_node, "PowerElectronicsConnection.ratedS", rated_s)
                self.add_triple(pec_node, "PowerElectronicsConnection.ratedU", rated_u)
                self.add_triple(pec_node, "PowerElectronicsConnection.maxQ", max_q)
                self.add_triple(pec_node, "PowerElectronicsConnection.minQ", min_q)
                self.add_triple(pec_node, "Equipment.inService", in_service)

                

                terminals = list(self.graph.subjects(object=rm, predicate=self.cim["Terminal.ConductingEquipment"]))
                for terminal in terminals:
                    # REMOVE old triple: Terminal -> ConductingEquipment -> RotatingMachine
                    self.graph.remove((terminal, self.cim["Terminal.ConductingEquipment"], rm))
                    # ADD new triple: Terminal -> ConductingEquipment -> PowerElectronicsConnection
                    self.graph.add((terminal, self.cim["Terminal.ConductingEquipment"], pec_node))
    
                
                # Create PowerElectronicsUnit
                peu_node = self.build_cim_obj(peu_type, name=peu_name)
                self.add_triple(peu_node, "PowerElectronicsUnit.minP", 0.0)
                self.add_triple(peu_node, "PowerElectronicsUnit.maxP", rated_s * rated_pf)
                
                # Link PEU to PEC
                self.graph.add((peu_node, self.cim["PowerElectronicsConnection.PowerElectronicsUnit"], pec_node))
                
                # Mark RotatingMachine for removal
                rotating_machines_to_replace.append(rm)
                
                logger.info(f"Converted RotatingMachine '{name}' to PowerElectronicsConnection with {peu_type}")
            
        # Remove all RotatingMachine objects
        for rm in rotating_machines_to_replace:
            self.to_remove.add((rm, None, None))


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
        - Either specifies upper triangular matrix, or full matrix
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
            if len(sequence_numbers) == 0 or (all(has_row) and all(has_col)): 
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
                r = c = 1
                for i in range(len(sequence_numbers)):
                    if c > conductor_count:
                        r +=1
                        c = r
                    rows.append(r)
                    cols.append(c)
                    c+=1
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
    pass
  