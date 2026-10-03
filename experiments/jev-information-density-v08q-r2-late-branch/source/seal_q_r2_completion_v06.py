"""Seal Q-R2 completion from already sealed results and replay receipts only."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
SRC = EXP / "source"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
PROV = RUN / "provenance"
PANEL, TRAIN, EVAL = RUN / "panel-v01", RUN / "training-v03", RUN / "evaluation-v03"
OUT = PROV / "q-r2-completion-seal-v06.json"
REPLAY = EVAL / "independent-replay-verification-v03.json"
AUDIT = PROV / "q-r2-replay-correction-audit-v05.json"
V05_FAIL = PROV / "q-r2-replay-correction-failure-v05.json"
V05_ADAPTER = SRC / "execute_q_r2_replay_correction_v05.py"
V06_PREFLIGHT = PROV / "q-r2-replay-correction-preflight-v05.json"
V06_EXECUTION = PROV / "q-r2-replay-correction-execution-v05.json"
OPENING_SHA = "2c291a352b8490ddf63b298a7118ec842cce50654005f27190975d22ef13a8f2"
PREDICTION_SHA = "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c"
TRAIN_SEAL_SHA = "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84"
TRAIN_TREE_SHA = "9708a4388923021c9b5d14b0b8dd33868902de61f568a200432f89cfb4cbaa9f"
PANEL_SEAL_SHA = "7b9b36c0fb39ff67b9b02c29034027bb5c1c238699c2a5f07799e8f29e8fb50c"
ANALYSIS_SEAL_SHA = "ab4d0a338b5dcbeeef00b1054d3e4d57c3f4ce5ec3f1a9d185a1acb80264531c"
REPLAY_SHA = "a1d8bdc5897b3bf829b3535e644daab032d8f469fb6ae376b9374d93e3bc1199"
AUDIT_SHA = "4e06c328eeabcd719737a47c7374602642e76649bc0e0d51d05fd94ab8c6f54e"
V05_FAIL_SHA = "e71fce45c88557e0003b07dca2e3eca06b9f6dfd0f241d63557df1f5092a4249"
V05_PREFLIGHT_SHA = "c02970a2e2f027102cdc325ce36633cb91cdc515372d1079d4de419b600ea14b"
V05_EXECUTION_SHA = "346eb479c6f0a6956a40f1d84e17cd45adb0552a5fabf4d5c0668c8122e51479"
V05_ADAPTER_SHA = "c76eb041f03b6055ddaf53046f6f2f287bd0713d501415a056034a184107f491"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def need(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    need(not OUT.exists(), "completion seal v06 already exists")
    bound = {
        "opening": EVAL / "panel-opening-receipt-v01.json",
        "panel_input_seal": PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
        "training_seal": TRAIN / "training-seal-manifest.json",
        "training_tree": TRAIN / "checkpoint-hash-tree.json",
        "prediction_tree": EVAL / "raw-prediction-hash-tree-v01.json",
        "analysis_seal": EVAL / "q-r2-analysis-seal-v01.json",
        "raw_predictions": EVAL / "raw-predictions-v01.jsonl",
        "replay": REPLAY,
        "numeric_audit": AUDIT,
        "v05_failure": V05_FAIL,
        "v05_adapter": V05_ADAPTER,
        "v05_preflight": V06_PREFLIGHT,
        "v05_execution": V06_EXECUTION,
    }
    observed = {name: sha(path) for name, path in bound.items()}
    expected = {"opening": OPENING_SHA, "panel_input_seal": PANEL_SEAL_SHA,
        "training_seal": TRAIN_SEAL_SHA, "training_tree": TRAIN_TREE_SHA,
        "prediction_tree": "d25ef7d58e51feabd1cdde65d062e5528db4b30c90e4eb56440429a6980fc0cd",
        "analysis_seal": ANALYSIS_SEAL_SHA, "raw_predictions": PREDICTION_SHA,
        "replay": REPLAY_SHA, "numeric_audit": AUDIT_SHA, "v05_failure": V05_FAIL_SHA,
        "v05_adapter": V05_ADAPTER_SHA, "v05_preflight": V05_PREFLIGHT_SHA,
        "v05_execution": V05_EXECUTION_SHA}
    need(observed == expected, f"sealed result binding mismatch: {observed}")
    opening, tree, training, audit, replay = (load(bound[name]) for name in
        ("opening", "prediction_tree", "training_seal", "numeric_audit", "replay"))
    failed = load(V05_FAIL)
    need(opening.get("opening_count") == 1 and opening.get("training_panel_feedback") is False,
         "opening receipt is not the single authorized no-feedback opening")
    need(tree.get("cell_count") == 120 and tree.get("prediction_rows") == 960_000,
         "prediction tree is incomplete")
    need(training.get("trained_checkpoint_count") == 120 and training.get("evaluation_panel_opened") is False,
         "training seal mismatch")
    need(audit.get("status") == "Q_R2_NESTED_NUMERIC_REPLAY_CORRECTION_PASS"
         and audit.get("prediction_and_analysis_bytes_modified") is False
         and audit.get("analysis_rerun") is False and audit.get("inference") is False
         and audit.get("opening_count") == 1,
         "numeric replay correction audit is invalid")
    need(replay.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS"
         and replay.get("cells_replayed") == 120 and replay.get("prediction_rows_replayed") == 960_000
         and replay.get("metric_rows_independently_replayed") == 240_000
         and replay.get("metric_coordinates_recomputed") == 29
         and replay.get("paired_effects_recomputed") == 696
         and replay.get("shared_resample_plans_replayed") is True,
         "independent replay receipt is incomplete")
    need(failed.get("exception") == "duplicate completion artifact path"
         and failed.get("opening_count") == 1 and failed.get("additional_unlock") is False,
         "v05 failure is not the known seal-manifest duplicate-path issue")

    # The earlier v05 manifest listed some provenance files twice via RUN/provenance
    # and PROV aliases. This finalizer records each absolute path exactly once.
    paths = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        PROV / "q-r2-instrument-package-seal-v01.json",
        PANEL / "seals/q-r2-panel-construction-seal-v01.json",
        PANEL / "seals/q-r2-feature-cache-seal-v01.json",
        bound["panel_input_seal"],
        RUN / "training-v01/schedule/schedule-seal.json",
        TRAIN / "common-prefix-seal-v01.json", bound["training_tree"], bound["training_seal"],
        PROV / "q-r2-training-input-correction-preflight-v01.json",
        PROV / "q-r2-device-correction-preflight-v02b.json",
        PROV / "q-r2-path-correction-preflight-v03b.json",
        PROV / "q-r2-path-correction-completion-v03.json",
        PROV / "q-r2-evaluation-routing-preflight-v01.json",
        PROV / "q-r2-evaluation-routing-execution-v01.json",
        PROV / "q-r2-evaluation-routing-failure-v01.json",
        PROV / "q-r2-evaluation-correction-preflight-v02.json",
        PROV / "q-r2-evaluation-correction-execution-v02.json",
        PROV / "q-r2-evaluation-correction-failure-v02.json",
        PROV / "q-r2-evaluation-correction-preflight-v03.json",
        PROV / "q-r2-evaluation-correction-execution-v03.json",
        PROV / "q-r2-evaluation-correction-failure-v03.json",
        PROV / "q-r2-replay-correction-preflight-v04.json",
        PROV / "q-r2-replay-correction-execution-v04.json",
        PROV / "q-r2-replay-correction-failure-v04.json",
        V06_PREFLIGHT, V06_EXECUTION, AUDIT, V05_FAIL,
        SRC / "execute_q_r2_evaluation_training-v03_adapter_v01.py",
        SRC / "execute_q_r2_evaluation_correction_v02.py",
        SRC / "execute_q_r2_evaluation_correction_v03.py",
        SRC / "execute_q_r2_replay_correction_v04.py", V05_ADAPTER,
        SRC / "seal_q_r2_completion_v06.py",
        SRC / "run_q_r2_training_v01.py",
        SRC / "analyze_q_r2_results_v01.py", SRC / "verify_q_r2_results_v01.py",
        bound["opening"], RUN / "evaluation-v01/evaluation-failure-receipt-v01.json",
        RUN / "evaluation-v02/panel-opening-receipt-v01.json",
        RUN / "evaluation-v02/evaluation-failure-receipt-v01.json",
        RUN / "evaluation-v02/raw-predictions-v01.jsonl",
        bound["prediction_tree"], EVAL / "inference-receipt-v01.json",
        bound["analysis_seal"], REPLAY, bound["raw_predictions"],
        EVAL / "neighborhood-metrics-v01.jsonl",
        EVAL / "shared-neighborhood-bootstrap-plan-v01.npy",
        EVAL / "shared-moderator-seed-resample-plan-v01.npy",
        EVAL / "q-r2-analysis-v01.json", EVAL / "q-r2-results-v01.md",
    ]
    canonical: dict[str, Path] = {}
    for path in paths:
        key = str(path.resolve())
        canonical.setdefault(key, path)
    need(len(canonical) == len(paths), "v06 explicit artifact manifest still contains aliases")
    rows = []
    for key, path in sorted(canonical.items()):
        need(path.is_file(), f"completion artifact missing: {path}")
        rows.append({"path": key, "bytes": path.stat().st_size, "sha256": sha(path)})
    root_material = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in rows)
    root = hashlib.sha256(root_material.encode()).hexdigest()
    result = {"status": "Q_R2_COMPLETE_RESULT_SEALED",
        "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
        "opening_count": 1, "second_unlock": False, "second_opening": False,
        "independent_replay_status": replay["status"], "artifact_count": len(rows),
        "artifact_root_sha256": root, "artifacts": rows,
        "training_runs": 24, "late_continuations": 48, "evaluation_cells": 120,
        "raw_prediction_rows": 960_000, "step120_primary": True, "step100_descriptive": True,
        "seed_population_inference": False, "controller_fitting": False,
        "seal_note": "v06 deduplicates absolute provenance paths; no scientific bytes changed",
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_new(OUT, result)
    print(json.dumps({"status": result["status"], "artifact_count": len(rows),
        "artifact_root_sha256": root, "completion_seal_sha256": sha(OUT),
        "independent_replay_sha256": sha(REPLAY), "opening_count": 1,
        "result_path": str(EVAL / "q-r2-results-v01.md")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
