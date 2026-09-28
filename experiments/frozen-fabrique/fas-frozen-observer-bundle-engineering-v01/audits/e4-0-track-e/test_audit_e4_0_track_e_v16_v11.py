"""Independent synthetic regressions for the v16-v11 historical audit."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v16_v11.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v16_v11", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import independent v16-v11 auditor")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
PROJECT = SCRIPT.parents[2]
WORKSPACE = PROJECT.parents[1]


class IndependentAuditV16V11Tests(unittest.TestCase):
    def test_v10_failed_preseal_is_exactly_bound_and_truth_closed(self):
        receipt_path = AUDIT.safe_path(WORKSPACE, AUDIT.V16_V10_PRESEAL_RECEIPT["path"])
        self.assertEqual(AUDIT.digest(receipt_path), (161408, "f3f8c6b5b616849a5bd18d3ca04cf4b00ef039910d96e7c32167c3d59b07d2e2"))
        receipt = AUDIT.load_json(receipt_path)
        self.assertEqual(receipt["status"], AUDIT.V16_V10_PRESEAL_RECEIPT["status"])
        self.assertEqual(receipt["issues"], AUDIT.V16_V10_PRESEAL_ISSUES)
        self.assertIs(receipt["pass"], False)
        self.assertIsNone(receipt["final_seal"])
        self.assertIs(receipt["population_truth_files_opened"], False)
        self.assertIs(receipt["template_or_joint_truth_opened"], False)
        self.assertEqual(AUDIT.V16_V10_FAILED_PRESEAL_ATTEMPT["runtime_contact_fields_absent"], list(AUDIT.V16_V10_RUNTIME_FIELDS_ABSENT))
        for field in AUDIT.V16_V10_RUNTIME_FIELDS_ABSENT:
            self.assertNotIn(field, receipt)
        self.assertFalse((PROJECT / "seals/e4-0-contract-v16-v08-seal.json").exists())

    def test_nested_v05_contract_identity_matches_actual_serialized_shape(self):
        projected = {key: AUDIT.V16_V05_CONTRACT[key] for key in ("path", "bytes", "sha256")}
        amendment_projection = {
            "contract_id": AUDIT.V16_CONTRACT_ID,
            "contract": projected,
            "seal": dict(AUDIT.V16_V05_SEAL),
            "independent_postseal_audit": dict(AUDIT.V16_V05_POSTSEAL_AUDIT),
        }
        self.assertNotIn("contract_id", amendment_projection["contract"])
        self.assertEqual(amendment_projection["contract"], {
            "path": AUDIT.V16_V05_CONTRACT["path"],
            "bytes": AUDIT.V16_V05_CONTRACT["bytes"],
            "sha256": AUDIT.V16_V05_CONTRACT["sha256"],
        })

    def test_prior_receipts_are_explicitly_predecessors_and_v11_is_current(self):
        registry = AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS
        self.assertIn("Predecessor Contract tooling v16 v10", registry)
        self.assertIn("Predecessor Track E v16 pre-map v10", registry)
        self.assertNotIn("Contract tooling v16 v10", registry)
        self.assertNotIn("Track E v16 pre-map v10", registry)
        self.assertTrue(AUDIT.V16_CONTRACT_DEFAULT.endswith("e4-0-contract-v16-v09-final.json"))
        self.assertTrue(AUDIT.V16_MAP_DEFAULT.endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v11.md"))
        self.assertEqual(AUDIT.V16_SEAL_ID, "FAS_E4_0_CONTRACT_V16_V09_SEAL")

    def test_source_role_projection_covers_current_v11_tooling_and_auditor(self):
        names = (
            "source/scripts/build_e4_0_source_map_v16_v11.py",
            "source/scripts/finalize_e4_0_contract_v16_v11.py",
            "source/scripts/seal_e4_0_contract_v16_v10.py",
            "source/scripts/test_e4_0_contract_v16_v11.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v11.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v11.py",
        )
        rows = [{"path": f"{AUDIT.PROJECT_REL}/{name}"} for name in names]
        projection = AUDIT.source_role_projection(rows, {"path": "map"})
        self.assertEqual(len(projection["e4_contract_seal_and_source_map_tooling"]["files"]), 4)
        self.assertEqual(len(projection["e4_independent_auditor"]["files"]), 2)
        self.assertTrue(AUDIT.is_independent_auditor_source(f"{AUDIT.PROJECT_REL}/{names[-2]}"))

    def test_current_defaults_and_preseal_status_are_v11(self):
        self.assertTrue(AUDIT.V16_CONTRACT_DEFAULT.endswith("e4-0-contract-v16-v09-final.json"))
        self.assertTrue(AUDIT.V16_MAP_DEFAULT.endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v11.md"))
        self.assertTrue(AUDIT.V16_PRESEAL_DEFAULT.endswith("track-e-preseal-receipt-v16-v11.json"))
        self.assertTrue(AUDIT.V16_POSTSEAL_DEFAULT.endswith("track-e-postseal-receipt-v16-v11.json"))
        self.assertIs(AUDIT.V16_V10_FAILED_PRESEAL_ATTEMPT["pass"], False)


if __name__ == "__main__":
    unittest.main()
