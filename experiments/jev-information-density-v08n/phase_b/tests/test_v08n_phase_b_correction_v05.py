from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v05.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v05_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CorrectionV05Tests(unittest.TestCase):
    def test_v04_retained_attempt_forensics_recompute(self) -> None:
        parent = MODULE.load_v04()
        details = MODULE.verify_retained_attempt(parent)
        self.assertEqual(details["seed"], 20260927)
        self.assertEqual(details["arm"], "B-DUP")
        self.assertEqual(details["optimizer_steps"], 0)
        self.assertFalse(details["evaluation_access"])
        self.assertEqual(set(details["files"]), {"run-config.json", "initial-head-template.sha256"})

    def test_cache_adapter_integration_uses_exact_shared_cache_path(self) -> None:
        from unittest.mock import patch
        from types import SimpleNamespace

        parent = SimpleNamespace(adapt_state_cache=lambda cache, key: {"adapted": cache, "key": key})
        trainer = SimpleNamespace(FEATURE_KEY="mean_full@16", torch=SimpleNamespace())
        sentinel = {"features": "same-object"}
        fake_path = Path(r"D:\fixture\state-cache.pt")
        with patch.object(MODULE, "read_json", return_value={"feature_tensor": {"path": str(fake_path)}}):
            with patch.object(MODULE.torch, "load", return_value=sentinel):
                MODULE.install_cache_adapter(trainer, parent)
                loaded = trainer.torch.load(fake_path, map_location="cpu")
        self.assertIs(loaded["adapted"], sentinel)
        self.assertEqual(loaded["key"], "mean_full@16")


if __name__ == "__main__":
    unittest.main()
