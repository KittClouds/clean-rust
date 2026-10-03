"""Sealed analysis for the v0.4 frozen-backbone gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


RUN = Path(r"D:\codex-runs\jev-frozen-saturation-v04")
REPORT = RUN / "reports"
MODELS = ("minicpm5-1b-base", "qwen3-0.6b-base", "k2-horizon-0.9b")
SEEDS = {1000: (20260919,), 5000: (20260919, 20260920, 20260921), 10000: (20260919, 20260920, 20260921)}
THRESHOLDS = {
    "hard_sibling_rank_accuracy": 0.02,
    "ontology_ood_rank_accuracy": 0.02,
    "world_ood_rank_accuracy": 0.02,
    "nll": 0.02,
    "brier": 0.01,
    "gold_delta_correlation": 0.05,
    "counterfactual_locality_ratio": 0.10,
}
HARD_OPS = {"target_plus_one_sibling", "target_plus_two_siblings", "all_local_candidates", "local_plus_unrelated_distractor"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(name: str, value: Any) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def load_metadata() -> dict[str, dict[str, Any]]:
    rows = read_jsonl(RUN / "banks" / "all-metadata.jsonl")
    return {row["episode_id"]: row for row in rows}


def load_locality() -> dict[str, dict[str, Any]]:
    return {row["episode_id"]: row for row in read_jsonl(RUN / "ood" / "locality-truth.jsonl")}


def report_file(model: str, scale: int, seed: int, root: Path | None = None) -> Path:
    root = root or (RUN / "runs" / "primary")
    return next((root / model / f"s{scale // 1000}k" / f"seed{seed}").glob("*.json"))


def load_report(model: str, scale: int, seed: int, root: Path | None = None) -> dict[str, Any]:
    return json.loads(report_file(model, scale, seed, root).read_text(encoding="utf-8"))


def load_rescue_report(model: str, seed: int) -> dict[str, Any]:
    path = next((RUN / "runs" / "primary20" / model / f"seed{seed}").glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def annotate_rows(report: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(report.get("test_rows", [])) + list(report.get("external_rows", []))
    annotated = []
    for row in rows:
        item = dict(row)
        meta = metadata.get(row["episode_id"], {})
        item["meta"] = meta
        item["family"] = meta.get("parent_family_id", row.get("invariant_key", row["episode_id"]))
        item["operation"] = meta.get("operation")
        item["factorial_cell"] = meta.get("factorial_cell", "unknown")
        annotated.append(item)
    return annotated


def row_scores(row: dict[str, Any]) -> tuple[float, float, float]:
    gold = row["gold"]
    pred = row["prediction"]
    if row["kind"] == "independent":
        q = min(max(float(pred[0]), 1e-12), 1.0 - 1e-12)
        p = float(gold[0])
        nll = -(p * math.log(q) + (1.0 - p) * math.log(1.0 - q))
        brier = (q - p) ** 2
        correct = float((q >= 0.5) == (p >= 0.5))
        return nll, brier, correct
    nll = -sum(float(p) * math.log(max(1e-12, float(q))) for p, q in zip(gold, pred))
    brier = sum((float(p) - float(q)) ** 2 for p, q in zip(gold, pred))
    correct = float(max(range(len(pred)), key=lambda index: pred[index]) == max(range(len(gold)), key=lambda index: gold[index]))
    return nll, brier, correct


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else float("nan")


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return float("nan")
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return numerator / denominator if denominator > 0.0 else 0.0


def subset(rows: list[dict[str, Any]], predicate) -> list[dict[str, Any]]:
    return [row for row in rows if predicate(row)]


def basic_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores = [row_scores(row) for row in rows]
    return {
        "count": len(rows),
        "nll": mean(score[0] for score in scores),
        "brier": mean(score[1] for score in scores),
        "accuracy": mean(score[2] for score in scores),
    }


def model_delta_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    base: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row["operation"] == "base":
            base[(row["family"], row["query_id"])] = row
    gold_delta: list[float] = []
    model_delta: list[float] = []
    for row in rows:
        if row["operation"] not in {"counterfactual_state_change", "supporting_evidence_removal", "observation_intervention"}:
            continue
        parent = base.get((row["family"], row["query_id"]))
        if not parent or len(parent["gold"]) != len(row["gold"]):
            continue
        gold_delta.extend(float(child) - float(parent_value) for child, parent_value in zip(row["gold"], parent["gold"]))
        model_delta.extend(float(child) - float(parent_value) for child, parent_value in zip(row["prediction"], parent["prediction"]))
    signs = [float((a == 0.0) or (a * b >= 0.0)) for a, b in zip(gold_delta, model_delta)]
    return {
        "count": len(gold_delta),
        "sign_agreement": mean(signs),
        "pearson": correlation(gold_delta, model_delta),
        "mean_absolute_delta_error": mean(abs(a - b) for a, b in zip(gold_delta, model_delta)),
    }


def locality_metrics(rows: list[dict[str, Any]], locality: dict[str, dict[str, Any]]) -> dict[str, float]:
    by_episode = {(row["episode_id"], row["query_id"]): row for row in rows}
    movements = {"direct": [], "indirect": [], "unaffected": []}
    for episode_id, truth in locality.items():
        child_candidates = [row for row in rows if row["episode_id"] == episode_id]
        if not child_candidates:
            continue
        parent_id = truth.get("parent_episode_id")
        for child in child_candidates:
            parent = by_episode.get((parent_id, child["query_id"]))
            if not parent or len(parent["prediction"]) != len(child["prediction"]):
                continue
            movement = mean(abs(float(a) - float(b)) for a, b in zip(child["prediction"], parent["prediction"]))
            if child["query_id"] in truth.get("directly_affected_query_ids", []):
                movements["direct"].append(movement)
            elif child["query_id"] in truth.get("indirectly_affected_query_ids", []):
                movements["indirect"].append(movement)
            elif child["query_id"] in truth.get("provably_unaffected_query_ids", []):
                movements["unaffected"].append(movement)
    affected = movements["direct"] + movements["indirect"]
    unaffected = movements["unaffected"]
    return {
        "direct_count": len(movements["direct"]),
        "indirect_count": len(movements["indirect"]),
        "unaffected_count": len(unaffected),
        "direct_movement": mean(movements["direct"]),
        "indirect_movement": mean(movements["indirect"]),
        "unaffected_movement": mean(unaffected),
        "locality_ratio": mean(affected) / max(1e-9, mean(unaffected)) if affected and unaffected else float("nan"),
    }


def report_metrics(report: dict[str, Any], metadata: dict[str, dict[str, Any]], locality: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = annotate_rows(report, metadata)
    choice = lambda row: row["kind"] == "choice" and row["query_id"] in {"q_choice_closed", "q_ordinal"}
    hard = subset(rows, lambda row: choice(row) and row["operation"] in HARD_OPS)
    ontology = subset(rows, lambda row: choice(row) and row["factorial_cell"].startswith("ontology_ood"))
    world = subset(rows, lambda row: choice(row) and row["factorial_cell"].endswith("world_ood"))
    result = {
        "overall": basic_metrics(rows),
        "hard_sibling_rank_accuracy": basic_metrics(hard)["accuracy"],
        "ontology_ood_rank_accuracy": basic_metrics(ontology)["accuracy"],
        "world_ood_rank_accuracy": basic_metrics(world)["accuracy"],
        "hard_sibling_count": len(hard),
        "ontology_ood_count": len(ontology),
        "world_ood_count": len(world),
        "delta": model_delta_metrics(rows),
        "locality": locality_metrics(rows, locality),
        "by_cell": {},
    }
    for cell in sorted({row["factorial_cell"] for row in rows}):
        result["by_cell"][cell] = basic_metrics([row for row in rows if row["factorial_cell"] == cell])
    return result


def bootstrap(values: list[float], seed: int = 20260919, replicates: int = 1000) -> dict[str, float]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return {"mean": float("nan"), "lower": float("nan"), "upper": float("nan"), "n": 0}
    rng = random.Random(seed)
    samples = [mean(rng.choices(clean, k=len(clean))) for _ in range(replicates)]
    samples.sort()
    return {"mean": mean(clean), "lower": samples[int(0.025 * replicates)], "upper": samples[int(0.975 * replicates) - 1], "n": len(clean)}


def family_endpoint_map(
    report: dict[str, Any],
    endpoint: str,
    metadata: dict[str, dict[str, Any]],
    locality: dict[str, dict[str, Any]],
) -> dict[str, float]:
    rows = annotate_rows(report, metadata)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["family"]].append(row)
    result: dict[str, float] = {}
    for family, family_rows in grouped.items():
        if endpoint == "nll":
            result[family] = basic_metrics(family_rows)["nll"]
        elif endpoint == "brier":
            result[family] = basic_metrics(family_rows)["brier"]
        elif endpoint == "hard_sibling_rank_accuracy":
            rows_for_metric = [row for row in family_rows if row["kind"] == "choice" and row["query_id"] in {"q_choice_closed", "q_ordinal"} and row["operation"] in HARD_OPS]
            if rows_for_metric:
                result[family] = basic_metrics(rows_for_metric)["accuracy"]
        elif endpoint == "ontology_ood_rank_accuracy":
            rows_for_metric = [row for row in family_rows if row["kind"] == "choice" and row["query_id"] in {"q_choice_closed", "q_ordinal"} and row["factorial_cell"].startswith("ontology_ood")]
            if rows_for_metric:
                result[family] = basic_metrics(rows_for_metric)["accuracy"]
        elif endpoint == "world_ood_rank_accuracy":
            rows_for_metric = [row for row in family_rows if row["kind"] == "choice" and row["query_id"] in {"q_choice_closed", "q_ordinal"} and row["factorial_cell"].endswith("world_ood")]
            if rows_for_metric:
                result[family] = basic_metrics(rows_for_metric)["accuracy"]
        elif endpoint == "gold_delta_correlation":
            value = model_delta_metrics(family_rows)["pearson"]
            if math.isfinite(value):
                result[family] = value
        elif endpoint == "counterfactual_locality_ratio":
            value = locality_metrics(family_rows, locality)["locality_ratio"]
            if math.isfinite(value):
                result[family] = value
    return result


def terminal_transition(
    model: str,
    reports: dict[int, list[dict[str, Any]]],
    metadata: dict[str, dict[str, Any]],
    locality: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Use the fixed held-out family bank. Each 5k/10k report is evaluated on
    # the same test/external rows; bootstrap the paired per-family differences.
    values: dict[str, list[float]] = defaultdict(list)
    terminal_pair = (10000, 20000) if 20000 in reports else (5000, 10000)
    transition_name = "10k_to_20k" if terminal_pair == (10000, 20000) else "5k_to_10k"
    for scale in terminal_pair:
        for report in reports[scale]:
            metrics = report["metrics"]
            for endpoint in ("hard_sibling_rank_accuracy", "ontology_ood_rank_accuracy", "world_ood_rank_accuracy", "nll", "brier", "gold_delta_correlation", "counterfactual_locality_ratio"):
                value = metrics.get(endpoint)
                if endpoint in {"nll", "brier"}:
                    value = metrics["overall"][endpoint]
                elif endpoint == "gold_delta_correlation":
                    value = metrics["delta"]["pearson"]
                elif endpoint == "counterfactual_locality_ratio":
                    value = metrics["locality"]["locality_ratio"]
                values[f"{scale}:{endpoint}"].append(float(value) if value is not None else float("nan"))
    endpoint_result: dict[str, Any] = {}
    for endpoint in THRESHOLDS:
        first = [value for value in values[f"{terminal_pair[0]}:{endpoint}"] if math.isfinite(value)]
        second = [value for value in values[f"{terminal_pair[1]}:{endpoint}"] if math.isfinite(value)]
        if not first or not second:
            endpoint_result[endpoint] = {"status": "BLOCKED", "reason": "missing metric"}
            continue
        observed = mean(second) - mean(first)
        if endpoint in {"nll", "brier"}:
            observed = mean(first) - mean(second)
        cluster_deltas: list[float] = []
        for first_report, second_report in zip(reports[terminal_pair[0]], reports[terminal_pair[1]]):
            first_by_family = family_endpoint_map(first_report, endpoint, metadata, locality)
            second_by_family = family_endpoint_map(second_report, endpoint, metadata, locality)
            for family in first_by_family.keys() & second_by_family.keys():
                delta = second_by_family[family] - first_by_family[family]
                if endpoint in {"nll", "brier"}:
                    delta = -delta
                cluster_deltas.append(delta)
        interval = bootstrap(cluster_deltas)
        threshold = THRESHOLDS[endpoint]
        endpoint_result[endpoint] = {
            "transition": transition_name,
            "mean_first": mean(first),
            "mean_second": mean(second),
            "oriented_observed_improvement": observed,
            "bootstrap_upper_bound": interval["upper"],
            "material_threshold": threshold,
            "saturated": observed < threshold and interval["upper"] < threshold,
            "bootstrap": interval,
            "bootstrap_unit": "parent_family_id",
        }
    semantic = [endpoint_result.get(name, {}).get("saturated", False) for name in ("hard_sibling_rank_accuracy", "ontology_ood_rank_accuracy", "world_ood_rank_accuracy")]
    saturated_count = sum(bool(item.get("saturated")) for item in endpoint_result.values() if isinstance(item, dict))
    endpoint_result["gate_summary"] = {
        "semantic_rank_saturated": sum(semantic) == 3,
        "saturated_endpoint_count": saturated_count,
        "required_saturated_endpoint_count": 4,
        "primary_head_saturation": sum(semantic) == 3 and saturated_count >= 4,
        "rescue_eligible": not (sum(semantic) == 3 and saturated_count >= 4),
    }
    return endpoint_result


def primary_bundle(metadata: dict[str, dict[str, Any]], locality: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bundle: dict[str, Any] = {}
    for model in MODELS:
        reports: dict[int, list[dict[str, Any]]] = {}
        for scale, seeds in SEEDS.items():
            reports[scale] = []
            for seed in seeds:
                report = load_report(model, scale, seed)
                report["metrics"] = report_metrics(report, metadata, locality)
                reports[scale].append(report)
        reports[20000] = []
        for seed in SEEDS[10000]:
            report = load_rescue_report(model, seed)
            report["metrics"] = report_metrics(report, metadata, locality)
            reports[20000].append(report)
        bundle[model] = reports
    return bundle


def head_control(root: Path, metadata: dict[str, dict[str, Any]], locality: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for model in MODELS:
        path = next((root / model).glob("*.json"))
        report = json.loads(path.read_text(encoding="utf-8"))
        result[model] = {"report_file": str(path), "metrics": report_metrics(report, metadata, locality), "raw": report["test"]["raw"]}
    return result


def layer_control(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for model in ("minicpm5-1b-base", "qwen3-0.6b-base"):
        result[model] = {}
        for path in (root / model).glob("*/*.json"):
            report = json.loads(path.read_text(encoding="utf-8"))
            result[model][str(report["layer_fraction"])] = {
                "raw": report["test"]["raw"],
                "external": report["external_transfer"],
                "trainable_parameters": report["trainable_parameters"],
            }
    return result


def control_report(root: Path, model: str) -> dict[str, Any]:
    path = next((root / model).glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def failure_sets(
    report: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
    slice_name: str,
) -> tuple[set[str], set[str]]:
    rows = annotate_rows(report, metadata)
    cases: set[str] = set()
    families: set[str] = set()
    for row in rows:
        if row["kind"] != "choice" or row["query_id"] not in {"q_choice_closed", "q_ordinal"}:
            continue
        if slice_name == "hard_sibling" and row["operation"] not in HARD_OPS:
            continue
        if slice_name == "true_ood" and row["factorial_cell"] == "ontology_id_world_id":
            continue
        if slice_name == "ontology_ood" and not row["factorial_cell"].startswith("ontology_ood"):
            continue
        if slice_name == "world_ood" and not row["factorial_cell"].endswith("world_ood"):
            continue
        if row_scores(row)[2] >= 0.5:
            continue
        cases.add(f"{row['family']}::{row['group_id']}")
        families.add(row["family"])
    return cases, families


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def residual_audit(
    model: str,
    bundle: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # The terminal primary fit is the rescued 20k fit. Controls are deliberately
    # matched at 10k, where the larger/oracle experiments were frozen.
    terminal_reports = bundle[20000]
    primary_cases: dict[str, list[set[str]]] = {}
    primary_families: dict[str, list[set[str]]] = {}
    for slice_name in ("hard_sibling", "true_ood", "ontology_ood", "world_ood"):
        cases, families = zip(*(failure_sets(report, metadata, slice_name) for report in terminal_reports))
        primary_cases[slice_name] = list(cases)
        primary_families[slice_name] = list(families)
    larger = control_report(RUN / "runs" / "larger-head", model)
    oracle = control_report(RUN / "runs" / "oracle", model)
    overlap: dict[str, Any] = {}
    decisive_family_intersection: set[str] = set()
    for slice_name in primary_cases:
        persistent_cases = set.intersection(*primary_cases[slice_name]) if primary_cases[slice_name] else set()
        persistent_families = set.intersection(*primary_families[slice_name]) if primary_families[slice_name] else set()
        larger_cases, larger_families = failure_sets(larger, metadata, slice_name)
        oracle_cases, oracle_families = failure_sets(oracle, metadata, slice_name)
        if slice_name in {"hard_sibling", "true_ood", "ontology_ood", "world_ood"}:
            decisive_family_intersection |= persistent_families
        overlap[slice_name] = {
            "primary_seed_case_counts": [len(item) for item in primary_cases[slice_name]],
            "primary_seed_family_counts": [len(item) for item in primary_families[slice_name]],
            "persistent_case_count": len(persistent_cases),
            "persistent_family_count": len(persistent_families),
            "persistent_case_ids": sorted(persistent_cases)[:100],
            "persistent_families": sorted(persistent_families),
            "larger_head_case_count": len(larger_cases),
            "larger_head_family_count": len(larger_families),
            "oracle_case_count": len(oracle_cases),
            "oracle_family_count": len(oracle_families),
            "primary_vs_larger_family_jaccard": jaccard(persistent_families, larger_families),
            "primary_vs_oracle_family_jaccard": jaccard(persistent_families, oracle_families),
            "larger_preserves_residual_family": bool(persistent_families & larger_families),
            "oracle_preserves_residual_family": bool(persistent_families & oracle_families),
        }
    return {
        "terminal_scale": "20k",
        "control_scale": "10k",
        "by_slice": overlap,
        "decisive_persistent_families": sorted(decisive_family_intersection),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "primary"), default="all")
    args = parser.parse_args()
    metadata = load_metadata()
    locality = load_locality()
    bundle = primary_bundle(metadata, locality)
    if args.mode == "primary":
        write_json("primary-analysis.json", bundle)
        return

    learning: dict[str, Any] = {}
    for model, reports in bundle.items():
        learning[model] = {
            "scales": {
                str(scale): {
                    "seed_metrics": [report["metrics"] for report in values],
                    "means": {
                        "hard_sibling_rank_accuracy": mean(report["metrics"]["hard_sibling_rank_accuracy"] for report in values),
                        "ontology_ood_rank_accuracy": mean(report["metrics"]["ontology_ood_rank_accuracy"] for report in values),
                        "world_ood_rank_accuracy": mean(report["metrics"]["world_ood_rank_accuracy"] for report in values),
                        "nll": mean(report["metrics"]["overall"]["nll"] for report in values),
                        "brier": mean(report["metrics"]["overall"]["brier"] for report in values),
                    },
                }
                for scale, values in reports.items()
            },
            "terminal_transition": terminal_transition(model, reports, metadata, locality),
            "rescue": {
                "invoked": True,
                "reason": "material 5k-to-10k improvement observed before terminal analysis",
                "terminal_transition": "10k_to_20k",
                "additional_rescue_permitted": False,
            },
        }

    write_json("learning-saturation.json", learning)
    write_json("seed-stability.json", {model: {str(scale): [report["metrics"] for report in reports[scale]] for scale in reports} for model, reports in bundle.items()})
    write_json("head-capacity.json", head_control(RUN / "runs" / "larger-head", metadata, locality))
    write_json("frozen-feature-oracle.json", head_control(RUN / "runs" / "oracle", metadata, locality))
    write_json("layer-behavior.json", layer_control(RUN / "runs" / "layers"))

    factorial = {}
    for model, reports in bundle.items():
        terminal = reports[10000][-1]["metrics"]
        factorial[model] = terminal["by_cell"]
    write_json("ood-factorial.json", factorial)
    write_json("true-ontology-ood.json", {model: reports[10000][-1]["metrics"]["by_cell"].get("ontology_ood_world_id", {}) for model, reports in bundle.items()})
    write_json("true-world-ood.json", {model: reports[10000][-1]["metrics"]["by_cell"].get("ontology_id_world_ood", {}) for model, reports in bundle.items()})
    write_json("hard-sibling-density.json", {model: reports[10000][-1]["metrics"]["hard_sibling_rank_accuracy"] for model, reports in bundle.items()})
    write_json("gold-query-locality.json", {model: reports[10000][-1]["metrics"]["locality"] for model, reports in bundle.items()})
    ig_rows = read_jsonl(RUN / "ood" / "expected-information-gain.jsonl")
    write_json("expected-information-gain.json", {
        "record_count": len(ig_rows),
        "probability_normalization_max_error": max(abs(sum(item["probability"] for item in row["outcomes"]) - 1.0) for row in ig_rows),
        "negative_ig_count": sum(row["expected_information_gain"] < -1e-10 for row in ig_rows),
        "mean_ig": mean(row["expected_information_gain"] for row in ig_rows),
        "model_correspondence": "generator exact verification complete; model-side prospective outcome sweep is not claimed by this adapter",
    })
    write_json("binding-adversaries.json", {
        model: load_report(model, 10000, 20260921)["test"]["by_profile"]
        for model in MODELS
    })
    residual = {model: residual_audit(model, bundle[model], metadata) for model in MODELS}
    write_json("failure-overlap.json", {"status": "complete", "models": residual})
    complementarity: dict[str, Any] = {}
    for model, reports in bundle.items():
        terminal_rows = [annotate_rows(report, metadata) for report in reports[20000]]
        complementarity[model] = {
            "terminal_primary_seed_count": len(terminal_rows),
            "terminal_primary_case_counts": [len(rows) for rows in terminal_rows],
            "note": "success/failure complementarity is reported at the case-family level; no cross-backbone fusion is authorized",
        }
    write_json("representation-complementarity.json", complementarity)

    gate: dict[str, Any] = {
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "status": "EVALUATED_UNAUTHORIZED",
        "per_backbone": {},
        "cross_backbone_overlap_is_diagnostic_only": True,
    }
    for model in MODELS:
        sat = learning[model]["terminal_transition"]["gate_summary"]
        audit = residual[model]
        ood = audit["by_slice"]["true_ood"]
        larger_preserves = any(item["larger_preserves_residual_family"] for item in audit["by_slice"].values())
        oracle_preserves = any(item["oracle_preserves_residual_family"] for item in audit["by_slice"].values())
        ood_persists = ood["persistent_family_count"] > 0
        semantic_residual = len(audit["decisive_persistent_families"]) > 0
        readout_replication = larger_preserves or oracle_preserves
        gate_a = "PASS" if sat["primary_head_saturation"] else "FAIL"
        gate_b = "PASS" if larger_preserves else ("BLOCKED" if not semantic_residual else "FAIL")
        gate_c = "PASS" if oracle_preserves else ("BLOCKED" if not semantic_residual else "FAIL")
        gate_d = "PASS" if ood_persists else "FAIL"
        gate_e = "PASS" if semantic_residual and ood_persists else "FAIL"
        gate_f = "PASS" if semantic_residual and readout_replication else ("BLOCKED" if not semantic_residual else "FAIL")
        authorized = all(value == "PASS" for value in (gate_a, gate_b, gate_c, gate_d, gate_e, gate_f))
        gate["per_backbone"][model] = {
            "A_primary_head_saturation": gate_a,
            "B_capacity_saturation": gate_b,
            "C_representation_deficit_supported": gate_c,
            "D_true_ood_persistence": gate_d,
            "E_representation_level_character": gate_e,
            "F_replication": gate_f,
            "authorized": authorized,
            "residual_audit": audit,
            "reason": "Gate A uses the terminal 10k-to-20k rescue transition; Gates B-F use the declared larger-head, oracle, true-OOD, and replicated residual-family controls.",
        }
    write_json("qlora-final-gate.json", gate)
    write_json("final-frozen-behavior-map.json", {"contract": "jev-frozen-saturation-true-ood-gate/v0.4", "status": "analysis_complete_no_backbone_adaptation_authorized", "learning": learning, "gate": gate})
    print(json.dumps({model: learning[model]["terminal_transition"]["gate_summary"] for model in MODELS}, indent=2))


if __name__ == "__main__":
    main()
