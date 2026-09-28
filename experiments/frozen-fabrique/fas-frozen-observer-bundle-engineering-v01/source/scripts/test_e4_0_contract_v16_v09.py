"""Synthetic-only checks for the v16-v07 source-role and lineage repair tooling."""
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

BUILDER = load("builder_v16_v09", HERE / "build_e4_0_source_map_v16_v09.py")
FINALIZER = load("finalizer_v16_v09", HERE / "finalize_e4_0_contract_v16_v09.py")
SEALER = load("sealer_v16_v08", HERE / "seal_e4_0_contract_v16_v08.py")
AUDIT = load("audit_v16_v09", PROJECT / "audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py")

class ContractV16V07Tests(unittest.TestCase):
    def test_versioned_paths_and_sealed_predecessor_are_exact(self):
        self.assertTrue(str(BUILDER.PRIOR_MAP).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v08.md"))
        self.assertTrue(str(BUILDER.OUTPUT).endswith("E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v09.md"))
        self.assertEqual(BUILDER.digest(BUILDER.PRIOR_MAP), (124095, "8a69757820d9ec8935270ad3cab4005457d1f3726cfa396824e0abe33f03d1f2"))
        self.assertTrue(FINALIZER.OUTPUT_REL.endswith("e4-0-contract-v16-v07-final.json"))
        self.assertTrue(SEALER.OUTPUT_REL.endswith("e4-0-contract-v16-v07-seal.json"))
        self.assertEqual(AUDIT.V16_SEAL_ID, "FAS_E4_0_CONTRACT_V16_V07_SEAL")

    def test_scientific_projection_remains_equal_to_v06_baseline(self):
        baseline = json.loads((PROJECT / "contracts/e4-0-contract-v06-final.json").read_text(encoding="utf-8"))
        prior = json.loads((PROJECT / "contracts/e4-0-contract-v16-v05-final.json").read_text(encoding="utf-8"))
        FINALIZER.require_scientific_invariance(prior, baseline)
        candidate = json.loads(json.dumps(baseline))
        candidate["fresh_qualification"]["performance_floor"] = 0.91
        with self.assertRaisesRegex(RuntimeError, "frozen scientific fields differ"):
            FINALIZER.require_scientific_invariance(candidate, baseline)

    def test_actual_v16_v05_stop_is_bound_and_no_contact(self):
        stop_path = PROJECT / "audits/e4-0-auth-issuer-v16-v05/online-parity-precontact-stop-v01.json"
        stop = json.loads(stop_path.read_text(encoding="utf-8"))
        self.assertEqual(BUILDER.digest(stop_path), (2259, "9ab0b637c15918ca6909728d05403c37349a875e707c3d75a246485b5149da6c"))
        self.assertEqual(stop["stop_class"], "AUTHORIZER_REFERENCE_AUTHORIZATION_ID_MISMATCH")
        for key in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertIs(stop[key], False)
        self.assertFalse((PROJECT / "audits/e4-0-auth-issuer-v16-v05/online-parity-authorization-v01.json").exists())

    def test_source_and_input_closures_include_repair_and_stop_lineage(self):
        sources = BUILDER.collect_sources()
        source_paths = {rel for rel, _path, _role in sources}
        required_sources = {
            "source/scripts/issue_e4_stage_authorization_v16_v06.py",
            "source/tests/test_e4_stage_authorization_v16_v06.py",
            "source/scripts/build_e4_0_source_map_v16_v09.py",
            "source/scripts/finalize_e4_0_contract_v16_v09.py",
            "source/scripts/seal_e4_0_contract_v16_v08.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py",
        }
        prefix = "experiments/fas-frozen-observer-bundle-engineering-v01/"
        self.assertTrue({prefix + item for item in required_sources} <= source_paths)
        inputs = BUILDER.collect_inputs()
        input_paths = {rel for rel, _path, _role in inputs}
        self.assertIn(prefix + "audits/e4-0-auth-issuer-v16-v05/online-parity-precontact-stop-v01.json", input_paths)
        self.assertIn(prefix + "seals/e4-0-contract-v16-v05-seal.json", input_paths)
        self.assertIn(prefix + "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v07.md", input_paths)
        self.assertIn(prefix + "audits/e4-0-track-e/finalization-stop-v16-v07-v01.json", input_paths)
        self.assertIn(prefix + "audits/e4-0-track-e/track-e-preseal-receipt-v16-v08.json", input_paths)
        self.assertIn(prefix + "audits/e4-0-track-e/history/v16-v08-preseal-stop-preservation-v01.json", input_paths)

    def test_v09_source_role_projection_includes_latest_issuer_and_audit_tools(self):
        rows = [{"path": "experiments/fas-frozen-observer-bundle-engineering-v01/" + name} for name in (
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
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v08.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v08.py",
            "audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py",
            "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v09.py",
        )]
        projection = AUDIT.source_role_projection(rows, {"path": "map"})
        self.assertEqual(len(projection["e4_stage_authorization_issuer"]["files"]), 2)
        self.assertEqual(len(projection["e4_contract_seal_and_source_map_tooling"]["files"]), 8)
        self.assertEqual(len(projection["e4_independent_auditor"]["files"]), 4)

    def test_source_test_receipt_registration_is_versioned(self):
        expected = {track: status for track, _rel in BUILDER.CURRENT_RECEIPTS for status in [BUILDER.CURRENT_RECEIPT_STATUSES[track]]}
        self.assertEqual(expected["Authorization issuer v16 v06"], "PASS_SYNTHETIC_TESTS_V16_V06")
        self.assertEqual(expected["Contract tooling v16 v08"], "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V08")
        self.assertEqual(expected["Track E v16 pre-map v08"], "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V08")
        self.assertEqual(expected["Contract tooling v16 v09"], "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V09")
        self.assertEqual(expected["Track E v16 pre-map v09"], "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V09")

if __name__ == "__main__":
    unittest.main()
