"""Analyze frozen-head stress results without pooling probability meanings."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(r"D:\codex-runs\jev-semantic-stress-v03")
RUNS = ROOT / "runs"
BANK = ROOT / "bank" / "splits"
REPORTS = ROOT / "reports"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def entropy(values: Iterable[float]) -> float:
    return -sum(value * math.log(max(value, 1e-12)) for value in values if value > 0.0)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    assert mx is not None and my is not None
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return numerator / denominator if denominator > 1e-12 else 0.0


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        rank = (index + end - 1) / 2.0
        for position in range(index, end):
            result[order[position]] = rank
        index = end
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(ranks(xs), ranks(ys))


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    parts = row["group_id"].split("|")
    return parts[0], parts[1]


def target_id(stress: dict[str, Any], query_id: str) -> str | None:
    for query in stress.get("queries", []):
        if query["query_id"] == query_id:
            return query.get("target_semantic_id")
    return None


def query_stress(stress: dict[str, Any], query_id: str) -> dict[str, Any]:
    return next(query for query in stress.get("queries", []) if query["query_id"] == query_id)


def candidate_ids(episode: dict[str, Any], query_id: str) -> list[str]:
    query = next(query for query in episode["queries"] if query["query_id"] == query_id)
    set_id = query.get("candidate_set_id")
    if not set_id:
        return []
    candidate_set = next(item for item in episode["runtime_schema"]["candidate_sets"] if item["candidate_set_id"] == set_id)
    candidates = {item["candidate_id"]: item["candidate_semantic_id"] for item in episode["runtime_schema"]["candidates"]}
    return [candidates[item] for item in candidate_set["candidate_ids"]]


def score_row(row: dict[str, Any]) -> dict[str, float]:
    gold = [float(value) for value in row["gold"]]
    prediction = [float(value) for value in row["prediction"]]
    if row["kind"] == "independent":
        p, q = gold[0], min(max(prediction[0], 1e-12), 1.0 - 1e-12)
        return {
            "nll": -(p * math.log(q) + (1.0 - p) * math.log(1.0 - q)),
            "brier": (q - p) ** 2,
            "correct": float((q >= 0.5) == (p >= 0.5)),
            "gold_entropy": -(p * math.log(max(p, 1e-12)) + (1.0 - p) * math.log(max(1.0 - p, 1e-12))),
            "model_entropy": -(q * math.log(q) + (1.0 - q) * math.log(1.0 - q)),
        }
    nll = -sum(p * math.log(max(q, 1e-12)) for p, q in zip(gold, prediction))
    return {
        "nll": nll,
        "brier": sum((p - q) ** 2 for p, q in zip(gold, prediction)),
        "correct": float(max(range(len(gold)), key=gold.__getitem__) == max(range(len(prediction)), key=prediction.__getitem__)),
        "gold_entropy": entropy(gold),
        "model_entropy": entropy(prediction),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [score_row(row) for row in rows]
    if not metrics:
        return {"count": 0}
    return {
        "count": len(metrics),
        "nll": mean([item["nll"] for item in metrics]),
        "brier": mean([item["brier"] for item in metrics]),
        "accuracy": mean([item["correct"] for item in metrics]),
        "gold_entropy": mean([item["gold_entropy"] for item in metrics]),
        "model_entropy": mean([item["model_entropy"] for item in metrics]),
    }


def load_context() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    episodes = {}
    for path in [BANK / "train.jsonl", BANK / "dev.jsonl", BANK / "test.jsonl"]:
        for episode in read_jsonl(path):
            episodes[episode["identity"]["episode_id"]] = episode
    metadata = {}
    for path in [BANK / "train-metadata.jsonl", BANK / "dev-metadata.jsonl", BANK / "test-metadata.jsonl"]:
        for record in read_jsonl(path):
            metadata[record["episode_id"]] = record
    return episodes, metadata


def load_run(path: Path, episodes: dict[str, dict[str, Any]], metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = read_json(path)
    rows = []
    for row in report.get("test_rows", []):
        episode_id, query_id = row_key(row)
        row = dict(row)
        row["candidate_semantic_ids"] = candidate_ids(episodes[episode_id], query_id)
        row["stress"] = metadata[episode_id]
        row["target_semantic_id"] = target_id(row["stress"], query_id)
        rows.append(row)
    return {"name": report["model_name"], "report": report, "rows": rows}


def grouped(rows: list[dict[str, Any]], key_fn) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(key_fn(row))].append(row)
    return result


def rows_for_operation(run: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    return [row for row in run["rows"] if row["stress"]["operation"] == operation]


def paired_deltas(run: dict[str, Any], episodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {row["group_id"]: row for row in run["rows"]}
    by_episode_query = {(row_key(row)): row for row in run["rows"]}
    result = []
    for row in run["rows"]:
        stress = row["stress"]
        parent_id = stress.get("parent_episode_id")
        if not parent_id or stress["operation"] in {"base", "criterion_paraphrase", "representation_change", "full_ontology_branch", "all_local_candidates", "target_plus_one_sibling", "target_plus_two_siblings", "local_plus_unrelated_distractor"}:
            continue
        parent = by_episode_query.get((parent_id, row["query_id"]))
        if not parent:
            continue
        child_ids = row["candidate_semantic_ids"]
        parent_ids = parent["candidate_semantic_ids"]
        child_by_id = dict(zip(child_ids, row["prediction"]))
        parent_by_id = dict(zip(parent_ids, parent["prediction"]))
        child_gold = dict(zip(child_ids, row["gold"]))
        parent_gold = dict(zip(parent_ids, parent["gold"]))
        shared = sorted(set(child_by_id) & set(parent_by_id))
        model_delta = [child_by_id[item] - parent_by_id[item] for item in shared]
        gold_delta = [child_gold[item] - parent_gold[item] for item in shared]
        target = row.get("target_semantic_id")
        if target in child_by_id and target in parent_by_id:
            model_target_delta = child_by_id[target] - parent_by_id[target]
            gold_target_delta = child_gold[target] - parent_gold[target]
        else:
            model_target_delta = max((abs(value) for value in model_delta), default=0.0)
            gold_target_delta = max((abs(value) for value in gold_delta), default=0.0)
        result.append({
            "episode_id": row["episode_id"],
            "parent_episode_id": parent_id,
            "query_id": row["query_id"],
            "operation": stress["operation"],
            "model_delta": model_delta,
            "gold_delta": gold_delta,
            "model_target_delta": model_target_delta,
            "gold_target_delta": gold_target_delta,
            "gold_magnitude": abs(gold_target_delta),
            "model_magnitude": abs(model_target_delta),
            "candidate_cardinality": row["candidate_cardinality"],
        })
    return result


def derive_affected_query_ids(parent: dict[str, Any], child: dict[str, Any]) -> tuple[set[str], set[str]]:
    parent_latent = {item["variable"]: item.get("value_index") for item in (parent.get("state", {}).get("latent") or []) if isinstance(item, dict)}
    child_latent = {item["variable"]: item.get("value_index") for item in (child.get("state", {}).get("latent") or []) if isinstance(item, dict)}
    variables = {key for key in set(parent_latent) | set(child_latent) if parent_latent.get(key) != child_latent.get(key)}
    parent_visible = set(parent.get("state", {}).get("variables", {}).get("observed", []))
    child_visible = set(child.get("state", {}).get("variables", {}).get("observed", []))
    changed_evidence = parent_visible ^ child_visible
    for item in parent.get("evidence_items", []):
        if item["evidence_id"] in changed_evidence:
            variables.add(item["content"].split("=", 1)[0])
    affected = set()
    for query in child.get("queries", []):
        semantic = query.get("query_semantic_id", "")
        if any(semantic.endswith(variable) for variable in variables):
            affected.add(query["query_id"])
    all_queries = {query["query_id"] for query in child.get("queries", [])}
    return affected, all_queries - affected


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    episodes, metadata = load_context()
    run_paths = sorted(RUNS.glob("*-mlp-mean_full-LL3-N5000.json"))
    runs = [load_run(path, episodes, metadata) for path in run_paths]
    hard_sibling: dict[str, Any] = {}
    schema_ood: dict[str, Any] = {}
    opaque: dict[str, Any] = {}
    paraphrase: dict[str, Any] = {}
    intervention: dict[str, Any] = {}
    locality: dict[str, Any] = {}
    information: dict[str, Any] = {}
    behavior: dict[str, Any] = {}
    for run in runs:
        name = run["name"]
        rows = run["rows"]
        choices = [row for row in rows if row["kind"] == "choice"]
        hard_sibling[name] = {}
        for key, values in grouped(
            choices,
            lambda row: (
                f"{row['stress']['operation']}|D"
                f"{max(query_stress(row['stress'], row['query_id']).get('candidate_distances', {}).values(), default=0)}|"
                f"K{row['candidate_cardinality']}"
            ),
        ).items():
            hard_sibling[name][key] = summarize(values)
        schema_ood[name] = {}
        for key, values in grouped(rows, lambda row: row["stress"]["schema_regime"]).items():
            schema_ood[name][key] = summarize(values)
        opaque[name] = {
            "train_profile": run["report"].get("profile_trained"),
            "by_profile": run["report"].get("test", {}).get("by_profile", {}),
            "name_definition_to_opaque_definition_nll_delta": (
                run["report"].get("test", {}).get("by_profile", {}).get("opaque_definition", {}).get("exact_generative_posterior", {}).get("nll", 0.0)
                - run["report"].get("test", {}).get("by_profile", {}).get("name_definition", {}).get("exact_generative_posterior", {}).get("nll", 0.0)
            ),
        }
        para_rows = rows_for_operation(run, "criterion_paraphrase")
        paraphrase[name] = summarize(para_rows)
        deltas = paired_deltas(run, episodes)
        intervention[name] = {}
        for operation in sorted({item["operation"] for item in deltas}):
            values = [item for item in deltas if item["operation"] == operation]
            model_values = [item["model_target_delta"] for item in values]
            gold_values = [item["gold_target_delta"] for item in values]
            bins = {"tiny": [], "small": [], "medium": [], "large": []}
            for item in values:
                magnitude = item["gold_magnitude"]
                bucket = "tiny" if magnitude < 0.05 else "small" if magnitude < 0.15 else "medium" if magnitude < 0.35 else "large"
                bins[bucket].append(item)
            intervention[name][operation] = {
                "count": len(values),
                "sign_agreement": mean([float((m >= 0) == (g >= 0)) for m, g in zip(model_values, gold_values)]),
                "pearson": pearson(model_values, gold_values),
                "spearman": spearman(model_values, gold_values),
                "mean_absolute_delta_error": mean([abs(m - g) for m, g in zip(model_values, gold_values)]),
                "magnitude_calibration": pearson([abs(value) for value in model_values], [abs(value) for value in gold_values]),
                "by_gold_magnitude": {
                    bucket: {"count": len(bucket_values), "mae": mean([abs(item["model_target_delta"] - item["gold_target_delta"]) for item in bucket_values])}
                    for bucket, bucket_values in bins.items()
                },
            }
        world_deltas = [item for item in deltas if item["operation"] == "counterfactual_state_change"]
        affected_values, unaffected_values = [], []
        by_id = {(item["episode_id"], item["query_id"]): item for item in rows}
        for item in world_deltas:
            child = episodes[item["episode_id"]]
            parent = episodes[item["parent_episode_id"]]
            affected, unaffected = derive_affected_query_ids(parent, child)
            movement = abs(item["model_target_delta"])
            if item["query_id"] in affected:
                affected_values.append(movement)
            elif item["query_id"] in unaffected:
                unaffected_values.append(movement)
        locality[name] = {
            "world_intervention_pairs": len(world_deltas),
            "affected_query_count": len(affected_values),
            "unaffected_query_count": len(unaffected_values),
            "mean_affected_movement": mean(affected_values),
            "mean_unaffected_movement": mean(unaffected_values),
            "locality_ratio": (mean(affected_values) / (mean(unaffected_values) + 1e-9)) if affected_values and unaffected_values else None,
            "note": "affectedness is derived from changed latent/visible variables and query semantic IDs; it is diagnostic until generator-side affected_query_ids are promoted",
        }
        info_pairs = [item for item in deltas if item["operation"] == "supporting_evidence_removal"]
        gold_info, model_info = [], []
        for item in info_pairs:
            child_row = by_id.get((item["episode_id"], item["query_id"]))
            parent_row = by_id.get((item["parent_episode_id"], item["query_id"]))
            if not child_row or not parent_row:
                continue
            gold_info.append(score_row(parent_row)["gold_entropy"] - score_row(child_row)["gold_entropy"])
            model_info.append(score_row(parent_row)["model_entropy"] - score_row(child_row)["model_entropy"])
        information[name] = {
            "count": len(gold_info),
            "realized_entropy_change_parent_minus_child": {"mean": mean(gold_info), "min": min(gold_info) if gold_info else None, "max": max(gold_info) if gold_info else None},
            "model_uncertainty_change": {"mean": mean(model_info), "min": min(model_info) if model_info else None, "max": max(model_info) if model_info else None},
            "gold_model_information_correlation": pearson(gold_info, model_info),
        }
        behavior[name] = {
            "stress_test": summarize(rows),
            "hard_sibling_choice_rows": len(choices),
            "schema_regime_rows": {key: len(values) for key, values in grouped(rows, lambda row: row["stress"]["schema_regime"]).items()},
            "head_parameters": run["report"].get("trainable_parameters"),
            "backbone_frozen": run["report"].get("backbone_frozen"),
        }
    write("hard-sibling-curves.json", {"protocol": "v0.3", "models": hard_sibling})
    write("schema-ood.json", {"protocol": "v0.3", "models": schema_ood})
    write("opaque-definition-binding.json", {"protocol": "v0.3", "models": opaque})
    write("definition-paraphrase.json", {"protocol": "v0.3", "models": paraphrase})
    write("intervention-delta.json", {"protocol": "v0.3", "models": intervention})
    write("counterfactual-locality.json", {"protocol": "v0.3", "models": locality})
    write("information-value.json", {"protocol": "v0.3", "models": information})
    write("backbone-behavior-map.json", {"protocol": "v0.3", "models": behavior})
    write("analysis-manifest.json", {"models": [run["name"] for run in runs], "test_rows": {run["name"]: len(run["rows"]) for run in runs}, "coverage": "final-layer 459k/328k/459k heads trained on dense synthetic stress bank"})


def write(name: str, value: Any) -> None:
    (REPORTS / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
