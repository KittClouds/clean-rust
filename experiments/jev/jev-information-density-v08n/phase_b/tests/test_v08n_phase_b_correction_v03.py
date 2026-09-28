from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ENTRYPOINT = Path(__file__).resolve().parents[1] / "train_phase_b_corrected_v03.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_corrected_entrypoint_v03_tests", ENTRYPOINT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeTrainer:
    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual

    def verify_runtime(self, contract: dict) -> None:
        if contract["runtime_environment"]["device"] != self.expected:
            raise RuntimeError("frozen runtime identity mismatch")


class CorrectionV03Tests(unittest.TestCase):
    def test_runtime_name_maps_only_after_identity_verification(self) -> None:
        trainer = FakeTrainer(MODULE.DEVICE_IDENTITY, MODULE.DEVICE_IDENTITY)
        contract = {"runtime_environment": {"device": MODULE.DEVICE_IDENTITY}}
        MODULE.runtime_device_mapping(trainer)
        with patch.object(MODULE.torch.cuda, "get_device_name", return_value=MODULE.DEVICE_IDENTITY):
            trainer.verify_runtime(contract)
        self.assertEqual(contract["runtime_environment"]["device"], "cuda:0")

    def test_runtime_mapping_fails_closed_on_hardware_identity_drift(self) -> None:
        trainer = FakeTrainer(MODULE.DEVICE_IDENTITY, MODULE.DEVICE_IDENTITY)
        contract = {"runtime_environment": {"device": MODULE.DEVICE_IDENTITY}}
        MODULE.runtime_device_mapping(trainer)
        with patch.object(MODULE.torch.cuda, "get_device_name", return_value="different GPU"):
            with self.assertRaises(RuntimeError):
                trainer.verify_runtime(contract)
        self.assertEqual(contract["runtime_environment"]["device"], MODULE.DEVICE_IDENTITY)


if __name__ == "__main__":
    unittest.main()
