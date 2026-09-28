import gc
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import test_policy_exposure as fixture
from ledgerd.core import Ledger, ProjectionLagError
from scripts.independent_verify import verify_store

HERE = Path(__file__).resolve().parents[1]


class AuthorizationInterleavings(unittest.TestCase):
    setUp = fixture.PolicyExposureTests.setUp
    tearDown = fixture.PolicyExposureTests.tearDown

    def test_policy_changes_before_queued_protected_open(self):
        ledger = self.ledger
        auth, _ = ledger.authorize_stage("acceptance.R1", "STAGE-A", "agent-A", self.expiry, "authorize-race")
        queued = threading.Event()
        def open_old():
            queued.set()
            return ledger.open_panel("P-1", "terminal", "acceptance.R1", "STAGE-A", "agent-A", self.token, auth, "raced-open")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with ledger.lock:
                future = pool.submit(open_old)
                self.assertTrue(queued.wait(5))
                ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": "STAGE-A", "version": "v2",
                    "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "policy-race-v2")
            self.assertIsNone(future.result(timeout=10)[0])
        self.assertEqual(ledger.exposure.report("P-1")["count"], 0)

    def test_new_truth_contact_invalidates_live_consumption(self):
        ledger = self.ledger
        policy, _ = ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": "STAGE-A", "version": "v2",
            "requires": {"actor": "AUTHORIZED"}, "forbids": {"truth_label_contact": True}}, "truth-policy")
        for action in ("authorize_stage", "open_panel"):
            ledger.issue_grant("new-" + action, "agent-A", action, "acceptance.R1", "STAGE-A", policy, self.expiry, "grant-new-" + action)
        auth, _ = ledger.authorize_stage("acceptance.R1", "STAGE-A", "agent-A", self.expiry, "truth-auth")
        self.assertTrue(ledger.authorization_valid(auth, "agent-A", "acceptance.R1", "STAGE-A"))
        ledger.record_contact("acceptance.R1", "STAGE-A", "TRUTH_LABEL", "fixture-only", "agent-A", "truth-contact")
        self.assertFalse(ledger.authorization_valid(auth, "agent-A", "acceptance.R1", "STAGE-A"))
        opened, _, _ = ledger.open_panel("P-1", "terminal", "acceptance.R1", "STAGE-A", "agent-A", self.token, auth, "post-truth-open")
        self.assertIsNone(opened)


class IngestionInterleavings(unittest.TestCase):
    def test_duplicate_keys_projection_lag_and_reads(self):
        with tempfile.TemporaryDirectory(prefix="kammi-races-") as directory:
            ledger = Ledger(Path(directory))
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(lambda _: ledger.register_bytes(b"duplicate", kind="source", actor="agent", request_id="same-key"), range(24)))
                self.assertEqual(len(set(responses)), 1)
                self.assertEqual(len(ledger.journal.events), 1)
                with patch.object(ledger.graph, "apply", side_effect=RuntimeError("injected projection lag")):
                    with self.assertRaises(ProjectionLagError):
                        ledger.create_run("lag-run", "library", "agent", "lag-key")
                self.assertEqual(ledger.status()["projection_lag"], 1)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    snapshots = list(pool.map(lambda _: ledger.status(), range(16)))
                self.assertTrue(all(s["projection_lag"] == 1 for s in snapshots))
                self.assertIn("lag-run", ledger.runs)
                ledger.create_run("lag-run", "library", "agent", "lag-key")
                self.assertEqual(ledger.status()["projection_lag"], 0)
                self.assertEqual(len(ledger.journal.events), 2)
                with self.assertRaises(ValueError):
                    ledger.register_bytes(b"conflicting bytes", kind="source", actor="agent", request_id="same-key")
            finally:
                ledger.close()
                gc.collect()

    def test_memory_write_search_during_custody_ingestion(self):
        with tempfile.TemporaryDirectory(prefix="kammi-mixed-race-") as directory:
            ledger = Ledger(Path(directory), embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
            try:
                evidence, _ = ledger.register_bytes(b"grounding", kind="receipt", actor="audit", request_id="evidence")
                ledger.memory.record(kind="OBSERVED", scope="library", text="Concurrent custody baseline",
                    actor="agent", custody_refs=[evidence], tags=[], request_id="baseline")
                def work(i):
                    if i % 3 == 0:
                        return ledger.register_bytes(str(i).encode(), kind="source", actor="agent", request_id="ingest-" + str(i))
                    if i % 3 == 1:
                        return ledger.memory.record(kind="OBSERVED", scope="library", text="Concurrent custody record " + str(i),
                            actor="agent", custody_refs=[evidence], tags=[], request_id="memory-" + str(i))
                    return ledger.memory.search("custody", scope="library", actor="agent", mode="hybrid", request_id="search-" + str(i))
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(work, range(60)))
                self.assertEqual(len(results), 60)
                self.assertEqual(len(ledger.memory.records), 21)
                self.assertEqual(len(ledger.artifacts), 21)
                self.assertEqual(verify_store(ledger.root)["status"], "PASS")
                self.assertEqual(ledger.status()["projection_lag"], 0)
            finally:
                ledger.close()
                gc.collect()
