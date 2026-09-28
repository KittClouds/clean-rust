"""Prepare the isolated 250k S100 bank for frozen decision-surface scaling."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
SYNTHETIC = RUN / "synthetic-stress"
V05 = Path(r"D:\codex-runs\jev-frozen-scaling-v05")
OUT = RUN / "banks"
TARGET = 250_000


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def split_family(family: str) -> str:
    bucket = int(hashlib.sha256(family.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if bucket == 0 else "dev" if bucket == 1 else "train"


def root_family_id(episode_id: str, parents: dict[str, str | None]) -> str:
    seen: set[str] = set()
    current = episode_id
    while parents.get(current):
        if current in seen:
            raise ValueError(f"parent cycle at {episode_id}")
        seen.add(current)
        current = parents[current]  # type: ignore[index]
    return current


def group_count(episode: dict[str, Any]) -> int:
    candidates = {
        item["candidate_id"]: item
        for item in episode.get("runtime_schema", {}).get("candidates", [])
    }
    sets = {
        item["candidate_set_id"]: item
        for item in episode.get("runtime_schema", {}).get("candidate_sets", [])
    }
    targets = {item["query_id"]: item for item in episode.get("gold_targets", [])}
    total = 0
    for query in episode.get("queries", []):
        if query.get("view") in {"abstain", "span_type", "relation"}:
            continue
        body = (targets.get(query.get("query_id"), {}).get("target") or {})
        kind = body.get("target_kind")
        if kind == "independent_applicability":
            total += len(body.get("candidates") or [])
        elif kind in {"choice", "ordinal"}:
            candidate_set = sets.get(query.get("candidate_set_id"), {})
            if float(body.get("other_probability") or 0.0) == 0.0:
                total += int(any(cid in candidates for cid in candidate_set.get("candidate_ids", [])))
    return total


def main() -> None:
    episodes = read_jsonl(SYNTHETIC / "stress-episodes.jsonl")
    metadata = {row["episode_id"]: row for row in read_jsonl(SYNTHETIC / "stress-metadata.jsonl")}
    parents = {key: row.get("parent_episode_id") for key, row in metadata.items()}
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        episode_id = episode["identity"]["episode_id"]
        family = root_family_id(episode_id, parents)
        episode["_v06_family_id"] = family
        families[family].append(episode)

    family_split = {family: split_family(family) for family in families}
    train_families = sorted(family for family in families if family_split[family] == "train")
    family_counts = {family: sum(group_count(row) for row in families[family]) for family in train_families}
    selected: list[str] = []
    total = 0
    for family in train_families:
        selected.append(family)
        total += family_counts[family]
        if total >= TARGET:
            break
    if total < TARGET:
        raise RuntimeError(f"generated bank only has {total} eligible groups")

    train_rows = [row for family in selected for row in families[family]]
    # Keep the protected v0.5 evaluation surface unchanged. The new source
    # contributes only family-safe S100 training worlds in this lane.
    v05_bank = V05 / "banks" / "feature-bank"
    eval_rows = {
        name: read_jsonl(v05_bank / f"{name}.jsonl")
        for name in ("dev", "test", "external-eval")
    }
    feature_bank = OUT / "feature-bank"
    write_jsonl(feature_bank / "train.jsonl", train_rows)
    for name, rows in eval_rows.items():
        write_jsonl(feature_bank / f"{name}.jsonl", rows)
    scale_bank = OUT / "s250k"
    write_jsonl(scale_bank / "train.jsonl", train_rows)
    for name, rows in eval_rows.items():
        write_jsonl(scale_bank / f"{name}.jsonl", rows)

    manifest = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-S",
        "mode": "S100",
        "target_groups": TARGET,
        "selected_group_count": total,
        "synthetic_episode_count": len(episodes),
        "synthetic_root_world_count": len(families),
        "selected_root_world_count": len(selected),
        "split_counts": dict(Counter(family_split.values())),
        "selected_families": selected,
        "train_episode_count": len(train_rows),
        "protected_eval_source": str(v05_bank),
        "backbone_adaptation": False,
        "v04_gate_reopened": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scale-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
