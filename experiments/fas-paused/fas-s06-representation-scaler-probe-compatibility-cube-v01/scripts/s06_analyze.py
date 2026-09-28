from __future__ import annotations

import itertools
import json
import math
from collections import Counter
from typing import Any

import numpy as np

from s06_common import (
    AUTHORIZATION,
    CELL_INFO,
    CELL_ORDER,
    CLASS_NAMES,
    CONTRACT,
    DIRECT_INPUT_HASHES,
    FAS00_MEAN_FEATURES,
    FAS00_MEAN_PROBE,
    FAS00_EVENTS,
    FAS00_RUN,
    HIDDEN,
    PAIR_ORDER,
    RUN,
    S01_FEATURE_ROWS,
    S01_FINAL_FEATURES,
    S01_FINAL_PROBE,
    S01_FINAL_PROBS,
    S01_MEAN_FEATURES,
    S01_MEAN_PROBE,
    S01_MEAN_PROBS,
    S02_FINAL_FEATURES,
    S02_FINAL_PROBE,
    S05_LEDGER,
    S05_POPULATIONS,
    FailClosed,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol,
    write_json,
    write_jsonl,
)


BATCH = 1024
PAIR_MARGIN_NAMES = tuple(f"class_{a}_minus_class_{b}" for a, b in PAIR_ORDER)
MARGIN_NAMES = PAIR_MARGIN_NAMES + ("target_vs_best_rival",)
TRANSITION_PAIRS = tuple(itertools.combinations(CELL_ORDER, 2))


def _finite(name: str, values: np.ndarray) -> None:
    if not np.isfinite(values).all():
        raise FailClosed(f"Non-finite S06 values: {name}")


def _load_readout(path, dataset: str) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        keys = set(archive.files)
        expected = {"weights", "bias", "mean", "scale"} if dataset == "FAS00_ORIGINAL" else {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
        if keys != expected:
            raise FailClosed(f"Readout state inventory differs: {path.name}")
        state = {key: np.array(archive[key], copy=True) for key in keys}
    if dataset == "FAS00_ORIGINAL":
        if any(state[key].dtype != np.dtype("<f8") for key in ("weights", "bias", "mean", "scale")):
            raise FailClosed(f"FAS-00 readout precision differs: {path.name}")
        mean, scale = state["mean"], state["scale"]
    else:
        if (state["classes"].shape != (3,) or not np.array_equal(state["classes"], np.asarray([0, 1, 2])) or
                state["weights"].dtype != np.dtype("<f4") or state["bias"].dtype != np.dtype("<f4") or
                state["scaler_mean"].dtype != np.dtype("<f8") or state["scaler_scale"].dtype != np.dtype("<f8")):
            raise FailClosed(f"S01 readout precision/class order differs: {path.name}")
        # This is the exact scaler cast used in S01's sealed replay.
        state["weights"] = state["weights"].astype(np.float32, copy=False)
        state["bias"] = state["bias"].astype(np.float32, copy=False)
        mean = state["scaler_mean"].astype(np.float32)
        scale = state["scaler_scale"].astype(np.float32)
    if state["weights"].shape != (3, HIDDEN) or state["bias"].shape != (3,) or mean.shape != (HIDDEN,) or scale.shape != (HIDDEN,):
        raise FailClosed(f"Readout dimensions differ: {path.name}")
    if not np.isfinite(state["weights"]).all() or not np.isfinite(state["bias"]).all() or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise FailClosed(f"Invalid or non-finite readout parameters: {path.name}")
    state["replay_mean"] = mean
    state["replay_scale"] = scale
    return state


def _load_states(dataset: str) -> dict[str, dict[str, np.ndarray]]:
    if dataset == "FAS00_ORIGINAL":
        return {"M": _load_readout(FAS00_MEAN_PROBE, dataset), "F": _load_readout(S02_FINAL_PROBE, dataset)}
    return {"M": _load_readout(S01_MEAN_PROBE, dataset), "F": _load_readout(S01_FINAL_PROBE, dataset)}


def _cell_id(r: str, c: str, d: str, w: str) -> str:
    return f"R_{r}_C_{c}_D_{d}_W_{w}"


def _semantic_logits(slots: np.ndarray, row: dict[str, Any]) -> np.ndarray:
    order = [int(value) for value in row["candidate_identity_order"]]
    mapping = {int(key): int(value) for key, value in row["state_by_candidate_identity"].items()}
    if set(order) != {0, 1, 2} or set(mapping) != {0, 1, 2} or set(mapping.values()) != {0, 1, 2}:
        raise FailClosed(f"Invalid per-event S01 output mapping: {row['event_id']}")
    semantic = np.empty(3, dtype=np.float64)
    for position, identity in enumerate(order):
        semantic[mapping[identity]] = float(slots[position])
    return semantic


def _cell_logits(raw: np.ndarray, state: dict[str, np.ndarray], center_source: str,
                 scale_source: str, states: dict[str, dict[str, np.ndarray]], dataset: str) -> np.ndarray:
    center = states[center_source]["replay_mean"]
    scale = states[scale_source]["replay_scale"]
    probe = state
    if dataset == "FAS00_ORIGINAL":
        x = np.asarray(raw, dtype=np.float32).astype(np.float64, copy=True)
        x -= center
        x /= scale
        logits = x @ probe["weights"].T + probe["bias"]
        _finite("FAS00 replay logits", logits)
        return logits
    x = np.asarray(raw, dtype=np.float32).copy()
    x -= center
    x /= scale
    logits = np.empty((len(x), 3), dtype=np.float32)
    np.matmul(x, probe["weights"].T, out=logits)
    logits += probe["bias"]
    _finite("S01 replay logits", logits)
    return logits.astype(np.float64)


def _nearest_rank(values: np.ndarray, p: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    return float(ordered[max(0, math.ceil(p * len(ordered)) - 1)])


def _stats(values: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(values, dtype=np.float64)
    _finite("distribution summary", x)
    return {"n": int(x.size), "mean": float(x.mean()), "median": float(np.median(x)),
            "nearest_rank_p10": _nearest_rank(x, 0.10), "nearest_rank_p90": _nearest_rank(x, 0.90),
            "min": float(x.min()), "max": float(x.max())}


def _margin_row(logits: np.ndarray, target: int) -> dict[str, float]:
    out = {f"class_{a}_minus_class_{b}": float(logits[a] - logits[b]) for a, b in PAIR_ORDER}
    out["target_vs_best_rival"] = float(logits[target] - max(logits[k] for k in range(3) if k != target))
    return out


def _load_feature_sources(dataset: str) -> dict[str, np.memmap]:
    if dataset == "FAS00_ORIGINAL":
        return {
            "M": np.memmap(FAS00_MEAN_FEATURES, dtype="<f4", mode="r", shape=(65_536, HIDDEN)),
            "F": np.memmap(S02_FINAL_FEATURES, dtype="<f4", mode="r", shape=(FAS00_EVENTS, HIDDEN)),
        }
    return {
        "M": np.memmap(S01_MEAN_FEATURES, dtype="<f4", mode="r", shape=(S01_FEATURE_ROWS, HIDDEN)),
        "F": np.memmap(S01_FINAL_FEATURES, dtype="<f4", mode="r", shape=(S01_FEATURE_ROWS, HIDDEN)),
    }


def _load_parent_ledger() -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    with S05_LEDGER.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            item = json.loads(line)
            key = (item["dataset"], item["event_id"])
            if key in rows:
                raise FailClosed(f"Duplicate S05 ledger event at line {line_number}")
            rows[key] = item
    if len(rows) != 20244:
        raise FailClosed(f"S05 parent ledger row count mismatch: {len(rows)}")
    return rows


def _replay_dataset(dataset: str, rows: list[dict[str, Any]], s05_ledger: dict[tuple[str, str], dict[str, Any]],
                    s01_probs: dict[str, np.ndarray] | None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    states = _load_states(dataset)
    feature_sources = _load_feature_sources(dataset)
    n = len(rows)
    raw_indices = {
        "M": np.fromiter((int(row["mean_feature_row"] if dataset == "FAS00_ORIGINAL" else row["feature_row_index"]) for row in rows), dtype=np.int64, count=n),
        "F": np.fromiter((int(row["final_feature_row"] if dataset == "FAS00_ORIGINAL" else row["feature_row_index"]) for row in rows), dtype=np.int64, count=n),
    }
    targets = np.fromiter((int(row["exact_target"] if dataset == "FAS00_ORIGINAL" else row["target_state_id"]) for row in rows), dtype=np.int64, count=n)
    slot_predictions: dict[str, np.ndarray] = {cell: np.empty(n, dtype=np.int8) for cell in CELL_ORDER}
    logits_by_cell: dict[str, np.ndarray] = {cell: np.empty((n, 3), dtype=np.float64) for cell in CELL_ORDER}
    for start in range(0, n, BATCH):
        end = min(start + BATCH, n)
        for representation in ("M", "F"):
            raw = np.asarray(feature_sources[representation][raw_indices[representation][start:end]], dtype=np.float32)
            _finite(f"{dataset} {representation} input", raw)
            for center in ("M", "F"):
                for scale in ("M", "F"):
                    for probe_source in ("M", "F"):
                        slot_logits = _cell_logits(raw, states[probe_source], center, scale, states, dataset)
                        cell = _cell_id(representation, center, scale, probe_source)
                        for local, global_index in enumerate(range(start, end)):
                            slot_predictions[cell][global_index] = int(np.argmax(slot_logits[local]))
                            if dataset == "S01_CONTROLLED":
                                semantic = _semantic_logits(slot_logits[local], rows[global_index])
                                logits_by_cell[cell][global_index] = semantic
                            else:
                                logits_by_cell[cell][global_index] = slot_logits[local]

    # S05's fixed diagonal predictions are hard gates on both datasets.
    for index, row in enumerate(rows):
        event_key = (dataset, row["event_id"])
        parent_row = s05_ledger.get(event_key)
        if parent_row is None:
            raise FailClosed(f"S05 parent ledger omitted event {row['event_id']}")
        for cell in (_cell_id("M", "M", "M", "M"), _cell_id("F", "F", "F", "F")):
            expected = int(parent_row["cells"]["MM" if cell == _cell_id("M", "M", "M", "M") else "FF"]["prediction"])
            observed = int(np.argmax(logits_by_cell[cell][index]))
            if observed != expected:
                raise FailClosed(f"S06 diagonal prediction mismatch: {dataset}/{row['event_id']}/{cell}")
            if dataset == "FAS00_ORIGINAL":
                expected_s02 = int(row["s02_mean_prediction"] if cell == _cell_id("M", "M", "M", "M") else row["s02_final_prediction"])
                if observed != expected_s02:
                    raise FailClosed(f"S06 FAS-00/S02 prediction gate mismatch: {row['event_id']}/{cell}")
            elif s01_probs is not None:
                view = "M" if cell == _cell_id("M", "M", "M", "M") else "F"
                probs = s01_probs[view]
                saved_slot = int(np.argmax(probs[int(row["test_row"])]))
                if saved_slot != int(slot_predictions[cell][index]):
                    raise FailClosed(f"S06 S01 saved probability argmax mismatch: {row['event_id']}/{cell}")
                if observed != expected:
                    raise FailClosed(f"S06 S01 semantic diagonal prediction mismatch: {row['event_id']}/{cell}")

    ledger: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        target = int(targets[index])
        cell_data: dict[str, Any] = {}
        for cell in CELL_ORDER:
            logits = logits_by_cell[cell][index]
            prediction = int(np.argmax(logits))
            margins = _margin_row(logits, target)
            item = {"logits": [float(x) for x in logits], "prediction": prediction,
                    "correct": prediction == target, "target_margin": margins["target_vs_best_rival"],
                    "margins": margins}
            if dataset == "S01_CONTROLLED":
                item["candidate_position_prediction"] = int(slot_predictions[cell][index])
            cell_data[cell] = item
        ledger.append({"dataset": dataset, "event_id": row["event_id"], "target": target,
                       "slices": row.get("slices", ["FACTORIAL_TEST"]), "row_index": row.get("row_index"),
                       "quartet_id": row.get("quartet_id"), "variant_id": row.get("variant_id"), "cells": cell_data})

    geometry = _effective_geometry(dataset, {dataset: states})
    receipt = {"dataset": dataset, "events": n, "cells": len(CELL_ORDER), "diagonal_gate": "PASS",
               "FAS00_S02_diagonal_predictions_exact": dataset == "FAS00_ORIGINAL",
               "S01_saved_and_S05_diagonal_argmax_exact": dataset == "S01_CONTROLLED",
               "precision": "FP64" if dataset == "FAS00_ORIGINAL" else "FP32",
               "feature_extraction": False, "probe_fitting": False}
    return ledger, receipt, {"logits": logits_by_cell, "states": states, "geometry": geometry}


def _effective_geometry(dataset: str, states: dict[str, dict[str, dict[str, np.ndarray]]]) -> dict[str, Any]:
    cells = {}
    for cell in CELL_ORDER:
        info = CELL_INFO[cell]
        center_state = states[dataset][info["center_source"]]
        scale_state = states[dataset][info["scale_source"]]
        probe = states[dataset][info["probe_source"]]
        mu = np.asarray(center_state["replay_mean"], dtype=np.float64)
        sigma = np.asarray(scale_state["replay_scale"], dtype=np.float64)
        weights = np.asarray(probe["weights"], dtype=np.float64)
        bias = np.asarray(probe["bias"], dtype=np.float64)
        normals = weights / sigma[None, :]
        intercept = bias - normals @ mu
        _finite(f"{dataset}/{cell}/effective normals", normals)
        _finite(f"{dataset}/{cell}/effective intercept", intercept)
        reference = _cell_id(info["representation"], info["representation"], info["representation"], info["representation"])
        ref_info = CELL_INFO[reference]
        ref_probe = states[dataset][ref_info["probe_source"]]
        ref_mu = np.asarray(states[dataset][ref_info["center_source"]]["replay_mean"], dtype=np.float64)
        ref_sigma = np.asarray(states[dataset][ref_info["scale_source"]]["replay_scale"], dtype=np.float64)
        ref_normals = np.asarray(ref_probe["weights"], dtype=np.float64) / ref_sigma[None, :]
        ref_intercept = np.asarray(ref_probe["bias"], dtype=np.float64) - ref_normals @ ref_mu
        pair_geometry = {}
        for a, b in PAIR_ORDER:
            boundary = normals[a] - normals[b]
            ref_boundary = ref_normals[a] - ref_normals[b]
            norm = float(np.linalg.norm(boundary))
            ref_norm = float(np.linalg.norm(ref_boundary))
            cosine = float(np.dot(boundary, ref_boundary) / (norm * ref_norm))
            cosine = min(1.0, max(-1.0, cosine))
            pair_geometry[f"class_{a}_minus_class_{b}"] = {
                "effective_normal_l2": norm,
                "cosine_to_native_matched_cell": cosine,
                "angle_degrees_to_native_matched_cell": float(math.degrees(math.acos(cosine))),
            }
        mu_stats = _stats(mu)
        sigma_stats = _stats(sigma)
        cells[cell] = {
            **info,
            "effective_class_normals": normals.tolist(),
            "effective_class_normal_l2": [float(np.linalg.norm(row)) for row in normals],
            "effective_pairwise_geometry": pair_geometry,
            "effective_intercepts": intercept.tolist(),
            "native_reference_cell": reference,
            "intercept_displacement_vs_native": (intercept - ref_intercept).tolist(),
            "intercept_displacement_l2": float(np.linalg.norm(intercept - ref_intercept)),
            "selected_center_source_summary": {"l2": float(np.linalg.norm(mu)), "mean": mu_stats["mean"], "std": float(mu.std())},
            "selected_scale_source_summary": {"l2": float(np.linalg.norm(sigma)), "mean": sigma_stats["mean"], "std": float(sigma.std()), "min": sigma_stats["min"], "median": sigma_stats["median"], "max": sigma_stats["max"]},
        }
    return {"dataset": dataset,
            "weight_coordinate_note": "FAS00 classes use safe/risky/idle order. S01 effective class normals/intercepts are in fixed candidate-output-slot coordinates; per-event semantic remapping applies only to metrics and predictions.",
            "affine_parameter_arithmetic": "FP64 from sealed parameter values after the S01-prescribed FP32 scaler cast and FP32 weight/bias representation.",
            "cells": cells}


def _slice_indices(dataset: str, rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    if dataset == "FAS00_ORIGINAL":
        return {"UNION": list(range(len(rows))),
                "CONTEXT_TERM_3": [i for i, row in enumerate(rows) if "CONTEXT_TERM_3" in row["slices"]],
                "ENTITY_TERM_7": [i for i, row in enumerate(rows) if "ENTITY_TERM_7" in row["slices"]]}
    return {"FACTORIAL_TEST": list(range(len(rows)))}


def _metric_summary(ledger: list[dict[str, Any]], indices: list[int]) -> dict[str, Any]:
    selected = [ledger[i] for i in indices]
    y = np.asarray([row["target"] for row in selected], dtype=np.int64)
    support = np.bincount(y, minlength=3)
    if len(selected) == 0 or np.any(support == 0):
        raise FailClosed("S06 metric slice is empty or lacks a class")
    output: dict[str, Any] = {"n": len(selected), "support_by_class": support.tolist(), "cells": {}}
    for cell in CELL_ORDER:
        pred = np.asarray([row["cells"][cell]["prediction"] for row in selected], dtype=np.int64)
        logits = np.asarray([row["cells"][cell]["logits"] for row in selected], dtype=np.float64)
        confusion = np.zeros((3, 3), dtype=np.int64)
        np.add.at(confusion, (y, pred), 1)
        correct_by_class = confusion.diagonal()
        recall = correct_by_class / support
        margin_values = {name: np.asarray([row["cells"][cell]["margins"][name] for row in selected], dtype=np.float64) for name in MARGIN_NAMES}
        by_target = {}
        for target in range(3):
            class_logits = logits[y == target]
            by_target[str(target)] = {"n": int(len(class_logits)), "mean": class_logits.mean(axis=0).tolist(), "variance": class_logits.var(axis=0).tolist()}
        output["cells"][cell] = {
            "accuracy": float(np.mean(pred == y)), "balanced_accuracy": float(recall.mean()),
            "recall_by_class": recall.tolist(), "correct_by_class": correct_by_class.tolist(),
            "predicted_class_counts": np.bincount(pred, minlength=3).tolist(),
            "confusion_matrix_true_rows_predicted_columns": confusion.tolist(),
            "margins": {name: _stats(values) for name, values in margin_values.items()},
            "class_logits_overall": {"mean": logits.mean(axis=0).tolist(), "variance": logits.var(axis=0).tolist()},
            "class_logits_by_target": by_target,
        }
    return output


def _transitions(ledger: list[dict[str, Any]], slices: dict[str, list[int]]) -> dict[str, Any]:
    result = {}
    for slice_name, indices in slices.items():
        rows = [ledger[i] for i in indices]
        pairs = {}
        for first, second in TRANSITION_PAIRS:
            matrix = np.zeros((3, 3), dtype=np.int64)
            correctness = Counter({"both_correct": 0, "first_only_correct": 0, "second_only_correct": 0, "both_incorrect": 0})
            for row in rows:
                target = int(row["target"])
                a = int(row["cells"][first]["prediction"])
                b = int(row["cells"][second]["prediction"])
                matrix[a, b] += 1
                ca, cb = a == target, b == target
                correctness["both_correct" if ca and cb else "first_only_correct" if ca else "second_only_correct" if cb else "both_incorrect"] += 1
            if int(matrix.sum()) != len(rows) or sum(correctness.values()) != len(rows):
                raise FailClosed("S06 paired transition counts are incomplete")
            pairs[f"{first}_to_{second}"] = {"first_cell": first, "second_cell": second,
                "prediction_transition_counts_rows_first_columns_second": matrix.tolist(),
                "correctness_transitions": dict(correctness)}
        result[slice_name] = {"n": len(rows), "cell_pairs": pairs}
    return result


def _comparison_pairs() -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        "probe_swap_after_native_M_scaler": ((_cell_id("M", "M", "M", "M"), _cell_id("M", "M", "M", "F")),),
        "probe_swap_after_native_F_scaler": ((_cell_id("F", "F", "F", "F"), _cell_id("F", "F", "F", "M")),),
        "bundled_scaler_swap_holding_native_probe_M": ((_cell_id("M", "M", "M", "M"), _cell_id("M", "F", "F", "M")),),
        "bundled_scaler_swap_holding_native_probe_F": ((_cell_id("F", "F", "F", "F"), _cell_id("F", "M", "M", "F")),),
        "center_only_transport_holding_native_probe_M": ((_cell_id("M", "M", "M", "M"), _cell_id("M", "F", "M", "M")),),
        "center_only_transport_holding_native_probe_F": ((_cell_id("F", "F", "F", "F"), _cell_id("F", "M", "F", "F")),),
        "scale_only_transport_holding_native_probe_M": ((_cell_id("M", "M", "M", "M"), _cell_id("M", "M", "F", "M")),),
        "scale_only_transport_holding_native_probe_F": ((_cell_id("F", "F", "F", "F"), _cell_id("F", "F", "M", "F")),),
        "full_foreign_scaler_and_probe_on_M_representation": ((_cell_id("M", "M", "M", "M"), _cell_id("M", "F", "F", "F")),),
        "full_foreign_scaler_and_probe_on_F_representation": ((_cell_id("F", "F", "F", "F"), _cell_id("F", "M", "M", "M")),),
    }


def _comparisons(pop_summaries: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for population, summary in pop_summaries.items():
        result[population] = {}
        pairs = _comparison_pairs()
        for slice_name, metrics in summary.items():
            result[population][slice_name] = {}
            for label, alternatives in pairs.items():
                a, b = alternatives[0]
                left, right = metrics["cells"][a], metrics["cells"][b]
                result[population][slice_name][label] = {
                    "from_cell": a, "to_cell": b,
                    "delta_accuracy": right["accuracy"] - left["accuracy"],
                    "delta_balanced_accuracy": right["balanced_accuracy"] - left["balanced_accuracy"],
                    "delta_recall_by_class": [right["recall_by_class"][i] - left["recall_by_class"][i] for i in range(3)],
                    "delta_mean_pair_and_target_margins": {name: right["margins"][name]["mean"] - left["margins"][name]["mean"] for name in MARGIN_NAMES},
                    "delta_overall_class_logit_mean": [right["class_logits_overall"]["mean"][i] - left["class_logits_overall"]["mean"][i] for i in range(3)],
                    "delta_overall_class_logit_variance": [right["class_logits_overall"]["variance"][i] - left["class_logits_overall"]["variance"][i] for i in range(3)],
                }
    return result


def _report(summaries: dict[str, Any], comparisons: dict[str, Any], receipts: list[dict[str, Any]]) -> str:
    lines = ["# FAS-S06 Results: Representation × Scaler × Probe Compatibility Cube", "",
        "S06 replays sealed feature arrays and readout states. Each cell is `logits = W_k * ((h_r - mu_c) / sigma_d) + b_k`. The eight bundled-scaler cells have `c=d`; the other eight split center and scale sources. No fitting, model contact, or new feature extraction occurred.", "",
        "Cell IDs encode representation R, center source C, scale source D, and probe W. `M` is mean_full and `F` is final_position. S01 prediction metrics are mapped to semantic state order; effective normals remain in candidate-slot coordinates.", ""]
    key_slices = {"FAS00_ORIGINAL": ("CONTEXT_TERM_3", "ENTITY_TERM_7"), "S01_CONTROLLED": ("FACTORIAL_TEST",)}
    for population, slices in summaries.items():
        lines.extend([f"## {population}", ""])
        for slice_name in key_slices[population]:
            report = slices[slice_name]
            lines.extend([f"### {slice_name} (n={report['n']}; support={report['support_by_class']})", "",
                "| R/C/D/W | Accuracy | Balanced accuracy | Recall by class |", "|---|---:|---:|---|"])
            for cell in CELL_ORDER:
                metric = report["cells"][cell]
                lines.append(f"| {cell} | {metric['accuracy']:.6f} | {metric['balanced_accuracy']:.6f} | " + ", ".join(f"{x:.6f}" for x in metric["recall_by_class"]) + " |")
            lines.extend(["", "Selected fixed compatibility contrasts (to-cell minus from-cell):", "",
                "| Contrast | Δ accuracy | Δ balanced accuracy | Δ recall by class | Δ target margin mean |", "|---|---:|---:|---|---:|"])
            for label, contrast in comparisons[population][slice_name].items():
                lines.append(f"| {label} | {contrast['delta_accuracy']:.6f} | {contrast['delta_balanced_accuracy']:.6f} | " + ", ".join(f"{x:.6f}" for x in contrast["delta_recall_by_class"]) + f" | {contrast['delta_mean_pair_and_target_margins']['target_vs_best_rival']:.6f} |")
            lines.append("")
    lines.extend(["## Replay gates", ""])
    for receipt in receipts:
        lines.append(f"- `{receipt['dataset']}`: {receipt['events']:,} rows; all {receipt['cells']} cells replayed; diagonal parity `{receipt['diagonal_gate']}`; precision `{receipt['precision']}`.")
    lines.extend(["", "Full confusion matrices, margin distributions, class-logit means/variances, all 120 cell-pair transitions, and effective affine normals/intercepts are in the sealed JSON and JSONL outputs. No significance tests or confidence intervals were computed.", "",
        "Interpretation is limited to descriptive compatibility of the fixed pipelines on these two bound populations. FAS-00 remains `SENSOR_FAIL_NO_SIGNAL`; S06 does not authorize adaptation or SAE analysis.", ""])
    return "\n".join(lines)


def main() -> None:
    protocol = verify_protocol()
    parents = verify_parents()
    preflight = read_json(RUN / "preflight-receipt-v01.json")
    if (preflight.get("status") != "PASS" or preflight.get("protocol_root_sha256") != protocol["root_sha256"] or
            preflight.get("parents") != parents or preflight.get("analysis_contract_sha256") != sha_file(CONTRACT) or
            preflight.get("authorization_packet_sha256") != sha_file(AUTHORIZATION)):
        raise FailClosed("S06 preflight binding mismatch")
    population_doc = read_json(S05_POPULATIONS)
    fas_rows = population_doc["FAS00_ORIGINAL"]["rows"]
    s01_rows = population_doc["S01_CONTROLLED"]["rows"]
    parent_ledger = _load_parent_ledger()
    s01_probs = {"M": np.load(S01_MEAN_PROBS, mmap_mode="r", allow_pickle=False),
                 "F": np.load(S01_FINAL_PROBS, mmap_mode="r", allow_pickle=False)}
    ledgers: dict[str, list[dict[str, Any]]] = {}
    receipts = []
    geometries = {}
    internals = {}
    for dataset, rows in (("FAS00_ORIGINAL", fas_rows), ("S01_CONTROLLED", s01_rows)):
        ledgers[dataset], receipt, internals[dataset] = _replay_dataset(dataset, rows, parent_ledger, s01_probs if dataset == "S01_CONTROLLED" else None)
        receipts.append(receipt)
        geometries[dataset] = internals[dataset]["geometry"]

    summaries: dict[str, Any] = {}
    transitions: dict[str, Any] = {}
    for dataset, ledger in ledgers.items():
        slices = _slice_indices(dataset, fas_rows if dataset == "FAS00_ORIGINAL" else s01_rows)
        summaries[dataset] = {name: _metric_summary(ledger, indices) for name, indices in slices.items()}
        transitions[dataset] = _transitions(ledger, slices)
    comparisons = _comparisons(summaries)
    all_ledger = ledgers["FAS00_ORIGINAL"] + ledgers["S01_CONTROLLED"]
    write_jsonl(RUN / "crossed-cube-ledger-v01.jsonl", all_ledger)
    summary = {
        "summary_id": "FAS_S06_COMPATIBILITY_SUMMARY_V01", "status": "COMPLETE",
        "cell_order": list(CELL_ORDER), "cell_definitions": CELL_INFO,
        "bundled_scaler_cells": [cell for cell in CELL_ORDER if CELL_INFO[cell]["center_source"] == CELL_INFO[cell]["scale_source"]],
        "center_scale_control_cells": [cell for cell in CELL_ORDER if CELL_INFO[cell]["center_source"] != CELL_INFO[cell]["scale_source"]],
        "populations": summaries, "fixed_compatibility_comparisons": comparisons,
        "no_significance_tests": True, "no_confidence_intervals": True,
        "model_contact": False, "probe_fitting": False,
    }
    write_json(RUN / "compatibility-summary-v01.json", summary)
    write_json(RUN / "prediction-transitions-v01.json", {"transition_id": "FAS_S06_TRANSITIONS_V01", "populations": transitions, "cell_pair_count": len(TRANSITION_PAIRS), "no_significance_tests": True})
    write_json(RUN / "effective-geometry-v01.json", geometries)
    report_path = RUN / "S06-RESULTS.md"
    if report_path.exists():
        raise FailClosed("Refusing to overwrite S06 report")
    report_path.write_text(_report(summaries, comparisons, receipts), encoding="utf-8", newline="\n")
    outputs = ("crossed-cube-ledger-v01.jsonl", "compatibility-summary-v01.json", "prediction-transitions-v01.json", "effective-geometry-v01.json", "S06-RESULTS.md")
    receipt = {
        "receipt_id": "FAS_S06_EXECUTION_RECEIPT_V01", "status": "COMPLETE",
        "S06_PARENT_BINDING_PASS": True, "S06_EIGHT_CELL_CUBE_COMPLETE": True,
        "S06_CENTER_SCALE_CONTROLS_COMPLETE": True, "S06_RESULT_READY": True,
        "FAS00_SENSOR_PASS": False, "FAS00_PHASE4_AUTHORIZED": False, "SAE_ANALYSIS_AUTHORIZED": False,
        "protocol_root_sha256": protocol["root_sha256"], "analysis_contract_sha256": sha_file(CONTRACT),
        "authorization_packet_sha256": sha_file(AUTHORIZATION), "preflight_receipt_sha256": sha_file(RUN / "preflight-receipt-v01.json"),
        "parents": parents, "replay_receipts": receipts,
        "outputs": {name: {"sha256": sha_file(RUN / name), "bytes": (RUN / name).stat().st_size} for name in outputs},
        "model_contact": False, "feature_extraction": False, "probe_fitting": False,
        "scaler_fitting": False, "adaptive_mechanisms": False, "SAE_analysis": False,
        "significance_tests": False, "confidence_intervals": False,
    }
    write_json(RUN / "execution-receipt-v01.json", receipt)
    print(f"S06_COMPATIBILITY_CUBE_COMPLETE fas00={len(fas_rows)} s01={len(s01_rows)} cells={len(CELL_ORDER)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S06_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
