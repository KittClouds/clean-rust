from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

# Keep the fixed FP32 replay reproducible on CPU and avoid BLAS oversubscription.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np

from s04_common_v02 import (
    CONTRACT,
    EVENTS,
    FACTOR_ORDER,
    RUN,
    STATE_PAIRS,
    VARIANT_ORDER,
    VIEW_INFO,
    FailClosed,
    canonical_root,
    iter_jsonl,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol_bundle,
    write_json,
    write_jsonl,
)


STATE_SURFACES = {0: "zavik", 1: "nurex", 2: "pavom"}
PAIR_NAMES = {pair: f"state_{pair[0]}_minus_state_{pair[1]}" for pair in STATE_PAIRS}
GROUP_AXES = (
    "context_term_split",
    "entity_term_split",
    "context_term_id",
    "entity_term_id",
    "relation_id",
    "state_id",
    "world_family_id",
    "observation_template_id",
    "query_template_id",
    "context_term_split_x_entity_term_split",
    "relation_id_x_state_id",
)
FACTORS = {"C": "context_alias", "E": "entity_alias", "P": "observation_paraphrase"}
BATCH_ROWS = 1024


def _finite_array(name: str, value: np.ndarray) -> None:
    if not np.isfinite(value).all():
        raise FailClosed(f"Non-finite values in sealed {name}")


def _load_probe(view: str) -> dict[str, np.ndarray]:
    path = VIEW_INFO[view]["probe"]
    with np.load(path, allow_pickle=False) as archive:
        required = {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
        if set(archive.files) != required:
            raise FailClosed(f"Unexpected sealed probe-state keys for {view}")
        state = {key: np.array(archive[key], copy=True) for key in required}
    dimension = int(VIEW_INFO[view]["dimension"])
    if (state["classes"].shape != (3,) or not np.array_equal(state["classes"], np.asarray([0, 1, 2])) or
            state["weights"].shape != (3, dimension) or state["weights"].dtype != np.dtype("<f4") or
            state["bias"].shape != (3,) or state["bias"].dtype != np.dtype("<f4") or
            state["scaler_mean"].shape != (dimension,) or state["scaler_mean"].dtype != np.dtype("<f8") or
            state["scaler_scale"].shape != (dimension,) or state["scaler_scale"].dtype != np.dtype("<f8")):
        raise FailClosed(f"Sealed probe-state dimensions, class order, or dtype differ for {view}")
    for name, values in state.items():
        if name != "classes":
            _finite_array(f"{view} probe {name}", values)
    mean32 = state["scaler_mean"].astype(np.float32)
    scale32 = state["scaler_scale"].astype(np.float32)
    if not np.isfinite(mean32).all() or not np.isfinite(scale32).all() or np.any(scale32 == 0):
        raise FailClosed(f"Sealed scaler is invalid after the contracted FP32 cast for {view}")
    return {**state, "mean32": mean32, "scale32": scale32}


def _load_selection() -> tuple[dict[str, Any], dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    protocol = verify_protocol_bundle()
    parents = verify_parents()
    preflight_path = RUN / "preflight-receipt-v01.json"
    audit_path = RUN / "design-audit-receipt-v01.json"
    eligibility_path = RUN / "design-eligibility-v01.json"
    preflight = read_json(preflight_path)
    audit = read_json(audit_path)
    eligibility = read_json(eligibility_path)
    if (preflight.get("status") != "PASS" or preflight.get("S04_DESIGN_AUDIT_PASS") is not True or
            preflight.get("S04_MARGIN_ANALYSIS_COMPLETE") is not False or
            preflight.get("protocol_root_sha256") != protocol["root_sha256"] or
            preflight.get("runner_correction_root_sha256") != protocol["runner_correction_root_sha256"] or
            preflight.get("eligibility_sha256") != sha_file(eligibility_path) or
            preflight.get("design_audit_receipt_sha256") != sha_file(audit_path) or
            audit.get("status") != "PASS" or audit.get("parents") != parents or
            audit.get("runner_correction_root_sha256") != protocol["runner_correction_root_sha256"] or
            eligibility.get("status") != "PASS" or eligibility.get("model_contact") is not False or
            eligibility.get("feature_payloads_read") is not False):
        raise FailClosed("S04 design preflight is absent, changed, or inconsistent")
    if preflight.get("parents") != parents:
        raise FailClosed("S04 preflight parent identities differ from current sealed parents")
    if eligibility.get("estimand_eligibility", {}).get("CE_joint_alias_interaction", "").startswith("ELIGIBLE"):
        raise FailClosed("S04 eligibility improperly promotes the absent CE intervention")
    event_index: dict[tuple[str, str], dict[str, Any]] = {}
    for quartet in eligibility.get("selected_quartets", []):
        qid = quartet["quartet_id"]
        if quartet.get("track_id") != "FACTORIAL_BALANCED":
            raise FailClosed(f"Non-factorial quartet in S04 selection: {qid}")
        if set(quartet.get("candidate_identity_order", [])) != {0, 1, 2}:
            raise FailClosed(f"Candidate identity order is invalid in {qid}")
        state_by_identity = {
            int(item["candidate_identity"]): int(item["state_id"])
            for item in quartet.get("candidate_semantics", [])
        }
        if set(state_by_identity) != {0, 1, 2} or set(state_by_identity.values()) != {0, 1, 2}:
            raise FailClosed(f"Candidate semantics do not map bijectively to state IDs in {qid}")
        quartet["_state_by_identity"] = state_by_identity
        for ref in quartet["variants"]:
            key = (qid, ref["variant_id"])
            if key in event_index:
                raise FailClosed(f"Duplicate selected event reference {key}")
            event_index[key] = {**ref, "quartet": quartet}
    if len(event_index) != int(preflight["selected_events"]):
        raise FailClosed("S04 selected event count differs from the sealed preflight")
    return {"protocol": protocol, "parents": parents, "preflight": preflight,
            "eligibility": eligibility, "event_index": event_index}, parents, event_index


def _replay_view(
    view: str,
    event_index: dict[tuple[str, str], dict[str, Any]],
    parent_identities: dict[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    info = VIEW_INFO[view]
    dimension = int(info["dimension"])
    feature_path = info["tensor"]
    expected_bytes = EVENTS * dimension * 4
    if feature_path.stat().st_size != expected_bytes:
        raise FailClosed(f"Feature tensor byte length differs for {view}")
    matrix = np.memmap(feature_path, dtype="<f4", mode="r", shape=(EVENTS, dimension), order="C")
    probabilities = np.load(info["probabilities"], mmap_mode="r", allow_pickle=False)
    if probabilities.shape != (21_272, 3) or probabilities.dtype != np.dtype("<f4"):
        raise FailClosed(f"Sealed S01-3 prediction array dimensions or dtype differ for {view}")
    state = _load_probe(view)

    ordered = sorted(event_index.items(), key=lambda item: int(item[1]["test_row"]))
    if [int(ref["test_row"]) for _, ref in ordered] != sorted({int(ref["test_row"]) for ref in event_index.values()}):
        raise FailClosed("Selected S04 test rows are not unique")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    parity_rows = 0
    for start in range(0, len(ordered), BATCH_ROWS):
        batch = ordered[start : start + BATCH_ROWS]
        feature_rows = np.fromiter((int(ref["feature_row_index"]) for _, ref in batch), dtype=np.int64, count=len(batch))
        test_rows = np.fromiter((int(ref["test_row"]) for _, ref in batch), dtype=np.int64, count=len(batch))
        if (np.any(feature_rows < 0) or np.any(feature_rows >= EVENTS) or
                np.any(test_rows < 0) or np.any(test_rows >= len(probabilities))):
            raise FailClosed(f"Out-of-range S01 feature/test row in {view}")
        raw = np.asarray(matrix[feature_rows], dtype=np.float32)
        _finite_array(f"{view} selected feature batch", raw)
        standardized = raw.copy()
        standardized -= state["mean32"]
        standardized /= state["scale32"]
        position_logits = np.empty((len(batch), 3), dtype=np.float32)
        np.matmul(standardized, state["weights"].T, out=position_logits)
        position_logits += state["bias"]
        _finite_array(f"{view} replay logits", position_logits)
        saved_prob = np.asarray(probabilities[test_rows], dtype=np.float32)
        _finite_array(f"{view} sealed probabilities", saved_prob)
        if not np.allclose(saved_prob.sum(axis=1, dtype=np.float64), 1.0, rtol=0, atol=2e-6):
            raise FailClosed(f"Sealed S01-3 probability row normalization failed for {view}")
        replay_argmax = position_logits.argmax(axis=1)
        saved_argmax = saved_prob.argmax(axis=1)
        mismatches = np.flatnonzero(replay_argmax != saved_argmax)
        if len(mismatches):
            row = batch[int(mismatches[0])][1]
            raise FailClosed(f"Sealed prediction argmax parity failure for {view}, test_row={row['test_row']}")
        parity_rows += len(batch)

        for offset, (key, ref) in enumerate(batch):
            quartet = ref["quartet"]
            order = [int(value) for value in quartet["candidate_identity_order"]]
            state_by_identity = quartet["_state_by_identity"]
            semantic_logits = np.empty(3, dtype=np.float64)
            for candidate_position, candidate_identity in enumerate(order):
                state_id = state_by_identity[candidate_identity]
                semantic_logits[state_id] = float(position_logits[offset, candidate_position])
            if not np.isfinite(semantic_logits).all():
                raise FailClosed(f"Semantic-state logit remapping is invalid for {key}")
            pred_position = int(replay_argmax[offset])
            pred_state = state_by_identity[order[pred_position]]
            result[key] = {
                "semantic_state_logits": semantic_logits,
                "position_logits": position_logits[offset].astype(np.float64),
                "replayed_candidate_position": pred_position,
                "sealed_candidate_position": int(saved_argmax[offset]),
                "replayed_state_id": pred_state,
                "argmax_parity": True,
            }
    if parity_rows != len(event_index) or len(result) != len(event_index):
        raise FailClosed(f"S01-3 replay did not cover every selected event for {view}")
    del matrix, probabilities
    return result, {
        "view": view,
        "selected_rows_replayed": parity_rows,
        "argmax_parity_failures": 0,
        "probe_state_sha256": parent_identities["exact_target_probe_state_sha256"][view],
        "prediction_array_sha256": parent_identities["exact_target_probabilities_sha256"][view],
        "feature_tensor_sha256": parent_identities["selected_feature_tensor_sha256"][view],
        "probe_iteration_limit_reached": True,
        "probe_fitting": False,
        "optimizer_continuation": False,
    }


def _margin_vector(logits: np.ndarray, target_state: int) -> dict[str, Any]:
    values = {PAIR_NAMES[pair]: float(logits[pair[0]] - logits[pair[1]]) for pair in STATE_PAIRS}
    rivals = [float(logits[state]) for state in range(3) if state != target_state]
    values["target_vs_best_rival"] = float(logits[target_state] - max(rivals))
    values["semantic_state_logits"] = [float(value) for value in logits]
    return values


def _diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float]:
    fields = list(PAIR_NAMES.values()) + ["target_vs_best_rival"]
    return {key: float(right[key] - left[key]) for key in fields}


def _build_ledger(design: dict[str, Any], replay: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for quartet in design["eligibility"]["selected_quartets"]:
        qid = quartet["quartet_id"]
        target = int(quartet["target_state_id"])
        event_refs = {ref["variant_id"]: ref for ref in quartet["variants"]}
        views: dict[str, Any] = {}
        for view in VIEW_INFO:
            variant_metrics: dict[str, Any] = {}
            for variant in VARIANT_ORDER:
                item = replay[view][(qid, variant)]
                variant_metrics[variant] = {
                    **_margin_vector(item["semantic_state_logits"], target),
                    "replayed_candidate_position": item["replayed_candidate_position"],
                    "sealed_candidate_position": item["sealed_candidate_position"],
                    "replayed_state_id": item["replayed_state_id"],
                    "argmax_parity": item["argmax_parity"],
                }
            deltas = {
                factor: _diff(variant_metrics["A"], variant_metrics[factor])
                for factor in FACTOR_ORDER
            }
            views[view] = {"variants": variant_metrics, "factor_deltas": deltas}
        gamma = {
            factor: {
                key: float(views["V1_FINAL_POSITION"]["factor_deltas"][factor][key] -
                           views["V0_MEAN_FULL"]["factor_deltas"][factor][key])
                for key in list(PAIR_NAMES.values()) + ["target_vs_best_rival"]
            }
            for factor in FACTOR_ORDER
        }
        surface_shift = {
            variant: _diff(
                views["V0_MEAN_FULL"]["variants"][variant],
                views["V1_FINAL_POSITION"]["variants"][variant],
            )
            for variant in VARIANT_ORDER
        }
        ledger.append({
            "quartet_id": qid,
            "track_id": quartet["track_id"],
            "context_term_split": quartet["context_term_split"],
            "entity_term_split": quartet["entity_term_split"],
            "context_term_id_A": quartet["context_term_id_A"],
            "context_term_id_C": quartet["context_term_id_C"],
            "context_term_A": quartet["context_term_A"],
            "context_term_C": quartet["context_term_C"],
            "context_pair_id": quartet["context_pair_id"],
            "entity_term_id_A": quartet["entity_term_id_A"],
            "entity_term_id_E": quartet["entity_term_id_E"],
            "entity_term_A": quartet["entity_term_A"],
            "entity_term_E": quartet["entity_term_E"],
            "entity_pair_id": quartet["entity_pair_id"],
            "relation_id": quartet["relation_id"],
            "state_id": quartet["state_id"],
            "state_surface": STATE_SURFACES[target],
            "world_family_id": quartet["world_family_id"],
            "observation_template_id_A": quartet["observation_template_id"],
            "observation_template_id_P": quartet["observation_template_id_P"],
            "query_template_id": quartet["query_template_id"],
            "target_state_id": target,
            "candidate_identity_order": quartet["candidate_identity_order"],
            "events": {
                variant: {
                    "event_id": event_refs[variant]["event_id"],
                    "test_row": event_refs[variant]["test_row"],
                    "feature_row_index": event_refs[variant]["feature_row_index"],
                }
                for variant in VARIANT_ORDER
            },
            "views": views,
            "surface_shift_final_minus_mean": surface_shift,
            "surface_differentials_final_minus_mean": gamma,
        })
    return ledger


def _group_values(quartet: dict[str, Any]) -> dict[str, str]:
    values = {
        "context_term_split": str(quartet["context_term_split"]),
        "entity_term_split": str(quartet["entity_term_split"]),
        "context_term_id": str(quartet["context_term_id_A"]),
        "entity_term_id": str(quartet["entity_term_id_A"]),
        "relation_id": str(quartet["relation_id"]),
        "state_id": str(quartet["state_id"]),
        "world_family_id": str(quartet["world_family_id"]),
        "observation_template_id": str(quartet["observation_template_id_A"]),
        "query_template_id": str(quartet["query_template_id"]),
        "context_term_split_x_entity_term_split": f"{quartet['context_term_split']}|{quartet['entity_term_split']}",
        "relation_id_x_state_id": f"{quartet['relation_id']}|{quartet['state_id']}",
    }
    return values


def _statistics(values: list[float]) -> dict[str, Any]:
    if not values:
        raise FailClosed("Cannot summarize an empty S04 measure group")
    array = np.asarray(values, dtype=np.float64)
    _finite_array("S04 summary values", array)
    ordered = np.sort(array)
    n = int(len(ordered))
    return {
        "n": n,
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


def _summary_series(ledger: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[dict[str, str], float]]]:
    series: dict[tuple[str, str], list[tuple[dict[str, str], float]]] = defaultdict(list)
    for row in ledger:
        groups = _group_values(row)
        for view in VIEW_INFO:
            for variant in VARIANT_ORDER:
                metrics = row["views"][view]["variants"][variant]
                for state_id, logit in enumerate(metrics["semantic_state_logits"]):
                    series[(f"logit/{view}/{variant}/state_{state_id}", "variant_value")].append((groups, float(logit)))
                for name in list(PAIR_NAMES.values()) + ["target_vs_best_rival"]:
                    series[(f"margin/{view}/{variant}/{name}", "variant_value")].append((groups, float(metrics[name])))
            for factor in FACTOR_ORDER:
                for name, value in row["views"][view]["factor_deltas"][factor].items():
                    series[(f"delta/{view}/{factor}/{name}", "factor_delta")].append((groups, float(value)))
        for factor in FACTOR_ORDER:
            for name, value in row["surface_differentials_final_minus_mean"][factor].items():
                series[(f"gamma/{factor}/{name}", "surface_differential")].append((groups, float(value)))
        for variant in VARIANT_ORDER:
            for name, value in row["surface_shift_final_minus_mean"][variant].items():
                series[(f"surface_shift/{variant}/{name}", "surface_shift")].append((groups, float(value)))
    return series


def _make_summary(ledger: list[dict[str, Any]], eligibility: dict[str, Any]) -> dict[str, Any]:
    series = _summary_series(ledger)
    summaries = []
    for (measure_id, measure_kind), observations in sorted(series.items()):
        for axis in GROUP_AXES:
            buckets: dict[str, list[float]] = defaultdict(list)
            for groups, value in observations:
                buckets[groups[axis]].append(value)
            for group_value, values in sorted(buckets.items()):
                summaries.append({
                    "measure_id": measure_id,
                    "measure_kind": measure_kind,
                    "group_axis": axis,
                    "group_value": group_value,
                    **_statistics(values),
                })
    return {
        "summary_id": "FAS_S04_MARGIN_SUMMARY_V01",
        "status": "COMPLETE",
        "unit": "one complete held-out A/C/E/P quartet",
        "quartets": len(ledger),
        "selected_events": len(ledger) * 4,
        "group_axes": list(GROUP_AXES),
        "term_id_grouping": "A-variant anchor alias; replacement alias IDs are explicit in the ledger",
        "statistic_set": ["n", "mean", "median", "nearest_rank_p10", "nearest_rank_p90", "min", "max", "positive", "zero", "negative"],
        "inference": {"significance_tests": False, "confidence_intervals": False, "view_selection": False},
        "estimand_eligibility": eligibility["estimand_eligibility"],
        "summaries": summaries,
        "model_contact": False,
        "probe_fitting": False,
    }


def _report(summary: dict[str, Any], ledger: list[dict[str, Any]], replay_receipts: list[dict[str, Any]]) -> str:
    lines = [
        "# FAS-S04 Results: Controlled Factor-to-Decision Transfer Geometry",
        "",
        f"Disposition: **{summary['status']}**. This report uses {len(ledger):,} held-out factorial-balanced A/C/E/P quartets ({len(ledger) * 4:,} events).",
        "",
        "## Scope and interpretation",
        "",
        "The analysis replays the two sealed S01-3 exact-target probes over the existing S01-2 `mean_full` and `final_position` feature arrays. The reported effects are lexical context-alias substitution (C), lexical entity-alias substitution (E), and observation-template paraphrase (P) responses. Canonical world semantics and target remain fixed within each quartet.",
        "",
        "The S01 controlled corpus has no joint CE variant and no within-quartet relation or state intervention. Therefore CE interaction and relation/state causal effects are not estimated. Relation and state summaries are strata only. State labels remain the invented terms `zavik`, `nurex`, and `pavom`.",
        "",
        "Each view has its own separately fitted sealed linear probe and standardizer. Gamma is the difference between these complete fixed pipelines; it does not isolate representation-only causation. Both exact-target probes reached their sealed 300-iteration limit. No continuation or refitting was performed.",
        "",
        "## Pooled surface differentials",
        "",
        "Each row reports the mean and median across quartets for one fixed estimand. A positive value means the final-position pipeline's within-quartet change is more positive than the mean-full pipeline's change for that margin.",
        "",
        "| Factor edge | Margin | n | Mean Gamma | Median Gamma | p10 | p90 | Positive / zero / negative |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    names = list(PAIR_NAMES.values()) + ["target_vs_best_rival"]
    for factor in FACTOR_ORDER:
        for name in names:
            vals = [float(row["surface_differentials_final_minus_mean"][factor][name]) for row in ledger]
            stat = _statistics(vals)
            lines.append(
                f"| {factor} ({FACTORS[factor]}) | {name} | {stat['n']} | {stat['mean']:.6f} | {stat['median']:.6f} | {stat['nearest_rank_p10']:.6f} | {stat['nearest_rank_p90']:.6f} | {stat['positive']} / {stat['zero']} / {stat['negative']} |"
            )
    lines.extend([
        "",
        "## Paired surface shifts",
        "",
        "These are final-position minus mean-full margin changes for the same quartet variant. They summarize whole-pipeline decision margins and must be interpreted with the separate probe fits and scalers in view.",
        "",
        "| Variant | Margin | n | Mean shift | Median shift | p10 | p90 | Positive / zero / negative |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for variant in VARIANT_ORDER:
        for name in names:
            vals = [float(row["surface_shift_final_minus_mean"][variant][name]) for row in ledger]
            stat = _statistics(vals)
            lines.append(
                f"| {variant} | {name} | {stat['n']} | {stat['mean']:.6f} | {stat['median']:.6f} | {stat['nearest_rank_p10']:.6f} | {stat['nearest_rank_p90']:.6f} | {stat['positive']} / {stat['zero']} / {stat['negative']} |"
            )
    lines.extend([
        "",
        "The full declared stratification set, including anchor term IDs, relation/state, world family, templates, and their preregistered cross-strata, is in `margin-summary-v01.json`. The complete per-quartet logits, pair margins, target margins, deltas, and Gamma values are in `quartet-margin-ledger-v01.jsonl`.",
        "",
        "## Replay integrity",
        "",
    ])
    for receipt in replay_receipts:
        lines.append(f"- `{receipt['view']}`: {receipt['selected_rows_replayed']:,} selected events replayed; sealed prediction argmax mismatches: {receipt['argmax_parity_failures']}; fixed probe iteration limit reached: `{receipt['probe_iteration_limit_reached']}`.")
    lines.extend([
        "",
        "No LFM load, feature extraction, probe fitting, optimizer continuation, significance testing, confidence interval, or adaptive mechanism was used. FAS-00 remains failed and no later phase is authorized by this result.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    design, _, event_index = _load_selection()
    replay: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    replay_receipts = []
    for view in VIEW_INFO:
        replay[view], receipt = _replay_view(view, event_index, design["parents"])
        replay_receipts.append(receipt)
    ledger = _build_ledger(design, replay)
    if len(ledger) != int(design["eligibility"]["selected_factorial_test_quartets"]):
        raise FailClosed("S04 ledger count differs from the sealed selected-quartet count")
    ledger_path = RUN / "quartet-margin-ledger-v01.jsonl"
    write_jsonl(ledger_path, ledger)
    summary = _make_summary(ledger, design["eligibility"])
    summary_path = RUN / "margin-summary-v01.json"
    write_json(summary_path, summary)
    report_path = RUN / "S04-RESULTS.md"
    if report_path.exists():
        raise FailClosed("Refusing to overwrite S04 results report")
    report_path.write_text(_report(summary, ledger, replay_receipts), encoding="utf-8", newline="\n")
    receipt = {
        "receipt_id": "FAS_S04_EXECUTION_RECEIPT_V01",
        "status": "COMPLETE",
        "protocol_root_sha256": design["protocol"]["root_sha256"],
        "runner_correction_root_sha256": design["protocol"]["runner_correction_root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT),
        "preflight_receipt_sha256": sha_file(RUN / "preflight-receipt-v01.json"),
        "design_eligibility_sha256": sha_file(RUN / "design-eligibility-v01.json"),
        "design_audit_receipt_sha256": sha_file(RUN / "design-audit-receipt-v01.json"),
        "parents": design["parents"],
        "selected_quartets": len(ledger),
        "selected_events": len(ledger) * 4,
        "replay": replay_receipts,
        "outputs": {
            "quartet-margin-ledger-v01.jsonl": {"sha256": sha_file(ledger_path), "bytes": ledger_path.stat().st_size},
            "margin-summary-v01.json": {"sha256": sha_file(summary_path), "bytes": summary_path.stat().st_size},
            "S04-RESULTS.md": {"sha256": sha_file(report_path), "bytes": report_path.stat().st_size},
        },
        "model_contact": False,
        "LFM_loaded": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "optimizer_continuation": False,
        "adaptive_mechanisms": False,
        "significance_tests": False,
        "confidence_intervals": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "SAE_ANALYSIS_AUTHORIZED": False,
        "FAS00_modified": False,
        "S01_modified": False,
    }
    write_json(RUN / "execution-receipt-v01.json", receipt)
    print(f"S04_MARGIN_ANALYSIS_COMPLETE quartets={len(ledger)} events={len(ledger) * 4} summary_rows={len(summary['summaries'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S04_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
