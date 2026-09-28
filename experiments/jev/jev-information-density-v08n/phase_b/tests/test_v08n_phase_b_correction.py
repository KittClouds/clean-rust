from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import torch


SOURCE = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v01.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_cache_adapter_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class PhaseBCorrectionTests(unittest.TestCase):
    def test_schema_view_preserves_the_identical_contiguous_tensor(self) -> None:
        tensor = torch.arange(6, dtype=torch.float32).reshape(2, 3).contiguous()
        cache = {"features": tensor, "feature_key": "test-key", "scope_content_sha256": "fixture"}
        adapted = ADAPTER.adapt_state_cache(cache, "test-key", expected_shape=(2, 3))
        self.assertIs(adapted["features"]["state"]["test-key"], tensor)
        self.assertEqual(adapted["features"]["state"]["test-key"].data_ptr(), tensor.data_ptr())
        self.assertEqual(adapted["scope_content_sha256"], "fixture")

    def test_adapter_fails_closed_on_unexpected_feature_key(self) -> None:
        tensor = torch.ones((2, 3), dtype=torch.float32)
        with self.assertRaises(RuntimeError):
            ADAPTER.adapt_state_cache({"features": tensor, "feature_key": "other"}, "expected", (2, 3))

    def test_adapter_fails_closed_on_non_tensor_container(self) -> None:
        with self.assertRaises(RuntimeError):
            ADAPTER.adapt_state_cache({"features": {"state": torch.ones((2, 3))}, "feature_key": "expected"}, "expected", (2, 3))


if __name__ == "__main__":
    unittest.main()
