from __future__ import annotations

import csv
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
SEAL = STUDY / "qualification/universe/obs-open-03a-audit"
EXPECTED_PARENT = "7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273"
EXPECTED_ROOT = "db9ffaf084b7ed6604599f0f4c1f47520646e213f9145272d41d851d73def5fc"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class ObsOpen03AAuditTests(unittest.TestCase):
    def test_root_binds_builder_parent_and_manifest(self) -> None:
        root = json.loads((SEAL / "obs_open_03a_root_receipt.json").read_text(encoding="utf-8"))
        claimed = root.pop("obs_open_03a_root_sha256")
        self.assertEqual(EXPECTED_ROOT, claimed)
        self.assertEqual(EXPECTED_ROOT, hashlib.sha256(canonical_json(root)).hexdigest())
        self.assertEqual(EXPECTED_PARENT, root["parent_discovery_root_sha256"])
        self.assertEqual(sha256(STUDY / "tools/build_obs_open_03a_audit.py"), root["audit_builder_sha256"])
        self.assertEqual(sha256(SEAL / "obs_open_03a_content_manifest.tsv"), root["content_manifest_sha256"])

    def test_all_119_estimands_receive_one_geometry_class(self) -> None:
        with (SEAL / "estimand_geometry_classification.tsv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(119, len(rows))
        self.assertTrue(all(row["source_kind"] == "MACHINE_DERIVED" for row in rows))
        self.assertEqual(
            Counter({"EMPIRICAL": 60, "OBSERVER_CONSTRAINED": 59}),
            Counter(row["geometry_class"] for row in rows),
        )
        by_template = Counter((row["template_id"], row["geometry_class"]) for row in rows)
        self.assertEqual(29, by_template[("WIDTH_DELTA_ADJACENT", "OBSERVER_CONSTRAINED")])
        self.assertEqual(30, by_template[("SIGNED_PATH_DISPLACEMENT", "OBSERVER_CONSTRAINED")])
        self.assertEqual(30, by_template[("FIRST_OUTSIDE_SIDE_BALANCE", "EMPIRICAL")])
        self.assertEqual(30, by_template[("LOCATION_BALANCE", "EMPIRICAL")])
        self.assertTrue(all(row["original_decision_changed"] == "False" for row in rows))

    def test_observer_invariants_are_verified_without_new_authority(self) -> None:
        receipt = json.loads((SEAL / "observer_invariants.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["raw_source_read"])
        self.assertEqual(0, receipt["confirmation_rows_read"])
        self.assertTrue(all(row["corpus_check"] == "PASS" for row in receipt["invariants"]))
        corpus = receipt["corpus_verification"]
        self.assertEqual(257, corpus["sessions_checked"])
        self.assertEqual(190, corpus["one_terminal_span_sessions"])
        self.assertEqual(67, corpus["two_terminal_span_sessions"])
        self.assertEqual(24, corpus["formal_signed_duplicate_estimands_beyond_group_representatives"])

    def test_resolution_floor_is_arithmetic_only(self) -> None:
        receipt = json.loads((SEAL / "inferential_resolution_receipt.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["first_holm_rejection_reachable"])
        self.assertEqual(4759, receipt["arithmetic_minimum_resamples_to_touch_first_holm_threshold"])
        self.assertEqual("BOUNDARY_ONLY_NOT_OPERATIONAL_SELECTION", receipt["arithmetic_floor_status"])
        self.assertIsNone(receipt["future_operational_resample_count"])
        self.assertFalse(receipt["post_discovery_extension_authorized"])
        self.assertFalse(receipt["confirmation_access_authorized"])

    def test_sealed_members_match_content_manifest(self) -> None:
        with (SEAL / "obs_open_03a_content_manifest.tsv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(5, len(rows))
        for row in rows:
            member = SEAL / row["path"]
            self.assertEqual(int(row["size_bytes"]), member.stat().st_size)
            self.assertEqual(row["sha256"], sha256(member))


if __name__ == "__main__":
    unittest.main()
