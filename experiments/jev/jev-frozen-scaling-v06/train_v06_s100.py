"""Run the fixed v0.5 compatibility head on the isolated 250k S100 bank."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
FEATURES = RUN / "features"
OUT = RUN / "head-runs"

sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


def run_model(model_name: str, device: str, seed: int) -> dict:
    cache_path = FEATURES / f"{model_name}-features.pt"
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    groups = cache["groups"]
    train = [
        item for item in groups
        if item["split"] == "train"
        and base.eligible(item)
        and item["authority"] == "synthetic_control"
    ]
    dev = base.select_eval(groups, "dev")
    test = base.select_eval(groups, "test")
    external = base.select_eval(groups, "external")
    if len(train) < 250_000:
        raise RuntimeError(f"{model_name}: only {len(train)} eligible training groups")
    args = argparse.Namespace(
        model_name=model_name,
        device=device,
        location="mean_full",
        profile="name_definition",
        seed=seed,
    )
    base.OUT = OUT
    report = base.train_one(cache, train, dev, test, external, args, 250_000, "S100")
    report["protocol"] = "jev-frozen-decision-surface-scaling/v0.6-S"
    report["v05_reference"] = {
        "head_unchanged": True,
        "loss": "v0.4_L3_source_typed",
        "backbone_adaptation": False,
    }
    report["train_groups"] = len(train)
    report_path = OUT / model_name / f"{model_name}-s250k-S100.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "model": model_name,
        "train_groups": len(train),
        "wall_clock_seconds": report["wall_clock_seconds"],
        "exact": report["test"]["temperature_scaled"].get("synthetic_control"),
    }), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args()
    run_model(args.model_name, args.device, args.seed)


if __name__ == "__main__":
    main()
