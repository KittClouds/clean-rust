from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-PRED2"
IDENTITY = "q10-gc1-lr1-requal1-csc1-pred2-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PRED1 = ROOT.parent / "q10-gc1-lr1-requal1-csc1-pred1-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest().upper()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pred1_module() -> Any:
    path = PRED1 / "scripts" / "run_pred1.py"
    spec = importlib.util.spec_from_file_location("pred1_frozen", path)
    require(spec is not None and spec.loader is not None, "cannot load frozen PRED1 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_contract(allow_outputs: bool = False) -> dict[str, Any]:
    contract = load(ROOT / "CONTRACT.json")
    require(contract["identity"] == IDENTITY, "PRED2 contract identity mismatch")
    require(contract["status"] == "SEALED_PREMEASUREMENT", "PRED2 contract is not sealed")
    preexecution = load(ROOT / "PREEXECUTION.json")
    require(preexecution["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "PRED2 contract drift")
    if not allow_outputs:
        require(not (ROOT / "REPORT.json").exists(), "PRED2 report already exists")
        require(not (ROOT / "source-records.jsonl").exists(), "PRED2 source records already exist")
    require(not list(ROOT.rglob("__pycache__")), "unexpected bytecode tree")
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.is_file(), f"missing bound input: {binding['path']}")
        require(path.stat().st_size == int(binding["bytes"]), f"bound byte drift: {binding['path']}")
        require(digest(path) == binding["sha256"], f"bound hash drift: {binding['path']}")
    return contract


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def difficulty(k: int, n: int) -> str:
    if k == 0:
        return "NO_SUCCESS_OBSERVED"
    p = k / n
    if p <= 0.25:
        return "HARD"
    if p <= 0.75:
        return "MEDIUM"
    return "EASY"


def hypergeometric_hit(n: int, k: int, budget: int) -> float:
    if k == 0:
        return 0.0
    h = min(max(0, budget), n)
    if h == 0:
        return 0.0
    if h > n - k:
        return 1.0
    return 1.0 - (math.comb(n - k, h) / math.comb(n, h))


def quantiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "median": None, "mean": None, "min": None, "max": None}
    ordered = sorted(values)
    return {"count": len(values), "median": statistics.median(ordered), "mean": statistics.fmean(values), "min": ordered[0], "max": ordered[-1]}


def rank(observations: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    if metric == "full_alignment":
        return sorted(observations, key=lambda x: (-(x["full_alignment"] if x["full_alignment"] is not None else -float("inf")), x["tie"]))
    if metric == "axis_alignment":
        return sorted(observations, key=lambda x: (-(x["axis_alignment"] if x["axis_alignment"] is not None else -float("inf")), x["tie"]))
    if metric == "partner_magnitude":
        return sorted(observations, key=lambda x: (-x["partner_delta_norm"], x["tie"]))
    if metric == "partner_readout":
        return sorted(observations, key=lambda x: (x["partner_score_key"], x["tie"]))
    if metric == "deterministic_random":
        return sorted(observations, key=lambda x: (x["random_key"], x["tie"]))
    raise RuntimeError(metric)


METHODS = ("full_alignment", "axis_alignment", "partner_magnitude", "partner_readout", "deterministic_random")


def source_metrics(observations: list[dict[str, Any]], method: str) -> dict[str, Any]:
    n = len(observations)
    k = sum(bool(x["success"]) for x in observations)
    ordered = rank(observations, method)
    ranks = [i + 1 for i, x in enumerate(ordered) if x["success"]]
    first = min(ranks) if ranks else None
    stop_cost = first if first is not None else n
    return {
        "first_success_rank": first,
        "stop_cost": stop_cost,
        "saved_fraction": (n - stop_cost) / n if n else 0.0,
        "mrr": 1.0 / first if first is not None else 0.0,
        "hit_at_1": bool(first is not None and first <= 1),
        "hit_at_5": bool(first is not None and first <= min(5, n)),
        "hit_at_10": bool(first is not None and first <= min(10, n)),
        "normalized_success_area": (n - first + 1) / n if first is not None else 0.0,
        "true_recall_at_1": sum(bool(x["success"]) for x in ordered[:1]) / k if k else None,
        "true_recall_at_5": sum(bool(x["success"]) for x in ordered[:5]) / k if k else None,
        "true_recall_at_10": sum(bool(x["success"]) for x in ordered[:10]) / k if k else None,
    }


def aggregate(groups: dict[str, list[dict[str, Any]]], method: str) -> dict[str, Any]:
    rows = []
    for observations in groups.values():
        item = source_metrics(observations, method)
        item["n"] = len(observations)
        item["k"] = sum(bool(x["success"]) for x in observations)
        rows.append(item)
    first = [x["first_success_rank"] for x in rows if x["first_success_rank"] is not None]
    recalls = {name: [x[name] for x in rows if x[name] is not None] for name in ("true_recall_at_1", "true_recall_at_5", "true_recall_at_10")}
    return {
        "sources": len(rows),
        "candidates": sum(x["n"] for x in rows),
        "successes": sum(x["k"] for x in rows),
        "success_containing_sources": sum(x["k"] > 0 for x in rows),
        "no_success_sources": sum(x["k"] == 0 for x in rows),
        "size_one_sources": sum(x["n"] == 1 for x in rows),
        "first_success_rank_conditional": quantiles([float(x) for x in first]),
        "mean_stop_cost_all_sources": statistics.fmean(x["stop_cost"] for x in rows) if rows else None,
        "median_stop_cost_all_sources": statistics.median(x["stop_cost"] for x in rows) if rows else None,
        "mean_saved_fraction_all_sources": statistics.fmean(x["saved_fraction"] for x in rows) if rows else None,
        "mean_reciprocal_rank_all_sources": statistics.fmean(x["mrr"] for x in rows) if rows else None,
        "hit_at_1_all_sources": statistics.fmean(x["hit_at_1"] for x in rows) if rows else None,
        "hit_at_5_all_sources": statistics.fmean(x["hit_at_5"] for x in rows) if rows else None,
        "hit_at_10_all_sources": statistics.fmean(x["hit_at_10"] for x in rows) if rows else None,
        "normalized_success_area_all_sources": statistics.fmean(x["normalized_success_area"] for x in rows) if rows else None,
        "true_recall_at_1_conditional": statistics.fmean(recalls["true_recall_at_1"]) if recalls["true_recall_at_1"] else None,
        "true_recall_at_5_conditional": statistics.fmean(recalls["true_recall_at_5"]) if recalls["true_recall_at_5"] else None,
        "true_recall_at_10_conditional": statistics.fmean(recalls["true_recall_at_10"]) if recalls["true_recall_at_10"] else None,
        "analytic_random_first_rank_mean": statistics.fmean((x["n"] + 1) / (x["k"] + 1) if x["k"] else x["n"] for x in rows) if rows else None,
        "analytic_random_hit_at_1_mean": statistics.fmean(hypergeometric_hit(x["n"], x["k"], 1) for x in rows) if rows else None,
        "analytic_random_hit_at_5_mean": statistics.fmean(hypergeometric_hit(x["n"], x["k"], 5) for x in rows) if rows else None,
        "analytic_random_hit_at_10_mean": statistics.fmean(hypergeometric_hit(x["n"], x["k"], 10) for x in rows) if rows else None,
    }


def paired(groups: dict[str, list[dict[str, Any]]], left: str, right: str) -> dict[str, Any]:
    wins = ties = losses = 0
    differences = []
    for observations in groups.values():
        a = source_metrics(observations, left)["stop_cost"]
        b = source_metrics(observations, right)["stop_cost"]
        differences.append(b - a)
        if a < b:
            wins += 1
        elif a > b:
            losses += 1
        else:
            ties += 1
    return {"left": left, "right": right, "wins_lower_stop_cost": wins, "ties": ties, "losses": losses, "mean_right_minus_left_stop_cost": statistics.fmean(differences) if differences else None}


def build_groups(p1: Any) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    vmat = p1.VMAT
    domain = p1.DOMAIN
    ref = p1.load(p1.REF / "execution.json")
    v_scores = {(item["endpoint"], int(item["set_index"])): p1.score_key(item["best_valid"]["score"]) for item in ref["results"]}
    groups: dict[str, list[dict[str, Any]]] = {}
    contexts: dict[str, Any] = {}
    for key in p1.PAIR_KEYS:
        context_slug = p1.slug(key)
        records = [json.loads(line) for line in (vmat / "shards" / f"{context_slug}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        domain_rows = p1.load(domain / "shards" / f"{context_slug}.jsonl")
        require(len(records) == len(domain_rows), f"domain/VMAT row mismatch: {context_slug}")
        index = {row["state_ref"]: row for row in (json.loads(line) for line in (vmat / "sidecars" / context_slug / "state-index.jsonl").read_text(encoding="utf-8").splitlines() if line)}
        side = p1.Sidecar(vmat / "sidecars" / context_slug)
        added = 0
        try:
            for record, domain_row in zip(records, domain_rows):
                for source_role, partner_role, source_field, partner_field in (("A", "B", "a", "b"), ("B", "A", "b", "a")):
                    if not p1.split_is_test(key, int(record["pair_index"]), source_role):
                        continue
                    if bool(record["final_geometry_pass"][source_role]) or p1.score_key(record["scores"][source_role]) >= v_scores[key]:
                        continue
                    source = side.read(index[record["state_refs"][source_role]])
                    partner = side.read(index[record["state_refs"][partner_role]])
                    baseline = side.read(index[record["state_refs"]["S"]])
                    delta = tuple(x - y for x, y in zip(partner, baseline))
                    source_deficit = p1.deficit(source)
                    token = f"{key[0]}|{key[1]}|{record['pair_index']}|{source_role}|{domain_row[source_field]['group']}|{domain_row[source_field]['to']}|{domain_row[partner_field]['group']}|{domain_row[partner_field]['to']}".encode("utf-8")
                    source_id = f"{source_role}:{domain_row[source_field]['group']}:{domain_row[source_field]['to']}"
                    axis_alignment = None if delta[0] == 0.0 or source_deficit[0] == 0.0 else (delta[0] * source_deficit[0]) / (abs(delta[0]) * abs(source_deficit[0]))
                    observation = {
                        "success": record["outcome"] == "VALID_ADVANTAGE_PRESERVED",
                        "full_alignment": p1.cosine(delta, source_deficit),
                        "axis_alignment": axis_alignment,
                        "partner_delta_norm": p1.norm(delta),
                        "partner_score_key": p1.score_key(record["scores"][partner_role]),
                        "random_key": hashlib.sha256(token).hexdigest(),
                        "tie": (int(record["pair_index"]), partner_role),
                        "context": context_slug,
                        "pair_index": int(record["pair_index"]),
                        "source_role": source_role,
                    }
                    groups.setdefault(f"{context_slug}|{source_id}", []).append(observation)
                    added += 1
        finally:
            side.close()
        contexts[context_slug] = {"pair_records": len(records), "observations": added}
    return groups, contexts


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    report: dict[str, Any] = {"protocol": PROTOCOL, "identity": IDENTITY, "replay_performed": False, "scientific_promotion": False}
    try:
        contract = verify_contract()
        p1 = load_pred1_module()
        groups, contexts = build_groups(p1)
        pred1_report = load(PRED1 / "REPORT.json")
        require(pred1_report["status"] == "CSC1_PRED1_COMPLETE", "PRED1 status mismatch")
        eligible = {key: value for key, value in groups.items() if len(value) >= 2 and any(item["success"] for item in value)}
        reconciliation = {}
        for method in METHODS:
            actual = p1.ranking_metrics(eligible, method)
            expected = pred1_report["metrics"][method]
            require(actual == expected, f"PRED1 metric mismatch for {method}")
            reconciliation[method] = "EXACT"
        populations = {"all_observed_sources": groups, "size_at_least_two": {k: v for k, v in groups.items() if len(v) >= 2}, "pred1_eligible": eligible}
        bins = {name: {k: v for k, v in groups.items() if (difficulty(sum(x["success"] for x in v), len(v)) == name)} for name in ("NO_SUCCESS_OBSERVED", "HARD", "MEDIUM", "EASY")}
        metrics = {population: {method: {"aggregate": aggregate(pool, method)} for method in METHODS} for population, pool in populations.items()}
        metrics["difficulty_bins"] = {name: {method: {"aggregate": aggregate(pool, method)} for method in METHODS} for name, pool in bins.items()}
        metrics["contexts"] = {context: {method: {"aggregate": aggregate({k: v for k, v in groups.items() if k.startswith(context + "|")}, method)} for method in METHODS} for context in contexts}
        pairs = {"all_observed_sources": {}, "size_at_least_two": {}, "pred1_eligible": {}, "difficulty_bins": {}, "contexts": {}}
        for population, pool in populations.items():
            pairs[population] = {f"{method}_vs_{baseline}": paired(pool, method, baseline) for method in ("full_alignment", "axis_alignment", "partner_magnitude") for baseline in ("deterministic_random", "partner_readout")}
        for name, pool in bins.items():
            pairs["difficulty_bins"][name] = {f"{method}_vs_{baseline}": paired(pool, method, baseline) for method in ("full_alignment", "axis_alignment", "partner_magnitude") for baseline in ("deterministic_random", "partner_readout")}
        for context in contexts:
            pool = {k: v for k, v in groups.items() if k.startswith(context + "|")}
            pairs["contexts"][context] = {f"{method}_vs_{baseline}": paired(pool, method, baseline) for method in ("full_alignment", "axis_alignment", "partner_magnitude") for baseline in ("deterministic_random", "partner_readout")}
        records = []
        for source_key, observations in sorted(groups.items()):
            n = len(observations)
            k = sum(bool(x["success"]) for x in observations)
            row = {"source_key": source_key, "context": observations[0]["context"], "n": n, "k": k, "success_density": k / n, "difficulty": difficulty(k, n), "methods": {method: source_metrics(observations, method) for method in METHODS}}
            records.append(row)
        report.update({"status": "CSC1_PRED2_COMPLETE", "analysis_scope": "retrospective difficulty stratification of PRED1 observed geometry-screened pools", "parents": {"pred1_report_sha256": digest(PRED1 / "REPORT.json"), "pred1_contract_sha256": digest(PRED1 / "CONTRACT.json")}, "reconciliation": {"pools": len(groups), "pred1_eligible_pools": len(eligible), "heldout_observations": sum(len(x) for x in groups.values()), "pred1_metrics": reconciliation}, "context_counts": contexts, "method_order": METHODS, "metrics": metrics, "paired_comparisons": pairs, "interpretation_limits": ["all retained pair opportunities passed geometry screening before replay", "zero-success means none observed in this held-out pool, not in-domain impossibility", "source pools include directed A/B roles and may share actions", "no new replay was performed", "partner_readout is a prespecified singleton-measurement baseline"], "replay_performed": False, "scientific_promotion": False})
        write_jsonl(ROOT / "source-records.jsonl", records)
        with (ROOT / "REPORT.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        require(verify_contract(allow_outputs=True)["identity"] == IDENTITY, "post-analysis input verification failed")
        return 0
    except Exception as exc:
        report.update({"status": "CSC1_PRED2_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)})
        if not (ROOT / "REPORT.json").exists():
            with (ROOT / "REPORT.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
