"""Protocol and sample tests for Q10-PF6-S1."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import select_q10_pf6_s1 as sampler  # noqa: E402


class S1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = json.loads((ROOT / "qualification/sample.json").read_text(encoding="utf-8"))
        cls.contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))

    def test_sample_is_exactly_84_and_three_per_endpoint(self) -> None:
        selected = self.sample["selected_groups"]
        self.assertEqual(len(selected), 84)
        self.assertEqual(len({tuple(item["identity"]) for item in selected}), 84)
        counts: dict[tuple[str, int], int] = {}
        for item in selected:
            endpoint = tuple(item["endpoint"])
            counts[endpoint] = counts.get(endpoint, 0) + 1
        self.assertEqual(len(counts), 28)
        self.assertEqual(set(counts.values()), {3})

    def test_selection_is_deterministic_and_slice_is_excluded(self) -> None:
        sample, _ = sampler.build_manifest()
        expected = [tuple(item["identity"]) for item in self.sample["selected_groups"]]
        actual = [tuple(item["identity"]) for item in sample["selected_groups"]]
        self.assertEqual(actual, expected)
        self.assertNotIn(("seed9731-L-tau16.json", 0, 6), actual)

    def test_contract_freezes_search_and_scope(self) -> None:
        self.assertEqual(self.contract["population"]["sample_groups"], 84)
        self.assertEqual(self.contract["population"]["groups_per_endpoint"], 3)
        self.assertEqual(self.contract["pf6"]["exploit_width"], 24)
        self.assertEqual(self.contract["pf6"]["explore_width"], 8)
        self.assertEqual(self.contract["pf6"]["maximum_rounds"], 16)
        self.assertEqual(self.contract["pf6"]["max_nodes_per_group"], 32768)
        self.assertFalse(self.contract["scope"]["behavioral_probe"])
        self.assertFalse(self.contract["scope"]["canonical_state_updated"])
        self.assertFalse(self.contract["scope"]["dh08b_authorized"])

    def test_preflight_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "scripts/preflight_q10_pf6_s1.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pool=1456 selected=84 endpoints=28", result.stdout)


if __name__ == "__main__":
    unittest.main()
