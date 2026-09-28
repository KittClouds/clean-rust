"""Prepare nested family-safe synthetic banks and bounded mixed feature inputs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v05")
SYNTHETIC = RUN / "synthetic-stress"
REAL = RUN / "real-bank"
V04 = Path(r"D:\codex-runs\jev-frozen-saturation-v04\banks\s10k")
OUT = RUN / "banks"
SCALES = (50_000, 100_000)
REAL_TRAIN_LIMIT = 2_500
REAL_EVAL_LIMIT = 500


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


def root_family_id(
    episode_id: str,
    parent_by_id: dict[str, str | None],
    memo: dict[str, str],
) -> str:
    """Return the base-world identity for every perturbation descendant.

    ``stress_family_id`` describes the immediate perturbation family (for
    example ``surface:<base-id>``), which is useful for diagnostics but is
    too fine-grained for family-safe scaling.  The scaling banks must keep
    every descendant of one sampled world together, so resolve the explicit
    parent chain to its root episode instead.
    """
    cached = memo.get(episode_id)
    if cached is not None:
        return cached
    seen: set[str] = set()
    current = episode_id
    while parent_by_id.get(current):
        if current in seen:
            raise ValueError(f"perturbation parent cycle at {episode_id}")
        seen.add(current)
        current = parent_by_id[current]  # type: ignore[index]
    memo[episode_id] = current
    return current


def group_count(episode: dict[str, Any]) -> int:
    candidates = {item["candidate_id"]: item for item in episode.get("runtime_schema", {}).get("candidates", [])}
    sets = {item["candidate_set_id"]: item for item in episode.get("runtime_schema", {}).get("candidate_sets", [])}
    targets = {item["query_id"]: item for item in episode.get("gold_targets", [])}
    total = 0
    for query in episode.get("queries", []):
        if query.get("view") in {"abstain", "span_type", "relation"}:
            continue
        target = targets.get(query.get("query_id"), {})
        body = target.get("target") or {}
        kind = body.get("target_kind")
        if kind == "independent_applicability":
            total += len(body.get("candidates") or [])
        elif kind in {"choice", "ordinal"}:
            candidate_set = sets.get(query.get("candidate_set_id"), {})
            if float(body.get("other_probability") or 0.0) == 0.0:
                total += int(bool([cid for cid in candidate_set.get("candidate_ids", []) if cid in candidates]))
    return total


def bounded(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: row["identity"]["episode_id"])
    # Keep every bounded pilot source visible when a split also contains the
    # expanded GoEmotions lane.  Otherwise lexical sorting can consume the
    # whole cap before ChaosNLI/MASSIVE reaches the feature bank.
    pilot = [
        row for row in ordered
        if row.get("identity", {}).get("world_family_id", "").startswith("external:")
        and "go_emotions" not in row.get("identity", {}).get("world_family_id", "")
    ]
    remainder = [row for row in ordered if row not in pilot]
    return (pilot + remainder)[:limit]


def main() -> None:
    episodes = read_jsonl(SYNTHETIC / "stress-episodes.jsonl")
    metadata = {row["episode_id"]: row for row in read_jsonl(SYNTHETIC / "stress-metadata.jsonl")}
    parent_by_id = {
        row["episode_id"]: row.get("parent_episode_id")
        for row in metadata.values()
    }
    root_memo: dict[str, str] = {}
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        episode_id = episode["identity"]["episode_id"]
        family = root_family_id(episode_id, parent_by_id, root_memo)
        episode["_v05_family_id"] = family
        families[family].append(episode)
    family_split = {family: split_family(family) for family in families}
    train_families = sorted(family for family in families if family_split[family] == "train")
    family_counts = {family: sum(group_count(row) for row in families[family]) for family in train_families}
    nested: dict[int, list[str]] = {}
    for target in SCALES:
        selected: list[str] = []
        total = 0
        for family in train_families:
            selected.append(family)
            total += family_counts[family]
            if total >= target:
                break
        nested[target] = selected

    synthetic_splits = {
        "dev": [row for family, rows in families.items() if family_split[family] == "dev" for row in rows],
        "test": [row for family, rows in families.items() if family_split[family] == "test" for row in rows],
    }
    real_splits = {name: read_jsonl(REAL / f"{name}.jsonl") for name in ("train", "dev", "test")}
    real_splits["external"] = read_jsonl(REAL / "external-eval.jsonl")
    real_splits["train"] = bounded(real_splits["train"], REAL_TRAIN_LIMIT)
    real_splits["dev"] = bounded(real_splits["dev"], REAL_EVAL_LIMIT)
    real_splits["test"] = bounded(real_splits["test"], REAL_EVAL_LIMIT)
    real_splits["external"] = bounded(real_splits["external"], REAL_EVAL_LIMIT)

    feature_bank = OUT / "feature-bank"
    train_union = [row for family in nested[100_000] for row in families[family]] + real_splits["train"]
    dev_union = synthetic_splits["dev"] + read_jsonl(V04 / "dev.jsonl") + real_splits["dev"]
    test_union = synthetic_splits["test"] + read_jsonl(V04 / "test.jsonl") + real_splits["test"]
    external_union = read_jsonl(V04 / "external-eval.jsonl") + real_splits["external"]
    for name, rows in (("train", train_union), ("dev", dev_union), ("test", test_union), ("external-eval", external_union)):
        write_jsonl(feature_bank / f"{name}.jsonl", rows)

    scale_manifest: dict[str, Any] = {
        "contract": "jev-frozen-decision-surface-scaling/v0.5",
        "synthetic_episode_count": len(episodes),
        "synthetic_family_count": len(families),
        "synthetic_family_split_counts": dict(Counter(family_split.values())),
        "real_limits": {"train_episodes": REAL_TRAIN_LIMIT, "eval_episodes_per_split": REAL_EVAL_LIMIT},
        "feature_bank": str(feature_bank),
        "scales": {},
    }
    for target in SCALES:
        chosen = set(nested[target])
        rows = [row for family in chosen for row in families[family]]
        bank = OUT / f"s{target // 1000}k"
        write_jsonl(bank / "train.jsonl", rows)
        write_jsonl(bank / "dev.jsonl", dev_union)
        write_jsonl(bank / "test.jsonl", test_union)
        write_jsonl(bank / "external-eval.jsonl", external_union)
        scale_manifest["scales"][str(target)] = {
            "selected_family_count": len(chosen),
            "selected_families": sorted(chosen),
            "train_episode_count": len(rows),
            "train_group_count_estimate": sum(group_count(row) for row in rows),
            "unique_parent_worlds": len(chosen),
            "unique_ontology_families": len({row["identity"].get("schema_family_id") for row in rows}),
            "unique_schema_instances": len({row["identity"]["episode_id"] for row in rows}),
        }
    scale_manifest["real"] = {
        "train_episode_count": len(real_splits["train"]),
        "dev_episode_count": len(real_splits["dev"]),
        "test_episode_count": len(real_splits["test"]),
        "external_episode_count": len(real_splits["external"]),
        "source_counts_train": dict(Counter((row.get("identity", {}).get("domain_family_id") for row in real_splits["train"]))),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scale-manifest.json").write_text(json.dumps(scale_manifest, indent=2), encoding="utf-8")
    print(json.dumps(scale_manifest, indent=2))


if __name__ == "__main__":
    main()
