"""Run the sealed v0.8H post-hoc audit; never loads a model or a checkpoint."""

from __future__ import annotations

import argparse
import datetime as dt
import gc
from pathlib import Path
from typing import Any

from v08h_core import read_json, sha256_file, write_json
from v08h_exposure import build_treatment
from v08h_predictions import analyze_predictions
from v08h_preflight import CONTRACT_PATH, preflight

OUTPUT_NAMES = {
    "treatment-multiset-anatomy": "treatment_multiset_anatomy",
    "decision-type-exposure": "decision_type_exposure",
    "target-probability-geometry": "target_probability_geometry",
    "local-discrimination-exposure": "local_discrimination_exposure",
    "redundancy-and-reinforcement": "redundancy_and_reinforcement",
    "state-root-treatment-map": "state_root_treatment_map",
    "curation-component-decomposition": "curation_component_decomposition",
    "choice-prediction-geometry": "choice_prediction_geometry",
    "applicability-probability-geometry": "applicability_probability_geometry",
    "ordinal-cumulative-geometry": "ordinal_cumulative_geometry",
    "hard-sibling-breakdown": "hard_sibling_breakdown",
    "binding-directionality": "binding_directionality",
    "intervention-family-breakdown": "intervention_family_breakdown",
    "legacy-instability-audit": "legacy_instability_audit",
    "acquisition-trajectories": "acquisition_trajectories",
}


def _capability_map(exposure: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    run_metrics = predictions["run_typed_metrics"]
    effects = predictions["paired_seed_effects"]["across_seed"]
    by_view: dict[str, Any] = {}
    for view, result_key in (
        ("choice", "choice_prediction_geometry"),
        ("independent_applicability", "applicability_probability_geometry"),
        ("ordinal_score", "ordinal_cumulative_geometry"),
    ):
        seed_rows = {}
        for seed in range(1, 4):
            arms = {}
            for arm in ("random", "curated"):
                run_key = f"seed-{seed}/{arm}"
                arms[arm] = run_metrics[run_key][view]
            seed_rows[f"seed-{seed}"] = {
                "random": arms["random"], "curated": arms["curated"],
                "delta_curated_minus_random": {
                    metric: (arms["curated"]["metrics"][metric] - arms["random"]["metrics"][metric])
                    for metric in arms["random"]["metrics"].keys() & arms["curated"]["metrics"].keys()
                    if isinstance(arms["random"]["metrics"][metric], (int, float))
                    and isinstance(arms["curated"]["metrics"][metric], (int, float))
                },
            }
        related = {key: value for key, value in effects.items() if key.startswith(f"{view}/")}
        by_view[view] = {
            "training_exposure": {
                "full_bank_counts": exposure["decision_type_exposure"]["full_bank_counts"],
                "treatment_active_geometry": exposure["target_probability_geometry"]["by_decision_type"].get(view),
                "local_discrimination": exposure["local_discrimination_exposure"]["by_view"].get(view),
            },
            "evaluation_by_seed": seed_rows,
            "paired_root_cluster_effects": related,
            "interpretation": "Descriptive allocation map. Training-exposure differences and evaluation outcomes are not a causal mediation estimate.",
        }
    return {
        "status": "DESCRIPTIVE_POSTHOC_MAP",
        "training_treatment": exposure["treatment_multiset_anatomy"],
        "policy_component_shifts": exposure["curation_component_decomposition"],
        "decision_types": by_view,
        "binding": predictions["binding_directionality"],
        "interventions": predictions["intervention_family_breakdown"],
        "acquisition": predictions["acquisition_trajectories"],
        "causal_claim": False,
    }


def _candidate_mechanisms(exposure: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    components = exposure["curation_component_decomposition"]["components"]
    treatment = exposure["treatment_multiset_anatomy"]
    effects = predictions["paired_seed_effects"]["across_seed"]
    choice_sibling = predictions["hard_sibling_breakdown"]
    candidates = [
        {
            "id": "M1_TARGETED_POLICY_ALLOCATION",
            "tier": "A_observed_descriptive",
            "claim": "The arms differ in learner-visible signature mass, and the frozen curation objective has a measurable component profile on that active mass.",
            "evidence": {
                "D_train": treatment["D_train_reconstructed"],
                "random_enriched_mass": treatment["random_enriched_mass"],
                "curated_enriched_mass": treatment["curated_enriched_mass"],
                "component_enriched_deltas": {
                    name: item["mean_delta_curated_minus_random"]
                    for name, item in components.items()
                },
            },
            "causal_status": "not_established",
        },
        {
            "id": "M2_LOCAL_DISCRIMINATION_TRANSFER",
            "tier": "B_candidate_association",
            "claim": "Local-discrimination exposure may be associated with hard-sibling evaluation behavior.",
            "evidence": {
                "local_discrimination_exposure": exposure["local_discrimination_exposure"],
                "hard_sibling_by_run": choice_sibling,
                "paired_choice_effects": {key: value for key, value in effects.items()
                                           if key.startswith("choice/")},
            },
            "limitation": "Three paired optimization seeds and descriptive exposure contrasts do not identify mediation or causation.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M3_PROBABILITY_GEOMETRY_TRANSFER",
            "tier": "B_candidate_association",
            "claim": "Target-distribution geometry in treatment-active training mass may relate to probability-quality changes by decision type.",
            "evidence": {
                "training_target_geometry": exposure["target_probability_geometry"],
                "paired_probability_effects": {
                    key: value for key, value in effects.items()
                    if any(token in key for token in ("/brier", "/nll", "/posterior_l1", "/ordinal_rps"))
                },
            },
            "limitation": "No example-level training-to-evaluation linkage or randomized mediator intervention is available.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M4_STATE_SELECTION_AND_REINFORCEMENT",
            "tier": "B_candidate_association",
            "claim": "State identity turnover and repeated-signature/state exposure are candidate routes through which the policy may allocate supervision.",
            "evidence": {
                "state_root_treatment": exposure["state_root_treatment_map"],
                "redundancy_reinforcement": exposure["redundancy_and_reinforcement"],
            },
            "limitation": "Exposure geometry is matched, but state identities may differ by design; descriptive overlap cannot establish a learning mechanism.",
            "causal_status": "hypothesis_only",
        },
        {
            "id": "M5_HIDDEN_FAILURE_MODE",
            "tier": "C_not_measurable_from_frozen_artifacts",
            "claim": "Legacy class/slot collapse, per-example standard-schema drift, and locality mediation cannot be resolved from persisted aggregates alone.",
            "evidence": {
                "legacy": predictions["legacy_instability_audit"]["status"],
                "standard_schema_rowwise": "NOT_MEASURABLE_FROM_FROZEN_ARTIFACTS",
                "counterfactual_locality": "NOT_MEASURABLE_FROM_FROZEN_ARTIFACTS",
            },
            "causal_status": "not_tested",
        },
    ]
    return {
        "status": "CANDIDATES_ONLY_NO_CAUSAL_ATTRIBUTION",
        "tiers": {
            "A": "directly observed metadata or saved-output facts",
            "B": "descriptive cross-domain associations/hypotheses; not identified causes",
            "C": "not measurable from the sealed v0.8G artifacts",
        },
        "candidates": candidates,
        "forbidden_inference": "No candidate mechanism is promoted to causal explanation by this report.",
    }


def _integrity_receipt(context: dict[str, Any], output_dir: Path,
                       report_paths: list[Path], contract_path: Path) -> dict[str, Any]:
    local_sources = [contract_path, Path(__file__), Path(__file__).with_name("v08h_core.py"),
                     Path(__file__).with_name("v08h_preflight.py"),
                     Path(__file__).with_name("v08h_exposure.py"),
                     Path(__file__).with_name("v08h_predictions.py")]
    return {
        "protocol": "jev-information-density/v0.8h-treatment-attribution",
        "status": "PASS_POSTHOC_AUDIT_ONLY",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inputs_verified_by_preflight": context["verified_hashes"],
        "observed_unpinned_binding_predictions": context["binding_predictions_observed"],
        "analysis_sources": {
            str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in local_sources
        },
        "reports": {
            str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in report_paths
        },
        "boundaries": {
            "model_loaded": False,
            "lfm_inference": False,
            "feature_extraction": False,
            "head_training": False,
            "head_inference": False,
            "bank_reconstruction": False,
            "bank_optimization": False,
            "new_curation_scoring": False,
            "pstar_modified": False,
            "evaluation_changed": False,
            "phoenix_access": False,
            "follow_on_training_authorized": False,
        },
        "output_directory": str(output_dir),
        "receipt_note": "This receipt hashes all v0.8H reports except itself; hash the final receipt file externally for archival identity.",
    }


def run(contract_path: Path = CONTRACT_PATH, output_dir: Path | None = None) -> dict[str, Any]:
    contract = read_json(contract_path)
    output_dir = output_dir or Path(contract["external_output"])
    output_dir.mkdir(parents=True, exist_ok=True)
    print("v0.8H preflight: verifying sealed inputs and policy replay", flush=True)
    context = preflight(contract_path)
    print("v0.8H exposure: reconstructing signature-multiset treatment", flush=True)
    exposure = build_treatment(context)
    # The exposure builders return working-only row/index objects alongside
    # report payloads. Drop them before parsing the six saved prediction files.
    for key in ("enriched_rows", "arm_stats", "treatment_distributions"):
        exposure.pop(key, None)
    for key in (
        "random_rows", "curated_rows", "metadata", "counts_random", "counts_curated",
        "base_counts_random", "base_counts_curated", "policy", "score_components", "policy_scores",
    ):
        context.pop(key, None)
    gc.collect()
    print("v0.8H predictions: reading and validating saved outputs", flush=True)
    predictions = analyze_predictions(context)

    reports: dict[str, Any] = {}
    for filename, key in OUTPUT_NAMES.items():
        source = exposure if key in exposure else predictions
        reports[filename] = source[key]
    reports["capability-allocation-map"] = _capability_map(exposure, predictions)
    reports["candidate-mechanisms"] = _candidate_mechanisms(exposure, predictions)

    paths = []
    for name, content in reports.items():
        path = output_dir / f"{name}.json"
        write_json(path, content)
        paths.append(path)
        print(f"wrote {path.name}", flush=True)

    receipt = _integrity_receipt(context, output_dir, paths, contract_path)
    receipt_path = output_dir / "integrity-receipt.json"
    write_json(receipt_path, receipt)
    print(f"receipt sha256={sha256_file(receipt_path)}", flush=True)
    print(f"completed reports={len(paths)} plus integrity-receipt.json", flush=True)
    return {"output_dir": str(output_dir), "report_count": len(paths), "receipt": receipt}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    run(args.contract, args.output)


if __name__ == "__main__":
    main()
