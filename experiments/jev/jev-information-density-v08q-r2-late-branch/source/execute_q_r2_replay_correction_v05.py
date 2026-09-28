"""Replay sealed Q-R2 outputs with the frozen verifier's numeric tolerance.

This verifier-only continuation repairs v04's adapter bug. It performs no
inference, prediction generation, analysis rewrite, or panel opening.
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
SRC = EXP / "source"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
PANEL, TRAIN, EVAL = RUN / "panel-v01", RUN / "training-v03", RUN / "evaluation-v03"
PROV = RUN / "provenance"
V03 = SRC / "execute_q_r2_evaluation_correction_v03.py"
V04 = SRC / "execute_q_r2_replay_correction_v04.py"
ANALYZER = SRC / "analyze_q_r2_results_v01.py"
VERIFIER = SRC / "verify_q_r2_results_v01.py"
TRAINER = SRC / "run_q_r2_training_v01.py"
PREFLIGHT = PROV / "q-r2-replay-correction-preflight-v05.json"
EXECUTION = PROV / "q-r2-replay-correction-execution-v05.json"
AUDIT = PROV / "q-r2-replay-correction-audit-v05.json"
FAILURE = PROV / "q-r2-replay-correction-failure-v05.json"
REPLAY = EVAL / "independent-replay-verification-v03.json"
COMPLETION = PROV / "q-r2-completion-seal-v06.json"
NUMERIC_TOL = 1e-12
DIFFERENCES: list[dict[str, Any]] = []

EXPECTED = {
    "v03_adapter": "7463a302af0001b86465cef42eee26d676baba1259d4fb0e172c28cdc6920072",
    "v04_adapter": "a9b5e25c6456f30b6db71748d3b7d6d7e4b5d77c8d89bc5b8db3dcd2a3fcf661",
    "v04_preflight": "89651fef0a2a3f74e167ecdd3c2a63e56871d06140870d624bcb2b6236591448",
    "v04_execution": "76b529be3f2a92671a2c8d746814f060788adf6603fbf28d3a9599a6a94fb058",
    "v04_failure": "64d14ffa650a1e086e34ebe096f2c6bf65677e6745af2d0de76caaa2a2fd03d8",
    "analyzer": "3f9a87fd059f7ada026a6b9913f6ffdeb1058327322779901422037db667038a",
    "verifier": "c51073d6ab32cb9a9d8a8c9051a5123b27c7f3840f4e8712f931c640c33ee521",
    "trainer": "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0",
    "opening": "2c291a352b8490ddf63b298a7118ec842cce50654005f27190975d22ef13a8f2",
    "prediction_tree": "d25ef7d58e51feabd1cdde65d062e5528db4b30c90e4eb56440429a6980fc0cd",
    "analysis_seal": "ab4d0a338b5dcbeeef00b1054d3e4d57c3f4ce5ec3f1a9d185a1acb80264531c",
    "training_seal": "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84",
    "training_tree": "9708a4388923021c9b5d14b0b8dd33868902de61f568a200432f89cfb4cbaa9f",
    "raw_predictions": "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def preflight() -> dict[str, Any]:
    paths = {
        "v03_adapter": V03,
        "v04_adapter": V04,
        "v04_preflight": PROV / "q-r2-replay-correction-preflight-v04.json",
        "v04_execution": PROV / "q-r2-replay-correction-execution-v04.json",
        "v04_failure": PROV / "q-r2-replay-correction-failure-v04.json",
        "analyzer": ANALYZER, "verifier": VERIFIER, "trainer": TRAINER,
        "opening": EVAL / "panel-opening-receipt-v01.json",
        "prediction_tree": EVAL / "raw-prediction-hash-tree-v01.json",
        "analysis_seal": EVAL / "q-r2-analysis-seal-v01.json",
        "training_seal": TRAIN / "training-seal-manifest.json",
        "training_tree": TRAIN / "checkpoint-hash-tree.json",
        "raw_predictions": EVAL / "raw-predictions-v01.jsonl",
    }
    observed = {name: sha(path) for name, path in paths.items()}
    need(observed == EXPECTED, f"input identity mismatch: {observed}")
    opening = json.loads(paths["opening"].read_text(encoding="utf-8"))
    tree = json.loads(paths["prediction_tree"].read_text(encoding="utf-8"))
    need(opening.get("opening_count") == 1 and opening.get("training_panel_feedback") is False,
         "panel opening is not the single authorized opening")
    need(tree.get("cell_count") == 120 and tree.get("prediction_rows") == 960_000,
         "sealed prediction matrix count mismatch")
    need(not any(p.exists() for p in (PREFLIGHT, EXECUTION, AUDIT, FAILURE, REPLAY, COMPLETION)),
         "v05 replay namespace already used")
    return {"status": "Q_R2_NUMERIC_REPLAY_V05_PREFLIGHT_PASS",
            "inputs": [{"name": n, "path": str(paths[n]), "sha256": h} for n, h in sorted(observed.items())],
            "opening_count": 1, "inference": False, "analysis_rerun": False,
            "correction": "recursively compare numeric leaves at existing 1e-12 tolerance"}


def compare_nested(expected: Any, observed: Any, label: str, replay: Any) -> None:
    if isinstance(expected, dict):
        replay.need(isinstance(observed, dict) and expected.keys() == observed.keys(),
                    f"replay field mismatch at {label}")
        for key, value in expected.items():
            compare_nested(value, observed[key], f"{label}/{key}", replay)
    elif isinstance(expected, list):
        replay.need(isinstance(observed, list) and len(expected) == len(observed),
                    f"replay list shape mismatch at {label}")
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            compare_nested(left, right, f"{label}[{index}]", replay)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        replay.need(isinstance(observed, (float, int)) and not isinstance(observed, bool)
                    and math.isclose(float(expected), float(observed), rel_tol=NUMERIC_TOL, abs_tol=NUMERIC_TOL),
                    f"numeric replay mismatch {label}: {expected!r} != {observed!r}")
        if float(expected) != float(observed):
            DIFFERENCES.append({"path": label, "expected": float(expected), "observed": float(observed),
                                "absolute_difference": abs(float(expected) - float(observed))})
    else:
        replay.need(expected == observed, f"category replay mismatch {label}")


def main() -> int:
    need(not any(p.exists() for p in (PREFLIGHT, EXECUTION, AUDIT, FAILURE, REPLAY, COMPLETION)),
         "v05 replay identity already consumed")
    pre = preflight()
    write_new(PREFLIGHT, pre)
    write_new(EXECUTION, {"status": "Q_R2_RESULT_REPLAY_ONLY_STARTED",
        "identity": "JEV-V08Q-R2-NESTED-NUMERIC-COMPARISON-CORRECTION-V05",
        "preflight_sha256": sha(PREFLIGHT), "adapter_sha256": sha(Path(__file__).resolve()),
        "opening_count": 1, "additional_unlock": False, "inference": False,
        "analysis_reexecution": False, "scientific_contract_changed": False})
    try:
        v03 = load(V03, "q_r2_v03_adapter_for_v05_replay")
        _, _, _, replay, _ = v03.load_bundle()
        replay.RECEIPT = REPLAY
        replay.compare_record = lambda expected, observed, label: compare_nested(expected, observed, label, replay)
        result = replay.verify()
        need(result.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS", "independent replay did not pass")
        audit = {"status": "Q_R2_NESTED_NUMERIC_REPLAY_CORRECTION_PASS",
            "identity": "JEV-V08Q-R2-NESTED-NUMERIC-COMPARISON-CORRECTION-V05",
            "v04_failure_sha256": sha(PROV / "q-r2-replay-correction-failure-v04.json"),
            "adapter_sha256": sha(Path(__file__).resolve()), "verifier_sha256": sha(VERIFIER),
            "analysis_sha256": sha(ANALYZER), "correction": "existing 1e-12 tolerance applied recursively",
            "nonidentical_numeric_leaf_count": len(DIFFERENCES),
            "max_absolute_difference": max((d["absolute_difference"] for d in DIFFERENCES), default=0.0),
            "prediction_and_analysis_bytes_modified": False, "inference": False,
            "analysis_rerun": False, "opening_count": 1, "additional_unlock": False,
            "replay_receipt_sha256": sha(REPLAY)}
        write_new(AUDIT, audit)
        artifact_paths = [
            EXP / "seals/q-r2-phase-packet-seal-v01.json",
            EXP / "contracts/q-r2-run-contract-v01.json",
            EXP / "contracts/q-r2-analysis-contract-v01.json",
            EXP / "contracts/q-r2-panel-contract-v01.json",
            RUN / "provenance/q-r2-instrument-package-seal-v01.json",
            PANEL / "seals/q-r2-panel-construction-seal-v01.json",
            PANEL / "seals/q-r2-feature-cache-seal-v01.json",
            PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
            RUN / "training-v01/schedule/schedule-seal.json",
            TRAIN / "common-prefix-seal-v01.json", TRAIN / "checkpoint-hash-tree.json",
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
            RUN / "provenance/q-r2-evaluation-correction-preflight-v03.json",
            RUN / "provenance/q-r2-evaluation-correction-execution-v03.json",
            RUN / "provenance/q-r2-evaluation-correction-failure-v03.json",
            SRC / "execute_q_r2_evaluation_training-v03_adapter_v01.py",
            SRC / "execute_q_r2_evaluation_correction_v02.py", V03, V04,
            Path(__file__).resolve(), TRAINER, ANALYZER, VERIFIER,
            EVAL / "panel-opening-receipt-v01.json",
            RUN / "evaluation-v01/evaluation-failure-receipt-v01.json",
            RUN / "evaluation-v02/panel-opening-receipt-v01.json",
            RUN / "evaluation-v02/evaluation-failure-receipt-v01.json",
            RUN / "evaluation-v02/raw-predictions-v01.jsonl",
            PROV / "q-r2-evaluation-correction-preflight-v02.json",
            PROV / "q-r2-evaluation-correction-execution-v02.json",
            PROV / "q-r2-evaluation-correction-failure-v02.json",
            PROV / "q-r2-evaluation-correction-preflight-v03.json",
            PROV / "q-r2-evaluation-correction-execution-v03.json",
            PROV / "q-r2-evaluation-correction-failure-v03.json",
            PROV / "q-r2-replay-correction-preflight-v04.json",
            PROV / "q-r2-replay-correction-execution-v04.json",
            PROV / "q-r2-replay-correction-failure-v04.json",
            PREFLIGHT, EXECUTION, AUDIT, REPLAY,
            EVAL / "raw-prediction-hash-tree-v01.json", EVAL / "inference-receipt-v01.json",
            EVAL / "q-r2-analysis-seal-v01.json", EVAL / "raw-predictions-v01.jsonl",
            EVAL / "neighborhood-metrics-v01.jsonl", EVAL / "shared-neighborhood-bootstrap-plan-v01.npy",
            EVAL / "shared-moderator-seed-resample-plan-v01.npy", EVAL / "q-r2-analysis-v01.json",
            EVAL / "q-r2-results-v01.md",
        ]
        rows = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)} for path in artifact_paths]
        need(all(path.is_file() for path in artifact_paths), "completion artifact missing")
        need(len({r["path"] for r in rows}) == len(rows), "duplicate completion artifact path")
        root = hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n"
            for r in sorted(rows, key=lambda row: row["path"])).encode()).hexdigest()
        completion = {"status": "Q_R2_COMPLETE_RESULT_SEALED",
            "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
            "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
            "opening_count": 1, "second_unlock": False, "second_opening": False,
            "independent_replay_status": result["status"], "artifact_count": len(rows),
            "artifact_root_sha256": root, "artifacts": rows,
            "training_runs": 24, "late_continuations": 48, "evaluation_cells": 120,
            "prediction_rows": 960_000, "step120_primary": True, "step100_descriptive": True,
            "seed_population_inference": False, "controller_fitting": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat()}
        write_new(COMPLETION, completion)
        print(json.dumps({"status": completion["status"], "artifact_root_sha256": root,
            "completion_sha256": sha(COMPLETION), "replay_sha256": sha(REPLAY),
            "numeric_tolerance_audit_sha256": sha(AUDIT), "opening_count": 1,
            "result_path": str(EVAL / "q-r2-results-v01.md")}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if not FAILURE.exists():
            write_new(FAILURE, {"status": "Q_R2_REPLAY_CORRECTION_FAILED_CLOSED",
                "identity": "JEV-V08Q-R2-NESTED-NUMERIC-COMPARISON-CORRECTION-V05",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "opening_count": 1, "additional_unlock": False,
                "prediction_sha256": sha(EVAL / "raw-predictions-v01.jsonl"),
                "analysis_sha256": sha(EVAL / "q-r2-analysis-v01.json"),
                "automatic_inference_retry": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
