"""Route the sealed account-switch-resumed training tree into frozen R3 evaluation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\code land\clean-rust")
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
TRAINING = RUN / "training-v01/account-switch-resume-v01/artifacts-v01"
EXECUTION_FIX = RUN / "training-v01/execution-fix-v03-account-switch-resume-v01"
COMPLETION = RUN / "training-v01/account-switch-resume-v01/invocations/invocation-001-completion.json"
BINDING = EXECUTION_FIX / "training-output-binding-v01.json"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
EVALUATOR = EXP / "source/evaluate_r3_confirmatory_matrix_v01.py"
ADAPTER_RECEIPTS = RUN / "evaluation-adapter-resumed-training-v01"
EXPECTED_LOCK_ROOT = "adb6e7c2267bb92580c823faf58964179887a53a1a5109fa96ef32e5d097acc4"
EXPECTED_EVALUATOR_SHA256 = "f55cb64d11bae2a475e907522fab965a3ac8713285a163eac2f7192516b2acde"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    require(not ADAPTER_RECEIPTS.exists(), "refusing existing resumed-evaluation adapter namespace")
    require(not (RUN / "evaluation-v01").exists(), "refusing existing evaluation namespace")
    lock = read_json(LOCK)
    completion = read_json(COMPLETION)
    binding = read_json(BINDING)
    lock_sha = sha_file(LOCK)
    completion_sha = sha_file(COMPLETION)
    binding_sha = sha_file(BINDING)
    evaluator_sha = sha_file(EVALUATOR)
    adapter_sha = sha_file(Path(__file__).resolve())
    train_seal_path = TRAINING / "training-seal-v01.json"
    train_manifest_path = TRAINING / "training-manifest.json"
    train_receipts_path = TRAINING / "history-training-receipts.jsonl"

    require(lock.get("contract_bundle_root_sha256") == EXPECTED_LOCK_ROOT
        and completion.get("status") == "R3_V03_TRAINING_COMPLETE_RESUMED_AND_SEALED"
        and binding.get("status") == "R3_EXECFIX03_RESUMED_TRAINING_OUTPUT_BOUND",
        "R3 lock or resumed training status mismatch")
    require(completion.get("panel_opened") is False and completion.get("predictions_created") is False
        and completion.get("metrics_computed") is False
        and binding.get("panel_opened") is False and binding.get("predictions_created") is False
        and binding.get("metrics_computed") is False,
        "training completion records indicate premature behavioral access")
    require(completion.get("training_binding_sha256") == binding_sha
        and completion.get("training_seal_sha256") == sha_file(train_seal_path)
        and binding.get("training_seal_sha256") == sha_file(train_seal_path),
        "resumed training binding/seal identity mismatch")
    train_seal = read_json(train_seal_path)
    require(train_seal.get("status") == "R3_V03_ALL_TRAINING_TRAJECTORIES_SEALED_PRE_EVALUATION"
        and train_seal.get("panel_behavior_opened") is False
        and train_seal.get("entries_root_sha256") == completion.get("training_entries_root_sha256")
        and train_seal.get("entries_root_sha256") == binding.get("training_entries_root_sha256"),
        "resumed training artifact root or status mismatch")
    require(sha_file(EVALUATOR) == EXPECTED_EVALUATOR_SHA256,
        "frozen evaluator differs from the phase-locked source")
    locked_evaluator = next((row for row in lock.get("execution_sources", [])
        if row.get("name") == "R3 target-free evaluator"), None)
    require(locked_evaluator is not None and locked_evaluator.get("sha256") == evaluator_sha
        and Path(locked_evaluator["path"]).resolve() == EVALUATOR.resolve(),
        "phase lock does not bind the evaluator source")

    ADAPTER_RECEIPTS.mkdir(parents=False, exist_ok=False)
    preflight = {
        "identity": "JEV-V08Q-R3-RESUMED-TRAINING-EVALUATOR-ADAPTER",
        "status": "RESUMED_TRAINING_BOUND_BEFORE_PANEL_OPENING",
        "phase_lock_sha256": lock_sha,
        "phase_lock_root_sha256": EXPECTED_LOCK_ROOT,
        "adapter_source_sha256": adapter_sha,
        "evaluator_source_sha256": evaluator_sha,
        "training_binding_sha256": binding_sha,
        "training_completion_sha256": completion_sha,
        "training_seal_sha256": sha_file(train_seal_path),
        "training_manifest_sha256": sha_file(train_manifest_path),
        "training_receipt_sha256": sha_file(train_receipts_path),
        "training_entries_root_sha256": train_seal["entries_root_sha256"],
        "training_root": str(TRAINING),
        "panel_opened": False,
        "predictions_created": False,
        "metrics_computed": False,
    }
    write_json(ADAPTER_RECEIPTS / "preflight-receipt.json", preflight)

    spec = importlib.util.spec_from_file_location("jev_r3_frozen_evaluator_resumed_adapter", EVALUATOR)
    require(spec is not None and spec.loader is not None, "cannot load frozen R3 evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TRAINING = TRAINING
    exit_code = int(module.main())
    require(exit_code == 0, f"frozen R3 evaluator returned {exit_code}")

    prediction_seal = RUN / "evaluation-v01/predictions-v01/prediction-seal-v01.json"
    require(prediction_seal.is_file(), "frozen evaluator returned without prediction seal")
    prediction = read_json(prediction_seal)
    prediction_manifest = read_json(prediction_seal.parent / "prediction-manifest.json")
    require(prediction.get("status") == "R3_V03_COMPLETE_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS"
        and prediction.get("targets_read") is False and prediction.get("metrics_computed") is False,
        "prediction seal has an invalid phase status")
    completion_receipt = {
        **preflight,
        "status": "R3_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS",
        "panel_opened": True,
        "prediction_seal_sha256": sha_file(prediction_seal),
        "prediction_root_sha256": prediction.get("entries_root_sha256"),
        "prediction_manifest_sha256": prediction.get("manifest_sha256"),
        "prediction_cells": prediction_manifest.get("cells"),
        "prediction_rows": prediction_manifest.get("shape", [0])[0] * prediction_manifest.get("shape", [0, 0])[1],
        "targets_read": False,
        "metrics_computed": False,
    }
    write_json(ADAPTER_RECEIPTS / "completion-receipt.json", completion_receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
