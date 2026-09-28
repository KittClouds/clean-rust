"""Run the fixed v0.6 compatibility head on frozen LFM features."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
BANKS = Path(r"D:\codex-runs\jev-frozen-scaling-v05\banks")
FEATURES = RUN / "features"
OUT = RUN / "head-runs"

sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


def train_scale(cache: dict, scale: int, args: argparse.Namespace) -> dict:
    groups = cache["groups"]
    dev = base.select_eval(groups, "dev")
    test = base.select_eval(groups, "test")
    external = base.select_eval(groups, "external")
    synthetic = [
        item for item in groups
        if base.eligible(item)
        and item["authority"] == "synthetic_control"
    ]
    if scale == 50_000:
        ids = base.episode_ids(BANKS / "s50k" / "train.jsonl")
        train = [item for item in synthetic if item["episode_id"] in ids]
    elif scale == 100_000:
        train = synthetic
    elif scale == 250_000:
        train = synthetic
        if len(train) < 250_000:
            raise RuntimeError(f"only {len(train)} eligible groups in the promoted 250k bank")
    else:
        raise ValueError(f"unsupported v0.7 scale: {scale}")
    if len(train) == 0:
        raise RuntimeError(f"no eligible LFM training groups at scale {scale}")
    base.BANKS = BANKS
    base.OUT = OUT
    report = base.train_one(cache, train, dev, test, external, args, scale, "S100")
    report.update({
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "v07_contract": str(ROOT / "experiments" / "jev-lfm-variable-v07" / "v07-contract.json"),
        "architecture_variable": "lfm2.5-1.2b-base",
        "backbone_frozen": True,
        "training_source": "synthetic_control",
        "fixed_reference_head": True,
        "nonidentical_fields": [],
        "v04_gate_modified": False,
        "v05_v06_reports_modified": False,
    })
    output_dir = OUT / cache["model_name"]
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{cache['model_name']}-s{scale // 1000}k-S100.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "model": cache["model_name"],
        "scale": scale,
        "train_groups": len(train),
        "test_groups": len(test),
        "wall_clock_seconds": report["wall_clock_seconds"],
        "test_exact": report["test"]["temperature_scaled"].get("synthetic_control"),
    }), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=20260927)
    parser.add_argument("--scales", default="50000,100000")
    parser.add_argument("--feature-cache", default=str(FEATURES / "lfm2.5-1.2b-base-features.pt"))
    args = parser.parse_args()
    cache = torch.load(args.feature_cache, map_location="cpu", weights_only=False)
    train_args = argparse.Namespace(
        model_name=cache["model_name"],
        device=args.device,
        location="mean_full",
        profile="name_definition",
        seed=args.seed,
    )
    reports = [
        train_scale(cache, int(item), train_args)
        for item in args.scales.split(",") if item
    ]
    summary_path = OUT / cache["model_name"] / "summary.json"
    summary_path.write_text(json.dumps({
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "runs": reports,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
