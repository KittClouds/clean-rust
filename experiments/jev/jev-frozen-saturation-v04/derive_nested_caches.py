"""Derive nested cache views without changing frozen representations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import torch


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [__import__("json").loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True)
    parser.add_argument("--banks", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cache_path = Path(args.cache)
    bank_root = Path(args.banks)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    all_groups = cache["groups"]
    for target in (1000, 5000, 10000):
        bank = bank_root / f"s{target // 1000}k"
        train_ids = {row["identity"]["episode_id"] for row in read_jsonl(bank / "train.jsonl")}
        groups = [
            group
            for group in all_groups
            if group["split"] != "train" or group["episode_id"] in train_ids
        ]
        view = dict(cache)
        view["groups"] = groups
        view["nested_bank_target"] = target
        view["nested_train_episode_count"] = len(train_ids)
        torch.save(view, output / f"{cache_path.stem}-s{target // 1000}k.pt")
        print({"target": target, "groups": len(groups), "train_episodes": len(train_ids)})


if __name__ == "__main__":
    main()
