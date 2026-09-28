"""Post-hoc paired analysis for the v0.8I frozen Phase-B intervention."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("S100", "F100")
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


def mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return sum(data) / len(data) if data else None


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm, rm = mean(left), mean(right)
    assert lm is not None and rm is not None
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right))
    return numerator / denominator if denominator else 0.0


def spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        result = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            rank = (start + end - 1) / 2.0
            for offset in range(start, end):
                result[order[offset]] = rank
            start = end
        return result

    return pearson(ranks(left), ranks(right))


def candidate_map(row: dict[str, Any], field: str) -> dict[str, float]:
    ids = row["candidate_semantic_ids"]
    values = row[field]
    if len(ids) != len(values) or len(set(ids)) != len(ids):
        raise ValueError(f"candidate alignment/identity error: {row.get('group_id')}")
    return {str(key): float(value) for key, value in zip(ids, values)}


def winner(values: dict[str, float]) -> str:
    return max(values, key=lambda key: (values[key], key))


def rank_of(values: dict[str, float], candidate: str) -> int:
    ordered = sorted(values, key=lambda key: (-values[key], key))
    return ordered.index(candidate) + 1


def summarize_fact_flip(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {"pair_count": 0}
    new_delta: list[float] = []
    gold_delta: list[float] = []
    margin_delta: list[float] = []
    gold_margin_delta: list[float] = []
    rank_gain: list[float] = []
    gold_rank_gain: list[float] = []
    direction: list[bool] = []
    strict_map = 0
    flip_map_new = 0
    anchor_map_old = 0
    for pair in pairs:
        anchor, child = pair["anchor"], pair["fact_flip"]
        old_id, new_id = pair["old_id"], pair["new_id"]
        pred_a, pred_c = candidate_map(anchor, "prediction"), candidate_map(child, "prediction")
        gold_a, gold_c = candidate_map(anchor, "gold"), candidate_map(child, "gold")
        if set(pred_a) != set(pred_c) or set(gold_a) != set(gold_c) or set(pred_a) != set(gold_a):
            raise ValueError(f"fact-flip candidate set changed: {pair['anchor_id']}")
        if old_id not in pred_a or new_id not in pred_a or old_id == new_id:
            raise ValueError(f"invalid certified old/new winners: {pair['anchor_id']}")
        dp = pred_c[new_id] - pred_a[new_id]
        dg = gold_c[new_id] - gold_a[new_id]
        dm = (pred_c[new_id] - pred_c[old_id]) - (pred_a[new_id] - pred_a[old_id])
        dgm = (gold_c[new_id] - gold_c[old_id]) - (gold_a[new_id] - gold_a[old_id])
        rg = rank_of(pred_a, new_id) - rank_of(pred_c, new_id)
        grg = rank_of(gold_a, new_id) - rank_of(gold_c, new_id)
        new_delta.append(dp)
        gold_delta.append(dg)
        margin_delta.append(dm)
        gold_margin_delta.append(dgm)
        rank_gain.append(float(rg))
        gold_rank_gain.append(float(grg))
        direction.append(dp * dg > 0.0 if abs(dg) > 1e-12 else abs(dp) <= 1e-12)
        anchor_map_old += int(winner(pred_a) == old_id)
        flip_map_new += int(winner(pred_c) == new_id)
        strict_map += int(winner(pred_a) == old_id and winner(pred_c) == new_id)

    count = len(pairs)
    return {
        "pair_count": count,
        "new_winner_probability_movement": {
            "mean_model_delta": mean(new_delta), "mean_exact_gold_delta": mean(gold_delta),
            "correct_direction_rate": sum(direction) / count,
            "pearson_model_vs_gold_delta": pearson(gold_delta, new_delta),
            "spearman_model_vs_gold_delta": spearman(gold_delta, new_delta),
            "mean_absolute_delta_error": mean(abs(a - b) for a, b in zip(new_delta, gold_delta)),
        },
        "map_response": {"strict_old_to_new_transition_rate": strict_map / count,
                         "anchor_map_is_certified_old_rate": anchor_map_old / count,
                         "fact_flip_map_is_certified_new_rate": flip_map_new / count},
        "rank_response": {"mean_predicted_new_winner_rank_gain": mean(rank_gain),
                          "mean_exact_gold_new_winner_rank_gain": mean(gold_rank_gain),
                          "rank_gain_direction_agreement": sum(
                              int((a > 0) == (b > 0)) for a, b in zip(rank_gain, gold_rank_gain)
                          ) / count},
        "old_new_margin": {"mean_model_margin_movement": mean(margin_delta),
                           "mean_exact_gold_margin_movement": mean(gold_margin_delta),
                           "mean_absolute_margin_delta_error": mean(
                               abs(a - b) for a, b in zip(margin_delta, gold_margin_delta)
                           )},
    }


def summarize_sham(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {"pair_count": 0}
    l1, gold_l1, flips, new_move, old_move, margin_move = [], [], 0, [], [], []
    for pair in pairs:
        anchor, sham = pair["anchor"], pair["sham"]
        old_id, new_id = pair["old_id"], pair["new_id"]
        pred_a, pred_s = candidate_map(anchor, "prediction"), candidate_map(sham, "prediction")
        gold_a, gold_s = candidate_map(anchor, "gold"), candidate_map(sham, "gold")
        if set(pred_a) != set(pred_s) or set(gold_a) != set(gold_s) or set(pred_a) != set(gold_a):
            raise ValueError(f"sham candidate set changed: {pair['anchor_id']}")
        l1.append(sum(abs(pred_a[key] - pred_s[key]) for key in pred_a))
        gold_l1.append(sum(abs(gold_a[key] - gold_s[key]) for key in gold_a))
        flips += int(winner(pred_a) != winner(pred_s))
        new_move.append(pred_s[new_id] - pred_a[new_id])
        old_move.append(pred_s[old_id] - pred_a[old_id])
        margin_move.append((pred_s[new_id] - pred_s[old_id]) - (pred_a[new_id] - pred_a[old_id]))
    count = len(pairs)
    return {"pair_count": count, "mean_prediction_distribution_l1": mean(l1),
            "mean_exact_gold_distribution_l1": mean(gold_l1),
            "map_flip_rate": flips / count,
            "mean_new_winner_probability_movement": mean(new_move),
            "mean_old_winner_probability_movement": mean(old_move),
            "mean_new_minus_old_margin_movement": mean(margin_move)}


def collect_triplets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    families: dict[str, str] = {}
    for row in rows:
        anchor_id = str(row["contrast_anchor_id"])
        role = str(row["contrast_role"])
        if role not in {"anchor", "fact_flip", "sham"} or role in grouped[anchor_id]:
            raise ValueError(f"invalid/duplicate triplet role for {anchor_id}: {role}")
        grouped[anchor_id][role] = row
        family = str(row["contrast_family_id"])
        if anchor_id in families and families[anchor_id] != family:
            raise ValueError(f"contrast family drift for {anchor_id}")
        families[anchor_id] = family
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for anchor_id, roles in grouped.items():
        if set(roles) != {"anchor", "fact_flip", "sham"}:
            raise ValueError(f"incomplete contrast triplet: {anchor_id}")
        old_ids = {str(row["expected_old_winner_id"]) for row in roles.values()}
        new_ids = {str(row["expected_new_winner_id"]) for row in roles.values()}
        if len(old_ids) != 1 or len(new_ids) != 1:
            raise ValueError(f"certified winners drift within triplet: {anchor_id}")
        by_family[families[anchor_id]].append({"anchor_id": anchor_id, **roles,
                                               "old_id": next(iter(old_ids)),
                                               "new_id": next(iter(new_ids))})
    return by_family


def analyze_triplets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    families = collect_triplets(rows)
    ordered = sorted(families)
    flattened = [pair for family in ordered for pair in families[family]]
    return {
        "pair_count": len(flattened), "group_count": len(rows),
        "family_counts": {family: len(families[family]) for family in ordered},
        "fact_flip": {
            "overall": summarize_fact_flip(flattened),
            "by_family": {family: summarize_fact_flip(families[family]) for family in ordered},
        },
        "sham_invariance": {
            "overall": summarize_sham(flattened),
            "by_family": {family: summarize_sham(families[family]) for family in ordered},
        },
        "dependence_note": "Triplet descendants are paired within anchor; family summaries are reported and rows are not treated as independent inferential replicates.",
    }


def view_vector(metrics: dict[str, Any]) -> dict[str, Any]:
    vector: dict[str, Any] = {}
    for view, values in metrics.get("by_view", {}).items():
        for key in ("accuracy", "nll", "brier", "posterior_l1", "ece_soft"):
            if key in values:
                vector[f"{view}.{key}"] = values[key]
        ordinal = values.get("ordinal")
        if isinstance(ordinal, dict):
            for key in ("exact_accuracy", "adjacent_accuracy", "expected_rank_spearman",
                        "ranked_probability_score_normalized"):
                if key in ordinal:
                    vector[f"{view}.{key}"] = ordinal[key]
    return vector


def capability_vector(epoch_record: dict[str, Any]) -> dict[str, Any]:
    direct = epoch_record["direct_contrast"]["analysis"]
    fact = direct["fact_flip"]["overall"]
    sham = direct["sham_invariance"]["overall"]
    binding = epoch_record["new_tight_schema_binding"]["name_definition_vs_opaque_definition"]
    return {
        "direct_fact_flip": {
            "correct_direction_rate": fact.get("new_winner_probability_movement", {}).get("correct_direction_rate"),
            "strict_map_transition_rate": fact.get("map_response", {}).get("strict_old_to_new_transition_rate"),
            "delta_correlation": fact.get("new_winner_probability_movement", {}).get("pearson_model_vs_gold_delta"),
            "delta_mae": fact.get("new_winner_probability_movement", {}).get("mean_absolute_delta_error"),
        },
        "direct_sham": {"mean_l1": sham.get("mean_prediction_distribution_l1"),
                        "map_flip_rate": sham.get("map_flip_rate")},
        "newtight_typed_views": view_vector(epoch_record["new_tight_eval"]),
        "schema_binding": binding,
        "world_intervention": epoch_record["new_tight_intervention_geometry"],
    }


def load_run(seed_index: int, arm: str) -> tuple[dict[str, Any], Path]:
    path = RUN / "runs" / f"seed-{seed_index + 1}" / arm / "run-report.json"
    if not path.is_file():
        raise FileNotFoundError(f"required completed run missing: {path}")
    report = read_json(path)
    if report.get("status") != "COMPLETE" or report.get("backbone_frozen") is not True:
        raise ValueError(f"run incomplete or backbone boundary failed: {path}")
    return report, path


def analyze_completed_runs() -> dict[str, Any]:
    runs: dict[tuple[int, str], dict[str, Any]] = {}
    predictions: dict[tuple[int, str, int], dict[str, Any]] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            report, report_path = load_run(seed_index, arm)
            runs[(seed_index, arm)] = report
            if report.get("seed") != seed or report.get("arm") != arm:
                raise ValueError(f"run identity mismatch: {report_path}")
            if len(report.get("history", [])) != 3:
                raise ValueError(f"run does not contain exactly three epoch snapshots: {report_path}")
            for epoch, record in enumerate(report["history"], 1):
                pred_path = Path(record["direct_contrast"]["prediction_path"])
                if sha256_file(pred_path) != record["direct_contrast"]["prediction_sha256"]:
                    raise ValueError(f"direct prediction hash mismatch: {pred_path}")
                rows = read_jsonl(pred_path)
                if len(rows) != 6_000:
                    raise ValueError(f"direct contrast row count mismatch: {pred_path}")
                predictions[(seed_index, arm, epoch)] = analyze_triplets(rows)
        if runs[(seed_index, "S100")]["initial_head_sha256"] != runs[(seed_index, "F100")]["initial_head_sha256"]:
            raise ValueError(f"paired head initialization differs for seed {seed_index + 1}")

    paired: dict[str, Any] = {}
    for seed_index, seed in enumerate(SEEDS):
        seed_report: dict[str, Any] = {}
        for epoch in range(1, 4):
            s = predictions[(seed_index, "S100", epoch)]
            f = predictions[(seed_index, "F100", epoch)]
            seed_report[f"epoch-{epoch}"] = {
                "S100": s, "F100": f,
                "descriptive_F_minus_S": {
                    "fact_flip_direction_rate": (
                        f["fact_flip"]["overall"]["new_winner_probability_movement"]["correct_direction_rate"]
                        - s["fact_flip"]["overall"]["new_winner_probability_movement"]["correct_direction_rate"]
                    ),
                    "strict_map_transition_rate": (
                        f["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"]
                        - s["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"]
                    ),
                    "sham_l1": (
                        f["sham_invariance"]["overall"]["mean_prediction_distribution_l1"]
                        - s["sham_invariance"]["overall"]["mean_prediction_distribution_l1"]
                    ),
                    "sham_map_flip_rate": (
                        f["sham_invariance"]["overall"]["map_flip_rate"]
                        - s["sham_invariance"]["overall"]["map_flip_rate"]
                    ),
                },
                "capability_vector": {
                    "S100": capability_vector(runs[(seed_index, "S100")]["history"][epoch - 1]),
                    "F100": capability_vector(runs[(seed_index, "F100")]["history"][epoch - 1]),
                },
            }
        paired[f"seed-{seed_index + 1}"] = seed_report

    per_seed_final = {}
    for seed_index in range(3):
        f = predictions[(seed_index, "F100", 3)]
        s = predictions[(seed_index, "S100", 3)]
        per_seed_final[f"seed-{seed_index + 1}"] = {
            "fact_flip_direction_rate_delta": f["fact_flip"]["overall"]["new_winner_probability_movement"]["correct_direction_rate"]
            - s["fact_flip"]["overall"]["new_winner_probability_movement"]["correct_direction_rate"],
            "strict_map_transition_rate_delta": f["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"]
            - s["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"],
            "sham_l1_delta": f["sham_invariance"]["overall"]["mean_prediction_distribution_l1"]
            - s["sham_invariance"]["overall"]["mean_prediction_distribution_l1"],
        }

    return {
        "protocol": "jev-information-density/v0.8i-phase-b-v01",
        "status": "POST_HOC_ANALYSIS_COMPLETE",
        "primary_surface": "held-out exact-world controlled contrast pairs",
        "runs": {f"seed-{i + 1}/{arm}": {
            "report_sha256": sha256_file(RUN / "runs" / f"seed-{i + 1}" / arm / "run-report.json"),
            "status": runs[(i, arm)]["status"], "seed": runs[(i, arm)]["seed"],
            "initial_head_sha256": runs[(i, arm)]["initial_head_sha256"],
        } for i in range(3) for arm in ARMS},
        "direct_contrast_by_seed_and_epoch": paired,
        "terminal_paired_seed_deltas_F_minus_S": per_seed_final,
        "terminal_generalization": {f"seed-{i + 1}/{arm}": {
            "newtight": runs[(i, arm)]["secondary_newtight_eval"],
            "legacy": runs[(i, arm)]["legacy_evaluation"],
            "schema_profiles": runs[(i, arm)]["schema_profiles_newtight"],
            "contradictory_binding": runs[(i, arm)]["contradictory_binding"],
        } for i in range(3) for arm in ARMS},
        "interpretation_guard": "Descriptive matched intervention only. No composite score, arbitrary win threshold, causal claim beyond the randomized controlled contrast, or follow-on authorization.",
        "phoenix_access": False,
    }


def main() -> int:
    reports = RUN / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    result = analyze_completed_runs()
    path = reports / "phase-b-direct-contrast-and-capability-vector.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(json.dumps({"status": result["status"], "report": str(path),
                      "runs": len(result["runs"]), "terminal_seed_pairs": 3}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
