"""Build the family-safe v0.4 factorial bank and nested training banks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-frozen-saturation-v04")
STRESS = RUN / "stress-bank"
OOD = RUN / "ood"
OUT = RUN / "banks"
TARGETS = (1000, 5000, 10000)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def stress_family(episode: dict[str, Any]) -> str:
    perturbation = episode.get("perturbation") or {}
    return perturbation.get("parent_episode_id") or episode["identity"]["episode_id"]


def bucket(family: str) -> str:
    value = int(hashlib.sha256(family.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if value == 0 else "dev" if value == 1 else "train"


def query_group_count(episode: dict[str, Any]) -> int:
    candidates = {item["candidate_id"]: item for item in episode["runtime_schema"].get("candidates", [])}
    sets = {item["candidate_set_id"]: item for item in episode["runtime_schema"].get("candidate_sets", [])}
    targets = {item["query_id"]: item for item in episode.get("gold_targets", [])}
    total = 0
    for query in episode.get("queries", []):
        if query.get("view") in {"abstain", "span_type", "relation"}:
            continue
        target = targets.get(query.get("query_id"), {})
        body = target.get("target") or {}
        if body.get("target_kind") == "independent_applicability":
            total += len(body.get("candidates") or [])
        elif body.get("target_kind") in {"choice", "ordinal"}:
            candidate_set = sets.get(query.get("candidate_set_id"), {})
            candidate_ids = [cid for cid in candidate_set.get("candidate_ids", []) if cid in candidates]
            if candidate_ids:
                total += 1
    return total


def normalize_metadata(
    episode: dict[str, Any], metadata: dict[str, Any], source: str
) -> dict[str, Any]:
    if source == "stress":
        world_regime = "id"
        ontology_regime = "id"
        cell = "ontology_id_world_id"
        family = stress_family(episode)
        topology = "known_v03_topology"
        operation = metadata.get("operation", "base")
    elif source == "world_ood":
        world_regime = "ood"
        ontology_regime = "id"
        cell = "ontology_id_world_ood"
        family = metadata.get("parent_episode_id") or metadata["episode_id"]
        topology = metadata.get("topology_template_id", "held_out_causal_topology")
        operation = metadata.get("intervention", "base")
    else:
        world_regime = metadata["world_regime"]
        ontology_regime = "ood"
        cell = metadata["factorial_cell"]
        family = stress_family(episode)
        topology = metadata.get("topology_class", "deep_narrow")
        operation = metadata.get("transformation", "schema_ood")
    return {
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "episode_id": episode["identity"]["episode_id"],
        "parent_family_id": family,
        "source": source,
        "ontology_regime": ontology_regime,
        "world_regime": world_regime,
        "factorial_cell": cell,
        "ontology_family_id": episode["identity"].get("schema_family_id"),
        "world_family_id": episode["identity"].get("world_family_id"),
        "topology_class": topology,
        "operation": operation,
        "semantic_fingerprint": episode["identity"].get("semantic_fingerprint"),
    }


def load_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stress_episodes = read_jsonl(STRESS / "stress-episodes.jsonl")
    stress_metadata = {row["episode_id"]: row for row in read_jsonl(STRESS / "stress-metadata.jsonl")}
    rows: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for episode in stress_episodes:
        record = normalize_metadata(episode, stress_metadata[episode["identity"]["episode_id"]], "stress")
        episode["_v04_family_id"] = record["parent_family_id"]
        rows.append(episode)
        metadata.append(record)

    world_episodes = read_jsonl(OOD / "world-ood-episodes.jsonl")
    world_metadata = {row["episode_id"]: row for row in read_jsonl(OOD / "world-ood-metadata.jsonl")}
    for episode in world_episodes:
        record = normalize_metadata(episode, world_metadata[episode["identity"]["episode_id"]], "world_ood")
        episode["_v04_family_id"] = record["parent_family_id"]
        rows.append(episode)
        metadata.append(record)

    for filename, source in (
        ("ontology-id-world-id-episodes.jsonl", "ontology_ood"),
        ("ontology-ood-world-ood-episodes.jsonl", "ontology_ood"),
    ):
        episode_path = OOD / filename
        metadata_path = OOD / filename.replace("-episodes", "-metadata")
        variant_episodes = read_jsonl(episode_path)
        variant_metadata = {row["episode_id"]: row for row in read_jsonl(metadata_path)}
        for episode in variant_episodes:
            record = normalize_metadata(episode, variant_metadata[episode["identity"]["episode_id"]], source)
            episode["_v04_family_id"] = record["parent_family_id"]
            rows.append(episode)
            metadata.append(record)
    return rows, metadata


def main() -> None:
    episodes, metadata = load_inputs()
    metadata_by_id = {row["episode_id"]: row for row in metadata}
    id_id = [episode for episode in episodes if metadata_by_id[episode["identity"]["episode_id"]]["factorial_cell"] == "ontology_id_world_id"]
    ood_eval = [episode for episode in episodes if episode not in id_id]

    # Preserve the v0.4 rule that OOD families are evaluation-only.
    family_split: dict[str, str] = {}
    for episode in id_id:
        family = episode["_v04_family_id"]
        family_split.setdefault(family, bucket(family))
    split_rows: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": [], "external": ood_eval}
    for episode in id_id:
        split_rows[family_split[episode["_v04_family_id"]]].append(episode)

    train_families = sorted(family for family, split in family_split.items() if split == "train")
    family_counts = {
        family: sum(query_group_count(episode) for episode in split_rows["train"] if episode["_v04_family_id"] == family)
        for family in train_families
    }
    nested_families: dict[int, list[str]] = {}
    for target in TARGETS:
        selected: list[str] = []
        total = 0
        for family in train_families:
            selected.append(family)
            total += family_counts[family]
            if total >= target:
                break
        nested_families[target] = selected

    split_manifest: dict[str, Any] = {
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "nested_training_targets": list(TARGETS),
        "family_split_counts": dict(Counter(family_split.values())),
        "episode_counts": {name: len(rows) for name, rows in split_rows.items()},
        "factorial_cells": dict(Counter(metadata_by_id[episode["identity"]["episode_id"]]["factorial_cell"] for episode in episodes)),
        "banks": {},
    }
    for target in TARGETS:
        selected = set(nested_families[target])
        bank = OUT / f"s{target // 1000}k"
        rows = {
            "train": [episode for episode in split_rows["train"] if episode["_v04_family_id"] in selected],
            "dev": split_rows["dev"],
            "test": split_rows["test"],
            "external": split_rows["external"],
        }
        for split, values in rows.items():
            write_jsonl(bank / ("external-eval.jsonl" if split == "external" else f"{split}.jsonl"), values)
            write_jsonl(
                bank / ("external-metadata.jsonl" if split == "external" else f"{split}-metadata.jsonl"),
                [metadata_by_id[episode["identity"]["episode_id"]] for episode in values],
            )
        split_manifest["banks"][str(target)] = {
            "path": str(bank),
            "train_episode_count": len(rows["train"]),
            "train_group_count": sum(query_group_count(episode) for episode in rows["train"]),
            "selected_family_count": len(selected),
            "selected_families": sorted(selected),
        }

    write_jsonl(OUT / "all-episodes.jsonl", episodes)
    write_jsonl(OUT / "all-metadata.jsonl", metadata)
    (OUT / "split-manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "split-manifest.json").write_text(json.dumps(split_manifest, indent=2), encoding="utf-8")
    print(json.dumps(split_manifest, indent=2))


if __name__ == "__main__":
    main()
