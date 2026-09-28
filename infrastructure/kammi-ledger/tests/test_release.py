import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledgerd.core import Ledger
from ledgerd.identity import canonical
from ledgerd.release import GATES, architecture_identity, runtime_identity, source_manifest


class ReleaseTests(unittest.TestCase):
    def test_gate_requires_complete_current_independently_bound_evidence(self):
        with tempfile.TemporaryDirectory(prefix="kammi-release-") as directory:
            ledger = Ledger(Path(directory))
            try:
                _, source = source_manifest()
                _, runtime = runtime_identity()
                proof, _ = ledger.register_bytes(b"fixture passing test evidence", kind="receipt",
                                                 actor="auditor", request_id="proof")
                suite = {"schema": "KAMMI_ENDSTATE_ACCEPTANCE_V1", "status": "PASS",
                         "source_root": source, "runtime_identity": runtime,
                         "gates": {gate: {"status": "PASS", "evidence": [proof]} for gate in GATES}}
                suite_id, _ = ledger.register_bytes(canonical(suite), kind="acceptance-suite",
                                                    actor="auditor", request_id="suite")
                audit = {"schema": "KAMMI_ENDSTATE_INDEPENDENT_AUDIT_V1", "status": "PASS",
                         "source_root": source, "runtime_identity": runtime, "acceptance_suite_root": suite_id}
                audit_id, _ = ledger.register_bytes(canonical(audit), kind="independent-audit",
                                                    actor="auditor", request_id="audit")
                acceptance = {"schema": "LibraryAcceptanceV1", "gates": {g: "PASS" for g in GATES},
                              "architecture_hash": architecture_identity(),
                              "source_root": source, "runtime_identity": runtime,
                              "acceptance_suite_root": suite_id, "independent_verification_root": audit_id}
                self.assertEqual(ledger.flight_state()["state"], "CLOSED_PENDING_ACCEPTANCE")
                for mutation in ({"source_root": "sha256:" + "0" * 64},
                                 {"runtime_identity": "sha256:" + "0" * 64},
                                 {"acceptance_suite_root": proof},
                                 {"gates": {**acceptance["gates"], GATES[0]: "FAIL"}}):
                    with self.assertRaises(ValueError):
                        ledger.accept_library({**acceptance, **mutation}, "bad-acceptance")
                identity, _ = ledger.accept_library(acceptance, "acceptance")
                self.assertEqual(ledger.flight_state()["acceptance_identity"], identity)
                self.assertEqual(ledger.flight_state()["state"], "OPEN")
                with patch("ledgerd.release.runtime_identity", return_value=({}, "changed")):
                    self.assertEqual(ledger.flight_state()["state"], "CLOSED_PENDING_ACCEPTANCE")
                with patch("ledgerd.release.source_manifest", return_value=({}, "changed")):
                    self.assertEqual(ledger.flight_state()["state"], "CLOSED_PENDING_ACCEPTANCE")
            finally:
                ledger.close()
                gc.collect()
