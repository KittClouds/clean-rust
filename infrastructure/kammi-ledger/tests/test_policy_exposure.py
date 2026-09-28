from __future__ import annotations

import gc
import hashlib
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ledgerd.api import create_app
from ledgerd.core import Ledger
from ledgerd.executor import StaleLease, run_fenced
from ledgerd.identity import strict_json


class PolicyExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kammi-policy-"))
        self.ledger = Ledger(self.root)
        self.token = "scoped-agent-secret"
        self.ledger.register_actor(
            "agent-A", "agent", "lab-A", hashlib.sha256(self.token.encode()).hexdigest(),
            "actor-A",
        )
        self.ledger.create_run("acceptance.R1", "lab-A", "ledger-admin", "run-A")
        self.policy_hash, _ = self.ledger.register_policy({
            "schema": "KAMMI_POLICY_V1", "stage_id": "STAGE-A", "version": "v1",
            "requires": {"actor": "AUTHORIZED"}, "forbids": {},
        }, "policy-A")
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for action in ("authorize_stage", "open_panel"):
            self.ledger.issue_grant(
                "grant-" + action, "agent-A", action, "acceptance.R1", "STAGE-A",
                self.policy_hash, self.expiry, "grant-" + action,
            )
        artifact, _ = self.ledger.register_bytes(
            b"protected fixture", kind="panel", actor="ledger-admin", request_id="panel-bytes"
        )
        self.ledger.register_panel("P-1", artifact, "lab-A", "panel-register")
        self.client = TestClient(create_app(self.ledger, "admin-secret", acceptance_mode=True))

    def tearDown(self) -> None:
        self.client.close()
        self.ledger.close()
        del self.ledger
        gc.collect()
        shutil.rmtree(self.root)

    def test_terminal_open_is_guarded_and_retry_is_idempotent(self) -> None:
        headers = {"Authorization": "Bearer " + self.token}
        request = {
            "purpose": "terminal", "run_id": "acceptance.R1", "stage_id": "STAGE-A",
            "actor_id": "agent-A", "authorization_id": "sha256:" + "0" * 64,
            "request_id": "open-before-auth",
        }
        denied = self.client.post("/v1/panels/P-1/open", json=request, headers=headers)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.ledger.exposure.report("P-1")["count"], 0)
        authorization = self.client.post(
            "/v1/acceptance/stages/authorize",
            json={"run_id": "acceptance.R1", "stage_id": "STAGE-A",
                  "actor_id": "agent-A", "expires_utc": self.expiry,
                  "request_id": "authorize-fixture"},
            headers=headers,
        )
        self.assertEqual(authorization.status_code, 200)
        self.assertEqual(authorization.json()["receipt"]["decision"], "AUTHORIZED")
        request["authorization_id"] = authorization.json()["event_id"]
        request["request_id"] = "open-authorized"
        opened = self.client.post("/v1/panels/P-1/open", json=request, headers=headers)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.content, b"protected fixture")
        self.assertEqual(self.ledger.exposure.report("P-1")["exposure_vector"]["terminal"], 1)
        repeat = self.client.post("/v1/panels/P-1/open", json=request, headers=headers)
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.headers["X-Exposure-Event"], opened.headers["X-Exposure-Event"])
        self.assertEqual(self.ledger.exposure.report("P-1")["count"], 1)
        wrong = self.client.post(
            "/v1/panels/P-1/open", json={**request, "request_id": "wrong-actor"},
            headers={"Authorization": "Bearer another-agent-token"},
        )
        self.assertEqual(wrong.status_code, 401)

    def test_spec_supersession_and_authorization_expiry_receipts(self):
        ledger = self.ledger
        a, _ = ledger.register_bytes(b"spec-one", kind="scientific-spec", actor="admin", request_id="first-spec")
        b, _ = ledger.register_bytes(b"spec-two", kind="scientific-spec", actor="admin", request_id="second-spec")
        seal, _ = ledger.create_seal([a, b], [], "admin", "spec-seal")
        ledger.bind_spec("acceptance.R1", "STAGE-A", "SCIENTIFIC", a, seal, "agent-A", "bind-one")
        auth, _ = ledger.authorize_stage("acceptance.R1", "STAGE-A", "agent-A", self.expiry, "spec-auth")
        self.assertTrue(ledger.policy.authorization_valid(auth, "agent-A", "acceptance.R1", "STAGE-A"))
        self.assertFalse(ledger.policy.authorization_valid(auth, "different-agent", "acceptance.R1", "STAGE-A"))
        ledger.bind_spec("acceptance.R1", "STAGE-A", "SCIENTIFIC", b, seal, "agent-A", "bind-two")
        self.assertFalse(ledger.policy.authorization_valid(auth, "agent-A", "acceptance.R1", "STAGE-A"))
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        _, denied = ledger.authorize_stage("acceptance.R1", "STAGE-A", "agent-A", later, "outlive-grant")
        self.assertEqual(denied["decision"], "DENIED")
        evaluated, _ = ledger.journal.by_request["outlive-grant:evaluated"]
        self.assertEqual(strict_json(ledger.cas.get(evaluated["payload_artifact"]))["decision"], "DENIED")

    def test_gpu_collision_expiry_and_stale_fence(self) -> None:
        other_token = "other-agent-secret"
        self.ledger.register_actor(
            "agent-B", "agent", "lab-A", hashlib.sha256(other_token.encode()).hexdigest(),
            "actor-B",
        )
        self.ledger.register_resource("gpu.local.0", "GPU", "local", {}, "gpu-register")
        for actor_id in ("agent-A", "agent-B"):
            self.ledger.issue_grant(
                "lease-grant-" + actor_id, actor_id, "acquire_lease",
                "acceptance.R1", "STAGE-A", self.policy_hash, self.expiry,
                "lease-grant-request-" + actor_id,
            )

        def acquire(actor_id: str, credential: str):
            return self.ledger.acquire_lease(
                "gpu.local.0", "acceptance.R1", "STAGE-A", actor_id,
                credential, "fixture-work", 1, "acquire-" + actor_id,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda pair: acquire(*pair), [
                ("agent-A", self.token), ("agent-B", other_token),
            ]))
        granted = [item[1] for item in answers if item[1]["decision"] == "GRANTED"]
        denied = [item[1] for item in answers if item[1]["decision"] == "DENIED"]
        self.assertEqual((len(granted), len(denied)), (1, 1))
        old = granted[0]
        with self.assertRaises(StaleLease):
            run_fenced(
                self.ledger, lease_id="lease-does-not-exist", resource_id="gpu.local.0",
                fencing_token=0, actor_id=old["actor_id"], run_id="acceptance.R1",
                argv=[sys.executable, "-c", "print('should-not-run')"], cwd=self.root,
            )
        later = datetime.fromisoformat(old["expires_utc"]) + timedelta(seconds=1)
        winner = denied[0]["actor_id"]
        credential = self.token if winner == "agent-A" else other_token
        _, next_lease = self.ledger.acquire_lease(
            "gpu.local.0", "acceptance.R1", "STAGE-A", winner, credential,
            "fixture-work", 60, "acquire-after-expiry", at=later,
        )
        self.assertEqual(next_lease["decision"], "GRANTED")
        self.assertEqual(next_lease["fencing_token"], old["fencing_token"] + 1)
        with self.assertRaises(StaleLease):
            run_fenced(
                self.ledger, lease_id=old["lease_id"], resource_id="gpu.local.0",
                fencing_token=old["fencing_token"], actor_id=old["actor_id"],
                run_id="acceptance.R1", argv=[sys.executable, "-c", "print('stale')"],
                cwd=self.root,
            )
        code, stdout, _ = run_fenced(
            self.ledger, lease_id=next_lease["lease_id"], resource_id="gpu.local.0",
            fencing_token=next_lease["fencing_token"], actor_id=winner,
            run_id="acceptance.R1", argv=[sys.executable, "-c", "print('qualified')"],
            cwd=self.root,
        )
        self.assertEqual(code, 0)
        self.assertIn(b"qualified", stdout)

    def test_adapter_preserves_source_identity(self) -> None:
        self.ledger.issue_grant(
            "adapter-grant", "agent-A", "apply_adapter", "acceptance.R1",
            "STAGE-A", self.policy_hash, self.expiry, "adapter-grant-request",
        )
        authorization_id, receipt = self.ledger.authorize_stage(
            "acceptance.R1", "STAGE-A", "agent-A", self.expiry, "adapter-auth"
        )
        self.assertEqual(receipt["decision"], "AUTHORIZED")
        self.ledger.register_adapter("EVAL_CELLS_RENAME_V1", "adapter-register")
        original_bytes = b'{"schema":"evaluation-v1","evaluation_checkpoint_cells":[1,2]}'
        original, _ = self.ledger.register_bytes(
            original_bytes, kind="legacy-evaluation", actor="agent-A",
            request_id="adapter-original",
        )
        derived, _ = self.ledger.apply_adapter(
            "EVAL_CELLS_RENAME_V1", original, "agent-A", self.token,
            "acceptance.R1", "STAGE-A", authorization_id,
            "schema_handoff", "adapter-apply",
        )
        self.assertEqual(self.ledger.cas.get(original), original_bytes)
        self.assertNotEqual(derived, original)
        converted = strict_json(self.ledger.cas.get(derived))
        self.assertEqual(converted["evaluation_cells"], [1, 2])
        self.assertNotIn("evaluation_checkpoint_cells", converted)


if __name__ == "__main__":
    unittest.main()
