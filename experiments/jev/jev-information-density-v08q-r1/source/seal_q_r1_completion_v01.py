"""Seal Q-R1 completion provenance after independent replay passes."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
OUT = RUN / "evaluation-v01"
ANALYSIS = OUT / "q-r1-analysis-v01.json"
ANALYSIS_SEAL = OUT / "q-r1-analysis-seal-v01.json"
INFERENCE = OUT / "inference-receipt-v01.json"
TREE = OUT / "raw-prediction-hash-tree-v01.json"
VERIFY = OUT / "independent-result-verification-v01.json"
VERIFY_RECEIPT = OUT / "independent-verification-receipt-v01.json"
CONTINUATION = OUT / "continuation-v01/continuation-receipt-v01.json"
PARTIAL = OUT / "failed-attempt-01/raw-predictions-partial-v01.jsonl"
EVAL_FAILURE = OUT / "evaluation-failure-receipt-v01.json"
ANALYSIS_BINDING = OUT / "analysis-binding-correction-receipt-v01.json"
ANALYSIS_FAILURE = OUT / "analysis-failure-receipt-v01.json"
REPLAY_PREFLIGHT = OUT / "independent-replay-adapter-preflight-v01.json"
COMPLETION = OUT / "q-r1-completion-seal-v01.json"

EXPECTED = {
    "panel_root_sha256": "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53",
    "training_seal_sha256": "9a6abae90339b63c76d9f91dc7c25dcfc56d4f16d1a31b29d823be0f8fe5c9a4",
    "instrument_seal_sha256": "2cdcde6326bbf485c75d05ea3f0ad9c24dabc93937a56be93a14ad2fea033a23",
    "prediction_sha256": "380c67afb7d9fac36c2919d76327252f266975eaa4bab5a5ca4e4556b941c4ef",
    "analysis_seal_sha256": "1596b680844fd50fdf4d19721dd612b792711080e4262d247f240b3c6ee877c5",
    "verification_receipt_sha256": "44ea260cdb57eb48cc7f266ddab0b334519c8d20aa8e8bff8818da5abb2e4652",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    need(not COMPLETION.exists(), "completion seal already exists")
    inference, tree = read(INFERENCE), read(TREE)
    analysis, analysis_seal = read(ANALYSIS), read(ANALYSIS_SEAL)
    verification, verification_receipt = read(VERIFY), read(VERIFY_RECEIPT)
    continuation = read(CONTINUATION)
    need(inference.get("status") == "Q_R1_ALL_204_CELLS_INFERRED_AND_SEALED"
         and inference.get("panel_open_count") == 1 and inference.get("cell_count") == 204
         and inference.get("prediction_rows") == 1_632_000
         and sha(OUT / "raw-predictions-v01.jsonl") == EXPECTED["prediction_sha256"],
         "complete prediction matrix/opening verification failed")
    need(tree.get("panel_open_count") == 1 and tree.get("cell_count") == 204
         and tree.get("prediction_rows") == 1_632_000
         and tree.get("predictions_before_analysis") is True,
         "prediction hash tree/opening order invalid")
    need(analysis_seal.get("status") == "Q_R1_ANALYSIS_OUTPUTS_SEALED"
         and sha(ANALYSIS_SEAL) == EXPECTED["analysis_seal_sha256"]
         and analysis.get("prediction_sha256") == EXPECTED["prediction_sha256"],
         "analysis seal/result binding invalid")
    for row in analysis_seal["outputs"]:
        path = OUT / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"analysis output mismatch: {path.name}")
    need(verification.get("status") == "Q_R1_INDEPENDENT_RESULT_REPLAY_PASS"
         and verification.get("independently_replayed_cells") == 204
         and verification.get("independently_replayed_prediction_rows") == 1_632_000
         and verification.get("independently_replayed_metric_rows") == 408_000
         and verification.get("panel_open_count") == 1
         and verification_receipt.get("status") == "Q_R1_INDEPENDENT_RESULT_REPLAY_PASS"
         and sha(VERIFY_RECEIPT) == EXPECTED["verification_receipt_sha256"],
         "independent replay verification failed")
    need(continuation.get("status") == "Q_R1_PRE_METRIC_EVALUATOR_PLUMBING_CORRECTION_CONTINUATION_AUTHORIZED"
         and continuation.get("panel_open_count_before_continuation") == 1
         and continuation.get("second_panel_opening") is False
         and continuation.get("training_repeated") is False
         and sha(PARTIAL) == continuation.get("preserved_partial_prediction_sha256")
         and sha(EVAL_FAILURE) == continuation.get("original_failure_receipt_sha256"),
         "failed first evaluation attempt was not preserved/bound")
    labels = analysis["cohort_q_labels"]
    counts = labels["observed_counts_out_of_12"]
    need(counts["tunable_gain_locality_operating_point"] == 1
         and counts["stiff_coupling_pattern"] == 0
         and counts["meaningful_map_response"] == 4
         and labels["two_thirds_threshold_count"] == 8
         and not any(labels["labels"].values()), "registered cohort-label replay mismatch")

    bound_paths = [INFERENCE, TREE, ANALYSIS, ANALYSIS_SEAL, VERIFY, VERIFY_RECEIPT,
                   CONTINUATION, PARTIAL, EVAL_FAILURE, ANALYSIS_BINDING, ANALYSIS_FAILURE,
                   REPLAY_PREFLIGHT, OUT / "raw-predictions-v01.jsonl",
                   OUT / "neighborhood-metrics-v01.jsonl", OUT / "q-r1-results-v01.md",
                   OUT / "shared-bootstrap-resample-plan-v01.npy"]
    entries = [{"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha(path)}
               for path in bound_paths]
    entries_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(entries, key=lambda item: item["path"])
    ).encode()).hexdigest()
    receipt = {
        "status": "Q_R1_COMPLETE_RESULT_AND_INDEPENDENT_REPLAY_SEALED",
        "identity": "JEV-V08Q-R1-FIXED-DOSE-RESPONSE-PHENOTYPE-REPLICATION",
        "panel_root_sha256": EXPECTED["panel_root_sha256"],
        "training_seal_sha256": EXPECTED["training_seal_sha256"],
        "instrument_seal_sha256": EXPECTED["instrument_seal_sha256"],
        "prediction_sha256": EXPECTED["prediction_sha256"],
        "analysis_seal_sha256": EXPECTED["analysis_seal_sha256"],
        "independent_verification_receipt_sha256": EXPECTED["verification_receipt_sha256"],
        "panel_open_count": 1,
        "training_rerun": False,
        "evaluation_cells": 204,
        "prediction_rows": 1_632_000,
        "independently_replayed_metric_rows": 408_000,
        "observed_same_seed_counts_out_of_12": counts,
        "cohort_threshold": 8,
        "no_optimizer_seed_population_inference": True,
        "failed_plumbing_attempts_preserved": {
            "evaluation_nameerror_receipt_sha256": sha(EVAL_FAILURE),
            "first_init_cell_sha256": sha(PARTIAL),
            "analysis_hash_binding_receipt_sha256": sha(ANALYSIS_BINDING),
            "analysis_failed_attempt_receipt_sha256": sha(ANALYSIS_FAILURE),
            "independent_replay_schema_preflight_sha256": sha(REPLAY_PREFLIGHT),
        },
        "bound_completion_artifacts": entries,
        "completion_artifacts_root_sha256": entries_root,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    COMPLETION.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    with COMPLETION.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": receipt["status"],
                      "completion_root_sha256": entries_root,
                      "completion_seal_sha256": sha(COMPLETION)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
