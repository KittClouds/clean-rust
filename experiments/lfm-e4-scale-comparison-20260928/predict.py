"""Seal five-head linear predictions before fresh TEST labels are opened."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from common import TASKS, feature_map, read_jsonl, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--feature-rows", type=int, required=True)
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--index-field", choices=("e1_index", "compact_index", "ordinal"), required=True)
    parser.add_argument("--partition", choices=("TRAIN", "DEV", "TEST"), required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("prediction output already exists")
    fit_receipt = json.loads((args.fit / "fit-receipt.json").read_text(encoding="utf-8"))
    if fit_receipt["dimension"] != args.dimension or fit_receipt["arm"] != args.arm:
        raise RuntimeError("fit artifact does not match arm or dimension")
    rows = list(read_jsonl(args.rows))
    if args.index_field == "ordinal":
        if args.partition != "TEST" or len(rows) != args.feature_rows:
            raise RuntimeError("ordinal mode requires a complete TEST input stream")
        indices = np.arange(len(rows), dtype=np.int64)
    else:
        rows = [r for r in rows if r["partition"] == args.partition]
        indices = np.asarray([r[args.index_field] for r in rows], dtype=np.int64)
    if not rows or len(set(r["row_id"] for r in rows)) != len(rows):
        raise RuntimeError("empty or duplicate prediction row IDs")
    if indices.min() < 0 or indices.max() >= args.feature_rows:
        raise RuntimeError("feature index outside cache")
    features = feature_map(args.features, args.feature_rows, args.dimension)
    head_parameters = {}
    for name, (_, classes) in TASKS.items():
        mean = np.fromfile(args.fit / f"{name}.mean.f32le", dtype="<f4")
        scale = np.fromfile(args.fit / f"{name}.scale.f32le", dtype="<f4")
        weight = np.fromfile(args.fit / f"{name}.weight.f32le", dtype="<f4").reshape(classes, args.dimension)
        bias = np.fromfile(args.fit / f"{name}.bias.f32le", dtype="<f4")
        head_parameters[name] = tuple(torch.from_numpy(a.copy()) for a in (mean, scale, weight, bias))
    args.output.mkdir(parents=True)
    prediction_path = args.output / "predictions.jsonl"
    began = time.perf_counter()
    with prediction_path.open("x", encoding="utf-8", newline="\n") as output:
        for start in range(0, len(rows), 2048):
            batch_rows = rows[start : start + 2048]
            x = np.array(features[indices[start : start + len(batch_rows)]], dtype=np.float32, order="C", copy=True)
            batch_preds: dict[str, np.ndarray] = {}
            for name, (_, classes) in TASKS.items():
                mean, scale, weight, bias = head_parameters[name]
                standardized = torch.from_numpy(x.copy())
                standardized.sub_(mean).div_(scale)
                logits = F.linear(standardized, weight, bias)
                batch_preds[name] = torch.argmax(logits, dim=1).numpy().astype(np.uint8)
            for offset, row in enumerate(batch_rows):
                record = {"row_id": row["row_id"], "quartet_id": row["quartet_id"],
                          "variant_id": row["variant_id"]}
                record.update({name: int(values[offset]) for name, values in batch_preds.items()})
                output.write(json.dumps(record, separators=(",", ":")) + "\n")
    model_files = sorted(args.fit.glob("*.f32le"))
    receipt = {
        "schema": "phoenix.e4-scale-predictions/v1",
        "arm": args.arm, "partition": args.partition, "rows": len(rows),
        "truth_join_performed": False,
        "prediction_path": str(prediction_path.resolve()),
        "prediction_sha256": sha256(prediction_path),
        "feature_sha256": sha256(args.features),
        "row_manifest_sha256": sha256(args.rows),
        "fit_receipt_sha256": sha256(args.fit / "fit-receipt.json"),
        "model_files": {p.name: sha256(p) for p in model_files},
        "inference_seconds": time.perf_counter() - began,
    }
    (args.output / "prediction-seal.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"arm": args.arm, "partition": args.partition, "rows": len(rows),
                      "prediction_sha256": receipt["prediction_sha256"]}), flush=True)


if __name__ == "__main__":
    main()
