from __future__ import annotations

import gc
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from ledgerd.api import create_app
from ledgerd.core import Ledger
from ledgerd.identity import canonical, strict_json
from ledgerd.journal import EventJournal
from ledgerd.writer import WriterBusy


class IdentityTests(unittest.TestCase):
    def test_strict_json_rejects_ambiguous_values(self) -> None:
        with self.assertRaises(ValueError):
            strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            canonical({"n": 1 << 53})
        with self.assertRaises(ValueError):
            strict_json(b'{"n":1e-400}')
        self.assertEqual(canonical({"b": 2, "a": 1}), b'{"a":1,"b":2}')


class CustodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kammi-custody-"))
        self.ledger = Ledger(self.root)

    def tearDown(self) -> None:
        self.ledger.close()
        del self.ledger
        gc.collect()
        shutil.rmtree(self.root)

    def test_merkle_lineage_and_tamper(self) -> None:
        first, _ = self.ledger.register_bytes(
            b"first", kind="fixture", actor="chief", request_id="r1"
        )
        second, _ = self.ledger.register_bytes(
            b"second", kind="fixture", actor="chief", request_id="r2"
        )
        parent, _ = self.ledger.create_seal([first], [], "chief", "r3")
        child, _ = self.ledger.create_seal([second], [parent], "chief", "r4")
        self.assertEqual(self.ledger.verify_seal(child), sorted([first, second]))
        child_payload = strict_json(
            self.ledger.cas.get(self.ledger.seal_artifacts[child])
        )
        self.assertEqual(child_payload["direct_members"], [second])
        self.assertEqual(child_payload["parents"], [parent])
        self.assertEqual(self.ledger.status()["projection_seq"], 4)
        self.ledger.cas.path_for(first).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "corrupt"):
            self.ledger.verify_seal(child)

    def test_replay_committed_event_after_projection_gap(self) -> None:
        payload = {"run_id": "R-1", "lab": "lab-A"}
        payload_artifact, _ = self.ledger.cas.put_bytes(canonical(payload))
        event = {
            "schema": "KAMMI_EVENT_V1",
            "seq": 1,
            "prev": self.ledger.journal.head,
            "type": "RunCreated",
            "payload_artifact": payload_artifact,
            "actor": "chief",
            "request_id": "crash-1",
            "utc": "2026-09-27T00:00:00Z",
        }
        event_id = self.ledger.journal.append(event)
        self.ledger.close()
        del self.ledger
        gc.collect()
        self.ledger = Ledger(self.root)
        self.assertIn("R-1", self.ledger.runs)
        self.assertEqual(self.ledger.status()["projection_head"], event_id)

    def test_incomplete_journal_tail_is_preserved_and_repaired(self) -> None:
        self.ledger.create_run("R-1", "lab-A", "chief", "r1")
        original_head = self.ledger.journal.head
        with self.ledger.journal.path.open("ab") as output:
            output.write(b"\x00\x00")
        recovered = EventJournal(self.root)
        self.assertEqual(recovered.head, original_head)
        partials = list((self.root / "journal" / "recovery").glob("*.partial"))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].read_bytes(), b"\x00\x00")

    def test_api_rejects_unauthorized_and_ambiguous_input(self) -> None:
        client = TestClient(create_app(self.ledger, "secret-test-token"))
        self.assertEqual(client.get("/v1/status").status_code, 401)
        headers = {"Authorization": "Bearer secret-test-token"}
        self.assertEqual(client.post("/v1/authorize", headers=headers).status_code, 423)
        bad = client.post(
            "/v1/runs", content=b'{"run_id":"a","run_id":"b"}', headers=headers
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.ledger.status()["journal_events"], 0)
        accepted = client.post(
            "/v1/artifacts", content=b"fixture", headers={
                **headers, "X-Kind": "fixture", "X-Actor": "chief",
                "X-Request-ID": "api-1",
            }
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.ledger.status()["journal_events"], 1)

    def test_typed_history_uses_registered_evidence_and_rebuilds(self) -> None:
        evidence, _ = self.ledger.register_bytes(
            b'{"model_contact":false}', kind="legacy-receipt",
            actor="chief", request_id="evidence-1",
        )
        self.ledger.create_run("R-1", "lab-A", "chief", "run-1")
        fact = {
            "run_id": "R-1", "kind": "CONTACT", "subject": evidence,
            "object": "model", "value": "NO_ATTESTED",
            "evidence_artifact": evidence, "scope": "LEGACY_RECEIPT_SELF_ATTESTATION",
        }
        fact_id, _ = self.ledger.record_fact(fact, "chief", "fact-1")
        self.assertEqual(self.ledger.record_fact(fact, "chief", "fact-1")[0], fact_id)
        self.assertEqual(self.ledger.history("R-1")[0]["fact_id"], fact_id)
        summary = self.ledger.history_summary("R-1")
        self.assertEqual(summary["contact_global_state"], "UNKNOWN_GLOBALLY")
        self.assertEqual(len(summary["contact_assertions"]), 1)
        with self.assertRaisesRegex(ValueError, "central vocabulary"):
            self.ledger.record_fact({**fact, "lab_special": True}, "chief", "fact-2")
        with self.assertRaisesRegex(ValueError, "registered artifact"):
            self.ledger.record_fact(
                {**fact, "evidence_artifact": "sha256:" + "0" * 64},
                "chief", "fact-3",
            )
        expected = self.ledger.status()
        self.ledger.close()
        del self.ledger
        gc.collect()
        (self.root / "custody.lbdb").unlink()
        self.ledger = Ledger(self.root)
        self.assertEqual({k: v for k, v in self.ledger.status().items() if k != "writer"},
                         {k: v for k, v in expected.items() if k != "writer"})
        self.assertEqual(self.ledger.history("R-1")[0]["value"], "NO_ATTESTED")

    def test_single_writer_fencing_across_processes(self) -> None:
        with self.assertRaises(WriterBusy):
            Ledger(self.root)
        probe = (
            "from pathlib import Path\n"
            "from ledgerd.writer import StoreOwner, WriterBusy\n"
            "import sys\n"
            "try:\n StoreOwner(Path(sys.argv[1]))\n"
            "except WriterBusy:\n sys.exit(17)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(self.root)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        self.ledger.close()
        replacement = Ledger(self.root)
        replacement.close()

    def test_history_api_keeps_imported_claims_scoped(self) -> None:
        evidence, _ = self.ledger.register_bytes(
            b"legacy", kind="receipt", actor="chief", request_id="evidence-1"
        )
        self.ledger.create_run("R-1", "lab-A", "chief", "run-1")
        self.ledger.record_fact({
            "run_id": "R-1", "kind": "HEAD", "subject": "contract",
            "object": evidence, "value": "SEALED", "evidence_artifact": evidence,
            "scope": "VERIFIED_LEGACY_FIXTURE_HEAD_ONLY",
        }, "chief", "fact-1")
        client = TestClient(create_app(self.ledger, "secret-test-token"))
        headers = {"Authorization": "Bearer secret-test-token"}
        response = client.get("/v1/runs/R-1/history/summary", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["heads"][0]["object"], evidence)
        self.assertFalse(response.json()["authorization_conferred"])

    def test_policy_authorization_is_actor_run_and_policy_bound(self) -> None:
        policy = {
            "schema": "KAMMI_POLICY_V1", "stage_id": "STAGE-A", "version": "v1",
            "requires": {
                "actor": "AUTHORIZED", "scientific_spec": "SEALED",
                "execution_spec": "SEALED", "predecessor_seal": "VERIFIED",
            },
            "forbids": {"truth_label_contact": True, "eval_panel_opened": True},
        }
        policy_hash, _ = self.ledger.register_policy(policy, "policy-1")
        self.ledger.create_run("R-1", "lab-A", "chief", "run-1")
        self.ledger.create_run("R-2", "lab-A", "chief", "run-2")
        self.ledger.register_actor(
            "agent-1", "agent", "lab-A", hashlib.sha256(b"agent-secret").hexdigest(),
            "actor-1",
        )
        spec, _ = self.ledger.register_bytes(
            b"spec", kind="scientific-spec", actor="chief", request_id="spec-1"
        )
        execution, _ = self.ledger.register_bytes(
            b"execution", kind="execution-spec", actor="chief", request_id="spec-2"
        )
        root, _ = self.ledger.create_seal([spec, execution], [], "chief", "seal-1")
        self.ledger.bind_spec("R-1", "STAGE-A", "SCIENTIFIC", spec, root, "agent-1", "bind-1")
        self.ledger.bind_spec("R-1", "STAGE-A", "EXECUTION", execution, root, "agent-1", "bind-2")
        self.ledger.record_seal_verification("R-1", "STAGE-A", root, "agent-1", "verify-1")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.ledger.issue_grant(
            "grant-1", "agent-1", "authorize_stage", "R-1", "STAGE-A",
            policy_hash, expiry, "grant-request-1",
        )
        decision_id, receipt = self.ledger.authorize_stage(
            "R-1", "STAGE-A", "agent-1", expiry, "auth-1"
        )
        self.assertEqual(receipt["decision"], "AUTHORIZED")
        self.assertTrue(self.ledger.policy.authorization_valid(
            decision_id, "agent-1", "R-1", "STAGE-A"
        ))
        self.assertEqual(self.ledger.authorize_stage(
            "R-1", "STAGE-A", "agent-1", expiry, "auth-1"
        )[0], decision_id)
        self.assertFalse(self.ledger.policy.authorization_valid(
            decision_id, "agent-1", "R-2", "STAGE-A"
        ))
        denial_id, denial = self.ledger.authorize_stage(
            "R-2", "STAGE-A", "agent-1", expiry, "auth-2"
        )
        self.assertEqual(denial["decision"], "DENIED")
        self.assertNotEqual(decision_id, denial_id)
        next_policy = {**policy, "version": "v2"}
        self.ledger.register_policy(next_policy, "policy-2")
        self.assertFalse(self.ledger.policy.authorization_valid(
            decision_id, "agent-1", "R-1", "STAGE-A"
        ))


if __name__ == "__main__":
    unittest.main()

