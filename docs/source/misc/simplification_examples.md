# Simplification Examples (DRAFT)

This **draft** document **proposes** various examples of simplifying power system component representations in JSON format. The simplifications maintain essential operational characteristics, in particular for Optimal Power Flow (OPF) while reducing data size and complexity.

## AC Power Lines

### Per Length Line Implementation

**Original:**

```json
"645646": {
    "Ravens.cimObjectType": "ACLineSegment",
    "IdentifiedObject.mRID": "9156104a-c10e-4156-82f3-e958006318c6",
    "IdentifiedObject.name": "645646",
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
    "Conductor.length": 0.0568,
    "ACLineSegment.PerLengthImpedance": "PerLengthPhaseImpedance::'645646_PUZ'",
    "ACLineSegment.ACLineSegmentPhase": [
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.mRID": "4968badc-25c7-40af-a102-8b4c6fdb79ae",
        "IdentifiedObject.name": "645646_C",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.C",
        "ACLineSegmentPhase.sequenceNumber": 1
    },
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.mRID": "03f54dfe-c8b3-44b2-8c6f-b0898da12f75",
        "IdentifiedObject.name": "645646_B",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.B",
        "ACLineSegmentPhase.sequenceNumber": 2
    }
    ],
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "72081d5a-e5c3-4319-8fb8-bac42aa05b2d",
        "IdentifiedObject.name": "645646_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.BC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'645'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_230.0_600.0'"
    },
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "73402642-7323-417c-be3f-c0b244ec1cd0",
        "IdentifiedObject.name": "645646_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.BC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'646'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_230.0_600.0'"
    }
    ]
},
"645646_PUZ": {
    "Ravens.cimObjectType": "PerLengthPhaseImpedance",
    "IdentifiedObject.mRID": "fefd65a4-ae87-4dcc-a701-f4f203c20d46",
    "IdentifiedObject.name": "645646_PUZ",
    "PerLengthPhaseImpedance.conductorCount": 2,
    "PerLengthPhaseImpedance.PhaseImpedanceData": [
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 2,
        "PhaseImpedanceData.column": 1,
        "PhaseImpedanceData.r": 0.2066,
        "PhaseImpedanceData.x": 0.4591,
        "PhaseImpedanceData.b": -2.2619467105846504e-07
    },
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 1,
        "PhaseImpedanceData.column": 1,
        "PhaseImpedanceData.r": 1.3238,
        "PhaseImpedanceData.x": 1.3569,
        "PhaseImpedanceData.b": 1.0555751316061704e-06
    },
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 2,
        "PhaseImpedanceData.column": 2,
        "PhaseImpedanceData.r": 1.3294,
        "PhaseImpedanceData.x": 1.3471,
        "PhaseImpedanceData.b": 1.0555751316061704e-06
    }
    ]
}
```

Lines Used: 77

**Simplified:**

```json
"645646": {
    "IdentifiedObject.name": "645646",
    "Equipment.inService": true,
    "Conductor.length": 0.0568,
    "ACLineSegment.PerLengthImpedance": "PerLengthPhaseImpedance::'645646_PUZ'",
    "ACLineSegment.ACLineSegmentPhase": [
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.name": "645646_C",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.C",
        "ACLineSegmentPhase.sequenceNumber": 1
    },
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.name": "645646_B",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.B",
        "ACLineSegmentPhase.sequenceNumber": 2
    }
    ],
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "645646_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.BC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'645'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_230.0_600.0'"
    },
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "645646_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.BC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'646'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_230.0_600.0'"
    }
    ]
}
"645646_PUZ": {
    "Ravens.cimObjectType": "PerLengthPhaseImpedance",
    "IdentifiedObject.name": "645646_PUZ",
    "PerLengthPhaseImpedance.conductorCount": 2,
    "PerLengthPhaseImpedance.PhaseImpedanceData": [
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 1,
        "PhaseImpedanceData.column": 1,
        "PhaseImpedanceData.r": 1.3238,
        "PhaseImpedanceData.x": 1.3569,
        "PhaseImpedanceData.b": 1.0555751316061704e-06
    },
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 2,
        "PhaseImpedanceData.column": 1,
        "PhaseImpedanceData.r": 0.2066,
        "PhaseImpedanceData.x": 0.4591,
        "PhaseImpedanceData.b": -2.2619467105846504e-07
    },
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 2,
        "PhaseImpedanceData.column": 2,
        "PhaseImpedanceData.r": 1.3294,
        "PhaseImpedanceData.x": 1.3471,
        "PhaseImpedanceData.b": 1.0555751316061704e-06
    }
    ]
}
```

Lines Used: 69

**Key Changes:**

- Removed UUID identifiers (mRID)
- Removed object type declarations where inferrable from context
- Preserved phase information, connectivity, and electrical parameters
- Maintained terminal connectivity information
- Retained impedance data essential for power flow calculations

**Benefits:** Reduced from 77 to 69 lines (10% reduction) while preserving all information needed for power flow analysis.

### Wire Info Implementation

**Original:**

```json
"684652": {
    "Ravens.cimObjectType": "ACLineSegment",
    "IdentifiedObject.mRID": "107d49e7-17ff-494c-9c5a-741c8b3f1128",
    "IdentifiedObject.name": "684652",
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
    "Conductor.length": 243.84,
    "ACLineSegment.WireSpacingInfo": "WireSpacingInfo::'607'",
    "PowerSystemResource.AssetDatasheet": "WireSpacingInfo::'607'",
    "ACLineSegment.ACLineSegmentPhase": [
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.mRID": "8f9544d4-7b42-48c4-8faa-2c86d8d65c81",
        "IdentifiedObject.name": "684652_A",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.A",
        "ACLineSegmentPhase.sequenceNumber": 1,
        "PowerSystemResource.AssetDatasheet": "TapeShieldCableInfo::'d5fd4d3d-f1ea-4b45-9c89-d24fbe7f6fe7'"
    }
    ],
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "851d6534-41dd-4c3f-9096-3e032c23a638",
        "IdentifiedObject.name": "684652_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.A",
        "Terminal.ConnectivityNode": "ConnectivityNode::'684'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_165.0_247.5'"
    },
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "41e9b990-c67d-431b-899a-4091caafaed3",
        "IdentifiedObject.name": "684652_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.A",
        "Terminal.ConnectivityNode": "ConnectivityNode::'652'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_165.0_247.5'"
    }
    ]
}
"607": {
        "Ravens.cimObjectType": "WireSpacingInfo",
        "IdentifiedObject.mRID": "d47ae2c5-c6bf-4348-a3e4-c8e4e6b07a82",
        "IdentifiedObject.name": "607",
        "WireSpacingInfo.usage": "WireUsageKind.distribution",
        "WireSpacingInfo.phaseWireCount": 1,
        "WireSpacingInfo.phaseWireSpacing": 0.0,
        "WireSpacingInfo.isCable": false,
        "WireSpacingInfo.WirePositions": [
          {
            "Ravens.cimObjectType": "WirePosition",
            "IdentifiedObject.mRID": "eb67fbb8-88d9-495d-aa44-06d8c1e6a470",
            "IdentifiedObject.name": "WP_607_1",
            "WirePosition.sequenceNumber": 1,
            "WirePosition.xCoord": 0.0,
            "WirePosition.yCoord": -1.2192
          },
          {
            "Ravens.cimObjectType": "WirePosition",
            "IdentifiedObject.mRID": "83e712d3-9755-49bc-9755-697d7f7839f8",
            "IdentifiedObject.name": "WP_607_2",
            "WirePosition.sequenceNumber": 2,
            "WirePosition.xCoord": 0.0762,
            "WirePosition.yCoord": -1.2192
          }
        ]
      }
```

Lines Used: 67

**Simplified:**

```json
"684652": {
    "IdentifiedObject.name": "684652",
    "Equipment.inService": true,
    "Conductor.length": 243.84,
    "ACLineSegment.ACLineSegmentPhase": [
    {
        "Ravens.cimObjectType": "ACLineSegmentPhase",
        "IdentifiedObject.name": "684652_A",
        "ACLineSegmentPhase.phase": "SinglePhaseKind.A",
        "ACLineSegmentPhase.sequenceNumber": 1
    }
    ],
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "684652_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.A",
        "Terminal.ConnectivityNode": "ConnectivityNode::'684'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_165.0_247.5'"
    },
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "684652_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.A",
        "Terminal.ConnectivityNode": "ConnectivityNode::'652'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_165.0_247.5'"
    }
    ],
    "ACLineSegment.PerLengthImpedance": "PerLengthPhaseImpedance::'simplified_684652'"
},
"simplified_684652": {
    "Ravens.cimObjectType": "PerLengthPhaseImpedance",
    "IdentifiedObject.name": "simplified_684652",
    "PerLengthPhaseImpedance.conductorCount": 1,
    "PerLengthPhaseImpedance.PhaseImpedanceData": [
    {
        "Ravens.cimObjectType": "PhaseImpedanceData",
        "PhaseImpedanceData.row": 1,
        "PhaseImpedanceData.column": 1,
        "PhaseImpedanceData.r": 0.0008672738947786586,
        "PhaseImpedanceData.x": 0.0008444951227417714,
        "PhaseImpedanceData.g": 0.0,
        "PhaseImpedanceData.b": 7.157577825587879
    }
    ]
}
```

Lines Used: 48

**Key Changes:**

- Replaced complex wire spacing information with equivalent impedance data
- Created a simplified impedance model that captures the electrical characteristics
- Removed detailed physical wire positioning information
- Consolidated multiple related objects into a simpler representation
- Maintained terminal connectivity and phase information

**Benefits:** Reduced from 67 to 48 lines (28% reduction) while maintaining electrical equivalence.

## Battery Unit

### Standard Battery Implementation

**Original:**

```json
"s1": {
    "Ravens.cimObjectType": "PowerElectronicsConnection",
    "IdentifiedObject.mRID": "619bff40-d23e-4422-8aa6-9e06c94ca055",
    "IdentifiedObject.name": "s1",
    "PowerElectronicsConnection.maxIFault": 1.1111111111111112,
    "PowerElectronicsConnection.p": -0.0,
    "PowerElectronicsConnection.q": -0.0,
    "PowerElectronicsConnection.ratedS": 60000.0,
    "PowerElectronicsConnection.ratedU": 400.0,
    "PowerElectronicsConnection.maxQ": 25000.0,
    "PowerElectronicsConnection.minQ": -25000.0,
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_0.4'",
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "9c7322ed-2a5c-4add-944e-d371fc080ac1",
        "IdentifiedObject.name": "s1_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'loadbus'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimV_360.00000000000006-440.00000000000006'"
        }
    ],
    "PowerElectronicsConnection.PowerElectronicsUnit": {
        "Ravens.cimObjectType": "BatteryUnit",
        "IdentifiedObject.mRID": "f9e87072-5642-4a89-8f14-8138a9a72fbd",
        "IdentifiedObject.name": "s1_Cells",
        "PowerElectronicsUnit.minP": -48000.0,
        "PowerElectronicsUnit.maxP": 36000.0,
        "BatteryUnit.storedE": 6000.0,
        "BatteryUnit.ratedE": 60000.0,
        "BatteryUnit.BatteryUnitEfficiency": {
        "Ravens.cimObjectType": "BatteryUnitEfficiency",
        "BatteryUnitEfficiency.reserveEnergy": 20.0,
        "BatteryUnitEfficiency.limitEnergy": 100.0,
        "BatteryUnitEfficiency.efficiencyDischarge": 98.0,
        "BatteryUnitEfficiency.efficiencyCharge": 95.0
        }
    }
}
```

Lines Used: 41

**Simplified:**

```json
"s1": {
    "IdentifiedObject.name": "s1",
    "PowerElectronicsConnection.p": -0.0,
    "PowerElectronicsConnection.q": -0.0,
    "PowerElectronicsConnection.ratedS": 60000.0,
    "PowerElectronicsConnection.ratedU": 400.0,
    "PowerElectronicsConnection.maxQ": 25000.0,
    "PowerElectronicsConnection.minQ": -25000.0,
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_0.4'",
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "s1_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'loadbus'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimV_360.00000000000006-440.00000000000006'"
        }
    ],
    "PowerElectronicsConnection.PowerElectronicsUnit": {
        "Ravens.cimObjectType": "BatteryUnit",
        "IdentifiedObject.name": "s1_Cells",
        "PowerElectronicsUnit.minP": -48000.0,
        "PowerElectronicsUnit.maxP": 36000.0,
        "BatteryUnit.storedE": 6000.0,
        "BatteryUnit.ratedE": 60000.0,
        "BatteryUnit.BatteryUnitEfficiency": {
        "Ravens.cimObjectType": "BatteryUnitEfficiency",
        "BatteryUnitEfficiency.reserveEnergy": 20.0,
        "BatteryUnitEfficiency.limitEnergy": 100.0,
        "BatteryUnitEfficiency.efficiencyDischarge": 98.0,
        "BatteryUnitEfficiency.efficiencyCharge": 95.0
        }
    }
}
```

Lines Used: 36

**Key Changes:**

- Removed UUID identifiers (mRID)
- Preserved all operational parameters (power ratings, energy capacity, efficiency)
- Maintained terminal connections and voltage references
- Kept all battery-specific parameters needed for simulation

**Benefits:** Reduced from 41 to 36 lines (12% reduction) while preserving all functional characteristics.

## Energy Source

### Standard Energy Source Implementation

**Original:**

```json
"source": {
    "Ravens.cimObjectType": "EnergySource",
    "IdentifiedObject.mRID": "23f05a43-a11c-4619-a0c8-630f40da179f",
    "IdentifiedObject.name": "source",
    "EnergySource.nominalVoltage": 115000.0,
    "EnergySource.voltageMagnitude": 115000.0,
    "EnergySource.voltageAngle": 0.5235987755982988,
    "EnergySource.r": 0.16037668205527517,
    "EnergySource.x": 0.6415067282211007,
    "EnergySource.r0": 0.17960358301233564,
    "EnergySource.x0": 0.5388107490370069,
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_115.00000000000001'",
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "46abef4c-e853-4cf1-a5f2-548036f47cd9",
        "IdentifiedObject.name": "source_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'"
    }
    ]
}
```

Lines Used: 24

**Simplified:**

```json
"source": {
    "IdentifiedObject.name": "source",
    "EnergySource.nominalVoltage": 115000.0,
    "EnergySource.voltageMagnitude": 115000.0,
    "EnergySource.voltageAngle": 0.5235987755982988,
    "EnergySource.r": 0.16037668205527517,
    "EnergySource.x": 0.6415067282211007,
    "EnergySource.r0": 0.17960358301233564,
    "EnergySource.x0": 0.5388107490370069,
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_115.00000000000001'",
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "source_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'"
    }
    ]
}
```

Lines Used: 21

**Key Changes:**

- Removed UUID identifiers (mRID)
- Preserved all electrical parameters (voltage, impedance values)
- Maintained terminal connections
- Kept all parameters needed for power flow analysis

**Benefits:** Reduced from 24 to 21 lines (12.5% reduction) while maintaining complete electrical representation.

## Energy Consumer

### Standard Energy Consumer Implementation

**Original:**

```json
"670c": {
    "Ravens.cimObjectType": "EnergyConsumer",
    "IdentifiedObject.mRID": "cdc9911e-3426-482e-8970-9f9a233c8009",
    "IdentifiedObject.name": "670c",
    "EnergyConsumer.p": 117000.0,
    "EnergyConsumer.q": 68000.0,
    "EnergyConsumer.customerCount": 1,
    "EnergyConsumer.grounded": false,
    "Equipment.inService": true,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
    "EnergyConsumer.phaseConnection": "PhaseShuntConnectionKind.Y",
    "EnergyConsumer.LoadResponse": "LoadResponseCharacteristic::'Constant kVA'",
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "63762d28-fc9c-463a-9fd3-1d9f6b9b1e20",
        "IdentifiedObject.name": "670c_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.C",
        "Terminal.ConnectivityNode": "ConnectivityNode::'670'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimV_3952.0-4368.0'"
    }
    ],
    "EnergyConsumer.EnergyConsumerPhase": [
    {
        "Ravens.cimObjectType": "EnergyConsumerPhase",
        "IdentifiedObject.mRID": "729b7d47-6a37-4225-8cbe-5eb32280c720",
        "IdentifiedObject.name": "670c_C",
        "EnergyConsumerPhase.p": 117000.0,
        "EnergyConsumerPhase.q": 68000.0,
        "EnergyConsumerPhase.phase": "SinglePhaseKind.C"
    }
    ]
},
```

Lines Used: 34

**Simplified:**

```json
"670c": {
    "IdentifiedObject.name": "670c",
    "EnergyConsumer.p": 117000.0,
    "EnergyConsumer.q": 68000.0,
    "EnergyConsumer.grounded": false,
    "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
    "EnergyConsumer.phaseConnection": "PhaseShuntConnectionKind.Y",
    "EnergyConsumer.LoadResponse": "LoadResponseCharacteristic::'Constant kVA'",
    "EnergyConsumer.EnergyConsumerPhase": [
    {
        "Ravens.cimObjectType": "EnergyConsumerPhase",
        "IdentifiedObject.name": "670c_C",
        "EnergyConsumerPhase.p": 117000.0,
        "EnergyConsumerPhase.q": 68000.0,
        "EnergyConsumerPhase.phase": "SinglePhaseKind.C"
    }
    ],
    "ConductingEquipment.Terminals": [
    {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "670c_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.C",
        "Terminal.ConnectivityNode": "ConnectivityNode::'670'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimV_3952.0-4368.0'"
    }
    ]
},
```

Lines Used: 28

**Key Changes:**

- Removed UUID identifiers (mRID)
- Preserved power consumption values and connection information
- Maintained phase data and terminal connections
- Kept load response characteristics

**Benefits:** Reduced from 34 to 28 lines (17.6% reduction) while preserving load modeling accuracy.

## Power Transformers

### Standard Transformer Implementation

**Original:**

```json
"sub": {
    "Ravens.cimObjectType": "PowerTransformer",
    "IdentifiedObject.mRID": "cd868f80-4113-4d22-8d39-fb156f9f7d7b",
    "IdentifiedObject.name": "sub",
    "PowerTransformer.vectorGroup": "Yn1yn1",
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "7194ac04-f873-43b8-b5a5-5f61d26d3dbe",
        "IdentifiedObject.name": "sub_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_27.61240417863427_37.65327842541037'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "1da98dbc-3b21-4ff6-b4aa-1027e9e8cace",
        "IdentifiedObject.name": "sub_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'"
        }
    ],
    "PowerTransformer.PowerTransformerEnd": [
        {
        "Ravens.cimObjectType": "PowerTransformerEnd",
        "IdentifiedObject.mRID": "f9d4dd45-4301-407a-bb16-3f82d927169a",
        "IdentifiedObject.name": "sub_End_1",
        "PowerTransformerEnd.ratedS": 5000000.0,
        "PowerTransformerEnd.ratedU": 115000.0,
        "PowerTransformerEnd.r": 0.013225,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y",
        "PowerTransformerEnd.phaseAngleClock": 0,
        "TransformerEnd.grounded": false,
        "TransformerEnd.endNumber": 1,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_115.00000000000001'",
        "TransformerEnd.MeshImpedance": {
            "Ravens.cimObjectType": "TransformerMeshImpedance",
            "IdentifiedObject.mRID": "d3e36037-a612-457c-9331-7f18f5639ec1",
            "IdentifiedObject.name": "sub_Zsc_1",
            "TransformerMeshImpedance.r": 0.02645,
            "TransformerMeshImpedance.r0": 0.02645,
            "TransformerMeshImpedance.x": 21.16,
            "TransformerMeshImpedance.x0": 21.16
        },
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "IdentifiedObject.mRID": "1a977a03-5c8e-49ac-be8b-df7f3ab3df15",
            "IdentifiedObject.name": "sub_Yc",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.g0": 0.0,
            "TransformerCoreAdmittance.b": -0.0,
            "TransformerCoreAdmittance.b0": -0.0
        }
        },
        {
        "Ravens.cimObjectType": "PowerTransformerEnd",
        "IdentifiedObject.mRID": "78e261d2-b11c-496a-b583-1fc48211baac",
        "IdentifiedObject.name": "sub_End_2",
        "PowerTransformerEnd.ratedS": 5000000.0,
        "PowerTransformerEnd.ratedU": 4160.0,
        "PowerTransformerEnd.r": 1.7305600000000002e-05,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y",
        "PowerTransformerEnd.phaseAngleClock": 0,
        "TransformerEnd.grounded": false,
        "TransformerEnd.endNumber": 2,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.MeshImpedance": {
            "Ravens.cimObjectType": "TransformerMeshImpedance",
            "IdentifiedObject.mRID": "d3e36037-a612-457c-9331-7f18f5639ec1",
            "IdentifiedObject.name": "sub_Zsc_1",
            "TransformerMeshImpedance.r": 0.02645,
            "TransformerMeshImpedance.r0": 0.02645,
            "TransformerMeshImpedance.x": 21.16,
            "TransformerMeshImpedance.x0": 21.16
        }
        }
    ]
},
```

Lines Used: 80

**Simplified:**

```json
"sub": {
    "IdentifiedObject.name": "sub",
    "PowerTransformer.PowerTransformerEnd": [
        {
        "PowerTransformerEnd.ratedS": 5000000.0,
        "PowerTransformerEnd.ratedU": 115000.0,
        "PowerTransformerEnd.r": 0.013225,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y",
        "TransformerEnd.endNumber": 1,
        "TransformerEnd.MeshImpedance": {
            "Ravens.cimObjectType": "TransformerMeshImpedance",
            "IdentifiedObject.name": "sub_Zsc_1",
            "TransformerMeshImpedance.r": 0.02645,
            "TransformerMeshImpedance.r0": 0.02645,
            "TransformerMeshImpedance.x": 21.16,
            "TransformerMeshImpedance.x0": 21.16
        },
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "IdentifiedObject.name": "sub_Yc",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.g0": 0.0,
            "TransformerCoreAdmittance.b": -0.0,
            "TransformerCoreAdmittance.b0": -0.0
        }
        },
        {
        "PowerTransformerEnd.ratedS": 5000000.0,
        "PowerTransformerEnd.ratedU": 4160.0,
        "PowerTransformerEnd.r": 1.7305600000000002e-05,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y",
        "TransformerEnd.endNumber": 2,
        "TransformerEnd.MeshImpedance": {
            "Ravens.cimObjectType": "TransformerMeshImpedance",
            "IdentifiedObject.name": "sub_Zsc_1",
            "TransformerMeshImpedance.r": 0.02645,
            "TransformerMeshImpedance.r0": 0.02645,
            "TransformerMeshImpedance.x": 21.16,
            "TransformerMeshImpedance.x0": 21.16
        }
        }
    ],
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "sub_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_27.61240417863427_37.65327842541037'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "sub_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.ABC",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'"
        }
    ]
},
```

Lines Used: 60

**Key Changes:**

- Removed UUID identifiers (mRID)
- Preserved all winding parameters and impedance data
- Maintained terminal connections
- Kept core admittance information

**Benefits:** Reduced from 80 to 60 lines (25% reduction) while maintaining transformer electrical model accuracy.

### Tank-Based Implementation

**Original:**

```json
"Reg": {
    "Ravens.cimObjectType": "PowerTransformer",
    "IdentifiedObject.mRID": "45a183d8-f98f-4013-b54f-9f85ba50c7e1",
    "IdentifiedObject.name": "Reg",
    "PowerTransformer.vectorGroup": "Yn1yn1",
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "f151a53f-968c-4b3f-9b5f-59b4d35c026f",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "47914c0a-7440-4712-9951-3c5716d1f1f7",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ],
    "PowerTransformer.TransformerTank": [
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "beb4da7c-0ab3-4f34-bed5-55bd36bdb112",
        "IdentifiedObject.name": "reg2",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "40c9c8ac-c263-4756-8669-0ef3517bdc64",
            "IdentifiedObject.name": "reg2_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.BN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "8ac05e6a-2707-4732-8e54-4a9c49221bd9",
            "IdentifiedObject.name": "reg2_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.BN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        },
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "3a23cbf7-b8e5-43c5-9355-a05375ed7391",
        "IdentifiedObject.name": "reg1",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "39987fd3-9af5-45ad-88ba-dcfda35d1faa",
            "IdentifiedObject.name": "reg1_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.AN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "23166e14-de9f-4f35-aa0b-5b31adf7ed66",
            "IdentifiedObject.name": "reg1_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.AN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        },
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "b05e03ab-20a4-4f06-acbb-f25ff97ebe41",
        "IdentifiedObject.name": "reg3",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "3563b2e5-554f-47a7-8c53-aeb2594c8640",
            "IdentifiedObject.name": "reg3_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.CN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "070b80dc-53a6-4fbe-be72-f350fb96b9e1",
            "IdentifiedObject.name": "reg3_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.CN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        }
    ]
},
"regleg": {
    "PowerTransformerInfo.TransformerTankInfos": {
        "regleg": {
        "Ravens.cimObjectType": "TransformerTankInfo",
        "IdentifiedObject.mRID": "b5670e17-3642-4020-9f7a-23935a9bf631",
        "IdentifiedObject.name": "regleg",
        "TransformerTankInfo.TransformerEndInfos": [
            {
            "Ravens.cimObjectType": "TransformerEndInfo",
            "IdentifiedObject.mRID": "89768b93-fefb-426a-a5fb-9e7cd16fcbd4",
            "IdentifiedObject.name": "regleg_1",
            "TransformerEndInfo.endNumber": 1,
            "TransformerEndInfo.connectionKind": "WindingConnection.I",
            "TransformerEndInfo.phaseAngleClock": 0,
            "TransformerEndInfo.ratedU": 2400.0,
            "TransformerEndInfo.ratedS": 1666000.0,
            "TransformerEndInfo.shortTermS": 1832599.9999999998,
            "TransformerEndInfo.emergencyS": 2499000.0,
            "TransformerEndInfo.r": 0.00017286914765906363,
            "TransformerEndInfo.insulationU": 0.0,
            "TransformerEndInfo.EnergisedEndNoLoadTests": [
                {
                "Ravens.cimObjectType": "NoLoadTest",
                "IdentifiedObject.mRID": "4383edbe-ca54-42f9-a73e-61ba10412643",
                "IdentifiedObject.name": "regleg_1_noload",
                "NoLoadTest.energisedEndVoltage": 2400.0,
                "NoLoadTest.excitingCurrent": 0.0,
                "NoLoadTest.excitingCurrentZero": 0.0,
                "NoLoadTest.loss": 0.0,
                "NoLoadTest.lossZero": 0.0,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ],
            "TransformerEndInfo.EnergisedEndShortCircuitTests": [
                {
                "Ravens.cimObjectType": "ShortCircuitTest",
                "IdentifiedObject.mRID": "0dd03f25-8ce7-4267-8f9e-8bed9b261eb4",
                "IdentifiedObject.name": "regleg_1_shortcircuit",
                "ShortCircuitTest.energisedEndStep": 1,
                "ShortCircuitTest.groundedEndStep": 1,
                "ShortCircuitTest.leakageImpedance": 0.04889477862706499,
                "ShortCircuitTest.leakageImpedanceZero": 0.04889477862706499,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ]
            },
            {
            "Ravens.cimObjectType": "TransformerEndInfo",
            "IdentifiedObject.mRID": "4a796171-0ed5-4d28-9a4a-27125bea7aa7",
            "IdentifiedObject.name": "regleg_2",
            "TransformerEndInfo.endNumber": 2,
            "TransformerEndInfo.connectionKind": "WindingConnection.I",
            "TransformerEndInfo.phaseAngleClock": 0,
            "TransformerEndInfo.ratedU": 2400.0,
            "TransformerEndInfo.ratedS": 1666000.0,
            "TransformerEndInfo.shortTermS": 1832599.9999999998,
            "TransformerEndInfo.emergencyS": 2499000.0,
            "TransformerEndInfo.r": 0.00017286914765906363,
            "TransformerEndInfo.insulationU": 0.0,
            "TransformerEndInfo.EnergisedEndShortCircuitTests": [
                {
                "Ravens.cimObjectType": "ShortCircuitTest",
                "IdentifiedObject.mRID": "0dd03f25-8ce7-4267-8f9e-8bed9b261eb4",
                "IdentifiedObject.name": "regleg_1_shortcircuit",
                "ShortCircuitTest.energisedEndStep": 1,
                "ShortCircuitTest.groundedEndStep": 1,
                "ShortCircuitTest.leakageImpedance": 0.04889477862706499,
                "ShortCircuitTest.leakageImpedanceZero": 0.04889477862706499,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ]
            }
        ]
        }
    }
},
```

Lines Used: 196

**Simplified:**

```json
"Simplified_reg3_End_1": {
    "IdentifiedObject.name": "Simplified_reg3_End_1",
    "Ravens.cimObjectType": "PowerTransformer",
    "PowerTransformer.PowerTransformerEnd": [
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg3_End_1",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 1,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.b": 0.0
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        },
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg3_End_2",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 2,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        }
    ],
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.CN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.CN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ]
},
"Simplified_reg2_End_1": {
    "IdentifiedObject.name": "Simplified_reg2_End_1",
    "Ravens.cimObjectType": "PowerTransformer",
    "PowerTransformer.PowerTransformerEnd": [
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg2_End_1",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 1,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.b": 0.0
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        },
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg2_End_2",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 2,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        }
    ],
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.BN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.BN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ]
},
"Simplified_reg1_End_1": {
    "IdentifiedObject.name": "Simplified_reg1_End_1",
    "Ravens.cimObjectType": "PowerTransformer",
    "PowerTransformer.PowerTransformerEnd": [
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg1_End_1",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 1,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.b": 0.0
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        },
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "reg1_End_2",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 2,
        "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "PowerTransformerEnd.ratedS": 1666000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
        }
    ],
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.AN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.AN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ]
},
```

Lines Used: 174

**Key Changes:**

- Converted tank-based model to equivalent star impedance representation
- Created individual transformer objects for each phase
- Preserved electrical characteristics and ratings
- Maintained terminal connections

**Benefits:** Reduced from 196 to 174 lines (11% reduction) while preserving electrical equivalence.

### Tank-Based with Advanced Simplification

**Original:**

```json
"Reg": {
    "Ravens.cimObjectType": "PowerTransformer",
    "IdentifiedObject.mRID": "45a183d8-f98f-4013-b54f-9f85ba50c7e1",
    "IdentifiedObject.name": "Reg",
    "PowerTransformer.vectorGroup": "Yn1yn1",
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "f151a53f-968c-4b3f-9b5f-59b4d35c026f",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.mRID": "47914c0a-7440-4712-9951-3c5716d1f1f7",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ],
    "PowerTransformer.TransformerTank": [
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "beb4da7c-0ab3-4f34-bed5-55bd36bdb112",
        "IdentifiedObject.name": "reg2",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "40c9c8ac-c263-4756-8669-0ef3517bdc64",
            "IdentifiedObject.name": "reg2_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.BN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "8ac05e6a-2707-4732-8e54-4a9c49221bd9",
            "IdentifiedObject.name": "reg2_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.BN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        },
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "3a23cbf7-b8e5-43c5-9355-a05375ed7391",
        "IdentifiedObject.name": "reg1",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "39987fd3-9af5-45ad-88ba-dcfda35d1faa",
            "IdentifiedObject.name": "reg1_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.AN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "23166e14-de9f-4f35-aa0b-5b31adf7ed66",
            "IdentifiedObject.name": "reg1_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.AN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        },
        {
        "Ravens.cimObjectType": "TransformerTank",
        "IdentifiedObject.mRID": "b05e03ab-20a4-4f06-acbb-f25ff97ebe41",
        "IdentifiedObject.name": "reg3",
        "PowerSystemResource.AssetDatasheet": "TransformerTankInfo::'regleg'",
        "TransformerTank.TransformerTankEnd": [
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "3563b2e5-554f-47a7-8c53-aeb2594c8640",
            "IdentifiedObject.name": "reg3_End_1",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.CN",
            "TransformerEnd.endNumber": 1,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'"
            },
            {
            "Ravens.cimObjectType": "TransformerTankEnd",
            "IdentifiedObject.mRID": "070b80dc-53a6-4fbe-be72-f350fb96b9e1",
            "IdentifiedObject.name": "reg3_End_2",
            "TransformerEnd.grounded": true,
            "TransformerEnd.rground": 0.0,
            "TransformerEnd.xground": 0.0,
            "TransformerTankEnd.phases": "PhaseCode.CN",
            "TransformerEnd.endNumber": 2,
            "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
            }
        ]
        }
    ]
},
"regleg": {
    "PowerTransformerInfo.TransformerTankInfos": {
        "regleg": {
        "Ravens.cimObjectType": "TransformerTankInfo",
        "IdentifiedObject.mRID": "b5670e17-3642-4020-9f7a-23935a9bf631",
        "IdentifiedObject.name": "regleg",
        "TransformerTankInfo.TransformerEndInfos": [
            {
            "Ravens.cimObjectType": "TransformerEndInfo",
            "IdentifiedObject.mRID": "89768b93-fefb-426a-a5fb-9e7cd16fcbd4",
            "IdentifiedObject.name": "regleg_1",
            "TransformerEndInfo.endNumber": 1,
            "TransformerEndInfo.connectionKind": "WindingConnection.I",
            "TransformerEndInfo.phaseAngleClock": 0,
            "TransformerEndInfo.ratedU": 2400.0,
            "TransformerEndInfo.ratedS": 1666000.0,
            "TransformerEndInfo.shortTermS": 1832599.9999999998,
            "TransformerEndInfo.emergencyS": 2499000.0,
            "TransformerEndInfo.r": 0.00017286914765906363,
            "TransformerEndInfo.insulationU": 0.0,
            "TransformerEndInfo.EnergisedEndNoLoadTests": [
                {
                "Ravens.cimObjectType": "NoLoadTest",
                "IdentifiedObject.mRID": "4383edbe-ca54-42f9-a73e-61ba10412643",
                "IdentifiedObject.name": "regleg_1_noload",
                "NoLoadTest.energisedEndVoltage": 2400.0,
                "NoLoadTest.excitingCurrent": 0.0,
                "NoLoadTest.excitingCurrentZero": 0.0,
                "NoLoadTest.loss": 0.0,
                "NoLoadTest.lossZero": 0.0,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ],
            "TransformerEndInfo.EnergisedEndShortCircuitTests": [
                {
                "Ravens.cimObjectType": "ShortCircuitTest",
                "IdentifiedObject.mRID": "0dd03f25-8ce7-4267-8f9e-8bed9b261eb4",
                "IdentifiedObject.name": "regleg_1_shortcircuit",
                "ShortCircuitTest.energisedEndStep": 1,
                "ShortCircuitTest.groundedEndStep": 1,
                "ShortCircuitTest.leakageImpedance": 0.04889477862706499,
                "ShortCircuitTest.leakageImpedanceZero": 0.04889477862706499,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ]
            },
            {
            "Ravens.cimObjectType": "TransformerEndInfo",
            "IdentifiedObject.mRID": "4a796171-0ed5-4d28-9a4a-27125bea7aa7",
            "IdentifiedObject.name": "regleg_2",
            "TransformerEndInfo.endNumber": 2,
            "TransformerEndInfo.connectionKind": "WindingConnection.I",
            "TransformerEndInfo.phaseAngleClock": 0,
            "TransformerEndInfo.ratedU": 2400.0,
            "TransformerEndInfo.ratedS": 1666000.0,
            "TransformerEndInfo.shortTermS": 1832599.9999999998,
            "TransformerEndInfo.emergencyS": 2499000.0,
            "TransformerEndInfo.r": 0.00017286914765906363,
            "TransformerEndInfo.insulationU": 0.0,
            "TransformerEndInfo.EnergisedEndShortCircuitTests": [
                {
                "Ravens.cimObjectType": "ShortCircuitTest",
                "IdentifiedObject.mRID": "0dd03f25-8ce7-4267-8f9e-8bed9b261eb4",
                "IdentifiedObject.name": "regleg_1_shortcircuit",
                "ShortCircuitTest.energisedEndStep": 1,
                "ShortCircuitTest.groundedEndStep": 1,
                "ShortCircuitTest.leakageImpedance": 0.04889477862706499,
                "ShortCircuitTest.leakageImpedanceZero": 0.04889477862706499,
                "TransformerTest.basePower": 1666000.0,
                "TransformerTest.temperature": 50.0
                }
            ]
            }
        ]
        }
    }
},
```

Lines Used: 196

**Simplified:**

```json
"Simplified_Reg": {
    "IdentifiedObject.name": "Reg",
    "Ravens.cimObjectType": "PowerTransformer",
    "PowerTransformer.PowerTransformerEnd": [
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "Reg_1",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 1,
        "TransformerEnd.CoreAdmittance": {
            "Ravens.cimObjectType": "TransformerCoreAdmittance",
            "TransformerCoreAdmittance.g": 0.0,
            "TransformerCoreAdmittance.b": 0.0
        },
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "PowerTransformerEnd.ratedS": 4998000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Yn",
        "PowerTransformerEnd.r": 0.00017286914765906363
        },
        {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": "Reg_2",
        "TransformerEnd.grounded": true,
        "TransformerEnd.endNumber": 2,
        "TransformerEnd.StarImpedance": {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": 0.00034573829531812727,
            "TransformerStarImpedance.x": 0.00034573829531812727
        },
        "PowerTransformerEnd.ratedS": 4998000.0,
        "PowerTransformerEnd.ratedU": 2400.0,
        "PowerTransformerEnd.connectionKind": "WindingConnection.Yn",
        "PowerTransformerEnd.r": 0.00017286914765906363
        }
    ],
    "ConductingEquipment.Terminals": [
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T1",
        "ACDCTerminal.sequenceNumber": 1,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'650'",
        "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_763.5833333333334_1041.25'"
        },
        {
        "Ravens.cimObjectType": "Terminal",
        "IdentifiedObject.name": "Reg_T2",
        "ACDCTerminal.sequenceNumber": 2,
        "Terminal.phases": "PhaseCode.ABCN",
        "Terminal.ConnectivityNode": "ConnectivityNode::'rg60'"
        }
    ]
}
```

Lines Used: 58

**Key Changes:**

- Consolidated three single-phase transformers into one three-phase unit
- Combined electrical parameters appropriately (3× power rating)
- Created equivalent star impedance representation
- Maintained terminal connections with appropriate phase information

**Benefits:** Reduced from 196 to 58 lines (70% reduction) while maintaining electrical equivalence for balanced operation.
