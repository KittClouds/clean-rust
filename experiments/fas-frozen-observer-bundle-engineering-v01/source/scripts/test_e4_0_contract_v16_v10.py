"""Synthetic-only checks for the v16-v10 contract/source-closure repair."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
WORKSPACE = PROJECT.parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load("builder_v16_v10", HERE / "build_e4_0_source_map_v16_v10.py")
FINALIZER = load("finalizer_v16_v10", HERE / "finalize_e4_0_contract_v16_v10.py")
SEALER = load("sealer_v16_v09", HERE / "seal_e4_0_contract_v16_v09.py")
AUDIT = load("audit_v16_v10", PROJECT / "audits/e4-0-track-e/audit_e4_0_track_e_v16_v10.py")


class ContractV16V10Tests(unittest.TestCase):
    def test_versioned_paths_and_predecessor_map_are_exact(self):
        self.assertTrue(str(BUILDER.PRIOR_MAP).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v09.md"))
        self.assertTrue(str(BUILDER.OUTPUT).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v10.md"))
        self.assertEqual(BUILDER.digest(BUILDER.PRIOR_MAP), (127133, "fa4cf7dbdf5518e12432e9779264988128bf07fa091f55179ebf77be62317c0f"))
        self.assertTrue(FINALIZER.OUTPUT_REL.endswith("e4-0-contract-v16-v08-final.json"))
        self.assertTrue(SEALER.CONTRACT_REL.endswith("e4-0-contract-v16-v08-final.json"))
        self.assertTrue(SEALER.MAP_REL.endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v10.md"))
        self.assertTrue(SEALER.OUTPUT_REL.endswith("e4-0-contract-v16-v08-seal.json"))
        self.assertEqual(AUDIT.V16_CONTRACT_DEFAULT, FINALIZER.OUTPUT_REL)
        self.assertEqual(AUDIT.V16_MAP_DEFAULT, f"{FINALIZER.PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v10.md")

    def test_scientific_projection_remains_equal_to_v06_baseline(self):
        baseline = json.loads((PROJECT / "contracts/e4-0-contract-v06-final.json").read_text(encoding="utf-8"))
        prior = json.loads((PROJECT / "contracts/e4-0-contract-v16-v05-final.json").read_text(encoding="utf-8"))
        FINALIZER.require_scientific_invariance(prior, baseline)
        candidate = json.loads(json.dumps(baseline))
        candidate["fresh_qualification"]["performance_floor"] = 0.91
        with self.assertRaisesRegex(RuntimeError, "frozen scientific fields differ"):
            FINALIZER.require_scientific_invariance(candidate, baseline)

    def test_v08_preseal_schema_and_separate_preservation_receipt(self):
        preseal_path = WORKSPACE / FINALIZER.V16_V08_PRESEAL_RECEIPT["path"]
        preservation_path = WORKSPACE / FINALIZER.V16_V08_PRESERVATION_RECEIPT["path"]
        preseal = json.loads(preseal_path.read_text(encoding="utf-8"))
        preservation = json.loads(preservation_path.read_text(encoding="utf-8"))
        self.assertIs(preseal["population_truth_files_opened"], False)
        self.assertIs(preseal["template_or_joint_truth_opened"], False)
        for key in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertNotIn(key, preseal)
            self.assertIs(preservation[key], False)
        self.assertEqual(preseal["issues"], FINALIZER.V16_V08_PRESEAL_ISSUES)
        self.assertEqual(preservation["preseal_status"], preseal["status"])

    def test_v09_in_memory_stop_is_bound_and_no_contact(self):
        stop_path = WORKSPACE / FINALIZER.V16_V09_PREMATERIALIZATION_STOP["path"]
        stop = json.loads(stop_path.read_text(encoding="utf-8"))
        self.assertEqual(BUILDER.digest(stop_path), (2019, "00f823fcacd6eea7f75b9bce839b1972e62e1beafa4a67d5c4286554e07c3aa4"))
        self.assertEqual(stop["source_map"], FINALIZER.V16_V09_MAP_ATTEMPT)
        self.assertEqual(stop["finalizer_source"], FINALIZER.V16_V09_FINALIZER_ATTEMPT)
        self.assertEqual(stop["diagnostic"], FINALIZER.V16_V09_FINALIZER_DIAGNOSTIC)
        for key in ("contract_candidate_written", "seal_written", "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened", "population_truth_files_opened", "template_or_joint_truth_opened"):
            self.assertIs(stop[key], False)
        self.assertEqual(stop["contract_candidate"], {
            "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v07-final.json",
            "exists": False,
        })

    def test_source_and_input_closures_include_v10_and_preserved_stops(self):
        sources = BUILDER.collect_sources()
        source_paths = {rel for rel, _path, _role in sources}
        prefix = "experiments/fas-frozen-observer-bundle-engineering-v01/"
        required_sources = {
            "source/scripts/build_e4_0_source_map_v16_v10.py",
            "source/scripts/finalize_e4_0_contract_v16_v10.py",
            "source/scripts/seal_e4_0_contract_v16_v09.py",
            "source/scripts/test_e4_0_contract_v16_v10.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v10.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v10.py",
        }
        self.assertTrue({prefix + item for item in required_sources} <= source_paths)
        inputs = BUILDER.collect_inputs()
        input_paths = {rel for rel, _path, _role in inputs}
        self.assertIn(prefix + "audits/e4-0-track-e/history/pre-finalization-stop-v16-v09-v01.json", input_paths)
        self.assertIn(prefix + "audits/e4-0-track-e/track-e-preseal-receipt-v16-v08.json", input_paths)
        self.assertIn(prefix + "audits/e4-0-track-e/history/v16-v08-preseal-stop-preservation-v01.json", input_paths)

    def test_v10_role_projection_is_complete(self):
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
        rows = [{"path": "experiments/fas-frozen-observer-bundle-engineering-v01/" + name} for name in names]
        projection = AUDIT.source_role_projection(rows, {"path": "map"})
        self.assertEqual(len(projection["e4_stage_authorization_issuer"]["files"]), 2)
        self.assertEqual(len(projection["e4_contract_seal_and_source_map_tooling"]["files"]), 12)
        self.assertEqual(len(projection["e4_independent_auditor"]["files"]), 6)

    def test_current_receipt_registration_is_versioned(self):
        expected = BUILDER.CURRENT_RECEIPT_STATUSES
        self.assertEqual(expected["Contract tooling v16 v09"], "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V09")
        self.assertEqual(expected["Track E v16 pre-map v09"], "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V09")
        self.assertEqual(expected["Contract tooling v16 v10"], "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V10")
        self.assertEqual(expected["Track E v16 pre-map v10"], "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V10")


if __name__ == "__main__":
    unittest.main()
