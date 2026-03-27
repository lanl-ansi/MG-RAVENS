import json
import pathlib
import traceback

from ast import literal_eval
from collections import namedtuple
from copy import deepcopy
from datetime import datetime

from rdflib.namespace import RDF
from rdflib.term import URIRef, Literal

from ravens import __version__
from ravens.logging import logger
from ravens.data import _DEFAULT_CIM_NAMESPACE
from ravens.schema import SchemaTemplate, RavensSchema

from ravens.xml.xml2ravens import RavensImport
from ravens.xml.simplifiers.tl_simp import tl_simp as tl
from ravens.xml.simplifiers.ll_simp import ll_simp as ll
from ravens.xml.simplifiers.ravens_simplifier import simplifier as simp
from ravens.xml.simplifiers.wire2PL import wire2PL as w2pl
from ravens.xml.simplifiers.tank2transformer import tank2transformer as t2t
from ravens.xml.graph import RDFGraph



class CrowsImport(RavensImport):
    def __init__(
        self,
        network_profile: pathlib.Path | str | RDFGraph,  
        cim_profile_path: pathlib.PosixPath | str | None = None, 
        remove_BIS: bool = True, 
        simplify_AC: bool = True,
        simplify_tank: bool = True,
        tank_merge: bool = True,
        schema_template: SchemaTemplate | None = None, 
        cim_namespace: str = _DEFAULT_CIM_NAMESPACE, 
        schema: RavensSchema | None = None
    ):
        


        # Initialize the parent class with its expected parameters
        super().__init__(
            network_profile = network_profile,
            schema_template = schema_template,
            cim_namespace = cim_namespace,
            schema = schema,
        )

        self.status = 0 #data is un-simplified
        self.__name__ = "User Facing Simplifier"

        #Save Ravens Init Parameters
        self.network_profile = deepcopy(network_profile)
        self.schema_template = deepcopy(schema_template)
        self.cim_namespace = deepcopy(cim_namespace)
        self.schema = deepcopy(schema)

        #Simplification Parameters
        self.remove_BIS = remove_BIS
        self.simplify_AC = simplify_AC
        self.simplify_tank = simplify_tank
        self.tank_merge = tank_merge


        #Component Simplification
        if self.simplify_AC:
            self._convert_all_to_puz() #wire info simplification
        if self.simplify_tank:
            self._convert_all_to_std_trans() #transformer simplification

        #Top Level Simplification
        self._remove_superfluous_objects() #Does work of TL Simplification

        #Lower Level Simplification
        self._simplify_lower_level_members()
        
        self._cleanup()

        self.status = 1 #data is simplified

    def _remove_superfluous_objects(self):
        'removes objects that are unnecessary for OPF'
        targets = ['Location', 'EnergyConnectionProfile','CoordinateSystem','TopologicalNode',
                    'Group','SwitchingAction','Fault','Location','DynamicsFunctionBlock','Document',
                    'ActivityRecord','EnvironmentalPhenomenon','Asset','ProposedSiteLocation','FossilFuelCosts','OutageScenario',
                    'CommunityFacility','EconomicProperty','EnergyPrices','PredictedEmissions','AlgorithmProperties','ProposedAssetOption',
                    'ProposedAsset','EstimatedCost','Application','Algorithm','Message']
        tl_simp = tl(targets) #define Top Level Simplifier Function
        self.data = tl_simp(self.data) #simplify MG-RAVENS Data

    def _convert_all_to_puz(self):
        'converts all WireInfo type objects into PerLengthImpedance objects'
        self.data = w2pl(self.data) #simplify MG-RAVENS Data

    def _convert_all_to_std_trans(self):
        'converts all tank-based transformer objects into standard transformer objects'
        self.data = t2t(self.data,tank_merge=self.tank_merge)

    def _simplify_lower_level_members(self):
        'simplifies lower level members of all objects'
        #fixed input of optimal simplification targets
        targets = ["IdentifiedObject.mRID","IdentifiedObject.description","IdentifiedObject.aliasName","PowerSystemResource.Location",
                "BasicIntervalSchedule.startTime","EnergyConsumerSchedule.endTime","EnergyConsumerSchedule.startDate",
                "EnergyConsumerSchedule.startDay","EnergyConsumerSchedule.IrregularTimePoints",
                "PerLengthLineParameter.WireAssemblyInfo","WireAssemblyInfo", "TapChangerInfo",
                "ACDCConverter","EquivalentEquipment","Connector","EarthFaultCompensator","Clamp",
                "SeriesCompensator","Ground", "PowerSystemResource.GenericAction", "WireSegment",
                "StaticVarCompensator","ExternalNetworkInjection","FrequencyConverter","PhaseTapChanger"]
        pattern = {'RegulatingControl':["RegulatingControl.targetValue","RegulatingControl.targetDeadband"],
                'OperationalLimitType':["OperationalLimitType.direction","OperationalLimitType.acceptableDuration"],
                'EnergySource':["ConductingEquipment.Terminals","ConductingEquipment.BaseVoltage","EnergySourcePhase.phase","Equipment.inService",
                                "EnergySource.connectionKind","EnergySource.nominalVoltage","EnergySource.activePower","IdentifiedObject.name",
                                "EnergySource.reactivePower","EnergySource.voltageMagnitude","EnergySource.pMin","EnergySource.pMax",
                                "EnergySource.qMin","EnergySource.qMax","EnergySource.connectionKind","EnergySource.r","EnergySource.x",
                                "EnergySource.voltageMagnitude","EnergySource.voltageAngle","EnergySource.vpairMin","EnergySource.vpairMax",
                                "EnergySource.r0","EnergySource.x0"],
                'EnergyConsumer':["ConductingEquipment.Terminals","ConductingEquipment.BaseVoltage","IdentifiedObject.name",
                                  "EnergyConsumer.LoadResponse","EnergyConsumer.EnergyConsumerPhase","EnergyConsumer.p","EnergyConsumer.q",
                                  "EnergyConsumer.grounded","EnergyConsumer.phaseConnection"],
                'ACLineSegment':["IdentifiedObject.name","ConductingEquipment.Terminals","ACLineSegment.PerLengthImpedance",
                                 "ACLineSegment.PerLengthImpedance","ACLineSegment.WireSpacingInfo","PowerSystemResource.AssetDatasheet",
                                 "Conductor.length","Equipment.inService","ACLineSegment.ACLineSegmentPhase"],
                'Switch':["IdentifiedObject.name","ConductingEquipment.Terminals","Switch.SwitchPhase","Equipment.inService","Switch.open",
                          "PowerSystemResource.AssetDatasheet"],
                'PowerElectronicsConnection':["IdentifiedObject.name","Equipment.inService","ConductingEquipment.Terminals",
                                              "PowerElectronicsConnection.PowerElectronicsUnit","ConductingEquipment.BaseVoltage",
                                              "PowerElectronicsConnection.ratedU","PowerElectronicsConnection.maxP","PowerElectronicsConnection.ratedS",
                                              "PowerElectronicsConnection.minP","PowerElectronicsConnection.minQ","PowerElectronicsConnection.maxQ",
                                              "PowerElectronicsConnection.p","PowerElectronicsConnection.q","PowerElectronicsConnection.r"
                                              "PowerElectronicsConnection.x"],
                'ShuntCompensator':["IdentifiedObject.name","Equipment.inService","ConductingEquipment.Terminals","LinearShuntCompensator.bPerSection",
                                    "LinearShuntCompensator.gPerSection"],
                'RotatingMachine':["IdentifiedObject.name","Equipment.inService","ConductingEquipment.Terminals","RotatingMachine.GeneratingUnit",
                                   "RotatingMachine.ratedS","RotatingMachine.ratedPowerFactor","ConductingEquipment.BaseVoltage","RotatingMachine.ratedU",
                                   "RotatingMachine.minQ","SynchronousMachine.minQ","RotatingMachine.ratedPowerFactor","RotatingMachine.maxQ",
                                   "SynchronousMachine.maxQ","RotatingMachine.p","RotatingMachine.q"],
                'PowerTransformer':["IdentifiedObject.name","Equipment.inService","ConductingEquipment.Terminals","PowerTransformer.PowerTransformerEnd",
                                    "PowerTransformer.TransformerTank","PowerSystemResource.AssetDatasheet"],
                'RatioTapChanger':["IdentifiedObject.name","Equipment.inService","ConductingEquipment.Terminals","TapChanger.highStep","TapChanger.lowStep","TapChanger.step",
                                   "TapChanger.ltcFlag","TapChanger.neutralU","RatioTapChanger.stepVoltageIncrement","TapChanger.TapChangerControl","TapChanger.TapChangerRatio"],
                'WireInfo':["IdentifiedObject.name","WireInfo.radius","WireInfo.gmr","Ravens.cimObjectType","WireInfo.rAC25","WireInfo.rDC20",
                            "ConcentricNeutralCableInfo.neutralStrandRDC20","ConcentricNeutralCableInfo.neutralStrandCount",
                            "ConcentricNeutralCableInfo.neutralStrandRadius","ConcentricNeutralCableInfo.neutralStrandGmr",
                            "CableInfo.diameterOverJacket","WireInfo.insulationThickness","TapeShieldCableInfo.tapeThickness",
                            "TapeShieldCableInfo.tapeLap","ConcentricNeutralCableInfo.diameterOverNeutral"]}
        unit_pattern = {'PowerElectronicsConnection.PowerElectronicsUnit':["Ravens.cimObjectType","Equipment.inService",
                                    "ConductingEquipment.Terminals","PowerElectronicsUnit.maxP","PowerElectronicsUnit.minP",
                                    "BatteryUnit.storedE","BatteryUnit.BatteryUnitEfficiency","BatteryUnit.ratedE","BatteryUnit.RatedE"],
                    'BatteryUnitEfficiency':["BatteryUnitEfficiency.limitEnergy","BatteryUnitEfficiency.efficiencyCharge",
                                                "BatteryUnitEfficiency.efficiencyDischarge","BatteryUnitEfficiency.idlingActivePower",
                                                "BatteryUnitEfficiency.idlingReactivePower"],
                    'RotatingMachine.GeneratingUnit':["GeneratingUnit.minOperatingP","GeneratingUnit.maxOperatingP"],
                    'PowerTransformer.PowerTransformerEnd':["IS_MULTI","TransformerEnd.endNumber","PowerTransformerEnd.connectionKind","PowerTransformerEnd.ratedU",
                                                            "PowerTransformerEnd.ratedS","PowerTransformerEnd.ratedI","TransformerEnd.StarImpedance",
                                                            "TransformerEnd.MeshImpedance", "PowerTransformerEnd.r","TransformerEnd.CoreAdmittance",
                                                            "TransformerEnd.RatioTapChanger","TransformerEnd.endNumber","ConductingEquipment.Terminals"],
                    'PowerTransformer.TransformerTank':["IS_MULTI","TransformerTank.TransformerTankEnd","ConductingEquipment.Terminals","PowerSystemResource.AssetDatasheet"],
                    'TransformerEnd.MeshImpedance':["TransformerMeshImpedance.r"],
                    'TransformerEnd.StarImpedance':["TransformerStarImpedance.x","TransformerStarImpedance.r"],
                    'TransformerEnd.CoreAdmittance':["TransformerCoreAdmittance.g","TransformerCoreAdmittance.b"],
                    'TransformerTankInfo.TransformerEndInfos':["IS_MULTI","TransformerEndInfo.ratedU","TransformerEndInfo.ratedS","TransformerEndInfo.TransformerStarImpedance",
                                                               "TransformerEndInfo.r","TransformerEndInfo.x","TransformerEndInfo.EnergisedEndShortCircuitTests",
                                                               "TransformerEndInfo.EnergisedEndNoLoadTests","TransformerEndInfo.connectionKind","TransformerEndInfo.emergencyS",
                                                               "TransformerEndInfo.ratedI"],
                    'TransformerEndInfo.EnergisedEndShortCircuitTests':["IS_MULTI","ShortCircuitTest.leakageImpedance"],
                    'TransformerEndInfo.EnergisedEndNoLoadTests':["IS_MULTI","NoLoadTest.loss","NoLoadTest.excitingCurrent"],
                    'TransformerEndInfo.StarImpedance':["TransformerStarImpedance.x","TransformerStarImpedance.r"]}
        #handle simplification parameters
        if self.remove_BIS:
            targets.append("BasicIntervalSchedule")
        else:
            pattern['EnergyConsumer'].append("EnergyConsumer.LoadProfile")
            targets = targets[1:]
        #execute simplification
        ll_simp = ll("ll_simplifier",targets,pattern,unit_pattern,auto_tl=False)
        self.data = ll_simp(self.data)

    def _cleanup(self):
        'ensures that empty objects are removed'
        self.data = self._prune_empty(self.data)

    def _prune_empty(self,raven):
        'recursively eliminates empty objects '
        #base case: current item is non-dictionary [No-op]
        #working case: current item is a dictionary, must be parsed 
        if isinstance(raven,dict):
            for key, val in list(raven.items()):
                #recursive step
                if isinstance(val,dict):
                    self._prune_empty(val)
                    if len(val.keys()) == 0:
                        del raven[key]
                elif isinstance(val,list):
                    for item in val:
                        if isinstance(item,dict):
                            self._prune_empty(item)
                    if len(val) == 0:
                        del raven[key]
                #targeted removal [DFS must happen before removal to handle nested empties]
                if val == None:
                    del raven[key]
        return raven

    def restore_ravens(self):
        'method to re-convert to ravens from the base XML'
        super().__init__( #re-init the parent ImportRavens object to recreate data from raw xml
            network_profile=self.network_profile,
            schema_template=self.schema_template,
            cim_namespace=self.cim_namespace,
            schema=self.schema
        )
        self.status = 0 #data is un-simplified
    
    def restore_crows(self):
        'method to re-convert to crows from the base XML'
        #Component Simplification
        if self.simplify_AC:
            self._convert_all_to_puz() #wire info simplification
        if self.simplify_tank:
            self._convert_all_to_std_trans() #transformer simplification

        #Top Level Simplification
        self._remove_superfluous_objects() #Does work of TL Simplification

        #Lower Level Simplification
        self._simplify_lower_level_members()
        
        self._cleanup() 
        self.status = 1 #data is simplified

    def is_simplified(self):
        return self.status


if __name__ == "__main__":
    from pathlib import Path
    import sys, os
    MGR_ROOT = str(Path(__file__).resolve().parents[2])

    # Creation of MG-RAVENS File from xml 
    d = RavensImport(MGR_ROOT+"/examples/IEEE13_Assets.xml")

    #Creation of Simplified MG-RAVENS File from xml
    d2 = CrowsImport(MGR_ROOT+"/examples/IEEE13_Assets.xml")
    assert(d2.is_simplified())
    d2.restore_ravens()
    assert(not d2.is_simplified())