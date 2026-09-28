"""Prepare leakage-safe readout splits from validated canonical JSONL."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SYNTHETIC = Path(r"D:\codex-runs\jev-frozen-readout-v01\readout-episodes.jsonl")
BRIDGE = Path(r"D:\codex-runs\jev-corpus-bridge-v01\pilot-episodes.jsonl")
OUT = Path(r"D:\codex-runs\jev-frozen-readout-v01\bank")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def split_group(episode: dict[str, Any]) -> str:
    perturbation = episode.get("perturbation") or {}
    parent = perturbation.get("parent_episode_id")
    if parent:
        return f"synthetic-parent:{parent}"
    identity = episode["identity"]
    return ":".join(
        [
            episode.get("authority", {}).get("episode_authority_class", "unknown"),
            identity.get("source_dataset_id", ""),
            identity.get("world_instance_id", ""),
            identity.get("semantic_fingerprint", ""),
        ]
    )


def partition(group: str) -> str:
    bucket = int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if bucket == 0 else "dev" if bucket == 1 else "train"


def main() -> None:
    synthetic = read_jsonl(SYNTHETIC)
    bridge = read_jsonl(BRIDGE)
    external = [
        episode
        for episode in bridge
        if episode.get("authority", {}).get("episode_authority_class") != "synthetic_control"
    ]
    all_synthetic = synthetic
    splits = {"train": [], "dev": [], "test": []}
    for episode in all_synthetic:
        splits[partition(split_group(episode))].append(episode)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, episodes in splits.items():
        write_jsonl(OUT / f"{name}.jsonl", episodes)
    write_jsonl(OUT / "synthetic-all.jsonl", all_synthetic)
    write_jsonl(OUT / "external-eval.jsonl", external)
    manifest = {
        "protocol": "jev-frozen-compatibility-readout-v0.2",
        "synthetic_episode_count": len(all_synthetic),
        "external_episode_count": len(external),
        "synthetic_query_count": sum(len(item.get("queries", [])) for item in all_synthetic),
        "external_query_count": sum(len(item.get("queries", [])) for item in external),
        "episode_counts_by_split": {name: len(value) for name, value in splits.items()},
        "query_counts_by_split": {
            name: sum(len(item.get("queries", [])) for item in value)
            for name, value in splits.items()
        },
        "authority_counts": dict(Counter(item["authority"]["episode_authority_class"] for item in external)),
        "sibling_leakage_policy": "parent and all verified perturbation children share one split",
        "external_transfer_policy": "externally annotated rows are held out from synthetic training",
    }
    (OUT / "split-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
