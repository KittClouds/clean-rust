"""Separate, disposable contextual memory projection with native indexes."""
from __future__ import annotations

from pathlib import Path
import os
import re
import heapq
from collections import Counter

from .embedding import unpack_vector


class MemoryGraph:
    def __init__(self, root: Path, database) -> None:
        import ladybug as lb

        # The Library daemon owns one Ladybug Database object. Memory has its
        # own journal and tables, but shares the disposable physical projection.
        self.db = database
        self.conn = lb.Connection(self.db)
        for extension in ("FTS", "VECTOR"):
            directory = os.environ.get("KAMMI_EXTENSION_DIR", str(Path(__file__).resolve().parents[1] / "vendor/runtime-v1/extensions"))
            if directory:
                path = (Path(directory) / extension.lower() / ("lib" + extension.lower() + ".lbug_extension")).resolve()
                self.conn.execute("LOAD EXTENSION '" + path.as_posix().replace("'", "\\'") + "'")
            else:
                self.conn.execute("LOAD " + extension)
        for ddl in (
            "CREATE NODE TABLE IF NOT EXISTS Memory(id STRING PRIMARY KEY, text STRING, scope STRING, kind STRING, embedding FLOAT[384])",
            "CREATE NODE TABLE IF NOT EXISTS CustodyRef(id STRING PRIMARY KEY)",
            "CREATE NODE TABLE IF NOT EXISTS Entity(id STRING PRIMARY KEY)",
            "CREATE REL TABLE IF NOT EXISTS Cites(FROM Memory TO CustodyRef)",
            "CREATE REL TABLE IF NOT EXISTS About(FROM Memory TO Entity)",
            "CREATE REL TABLE IF NOT EXISTS Supersedes(FROM Memory TO Memory)",
        ):
            self.conn.execute(ddl)
        indexes = {row[1] for row in self.conn.execute("CALL SHOW_INDEXES() RETURN *")}
        self.fts_exists = "memory_text" in indexes
        self.vector_exists = "memory_vector" in indexes
        self.fts_dirty = True
        self.record_ids = set()
        self.delta_ids = set()
        self.delta_terms = {}
        self.indexed_count = 0
        self.fts_rebuilds = 0

    def add(self, record: dict, vector: bytes) -> None:
        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute(
                "MERGE (m:Memory {id:$id}) SET m.text=$text, m.scope=$scope, m.kind=$kind, m.embedding=$embedding",
                {"id": record["memory_id"], "text": record["text"],
                 "scope": record["scope"], "kind": record["kind"],
                 "embedding": unpack_vector(vector)},
            )
            for ref in record["custody_refs"]:
                self.conn.execute(
                    "MATCH (m:Memory {id:$memory}) MERGE (r:CustodyRef {id:$ref}) MERGE (m)-[:Cites]->(r)",
                    {"memory": record["memory_id"], "ref": ref},
                )
            for tag in record["tags"]:
                self.conn.execute(
                    "MATCH (m:Memory {id:$memory}) MERGE (t:Entity {id:$tag}) MERGE (m)-[:About]->(t)",
                    {"memory": record["memory_id"], "tag": tag},
                )
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.fts_dirty = True
        identity = record["memory_id"]
        self.record_ids.add(identity)
        self.delta_ids.add(identity)
        for term in set(re.findall(r"\w+", record["text"].casefold())):
            self.delta_terms.setdefault(term, set()).add(identity)

    def supersede(self, new_id: str, old_id: str) -> None:
        self.conn.execute(
            "MATCH (a:Memory {id:$new}), (b:Memory {id:$old}) MERGE (a)-[:Supersedes]->(b)",
            {"new": new_id, "old": old_id},
        )

    def indexes(self, *, lexical=False) -> None:
        # Rebuild FTS on doubling boundaries, not every write/search pair.
        # The incremental postings overlay exposes recent writes immediately.
        if lexical and self.fts_dirty and (not self.fts_exists or len(self.delta_ids) >= max(1, self.indexed_count)):
            if self.fts_exists:
                self.conn.execute("CALL DROP_FTS_INDEX('Memory', 'memory_text')")
            self.conn.execute("CALL CREATE_FTS_INDEX('Memory', 'memory_text', ['text'], stemmer := 'none')")
            self.fts_exists, self.fts_dirty = True, False
            self.indexed_count = len(self.record_ids)
            self.delta_ids.clear()
            self.delta_terms.clear()
            self.fts_rebuilds += 1
        if not self.vector_exists:
            self.conn.execute("CALL CREATE_VECTOR_INDEX('Memory', 'memory_vector', 'embedding', metric := 'cosine')")
            self.vector_exists = True

    def fts(self, query: str, count: int) -> list[tuple[str, float]]:
        self.indexes(lexical=True)
        base = [(str(r[0]), float(r[1])) for r in self.conn.execute(
            "CALL QUERY_FTS_INDEX('Memory', 'memory_text', $query, TOP := $count) RETURN node.id, score ORDER BY score DESC, node.id",
            {"query": query, "count": count},
        )]
        scores = Counter()
        for term in set(re.findall(r"\w+", query.casefold())):
            scores.update(self.delta_terms.get(term, ()))
        recent = heapq.nsmallest(count, scores.items(), key=lambda row: (-row[1], row[0]))
        # Scores from recent postings are lexical term overlap, while the frozen
        # native index uses BM25. They are retrieval ranks, never truth labels.
        merged = dict(base)
        for identity, score in recent:
            merged[identity] = max(float(score), merged.get(identity, 0.0))
        return heapq.nsmallest(count, merged.items(), key=lambda row: (-row[1], row[0]))

    def vector(self, vector: bytes, count: int) -> list[tuple[str, float]]:
        self.indexes()
        return [(str(r[0]), 1.0 - float(r[1])) for r in self.conn.execute(
            "CALL QUERY_VECTOR_INDEX('Memory', 'memory_vector', $vector, $count) RETURN node.id, distance ORDER BY distance, node.id",
            {"vector": unpack_vector(vector), "count": count},
        )]

    def neighbors(self, memory_id: str) -> list[str]:
        rows = self.conn.execute(
            "MATCH (a:Memory {id:$id})-[:About]->(t:Entity)<-[:About]-(b:Memory) WHERE b.id<>$id RETURN DISTINCT b.id",
            {"id": memory_id},
        )
        ids = {str(row[0]) for row in rows}
        for row in self.conn.execute(
            "MATCH (a:Memory {id:$id})-[:Cites]->(t:CustodyRef)<-[:Cites]-(b:Memory) WHERE b.id<>$id RETURN DISTINCT b.id",
            {"id": memory_id},
        ):
            ids.add(str(row[0]))
        return sorted(ids)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        self.db = None
