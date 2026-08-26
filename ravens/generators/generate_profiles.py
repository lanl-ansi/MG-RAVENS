import random
import uuid
import json
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Union
from copy import deepcopy
from ravens import RavensData


def generate_profiles(
    ravens_data: Dict[str, Any],
    load_file: Optional[str] = None,
    solar_file: Optional[str] = None,
    meter_json: Optional[str] = None,
    split_data: bool = False,
    random_seed: int = 4689
) -> Union[Dict[str, Any], tuple]:
    """
    Input: RAVENS object

    Parameters:
        - load_file: CSV of load profiles per meter
        - solar_file: CSV estimated solar generation per meter
        - meter_json: JSON meter lookup table
        - split_data: Whether to return separate dictionaries or combined
        - random_seed: Seed for UUID generation

    Output: RAVENS object that generates features needed to analyze RAVENS files including: 
        - Adds defined post-transformer loads to the RAVENS file 
        - Adds defined meter objects for fault analysis to the RAVENS file
    """
    
    # Set random seed
    random.seed(random_seed)
    
    # Check for required files
    if load_file is None or solar_file is None or meter_json is None:
        raise ValueError("load_file, solar_file, and meter_json must all be provided")

    # Parse ravens object
    energy_consumers = ravens_data.get("EnergyConsumer", {})
    PECs = ravens_data.get("PowerElectronicsConnection", {})

    # Scale/multiplier for power values for load and PVs
    to_kw = 1000.0

    # Create Dictionary for BasicIntervalSchedule
    BasicIntervalSchedule = {}

    # Create Dictionary for Curve, if it does not exist in ravens
    if "Curve" not in ravens_data:
        Curve = {}
    else:
        Curve = ravens_data["Curve"]

    # Read CSV files into dataframes
    df_load = pd.read_csv(load_file)
    df_solar = pd.read_csv(solar_file)
    
    # Read JSON file
    with open(meter_json, 'r') as f:
        meters = json.load(f)

    transformer_load = {}
    transformer_gen = {}
    found = []

    # Generate a dict from Transformer Names to Load Profiles at timestamps (meter name --> trans name)
    for meter in [col for col in df_load.columns if col != "timestamp"]:
        vals = df_load[meter].values
        
        meter_info = meters.get(meter)
        if meter_info is None:
            print(f"Meter {meter} not found in model")
            continue
        
        found.append(meter)
        trans_name = meter_info["transformer"]
        meter_phase = meter_info["phase"][0]
        
        if trans_name in transformer_load:
            trans_data = transformer_load[trans_name]
            trans_data["vals"] = trans_data["vals"] + vals
            
            # Merge phases if not already present
            existing_phase = trans_data["phase"][0]
            if meter_phase not in existing_phase:
                trans_data["phase"][0] = existing_phase + meter_phase
        else:
            transformer_load[trans_name] = {
                "vals": vals.copy(),
                "phase": deepcopy(meter_info["phase"])
            }
    
    # Generate a dict from Transformer Names to Solar Gen Profiles at timestamps (meter name --> trans name)
    for meter in [col for col in df_solar.columns if col != "timestamp"]:
        vals = df_solar[meter].values
        
        meter_info = meters.get(meter)
        if meter_info is None:
            print(f"Meter {meter} not found in model")
            continue
        
        found.append(meter)
        trans_name = meter_info["transformer"]
        meter_phase = meter_info["phase"][0]
        
        if trans_name in transformer_gen:
            trans_data = transformer_gen[trans_name]
            trans_data["vals"] = trans_data["vals"] + vals
            
            # Merge phases if not already present
            existing_phase = trans_data["phase"][0]
            if meter_phase not in existing_phase:
                trans_data["phase"][0] = existing_phase + meter_phase
        else:
            transformer_gen[trans_name] = {
                "vals": vals.copy(),
                "phase": deepcopy(meter_info["phase"])
            }

    # Get length of dataframe
    df_len = len(df_load)

    # Loop through the entire timeseries
    for i in range(df_len):
        # Load Forecasts
        for name, ravens_obj in energy_consumers.items():
            _name = name.replace("_L", "")
            
            # Create EnergyConsumerSchedule dictionary if none exists
            if f"{name}_Forecast" not in BasicIntervalSchedule:
                BasicIntervalSchedule[f"{name}_Forecast"] = {
                    "Ravens.cimObjectType": "EnergyConsumerSchedule",
                    "IdentifiedObject.mRID": f"#_{str(uuid.uuid4()).upper()}",
                    "IdentifiedObject.name": f"{name}_Forecast",
                    "BasicIntervalSchedule.value1Unit": "UnitSymbol.W",
                    "BasicIntervalSchedule.value1Multiplier": "UnitMultiplier.k",
                    "BasicIntervalSchedule.value2Unit": "UnitSymbol.VAr",
                    "BasicIntervalSchedule.value2Multiplier": "UnitMultiplier.k",
                    "EnergyConsumerSchedule.timeStep": 3600,
                    "EnergyConsumerSchedule.startDay": "Day.Sunday",
                    "EnergyConsumerSchedule.RegularTimePoints": [None] * df_len
                }
                
                # Add "EnergyConsumer.LoadProfile" to EnergyConsumer as reference
                ravens_obj["EnergyConsumer.LoadProfile"] = f"EnergyConsumerSchedule::'{name}_Forecast'"

            # Compute P and Q Forecast at time t
            pf = 0.95
            if _name in transformer_load:
                P_calc = transformer_load[_name]["vals"][i]
                Q_calc = transformer_load[_name]["vals"][i] / pf * np.sin(np.arccos(pf))
            else:
                print(f"Load missing {_name}")
                P_calc = 0.0
                Q_calc = 0.0

            # Compute load allocation
            BasicIntervalSchedule[f"{name}_Forecast"]["EnergyConsumerSchedule.RegularTimePoints"][i] = {
                "RegularTimePoint.sequenceNumber": i + 1,  # Julia is 1-indexed
                "RegularTimePoint.value1": P_calc,
                "RegularTimePoint.value2": Q_calc
            }

            # Correct the load values and use the max in the timeseries
            if i == 0:  # Assign the first timeseries value to start
                ravens_obj["EnergyConsumer.p"] = P_calc * to_kw
                ravens_obj["EnergyConsumer.q"] = Q_calc * to_kw

                if "EnergyConsumer.EnergyConsumerPhase" in ravens_obj:
                    num_phases = len(ravens_obj["EnergyConsumer.EnergyConsumerPhase"])
                    for p in range(num_phases):
                        ravens_obj["EnergyConsumer.EnergyConsumerPhase"][p]["EnergyConsumerPhase.p"] = \
                            ravens_obj["EnergyConsumer.p"] / num_phases
                        ravens_obj["EnergyConsumer.EnergyConsumerPhase"][p]["EnergyConsumerPhase.q"] = \
                            ravens_obj["EnergyConsumer.q"] / num_phases
            else:
                if P_calc * to_kw > ravens_obj["EnergyConsumer.p"]:
                    ravens_obj["EnergyConsumer.p"] = P_calc * to_kw

                    if "EnergyConsumer.EnergyConsumerPhase" in ravens_obj:
                        num_phases = len(ravens_obj["EnergyConsumer.EnergyConsumerPhase"])
                        for p in range(num_phases):
                            ravens_obj["EnergyConsumer.EnergyConsumerPhase"][p]["EnergyConsumerPhase.p"] = \
                                ravens_obj["EnergyConsumer.p"] / num_phases

                if Q_calc * to_kw > ravens_obj["EnergyConsumer.q"]:
                    ravens_obj["EnergyConsumer.q"] = Q_calc * to_kw

                    if "EnergyConsumer.EnergyConsumerPhase" in ravens_obj:
                        num_phases = len(ravens_obj["EnergyConsumer.EnergyConsumerPhase"])
                        for p in range(num_phases):
                            ravens_obj["EnergyConsumer.EnergyConsumerPhase"][p]["EnergyConsumerPhase.q"] = \
                                ravens_obj["EnergyConsumer.q"] / num_phases

        PECS_TO_IGNORE = []
        
        # Generation (Solar PV) Forecasts
        for name, ravens_obj in PECs.items():
            if name not in PECS_TO_IGNORE:
                _name = name.replace("_G", "")
                
                # Get rated S power from pec
                pecs_srated = ravens_obj["PowerElectronicsConnection.ratedS"]
                
                # Create values that go inside Curve
                if f"{name}_Profile" not in Curve:
                    Curve[f"{name}_Profile"] = {
                        "Ravens.cimObjectType": "DispatchCurve",
                        "IdentifiedObject.mRID": f"#_{str(uuid.uuid4()).upper()}",
                        "IdentifiedObject.name": f"{name}_Profile",
                        "Curve.xUnit": "UnitSymbol.h",
                        "Curve.y1Unit": "UnitSymbol.W",
                        "Curve.y1Multiplier": "UnitMultiplier.k",
                        "Curve.CurveDatas": [None] * df_len
                    }
                    
                    # Add reference to PowerElectronicsUnit
                    ravens_obj["PowerElectronicsConnection.PowerElectronicsUnit"]["PhotoVoltaicUnit.GenerationProfile"] = \
                        f"Curve::'{name}_Profile'"
                
                # Compute dispatch
                if _name in transformer_gen:
                    P_calc = transformer_gen[_name]["vals"][i]
                else:
                    print(f"Solar missing {_name}")
                    P_calc = 0.0
                
                Curve[f"{name}_Profile"]["Curve.CurveDatas"][i] = {
                    "CurveData.xvalue": i + 1,  # Julia is 1-indexed
                    "CurveData.y1value": P_calc
                }

                # Correct the dispatch values and use the max in the timeseries
                if i == 0:  # Assign the first timeseries value to start
                    ravens_obj["PowerElectronicsConnection.p"] = -P_calc * to_kw
                    if "PowerElectronicsConnection.PowerElectronicsUnit" in ravens_obj:
                        ravens_obj["PowerElectronicsConnection.PowerElectronicsUnit"]["PowerElectronicsUnit.maxP"] = \
                            ravens_obj["PowerElectronicsConnection.ratedS"]
                else:
                    if P_calc * to_kw > (-1 * ravens_obj["PowerElectronicsConnection.p"]):
                        ravens_obj["PowerElectronicsConnection.p"] = -P_calc * to_kw
                        if "PowerElectronicsConnection.PowerElectronicsUnit" in ravens_obj:
                            ravens_obj["PowerElectronicsConnection.PowerElectronicsUnit"]["PowerElectronicsUnit.maxP"] = \
                                ravens_obj["PowerElectronicsConnection.ratedS"]

    if split_data:
        return ravens_data, BasicIntervalSchedule, Curve
    
    ravens_data.data["BasicIntervalSchedule"] = BasicIntervalSchedule
    ravens_data.data["Curve"] = Curve
    rd = RavensData(ravens_data.data)
    return rd


