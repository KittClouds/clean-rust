from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v13.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v13", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV13AuditTests(unittest.TestCase):
    def test_v11_seal_diagnostic_identity_fields_are_exact(self) -> None:
        root = Path.cwd()
        receipt = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V11_POSTSEAL_STOP["path"]))
        final = receipt["final_seal"]
        self.assertEqual(final["path"], AUDIT.V11_SEAL["path"])
        self.assertEqual(final["bytes"], AUDIT.V11_SEAL["bytes"])
        self.assertEqual(final["sha256"], AUDIT.V11_SEAL["sha256"])
        self.assertEqual(AUDIT.validate_v11_history(root), [])

    def test_v12_candidate_and_preseal_stop_are_exact_and_no_contact(self) -> None:
        self.assertEqual(AUDIT.validate_v12_failed_preseal(Path.cwd()), [])
        self.assertEqual(AUDIT.V12_PRESEAL_STOP["status"], "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V12")
        self.assertFalse(AUDIT.V12_NO_CONTACT_FLAGS["authorization_written"])
        self.assertFalse(AUDIT.V12_NO_CONTACT_FLAGS["model_contact"])
        self.assertIsNone(AUDIT.V12_NO_CONTACT_FLAGS["final_seal"])

    def test_failed_v12_map_build_is_bound_as_unsealed_history(self) -> None:
        self.assertEqual(AUDIT.validate_v12_failed_map_build(Path.cwd()), [])
        self.assertEqual(AUDIT.V12_FAILED_MAP_BUILD["source_map"]["bytes"], 100147)
        self.assertEqual(AUDIT.V12_FAILED_MAP_BUILD["source_map"]["sha256"], "697a438d99ae8897a3dcb390783ef8ab65c17bd1ffcca16465ffb7f3a4d74073")
        self.assertFalse(AUDIT.V12_FAILED_MAP_BUILD["pass"])
        self.assertIsNone(AUDIT.V12_FAILED_MAP_BUILD["final_seal"])

    def test_all_sealed_ancestors_v06_through_v11_are_required(self) -> None:
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        self.assertEqual(len(entries), 10)
        self.assertEqual(AUDIT.validate_transitive_inventory(entries), [])
        self.assertFalse(any("V09" in item["artifact_id"] for item in entries))

    def test_omission_of_each_ancestor_contract_or_seal_fails(self) -> None:
        for index, missing in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            with self.subTest(artifact=missing["artifact_id"]):
                entries = [copy.deepcopy(item) for i, item in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY) if i != index]
                issues = AUDIT.validate_transitive_inventory(entries)
                self.assertTrue(any(missing["artifact_id"] in issue for issue in issues), issues)

    def test_every_ancestor_identity_coordinate_tamper_fails(self) -> None:
        for index, expected in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            for field in ("artifact_id", "path", "bytes", "sha256"):
                with self.subTest(artifact=expected["artifact_id"], field=field):
                    entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
                    entries[index][field] = -1 if field == "bytes" else "tampered"
                    self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_duplicate_or_unregistered_ancestor_fails(self) -> None:
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append(copy.deepcopy(entries[0]))
        self.assertTrue(AUDIT.validate_transitive_inventory(entries))
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append({"artifact_id": "E4_0_CONTRACT_V09_SUPERSEDED", "path": "candidate-v09", "bytes": 1, "sha256": "0" * 64})
        self.assertTrue(any("unregistered ancestry" in issue for issue in AUDIT.validate_transitive_inventory(entries)))

    def test_v08_missing_pair_from_v11_stop_is_now_in_full_closure(self) -> None:
        entries = [copy.deepcopy(item) for item in AUDIT.TRANSITIVE_SEAL_INVENTORY if "V08" not in item["artifact_id"]]
        issues = AUDIT.validate_transitive_inventory(entries)
        self.assertEqual(sum("V08" in issue for issue in issues), 2)

    def test_v13_amendment_construction_preserves_all_v11_diagnostics(self) -> None:
        root = Path.cwd()
        v12_contract = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V12_CONTRACT["path"]))
        prior = v12_contract["engineering_amendment"]
        stop = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V11_POSTSEAL_STOP["path"]))
        full_final = stop["final_seal"]
        self.assertEqual(prior["failed_v11_postseal_attempt"]["final_seal"], full_final)
        self.assertEqual(full_final["bytes"], 90814)
        self.assertEqual(full_final["path"], AUDIT.V11_SEAL["path"])
        self.assertEqual(full_final["sha256"], AUDIT.V11_SEAL["sha256"])
        failed_v12 = {
            "source_map": dict(AUDIT.V12_SOURCE_MAP), "contract": dict(AUDIT.V12_CONTRACT),
            "preseal_receipt": dict(AUDIT.V12_PRESEAL_STOP), "issues": list(AUDIT.V12_STOP_ISSUES),
            **dict(AUDIT.V12_NO_CONTACT_FLAGS),
        }
        expected = {
            "amendment_kind": "VERSIONED_TRACK_E_AUDITOR_EXPECTATION_SCHEMA_REPAIR",
            "immediate_predecessor": {"contract": dict(AUDIT.V12_CONTRACT), "source_map": dict(AUDIT.V12_SOURCE_MAP), "preseal_receipt": dict(AUDIT.V12_PRESEAL_STOP)},
            "last_sealed_predecessor": {
                "contract": dict(AUDIT.V11_CONTRACT),
                "seal": {"path": AUDIT.V11_SEAL["path"], "bytes": AUDIT.V11_SEAL["bytes"], "sha256": AUDIT.V11_SEAL["sha256"], "seal_id": AUDIT.V11_SEAL_ID, "root_sha256": AUDIT.V11_SEAL["root_sha256"]},
            },
            "prior_v12_lineage": copy.deepcopy(prior), "failed_v12_preseal_attempt": failed_v12,
            "failed_v12_map_build_attempt": copy.deepcopy(AUDIT.V12_FAILED_MAP_BUILD),
            "scope": "The v13 update preserves the v06 scientific object and exact v12 candidate lineage. It repairs the independent Track E auditor's expected v11 final_seal schema and corrects the v12 source-map heading, build status, and inherited input-role wording in a new v13 map. The failed v12 preseal and map-build attempts remain bound with no contact. No scientific field or execution boundary changes; no E4 stage authorization is granted.",
        }
        self.assertEqual(AUDIT.validate_inherited_roots(root, {"engineering_amendment": expected}), [])
        for field in ("bytes", "path", "sha256"):
            mutant = copy.deepcopy(expected)
            mutant["prior_v12_lineage"]["failed_v11_postseal_attempt"]["final_seal"].pop(field)
            issues = AUDIT.validate_inherited_roots(root, {"engineering_amendment": mutant})
            self.assertTrue(issues, field)

    def test_v13_source_test_registration_and_identity(self) -> None:
        self.assertEqual(AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Track E v13 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v22.json",
            "TRACK_E_SOURCE_TESTS_PASS_V13_MAP_V13_PREMAP_SYNTHETIC_AUDITOR"))
        self.assertEqual(AUDIT.V13_CONTRACT_ID, "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V13")
        self.assertEqual(AUDIT.V13_SEAL_ID, "FAS_E4_0_CONTRACT_V13_SEAL")
        self.assertEqual(AUDIT.expected_supersedes()["contract"], AUDIT.V11_CONTRACT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
