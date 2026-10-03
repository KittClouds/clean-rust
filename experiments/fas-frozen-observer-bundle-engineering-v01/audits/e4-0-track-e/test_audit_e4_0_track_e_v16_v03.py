from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v16_v03.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v16_v03", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV16AuditTests(unittest.TestCase):
    def test_sealed_ancestor_inventory_v06_through_v11_is_exact(self) -> None:
        rows = [copy.deepcopy(row) for row in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        self.assertEqual(len(rows), 10)
        self.assertEqual(AUDIT.validate_transitive_inventory(rows), [])
        self.assertEqual(AUDIT.validate_v11_history(Path.cwd()), [])

    def test_every_sealed_ancestor_omission_fails(self) -> None:
        for index, item in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            with self.subTest(artifact=item["artifact_id"]):
                rows = [copy.deepcopy(x) for i, x in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY) if i != index]
                self.assertTrue(AUDIT.validate_transitive_inventory(rows))

    def test_every_sealed_ancestor_identity_tamper_fails(self) -> None:
        for index, item in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            for field in ("artifact_id", "path", "bytes", "sha256"):
                with self.subTest(artifact=item["artifact_id"], field=field):
                    rows = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
                    rows[index][field] = -1 if field == "bytes" else "tampered"
                    self.assertTrue(AUDIT.validate_transitive_inventory(rows))

    def test_duplicate_and_unregistered_sealed_ancestors_fail(self) -> None:
        rows = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        rows.append(copy.deepcopy(rows[0]))
        self.assertTrue(AUDIT.validate_transitive_inventory(rows))
        rows = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        rows.append({"artifact_id": "E4_0_CONTRACT_V09_SUPERSEDED", "path": "v09", "bytes": 1, "sha256": "0" * 64})
        self.assertTrue(any("unregistered ancestry" in issue for issue in AUDIT.validate_transitive_inventory(rows)))

    def test_v14_stop_preserves_exact_absent_contact_schema(self) -> None:
        self.assertEqual(AUDIT.validate_v14_failed_preseal(Path.cwd()), [])
        receipt = AUDIT.load_json(AUDIT.safe_path(Path.cwd(), AUDIT.V14_PRESEAL_STOP["path"]))
        self.assertIs(receipt["pass"], False)
        self.assertIsNone(receipt["final_seal"])
        self.assertFalse(receipt["population_truth_files_opened"])
        self.assertFalse(receipt["template_or_joint_truth_opened"])
        for key in AUDIT.V10_NO_CONTACT_FIELDS:
            self.assertNotIn(key, receipt)
        self.assertNotIn("authorization_written", AUDIT.V14_FAILED_PRESEAL_ATTEMPT)

    def test_v15_stop_is_bound_exactly_and_contact_keys_stay_absent(self) -> None:
        self.assertEqual(AUDIT.validate_v15_failed_preseal(Path.cwd()), [])
        receipt = AUDIT.load_json(AUDIT.safe_path(Path.cwd(), AUDIT.V15_PRESEAL_STOP["path"]))
        self.assertEqual(receipt["issues"], AUDIT.V15_STOP_ISSUES)
        self.assertIs(receipt["pass"], False)
        self.assertIsNone(receipt["final_seal"])
        self.assertFalse(receipt["population_truth_files_opened"])
        self.assertFalse(receipt["template_or_joint_truth_opened"])
        for key in AUDIT.V10_NO_CONTACT_FIELDS:
            self.assertNotIn(key, receipt)
            self.assertNotIn(key, AUDIT.V15_FAILED_PRESEAL_ATTEMPT)
        self.assertNotIn("seal", AUDIT.load_json(AUDIT.safe_path(Path.cwd(), AUDIT.V15_CONTRACT["path"])))

    def test_v16_amendment_flattens_v12_to_v14_and_binds_v15_stop(self) -> None:
        root = Path.cwd()
        v14 = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V14_CONTRACT["path"]))
        expected = copy.deepcopy(v14["engineering_amendment"])
        expected.update({
            "amendment_kind": AUDIT.V16_AMENDMENT_KIND,
            "immediate_predecessor": {
                "contract": copy.deepcopy(AUDIT.V15_CONTRACT),
                "source_map": copy.deepcopy(AUDIT.V15_SOURCE_MAP),
                "preseal_receipt": copy.deepcopy(AUDIT.V15_PRESEAL_STOP),
            },
            "last_sealed_predecessor": {
                "contract": copy.deepcopy(AUDIT.V11_CONTRACT),
                "seal": {
                    "path": AUDIT.V11_SEAL["path"], "bytes": AUDIT.V11_SEAL["bytes"],
                    "sha256": AUDIT.V11_SEAL["sha256"], "seal_id": AUDIT.V11_SEAL_ID,
                    "root_sha256": AUDIT.V11_SEAL["root_sha256"],
                },
            },
            "failed_v14_preseal_attempt": copy.deepcopy(AUDIT.V14_FAILED_PRESEAL_ATTEMPT),
            "failed_v15_preseal_attempt": copy.deepcopy(AUDIT.V15_FAILED_PRESEAL_ATTEMPT),
            "failed_v16_map_finalization_attempt": {
                "source_map": copy.deepcopy(AUDIT.V16_FIRST_MAP),
                "finalization_stop_receipt": copy.deepcopy(AUDIT.V16_FINALIZATION_STOP),
                "contract_candidate_written": False, "seal_written": False,
                "model_contact": False, "tokenizer_contact": False,
                "cuda_initialized": False, "labels_opened": False,
            },
            "scope": AUDIT.V16_SCOPE,
        })
        self.assertEqual(AUDIT.validate_inherited_roots(root, {"engineering_amendment": expected}), [])
        self.assertNotIn("prior_v14_lineage", expected)
        for key in ("prior_v12_lineage", "failed_v12_preseal_attempt", "failed_v12_map_build_attempt", "failed_v13_finalization_attempt"):
            self.assertIn(key, expected)

    def test_source_role_projection_covers_v15_and_all_v16_auditors(self) -> None:
        prefix = f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/"
        names = [
            "audit_e4_0_track_e_v15.py", "test_audit_e4_0_track_e_v15.py",
            "audit_e4_0_track_e_v15_v02.py", "test_audit_e4_0_track_e_v15_v02.py",
            "audit_e4_0_track_e_v16.py", "test_audit_e4_0_track_e_v16.py",
            "audit_e4_0_track_e_v16_v02.py", "test_audit_e4_0_track_e_v16_v02.py",
            "audit_e4_0_track_e_v16_v03.py", "test_audit_e4_0_track_e_v16_v03.py",
        ]
        self.assertTrue(all(AUDIT.is_independent_auditor_source(prefix + name) for name in names))
        rows = [{"path": prefix + name, "bytes": 100, "sha256": "a" * 64, "role": "independent auditor"} for name in names]
        projected = AUDIT.source_role_projection(rows, {"path": "map.md", "bytes": 1, "sha256": "b" * 64})
        bound = projected["e4_independent_auditor"]["files"]
        self.assertEqual(bound, rows)
        omitted = [row for row in rows if not row["path"].endswith("audit_e4_0_track_e_v15_v02.py")]
        tampered_projection = AUDIT.source_role_projection(omitted, projected["source_map"])
        self.assertNotEqual(tampered_projection, projected)

    def test_v07_receipt_registry_uses_the_actual_v14_receipt_path(self) -> None:
        self.assertEqual(
            AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Predecessor Track E v07 pre-map"],
            (f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v14.json", "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR"),
        )

    def test_v15_and_all_v16_receipt_attempts_are_registered(self) -> None:
        registry = AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS
        self.assertEqual(registry["Predecessor Track E v15 pre-map attempt 1"][0].endswith("track-e-source-tests-v25.json"), True)
        self.assertEqual(registry["Predecessor Track E v15 pre-map attempt 2"][0].endswith("track-e-source-tests-v27.json"), True)
        self.assertEqual(registry["Initial Authorization issuer v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v15/source-tests-v01.json", "PASS_SYNTHETIC_TESTS"))
        self.assertEqual(registry["Authorization issuer v15"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-auth-issuer-v15/source-tests-v02.json", "PASS_SYNTHETIC_TESTS_V02"))
        self.assertEqual(registry["Initial Contract tooling v15"][0].endswith("contract-tooling-source-tests-v15.json"), True)
        self.assertEqual(registry["Predecessor Contract tooling v15 v02"][0].endswith("contract-tooling-source-tests-v15-v02.json"), True)
        self.assertEqual(registry["Contract tooling v15"][0].endswith("contract-tooling-source-tests-v15-v03.json"), True)
        self.assertEqual(registry["Initial Track E v16 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v28.json",
            "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR"))
        self.assertEqual(registry["Predecessor Track E v16 pre-map v02"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v29.json",
            "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V02"))
        self.assertEqual(registry["Track E v16 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v30.json",
            "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V03"))
        self.assertEqual(registry["Authorization issuer v16"][0].endswith("source-tests-v01.json"), True)
        self.assertEqual(registry["Initial Contract tooling v16"][0].endswith("contract-tooling-source-tests-v16.json"), True)
        self.assertEqual(registry["Predecessor Contract tooling v16 v02"][0].endswith("contract-tooling-source-tests-v16-v02.json"), True)
        self.assertEqual(registry["Contract tooling v16"][0].endswith("contract-tooling-source-tests-v16-v03.json"), True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
