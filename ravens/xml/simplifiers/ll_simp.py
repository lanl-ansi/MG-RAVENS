import json
from .tl_simp import tl_simp

class ll_simp:
    def __init__(self,name,ll_targets,ll_patterns,ll_unit_patterns,auto_tl=True):
        self.ll_targets = set(ll_targets) #should be a list 
        self.ll_patterns = ll_patterns #should be a (string,list) dict
        self.ll_unit_patterns = ll_unit_patterns #should be a (string,list) dict
        self.__name__ = name
        self.auto_tl = auto_tl
        self.no_names = set(["WireSpacingInfo.WirePositions","TapChanger.TapChangerRatio","TapChanger.TapChangerControl"])
        self.tl_simp = tl_simp(['Location', 'EnergyConnectionProfile','CoordinateSystem','TopologicalNode',
                                'Group','SwitchingAction','Fault','Location','DynamicsFunctionBlock','Document',
                                'ActivityRecord','EnvironmentalPhenomenon','Asset','ProposedSiteLocation','FossilFuelCosts','OutageScenario',
                                'CommunityFacility','EconomicProperty','EnergyPrices','PredictedEmissions','AlgorithmProperties','ProposedAssetOption',
                                'ProposedAsset','EstimatedCost','Application','Algorithm','Message'])
        

    def __call__(self,in_data,out_data=None):
        if out_data is None and isinstance(in_data, dict):
            if self.auto_tl:
                in_data = self.tl_simp(in_data)
            self.prune(in_data)
            return in_data

        elif isinstance(in_data, str) and isinstance(out_data, str):
            with open(in_data, 'r') as input_file, open("tmp/midpt.json",'r') as mid_file, open(out_data, 'w') as output_file:
                if self.auto_tl:
                    self.tl_simp(in_data,"tmp/midpt.json")
                else: 
                    mid_file = input_file
            
                content = mid_file.read()
                raven = json.loads(content)

                self.prune(raven)

                json.dump(raven, output_file, indent=2)
        else:
            raise ValueError("Invalid arguments. Expected either a dictionary or two filenames.")

    def prune(self,raven):
        if isinstance(raven,dict):
            for key, val in list(raven.items()):
                #targeted removal
                if key in self.ll_targets:
                    del raven[key]
                #pattern matching (P:objects:members)
                if key in self.ll_patterns.keys():#found a pattern we care about
                    pattern_set = raven[key]
                    for object in pattern_set.values(): #iterate over every object of given pattern
                        if isinstance(object,dict):
                            for key_o in list(object.keys()): #for every key/val pair in the object of given pattern
                                if key_o not in self.ll_patterns[key]:
                                    del object[key_o]
                #unit pattern matching (UP:members)
                if key in self.ll_unit_patterns.keys():#found a unit pattern we care about
                    pattern_set = raven[key]
                    if self.ll_unit_patterns[key][0] == "IS_MULTI":#multi unit pattern
                        for member_pattern_set in pattern_set:
                            if isinstance(member_pattern_set,dict):
                                for object in list(member_pattern_set.keys()): #iterate over every val in the unit pattern 
                                    if object not in self.ll_unit_patterns[key]:
                                        del member_pattern_set[object]
                    else:#single unit pattern
                        for object in pattern_set: #iterate over every val in the unit pattern 
                            if object not in self.ll_unit_patterns[key]:
                                del object
                if key in self.no_names:
                    pattern_set = raven[key]
                    if isinstance(pattern_set,dict):
                        for object in list(pattern_set.keys()): #iterate over every object of given pattern
                            if object == "IdentifiedObject.name":
                                del pattern_set[object]
                    if isinstance(pattern_set,list):
                        for object in list(pattern_set): #iterate over every object of given pattern
                            for key_o in list(object.keys()):
                                if key_o == "IdentifiedObject.name":
                                    del object[key_o]

                #recursive step
                if isinstance(val,dict):
                    self.prune(val)
                elif isinstance(val,list):
                    for item in val:
                        if isinstance(item,dict):
                            self.prune(item)
            


if __name__ == "__main__":
    #Setup Test Case
    targets = ["IdentifiedObject.mRID","IdentifiedObject.description","IdentifiedObject.aliasName","PowerSystemResource.Location",
                "BasicIntervalSchedule.startTime","EnergyConsumerSchedule.endTime","EnergyConsumerSchedule.startDate",
                "EnergyConsumerSchedule.startDay","EnergyConsumerSchedule.IrregularTimePoints",
                "PerLengthLineParameter.WireAssemblyInfo","WireAssemblyInfo", "TapChangerInfo",
                "ACDCConverter","EquivalentEquipment","Connector","EarthFaultCompensator","Clamp",
                "SeriesCompensator","Ground", "PowerSystemResource.GenericAction", "WireSegment",
                "StaticVarCompensator","ExternalNetworkInjection","FrequencyConverter",
                "PhaseTapChanger" ]



    pattern = {'RegulatingControl':["RegulatingControl.targetValue","RegulatingControl.targetDeadband"],
                'OperationalLimitType':["OperationalLimitType.direction"],
                'EnergySource':["ConductingEquipment.Terminals","ConductingEquipment.BaseVoltage","EnergySourcePhase.phase","Equipment.inService",
                                "EnergySource.connectionKind","EnergySource.nominalVoltage","EnergySource.activePower","IdentifiedObject.name",
                                "EnergySource.reactivePower","EnergySource.voltageMagnitude","EnergySource.pMin","EnergySource.pMax",
                                "EnergySource.qMin","EnergySource.qMax","EnergySource.connectionKind","EnergySource.r","EnergySource.x",
                                "EnergySource.voltageMagnitude","EnergySource.voltageAngle","EnergySource.vpairMin","EnergySource.vpairMax",
                                "EnergySource.r0","EnergySource.x0"],
                'EnergyConsumer':["ConductingEquipment.Terminals","ConductingEquipment.BaseVoltage","IdentifiedObject.name",
                                  "EnergyConsumer.LoadResponse","EnergyConsumer.EnergyConsumerPhase","EnergyConsumer.p","EnergyConsumer.q",
                                  "EnergyConsumer.LoadProfile","EnergyConsumer.grounded","EnergyConsumer.phaseConnection"],
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


    ll_test = ll_simp("test",targets,pattern,unit_pattern)
    ll_test("tmp/inspect_control.json","tmp/test.json")
