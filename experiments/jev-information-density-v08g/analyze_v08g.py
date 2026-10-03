"""Analyze completed v0.8G matched-policy LFM runs without model fitting."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
REPORTS = OUT / "reports"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("random", "curated")
EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_report(name: str, value: Any) -> Path:
    path = REPORTS / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def run_dir(seed_index: int, arm: str) -> Path:
    return OUT / "runs" / f"seed-{seed_index + 1}" / arm


def load_completed_runs() -> dict[tuple[int, str], dict[str, Any]]:
    result = {}
    for seed_index in range(3):
        for arm in ARMS:
            path = run_dir(seed_index, arm) / "run-report.json"
            if not path.is_file():
                raise FileNotFoundError(f"required run not complete: {path}")
            report = read_json(path)
            if report.get("status") != "COMPLETE" or report.get("backbone_frozen") is not True:
                raise ValueError(f"run status/backbone boundary failed: {path}")
            result[(seed_index, arm)] = report
    for seed_index in range(3):
        if result[(seed_index, "random")]["initial_head_sha256"] != result[(seed_index, "curated")]["initial_head_sha256"]:
            raise ValueError(f"paired initialization mismatch for seed {seed_index + 1}")
    return result


def row_metrics(row: dict[str, Any]) -> dict[str, float]:
    gold = [float(value) for value in row["gold"]]
    pred = [min(1.0, max(0.0, float(value))) for value in row["prediction"]]
    if len(gold) != len(pred) or not gold:
        raise ValueError(f"gold/prediction cardinality mismatch: {row.get('group_id')}")
    if row["kind"] == "independent":
        g, p = gold[0], pred[0]
        return {"accuracy": float((p >= 0.5) == (g >= 0.5)),
                "nll": -(g * math.log(max(EPS, p)) + (1.0 - g) * math.log(max(EPS, 1.0 - p))),
                "brier": (p - g) ** 2, "posterior_l1": abs(p - g),
                "confidence": p if p >= 0.5 else 1.0 - p,
                "gold_confidence": g if p >= 0.5 else 1.0 - g}
    p_sum, g_sum = sum(pred), sum(gold)
    if abs(p_sum - 1.0) > 1e-4 or abs(g_sum - 1.0) > 1e-4:
        raise ValueError(f"closed-set distribution is not normalized: {row.get('group_id')}")
    pred_i, gold_i = max(range(len(pred)), key=pred.__getitem__), max(range(len(gold)), key=gold.__getitem__)
    result = {"accuracy": float(pred_i == gold_i),
              "nll": -sum(g * math.log(max(EPS, p)) for g, p in zip(gold, pred)),
              "brier": sum((p - g) ** 2 for g, p in zip(gold, pred)),
              "posterior_l1": sum(abs(p - g) for g, p in zip(gold, pred)),
              "confidence": pred[pred_i], "gold_confidence": gold[pred_i]}
    if row.get("view") == "ordinal_score" and len(gold) > 1:
        g_cdf = p_cdf = squared = 0.0
        for g, p in zip(gold[:-1], pred[:-1]):
            g_cdf += g
            p_cdf += p
            squared += (g_cdf - p_cdf) ** 2
        result["ordinal_rps"] = squared / (len(gold) - 1)
        result["ordinal_adjacent"] = float(abs(pred_i - gold_i) <= 1)
        result["gold_expected_rank"] = sum(i * value for i, value in enumerate(gold))
        result["pred_expected_rank"] = sum(i * value for i, value in enumerate(pred))
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    metrics = [row_metrics(row) for row in rows]
    result: dict[str, Any] = {"count": len(rows)}
    for name in ("accuracy", "nll", "brier", "posterior_l1", "ordinal_rps", "ordinal_adjacent"):
        values = [item[name] for item in metrics if name in item]
        if values:
            result[name] = sum(values) / len(values)
    ece_pairs = [(item["confidence"], item["gold_confidence"]) for item in metrics]
    bins = []
    ece = 0.0
    for index in range(10):
        selected = [(conf, target) for conf, target in ece_pairs
                    if min(9, int(conf * 10)) == index]
        if selected:
            conf_mean = sum(x[0] for x in selected) / len(selected)
            target_mean = sum(x[1] for x in selected) / len(selected)
            ece += len(selected) / len(rows) * abs(conf_mean - target_mean)
            bins.append({"bin": index, "count": len(selected), "mean_confidence": conf_mean,
                         "mean_gold_confidence": target_mean})
        else:
            bins.append({"bin": index, "count": 0})
    result["ece_soft"] = ece
    result["reliability_bins"] = bins
    if rows[0].get("view") == "ordinal_score":
        result["expected_rank_spearman"] = spearman(
            [x["gold_expected_rank"] for x in metrics],
            [x["pred_expected_rank"] for x in metrics])
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[row["probability_source"]].append(row)
    result["by_probability_source"] = {
        source: {key: value for key, value in summarize_group(values).items()}
        for source, values in sorted(by_source.items())
    }
    return result


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [row_metrics(row) for row in rows]
    output: dict[str, Any] = {"count": len(rows)}
    for name in ("accuracy", "nll", "brier", "posterior_l1", "ordinal_rps", "ordinal_adjacent"):
        values = [item[name] for item in metrics if name in item]
        if values:
            output[name] = sum(values) / len(values)
    return output


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    def rank(values: list[float]) -> np.ndarray:
        order = np.argsort(values, kind="mergesort")
        ranks = np.empty(len(values), dtype=np.float64)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            ranks[order[start:end]] = (start + end - 1) / 2.0
            start = end
        return ranks
    x, y = rank(a), rank(b)
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def paired_root_sums(random_rows: list[dict[str, Any]], curated_rows: list[dict[str, Any]],
                     view: str) -> dict[str, dict[str, tuple[float, int]]]:
    if len(random_rows) != len(curated_rows):
        raise ValueError("paired prediction row count differs")
    totals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for left, right in zip(random_rows, curated_rows):
        if left["group_id"] != right["group_id"] or left.get("root_id") != right.get("root_id"):
            raise ValueError("paired evaluation rows differ in group/root identity")
        if view != "all" and left.get("view") != view:
            continue
        root = left.get("root_id") or left["episode_id"]
        lmetrics, rmetrics = row_metrics(left), row_metrics(right)
        for name in lmetrics.keys() & rmetrics.keys():
            if name not in {"accuracy", "nll", "brier", "posterior_l1", "ordinal_rps", "ordinal_adjacent"}:
                continue
            slot = totals[name][root]
            slot[0] += rmetrics[name] - lmetrics[name]
            slot[1] += 1
    return {metric: {root: (values[0], int(values[1])) for root, values in by_root.items()}
            for metric, by_root in totals.items()}


def cluster_interval(values: dict[str, tuple[float, int]], seed: int,
                     repetitions: int = 2000) -> dict[str, Any]:
    roots = sorted(values)
    sums = np.asarray([values[root][0] for root in roots], dtype=np.float64)
    counts = np.asarray([values[root][1] for root in roots], dtype=np.float64)
    point = float(sums.sum() / max(1.0, counts.sum()))
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(roots), size=(repetitions, len(roots)))
    boot_sum = sums[indices].sum(axis=1)
    boot_count = counts[indices].sum(axis=1)
    draws = boot_sum / np.maximum(1.0, boot_count)
    return {"point_delta_curated_minus_random": point,
            "family_cluster_bootstrap_95pct": [float(np.quantile(draws, 0.025)),
                                               float(np.quantile(draws, 0.975))],
            "bootstrap_repetitions": repetitions, "cluster_count": len(roots),
            "cluster_unit": "root_id"}


def eval_rows(seed_index: int, arm: str) -> list[dict[str, Any]]:
    return read_jsonl(Path(read_json(run_dir(seed_index, arm) / "run-report.json")
                           ["primary_newtight_eval"]["prediction_file"]))


def paired_effects(reports: dict[tuple[int, str], dict[str, Any]]) -> dict[str, Any]:
    by_seed: dict[str, Any] = {}
    pooled: dict[str, list[float]] = defaultdict(list)
    for seed_index in range(3):
        random_rows = eval_rows(seed_index, "random")
        curated_rows = eval_rows(seed_index, "curated")
        per_view = {}
        for view in ("choice", "independent_applicability", "ordinal_score"):
            root_values = paired_root_sums(random_rows, curated_rows, view)
            per_view[view] = {}
            for metric, values in sorted(root_values.items()):
                result = cluster_interval(values, seed=SEEDS[seed_index] + len(metric) + len(view))
                per_view[view][metric] = result
                pooled[f"{view}/{metric}"].append(result["point_delta_curated_minus_random"])
        by_seed[f"seed-{seed_index + 1}"] = per_view
    across = {}
    for key, values in sorted(pooled.items()):
        across[key] = {"seed_deltas": values, "mean": sum(values) / len(values),
                       "median": float(np.median(values)), "min": min(values), "max": max(values)}
    return {"seed_paired_cluster_deltas": by_seed, "across_seed_summary": across,
            "primary_endpoint": "NewTight-Eval", "no_composite_score": True}


def intervention_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("invariant_key"):
            by_key[row["invariant_key"]].append(row)
    deltas: dict[str, list[tuple[float, float]]] = defaultdict(list)
    pair_ids: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for values in by_key.values():
        base = next((row for row in values if row.get("perturbation_class") is None), None)
        if base is None:
            continue
        for child in values:
            kind = child.get("perturbation_class")
            if kind is None:
                continue
            gold_left, gold_right = dict(zip(base["candidate_semantic_ids"], base["gold"])), dict(zip(child["candidate_semantic_ids"], child["gold"]))
            pred_left, pred_right = dict(zip(base["candidate_semantic_ids"], base["prediction"])), dict(zip(child["candidate_semantic_ids"], child["prediction"]))
            shared = gold_left.keys() & gold_right.keys() & pred_left.keys() & pred_right.keys()
            for candidate in shared:
                gold_delta = float(gold_right[candidate] - gold_left[candidate])
                model_delta = float(pred_right[candidate] - pred_left[candidate])
                deltas[str(kind)].append((gold_delta, model_delta))
                pair_ids[str(kind)].add((str(base.get("invariant_key")), str(child.get("group_id"))))
    result = {}
    for kind, pairs in sorted(deltas.items()):
        gold = [x[0] for x in pairs]
        model = [x[1] for x in pairs]
        nonzero = [(g, m) for g, m in pairs if abs(g) > 1e-10]
        result[kind] = {"delta_count": len(pairs), "query_pair_count": len(pair_ids[kind]),
                        "sign_agreement_nonzero_gold": sum(int(g * m > 0) for g, m in nonzero) / max(1, len(nonzero)),
                        "nonzero_gold_delta_count": len(nonzero),
                        "pearson_model_gold_delta": pearson(gold, model),
                        "spearman_model_gold_delta": spearman(gold, model),
                        "mean_absolute_delta_error": sum(abs(g - m) for g, m in pairs) / max(1, len(pairs)),
                        "mean_gold_abs_delta": sum(abs(g) for g in gold) / max(1, len(gold)),
                        "mean_model_abs_delta": sum(abs(m) for m in model) / max(1, len(model))}
    return {"by_perturbation_class": result,
            "locality": {"status": "NOT_MEASURABLE_FROM_V08G_COMPACT_ROWS",
                         "reason": "generator-side affected/indirect/unaffected query truth is not present in the materialized evaluation rows; no locality labels were inferred"}}


def pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if float(x.std()) == 0 or float(y.std()) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def binding_report(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    by_id = {row["group_id"]: row for row in rows}
    paired = []
    unmatched = 0
    for row in rows:
        if "v06-binding-ordinary-" not in row["group_id"]:
            continue
        partner_id = row["group_id"].replace("v06-binding-ordinary-", "v06-binding-adversarial-", 1)
        partner = by_id.get(partner_id)
        if partner is None:
            unmatched += 1
            continue
        aligned_p, aligned_q = align_prediction(row, partner)
        if not aligned_p:
            unmatched += 1
            continue
        l1 = sum(abs(a - b) for a, b in zip(aligned_p, aligned_q))
        flip = max(range(len(aligned_p)), key=aligned_p.__getitem__) != max(range(len(aligned_q)), key=aligned_q.__getitem__)
        paired.append((row, partner, l1, flip))
    ordinary = [entry[0] for entry in paired]
    adversarial = [entry[1] for entry in paired]
    return {"profile": "opaque_definition", "selected_rows": len(rows),
            "ordinary_adversarial_pairs": len(paired), "unmatched_rows": unmatched,
            "ordinary_metrics": summarize(ordinary), "adversarial_metrics": summarize(adversarial),
            "paired_distribution_drift": {"mean_l1": sum(x[2] for x in paired) / max(1, len(paired)),
                                           "argmax_flip_rate": sum(int(x[3]) for x in paired) / max(1, len(paired)),
                                           "pairs": len(paired)},
            "interpretation": "paired opaque-definition response on the predeclared contradictory-binding bank"}


def align_prediction(left: dict[str, Any], right: dict[str, Any]) -> tuple[list[float], list[float]]:
    p = dict(zip(left["candidate_semantic_ids"], left["prediction"]))
    q = dict(zip(right["candidate_semantic_ids"], right["prediction"]))
    keys = [key for key in left["candidate_semantic_ids"] if key in q]
    return [p[key] for key in keys], [q[key] for key in keys]


def ood_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        axes = tuple(sorted(row.get("held_out_axes") or []))
        strata["/".join(axes) if axes else "family_seen_or_unlabeled"].append(row)
    by_family = {}
    for field in ("ontology_family", "world_or_topology_family"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("family_ids", {}).get(field, "missing"))].append(row)
        by_family[field] = {key: summarize(value) for key, value in sorted(grouped.items())}
    return {"axis_cells": {key: summarize(value) for key, value in sorted(strata.items())},
            "ontology_family": by_family["ontology_family"],
            "world_or_topology_family": by_family["world_or_topology_family"],
            "held_out_axis_definition": "family IDs absent from the union of R100* and C100* training metadata"}


def hard_sibling_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = row.get("coverage_features", {}).get("local_discrimination", [])
        count = 0
        for value in values:
            if str(value).startswith("same_parent_competitors:"):
                try:
                    count = int(str(value).split(":", 1)[1])
                except ValueError:
                    pass
        label = f"same_parent_competitors={count}"
        buckets[label].append(row)
    return {"metadata_proxy_only": True,
            "definition": "generator coverage_features.local_discrimination same_parent_competitors; not canonical ontology distance",
            "by_proxy_bucket": {key: summarize(value) for key, value in sorted(buckets.items())}}


def candidate_cardinality_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("candidate_cardinality", "unknown"))].append(row)
    return {"by_candidate_cardinality": {key: summarize(value) for key, value in sorted(buckets.items())}}


def invariance_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("invariant_key"):
            by_key[row["invariant_key"]].append(row)
    by_class: dict[str, list[tuple[float, bool, float]]] = defaultdict(list)
    for values in by_key.values():
        base = next((row for row in values if row.get("perturbation_class") is None), None)
        if base is None:
            continue
        for sibling in values:
            cls = str(sibling.get("perturbation_class") or "")
            if not cls:
                continue
            left, right = align_prediction(base, sibling)
            if not left:
                continue
            drift = sum(abs(a - b) for a, b in zip(left, right))
            flip = max(range(len(left)), key=left.__getitem__) != max(range(len(right)), key=right.__getitem__)
            gold_left = dict(zip(base["candidate_semantic_ids"], base["gold"]))
            gold_right = dict(zip(sibling["candidate_semantic_ids"], sibling["gold"]))
            gold_drift = sum(abs(gold_left[k] - gold_right[k]) for k in gold_left.keys() & gold_right.keys())
            by_class[cls].append((drift, flip, gold_drift))
    reports = {cls: {"pair_count": len(values),
                     "mean_aligned_prediction_l1": sum(x[0] for x in values) / len(values),
                     "argmax_flip_rate": sum(int(x[1]) for x in values) / len(values),
                     "mean_gold_l1": sum(x[2] for x in values) / len(values)}
               for cls, values in sorted(by_class.items())}
    order_classes = {name: value for name, value in reports.items()
                     if "reorder" in name.lower() or "candidate_order" in name.lower()}
    return {"all_certified_sibling_classes": reports,
            "candidate_order_classes": order_classes,
            "candidate_order_status": "MEASURED" if order_classes else "NO_CANDIDATE_REORDER_SIBLINGS_IN_EVAL_BANK",
            "semantic_surface_note": "Only generator-labeled sibling classes are summarized; class names are not inferred from prediction movement."}


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    reports = load_completed_runs()
    all_files: dict[str, str] = {}
    eval_by_run: dict[str, list[dict[str, Any]]] = {}
    for seed_index in range(3):
        for arm in ARMS:
            key = f"seed-{seed_index + 1}/{arm}"
            report = reports[(seed_index, arm)]
            pred_path = Path(report["primary_newtight_eval"]["prediction_file"])
            if sha256_file(pred_path) == "":
                raise RuntimeError("unreachable prediction hash error")
            all_files[str(run_dir(seed_index, arm) / "run-report.json")] = sha256_file(run_dir(seed_index, arm) / "run-report.json")
            all_files[str(pred_path)] = sha256_file(pred_path)
            eval_by_run[key] = read_jsonl(pred_path)

    typed = {f"seed-{i+1}/{arm}": reports[(i, arm)]["primary_newtight_eval"]["raw"]
             for i in range(3) for arm in ARMS}
    probability = {f"seed-{i+1}/{arm}": {
        "raw": reports[(i, arm)]["primary_newtight_eval"]["raw"],
        "temperature_scaled": reports[(i, arm)]["primary_newtight_eval"]["temperature_scaled"],
        "temperature": reports[(i, arm)]["primary_newtight_eval"]["temperature"]}
        for i in range(3) for arm in ARMS}
    effects = paired_effects(reports)

    schema = {f"seed-{i+1}/{arm}": reports[(i, arm)]["schema_profiles_newtight"]
              for i in range(3) for arm in ARMS}
    contradiction = {f"seed-{i+1}/{arm}": binding_report(
        Path(reports[(i, arm)]["contradictory_binding"]["prediction_file"]))
        for i in range(3) for arm in ARMS}
    interventions = {f"seed-{i+1}/{arm}": intervention_report(eval_by_run[f"seed-{i+1}/{arm}"])
                     for i in range(3) for arm in ARMS}
    ood = {f"seed-{i+1}/{arm}": ood_report(eval_by_run[f"seed-{i+1}/{arm}"])
           for i in range(3) for arm in ARMS}
    siblings = {f"seed-{i+1}/{arm}": hard_sibling_report(eval_by_run[f"seed-{i+1}/{arm}"])
                for i in range(3) for arm in ARMS}
    cardinality = {f"seed-{i+1}/{arm}": candidate_cardinality_report(eval_by_run[f"seed-{i+1}/{arm}"])
                   for i in range(3) for arm in ARMS}
    invariance = {f"seed-{i+1}/{arm}": invariance_report(eval_by_run[f"seed-{i+1}/{arm}"])
                  for i in range(3) for arm in ARMS}

    acquisition = {}
    longitudinal = {}
    for seed_index in range(3):
        for arm in ARMS:
            report = reports[(seed_index, arm)]
            key = f"seed-{seed_index + 1}/{arm}"
            acquisition[key] = [{"epoch": item["epoch"], "train": item["train"],
                                 "new_tight_eval": item["evaluation"]["new_tight_eval"],
                                 "legacy": item["evaluation"]["legacy"]}
                                for item in report["history"]]
            longitudinal[key] = report["legacy_evaluation"]

    behavior = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "status": "ANALYSIS_COMPLETE",
        "model": {"repo_id": "LiquidAI/LFM2.5-1.2B-Base",
                  "revision": read_json(REPORTS / "v08g-execution-scope.json")["model"]["revision"],
                  "backbone_frozen": True},
        "training": {"runs": 6, "seeds": SEEDS, "arms": list(ARMS), "epochs": 3,
                     "groups_per_arm": 100000, "paired_initialization_verified": True},
        "primary": "NewTight-Eval",
        "interpretation_guard": "No composite score or arbitrary win threshold is used.",
        "newtight_view_counts": {view: sum(1 for row in eval_by_run["seed-1/random"] if row.get("view") == view)
                                 for view in sorted({row.get("view") for row in eval_by_run["seed-1/random"]})},
        "open_world": "not evaluated: closed-set head/training lane",
        "locality": "not measurable: affected-query truth absent from compact eval records",
        "headline_effects": effects["across_seed_summary"],
        "run_wall_seconds": {f"seed-{i+1}/{arm}": reports[(i, arm)]["runtime"]["elapsed_seconds"]
                             for i in range(3) for arm in ARMS},
        "phoenix_access": False,
    }

    outputs = {
        "primary-newtight-eval.json": {key: reports[(i, arm)]["primary_newtight_eval"]
                                       for i in range(3) for arm in ARMS
                                       for key in [f"seed-{i+1}/{arm}"]},
        "longitudinal-eval.json": longitudinal,
        "typed-decision-quality.json": typed,
        "probability-quality.json": probability,
        "schema-binding.json": schema,
        "contradictory-binding.json": contradiction,
        "ood-transfer.json": ood,
        "hard-sibling.json": siblings,
        "candidate-cardinality.json": cardinality,
        "candidate-order-invariance.json": invariance,
        "intervention-geometry.json": interventions,
        "per-epoch-acquisition.json": acquisition,
        "paired-seed-effects.json": effects,
        "v08g-behavior-map.json": behavior,
    }
    written = {}
    for name, payload in outputs.items():
        path = write_report(name, payload)
        written[str(path)] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    integrity = {
        "status": "PASS", "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "execution_scope_sha256": sha256_file(REPORTS / "v08g-execution-scope.json"),
        "preflight_authorization_sha256": sha256_file(OUT / "preflight" / "model-contact-authorization.json"),
        "feature_cache_sha256": sha256_file(OUT / "feature-cache" / "lfm-v08g-features.pt"),
        "run_reports_and_predictions": all_files, "analysis_reports": written,
        "analyzer_source_sha256": sha256_file(Path(__file__)),
        "backbone_frozen": True, "phoenix_access": False,
    }
    integrity_path = write_report("integrity-receipt.json", integrity)
    print(json.dumps({"status": behavior["status"], "reports": len(written) + 1,
                      "integrity_sha256": sha256_file(integrity_path),
                      "headline_effects": effects["across_seed_summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
