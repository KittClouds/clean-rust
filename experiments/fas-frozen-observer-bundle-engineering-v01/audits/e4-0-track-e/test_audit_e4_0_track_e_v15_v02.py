from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v15_v02.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v15_v02", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV15V02AuditTests(unittest.TestCase):
    def test_sealed_ancestor_closure_v06_through_v11_is_exact(self) -> None:
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        self.assertEqual(len(entries), 10)
        self.assertEqual(AUDIT.validate_transitive_inventory(entries), [])
        self.assertEqual(AUDIT.validate_v11_history(Path.cwd()), [])

    def test_each_transitive_ancestor_omission_fails(self) -> None:
        for index, missing in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            with self.subTest(member=missing["artifact_id"]):
                entries = [copy.deepcopy(item) for i, item in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY) if i != index]
                self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_each_transitive_ancestor_identity_tamper_fails(self) -> None:
        for index, expected in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            for field in ("artifact_id", "path", "bytes", "sha256"):
                with self.subTest(member=expected["artifact_id"], field=field):
                    entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
                    entries[index][field] = -1 if field == "bytes" else "tampered"
                    self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_duplicate_and_unregistered_ancestors_fail(self) -> None:
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append(copy.deepcopy(entries[0]))
        self.assertTrue(AUDIT.validate_transitive_inventory(entries))
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append({"artifact_id": "E4_0_CONTRACT_V09_SUPERSEDED", "path": "v09", "bytes": 1, "sha256": "0" * 64})
        self.assertTrue(any("unregistered ancestry" in issue for issue in AUDIT.validate_transitive_inventory(entries)))

    def test_v14_failed_preseal_is_exact_and_truth_closed(self) -> None:
        self.assertEqual(AUDIT.validate_v14_failed_preseal(Path.cwd()), [])
        receipt = AUDIT.load_json(AUDIT.safe_path(Path.cwd(), AUDIT.V14_PRESEAL_STOP["path"]))
        for field in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertNotIn(field, receipt)
        self.assertFalse(receipt["population_truth_files_opened"])
        self.assertFalse(receipt["template_or_joint_truth_opened"])
        self.assertIsNone(receipt["final_seal"])
        attempt = AUDIT.V14_FAILED_PRESEAL_ATTEMPT
        self.assertFalse(attempt["pass"])
        self.assertIsNone(attempt["final_seal"])
        for field in ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized", "gpu_lease_acquired", "feature_cache_created", "labels_opened"):
            self.assertFalse(attempt[field])
        self.assertEqual(len(attempt["issues"]), 5)

    def test_v12_failed_preseal_uses_receipt_schema_not_contract_metadata(self) -> None:
        root = Path.cwd()
        candidate = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V14_CONTRACT["path"]))
        actual = candidate["engineering_amendment"]["failed_v12_preseal_attempt"]["contract"]
        self.assertEqual(set(actual), {"path", "bytes", "sha256"})
        self.assertNotIn("contract_id", actual)
        self.assertEqual(AUDIT.validate_inherited_roots(root, {"engineering_amendment": self.expected_v15_amendment(root)}), [])

    def expected_v15_amendment(self, root: Path) -> dict:
        v14 = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V14_CONTRACT["path"]))
        amendment = copy.deepcopy(v14["engineering_amendment"])
        amendment["failed_v12_preseal_attempt"]["contract"] = {
            key: AUDIT.V12_CONTRACT[key] for key in ("path", "bytes", "sha256")
        }
        amendment["amendment_kind"] = "VERSIONED_TRACK_E_AUDITOR_AND_SOURCE_MAP_INPUT_CLOSURE_REPAIR"
        amendment["failed_v14_preseal_attempt"] = copy.deepcopy(AUDIT.V14_FAILED_PRESEAL_ATTEMPT)
        amendment["scope"] = (
            "The v15 update preserves the v06 scientific object and complete v14/v13/v12 lineage. "
            "It corrects only the independent Track E v14 auditor's receipt registry to the exact preserved "
            "issuer-v13/tooling-v13 and tooling-v14 receipt identities, corrects the v12 preseal nested contract "
            "identity schema, and adds the v13 finalizer source as a frozen input in a new v15 source map. "
            "The failed v14 preseal is bound exactly; no scientific field or execution boundary changes; "
            "no E4 stage authorization is granted."
        )
        return amendment

    def test_failed_v13_finalizer_preserves_stop_receipt_key(self) -> None:
        root = Path.cwd()
        self.assertEqual(AUDIT.validate_v13_failed_finalization(root), [])
        attempt = AUDIT.V14_FAILED_FINALIZATION_ATTEMPT
        self.assertIn("stop_receipt", attempt)
        self.assertNotIn("receipt", attempt)
        self.assertEqual(attempt["stop_receipt"], AUDIT.V13_FAILED_FINALIZATION["receipt"])

    def test_predecessor_receipt_registry_uses_actual_v13_v14_identities(self) -> None:
        registry = AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS
        self.assertEqual(registry["Predecessor Authorization issuer v13"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v13/source-tests-v02.json", "PASS_SYNTHETIC_TESTS"))
        self.assertEqual(registry["Predecessor Contract tooling v13"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v13.json",
            "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS"))
        self.assertEqual(registry["Predecessor Contract tooling v14"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v14.json",
            "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS"))
        self.assertEqual(registry["Predecessor Authorization issuer v14"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v14/source-tests-v01.json",
            "PASS_SYNTHETIC_TESTS"))
        self.assertEqual(registry["Initial Track E v15 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v25.json",
            "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V02"))
        self.assertEqual(registry["Track E v15 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v27.json",
            "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V03"))
        self.assertEqual(registry["Initial Contract tooling v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v15.json",
            "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS"))
        self.assertEqual(registry["Predecessor Contract tooling v15 v02"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v15-v02.json",
            "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02"))
        self.assertEqual(registry["Contract tooling v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v15-v03.json",
            "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V03"))
        self.assertEqual(registry["Initial Authorization issuer v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v15/source-tests-v01.json", "PASS_SYNTHETIC_TESTS"))
        self.assertEqual(registry["Authorization issuer v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v15/source-tests-v02.json", "PASS_SYNTHETIC_TESTS_V02"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
