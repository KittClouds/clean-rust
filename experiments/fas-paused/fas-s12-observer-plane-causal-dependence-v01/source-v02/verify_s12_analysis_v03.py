from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from s12_math import canonical_json, entry, sha256_file, tree_root


RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02")
S11 = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
RAW = RUN / "raw-v02"
ANALYSIS = RUN / "analysis-v02"
OUT = RUN / "independent-verification-v02.json"
EVENTS_PATH = S11 / "inputs" / "panel" / "selected-events-v02.jsonl"
QUARTETS_PATH = S11 / "inputs" / "panel" / "selected-quartets-v02.jsonl"
CONTRACT_PATH = RUN / "inputs" / "protocol" / "s12-execution-contract-v02.json"
ROWS = 21_272
QUARTETS = 5_318
SITES = ((4, "M"), (4, "F"), (8, "M"), (8, "F"), (12, "M"), (12, "F"))
STRENGTHS = (0.0, 0.25, 0.5, 1.0)
ARMS = 9
ENDPOINTS = ("M", "F")
VARIANTS = ("A", "C", "E", "P")
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def verify_seal(base: Path, path: Path) -> dict[str, Any]:
    seal = read_json(path)
    rows = [entry(base.joinpath(*record["path"].split("/")), base) for record in seal["entries"]]
    if rows != sorted(seal["entries"], key=lambda item: item["path"]) or tree_root(rows) != seal["root_sha256"]:
        raise RuntimeError(f"independent verifier found invalid tree seal: {path}")
    return seal


def metrics_reference(labels: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    matrix = [[0, 0, 0] for _ in range(3)]
    for truth, guess in zip(labels.tolist(), pred.tolist(), strict=True):
        matrix[int(truth)][int(guess)] += 1
    support = [sum(row) for row in matrix]
    recall = [matrix[c][c] / support[c] for c in range(3)]
    return {
        "n": len(labels),
        "confusion_matrix_true_rows_pred_columns": matrix,
        "per_class_support": support,
        "per_class_recall": recall,
        "accuracy": sum(matrix[c][c] for c in range(3)) / len(labels),
        "balanced_accuracy": sum(recall) / 3,
    }


def margin_reference(row_logits: np.ndarray, target: int) -> float:
    # Match the analysis contract's FP64 margin arithmetic. The raw array is
    # stored as FP32; subtracting its NumPy scalars directly rounds the margin
    # in FP32 before the float conversion and creates avoidable replay drift.
    values = np.asarray(row_logits, dtype=np.float64)
    return float(values[target] - max(values[c] for c in range(3) if c != target))


def assert_numeric(actual: Any, expected: Any, label: str, tolerance: float = 2e-12) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise RuntimeError(f"analysis object key mismatch: {label}")
        for key in expected:
            assert_numeric(actual[key], expected[key], f"{label}.{key}", tolerance)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise RuntimeError(f"analysis list shape mismatch: {label}")
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            assert_numeric(left, right, f"{label}[{index}]", tolerance)
    elif isinstance(expected, (float, np.floating)):
        if not np.isfinite(float(actual)) or abs(float(actual) - float(expected)) > tolerance:
            raise RuntimeError(f"analysis numeric mismatch: {label}: {actual} vs {expected}")
    elif actual != expected:
        raise RuntimeError(f"analysis value mismatch: {label}: {actual!r} vs {expected!r}")


def main() -> int:
    raw_seal = verify_seal(RAW, RAW / "raw-seal-v02.json")
    analysis_seal = verify_seal(ANALYSIS, ANALYSIS / "analysis-seal-v02.json")
    result = read_json(ANALYSIS / "s12-analysis-result-v02.json")
    secondary = read_json(ANALYSIS / "s12-secondary-metrics-v02.json")
    contract = read_json(CONTRACT_PATH)
    events = read_jsonl(EVENTS_PATH)
    quartets = read_jsonl(QUARTETS_PATH)
    if len(events) != ROWS or len(quartets) != QUARTETS or len({row["event_id"] for row in events}) != ROWS:
        raise RuntimeError("independent verifier panel dimensions or identities mismatch")
    row_for_event = {row["event_id"]: i for i, row in enumerate(events)}
    labels = np.asarray([int(row["exact_target"]) for row in events], dtype=np.int64)
    variants = [row["variant_id"] for row in events]
    groups: list[list[int]] = []
    quartet_labels = np.empty(QUARTETS, dtype=np.int64)
    for qi, quartet in enumerate(quartets):
        children = quartet["variants"]
        if [child["variant_id"] for child in children] != list(VARIANTS):
            raise RuntimeError(f"independent verifier quartet order mismatch at {qi}")
        indices = [row_for_event[child["event_id"]] for child in children]
        targets = {int(events[i]["exact_target"]) for i in indices}
        if len(indices) != 4 or len(set(indices)) != 4 or targets != {int(quartet["exact_target"])}:
            raise RuntimeError(f"independent verifier quartet join mismatch at {qi}")
        groups.append(indices)
        quartet_labels[qi] = int(quartet["exact_target"])
    observed_counts = {str(c): int(np.count_nonzero(quartet_labels == c)) for c in (0, 1, 2)}
    if observed_counts != contract["population"]["class_quartet_counts"]:
        raise RuntimeError("independent verifier class strata mismatch")

    shape = (ROWS, 6, 4, ARMS, 2, 3)
    logits = np.memmap(RAW / "intervention-probe-logits-v02.f32le", dtype="<f4", mode="r", shape=shape)
    probabilities = np.memmap(RAW / "intervention-probe-probabilities-v02.f32le", dtype="<f4", mode="r", shape=shape)
    checks = np.memmap(RAW / "intervention-checks-v02.f32le", dtype="<f4", mode="r", shape=(ROWS, 6, 4, ARMS, 10))
    pred_out = np.memmap(ANALYSIS / "event-predictions-v02.i8le", dtype="i1", mode="r", shape=(ROWS, 6, 4, 9, 2))
    target_out = np.memmap(ANALYSIS / "event-target-margins-v02.f32le", dtype="<f4", mode="r", shape=(ROWS, 6, 4, 9, 2))
    pairs_out = np.memmap(ANALYSIS / "event-pair-margins-v02.f32le", dtype="<f4", mode="r", shape=(ROWS, 6, 4, 9, 2, 3))
    event_contrasts_saved = np.fromfile(ANALYSIS / "primary-event-contrasts-v02.f64le", dtype="<f8").reshape(ROWS, 6)
    quartet_contrasts_saved = np.fromfile(ANALYSIS / "primary-quartet-contrasts-v02.f64le", dtype="<f8").reshape(QUARTETS, 6)
    bootstrap_saved = np.fromfile(ANALYSIS / "primary-bootstrap-estimates-v02.f64le", dtype="<f8").reshape(10_000, 6)

    max_margin_error = 0.0
    max_pair_error = 0.0
    max_softmax_error = 0.0
    primary_rows = np.empty((ROWS, 6), dtype="<f8")
    expected_secondary_sites = []
    for site, (layer, surface) in enumerate(SITES):
        primary_endpoint = 0 if surface == "M" else 1
        site_dict = secondary["sites"][site]
        if site_dict["site_index"] != site or site_dict["layer"] != layer or site_dict["surface"] != surface:
            raise RuntimeError("secondary site identity mismatch")
        site_strength_rows = []
        for si, strength in enumerate(STRENGTHS):
            strength_dict = site_dict["strengths"][si]
            if strength_dict["strength"] != strength:
                raise RuntimeError("secondary strength identity mismatch")
            strength_arm_rows = []
            for arm in range(ARMS):
                arm_dict = strength_dict["arms"][arm]
                if arm_dict["arm"] != ("target" if arm == 0 else f"random_{arm}"):
                    raise RuntimeError("secondary arm identity mismatch")
                endpoint_rows = []
                for endpoint in range(2):
                    cell = np.asarray(logits[:, site, si, arm, endpoint], dtype=np.float32)
                    probs = np.asarray(probabilities[:, site, si, arm, endpoint], dtype=np.float64)
                    prediction = np.argmax(cell, axis=1).astype(np.int8)
                    if not np.array_equal(prediction, pred_out[:, site, si, arm, endpoint]):
                        raise RuntimeError(f"prediction artifact mismatch at site={site}, strength={si}, arm={arm}, endpoint={endpoint}")
                    cell_margins = np.asarray([margin_reference(cell[i], int(labels[i])) for i in range(ROWS)], dtype="<f4")
                    max_margin_error = max(max_margin_error, float(np.max(np.abs(cell_margins - target_out[:, site, si, arm, endpoint]))))
                    pair = np.column_stack([cell[:, a] - cell[:, b] for a, b in PAIR_ORDER]).astype("<f4")
                    max_pair_error = max(max_pair_error, float(np.max(np.abs(pair - pairs_out[:, site, si, arm, endpoint, :]))))
                    stable = np.exp(cell.astype(np.float64) - np.max(cell, axis=1, keepdims=True))
                    stable /= stable.sum(axis=1, keepdims=True)
                    max_softmax_error = max(max_softmax_error, float(np.max(np.abs(stable - probs))))
                    all_metric = metrics_reference(labels, prediction)
                    by_variant = {name: metrics_reference(labels[np.asarray(variants) == name], prediction[np.asarray(variants) == name]) for name in VARIANTS}
                    endpoint_dict = arm_dict["endpoints"][endpoint]
                    assert_numeric(endpoint_dict["all_rows"], all_metric, f"site{site}.s{si}.a{arm}.e{endpoint}.all")
                    assert_numeric(endpoint_dict["by_variant"], by_variant, f"site{site}.s{si}.a{arm}.e{endpoint}.variant")
                    sham_logits = np.asarray(logits[:, site, 0, 0, endpoint], dtype=np.float32)
                    sham_pred = np.argmax(sham_logits, axis=1).astype(np.int8)
                    sham_margins = np.asarray([margin_reference(sham_logits[i], int(labels[i])) for i in range(ROWS)], dtype=np.float64)
                    expected_by_class = {}
                    for label in (0, 1, 2):
                        mask = labels == label
                        transition = [[0, 0, 0] for _ in range(3)]
                        for before, after in zip(sham_pred[mask].tolist(), prediction[mask].tolist(), strict=True):
                            transition[int(before)][int(after)] += 1
                        row_margins = [margin_reference(cell[i], label) for i in np.flatnonzero(mask)]
                        expected_by_class[str(label)] = {
                            "n": int(mask.sum()),
                            "accuracy": float(np.mean(prediction[mask] == label)),
                            "mean_target_margin": float(np.mean(row_margins, dtype=np.float64)),
                            "sham_to_intervention_prediction_transition_matrix": transition,
                        }
                    assert_numeric(endpoint_dict["by_exact_target"], expected_by_class, f"site{site}.s{si}.a{arm}.e{endpoint}.target", tolerance=2e-10)
                    sham_metric = metrics_reference(labels, sham_pred)
                    expected_sham_delta = {
                        "accuracy_delta": all_metric["accuracy"] - sham_metric["accuracy"],
                        "balanced_accuracy_delta": all_metric["balanced_accuracy"] - sham_metric["balanced_accuracy"],
                        "per_class_recall_delta": (np.asarray(all_metric["per_class_recall"]) - np.asarray(sham_metric["per_class_recall"])).tolist(),
                        "mean_target_margin_delta": float(np.mean([margin_reference(cell[i], int(labels[i])) for i in range(ROWS)], dtype=np.float64) - np.mean(sham_margins, dtype=np.float64)),
                    }
                    assert_numeric(endpoint_dict["sham_relative_changes"], expected_sham_delta, f"site{site}.s{si}.a{arm}.e{endpoint}.sham", tolerance=2e-10)
                    endpoint_rows.append(endpoint_dict)
                strength_arm_rows.append(endpoint_rows)
            site_strength_rows.append(strength_arm_rows)

        target_rows = np.asarray(logits[:, site, 3, 0, primary_endpoint], dtype=np.float32)
        target_values = np.asarray([margin_reference(target_rows[row], int(labels[row])) for row in range(ROWS)], dtype=np.float64)
        control_values = np.empty((ROWS, 8), dtype=np.float64)
        for control in range(8):
            control_rows = np.asarray(logits[:, site, 3, control + 1, primary_endpoint], dtype=np.float32)
            control_values[:, control] = [margin_reference(control_rows[row], int(labels[row])) for row in range(ROWS)]
        primary_rows[:, site] = control_values.mean(axis=1, dtype=np.float64) - target_values
        expected_secondary_sites.append({"site": site, "layer": layer, "surface": surface})

        block = np.asarray(checks[:, site], dtype=np.float64)
        if not np.isfinite(block).all():
            raise RuntimeError(f"non-finite manipulation checks for site {site}")
        if np.any(block[..., 6] - block[..., 7] > 1e-7):
            raise RuntimeError(f"projected-plane manipulation limit exceeded at site {site}")
        if np.any(block[..., 8] > 1e-5 + 1e-12):
            raise RuntimeError(f"summary displacement norm mismatch at site {site}")
        if np.any(np.abs(block[..., 0] - block[..., 1]) > np.maximum(1e-7, 1e-5 * block[..., 0])):
            raise RuntimeError(f"target/random norm matching failed at site {site}")

    if max_margin_error != 0.0 or max_pair_error != 0.0 or max_softmax_error > 1e-6:
        raise RuntimeError(f"independent derived-array mismatch margin={max_margin_error}, pair={max_pair_error}, softmax={max_softmax_error}")
    if event_contrasts_saved.tobytes() != primary_rows.tobytes():
        raise RuntimeError("independent event-level primary contrast replay mismatch")
    quartet_values = np.asarray([primary_rows[rows].mean(axis=0, dtype=np.float64) for rows in groups], dtype="<f8")
    if quartet_values.tobytes() != quartet_contrasts_saved.tobytes():
        raise RuntimeError("independent quartet-level contrast replay mismatch")
    estimates = quartet_values.mean(axis=0, dtype=np.float64)
    plan = np.memmap(RUN / contract["parents"]["bootstrap_plan"]["path"], dtype="<u4", mode="r", shape=(10_000, QUARTETS))
    boot_replay = np.empty((10_000, 6), dtype="<f8")
    for i in range(10_000):
        indices = np.asarray(plan[i], dtype=np.int64)
        boot_replay[i] = quartet_values[indices].mean(axis=0, dtype=np.float64)
    if not np.allclose(boot_replay, bootstrap_saved, rtol=0.0, atol=1e-14):
        raise RuntimeError("independent shared-bootstrap replay mismatch")
    se = boot_replay.std(axis=0, ddof=1)
    statistic = np.max(np.abs((boot_replay - estimates[None, :]) / se[None, :]), axis=1)
    critical = float(np.quantile(statistic, 0.95, method="linear"))
    intervals = np.column_stack((estimates - critical * se, estimates + critical * se))
    primary_record = read_json(ANALYSIS / "s12-analysis-result-v02.json")["primary"]
    for site in range(6):
        record = primary_record["sites"][site]
        if record["site_index"] != site or abs(record["estimate_random_minus_target_margin"] - estimates[site]) > 1e-12:
            raise RuntimeError(f"independent primary estimate mismatch at site {site}")
        if not np.allclose(record["simultaneous_95_percent_interval"], intervals[site], rtol=0.0, atol=1e-12):
            raise RuntimeError(f"independent simultaneous interval mismatch at site {site}")
        if record["selective_causal_dependence_supported"] != bool(intervals[site, 0] > 0.0):
            raise RuntimeError(f"independent site disposition mismatch at site {site}")
    if abs(primary_record["critical_value"] - critical) > 1e-12:
        raise RuntimeError("independent simultaneous critical value mismatch")

    baseline_predictions = np.fromfile(RUN / "baseline-v02" / "baseline-predictions-v02.i64le", dtype="<i8").reshape(ROWS, 2)
    baseline_metrics = {surface: metrics_reference(labels, baseline_predictions[:, i]) for i, surface in enumerate(ENDPOINTS)}
    for i, surface in enumerate(ENDPOINTS):
        reference = np.load(S11 / "transport-v01" / "predictions" / f"{surface}-src-16-tgt-16.npy", allow_pickle=False)
        if not np.array_equal(baseline_predictions[:, i], reference):
            raise RuntimeError(f"S11 baseline prediction parity failed for {surface}")
        expected = contract["observers"]["terminal_s11_context"]
        if abs(baseline_metrics[surface]["accuracy"] - expected[f"{surface}_accuracy"]) > 1e-14:
            raise RuntimeError(f"S11 baseline accuracy context mismatch for {surface}")
        if abs(baseline_metrics[surface]["balanced_accuracy"] - expected[f"{surface}_balanced_accuracy"]) > 1e-14:
            raise RuntimeError(f"S11 baseline balanced accuracy context mismatch for {surface}")

    result_bytes = (ANALYSIS / "s12-analysis-result-v02.json").read_bytes()
    receipt = {
        "verification_id": "FAS_S12_INDEPENDENT_ANALYSIS_REPLAY_V03",
        "complete": True,
        "raw_output_root_sha256": raw_seal["root_sha256"],
        "analysis_root_sha256": analysis_seal["root_sha256"],
        "analysis_result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "panel_rows_verified": ROWS,
        "quartets_verified": QUARTETS,
        "all_432_prediction_margin_and_metric_cells_replayed": True,
        "primary_event_and_quartet_values_byte_identical": True,
        "bootstrap_replay": {"replicates": 10_000, "shared_plan": True, "maximum_absolute_estimate_error": float(np.max(np.abs(boot_replay - bootstrap_saved))), "simultaneous_interval_reproduced": True},
        "s11_baseline_metrics_reproduced": baseline_metrics,
        "manipulation_checks": {"maximum_projected_limit_excess": float(np.max(np.asarray(checks[..., 6] - checks[..., 7], dtype=np.float64))), "maximum_norm_relative_error": float(np.max(np.asarray(checks[..., 8], dtype=np.float64))), "maximum_norm_absolute_difference": float(np.max(np.abs(np.asarray(checks[..., 0] - checks[..., 1], dtype=np.float64))))},
        "derived_output_maximum_absolute_errors": {"target_margin": max_margin_error, "pair_margin": max_pair_error, "softmax_probability": max_softmax_error},
    }
    OUT.write_bytes(canonical_json(receipt) + b"\n")
    print(json.dumps(receipt, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
