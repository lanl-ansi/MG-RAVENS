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

    lines = []
    lines_keys = []
    try:
        lines = list(dd.iter["ACLineSegment"].keys())
        lines_keys = copy.deepcopy(lines)
        for line in range(len(lines)):
            lines[line] = "ACLineSegment::'" + lines[line] + "'"
    except:
        lines = []

    trnfmrs = []
    trnfmrs_keys = []
    try:
        trnfmrs = list(dd.iter["PowerTransformer"].keys())
        trnfmrs_keys = copy.deepcopy(trnfmrs)
        for trn in range(len(trnfmrs)):
            trnfmrs[trn] = "PowerTransformer::'" + trnfmrs[trn] + "'"
    except:
        trnfmrs = []

    nodes = list(dd.iter["ConnectivityNode"].keys())
    nodes_keys = list(dd.iter["ConnectivityNode"].keys())
    for bus in range(len(nodes)):
        nodes[bus] = "ConnectivityNode::'" + nodes[bus] + "'"

    shunts = []
    shunts_keys = []
    try:
        shunts = list(dd.iter["LinearShuntCompensator"].keys())
        shunts_keys = copy.deepcopy(shunts)
        for shunt in range(len(shunts)):
            shunts[shunt] = "LinearShuntCompensator::'" + shunts[shunt] + "'"
    except:
        shunts = []

    more_shunts = []
    more_shunts_keys = []
    try:
        more_shunts = list(dd.iter["ShuntCompensator"].keys())
        more_shunts_keys = copy.deepcopy(shunts)
        for shunt in range(len(more_shunts)):
            more_shunts[shunt] = "ShuntCompensator::'" + more_shunts[shunt] + "'"
    except:
        more_shunts = []

    loads = []
    loads_keys = []
    try:
        loads = list(dd.iter["EnergyConsumer"].keys())
        loads_keys = copy.deepcopy(loads)
        for ld in range(len(loads)):
            loads[ld] = "EnergyConsumer::'" + loads[ld] + "'"
    except:
        loads = []

    srcs = []
    srcs_keys = []
    try:
        srcs = list(dd.iter["EnergySource"].keys())
        srcs_keys = copy.deepcopy(srcs)
        for src in range(len(srcs)):
            srcs[src] = "EnergySource::'" + srcs[src] + "'"
    except:
        srcs = []

    gens = []
    gens_keys = []
    try:
        gens = list(dd.iter["RotatingMachine"].keys())
        gens_keys = copy.deepcopy(gens)
        for gen in range(len(gens)):
            gens[gen] = "RotatingMachine::'" + gens[gen] + "'"
    except:
        gens = []

    switches = []
    switch_keys = []
    try:
        switches = list(dd.iter["Switch"].keys())
        switch_keys = copy.deepcopy(switches)
        for switch in range(len(switches)):
            switches[switch] = "Switch::'" + switches[switch] + "'"
    except:
        switches = []
    print(switches)

    batteries = []
    battery_keys = []
    try:
        batteries = list(dd.iter["PowerElectronicsConnection"].keys())
        battery_keys = copy.deepcopy(gens)
        for battery in range(len(batteries)):
            batteries[battery] = "PowerElectronicsConnection::'" + batteries[battery] + "'"
    except:
        batteries = []

    the_feeder = {
        feeder_name: {
            "Ravens.cimObjectType": "Feeder",
            "IdentifiedObject.mRID": str(uuid.uuid4()),
            "IdentifiedObject.name": "the_feeder",
            "ConnectivityNodeContainer.ConnectivityNodes": nodes,
            "EquipmentContainer.Equipments": lines + trnfmrs + shunts + loads + srcs + gens + batteries + switches + more_shunts,  # TODO: add other equipments as encountered (routine)
        }
    }

    itd_dict = merge_dicts(transmission_dict, dd_dict)

    itd_dict.update(the_feeder)

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
