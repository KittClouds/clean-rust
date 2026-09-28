from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from s12_math import canonical_json, entry, sha256_file, tree_root


RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
S11 = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
EVENTS = S11 / "inputs" / "panel" / "selected-events-v02.jsonl"
QUARTETS = S11 / "inputs" / "panel" / "selected-quartets-v02.jsonl"
CONTRACT = RUN / "inputs" / "protocol" / "s12-execution-contract-v01.json"
RAW = RUN / "raw-v01"
OUT = RUN / "analysis-v01"
N_ROWS = 21_272
N_QUARTETS = 5_318
N_SITES = 6
N_STRENGTHS = 4
N_ARMS = 9
N_ENDPOINTS = 2
N_CLASSES = 3
STRENGTHS = (0.0, 0.25, 0.5, 1.0)
SITE_TABLE = ((4, "M"), (4, "F"), (8, "M"), (8, "F"), (12, "M"), (12, "F"))
ENDPOINTS = ("M", "F")
VARIANTS = ("A", "C", "E", "P")
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise RuntimeError(f"unterminated JSONL row {line_number}: {path}")
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def verify_seal(base: Path, seal_path: Path) -> dict[str, Any]:
    seal = read_json(seal_path)
    actual = [entry(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    if actual != sorted(seal["entries"], key=lambda item: item["path"]) or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError(f"S12 input seal mismatch: {seal_path}")
    return seal


def metric_summary(labels: np.ndarray, predictions: np.ndarray) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64)
    p = np.asarray(predictions, dtype=np.int64)
    if y.shape != p.shape or y.ndim != 1 or not np.isin(y, (0, 1, 2)).all() or not np.isin(p, (0, 1, 2)).all():
        raise RuntimeError("invalid metric labels or predictions")
    matrix = np.zeros((3, 3), dtype=np.int64)
    np.add.at(matrix, (y, p), 1)
    support = matrix.sum(axis=1)
    if np.any(support == 0):
        raise RuntimeError("a metric slice has no support for a target class")
    recall = np.diag(matrix) / support
    return {
        "n": int(y.size),
        "confusion_matrix_true_rows_pred_columns": matrix.tolist(),
        "per_class_support": support.tolist(),
        "per_class_recall": recall.tolist(),
        "accuracy": float(np.trace(matrix) / y.size),
        "balanced_accuracy": float(np.mean(recall)),
    }


def target_margin(logits: np.ndarray, labels: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if values.shape != (y.size, 3) or not np.isfinite(values).all() or not np.isin(y, (0, 1, 2)).all():
        raise RuntimeError("invalid target-margin logits or labels")
    rows = np.arange(len(y))
    target_values = values[rows, y]
    rivals = values.copy()
    rivals[rows, y] = -np.inf
    return target_values - np.max(rivals, axis=1)


def make_event_groups(events: list[dict[str, Any]], quartets: list[dict[str, Any]]) -> tuple[list[list[int]], np.ndarray, dict[str, Any]]:
    if len(events) != N_ROWS or len(quartets) != N_QUARTETS:
        raise RuntimeError("S11 panel row/quartet count mismatch")
    row_by_event = {event["event_id"]: i for i, event in enumerate(events)}
    if len(row_by_event) != N_ROWS:
        raise RuntimeError("S11 event IDs are not unique")
    groups: list[list[int]] = []
    quartet_labels = np.empty(N_QUARTETS, dtype=np.int64)
    variant_digest = hashlib.sha256()
    for qi, quartet in enumerate(quartets):
        variant_events = quartet.get("variants", [])
        if [item.get("variant_id") for item in variant_events] != list(VARIANTS):
            raise RuntimeError(f"S11 quartet variant order mismatch at quartet {qi}")
        indices = [row_by_event[item["event_id"]] for item in variant_events]
        if len(indices) != 4 or len(set(indices)) != 4:
            raise RuntimeError(f"S11 quartet rows are not unique at quartet {qi}")
        label_values = [int(events[index]["exact_target"]) for index in indices]
        if len(set(label_values)) != 1 or label_values[0] != int(quartet["exact_target"]):
            raise RuntimeError(f"S11 quartet target mismatch at quartet {qi}")
        if [events[index]["variant_id"] for index in indices] != list(VARIANTS):
            raise RuntimeError(f"S11 event/quartet join mismatch at quartet {qi}")
        groups.append(indices)
        quartet_labels[qi] = label_values[0]
        variant_digest.update(canonical_json({"quartet_id": quartet["quartet_id"], "rows": indices, "target": label_values[0]}) + b"\n")
    counts = {str(label): int(np.count_nonzero(quartet_labels == label)) for label in (0, 1, 2)}
    return groups, quartet_labels, {"quartet_order_sha256": variant_digest.hexdigest(), "class_quartet_counts": counts}


def baseline_metric_gate(baseline_predictions: np.ndarray, labels: np.ndarray, contract: dict[str, Any]) -> dict[str, Any]:
    expected = contract["observers"]["terminal_s11_context"]
    reports = {}
    for endpoint_index, surface in enumerate(ENDPOINTS):
        report = metric_summary(labels, baseline_predictions[:, endpoint_index])
        exp_recalls = expected[f"{surface}_class_recall"]
        metrics = ("accuracy", "balanced_accuracy")
        for metric in metrics:
            if abs(report[metric] - float(expected[f"{surface}_{metric}"])) > 1e-14:
                raise RuntimeError(f"S12 baseline {surface} {metric} differs from sealed S11 context")
        if not np.allclose(report["per_class_recall"], exp_recalls, rtol=0.0, atol=1e-14):
            raise RuntimeError(f"S12 baseline {surface} recalls differ from sealed S11 context")
        reports[surface] = report
    return {"matches_s11_context": True, "metrics": reports}


def cell_summaries(
    labels: np.ndarray,
    events: list[dict[str, Any]],
    quartet_groups: list[list[int]],
    logits: np.memmap,
    probabilities: np.memmap,
    predictions_out: np.memmap,
    target_margins_out: np.memmap,
    pair_margins_out: np.memmap,
) -> tuple[dict[str, Any], np.ndarray]:
    summary: dict[str, Any] = {"metric_definitions": {"prediction": "argmax frozen-observer probe logits; class order 0,1,2", "target_margin": "true-target probe logit minus the larger of the two rival probe logits", "pair_margin_order": [[0, 1], [0, 2], [1, 2]]}, "sites": []}
    primary_event = np.empty((N_ROWS, N_SITES), dtype="<f8")
    variant_masks = {variant: np.asarray([event["variant_id"] == variant for event in events]) for variant in VARIANTS}
    target_masks = {label: labels == label for label in (0, 1, 2)}
    for site_index, (layer, surface) in enumerate(SITE_TABLE):
        site_report: dict[str, Any] = {"site_index": site_index, "layer": layer, "surface": surface, "primary_terminal_observer": surface, "strengths": []}
        for strength_index, strength in enumerate(STRENGTHS):
            strength_report: dict[str, Any] = {"strength": strength, "arms": []}
            for arm in range(N_ARMS):
                arm_name = "target" if arm == 0 else f"random_{arm}"
                arm_report: dict[str, Any] = {"arm": arm_name, "endpoints": []}
                for endpoint_index, endpoint in enumerate(ENDPOINTS):
                    cell_logits = np.asarray(logits[:, site_index, strength_index, arm, endpoint_index], dtype=np.float32)
                    pred = np.argmax(cell_logits, axis=1).astype(np.int8)
                    margins = target_margin(cell_logits, labels)
                    pair_margins = np.column_stack([cell_logits[:, a] - cell_logits[:, b] for a, b in PAIR_ORDER]).astype("<f4")
                    predictions_out[:, site_index, strength_index, arm, endpoint_index] = pred
                    target_margins_out[:, site_index, strength_index, arm, endpoint_index] = margins.astype("<f4")
                    pair_margins_out[:, site_index, strength_index, arm, endpoint_index, :] = pair_margins
                    endpoint_report: dict[str, Any] = {"endpoint": endpoint, "all_rows": metric_summary(labels, pred), "mean_target_margin": float(np.mean(margins, dtype=np.float64)), "mean_probe_probabilities_by_class": np.mean(np.asarray(probabilities[:, site_index, strength_index, arm, endpoint_index], dtype=np.float64), axis=0).tolist()}
                    sham_logits = np.asarray(logits[:, site_index, 0, 0, endpoint_index], dtype=np.float32)
                    sham_pred = np.argmax(sham_logits, axis=1).astype(np.int8)
                    sham_margin = target_margin(sham_logits, labels)
                    sham_metrics = metric_summary(labels, sham_pred)
                    current_metrics = endpoint_report["all_rows"]
                    endpoint_report["sham_relative_changes"] = {
                        "accuracy_delta": current_metrics["accuracy"] - sham_metrics["accuracy"],
                        "balanced_accuracy_delta": current_metrics["balanced_accuracy"] - sham_metrics["balanced_accuracy"],
                        "per_class_recall_delta": (np.asarray(current_metrics["per_class_recall"]) - np.asarray(sham_metrics["per_class_recall"])).tolist(),
                        "mean_target_margin_delta": float(np.mean(margins, dtype=np.float64) - np.mean(sham_margin, dtype=np.float64)),
                    }
                    endpoint_report["by_variant"] = {variant: metric_summary(labels[mask], pred[mask]) for variant, mask in variant_masks.items()}
                    endpoint_report["by_exact_target"] = {}
                    for label, mask in target_masks.items():
                        selected = pred[mask]
                        transitions = np.zeros((3, 3), dtype=np.int64)
                        baseline_pred = sham_pred[mask]
                        np.add.at(transitions, (baseline_pred, selected), 1)
                        endpoint_report["by_exact_target"][str(label)] = {
                            "n": int(mask.sum()),
                            "accuracy": float(np.mean(selected == label)),
                            "mean_target_margin": float(np.mean(margins[mask], dtype=np.float64)),
                            "sham_to_intervention_prediction_transition_matrix": transitions.tolist(),
                        }
                    if strength_index == 0 and arm == 0:
                        endpoint_report["sham_prediction_transitions"] = {"changed": 0, "matrix": np.diag(np.bincount(pred, minlength=3)).tolist()}
                    else:
                        sham_pred = np.asarray(predictions_out[:, site_index, 0, 0, endpoint_index], dtype=np.int8)
                        transition = np.zeros((3, 3), dtype=np.int64)
                        np.add.at(transition, (sham_pred.astype(np.int64), pred.astype(np.int64)), 1)
                        endpoint_report["sham_prediction_transitions"] = {"changed": int(np.count_nonzero(sham_pred != pred)), "matrix": transition.tolist()}
                    arm_report["endpoints"].append(endpoint_report)
                    if endpoint == surface:
                        if strength_index == 3 and arm == 0:
                            primary_event[:, site_index] = margins.astype(np.float64)
                strength_report["arms"].append(arm_report)
            site_report["strengths"].append(strength_report)
        # Replace the event-level target margin with the contracted target-vs-control margin difference.
        endpoint_index = 0 if surface == "M" else 1
        target_logits = np.asarray(logits[:, site_index, 3, 0, endpoint_index], dtype=np.float32)
        target_values = target_margin(target_logits, labels)
        control_logits = np.asarray(logits[:, site_index, 3, 1:9, endpoint_index], dtype=np.float32)
        control_values = np.stack([target_margin(control_logits[:, arm, :], labels) for arm in range(8)], axis=1)
        primary_event[:, site_index] = control_values.mean(axis=1, dtype=np.float64) - target_values
        summary["sites"].append(site_report)
    return summary, primary_event


def primary_analysis(
    event_contrasts: np.ndarray,
    groups: list[list[int]],
    quartet_labels: np.ndarray,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    quartet_values = np.empty((N_QUARTETS, N_SITES), dtype="<f8")
    for index, members in enumerate(groups):
        quartet_values[index] = event_contrasts[members].mean(axis=0, dtype=np.float64)
    estimates = quartet_values.mean(axis=0, dtype=np.float64)
    plan_meta = contract["parents"]["bootstrap_plan"]
    plan = np.memmap(RUN / plan_meta["path"], dtype="<u4", mode="r", shape=tuple(plan_meta["shape"]))
    if plan.shape != (10_000, N_QUARTETS):
        raise RuntimeError("S12 bootstrap plan shape mismatch")
    boot = np.empty((plan.shape[0], N_SITES), dtype="<f8")
    for start in range(0, plan.shape[0], 64):
        stop = min(start + 64, plan.shape[0])
        selection = np.asarray(plan[start:stop], dtype=np.int64)
        boot[start:stop] = quartet_values[selection].mean(axis=1, dtype=np.float64)
    standard_error = boot.std(axis=0, ddof=1)
    if not np.isfinite(standard_error).all() or np.any(standard_error <= 0.0):
        raise RuntimeError("S12 simultaneous bootstrap has a zero or invalid site standard error")
    standardized = (boot - estimates[None, :]) / standard_error[None, :]
    max_abs = np.max(np.abs(standardized), axis=1)
    critical = float(np.quantile(max_abs, 0.95, method="linear"))
    intervals = np.column_stack((estimates - critical * standard_error, estimates + critical * standard_error))
    sites = []
    for index, (layer, surface) in enumerate(SITE_TABLE):
        lower, upper = intervals[index]
        sites.append({
            "site_index": index,
            "layer": layer,
            "surface": surface,
            "same_surface_terminal_observer": surface,
            "estimate_random_minus_target_margin": float(estimates[index]),
            "bootstrap_standard_error": float(standard_error[index]),
            "simultaneous_95_percent_interval": [float(lower), float(upper)],
            "selective_causal_dependence_supported": bool(lower > 0.0),
        })
    report = {
        "primary_estimand": "fixed-stratum weighted mean over quartets of the A/C/E/P average of (mean random-control target-vs-best-rival probe margin - target-plane target-vs-best-rival probe margin), lambda=1, same-surface terminal observer",
        "interval_method": {
            "bootstrap_replicates": 10_000,
            "shared_plan": True,
            "bootstrap_standard_error": "sample standard deviation of bootstrap estimates with ddof=1",
            "standardized_deviation": "(bootstrap_estimate - point_estimate) / bootstrap_standard_error",
            "simultaneous_statistic": "replicate-wise maximum absolute standardized deviation across six sites",
            "critical_quantile": "NumPy quantile at 0.95 with method=linear",
            "interval": "point estimate +/- critical quantile * site bootstrap standard error",
        },
        "critical_value": critical,
        "sites": sites,
        "all_sites_gate": False,
    }
    return report, quartet_values, boot


def main() -> int:
    raw_seal = verify_seal(RAW, RAW / "raw-seal-v01.json")
    execution = read_json(RUN / "execution-receipt-v01.json")
    if execution.get("complete") is not True or execution.get("raw_output_root_sha256") != raw_seal["root_sha256"]:
        raise RuntimeError("S12 execution receipt does not bind the sealed raw outputs")
    contract = read_json(CONTRACT)
    events = read_jsonl(EVENTS)
    quartets = read_jsonl(QUARTETS)
    labels = np.asarray([int(event["exact_target"]) for event in events], dtype=np.int64)
    groups, quartet_labels, panel_info = make_event_groups(events, quartets)
    counts = {str(label): int(np.count_nonzero(quartet_labels == label)) for label in (0, 1, 2)}
    if counts != contract["population"]["class_quartet_counts"]:
        raise RuntimeError("S12 class-stratified bootstrap counts differ from contract")

    baseline_pred = np.fromfile(RUN / "baseline-v01" / "baseline-predictions-v01.i64le", dtype="<i8").reshape(N_ROWS, 2)
    baseline_gate = baseline_metric_gate(baseline_pred, labels, contract)
    raw_logits = np.memmap(RAW / "intervention-probe-logits-v01.f32le", dtype="<f4", mode="r", shape=(N_ROWS, 6, 4, 9, 2, 3))
    raw_probabilities = np.memmap(RAW / "intervention-probe-probabilities-v01.f32le", dtype="<f4", mode="r", shape=(N_ROWS, 6, 4, 9, 2, 3))
    checks = np.memmap(RAW / "intervention-checks-v01.f32le", dtype="<f4", mode="r", shape=(N_ROWS, 6, 4, 9, 10))
    if not np.isfinite(raw_logits).all() or not np.isfinite(raw_probabilities).all() or not np.isfinite(checks).all():
        raise RuntimeError("S12 sealed raw matrices contain non-finite values")

    existing_seal = OUT / "analysis-seal-v01.json"
    if existing_seal.exists():
        prior = verify_seal(OUT, existing_seal)
        prior_result = read_json(OUT / "s12-analysis-result-v01.json")
        if prior_result.get("parents", {}).get("raw_output_root_sha256") != raw_seal["root_sha256"]:
            raise RuntimeError("existing S12 analysis seal binds a different raw result")
        print(json.dumps({"analysis_root": prior["root_sha256"], "primary": prior_result["primary"]}, indent=2), flush=True)
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    pred_path = OUT / "event-predictions-v01.i8le"
    target_path = OUT / "event-target-margins-v01.f32le"
    pair_path = OUT / "event-pair-margins-v01.f32le"
    pred_out = np.memmap(pred_path, dtype="i1", mode="w+", shape=(N_ROWS, 6, 4, 9, 2))
    target_out = np.memmap(target_path, dtype="<f4", mode="w+", shape=(N_ROWS, 6, 4, 9, 2))
    pair_out = np.memmap(pair_path, dtype="<f4", mode="w+", shape=(N_ROWS, 6, 4, 9, 2, 3))
    cell_report, primary_events = cell_summaries(labels, events, groups, raw_logits, raw_probabilities, pred_out, target_out, pair_out)
    pred_out.flush()
    target_out.flush()
    pair_out.flush()
    del pred_out, target_out, pair_out
    event_contrast_path = OUT / "primary-event-contrasts-v01.f64le"
    quartet_contrast_path = OUT / "primary-quartet-contrasts-v01.f64le"
    bootstrap_path = OUT / "primary-bootstrap-estimates-v01.f64le"
    primary_events.tofile(event_contrast_path)
    primary_report, quartet_values, bootstrap_estimates = primary_analysis(primary_events, groups, quartet_labels, contract)
    quartet_values.tofile(quartet_contrast_path)
    bootstrap_estimates.tofile(bootstrap_path)

    report = {
        "result_id": "FAS_S12_OBSERVER_PLANE_CAUSAL_DEPENDENCE_RESULT_V01",
        "complete": True,
        "disposition": "ANALYSIS_COMPLETE",
        "claim_scope": contract["claim_scope"],
        "parents": {
            "execution_receipt_sha256": sha256_file(RUN / "execution-receipt-v01.json")[0],
            "raw_output_root_sha256": raw_seal["root_sha256"],
            "contract_sha256": sha256_file(CONTRACT)[0],
        },
        "population": {"rows": N_ROWS, "quartets": N_QUARTETS, "panel_order_sha256": panel_info["quartet_order_sha256"], "class_quartet_counts": counts},
        "baseline_s11_metric_gate": baseline_gate,
        "primary": primary_report,
        "secondary": cell_report,
        "outputs": [
            {"path": pred_path.name, "shape": [N_ROWS, 6, 4, 9, 2], "dtype": "i1", "sha256": sha256_file(pred_path)[0], "bytes": sha256_file(pred_path)[1]},
            {"path": target_path.name, "shape": [N_ROWS, 6, 4, 9, 2], "dtype": "<f4", "sha256": sha256_file(target_path)[0], "bytes": sha256_file(target_path)[1]},
            {"path": pair_path.name, "shape": [N_ROWS, 6, 4, 9, 2, 3], "dtype": "<f4", "sha256": sha256_file(pair_path)[0], "bytes": sha256_file(pair_path)[1]},
            {"path": event_contrast_path.name, "shape": [N_ROWS, 6], "dtype": "<f8", "sha256": sha256_file(event_contrast_path)[0], "bytes": sha256_file(event_contrast_path)[1]},
            {"path": quartet_contrast_path.name, "shape": [N_QUARTETS, 6], "dtype": "<f8", "sha256": sha256_file(quartet_contrast_path)[0], "bytes": sha256_file(quartet_contrast_path)[1]},
            {"path": bootstrap_path.name, "shape": [10_000, 6], "dtype": "<f8", "sha256": sha256_file(bootstrap_path)[0], "bytes": sha256_file(bootstrap_path)[1]},
        ],
    }
    write_json(OUT / "s12-analysis-result-v01.json", report)
    write_json(OUT / "s12-secondary-metrics-v01.json", cell_report)
    output_entries = [entry(path, OUT) for path in OUT.iterdir() if path.is_file() and path.name != "analysis-seal-v01.json"]
    output_entries.sort(key=lambda item: item["path"])
    write_json(OUT / "analysis-seal-v01.json", {"seal_id": "FAS_S12_ANALYSIS_SEAL_V01", "entries": output_entries, "root_sha256": tree_root(output_entries)})
    print(json.dumps({"analysis_root": tree_root(output_entries), "primary": primary_report}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
