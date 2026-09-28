from __future__ import annotations

import gc
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ledgerd.core import Ledger
from ledgerd.remote import public_bytes
from ledgerd.worker import execute_bundle


class RemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kammi-remote-"))
        self.ledger = Ledger(self.root, signing_key=os.urandom(32))
        self.agent_token = "agent-token"
        self.worker_token = "worker-token"
        self.ledger.register_actor(
            "agent", "agent", "lab", hashlib.sha256(self.agent_token.encode()).hexdigest(),
            "actor-agent",
        )
        self.ledger.register_actor(
            "worker", "remote_worker", "lab", hashlib.sha256(self.worker_token.encode()).hexdigest(),
            "actor-worker",
        )
        self.worker_private = Ed25519PrivateKey.generate()
        self.ledger.register_worker_key(
            "worker", public_bytes(self.worker_private).hex(), "worker-key",
        )
        self.ledger.create_run("acceptance.remote", "lab", "ledger-admin", "run")
        self.policy_hash, _ = self.ledger.register_policy({
            "schema": "KAMMI_POLICY_V1", "stage_id": "REMOTE", "version": "v1",
            "requires": {"actor": "AUTHORIZED"}, "forbids": {},
        }, "policy")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for action in ("authorize_stage", "execute_bundle"):
            self.ledger.issue_grant(
                action, "agent", action, "acceptance.remote", "REMOTE",
                self.policy_hash, expiry, "grant-" + action,
            )
        self.scientific, _ = self.ledger.register_bytes(
            b"science", kind="scientific-spec", actor="agent", request_id="science"
        )
        self.execution, _ = self.ledger.register_bytes(
            b"execution", kind="execution-spec", actor="agent", request_id="execution"
        )
        self.input, _ = self.ledger.register_bytes(
            b"declared input", kind="input", actor="agent", request_id="input"
        )
        self.env_lock, _ = self.ledger.register_bytes(
            b"env", kind="environment-lock", actor="agent", request_id="env"
        )
        self.root_seal, _ = self.ledger.create_seal(
            [self.scientific, self.execution, self.input, self.env_lock], [],
            "agent", "seal",
        )
        self.ledger.bind_spec(
            "acceptance.remote", "REMOTE", "SCIENTIFIC", self.scientific,
            self.root_seal, "agent", "bind-science",
        )
        self.ledger.bind_spec(
            "acceptance.remote", "REMOTE", "EXECUTION", self.execution,
            self.root_seal, "agent", "bind-execution",
        )
        self.authorization, receipt = self.ledger.authorize_stage(
            "acceptance.remote", "REMOTE", "agent", expiry, "authorize"
        )
        self.assertEqual(receipt["decision"], "AUTHORIZED")
        command = (
            "import os,pathlib; "
            "p=pathlib.Path(os.environ['KAMMI_OUTPUT_DIR'])/'answer.txt'; "
            "p.write_text('remote-ok')"
        )
        self.bundle = {
            "schema": "KAMMI_REMOTE_BUNDLE_V1",
            "run_id": "acceptance.remote", "lab": "lab", "stage_id": "REMOTE",
            "scientific_spec": self.scientific, "execution_spec": self.execution,
            "git_commit": "a" * 40, "dirty_tree_policy": "CLEAN_REQUIRED",
            "input_roots": [self.root_seal], "input_artifacts": [self.input],
            "environment_lock": self.env_lock,
            "runtime_requirements": {"runtime": "python-fixture"},
            "gpu_requirements": {}, "seeds": [1],
            "command": [sys.executable, "-c", command],
            "expected_outputs": ["answer.txt"],
            "authorization_id": self.authorization,
            "lease_id": None, "lease_resource_id": None, "fencing_token": None,
            "worker_actor_id": "worker",
        }

    def tearDown(self) -> None:
        self.ledger.close()
        del self.ledger
        gc.collect()
        shutil.rmtree(self.root)

    def test_signed_bundle_worker_return_and_tamper(self) -> None:
        _, envelope = self.ledger.create_remote_bundle(
            self.bundle, "agent", self.agent_token, "bundle"
        )
        bundle_id = envelope["bundle_artifact_id"]
        raw = self.ledger.cas.get(bundle_id)
        issuer_public = bytes.fromhex(envelope["issuer_public_hex"])
        environment = {"git_commit": "a" * 40, "dirty_tree": False,
                       "runtime": "python-fixture"}
        with self.assertRaisesRegex(ValueError, "signature invalid"):
            execute_bundle(
                raw + b" ", envelope["signature_hex"], issuer_public,
                {self.input: b"declared input"}, self.worker_private,
                environment, lambda *_: True,
            )
        receipt_raw, receipt_sig, outputs, stdout, stderr = execute_bundle(
            raw, envelope["signature_hex"], issuer_public,
            {self.input: b"declared input"}, self.worker_private,
            environment, lambda *_: True,
        )
        event_id, accepted = self.ledger.accept_remote_return(
            bundle_id, receipt_raw, receipt_sig, "worker", self.worker_token,
            outputs, stdout, stderr, "return",
        )
        self.assertEqual(accepted["status"], "VERIFIED_NOT_HEAD_PROMOTED")
        self.assertEqual(self.ledger.cas.get(accepted["outputs"]["answer.txt"]), b"remote-ok")
        self.assertEqual(self.ledger.accept_remote_return(
            bundle_id, receipt_raw, receipt_sig, "worker", self.worker_token,
            outputs, stdout, stderr, "return-retry",
        )[0], event_id)
        with self.assertRaisesRegex(ValueError, "output hash mismatch"):
            self.ledger.accept_remote_return(
                bundle_id, receipt_raw, receipt_sig, "worker", self.worker_token,
                {"answer.txt": b"wrong"}, stdout, stderr, "tampered-return",
            )


if __name__ == "__main__":
    unittest.main()
