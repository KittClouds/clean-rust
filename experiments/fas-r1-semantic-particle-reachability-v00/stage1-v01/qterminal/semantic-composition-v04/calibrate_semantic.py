#!/usr/bin/env python3
"""Train-only isotonic calibration for frozen Q-terminal semantic composition v04."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
V03_SOURCE = HERE.parent / "semantic-composition-v03"
sys.path.insert(0, str(V03_SOURCE))
import score_semantic as base  # noqa: E402

EXPECTED_MANIFEST_SHA256 = "a40d6f39d6b3d9813e0d7ac3acd9eac3c7bc01046cb8609db6af5a6dc7e6e073"


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = base.sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual.lower()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_value(row: dict[str, Any]) -> float:
    value = row["semantic_log_score"]
    return -math.inf if value is None else float(value)


def fit_isotonic(train_scores: np.ndarray, train_labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if len(train_scores) != len(train_labels) or not len(train_labels):
        raise ValueError("isotonic fit needs aligned nonempty training rows")
    if np.any(np.isnan(train_scores)) or np.any((train_labels != 0) & (train_labels != 1)):
        raise ValueError("invalid isotonic training values")
    unique_scores, inverse = np.unique(train_scores, return_inverse=True)
    counts = np.bincount(inverse).astype(np.int64)
    positives = np.bincount(inverse, weights=train_labels.astype(np.float64)).astype(np.float64)
    blocks: list[dict[str, float]] = []
    for x, count, positive in zip(unique_scores, counts, positives, strict=True):
        blocks.append({"lower": float(x), "upper": float(x), "count": float(count), "positive": float(positive)})
        while len(blocks) > 1:
            left, right = blocks[-2], blocks[-1]
            if left["positive"] / left["count"] <= right["positive"] / right["count"]:
                break
            blocks[-2:] = [{
                "lower": left["lower"], "upper": right["upper"],
                "count": left["count"] + right["count"],
                "positive": left["positive"] + right["positive"],
            }]
    upper = np.asarray([block["upper"] for block in blocks], dtype=np.float64)
    probability = np.asarray([block["positive"] / block["count"] for block in blocks], dtype=np.float64)
    if np.any(np.diff(probability) < -1e-15) or np.any(np.diff(upper) < 0):
        raise AssertionError("pool-adjacent-violators output is not monotone")
    summary = {
        "unique_training_scores": int(len(unique_scores)),
        "coefficient_block_count": int(len(blocks)),
        "training_rows": int(len(train_labels)),
        "training_positive_count": int(np.sum(train_labels)),
        "training_negative_count": int(len(train_labels) - np.sum(train_labels)),
        "blocks": [{"lower_score": block["lower"], "upper_score": block["upper"],
                    "rows": int(block["count"]), "valid_rate": block["positive"] / block["count"]}
                   for block in blocks],
    }
    return upper, probability, summary


def apply_isotonic(scores: np.ndarray, upper: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    indices = np.searchsorted(upper, scores, side="left")
    indices = np.minimum(indices, len(probabilities) - 1)
    return probabilities[indices]


def export_coefficients(output: Path, upper: np.ndarray, probabilities: np.ndarray,
                        training_ids_sha256: str, v03_score_sha256: str) -> dict[str, Any]:
    upper_le = np.asarray(upper, dtype="<f8", order="C")
    probability_le = np.asarray(probabilities, dtype="<f4", order="C")
    upper_bytes = upper_le.tobytes(order="C")
    probability_bytes = probability_le.tobytes(order="C")
    binary = upper_bytes + probability_bytes
    path = output / "isotonic-coefficients.f64f32le.bin"
    path.write_bytes(binary)
    metadata = {
        "schema": "R1_SEMANTIC_ISOTONIC_RUNTIME_EXPORT_V01",
        "method": "stepwise nondecreasing isotonic calibration",
        "input": "semantic_log_score=sum_j log(p_satisfied_j); JSON null corresponds to negative infinity",
        "lookup": "binary-search first upper_score_bound >= input; clamp to final block when input exceeds all bounds",
        "binary_file": path.name,
        "binary_sha256": base.sha256(path),
        "binary_bytes": len(binary),
        "fields": {
            "upper_score_bounds": {"dtype": "float64_le", "shape": [len(upper)], "byte_offset": 0,
                                   "byte_length": len(upper_bytes)},
            "validity_probabilities": {"dtype": "float32_le", "shape": [len(probabilities)],
                                       "byte_offset": len(upper_bytes), "byte_length": len(probability_bytes)},
        },
        "training_sample_ids_sha256": training_ids_sha256,
        "v03_candidate_scores_sha256": v03_score_sha256,
        "validation_or_test_labels_in_fit": False,
    }
    (output / "isotonic-export.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    blob = path.read_bytes()
    restored_upper = np.frombuffer(blob, dtype="<f8", count=len(upper), offset=0).astype(np.float64)
    restored_prob = np.frombuffer(blob, dtype="<f4", count=len(probabilities), offset=len(upper_bytes)).astype(np.float64)
    if not np.array_equal(restored_upper, upper) or not np.array_equal(restored_prob, probabilities.astype(np.float32).astype(np.float64)):
        raise ValueError("Rust coefficient binary readback mismatch")
    return metadata


def metric_group(indices: np.ndarray, rows: list[dict[str, Any]], labels: np.ndarray,
                 probabilities: dict[str, np.ndarray], ranking: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
        "count": int(len(indices)),
        "family_count": len({rows[int(i)]["family_id"] for i in indices}),
        "binary_metrics": {name: base.binary_metrics(labels[indices], values[indices], ranking[name][indices])
                           for name, values in probabilities.items()},
        "top1_metrics_by_feature_and_source": base.top1_metrics(indices, rows, labels, ranking),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--run-root", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01"))
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest-v04.json")
    parser.add_argument("--raw-run", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v03"))
    parser.add_argument("--output", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v04"))
    args = parser.parse_args()
    source_root, run_root = args.source_root.resolve(), args.run_root.resolve()
    manifest_path, raw_run = args.manifest.resolve(), args.raw_run.resolve()
    manifest_sha = require_hash(manifest_path, EXPECTED_MANIFEST_SHA256, "v04 calibration manifest")
    manifest = read_json(manifest_path)
    if manifest.get("schema") != "R1_QTERMINAL_SEMANTIC_ISOTONIC_CALIBRATION_V04":
        raise ValueError("unexpected v04 calibration manifest schema")
    v03_manifest = source_root / "qterminal" / "semantic-composition-v03" / "manifest-v03.json"
    selected = run_root / "run-v03" / "qterminal-data-v02" / "selected-candidates.jsonl"
    dataset_manifest_path = selected.parent / "dataset-manifest.json"
    support_path = source_root / "manifests" / "sensor-support-manifest-v02.json"
    v03_paths = {
        "v03_manifest": v03_manifest,
        "v03_script": source_root / "qterminal" / "semantic-composition-v03" / "score_semantic.py",
        "v03_receipt": raw_run / "receipt.json",
        "v03_report": raw_run / "report.json",
        "v03_candidate_scores": raw_run / "candidate-scores.jsonl",
        "v03_clause_probabilities": raw_run / "clause-probabilities.jsonl",
        "v03_identity_export": raw_run / "identity-head-export.json",
        "v03_identity_binary": raw_run / "identity-head-f32le.bin",
        "q_mix_manifest": source_root / "qterminal" / "manifest-v02.json",
        "support_manifest": support_path,
        "q_dataset_manifest": dataset_manifest_path,
        "selected_candidates": selected,
        "q_fitted_checkpoint": run_root / "run-v03" / "qterminal-fit-v02" / "qterminal-v02.pt",
    }
    expected = {
        "v03_manifest": manifest["raw_semantic_source"]["manifest_sha256"],
        "v03_script": manifest["raw_semantic_source"]["score_script_sha256"],
        "v03_receipt": manifest["raw_semantic_source"]["run_receipt_sha256"],
        "v03_report": manifest["raw_semantic_source"]["report_sha256"],
        "v03_candidate_scores": manifest["raw_semantic_source"]["candidate_scores_sha256"],
        "q_mix_manifest": manifest["dataset_lineage"]["q_mixture_manifest_sha256"],
        "support_manifest": manifest["dataset_lineage"]["support_manifest_sha256"],
        "q_dataset_manifest": manifest["dataset_lineage"]["q_dataset_manifest_sha256"],
        "selected_candidates": manifest["dataset_lineage"]["selected_candidates_sha256"],
        "q_fitted_checkpoint": manifest["dataset_lineage"]["q_fitted_checkpoint_sha256"],
    }
    hashes = {key: require_hash(v03_paths[key], digest, key) for key, digest in expected.items()}
    v03_receipt, v03_report = read_json(v03_paths["v03_receipt"]), read_json(v03_paths["v03_report"])
    if v03_receipt.get("status") != "COMPLETE" or v03_receipt.get("fitting_performed") or v03_receipt.get("calibration_performed"):
        raise ValueError("v03 receipt is incomplete or reports fit/calibration")
    output_hashes = {item["path"]: item["sha256"] for item in v03_receipt["output_files"]}
    for key in ("v03_candidate_scores", "v03_clause_probabilities", "v03_identity_export", "v03_identity_binary"):
        if output_hashes.get(v03_paths[key].name) != base.sha256(v03_paths[key]):
            raise ValueError(f"v03 receipt output hash mismatch for {key}")
    data_manifest = read_json(dataset_manifest_path)
    if data_manifest.get("selected_candidates_sha256") != hashes["selected_candidates"]:
        raise ValueError("Q prepared data does not bind selected candidate source")
    if data_manifest.get("candidate_jsonl_sha256") != v03_receipt["input_sha256"]["raw_candidate_records"]:
        raise ValueError("Q prepared data/raw candidate lineage mismatch")
    if v03_report.get("lineage", {}).get("inputs_sha256", {}).get("q_dataset_manifest") != hashes["q_dataset_manifest"]:
        raise ValueError("v03 report does not bind this Q prepared dataset")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing calibration output: {args.output}")

    score_rows = base.read_jsonl(v03_paths["v03_candidate_scores"])
    selected_rows = base.read_jsonl(selected)
    if len(score_rows) != len(selected_rows) or not score_rows:
        raise ValueError("raw semantic scores and selected Q candidate rows differ in length")
    for index, (scored, source) in enumerate(zip(score_rows, selected_rows, strict=True)):
        for name in ("sample_id", "task_id", "feature_id", "family_id", "split", "source_kind"):
            if scored[name] != source[name]:
                raise ValueError(f"candidate row {index} {name} differs between v03 score and frozen Q data")
        if int(scored["posthoc_valid"]) != int(source["posthoc_valid"]):
            raise ValueError(f"candidate row {index} label differs between v03 score and frozen Q data")
    family_split_name = np.asarray([row["split"] for row in score_rows], dtype="U10")
    labels = np.asarray([int(row["posthoc_valid"]) for row in selected_rows], dtype=np.uint8)
    all_scores = np.asarray([score_value(row) for row in score_rows], dtype=np.float64)
    train_indices = np.flatnonzero(family_split_name == "train")
    if set(family_split_name.tolist()) != {"train", "validation", "test"}:
        raise ValueError("Q candidate rows do not contain the three frozen splits")
    families = {split: {row["family_id"] for row in score_rows if row["split"] == split}
                for split in ("train", "validation", "test")}
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        if families[left] & families[right]:
            raise ValueError(f"Q family leakage between {left} and {right}")
    if len(train_indices) != 520 or int(np.sum(labels[train_indices])) != 260:
        raise ValueError("train-only isotonic calibration support differs from frozen Q-v02 training split")

    upper, calibrated_blocks, fit_summary = fit_isotonic(all_scores[train_indices], labels[train_indices])
    calibrated = apply_isotonic(all_scores, upper, calibrated_blocks).astype(np.float32).astype(np.float64)
    raw_probability = np.asarray([float(row["semantic_probability"]) for row in score_rows], dtype=np.float64)
    q_probability = np.asarray([float(row["q_v02_probability"]) for row in score_rows], dtype=np.float64)
    oracle_probability = np.asarray([float(row["private_kind_oracle_probability"]) for row in score_rows], dtype=np.float64)
    rankings = {
        "raw_identity_composition": all_scores,
        "calibrated_identity_composition": calibrated,
        "q_v02": np.asarray([float(row["q_v02_probability"]) for row in score_rows]),
        "private_kind_oracle": oracle_probability,
    }
    probabilities = {
        "raw_identity_composition": raw_probability,
        "calibrated_identity_composition": calibrated,
        "q_v02": q_probability,
        "private_kind_oracle": oracle_probability,
    }
    split_metrics: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        ix = np.flatnonzero(family_split_name == split)
        split_metrics[split] = metric_group(ix, score_rows, labels, probabilities, rankings)
    support = read_json(support_path)
    train_sensor_families = {row["family_id"] for row in support["family_roster"] if row["split"] == "train"}
    test_families = sorted(families["test"])
    strata = {"overlap_sensor_identity_train": [], "unseen_to_identity_train": []}
    for family in test_families:
        strata["overlap_sensor_identity_train" if family in train_sensor_families else "unseen_to_identity_train"].append(family)
    if {key: len(value) for key, value in strata.items()} != {"overlap_sensor_identity_train": 2, "unseen_to_identity_train": 2}:
        raise ValueError(f"Q test sensor-overlap family split changed: {strata}")
    stratified_metrics: dict[str, Any] = {}
    for name, family_ids in strata.items():
        ix = np.asarray([i for i, row in enumerate(score_rows) if row["split"] == "test" and row["family_id"] in family_ids], dtype=np.int64)
        stratified_metrics[name] = metric_group(ix, score_rows, labels, probabilities, rankings)
        stratified_metrics[name]["families"] = family_ids
    if {name: group["count"] for name, group in stratified_metrics.items()} != {
        "overlap_sensor_identity_train": 11, "unseen_to_identity_train": 13
    }:
        raise ValueError("Q test row counts differ from v03's bound overlap strata")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    training_ids = "\n".join(str(score_rows[i]["sample_id"]) for i in train_indices).encode("utf-8")
    training_ids_sha = hashlib.sha256(training_ids).hexdigest()
    coefficients = export_coefficients(output, upper, calibrated_blocks, training_ids_sha, hashes["v03_candidate_scores"])
    # Copy the unchanged frozen linear-head package so this output is self-contained for runtime use.
    import shutil
    for key in ("v03_identity_binary", "v03_identity_export"):
        shutil.copyfile(v03_paths[key], output / v03_paths[key].name)
    calibrated_rows = []
    for index, row in enumerate(score_rows):
        calibrated_rows.append({
            "sample_id": row["sample_id"], "task_id": row["task_id"], "feature_id": row["feature_id"],
            "family_id": row["family_id"], "split": row["split"], "source_kind": row["source_kind"],
            "posthoc_valid": labels[index], "semantic_log_score": all_scores[index],
            "raw_semantic_probability": raw_probability[index], "calibrated_validity_probability": calibrated[index],
            "q_v02_probability": q_probability[index], "private_kind_oracle_probability": oracle_probability[index],
        })
    score_output = output / "candidate-scores-calibrated.jsonl"
    base.write_jsonl(score_output, calibrated_rows)
    report = {
        "schema": "R1_QTERMINAL_SEMANTIC_ISOTONIC_REPORT_V04",
        "status": "TRAIN_ONLY_CALIBRATION_COMPLETE",
        "fit": {"algorithm": "pool-adjacent-violators isotonic regression", "fit_split": "train only",
                "validation_or_test_labels_used_for_fit": False, "training_family_count": len(families["train"]),
                "training_sample_ids_sha256": training_ids_sha, **fit_summary},
        "metrics_by_split": split_metrics,
        "test_strata": stratified_metrics,
        "calibration_deltas": {
            split: {key: (None if split_metrics[split]["binary_metrics"]["calibrated_identity_composition"].get(key) is None
                           or split_metrics[split]["binary_metrics"]["raw_identity_composition"].get(key) is None
                           else split_metrics[split]["binary_metrics"]["calibrated_identity_composition"][key]
                           - split_metrics[split]["binary_metrics"]["raw_identity_composition"][key])
                   for key in ("accuracy_at_0.5", "balanced_accuracy", "brier_score", "binary_cross_entropy", "roc_auc")}
            for split in ("train", "validation", "test")
        },
        "test_generalization_warning": "aggregate test combines identity-sensor-train-overlap families and families unseen to identity training; use the reported 11-row and 13-row strata separately",
        "runtime_export": coefficients,
        "lineage": {"manifest_sha256": manifest_sha, "input_sha256": hashes,
                    "v03_receipt_sha256": hashes["v03_receipt"],
                    "identity_head_binary_sha256": base.sha256(output / "identity-head-f32le.bin"),
                    "identity_head_export_sha256": base.sha256(output / "identity-head-export.json")},
        "interpretation": "Monotone calibration cannot improve the raw ranking except by collapsing ties. The v03 raw scorer already ties Q-v02 at top-1 on this four-family test; this run evaluates probability calibration separately.",
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(base.json_safe(report), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = [score_output, report_path, output / "isotonic-coefficients.f64f32le.bin",
                 output / "isotonic-export.json", output / "identity-head-f32le.bin", output / "identity-head-export.json"]
    receipt = {
        "schema": "R1_QTERMINAL_SEMANTIC_ISOTONIC_RECEIPT_V04", "status": "COMPLETE",
        "manifest_sha256": manifest_sha, "source_script_sha256": base.sha256(Path(__file__).resolve()),
        "source_root": str(source_root), "run_root": str(run_root),
        "input_sha256": hashes,
        "output_files": [{"path": path.name, "bytes": path.stat().st_size, "sha256": base.sha256(path)} for path in artifacts],
        "report_sha256": base.sha256(report_path), "train_only_fit": True,
        "validation_or_test_labels_used_for_fit": False,
        "q_v02_modified": False, "v03_raw_result_modified": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "receipt_sha256": base.sha256(output / "receipt.json"),
                      "report_sha256": receipt["report_sha256"], "fit_summary": fit_summary,
                      "validation_metrics": split_metrics["validation"]["binary_metrics"],
                      "test_metrics": split_metrics["test"]["binary_metrics"],
                      "test_strata_metrics": {key: value["binary_metrics"] for key, value in stratified_metrics.items()},
                      "calibration_deltas": report["calibration_deltas"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
