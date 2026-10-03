from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
SEAL = STUDY / "qualification/universe/obs-open-03-discovery"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ObsOpen03DiscoverySealTests(unittest.TestCase):
    def test_root_binds_current_executor_and_frozen_modules(self) -> None:
        receipt = json.loads((SEAL / "discovery_root_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273",
            receipt["discovery_root_sha256"],
        )
        self.assertEqual(sha256(STUDY / "tools/obs_open_03_discovery.py"), receipt["executor_sha256"])
        self.assertEqual(sha256(STUDY / "tools/obs_open_02_measurement.py"), receipt["measurement_module_sha256"])
        self.assertEqual(sha256(STUDY / "tools/obs_open_02r1_familywise_rules.py"), receipt["familywise_module_sha256"])
        self.assertEqual(sha256(STUDY / "tools/obs_open_02r2_semantics.py"), receipt["r2_semantics_module_sha256"])
        self.assertEqual(sha256(SEAL / "discovery_content_manifest.tsv"), receipt["content_manifest_sha256"])

    def test_confirmation_remains_unopened_and_no_candidate_was_promoted(self) -> None:
        root = json.loads((SEAL / "discovery_root_receipt.json").read_text(encoding="utf-8"))
        firewall = json.loads((SEAL / "confirmation_firewall_receipt.json").read_text(encoding="utf-8"))
        multiplicity = json.loads((SEAL / "multiplicity_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(0, root["confirmation_rows_read"])
        self.assertEqual("FROZEN_UNOPENED", root["confirmation_status"])
        self.assertEqual(0, root["candidate_rows"])
        self.assertEqual("PASS_FROZEN_UNOPENED", firewall["status"])
        self.assertTrue(multiplicity["minimum_raw_p_exceeds_first_holm_threshold"])
        self.assertEqual(0, multiplicity["holm_pass_count"])

    def test_report_sidecar_is_exact_and_machine_derived(self) -> None:
        receipt = json.loads((SEAL / "discovery_report_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual("MACHINE_DERIVED", receipt["source_kind"])
        self.assertFalse(receipt["raw_source_read"])
        self.assertEqual(0, receipt["confirmation_rows_read"])
        self.assertEqual(sha256(STUDY / "tools/build_obs_open_03_report.py"), receipt["report_builder_sha256"])
        for member in receipt["members"]:
            path = SEAL / member["path"]
            self.assertEqual(member["bytes"], path.stat().st_size)
            self.assertEqual(member["sha256"], sha256(path))

    def test_content_manifest_names_every_d_drive_authority_member(self) -> None:
        with (SEAL / "discovery_content_manifest.tsv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(12, len(rows))
        self.assertEqual(51_964_290, int(next(row for row in rows if row["path"] == "interaction_sequence.tsv")["size_bytes"]))


if __name__ == "__main__":
    unittest.main()
