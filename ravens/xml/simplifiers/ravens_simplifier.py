from .wire2PL import wire2PL as w2pl
from .tank2transformer import tank2transformer as t2t
from .ll_simp import ll_simp as ll


class simplifier:
    def __init__(self,remove_BIS = False, simplify_AC = False,simplify_tank=False,tank_merge=False,schema_mode=False,graph_gen = False, top_level_simp = True):
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
        self.__name__ = "Min-Ravens Simplifier"
        if remove_BIS:
            targets.append("BasicIntervalSchedule")
            self.__name__ += "_NO_BIS"
        else:
            pattern['EnergyConsumer'].append("EnergyConsumer.LoadProfile")
        if schema_mode == True:
            if simplify_AC == True:
                targets.append("WireInfo")
                del pattern["WireInfo"]
                targets.append("WireSpacingInfo")
                targets.append("ACLineSegmentPhase.WireInfo")
                self.__name__ += "_Simplified_ACLines"
            if simplify_tank == True:
                targets.append("PowerTransformerInfo.TransformerTankInfos")
                targets.append("PowerTransformer.TransformerTank")
                del unit_pattern["PowerTransformer.TransformerTank"]
                del unit_pattern["TransformerTankInfo.TransformerEndInfos"]
                targets.append("EnergisedEndNoLoadTests")
                targets.append("EnergisedEndShortCircuitTests")
            simplify_AC = False
            simplify_tank = False
            tank_merge = False
        if graph_gen:
            for object, members in pattern.items():
                members.append("Ravens.cimObjectType")
                members.append("IdentifiedObject.mRID")
                members.append("IdentifiedObject.name")
            for object, members in unit_pattern.items():
                members.append("Ravens.cimObjectType")
                members.append("IdentifiedObject.mRID")
                members.append("IdentifiedObject.name")
            targets = targets[1:]
        self.ll_simp = ll("internal_ll_simplifier",targets,pattern,unit_pattern,auto_tl=top_level_simp)
        if simplify_AC:
            self.__name__ += "_Simplified_ACLines"
        if simplify_tank:
            self.__name__ += "_Simplified_Tanks"
        if tank_merge:
            self.__name__ += "_Merged"
            if not simplify_tank:
                raise AssertionError("If using transformer tank merging the user must also use tank simplification")

        self.simplify_AC = simplify_AC
        self.simplify_tank = simplify_tank
        self.tank_merge = tank_merge

    def __call__(self,in_fn,out_fn):
        """
        Input: file name of a standard RAVENS.json file
        Output: file name for a simplified RAVENS version of the original dss file.
        """
        if self.simplify_AC and not self.simplify_tank:
            self.ll_simp(in_fn,"tmp/pre_wire_info.json")
            w2pl("tmp/pre_wire_info.json",out_fn)
        elif not self.simplify_AC and self.simplify_tank:
            self.ll_simp(in_fn,"tmp/pre_trans.json")
            t2t("tmp/pre_trans.json",out_fn,self.tank_merge)
        elif self.simplify_AC and self.simplify_tank:
            self.ll_simp(in_fn,"tmp/pre_trans.json")
            t2t("tmp/pre_trans.json","tmp/pre_wire_info.json",self.tank_merge)
            w2pl("tmp/pre_wire_info.json",out_fn)
        else:
            self.ll_simp(in_fn,out_fn)
