"""Paired E4 five-head scoring after both fresh TEST predictions are sealed."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from common import TASKS, read_jsonl, sha256


ENDPOINTS = (
    "context_identity", "entity_identity", "relation", "observed_state",
    "exact_target_in_domain", "exact_target_context_novel",
    "exact_target_entity_novel", "exact_target_both_novel",
)
STRATA = {
    "exact_target_in_domain": "IN_DOMAIN",
    "exact_target_context_novel": "CONTEXT_NOVEL",
    "exact_target_entity_novel": "ENTITY_NOVEL",
    "exact_target_both_novel": "BOTH_NOVEL",
}


def verified_predictions(path: Path, expected_rows: int) -> tuple[dict, list[dict]]:
    seal = json.loads((path / "prediction-seal.json").read_text(encoding="utf-8"))
    pred_file = path / "predictions.jsonl"
    if seal["prediction_sha256"] != sha256(pred_file) or seal["rows"] != expected_rows:
        raise RuntimeError(f"prediction seal failed: {path}")
    if seal["truth_join_performed"] is not False or seal["partition"] != "TEST":
        raise RuntimeError("fresh TEST prediction was not sealed label-blind")
    predictions = list(read_jsonl(pred_file))
    if len(predictions) != expected_rows:
        raise RuntimeError("prediction row count mismatch")
    return seal, predictions


def summary(truth: np.ndarray, predicted: np.ndarray, classes: int) -> dict:
    support = np.bincount(truth, minlength=classes)
    correct = np.bincount(truth[truth == predicted], minlength=classes)
    return {
        "rows": int(len(truth)), "accuracy": float(np.mean(truth == predicted)),
        "balanced_accuracy": float(np.mean(correct / np.maximum(support, 1))),
        "class_support": support.tolist(), "class_correct": correct.tolist(),
        "class_recall": (correct / np.maximum(support, 1)).tolist(),
    }


def bootstrap_pair(truth: np.ndarray, a: np.ndarray, b: np.ndarray, quartet_ids: list[str],
                   strata: list[int], classes: int, seed: int, replicates: int) -> dict:
    qids = list(dict.fromkeys(quartet_ids))
    q_index = {q: i for i, q in enumerate(qids)}
    q_support = np.zeros((len(qids), classes), dtype=np.int64)
    q_a = np.zeros_like(q_support)
    q_b = np.zeros_like(q_support)
    q_stratum = np.full(len(qids), -1, dtype=np.int64)
    for i, (qid, cls, stratum) in enumerate(zip(quartet_ids, truth, strata)):
        qi = q_index[qid]
        if q_stratum[qi] >= 0 and q_stratum[qi] != stratum:
            raise RuntimeError("mixed bootstrap stratum in quartet")
        q_stratum[qi] = stratum
        q_support[qi, cls] += 1
        q_a[qi, cls] += int(a[i] == cls)
        q_b[qi, cls] += int(b[i] == cls)
    strata_indices = [np.flatnonzero(q_stratum == cls) for cls in range(classes)]
    if any(len(indices) == 0 for indices in strata_indices):
        raise RuntimeError("bootstrap lacks a class stratum")
    rng = np.random.Generator(np.random.PCG64(seed))
    values_a = np.empty(replicates, dtype=np.float64)
    values_b = np.empty(replicates, dtype=np.float64)
    for start in range(0, replicates, 64):
        batch = min(64, replicates - start)
        support = np.zeros((batch, classes), dtype=np.int64)
        correct_a = np.zeros_like(support)
        correct_b = np.zeros_like(support)
        for population in strata_indices:
            sampled = rng.choice(population, size=(batch, len(population)), replace=True)
            support += q_support[sampled].sum(axis=1)
            correct_a += q_a[sampled].sum(axis=1)
            correct_b += q_b[sampled].sum(axis=1)
        if np.any(support == 0):
            raise RuntimeError("bootstrap replicate omitted a scored truth class")
        values_a[start : start + batch] = (correct_a / support).mean(axis=1)
        values_b[start : start + batch] = (correct_b / support).mean(axis=1)
    delta = values_b - values_a
    return {
        "unit": "whole quartet, class-stratified by baseline A truth",
        "replicates": replicates, "seed": seed,
        "a_5th_percentile": float(np.quantile(values_a, 0.05, method="linear")),
        "b_5th_percentile": float(np.quantile(values_b, 0.05, method="linear")),
        "b_minus_a_5th_percentile": float(np.quantile(delta, 0.05, method="linear")),
        "b_minus_a_95th_percentile": float(np.quantile(delta, 0.95, method="linear")),
        "b_minus_a_mean": float(delta.mean()),
        "quartets": len(qids),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-inputs", type=Path, required=True)
    parser.add_argument("--test-labels", type=Path, required=True)
    parser.add_argument("--population-seal", type=Path, required=True)
    parser.add_argument("--a-predictions", type=Path, required=True)
    parser.add_argument("--b-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=10_000)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("score output already exists")
    seal = json.loads(args.population_seal.read_text(encoding="utf-8"))
    hashes = {row["path"]: row["sha256"] for row in seal["files"]}
    if sha256(args.test_inputs) != hashes["inputs.jsonl"] or sha256(args.test_labels) != hashes["labels-sealed.jsonl"]:
        raise RuntimeError("fresh population hashes differ from its pre-model seal")
    inputs = list(read_jsonl(args.test_inputs))
    if len(inputs) != seal["primary_rows"] or len(inputs) != 74_668:
        raise RuntimeError("fresh E4-shaped population row count differs")
    a_seal, a = verified_predictions(args.a_predictions, len(inputs))
    b_seal, b = verified_predictions(args.b_predictions, len(inputs))
    labels = list(read_jsonl(args.test_labels))
    for i, (inp, left, right, label) in enumerate(zip(inputs, a, b, labels)):
        if not all(r["row_id"] == inp["row_id"] and r["quartet_id"] == inp["quartet_id"]
                   and r["variant_id"] == inp["variant_id"] for r in (left, right, label)):
            raise RuntimeError(f"prediction/label identity mismatch at {i}")
    by_quartet: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in labels:
        by_quartet[row["quartet_id"]][row["variant_id"]] = row
    if len(by_quartet) != 18_667 or any(set(variants) != {"A", "C", "E", "P"} for variants in by_quartet.values()):
        raise RuntimeError("fresh TEST is not whole-quartet complete")
    metrics = {}
    for endpoint_index, endpoint in enumerate(ENDPOINTS):
        task = "exact_target" if endpoint in STRATA else endpoint
        field, classes = TASKS[task]
        selected = [i for i, row in enumerate(labels)
                    if (endpoint not in STRATA or row["score_strata"] == STRATA[endpoint])
                    and (task in ("context_identity", "entity_identity", "exact_target")
                         or row["both_terms_train_side"])]
        truth = np.asarray([labels[i][field] for i in selected], dtype=np.int64)
        left = np.asarray([a[i][task] for i in selected], dtype=np.int64)
        right = np.asarray([b[i][task] for i in selected], dtype=np.int64)
        qids = [labels[i]["quartet_id"] for i in selected]
        strata = [by_quartet[qid]["A"][field] for qid in qids]
        metrics[endpoint] = {
            "a": summary(truth, left, classes), "b": summary(truth, right, classes),
            "paired_bootstrap": bootstrap_pair(truth, left, right, qids, strata, classes,
                                               20260928 + endpoint_index, args.replicates),
        }
        print(json.dumps({"endpoint": endpoint,
                          "a_balanced": metrics[endpoint]["a"]["balanced_accuracy"],
                          "b_balanced": metrics[endpoint]["b"]["balanced_accuracy"]}), flush=True)
    eligible = [i for i, row in enumerate(labels) if row["both_terms_train_side"]]
    for name, preds in (("a", a), ("b", b)):
        route_correct = np.asarray([
            all(preds[i][task] == labels[i][field]
                for task, (field, _) in TASKS.items() if task != "exact_target")
            for i in eligible], dtype=bool)
        exact_correct = np.asarray([preds[i]["exact_target"] == labels[i]["exact_target"]
                                    for i in eligible], dtype=bool)
        metrics[f"integrated_{name}"] = {
            "eligible_rows": len(eligible),
            "route_accuracy_four_heads": float(route_correct.mean()),
            "end_to_end_all_five_heads": float(np.mean(route_correct & exact_correct)),
            "route_misroutes": int((~route_correct).sum()),
            "forced_head_abstentions": 0,
        }
    args.output.mkdir(parents=True)
    receipt = {
        "schema": "phoenix.e4-scale-paired-scoring/v1",
        "claim": "independent synthetic E4 capability comparison; no lexical transport or protected E4-0 scoring claim",
        "a_arm": a_seal["arm"], "b_arm": b_seal["arm"],
        "population_seal_sha256": sha256(args.population_seal),
        "a_prediction_seal_sha256": sha256(args.a_predictions / "prediction-seal.json"),
        "b_prediction_seal_sha256": sha256(args.b_predictions / "prediction-seal.json"),
        "test_labels_sha256": sha256(args.test_labels),
        "metrics": metrics,
    }
    (args.output / "paired-score.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
