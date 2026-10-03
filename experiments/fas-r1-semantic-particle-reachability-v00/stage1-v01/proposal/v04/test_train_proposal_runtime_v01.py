from __future__ import annotations

import importlib.util
import math
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("train_proposal_runtime_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v04_runtime_fit_test_subject", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
TRAINER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TRAINER
SPEC.loader.exec_module(TRAINER)


class RuntimeProposalMathTests(unittest.TestCase):
    def test_runtime_normalized_logits_match_f64_population_stats_and_f32_stages(self) -> None:
        base = np.asarray([0.125, -1.75, 0.875, 0.0, -2.5], dtype=np.float32)
        masked_delta = np.asarray([0.2, -0.4, 1.1, 0.8, -0.3], dtype=np.float32)

        delta_values = [float(value) for value in masked_delta]
        base_values = [float(value) for value in base]
        delta_mean = sum(delta_values) / len(delta_values)
        base_mean = sum(base_values) / len(base_values)
        delta_sd = math.sqrt(
            sum((value - delta_mean) ** 2 for value in delta_values) / len(delta_values)
        )
        base_sd = math.sqrt(
            sum((value - base_mean) ** 2 for value in base_values) / len(base_values)
        )
        delta_mean_f32 = np.float32(delta_mean)
        delta_sd_f32 = np.float32(delta_sd)
        base_sd_f32 = np.float32(base_sd)
        expected = []
        for base_value, delta_value in zip(base, masked_delta):
            centered = np.float32(delta_value - delta_mean_f32)
            normalized = np.float32(centered / delta_sd_f32)
            base_scaled = np.float32(normalized * base_sd_f32)
            adjustment = np.float32(base_scaled * np.float32(4.0))
            expected.append(np.float32(base_value + adjustment))

        actual = TRAINER.runtime_normalized_logits_numpy(base, masked_delta)
        np.testing.assert_array_equal(actual, np.asarray(expected, dtype=np.float32))

    def test_torch_runtime_mix_matches_numpy_reference(self) -> None:
        try:
            import torch
        except ImportError:
            self.skipTest("PyTorch is required by the V02 trainer")
        base = np.asarray([1.5, -0.75, 0.125, 3.0], dtype=np.float32)
        masked_delta = np.asarray([-0.4, 0.2, 0.7, 1.1], dtype=np.float32)
        expected = TRAINER.runtime_normalized_logits_numpy(base, masked_delta)
        actual = TRAINER.runtime_normalized_logits_torch(
            torch.as_tensor(base), torch.as_tensor(masked_delta), torch
        ).detach().cpu().numpy()
        np.testing.assert_array_equal(actual, expected)

    def test_zero_population_spread_falls_back_to_base_logits(self) -> None:
        base = np.asarray([1.0, 2.0, 4.0], dtype=np.float32)
        masked_delta = np.asarray([0.25, 0.25, 0.25], dtype=np.float32)
        actual = TRAINER.runtime_normalized_logits_numpy(base, masked_delta)
        np.testing.assert_array_equal(actual, base)

    def test_temperature_calibration_is_bounded_and_excludes_zero_mass(self) -> None:
        positive = TRAINER.RuntimePrediction(
            task_id="validation-task",
            family_id="validation-family",
            state_index=0,
            actions=[(0, 1), (1, 0)],
            q=np.asarray([0.25, 0.75], dtype=np.float32),
            logits=np.asarray([0.0, 1.0], dtype=np.float32),
            zero_mass=False,
            target_sha256="a" * 64,
        )
        zero = TRAINER.RuntimePrediction(
            task_id="zero-task",
            family_id="zero-family",
            state_index=0,
            actions=[(0, 1), (1, 0)],
            q=np.asarray([0.0, 0.0], dtype=np.float32),
            logits=np.asarray([0.0, 0.0], dtype=np.float32),
            zero_mass=True,
            target_sha256="b" * 64,
        )
        result = TRAINER.calibrate_runtime_temperature([positive, zero])
        self.assertEqual(result["status"], "INTERIOR_OPTIMUM")
        self.assertAlmostEqual(result["selected_inverse_temperature"], math.log(3.0), places=9)
        self.assertEqual(result["zero_mass_validation_states_excluded"], 1)
        self.assertEqual(result["validation_tasks_scored"], 1)
        self.assertGreaterEqual(result["selected_inverse_temperature"], 0.02)
        self.assertLessEqual(result["selected_inverse_temperature"], 20.0)


class QualificationBoundaryTests(unittest.TestCase):
    def test_qualification_teacher_row_is_rejected_before_target_access(self) -> None:
        row = {"family_split": "qualification"}
        with self.assertRaisesRegex(ValueError, "qualification teacher row is forbidden"):
            TRAINER.require_train_validation_split(row.get("family_split"), "teacher")

    def test_qualification_score_row_is_rejected_before_score_access(self) -> None:
        row = {"family_split": "qualification"}
        with self.assertRaisesRegex(ValueError, "qualification Rust score row is forbidden"):
            TRAINER.require_train_validation_split(row.get("family_split"), "Rust score")

    def test_score_row_schema_is_checked_before_joining(self) -> None:
        row = {
            "schema": "wrong-score-row-schema",
            "proposal_weights_sha256": "a" * 64,
            "proposal_schema": TRAINER.INITIAL_PROPOSAL_SCHEMA,
            "task_id": "train-task",
            "family_id": "train-family",
            "family_split": "train",
            "state_index": 0,
            "edit": {"entity": 0, "new_role": 1},
            "base_logit": 0.0,
            "delta_c_raw": 0.0,
            "delta_c_incidence_masked": 0.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported schema"):
                TRAINER.read_score_groups(
                    path,
                    {"train-task": "train-family"},
                    {"train-task": "train"},
                    expected_proposal_sha256="a" * 64,
                    expected_proposal_schema=TRAINER.INITIAL_PROPOSAL_SCHEMA,
                )


class ScoreReceiptProvenanceTests(unittest.TestCase):
    def test_windows_extended_and_ordinary_paths_normalize_identically(self) -> None:
        ordinary = r"D:\codex-runs\stage1\scores.jsonl"
        extended = "\\\\?\\" + ordinary
        self.assertEqual(
            TRAINER.canonical_path_key(ordinary),
            TRAINER.canonical_path_key(extended),
        )
        ordinary_unc = r"\\score-host\exports\scores.jsonl"
        extended_unc = "\\\\?\\UNC\\" + ordinary_unc[2:]
        self.assertEqual(
            TRAINER.canonical_path_key(ordinary_unc),
            TRAINER.canonical_path_key(extended_unc),
        )

    @staticmethod
    def _extended_path(path: str) -> str:
        if path.startswith("\\\\"):
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path

    def test_receipt_binds_score_dump_weights_runtime_and_split_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score_path = root / "scores.jsonl"
            weights_path = root / "weights.json"
            score_path.write_text("score rows\n", encoding="utf-8")
            weights_path.write_text("weights\n", encoding="utf-8")
            score_record = TRAINER.file_record(score_path)
            weights_record = TRAINER.file_record(weights_path)
            score_record["path"] = self._extended_path(score_record["path"])
            weights_record["path"] = self._extended_path(weights_record["path"])
            receipt = {
                "schema": TRAINER.SCORE_RECEIPT_SCHEMA,
                "status": TRAINER.SCORE_RECEIPT_STATUS,
                "output_schema": TRAINER.SCORE_ROW_SCHEMA,
                "row_count": sum(TRAINER.SCORE_ROW_COUNTS.values()),
                "state_count": sum(TRAINER.SCORE_STATE_COUNTS.values()),
                "split_row_counts": {"train": 81920, "validation": 20480},
                "output": score_record,
                "output_path": self._extended_path(str(score_path.resolve())),
                "inputs": {"proposal_weights": weights_record},
                "runtime": {
                    "proposal_sha256": weights_record["sha256"],
                    "proposal_mix_logits": {
                        "base_logit": "BaseOnlyV03",
                        "logit_incidence_masked_norm_4": "IncidenceMaskedNormalizedV03 spread_ratio=4.0",
                    },
                },
            }
            validated = TRAINER.validate_score_dump_receipt(
                receipt, score_path, weights_path
            )
            self.assertEqual(validated["row_schema"], TRAINER.SCORE_ROW_SCHEMA)
            self.assertEqual(validated["base_logit_source"], "BaseOnlyV03")
            self.assertEqual(validated["split_row_counts"]["qualification"], 0)

            receipt["output"]["bytes"] += 1
            with self.assertRaisesRegex(ValueError, "score dump differs.*bytes"):
                TRAINER.validate_score_dump_receipt(receipt, score_path, weights_path)

    def test_receipt_rejects_checkpoint_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score_path = root / "scores.jsonl"
            weights_path = root / "weights.json"
            score_path.write_text("score rows\n", encoding="utf-8")
            weights_path.write_text("weights\n", encoding="utf-8")
            score_record = TRAINER.file_record(score_path)
            weights_record = TRAINER.file_record(weights_path)
            receipt = {
                "schema": TRAINER.SCORE_RECEIPT_SCHEMA,
                "status": TRAINER.SCORE_RECEIPT_STATUS,
                "output_schema": TRAINER.SCORE_ROW_SCHEMA,
                "row_count": sum(TRAINER.SCORE_ROW_COUNTS.values()),
                "state_count": sum(TRAINER.SCORE_STATE_COUNTS.values()),
                "split_row_counts": {"train": 81920, "validation": 20480},
                "output": score_record,
                "output_path": str(score_path.resolve()),
                "inputs": {"proposal_weights": weights_record},
                "runtime": {
                    "proposal_sha256": "b" * 64,
                    "proposal_mix_logits": {
                        "base_logit": "BaseOnlyV03",
                        "logit_incidence_masked_norm_4": "IncidenceMaskedNormalizedV03 spread_ratio=4.0",
                    },
                },
            }
            with self.assertRaisesRegex(ValueError, "runtime proposal digest differs"):
                TRAINER.validate_score_dump_receipt(receipt, score_path, weights_path)


class HistoricalSourcePinTests(unittest.TestCase):
    @staticmethod
    def _fit_receipt() -> dict[str, object]:
        records: dict[str, object] = {}
        for relative, expected_sha256 in TRAINER.V04.SOURCE_PINS.items():
            source_path = TRAINER.V04.PROPOSAL_DIR / relative.removeprefix("proposal/")
            current = TRAINER.file_record(source_path)
            records[relative] = {
                **current,
                "sha256": expected_sha256,
                "bytes": 663 if relative == "proposal/src/lib.rs" else current["bytes"],
            }
        return {"pinned_source_hashes": records}

    def test_v04_pins_verify_from_fit_receipt_while_new_simulator_is_recorded(self) -> None:
        historical, audit = TRAINER.verify_historical_v04_source_pins(self._fit_receipt())
        self.assertEqual(set(historical), set(TRAINER.V04.SOURCE_PINS))
        self.assertEqual(
            set(audit["current_source_revalidated"]),
            set(TRAINER.V04.SOURCE_PINS) - {"proposal/src/lib.rs"},
        )
        current_lib = audit["current_source_hash_recorded_without_historical_comparison"][
            "proposal/src/lib.rs"
        ]["current_source"]
        self.assertEqual(
            current_lib["sha256"],
            TRAINER.file_record(TRAINER.V04.PROPOSAL_DIR / "src/lib.rs")["sha256"],
        )

    def test_historical_pin_registry_mismatch_fails_closed(self) -> None:
        receipt = self._fit_receipt()
        receipt["pinned_source_hashes"]["proposal/src/teacher.rs"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "invalid historical source pin"):
            TRAINER.verify_historical_v04_source_pins(receipt)


if __name__ == "__main__":
    unittest.main()
