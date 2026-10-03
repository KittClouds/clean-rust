"""Bounded timing smoke for the v0.5 frozen-head runner."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch

from train_v05 import FEATURES, groups_for_scale, fast_tensor_batch, v05_loss, probe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--groups", type=int, default=1024)
    parser.add_argument("--batches", type=int, default=8)
    args = parser.parse_args()
    started = time.perf_counter()
    cache_path = FEATURES / args.model_name / f"{args.model_name}-features.pt"
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    loaded = time.perf_counter()
    synthetic, _real = groups_for_scale(cache["groups"], 50_000, 20260925)
    selected = synthetic[: args.groups]
    feature_key = f"mean_full@{cache['layer_count']}"
    state = cache["features"]["state"][feature_key].to(args.device)
    candidate = cache["features"]["candidate"]["name_definition"][feature_key].to(args.device)
    head = probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(args.device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=2e-3, weight_decay=0.01)
    prepared = time.perf_counter()
    batches = 0
    for start in range(0, len(selected), 256):
        chunk = selected[start : start + 256]
        state_batch, candidate_batch, gold, mask, kinds, sources = fast_tensor_batch(
            chunk, state, candidate, "name_definition", args.device, reorder=True,
        )
        optimizer.zero_grad(set_to_none=True)
        loss, _brier = v05_loss(head(state_batch, candidate_batch), gold, mask, kinds, sources, 0.25)
        loss.backward()
        optimizer.step()
        batches += 1
        if batches >= args.batches:
            break
    if args.device.startswith("cuda"):
        torch.cuda.synchronize()
    finished = time.perf_counter()
    print({
        "model": args.model_name,
        "groups": len(selected),
        "batches": batches,
        "load_seconds": loaded - started,
        "prepare_seconds": prepared - loaded,
        "update_seconds": finished - prepared,
        "cuda_peak": int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0,
    })


if __name__ == "__main__":
    main()
