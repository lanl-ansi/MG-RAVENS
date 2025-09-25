import json
import numpy as np
import scipy.special as sp
from .ll_simp import ll_simp as ll
from .DY_Transforms import wye_2_delta as w2d
# from ll_simp import ll_simp as ll
# from DY_Transforms import wye_2_delta as w2d
np.set_printoptions(edgeitems=3, linewidth=200, precision=5, suppress=False, threshold=1000, formatter=None)



def tank2transformer(in_data,out_data=None,tank_merge=True):
    """
    Input: Takes as an input a RAVENS files
    Output: A RAVENS file modified such that all references to tank based transformers are converted to standard transformers 
    Core Data Structures:
        - PT Dictionary of all PowerTransformer data
        - TTIs Dictionary of Transformer info in order to access Transformer Tank Info
    """
    if out_data is None and isinstance(in_data, dict):
        transformer_tank_purge = ll("transformer tank purge",["PowerTransformerInfo.TransformerTankInfos"],{},{},auto_tl=False) 
        raven = tank2transformer_compute(in_data,tank_merge=tank_merge)
        return transformer_tank_purge(raven)
    elif isinstance(in_data, str) and isinstance(out_data, str):
        transformer_tank_purge = ll("transformer tank purge",["PowerTransformerInfo.TransformerTankInfos"],{},{},auto_tl=False) 
        with open(in_data, 'r') as input_file,open("tmp/t2t_mp.json",'w') as mp_file, open(out_data, 'w') as output_file:
            #1) setup json dictionary
            raven = json.loads(input_file.read()) 

            #2) compute simplification
            raven = tank2transformer_compute(raven,output_file=output_file,tank_merge=tank_merge)
        
            #3) close down json dictionary
            json.dump(raven, mp_file, indent=2)
        #4) clean up any remaining wire info references
        transformer_tank_purge("tmp/t2t_mp.json", out_data)
    else:
        raise ValueError("Invalid arguments. Expected either a dictionary or two filenames.")


def tank2transformer_compute(raven,output_file = None, tank_merge = False):
    #1) find all transformer/transformer info 
    if not has(raven,"PowerTransformer"):
        return raven
    
    PowerTransformers = raven["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["PowerTransformer"]
    PT = raven_find(raven,"PowerTransformer")
    TTIs = get(raven,"PowerTransformerInfo") 
    
    #data lookup error/null case handling 
    if len(PT) > 1: #Error Case
        print("ERROR: Improperly specified Transformer")
        return
    elif len(PT) == 0: #Null Case
        return raven
    
    #identified all transformers and transformer info 
    PT = PT[0][1]
    

    #2) generate standard transformers
    for trans_name, trans_data in list(PT.items()):
        if has(trans_data,"PowerTransformer.TransformerTank"):
            #A) Setup Transformer Wide Info

            #check connection pattern
            conn_pattern = pattern(trans_data)
            #get all transformer terminals
            terminals = get(trans_data,"ConductingEquipment.Terminals")

            #B) Generate new transformer objects
            #B0) Found viable 3-phase Simplification
            if conn_pattern != [None for _ in conn_pattern] and tank_merge and not has(trans_data,"TransformerEnd.RatioTapChanger"):
                PowerTransformers["Simplified_"+trans_name] = gen_from_pattern(trans_name,trans_data,terminals,conn_pattern,TTIs)

            #B1) Iterate Over Each Tank - split each tank into a new transformer (no viable simplification exists)
            else: 
                for tank in get(trans_data,"PowerTransformer.TransformerTank"):
                    # a) Get Tank Data
                    #get tank name
                    tank_name = "Simplified_" + get(tank,"IdentifiedObject.name")

                    #get relevant tank ends
                    tank_ends = get(tank,"TransformerTank.TransformerTankEnd")
                    tank_end_numbers = [get(TE,"TransformerEnd.endNumber") for TE in tank_ends] #get numbers that match with terminals

                    #get relevant terminals
                    tank_terminals = []
                    for term in terminals:
                        if has(term, "ACDCTerminal.sequenceNumber") and get(term, "ACDCTerminal.sequenceNumber") in tank_end_numbers:
                            tank_terminals.append(term.copy())

                    #correct terminal phases
                    for term in tank_terminals:
                        term_number = get(term, "ACDCTerminal.sequenceNumber",None)
                        paired_tank_end = None
                        for te in tank_ends:
                            if get(te,"TransformerEnd.endNumber") == term_number:
                                paired_tank_end = te
                        term["Terminal.phases"] = paired_tank_end["TransformerTankEnd.phases"]

                    if len(tank_ends) != len(tank_terminals):
                        raise KeyError("Not able to find enough terminals for tank " + str(get(tank,"IdentifiedObject.name")))
                    
                    #get relevant transformer tank info
                    tank_info_name = get(tank,"PowerSystemResource.AssetDatasheet").split(":")[-1].strip("'")
                    # tank_info_name = get(tank,"PowerSystemResource.AssetDatasheet").strip("'")
                    TTI = []
                    for tti in TTIs.values():
                        if get(tti,"IdentifiedObject.name") == tank_info_name:
                            TTI.append(tti["PowerTransformerInfo.TransformerTankInfos"][tank_info_name]["TransformerTankInfo.TransformerEndInfos"])
                    if len(TTI) != 1:
                        raise KeyError("Transformer Tank Info improperly defined for " + str(tank_info_name))
                    TTI = TTI[0]

                    # b) convert to new math

                    #for each transformer end generate a new transformer 
                    aux = {}
                    aux["rated_U_1"] = get(TTI[0],"TransformerEndInfo.ratedU")
                    for i in range(len(tank_ends)):
                        #collect tank specific data
                        tank_end = tank_ends[i]
                        tank_end_info = TTI[i]

                        # Transformer Star Impedance 
                        TSI = get(tank_end_info,"TransformerEndInfo.TransformerStarImpedance",None)
                        TEI_xr = [get(tank_end_info,"TransformerEndInfo.x",None),get(tank_end_info,"TransformerEndInfo.r",None)]
                        ESCT = get(tank_end_info,"TransformerEndInfo.EnergisedEndShortCircuitTests",None)
                        tank_end["TransformerEnd.StarImpedance"] = calc_TSI(tank_end_info,TSI,TEI_xr,ESCT,aux)

                        # Transformer Core Admittance
                        EENLT = get(TTI[0],"TransformerEndInfo.EnergisedEndNoLoadTests",None) #always WRT the first winding
                        if (i==0):
                            tank_end["TransformerEnd.CoreAdmittance"] = calc_TCA(tank_end_info,EENLT,aux)

                        # S/U/R
                        tank_end["PowerTransformerEnd.ratedS"] = tank_end_info["TransformerEndInfo.ratedS"]
                        tank_end["PowerTransformerEnd.ratedU"] = tank_end_info["TransformerEndInfo.ratedU"]
                        # tank_end["PowerTransformerEnd.r"] = tank_end_info["TransformerEndInfo.r"]

                        # Specify Connection Kind
                        tank_end["PowerTransformerEnd.connectionKind"] = tank_end_info["TransformerEndInfo.connectionKind"]
                        if  tank_end["PowerTransformerEnd.connectionKind"] == "WindingConnection.I" or tank_end["PowerTransformerEnd.connectionKind"] == "WindingConnection.Yn":
                            tank_end["PowerTransformerEnd.connectionKind"] = "WindingConnection.Y"


                        # Clean Unneeded
                        if "TransformerTankEnd.phases" in tank_end.keys():
                            del tank_end["TransformerTankEnd.phases"]
                        if "TransformerEnd.rground" in tank_end.keys():
                            del tank_end["TransformerEnd.rground"]
                        if "TransformerEnd.xground" in tank_end.keys():
                            del tank_end["TransformerEnd.xground"]


                    # c) Write new transformer for the tank and info (if not already set)
                    PowerTransformers[tank_name] = {
                        "IdentifiedObject.name":tank_name, #DONE
                        "Ravens.cimObjectType": "PowerTransformer",
                        "PowerTransformer.PowerTransformerEnd":tank_ends, #DONE:
                        "ConductingEquipment.Terminals":tank_terminals #DONE
                    }

                    # d) fix delta/wye impedance issue
                    for end in range(1,3):
                        if PowerTransformers[tank_name]["PowerTransformer.PowerTransformerEnd"][end-1]["PowerTransformerEnd.connectionKind"] == "WindingConnection.D":
                            PowerTransformers[tank_name] = w2d(PowerTransformers[tank_name],end)

                

            #C) remove old tank based transformer
            del PowerTransformers[trans_name]
    return raven




#CONFIGURATION ID HELPERS

def gen_from_pattern(trans_name,transformer,terminals,pattern,TTIs):
    """
    Generates a new transformer based on existing data given specified Y/Yn/D patterns
    """
    end_1 = create_end(transformer,terminals,pattern[0],1,TTIs)
    end_2 = create_end(transformer,terminals,pattern[1],2,TTIs)

    return {
            "IdentifiedObject.name":trans_name, 
            "Ravens.cimObjectType": "PowerTransformer",
            "PowerTransformer.PowerTransformerEnd":[end_1,end_2], 
            "ConductingEquipment.Terminals":terminals 
            }

def create_end(transformer,terminals,pattern,end_num,TTIs):
    """
    Generates a an end of a new transformer based on existing data given a specified Y/Yn/D pattern
    """
    #Setup Data
    original_ends = []
    for tank in transformer["PowerTransformer.TransformerTank"]:
        for te in tank["TransformerTank.TransformerTankEnd"]:
            if te["TransformerEnd.endNumber"]==end_num:
                original_ends.append(te)
    new_end = {
        "Ravens.cimObjectType": "TransformerTankEnd",
        "IdentifiedObject.name": transformer["IdentifiedObject.name"]+"_"+str(end_num),
        "TransformerEnd.grounded": transformer["PowerTransformer.TransformerTank"][0]["TransformerTank.TransformerTankEnd"][0]["TransformerEnd.grounded"],
        "TransformerEnd.endNumber": end_num,
    }
    tank_end_info = None
    asset_info_name = transformer["PowerTransformer.TransformerTank"][0]["PowerSystemResource.AssetDatasheet"].split(":")[-1].strip("'")
    # asset_info_name = transformer["PowerTransformer.TransformerTank"][0]["PowerSystemResource.AssetDatasheet"].strip("'")
    for tti in TTIs.values():
        if get(tti,"IdentifiedObject.name") == asset_info_name:
            tank_end_info = tti["PowerTransformerInfo.TransformerTankInfos"][asset_info_name]["TransformerTankInfo.TransformerEndInfos"][0]
    aux = {}
    aux["rated_U_1"] = get(tank_end_info,"TransformerEndInfo.ratedU")

    #Core admittance
    if (end_num == 1):
        EENLT = get(tank_end_info,"TransformerEndInfo.EnergisedEndNoLoadTests",None) #always WRT the first winding
        
        new_end["TransformerEnd.CoreAdmittance"] = calc_TCA(tank_end_info,EENLT,aux)


    #Star Impedance
    TSI = get(tank_end_info,"TransformerEndInfo.TransformerStarImpedance",None)
    TEI_xr = [get(tank_end_info,"TransformerEndInfo.x",None),get(tank_end_info,"TransformerEndInfo.r",None)]
    ESCT = get(tank_end_info,"TransformerEndInfo.EnergisedEndShortCircuitTests",None)
    new_end["TransformerEnd.StarImpedance"] = calc_TSI(tank_end_info,TSI,TEI_xr,ESCT,aux)

    #TODO: Ratio Tap Changer    

    #TODO: Calculations to verify
    # r = r * sqrt3 (for delta)
    # S = 3*S
    # U = U
    # TCA = TCA * sqrt3 (for delta)
    # TSI = TSI / sqrt3 (for delta)


    #calculate common parameters
    new_end["PowerTransformerEnd.ratedS"] = 3*tank_end_info["TransformerEndInfo.ratedS"]
    new_end["PowerTransformerEnd.ratedU"] = tank_end_info["TransformerEndInfo.ratedU"]
    


    #pattern specific parameter generation
    if pattern == "Y": #TODO
        new_end["PowerTransformerEnd.connectionKind"] = "WindingConnection.Y"
        new_end["PowerTransformerEnd.r"] = tank_end_info["TransformerEndInfo.r"]
        new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"]
        new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"]
    elif pattern == "Yn": #TODO
        new_end["PowerTransformerEnd.connectionKind"] = "WindingConnection.Yn"
        new_end["PowerTransformerEnd.r"] = tank_end_info["TransformerEndInfo.r"]
        new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"]
        new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"]
    elif pattern == "D": #TODO
        new_end["PowerTransformerEnd.connectionKind"] = "WindingConnection.D"
        new_end["PowerTransformerEnd.r"] = np.sqrt(3)*tank_end_info["TransformerEndInfo.r"]
        new_end["TransformerEnd.MeshImpedance"] = {
            "Ravens.cimObjectType": "TransformerMeshImpedance",
            "TransformerMeshImpedance.r": 0,
            "TransformerMeshImpedance.x": 0,
        }
        new_end["TransformerEnd.MeshImpedance"]["TransformerMeshImpedance.r"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.r"]
        new_end["TransformerEnd.MeshImpedance"]["TransformerMeshImpedance.x"] = new_end["TransformerEnd.StarImpedance"]["TransformerStarImpedance.x"]
        del new_end["TransformerEnd.StarImpedance"]
        if has(new_end,"TransformerEnd.CoreAdmittance"):
            new_end["TransformerEnd.CoreAdmittance"]["TransformerCoreAdmittance.g"] = new_end["TransformerEnd.CoreAdmittance"]["TransformerCoreAdmittance.g"]*np.sqrt(3)
            new_end["TransformerEnd.CoreAdmittance"]["TransformerCoreAdmittance.b"] = new_end["TransformerEnd.CoreAdmittance"]["TransformerCoreAdmittance.b"]*np.sqrt(3)
    else:
        raise KeyError("Unsupported Connection Type",pattern)
    return new_end


def pattern(transformer):
    """
    Input: Dictionary for a given transformer
    Output: List of length equal to number of windings specifying a Y/Yn/D configuration for each winding
    """
    phases = {}
    windings = {}
    if has(transformer,"PowerTransformer.TransformerTank"):
        #Must Confirm all tanks have the same AssetInfo
        AssetInfo = []
        for tank in transformer["PowerTransformer.TransformerTank"]:
            AssetInfo.append(tank["PowerSystemResource.AssetDatasheet"])
        if len(set(AssetInfo)) != 1:
            return [None for _ in phases.values()]
        
        #1) Structural Modeling of Transformer
        #get connection information
        for terminal in transformer["ConductingEquipment.Terminals"]:
            name = terminal["IdentifiedObject.name"]
            phase_code = terminal["Terminal.phases"].split(".")[-1]
            seq_number = terminal["ACDCTerminal.sequenceNumber"]
            if seq_number not in phases:
                phases[seq_number] = {}
            for phase in phase_code:
                phases[seq_number][name + "_" + phase] = []
        #get winding information
        for tank in transformer["PowerTransformer.TransformerTank"]:
            for winding in tank["TransformerTank.TransformerTankEnd"]:
                name = winding["IdentifiedObject.name"]
                phase_code = winding["TransformerTankEnd.phases"].split(".")[-1]
                end_number = winding["TransformerEnd.endNumber"]
                if end_number not in windings:
                    windings[end_number] = {}
                windings[end_number][name] = set(phase_code)
        #match connections to windings
        for t, terminal in phases.items():
            for phase, connections in terminal.items():
                owned_connection = phase[-1]
                for w_name, winding in windings[t].items(): 
                    if owned_connection in winding:
                        connections.append(w_name)

        #2) Detection of Transformer Type based on model
        label = []
        for t, terminal in phases.items():
            #A) WYE detector
            valid_Y = True
            seen = set()
            #confirm the existence of 3 windings and 3 or 4 connections   
            if len(windings[t]) != 3 or len(terminal) < 3 or len(terminal) > 4: 
                valid_Y = False
            else:
                for phase, connections in terminal.items():
                    if len(connections) == 1:
                        if connections[0] in seen:
                            valid_Y = False
                            break
                        seen.add(connections[0])
                    elif len(connections) != 3:
                        valid_Y = False
                        break
            if valid_Y:
                if len(terminal) == 4 and max([len(connections) for connection in terminal.values()]) == 3:
                    label.append("Yn")
                else:
                    label.append("Y")
                continue
            #B) Delta detector
            valid_D = True
            seen = {}
            #confirm the existence of 3 windings and 3 or 4 connections   
            if len(windings[t]) != 3 or len(terminal) != 3: 
                valid_D = False
            else:
                for phase, connections in terminal.items():
                    if len(connections) == 2:
                        for conn in connections:
                            if conn in seen.keys():
                                seen[conn] +=1
                            else:
                                seen[conn] = 1
                    else:
                        valid_D = False 
                        break
                if len(seen.keys()) != 3:
                    valid_D = False
                for count in seen.values():
                    if count != 2:
                        valid_D = False
                        break
            if valid_D:
                label.append("D")
                continue
            #none found
            label.append(None)
    return label




#TRANSFORMER MATH

def calc_TSI(tank_end_info, TSI,TEI_xr,ESCT,aux):
    if TSI != None:
        return TSI
    if TEI_xr[0] != None and TEI_xr[1] != None:
        return {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": TEI_xr[1]*2, #TODO: Validate the 2x?
            "TransformerStarImpedance.x": TEI_xr[0],
        }
    elif ESCT != None:
        zbase = (get(tank_end_info,"TransformerEndInfo.ratedU")**2)/get(tank_end_info,"TransformerEndInfo.ratedS")
        ratio_self = get(tank_end_info,"TransformerEndInfo.ratedU")/1e3
        rated_U_1 = aux["rated_U_1"]
        ratio_1 = rated_U_1/1e3

        leak_impedance_wdg = ESCT[0]["ShortCircuitTest.leakageImpedance"]
        r_s = get(tank_end_info,"TransformerEndInfo.r")
        rs_pct = (r_s/zbase)*100.0
        x_sc = (np.sqrt((leak_impedance_wdg/zbase)**2 - (rs_pct+rs_pct)**2)/100)*zbase

        # REPEATED IN PARSING: RS and XSC computation based on ratios
        # r_s = r_s/ratio_self**2
        # x_sc = (x_sc/ratio_1**2)   # w.r.t wdg1

        return {
            "Ravens.cimObjectType": "TransformerStarImpedance",
            "TransformerStarImpedance.r": r_s*2, #TODO: Validate the 2x?
            "TransformerStarImpedance.x": x_sc,
        }
    else:
        raise KeyError("Did not specify enough transformer info to define a star impedance")

def calc_TCA(tank_end_info,EENLT,aux):
    if EENLT != None:
        rated_U_1 = aux["rated_U_1"]
        ratio_1 = rated_U_1/1e3
        snom_wdg = get(tank_end_info,"TransformerEndInfo.ratedS")
        zbase = (get(tank_end_info,"TransformerEndInfo.ratedU")**2)/get(tank_end_info,"TransformerEndInfo.ratedS")

        loss = get(EENLT[0], "NoLoadTest.loss", 0.0)
        pctNoLoadLoss = (loss*100)/(snom_wdg/1000.0)    # loss is in kW, thus snom_wdg/1000.0
        noLoadLoss = pctNoLoadLoss/100.0
        g_sh_tank =  noLoadLoss/zbase
        exct_current = get(EENLT[0], "NoLoadTest.excitingCurrent", pctNoLoadLoss)
        cmag = np.sqrt(exct_current**2 - pctNoLoadLoss**2)/100   # cmag = pctImag/100 = sqrt(pctIexc^2 - pctNoLoadLoss^2)/100
        b_sh_tank = -(cmag)/zbase
        #REPEATED IN PARSING
        # data is measured externally, but we now refer it to the internal side
        # g_sh = g_sh_tank*ratio_1**2   # w.r.t wdg1
        # b_sh = b_sh_tank*ratio_1**2   # w.r.t wdg1
        g_sh = g_sh_tank
        b_sh = -b_sh_tank #negation useful for the no tank parsing?
        return  {
                  "Ravens.cimObjectType": "TransformerCoreAdmittance",
                  "TransformerCoreAdmittance.g": g_sh,
                  "TransformerCoreAdmittance.b": b_sh,
                }
    else:
        raise KeyError("Did not specify enough transformer info to define a core admittance")

        



#RAVENS HELPER FUNCTIONS

def get(raven,target,default=0):
    return default if len(raven_find(raven,target)) == 0 else raven_find(raven,target)[0][1]

def has(raven,target):
    return len(raven_find(raven,target)) != 0


def raven_find(raven,target,path=""):
    """
    Input: raven JSON dictionary and a target member
    Output: list of all instances containing that target member with path to that instance 
    """
    found = []
    if isinstance(raven,dict):
        for key, val in list(raven.items()):
            #target found
            if key == target:
                found.append((path +"/"+str(key),val))
            #recursive step
            elif isinstance(val,dict):
                found += raven_find(val,target,path+"/"+str(key))
            elif isinstance(val,list):
                for item in val:
                    if isinstance(item,dict):
                        found += raven_find(item,target,path+"/"+str(key))
    return found






if __name__ == "__main__":
    tank2transformer("tmp/Bank_Conversion_IEEE13_Assets.json","tmp/NO_TANK_IEEE13_Assets.json")
    tank2transformer("tmp/Bank_Conversion_IEEE13_Assets_copy.json","tmp/NO_TANK_Assets_copy.json")
    tank2transformer("tmp/Bank_Conversion_IEEE13_RegControl.json","tmp/NO_TANK_IEEE13_RegControl.json")
    tank2transformer("tmp/Bank_Conversion_IEEE13_CapControl.json","tmp/NO_TANK_IEEE13_CapControl.json")
    tank2transformer("tmp/Bank_Conversion_ut_trans_2w_yy_bank.json","tmp/NO_TANK_ut_trans_2w_yy_bank.json")
    tank2transformer("tmp/Bank_Conversion_D_Test.json","tmp/NO_TANK_D_Test.json")