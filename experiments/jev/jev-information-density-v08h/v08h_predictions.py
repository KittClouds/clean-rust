"""Post-hoc analysis of saved v0.8G predictions and run reports only."""

from __future__ import annotations

import collections
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from v08h_core import (
    calibration_bins,
    distribution_geometry,
    pearson,
    read_json,
    read_jsonl,
    root_cluster_interval,
    row_metrics,
    sha256_file,
    spearman,
    summarize_rows,
    target_distribution,
    weighted_numeric,
)

VIEWS = ("choice", "independent_applicability", "ordinal_score")
METRICS = ("accuracy", "nll", "brier", "posterior_l1", "ordinal_rps", "ordinal_adjacent")


def _run_key(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.parent.name}"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ece_and_buckets(rows: list[dict[str, Any]], bins: int = 10) -> list[dict[str, Any]]:
    return calibration_bins(rows, bins)


def _validate_metric_reproduction(context: dict[str, Any], run_metrics: dict[str, Any]) -> dict[str, Any]:
    # Resolve the frozen report directly from the verified receipt, without regenerating predictions.
    expected_path = next(Path(path) for path in context["integrity"]["analysis_reports"]
                         if Path(path).name == "primary-newtight-eval.json")
    expected_report = read_json(expected_path)
    checks = []
    for key, by_view in run_metrics.items():
        for view in VIEWS:
            source = by_view[view]["probability_source"]
            actual = by_view[view]["metrics"]
            expected = expected_report[key]["raw"]["by_view"][view][source]
            names = ["count", "nll", "brier", "accuracy", "ece_soft"]
            if view == "ordinal_score":
                ordinal = expected_report[key]["raw"]["by_view"][view]["ordinal"]
                names.extend([])
                ordinal_pairs = {
                    "exact_accuracy": actual.get("accuracy"),
                    "adjacent_accuracy": actual.get("ordinal_adjacent"),
                    "expected_rank_spearman": actual.get("expected_rank_spearman"),
                    "ranked_probability_score_normalized": actual.get("ordinal_rps"),
                }
                for name, value in ordinal_pairs.items():
                    target = ordinal[name]
                    passed = value is not None and abs(float(value) - float(target)) <= 5e-12
                    checks.append({"run": key, "view": view, "metric": name,
                                   "actual": value, "expected": target, "pass": passed})
            for name in names:
                value = actual.get(name)
                target = expected.get(name)
                passed = (value == target) if name == "count" else (
                    value is not None and target is not None and abs(float(value) - float(target)) <= 5e-12
                )
                checks.append({"run": key, "view": view, "metric": name,
                               "actual": value, "expected": target, "pass": passed})
    if not all(item["pass"] for item in checks):
        failed = [item for item in checks if not item["pass"]][:10]
        raise ValueError(f"saved prediction metric reproduction failed: {failed}")
    return {"status": "PASS", "checks": len(checks), "tolerance": 5e-12, "details": checks}


def _rows_by_view(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result = {view: [] for view in VIEWS}
    for row in rows:
        result[row["view"]].append(row)
    return result


def _validate_eval_alignment(context: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    eval_rows = context["eval_rows"]
    eval_by_id = {str(row["group_id"]): row for row in eval_rows}
    if len(eval_by_id) != len(eval_rows):
        raise ValueError("frozen NewTight-Eval materialization contains duplicate group IDs")
    loaded: dict[str, list[dict[str, Any]]] = {}
    alignment = {}
    for path in context["primary_prediction_paths"]:
        key = _run_key(path)
        rows = read_jsonl(path)
        ids = [str(row["group_id"]) for row in rows]
        if len(rows) != len(eval_rows) or len(set(ids)) != len(ids) or set(ids) != set(eval_by_id):
            raise ValueError(f"prediction IDs/count do not exactly match frozen eval occurrences: {key}")
        for row in rows:
            expected = eval_by_id[str(row["group_id"])]
            for field in ("view", "kind", "candidate_cardinality", "candidate_semantic_ids", "gold", "root_id"):
                if row.get(field) != expected.get(field):
                    if field == "gold" and len(row.get("gold", [])) == len(expected.get("gold", [])):
                        equal = all(abs(float(a) - float(b)) <= 1e-12
                                    for a, b in zip(row["gold"], expected["gold"]))
                        if equal:
                            continue
                    raise ValueError(f"prediction/eval row mismatch for {key} {field} at {row['group_id']}")
        loaded[key] = rows
        alignment[key] = {
            "prediction_file": str(path),
            "prediction_sha256": sha256_file(path),
            "count": len(rows),
            "unique_group_ids": len(set(ids)),
            "expected_eval_occurrences": len(eval_rows),
            "missing_ids": 0,
            "extra_ids": 0,
            "duplicate_loss": 0,
            "status": "PASS_EXACT_ROW_ALIGNMENT",
        }
    if len(loaded) != 6:
        raise ValueError(f"expected six NewTight prediction sets, received {len(loaded)}")
    return loaded, alignment


def _view_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for view, selected in _rows_by_view(rows).items():
        if not selected:
            raise ValueError(f"missing evaluation view {view}")
        source_counts = Counter(row["probability_source"] for row in selected)
        if len(source_counts) != 1:
            raise ValueError(f"mixed probability source in v0.8G view {view}")
        result[view] = {"probability_source": next(iter(source_counts)),
                        "metrics": summarize_rows(selected)}
    return result


def _prediction_detail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [row_metrics(row) for row in rows]
    top_prob, margins, pred_entropy, gold_prob, gold_rank = [], [], [], [], []
    pred_positions, gold_positions = Counter(), Counter()
    correct_conf, wrong_conf = [], []
    by_cardinality: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, metric in zip(rows, metrics):
        pred = [float(value) for value in row["prediction"]]
        gold = [float(value) for value in row["gold"]]
        order = sorted(range(len(pred)), key=lambda index: (-pred[index], index))
        top_prob.append(pred[order[0]])
        margins.append(pred[order[0]] - pred[order[1]] if len(pred) > 1 else abs(2 * pred[0] - 1))
        pred_entropy.append(-sum(value * math.log(max(1e-12, value)) for value in pred if value > 0))
        if row["kind"] == "independent":
            gold_prob.append(gold[0] if pred[0] >= 0.5 else 1.0 - gold[0])
            gold_rank.append(1 if (pred[0] >= 0.5) == (gold[0] >= 0.5) else 2)
            pred_positions["positive" if pred[0] >= 0.5 else "negative"] += 1
            gold_positions["positive" if gold[0] >= 0.5 else "negative"] += 1
        else:
            gold_best = max(range(len(gold)), key=gold.__getitem__)
            rank = 1 + sum(1 for value in pred if value > pred[gold_best])
            gold_prob.append(gold[order[0]])
            gold_rank.append(rank)
            pred_positions[str(order[0])] += 1
            gold_positions[str(gold_best)] += 1
        (correct_conf if metric["accuracy"] == 1.0 else wrong_conf).append(metric["confidence"])
        by_cardinality[str(row.get("candidate_cardinality", len(pred)))].append(row)
    summary = summarize_rows(rows)
    return {
        "metrics": summary,
        "mean_predicted_top_probability": _mean(top_prob),
        "mean_top1_top2_margin": _mean(margins),
        "mean_prediction_entropy_nats": _mean(pred_entropy),
        "mean_gold_probability_at_predicted_top": _mean(gold_prob),
        "mean_predicted_rank_of_gold_top": _mean([float(value) for value in gold_rank]),
        "predicted_top_position_or_binary_class_histogram": dict(sorted(pred_positions.items())),
        "gold_top_position_or_binary_class_histogram": dict(sorted(gold_positions.items())),
        "confidence_correct": weighted_numeric(correct_conf, [1.0] * len(correct_conf)),
        "confidence_incorrect": weighted_numeric(wrong_conf, [1.0] * len(wrong_conf)),
        "reliability_buckets": summary.get("reliability_bins", []),
        "by_candidate_cardinality": {
            key: {"count": len(value), **summarize_rows(value)}
            for key, value in sorted(by_cardinality.items(), key=lambda item: int(item[0]))
        },
    }


def _applicability_detail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_class: dict[str, list[dict[str, Any]]] = {"negative_gold_p_lt_0_5": [], "positive_gold_p_ge_0_5": []}
    p_pos, p_neg = [], []
    for row in rows:
        label = "positive_gold_p_ge_0_5" if float(row["gold"][0]) >= 0.5 else "negative_gold_p_lt_0_5"
        by_class[label].append(row)
        (p_pos if label.startswith("positive") else p_neg).append(float(row["prediction"][0]))
    return {
        "threshold_definition": "gold posterior >= 0.5; a descriptive binary split, not a hard-label reinterpretation",
        "overall": _prediction_detail(rows),
        "by_gold_class": {
            label: {
                "count": len(selected),
                "metrics": summarize_rows(selected),
                "mean_predicted_positive_probability": _mean([float(row["prediction"][0]) for row in selected]),
                "calibration_bins": calibration_bins(selected),
            }
            for label, selected in by_class.items()
        },
        "mean_predicted_probability_on_positive_gold": _mean(p_pos),
        "mean_predicted_probability_on_negative_gold": _mean(p_neg),
        "all_probability_calibration_bins": calibration_bins(rows),
    }


def _ordinal_detail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    metrics = [row_metrics(row) for row in rows]
    thresholds: dict[int, list[tuple[float, float]]] = defaultdict(list)
    expected_rank_errors, mode_errors, mode_distances = [], [], []
    exact = adjacent = 0
    for row in rows:
        gold = [float(value) for value in row["gold"]]
        pred = [float(value) for value in row["prediction"]]
        if len(gold) != len(pred):
            raise ValueError("ordinal candidate count mismatch")
        gold_mode = max(range(len(gold)), key=gold.__getitem__)
        pred_mode = max(range(len(pred)), key=pred.__getitem__)
        exact += pred_mode == gold_mode
        adjacent += abs(pred_mode - gold_mode) <= 1
        gold_expected = sum(index * value for index, value in enumerate(gold))
        pred_expected = sum(index * value for index, value in enumerate(pred))
        expected_rank_errors.append(abs(pred_expected - gold_expected))
        mode_errors.append(pred_mode - gold_mode)
        mode_distances.append(abs(pred_mode - gold_mode))
        cdf_gold = cdf_pred = 0.0
        for threshold, (g, p) in enumerate(zip(gold[:-1], pred[:-1])):
            cdf_gold += g
            cdf_pred += p
            thresholds[threshold].append((cdf_pred, cdf_gold))
    threshold_report = {}
    for threshold, values in sorted(thresholds.items()):
        brier = sum((p - g) ** 2 for p, g in values) / len(values)
        nll = -sum(g * math.log(max(1e-12, p)) + (1 - g) * math.log(max(1e-12, 1 - p))
                   for p, g in values) / len(values)
        bins = []
        for index in range(10):
            low, high = index / 10, (index + 1) / 10
            selected = [(p, g) for p, g in values if low <= p < high or (index == 9 and p == 1.0)]
            bins.append({"bin": index, "count": len(selected),
                         "mean_predicted_cdf": _mean([p for p, _ in selected]),
                         "mean_gold_cdf": _mean([g for _, g in selected])})
        threshold_report[str(threshold)] = {"count": len(values), "brier": brier, "nll": nll, "calibration_bins": bins}
    base = summarize_rows(rows)
    return {
        "count": len(rows),
        "exact_accuracy": base["accuracy"],
        "adjacent_accuracy": _mean([item["ordinal_adjacent"] for item in metrics]),
        "expected_rank_spearman": base.get("expected_rank_spearman"),
        "normalized_ranked_probability_score": base.get("ordinal_rps"),
        "mean_absolute_expected_rank_error": _mean(expected_rank_errors),
        "mean_signed_mode_error_pred_minus_gold": _mean([float(value) for value in mode_errors]),
        "mean_absolute_mode_error": _mean([float(value) for value in mode_distances]),
        "cumulative_thresholds": threshold_report,
        "interpretation": "Threshold indices follow the stored ordinal candidate ordering; no order is inferred from text.",
    }


def _same_parent(row: dict[str, Any]) -> int:
    for item in row.get("coverage_features", {}).get("local_discrimination", []):
        text = str(item)
        if text.startswith("same_parent_competitors:"):
            try:
                return int(text.split(":", 1)[1])
            except ValueError:
                return -1
    return -1


def _gold_margin(row: dict[str, Any]) -> float:
    distribution = target_distribution(row)
    ordered = sorted(distribution, reverse=True)
    return ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)


def _hard_sibling_detail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    choice = [row for row in rows if row["view"] == "choice"]
    competitor_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cardinality_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    margin_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ontology_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in choice:
        competitor_groups[str(_same_parent(row))].append(row)
        cardinality_groups[str(row["candidate_cardinality"])].append(row)
        margin = _gold_margin(row)
        margin_bin = "[0,.1]" if margin <= 0.1 else "(.1,.25]" if margin <= 0.25 else "(.25,.5]" if margin <= 0.5 else "(.5,1]"
        margin_groups[margin_bin].append(row)
        family = row.get("family_ids", {}).get("ontology_family", "<missing>")
        ontology_groups[str(family)].append(row)
    def pack(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return {key: {"count": len(value), **summarize_rows(value)} for key, value in sorted(groups.items())}
    return {
        "count": len(choice),
        "by_same_parent_competitor_count": pack(competitor_groups),
        "by_candidate_cardinality": pack(cardinality_groups),
        "by_gold_margin_descriptive_fixed_bins": pack(margin_groups),
        "by_ontology_family": pack(ontology_groups),
        "gold_margin_edges": [0.1, 0.25, 0.5, 1.0],
    }


def _paired_seed_report(context: dict[str, Any], predictions: dict[str, list[dict[str, Any]]],
                        view_metrics: dict[str, Any]) -> dict[str, Any]:
    by_seed = {}
    across: dict[str, list[float]] = defaultdict(list)
    for seed_index in range(1, 4):
        random_rows = predictions[f"seed-{seed_index}/random"]
        curated_rows = predictions[f"seed-{seed_index}/curated"]
        r_by_id = {row["group_id"]: row for row in random_rows}
        c_by_id = {row["group_id"]: row for row in curated_rows}
        if r_by_id.keys() != c_by_id.keys():
            raise ValueError("paired arms have different evaluation identities")
        paired_for_ci = []
        for group_id in sorted(r_by_id):
            left, right = r_by_id[group_id], c_by_id[group_id]
            if left["root_id"] != right["root_id"]:
                raise ValueError("paired evaluation root IDs differ")
            lm, rm = row_metrics(left), row_metrics(right)
            delta = {key: rm[key] - lm[key] for key in lm.keys() & rm.keys()
                     if key in METRICS}
            pair = dict(left)
            pair["_delta_metrics"] = delta
            paired_for_ci.append(pair)
        seed_result = {}
        for view in VIEWS:
            selected = [row for row in paired_for_ci if row["view"] == view]
            seed_result[view] = {}
            for metric in METRICS:
                if not any(metric in row["_delta_metrics"] for row in selected):
                    continue
                ci = root_cluster_interval(selected, metric, seed=20260927 + seed_index * 100 + len(metric), repetitions=2000)
                seed_result[view][metric] = ci
                across[f"{view}/{metric}"].append(float(ci["point_delta_curated_minus_random"]))
        by_seed[f"seed-{seed_index}"] = seed_result
    across_summary = {}
    for key, values in sorted(across.items()):
        across_summary[key] = {"seed_deltas": values, "mean": _mean(values),
                               "median": sorted(values)[len(values) // 2],
                               "min": min(values), "max": max(values)}
    return {
        "paired_root_cluster_deltas": by_seed,
        "across_seed": across_summary,
        "cluster_unit": "root_id",
        "bootstrap_repetitions": 2000,
        "interpretation": "Seed-level optimization replication only; three paired seeds do not identify causal mechanisms.",
    }


def _intervention_detail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("invariant_key"):
            by_key[str(row["invariant_key"])].append(row)
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    pair_counts: Counter[str] = Counter()
    unmatched = 0
    for values in by_key.values():
        base = next((row for row in values if row.get("perturbation_class") is None), None)
        if base is None:
            continue
        for child in values:
            perturbation = child.get("perturbation_class")
            if perturbation is None:
                continue
            gold_base = dict(zip(base["candidate_semantic_ids"], map(float, base["gold"])))
            gold_child = dict(zip(child["candidate_semantic_ids"], map(float, child["gold"])))
            pred_base = dict(zip(base["candidate_semantic_ids"], map(float, base["prediction"])))
            pred_child = dict(zip(child["candidate_semantic_ids"], map(float, child["prediction"])))
            candidates = sorted(gold_base.keys() & gold_child.keys() & pred_base.keys() & pred_child.keys())
            if not candidates:
                unmatched += 1
                continue
            family = base.get("family_ids", {}).get("intervention_family", "<missing>")
            key = f"{family}|{perturbation}|{base.get('view')}"
            pair_counts[key] += 1
            for candidate in candidates:
                buckets[key].append((gold_child[candidate] - gold_base[candidate],
                                     pred_child[candidate] - pred_base[candidate]))
    result = {}
    for key, pairs in sorted(buckets.items()):
        gold = [left for left, _ in pairs]
        model = [right for _, right in pairs]
        moving = [(g, m) for g, m in pairs if abs(g) > 1e-12]
        direction = [float((g > 0 and m > 0) or (g < 0 and m < 0)) for g, m in moving]
        stationary = [(g, m) for g, m in pairs if abs(g) <= 1e-12]
        result[key] = {
            "paired_query_count": pair_counts[key],
            "candidate_delta_count": len(pairs),
            "gold_delta_mean": _mean(gold),
            "model_delta_mean": _mean(model),
            "gold_delta_abs_mean": _mean([abs(value) for value in gold]),
            "model_delta_abs_mean": _mean([abs(value) for value in model]),
            "delta_sign_agreement_nonzero_gold": _mean(direction),
            "nonzero_gold_delta_count": len(moving),
            "zero_gold_delta_count": len(stationary),
            "false_movement_rate_on_zero_gold": _mean([float(abs(m) > 0.02) for _, m in stationary]),
            "pearson_model_gold_delta": pearson(gold, model),
            "spearman_model_gold_delta": spearman(gold, model),
            "mean_absolute_delta_error": _mean([abs(g - m) for g, m in pairs]),
            "under_response_rate": _mean([float(abs(m) + 1e-12 < abs(g)) for g, m in moving]),
            "over_response_rate": _mean([float(abs(m) > abs(g) + 1e-12) for g, m in moving]),
        }
    return {
        "by_intervention_family_class_view": result,
        "paired_query_unmatched": unmatched,
        "locality": {
            "status": "NOT_MEASURABLE_FROM_FROZEN_ARTIFACTS",
            "reason": "The saved NewTight records do not contain compiler-side direct/indirect/unaffected query truth; no locality labels were inferred.",
        },
    }


def _binding_directionality(context: dict[str, Any]) -> dict[str, Any]:
    run_summaries = {}
    semantic_pairs = {}
    for run_path, report in context["run_reports"].items():
        run_key = f"{Path(run_path).parent.parent.name}/{Path(run_path).parent.name}"
        standard = report.get("schema_profiles_newtight", {})
        run_summaries[run_key] = {
            "aggregate_schema_profiles": {
                profile: value.get("by_view", {}) for profile, value in standard.items()
            },
            "opaque_profile_paired_drift": standard.get("opaque_definition", {}).get(
                "paired_schema_drift_vs_name_definition"
            ),
            "rowwise_standard_profile_predictions_available": False,
        }
        path = Path(report["contradictory_binding"]["prediction_file"])
        rows = read_jsonl(path)
        by_id = {row["group_id"]: row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError(f"duplicate group ID in saved identity-binding predictions: {run_key}")
        pair_rows = []
        for row in rows:
            if not str(row["group_id"]).startswith("v06-binding-ordinary-"):
                continue
            counterpart_id = str(row["group_id"]).replace("v06-binding-ordinary-", "v06-binding-adversarial-", 1)
            other = by_id.get(counterpart_id)
            if other is None:
                raise ValueError(f"unmatched saved identity-binding pair: {row['group_id']}")
            left = dict(zip(row["candidate_semantic_ids"], map(float, row["prediction"])))
            right = dict(zip(other["candidate_semantic_ids"], map(float, other["prediction"])))
            gold_left = dict(zip(row["candidate_semantic_ids"], map(float, row["gold"])))
            gold_right = dict(zip(other["candidate_semantic_ids"], map(float, other["gold"])))
            if gold_left != gold_right or left.keys() != right.keys():
                raise ValueError("opaque-ID challenge altered semantic candidates or gold in the saved pair")
            keys = sorted(left)
            l1 = sum(abs(left[key] - right[key]) for key in keys)
            left_top = max(keys, key=left.__getitem__)
            right_top = max(keys, key=right.__getitem__)
            gold_top = max(keys, key=gold_left.__getitem__)
            transition = ("correct" if left_top == gold_top else "wrong", "correct" if right_top == gold_top else "wrong")
            pair_rows.append({
                "group_id_ordinary": row["group_id"],
                "group_id_adversarial": other["group_id"],
                "view": row["view"],
                "probability_l1": l1,
                "argmax_flip": left_top != right_top,
                "correctness_transition": "->".join(transition),
                "predicted_semantic_id_before": left_top,
                "predicted_semantic_id_after": right_top,
                "gold_semantic_id": gold_top,
                "candidate_probability_deltas": {key: right[key] - left[key] for key in keys},
            })
        if len(pair_rows) * 2 != len(rows):
            raise ValueError(f"identity challenge pair count does not cover rows for {run_key}")
        semantic_pairs[run_key] = pair_rows
    aggregate = {}
    for run_key, pairs in semantic_pairs.items():
        by_view: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for pair in pairs:
            by_view[pair["view"]].append(pair)
        view_stats = {}
        for view, rows in sorted(by_view.items()):
            transitions = Counter(row["correctness_transition"] for row in rows)
            deltas_by_candidate: dict[str, list[float]] = defaultdict(list)
            for row in rows:
                for candidate, delta in row["candidate_probability_deltas"].items():
                    deltas_by_candidate[candidate].append(delta)
            view_stats[view] = {
                "pair_count": len(rows),
                "mean_probability_l1": _mean([row["probability_l1"] for row in rows]),
                "argmax_flip_rate": _mean([float(row["argmax_flip"]) for row in rows]),
                "correctness_transitions": dict(sorted(transitions.items())),
                "mean_candidate_delta_by_semantic_id": {
                    candidate: _mean(values) for candidate, values in sorted(deltas_by_candidate.items())
                },
            }
        aggregate[run_key] = view_stats
    return {
        "probe_semantics": {
            "type": "opaque_identity_conflict / identity substitution",
            "definitions_changed": False,
            "gold_targets_changed": False,
            "correct_semantic_behavior": "preserve candidate probabilities aligned by semantic ID under opaque-ID substitution",
            "definition_change_signed_response": "NOT_MEASURABLE_NOT_APPLICABLE_TO_THIS_SAVED_PROBE",
            "source_confirmation": "The sealed v0.6 builder changes opaque_id fields for the first two candidates while leaving candidate definitions and gold targets unchanged.",
        },
        "standard_schema_profile_aggregates": run_summaries,
        "identity_invariance_by_run": aggregate,
        "paired_rows_by_run": semantic_pairs,
        "limitation": "Standard NewTight alternate-profile per-row predictions were not persisted; only the sealed aggregate profile metrics are available. The saved identity challenge supports rowwise ID-aligned drift but not a signed response to a changed definition.",
    }


def _legacy_instability(context: dict[str, Any]) -> dict[str, Any]:
    by_run = {}
    for path, report in context["run_reports"].items():
        key = f"{Path(path).parent.parent.name}/{Path(path).parent.name}"
        by_run[key] = report.get("legacy_evaluation", {})
    return {
        "available_saved_aggregate_metrics": by_run,
        "row_level_prediction_files_available": False,
        "NOT_AVAILABLE_WITHOUT_MODEL_CONTACT": [
            "predicted class histogram", "confusion matrix", "candidate-position preference",
            "row-level confidence histogram", "source/domain row composition",
            "per-row calibration by legacy class", "head output norms",
        ],
        "status": "AGGREGATE_REPORT_ONLY",
        "interpretation": "The saved legacy report confirms seed-by-treatment metric instability. It cannot distinguish class collapse, slot collapse, confidence polarization, or domain mode switching without persisted row-level predictions; checkpoints were not loaded.",
    }


def _flatten_epoch(run_report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in run_report.get("history", []):
        epoch = int(item["epoch"])
        evaluation = item.get("evaluation", {}).get("new_tight_eval", {})
        output: dict[str, Any] = {"train": item.get("train", {}), "wall_seconds": item.get("wall_seconds")}
        by_view = evaluation.get("by_view", {})
        for view, content in by_view.items():
            if view == "ordinal_score" and isinstance(content, dict) and "ordinal" in content:
                output[f"{view}/ordinal"] = content["ordinal"]
                content = {key: value for key, value in content.items() if key != "ordinal"}
            if isinstance(content, dict):
                for source, metrics in content.items():
                    if isinstance(metrics, dict):
                        for metric, value in metrics.items():
                            if isinstance(value, (int, float)):
                                output[f"{view}/{source}/{metric}"] = value
        result[epoch] = output
    return result


def _acquisition(context: dict[str, Any]) -> dict[str, Any]:
    runs = {}
    by_arm_seed: dict[str, dict[int, dict[str, Any]]] = {}
    for path, report in context["run_reports"].items():
        key = f"{Path(path).parent.parent.name}/{Path(path).parent.name}"
        epochs = _flatten_epoch(report)
        by_arm_seed[key] = epochs
        runs[key] = {
            "epochs": epochs,
            "train_loss_by_epoch": {str(epoch): value.get("train", {}).get("loss") for epoch, value in epochs.items()},
            "wall_seconds_by_epoch": {str(epoch): value.get("wall_seconds") for epoch, value in epochs.items()},
        }
    paired = {}
    all_fields = sorted(set().union(*(set(value) for value in by_arm_seed.values())))
    for seed_index in range(1, 4):
        left_key, right_key = f"seed-{seed_index}/random", f"seed-{seed_index}/curated"
        left, right = by_arm_seed[left_key], by_arm_seed[right_key]
        epoch_rows = {}
        for epoch in (1, 2, 3):
            fields = set(left.get(epoch, {})) & set(right.get(epoch, {}))
            epoch_rows[str(epoch)] = {
                field: {"random": left[epoch][field], "curated": right[epoch][field],
                        "delta_curated_minus_random": right[epoch][field] - left[epoch][field]}
                for field in sorted(fields)
                if isinstance(left[epoch][field], (int, float)) and isinstance(right[epoch][field], (int, float))
            }
        transitions = {}
        for first, second in ((1, 2), (2, 3)):
            fields = set(left.get(first, {})) & set(left.get(second, {})) & set(right.get(first, {})) & set(right.get(second, {}))
            transitions[f"{first}_to_{second}"] = {
                field: {
                    "random_change": left[second][field] - left[first][field],
                    "curated_change": right[second][field] - right[first][field],
                    "difference_in_change": (right[second][field] - right[first][field])
                    - (left[second][field] - left[first][field]),
                }
                for field in sorted(fields)
                if isinstance(left[first][field], (int, float)) and isinstance(left[second][field], (int, float))
                and isinstance(right[first][field], (int, float)) and isinstance(right[second][field], (int, float))
            }
        paired[f"seed-{seed_index}"] = {"arm_metrics_by_epoch": epoch_rows, "typed_transition_changes": transitions}
    return {
        "runs": runs,
        "paired_seed_trajectories": paired,
        "epoch_fields": all_fields,
        "primary_terminal_epoch": 3,
        "note": "Only saved epoch aggregates are analyzed; no checkpoints or heads were loaded.",
    }


def analyze_predictions(context: dict[str, Any]) -> dict[str, Any]:
    predictions, alignment = _validate_eval_alignment(context)
    run_metrics = {key: _view_metrics(rows) for key, rows in predictions.items()}
    reproduction = _validate_metric_reproduction(context, run_metrics)
    choice, applicability, ordinal, hard_sibling = {}, {}, {}, {}
    interventions = {}
    for key, rows in predictions.items():
        by_view = _rows_by_view(rows)
        choice[key] = _prediction_detail(by_view["choice"])
        applicability[key] = _applicability_detail(by_view["independent_applicability"])
        ordinal[key] = _ordinal_detail(by_view["ordinal_score"])
        hard_sibling[key] = _hard_sibling_detail(rows)
        interventions[key] = _intervention_detail(rows)
    paired = _paired_seed_report(context, predictions, run_metrics)
    binding = _binding_directionality(context)
    legacy = _legacy_instability(context)
    acquisition = _acquisition(context)
    return {
        "prediction_alignment": alignment,
        "typed_metric_reproduction": reproduction,
        "run_typed_metrics": run_metrics,
        "choice_prediction_geometry": choice,
        "applicability_probability_geometry": applicability,
        "ordinal_cumulative_geometry": ordinal,
        "hard_sibling_breakdown": hard_sibling,
        "paired_seed_effects": paired,
        "binding_directionality": binding,
        "intervention_family_breakdown": interventions,
        "legacy_instability_audit": legacy,
        "acquisition_trajectories": acquisition,
        "prediction_rows_loaded_from_saved_files": sum(len(rows) for rows in predictions.values()),
    }
