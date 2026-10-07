import pathlib
import re

from uuid import uuid4

import networkx as nx

from rdflib.namespace import Namespace, NamespaceManager
from rdflib import Graph, RDF
from rdflib.term import URIRef, Literal
from rdflib.extras.external_graph_libs import rdflib_to_networkx_multidigraph

from ravens.data import _DEFAULT_CIM_NAMESPACE


class RDFGraph(object):
    def __init__(self, profile_path: str | pathlib.Path | None = None, cim_namespace: str = _DEFAULT_CIM_NAMESPACE, public_id: str = "#", uuid_format=None):
        if uuid_format is not None:
            self.uuid_format = uuid_format
        else:
            self.uuid_format = lambda x: x

        self.graph = Graph()

        self.public_id = public_id

        if profile_path is not None:
            self.graph = self.graph.parse(profile_path, format="application/rdf+xml", publicID=self.public_id)

        nm = NamespaceManager(self.graph, bind_namespaces="none")
        self.cim = Namespace(cim_namespace + "#")
        nm.bind("rdf", RDF)
        nm.bind("cim", self.cim, override=True)
        self.graph.namespace_manager = nm

    @staticmethod
    def _transform_to_cyme_uri(match):
        """
        Transform URIs to CYME format: #uuid -> #_UUID
        Match patterns like rdf:about="#uuid" or rdf:resource="#uuid"
        """
        prefix = match.group(1)  # rdf:about=" or rdf:resource="
        hash_sign = match.group(2)  # # or empty
        uuid = match.group(3)  # the UUID

        # Transform: remove leading underscore if present, uppercase, add underscore
        uuid_clean = uuid.lstrip('_')
        uuid_transformed = f"_{uuid_clean.upper()}"

        return f'{prefix}{hash_sign}{uuid_transformed}"'


    def mRID(self) -> str:
        return self.uuid_format(str(uuid4()))

    def build_cim_obj(self, rdf_type: str, mrid: str | None = None, name: str | None = None, skip_mrid: bool = False) -> URIRef:
        if mrid is None:
            mrid = self.mRID()

        # URIRef always includes public_id prefix
        node = URIRef(self.public_id + mrid)

        self.graph.add((node, RDF.type, self.cim[rdf_type]))
        if not skip_mrid:
            # mRID property value never includes public_id prefix
            self.graph.add((node, self.cim["IdentifiedObject.mRID"], Literal(mrid)))
        if name is not None:
            self.graph.add((node, self.cim["IdentifiedObject.name"], Literal(name)))

        return node

    def add_triple(self, subject: URIRef, predicate: str, obj):
        if isinstance(obj, bool):
            self.graph.add((subject, self.cim[predicate], Literal(str(obj).lower())))
        elif isinstance(obj, URIRef):
            if any(str(obj).startswith(str(ns)) for n, ns in self.graph.namespaces()):
                self.graph.add((subject, self.cim[predicate], URIRef(obj)))
            else:
                self.graph.add((subject, self.cim[predicate], URIRef(self.public_id + str(obj))))
        else:
            self.graph.add((subject, self.cim[predicate], Literal(str(obj))))

    def export_rdf_graphml(self, file_path: str | pathlib.Path):
        G = rdflib_to_networkx_multidigraph(self.graph)

        for i, e in enumerate(G.edges(keys=True)):
            G.edges[e].update({"label": str(e[-1]), "id": str(i)})
        for n in G.nodes:
            G.nodes[n].update({"label": str(n)})

        nx.write_graphml(G, file_path, named_key_ids=True, edge_id_from_attribute="id")

    def get(self, subject, predicate, default=None):
        _v = self.graph.value(subject=subject, predicate=predicate)
        if _v is None:
            return default

        return _v

    def get_name(self, subject):
        return self.get(subject, self.cim["IdentifiedObject.name"], str(subject))

    def save(self, path: pathlib.Path | str, make_cyme_compatible: bool = False) -> None:
        rdfxml = self.graph.serialize(max_depth=1, format="pretty-xml")

        if make_cyme_compatible:
            # Transform both rdf:about and rdf:resource attributes
            rdfxml = re.sub(
                r'(rdf:(?:about|resource)=")(#?)([a-fA-F0-9_-]+)"',
                self._transform_to_cyme_uri,
                rdfxml
            )

            # Change rdf:about to rdf:ID
            rdfxml = rdfxml.replace("rdf:about", "rdf:ID")

        with open(path, "w") as f:
            f.write(rdfxml)
