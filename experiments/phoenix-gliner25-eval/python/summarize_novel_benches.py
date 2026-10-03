#!/usr/bin/env python3
"""Aggregate the frozen per-novel five-surface benchmark receipts."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


FEATURES = (
    "long_context",
    "wide_span_entities",
    "span_attributes",
    "constrained_classification",
    "joint_information_extraction",
)


def quantile_summary(values: list[float]) -> dict[str, float]:
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output_path = args.output.resolve()
    paths = sorted(
        path
        for path in args.receipts.glob("bench-five-*.json")
        if path.resolve() != output_path
    )
    if not paths:
        raise SystemExit("no bench-five-*.json receipts found")

    documents: list[dict[str, object]] = []
    observed: dict[str, list[dict[str, object]]] = {name: [] for name in FEATURES}
    graph_publications = 0

    for path in paths:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["contract"] != "phoenix-gliner25-five-surface-novel-benchmark-v1":
            raise SystemExit(f"unexpected contract in {path}")
        by_feature = {row["feature"]: row for row in receipt["features"]}
        if tuple(by_feature) != FEATURES:
            raise SystemExit(f"feature order mismatch in {path}")
        graph_publications += int(receipt["graph_publications"])
        documents.append(
            {
                "name": Path(receipt["document"]).name,
                "document_bytes": receipt["document_bytes"],
                "engine_load_ms": receipt["engine_load_ms"],
                "short_window": receipt["short_window"],
                "long_window": receipt["long_window"],
                "features": receipt["features"],
            }
        )
        for feature in FEATURES:
            observed[feature].append(by_feature[feature])

    aggregate: dict[str, object] = {}
    for feature, rows in observed.items():
        output_counts = {int(row["stable_output_count"]) for row in rows}
        aggregate[feature] = {
            "p50_ms_across_documents": quantile_summary(
                [float(row["p50_ms"]) for row in rows]
            ),
            "p95_ms_across_documents": quantile_summary(
                [float(row["p95_ms"]) for row in rows]
            ),
            "p99_ms_across_documents": quantile_summary(
                [float(row["p99_ms"]) for row in rows]
            ),
            "stable_output_counts": sorted(output_counts),
            "maximum_peak_working_set_bytes": max(
                int(row["peak_working_set_bytes"]) for row in rows
            ),
        }

    summary = {
        "contract": "phoenix-gliner25-five-surface-novel-benchmark-summary-v1",
        "source_receipts": [path.name for path in paths],
        "documents": documents,
        "aggregate": aggregate,
        "graph_publications": graph_publications,
        "interpretation": {
            "latency": "min/median/max of each document's measured quantile",
            "quality": "not measured; no human gold set was used",
            "promotion": "candidate-only shadow evaluation",
        },
    }
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
