from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import torch


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v02.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v02_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CorrectionV02Tests(unittest.TestCase):
    def test_in_memory_patch_moves_catalog_declaration_before_first_use(self) -> None:
        original = MODULE.TRAINER_PATH.read_text(encoding="utf-8")
        corrected = MODULE.patch_trainer_source(original)
        declaration = corrected.index(MODULE.OLD_DECLARATION)
        first_use = corrected.index("== catalog_ids", declaration)
        self.assertLess(declaration, first_use)
        self.assertEqual(corrected.count(MODULE.OLD_DECLARATION), 1)
        self.assertEqual(original.count(MODULE.OLD_DECLARATION), 1)

    def test_source_patch_fails_closed_if_frozen_context_drifted(self) -> None:
        original = MODULE.TRAINER_PATH.read_text(encoding="utf-8")
        with self.assertRaises(RuntimeError):
            MODULE.patch_trainer_source(original.replace("candidate_semantic_id", "changed_id", 1))

    def test_cache_view_preserves_tensor_identity(self) -> None:
        tensor = torch.arange(6, dtype=torch.float32).reshape(2, 3).contiguous()
        cache = {"features": tensor, "feature_key": "expected"}
        view = MODULE.adapt_state_cache(cache, "expected", expected_shape=(2, 3))
        self.assertIs(view["features"]["state"]["expected"], tensor)
        self.assertEqual(view["features"]["state"]["expected"].data_ptr(), tensor.data_ptr())


if __name__ == "__main__":
    unittest.main()
