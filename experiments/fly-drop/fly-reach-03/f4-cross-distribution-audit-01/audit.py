from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STUDY = REPO / "experiments/fly-reach-03"
SYMMETRY_SCRIPTS = STUDY / "f4-symmetry-03" / "scripts"
sys.path.insert(0, str(SYMMETRY_SCRIPTS))
from common import read_predictors, sha_file  # noqa: E402

SPEC_PATH = HERE / "AUDIT-SCOPE-v0.1.md"
MARGIN_CUTS = (1e-12, 1e-10, 1e-8)
QUANTILES = (0.01, 0.10, 0.50, 0.90, 0.99)
EXPECTED = {
    "SYMMETRY03": {
        "run_id": "F4-SYMMETRY-03-QREP1-IMPLFIX1",
        "blocks": list(range(304000, 304008)),
        "predictor": "41bb93ca9a20036aaff513f220b7511442b83eb22d12cac9709adc1fc839e525",
        "truth": "4f0609d5f80f43c7f3d5eefefb496c0329e21c50430f08b7b74b826bd307a218",
        "task": "f91dac177eb5547fd2fb518a55b6156701f1ec3d5c876f3527cfa882f918a04e",
        "task_manifest_hash": "96217b4193964ee98ed9c9e2e3b6f7a2fc0422c20368bb103e71a3d279634e70",
        "collection": "950d770e09da362464237af7cb245d937548e0a2b0b5b6b3e233c3550f4ac187",
        "analysis": "experiments/fly-reach-03/runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/ANALYSIS.json",
        "integrity": "experiments/fly-reach-03/runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/INTEGRITY-RECEIPT.json",
        "terminal": "experiments/fly-reach-03/runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/TERMINAL-RECEIPT.json",
        "terminal_analysis_key": "runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/ANALYSIS.json",
        "task_path": "experiments/fly-reach-03/runs/f4-symmetry-03-structural-screen/training.json",
        "task_manifest": "experiments/fly-reach-03/runs/f4-symmetry-03-structural-screen/TASK-BANK-MANIFEST.json",
        "selected": True,
        "input_dir": "experiments/fly-reach-03/runs/F4-SYMMETRY-03-QREP1-IMPLFIX1",
        "truth_name": "RAW-SCORING-TRUTH.bin",
    },
    "QPROMO2": {
        "run_id": "F4-CALIBRATION-02-QPROMO2",
        "blocks": list(range(305012, 305024)),
        "predictor": "344e3e129665df2a0ccac2b6c0f12b9b59a76a5fe39e38627df151738377c390",
        "truth": "cab0340a2846c2582cbb61b040cef0af0b28476a37a8680239dbaf8685f836b7",
        "task": "9ec1f7c240143e7fb5537ae72eb6d5bb3fb4fb8fc0445bcbafa54ae913a826b5",
        "task_manifest_hash": "c1a63224682550e473b626780d3c1ba68d1636e00b4ef09f501f13dcbbc5967c",
        "collection": "d08966471e6af1c38365f370b9749794931c8ef588a9343ce4945bc1cac05601",
        "analysis": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/ANALYSIS.json",
        "integrity": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/INTEGRITY-RECEIPT.json",
        "terminal": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/F4-CALIBRATION-TERMINAL-RECEIPT.json",
        "terminal_analysis_key": "ANALYSIS.json",
        "task_path": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/task-bank/training.json",
        "task_manifest": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/task-bank/TASK-BANK-MANIFEST.json",
        "selected": False,
        "input_dir": "experiments/fly-reach-03/runs/F4-CALIBRATION-02-QPROMO2/collection-staging",
        "truth_name": "RAW-SCORING-TRUTH.bin",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order], dtype=np.float64)
    index = min(int(np.searchsorted(cumulative, q * cumulative[-1], side="left")), len(order) - 1)
    return float(values[order[index]])


def concentration(weights: np.ndarray) -> dict[str, float]:
    total = float(np.sum(weights, dtype=np.float64))
    square = float(np.sum(weights * weights, dtype=np.float64))
    ordered = np.sort(weights)[::-1]
    return {
        "total": total,
        "ess": total * total / square if square else 0.0,
        "ess_fraction": (total * total / square / len(weights)) if square and len(weights) else 0.0,
        **{
            f"top_{int(frac * 100)}pct_share": float(
                np.sum(ordered[: max(1, math.ceil(frac * len(ordered)))], dtype=np.float64) / total
            ) if total else 0.0
            for frac in (0.01, 0.05, 0.20)
        },
    }


def quantile_summary(values: np.ndarray, weights: np.ndarray) -> dict[str, Any]:
    return {
        "unweighted": {f"p{int(q * 100):02d}": float(np.quantile(values, q, method="linear")) for q in QUANTILES},
        "ipw_weighted_empirical": {f"p{int(q * 100):02d}": weighted_quantile(values, weights, q) for q in QUANTILES},
        "ipw_weighted_fraction_at_or_below": {
            f"{cut:.0e}": float(weights[values <= cut].sum(dtype=np.float64) / weights.sum(dtype=np.float64))
            for cut in MARGIN_CUTS
        },
    }


def task_summary(task: dict[str, Any], expected_blocks: list[int], selected: bool) -> dict[str, Any]:
    blocks = task["blocks"]
    require(sorted(int(key) for key in blocks) == expected_blocks, "task block IDs differ from frozen panel")
    cue_hist = np.zeros(4, dtype=np.int64)
    delay_hist = np.zeros(32, dtype=np.int64)
    per_block_cue_cv: list[float] = []
    per_block_delay_cv: list[float] = []
    label_assignments: Counter[str] = Counter()
    schedule_rows = 0
    for block_id in expected_blocks:
        block = blocks[str(block_id)]
        labels = block["labels"]
        schedule = block["schedule"]
        require(block["cue_count"] == 4 and block["pretraining_trials"] == 8192 and block["delay_steps"] == 12,
                f"task constants differ in block {block_id}")
        require(len(labels) == 4 and sum(bool(x) for x in labels) == 2, f"label balance differs in block {block_id}")
        require(len(schedule) == 8192 and all(len(row) == 13 for row in schedule), f"schedule shape differs in block {block_id}")
        label_assignments["".join("1" if x else "0" for x in labels)] += 1
        cues = np.fromiter((int(row[0]) for row in schedule), dtype=np.int64, count=len(schedule))
        delays = np.fromiter((int(value) - 4 for row in schedule for value in row[1:]), dtype=np.int64, count=12 * len(schedule))
        require(cues.min() >= 0 and cues.max() < 4 and delays.min() >= 0 and delays.max() < 32,
                f"schedule value outside declared range in block {block_id}")
        local_cue = np.bincount(cues, minlength=4)
        local_delay = np.bincount(delays, minlength=32)
        cue_hist += local_cue
        delay_hist += local_delay
        per_block_cue_cv.append(float(local_cue.std() / local_cue.mean()))
        per_block_delay_cv.append(float(local_delay.std() / local_delay.mean()))
        schedule_rows += len(schedule)
    require(schedule_rows == len(expected_blocks) * 8192, "task schedule row count mismatch")
    return {
        "block_count": len(expected_blocks), "cue_count": 4, "trials_per_block": 8192, "delay_steps": 12,
        "structural_pattern_selection": selected,
        "positive_negative_labels_per_block": "2/2",
        "distinct_label_assignments": len(label_assignments),
        "label_assignment_counts": dict(sorted(label_assignments.items())),
        "primary_cue_total_counts": cue_hist.tolist(),
        "primary_cue_cv_pooled": float(cue_hist.std() / cue_hist.mean()),
        "primary_cue_cv_by_block_min_median_max": [min(per_block_cue_cv), statistics.median(per_block_cue_cv), max(per_block_cue_cv)],
        "delay_token_total_counts_4_through_35": delay_hist.tolist(),
        "delay_token_cv_pooled": float(delay_hist.std() / delay_hist.mean()),
        "delay_token_cv_by_block_min_median_max": [min(per_block_delay_cv), statistics.median(per_block_delay_cv), max(per_block_delay_cv)],
    }


def load_run(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    input_dir = REPO / cfg["input_dir"]
    predictor = input_dir / "RAW-PREDICTORS.bin"
    truth = input_dir / cfg["truth_name"]
    task_path = REPO / cfg["task_path"]
    task_manifest_path = REPO / cfg["task_manifest"]
    collection_path = input_dir / "NATIVE-COLLECTION-RECEIPT.json"
    analysis_path = REPO / cfg["analysis"]
    integrity_path = REPO / cfg["integrity"]
    terminal_path = REPO / cfg["terminal"]
    require(sha_file(predictor) == cfg["predictor"], f"{name}: predictor hash mismatch")
    require(sha_file(truth) == cfg["truth"], f"{name}: truth hash mismatch")
    require(sha_file(task_path) == cfg["task"], f"{name}: task payload hash mismatch")
    require(sha_file(task_manifest_path) == cfg["task_manifest_hash"], f"{name}: task manifest hash mismatch")
    collection = read_json(collection_path)
    require(collection["status"] == "PASS" and collection["schema"].endswith("native-collection-v1"), f"{name}: native receipt status/schema")
    require(sha_file(collection_path) == cfg["collection"], f"{name}: collection receipt hash mismatch")
    require(collection["predictor_sha256"] == cfg["predictor"] and collection["truth_sha256"] == cfg["truth"], f"{name}: receipt data hashes differ")
    task_manifest = read_json(task_manifest_path)
    task = read_json(task_path)
    expected_blocks = cfg["blocks"]
    data = read_predictors(predictor, truth, expected_blocks)
    require(data.count == int(collection["row_count"]), f"{name}: row count differs from collection receipt")

    raw_truth = truth.read_bytes()
    n = data.count
    inclusion = np.ndarray(n, dtype="<f8", buffer=raw_truth, offset=50, strides=(39,)).copy()
    y = np.ndarray(n, dtype="i1", buffer=raw_truth, offset=58, strides=(39,)).copy()
    native = np.ndarray(n, dtype="<f4", buffer=raw_truth, offset=59, strides=(39,)).astype(np.float64)
    reference = np.ndarray(n, dtype="<f4", buffer=raw_truth, offset=67, strides=(39,)).astype(np.float64)
    require(np.isfinite(inclusion).all() and (inclusion > 0).all() and (inclusion <= 1).all(), f"{name}: invalid inclusion probabilities")
    require(np.isin(y, (-1, 1)).all() and np.isfinite(native).all() and np.isfinite(reference).all(), f"{name}: malformed scoring truth")
    q = 1.0 / inclusion
    abs_g = np.abs(reference)
    leverage = q * np.abs(native) * abs_g

    block_counts: list[dict[str, Any]] = []
    stream_rows: dict[int, int] = {int(block): 0 for block in expected_blocks}
    nonempty_cells: Counter[int] = Counter()
    for stream in collection["streams"]:
        block = int(stream["block_id"])
        stream_rows[block] += int(stream["rows"])
        nonempty_cells[block] += int(int(stream["rows"]) > 0)
    for block in expected_blocks:
        mask = data.blocks == block
        plus, minus = mask & (y == 1), mask & (y == -1)
        total_q = float(q[mask].sum(dtype=np.float64))
        block_counts.append({
            "block_id": block, "rows": int(mask.sum()), "nonempty_substrate_side_cells": int(nonempty_cells[block]),
            "positive_count": int(plus.sum()), "negative_count": int(minus.sum()),
            "positive_ipw_share": float(q[plus].sum(dtype=np.float64) / total_q) if total_q else None,
            "class_complete": bool(plus.any() and minus.any()),
            "leverage": concentration(leverage[mask]),
        })
    row_values = np.asarray([item["rows"] for item in block_counts], dtype=np.int64)
    classes = {"positive": int(np.sum(y == 1)), "negative": int(np.sum(y == -1))}
    class_q = {"positive": float(q[y == 1].sum(dtype=np.float64)), "negative": float(q[y == -1].sum(dtype=np.float64))}
    total_class_q = class_q["positive"] + class_q["negative"]
    margins = quantile_summary(abs_g, q)
    analysis = read_json(analysis_path)
    integrity = read_json(integrity_path)
    terminal = read_json(terminal_path)
    require(integrity.get("status") == "PASS", f"{name}: prior integrity receipt did not pass")
    terminal_analysis = terminal.get("artifact_sha256", {}).get(cfg["terminal_analysis_key"])
    if isinstance(terminal_analysis, dict):
        terminal_analysis = terminal_analysis.get("sha256")
    require(terminal_analysis == sha_file(analysis_path), f"{name}: analysis hash differs from terminal receipt")
    require(analysis.get("qualification_only") is True and analysis.get("measured_reach03_authorized") is False,
            f"{name}: analysis claim boundary mismatch")
    if name == "SYMMETRY03":
        outcome = analysis["pooled"]["D"]
        d_error, d_omega = outcome["balanced_error"], outcome["omega_hat_clipped"]
    else:
        outcome = analysis["pooled_D"]
        d_error, d_omega = outcome["balanced_error"], outcome["omega_hat_clipped"]

    if cfg["selected"]:
        task_selection = bool(task_manifest.get("structure_screen_sha256"))
        require(task_selection and task_manifest.get("screen_uses_outcome_data") is False,
                f"{name}: structure-only selection provenance missing")
    else:
        require(task_manifest.get("structural_pattern_selection") is False,
                f"{name}: ordinary task selection metadata mismatch")
        task_selection = False
    return {
        "run_id": cfg["run_id"], "block_ids": expected_blocks, "row_count": n,
        "task_structure": task_summary(task, expected_blocks, task_selection),
        "Ustar_support": {
            "rows_by_block": row_values.tolist(), "rows_min_median_max": [int(row_values.min()), float(np.median(row_values)), int(row_values.max())],
            "nonempty_substrate_side_cells_by_block": [int(nonempty_cells[b]) for b in expected_blocks],
            "class_complete_blocks": [item["block_id"] for item in block_counts if item["class_complete"]],
            "class_complete_count": sum(item["class_complete"] for item in block_counts), "total_blocks": len(expected_blocks),
            "blockwise": block_counts,
        },
        "class_balance": {
            "observed_counts": classes, "observed_positive_share": classes["positive"] / n,
            "ipw_weighted_totals": class_q,
            "ipw_positive_share": class_q["positive"] / total_class_q,
            "ipw_negative_share": class_q["negative"] / total_class_q,
        },
        "target_margin_abs_g": margins,
        "leverage_concentration": concentration(leverage),
        "pooled_D_outcome_anchor": {"balanced_error": d_error, "omega_hat_clipped": d_omega,
                                     "analysis_sha256": sha_file(analysis_path)},
        "artifact_hashes": {
            "predictors": sha_file(predictor), "scoring_truth": sha_file(truth),
            "native_collection_receipt": sha_file(collection_path), "task_training": sha_file(task_path),
            "task_manifest": sha_file(task_manifest_path),
            "integrity_receipt": sha_file(integrity_path), "terminal_receipt": sha_file(terminal_path),
        },
    }


def write_json(path: Path, value: Any) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return sha_bytes(raw)


def write_report(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# F4 Cross-Distribution Failure Audit",
        "",
        "Analysis-only comparison of sealed qualification artifacts. No fits, refits, or prediction scoring were performed.",
        "",
        "## Frozen D outcome anchors",
        "",
        "| Run | U* rows | D balanced error | D Omega-hat | Task blocks | Structurally screened |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for label in ("SYMMETRY03", "QPROMO2"):
        item = result["runs"][label]
        lines.append(f"| {label} | {item['row_count']:,} | {item['pooled_D_outcome_anchor']['balanced_error']:.6f} | {item['pooled_D_outcome_anchor']['omega_hat_clipped']:.6f} | {len(item['block_ids'])} | {item['task_structure']['structural_pattern_selection']} |")
    lines.extend(["", "## Task-only structure", ""])
    for label in ("SYMMETRY03", "QPROMO2"):
        task = result["runs"][label]["task_structure"]
        lines.append(f"- **{label}:** {task['block_count']} blocks; {task['cue_count']} cues; {task['trials_per_block']:,} trials/block; {task['delay_steps']} delay steps; {task['distinct_label_assignments']} distinct balanced cue-label assignments; pooled primary-cue CV {task['primary_cue_cv_pooled']:.4f}; pooled delay-token CV {task['delay_token_cv_pooled']:.4f}.")
    lines.extend(["", "## Scored U* support and labels", ""])
    for label in ("SYMMETRY03", "QPROMO2"):
        item = result["runs"][label]
        support, classes = item["Ustar_support"], item["class_balance"]
        lo, med, hi = support["rows_min_median_max"]
        lines.append(f"- **{label}:** class-complete blocks {support['class_complete_count']}/{support['total_blocks']}; rows/block min–median–max {lo:,}–{med:,.1f}–{hi:,}; observed positive share {classes['observed_positive_share']:.3%}; IPW positive share {classes['ipw_positive_share']:.3%}.")
    lines.extend(["", "## Target-margin and leverage summaries", ""])
    for label in ("SYMMETRY03", "QPROMO2"):
        item = result["runs"][label]
        margin, lev = item["target_margin_abs_g"], item["leverage_concentration"]
        q = margin["ipw_weighted_empirical"]
        lines.append(f"- **{label}:** IPW |g| quantiles p10/p50/p90 = {q['p10']:.3e}/{q['p50']:.3e}/{q['p90']:.3e}; IPW share |g|≤1e-8 = {margin['ipw_weighted_fraction_at_or_below']['1e-08']:.3%}; leverage ESS {lev['ess']:.1f}/{item['row_count']:,} ({lev['ess_fraction']:.3%}); top-1/5/20% leverage shares {lev['top_1pct_share']:.3%}/{lev['top_5pct_share']:.3%}/{lev['top_20pct_share']:.3%}.")
    lines.extend([
        "",
        "## Bounded interpretation",
        "",
        result["interpretation"],
        "",
        "This is descriptive archaeology across different frozen block seeds and selection procedures. It cannot isolate structural screening as the sole cause of the calibration gap. No incidence-pattern or correctness-conditioned follow-up was computed.",
        "",
        f"Audit scope SHA-256: `{result['audit_scope_sha256']}`.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "output-v0.1-authoritative")
    args = parser.parse_args()
    require(SPEC_PATH.is_file(), "audit scope contract missing")
    scope_hash = sha_file(SPEC_PATH)
    args.output.mkdir(parents=True, exist_ok=False)
    runs = {name: load_run(name, cfg) for name, cfg in EXPECTED.items()}
    s, q = runs["SYMMETRY03"], runs["QPROMO2"]
    result = {
        "schema": "F4-cross-distribution-audit-v0.1",
        "status": "PASS_DESCRIPTIVE_AUDIT",
        "audit_scope_sha256": scope_hash,
        "analyzer_sha256": sha_file(Path(__file__)),
        "no_fits_or_prediction_rescoring": True,
        "runs": runs,
        "comparison": {
            "D_balanced_error_difference_QPROMO2_minus_SYMMETRY03": q["pooled_D_outcome_anchor"]["balanced_error"] - s["pooled_D_outcome_anchor"]["balanced_error"],
            "D_omega_difference_QPROMO2_minus_SYMMETRY03": q["pooled_D_outcome_anchor"]["omega_hat_clipped"] - s["pooled_D_outcome_anchor"]["omega_hat_clipped"],
        },
        "interpretation": "D calibration accessibility differed sharply between these qualification distributions. Both task banks use the same four-cue schedule design, but SYMMETRY-03 task blocks were structure-screened while QPROMO2 blocks were ordinary and unscreened. Differences in scored U* support, target margins, and leverage concentration describe where the sampled populations differ; because block seeds and selection procedures differ, this comparison does not identify structural screening as the sole cause.",
    }
    analysis_sha = write_json(args.output / "CROSS-DISTRIBUTION-AUDIT.json", result)
    write_report(args.output / "RESULTS.md", result)
    receipt = {
        "schema": "F4-cross-distribution-audit-receipt-v1", "status": "PASS_DESCRIPTIVE_AUDIT",
        "audit_scope_sha256": scope_hash, "analyzer_sha256": sha_file(Path(__file__)), "analysis_sha256": analysis_sha,
        "results_sha256": sha_file(args.output / "RESULTS.md"),
        "source_runs": {name: item["artifact_hashes"] for name, item in runs.items()},
        "no_fits_or_prediction_rescoring": True,
        "interpretation_boundary": "descriptive archaeology only; no causal attribution or measured REACH-03 authorization",
    }
    write_json(args.output / "AUDIT-RECEIPT.json", receipt)
    print(json.dumps({"status": result["status"], "output": str(args.output), "rows": {name: item["row_count"] for name, item in runs.items()}, "analysis_sha256": analysis_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
