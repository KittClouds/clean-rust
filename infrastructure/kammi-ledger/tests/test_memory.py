from __future__ import annotations

import gc
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ledgerd.api import create_app
from ledgerd.core import Ledger

CACHE = Path(__file__).resolve().parents[1] / ".kammi-dev" / "embedding-cache"


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kammi-memory-test-"))
        self.ledger = Ledger(self.root, embedding_cache=CACHE)
        self.token = "memory-agent-credential"
        self.ledger.register_actor("memory-agent", "agent", "library",
                                   hashlib.sha256(self.token.encode()).hexdigest(), "actor")
        self.evidence, _ = self.ledger.register_bytes(
            b"E4 fixture: WDDM graphics rows are not CUDA compute leases.",
            kind="receipt", actor="admin", request_id="evidence")

    def tearDown(self):
        self.ledger.close()
        gc.collect()
        shutil.rmtree(self.root)

    def record(self, kind, text, request, refs=None, tags=None):
        return self.ledger.memory.record(kind=kind, text=text, scope="library",
                                         actor="memory-agent", request_id=request,
                                         custody_refs=refs or [], tags=tags or ["gpu"])[0]

    def test_trust_search_supersession_trace_and_rebuild(self):
        memory = self.ledger.memory
        failure = self.record("FAILURE_MODE",
                              "A desktop graphics process was mistaken for an active accelerator training job. WDDM CUDA ambiguity.",
                              "failure", [self.evidence])
        procedure = self.record("PROCEDURE", "Classify GPU owners by compute workload and fencing lease; ignore display clients.", "procedure", [self.evidence])
        hypothesis = self.record("HYPOTHESIS", "WDDM CUDA always means a training process.", "hypothesis")
        exact = memory.search("WDDM", scope="library", actor="memory-agent",
                              request_id="fts", mode="fts", grounded_only=True)
        self.assertEqual(exact["results"][0]["memory"]["memory_id"], failure)
        semantic = memory.search("video card occupation incorrectly assigned to a neural network learner",
                                 scope="library", actor="memory-agent", request_id="vector",
                                 mode="vector", grounded_only=True)
        self.assertIn(failure, [r["memory"]["memory_id"] for r in semantic["results"]])
        neighbors = memory.search("", scope="library", actor="memory-agent", request_id="graph",
                                  mode="graph", seed_memory=failure, exclude_kinds=["HYPOTHESIS"])
        self.assertIn(procedure, [r["memory"]["memory_id"] for r in neighbors["results"]])
        memory.supersede(hypothesis, procedure, "memory-agent", "supersede")
        self.assertEqual(memory.get(hypothesis)["superseded_by"], [procedure])
        self.assertTrue(memory.trace(failure)["references"][0]["verified"])
        with self.assertRaises(ValueError):
            self.record("OBSERVED", "unsupported observation", "unsupported")
        head, count = memory.journal.head, len(memory.records)
        custody_head = self.ledger.journal.head
        self.ledger.close()
        gc.collect()
        db = self.root / "custody.lbdb"
        if db.is_dir():
            shutil.rmtree(db)
        else:
            db.unlink()
        self.ledger = Ledger(self.root, embedding_cache=CACHE)
        self.assertEqual(self.ledger.memory.journal.head, head)
        self.assertEqual(len(self.ledger.memory.records), count)
        self.assertEqual(self.ledger.journal.head, custody_head)
        self.assertEqual(self.ledger.memory.get(hypothesis)["superseded_by"], [procedure])
        rebuilt = self.ledger.memory.search("WDDM", scope="library", actor="memory-agent",
                                           request_id="rebuilt", mode="fts", grounded_only=True)
        self.assertEqual(rebuilt["results"][0]["memory"]["memory_id"], failure)

    def test_http_actor_scope_and_idempotence(self):
        with TestClient(create_app(self.ledger, "admin-token")) as client:
            headers = {"Authorization": "Bearer " + self.token}
            body = {"kind": "OBSERVED", "scope": "library", "text": "Exact evidence observation",
                    "custody_refs": [self.evidence], "tags": ["evidence"],
                    "actor_id": "memory-agent", "request_id": "http-record"}
            first = client.post("/v1/memory", json=body, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), client.post("/v1/memory", json=body, headers=headers).json())
            bad = client.post("/v1/memory", json={**body, "scope": "JEV"}, headers=headers)
            self.assertEqual(bad.status_code, 403)
            identity = first.json()["memory_id"]
            trace = client.get(f"/v1/memory/{identity}/trace?actor_id=memory-agent", headers=headers)
            self.assertTrue(trace.json()["references"][0]["verified"])

    def test_incremental_fts_doubling_and_committed_memory_retry(self):
        memory = self.ledger.memory
        for i in range(17):
            # Native FTS tokenization can normalize digits; use distinct words
            # so this tests immediate lexical visibility rather than rank ties.
            needle = "IncrementalNeedle" + chr(ord("a") + i)
            identity = self.record("PROCEDURE", needle, "incremental-" + str(i))
            result = memory.search(needle, scope="library", actor="memory-agent",
                request_id="incremental-search-" + str(i), mode="fts", limit=1)
            self.assertEqual(result["results"][0]["memory"]["memory_id"], identity)
        self.assertEqual(memory.graph.fts_rebuilds, 5)
        before = memory.graph.fts_rebuilds
        self.record("PROCEDURE", "VectorOnlyRecord", "vector-only-record")
        memory.search("VectorOnlyRecord", scope="library", actor="memory-agent", request_id="vector-only", mode="vector")
        self.assertEqual(memory.graph.fts_rebuilds, before)
        with patch.object(memory.graph, "add", side_effect=RuntimeError("injected memory projection fault")):
            with self.assertRaises(RuntimeError):
                self.record("PROCEDURE", "RepairNeedle", "repair-committed-memory")
        events = len(memory.journal.events)
        identity = self.record("PROCEDURE", "RepairNeedle", "repair-committed-memory")
        self.assertEqual(len(memory.journal.events), events)
        self.assertIn(identity, memory.records)
