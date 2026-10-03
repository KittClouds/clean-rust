"""Synthetic-only regressions for the v16-v11 contract/source-closure repair."""
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


BUILDER = load("builder_v16_v11", HERE / "build_e4_0_source_map_v16_v11.py")
FINALIZER = load("finalizer_v16_v11", HERE / "finalize_e4_0_contract_v16_v11.py")
SEALER = load("sealer_v16_v10", HERE / "seal_e4_0_contract_v16_v10.py")
AUDIT = load("audit_v16_v11", PROJECT / "audits/e4-0-track-e/audit_e4_0_track_e_v16_v11.py")


class ContractV16V11Tests(unittest.TestCase):
    def test_versioned_paths_and_predecessor_map_are_exact(self):
        self.assertTrue(str(BUILDER.PRIOR_MAP).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v10.md"))
        self.assertTrue(str(BUILDER.OUTPUT).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v11.md"))
        self.assertEqual(BUILDER.digest(BUILDER.PRIOR_MAP), (129674, "49448f4d8e535d2f7549187d7d8596ebd7087801e541d4808ae05a48f3ea138e"))
        self.assertTrue(FINALIZER.OUTPUT_REL.endswith("e4-0-contract-v16-v09-final.json"))
        self.assertEqual(SEALER.CONTRACT_REL, FINALIZER.OUTPUT_REL)
        self.assertTrue(SEALER.MAP_REL.endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v11.md"))
        self.assertTrue(SEALER.OUTPUT_REL.endswith("e4-0-contract-v16-v09-seal.json"))
        self.assertEqual(AUDIT.V16_CONTRACT_DEFAULT, FINALIZER.OUTPUT_REL)
        self.assertEqual(AUDIT.V16_MAP_DEFAULT, SEALER.MAP_REL)
        self.assertEqual(AUDIT.V16_SEAL_DEFAULT, SEALER.OUTPUT_REL)

    def test_scientific_projection_remains_equal_to_v06_baseline(self):
        baseline = json.loads((PROJECT / "contracts/e4-0-contract-v06-final.json").read_text(encoding="utf-8"))
        prior = json.loads((PROJECT / "contracts/e4-0-contract-v16-v05-final.json").read_text(encoding="utf-8"))
        FINALIZER.require_scientific_invariance(prior, baseline)
        candidate = json.loads(json.dumps(baseline))
        candidate["fresh_qualification"]["performance_floor"] = 0.91
        with self.assertRaisesRegex(RuntimeError, "frozen scientific fields differ"):
            FINALIZER.require_scientific_invariance(candidate, baseline)

    def test_v10_preseal_stop_is_exact_and_has_no_runtime_fields(self):
        receipt_path = WORKSPACE / FINALIZER.V16_V10_PRESEAL_RECEIPT["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(BUILDER.digest(receipt_path), (161408, "f3f8c6b5b616849a5bd18d3ca04cf4b00ef039910d96e7c32167c3d59b07d2e2"))
        self.assertEqual(receipt["status"], FINALIZER.V16_V10_PRESEAL_RECEIPT["status"])
        self.assertEqual(receipt["issues"], FINALIZER.V16_V10_PRESEAL_ISSUES)
        self.assertIs(receipt["pass"], False)
        self.assertIsNone(receipt["final_seal"])
        self.assertIs(receipt["population_truth_files_opened"], False)
        self.assertIs(receipt["template_or_joint_truth_opened"], False)
        for field in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertNotIn(field, receipt)
        self.assertFalse((PROJECT / "seals/e4-0-contract-v16-v08-seal.json").exists())
        BUILDER.validate_v16_v10_preseal_stop()

    def test_v05_nested_identity_uses_receipt_projection(self):
        projected = {key: AUDIT.V16_V05_CONTRACT[key] for key in ("path", "bytes", "sha256")}
        self.assertNotIn("contract_id", projected)
        self.assertEqual(projected["sha256"], "762fdeb9705e659136ce8f7c2f448d2762c1d8129228b85125d10571ac818574")
        self.assertEqual(AUDIT.V16_V10_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]["status"], "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V16_V10")
        self.assertEqual(AUDIT.V16_V10_FAILED_PRESEAL_ATTEMPT["runtime_contact_fields_absent"], ["authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"])

    def test_source_and_input_closures_include_v10_history_and_v11_sources(self):
        sources = BUILDER.collect_sources()
        source_paths = {rel for rel, _path, _role in sources}
        prefix = "experiments/fas-frozen-observer-bundle-engineering-v01/"
        required = {
            "source/scripts/build_e4_0_source_map_v16_v10.py",
            "source/scripts/finalize_e4_0_contract_v16_v10.py",
            "source/scripts/seal_e4_0_contract_v16_v10.py",
            "source/scripts/test_e4_0_contract_v16_v10.py",
            "source/scripts/build_e4_0_source_map_v16_v11.py",
            "source/scripts/finalize_e4_0_contract_v16_v11.py",
            "source/scripts/test_e4_0_contract_v16_v11.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v11.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v11.py",
        }
        self.assertTrue({prefix + item for item in required} <= source_paths)
        self.assertIn(prefix + "source/scripts/seal_e4_0_contract_v16_v10.py", source_paths)
        inputs = BUILDER.collect_inputs()
        input_paths = {rel for rel, _path, _role in inputs}
        self.assertIn(prefix + "audits/e4-0-track-e/track-e-preseal-receipt-v16-v10.json", input_paths)
        self.assertIn(prefix + "contracts/e4-0-contract-v16-v08-final.json", input_paths)

    def test_receipt_labels_normalize_prior_tracks_and_current_statuses_are_v11(self):
        self.assertEqual(BUILDER.predecessor_track("Contract tooling v16 v10"), "Predecessor Contract tooling v16 v10")
        self.assertEqual(BUILDER.predecessor_track("Track E v16 pre-map v10"), "Predecessor Track E v16 pre-map v10")
        self.assertEqual(BUILDER.CURRENT_RECEIPT_STATUSES["Contract tooling v16 v11"], "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V11")
        self.assertEqual(BUILDER.CURRENT_RECEIPT_STATUSES["Track E v16 pre-map v11"], "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V11")

    def test_current_source_role_projection_includes_v11_repair(self):
        source_rows = [{"path": rel} for rel, _path, _role in BUILDER.collect_sources()]
        projection = AUDIT.source_role_projection(source_rows, {"path": "map"})
        tooling_paths = {row["path"] for row in projection["e4_contract_seal_and_source_map_tooling"]["files"]}
        auditor_paths = {row["path"] for row in projection["e4_independent_auditor"]["files"]}
        prefix = f"{AUDIT.PROJECT_REL}/"
        self.assertTrue({prefix + name for name in (
            "source/scripts/build_e4_0_source_map_v16_v11.py",
            "source/scripts/finalize_e4_0_contract_v16_v11.py",
            "source/scripts/seal_e4_0_contract_v16_v10.py",
            "source/scripts/test_e4_0_contract_v16_v11.py",
        )} <= tooling_paths)
        self.assertTrue({prefix + name for name in (
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v11.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v11.py",
        )} <= auditor_paths)
        self.assertTrue(AUDIT.is_independent_auditor_source(f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/audit_e4_0_track_e_v16_v11.py"))


if __name__ == "__main__":
    unittest.main()
