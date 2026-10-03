from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v12.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v12", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV12AuditTests(unittest.TestCase):
    def test_v11_seal_and_failed_stop_are_exact_and_truth_closed(self) -> None:
        self.assertEqual(AUDIT.validate_v11_history(Path.cwd()), [])
        self.assertEqual(AUDIT.V11_SEAL["root_sha256"], "dc7ec0731a6f637bd8aa6416bd74aba8e074e8bf0c936a1bda830e79c0afa6c3")
        self.assertEqual(AUDIT.V11_POSTSEAL_STOP["sha256"], "09822f935ef94c9307f3a9754dc8a408294de0f77832b7ef09f8e47d56272aa9")

    def test_transitive_inventory_has_all_sealed_ancestors_v06_through_v11(self) -> None:
        self.assertEqual(len(AUDIT.TRANSITIVE_SEAL_INVENTORY), 10)
        self.assertEqual(AUDIT.validate_transitive_inventory([copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]), [])

    def test_omission_of_each_contract_or_seal_is_rejected(self) -> None:
        for index, missing in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            with self.subTest(artifact=missing["artifact_id"]):
                entries = [copy.deepcopy(x) for i, x in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY) if i != index]
                issues = AUDIT.validate_transitive_inventory(entries)
                self.assertTrue(any(missing["artifact_id"] in issue for issue in issues), issues)

    def test_every_registered_identity_coordinate_is_bound(self) -> None:
        for index, expected in enumerate(AUDIT.TRANSITIVE_SEAL_INVENTORY):
            for field in ("artifact_id", "path", "bytes", "sha256"):
                with self.subTest(artifact=expected["artifact_id"], field=field):
                    entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
                    entries[index][field] = "tampered" if field != "bytes" else -1
                    issues = AUDIT.validate_transitive_inventory(entries)
                    self.assertTrue(any(expected["artifact_id"] in issue for issue in issues), issues)

    def test_unregistered_or_duplicate_ancestry_is_rejected(self) -> None:
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append({"artifact_id": "E4_0_CONTRACT_V09_SUPERSEDED", "path": "contracts/v09", "bytes": 1, "sha256": "0" * 64})
        self.assertTrue(any("unregistered ancestry" in x for x in AUDIT.validate_transitive_inventory(entries)))
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY]
        entries.append(copy.deepcopy(entries[0]))
        self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_v08_pair_is_required_despite_v11_stop(self) -> None:
        entries = [copy.deepcopy(x) for x in AUDIT.TRANSITIVE_SEAL_INVENTORY if "V08" not in x["artifact_id"]]
        issues = AUDIT.validate_transitive_inventory(entries)
        self.assertEqual(sum("V08" in issue for issue in issues), 2)

    def test_direct_supersedes_is_sealed_v11(self) -> None:
        expected = AUDIT.expected_supersedes()
        self.assertEqual(expected["contract"], AUDIT.V11_CONTRACT)
        self.assertEqual(expected["seal"]["root_sha256"], AUDIT.V11_SEAL["root_sha256"])
        self.assertEqual(expected["seal"]["contract_member_artifact_id"], "E4_0_CONTRACT_V11_FINAL")

    def test_v12_registry_binds_new_auditor_receipt(self) -> None:
        self.assertEqual(AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Track E v12 pre-map"], (
            f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v20.json",
            "TRACK_E_SOURCE_TESTS_PASS_V12_PREMAP_SYNTHETIC_AUDITOR"))
        self.assertEqual(AUDIT.V12_CONTRACT_ID, "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V12")
        self.assertEqual(AUDIT.V12_SEAL_ID, "FAS_E4_0_CONTRACT_V12_SEAL")

    def test_v11_stop_contacts_are_not_promoted(self) -> None:
        self.assertTrue(all(value is None for value in AUDIT.V11_NO_CONTACT_FIELDS.values()))
        self.assertEqual(len(AUDIT.V11_STOP_ISSUES), 3)
        self.assertEqual(AUDIT.V11_NO_CONTACT_FIELDS["model_contact"], None)


if __name__ == "__main__":
    unittest.main(verbosity=2)

