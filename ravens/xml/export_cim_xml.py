import json
import re

from uuid import uuid4

from rdflib.exceptions import UniquenessError
from rdflib.namespace import Namespace
from rdflib.term import URIRef, Literal
from rdflib import Graph, RDF


class RavensExport:
    def __init__(self, data):
        self.data = data

        self.graph = Graph()
        self.cim = Namespace("http://iec.ch/TC57/CIM100#")
        self.graph.bind("cim", self.cim, override=True)

        self.build_rdf_graph(self.data)
        self.update_uri_refs()

    def build_rdf_graph(self, data, parent_subject=None, parent_predicate=None):
        for k, v in data.items():
            if isinstance(v, dict):
                if "Ravens.CimObjectType" in v:
                    child_node = self.add_object_to_graph(v, parent_subject=parent_subject, parent_predicate=parent_predicate)
                else:
                    self.build_rdf_graph(v)
            elif isinstance(v, list):
                pass
            else:
                pass
                # self.add_to_graph()

    def add_object_to_graph(self, obj, obj_name=None, parent_subject=None, parent_predicate=None):
        mrid = obj.get("IdentifiedObject.mRID", str(uuid4()))
        if "IdentifiedObject.name" not in obj and obj_name is not None:
            obj["IdentifiedObject.name"] = obj_name

        cim_type = obj.pop("Ravens.CimObjectType")

        node = URIRef(mrid)

        a = self.graph.add((node, RDF.type, self.cim[cim_type]))
        # if parent_subject is not None and parent_predicate is not None:
        #     self.graph.add((node, parent_predicate, parent_subject))

        for k, v in obj.items():
            if isinstance(v, dict):
                self.build_rdf_graph(v, parent_subject=node, parent_predicate=self.cim[k])
            elif isinstance(v, list):
                for item in v:
                    if "Ravens.CimObjectType" in item:
                        child_node = self.add_object_to_graph(item, parent_subject=node, parent_predicate=self.cim[k])
                        self.graph.add((node, self.cim[k], child_node))
                    else:
                        self.build_rdf_graph(item, parent_subject=node, parent_predicate=self.cim[k])
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
            try:
                target_subject = self.graph.value(predicate=CIM["IdentifiedObject.name"], object=Literal(obj_name), any=False)
            except UniquenessError as msg:
                for s in self.graph.subjects(predicate=CIM["IdentifiedObject.name"], object=Literal(obj_name)):
                    if self.graph.value(subject=s, predicate=RDF.type) == CIM[f"{cim_type}"]:
                        target_subject = s
                        break

                if target_subject is None:
                    raise UniquenessError(msg)

            for s in self.graph.subjects(predicate=p, object=o):
                self.graph.add((s, p, target_subject))
                triple_to_delete.append((s, p, o))

        for triple in triple_to_delete:
            self.graph.remove(triple)


if __name__ == "__main__":
    with open("out/test_xml2json_case3.json", "r") as f:
        d = json.load(f)

    r = RavensExport(d)
    r.graph.serialize("out/test_output.xml", max_depth=1, base=CIM, format="pretty-xml")
