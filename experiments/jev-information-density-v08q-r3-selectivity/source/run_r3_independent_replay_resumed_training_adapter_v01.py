"""Route the exact resumed training seal into the locked independent R3 verifier."""

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
COMPLETION = RUN / "training-v01/account-switch-resume-v01/invocations/invocation-001-completion.json"
BINDING = RUN / "training-v01/execution-fix-v03-account-switch-resume-v01/training-output-binding-v01.json"
PREDICTION_SEAL = RUN / "evaluation-v01/predictions-v01/prediction-seal-v01.json"
ANALYSIS_ROOT = RUN / "evaluation-v01/analysis-v01/analysis-root-v01.json"
VERIFIER = EXP / "source/verify_r3_independent_replay_v01.py"
ADAPTER_RECEIPTS = RUN / "independent-replay-adapter-v01"
EXPECTED_LOCK_ROOT = "adb6e7c2267bb92580c823faf58964179887a53a1a5109fa96ef32e5d097acc4"
EXPECTED_VERIFIER_SHA256 = "2e4a55858624b014a37beb48254290e7f5337283cf15251026ca72b1fc8c0c24"


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
    require(not ADAPTER_RECEIPTS.exists(), "refusing existing independent-replay adapter namespace")
    require(not (ANALYSIS_ROOT.parent / "independent-replay-receipt-v01.json").exists()
        and not (ANALYSIS_ROOT.parent / "final-result-seal-v01.json").exists(),
        "refusing an already-started independent replay")
    completion = read_json(COMPLETION)
    binding = read_json(BINDING)
    training_seal = TRAINING / "training-seal-v01.json"
    prediction = read_json(PREDICTION_SEAL)
    analysis_root = read_json(ANALYSIS_ROOT)
    verifier_sha = sha_file(VERIFIER)
    require(completion.get("status") == "R3_V03_TRAINING_COMPLETE_RESUMED_AND_SEALED"
        and binding.get("status") == "R3_EXECFIX03_RESUMED_TRAINING_OUTPUT_BOUND"
        and completion.get("panel_opened") is False,
        "resumed training provenance does not support independent replay")
    require(completion.get("training_seal_sha256") == sha_file(training_seal)
        and binding.get("training_seal_sha256") == sha_file(training_seal)
        and completion.get("training_entries_root_sha256") == binding.get("training_entries_root_sha256"),
        "resumed training seal/binding mismatch")
    require(prediction.get("status") == "R3_V03_COMPLETE_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS"
        and prediction.get("targets_read") is False and prediction.get("metrics_computed") is False
        and analysis_root.get("status") == "R3_V03_PRIMARY_ANALYSIS_COMPLETE_AWAITING_INDEPENDENT_REPLAY",
        "sealed prediction/analysis inputs are not ready for replay")
    require(verifier_sha == EXPECTED_VERIFIER_SHA256,
        "independent replay source differs from the phase-locked verifier")

    ADAPTER_RECEIPTS.mkdir(parents=False, exist_ok=False)
    preflight = {
        "identity": "JEV-V08Q-R3-INDEPENDENT-REPLAY-RESUMED-TRAINING-ADAPTER",
        "status": "SEALED_INPUTS_BOUND_BEFORE_INDEPENDENT_REPLAY",
        "adapter_source_sha256": sha_file(Path(__file__).resolve()),
        "verifier_source_sha256": verifier_sha,
        "phase_lock_root_sha256": EXPECTED_LOCK_ROOT,
        "training_completion_sha256": sha_file(COMPLETION),
        "training_binding_sha256": sha_file(BINDING),
        "training_seal_sha256": sha_file(training_seal),
        "training_entries_root_sha256": binding["training_entries_root_sha256"],
        "prediction_seal_sha256": sha_file(PREDICTION_SEAL),
        "analysis_root_sha256": sha_file(ANALYSIS_ROOT),
        "training_root": str(TRAINING),
        "panel_opening_count": 1,
        "targets_read_before_prediction_seal": False,
    }
    write_json(ADAPTER_RECEIPTS / "preflight-receipt.json", preflight)

    spec = importlib.util.spec_from_file_location("jev_r3_locked_independent_replay", VERIFIER)
    require(spec is not None and spec.loader is not None, "cannot load phase-locked independent verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TRAINING = TRAINING
    exit_code = int(module.main())
    require(exit_code == 0, f"independent replay verifier returned {exit_code}")

    replay_receipt = ANALYSIS_ROOT.parent / "independent-replay-receipt-v01.json"
    final_seal = ANALYSIS_ROOT.parent / "final-result-seal-v01.json"
    require(replay_receipt.is_file() and final_seal.is_file(),
        "independent replay did not produce both required seals")
    replay = read_json(replay_receipt)
    final = read_json(final_seal)
    require(replay.get("status") == "R3_V03_INDEPENDENT_ANALYSIS_REPLAY_PASS"
        and replay.get("scientific_metrics_recomputed_independently") is True
        and final.get("status") == "POST_REGISTERED_R3_RESULT_SEALED",
        "independent replay or final result seal status mismatch")
    write_json(ADAPTER_RECEIPTS / "completion-receipt.json", {
        **preflight,
        "status": "R3_INDEPENDENT_REPLAY_AND_FINAL_RESULT_SEALED",
        "replay_receipt_sha256": sha_file(replay_receipt),
        "independent_replay_max_abs_difference": replay.get("maximum_absolute_metric_difference"),
        "final_result_seal_sha256": sha_file(final_seal),
        "final_result_root_sha256": final.get("entries_root_sha256"),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
