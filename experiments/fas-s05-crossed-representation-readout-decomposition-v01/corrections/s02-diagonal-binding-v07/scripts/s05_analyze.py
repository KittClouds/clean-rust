from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

from s05_common import (
    AUTHORIZATION_PATH,
    CELL_DESCRIPTION,
    CELL_ORDER,
    CLASS_NAMES,
    CONTRACT_PATH,
    FAS00_FEATURES,
    FAS00_RUN,
    FAS_EVENTS,
    HIDDEN,
    INPUT_HASHES,
    PAIR_ORDER,
    RUN,
    S01_2_CACHE,
    S01_FEATURE_ROWS,
    S01_TEST_ROWS,
    S01_3_RUN,
    S02_FINAL_FEATURES,
    S02_FINAL_PROBE,
    S02_MEAN_PREDICTIONS,
    S02_METRICS,
    S02_MEAN_PREDICTIONS,
    S02_FINAL_PREDICTIONS,
    FailClosed,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol_bundle,
    write_json,
    write_jsonl,
)


BATCH_ROWS = 2048
PAIR_NAMES = {pair: f"class_{pair[0]}_minus_class_{pair[1]}" for pair in PAIR_ORDER}
MARGIN_NAMES = tuple(PAIR_NAMES.values()) + ("target_vs_best_rival",)
DECOMP_NAMES = ("representation_at_M_readout", "readout_at_M_representation", "interaction", "diagonal_total")
CELL_PAIRS = (("MM", "FM"), ("MM", "MF"), ("MM", "FF"), ("FM", "MF"), ("FM", "FF"), ("MF", "FF"))
CELL_EXECUTION = {
    "MM": ("M", "M"),
    "FM": ("F", "M"),
    "MF": ("M", "F"),
    "FF": ("F", "F"),
}


def _finite(name: str, array: np.ndarray) -> None:
    if not np.isfinite(array).all():
        raise FailClosed(f"Non-finite S05 values in {name}")


def _load_probe(path, precision: str) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        expected = {"weights", "bias", "mean", "scale"} if precision == "float64" else {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
        if set(archive.files) != expected:
            raise FailClosed(f"Sealed S05 readout state inventory differs: {path.name}")
        state = {key: np.array(archive[key], copy=True) for key in expected}
    if precision == "float64":
        state = {"weights": state["weights"], "bias": state["bias"], "mean": state["mean"], "scale": state["scale"]}
        if any(state[k].dtype != np.dtype("<f8") for k in state):
            raise FailClosed(f"S02 fixed readout dtype mismatch: {path.name}")
        mean_key, scale_key = "mean", "scale"
    else:
        if (state["classes"].shape != (3,) or not np.array_equal(state["classes"], np.asarray([0, 1, 2])) or
                state["weights"].dtype != np.dtype("<f4") or state["bias"].dtype != np.dtype("<f4") or
                state["scaler_mean"].dtype != np.dtype("<f8") or state["scaler_scale"].dtype != np.dtype("<f8")):
            raise FailClosed(f"S01 fixed readout dtype/class order mismatch: {path.name}")
        mean_key, scale_key = "scaler_mean", "scaler_scale"
    if (state["weights"].shape != (3, HIDDEN) or state["bias"].shape != (3,) or
            state[mean_key].shape != (HIDDEN,) or state[scale_key].shape != (HIDDEN,)):
        raise FailClosed(f"S05 readout dimensions differ: {path.name}")
    for key, values in state.items():
        if key != "classes":
            _finite(f"readout {path.name}/{key}", values)
    if np.any(state[scale_key] <= 0):
        raise FailClosed(f"S05 scaler must be strictly positive: {path.name}")
    return {**state, "_mean_key": mean_key, "_scale_key": scale_key}


def _verify_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = verify_protocol_bundle()
    # Rehash all parent payloads immediately before replay, not only at preflight.
    parent_identities = verify_parents(deep=True)
    preflight_path = RUN / "preflight-receipt-v01.json"
    populations_path = RUN / "event-populations-v01.json"
    preflight = read_json(preflight_path)
    populations = read_json(populations_path)
    if (preflight.get("status") != "PASS" or
            preflight.get("protocol_root_sha256") != protocol["root_sha256"] or
            preflight.get("analysis_contract_sha256") != sha_file(CONTRACT_PATH) or
            preflight.get("authorization_packet_sha256") != sha_file(AUTHORIZATION_PATH) or
            preflight.get("event_populations_sha256") != sha_file(populations_path) or
            preflight.get("parents") != parent_identities or
            populations.get("parents") != parent_identities or
            populations.get("model_contact") is not False or
            populations.get("feature_payloads_used_for_selection") is not False):
        raise FailClosed("S05 preflight identities are absent or changed")
    return {"protocol": protocol, "parents": parent_identities, "preflight": preflight}, populations


def _load_states() -> dict[str, dict[str, dict[str, np.ndarray]]]:
    return {
        "FAS00_ORIGINAL": {
            "M": _load_probe(FAS00_RUN / "phase3-v02" / "results-v01" / "probe-artifacts" / "HELDOUT_TERM_EXACT_TARGET.npz", "float64"),
            "F": _load_probe(S02_FINAL_PROBE, "float64"),
        },
        "S01_CONTROLLED": {
            "M": _load_probe(S01_3_RUN / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz", "float32"),
            "F": _load_probe(S01_3_RUN / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz", "float32"),
        },
    }


def _cell_logits(raw: np.ndarray, state: dict[str, np.ndarray], precision: str) -> np.ndarray:
    mean = state[state["_mean_key"]]
    scale = state[state["_scale_key"]]
    if precision == "float64":
        x = np.asarray(raw, dtype=np.float32).astype(np.float64, copy=True)
        x -= mean
        x /= scale
        logits = x @ state["weights"].T + state["bias"]
        _finite("FAS00 logits", logits)
        return logits
    x = np.asarray(raw, dtype=np.float32).copy()
    mean32 = mean.astype(np.float32)
    scale32 = scale.astype(np.float32)
    if not np.isfinite(mean32).all() or not np.isfinite(scale32).all() or np.any(scale32 == 0):
        raise FailClosed("S01 scaler is invalid after contracted FP32 cast")
    x -= mean32
    x /= scale32
    logits = np.empty((len(x), 3), dtype=np.float32)
    np.matmul(x, state["weights"].T, out=logits)
    logits += state["bias"]
    _finite("S01 logits", logits)
    return logits


def _semantic_logits(candidate_logits: np.ndarray, row: dict[str, Any]) -> np.ndarray:
    order = [int(value) for value in row["candidate_identity_order"]]
    state_by_id = {int(key): int(value) for key, value in row["state_by_candidate_identity"].items()}
    if len(candidate_logits) != 3 or set(order) != {0, 1, 2} or set(state_by_id) != {0, 1, 2} or set(state_by_id.values()) != {0, 1, 2}:
        raise FailClosed("S01 candidate-position to semantic-state mapping is not a three-class permutation")
    semantic = np.empty(3, dtype=np.float64)
    for position, candidate_identity in enumerate(order):
        semantic[state_by_id[candidate_identity]] = float(candidate_logits[position])
    return semantic


def _replay_dataset(dataset: str, rows: list[dict[str, Any]], states: dict[str, dict[str, dict[str, np.ndarray]]], s01_probability_arrays=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    precision = "float64" if dataset == "FAS00_ORIGINAL" else "float32"
    if dataset == "FAS00_ORIGINAL":
        rep_arrays = {
            "M": np.memmap(FAS00_FEATURES, dtype="<f4", mode="r", shape=(65_536, HIDDEN)),
            "F": np.memmap(S02_FINAL_FEATURES, dtype="<f4", mode="r", shape=(FAS_EVENTS, HIDDEN)),
        }
        indices = {
            "M": np.fromiter((int(row["mean_feature_row"]) for row in rows), dtype=np.int64, count=len(rows)),
            "F": np.fromiter((int(row["final_feature_row"]) for row in rows), dtype=np.int64, count=len(rows)),
        }
        targets = np.fromiter((int(row["exact_target"]) for row in rows), dtype=np.int64, count=len(rows))
        state_maps = None
    else:
        rep_arrays = {
            "M": np.memmap(S01_2_CACHE / "V0_MEAN_FULL.f32le", dtype="<f4", mode="r", shape=(S01_FEATURE_ROWS, HIDDEN)),
            "F": np.memmap(S01_2_CACHE / "V1_FINAL_POSITION.f32le", dtype="<f4", mode="r", shape=(S01_FEATURE_ROWS, HIDDEN)),
        }
        indices = {"M": np.fromiter((int(row["feature_row_index"]) for row in rows), dtype=np.int64, count=len(rows)),
                   "F": np.fromiter((int(row["feature_row_index"]) for row in rows), dtype=np.int64, count=len(rows))}
        targets = np.fromiter((int(row["target_state_id"]) for row in rows), dtype=np.int64, count=len(rows))
        state_maps = rows

    n = len(rows)
    logits_by_cell = {cell: np.empty((n, 3), dtype=np.float64) for cell in CELL_ORDER}
    candidate_position_by_cell = {cell: np.empty(n, dtype=np.int8) for cell in CELL_ORDER}
    for start in range(0, n, BATCH_ROWS):
        end = min(start + BATCH_ROWS, n)
        rep_logits: dict[str, dict[str, np.ndarray]] = {"M": {}, "F": {}}
        for representation in ("M", "F"):
            feature_batch = np.asarray(rep_arrays[representation][indices[representation][start:end]], dtype=np.float32)
            _finite(f"{dataset}/{representation} feature batch", feature_batch)
            for readout in ("M", "F"):
                rep_logits[representation][readout] = _cell_logits(feature_batch, states[dataset][readout], precision)
        for cell, (representation, readout) in CELL_EXECUTION.items():
            logits = rep_logits[representation][readout]
            if dataset == "S01_CONTROLLED":
                for local, global_index in enumerate(range(start, end)):
                    row = state_maps[global_index]
                    logits_by_cell[cell][global_index] = _semantic_logits(logits[local], row)
                    candidate_position_by_cell[cell][global_index] = int(np.argmax(logits[local]))
            else:
                logits_by_cell[cell][start:end] = logits
                candidate_position_by_cell[cell][start:end] = np.argmax(logits, axis=1).astype(np.int8)

    prediction_by_cell = {cell: np.argmax(logits, axis=1).astype(np.int8) for cell, logits in logits_by_cell.items()}
    if dataset == "FAS00_ORIGINAL":
        for index, row in enumerate(rows):
            if (int(prediction_by_cell["MM"][index]) != int(row["s02_mean_prediction"]) or
                    int(prediction_by_cell["FF"][index]) != int(row["s02_final_prediction"])):
                raise FailClosed(f"S05 original-corpus diagonal prediction mismatch for {row['event_id']}")
    else:
        for cell, view in (("MM", "V0_MEAN_FULL"), ("FF", "V1_FINAL_POSITION")):
            probs = s01_probability_arrays[view]
            test_rows = np.fromiter((int(row["test_row"]) for row in rows), dtype=np.int64, count=n)
            saved_positions = np.asarray(probs[test_rows], dtype=np.float32).argmax(axis=1)
            observed_positions = candidate_position_by_cell[cell]
            if not np.array_equal(saved_positions, observed_positions):
                mismatch = int(np.flatnonzero(saved_positions != observed_positions)[0])
                raise FailClosed(f"S05 S01 diagonal argmax mismatch for {view}, event={rows[mismatch]['event_id']}")

    ledger = []
    for index, row in enumerate(rows):
        target = int(targets[index])
        cells: dict[str, Any] = {}
        margins_by_cell: dict[str, dict[str, float]] = {}
        for cell in CELL_ORDER:
            logits = logits_by_cell[cell][index]
            margin_values = {PAIR_NAMES[pair]: float(logits[pair[0]] - logits[pair[1]]) for pair in PAIR_ORDER}
            margin_values["target_vs_best_rival"] = float(logits[target] - max(float(logits[c]) for c in range(3) if c != target))
            margins_by_cell[cell] = margin_values
            cells[cell] = {
                "logits": [float(value) for value in logits],
                "prediction": int(prediction_by_cell[cell][index]),
                "correct": bool(int(prediction_by_cell[cell][index]) == target),
                "target_state_id": target,
                "target_margin": margin_values["target_vs_best_rival"],
                "margins": margin_values,
                "candidate_position_prediction": int(candidate_position_by_cell[cell][index]),
            }
        margin_decomposition = {}
        for name in MARGIN_NAMES:
            mm, fm, mf, ff = (margins_by_cell[cell][name] for cell in CELL_ORDER)
            margin_decomposition[name] = {
                "representation_at_M_readout": fm - mm,
                "readout_at_M_representation": mf - mm,
                "interaction": ff - fm - mf + mm,
                "diagonal_total": ff - mm,
            }
        ledger.append({
            "dataset": dataset,
            "event_id": row["event_id"],
            "target": target,
            "slices": row.get("slices", ["FACTORIAL_TEST"]),
            "row_index": row.get("row_index"),
            "quartet_id": row.get("quartet_id"),
            "variant_id": row.get("variant_id"),
            "cells": cells,
            "margin_decomposition": margin_decomposition,
        })
    receipt = {
        "dataset": dataset,
        "unique_events_replayed": n,
        "cells": list(CELL_ORDER),
        "diagonal_gate": "PASS",
        "FAS00_diagonal_predictions_exact": dataset == "FAS00_ORIGINAL",
        "S01_diagonal_argmax_parity": dataset == "S01_CONTROLLED",
        "precision": precision,
        "probe_fitting": False,
        "feature_extraction": False,
    }
    return ledger, receipt


def _stats(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    _finite("summary input", array)
    ordered = np.sort(array)
    n = len(ordered)
    return {
        "n": int(n),
        "mean": float(array.mean(dtype=np.float64)),
        "median": float(np.median(ordered)),
        "nearest_rank_p10": float(ordered[max(0, math.ceil(0.10 * n) - 1)]),
        "nearest_rank_p90": float(ordered[max(0, math.ceil(0.90 * n) - 1)]),
        "min": float(ordered[0]),
        "max": float(ordered[-1]),
        "positive": int(np.count_nonzero(array > 0)),
        "zero": int(np.count_nonzero(array == 0)),
        "negative": int(np.count_nonzero(array < 0)),
    }


def _metric_vector(rows: list[dict[str, Any]], indices: list[int], classes: int) -> dict[str, Any]:
    targets = np.asarray([rows[index]["target"] for index in indices], dtype=np.int64)
    support = np.bincount(targets, minlength=classes)
    if np.any(support == 0):
        raise FailClosed("S05 metric population lacks support for one or more classes")
    metrics: dict[str, Any] = {"n": int(len(indices)), "support": support.tolist()}
    for cell in CELL_ORDER:
        pred = np.asarray([rows[index]["cells"][cell]["prediction"] for index in indices], dtype=np.int64)
        correct = targets == pred
        correct_by_class = np.bincount(targets[correct], minlength=classes)
        recall = correct_by_class / support
        metrics.setdefault("cell_metrics", {})[cell] = {
            "accuracy": float(correct.mean()),
            "balanced_accuracy": float(recall.mean()),
            "correct_by_class": correct_by_class.tolist(),
            "recall_by_class": [float(value) for value in recall],
            "predicted_class_counts": np.bincount(pred, minlength=classes).tolist(),
        }
    scalar_values: dict[str, dict[str, float]] = {
        "accuracy": {cell: metrics["cell_metrics"][cell]["accuracy"] for cell in CELL_ORDER},
        "balanced_accuracy": {cell: metrics["cell_metrics"][cell]["balanced_accuracy"] for cell in CELL_ORDER},
    }
    for class_id in range(classes):
        scalar_values[f"recall_class_{class_id}"] = {
            cell: metrics["cell_metrics"][cell]["recall_by_class"][class_id] for cell in CELL_ORDER
        }
    margin_summary: dict[str, Any] = {}
    margin_statistics = ("mean", "median", "nearest_rank_p10", "nearest_rank_p90")
    for cell in CELL_ORDER:
        margin_summary[cell] = {}
        for name in MARGIN_NAMES:
            vals = [float(rows[index]["cells"][cell]["margins"][name]) for index in indices]
            margin_summary[cell][name] = _stats(vals)
            for statistic in margin_statistics:
                scalar_values.setdefault(f"{statistic}_margin/{name}", {})[cell] = margin_summary[cell][name][statistic]
    metrics["margin_summary"] = margin_summary
    decompositions = {}
    for measure, values in scalar_values.items():
        mm, fm, mf, ff = (values[cell] for cell in CELL_ORDER)
        decompositions[measure] = {
            "cell_values": values,
            "representation_at_M_readout": fm - mm,
            "readout_at_M_representation": mf - mm,
            "interaction": ff - fm - mf + mm,
            "diagonal_total": ff - mm,
            "decomposition_identity_error": (fm - mm) + (mf - mm) + (ff - fm - mf + mm) - (ff - mm),
        }
    metrics["metric_decomposition"] = decompositions

    margin_decomposition_summary = {}
    for name in MARGIN_NAMES:
        margin_decomposition_summary[name] = {}
        for component in DECOMP_NAMES:
            values = [float(rows[index]["margin_decomposition"][name][component]) for index in indices]
            margin_decomposition_summary[name][component] = _stats(values)
    metrics["event_margin_decomposition"] = margin_decomposition_summary
    return metrics


def _transition_summary(rows: list[dict[str, Any]], slices: dict[str, list[int]], classes: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for slice_name, indices in slices.items():
        targets = np.asarray([rows[index]["target"] for index in indices], dtype=np.int64)
        result[slice_name] = {"n": len(indices), "cell_pairs": {}}
        for first, second in CELL_PAIRS:
            matrix = np.zeros((classes, classes), dtype=np.int64)
            correctness = {"both_correct": 0, "first_only_correct": 0, "second_only_correct": 0, "both_incorrect": 0}
            for index, target in zip(indices, targets):
                pred_first = int(rows[index]["cells"][first]["prediction"])
                pred_second = int(rows[index]["cells"][second]["prediction"])
                matrix[pred_first, pred_second] += 1
                first_ok, second_ok = pred_first == target, pred_second == target
                if first_ok and second_ok:
                    correctness["both_correct"] += 1
                elif first_ok:
                    correctness["first_only_correct"] += 1
                elif second_ok:
                    correctness["second_only_correct"] += 1
                else:
                    correctness["both_incorrect"] += 1
            result[slice_name]["cell_pairs"][f"{first}_to_{second}"] = {
                "first_cell": first,
                "second_cell": second,
                "prediction_transition_counts_rows_first_columns_second": matrix.tolist(),
                "correctness_transitions": correctness,
            }
    return result


def _analyze_population(dataset: str, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if dataset == "FAS00_ORIGINAL":
        definitions = {
            "UNION": list(range(len(rows))),
            "CONTEXT_TERM_3": [i for i, row in enumerate(rows) if "CONTEXT_TERM_3" in row["slices"]],
            "ENTITY_TERM_7": [i for i, row in enumerate(rows) if "ENTITY_TERM_7" in row["slices"]],
        }
    else:
        definitions = {"FACTORIAL_TEST": list(range(len(rows)))}
    classes = 3
    summaries = {name: _metric_vector(rows, indices, classes) for name, indices in definitions.items()}
    transitions = _transition_summary(rows, definitions, classes)
    return summaries, transitions


def _report(summaries: dict[str, dict[str, Any]], receipts: list[dict[str, Any]]) -> str:
    lines = [
        "# FAS-S05 Results: Crossed Representation × Readout Decomposition",
        "",
        "## Scope",
        "",
        "This is a fixed replay of the sealed `mean_full` and `final_position` feature arrays with each sealed scaler-plus-probe pipeline. It uses no model, extraction, fit, update, or tuning. Original-corpus and S01 controlled results are separate because their tasks, labels, and probes differ.",
        "",
        "Cells are `MM` = mean representation/mean readout, `FM` = final representation/mean readout, `MF` = mean representation/final readout, and `FF` = final representation/final readout.",
        "",
        "For each scalar outcome, the baseline-anchored components are representation-at-M `FM−MM`, readout-at-M `MF−MM`, interaction `FF−FM−MF+MM`, and diagonal total `FF−MM`. These sum by construction. Readout pipelines include their own standardizers; crossed cells are transport tests of complete fixed pipelines.",
        "",
    ]
    for dataset, populations in summaries.items():
        lines += [f"## {dataset}", ""]
        for population, report in populations.items():
            lines += [f"### {population} (n={report['n']})", "", "| Cell | Accuracy | Balanced accuracy | Recall by class | Support |", "|---|---:|---:|---|---|"]
            for cell in CELL_ORDER:
                item = report["cell_metrics"][cell]
                lines.append(f"| {cell} | {item['accuracy']:.6f} | {item['balanced_accuracy']:.6f} | " + ", ".join(f"{x:.6f}" for x in item["recall_by_class"]) + " | " + ", ".join(str(x) for x in report["support"]) + " |")
            lines += ["", "| Outcome | Representation at M | Readout at M | Interaction | Diagonal total |", "|---|---:|---:|---:|---:|"]
            for outcome in ("accuracy", "balanced_accuracy", "recall_class_0", "recall_class_1", "recall_class_2", *[f"mean_margin/{name}" for name in MARGIN_NAMES]):
                item = report["metric_decomposition"][outcome]
                lines.append(f"| {outcome} | {item['representation_at_M_readout']:.6f} | {item['readout_at_M_representation']:.6f} | {item['interaction']:.6f} | {item['diagonal_total']:.6f} |")
            lines.append("")
    lines += ["## Replay gates", ""]
    for receipt in receipts:
        lines.append(f"- `{receipt['dataset']}`: {receipt['unique_events_replayed']:,} unique rows; diagonal gate `{receipt['diagonal_gate']}`; mean/final prediction reproduction: `{receipt['FAS00_diagonal_predictions_exact']}`; S01 saved argmax parity: `{receipt['S01_diagonal_argmax_parity']}`.")
    lines += ["", "Cell-pair prediction transitions and per-event logits, margins, and decompositions are sealed in the JSON artifacts. No significance tests or confidence intervals were computed. Cross-cell degradation is retained as a transport result if replay identity checks pass.", "", "FAS-00 remains `SENSOR_FAIL_NO_SIGNAL`. S05 does not authorize Phase 4, an SAE, adaptation, or additional model contact.", ""]
    return "\n".join(lines)


def main() -> None:
    verified, populations = _verify_inputs()
    states = _load_states()
    s01_probabilities = {
        "V0_MEAN_FULL": np.load(S01_3_RUN / "predictions" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probabilities.npy", mmap_mode="r", allow_pickle=False),
        "V1_FINAL_POSITION": np.load(S01_3_RUN / "predictions" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probabilities.npy", mmap_mode="r", allow_pickle=False),
    }
    original_rows = populations["FAS00_ORIGINAL"]["rows"]
    s01_rows = populations["S01_CONTROLLED"]["rows"]
    ledgers: dict[str, list[dict[str, Any]]] = {}
    replay_receipts = []
    ledgers["FAS00_ORIGINAL"], receipt = _replay_dataset("FAS00_ORIGINAL", original_rows, states)
    replay_receipts.append(receipt)
    ledgers["S01_CONTROLLED"], receipt = _replay_dataset("S01_CONTROLLED", s01_rows, states, s01_probabilities)
    replay_receipts.append(receipt)

    # Verify the original S02 diagonal aggregate metrics exactly before saving results.
    sealed_s02_metrics = read_json(S02_METRICS)
    summaries: dict[str, dict[str, Any]] = {}
    transitions: dict[str, Any] = {}
    for dataset, rows in ledgers.items():
        summaries[dataset], transitions[dataset] = _analyze_population(dataset, rows)
    for slice_key, summary_key in (("CONTEXT_TERM_3", "test_context_term_3"), ("ENTITY_TERM_7", "test_entity_term_7")):
        for cell, view in (("MM", "mean_full"), ("FF", "final_position")):
            actual = summaries["FAS00_ORIGINAL"][slice_key]["cell_metrics"][cell]
            expected = sealed_s02_metrics["views"][view]["evaluations"][summary_key]
            if (actual["accuracy"] != expected["accuracy"] or
                    actual["balanced_accuracy"] != expected["balanced_accuracy"] or
                    actual["recall_by_class"] != expected["recall_by_class"] or
                    summaries["FAS00_ORIGINAL"][slice_key]["support"] != expected["support"]):
                raise FailClosed(f"S05 diagonal metrics do not exactly reproduce S02: {summary_key}/{view}")
    for dataset, populations_summary in summaries.items():
        for pop_name, pop_summary in populations_summary.items():
            for measure in pop_summary["metric_decomposition"].values():
                if abs(float(measure["decomposition_identity_error"])) > 1e-10:
                    raise FailClosed(f"S05 decomposition arithmetic identity failed for {dataset}/{pop_name}")

    # Write one ordered per-event ledger across the two nonpooled corpora.
    combined_ledger = ledgers["FAS00_ORIGINAL"] + ledgers["S01_CONTROLLED"]
    write_jsonl(RUN / "crossed-replay-ledger-v01.jsonl", combined_ledger)
    summary_payload = {
        "summary_id": "FAS_S05_CROSSED_SUMMARY_V01",
        "status": "COMPLETE",
        "cell_order": list(CELL_ORDER),
        "cell_definitions": {cell: {"representation": rep, "readout_pipeline": readout} for cell, (rep, readout) in CELL_DESCRIPTION.items()},
        "decomposition": {
            "reference_anchored": True,
            "formula": {"representation_at_M_readout": "FM-MM", "readout_at_M_representation": "MF-MM", "interaction": "FF-FM-MF+MM", "diagonal_total": "FF-MM"},
            "identity_checked": True,
        },
        "populations": summaries,
        "no_significance_tests": True,
        "no_confidence_intervals": True,
        "model_contact": False,
        "probe_fitting": False,
    }
    write_json(RUN / "crossed-summary-v01.json", summary_payload)
    transitions_payload = {
        "transition_id": "FAS_S05_PREDICTION_TRANSITIONS_V01",
        "class_orders": CLASS_NAMES,
        "populations": transitions,
        "pair_order": [f"{a}_to_{b}" for a, b in CELL_PAIRS],
        "counts_only": True,
        "no_significance_tests": True,
    }
    write_json(RUN / "prediction-transitions-v01.json", transitions_payload)
    report_path = RUN / "S05-RESULTS.md"
    if report_path.exists():
        raise FailClosed("Refusing to overwrite S05 report")
    report_path.write_text(_report(summaries, replay_receipts), encoding="utf-8", newline="\n")
    receipt = {
        "receipt_id": "FAS_S05_EXECUTION_RECEIPT_V01",
        "status": "COMPLETE",
        "S05_RESULT_READY": True,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "S02_ADAPTIVE_MECHANISM_AUTHORIZED": False,
        "protocol_root_sha256": verified["protocol"]["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT_PATH),
        "authorization_packet_sha256": sha_file(AUTHORIZATION_PATH),
        "event_populations_sha256": sha_file(RUN / "event-populations-v01.json"),
        "parents": verified["parents"],
        "replay_receipts": replay_receipts,
        "outputs": {
            name: {"sha256": sha_file(RUN / name), "bytes": (RUN / name).stat().st_size}
            for name in ("crossed-replay-ledger-v01.jsonl", "crossed-summary-v01.json", "prediction-transitions-v01.json", "S05-RESULTS.md")
        },
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "scaler_fitting": False,
        "optimizer_continuation": False,
        "adaptive_mechanisms": False,
        "SAE_analysis": False,
        "significance_tests": False,
        "confidence_intervals": False,
        "FAS00_PHASE4_AUTHORIZED": False,
    }
    write_json(RUN / "execution-receipt-v01.json", receipt)
    print(f"S05_CROSSED_REPLAY_COMPLETE original={len(ledgers['FAS00_ORIGINAL'])} s01={len(ledgers['S01_CONTROLLED'])} cells=4")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S05_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
