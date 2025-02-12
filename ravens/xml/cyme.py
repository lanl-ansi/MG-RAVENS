import math
import pathlib

from ast import literal_eval
from uuid import uuid4

from rdflib.namespace import Namespace
from rdflib.term import URIRef, Literal
from rdflib import Graph, RDF

from ravens.logging import logger
from ravens.data import _DEFAULT_CIM_NAMESPACE


# ohm.m @ 20C
material_resistivity = {"copper": 1.68e-8, "aluminum": 2.82e-8}


class CymeConverter:
    def __init__(self, cim_profile_path: pathlib.Path, cim_namespace: str = _DEFAULT_CIM_NAMESPACE, prune_remaining_cyme: bool = False):
        g = Graph()
        self.graph = g.parse(cim_profile_path, format="application/rdf+xml", publicID="#")

        self.cyme_ns = Namespace("http://www.cyme.com/CIM/1.0.2#")

        self.cim_ns = Namespace(cim_namespace)

        self.graph.bind("cim", self.cim_ns, override=True)
        self.graph.bind("cyme", self.cyme_ns, override=True)

        self.rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

        self.convert_cyme_cable_concentric_neutrals()

        if prune_remaining_cyme:
            self.remove_cyme_objects()

    def build_cim_obj(self, rdf_type: str, mrid: str = None, name: str = None, skip_mrid: bool = False) -> URIRef:
        if mrid is None:
            mrid = str(uuid4())
        node = URIRef(mrid)

        self.graph.add((node, RDF.type, self.cim_ns[rdf_type]))
        if not skip_mrid:
            self.graph.add((node, self.cim_ns["IdentifiedObject.mRID"], Literal(mrid)))
        if name is not None:
            self.graph.add((node, self.cim_ns["IdentifiedObject.name"], Literal(name)))

        return node

    def add_triple(self, subject: URIRef, predicate: str, obj):
        if isinstance(obj, bool):
            self.graph.add((subject, self.cim_ns[predicate], Literal(str(obj).lower())))
        elif isinstance(obj, URIRef):
            self.graph.add((subject, self.cim_ns[predicate], obj))
        else:
            self.graph.add((subject, self.cim_ns[predicate], Literal(str(obj))))

    def remove_cyme_objects(self):
        to_remove = set()
        for s, o in self.graph.subject_objects(predicate=self.rdf_type):
            if o.startswith(str(self.cyme_ns)):
                for triple in self.graph.triples((s, None, None)):
                    to_remove.add(triple)

        for p in self.graph.predicates():
            if p.startswith(str(self.cyme_ns)):
                for triple in self.graph.triples((None, p, None)):
                    to_remove.add(triple)

        for triple in to_remove:
            self.graph.remove(triple)

    def convert_cyme_cable_concentric_neutrals(self):
        cableinfo_triples_to_remove = set()
        cableinfo_to_replace = set()
        cccn_to_prune = set()
        for s in self.graph.subjects(predicate=self.rdf_type, object=self.cim_ns["CableInfo"]):
            cccn_ref = self.graph.value(subject=s, predicate=self.cyme_ns["CYMECableConstruction.CableConcentricNeutrals"])
            if cccn_ref is not None:
                node = self.build_cim_obj("ConcentricNeutralCableInfo", name=self.graph.value(subject=s, predicate=self.cim_ns["IdentifiedObject.name"]))

                for p, o in self.graph.predicate_objects(subject=s):
                    cableinfo_triples_to_remove.add((s, p, o))
                    if not p.startswith(str(self.cyme_ns)):
                        self.add_triple(node, p.split("#", maxsplit=2)[-1], o)

                neutral_radius = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.wireDiameter"]).value) / 2
                neutral_gmr = neutral_radius * 0.7788
                rdc20 = material_resistivity.get(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.material"]).split("#")[-1], 2e-8) / (math.pi * neutral_radius**2)
                neutral_count = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.numberOfWires"]).value)
                diameter_over_neutral = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.outerDiameter"]).value)

                self.add_triple(node, "ConcentricNeutralCableInfo.nuetralStrandRadius", neutral_radius)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStandGmr", neutral_gmr)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRDC20", rdc20)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandCount", neutral_count)
                self.add_triple(node, "ConcentricNeutralCableInfo.diameterOverNeutral", diameter_over_neutral)

                cableinfo_to_replace.add((s, node))
                cccn_to_prune.add(cccn_ref)
            else:
                for p, o in self.graph.predicate_objects(subject=s):
                    if p.startswith(str(self.cyme_ns)):
                        cableinfo_triples_to_remove.add((s, p, o))

        for old_o, new_o in cableinfo_to_replace:
            for s, p, _ in list(self.graph.triples((None, None, old_o))):
                self.graph.add((s, p, new_o))
                self.graph.remove((s, p, old_o))

        for triple in cableinfo_triples_to_remove:
            self.graph.remove(triple)

        for cccn in cccn_to_prune:
            for triple in self.graph.triples((cccn, None, None)):
                self.graph.remove(triple)

    def convert_cyme_cable_construction(self):
        # nothing to do
        pass

    def convert_cyme_customer_class(self):
        # nothing to do
        pass

    def convert_cyme_customer_load(self):
        # nothing to do
        pass

    def convert_cyme_customer_load_value(self):
        # nothing to do
        pass

    def convert_cyme_structure(self):
        # nothing to do
        pass

    def save(self, path: pathlib.PosixPath):
        self.graph.serialize(path, max_depth=1, format="pretty-xml", base="")


if __name__ == "__main__":
    # TODO: need synthetic feeder exported from CYME for example
    pass
