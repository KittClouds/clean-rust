from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("refit_vreach_runtime_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v04_runtime_vreach_refit_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REFIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REFIT
SPEC.loader.exec_module(REFIT)


def source_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256(f"source:{name}".encode("ascii")).hexdigest()
        for name in REFIT.POLICY_IDENTITY_SOURCE_FILES
    }


def policy_identity(
    weights_sha256: str,
    temperature: float,
    source_sha256: dict[str, str] | None = None,
) -> dict[str, object]:
    sources = source_sha256 or source_hashes()
    return {
        "schema": REFIT.V03_IDENTITY_SCHEMA,
        "sha256": REFIT._policy_identity_digest(
            weights_sha256,
            REFIT.V03_MIXTURE_ID,
            temperature,
            REFIT.V03_SIMULATOR_VERSION,
            sources,
        ),
        "weights_sha256": weights_sha256,
        "mixture_id": REFIT.V03_MIXTURE_ID,
        "temperature": temperature,
        "temperature_f64_bits_le_hex": struct.pack("<d", temperature).hex(),
        "simulator_version": REFIT.V03_SIMULATOR_VERSION,
        "source_sha256": sources,
    }


class PolicyIdentityContractTests(unittest.TestCase):
    def test_composite_identity_binds_weights_mix_temperature_and_sources(self) -> None:
        weights_sha = "12" * 32
        temperature = 0.9809063775890474
        sources = source_hashes()
        identity = policy_identity(weights_sha, temperature, sources)
        result = REFIT.validate_policy_identity(
            identity,
            weights_sha,
            temperature,
            str(identity["sha256"]),
            expected_source_hashes=sources,
        )
        self.assertEqual(result["sha256"], identity["sha256"])

        with self.assertRaisesRegex(ValueError, "temperature"):
            REFIT.validate_policy_identity(
                identity,
                weights_sha,
                temperature + 0.01,
                str(identity["sha256"]),
                expected_source_hashes=sources,
            )

    def test_identity_rejects_changed_source_digest(self) -> None:
        weights_sha = "34" * 32
        temperature = 1.0
        identity = policy_identity(weights_sha, temperature)
        changed_sources = dict(identity["source_sha256"])
        changed_sources["simulator_core"] = "ab" * 32
        with self.assertRaisesRegex(ValueError, "source digests"):
            REFIT.validate_policy_identity(
                identity,
                weights_sha,
                temperature,
                str(identity["sha256"]),
                expected_source_hashes=changed_sources,
            )


class WindowsReceiptPathTests(unittest.TestCase):
    def test_extended_drive_path_matches_ordinary_canonical_path(self) -> None:
        ordinary = r"D:\codex-runs\fas-r1\labels.jsonl"
        extended = r"\\?\D:\codex-runs\fas-r1\labels.jsonl"
        self.assertEqual(
            REFIT.canonical_path_key(ordinary),
            REFIT.canonical_path_key(extended),
        )

    def test_extended_unc_path_matches_ordinary_unc_path(self) -> None:
        ordinary = r"\\server\share\labels.jsonl"
        extended = r"\\?\UNC\server\share\labels.jsonl"
        self.assertEqual(
            REFIT.canonical_path_key(ordinary),
            REFIT.canonical_path_key(extended),
        )


class CalibrationContractTests(unittest.TestCase):
    def test_temperature_artifact_is_bound_to_runtime_receipt(self) -> None:
        temperature = 0.9809063775890474
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-temperature-calibration-v01.json"
            calibration = {
                "schema": REFIT.TEMPERATURE_CALIBRATION_SCHEMA,
                "status": "INTERIOR_OPTIMUM",
                "calibration_scope": "validation one-step teacher-distribution calibration",
                "search_reachability_evidence": False,
                "qualification_teacher_rows_used": False,
                "qualification_labels_or_outcomes_used": False,
                "selected_temperature": temperature,
                "selected_inverse_temperature": 1.0 / temperature,
            }
            path.write_text(json.dumps(calibration), encoding="utf-8")
            record = REFIT.file_record(path)
            runtime_receipt = {
                "temperature_calibration": {
                    "artifact_file": path.name,
                    "temperature_sha256": record["sha256"],
                    "selected_temperature": temperature,
                    "status": calibration["status"],
                    "calibration_scope": calibration["calibration_scope"],
                    "search_reachability_evidence": False,
                },
                "output_files": {path.name: record},
            }
            self.assertEqual(
                REFIT.validate_temperature_calibration(calibration, runtime_receipt, path),
                temperature,
            )

            calibration["selected_temperature"] = 1.0
            with self.assertRaisesRegex(ValueError, "temperature"):
                REFIT.validate_temperature_calibration(calibration, runtime_receipt, path)

    def test_boundary_temperature_must_fall_back_to_one(self) -> None:
        calibration = {
            "schema": REFIT.TEMPERATURE_CALIBRATION_SCHEMA,
            "status": "UPPER_BOUNDARY_FALLBACK_T1",
            "calibration_scope": "validation one-step teacher-distribution calibration",
            "search_reachability_evidence": False,
            "qualification_teacher_rows_used": False,
            "qualification_labels_or_outcomes_used": False,
            "selected_temperature": 1.0,
            "fallback_temperature": 1.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-temperature-calibration-v01.json"
            path.write_text("{}", encoding="utf-8")
            record = REFIT.file_record(path)
            receipt = {
                "temperature_calibration": {
                    "artifact_file": path.name,
                    "temperature_sha256": record["sha256"],
                    "selected_temperature": 0.9,
                    "status": calibration["status"],
                    "calibration_scope": calibration["calibration_scope"],
                    "search_reachability_evidence": False,
                },
                "output_files": {path.name: record},
            }
            with self.assertRaisesRegex(ValueError, "does not bind"):
                REFIT.validate_temperature_calibration(calibration, receipt, path)


class EngineeringTemperatureOverrideTests(unittest.TestCase):
    def valid_override(self, **updates: object) -> dict[str, object]:
        override: dict[str, object] = {
            "schema": REFIT.TEMPERATURE_ENGINEERING_OVERRIDE_SCHEMA,
            "status": "COMPLETE",
            "mode": "ADAPTIVE_ENGINEERING",
            "qualification_selection_access": True,
            "scientific_confirmation_eligible": False,
            "proposal_sha256": REFIT.ENGINEERING_OVERRIDE_PROPOSAL_SHA256,
            "selected_temperature": REFIT.ENGINEERING_OVERRIDE_SELECTED_TEMPERATURE,
            "selected_temperature_f64_bits_le_hex": REFIT.ENGINEERING_OVERRIDE_TEMPERATURE_BITS_LE_HEX,
            "source_lineage": {
                "proposal_id": "V132",
                "proposal_sha256": REFIT.ENGINEERING_OVERRIDE_PROPOSAL_SHA256,
                "qualification_trial_id": "v132-paired-one-salt-t018864",
                "qualification_trial_receipt_sha256": "ab" * 32,
                "qualification_trial_design": "paired-one-salt",
            },
        }
        override.update(updates)
        return override

    def validate(self, override: dict[str, object]) -> float:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-temperature-engineering-override-v01.json"
            path.write_text(json.dumps(override), encoding="utf-8")
            return REFIT.validate_temperature_override(
                override,
                path,
                REFIT.ENGINEERING_OVERRIDE_PROPOSAL_SHA256,
            )

    def test_accepts_explicit_v132_qualification_engineering_override(self) -> None:
        self.assertEqual(
            self.validate(self.valid_override()),
            REFIT.ENGINEERING_OVERRIDE_SELECTED_TEMPERATURE,
        )

    def test_rejects_wrong_current_or_declared_proposal_sha(self) -> None:
        override = self.valid_override(proposal_sha256="00" * 32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.json"
            path.write_text(json.dumps(override), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact current V132 proposal SHA"):
                REFIT.validate_temperature_override(
                    override, path, REFIT.ENGINEERING_OVERRIDE_PROPOSAL_SHA256
                )

    def test_rejects_missing_qualification_access_disclosure(self) -> None:
        override = self.valid_override()
        del override["qualification_selection_access"]
        with self.assertRaisesRegex(ValueError, "explicitly disclose"):
            self.validate(override)

    def test_rejects_wrong_selected_temperature_bits(self) -> None:
        override = self.valid_override(selected_temperature_f64_bits_le_hex="00" * 8)
        with self.assertRaisesRegex(ValueError, "f64 bits"):
            self.validate(override)

    def test_rejects_non_complete_status(self) -> None:
        override = self.valid_override(status="INCOMPLETE")
        with self.assertRaisesRegex(ValueError, "not COMPLETE"):
            self.validate(override)

    def test_rejects_missing_qualification_source_lineage(self) -> None:
        override = self.valid_override(source_lineage={})
        with self.assertRaisesRegex(ValueError, "does not identify V132"):
            self.validate(override)


class V03ReceiptAndRowTests(unittest.TestCase):
    def test_v03_receipt_binds_weights_labels_traces_and_request(self) -> None:
        temperature = 0.9809063775890474
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / name
                for name in ("weights.json", "labels.jsonl", "traces.jsonl", "requests.jsonl")
            }
            for name, path in paths.items():
                path.write_text(name + "\n", encoding="utf-8")
            weights_sha = hashlib.sha256(paths["weights.json"].read_bytes()).hexdigest()
            identity = policy_identity(weights_sha, temperature)
            receipt = {
                "schema": REFIT.V03_SIMULATOR_RECEIPT_SCHEMA,
                "status": "COMPLETE",
                "qualification_access_by_simulator": False,
                "policy_identity": identity,
                "request_file": REFIT.file_record(paths["requests.jsonl"]),
                "proposal_weights_file": REFIT.file_record(paths["weights.json"]),
                "label_file": REFIT.file_record(paths["labels.jsonl"]),
                "trace_file": REFIT.file_record(paths["traces.jsonl"]),
                "task_count": 1,
                "state_count": 1,
                "rollout_count": 4,
            }
            result = REFIT.validate_v03_simulator_receipt(
                receipt,
                paths["labels.jsonl"],
                paths["traces.jsonl"],
                paths["requests.jsonl"],
                paths["weights.json"],
                weights_sha,
                str(identity["sha256"]),
                temperature,
                expected_source_hashes=identity["source_sha256"],
                expected_tasks=1,
            )
            self.assertEqual(result["state_count"], 1)
            receipt["trace_file"]["sha256"] = "00" * 32
            with self.assertRaisesRegex(ValueError, "trace file differs"):
                REFIT.validate_v03_simulator_receipt(
                    receipt,
                    paths["labels.jsonl"],
                    paths["traces.jsonl"],
                    paths["requests.jsonl"],
                    paths["weights.json"],
                    weights_sha,
                    str(identity["sha256"]),
                    temperature,
                    expected_source_hashes=identity["source_sha256"],
                    expected_tasks=1,
                )

    def test_v03_dataset_state_and_rollout_use_policy_identity_not_weight_sha(self) -> None:
        weights_sha = "78" * 32
        temperature = 0.9809063775890474
        identity = policy_identity(weights_sha, temperature)
        policy_sha = str(identity["sha256"])
        row = {
            "schema": REFIT.V03_LABEL_SCHEMA,
            "task_id": "train-task",
            "proposal_sha256": policy_sha,
            "policy_identity_sha256": policy_sha,
            "policy_identity": identity,
            "states": [
                {
                    "schema": REFIT.V03_STATE_SCHEMA,
                    "task_id": "train-task",
                    "proposal_sha256": policy_sha,
                    "policy_identity_sha256": policy_sha,
                    "rollouts": [
                        {
                            "proposal_sha256": policy_sha,
                            "policy_identity_sha256": policy_sha,
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            counts = REFIT.validate_v03_label_rows(
                path,
                {"train-task"},
                {"train-task": "train"},
                weights_sha,
                policy_sha,
                identity,
                1,
                1,
            )
            self.assertEqual(counts, {"task_count": 1, "state_count": 1, "rollout_count": 1})

            row["states"][0]["rollouts"][0]["policy_identity_sha256"] = weights_sha
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nested V03 rollout identity"):
                REFIT.validate_v03_label_rows(
                    path,
                    {"train-task"},
                    {"train-task": "train"},
                    weights_sha,
                    policy_sha,
                    identity,
                    1,
                    1,
                )

    def test_qualification_dataset_is_rejected(self) -> None:
        policy_sha = "9a" * 32
        identity = {"weights_sha256": "bc" * 32}
        row = {
            "schema": REFIT.V03_LABEL_SCHEMA,
            "task_id": "qual-task",
            "states": [{"private_outcome": "must-not-be-used"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qualification V_reach labels"):
                REFIT.validate_v03_label_rows(
                    path,
                    set(),
                    {"qual-task": "qualification"},
                    str(identity["weights_sha256"]),
                    policy_sha,
                    identity,
                    1,
                    1,
                )


class RequestStartProvenanceTests(unittest.TestCase):
    def test_old_start_proposal_sha_is_separate_from_new_runtime_weights(self) -> None:
        old_start_sha = "ab" * 32
        current_runtime_sha = "cd" * 32
        request_receipt = {
            "proposal": {"weights_sha256": old_start_sha},
            "inputs": {"proposal_weights": {"sha256": old_start_sha}},
        }
        self.assertEqual(REFIT.get_request_proposal_sha256(request_receipt), old_start_sha)
        self.assertNotEqual(old_start_sha, current_runtime_sha)

    def test_runtime_fit_receipt_binds_v132_weights_and_nonuse_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal-weights-runtime-v01.json"
            weights = {
                "schema": REFIT.REQUESTS.PROPOSAL_SCHEMA,
                "architecture": REFIT.REQUESTS.PROPOSAL_ARCHITECTURE,
                "input_dim": 10,
                "hidden_dim": 16,
            }
            path.write_text(json.dumps(weights), encoding="utf-8")
            record = REFIT.file_record(path)
            receipt = {
                "schema": REFIT.RUNTIME_PROPOSAL_RECEIPT_SCHEMA,
                "status": REFIT.RUNTIME_PROPOSAL_RECEIPT_STATUS,
                "analysis_mode": "ADAPTIVE_ENGINEERING",
                "scientific_confirmation_eligible": False,
                "runtime_mix": {"name": REFIT.V03_MIXTURE_ID},
                "qualification_non_use": {
                    "teacher_rows_used_for_fit": False,
                    "score_rows_used_for_fit": False,
                    "private_labels_or_outcomes_read": False,
                    "features_used_for_fit": False,
                    "metrics_used_for_selection": False,
                    "qualification_embeddings_used_for_fit": False,
                },
                "model": {
                    "output_weights_sha256": record["sha256"],
                    "architecture": REFIT.REQUESTS.PROPOSAL_ARCHITECTURE,
                    "initial_weights_sha256": "ef" * 32,
                },
                "input_hashes": {"initial_weights": {"sha256": "ef" * 32}},
                "output_files": {path.name: record},
            }
            observed_sha, observed_weights = REFIT.validate_runtime_proposal_receipt(
                receipt, path
            )
            self.assertEqual(observed_sha, record["sha256"])
            self.assertEqual(observed_weights["schema"], REFIT.REQUESTS.PROPOSAL_SCHEMA)

            receipt["qualification_non_use"]["private_labels_or_outcomes_read"] = True
            with self.assertRaisesRegex(ValueError, "does not certify"):
                REFIT.validate_runtime_proposal_receipt(receipt, path)


if __name__ == "__main__":
    unittest.main()
