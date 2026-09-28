import unittest
from pathlib import Path

import test_remote as fixture
from ledgerd.embedding import Embedder
from ledgerd.memory import MemoryService
from ledgerd.identity import canonical, strict_json
from scripts.independent_verify import verify_store


class StructuredTamperTests(unittest.TestCase):
    setUp = fixture.RemoteTests.setUp
    tearDown = fixture.RemoteTests.tearDown

    def test_policy_actor_lease_adapter_remote_memory_mutations(self):
        ledger = self.ledger
        ledger.register_resource("gpu.tamper", "GPU", "local", {}, "resource")
        expiry = ledger.policy.authorizations[self.authorization]["expires_utc"]
        ledger.issue_grant("lease", "agent", "acquire_lease", "acceptance.remote", "REMOTE", self.policy_hash, expiry, "lease-grant")
        ledger.acquire_lease("gpu.tamper", "acceptance.remote", "REMOTE", "agent", self.agent_token, "tamper", 120, "lease")
        ledger.register_adapter("EVAL_CELLS_RENAME_V1", "adapter")
        _, envelope = ledger.create_remote_bundle(self.bundle, "agent", self.agent_token, "bundle")
        ledger.memory = MemoryService(ledger.root, ledger.cas,
            Embedder(Path(__file__).resolve().parents[1] / "vendor/runtime-v1/embedding-cache"),
            ledger.valid_custody_ref, ledger.graph.db, ledger.lock)
        memory_id, _ = ledger.memory.record(kind="OBSERVED", scope="lab", text="Grounded tamper fixture",
            actor="agent", custody_refs=[self.input], tags=[], request_id="memory")
        memory = ledger.memory.get(memory_id)
        record_event, _ = ledger.memory.journal.by_request["memory"]
        record_payload = strict_json(ledger.cas.get(record_event["payload_artifact"]))
        cases = [("authorization policy ID", "authorize:final", "policy_id", "wrong-policy"),
                 ("actor ID", "actor-agent", "actor_id", "wrong-actor"),
                 ("lease token", "lease:granted", "fencing_token", 999),
                 ("adapter identity", "adapter:registered", "adapter_id", "wrong-adapter")]
        for label, request, field, value in cases:
            event, _ = ledger.journal.by_request[request]
            cases_identity = event["payload_artifact"]
            with self.subTest(mutation=label):
                self.reject_changed(ledger, cases_identity, field, value)
        with self.subTest(mutation="remote manifest"):
            self.reject_changed(ledger, envelope["bundle_artifact_id"], "command", ["malicious-change"])
        with self.subTest(mutation="memory custody reference"):
            self.reject_changed(ledger, record_payload["record_artifact_id"], "custody_refs", ["sha256:" + "0" * 64])
        self.assertEqual(verify_store(ledger.root)["status"], "PASS")

    def reject_changed(self, ledger, identity, field, value):
        path = ledger.cas.path_for(identity)
        original = path.read_bytes()
        changed = strict_json(original)
        changed[field] = value
        try:
            path.write_bytes(canonical(changed))
            with self.assertRaisesRegex(ValueError, "CAS digest mismatch"):
                verify_store(ledger.root)
        finally:
            path.write_bytes(original)
