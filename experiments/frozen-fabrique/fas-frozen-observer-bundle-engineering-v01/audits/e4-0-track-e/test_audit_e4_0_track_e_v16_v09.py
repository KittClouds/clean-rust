from pathlib import Path
import importlib.util
import unittest

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v16_v09.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v16_v09", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import independent v16-v09 auditor")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
PROJECT = SCRIPT.parents[2]

class IndependentAuditV16V09Tests(unittest.TestCase):
    def test_actual_v16_v05_authorization_stop_is_exact_and_no_contact(self):
        identity = AUDIT.V16_V05_AUTH_STOP
        root = PROJECT.parents[1]
        path = AUDIT.safe_path(root, identity["path"])
        self.assertEqual(AUDIT.digest(path), (identity["bytes"], identity["sha256"]))
        stop = AUDIT.load_json(path)
        self.assertEqual(stop["stop_class"], AUDIT.V16_V05_AUTH_STOP_CLASS)
        self.assertEqual(stop["diagnostic"], AUDIT.V16_V05_AUTH_DIAGNOSTIC)
        for field in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertIs(stop[field], False)
        self.assertFalse(AUDIT.safe_path(root, AUDIT.V16_V05_AUTH_OUTPUT["path"]).exists())

    def test_historical_and_current_authorization_identities_are_distinct(self):
        issuer = PROJECT / "source/scripts/issue_e4_stage_authorization_v16_v06.py"
        source = issuer.read_text(encoding="utf-8")
        self.assertIn('V06_REFERENCE_AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01"', source)
        self.assertIn('AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V06"', source)

    def test_current_source_roles_include_the_versioned_repair(self):
        rows = [
            {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/issue_e4_stage_authorization_v16_v06.py"},
            {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e4_stage_authorization_v16_v06.py"},
        ]
        projection = AUDIT.source_role_projection(rows, {"path": "map"})
        self.assertEqual(len(projection["e4_stage_authorization_issuer"]["files"]), 2)
        auditor_paths = (
            "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py",
            "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v09.py",
        )
        self.assertTrue(all(AUDIT.is_independent_auditor_source(path) for path in auditor_paths))

    def test_v05_stop_references_match_the_serialized_path_bytes_hash_schema(self):
        root = PROJECT.parents[1]
        stop = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V16_V05_AUTH_STOP["path"]))
        expected_contract = {key: AUDIT.V16_V05_CONTRACT[key] for key in ("path", "bytes", "sha256")}
        self.assertEqual(stop["contract"], expected_contract)
        self.assertEqual(
            AUDIT.V16_V05_FAILED_AUTHORIZATION_ATTEMPT["contract"],
            expected_contract,
        )

    def test_v07_stop_keeps_original_no_candidate_result_while_later_candidate_is_preserved(self):
        root = PROJECT.parents[1]
        stop = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V16_V07_FINALIZATION_STOP["path"]))
        self.assertEqual(
            stop["contract_candidate"],
            {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v06-final.json", "exists": False},
        )
        candidate = AUDIT.safe_path(root, AUDIT.V16_V08_CONTRACT_CANDIDATE["path"])
        self.assertTrue(candidate.is_file())
        self.assertEqual(AUDIT.digest(candidate), (AUDIT.V16_V08_CONTRACT_CANDIDATE["bytes"], AUDIT.V16_V08_CONTRACT_CANDIDATE["sha256"]))
        self.assertFalse(AUDIT.safe_path(root, "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v06-seal.json").exists())

    def test_v06_replacement_receipt_registry_is_explicit(self):
        self.assertEqual(
            AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Authorization issuer v16 v06"],
            ("experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v06/source-tests-v01.json", "PASS_SYNTHETIC_TESTS_V16_V06"),
        )
        self.assertEqual(AUDIT.V16_SEAL_ID, "FAS_E4_0_CONTRACT_V16_V07_SEAL")
        self.assertTrue(AUDIT.V16_CONTRACT_DEFAULT.endswith("e4-0-contract-v16-v07-final.json"))

if __name__ == "__main__":
    unittest.main()
