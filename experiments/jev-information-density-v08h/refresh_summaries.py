"""Compact duplicate v0.8H summaries from sealed post-hoc reports only.

This script never opens a model, prediction file, bank, or feature cache. It
reads the reports already written by run_v08h.py, replaces two duplicated
summary reports with reference-oriented versions, and refreshes their hashes.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from v08h_core import read_json, sha256_file, write_json

DEFAULT_OUTPUT = Path(r"D:\codex-runs\jev-information-density-v08h")
EXPECTED_REPORTS = (
    "treatment-multiset-anatomy.json",
    "decision-type-exposure.json",
    "target-probability-geometry.json",
    "local-discrimination-exposure.json",
    "redundancy-and-reinforcement.json",
    "state-root-treatment-map.json",
    "curation-component-decomposition.json",
    "choice-prediction-geometry.json",
    "applicability-probability-geometry.json",
    "ordinal-cumulative-geometry.json",
    "hard-sibling-breakdown.json",
    "binding-directionality.json",
    "intervention-family-breakdown.json",
    "legacy-instability-audit.json",
    "acquisition-trajectories.json",
    "capability-allocation-map.json",
    "candidate-mechanisms.json",
)
METRIC_FIELDS = ("count", "accuracy", "nll", "brier", "posterior_l1", "ece_soft")
ORDINAL_FIELDS = (
    "count", "exact_accuracy", "adjacent_accuracy", "expected_rank_spearman",
    "ranked_probability_score_normalized",
)


def _pick(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in fields if key in source}


def _compact_schema_profiles(binding: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for run_key, run in binding["standard_schema_profile_aggregates"].items():
        profiles: dict[str, Any] = {}
        for profile, views in run["aggregate_schema_profiles"].items():
            profiles[profile] = {}
            for view, sources in views.items():
                selected: dict[str, Any] = {}
                exact = sources.get("exact_generative_posterior")
                if exact:
                    selected["exact_generative_posterior"] = _pick(exact, METRIC_FIELDS)
                ordinal = sources.get("ordinal")
                if ordinal:
                    selected["ordinal"] = _pick(ordinal, ORDINAL_FIELDS)
                profiles[profile][view] = selected
        compact[run_key] = profiles
    return compact


def _compact_binding(binding: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for run_key, views in binding["identity_invariance_by_run"].items():
        identity[run_key] = {
            view: _pick(metrics, ("pair_count", "mean_probability_l1", "argmax_flip_rate"))
            for view, metrics in views.items()
        }
    return {
        "probe_semantics": binding["probe_semantics"],
        "standard_schema_profile_metrics_by_run": _compact_schema_profiles(binding),
        "identity_substitution_metrics_by_run": identity,
        "interpretation_limit": binding["limitation"],
        "detailed_report": "binding-directionality.json",
    }


def _compact_type_map(capability: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for view, details in capability["decision_types"].items():
        exposure = details["training_exposure"]
        active = exposure["treatment_active_geometry"]
        geometry: dict[str, Any] = {}
        for arm in ("random", "curated"):
            source = active[f"{arm}_enriched_geometry"]
            geometry[arm] = {
                field: source[field]["mean"]
                for field in ("entropy_nats", "max_probability", "top_two_margin")
                if field in source
            }
        local = exposure.get("local_discrimination", {})
        local_summary = {}
        for feature, pair in local.items():
            if isinstance(pair, dict) and "mean_delta_curated_minus_random" in pair:
                local_summary[feature] = pair["mean_delta_curated_minus_random"]
        result[view] = {
            "full_bank_counts": exposure["full_bank_counts"],
            "treatment_active_mass": active["enriched_mass"],
            "treatment_active_target_geometry_mean": geometry,
            "local_discrimination_delta": local_summary,
            "paired_root_cluster_effects": details["paired_root_cluster_effects"],
            "detail_reports": {
                "training": "target-probability-geometry.json",
                "evaluation": {
                    "choice": "choice-prediction-geometry.json",
                    "independent_applicability": "applicability-probability-geometry.json",
                    "ordinal_score": "ordinal-cumulative-geometry.json",
                }[view],
            },
        }
    return result


def _compact_acquisition(acquisition: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "train_loss", "loss", "wall_seconds",
        "choice/exact_generative_posterior/accuracy",
        "choice/exact_generative_posterior/brier",
        "independent_applicability/exact_generative_posterior/brier",
        "ordinal_score/ordinal/exact_accuracy",
        "ordinal_score/ordinal/adjacent_accuracy",
        "ordinal_score/ordinal/ranked_probability_score_normalized",
    )
    by_run: dict[str, Any] = {}
    for run_key, run in acquisition["runs"].items():
        epochs: dict[str, Any] = {}
        for epoch, record in run["epochs"].items():
            flattened = dict(record)
            train = flattened.pop("train", {})
            row = _pick(flattened, fields)
            if "loss" in train:
                row["train_loss"] = train["loss"]
            ordinal = record.get("ordinal_score/ordinal")
            if ordinal:
                row["ordinal"] = _pick(ordinal, ORDINAL_FIELDS)
            epochs[epoch] = row
        by_run[run_key] = epochs
    return {
        "runs_by_epoch": by_run,
        "primary_terminal_epoch": acquisition["primary_terminal_epoch"],
        "note": acquisition["note"],
        "detailed_report": "acquisition-trajectories.json",
    }


def compact_capability_map(output_dir: Path) -> dict[str, Any]:
    original = read_json(output_dir / "capability-allocation-map.json")
    treatment = original["training_treatment"]
    policy = original["policy_component_shifts"]
    components = {
        name: item["mean_delta_curated_minus_random"]
        for name, item in policy["components"].items()
    }
    enriched = policy["enriched_mass"]
    state_root = read_json(output_dir / "state-root-treatment-map.json")
    redundancy = read_json(output_dir / "redundancy-and-reinforcement.json")
    binding_report = read_json(output_dir / "binding-directionality.json")
    intervention = read_json(output_dir / "intervention-family-breakdown.json")
    legacy = read_json(output_dir / "legacy-instability-audit.json")
    acquisition = original["acquisition"]

    interventions = {
        "run_count": len(intervention),
        "family_class_view_cells_per_run": sorted({
            key.split("|", 1)[-1] for run in intervention.values()
            for key in run["by_intervention_family_class_view"]
        }),
        "locality_status": "NOT_MEASURABLE_FROM_FROZEN_ARTIFACTS",
        "locality_reason": "The persisted NewTight rows lack compiler-side direct/indirect/unaffected query truth.",
        "detailed_report": "intervention-family-breakdown.json",
    }
    return {
        "status": "DESCRIPTIVE_POSTHOC_MAP_COMPACT",
        "causal_claim": False,
        "training_treatment": {
            "groups_per_arm": treatment["groups_per_arm"],
            "D_train": treatment["D_train_reconstructed"],
            "D_supervised_signature_only": treatment["D_supervised_signature_only"],
            "random_enriched_mass": treatment["random_enriched_mass"],
            "curated_enriched_mass": treatment["curated_enriched_mass"],
            "unique_signatures": {
                "random": treatment["unique_signatures_random"],
                "curated": treatment["unique_signatures_curated"],
            },
            "raw_group_id_jaccard": treatment["raw_group_id_jaccard"],
            "multiset_hashes": treatment["training_multiset_sha256"],
        },
        "frozen_policy": {
            "score_replay": policy["reconstruction_validation"],
            "full_bank": policy["full_bank"],
            "enriched_mass": {
                arm: _pick(values, ("mass", "mean", "median"))
                for arm, values in enriched.items()
            },
            "component_mean_delta_curated_minus_random": components,
            "detailed_report": "curation-component-decomposition.json",
        },
        "decision_types": _compact_type_map(original),
        "state_root": {
            "state_identity": _pick(state_root["state_identity"], (
                "random_unique", "curated_unique", "shared", "random_only", "curated_only",
                "jaccard", "state_multiplicity_histogram_tv",
                "different_exact_training_signature_composition_within_shared_states",
                "fraction_of_random_enriched_mass_on_shared_state_ids",
                "fraction_of_curated_enriched_mass_on_shared_state_ids",
            )),
            "root_identity": _pick(state_root["root_identity"], (
                "random_unique", "curated_unique", "shared", "random_only", "curated_only",
                "jaccard", "root_multiplicity_histogram_tv",
                "fraction_of_random_enriched_mass_on_shared_root_ids",
                "fraction_of_curated_enriched_mass_on_shared_root_ids",
            )),
            "detailed_report": "state-root-treatment-map.json",
        },
        "redundancy": {
            key: {
                "random_mean": value["random_enriched"]["mean"],
                "curated_mean": value["curated_enriched"]["mean"],
                "delta_curated_minus_random": value["mean_delta_curated_minus_random"],
            }
            for key, value in redundancy["enriched_mass"].items()
        } | {"detailed_report": "redundancy-and-reinforcement.json"},
        "binding": _compact_binding(binding_report),
        "interventions": interventions,
        "acquisition": _compact_acquisition(acquisition),
        "legacy": {
            "status": legacy["status"],
            "row_level_prediction_files_available": legacy["row_level_prediction_files_available"],
            "limitation": legacy["interpretation"],
            "detailed_report": "legacy-instability-audit.json",
        },
        "report_index": {
            "detailed_decision_metrics": [
                "choice-prediction-geometry.json",
                "applicability-probability-geometry.json",
                "ordinal-cumulative-geometry.json",
                "hard-sibling-breakdown.json",
                "binding-directionality.json",
                "intervention-family-breakdown.json",
            ],
            "large_detail_reports_are_retained_without_duplication": True,
        },
    }


def compact_candidate_mechanisms(output_dir: Path, capability: dict[str, Any]) -> dict[str, Any]:
    train = capability["training_treatment"]
    policy = capability["frozen_policy"]
    types = capability["decision_types"]
    state_root = capability["state_root"]
    redundancy = capability["redundancy"]
    hard_sibling = read_json(output_dir / "hard-sibling-breakdown.json")
    hard_sibling_summary = {}
    for competitor_count in ("0", "1", "3"):
        pair: dict[str, list[float]] = {"random": [], "curated": []}
        for seed in range(1, 4):
            for arm in pair:
                pair[arm].append(
                    hard_sibling[f"seed-{seed}/{arm}"]["by_same_parent_competitor_count"][competitor_count]["accuracy"]
                )
        mean = {arm: sum(values) / len(values) for arm, values in pair.items()}
        hard_sibling_summary[competitor_count] = {
            "mean_accuracy_by_arm": mean,
            "curated_minus_random": mean["curated"] - mean["random"],
            "seed_values": pair,
        }

    candidates = [
        {
            "id": "M1_TARGETED_POLICY_ALLOCATION",
            "tier": "A_observed_descriptive",
            "claim": "The arms differ in exact training-signature mass; the frozen policy's selected increment has a measurable score-component profile.",
            "evidence": {
                "D_train": train["D_train"],
                "enriched_mass_per_arm": train["random_enriched_mass"],
                "curation_score_delta_by_component": policy["component_mean_delta_curated_minus_random"],
                "curation_score_replay": policy["score_replay"]["status"],
            },
            "detail": "treatment-multiset-anatomy.json; curation-component-decomposition.json",
            "causal_status": "not_established",
        },
        {
            "id": "M2_LOCAL_DISCRIMINATION_TRANSFER",
            "tier": "B_candidate_association",
            "claim": "Local-discrimination exposure differs slightly, while curated choice accuracy is lower across the observed hard-sibling competitor strata.",
            "evidence": {
                "choice_local_discrimination_delta": types["choice"]["local_discrimination_delta"],
                "hard_sibling_accuracy": hard_sibling_summary,
                "paired_choice_effects": types["choice"]["paired_root_cluster_effects"],
            },
            "detail": "local-discrimination-exposure.json; hard-sibling-breakdown.json; choice-prediction-geometry.json",
            "limitation": "These are descriptive contrasts across three paired optimization seeds, not mediation or causation.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M3_PROBABILITY_GEOMETRY_TRANSFER",
            "tier": "B_candidate_association",
            "claim": "Typed probability behavior shows different directions by decision type; there is no general probability-quality win.",
            "evidence": {
                "paired_probability_effects": {
                    view: {
                        key: metric
                        for key, metric in details["paired_root_cluster_effects"].items()
                        if any(token in key for token in ("/brier", "/nll", "/posterior_l1", "/ordinal_rps"))
                    }
                    for view, details in types.items()
                },
                "curation_component_deltas": policy["component_mean_delta_curated_minus_random"],
            },
            "detail": "target-probability-geometry.json; choice-prediction-geometry.json; applicability-probability-geometry.json; ordinal-cumulative-geometry.json",
            "limitation": "No example-level training-to-evaluation linkage or randomized mediator intervention is available.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M4_STATE_SELECTION_AND_REINFORCEMENT",
            "tier": "B_candidate_association",
            "claim": "The arms have nearly identical state multiplicity geometry but different training-signature composition within shared states; repetition descriptors also shift.",
            "evidence": {
                "state_identity_summary": state_root["state_identity"],
                "root_identity_summary": state_root["root_identity"],
                "enriched_redundancy_summary": redundancy,
            },
            "detail": "state-root-treatment-map.json; redundancy-and-reinforcement.json",
            "limitation": "State/root exposure summaries cannot identify which exposure changes caused model outcomes.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M5_UNRESOLVED_FAILURE_MODES",
            "tier": "C_not_measurable_from_frozen_artifacts",
            "claim": "Legacy rowwise class/slot behavior, standard-schema rowwise drift, and counterfactual locality attribution remain unresolved.",
            "evidence": {
                "legacy_rowwise_predictions": "NOT_AVAILABLE",
                "standard_schema_rowwise_predictions": "NOT_AVAILABLE",
                "counterfactual_locality": "NOT_MEASURABLE_FROM_FROZEN_ARTIFACTS",
                "binding_probe_scope": "opaque identity substitution only; definitions and gold unchanged",
            },
            "detail": "legacy-instability-audit.json; binding-directionality.json; intervention-family-breakdown.json",
            "causal_status": "not_tested",
        },
    ]
    return {
        "status": "CANDIDATES_ONLY_NO_CAUSAL_ATTRIBUTION",
        "summary_only": True,
        "tiers": {
            "A": "directly observed metadata or saved-output facts",
            "B": "descriptive cross-domain associations/hypotheses; not identified causes",
            "C": "not measurable from the sealed v0.8G artifacts",
        },
        "candidates": candidates,
        "forbidden_inference": "No candidate mechanism is promoted to causal explanation by this report.",
        "detailed_report_index": "capability-allocation-map.json",
    }


def _check_no_model_runtime(source_root: Path) -> None:
    forbidden = {"torch", "transformers", "safetensors", "accelerate"}
    for path in source_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        if imported & forbidden:
            raise RuntimeError(f"forbidden model runtime import in {path}: {imported & forbidden}")


def refresh(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    source_root = Path(__file__).resolve().parent
    _check_no_model_runtime(source_root)
    missing = [name for name in EXPECTED_REPORTS if not (output_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing sealed reports: {missing}")
    receipt_path = output_dir / "integrity-receipt.json"
    receipt = read_json(receipt_path)
    if receipt["protocol"] != "jev-information-density/v0.8h-treatment-attribution":
        raise ValueError("unexpected integrity-receipt protocol")
    if any(receipt["boundaries"].values()):
        raise ValueError("a sealed no-contact boundary is not false")

    capability_path = output_dir / "capability-allocation-map.json"
    candidate_path = output_dir / "candidate-mechanisms.json"
    current_capability = read_json(capability_path)
    if current_capability.get("status") == "DESCRIPTIVE_POSTHOC_MAP_COMPACT":
        compact_capability = current_capability
        compact_candidates = read_json(candidate_path)
        if compact_candidates.get("summary_only") is not True:
            raise ValueError("compact capability map is present but candidate summary is not compact")
    else:
        compact_capability = compact_capability_map(output_dir)
        compact_candidates = compact_candidate_mechanisms(output_dir, compact_capability)
        write_json(capability_path, compact_capability)
        write_json(candidate_path, compact_candidates)

    report_paths = [output_dir / name for name in EXPECTED_REPORTS]
    receipt["reports"] = {
        str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in report_paths
    }
    source_paths = [
        source_root / "v08h-contract.json",
        source_root / "run_v08h.py",
        source_root / "v08h_core.py",
        source_root / "v08h_preflight.py",
        source_root / "v08h_exposure.py",
        source_root / "v08h_predictions.py",
        Path(__file__).resolve(),
    ]
    receipt["analysis_sources"] = {
        str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in source_paths
    }
    receipt["summary_refresh"] = {
        "mode": "posthoc_compaction_from_existing_v08h_reports_only",
        "model_or_prediction_access": False,
        "reports_compacted": ["capability-allocation-map.json", "candidate-mechanisms.json"],
        "detailed_source_reports_preserved": True,
        "script_sha256": sha256_file(Path(__file__).resolve()),
    }
    receipt["generated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(receipt_path, receipt)
    return {
        "receipt_sha256": sha256_file(receipt_path),
        "report_bytes": {
            name: (output_dir / name).stat().st_size
            for name in ("capability-allocation-map.json", "candidate-mechanisms.json")
        },
        "report_count": len(receipt["reports"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(refresh(args.output))


if __name__ == "__main__":
    main()
