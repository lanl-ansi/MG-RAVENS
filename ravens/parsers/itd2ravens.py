import json
import uuid

from ravens import RavensData


def import_json(file):
    with open(file) as f:
        return json.load(f)


# a similar function can be found on stackexchange


def merge_dicts(dict1, dict2):
    """
    Merges two nested dictionaries without overwriting any entries in the original dictionary.

    Args:
        dict1 (dict): The original dictionary.
        dict2 (dict): The dictionary to be added to the original dictionary.

    Returns:
        dict: The merged dictionary.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


# I used the AI portal to write this function


def merge_TD(folder, t_ravens, d_dss, bd_json, feeder_name, merged_file_name, num_feeders):
    """
    Right now, this looks like it can only handle a single feeder.
    The solution is to run this merge_TD for each distribution
    dss file. The first run should define t_ravens as the
    transmission RAVENS file (json). The subsequent runs should use the merged file for t_ravens.
    Note that, if this works, the transmission equipment and
    connectivity node keys should stay the same. For the
    distribution network, any keys which are also present
    in the transmission system will be appended with _d
    in the distribution feeder. For multinetwork, the keys
    for the second dist will have _d_d at the end, third
    _d_d_d, etc.
    """
    dd = RavensData().import_dss(d_dss)
    dd.dump("temp_dd_file.json")
    dd_dict = import_json("temp_dd_file.json")

    transmission_dict = import_json(t_ravens)

    # This part of the function extracts all of the keys
    # from the distribution network and overwrites them
    # with identifiers

    # Lines
    lines = []
    lines_keys = []
    try:
        lines_keys = list(dd.iter["ACLineSegment"].keys())
        print("lines_keys = ", lines_keys)
        lines = [f"ACLineSegment::'{line}'" for line in lines_keys]
    except Exception as e:
        print(f"Error in lines: {e}")
        lines = []
    print("lines = ", lines)

    # Transformers
    trnfmrs = []
    trnfmrs_keys = []
    try:
        trnfmrs_keys = list(dd.iter["PowerTransformer"].keys())
        trnfmrs = [f"PowerTransformer::'{trn}'" for trn in trnfmrs_keys]
    except Exception as e:
        print(f"Error in transformers: {e}")
        trnfmrs = []

    # Nodes (no try-except in original, so keeping it the same)
    nodes_keys = list(dd.iter["ConnectivityNode"].keys())
    nodes = [f"ConnectivityNode::'{bus}'" for bus in nodes_keys]

    # Shunts
    shunts = []
    shunts_keys = []
    try:
        shunts_keys = list(dd.iter["LinearShuntCompensator"].keys())
        shunts = [f"LinearShuntCompensator::'{shunt}'" for shunt in shunts_keys]
    except Exception as e:
        print(f"Error in shunts: {e}")
        shunts = []

    # More shunts (FIXED BUG: was copying 'shunts' instead of 'more_shunts')
    more_shunts = []
    more_shunts_keys = []
    try:
        more_shunts_keys = list(dd.iter["ShuntCompensator"].keys())
        more_shunts = [f"ShuntCompensator::'{shunt}'" for shunt in more_shunts_keys]
    except Exception as e:
        print(f"Error in more_shunts: {e}")
        more_shunts = []

    # Loads
    loads = []
    loads_keys = []
    try:
        loads_keys = list(dd.iter["EnergyConsumer"].keys())
        loads = [f"EnergyConsumer::'{ld}'" for ld in loads_keys]
    except Exception as e:
        print(f"Error in loads: {e}")
        loads = []

    # Sources
    srcs = []
    srcs_keys = []
    try:
        srcs_keys = list(dd.iter["EnergySource"].keys())
        srcs = [f"EnergySource::'{src}'" for src in srcs_keys]
    except Exception as e:
        print(f"Error in sources: {e}")
        srcs = []

    # Generators
    gens = []
    gens_keys = []
    try:
        gens_keys = list(dd.iter["RotatingMachine"].keys())
        gens = [f"RotatingMachine::'{gen}'" for gen in gens_keys]
    except Exception as e:
        print(f"Error in generators: {e}")
        gens = []

    # Switches
    switches = []
    switch_keys = []
    try:
        switch_keys = list(dd.iter["Switch"].keys())
        switches = [f"Switch::'{switch}'" for switch in switch_keys]
    except Exception as e:
        print(f"Error in switches: {e}")
        switches = []
    print(switches)

    # Batteries (FIXED BUG: was copying 'gens' instead of 'batteries')
    batteries = []
    battery_keys = []
    try:
        battery_keys = list(dd.iter["PowerElectronicsConnection"].keys())
        batteries = [f"PowerElectronicsConnection::'{battery}'" for battery in battery_keys]
    except Exception as e:
        print(f"Error in batteries: {e}")
        batteries = []

    the_feeder = {
        feeder_name: {
            "Ravens.cimObjectType": "Feeder",
            "IdentifiedObject.mRID": str(uuid.uuid4()),
            "IdentifiedObject.name": feeder_name,
            "ConnectivityNodeContainer.ConnectivityNodes": nodes,
            "EquipmentContainer.Equipments": lines + trnfmrs + shunts + loads + srcs + gens + batteries + switches + more_shunts,  # TODO: add other equipments as encountered (routine)
        }
    }

    itd_dict = merge_dicts(transmission_dict, dd_dict)

    itd_dict['Group'].update(the_feeder)

    bndry = import_json(bd_json)

    # pulls the bus where the voltage source is located
    dist_bus = dd_dict["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["EnergyConnection"]["EnergySource"]["source"]["ConductingEquipment.Terminals"][0]["Terminal.ConnectivityNode"]
    print("the distribution bus is ", dist_bus)
    energy_src = dd_dict["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["EnergyConnection"]["EnergySource"]["source"]

    # create a line for each boundary connection

    # current_num_lines = len(itd_dict['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor']['ACLineSegment'])
    current_num_lines = 0
    bd_lines = {}
    for bd in range(len(bndry)):
        bdl = {
            "line_bd_"
            + str(bd + 1 + current_num_lines): {
                "Ravens.cimObjectType": "ACLineSegment",
                "IdentifiedObject.mRID": str(uuid.uuid4()),
                "IdentifiedObject.name": "line_bd_" + str(bd + 1),
                "Equipment.inService": True,
                "ACLineSegment.r": energy_src["EnergySource.r"],
                "ACLineSegment.x": energy_src["EnergySource.x"],
                "ConductingEquipment.Terminals": [
                    {
                        "Ravens.cimObjectType": "Terminal",
                        "IdentifiedObject.mRID": str(uuid.uuid4()),
                        "IdentifiedObject.name": "line_bd_" + str(bd + 1 + current_num_lines) + "_T",
                        "ACDCTerminal.sequenceNumber": 1,
                        "Terminal.ConnectivityNode": "ConnectivityNode::'" + bndry[bd]["transmission_boundary"] + "'",
                    },
                    {
                        "Ravens.cimObjectType": "Terminal",
                        "IdentifiedObject.mRID": str(uuid.uuid4()),
                        "IdentifiedObject.name": "line_bd_" + str(bd + 1 + current_num_lines) + "_D",
                        "ACDCTerminal.sequenceNumber": 2,
                        "Terminal.ConnectivityNode": dist_bus,
                    },
                ],
            }
        }
        bd_lines.update(bdl)

    # add them to the itd_dict

    itd_dict["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"].update(bd_lines)

    with open(folder + "/" + merged_file_name + ".json", "w") as fp:
        json.dump(itd_dict, fp, indent=2)