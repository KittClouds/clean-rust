import unittest
import test_policy_exposure as fixtures


class LifecycleTests(unittest.TestCase):
    setUp = fixtures.PolicyExposureTests.setUp
    tearDown = fixtures.PolicyExposureTests.tearDown
    def test_failed_attempt_does_not_mutate_specs_or_head(self):
        ledger = self.ledger
        authorization, _ = ledger.authorize_stage("acceptance.R1", "STAGE-A", "agent-A", self.expiry, "auth-life")
        ledger.start_attempt("attempt-1", "acceptance.R1", "STAGE-A", "agent-A", authorization, "start-1")
        evidence, _ = ledger.register_bytes(b"failure", kind="receipt", actor="agent-A", request_id="failed-receipt")
        before = dict(ledger.policy.specs)
        event = ledger.finish_attempt("attempt-1", "agent-A", "STOPPED", evidence, "fixture failure", "finish-1")
        self.assertEqual(ledger.lifecycle.attempts["attempt-1"]["state"], "STOPPED")
        self.assertEqual(ledger.finish_attempt("attempt-1", "agent-A", "STOPPED", evidence, "fixture failure", "finish-1"), event)
        self.assertEqual(ledger.policy.specs, before)
        self.assertEqual(ledger.lifecycle.heads, {})
        ledger.start_attempt("attempt-2", "acceptance.R1", "STAGE-A", "agent-A", authorization, "start-2")
        ledger.finish_attempt("attempt-2", "agent-A", "COMPLETE", evidence, "fixture recovered", "finish-2")
        seal, _ = ledger.create_seal([evidence], [], "agent-A", "life-seal")
        ledger.declare_result("acceptance.R1", "STAGE-A", "agent-A", authorization, seal, None, "result-1")
        self.assertEqual(ledger.lifecycle.heads[("acceptance.R1", "STAGE-A")]["seal_root"], seal)
        self.assertEqual(ledger.lifecycle.attempts["attempt-1"]["state"], "STOPPED")
