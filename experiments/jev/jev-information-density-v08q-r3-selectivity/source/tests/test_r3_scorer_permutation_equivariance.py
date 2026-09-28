from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[4]
PROBE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
SPEC = importlib.util.spec_from_file_location("r3_permutation_probe", PROBE)
assert SPEC is not None and SPEC.loader is not None
PROBE_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE_MODULE
SPEC.loader.exec_module(PROBE_MODULE)


class CandidateScorerEquivarianceTests(unittest.TestCase):
    def test_candidate_score_equivariance_on_synthetic_fixture(self) -> None:
        torch.manual_seed(20260926)
        head = PROBE_MODULE.CompatibilityHead(2048, "mlp", 128).eval()
        states = torch.randn(7, 2048)
        candidates = torch.randn(7, 4, 2048)
        permutation = torch.tensor([2, 0, 3, 1])
        with torch.inference_mode():
            baseline = head(states, candidates)
            permuted = head(states, candidates[:, permutation, :])
        torch.testing.assert_close(permuted, baseline[:, permutation], rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
