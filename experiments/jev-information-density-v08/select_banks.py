"""Family-safe, metadata-only R100/C100 selector for v0.8 group records.

The program never loads a model, reads predictions, or prints observable text.
Input is a compact metadata JSONL emitted by the separately versioned world
generator. All output belongs in an external run directory.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import heapq
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CONTRACT_PATH = Path(__file__).with_name("v08-contract.json")
GROUP_LIMIT = 100_000
MIN_ELIGIBLE = 300_000
HOLDOUT_FRACTION = 0.20
HOLDOUT_SALT = "jev-idv08-family-bundle-holdout-sha256-v1"
RANDOM_SEED = "jev-idv08-r100-sha256-v1"
CURATED_SEED = "jev-idv08-c100-sha256-v3-static-frequency-coverage"
FAMILY_AXES = (
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
)
COVERAGE_AXES = (
    "semantic_novelty",
    "local_discrimination",
    "probability_geometry",
    "structural_coverage",
    "redundancy",
)
STRATUM_FIELDS = (
    "world_family",
    "query_view_type",
    "candidate_cardinality_bin",
    "posterior_entropy_quintile",
)
GROUP_FIELDS = {
    "group_id",
    "episode_id",
    "root_id",
    "valid",
    "family_ids",
    "strata",
    "coverage_features",
    "overlap_keys",
    "split_family_bundle_id",
    "posterior_entropy_nats",
}


@dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    episode_id: str
    root_id: str
    families: tuple[tuple[str, str], ...]
    strata: tuple[str, ...]
    features: tuple[tuple[str, ...], ...]
    overlap_keys: tuple[str, ...]
    split_family_bundle_id: str
    posterior_entropy_nats: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(seed: str, value: str) -> bytes:
    return hashlib.sha256(f"{seed}|{value}".encode("utf-8")).digest()


def read_group_records(path: Path) -> list[Group]:
    groups: list[Group] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if set(row) != GROUP_FIELDS:
                missing = sorted(GROUP_FIELDS - set(row))
                extra = sorted(set(row) - GROUP_FIELDS)
                raise ValueError(f"group record fields at line {line_number}: missing={missing}, extra={extra}")
            group_id = str(row["group_id"])
            if not group_id or group_id in seen:
                raise ValueError(f"empty or duplicate group_id at line {line_number}: {group_id!r}")
            seen.add(group_id)
            if row["valid"] is not True:
                continue
            families = row["family_ids"]
            if not isinstance(families, dict) or set(families) != set(FAMILY_AXES):
                raise ValueError(
                    f"family_ids must provide exactly the frozen axes at line {line_number}"
                )
            family_items = tuple(
                (axis, str(families[axis]))
                for axis in FAMILY_AXES
                if families.get(axis) not in (None, "", "none", "unknown")
            )
            if len(family_items) != len(FAMILY_AXES):
                raise ValueError(f"empty or unknown family ID at line {line_number}")
            strata_obj = row["strata"]
            strata = tuple(str(strata_obj[field]) for field in STRATUM_FIELDS)
            coverage = row["coverage_features"]
            features: list[tuple[str, ...]] = []
            for axis in COVERAGE_AXES:
                values = coverage.get(axis)
                if not isinstance(values, list) or not values:
                    raise ValueError(f"missing coverage features for {axis} at line {line_number}")
                features.append(tuple(sorted({str(value) for value in values})))
            overlap_keys = tuple(sorted({str(value) for value in row["overlap_keys"]}))
            input_digests = [
                key.removeprefix("model_input:")
                for key in overlap_keys
                if key.startswith("model_input:")
            ]
            if len(input_digests) != 1:
                raise ValueError(f"group needs exactly one model_input digest at line {line_number}")
            redundancy_index = COVERAGE_AXES.index("redundancy")
            features[redundancy_index] = tuple(
                sorted(set(features[redundancy_index]) | {f"input:{input_digests[0]}"})
            )
            groups.append(
                Group(
                    group_id=group_id,
                    episode_id=str(row["episode_id"]),
                    root_id=str(row["root_id"]),
                    families=family_items,
                    strata=strata,
                    features=tuple(features),
                    overlap_keys=overlap_keys,
                    split_family_bundle_id=str(row["split_family_bundle_id"]),
                    posterior_entropy_nats=float(row["posterior_entropy_nats"]),
                )
            )
    return groups


def read_registry(paths: Iterable[Path]) -> tuple[set[str], dict[str, int]]:
    keys: set[str] = set()
    counts: dict[str, int] = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"required firewall registry missing: {path}")
        count = 0
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                row_keys = row.get("overlap_keys")
                if not isinstance(row_keys, list):
                    raise ValueError(f"registry row needs overlap_keys: {path}:{line_number}")
                keys.update(str(key) for key in row_keys)
                count += 1
        counts[str(path)] = count
    return keys, counts


def audit_input_target_consistency(groups: Iterable[Group]) -> dict[str, int]:
    """Fail closed if one model-visible input maps to incompatible exact gold."""
    targets_by_input: dict[str, set[str]] = defaultdict(set)
    input_counts: Counter[str] = Counter()
    for group in groups:
        inputs = [key.removeprefix("model_input:") for key in group.overlap_keys if key.startswith("model_input:")]
        targets = [key.removeprefix("gold_target:") for key in group.overlap_keys if key.startswith("gold_target:")]
        if len(inputs) != 1 or len(targets) != 1:
            raise ValueError(f"group {group.group_id} requires exactly one model_input and gold_target digest")
        targets_by_input[inputs[0]].add(targets[0])
        input_counts[inputs[0]] += 1
    conflicts = {key: values for key, values in targets_by_input.items() if len(values) > 1}
    return {
        "group_count": sum(input_counts.values()),
        "unique_model_input_count": len(targets_by_input),
        "duplicate_input_occurrence_count": sum(count - 1 for count in input_counts.values() if count > 1),
        "conflicting_model_input_count": len(conflicts),
        "max_gold_signatures_per_input": max((len(values) for values in targets_by_input.values()), default=0),
    }


def is_held_out(bundle_id: str) -> bool:
    digest = hashlib.sha256(
        f"{HOLDOUT_SALT}|family_bundle|{bundle_id}".encode("utf-8")
    ).digest()
    threshold = int(HOLDOUT_FRACTION * (1 << 256))
    return int.from_bytes(digest, "big") < threshold


def split_families(groups: list[Group]) -> tuple[list[Group], list[tuple[Group, tuple[str, ...]]], dict[str, Any]]:
    all_values: dict[str, set[str]] = defaultdict(set)
    family_owner: dict[tuple[str, str], str] = {}
    root_owner: dict[str, str] = {}
    episode_owner: dict[str, str] = {}
    bundle_axes: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    bundle_roots: dict[str, set[str]] = defaultdict(set)
    bundle_episodes: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        bundle = group.split_family_bundle_id
        if not bundle:
            raise ValueError(f"empty split_family_bundle_id for {group.group_id}")
        for axis, value in group.families:
            all_values[axis].add(value)
            key = (axis, value)
            owner = family_owner.setdefault(key, bundle)
            if owner != bundle:
                raise ValueError(
                    f"family value crosses split bundles: axis={axis} value={value} "
                    f"bundles={owner},{bundle}"
                )
            bundle_axes[bundle][axis].add(value)
        for owners, identity, label in (
            (root_owner, group.root_id, "root"),
            (episode_owner, group.episode_id, "episode"),
        ):
            owner = owners.setdefault(identity, bundle)
            if owner != bundle:
                raise ValueError(
                    f"{label} crosses split bundles: id={identity} bundles={owner},{bundle}"
                )
        bundle_roots[bundle].add(group.root_id)
        bundle_episodes[bundle].add(group.episode_id)

    bundles = set(bundle_axes)
    held_out_bundles = {bundle for bundle in bundles if is_held_out(bundle)}
    train: list[Group] = []
    evaluation: list[tuple[Group, tuple[str, ...]]] = []
    for group in groups:
        if group.split_family_bundle_id in held_out_bundles:
            evaluation.append((group, tuple(axis for axis, _ in group.families)))
        else:
            train.append(group)
    axis_report = {
        axis: {
            "family_value_count": len(values),
            "held_out_family_count": sum(
                owner in held_out_bundles
                for (family_axis, _value), owner in family_owner.items()
                if family_axis == axis
            ),
            "retained_family_count": sum(
                owner not in held_out_bundles
                for (family_axis, _value), owner in family_owner.items()
                if family_axis == axis
            ),
            "available": len(values) >= 2
            and any(
                owner in held_out_bundles
                for (family_axis, _value), owner in family_owner.items()
                if family_axis == axis
            )
            and any(
                owner not in held_out_bundles
                for (family_axis, _value), owner in family_owner.items()
                if family_axis == axis
            ),
            "held_out_family_ids_sha256": hashlib.sha256(
                "\n".join(sorted(
                    value for (family_axis, value), owner in family_owner.items()
                    if family_axis == axis and owner in held_out_bundles
                )).encode("utf-8")
            ).hexdigest(),
        }
        for axis, values in sorted(all_values.items())
    }
    axis_report["split_family_bundle"] = {
        "bundle_count": len(bundles),
        "held_out_bundle_count": len(held_out_bundles),
        "retained_bundle_count": len(bundles - held_out_bundles),
        "held_out_group_count": len(evaluation),
        "retained_group_count": len(train),
        "held_out_bundle_ids_sha256": hashlib.sha256(
            "\n".join(sorted(held_out_bundles)).encode("utf-8")
        ).hexdigest(),
        "root_count_by_bundle_sha256": hashlib.sha256(
            "\n".join(
                f"{bundle}:{len(bundle_roots[bundle])}:{len(bundle_episodes[bundle])}"
                for bundle in sorted(bundles)
            ).encode("utf-8")
        ).hexdigest(),
    }
    return train, evaluation, axis_report


def assign_training_entropy_quintiles(groups: list[Group]) -> list[Group]:
    """Assign entropy bins using eligible training rows only, never NewTight-Eval."""
    import dataclasses

    if not groups:
        return []
    values = sorted(group.posterior_entropy_nats for group in groups)
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("posterior entropy must be finite and nonnegative")
    thresholds = [values[min(len(values) - 1, math.floor(len(values) * q / 5))] for q in range(1, 5)]
    result: list[Group] = []
    for group in groups:
        quintile = bisect.bisect_right(thresholds, group.posterior_entropy_nats) + 1
        strata = (*group.strata[:3], f"q{quintile}")
        result.append(dataclasses.replace(group, strata=strata))
    return result


def group_stratum(group: Group) -> str:
    return json.dumps(group.strata, ensure_ascii=False, separators=(",", ":"))


def select_random(groups: list[Group], count: int = GROUP_LIMIT) -> list[Group]:
    buckets: dict[str, list[Group]] = defaultdict(list)
    for group in groups:
        buckets[group_stratum(group)].append(group)
    total = len(groups)
    if total < count:
        raise ValueError(f"R100 requires {count} groups; eligible universe has {total}")
    quotas = {key: (len(values) * count) // total for key, values in buckets.items()}
    remaining = count - sum(quotas.values())
    fractional = sorted(
        buckets,
        key=lambda key: (-(len(buckets[key]) * count % total), key),
    )
    for key in fractional[:remaining]:
        quotas[key] += 1
    selected: list[Group] = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda group: (stable_digest(RANDOM_SEED, group.group_id), group.group_id))
        selected.extend(rows[:quotas[key]])
    if len(selected) != count:
        raise AssertionError(f"R100 selected {len(selected)}, expected {count}")
    return selected


def select_curated(groups: list[Group], count: int = GROUP_LIMIT) -> list[Group]:
    if len(groups) < count:
        raise ValueError(f"C100 requires {count} groups; eligible universe has {len(groups)}")
    feature_counts = [
        Counter(feature for group in groups for feature in group.features[axis_index])
        for axis_index in range(len(COVERAGE_AXES))
    ]

    def ranked(index_and_group: tuple[int, Group]) -> tuple[float, bytes, str, int]:
        index, group = index_and_group
        axis_scores = [
            sum(1.0 / math.sqrt(feature_counts[axis_index][feature]) for feature in values) / len(values)
            for axis_index, values in enumerate(group.features)
            if values
        ]
        score = sum(axis_scores) / len(axis_scores)
        return (-score, stable_digest(CURATED_SEED, group.group_id), group.group_id, index)

    # A global rarity score preserves the equal-weight coverage objective while
    # avoiding the quadratic stale-score churn of exact dynamic greedy updates.
    best = heapq.nsmallest(count, enumerate(groups), key=ranked)
    return [groups[index] for index, _group in best]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ids(path: Path, groups: Iterable[Group]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for group in groups:
            stream.write(json.dumps({"group_id": group.group_id, "episode_id": group.episode_id}, separators=(",", ":")))
            stream.write("\n")


def key_type(key: str) -> str:
    return key.split(":", 1)[0]


def collision_report(groups: list[Group], registry_keys: set[str]) -> dict[str, Any]:
    collision_groups: list[str] = []
    group_counts: Counter[str] = Counter()
    key_counts: Counter[str] = Counter()
    for group in groups:
        matches = registry_keys.intersection(group.overlap_keys)
        if not matches:
            continue
        collision_groups.append(group.group_id)
        group_counts.update({key_type(key) for key in matches})
        key_counts.update(matches)
    return {
        "collision_group_count": len(collision_groups),
        "collision_group_ids_sha256": hashlib.sha256(
            "\n".join(sorted(collision_groups)).encode("utf-8")
        ).hexdigest(),
        "collision_groups_by_key_type": dict(sorted(group_counts.items())),
        "distinct_collision_keys_by_type": dict(sorted(
            Counter({kind: sum(key_type(key) == kind for key in key_counts) for kind in group_counts}).items()
        )),
    }


def topology_coverage(groups: Iterable[Group]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for group in groups:
        for value in group.features[3]:
            if value.startswith("topology:"):
                counts[value.removeprefix("topology:")] += 1
    return dict(sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--registry", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-eligible", type=int, default=MIN_ELIGIBLE)
    parser.add_argument("--target", type=int, default=GROUP_LIMIT)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {args.out}")
    args.out.mkdir(parents=True, exist_ok=True)

    groups = read_group_records(args.group_records)
    input_consistency = audit_input_target_consistency(groups)
    if input_consistency["conflicting_model_input_count"]:
        consistency_receipt = {
            "contract": "jev-decision-data-information-density/v0.8",
            "group_records_sha256": sha256_file(args.group_records),
            **input_consistency,
            "status": "FAIL",
        }
        conflict_report = {
            "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "selector_source_sha256": sha256_file(Path(__file__)),
            "group_records_sha256": sha256_file(args.group_records),
            "raw_valid_group_count": len(groups),
            "input_target_consistency": consistency_receipt,
            "model_outputs_or_features_read": False,
            "protected_text_exported": False,
            "training_banks_materialized": False,
            "status": "input_target_conflict",
        }
        write_json(args.out / "preselection-audit.json", conflict_report)
        write_json(args.out / "input-target-consistency.json", consistency_receipt)
        write_json(args.out / "new-universe-novelty-audit.json", conflict_report)
        return
    registry_keys, registry_counts = read_registry(args.registry)
    unique_families = len({group.root_id for group in groups})
    source_overlap = collision_report(groups, registry_keys)
    firewall_hits = source_overlap["collision_group_count"]
    clean_groups = [group for group in groups if not registry_keys.intersection(group.overlap_keys)]
    train_pool, eval_pairs, split_report = split_families(clean_groups)
    train_pool = assign_training_entropy_quintiles(train_pool)
    valid_axes = {axis: split_report[axis]["available"] for axis in FAMILY_AXES}
    eligible_count = len(train_pool)
    contract_hash = sha256_file(CONTRACT_PATH)
    report: dict[str, Any] = {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": contract_hash,
        "group_records_sha256": sha256_file(args.group_records),
        "registry_sha256": {str(path): sha256_file(path) for path in args.registry},
        "registry_record_counts": registry_counts,
        "raw_valid_group_count": len(groups),
        "unique_root_world_count": unique_families,
        "legacy_firewall_collision_group_count": firewall_hits,
        "clean_group_count": len(clean_groups),
        "new_tight_eval_group_count": len(eval_pairs),
        "eligible_training_group_count": eligible_count,
        "held_out_family_axes": split_report,
        "held_out_axis_availability": valid_axes,
        "input_target_consistency": {
            "contract": "jev-decision-data-information-density/v0.8",
            "group_records_sha256": sha256_file(args.group_records),
            **input_consistency,
            "status": "PASS",
        },
        "model_outputs_or_features_read": False,
        "protected_text_exported": False,
        "training_banks_materialized": False,
        "status": "insufficient_selection_surplus" if eligible_count < max(args.minimum_eligible, args.target) else "ready_for_selection",
    }
    write_json(args.out / "preselection-audit.json", report)
    write_json(args.out / "input-target-consistency.json", input_consistency)
    write_json(args.out / "source-overlap-report.json", {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": contract_hash,
        "group_records_sha256": report["group_records_sha256"],
        "registry_sha256": report["registry_sha256"],
        "registry_record_counts": registry_counts,
        "selector_source_sha256": sha256_file(Path(__file__)),
        **source_overlap,
        "protected_text_exported": False,
        "model_outputs_or_features_read": False,
    })
    write_json(args.out / "new-universe-novelty-audit.json", {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": contract_hash,
        "group_records_sha256": report["group_records_sha256"],
        "generation_receipt_sha256": sha256_file(args.group_records.parent / "generation-receipt.json"),
        "raw_valid_group_count": len(groups),
        "legacy_firewall_collision_group_count": firewall_hits,
        "clean_group_count": len(clean_groups),
        "new_tight_eval_group_count": len(eval_pairs),
        "eligible_training_group_count": eligible_count,
        "family_axis_coverage": split_report,
        "heldout_topology_coverage": topology_coverage(group for group, _ in eval_pairs),
        "retained_topology_coverage": topology_coverage(train_pool),
        "input_target_consistency": report["input_target_consistency"],
        "overcomplete_minimum_eligible_groups": args.minimum_eligible,
        "status": report["status"],
        "model_outputs_or_features_read": False,
        "protected_text_exported": False,
    })
    eval_rows = [
        {
            "group_id": group.group_id,
            "episode_id": group.episode_id,
            "split_family_bundle_id": group.split_family_bundle_id,
            "held_out_axes": list(axes),
            "held_out_family_ids": dict(group.families),
        }
        for group, axes in eval_pairs
    ]
    eval_manifest = args.out / "new-tight-eval-group-ids.jsonl"
    with eval_manifest.open("w", encoding="utf-8", newline="\n") as stream:
        for row in eval_rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    write_json(args.out / "ood-family-split.json", {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": contract_hash,
        "split_family_bundle": split_report["split_family_bundle"],
        "axes": {axis: split_report[axis] for axis in FAMILY_AXES},
        "heldout_topology_coverage": topology_coverage(group for group, _ in eval_pairs),
        "retained_topology_coverage": topology_coverage(train_pool),
        "eval_group_count": len(eval_rows),
        "eval_manifest_sha256": sha256_file(eval_manifest),
        "family_ids_in_sidecar": True,
        "composite_ood_not_factorial_estimate": True,
        "model_outputs_or_features_read": False,
    })
    if report["status"] != "ready_for_selection":
        return

    random_rows = select_random(train_pool, args.target)
    curated_rows = select_curated(train_pool, args.target)
    random_ids = {group.group_id for group in random_rows}
    curated_ids = {group.group_id for group in curated_rows}
    write_ids(args.out / "new-tight-r100-group-ids.jsonl", random_rows)
    write_ids(args.out / "new-tight-c100-group-ids.jsonl", curated_rows)
    eval_manifest_hash = sha256_file(eval_manifest)
    report.update({
        "status": "selectors_materialized_pretraining_lock",
        "random_group_count": len(random_rows),
        "curated_group_count": len(curated_rows),
        "random_curated_group_overlap": len(random_ids & curated_ids),
        "random_unique_root_count": len({group.root_id for group in random_rows}),
        "curated_unique_root_count": len({group.root_id for group in curated_rows}),
        "r100_manifest_sha256": sha256_file(args.out / "new-tight-r100-group-ids.jsonl"),
        "c100_manifest_sha256": sha256_file(args.out / "new-tight-c100-group-ids.jsonl"),
        "eval_manifest_sha256": eval_manifest_hash,
        "training_banks_materialized": False,
        "model_contact_authorized": False,
        "selector_source_sha256": sha256_file(Path(__file__)),
        "random_selector_seed": RANDOM_SEED,
        "curated_selector_seed": CURATED_SEED,
        "curated_policy": "deterministic_one_pass_global_rarity_weighted_coverage_with_model_input_redundancy",
    })
    write_json(args.out / "r100-c100-selection-audit.json", report)


if __name__ == "__main__":
    main()
