#!/usr/bin/env python3
"""Export intermediate FP32 boundary buckets from the pinned v1 exporter."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import torch
from gliner2 import AutoExtractor


def load_exporter(path: Path):
    spec = importlib.util.spec_from_file_location("pinned_boundary_exporter", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import exporter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--onnx-dir", required=True, type=Path)
    parser.add_argument("--exporter", required=True, type=Path)
    parser.add_argument("--buckets", nargs="+", type=int, default=[320, 384, 448])
    args = parser.parse_args()

    exporter = load_exporter(args.exporter)
    model = AutoExtractor.from_pretrained(args.model, local_files_only=True)
    model.eval()
    model.boundary_head.eval()
    model.boundary_head.collect_diagnostics = False
    hidden = int(model.encoder.config.hidden_size)
    query_count = 4
    query_dimension = torch.export.Dim("num_queries", min=1, max=256)

    for bucket in sorted(set(args.buckets)):
        output = args.onnx_dir / f"boundary_head_L{bucket}_fp32.onnx"
        wrapper = exporter.BoundaryHeadWrapper(model.boundary_head)
        wrapper.eval()
        with exporter._unstable_sort():
            exporter._export(
                wrapper,
                (
                    torch.randn(1, bucket, hidden),
                    torch.ones(1, bucket, dtype=torch.long),
                    torch.randn(1, query_count, hidden),
                    torch.ones(1, query_count, dtype=torch.long),
                ),
                output,
                ["text_states", "text_mask", "query_states", "query_mask"],
                [
                    "cand_indices",
                    "pair_logits",
                    "cand_valid",
                    "null_logits",
                    "count_log_rates",
                ],
                dynamic_shapes={
                    "text_states": {1: bucket},
                    "text_mask": {1: bucket},
                    "query_states": {1: query_dimension},
                    "query_mask": {1: query_dimension},
                },
                dynamo=True,
            )
        print(f"{output.name}: {output.stat().st_size / 1e6:.2f} MB")

    manifest_path = args.onnx_dir / "boundary_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["length_buckets"] = sorted(
        set(int(value) for value in manifest["length_buckets"]) | set(args.buckets)
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
