import unittest
import sys
import subprocess
import time
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import test_remote as fixture
from ledgerd.identity import canonical, strict_json
from ledgerd.remote import sign
from ledgerd.worker import execute_bundle
from scripts.independent_verify import verify_store


class RemoteAdversarialTests(unittest.TestCase):
    setUp = fixture.RemoteTests.setUp
    tearDown = fixture.RemoteTests.tearDown

    def run_worker(self, bundle=None, environment=None, inputs=None, validator=None, timeout=5):
        bundle = bundle or self.bundle
        raw = canonical(bundle)
        return execute_bundle(raw, sign(self.ledger.signing_private, raw),
                              bytes.fromhex(self.envelope["issuer_public_hex"]),
                              inputs or {self.input: b"declared input"}, self.worker_private,
                              environment or self.environment, validator or (lambda *_: True), timeout)

    def test_bundle_environment_output_and_crash_matrix(self):
        _, self.envelope = self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bundle")
        self.environment = {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}
        for changed in ({"git_commit": "b" * 40}, {"dirty_tree": True}, {"runtime": "wrong"}):
            with self.subTest(environment=changed), self.assertRaises(ValueError):
                self.run_worker(environment={**self.environment, **changed})
        for category, field, required, actual in (
            ("gpu_requirements", "cuda", "12.4", "12.5"),
            ("gpu_requirements", "gpu_class", "RTX3080", "other"),
        ):
            bundle = {**self.bundle, category: {field: required}}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_worker(bundle=bundle, environment={**self.environment, field: actual})
        with self.assertRaises(ValueError):
            self.run_worker(inputs={self.input: b"tampered"})
        with self.assertRaises(ValueError):
            self.run_worker(bundle={**self.bundle, "expected_outputs": ["missing.txt"]})
        with self.assertRaises(ValueError):
            self.run_worker(bundle={**self.bundle, "expected_outputs": []})
        with self.assertRaises(ValueError):
            self.run_worker(bundle={**self.bundle, "command": [sys.executable, "-c", "raise SystemExit(9)"]})
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_worker(bundle={**self.bundle, "command": [sys.executable, "-c", "import time;time.sleep(10)"]}, timeout=0.1)
        with self.assertRaises(ValueError):
            self.run_worker(bundle={**self.bundle, "lease_id": "fake", "lease_resource_id": "gpu", "fencing_token": 1}, validator=lambda *_: False)
        result = self.run_worker()
        bundle_id = self.envelope["bundle_artifact_id"]
        raw, signature, outputs, stdout, stderr = result
        with self.assertRaises(ValueError):
            self.ledger.accept_remote_return(bundle_id, raw[:-1], signature, "worker", self.worker_token,
                                             outputs, stdout, stderr, "partial-upload")
        self.ledger.remote_worker_started(bundle_id, "worker", self.worker_token, "started")
        first = self.ledger.accept_remote_return(bundle_id, raw, signature, "worker", self.worker_token,
                                                 outputs, stdout, stderr, "accepted")
        # Lost response / network interruption: different transport request returns
        # the already verified semantic result, without a second acceptance event.
        retry = self.ledger.accept_remote_return(bundle_id, raw, signature, "worker", self.worker_token,
                                                 outputs, stdout, stderr, "network-retry")
        self.assertEqual(first, retry)
        modified = strict_json(raw)
        modified["elapsed_ms"] += 1
        altered = canonical(modified)
        with self.assertRaises(ValueError):
            self.ledger.accept_remote_return(bundle_id, altered, sign(self.worker_private, altered),
                                             "worker", self.worker_token, outputs, stdout, stderr, "receipt-replay")
        self.assertEqual(verify_store(self.root)["status"], "PASS")

    def test_stale_authorization_rejects_new_bundle_and_return(self):
        _, self.envelope = self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bundle")
        self.environment = {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}
        raw, signature, outputs, stdout, stderr = self.run_worker()
        self.ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": "REMOTE",
                                     "version": "v2", "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "policy-v2")
        with self.assertRaises(ValueError):
            self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "stale-bundle")
        with self.assertRaises(ValueError):
            self.ledger.accept_remote_return(self.envelope["bundle_artifact_id"], raw, signature,
                                             "worker", self.worker_token, outputs, stdout, stderr, "stale-return")

    def test_protected_panel_cannot_bypass_exposure_as_remote_input(self):
        self.ledger.register_panel("protected-input", self.input, "lab", "panel")
        with self.assertRaisesRegex(ValueError, "guarded exposure"):
            self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bypass-bundle")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.ledger.issue_grant("panel-grant", "agent", "open_panel", "acceptance.remote", "REMOTE", self.policy_hash, expiry, "panel-grant")
        data, _, _ = self.ledger.open_panel("protected-input", "diagnostic", "acceptance.remote", "REMOTE", "agent", self.agent_token, self.authorization, "open-input")
        self.assertEqual(data, b"declared input")
        self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "exposed-bundle")

    def test_stale_lease_rejects_execution_and_return(self):
        self.ledger.register_resource("gpu.remote", "GPU", "fixture", {}, "resource")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.ledger.issue_grant("lease-grant", "agent", "acquire_lease", "acceptance.remote", "REMOTE", self.policy_hash, expiry, "lease-grant")
        _, lease = self.ledger.acquire_lease("gpu.remote", "acceptance.remote", "REMOTE", "agent", self.agent_token, "remote", 10, "lease")
        self.bundle = {**self.bundle, "lease_id": lease["lease_id"], "lease_resource_id": "gpu.remote", "fencing_token": lease["fencing_token"]}
        _, self.envelope = self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bundle")
        self.environment = {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}
        calls = [0]
        def expires_during_execution(*_):
            calls[0] += 1
            return calls[0] == 1
        with self.assertRaisesRegex(ValueError, "expired during execution"):
            self.run_worker(validator=expires_during_execution)
        raw, signature, outputs, stdout, stderr = self.run_worker()
        self.ledger.release_lease(lease["lease_id"], lease["fencing_token"], "agent", self.agent_token, "release")
        with self.assertRaisesRegex(ValueError, "lease is stale"):
            self.ledger.accept_remote_return(self.envelope["bundle_artifact_id"], raw, signature, "worker", self.worker_token,
                                             outputs, stdout, stderr, "stale-return")

    def test_lease_expires_while_remote_return_uploads(self):
        self.ledger.register_resource("gpu.return", "GPU", "fixture", {}, "resource")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.ledger.issue_grant("lease-grant", "agent", "acquire_lease", "acceptance.remote", "REMOTE", self.policy_hash, expiry, "lease-grant")
        _, lease = self.ledger.acquire_lease("gpu.return", "acceptance.remote", "REMOTE", "agent", self.agent_token, "return-race", 1, "lease")
        self.bundle = {**self.bundle, "lease_id": lease["lease_id"], "lease_resource_id": "gpu.return", "fencing_token": lease["fencing_token"]}
        _, self.envelope = self.ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bundle")
        self.environment = {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}
        raw, signature, outputs, stdout, stderr = self.run_worker()
        register = self.ledger.register_bytes
        def slow_upload(data, **kwargs):
            if kwargs.get("kind") == "remote-output":
                time.sleep(1.05)
            return register(data, **kwargs)
        with patch.object(self.ledger, "register_bytes", side_effect=slow_upload):
            with self.assertRaisesRegex(ValueError, "expired during upload"):
                self.ledger.accept_remote_return(self.envelope["bundle_artifact_id"], raw, signature,
                    "worker", self.worker_token, outputs, stdout, stderr, "return-race")
        self.assertNotIn(self.envelope["bundle_artifact_id"], self.ledger.remote.returns)
        self.assertEqual(verify_store(self.root)["status"], "PASS")
