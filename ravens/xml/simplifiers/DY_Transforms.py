import copy

def delta_2_wye(delta_trans,end):
    """
    Input: MG-RAVENS Transformer in a Python dictionary defined as a 3-phase 2-end transformer with a mesh impedance on end N, and end N = (1 or 2)
    Output: MG-RAVENS Transformer in a Python dictionary defined as a 3-phase 2-end transformer with a star impedance on end N and WindingConnection.Y
    """
    #0) parse input transformer
    wye_trans = copy.deepcopy(delta_trans)
    del wye_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.MeshImpedance"]
    TMI = delta_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.MeshImpedance"]
    mesh_r = TMI["TransformerMeshImpedance.r"]
    mesh_x = TMI["TransformerMeshImpedance.x"]
    #1) calculate new impedance  
    TSI = {"Ravens.cimObjectType": "TransformerStarImpedance",
           "TransformerStarImpedance.r": mesh_r/3,
           "TransformerStarImpedance.x": mesh_x/3 
          }
    #2) define new transformer with modified windings
    wye_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.StarImpedance"] = TSI
    wye_trans["PowerTransformer.PowerTransformerEnd"][end-1]["PowerTransformerEnd.connectionKind"] = "WindingConnection.Y"
    return wye_trans

def wye_2_delta(wye_trans,end):
    """
    Input: MG-RAVENS Transformer in a Python dictionary defined as a 3-phase 2-end transformer with a star impedance on end N, and end N = (1 or 2)
    Output: MG-RAVENS Transformer in a Python dictionary defined as a 3-phase 2-end transformer with a mesh impedance on end N and WindingConnection.D
    """
    #0) parse input transformer
    delta_trans = copy.deepcopy(wye_trans)
    del delta_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.StarImpedance"]
    TSI = wye_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.StarImpedance"]
    star_r = TSI["TransformerStarImpedance.r"]
    star_x = TSI["TransformerStarImpedance.x"]
    #1) calculate new impedance  
    TMI = {"Ravens.cimObjectType": "TransformerMeshImpedance",
           "TransformerMeshImpedance.r": star_r*3,
           "TransformerMeshImpedance.x": star_x*3
          }
    #2) define new transformer with modified windings
    delta_trans["PowerTransformer.PowerTransformerEnd"][end-1]["TransformerEnd.MeshImpedance"] = TMI
    delta_trans["PowerTransformer.PowerTransformerEnd"][end-1]["PowerTransformerEnd.connectionKind"] = "WindingConnection.D"
    return delta_trans



if __name__ == "__main__":
    import json
    tol = 1e-16
    delta = wye = json.loads("""{
            "IdentifiedObject.name": "Simplified_sub",
            "Ravens.cimObjectType": "PowerTransformer",
            "PowerTransformer.PowerTransformerEnd": [
              {
                "Ravens.cimObjectType": "TransformerTankEnd",
                "IdentifiedObject.mRID": "fc0825c1-86fc-49f6-a517-398de27ccd61",
                "IdentifiedObject.name": "sub_End_1",
                "TransformerEnd.grounded": false,
                "TransformerEnd.endNumber": 1,
                "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_115.00000000000001'",
                "TransformerEnd.StarImpedance": {
                  "Ravens.cimObjectType": "TransformerStarImpedance",
                  "TransformerStarImpedance.r": 0.02645,
                  "TransformerStarImpedance.x": 0.2116
                },
                "TransformerEnd.CoreAdmittance": {
                  "Ravens.cimObjectType": "TransformerCoreAdmittance",
                  "TransformerCoreAdmittance.g": 0.0,
                  "TransformerCoreAdmittance.b": 0.0
                },
                "PowerTransformerEnd.ratedS": 5000000.0,
                "PowerTransformerEnd.ratedU": 115000.0,
                "PowerTransformerEnd.r": 0.013225,
                "PowerTransformerEnd.connectionKind": "WindingConnection.D"
              },
              {
                "Ravens.cimObjectType": "TransformerTankEnd",
                "IdentifiedObject.mRID": "79713a25-dcab-4f95-ba68-47b0d109dcf2",
                "IdentifiedObject.name": "sub_End_2",
                "TransformerEnd.grounded": true,
                "TransformerEnd.endNumber": 2,
                "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_4.16'",
                "TransformerEnd.StarImpedance": {
                  "Ravens.cimObjectType": "TransformerStarImpedance",
                  "TransformerStarImpedance.r": 3.461120000000001e-05,
                  "TransformerStarImpedance.x": 0.21324671463369566
                },
                "PowerTransformerEnd.ratedS": 5000000.0,
                "PowerTransformerEnd.ratedU": 4160.0,
                "PowerTransformerEnd.r": 1.7305600000000006e-05,
                "PowerTransformerEnd.connectionKind": "WindingConnection.Y"
              }
            ],
            "ConductingEquipment.Terminals": [
              {
                "Ravens.cimObjectType": "Terminal",
                "IdentifiedObject.mRID": "45138108-d15d-4cd0-a3f7-cd3c1281dede",
                "IdentifiedObject.name": "sub_T1",
                "ACDCTerminal.sequenceNumber": 1,
                "Terminal.phases": "PhaseCode.ABC",
                "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'",
                "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'OpLimI_27.61240417863427_37.65327842541037'"
              },
              {
                "Ravens.cimObjectType": "Terminal",
                "IdentifiedObject.mRID": "d2b7a6b1-7e66-472f-aa92-bffa2986c3ea",
                "IdentifiedObject.name": "sub_T2",
                "ACDCTerminal.sequenceNumber": 2,
                "Terminal.phases": "PhaseCode.ABCN",
                "Terminal.ConnectivityNode": "ConnectivityNode::'650'"
              }
            ]
          }""")
    mid_delta = wye_2_delta(wye,2)
    res_wye = delta_2_wye(wye_2_delta(wye,2),2)
    assert(abs(res_wye["PowerTransformer.PowerTransformerEnd"][1]["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"] - wye["PowerTransformer.PowerTransformerEnd"][1]["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"])<tol)
    assert(abs(res_wye["PowerTransformer.PowerTransformerEnd"][1]["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"] - wye["PowerTransformer.PowerTransformerEnd"][1]["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"])<tol)
    assert(res_wye["PowerTransformer.PowerTransformerEnd"][1]["PowerTransformerEnd.connectionKind"] == "WindingConnection.Y")
    assert(mid_delta["PowerTransformer.PowerTransformerEnd"][1]["PowerTransformerEnd.connectionKind"] == "WindingConnection.D")
    print("<TESTING> Wye-Delta-Wye test passed")
