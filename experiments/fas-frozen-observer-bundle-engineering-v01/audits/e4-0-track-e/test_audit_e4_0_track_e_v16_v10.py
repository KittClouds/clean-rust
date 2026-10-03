"""Independent synthetic regressions for the v16-v10 historical audit."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v16_v10.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v16_v10", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import independent v16-v10 auditor")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
PROJECT = SCRIPT.parents[2]
WORKSPACE = PROJECT.parents[1]


class IndependentAuditV16V10Tests(unittest.TestCase):
    def test_v08_preseal_schema_is_not_confused_with_runtime_receipt(self):
        preseal = AUDIT.load_json(AUDIT.safe_path(WORKSPACE, AUDIT.V16_V08_PRESEAL_RECEIPT["path"]))
        preservation = AUDIT.load_json(AUDIT.safe_path(WORKSPACE, AUDIT.V16_V08_PRESERVATION_RECEIPT["path"]))
        self.assertEqual(preseal["status"], AUDIT.V16_V08_PRESEAL_RECEIPT["status"])
        self.assertEqual(preseal["issues"], AUDIT.V16_V08_PRESEAL_ISSUES)
        self.assertIs(preseal["population_truth_files_opened"], False)
        self.assertIs(preseal["template_or_joint_truth_opened"], False)
        for key in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertNotIn(key, preseal)
            self.assertIs(preservation[key], False)
        self.assertEqual(preservation["status"], AUDIT.V16_V08_PRESERVATION_RECEIPT["status"])

    def test_v09_prematerialization_stop_is_exact_no_contact_history(self):
        path = AUDIT.safe_path(WORKSPACE, AUDIT.V16_V09_PREMATERIALIZATION_STOP["path"])
        self.assertEqual(AUDIT.digest(path), (2019, "00f823fcacd6eea7f75b9bce839b1972e62e1beafa4a67d5c4286554e07c3aa4"))
        stop = AUDIT.load_json(path)
        self.assertEqual(stop["source_map"], AUDIT.V16_V09_MAP_ATTEMPT)
        self.assertEqual(stop["finalizer_source"], AUDIT.V16_V09_FINALIZER_ATTEMPT)
        self.assertEqual(stop["diagnostic"], AUDIT.V16_V09_FINALIZER_DIAGNOSTIC)
        for field in (
            "contract_candidate_written", "seal_written", "authorization_written", "tokenizer_contact",
            "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created",
            "labels_opened", "population_truth_files_opened", "template_or_joint_truth_opened",
        ):
            self.assertIs(stop[field], False)
        self.assertEqual(
            stop["contract_candidate"],
            AUDIT.V16_V09_FAILED_PREMATERIALIZATION_ATTEMPT["contract_candidate"],
        )

    def test_historical_authorization_identity_remains_distinct(self):
        issuer = PROJECT / "source/scripts/issue_e4_stage_authorization_v16_v06.py"
        source = issuer.read_text(encoding="utf-8")
        self.assertIn('V06_REFERENCE_AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01"', source)
        self.assertIn('AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V06"', source)

    def test_v10_source_role_projection_contains_current_and_history(self):
        names = (
            "source/scripts/issue_e4_stage_authorization_v16_v06.py",
            "source/tests/test_e4_stage_authorization_v16_v06.py",
            "source/scripts/build_e4_0_source_map_v16_v08.py",
            "source/scripts/finalize_e4_0_contract_v16_v08.py",
            "source/scripts/seal_e4_0_contract_v16_v07.py",
            "source/scripts/test_e4_0_contract_v16_v08.py",
            "source/scripts/build_e4_0_source_map_v16_v09.py",
            "source/scripts/finalize_e4_0_contract_v16_v09.py",
            "source/scripts/seal_e4_0_contract_v16_v08.py",
            "source/scripts/test_e4_0_contract_v16_v09.py",
            "source/scripts/build_e4_0_source_map_v16_v10.py",
            "source/scripts/finalize_e4_0_contract_v16_v10.py",
            "source/scripts/seal_e4_0_contract_v16_v09.py",
            "source/scripts/test_e4_0_contract_v16_v10.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v08.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v08.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v09.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v10.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v10.py",
        )
        rows = [{"path": f"{AUDIT.PROJECT_REL}/{name}"} for name in names]
        projection = AUDIT.source_role_projection(rows, {"path": "map"})
        self.assertEqual(len(projection["e4_stage_authorization_issuer"]["files"]), 2)
        self.assertEqual(len(projection["e4_contract_seal_and_source_map_tooling"]["files"]), 12)
        self.assertEqual(len(projection["e4_independent_auditor"]["files"]), 6)
        self.assertTrue(AUDIT.is_independent_auditor_source(f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/audit_e4_0_track_e_v16_v10.py"))

    def test_current_receipt_registry_points_to_v10_only(self):
        self.assertEqual(
            AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Contract tooling v16 v10"],
            (f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v16-v10.json", "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V10"),
        )
        self.assertEqual(
            AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Track E v16 pre-map v10"],
            (f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v37.json", "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V10"),
        )
        self.assertTrue(AUDIT.V16_CONTRACT_DEFAULT.endswith("e4-0-contract-v16-v08-final.json"))
        self.assertTrue(AUDIT.V16_MAP_DEFAULT.endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v10.md"))
        self.assertEqual(AUDIT.V16_SEAL_ID, "FAS_E4_0_CONTRACT_V16_V08_SEAL")


if __name__ == "__main__":
    unittest.main()
