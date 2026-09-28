from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v14.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v14", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV14AuditTests(unittest.TestCase):
    def test_sealed_ancestor_closure_v06_through_v11_is_exact(self) -> None:
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        self.assertEqual(len(entries), 10)
        self.assertEqual(AUDIT.validate_transitive_inventory(entries), [])
        self.assertEqual(AUDIT.validate_v11_history(Path.cwd()), [])

    def test_every_ancestor_contract_and_seal_omission_fails(self) -> None:
        for index, missing in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            with self.subTest(member=missing["artifact_id"]):
                entries = [copy.deepcopy(x) for i, x in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY) if i != index]
                self.assertTrue(any(missing["artifact_id"] in issue for issue in AUDIT.validate_transitive_inventory(entries)))

    def test_every_ancestor_field_tamper_fails(self) -> None:
        for index, expected in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            for field in ("artifact_id", "path", "bytes", "sha256"):
                with self.subTest(member=expected["artifact_id"], field=field):
                    entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
                    entries[index][field] = -1 if field == "bytes" else "tampered"
                    self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_duplicate_and_unregistered_ancestry_fail(self) -> None:
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append(copy.deepcopy(entries[0]))
        self.assertTrue(AUDIT.validate_transitive_inventory(entries))
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append({"artifact_id": "E4_0_CONTRACT_V09_SUPERSEDED", "path": "v09", "bytes": 1, "sha256": "0" * 64})
        self.assertTrue(any("unregistered ancestry" in issue for issue in AUDIT.validate_transitive_inventory(entries)))

    def test_failed_v12_candidate_and_map_history_are_exact_unsealed_inputs(self) -> None:
        self.assertEqual(AUDIT.validate_v12_failed_preseal(Path.cwd()), [])
        self.assertEqual(AUDIT.validate_v12_failed_map_build(Path.cwd()), [])
        self.assertEqual(AUDIT.V12_FAILED_MAP_BUILD["source_map"]["bytes"], 100147)
        self.assertIsNone(AUDIT.V12_NO_CONTACT_FLAGS["final_seal"])

    def test_v13_finalizer_stop_is_exact_and_no_contact(self) -> None:
        self.assertEqual(AUDIT.validate_v13_failed_finalization(Path.cwd()), [])
        attempt = AUDIT.V14_FAILED_FINALIZATION_ATTEMPT
        self.assertFalse(attempt["pass"])
        self.assertIsNone(attempt["contract_candidate"])
        self.assertIsNone(attempt["final_seal"])
        self.assertFalse(attempt["model_contact"])
        self.assertFalse(attempt["tokenizer_contact"])

    def test_v11_final_seal_diagnostic_identity_is_complete(self) -> None:
        receipt = AUDIT.load_json(AUDIT.safe_path(Path.cwd(), AUDIT.V11_POSTSEAL_STOP["path"]))
        stored = receipt["final_seal"]
        self.assertEqual(stored["path"], AUDIT.V11_SEAL["path"])
        self.assertEqual(stored["bytes"], AUDIT.V11_SEAL["bytes"])
        self.assertEqual(stored["sha256"], AUDIT.V11_SEAL["sha256"])
        self.assertEqual(AUDIT.V12_CONTRACT["path"], AUDIT.V12_PRESEAL_STOP["path"].replace("audits/e4-0-track-e/track-e-preseal-receipt-v12.json", "contracts/e4-0-contract-v12-final.json"))

    def test_v14_reconstructs_v12_lineage_and_appends_v13_failure(self) -> None:
        root = Path.cwd()
        v12 = AUDIT.load_json(AUDIT.safe_path(root, AUDIT.V12_CONTRACT["path"]))
        prior = copy.deepcopy(v12["engineering_amendment"])
        v13 = {
            "amendment_kind": "VERSIONED_TRACK_E_AUDITOR_EXPECTATION_SCHEMA_REPAIR",
            "immediate_predecessor": {"contract": dict(AUDIT.V12_CONTRACT), "source_map": dict(AUDIT.V12_SOURCE_MAP), "preseal_receipt": dict(AUDIT.V12_PRESEAL_STOP)},
            "last_sealed_predecessor": {"contract": dict(AUDIT.V11_CONTRACT), "seal": {"path": AUDIT.V11_SEAL["path"], "bytes": AUDIT.V11_SEAL["bytes"], "sha256": AUDIT.V11_SEAL["sha256"], "seal_id": AUDIT.V11_SEAL_ID, "root_sha256": AUDIT.V11_SEAL["root_sha256"]}},
            "prior_v12_lineage": prior,
            "failed_v12_preseal_attempt": {"source_map": dict(AUDIT.V12_SOURCE_MAP), "contract": dict(AUDIT.V12_CONTRACT), "preseal_receipt": dict(AUDIT.V12_PRESEAL_STOP), "issues": list(AUDIT.V12_STOP_ISSUES), **dict(AUDIT.V12_NO_CONTACT_FLAGS)},
            "failed_v12_map_build_attempt": copy.deepcopy(AUDIT.V12_FAILED_MAP_BUILD),
            "scope": "The v13 update preserves the v06 scientific object and exact v12 candidate lineage. It repairs the independent Track E auditor's expected v11 final_seal schema and corrects the v12 source-map heading, build status, and inherited input-role wording in a new v13 map. The failed v12 preseal and map-build attempts remain bound with no contact. No scientific field or execution boundary changes; no E4 stage authorization is granted.",
        }
        expected = copy.deepcopy(v13)
        expected.update({
            "amendment_kind": "VERSIONED_FINALIZER_RECEIPT_STATUS_REGISTRY_REPAIR",
            "failed_v13_finalization_attempt": copy.deepcopy(AUDIT.V14_FAILED_FINALIZATION_ATTEMPT),
            "scope": "The v14 update preserves the v06 scientific object and exact v12 candidate lineage. It corrects only the v13 contract finalizer's accepted predecessor receipt-status registry by adding the exact registered v12 Track E PASS status, and binds the resulting v13 pre-finalization stop as history. The v13 map, source identities, and failed v12 attempts remain immutable. No scientific field or execution boundary changes; no E4 stage authorization is granted.",
        })
        self.assertEqual(AUDIT.validate_inherited_roots(root, {"engineering_amendment": expected}), [])
        for field in ("source_map", "finalizer_source", "stop_receipt", "diagnostic", "final_seal"):
            mutant = copy.deepcopy(expected)
            if field == "final_seal":
                mutant["failed_v13_finalization_attempt"][field] = {"root_sha256": "tampered"}
            else:
                mutant["failed_v13_finalization_attempt"][field] = None
            self.assertTrue(AUDIT.validate_inherited_roots(root, {"engineering_amendment": mutant}), field)

    def test_v14_source_test_registration_and_ids(self) -> None:
        self.assertEqual(AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Track E v14 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v23.json",
            "TRACK_E_SOURCE_TESTS_PASS_V14_PREMAP_SYNTHETIC_AUDITOR"))
        self.assertEqual(AUDIT.V14_CONTRACT_ID, "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V14")
        self.assertEqual(AUDIT.V14_SEAL_ID, "FAS_E4_0_CONTRACT_V14_SEAL")
        self.assertEqual(AUDIT.expected_supersedes()["contract"], AUDIT.V11_CONTRACT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
