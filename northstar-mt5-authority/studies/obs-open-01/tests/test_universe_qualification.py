from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "qualification" / "universe"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class UniverseQualificationTests(unittest.TestCase):
    def test_clock_transport_and_universe_are_qualified(self) -> None:
        clock = json.loads((UNIVERSE / "clock" / "clock_transport_receipt.json").read_text("utf-8"))
        universe = json.loads(
            (UNIVERSE / "universe" / "universe_qualification_receipt.json").read_text("utf-8")
        )
        self.assertEqual("QUALIFIED", clock["outcome"])
        self.assertEqual(clock["required_anchors"], clock["qualified_anchors"])
        self.assertEqual("QUALIFIED", universe["outcome"])
        self.assertEqual("FROZEN_UNOPENED", universe["confirmation_status"])
        self.assertTrue(all(universe["gates"].values()))
        self.assertFalse(clock["substantive_observer_outputs_read"])
        self.assertFalse(universe["substantive_observer_outputs_read"])

    def test_partition_is_temporal_disjoint_and_unopened(self) -> None:
        rows = read_tsv(UNIVERSE / "universe" / "partition_manifest.tsv")
        discovery = {row["session_id"] for row in rows if row["partition"] == "DISCOVERY"}
        confirmation = {row["session_id"] for row in rows if row["partition"] == "CONFIRMATION"}
        self.assertTrue(discovery)
        self.assertTrue(confirmation)
        self.assertFalse(discovery & confirmation)
        for row in rows:
            if row["partition"] == "DISCOVERY":
                self.assertLessEqual(row["civil_date"], "2025-06-30")
                self.assertEqual("NOT_APPLICABLE", row["confirmation_status"])
            else:
                self.assertGreaterEqual(row["civil_date"], "2025-07-01")
                self.assertEqual("FROZEN_UNOPENED", row["confirmation_status"])

    def test_qualification_artifacts_do_not_expose_substantive_fields(self) -> None:
        forbidden = {
            "range_high", "range_low", "range_mid", "range_width", "location",
            "grammar_event", "outside_run", "excursion", "direction", "return",
            "profit", "loss", "entry", "target", "stop",
        }
        for path in (UNIVERSE / "universe").glob("*.tsv"):
            header = path.read_text("utf-8").splitlines()[0].lower().split("\t")
            self.assertFalse(forbidden.intersection(header), path.name)

    def test_local_manifest_keeps_bulk_authority_off_git(self) -> None:
        manifest = json.loads(
            (UNIVERSE / "provenance" / "local_raw_authority_manifest.json").read_text("utf-8")
        )
        receipt = json.loads(
            (UNIVERSE / "provenance" / "local_raw_verification_receipt.json").read_text("utf-8")
        )
        self.assertEqual("D_DRIVE_LOCAL_ONLY", manifest["storage_class"])
        self.assertFalse(manifest["online_publication"])
        self.assertFalse(receipt["large_artifacts_committed_to_git"])

    def test_seal_reconstructs(self) -> None:
        seal = UNIVERSE / "seal"
        receipt = json.loads((seal / "universe_qualification_root_receipt.json").read_text("utf-8"))
        manifest = (seal / "universe_qualification_content_manifest.tsv").read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), receipt["qualification_root_sha256"])
        self.assertEqual("FROZEN_UNOPENED", receipt["substantive_results_status"])
        self.assertFalse(receipt["economic_authority"])
        self.assertFalse(receipt["trading_authority"])


if __name__ == "__main__":
    unittest.main()
