import math
import pathlib

from ast import literal_eval
from uuid import uuid4

from rdflib.namespace import Namespace, RDF
from rdflib.term import URIRef, Literal
from rdflib import Graph

from ravens.logging import logger
from ravens.data import _DEFAULT_CIM_NAMESPACE


# ohm.m @ 20C
material_resistivity = {"CYMEConductorMaterial.copper": 1.68e-8, "CYMEConductorMaterial.aluminum": 2.82e-8}


class CymeConverter:
    def __init__(self, cim_profile_path: pathlib.Path | str, cim_namespace: str = _DEFAULT_CIM_NAMESPACE, prune_remaining_cyme: bool = False):
        g = Graph()
        self.graph = g.parse(cim_profile_path, format="application/rdf+xml", publicID="#")

        self.cyme_ns = Namespace("http://www.cyme.com/CIM/1.0.2" + "#")

        self.cim_ns = Namespace(cim_namespace + "#")

        self.graph.bind("rdf", RDF)
        self.graph.bind("cim", self.cim_ns, override=True)
        self.graph.bind("cyme", self.cyme_ns, override=True)

        # TODO: other load models
        self.load_response_values = {"CYMELoadFormat.kw_kvar": {"name": "Constant kVA", "values": {"pConstantPower": 100.0, "qConstantPower": 100.0}}}
        self.load_response_uris = {}

        self.convert_cyme_cable_concentric_neutrals()
        self.convert_cyme_customer_class()
        self.convert_cyme_customer_load_value()

        self.fix_EnergyConsumerPhase()
        self.fix_WireInfo()

        if prune_remaining_cyme:
            self.remove_cyme_objects()

    def build_cim_obj(self, rdf_type: str, mrid: str | None = None, name: str | None = None, skip_mrid: bool = False) -> URIRef:
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
        for s, o in self.graph.subject_objects(predicate=RDF.type):
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
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim_ns["CableInfo"]):
            cccn_ref = self.graph.value(subject=s, predicate=self.cyme_ns["CYMECableConstruction.CableConcentricNeutrals"])
            if cccn_ref is not None:
                node = self.build_cim_obj("ConcentricNeutralCableInfo", name=self.graph.value(subject=s, predicate=self.cim_ns["IdentifiedObject.name"]))

                for p, o in self.graph.predicate_objects(subject=s):
                    cableinfo_triples_to_remove.add((s, p, o))
                    if not p.startswith(str(self.cyme_ns)) and p != RDF.type:
                        self.add_triple(node, p.split("#", maxsplit=2)[-1], o)

                neutral_radius = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.wireDiameter"]).value) / 2
                neutral_gmr = neutral_radius * 0.7788
                rdc20 = material_resistivity.get(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.material"]).split("#")[-1], 2e-8) / (math.pi * neutral_radius**2)
                neutral_count = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.numberOfWires"]).value)
                diameter_over_neutral = literal_eval(self.graph.value(subject=cccn_ref, predicate=self.cyme_ns["CYMECableConcentricNeutrals.outerDiameter"]).value)

                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandRadius", neutral_radius)
                self.add_triple(node, "ConcentricNeutralCableInfo.neutralStrandGmr", neutral_gmr)
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
        to_prune = set()
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme_ns["CYMECustomerClass"]):
            to_prune.add(s)
            node = self.build_cim_obj("LoadGroup", name=str(self.graph.value(subject=s, predicate=self.cim_ns["IdentifiedObject.name"])))
            for _s in self.graph.subjects(predicate=self.cyme_ns["CYMECustomerLoad.CustomerClass"], object=s):
                assert self.graph.value(subject=_s, predicate=RDF.type) == self.cyme_ns["CYMECustomerLoad"]
                ec_uri = self.graph.value(subject=_s, predicate=self.cyme_ns["CYMECustomerLoad.EnergyConsumer"])
                self.add_triple(ec_uri, "EnergyConsumer.LoadGroup", node)

    def convert_cyme_customer_load(self):
        # nothing to do
        pass

    def convert_cyme_customer_load_value(self):
        sub_to_prune = set()
        for s in self.graph.subjects(predicate=RDF.type, object=self.cyme_ns["CYMECustomerLoadValue"]):
            cust_load = self.graph.value(subject=s, predicate=self.cyme_ns["CYMECustomerLoadValue.CustomerLoad"])
            ec_uri = self.graph.value(subject=cust_load, predicate=self.cyme_ns["CYMECustomerLoad.EnergyConsumer"])

            for k in ["p", "q"]:
                v = self.graph.value(subject=s, predicate=self.cyme_ns[f"CYMECustomerLoadValue.{k}"])
                if v is not None:
                    self.add_triple(ec_uri, f"EnergyConsumer.{k}", v)

            self.add_LoadResponseCharacteristic(ec_uri, self.graph.value(subject=s, predicate=self.cyme_ns["CYMECustomerLoadValue.loadFormat"]).split("#")[-1])

            sub_to_prune.add(s)

        to_remove = set()
        for s in sub_to_prune:
            for triple in self.graph.triples((s, None, None)):
                to_remove.add(triple)

        for triple in to_remove:
            self.graph.remove(triple)

    def add_LoadResponseCharacteristic(self, subject_uri: URIRef, cyme_load_format: str):
        lrc_values = self.load_response_values.get(cyme_load_format, None)
        if lrc_values is not None:
            if cyme_load_format not in self.load_response_uris:
                node = self.build_cim_obj("LoadResponseCharacteristic", name=lrc_values["name"])
                for k, v in lrc_values["values"].items():
                    self.add_triple(node, f"LoadResponseCharacteristic.{k}", v)

                self.load_response_uris[cyme_load_format] = node

            self.add_triple(subject_uri, "EnergyConsumer.LoadResponse", self.load_response_uris[cyme_load_format])

    def fix_EnergyConsumerPhase(self):
        triple_to_prune = set()
        for s in self.graph.subjects(predicate=RDF.type, object=self.cim_ns["EnergyConsumerPhase"]):
            for k in ["p", "q"]:
                v = self.graph.value(subject=s, predicate=self.cim_ns[f"EnergyConsumerPhase.{k}Fixed"])
                if v is not None:
                    self.add_triple(s, f"EnergyConsumerPhase.{k}", v)
                    triple_to_prune.add((s, self.cim_ns[f"EnergyConsumerPhase.{k}Fixed"], v))

        for triple in triple_to_prune:
            self.graph.remove(triple)

    def fix_WireInfo(self):
        for wi in ["WireInfo", "CableInfo", "OverheadWireInfo", "ConcentricNeutralCableInfo", "TapeShieldCableInfo"]:
            for s in self.graph.subjects(predicate=RDF.type, object=self.cim_ns[wi]):
                radius = self.graph.value(subject=s, predicate=self.cim_ns["WireInfo.radius"])
                material = self.graph.value(subject=s, predicate=self.cim_ns["WireInfo.material"])

                if self.graph.value(subject=s, predicate=self.cim_ns["WireInfo.gmr"]) is None:
                    if radius is not None:
                        self.add_triple(s, "WireInfo.gmr", literal_eval(radius.value) * 0.7788)

                if self.graph.value(subject=s, predicate=self.cim_ns["WireInfo.rDC20"]) is None:
                    if radius is not None and material is not None:
                        self.add_triple(s, "WireInfo.rDC20", material_resistivity.get(str(material).split("#")[-1], 2e-8) / (math.pi * literal_eval(radius.value) ** 2))

    def convert_cyme_structure(self):
        # nothing to do
        pass

    def save(self, path: pathlib.PosixPath | str):
        self.graph.serialize(path, max_depth=1, format="pretty-xml", base="")


if __name__ == "__main__":
    # TODO: need synthetic feeder exported from CYME for example
    pass
