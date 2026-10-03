"""Create leakage-safe stress splits while preserving every sibling family."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE = Path(r"D:\codex-runs\jev-semantic-stress-v03\bank")
OUTPUT = SOURCE / "splits"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def bucket(group_id: str) -> str:
    value = int(hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if value == 0 else "dev" if value == 1 else "train"


def main() -> None:
    episodes = read_jsonl(SOURCE / "stress-episodes.jsonl")
    metadata = read_jsonl(SOURCE / "stress-metadata.jsonl")
    metadata_by_episode = {row["episode_id"]: row for row in metadata}
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    metadata_splits: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    family_to_split: dict[str, str] = {}
    for episode in episodes:
        stress = metadata_by_episode[episode["identity"]["episode_id"]]
        family = stress.get("parent_episode_id") or stress["episode_id"]
        split = family_to_split.setdefault(family, bucket(family))
        splits[split].append(episode)
        metadata_splits[split].append(stress)
    for split, rows in splits.items():
        write_jsonl(OUTPUT / f"{split}.jsonl", rows)
        write_jsonl(OUTPUT / f"{split}-metadata.jsonl", metadata_splits[split])
    write_jsonl(OUTPUT / "stress-all.jsonl", episodes)
    write_jsonl(OUTPUT / "stress-metadata.jsonl", metadata)
    manifest = {
        "protocol": "jev-semantic-stress-intervention-geometry-v0.3",
        "episode_counts": {name: len(rows) for name, rows in splits.items()},
        "metadata_counts": {name: len(rows) for name, rows in metadata_splits.items()},
        "family_counts": len(family_to_split),
        "family_partition_policy": "all base, surface, observation, world, schema, and paraphrase siblings share the parent family split",
        "operation_counts": dict(Counter(row["operation"] for row in metadata)),
        "schema_regime_counts": dict(Counter(row["schema_regime"] for row in metadata)),
        "world_regime_counts": dict(Counter(row["world_regime"] for row in metadata)),
    }
    (OUTPUT / "split-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
