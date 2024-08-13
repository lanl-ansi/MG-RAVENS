import json


class CIMTemplate:
    def __init__(self, file):
        with open(file, "r") as f:
            self.template = json.load(f)


def collect_template_node_names(template: dict, nodes: list, currentParent: str = None, parentObject: str = None):
    for k, v in template.items():
        if isinstance(v, dict) and v.get("type", "none") == "container":
            nodes = collect_template_node_names(v.get("properties", {}), nodes, parentObject=k)
        elif isinstance(v, dict) and v.get("type", "none") == "object":
            if currentParent is not None:
                nodes.append(f"{currentParent}::{k}")
                nodes = collect_template_node_names(v.get("properties", {}), nodes, currentParent=f"{currentParent}::{k}")
            else:
                nodes.append(k)
                nodes = collect_template_node_names(v.get("properties", {}), nodes, currentParent=k)
        elif isinstance(v, dict) and v.get("type", "none") == "ref":
            continue

    return nodes
