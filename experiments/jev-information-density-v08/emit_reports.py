"""Emit count-only v0.8 reports after ID-manifest selection; never export text."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from select_banks import FAMILY_AXES, sha256_file


PREFIXES = (
    "group",
    "episode",
    "root",
    "semantic",
    "text",
    "text_exact",
    "schema_surface",
    "model_input",
    "structural",
    "world_family",
    "ontology_family",
    "schema_composition",
    "generator_template",
    "definition_template",
    "intervention_family",
)
CURVE_PREFIXES = (
    "root",
    "semantic",
    "text",
    "schema_surface",
    "model_input",
    "structural",
    "world_family",
    "ontology_family",
    "definition_template",
    "intervention_family",
)
CHECKPOINT = 10_000


def sha256_tree(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    files = sorted(
        file
        for path in paths
        for file in (path.rglob("*") if path.is_dir() else [path])
        if file.is_file() and "__pycache__" not in file.parts and "target" not in file.parts
    )
    for file in files:
        relative = str(file).replace("\\", "/").encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content_hash = bytes.fromhex(sha256_file(file))
        digest.update(content_hash)
    return digest.hexdigest()


def read_manifest_ids(path: Path) -> set[str]:
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row.get("group_id")
            if not isinstance(group_id, str) or not group_id:
                raise ValueError(f"missing group_id at {path}:{line_number}")
            if group_id in result:
                raise ValueError(f"duplicate group ID at {path}:{line_number}")
            result.add(group_id)
    return result


def overlap_values(row: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in row["overlap_keys"]:
        prefix, separator, value = str(key).partition(":")
        if separator and prefix in PREFIXES:
            values.setdefault(prefix, value)
    return values


def entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


class Census:
    def __init__(self) -> None:
        self.count = 0
        self.values: dict[str, set[str]] = {prefix: set() for prefix in PREFIXES}
        self.family_values: dict[str, set[str]] = {axis: set() for axis in FAMILY_AXES}
        self.input_frequency: Counter[str] = Counter()
        self.query_views: Counter[str] = Counter()
        self.cardinality_bins: Counter[str] = Counter()
        self.entropy_bands: Counter[str] = Counter()
        self.world_families: Counter[str] = Counter()
        self.entropy_quintiles: Counter[str] = Counter()
        self.strata: Counter[str] = Counter()
        self.feature_values: dict[str, set[str]] = defaultdict(set)

    def add(
        self,
        row: dict[str, Any],
        include_probability_metadata: bool = True,
        entropy_quintile: str | None = None,
    ) -> None:
        self.count += 1
        values = overlap_values(row)
        for prefix, value in values.items():
            self.values[prefix].add(value)
        input_key = values.get("model_input")
        if input_key is not None:
            self.input_frequency[input_key] += 1
        for axis, value in row["family_ids"].items():
            self.family_values[axis].add(str(value))
        for axis, features in row["coverage_features"].items():
            self.feature_values[axis].update(str(feature) for feature in features)
        input_digest = values.get("model_input")
        if input_digest is not None:
            self.feature_values["redundancy"].add(f"input:{input_digest}")
        strata = row["strata"]
        world_family = str(strata["world_family"])
        query_view = str(strata["query_view_type"])
        cardinality = str(strata["candidate_cardinality_bin"])
        entropy_quintile = entropy_quintile or str(strata["posterior_entropy_quintile"])
        self.world_families[world_family] += 1
        self.query_views[query_view] += 1
        self.cardinality_bins[cardinality] += 1
        self.entropy_quintiles[entropy_quintile] += 1
        stratum_key = json.dumps(
            [world_family, query_view, cardinality, entropy_quintile],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.strata[stratum_key] += 1
        if include_probability_metadata:
            self.entropy_bands[entropy_band(float(row["posterior_entropy_nats"]))] += 1


def training_entropy_thresholds(group_records: Path, eval_ids: set[str]) -> list[float]:
    """Reproduce selector quintiles from eligible training rows only."""
    values: list[float] = []
    with group_records.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row["group_id"]) not in eval_ids:
                values.append(float(row["posterior_entropy_nats"]))
    if not values:
        raise ValueError("cannot derive training entropy quintiles from an empty eligible pool")
    values.sort()
    return [values[min(len(values) - 1, (len(values) * q) // 5)] for q in range(1, 5)]


def entropy_quintile_for(value: float, thresholds: list[float]) -> str:
    return f"q{bisect.bisect_right(thresholds, value) + 1}"

    def report(self) -> dict[str, Any]:
        unique_inputs = len(self.values["model_input"])
        return {
            "group_count": self.count,
            "unique_counts_by_signature": {
                key: len(values) for key, values in sorted(self.values.items())
            },
            "unique_root_world_count": len(self.values["root"]),
            "unique_model_input_count": unique_inputs,
            "repeated_model_input_occurrences": self.count - unique_inputs,
            "model_input_unique_fraction": unique_inputs / self.count if self.count else 0.0,
            "unique_model_inputs_per_10000_groups": 10_000 * unique_inputs / self.count if self.count else 0.0,
            "mean_occurrences_per_unique_model_input": self.count / unique_inputs if unique_inputs else None,
            "input_frequency_histogram": {
                str(count): frequency
                for count, frequency in sorted(Counter(self.input_frequency.values()).items())
            },
            "family_value_counts": {
                key: len(values) for key, values in sorted(self.family_values.items())
            },
            "coverage_feature_cardinality": {
                key: len(values) for key, values in sorted(self.feature_values.items())
            },
            "query_view_counts": dict(sorted(self.query_views.items())),
            "world_family_counts": dict(sorted(self.world_families.items())),
            "candidate_cardinality_bin_counts": dict(sorted(self.cardinality_bins.items())),
            "posterior_entropy_quintile_counts": dict(sorted(self.entropy_quintiles.items())),
            "gold_entropy_band_counts": dict(sorted(self.entropy_bands.items())),
            "selection_stratum_counts": dict(sorted(self.strata.items())),
        }


def normalized_counts(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {key: value / total for key, value in counts.items()} if total else {}


def total_variation(left: dict[str, int], right: dict[str, int]) -> float:
    left_p = normalized_counts(left)
    right_p = normalized_counts(right)
    categories = set(left_p) | set(right_p)
    return 0.5 * sum(abs(left_p.get(key, 0.0) - right_p.get(key, 0.0)) for key in categories)


def selection_composition_report(random: dict[str, Any], curated: dict[str, Any]) -> dict[str, Any]:
    dimensions = {
        "world_family": "world_family_counts",
        "query_view_type": "query_view_counts",
        "candidate_cardinality_bin": "candidate_cardinality_bin_counts",
        "posterior_entropy_quintile": "posterior_entropy_quintile_counts",
        "gold_entropy_band": "gold_entropy_band_counts",
    }
    marginal_comparisons: dict[str, Any] = {}
    for label, field in dimensions.items():
        random_counts = random[field]
        curated_counts = curated[field]
        marginal_comparisons[label] = {
            "r100_counts": random_counts,
            "c100_counts": curated_counts,
            "r100_proportions": normalized_counts(random_counts),
            "c100_proportions": normalized_counts(curated_counts),
            "total_variation_distance": total_variation(random_counts, curated_counts),
        }
    random_strata = random["selection_stratum_counts"]
    curated_strata = curated["selection_stratum_counts"]
    all_strata = set(random_strata) | set(curated_strata)
    strata_match = all(random_strata.get(key, 0) == curated_strata.get(key, 0) for key in all_strata)
    r_unique = random["unique_model_input_count"]
    c_unique = curated["unique_model_input_count"]
    return {
        "unit": "selected atomic decision groups",
        "same_group_budget": random["group_count"] == curated["group_count"],
        "group_count": {"r100": random["group_count"], "c100": curated["group_count"]},
        "exact_predeclared_strata_match": strata_match,
        "r100_selection_stratum_counts": random_strata,
        "c100_selection_stratum_counts": curated_strata,
        "marginal_comparisons": marginal_comparisons,
        "model_visible_input_coverage": {
            "r100_unique_inputs": r_unique,
            "c100_unique_inputs": c_unique,
            "r100_unique_fraction": random["model_input_unique_fraction"],
            "c100_unique_fraction": curated["model_input_unique_fraction"],
            "c100_minus_r100_unique_input_count": c_unique - r_unique,
            "c100_minus_r100_unique_input_fraction": (
                curated["model_input_unique_fraction"] - random["model_input_unique_fraction"]
            ),
            "r100_repeated_occurrences": random["repeated_model_input_occurrences"],
            "c100_repeated_occurrences": curated["repeated_model_input_occurrences"],
        },
        "interpretation": (
            "R100 and C100 have equal group budgets, but C100 is not matched to R100's broad "
            "strata unless exact_predeclared_strata_match is true. Any future R100/C100 model "
            "difference estimates the total effect of the frozen selection policy, including "
            "task/entropy reweighting; it must not be attributed solely to within-stratum "
            "information density."
        ),
        "model_outputs_or_features_read": False,
        "protected_text_exported": False,
    }


def update_curve_sets(sets: dict[str, set[str]], row: dict[str, Any]) -> None:
    values = overlap_values(row)
    for prefix in CURVE_PREFIXES:
        if prefix in values:
            sets[prefix].add(values[prefix])


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite report: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_legacy_manifest(path: Path, kind: str) -> dict[str, Any]:
    source = json.loads(path.read_text(encoding="utf-8"))
    if kind == "old100":
        scale = source["scales"]["100000"]
        summary = {
            "manifest_group_count": scale["train_group_count_estimate"],
            "training_episode_count": scale["train_episode_count"],
            "root_world_count": scale["unique_parent_worlds"],
            "ontology_family_count": scale["unique_ontology_families"],
            "schema_instance_count": scale["unique_schema_instances"],
        }
    elif kind == "old250":
        summary = {
            "manifest_group_count": source["selected_group_count"],
            "training_episode_count": source["train_episode_count"],
            "root_world_count": source["selected_root_world_count"],
            "selected_family_count": len(source["selected_families"]),
            "schema_instance_count": None,
        }
    else:
        raise ValueError(f"unknown legacy manifest kind: {kind}")
    return {"manifest_path": str(path), "manifest_sha256": sha256_file(path), **summary}


class RegistryProjectionCensus:
    """Count-only view of old canonical query projections; not canonical bank groups."""

    def __init__(self) -> None:
        self.count = 0
        self.values: dict[str, set[str]] = {prefix: set() for prefix in PREFIXES}
        self.input_frequency: Counter[str] = Counter()

    def add(self, row: dict[str, Any]) -> None:
        self.count += 1
        for prefix, value in overlap_values(row).items():
            self.values[prefix].add(value)
        input_value = next(
            (key.removeprefix("model_input:") for key in row["overlap_keys"] if key.startswith("model_input:")),
            None,
        )
        if input_value is not None:
            self.input_frequency[input_value] += 1

    def report(self) -> dict[str, Any]:
        unique_inputs = len(self.values["model_input"])
        return {
            "registry_projection_row_count": self.count,
            "unique_counts_by_signature": {key: len(value) for key, value in sorted(self.values.items())},
            "unique_model_input_count": unique_inputs,
            "repeated_input_occurrences": self.count - unique_inputs,
            "unique_model_inputs_per_10000_projection_rows": 10_000 * unique_inputs / self.count if self.count else 0.0,
            "input_frequency_histogram": {
                str(count): frequency
                for count, frequency in sorted(Counter(self.input_frequency.values()).items())
            },
            "unit_warning": "registry query projection rows are not the source bank's canonical atomic group count",
        }


def read_legacy_registry_projections(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    sources = {
        "v05-s100k-train": "Old100",
        "v06-s250k-train": "Old250",
        "StrictNovel93": "StrictNovel93",
    }
    censuses = {name: RegistryProjectionCensus() for name in sources.values()}
    curves: dict[str, list[dict[str, Any]]] = {name: [] for name in sources.values()}
    curve_sets: dict[str, dict[str, set[str]]] = {
        name: {prefix: set() for prefix in CURVE_PREFIXES} for name in sources.values()
    }
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            label = sources.get(str(row.get("source_id")))
            if label is None:
                continue
            censuses[label].add(row)
            values = overlap_values(row)
            for prefix in CURVE_PREFIXES:
                if prefix in values:
                    curve_sets[label][prefix].add(values[prefix])
            count = censuses[label].count
            if count % CHECKPOINT == 0:
                curves[label].append({
                    "registry_projection_ordinal": count,
                    "unique_counts": {key: len(value) for key, value in sorted(curve_sets[label].items())},
                })
    reports = {name: census.report() for name, census in censuses.items()}
    for name, census in censuses.items():
        if census.count and (not curves[name] or curves[name][-1]["registry_projection_ordinal"] != census.count):
            curves[name].append({
                "registry_projection_ordinal": census.count,
                "unique_counts": {key: len(value) for key, value in sorted(curve_sets[name].items())},
            })
    return reports, curves


def old_tail_audit(source_audit: dict[str, Any]) -> dict[str, Any]:
    source_hashes = {row["source_id"]: row["sha256"] for row in source_audit["sources"]}
    return {
        "contract": "jev-decision-data-information-density/v0.8",
        "provenance": "read-only subagent audit of prior training-side banks; not independently recomputed in this report pass",
        "sources": {
            "old100_path": "D:/codex-runs/jev-frozen-scaling-v05/banks/s100k/train.jsonl",
            "old100_sha256": source_hashes.get("v05-s100k-train"),
            "old250_path": "D:/codex-runs/jev-frozen-scaling-v06/banks/s250k/train.jsonl",
            "old250_sha256": source_hashes.get("v06-s250k-train"),
        },
        "tail_definition": {
            "serialized_group_ordinals": [100001, 250000],
            "not_true_set_difference": True,
            "reason": "v0.6 source ordering/family lineage means this ordinal tail is not Old250 minus Old100",
        },
        "counts": {
            "tail_groups": 150000,
            "tail_episodes": 37501,
            "tail_roots": 1861,
            "tail_rows_under_root_family_ids_also_selected_in_old100": 48472,
            "tail_rows_under_root_family_ids_absent_from_old100": 101528,
            "of_absent_family_rows_with_earlier_rows": 599,
            "mean_groups_per_root": 80.6,
            "median_groups_per_root": 80,
            "min_groups_per_root": 21,
            "max_groups_per_root": 84,
        },
        "overlap_with_old100": {
            "episode_ids": 22346,
            "semantic_fingerprint_matches_among_overlapping_episodes": 37,
            "candidate_aligned_gold_matches": {"matching_group_ids": 3804, "compared_group_ids": 89384},
        },
        "visible_structure": {
            "unique_model_input_signatures": 7863,
            "repeated_input_occurrences": 142137,
            "conflicting_gold_signatures_per_input": 0,
            "normalized_state_strings": 2161,
            "candidate_semantic_ids": 19,
            "candidate_definition_tuples": 19,
            "query_semantic_ids": "all already present in Old100",
            "candidate_set_combinations": "all already present in Old100",
            "coarse_structural_tuples": 66,
            "observed_variable_masks": 32,
        },
        "generator_side_novelty": {
            "latent_state_signatures": 1217,
            "latent_state_signatures_unseen_in_old100": 258,
            "interpretation": "generator-side distinction only; not necessarily visible in model input",
        },
        "operation_mix": {
            "evidence_or_world_interventions": 75607,
            "hide_evidence": 23552,
            "world_do_interventions": 52055,
            "candidate_or_schema_operations": 37193,
            "representation_change_json_or_log": 14880,
            "criterion_paraphrase": 14880,
        },
        "target_metadata": {
            "independent_applicability_groups": 75000,
            "choice_groups": 37500,
            "ordinal_groups": 37500,
            "median_gold_entropy_nats": 0.61065,
            "groups_with_max_gold_probability_at_least_0_95": 35828,
            "high_probability_note": "target concentration only; not model-evaluated ease",
        },
        "classification": {
            "new_candidate_semantic_ids_vs_old100": 0,
            "new_candidate_definition_tuples_vs_old100": 0,
            "new_candidate_set_combinations_vs_old100": 0,
            "new_coarse_structural_tuples_vs_old100": 0,
            "new_observed_variable_masks_vs_old100": 0,
            "new_latent_state_signatures_vs_old100": 258,
            "full_taxonomic_classification": "unknown; no stronger classification is justified from the audited metadata",
        },
        "limitations": [
            "the tail is an ordinal slice rather than an exact set difference",
            "counts are inherited from the read-only audit and should be treated as reported, not re-derived here",
            "visible-input signatures are the compiler-input projection used by the audit, not a universal measure of semantic novelty",
        ],
        "protected_evaluation_bodies_or_predictions_read": False,
    }


def emit(args: argparse.Namespace) -> None:
    run = args.run_dir
    selection = args.selection_dir
    firewall = args.firewall_dir
    if args.out.exists() and any(args.out.iterdir()):
        raise FileExistsError(f"report directory is not empty: {args.out}")
    args.out.mkdir(parents=True, exist_ok=True)

    r_ids = read_manifest_ids(selection / "new-tight-r100-group-ids.jsonl")
    c_ids = read_manifest_ids(selection / "new-tight-c100-group-ids.jsonl")
    eval_ids = read_manifest_ids(selection / "new-tight-eval-group-ids.jsonl")
    preselection = json.loads((selection / "preselection-audit.json").read_text(encoding="utf-8"))
    if preselection["legacy_firewall_collision_group_count"] != 0:
        raise ValueError("full information-density census requires a zero-collision eligible universe")
    heldout_bundles = set()
    with (selection / "new-tight-eval-group-ids.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                heldout_bundles.add(json.loads(line)["split_family_bundle_id"])

    entropy_thresholds = training_entropy_thresholds(run / "group-records.jsonl", eval_ids)

    censuses = {name: Census() for name in ("new_universe", "new_eval", "new_eligible", "new_r100", "new_c100")}
    curve_sets: dict[str, set[str]] = {prefix: set() for prefix in CURVE_PREFIXES}
    curve: list[dict[str, Any]] = []
    group_id_seen: set[str] = set()
    universe_count = 0
    with (run / "group-records.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = str(row["group_id"])
            if group_id in group_id_seen:
                raise ValueError(f"duplicate generated group ID at line {line_number}")
            group_id_seen.add(group_id)
            universe_count += 1
            entropy_quintile = entropy_quintile_for(float(row["posterior_entropy_nats"]), entropy_thresholds)
            update_curve_sets(curve_sets, row)
            censuses["new_universe"].add(row, entropy_quintile=entropy_quintile)
            if group_id in eval_ids:
                censuses["new_eval"].add(row, entropy_quintile=entropy_quintile)
            else:
                censuses["new_eligible"].add(row, entropy_quintile=entropy_quintile)
            if group_id in r_ids:
                censuses["new_r100"].add(row, entropy_quintile=entropy_quintile)
            if group_id in c_ids:
                censuses["new_c100"].add(row, entropy_quintile=entropy_quintile)
            if universe_count % CHECKPOINT == 0 or universe_count == 500_000:
                curve.append({
                    "group_ordinal": universe_count,
                    "unique_counts": {key: len(values) for key, values in sorted(curve_sets.items())},
                })
    if universe_count != 500_000:
        raise ValueError(f"expected 500000 group records, found {universe_count}")
    if censuses["new_r100"].count != 100_000 or censuses["new_c100"].count != 100_000:
        raise ValueError("selected bank census does not match the exact 100k contract")
    if censuses["new_eval"].count != len(eval_ids):
        raise ValueError("evaluation manifest contains groups absent from the universe")
    if censuses["new_eligible"].count != preselection["eligible_training_group_count"]:
        raise ValueError("eligible census differs from selector preselection receipt")

    legacy_registry = firewall / "legacy-training-registry.jsonl"
    legacy_projection_stats, legacy_projection_curves = read_legacy_registry_projections(legacy_registry)
    old100_manifest = load_legacy_manifest(args.old100_manifest, "old100")
    old250_manifest = load_legacy_manifest(args.old250_manifest, "old250")
    strict_manifest = json.loads(args.strict_manifest.read_text(encoding="utf-8"))
    strict_manifest_summary = {
        "manifest_path": str(args.strict_manifest),
        "manifest_sha256": sha256_file(args.strict_manifest),
        "verified_group_count": 93_252,
        "episode_count": 23_313,
        "root_count": 1_132,
        "world_family_coverage": "system_diagnosis_only",
        "status": strict_manifest.get("status", "not_read_from_manifest"),
        "role": "read_only_novelty_transfer_diagnostic_not_C100",
    }
    census_reports = {name: census.report() for name, census in censuses.items()}

    info = {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": sha256_file(Path(__file__).with_name("v08-contract.json")),
        "unit": "atomic group; unique model-input signatures reported separately",
        "model_outputs_or_features_read": False,
        "protected_text_exported": False,
        "banks": census_reports,
        "legacy_training_registry_projection_counts": legacy_projection_stats,
        "legacy_manifest_references": {
            "Old100": old100_manifest,
            "Old250": old250_manifest,
            "StrictNovel93": strict_manifest_summary,
        },
        "selection": {
            "eligible_pool_group_count": preselection["eligible_training_group_count"],
            "eval_group_count": len(eval_ids),
            "training_entropy_quintile_thresholds_nats": entropy_thresholds,
            "random_curated_group_overlap": json.loads((selection / "r100-c100-selection-audit.json").read_text(encoding="utf-8"))["random_curated_group_overlap"],
        },
    }
    write_json(args.out / "information-density.json", info)
    write_json(
        args.out / "selection-composition-diagnostic.json",
        selection_composition_report(census_reports["new_r100"], census_reports["new_c100"]),
    )
    write_json(args.out / "novelty-growth-curves.json", {
        "contract": "jev-decision-data-information-density/v0.8",
        "group_record_order": "frozen deterministic generator serialization order",
        "checkpoint_interval_groups": CHECKPOINT,
        "curve": curve,
        "legacy_registry_projection_curves": legacy_projection_curves,
        "no_text_or_model_outputs": True,
    })
    write_json(args.out / "old-tail-audit.json", old_tail_audit(
        json.loads((firewall / "source-audit.json").read_text(encoding="utf-8"))
    ))

    contract = Path(__file__).with_name("v08-contract.json")
    plan = Path(__file__).with_name("source-plan.json")
    generator = Path(__file__).with_name("generator")
    frozen_world_libraries = [
        Path(__file__).resolve().parents[1] / "jev-decision-world-v01",
        Path(__file__).resolve().parents[1] / "jev-decision-world-v02",
    ]
    source_audit = json.loads((firewall / "source-audit.json").read_text(encoding="utf-8"))
    selection_audit = json.loads((selection / "r100-c100-selection-audit.json").read_text(encoding="utf-8"))
    input_audit = json.loads((run / "input-target-consistency.json").read_text(encoding="utf-8"))
    current_hashes = {source["source_id"]: sha256_file(Path(source["path"])) for source in source_audit["sources"]}
    prior_hashes = {source["source_id"]: source["sha256"] for source in source_audit["sources"]}
    source_hashes_unchanged = current_hashes == prior_hashes
    c100_source = next(source for source in source_audit["sources"] if source["source_id"] == "StrictNovel93")
    receipt = {
        "contract": "jev-decision-data-information-density/v0.8",
        "contract_sha256": sha256_file(contract),
        "report_builder_sha256": sha256_file(Path(__file__)),
        "source_plan_sha256": sha256_file(plan),
        "selector_source_sha256": selection_audit["selector_source_sha256"],
        "generator_source_tree_sha256": sha256_tree([generator, *frozen_world_libraries]),
        "generator_binary_sha256": sha256_file(args.generator_binary),
        "canonical_universe_sha256": sha256_file(run / "new-universe-canonical.jsonl"),
        "group_records_sha256": sha256_file(run / "group-records.jsonl"),
        "generation_receipt_sha256": sha256_file(run / "generation-receipt.json"),
        "input_target_consistency_sha256": sha256_file(run / "input-target-consistency.json"),
        "source_audit_sha256": sha256_file(firewall / "source-audit.json"),
        "old100_manifest_sha256": old100_manifest["manifest_sha256"],
        "old250_manifest_sha256": old250_manifest["manifest_sha256"],
        "strict_novel93_selection_manifest_sha256": strict_manifest_summary["manifest_sha256"],
        "source_registry_hashes_unchanged_on_postaudit": source_hashes_unchanged,
        "source_hash_mismatch_ids": sorted(key for key in prior_hashes if prior_hashes[key] != current_hashes[key]),
        "strict_novel93_train_sha256": c100_source["sha256"],
        "strict_novel93_hash_matches_contract": c100_source["sha256"] == "04521d2fe999bc097eb5c5d4471203610f3e0a7f1f7f9b3f1552ed979b5cf908",
        "r100_manifest_sha256": selection_audit["r100_manifest_sha256"],
        "c100_manifest_sha256": selection_audit["c100_manifest_sha256"],
        "eval_manifest_sha256": selection_audit["eval_manifest_sha256"],
        "source_registry_sha256": selection_audit["registry_sha256"],
        "qlora_or_backbone_training_performed": False,
        "model_feature_extraction_performed": False,
        "phoenix_accessed": False,
        "v04_v07_sources_mutated_by_this_run": False,
        "training_banks_materialized": False,
        "model_contact_authorized": False,
        "status": "PASS" if source_hashes_unchanged and c100_source["sha256"] == "04521d2fe999bc097eb5c5d4471203610f3e0a7f1f7f9b3f1552ed979b5cf908" and input_audit["status"] == "PASS" else "FAIL",
    }
    write_json(args.out / "v08-integrity-receipt.json", receipt)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--selection-dir", type=Path, required=True)
    parser.add_argument("--firewall-dir", type=Path, required=True)
    parser.add_argument("--generator-binary", type=Path, required=True)
    parser.add_argument("--old100-manifest", type=Path, default=Path("D:/codex-runs/jev-frozen-scaling-v05/banks/scale-manifest.json"))
    parser.add_argument("--old250-manifest", type=Path, default=Path("D:/codex-runs/jev-frozen-scaling-v06/banks/scale-manifest.json"))
    parser.add_argument("--strict-manifest", type=Path, default=Path("C:/Users/shuga/.codex/worktrees/3c8a/clean-rust/experiments/jev-curated-c100-v01/selection-manifest.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    emit(args)
    print(json.dumps({"reports_written": 5, "model_outputs_or_features_read": False, "phoenix_in_scope": False}))


if __name__ == "__main__":
    main()
