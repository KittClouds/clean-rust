"""Audit and build a family-safe, training-only Jev C100 candidate.

The source and current banks live outside this checkout by design.  This tool
reads them without modifying them and writes a new candidate bank under the
requested output directory.  Selection is based only on source metadata,
source gold structure, and current training identities; protected evaluation
rows and model outcomes are never inputs to selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SOURCE_EPISODES = Path(r"D:\codex-runs\jev-frozen-scaling-v06\synthetic-stress\stress-episodes.jsonl")
DEFAULT_SOURCE_METADATA = Path(r"D:\codex-runs\jev-frozen-scaling-v06\synthetic-stress\stress-metadata.jsonl")
DEFAULT_V05_TRAIN = Path(r"D:\codex-runs\jev-frozen-scaling-v05\banks\s100k\train.jsonl")
DEFAULT_V06_TRAIN = Path(r"D:\codex-runs\jev-frozen-scaling-v06\banks\s250k\train.jsonl")


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def family_split(family: str) -> str:
    bucket = int(sha256_text(family)[:8], 16) % 10
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


def entropy(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if float(value) > 0.0]
    total = sum(values)
    if total <= 0.0:
        return None
    return -sum((value / total) * math.log(value / total) for value in values)


def target_entropies(episode: dict[str, Any]) -> list[float]:
    result: list[float] = []
    for gold in episode.get("gold_targets", []):
        target = gold.get("target") or {}
        kind = target.get("target_kind")
        if kind in {"choice", "abstention"}:
            values = [item.get("probability", 0.0) for item in target.get("distribution") or []]
            if target.get("other_probability") is not None:
                values.append(target["other_probability"])
            value = entropy(values)
            if value is not None:
                result.append(value)
        elif kind == "ordinal":
            value = entropy(target.get("distribution") or [])
            if value is not None:
                result.append(value)
        elif kind == "independent_applicability":
            binary = []
            for item in target.get("candidates") or []:
                probability = item.get("probability")
                if probability is not None:
                    binary.append(entropy([probability, 1.0 - probability]))
            result.extend(value for value in binary if value is not None)
    return result


def candidate_set_sizes(episode: dict[str, Any]) -> list[int]:
    candidates = {item.get("candidate_id") for item in episode.get("runtime_schema", {}).get("candidates", [])}
    return [
        sum(candidate in candidates for candidate in item.get("candidate_ids", []))
        for item in episode.get("runtime_schema", {}).get("candidate_sets", [])
    ]


def structural_fingerprint(episode: dict[str, Any]) -> str:
    """Fingerprint model-facing structure without surface text or outcomes."""
    schema = episode.get("runtime_schema", {})
    candidates = sorted(
        (
            item.get("candidate_semantic_id"),
            item.get("kind"),
            item.get("parent_candidate_semantic_id"),
            item.get("order_rank"),
            item.get("mutually_exclusive_group_id"),
            item.get("independent_allowed"),
        )
        for item in schema.get("candidates", [])
    )
    sets = []
    by_id = {item.get("candidate_id"): item for item in schema.get("candidates", [])}
    for item in schema.get("candidate_sets", []):
        members = sorted(by_id.get(value, {}).get("candidate_semantic_id") for value in item.get("candidate_ids", []))
        sets.append((item.get("set_role"), item.get("declared_semantics"), item.get("ordered"), members))
    queries = sorted((item.get("query_semantic_id"), item.get("view"), item.get("candidate_set_id")) for item in episode.get("queries", []))
    payload = {"schema_family": schema.get("schema_family_id"), "candidates": candidates, "sets": sorted(sets), "queries": queries}
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def query_distance_bins(metadata: dict[str, Any]) -> Counter[str]:
    """Return a diagnostic D1/D2/D4 proxy, never treated as a canonical field."""
    result: Counter[str] = Counter()
    for query in metadata.get("queries", []):
        distances = [int(value) for value in (query.get("candidate_distances") or {}).values()]
        if not distances:
            continue
        minimum = min(distances)
        if minimum <= 1:
            result["D1_proxy"] += 1
        elif minimum == 2:
            result["D2_proxy"] += 1
        elif minimum >= 4:
            result["D4_proxy"] += 1
        else:
            result["D3_proxy"] += 1
    return result


def compact_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_id": row.get("episode_id"),
        "parent_episode_id": row.get("parent_episode_id"),
        "operation": row.get("operation", "unknown"),
        "intervention_class": row.get("intervention_class", "unknown"),
        "lexical_regime": row.get("lexical_regime", "unknown"),
        "ontology_id": row.get("ontology_id", "unknown"),
        "candidate_profiles": tuple(sorted(row.get("candidate_profiles") or [])),
        "query_count": len(row.get("queries") or []),
        "distance_bins": dict(query_distance_bins(row)),
        "expected_relation": row.get("expected_relation", "unknown"),
    }


@dataclass
class RootSummary:
    root_id: str
    world_family: str
    schema_families: Counter[str] = field(default_factory=Counter)
    episode_count: int = 0
    groups: int = 0
    operations: Counter[str] = field(default_factory=Counter)
    intervention_classes: Counter[str] = field(default_factory=Counter)
    lexical_regimes: Counter[str] = field(default_factory=Counter)
    candidate_profiles: Counter[str] = field(default_factory=Counter)
    candidate_sizes: list[int] = field(default_factory=list)
    entropies: list[float] = field(default_factory=list)
    distance_bins: Counter[str] = field(default_factory=Counter)
    fingerprints: set[str] = field(default_factory=set)
    text_hashes: set[str] = field(default_factory=set)
    normalized_text_hashes: set[str] = field(default_factory=set)
    structural_fingerprints: set[str] = field(default_factory=set)

    def update(self, episode: dict[str, Any], metadata: dict[str, Any]) -> None:
        identity = episode.get("identity", {})
        self.episode_count += 1
        self.groups += group_count(episode)
        self.schema_families[str(identity.get("schema_family_id"))] += 1
        self.operations[metadata["operation"]] += 1
        self.intervention_classes[metadata["intervention_class"]] += 1
        self.lexical_regimes[metadata["lexical_regime"]] += 1
        for profile in metadata["candidate_profiles"]:
            self.candidate_profiles[profile] += 1
        self.candidate_sizes.extend(candidate_set_sizes(episode))
        self.entropies.extend(target_entropies(episode))
        self.distance_bins.update(metadata["distance_bins"])
        fingerprint = str(identity.get("semantic_fingerprint", ""))
        if fingerprint:
            self.fingerprints.add(fingerprint)
        content = str((episode.get("state", {}).get("observable") or {}).get("content", ""))
        self.text_hashes.add(sha256_text(content))
        self.normalized_text_hashes.add(sha256_text(normalized_text(content)))
        self.structural_fingerprints.add(structural_fingerprint(episode))

    def feature_signature(self, entropy_band: str) -> tuple[str, ...]:
        max_size = max(self.candidate_sizes, default=0)
        dense = "dense" if max_size >= 4 else "sparse"
        hard = "hard" if sum(self.distance_bins.get(key, 0) for key in ("D2_proxy", "D4_proxy")) else "not_hard"
        return (
            self.world_family,
            entropy_band,
            dense,
            hard,
            "+".join(sorted(self.operations)),
            "+".join(sorted(self.lexical_regimes)),
        )


@dataclass
class CurrentAudit:
    name: str
    rows: int = 0
    groups: int = 0
    episode_ids: set[str] = field(default_factory=set)
    roots: set[str] = field(default_factory=set)
    world_families: Counter[str] = field(default_factory=Counter)
    schema_families: Counter[str] = field(default_factory=Counter)
    operations: Counter[str] = field(default_factory=Counter)
    fingerprints: set[str] = field(default_factory=set)
    text_hashes: set[str] = field(default_factory=set)
    normalized_text_hashes: set[str] = field(default_factory=set)
    structural_fingerprints: set[str] = field(default_factory=set)
    candidate_sizes: list[int] = field(default_factory=list)
    entropies: list[float] = field(default_factory=list)
    distance_bins: Counter[str] = field(default_factory=Counter)

    def update(self, episode: dict[str, Any], root: str | None = None) -> None:
        self.rows += 1
        self.groups += group_count(episode)
        identity = episode.get("identity", {})
        self.episode_ids.add(str(identity.get("episode_id")))
        if root:
            self.roots.add(root)
        self.world_families[str(identity.get("world_family_id"))] += 1
        self.schema_families[str(identity.get("schema_family_id"))] += 1
        self.operations[str((episode.get("perturbation") or {}).get("operation", "base"))] += 1
        fingerprint = str(identity.get("semantic_fingerprint", ""))
        if fingerprint:
            self.fingerprints.add(fingerprint)
        content = str((episode.get("state", {}).get("observable") or {}).get("content", ""))
        self.text_hashes.add(sha256_text(content))
        self.normalized_text_hashes.add(sha256_text(normalized_text(content)))
        self.structural_fingerprints.add(structural_fingerprint(episode))
        self.candidate_sizes.extend(candidate_set_sizes(episode))
        self.entropies.extend(target_entropies(episode))


def percentile_bands(values: list[float]) -> dict[float, str]:
    if not values:
        return {}
    ordered = sorted(values)
    lower = ordered[len(ordered) // 3]
    upper = ordered[(2 * len(ordered)) // 3]
    return {value: ("low" if value < lower else "mid" if value < upper else "high") for value in set(values)}


def select_roots(roots: list[RootSummary], target_groups: int, seed: str) -> list[RootSummary]:
    if target_groups <= 0:
        raise ValueError("target_groups must be positive")
    bands = percentile_bands([sum(root.entropies) / len(root.entropies) for root in roots if root.entropies])
    entropy_band = {
        root.root_id: bands.get(sum(root.entropies) / len(root.entropies), "unknown")
        if root.entropies else "unknown"
        for root in roots
    }
    candidates = [root for root in roots if root.groups > 0 and root.groups <= target_groups]
    counts: Counter[tuple[str, ...]] = Counter()
    chosen: list[RootSummary] = []
    chosen_ids: set[str] = set()
    total = 0
    while True:
        eligible = [root for root in candidates if root.root_id not in chosen_ids and total + root.groups <= target_groups]
        if not eligible:
            break
        def rank(root: RootSummary) -> tuple[float, float, str]:
            signature = root.feature_signature(entropy_band[root.root_id])
            rarity = sum(1.0 / (1.0 + counts[(signature[0], value)]) for value in signature)
            hard_bonus = 0.25 if signature[3] == "hard" else 0.0
            tie = sha256_text(f"{seed}:{root.root_id}")
            return (rarity + hard_bonus, root.groups * -1.0, tie)
        selected = max(eligible, key=rank)
        chosen.append(selected)
        chosen_ids.add(selected.root_id)
        total += selected.groups
        counts.update((selected.feature_signature(entropy_band[selected.root_id])[0], value) for value in selected.feature_signature(entropy_band[selected.root_id]))

    residual = target_groups - total
    if residual:
        by_sum: dict[int, list[RootSummary]] = {0: []}
        for root in sorted(candidates, key=lambda item: sha256_text(f"{seed}:fill:{item.root_id}")):
            if root.root_id in chosen_ids or root.groups > residual:
                continue
            snapshot = list(by_sum.items())
            for amount, picked in snapshot:
                new_amount = amount + root.groups
                if new_amount <= residual and new_amount not in by_sum:
                    by_sum[new_amount] = picked + [root]
            if residual in by_sum:
                break
        fill = by_sum.get(residual) or by_sum[max(by_sum)]
        for root in fill:
            chosen.append(root)
            chosen_ids.add(root.root_id)
    return sorted(chosen, key=lambda item: item.root_id)


def audit_current(path: Path, name: str, root_field: str) -> CurrentAudit:
    audit = CurrentAudit(name=name)
    for episode in read_jsonl(path):
        audit.update(episode, str(episode.get(root_field) or episode.get("identity", {}).get("world_instance_id")))
    return audit


def summarize_counter(values: Counter[str]) -> dict[str, int]:
    return dict(sorted(values.items()))


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p25": None, "p50": None, "p75": None}
    ordered = sorted(values)
    return {f"p{percentile}": ordered[min(len(ordered) - 1, int((percentile / 100) * (len(ordered) - 1)))] for percentile in (25, 50, 75)}


def audit_summary(audit: CurrentAudit) -> dict[str, Any]:
    return {
        "name": audit.name,
        "rows": audit.rows,
        "groups": audit.groups,
        "unique_root_families": len(audit.roots),
        "world_families": summarize_counter(audit.world_families),
        "schema_families": summarize_counter(audit.schema_families),
        "operations": summarize_counter(audit.operations),
        "unique_semantic_fingerprints": len(audit.fingerprints),
        "unique_exact_text_hashes": len(audit.text_hashes),
        "unique_normalized_text_hashes": len(audit.normalized_text_hashes),
        "unique_structural_fingerprints": len(audit.structural_fingerprints),
        "candidate_set_size": {"count": len(audit.candidate_sizes), **quantiles([float(value) for value in audit.candidate_sizes])},
        "posterior_entropy": {"count": len(audit.entropies), **quantiles(audit.entropies)},
        "distance_bins_proxy": summarize_counter(audit.distance_bins),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-episodes", type=Path, default=DEFAULT_SOURCE_EPISODES)
    parser.add_argument("--source-metadata", type=Path, default=DEFAULT_SOURCE_METADATA)
    parser.add_argument("--current-v05", type=Path, default=DEFAULT_V05_TRAIN)
    parser.add_argument("--current-v06", type=Path, default=DEFAULT_V06_TRAIN)
    parser.add_argument("--out", type=Path, default=Path("experiments/jev-curated-c100-v01"))
    parser.add_argument("--target-groups", type=int, default=100_000)
    parser.add_argument("--seed", default="jev-c100-v01")
    args = parser.parse_args()
    for path in (args.source_episodes, args.source_metadata, args.current_v05, args.current_v06):
        if not path.is_file():
            raise FileNotFoundError(path)

    current_v05 = audit_current(args.current_v05, "current_v05_s100k", "_v05_family_id")
    current_v06 = audit_current(args.current_v06, "current_v06_s250k", "_v06_family_id")
    current_roots = current_v05.roots | current_v06.roots
    current_fingerprints = current_v05.fingerprints | current_v06.fingerprints
    current_text_hashes = current_v05.text_hashes | current_v06.text_hashes
    current_normalized_hashes = current_v05.normalized_text_hashes | current_v06.normalized_text_hashes
    current_structural = current_v05.structural_fingerprints | current_v06.structural_fingerprints

    metadata: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    for row in read_jsonl(args.source_metadata):
        compact = compact_metadata(row)
        metadata[str(compact["episode_id"])] = compact
        parents[str(compact["episode_id"])] = compact["parent_episode_id"]

    roots: dict[str, RootSummary] = {}
    source_rows = 0
    source_groups = 0
    source_fingerprints: set[str] = set()
    source_text_hashes: set[str] = set()
    source_normalized_hashes: set[str] = set()
    source_structural: set[str] = set()
    source_ops: Counter[str] = Counter()
    source_lexical: Counter[str] = Counter()
    source_worlds: Counter[str] = Counter()
    for episode in read_jsonl(args.source_episodes):
        source_rows += 1
        episode_id = str(episode.get("identity", {}).get("episode_id"))
        meta = metadata.get(episode_id)
        if meta is None:
            raise ValueError(f"source episode missing metadata: {episode_id}")
        root_id = root_family_id(episode_id, parents)
        identity = episode.get("identity", {})
        root = roots.setdefault(root_id, RootSummary(root_id, str(identity.get("world_family_id"))))
        root.update(episode, meta)
        source_groups += group_count(episode)
        source_ops[meta["operation"]] += 1
        source_lexical[meta["lexical_regime"]] += 1
        source_worlds[str(identity.get("world_family_id"))] += 1
        fingerprint = str(identity.get("semantic_fingerprint", ""))
        if fingerprint:
            source_fingerprints.add(fingerprint)
        text = str((episode.get("state", {}).get("observable") or {}).get("content", ""))
        source_text_hashes.add(sha256_text(text))
        source_normalized_hashes.add(sha256_text(normalized_text(text)))
        source_structural.add(structural_fingerprint(episode))

    eligible = [
        root for root in roots.values()
        if (
            family_split(root.root_id) == "train"
            and root.root_id not in current_roots
            and not (root.text_hashes & current_text_hashes)
            and not (root.normalized_text_hashes & current_normalized_hashes)
        )
    ]
    quarantined_text_roots = [
        root for root in roots.values()
        if root.root_id not in current_roots
        and (root.text_hashes & current_text_hashes or root.normalized_text_hashes & current_normalized_hashes)
    ]
    selected = select_roots(eligible, args.target_groups, args.seed)
    selected_ids = {root.root_id for root in selected}
    selected_groups = sum(root.groups for root in selected)
    if selected_groups > args.target_groups:
        raise AssertionError("selection exceeded budget")
    if not selected:
        raise RuntimeError("no eligible candidate roots")

    out = args.out
    train_path = out / "train.jsonl"
    metadata_path = out / "selected-metadata.jsonl"
    train_path.parent.mkdir(parents=True, exist_ok=True)
    selected_episode_ids: set[str] = set()
    selected_fingerprints: set[str] = set()
    selected_text_hashes: set[str] = set()
    selected_normalized_hashes: set[str] = set()
    selected_structural: set[str] = set()
    selected_rows = 0
    selected_group_check = 0
    with train_path.open("w", encoding="utf-8", newline="\n") as train, metadata_path.open("w", encoding="utf-8", newline="\n") as meta_out:
        for episode in read_jsonl(args.source_episodes):
            episode_id = str(episode.get("identity", {}).get("episode_id"))
            root_id = root_family_id(episode_id, parents)
            if root_id not in selected_ids:
                continue
            train.write(json.dumps(episode, ensure_ascii=False, separators=(",", ":")) + "\n")
            meta = metadata[episode_id]
            selected_meta = dict(meta)
            selected_meta["root_family_id"] = root_id
            selected_meta["family_split"] = family_split(root_id)
            selected_meta["group_count"] = group_count(episode)
            selected_meta["semantic_fingerprint"] = episode.get("identity", {}).get("semantic_fingerprint")
            selected_meta["text_sha256"] = sha256_text(str((episode.get("state", {}).get("observable") or {}).get("content", "")))
            selected_meta["normalized_text_sha256"] = sha256_text(normalized_text(str((episode.get("state", {}).get("observable") or {}).get("content", ""))))
            selected_meta["structural_fingerprint"] = structural_fingerprint(episode)
            meta_out.write(json.dumps(selected_meta, ensure_ascii=False, separators=(",", ":")) + "\n")
            selected_rows += 1
            selected_group_check += group_count(episode)
            selected_episode_ids.add(episode_id)
            selected_fingerprints.add(str(episode.get("identity", {}).get("semantic_fingerprint", "")))
            text = str((episode.get("state", {}).get("observable") or {}).get("content", ""))
            selected_text_hashes.add(sha256_text(text))
            selected_normalized_hashes.add(sha256_text(normalized_text(text)))
            selected_structural.add(structural_fingerprint(episode))

    selection_rows = [
        {
            "root_family_id": root.root_id,
            "world_family": root.world_family,
            "family_split": family_split(root.root_id),
            "episode_count": root.episode_count,
            "group_count": root.groups,
            "schema_families": summarize_counter(root.schema_families),
            "operations": summarize_counter(root.operations),
            "intervention_classes": summarize_counter(root.intervention_classes),
            "lexical_regimes": summarize_counter(root.lexical_regimes),
            "candidate_profiles": summarize_counter(root.candidate_profiles),
            "candidate_set_sizes": summarize_counter(Counter(map(str, root.candidate_sizes))),
            "posterior_entropy": {"count": len(root.entropies), **quantiles(root.entropies)},
            "distance_bins_proxy": summarize_counter(root.distance_bins),
            "semantic_fingerprint_count": len(root.fingerprints),
            "structural_fingerprint_count": len(root.structural_fingerprints),
        }
        for root in selected
    ]
    selection_manifest = {
        "protocol": "jev-curated-training-c100/v0.1",
        "status": "gated_candidate_not_active_training",
        "selection_seed": args.seed,
        "target_groups": args.target_groups,
        "selected_group_count": selected_group_check,
        "budget_status": "met" if selected_group_check == args.target_groups else "underfilled_fail_closed",
        "candidate_label": "C100" if selected_group_check == args.target_groups else f"C100-underfilled-{selected_group_check}",
        "blocker": None if selected_group_check == args.target_groups else "strict non-overlap and family-safe train-only boundary leaves fewer than 100000 eligible groups",
        "smallest_safe_next_step": None if selected_group_check == args.target_groups else "add a separately audited unused source lane or approve a new semantic-family/surface boundary; do not promote this underfilled candidate as C100",
        "selected_episode_count": selected_rows,
        "selected_root_count": len(selected),
        "source_episode_count": source_rows,
        "source_group_count": source_groups,
        "source_root_count": len(roots),
        "eligible_root_count": len(eligible),
        "eligible_root_group_count": sum(root.groups for root in eligible),
        "current_root_exclusion_count": len(current_roots),
        "quarantined_exact_or_normalized_text_root_count": len(quarantined_text_roots),
        "quarantined_exact_or_normalized_text_episode_count": sum(root.episode_count for root in quarantined_text_roots),
        "eligible_world_family_counts": summarize_counter(Counter(root.world_family for root in eligible)),
        "selected_world_family_counts": summarize_counter(Counter(root.world_family for root in selected)),
        "coverage_status": "single_novel_world_family_after_current_firewall" if len({root.world_family for root in selected}) == 1 else "multi_world_family",
        "current_semantic_fingerprint_count": len(current_fingerprints),
        "root_selection_sha256": sha256_text(json.dumps(selection_rows, sort_keys=True, separators=(",", ":"))),
        "train_sha256": sha256_file(train_path),
        "metadata_sha256": sha256_file(metadata_path),
        "selection_policy": {
            "source_split": "sha256(root_family_id)[:8] mod 10: train is 2..9",
            "family_integrity": "all source episodes sharing a root parent chain are selected together",
            "exclusions": ["current v05 s100k roots", "current v06 s250k roots", "non-train source roots"],
            "objective": "coverage-first deterministic greedy over world family, entropy band, candidate density, hard-sibling proxy, operation and lexical signatures; residual filled by deterministic bounded subset sum",
            "protected_outcomes_used": False,
        },
        "selected_roots": selection_rows,
    }
    write_json(out / "selection-manifest.json", selection_manifest)

    overlap = {
        "exact_episode_id": len(selected_episode_ids & (current_v05.episode_ids | current_v06.episode_ids)),
        "semantic_fingerprint": len((selected_fingerprints - {""}) & current_fingerprints),
        "exact_text_sha256": len(selected_text_hashes & current_text_hashes),
        "normalized_text_sha256": len(selected_normalized_hashes & current_normalized_hashes),
        "structural_fingerprint": len(selected_structural & current_structural),
        "same_root_family": len(selected_ids & current_roots),
        "selected_semantic_family_collisions_with_current": len(selected_ids & current_roots),
        "note": "root-family exclusion is the semantic-family firewall; structural fingerprints are reported separately because they describe reusable task shape rather than world identity",
    }
    current_summary = {"v05": audit_summary(current_v05), "v06": audit_summary(current_v06)}
    geometry = {
        "source_training_side": {
            "world_family_counts": summarize_counter(source_worlds),
            "operation_counts": summarize_counter(source_ops),
            "lexical_regime_counts": summarize_counter(source_lexical),
            "unique_semantic_fingerprints": len(source_fingerprints),
            "unique_exact_text_hashes": len(source_text_hashes),
            "unique_normalized_text_hashes": len(source_normalized_hashes),
            "unique_structural_fingerprints": len(source_structural),
            "posterior_entropy": {"count": sum(len(root.entropies) for root in roots.values()), **quantiles([value for root in roots.values() for value in root.entropies])},
        },
        "selected": {
            "world_family_counts": dict(Counter(row["world_family"] for row in selection_rows)),
            "coverage_status": "single_novel_world_family_after_current_firewall" if len({row["world_family"] for row in selection_rows}) == 1 else "multi_world_family",
            "root_count": len(selection_rows),
            "groups": selected_group_check,
            "episodes": selected_rows,
            "operation_counts": dict(Counter(op for row in selection_rows for op, count in row["operations"].items() for _ in range(count))),
            "lexical_regime_counts": dict(Counter(regime for row in selection_rows for regime, count in row["lexical_regimes"].items() for _ in range(count))),
            "candidate_profile_counts": dict(Counter(profile for row in selection_rows for profile, count in row["candidate_profiles"].items() for _ in range(count))),
            "candidate_set_size_counts": dict(Counter(size for row in selection_rows for size, count in row["candidate_set_sizes"].items() for _ in range(int(count)))),
            "posterior_entropy": {"count": sum(len(root.entropies) for root in selected), **quantiles([value for root in selected for value in root.entropies])},
            "semantic_family_count": len(selected_ids),
            "semantic_fingerprint_count": len(selected_fingerprints - {""}),
            "structural_fingerprint_count": len(selected_structural),
        },
        "unavailable_or_proxy": {
            "canonical_D1_D2_D4_competitor_balance": "unavailable; only generator candidate_distances exist, so D1_proxy/D2_proxy/D4_proxy are diagnostic",
            "causal_topology": "unavailable in v06 stress metadata; v04 known_v03_topology is a training-side placeholder, not promoted here",
            "intervention_magnitude": "unavailable as a numeric magnitude; intervention classes and gold posterior entropy are available",
            "opaque_definition_schema_variation": "candidate_profiles are available; numeric schema variation beyond profile labels is unavailable",
            "protected_evaluation_outcomes": "not read and not used",
        },
    }
    write_json(out / "current-set-audit.json", current_summary)
    write_json(out / "overlap-audit.json", overlap)
    write_json(out / "geometry-audit.json", geometry)
    write_json(out / "source-receipt.json", {
        "source_episodes": {"path": str(args.source_episodes), "bytes": args.source_episodes.stat().st_size, "sha256": sha256_file(args.source_episodes)},
        "source_metadata": {"path": str(args.source_metadata), "bytes": args.source_metadata.stat().st_size, "sha256": sha256_file(args.source_metadata)},
        "current_v05_train": {"path": str(args.current_v05), "bytes": args.current_v05.stat().st_size, "sha256": sha256_file(args.current_v05)},
        "current_v06_train": {"path": str(args.current_v06), "bytes": args.current_v06.stat().st_size, "sha256": sha256_file(args.current_v06)},
    })
    print(json.dumps({"out": str(out), "selected_groups": selected_group_check, "selected_episodes": selected_rows, "selected_roots": len(selected), "overlap": overlap}, indent=2))


if __name__ == "__main__":
    main()
