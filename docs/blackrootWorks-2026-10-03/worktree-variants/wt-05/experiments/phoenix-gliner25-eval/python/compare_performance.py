#!/usr/bin/env python3
"""Compare matched five-surface novel benchmark summaries."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def feature_map(document: dict) -> dict[str, dict]:
    return {row["feature"]: row for row in document["features"]}


def geometric_mean(values: list[float]) -> float:
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    before = {row["name"]: row for row in baseline["documents"]}
    after = {row["name"]: row for row in candidate["documents"]}
    if before.keys() != after.keys():
        raise SystemExit("document sets differ")

    per_feature: dict[str, dict] = {}
    all_ratios: list[float] = []
    counts_exact = True
    baseline_peak = 0
    candidate_peak = 0
    for document in before:
        old = feature_map(before[document])
        new = feature_map(after[document])
        if old.keys() != new.keys():
            raise SystemExit(f"feature sets differ for {document}")
        for feature in old:
            ratio = new[feature]["p50_ms"] / old[feature]["p50_ms"]
            all_ratios.append(ratio)
            row = per_feature.setdefault(feature, {"ratios": [], "documents": {}})
            row["ratios"].append(ratio)
            row["documents"][document] = {
                "baseline_p50_ms": old[feature]["p50_ms"],
                "candidate_p50_ms": new[feature]["p50_ms"],
                "change_percent": (ratio - 1.0) * 100.0,
            }
            counts_exact &= (
                old[feature]["stable_output_count"]
                == new[feature]["stable_output_count"]
            )
            baseline_peak = max(baseline_peak, old[feature]["peak_working_set_bytes"])
            candidate_peak = max(candidate_peak, new[feature]["peak_working_set_bytes"])

    for row in per_feature.values():
        ratios = row.pop("ratios")
        row["geometric_mean_change_percent"] = (geometric_mean(ratios) - 1.0) * 100.0
        row["median_change_percent"] = (statistics.median(ratios) - 1.0) * 100.0
        row["minimum_change_percent"] = (min(ratios) - 1.0) * 100.0
        row["maximum_change_percent"] = (max(ratios) - 1.0) * 100.0

    receipt = {
        "contract": "phoenix-gliner25-five-surface-performance-comparison-v1",
        "baseline": args.baseline.name,
        "candidate": args.candidate.name,
        "documents": sorted(before),
        "stable_output_counts_exact": counts_exact,
        "per_feature": per_feature,
        "all_matched_p50_geometric_mean_change_percent": (
            geometric_mean(all_ratios) - 1.0
        )
        * 100.0,
        "maximum_peak_working_set": {
            "baseline_bytes": baseline_peak,
            "candidate_bytes": candidate_peak,
            "change_percent": (candidate_peak / baseline_peak - 1.0) * 100.0,
        },
        "graph_publications": candidate["graph_publications"],
        "interpretation": "Matched release p50 ratios; no quality claim.",
    }
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
