"""X0: the smallest generic graph kernel for System 1.5 — typed nodes, typed directed weighted edges, provenance, source and disposition.

No learning and no BANK knowledge here. Node kinds are ENTITY, STATE, ACTION, GOAL, EVIDENCE, REQUIREMENT; relations are REQUIRES, SUPPORTS, CONTRADICTS, APPLICABLE_TO, CAUSES, ACHIEVES.
Every edge says who proposed it (`source`: a rule, an observer, an oracle), with what confidence (`weight`, 0..1), and why (`provenance`), and can carry a `disposition` (KEEP / DROP / DEFER) so that heterogeneous proposals can be triaged through one interface.
"""
from __future__ import annotations

import hashlib
import json

NODE_KINDS = ("ENTITY", "STATE", "ACTION", "GOAL", "EVIDENCE", "REQUIREMENT")
RELATIONS = ("REQUIRES", "SUPPORTS", "CONTRADICTS", "APPLICABLE_TO", "CAUSES", "ACHIEVES")
DISPOSITIONS = (None, "KEEP", "DROP", "DEFER")


class GraphError(ValueError):
    pass


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._out: dict[str, list[int]] = {}
        self._in: dict[str, list[int]] = {}

    def add_node(self, node_id: str, kind: str, **attrs) -> str:
        if kind not in NODE_KINDS:
            raise GraphError(f"unknown node kind {kind!r}")
        if node_id in self.nodes:
            if self.nodes[node_id]["kind"] != kind:
                raise GraphError(f"node {node_id!r} already exists as {self.nodes[node_id]['kind']}")
            return node_id
        self.nodes[node_id] = {"kind": kind, **attrs}
        return node_id

    def add_edge(self, src: str, dst: str, rel: str, weight: float = 1.0, source: str = "", provenance: str = "", disposition=None, **attrs) -> int:
        if rel not in RELATIONS:
            raise GraphError(f"unknown relation {rel!r}")
        if src not in self.nodes or dst not in self.nodes:
            raise GraphError(f"edge {src!r} -> {dst!r} names a missing node")
        if not 0.0 <= weight <= 1.0:
            raise GraphError("edge weight must be within [0, 1]")
        if disposition not in DISPOSITIONS:
            raise GraphError(f"unknown disposition {disposition!r}")
        index = len(self.edges)
        self.edges.append({"src": src, "dst": dst, "rel": rel, "weight": weight, "source": source, "provenance": provenance, "disposition": disposition, **attrs})
        self._out.setdefault(src, []).append(index)
        self._in.setdefault(dst, []).append(index)
        return index

    def out(self, node_id: str, rel: str | None = None) -> list[dict]:
        return [self.edges[i] for i in self._out.get(node_id, []) if rel is None or self.edges[i]["rel"] == rel]

    def into(self, node_id: str, rel: str | None = None) -> list[dict]:
        return [self.edges[i] for i in self._in.get(node_id, []) if rel is None or self.edges[i]["rel"] == rel]

    def of_kind(self, kind: str) -> list[str]:
        return [n for n, a in self.nodes.items() if a["kind"] == kind]

    def canonical(self) -> str:
        """Deterministic text form: sorted nodes and edges, no floats beyond their shortest repr."""
        nodes = [[n, self.nodes[n]] for n in sorted(self.nodes)]
        edges = sorted(json.dumps(e, sort_keys=True, separators=(",", ":")) for e in self.edges)
        return json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def counts(self) -> dict:
        kinds, rels = {}, {}
        for a in self.nodes.values():
            kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
        for e in self.edges:
            rels[e["rel"]] = rels.get(e["rel"], 0) + 1
        return {"nodes": kinds, "edges": rels}
