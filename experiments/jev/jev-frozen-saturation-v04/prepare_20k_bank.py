"""Materialize the single contract-authorized 20k rescue bank."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from prepare_v04_banks import bucket, load_inputs, query_group_count, write_jsonl


RUN = Path(r"D:\codex-runs\jev-frozen-saturation-v04")
OUT = RUN / "banks" / "s20k"


def main() -> None:
    episodes, metadata = load_inputs()
    metadata_by_id = {row["episode_id"]: row for row in metadata}
    id_id = [episode for episode in episodes if metadata_by_id[episode["identity"]["episode_id"]]["factorial_cell"] == "ontology_id_world_id"]
    external = [episode for episode in episodes if episode not in id_id]
    family_split: dict[str, str] = {}
    for episode in id_id:
        family = episode["_v04_family_id"]
        family_split.setdefault(family, bucket(family))
    split_rows = {"train": [], "dev": [], "test": [], "external": external}
    for episode in id_id:
        split_rows[family_split[episode["_v04_family_id"]]].append(episode)
    train_families = sorted(family for family, split in family_split.items() if split == "train")
    selected: list[str] = []
    total = 0
    for family in train_families:
        selected.append(family)
        total += sum(query_group_count(episode) for episode in split_rows["train"] if episode["_v04_family_id"] == family)
        if total >= 20000:
            break
    chosen = set(selected)
    rows = {
        "train": [episode for episode in split_rows["train"] if episode["_v04_family_id"] in chosen],
        "dev": split_rows["dev"],
        "test": split_rows["test"],
        "external": split_rows["external"],
    }
    for split, values in rows.items():
        write_jsonl(OUT / ("external-eval.jsonl" if split == "external" else f"{split}.jsonl"), values)
        write_jsonl(
            OUT / ("external-metadata.jsonl" if split == "external" else f"{split}-metadata.jsonl"),
            [metadata_by_id[episode["identity"]["episode_id"]] for episode in values],
        )
    manifest = {
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "reason": "single contract-authorized rescue after material 5k-to-10k improvement",
        "terminal_transition": "10k_to_20k",
        "selected_family_count": len(selected),
        "selected_families": selected,
        "episode_counts": {split: len(values) for split, values in rows.items()},
        "train_group_count_estimate": sum(query_group_count(episode) for episode in rows["train"]),
        "family_split_counts": dict(Counter(family_split.values())),
    }
    (OUT / "rescue-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
