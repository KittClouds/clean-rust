"""Rerun only the sealed-result verifier with tolerant nested numeric comparison.

The v01 verifier already applies its 1e-12 numeric tolerance to scalar fields,
but accidentally uses exact equality for numeric values nested in CI lists.
This adapter preserves every frozen metric and prediction byte and changes only
the verifier's comparison traversal. It does not run inference or analysis.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
SOURCE = EXP / "source"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
PROVENANCE = RUN / "provenance"
PANEL = RUN / "panel-v01"
TRAIN = RUN / "training-v03"
EVAL = RUN / "evaluation-v03"
V03_ADAPTER = SOURCE / "execute_q_r2_evaluation_correction_v03.py"
ANALYZER = SOURCE / "analyze_q_r2_results_v01.py"
VERIFIER = SOURCE / "verify_q_r2_results_v01.py"
TRAINER = SOURCE / "run_q_r2_training_v01.py"
PREDICTION_TREE = EVAL / "raw-prediction-hash-tree-v01.json"
ANALYSIS_SEAL = EVAL / "q-r2-analysis-seal-v01.json"
FAILED_V03 = PROVENANCE / "q-r2-evaluation-correction-failure-v03.json"
OPENING = EVAL / "panel-opening-receipt-v01.json"
PREFLIGHT = PROVENANCE / "q-r2-replay-correction-preflight-v04.json"
EXECUTION = PROVENANCE / "q-r2-replay-correction-execution-v04.json"
AUDIT = PROVENANCE / "q-r2-replay-correction-audit-v04.json"
REPLAY_RECEIPT = EVAL / "independent-replay-verification-v02.json"
COMPLETION = PROVENANCE / "q-r2-completion-seal-v05.json"

EXPECTED = {
    "adapter_v03": "7463a302af0001b86465cef42eee26d676baba1259d4fb0e172c28cdc6920072",
    "analyzer": "3f9a87fd059f7ada026a6b9913f6ffdeb1058327322779901422037db667038a",
    "verifier": "c51073d6ab32cb9a9d8a8c9051a5123b27c7f3840f4e8712f931c640c33ee521",
    "trainer": "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0",
    "prediction_tree": "d25ef7d58e51feabd1cdde65d062e5528db4b30c90e4eb56440429a6980fc0cd",
    "analysis_seal": "ab4d0a338b5dcbeeef00b1054d3e4d57c3f4ce5ec3f1a9d185a1acb80264531c",
    "failed_v03": "ea33cab6a344f5b76f7817cd217ef961fa8f3caff7524a8b93e42213e3d00df0",
    "opening": "2c291a352b8490ddf63b298a7118ec842cce50654005f27190975d22ef13a8f2",
    "training_seal": "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84",
    "training_tree": "9708a4388923021c9b5d14b0b8dd33868902de61f568a200432f89cfb4cbaa9f",
    "raw_predictions": "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_inputs() -> dict[str, Any]:
    bound_paths = {
        "adapter_v03": V03_ADAPTER,
        "analyzer": ANALYZER,
        "verifier": VERIFIER,
        "trainer": TRAINER,
        "prediction_tree": PREDICTION_TREE,
        "analysis_seal": ANALYSIS_SEAL,
        "failed_v03": FAILED_V03,
        "opening": OPENING,
        "training_seal": TRAIN / "training-seal-manifest.json",
        "training_tree": TRAIN / "checkpoint-hash-tree.json",
        "raw_predictions": EVAL / "raw-predictions-v01.jsonl",
    }
    observed = {name: sha(path) for name, path in bound_paths.items()}
    require(observed == EXPECTED, f"sealed input identity mismatch: {observed}")
    opening = json.loads(OPENING.read_text(encoding="utf-8"))
    tree = json.loads(PREDICTION_TREE.read_text(encoding="utf-8"))
    training = json.loads((TRAIN / "training-seal-manifest.json").read_text(encoding="utf-8"))
    failure = json.loads(FAILED_V03.read_text(encoding="utf-8"))
    require(opening.get("opening_count") == 1
            and opening.get("training_panel_feedback") is False
            and opening.get("all_training_artifacts_sealed_before_open") is True,
            "original single-opening receipt changed")
    require(tree.get("status") == "Q_R2_ALL_120_CELLS_AND_960000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS"
            and tree.get("prediction_rows") == 960_000 and tree.get("cell_count") == 120,
            "prediction matrix is not the contracted sealed matrix")
    require(training.get("status") == "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED"
            and training.get("trained_checkpoint_count") == 120,
            "training seal is not the expected complete sealed tree")
    require(failure.get("opening_count") == 1 and failure.get("additional_unlock") is False
            and failure.get("prediction_file_bytes") == 1_084_223_247
            and "paired contrast 646142852/anchor_nll/ci95" in failure.get("exception", ""),
            "preserved v03 verifier failure does not match the known tolerance seam")
    require(not any(path.exists() for path in (PREFLIGHT, EXECUTION, AUDIT, REPLAY_RECEIPT, COMPLETION)),
            "refusing to overwrite a v04/v05 replay artifact")
    return {"status": "Q_R2_REPLAY_CORRECTION_PREFLIGHT_PASS",
            "bound_inputs": [{"name": name, "path": str(bound_paths[name]), "sha256": digest}
                             for name, digest in sorted(observed.items())],
            "opening_count": 1, "inference": False, "analysis_rerun": False,
            "predictions_read_for_inference": False,
            "diagnosis": "frozen verifier compares nested numeric CI lists with exact equality unlike scalar metrics"}


NUMERIC_TOLERANCE = {"rel_tol": 1e-12, "abs_tol": 1e-12}
NUMERIC_DIFFERENCES: list[dict[str, Any]] = []


def numeric_close(left: Any, right: Any) -> bool:
    return math.isclose(float(left), float(right), **NUMERIC_TOLERANCE)


def compare_nested(expected: Any, observed: Any, label: str, close: Any, need: Any) -> None:
    if isinstance(expected, dict):
        need(isinstance(observed, dict) and expected.keys() == observed.keys(),
             f"independent metric replay fields differ at {label}")
        for key, value in expected.items():
            compare_nested(value, observed[key], f"{label}/{key}", close, need)
        return
    if isinstance(expected, list):
        need(isinstance(observed, list) and len(expected) == len(observed),
             f"independent metric replay list shape differs at {label}")
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            compare_nested(left, right, f"{label}[{index}]", close, need)
        return
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        need(isinstance(observed, (float, int)) and not isinstance(observed, bool)
             and close(expected, observed, **NUMERIC_TOLERANCE),
             f"independent numeric replay mismatch {label}: {expected!r} != {observed!r}")
        if float(expected) != float(observed):
            NUMERIC_DIFFERENCES.append({"path": label, "expected": float(expected),
                                        "observed": float(observed),
                                        "absolute_difference": abs(float(expected) - float(observed))})
        return
    need(expected == observed, f"independent metric replay category mismatch {label}")


def artifact_rows(replay_receipt: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        RUN / "provenance/q-r2-instrument-package-seal-v01.json",
        PANEL / "seals/q-r2-panel-construction-seal-v01.json",
        PANEL / "seals/q-r2-feature-cache-seal-v01.json",
        PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
        RUN / "training-v01/schedule/schedule-seal.json",
        TRAIN / "common-prefix-seal-v01.json",
        TRAIN / "checkpoint-hash-tree.json",
        TRAIN / "training-seal-manifest.json",
        RUN / "provenance/q-r2-training-input-correction-preflight-v01.json",
        RUN / "provenance/q-r2-device-correction-preflight-v02b.json",
        RUN / "provenance/q-r2-path-correction-preflight-v03b.json",
        RUN / "provenance/q-r2-path-correction-completion-v03.json",
        RUN / "provenance/q-r2-evaluation-routing-preflight-v01.json",
        RUN / "provenance/q-r2-evaluation-routing-execution-v01.json",
        RUN / "provenance/q-r2-evaluation-routing-failure-v01.json",
        RUN / "provenance/q-r2-evaluation-correction-preflight-v02.json",
        RUN / "provenance/q-r2-evaluation-correction-execution-v02.json",
        RUN / "provenance/q-r2-evaluation-correction-failure-v02.json",
        V03_ADAPTER,
        SOURCE / "execute_q_r2_evaluation_correction_v02.py",
        TRAINER,
        ANALYZER,
        VERIFIER,
        Path(__file__).resolve(),
        OPENING,
        RUN / "evaluation-v01/evaluation-failure-receipt-v01.json",
        RUN / "evaluation-v02/panel-opening-receipt-v01.json",
        RUN / "evaluation-v02/evaluation-failure-receipt-v01.json",
        RUN / "evaluation-v02/raw-predictions-v01.jsonl",
        RUN / "provenance/q-r2-evaluation-correction-preflight-v03.json",
        RUN / "provenance/q-r2-evaluation-correction-execution-v03.json",
        FAILED_V03,
        PREFLIGHT,
        EXECUTION,
        AUDIT,
        REPLAY_RECEIPT,
        EVAL / "panel-opening-receipt-v01.json",
        PREDICTION_TREE,
        EVAL / "inference-receipt-v01.json",
        ANALYSIS_SEAL,
        EVAL / "raw-predictions-v01.jsonl",
        EVAL / "neighborhood-metrics-v01.jsonl",
        EVAL / "shared-neighborhood-bootstrap-plan-v01.npy",
        EVAL / "shared-moderator-seed-resample-plan-v01.npy",
        EVAL / "q-r2-analysis-v01.json",
        EVAL / "q-r2-results-v01.md",
    ]
    rows = []
    for path in paths:
        require(path.is_file(), f"completion input missing: {path}")
        rows.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    require(len({row["path"] for row in rows}) == len(rows), "duplicate path in completion tree")
    return rows


def main() -> int:
    require(not any(path.exists() for path in (PREFLIGHT, EXECUTION, AUDIT, REPLAY_RECEIPT, COMPLETION)),
            "v04 correction identity has already been used")
    preflight = verify_inputs()
    write_new(PREFLIGHT, preflight)
    write_new(EXECUTION, {"status": "Q_R2_SEALED_RESULT_REPLAY_ONLY_STARTED",
        "identity": "JEV-V08Q-R2-NESTED-NUMERIC-VERIFIER-CORRECTION-V04",
        "preflight_sha256": sha(PREFLIGHT), "adapter_sha256": sha(Path(__file__).resolve()),
        "opening_count": 1, "additional_unlock": False, "inference": False,
        "analysis_rerun": False, "metric_contract_changed": False,
        "nested_numeric_comparison": NUMERIC_TOLERANCE})
    v03 = load(V03_ADAPTER, "q_r2_v03_adapter_for_v04_replay")
    _, _, _, replay, _ = v03.load_bundle()
    replay.RECEIPT = REPLAY_RECEIPT
    def tolerant_compare(expected: dict[str, Any], observed: dict[str, Any], label: str) -> None:
        compare_nested(expected, observed, label, numeric_close, replay.need)

    replay.compare_record = tolerant_compare
    try:
        result = replay.verify()
        require(result.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS",
                f"corrected independent replay did not pass: {result}")
        max_delta = max((row["absolute_difference"] for row in NUMERIC_DIFFERENCES), default=0.0)
        require(all(row["absolute_difference"] <= max(1e-12, 1e-12 * max(abs(row["expected"]), abs(row["observed"])))
                    for row in NUMERIC_DIFFERENCES), "numeric replay difference exceeded frozen tolerance")
        audit = {"status": "Q_R2_NUMERIC_COMPARISON_CORRECTION_PASS",
            "identity": "JEV-V08Q-R2-NESTED-NUMERIC-VERIFIER-CORRECTION-V04",
            "failed_v03_receipt_sha256": sha(FAILED_V03),
            "verifier_source_sha256": sha(VERIFIER), "analysis_source_sha256": sha(ANALYZER),
            "adapter_sha256": sha(Path(__file__).resolve()),
            "correction_scope": "recursive application of existing verifier 1e-12 numeric tolerance",
            "metric_or_analysis_change": False, "predictions_or_metrics_rewritten": False,
            "opening_count": 1, "additional_unlock": False,
            "nonidentical_numeric_comparisons_within_tolerance": len(NUMERIC_DIFFERENCES),
            "maximum_absolute_numeric_difference": max_delta,
            "failed_comparison_location": "step120 paired anchor_nll ci95 for seed 646142852",
            "independent_replay_receipt_sha256": sha(REPLAY_RECEIPT)}
        write_new(AUDIT, audit)
        rows = artifact_rows(result, audit)
        root = hashlib.sha256("".join(
            f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
            for row in sorted(rows, key=lambda item: item["path"])).encode()).hexdigest()
        completion = {"status": "Q_R2_COMPLETE_RESULT_SEALED",
            "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
            "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
            "evaluation_namespace": str(EVAL), "opening_count": 1,
            "second_unlock": False, "second_opening": False,
            "original_opening_receipt_sha256": EXPECTED["opening"],
            "corrections": [
                {"identity": "Q-R2-FEATURE-CACHE-ROOT-BINDING-RECONSTRUCTION-V02",
                 "adapter_sha256": "157e397aac307269aab39396617f9aaafd131077cbb6e4bb32dbc571270905bc",
                 "scientific_contracts_changed": False, "metrics_changed": False},
                {"identity": "Q-R2-TRAINER-CONSISTENT-CHECKPOINT-STATE-HASH-V03",
                 "adapter_sha256": EXPECTED["adapter_v03"], "state_hash_source_sha256": EXPECTED["trainer"],
                 "scientific_contracts_changed": False, "metrics_changed": False},
                {"identity": "Q-R2-NESTED-NUMERIC-COMPARATOR-TOLERANCE-V04",
                 "adapter_sha256": sha(Path(__file__).resolve()), "numeric_tolerance": NUMERIC_TOLERANCE,
                 "scientific_contracts_changed": False, "metrics_changed": False}],
            "independent_replay_status": result["status"], "artifact_root_sha256": root,
            "artifact_count": len(rows), "artifacts": rows,
            "training_checkpoint_tree_root_sha256": "db75e29c1ec0295d38ff6d83eff40719f5d4209a81fb84ba45dd46be522ab461",
            "training_runs": 24, "late_continuations": 48, "evaluation_cells": 120,
            "raw_prediction_rows": 960_000, "step120_primary": True, "step100_descriptive": True,
            "seed_population_inference": False, "controller_fitting": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat()}
        write_new(COMPLETION, completion)
        print(json.dumps({"status": completion["status"], "artifact_root_sha256": root,
            "completion_seal_sha256": sha(COMPLETION), "independent_replay": result["status"],
            "numeric_tolerance_audit_sha256": sha(AUDIT), "opening_count": 1,
            "result_path": str(EVAL / "q-r2-results-v01.md")}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        failure = PROVENANCE / "q-r2-replay-correction-failure-v04.json"
        if not failure.exists():
            write_new(failure, {"status": "Q_R2_REPLAY_CORRECTION_FAILED_CLOSED",
                "identity": "JEV-V08Q-R2-NESTED-NUMERIC-VERIFIER-CORRECTION-V04",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "opening_count": 1, "additional_unlock": False,
                "prediction_sha256": sha(EVAL / "raw-predictions-v01.jsonl"),
                "analysis_sha256": sha(EVAL / "q-r2-analysis-v01.json"),
                "automatic_inference_or_analysis_retry": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
