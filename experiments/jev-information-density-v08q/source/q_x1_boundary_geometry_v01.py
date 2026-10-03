#!/usr/bin/env python3
"""Exploratory boundary-margin diagnostics over sealed JEV Q predictions.

This reader never loads a model and never edits Q's sealed outputs. It writes
only to a new Q-X1 output directory. Margins are probability-space old/new
pairwise margins because logits are not present in the sealed prediction file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_PREDICTION_SHA256 = (
    "d4bc4fce5fd1c51815ac214b794e3b5d5c51f549d80ad7e1362ec5c04abc976e"
)
EXPECTED_ANALYSIS_SHA256 = (
    "403994de956e96c7ff2809fc8c255f9cd3fdadfcc0b270eb3b5a30306e38901e"
)
EXPECTED_SEEDS = (2540205348, 2603246505, 3565067208)
EXPECTED_ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
EXPECTED_FAMILIES = (
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
)
EXPECTED_VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
EXPECTED_TOTAL_ROWS = 408_000
EXPECTED_STEP120_ROWS = 96_000
EXPECTED_NEIGHBORHOODS_PER_CELL = 2_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def family_name(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def linear_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile of empty data")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("empty distribution")
    return {
        "mean": math.fsum(values) / len(values),
        "median": linear_quantile(values, 0.50),
        "p05": linear_quantile(values, 0.05),
        "p95": linear_quantile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def prediction_map(row: dict[str, Any]) -> tuple[dict[str, float], str, float]:
    identities = row["candidate_semantic_ids"]
    probabilities = row["prediction"]
    if len(identities) != 4 or len(set(identities)) != 4:
        raise ValueError("candidate identity vector is not four unique IDs")
    if len(probabilities) != 4:
        raise ValueError("prediction vector is not length four")
    values = [float(value) for value in probabilities]
    if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values):
        raise ValueError("prediction contains invalid probability")
    if abs(math.fsum(values) - 1.0) > 1e-5:
        raise ValueError("prediction probabilities do not sum to one")
    mapped = dict(zip(identities, values, strict=True))
    ranking = sorted(values, reverse=True)
    winner = identities[values.index(ranking[0])]
    top_two_gap = ranking[0] - ranking[1]
    return mapped, winner, top_two_gap


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    a_old = sum(record["anchor_old_winner"] for record in records)
    f_new = sum(record["fact_new_winner"] for record in records)
    cells = {
        "A_old_AND_F_new": 0,
        "A_old_AND_NOT_F_new": 0,
        "NOT_A_old_AND_F_new": 0,
        "NOT_A_old_AND_NOT_F_new": 0,
    }
    for record in records:
        if record["anchor_old_winner"] and record["fact_new_winner"]:
            cells["A_old_AND_F_new"] += 1
        elif record["anchor_old_winner"]:
            cells["A_old_AND_NOT_F_new"] += 1
        elif record["fact_new_winner"]:
            cells["NOT_A_old_AND_F_new"] += 1
        else:
            cells["NOT_A_old_AND_NOT_F_new"] += 1
    return {
        "n": n,
        "anchor_old_winner_rate": a_old / n,
        "fact_new_winner_rate": f_new / n,
        "strict_transition_rate": sum(
            record["anchor_old_winner"] and record["fact_new_winner"]
            for record in records
        ) / n,
        "pairwise_margin_anchor_new_minus_old": distribution(
            [record["margin_anchor"] for record in records]
        ),
        "pairwise_margin_fact_new_minus_old": distribution(
            [record["margin_fact"] for record in records]
        ),
        "fact_minus_anchor_pairwise_margin": distribution(
            [record["margin_fact"] - record["margin_anchor"] for record in records]
        ),
        "new_candidate_probability_fact_minus_anchor": distribution(
            [record["delta_p_new"] for record in records]
        ),
        "old_candidate_probability_fact_minus_anchor": distribution(
            [record["delta_p_old"] for record in records]
        ),
        "anchor_top_two_probability_gap": distribution(
            [record["anchor_top_two_gap"] for record in records]
        ),
        "fact_top_two_probability_gap": distribution(
            [record["fact_top_two_gap"] for record in records]
        ),
        "sham_l1": distribution([record["sham_l1"] for record in records]),
        "matched_neutral_l1": distribution(
            [record["matched_l1"] for record in records]
        ),
        "four_cell_A_F": {
            key: {"count": count, "rate": count / n}
            for key, count in cells.items()
        },
        "pairwise_margin_nonnegative_rate_anchor": sum(
            record["margin_anchor"] >= 0.0 for record in records
        ) / n,
        "pairwise_margin_nonnegative_rate_fact": sum(
            record["margin_fact"] >= 0.0 for record in records
        ) / n,
        "pairwise_vs_multiclass_fact_disagreement": {
            "margin_nonnegative_but_new_not_map": sum(
                record["margin_fact"] >= 0.0 and not record["fact_new_winner"]
                for record in records
            ),
            "new_is_map_but_pairwise_margin_negative": sum(
                record["margin_fact"] < 0.0 and record["fact_new_winner"]
                for record in records
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--frozen-analysis", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()

    if args.outdir.exists() and any(args.outdir.iterdir()):
        raise SystemExit(f"refusing non-empty output directory: {args.outdir}")
    args.outdir.mkdir(parents=True, exist_ok=True)

    analysis_sha = sha256_file(args.frozen_analysis)
    if analysis_sha != EXPECTED_ANALYSIS_SHA256:
        raise SystemExit(f"frozen analysis hash mismatch: {analysis_sha}")
    frozen = json.loads(args.frozen_analysis.read_text(encoding="utf-8"))
    if frozen.get("prediction_sha256") != EXPECTED_PREDICTION_SHA256:
        raise SystemExit("frozen analysis does not bind expected prediction hash")

    cells: dict[tuple[int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    prediction_hash = hashlib.sha256()
    total_rows = 0
    step120_rows = 0
    with args.predictions.open("rb") as source:
        for raw_line in source:
            prediction_hash.update(raw_line)
            total_rows += 1
            row = json.loads(raw_line)
            if row.get("global_step") != 120:
                continue
            step120_rows += 1
            seed = int(row["seed"])
            arm = str(row["arm"])
            if seed not in EXPECTED_SEEDS or arm not in EXPECTED_ARMS:
                raise ValueError(f"unexpected step-120 cell: {seed}/{arm}")
            view = str(row["view"])
            if view not in EXPECTED_VIEWS:
                raise ValueError(f"unexpected step-120 view: {view}")
            neighborhood = str(row["neighborhood_id"])
            key = (seed, arm)
            bucket = cells[key].setdefault(neighborhood, {
                "family": family_name(str(row["family_id"])),
                "views": {},
                "old_id": str(row["old_candidate_id"]),
                "new_id": str(row["new_candidate_id"]),
                "candidate_ids": tuple(row["candidate_semantic_ids"]),
            })
            if bucket["family"] != family_name(str(row["family_id"])):
                raise ValueError("family identity changes within neighborhood")
            if bucket["old_id"] != str(row["old_candidate_id"]):
                raise ValueError("old candidate identity changes within neighborhood")
            if bucket["new_id"] != str(row["new_candidate_id"]):
                raise ValueError("new candidate identity changes within neighborhood")
            if set(bucket["candidate_ids"]) != set(row["candidate_semantic_ids"]):
                raise ValueError("candidate semantic set changes across neighborhood views")
            if view in bucket["views"]:
                raise ValueError(f"duplicate view {view} for {seed}/{arm}/{neighborhood}")
            probabilities, winner, top_two_gap = prediction_map(row)
            if bucket["old_id"] not in probabilities or bucket["new_id"] not in probabilities:
                raise ValueError("old/new semantic IDs absent from candidate vector")
            bucket["views"][view] = {
                "probabilities": probabilities,
                "winner": winner,
                "top_two_gap": top_two_gap,
            }

    observed_sha = prediction_hash.hexdigest()
    if observed_sha != EXPECTED_PREDICTION_SHA256:
        raise SystemExit(f"raw prediction hash mismatch: {observed_sha}")
    if total_rows != EXPECTED_TOTAL_ROWS or step120_rows != EXPECTED_STEP120_ROWS:
        raise SystemExit(
            f"row-count mismatch: total={total_rows}, step120={step120_rows}"
        )

    records: list[dict[str, Any]] = []
    for seed in EXPECTED_SEEDS:
        for arm in EXPECTED_ARMS:
            neighborhoods = cells[(seed, arm)]
            if len(neighborhoods) != EXPECTED_NEIGHBORHOODS_PER_CELL:
                raise ValueError(f"wrong neighborhood count for {seed}/{arm}")
            family_counts: dict[str, int] = defaultdict(int)
            for neighborhood, item in neighborhoods.items():
                family_counts[item["family"]] += 1
                if set(item["views"]) != set(EXPECTED_VIEWS):
                    raise ValueError(f"incomplete views for {seed}/{arm}/{neighborhood}")
                a = item["views"]["anchor"]
                f = item["views"]["fact_flip"]
                s = item["views"]["sham"]
                m = item["views"]["matched_neutral"]
                old_id, new_id = item["old_id"], item["new_id"]
                pa, pf = a["probabilities"], f["probabilities"]
                margin_a = pa[new_id] - pa[old_id]
                margin_f = pf[new_id] - pf[old_id]
                delta_p_new = pf[new_id] - pa[new_id]
                delta_p_old = pf[old_id] - pa[old_id]
                record = {
                    "seed": seed,
                    "arm": arm,
                    "family": item["family"],
                    "neighborhood_id": neighborhood,
                    "old_candidate_id": old_id,
                    "new_candidate_id": new_id,
                    "margin_anchor": margin_a,
                    "margin_fact": margin_f,
                    "margin_fact_minus_anchor": margin_f - margin_a,
                    "delta_p_new": delta_p_new,
                    "delta_p_old": delta_p_old,
                    "anchor_top_two_gap": a["top_two_gap"],
                    "fact_top_two_gap": f["top_two_gap"],
                    "anchor_winner_id": a["winner"],
                    "fact_winner_id": f["winner"],
                    "anchor_old_winner": a["winner"] == old_id,
                    "fact_new_winner": f["winner"] == new_id,
                    "sham_l1": math.fsum(
                        abs(pa[candidate] - s["probabilities"][candidate])
                        for candidate in pa
                    ),
                    "matched_l1": math.fsum(
                        abs(pa[candidate] - m["probabilities"][candidate])
                        for candidate in pa
                    ),
                }
                records.append(record)
            if dict(family_counts) != {family: 500 for family in EXPECTED_FAMILIES}:
                raise ValueError(f"family allocation mismatch for {seed}/{arm}: {dict(family_counts)}")

    by_cell: dict[str, Any] = {}
    by_family: dict[str, Any] = {}
    record_groups: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        record_groups[(record["seed"], record["arm"], record["family"])].append(record)
    for seed in EXPECTED_SEEDS:
        for arm in EXPECTED_ARMS:
            selected = [r for r in records if r["seed"] == seed and r["arm"] == arm]
            cell_summary = summarize(selected)
            by_cell[f"{seed}/{arm}"] = cell_summary
            frozen_summary = frozen["response_summaries"][f"{seed}/{arm}/120"]["overall"]
            parity_checks = {
                "fact_new_map": cell_summary["fact_new_winner_rate"],
                "anchor_old_map": cell_summary["anchor_old_winner_rate"],
                "sham_l1": cell_summary["sham_l1"]["mean"],
                "matched_l1": cell_summary["matched_neutral_l1"]["mean"],
                "new_probability_delta": cell_summary[
                    "new_candidate_probability_fact_minus_anchor"
                ]["mean"],
            }
            for metric, observed in parity_checks.items():
                if abs(observed - float(frozen_summary[metric])) > 1e-6:
                    raise ValueError(
                        f"sealed metric parity failed for {seed}/{arm}/{metric}: "
                        f"{observed} != {frozen_summary[metric]}"
                    )
            for family in EXPECTED_FAMILIES:
                by_family[f"{seed}/{arm}/{family}"] = summarize(
                    record_groups[(seed, arm, family)]
                )

    paired: dict[str, Any] = {}
    crossing_strata: dict[str, Any] = {}
    indexed = {(r["seed"], r["arm"], r["neighborhood_id"]): r for r in records}
    for seed in EXPECTED_SEEDS:
        for family in EXPECTED_FAMILIES:
            low_records = [
                r for r in records
                if r["seed"] == seed and r["arm"] == "B-SHAM-LOW" and r["family"] == family
            ]
            sham_records = [
                r for r in records
                if r["seed"] == seed and r["arm"] == "B-SHAM" and r["family"] == family
            ]
            delta_anchor: list[float] = []
            delta_fact: list[float] = []
            delta_fact_response: list[float] = []
            delta_new_probability_movement: list[float] = []
            delta_old_probability_movement: list[float] = []
            crossed_low_anchor_margins: list[float] = []
            uncrossed_low_anchor_margins: list[float] = []
            crossed_low_fact_response: list[float] = []
            uncrossed_low_fact_response: list[float] = []
            crossed_low_abs_anchor_margin: list[float] = []
            uncrossed_low_abs_anchor_margin: list[float] = []
            crossed_baseline_margins: list[float] = []
            uncrossed_baseline_margins: list[float] = []
            crossed_low_margins: list[float] = []
            uncrossed_low_margins: list[float] = []
            crossed_sham_l1: list[float] = []
            uncrossed_sham_l1: list[float] = []
            crossed_low_sham_l1: list[float] = []
            uncrossed_low_sham_l1: list[float] = []
            crossed_low_matched_l1: list[float] = []
            uncrossed_low_matched_l1: list[float] = []
            for low in low_records:
                sham = indexed[(seed, "B-SHAM", low["neighborhood_id"])]
                delta_anchor.append(low["margin_anchor"] - sham["margin_anchor"])
                delta_fact.append(low["margin_fact"] - sham["margin_fact"])
                delta_fact_response.append(
                    low["margin_fact_minus_anchor"] - sham["margin_fact_minus_anchor"]
                )
                delta_new_probability_movement.append(low["delta_p_new"] - sham["delta_p_new"])
                delta_old_probability_movement.append(low["delta_p_old"] - sham["delta_p_old"])
                destination = crossed_baseline_margins if low["fact_new_winner"] else uncrossed_baseline_margins
                destination.append(sham["margin_fact"])
                (crossed_low_margins if low["fact_new_winner"] else uncrossed_low_margins).append(
                    low["margin_fact"]
                )
                (crossed_low_anchor_margins if low["fact_new_winner"] else uncrossed_low_anchor_margins).append(
                    low["margin_anchor"]
                )
                (crossed_low_fact_response if low["fact_new_winner"] else uncrossed_low_fact_response).append(
                    low["margin_fact_minus_anchor"]
                )
                (crossed_low_abs_anchor_margin if low["fact_new_winner"] else uncrossed_low_abs_anchor_margin).append(
                    abs(low["margin_anchor"])
                )
                (crossed_sham_l1 if low["fact_new_winner"] else uncrossed_sham_l1).append(
                    sham["sham_l1"]
                )
                (crossed_low_sham_l1 if low["fact_new_winner"] else uncrossed_low_sham_l1).append(
                    low["sham_l1"]
                )
                (crossed_low_matched_l1 if low["fact_new_winner"] else uncrossed_low_matched_l1).append(
                    low["matched_l1"]
                )
            label = f"{seed}/{family}"
            paired[label] = {
                "n": len(low_records),
                "low_fact_new_winner_rate": sum(r["fact_new_winner"] for r in low_records) / len(low_records),
                "sham_minus_low_margin_effects": {
                    "low_minus_sham_anchor_margin": distribution(delta_anchor),
                    "low_minus_sham_fact_margin": distribution(delta_fact),
                    "low_minus_sham_fact_response_margin": distribution(delta_fact_response),
                    "low_minus_sham_new_candidate_probability_movement": distribution(delta_new_probability_movement),
                    "low_minus_sham_old_candidate_probability_movement": distribution(delta_old_probability_movement),
                },
            }
            crossing_strata[label] = {
                "crossed_n": len(crossed_low_margins),
                "not_crossed_n": len(uncrossed_low_margins),
                "sham_trained_fact_margin_before_low_treatment_by_low_crossing": {
                    "crossed": distribution(crossed_baseline_margins) if crossed_baseline_margins else None,
                    "not_crossed": distribution(uncrossed_baseline_margins) if uncrossed_baseline_margins else None,
                },
                "sham_low_fact_margin_by_actual_multiclass_crossing": {
                    "crossed": distribution(crossed_low_margins) if crossed_low_margins else None,
                    "not_crossed": distribution(uncrossed_low_margins) if uncrossed_low_margins else None,
                },
                "sham_low_anchor_margin_before_fact_view_by_actual_crossing": {
                    "crossed": distribution(crossed_low_anchor_margins) if crossed_low_anchor_margins else None,
                    "not_crossed": distribution(uncrossed_low_anchor_margins) if uncrossed_low_anchor_margins else None,
                },
                "sham_low_fact_minus_anchor_margin_response_by_actual_crossing": {
                    "crossed": distribution(crossed_low_fact_response) if crossed_low_fact_response else None,
                    "not_crossed": distribution(uncrossed_low_fact_response) if uncrossed_low_fact_response else None,
                },
                "absolute_sham_low_anchor_pairwise_margin_by_actual_crossing": {
                    "crossed": distribution(crossed_low_abs_anchor_margin) if crossed_low_abs_anchor_margin else None,
                    "not_crossed": distribution(uncrossed_low_abs_anchor_margin) if uncrossed_low_abs_anchor_margin else None,
                },
                "sham_locality_by_low_crossing": {
                    "SHAM_arm": {
                        "crossed": distribution(crossed_sham_l1) if crossed_sham_l1 else None,
                        "not_crossed": distribution(uncrossed_sham_l1) if uncrossed_sham_l1 else None,
                    },
                    "SHAM_LOW_arm": {
                        "crossed": distribution(crossed_low_sham_l1) if crossed_low_sham_l1 else None,
                        "not_crossed": distribution(uncrossed_low_sham_l1) if uncrossed_low_sham_l1 else None,
                    },
                },
                "matched_locality_SHAM_LOW_by_low_crossing": {
                    "crossed": distribution(crossed_low_matched_l1) if crossed_low_matched_l1 else None,
                    "not_crossed": distribution(uncrossed_low_matched_l1) if uncrossed_low_matched_l1 else None,
                },
            }

    summary = {
        "identity": "JEV-Q-X1-BOUNDARY-GEOMETRY-DIAGNOSTIC-V01",
        "disposition": "EXPLORATORY_READ_ONLY_DIAGNOSTIC",
        "input_prediction_sha256": observed_sha,
        "input_frozen_analysis_sha256": analysis_sha,
        "source_prediction_rows": total_rows,
        "step120_prediction_rows": step120_rows,
        "step120_neighborhood_rows": len(records),
        "seeds": list(EXPECTED_SEEDS),
        "arms": list(EXPECTED_ARMS),
        "families": list(EXPECTED_FAMILIES),
        "definitions": {
            "margin": "P(new_candidate)-P(old_candidate), using exact semantic IDs and stored probabilities",
            "actual_fact_crossing": "argmax of the four-candidate fact_flip prediction equals new_candidate_id",
            "anchor_preservation": "argmax of the four-candidate anchor prediction equals old_candidate_id",
            "top_two_gap": "largest minus second-largest predicted candidate probability",
            "logits_available": False,
            "interpretation_limit": "Pairwise probability margin is not the multiclass logit margin or full decision-boundary distance; third/fourth candidates can win.",
            "quantiles": "linear interpolation at p05, median, and p95",
            "no_model_contact": True,
            "registered_q_labels_modified": False,
        },
        "by_seed_arm": by_cell,
        "by_seed_arm_family": by_family,
        "paired_SHAM_LOW_minus_SHAM": paired,
        "baseline_SHAM_margin_and_locality_stratified_by_SHAM_LOW_fact_crossing": crossing_strata,
    }

    csv_path = args.outdir / "q-x1-step120-neighborhood-margins-v01.csv"
    fields = [
        "seed", "arm", "family", "neighborhood_id", "old_candidate_id", "new_candidate_id",
        "margin_anchor", "margin_fact", "margin_fact_minus_anchor", "anchor_top_two_gap",
        "delta_p_new", "delta_p_old", "fact_top_two_gap", "anchor_winner_id", "fact_winner_id", "anchor_old_winner",
        "fact_new_winner", "sham_l1", "matched_l1",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in sorted(records, key=lambda r: (r["seed"], r["arm"], r["family"], r["neighborhood_id"])):
            writer.writerow(record)

    json_path = args.outdir / "q-x1-boundary-summary-v01.json"
    json_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "identity": summary["identity"],
        "status": "Q_X1_DIAGNOSTIC_COMPLETE",
        "input_prediction_sha256": observed_sha,
        "input_frozen_analysis_sha256": analysis_sha,
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "outputs": [
            {"path": csv_path.name, "bytes": csv_path.stat().st_size, "sha256": sha256_file(csv_path)},
            {"path": json_path.name, "bytes": json_path.stat().st_size, "sha256": sha256_file(json_path)},
        ],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_contact": False,
        "training": False,
        "new_panel": False,
    }
    receipt_path = args.outdir / "q-x1-receipt-v01.json"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": receipt["status"],
        "total_rows": total_rows,
        "step120_rows": step120_rows,
        "neighborhood_rows": len(records),
        "outputs": receipt["outputs"],
        "receipt": receipt_path.as_posix(),
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
