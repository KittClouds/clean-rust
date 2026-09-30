"""Apply the frozen Rung-1 edge-existence observer to specialized local vectors."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

GRAPH_DIR = Path(__file__).resolve().parents[1] / "bank-v1-graph-surface-v2-20260929"
sys.path.insert(0, str(GRAPH_DIR))
import common  # noqa: E402
import fit_graph  # noqa: E402
import graph_metrics  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-features", type=Path, required=True)
    parser.add_argument("--r0-output", type=Path, required=True)
    parser.add_argument("--graph-base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extraction_path = args.local_features / "features" / "extraction-seal.json"
    receipt = read_json(extraction_path)
    if receipt.get("truth_joined") is not False:
        raise RuntimeError("specialized graph features joined labels before scoring")
    adapted_mentions = args.local_features / "row-mentions.jsonl"
    base_mentions = args.graph_base / "row-mentions.jsonl"
    if sha256(adapted_mentions) != sha256(base_mentions):
        raise RuntimeError("entity IDs/mention order changed; frozen sentinel indices no longer align")
    target_dir = args.output / "task-examples" / "edge_existence"
    target_dir.mkdir(parents=True, exist_ok=False)
    task_source = args.graph_base / "task-examples" / "edge_existence"
    splits = ("DEV", *[name for name in common.WORLD_SPLITS if name.startswith("TEST-")])
    task_hashes = {}
    for split in splits:
        source = task_source / f"{split}.jsonl"
        os.link(source, target_dir / source.name)
        task_hashes[split] = sha256(source)

    arrays = {"entity": {}, "goal": {}}
    for name in ("middle_mean", "final_mean"):
        key = f"entity_{name}"
        spec = receipt["features"][key]
        path = args.local_features / "features" / f"{key}.npy"
        if sha256(path) != spec["sha256"]:
            raise RuntimeError(f"specialized local feature hash mismatch: {key}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(array.shape) != spec["shape"] or array.dtype != np.dtype("<f2"):
            raise RuntimeError(f"invalid specialized local feature array: {key}")
        arrays["entity"][name] = array
    scaler_path = args.graph_base / "scalers" / "local-middle_plus_final.npz"
    with __import__("numpy").load(scaler_path, allow_pickle=False) as scaler:
        mean, scale = scaler["mean"].copy(), scaler["scale"].copy()
    if mean.shape != scale.shape or mean.shape != (2048,):
        raise RuntimeError("locked sentinel scaler dimensions changed")
    scalers = {"local": {"middle_plus_final": (mean, scale)}}
    model_path = args.graph_base / "models" / "edge_existence-middle_plus_final-tiny_mlp.pt"
    model = fit_graph.load_saved_head(__import__("torch"), model_path, "edge_existence",
                                      "tiny_mlp", len(mean))
    scores = fit_graph.evaluate_task_model(__import__("torch"), model, "edge_existence",
        "middle_plus_final", args.output, arrays, None, scalers, split_names=splits)
    test_splits = {key: value for key, value in scores.items() if key.startswith("TEST-")}
    baseline = read_json(args.graph_base / "graph-readout-results.json")
    base_summary = baseline["task_summary"]["edge_existence"]
    result = {
        "schema": "lexi-specialization-edge-sentinel/v1",
        "task": "edge_existence", "surface": "middle_plus_final",
        "head": "original Rung-1 tiny_mlp, unchanged",
        "features_extraction_sha256": sha256(extraction_path),
        "mentions_sha256": sha256(adapted_mentions),
        "task_examples_sha256_by_split": task_hashes,
        "scaler_sha256": sha256(scaler_path),
        "head_sha256": sha256(model_path),
        "metrics_by_split": scores,
        "test_aggregate_auc": graph_metrics.aggregate_over_splits(test_splits, "roc_auc"),
        "held_renderer_s7_s8_s9_auc": graph_metrics.aggregate_renderer(
            test_splits, "roc_auc", held_out=True),
        "base_test_aggregate_auc": base_summary["test_metric"],
        "base_held_renderer_s7_s8_s9_auc": base_summary["held_renderer_metric"],
        "readout_refit": False,
    }
    write_json(args.output / "edge-sentinel-score.json", result)
    print(json.dumps({"status": "EDGE_SENTINEL_SCORED",
                      "test_auc": result["test_aggregate_auc"],
                      "held_renderer_auc": result["held_renderer_s7_s8_s9_auc"],
                      "base_test_auc": result["base_test_aggregate_auc"],
                      "base_held_renderer_auc": result["base_held_renderer_s7_s8_s9_auc"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
