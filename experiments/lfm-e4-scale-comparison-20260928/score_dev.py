"""Non-gating E1 FIT-derived DEV sanity check for each refit observer bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from common import TASKS, read_jsonl, sha256, task_eligible
from score import summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("DEV score output already exists")
    seal = json.loads((args.predictions / "prediction-seal.json").read_text(encoding="utf-8"))
    if seal["partition"] != "DEV" or seal["prediction_sha256"] != sha256(args.predictions / "predictions.jsonl"):
        raise RuntimeError("DEV prediction seal mismatch")
    labels = {r["row_id"]: r for r in read_jsonl(args.row_map) if r["partition"] == "DEV"}
    predictions = list(read_jsonl(args.predictions / "predictions.jsonl"))
    if len(predictions) != len(labels) or len(predictions) != seal["rows"]:
        raise RuntimeError("DEV row count mismatch")
    for row in predictions:
        if row["row_id"] not in labels or row["quartet_id"] != labels[row["row_id"]]["quartet_id"]:
            raise RuntimeError("DEV identity mismatch")
    metrics = {}
    for task, (field, classes) in TASKS.items():
        eligible = [row for row in predictions if task_eligible(labels[row["row_id"]], task)]
        truth = np.asarray([labels[row["row_id"]][field] for row in eligible])
        predicted = np.asarray([row[task] for row in eligible])
        metrics[task] = summary(truth, predicted, classes)
    receipt = {
        "schema": "phoenix.e4-scale-dev-sanity/v1",
        "arm": seal["arm"], "source": "E1 FIT-derived DEV only; no fresh TEST truth used",
        "prediction_seal_sha256": sha256(args.predictions / "prediction-seal.json"),
        "row_map_sha256": sha256(args.row_map), "metrics": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"arm": seal["arm"], "accuracy": {k: v["accuracy"] for k, v in metrics.items()}}))


if __name__ == "__main__":
    main()
