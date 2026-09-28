"""Detect projection-only mutation by independent authority plus fresh replay."""
from pathlib import Path
import tempfile
import gc

from ledgerd.backup import backup, restore
from ledgerd.core import Ledger
from scripts.independent_verify import verify_store


def snapshot(ledger):
    conn = ledger.graph.conn
    queries = {
        "artifacts": "MATCH (n:Artifact) RETURN n.id, n.byte_count ORDER BY n.id",
        "events": "MATCH (n:Event) RETURN n.id, n.seq, n.typ, n.payload, n.prev ORDER BY n.seq",
        "seals": "MATCH (n:Seal) RETURN n.root, n.payload ORDER BY n.root",
        "runs": "MATCH (n:Run) RETURN n.id, n.lab ORDER BY n.id",
        "facts": "MATCH (n:CustodyFact) RETURN n.id, n.run_id, n.kind, n.subject, n.target, n.value, n.evidence_id, n.scope ORDER BY n.id",
        "entities": "MATCH (n:Entity) RETURN n.id, n.kind, n.payload ORDER BY n.id",
        "links": "MATCH (a:Entity)-[r:Link]->(b:Entity) RETURN a.id, r.kind, b.id ORDER BY a.id, r.kind, b.id",
    }
    result = {key: list(conn.execute(query)) for key, query in queries.items()}
    if ledger.memory is not None:
        memory_conn = ledger.memory.graph.conn
        for name, query in {
            "memory_rows": "MATCH (n:Memory) RETURN n.id, n.text, n.scope, n.kind, n.embedding ORDER BY n.id",
            "memory_refs": "MATCH (a:Memory)-[:Cites]->(b:CustodyRef) RETURN a.id, b.id ORDER BY a.id, b.id",
            "memory_tags": "MATCH (a:Memory)-[:About]->(b:Entity) RETURN a.id, b.id ORDER BY a.id, b.id",
            "memory_supersession": "MATCH (a:Memory)-[:Supersedes]->(b:Memory) RETURN a.id, b.id ORDER BY a.id, b.id",
        }.items():
            result[name] = list(memory_conn.execute(query))
    return result


def compare_rebuild(ledger):
    independent = verify_store(ledger.root)
    with tempfile.TemporaryDirectory(prefix="kammi-projection-audit-") as directory:
        root = Path(directory)
        backup(ledger, root / "backup")
        restore(root / "backup", root / "rebuild")
        fresh = Ledger(root / "rebuild")
        try:
            if ledger.memory is not None:
                from ledgerd.embedding import Embedder
                from ledgerd.memory import MemoryService
                fresh.memory = MemoryService(fresh.root, fresh.cas, ledger.memory.embedder,
                                              fresh.valid_custody_ref, fresh.graph.db, fresh.lock)
            expected, actual = snapshot(fresh), snapshot(ledger)
            if actual != expected:
                raise ValueError("projection content differs from authority replay")
            return {"status": "PASS", "head": ledger.journal.head,
                    "independent": independent, "tables_compared": sorted(actual)}
        finally:
            fresh.close()
            gc.collect()
