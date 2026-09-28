from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v11.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v11", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TrackEV11AuditTests(unittest.TestCase):
    def test_v10_seal_and_both_postseal_stops_are_exact_and_no_contact(self) -> None:
        issues = AUDIT.validate_v10_history(Path.cwd())
        self.assertEqual(issues, [])
        self.assertEqual(AUDIT.V10_SEAL["root_sha256"], "b9eab12e1ff189c6c9fff3d63ea1e11b4f0e7a54d92a2b57accd39adee5ec5b5")
        self.assertEqual(AUDIT.V10_POSTSEAL_ATTEMPTS[1]["receipt"]["sha256"], "e4561320636702663836d39f1deee4320d465efbc00feaea0369754a6a32f221")

    def test_v10_postseal_contact_tampering_is_rejected(self) -> None:
        workspace = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for binding in (
                AUDIT.V10_CONTRACT, AUDIT.V10_SOURCE_MAP, AUDIT.V10_PRESEAL,
                {"path": AUDIT.V10_SEAL["path"], "bytes": AUDIT.V10_SEAL["bytes"], "sha256": AUDIT.V10_SEAL["sha256"]},
                *(item["receipt"] for item in AUDIT.V10_POSTSEAL_ATTEMPTS),
            ):
                source = workspace / Path(binding["path"])
                target = root / Path(binding["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            stop_path = root / Path(AUDIT.V10_POSTSEAL_ATTEMPTS[1]["receipt"]["path"])
            stop = json.loads(stop_path.read_text(encoding="utf-8"))
            stop["model_contact"] = True
            stop_path.write_text(json.dumps(stop, sort_keys=True) + "\n", encoding="utf-8")
            issues = AUDIT.validate_v10_history(root)
            self.assertTrue(any("unexpected model_contact" in issue for issue in issues), issues)

    def test_v07_transitive_inventory_omissions_fail(self) -> None:
        issues = AUDIT.validate_transitive_inventory([])
        self.assertEqual(len(issues), 2)
        self.assertIn("E4_0_CONTRACT_V07_SUPERSEDED", issues[0])
        self.assertIn("E4_0_CONTRACT_V07_SEAL_SUPERSEDED", issues[1])

    def test_repaired_v07_inventory_passes(self) -> None:
        entries = [copy.deepcopy(entry) for entry in AUDIT.V07_REQUIRED_TRANSITIVE_MEMBERS]
        self.assertEqual(AUDIT.validate_transitive_inventory(entries), [])

    def test_partial_repair_still_fails(self) -> None:
        entries = [copy.deepcopy(AUDIT.V07_REQUIRED_TRANSITIVE_MEMBERS[0])]
        issues = AUDIT.validate_transitive_inventory(entries)
        self.assertEqual(len(issues), 1)
        self.assertIn("E4_0_CONTRACT_V07_SEAL_SUPERSEDED", issues[0])

    def test_wrong_v07_path_or_identity_fails(self) -> None:
        for mutation in ("path", "sha256", "artifact_id"):
            with self.subTest(mutation=mutation):
                entries = [copy.deepcopy(item) for item in AUDIT.V07_REQUIRED_TRANSITIVE_MEMBERS]
                entries[0][mutation] = "tampered"
                self.assertTrue(AUDIT.validate_transitive_inventory(entries))

    def test_direct_supersedes_is_sealed_v10(self) -> None:
        supersedes = AUDIT.expected_supersedes()
        self.assertEqual(supersedes["contract"], AUDIT.V10_CONTRACT)
        self.assertEqual(supersedes["seal"]["root_sha256"], AUDIT.V10_SEAL["root_sha256"])
        self.assertEqual(supersedes["seal"]["contract_member_artifact_id"], "E4_0_CONTRACT_V10_FINAL")

    def test_v11_receipt_registry_binds_v11_auditor(self) -> None:
        self.assertEqual(
            AUDIT.REGISTERED_SOURCE_TEST_RECEIPTS["Track E v11 pre-map"],
            (f"{AUDIT.PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v19.json", "TRACK_E_SOURCE_TESTS_PASS_V11_PREMAP_SYNTHETIC_AUDITOR"),
        )
        self.assertEqual(AUDIT.V11_CONTRACT_ID, "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V11")
        self.assertEqual(AUDIT.V11_SEAL_ID, "FAS_E4_0_CONTRACT_V11_SEAL")

    def test_failed_v10_receipt_contact_fields_are_nullable_but_not_true(self) -> None:
        # The metadata-only v10 postseal receipts leave execution-contact fields
        # absent; the v11 amendment records explicit false wrapper flags.
        for field in AUDIT.V10_NO_CONTACT_FIELDS:
            self.assertIsNone(AUDIT.V10_NO_CONTACT_FIELDS[field])
        self.assertEqual(AUDIT.V10_POSTSEAL_ATTEMPTS[0]["final_seal"], None)
        self.assertTrue(AUDIT.V10_POSTSEAL_ATTEMPTS[1]["final_seal"]["root_match"])
        self.assertFalse(AUDIT.V10_POSTSEAL_ATTEMPTS[1]["final_seal"]["member_set_exact"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
