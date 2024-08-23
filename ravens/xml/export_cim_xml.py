import json
import re

from copy import deepcopy
from uuid import uuid4

from rdflib.exceptions import UniquenessError
from rdflib.namespace import Namespace
from rdflib.term import URIRef, Literal
from rdflib import Graph, RDF

from ravens.cim_tools.common import get_names_of_enumeration_classes
from ravens.io import parse_eap_data


class RavensExport(object):
    def __init__(self, data, core_data_path=None):
        self.data = deepcopy(data)
        self.cim_enums = None
        if core_data_path is not None:
            core_data = parse_eap_data(core_data_path)
            self.cim_enums = get_names_of_enumeration_classes(core_data.objects)

        self.graph = Graph()
        self.cim = Namespace("http://iec.ch/TC57/CIM100#")
        self.graph.bind("cim", self.cim, override=True)

        self.build_rdf_graph(self.data)
        self.update_uri_refs()
        if self.cim_enums is not None:
            self.update_enumeration_uri_refs()

    def build_rdf_graph(self, data, obj_name=None):
        for k, v in data.items():
            if isinstance(v, dict):
                if "Ravens.CimObjectType" in v:
                    child_node = self.add_object_to_graph(v)
                else:
                    self.build_rdf_graph(v, obj_name=k)
            else:
                raise Exception(f"This shouldn't happen. Error at '{k}' with value of type '{type(v)}'")

    def add_object_to_graph(self, obj, obj_name=None):
        mrid = obj.get("IdentifiedObject.mRID", str(uuid4()))
        cim_type = obj.pop("Ravens.CimObjectType")
        node = URIRef(mrid)
        self.graph.add((node, RDF.type, self.cim[cim_type]))

        if "IdentifiedObject.name" not in obj and obj_name is not None:
            obj["IdentifiedObject.name"] = obj_name

        for k, v in obj.items():
            if isinstance(v, dict):
                if "Ravens.CimObjectType" in v:
                    child_node = self.add_object_to_graph(v)
                    self.graph.add((node, self.cim[k], child_node))
                else:
                    self.build_rdf_graph(v)
            elif isinstance(v, list):
                for item in v:
                    if "Ravens.CimObjectType" in item:
                        child_node = self.add_object_to_graph(item)
                        self.graph.add((node, self.cim[k], child_node))
                    else:
                        self.build_rdf_graph(item)
            else:
                self.graph.add((node, self.cim[k], Literal(str(v))))

        return node

    def update_uri_refs(self):
        po_to_update = {}
        for p, o in self.graph.predicate_objects():
            if isinstance(o, Literal):
                match = re.match(r"(\w+)::'(.+)'", o)
                if match:
                    cim_type, obj_name = match.groups()
                    po_to_update[(p, o)] = (cim_type, obj_name)

        triple_to_delete = []
        for (p, o), (cim_type, obj_name) in po_to_update.items():
            target_subject = None
            # TODO: how to handle if using IdentifiedObject.name vs IdentifiedObject.mRID?
            try:
                target_subject = self.graph.value(predicate=self.cim["IdentifiedObject.name"], object=Literal(obj_name), any=False)
            except UniquenessError as msg:
                for s in self.graph.subjects(predicate=self.cim["IdentifiedObject.name"], object=Literal(obj_name)):
                    if self.graph.value(subject=s, predicate=RDF.type) == self.cim[f"{cim_type}"]:
                        target_subject = s
                        break

                if target_subject is None:
                    raise UniquenessError(msg)

            for s in self.graph.subjects(predicate=p, object=o):
                self.graph.add((s, p, target_subject))
                triple_to_delete.append((s, p, o))

        for triple in triple_to_delete:
            self.graph.remove(triple)

    def update_enumeration_uri_refs(self):
        triple_to_delete = []
        for s, p, o in self.graph.triples((None, None, None)):
            if isinstance(o, Literal):
                if any(o.startswith(enum) for enum in self.cim_enums):
                    self.graph.add((s, p, self.cim[str(o)]))
                    triple_to_delete.append((s, p, o))

        for triple in triple_to_delete:
            self.graph.remove(triple)


if __name__ == "__main__":
    with open("out/test_xml2json_case3.json", "r") as f:
        d = json.load(f)

    r = RavensExport(d, core_data_path="cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap")
    r.graph.serialize("out/test_output.xml", max_depth=1, format="pretty-xml")
