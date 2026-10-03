"""Resume Q-R1's first prediction cell after the evaluator's pre-metric NameError.

The frozen evaluator wrote only seed 77720160 COMMON_INIT (8,000 rows), then
failed on an out-of-scope schedule variable before any trained checkpoint was
loaded. This adapter preserves those bytes and continues at the next contracted
cell without reopening the panel or repeating any inference.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
TRAIN = RUN / "training"
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
OUTPUT = RUN / "evaluation-v01"
EVALUATOR = R1 / "source/evaluate_q_r1_panel_v01.py"
FAILURE = OUTPUT / "evaluation-failure-receipt-v01.json"
PARTIAL = OUTPUT / "raw-predictions-v01.jsonl"
PRESERVED_DIR = OUTPUT / "failed-attempt-01"
PRESERVED_PARTIAL = PRESERVED_DIR / "raw-predictions-partial-v01.jsonl"
CONTINUATION_DIR = OUTPUT / "continuation-v01"
CONTINUATION_RECEIPT = CONTINUATION_DIR / "continuation-receipt-v01.json"
PACKET_SHA = "80090a8011455395134f5ba8e0ef2a4eef33d4a78ccc795a137b9d7dc0bed7a4"
PANEL_ROOT = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
TRAIN_SEAL_SHA = "9a6abae90339b63c76d9f91dc7c25dcfc56d4f16d1a31b29d823be0f8fe5c9a4"
TREE_SHA = "862fee44408eda5a5698ead5d6df13664f0dbb977ae820e5286e31900498a898"
SEEDS = (77720160, 4245719435, 3815947415, 3112928194, 4241626823, 534474641,
         3124582801, 4247677041, 811956520, 3972258, 950790373, 949206414)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
STEPS = (40, 80, 100, 120)
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location("q_r1_frozen_evaluator_continuation", EVALUATOR)
    need(spec is not None and spec.loader is not None, "cannot load frozen evaluator helpers")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.INSTRUMENT_RECEIPT = module.verify_instrument_package()
    return module


def expected_cells():
    for seed in SEEDS:
        yield seed, "COMMON_INIT", 0
        for step in STEPS:
            for arm in ARMS:
                yield seed, arm, step


def verify_partial_prefix(module: Any, panel_rows: list[dict[str, Any]],
                          templates: dict[int, dict[str, Any]]) -> dict[str, Any]:
    need(FAILURE.is_file() and not (OUTPUT / "inference-receipt-v01.json").exists()
         and not (OUTPUT / "raw-prediction-hash-tree-v01.json").exists()
         and PARTIAL.is_file(), "not the expected pre-metric partial evaluation state")
    failure = read_json(FAILURE)
    need(failure.get("status") == "Q_R1_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED"
         and failure.get("exception_type") == "NameError"
         and failure.get("exception") == "name 'seed_schedule' is not defined"
         and failure.get("panel_opened") is True,
         "failed evaluation receipt does not match the known plumbing defect")
    opening = read_json(OUTPUT / "panel-opening-receipt-v01.json")
    need(opening.get("opening_count") == 1 and opening.get("panel_root_sha256") == PANEL_ROOT
         and opening.get("training_seal_sha256") == TRAIN_SEAL_SHA
         and opening.get("checkpoint_tree_sha256") == TREE_SHA,
         "existing single panel opening receipt mismatch")
    expected_ids = [row["neighborhood_id"] for row in sorted(panel_rows, key=lambda row: row["neighborhood_id"])]
    init_file_sha = sha(TRAIN / "initial-templates" / f"seed-{SEEDS[0]}.pt")
    count = 0
    with PARTIAL.open("r", encoding="utf-8") as stream:
        for row in (json.loads(line) for line in stream if line.strip()):
            need((row.get("seed"), row.get("arm"), row.get("global_step")) == (SEEDS[0], "COMMON_INIT", 0),
                 "partial evaluation contains a non-initialization/treatment row")
            need(row.get("checkpoint_sha256") == init_file_sha
                 and row.get("head_state_sha256") == templates[SEEDS[0]]["state_sha256"],
                 "partial initialization row is not bound to the shared init template")
            key = (str(row.get("neighborhood_id")), str(row.get("view")))
            expected_nid = expected_ids[count // 4] if count < 8_000 else None
            need(key[0] == expected_nid and key[1] == VIEWS[count % 4],
                 "partial output is not exactly the complete first contracted cell prefix")
            count += 1
    need(count == 8_000, f"expected exactly 8,000 init-only partial rows; found {count}")
    return {"partial_path": str(PARTIAL), "partial_bytes": PARTIAL.stat().st_size,
            "partial_sha256": sha(PARTIAL), "partial_rows": count,
            "only_cell": {"seed": SEEDS[0], "arm": "COMMON_INIT", "step": 0},
            "trained_checkpoint_rows": 0, "treatment_metric_artifacts": 0,
            "failure_receipt_sha256": sha(FAILURE), "opening_receipt_sha256": sha(OUTPUT / "panel-opening-receipt-v01.json")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    need(not CONTINUATION_RECEIPT.exists(), "continuation receipt already exists")
    need(not PRESERVED_DIR.exists(), "failed-attempt preservation target already exists")
    need(not (OUTPUT / "raw-prediction-hash-tree-v01.json").exists()
         and not (OUTPUT / "inference-receipt-v01.json").exists(),
         "completed prediction seal already exists")
    module = load_evaluator()
    instrument_manifest = read_json(RUN / "instrument-v01/instrument-manifest-v01.json")
    evaluator_entry = next((row for row in instrument_manifest["entries"]
                            if row["path"] == str(EVALUATOR.resolve())), None)
    need(evaluator_entry is not None and sha(EVALUATOR) == evaluator_entry["sha256"],
         "frozen evaluator source differs from pre-run instrument package")
    packet = module.verify_packet()
    training_seal, checkpoint_lookup = module.verify_training()
    panel_binding = module.verify_panel_seal()
    need(packet["packet_sha256"] == PACKET_SHA
         and training_seal["checkpoint_tree_sha256"] == TREE_SHA
         and training_seal["status"] == "Q_R1_ALL_48_RUNS_COMPLETE_SEALED_UNEVALUATED"
         and panel_binding["panel_root_sha256"] == PANEL_ROOT,
         "sealed experiment inputs differ from the authorized R1 packet")
    panel_rows, scope, metadata, states, candidates, candidate_index, schema_order = module.build_panel()
    templates: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
        templates[seed] = torch.load(path, map_location="cpu", weights_only=True)
    prefix = verify_partial_prefix(module, panel_rows, templates)
    if args.preflight_only:
        print(json.dumps({"status": "Q_R1_EVALUATION_CONTINUATION_PREFLIGHT_PASS_NO_NEW_INFERENCE",
                          "partial": prefix, "panel_open_count": 1,
                          "training_seal_sha256": module.sha(TRAIN / "training-seal-manifest.json"),
                          "checkpoint_tree_sha256": module.sha(TRAIN / "checkpoint-hash-tree.json"),
                          "preservation_or_continuation_started": False}, indent=2))
        return 0
    evaluator_source_sha = sha(EVALUATOR)
    adapter_sha = sha(Path(__file__).resolve())
    receipt = {
        "status": "Q_R1_PRE_METRIC_EVALUATOR_PLUMBING_CORRECTION_CONTINUATION_AUTHORIZED",
        "identity": "Q-R1-EVALUATION-CONTINUATION-AFTER-SEED-SCHEDULE-SCOPE-FIX-V01",
        "original_evaluator_sha256": evaluator_source_sha,
        "continuation_adapter_sha256": adapter_sha,
        "original_failure_receipt_sha256": prefix["failure_receipt_sha256"],
        "preserved_partial_prediction_sha256": prefix["partial_sha256"],
        "preserved_partial_prediction_rows": 8_000,
        "partial_scope": "first COMMON_INIT cell only; no trained checkpoint rows and no treatment metrics",
        "panel_open_count_before_continuation": 1,
        "second_panel_opening": False,
        "training_repeated": False,
        "first_cell_inference_repeated": False,
        "metric_or_threshold_changed": False,
        "correction": "reconstruct the already-sealed per-seed schedule hash map in adapter scope, then continue at the next cell",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_new(CONTINUATION_RECEIPT, receipt)
    PRESERVED_DIR.mkdir(parents=False, exist_ok=False)
    PARTIAL.rename(PRESERVED_PARTIAL)
    prediction_path = PARTIAL
    shutil.copyfile(PRESERVED_PARTIAL, prediction_path)
    need(sha(prediction_path) == prefix["partial_sha256"], "copied prediction prefix differs from preserved failed attempt")

    preflight = module.read_json(TRAIN / "training-preflight-receipt-v01.json")
    seed_schedule = {int(row["seed"]): row for row in preflight["per_seed_schedule_receipts"]}
    need(len(seed_schedule) == 12 and all(seed_schedule[s]["rows"] == 120 for s in SEEDS),
         "sealed per-seed schedule receipts invalid")
    probe_path = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
    metric_path = ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py"
    need(module.sha(probe_path) == module.PROBE_SHA and module.sha(metric_path) == module.METRIC_SHA,
         "frozen inference dependencies differ from sealed R1 instrument")
    probe = module.load_module(probe_path, "q_r1_frozen_probe_continuation")
    metric = module.load_module(metric_path, "q_r1_frozen_prediction_function_continuation")
    cell_order = [{"seed": SEEDS[0], "arm": "COMMON_INIT", "step": 0, "rows": 8_000,
                   "checkpoint_sha256": sha(TRAIN / "initial-templates" / f"seed-{SEEDS[0]}.pt")}]
    completed_cells = 1
    with prediction_path.open("a", encoding="utf-8", newline="\n") as stream:
        cells = list(expected_cells())
        need(cells[0] == (SEEDS[0], "COMMON_INIT", 0), "expected first matrix cell changed")
        for seed, arm, step in cells[1:]:
            if arm == "COMMON_INIT":
                init_pack = templates[seed]
                init_path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
                head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                head.load_state_dict(init_pack["state_dict"], strict=True)
                try:
                    rows, _ = metric.metrics_for_run(seed, "COMMON_INIT", head, panel_rows, scope, metadata,
                                                     states, candidates, candidate_index, schema_order, "cuda")
                    checkpoint_hash = module.sha(init_path)
                    head_hash = init_pack["state_sha256"]
                finally:
                    del head
                    torch.cuda.empty_cache()
            else:
                entry = checkpoint_lookup[(seed, arm, step)]
                checkpoint = torch.load(entry["path"], map_location="cpu", weights_only=False)
                init_pack = templates[seed]
                need(checkpoint.get("seed") == seed and checkpoint.get("arm") == arm
                     and checkpoint.get("global_step") == step
                     and checkpoint.get("schedule_sha256") == module.sha(RUN / "schedule/fixed-schedule.jsonl")
                     and checkpoint.get("seed_schedule_sha256") == seed_schedule[seed]["schedule_sha256"]
                     and checkpoint.get("initial_head_sha256") == init_pack["state_sha256"]
                     and module.state_sha(checkpoint["head_state"]) == checkpoint.get("head_sha256") == entry["head_sha256"],
                     f"checkpoint metadata/hash mismatch in continuation: {seed}/{arm}/{step}")
                head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                head.load_state_dict(checkpoint["head_state"], strict=True)
                try:
                    rows, _ = metric.metrics_for_run(seed, arm, head, panel_rows, scope, metadata,
                                                     states, candidates, candidate_index, schema_order, "cuda")
                    checkpoint_hash = entry["sha256"]
                    head_hash = checkpoint["head_sha256"]
                finally:
                    del head, checkpoint
                    torch.cuda.empty_cache()
            need(len(rows) == 8_000, f"continued evaluation cell row count mismatch: {seed}/{arm}/{step}")
            for row in rows:
                row.update({"global_step": step,
                            "checkpoint_label": "COMMON_INIT" if arm == "COMMON_INIT" else f"step-{step:03}",
                            "checkpoint_sha256": checkpoint_hash, "head_state_sha256": head_hash})
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            cell_order.append({"seed": seed, "arm": arm, "step": step, "rows": len(rows),
                               "checkpoint_sha256": checkpoint_hash})
            completed_cells += 1
            if completed_cells % 4 == 0:
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps({"event": "q_r1_eval_continuation_cell_complete", "seed": seed,
                              "arm": arm, "step": step, "cells": completed_cells,
                              "expected_cells": 204}, separators=(",", ":")), flush=True)
        stream.flush()
        os.fsync(stream.fileno())
    need(len(cell_order) == 204 and all(row["rows"] == 8_000 for row in cell_order),
         "continued raw prediction matrix incomplete")
    prediction_sha = module.sha(prediction_path)
    correction_sha = sha(CONTINUATION_RECEIPT)
    tree = {
        "status": "Q_R1_ALL_204_CELLS_AND_1632000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS",
        "identity": "JEV-V08Q-R1-RESPONSE-PHENOTYPE-REPLICATION",
        "packet_sha256": packet["packet_sha256"],
        "training_seal_sha256": module.sha(TRAIN / "training-seal-manifest.json"),
        "checkpoint_tree_sha256": module.sha(TRAIN / "checkpoint-hash-tree.json"),
        "panel_opening_receipt_sha256": module.sha(OUTPUT / "panel-opening-receipt-v01.json"),
        "panel_root_sha256": PANEL_ROOT, "cell_count": 204, "prediction_rows": 1_632_000,
        "rows_by_cell": cell_order,
        "raw_predictions": {"path": str(prediction_path), "bytes": prediction_path.stat().st_size,
                            "sha256": prediction_sha},
        "panel_open_count": 1, "predictions_before_analysis": True,
        "checkpoint_selection": False, "training_feedback": False,
        "continuation_receipt_sha256": correction_sha,
        "failed_attempt_partial_sha256": prefix["partial_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    module.write_json(OUTPUT / "raw-prediction-hash-tree-v01.json", tree)
    module.write_json(OUTPUT / "inference-receipt-v01.json", {
        "status": "Q_R1_ALL_204_CELLS_INFERRED_AND_SEALED",
        "prediction_hash_tree_sha256": module.sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
        "prediction_sha256": prediction_sha, "prediction_rows": 1_632_000,
        "cell_count": 204, "panel_open_count": 1, "predictions_before_analysis": True,
        "training": False, "continuation_receipt_sha256": correction_sha,
    })
    print(json.dumps({"status": tree["status"], "cells": len(cell_order), "rows": 1_632_000,
                      "prediction_sha256": prediction_sha, "continuation_receipt_sha256": correction_sha},
                     indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
