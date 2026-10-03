"""Frozen v0.8N response-matrix metrics and paired neighborhood analysis."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
SEEDS = (20260927, 20260928, 20260929)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
VIEWS = ("anchor", "fact_flip", "matched_neutral", "sham")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def candidate_map(row: dict[str, Any], field: str) -> dict[str, float]:
    ids = [str(value) for value in row["candidate_semantic_ids"]]
    values = row[field]
    if len(ids) != len(values) or len(set(ids)) != len(ids):
        raise ValueError(f"candidate alignment error: {row.get('neighborhood_id')}/{row.get('view')}")
    return {key: float(value) for key, value in zip(ids, values)}


def winner(values: dict[str, float]) -> str:
    return max(values, key=lambda key: (values[key], key))


def rank(values: dict[str, float], target: str) -> int:
    return sorted(values, key=lambda key: (-values[key], key)).index(target) + 1


def neighborhood_metrics(views: dict[str, dict[str, Any]]) -> dict[str, float | str]:
    if set(views) != set(VIEWS):
        raise ValueError("each neighborhood must contain anchor/fact/matched/sham exactly once")
    maps = {view: candidate_map(row, "prediction") for view, row in views.items()}
    gold = {view: candidate_map(row, "gold") for view, row in views.items()}
    ids = set(maps["anchor"])
    if any(set(value) != ids for value in [*maps.values(), *gold.values()]):
        raise ValueError("candidate semantic ID set changed across paired views")
    old_id = str(views["anchor"]["old_candidate_id"])
    new_id = str(views["anchor"]["new_candidate_id"])
    if old_id not in ids or new_id not in ids or old_id == new_id:
        raise ValueError("invalid certified old/new candidate identity")
    if any(str(row["old_candidate_id"]) != old_id or str(row["new_candidate_id"]) != new_id for row in views.values()):
        raise ValueError("certified old/new candidate identity drift within neighborhood")
    family = str(views["anchor"]["family_id"]).split(":")[-1]
    if family not in FAMILIES:
        raise ValueError(f"unexpected held-out family identity: {views['anchor']['family_id']}")
    for view in VIEWS:
        if str(views[view]["family_id"]).split(":")[-1] != family:
            raise ValueError("family identity drift within neighborhood")

    pa = maps["anchor"]
    fact = maps["fact_flip"]
    p_gold_a = gold["anchor"]
    p_gold_f = gold["fact_flip"]
    d_model = fact[new_id] - pa[new_id]
    d_exact = p_gold_f[new_id] - p_gold_a[new_id]
    strict = float(winner(pa) == old_id and winner(fact) == new_id)
    direction = float(d_model * d_exact > 0.0 if abs(d_exact) > 1e-12 else abs(d_model) <= 1e-12)
    result: dict[str, float | str] = {
        "family_id": family,
        "strict_transition": strict,
        "anchor_old_map": float(winner(pa) == old_id),
        "fact_new_map": float(winner(fact) == new_id),
        "correct_direction": direction,
        "new_probability_delta": d_model,
        "exact_new_probability_delta": d_exact,
        "delta_mae": abs(d_model - d_exact),
        "new_rank_gain": float(rank(pa, new_id) - rank(fact, new_id)),
        "anchor_nll": -sum(p_gold_a[key] * np.log(max(pa[key], 1e-30)) for key in ids),
        "anchor_brier": sum((pa[key] - p_gold_a[key]) ** 2 for key in ids),
        "anchor_gold_map_accuracy": float(winner(pa) == winner(p_gold_a)),
    }
    for view, prefix in (("sham", "sham"), ("matched_neutral", "matched")):
        pred = maps[view]
        gold_view = gold[view]
        result[f"{prefix}_l1"] = sum(abs(pa[key] - pred[key]) for key in ids)
        result[f"{prefix}_map_flip"] = float(winner(pa) != winner(pred))
        result[f"{prefix}_gold_probability_movement"] = pred[old_id] - pa[old_id]
        result[f"{prefix}_new_probability_movement"] = pred[new_id] - pa[new_id]
        result[f"{prefix}_margin_movement"] = (pred[new_id] - pred[old_id]) - (pa[new_id] - pa[old_id])
        result[f"{prefix}_exact_gold_l1"] = sum(abs(gold["anchor"][key] - gold_view[key]) for key in ids)
    return result


def stratified_bootstrap(values: np.ndarray, families: np.ndarray, rng: np.random.Generator, replicates: int = 10_000) -> dict[str, float]:
    samples = np.zeros(replicates, dtype=np.float64)
    unique = sorted(set(families.tolist()))
    if len(unique) != 4:
        raise ValueError(f"expected four held-out families; found {unique}")
    for family in unique:
        block = values[families == family]
        if len(block) != 500:
            raise ValueError(f"expected 500 anchors per family; found {len(block)} for {family}")
        indices = rng.integers(0, len(block), size=(replicates, len(block)), endpoint=False)
        samples += block[indices].mean(axis=1) / 4.0
    return {"mean": float(values.mean()), "ci90": [float(x) for x in np.quantile(samples, [0.05, 0.95])],
            "ci95": [float(x) for x in np.quantile(samples, [0.025, 0.975])], "replicates": replicates}


def group_prediction_rows(rows: list[dict[str, Any]]) -> dict[tuple[int, str, str], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[int, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (int(row["seed"]), str(row["arm"]), str(row["neighborhood_id"]))
        view = str(row["view"])
        if view not in VIEWS or view in grouped[key]:
            raise ValueError(f"invalid/duplicate prediction view: {key}/{view}")
        grouped[key][view] = row
    return grouped


def analyze(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    grouped = group_prediction_rows(rows)
    metric_rows: dict[tuple[int, str], dict[str, dict[str, float | str]]] = {}
    expected_ids: set[str] | None = None
    for seed in SEEDS:
        for arm in ARMS:
            pairs = []
            for (row_seed, row_arm, neighborhood_id), views in sorted(grouped.items()):
                if row_seed != seed or row_arm != arm:
                    continue
                if set(views) != set(VIEWS):
                    raise ValueError(f"incomplete response matrix cell {seed}/{arm}/{neighborhood_id}")
                pairs.append((neighborhood_id, neighborhood_metrics(views)))
            if len(pairs) != 2_000 or len({key for key, _ in pairs}) != 2_000:
                raise ValueError(f"expected 2000 unique neighborhoods for {seed}/{arm}; got {len(pairs)}")
            ids = {key for key, _ in pairs}
            if expected_ids is None:
                expected_ids = ids
            elif ids != expected_ids:
                raise ValueError("held-out neighborhood identities differ across seed/arm cells")
            metric_rows[(seed, arm)] = {key: value for key, value in pairs}

    rng = np.random.Generator(np.random.PCG64(20260930))
    example_id = sorted(expected_ids or [])[0]
    metric_names = sorted(key for key in metric_rows[(SEEDS[0], ARMS[0])][example_id] if key != "family_id")
    response_matrix: dict[str, Any] = {}
    for seed in SEEDS:
        response_matrix[str(seed)] = {}
        for arm in ARMS:
            per_id = metric_rows[(seed, arm)]
            ordered_ids = sorted(per_id)
            family_values = np.array([str(per_id[nid]["family_id"]) for nid in ordered_ids])
            values: dict[str, Any] = {}
            for metric in metric_names:
                arr = np.array([float(per_id[nid][metric]) for nid in ordered_ids], dtype=np.float64)
                values[metric] = {
                    "overall_mean": float(arr.mean()),
                    "by_family": {family: float(arr[family_values == family].mean()) for family in FAMILIES},
                }
            response_matrix[str(seed)][arm] = values

    comparisons: dict[str, Any] = {}
    primary_conditions = {}
    for seed in SEEDS:
        seed_key = str(seed)
        comparisons[seed_key] = {}
        for effect, left_arm, right_arm, metric in (
            ("sham_locality_l1_benefit", "B-MATCHED", "B-SHAM", "sham_l1"),
            ("sham_locality_map_benefit", "B-MATCHED", "B-SHAM", "sham_map_flip"),
            ("generic_sham_locality_l1_benefit", "B-DUP", "B-MATCHED", "sham_l1"),
            ("generic_sham_locality_map_benefit", "B-DUP", "B-MATCHED", "sham_map_flip"),
            ("generic_matched_locality_l1_benefit", "B-DUP", "B-MATCHED", "matched_l1"),
            ("generic_matched_locality_map_benefit", "B-DUP", "B-MATCHED", "matched_map_flip"),
        ):
            left = metric_rows[(seed, left_arm)]
            right = metric_rows[(seed, right_arm)]
            ordered_ids = sorted(left)
            diff = np.array([float(left[nid][metric]) - float(right[nid][metric]) for nid in ordered_ids], dtype=np.float64)
            families = np.array([str(left[nid]["family_id"]) for nid in ordered_ids])
            record = stratified_bootstrap(diff, families, rng)
            record["contrast"] = f"{left_arm} - {right_arm} on {metric}; positive means lower metric in right arm"
            record["by_family"] = {}
            for family in FAMILIES:
                block = diff[families == family]
                indexes = rng.integers(0, len(block), size=(10_000, len(block)), endpoint=False)
                boot = block[indexes].mean(axis=1)
                record["by_family"][family] = {"mean": float(block.mean()), "ci95": [float(x) for x in np.quantile(boot, [0.025, 0.975])], "n": len(block)}
            comparisons[seed_key][effect] = record

        ids = sorted(metric_rows[(seed, "B-SHAM")])
        families = np.array([str(metric_rows[(seed, "B-SHAM")][nid]["family_id"]) for nid in ids])
        interaction = np.array([
            (float(metric_rows[(seed, "B-SHAM")][nid]["sham_l1"]) - float(metric_rows[(seed, "B-MATCHED")][nid]["sham_l1"]))
            - (float(metric_rows[(seed, "B-SHAM")][nid]["matched_l1"]) - float(metric_rows[(seed, "B-MATCHED")][nid]["matched_l1"]))
            for nid in ids
        ], dtype=np.float64)
        interaction_record = stratified_bootstrap(interaction, families, rng)
        interaction_record["definition"] = "(R[B-SHAM,S]-R[B-MATCHED,S])-(R[B-SHAM,M]-R[B-MATCHED,M]); negative means larger SHAM-trained advantage on the sham test axis"
        comparisons[seed_key]["cross_perturbation_interaction_l1"] = interaction_record

        sham_transition = float(response_matrix[seed_key]["B-SHAM"]["strict_transition"]["overall_mean"])
        matched_transition = float(response_matrix[seed_key]["B-MATCHED"]["strict_transition"]["overall_mean"])
        floor = float(contract["sensitivity_guard_and_claim_rules"]["absolute_sensitivity_floor"]["minimum_per_seed"])
        primary_conditions[seed_key] = {
            "matched_sensitivity_at_floor": matched_transition >= floor,
            "sham_sensitivity_at_floor": sham_transition >= floor,
            "strict_transition_sham_minus_matched": sham_transition - matched_transition,
            "sham_l1_benefit_positive": comparisons[seed_key]["sham_locality_l1_benefit"]["mean"] > 0,
            "sham_map_benefit_positive": comparisons[seed_key]["sham_locality_map_benefit"]["mean"] > 0,
        }

    seed_effects = {
        name: [comparisons[str(seed)][name]["mean"] for seed in SEEDS]
        for name in ("sham_locality_l1_benefit", "sham_locality_map_benefit", "generic_sham_locality_l1_benefit", "generic_sham_locality_map_benefit", "generic_matched_locality_l1_benefit", "generic_matched_locality_map_benefit", "cross_perturbation_interaction_l1")
    }
    seed_effect_summary = {
        name: {"per_seed": values, "mean": float(np.mean(values)), "median": float(np.median(values))}
        for name, values in seed_effects.items()
    }
    floor_all = all(primary_conditions[str(seed)]["matched_sensitivity_at_floor"] and primary_conditions[str(seed)]["sham_sensitivity_at_floor"] for seed in SEEDS)
    mean_transition_loss = float(np.mean([primary_conditions[str(seed)]["strict_transition_sham_minus_matched"] for seed in SEEDS]))
    all_locality_signs = all(primary_conditions[str(seed)]["sham_l1_benefit_positive"] and primary_conditions[str(seed)]["sham_map_benefit_positive"] for seed in SEEDS)
    support = floor_all and all_locality_signs and mean_transition_loss >= -0.05
    signs_heterogeneous = any(
        min(seed_effects[name]) < 0 < max(seed_effects[name])
        for name in ("sham_locality_l1_benefit", "sham_locality_map_benefit")
    )
    return {
        "protocol": "jev-information-density/v0.8n-road-b-phase-b-v01",
        "status": "ANALYSIS_COMPLETE", "estimand": "B-SHAM versus B-MATCHED on held-out sham locality; positive benefit means lower locality in B-SHAM",
        "metric_contract_sha256": hashlib.sha256((PHASE / "phase-b-analysis-contract-v01.json").read_bytes()).hexdigest(),
        "response_matrix": response_matrix, "paired_neighborhood_effects": comparisons,
        "primary_gate": {
            "per_seed": primary_conditions, "all_arms_meet_absolute_sensitivity_floor": floor_all,
            "all_three_seeds_favor_sham_on_both_locality_metrics": all_locality_signs,
            "mean_strict_transition_loss_within_5pp": mean_transition_loss >= -0.05,
            "mean_strict_transition_sham_minus_matched": mean_transition_loss,
            "localized_radius_control_support": support,
        },
        "seed_heterogeneity": {"effect_signs_by_seed": seed_effects, "paired_seed_effect_summary": seed_effect_summary, "mixed_sign_detected": signs_heterogeneous,
                               "no_pooled_optimizer_seed_inference": True},
        "equivalence": equivalence_report(comparisons, contract),
        "interpretation_ceiling": contract["sensitivity_guard_and_claim_rules"]["radius_only_interpretation_ceiling"],
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
    }


def equivalence_report(comparisons: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    margins = contract["sensitivity_guard_and_claim_rules"]["near_equivalence_margins"]
    result = {}
    for metric_key, margin_key in (("sham_locality_l1_benefit", "posterior_l1_absolute"), ("sham_locality_map_benefit", "map_flip_rate_absolute")):
        margin = float(margins[margin_key])
        by_seed = {}
        for seed in SEEDS:
            record = comparisons[str(seed)][metric_key]
            ci = record["ci90"]
            within = ci[0] >= -margin and ci[1] <= margin
            by_seed[str(seed)] = {"difference_ci90": ci, "absolute_margin": margin, "within_margin": within}
        result[metric_key] = {"by_seed": by_seed, "approximately_equivalent_all_seeds": all(item["within_margin"] for item in by_seed.values())}
    return result


def main() -> int:
    auth_path = PHASE / "phase-b-authorization-event-v01.json"
    auth = read_json(auth_path)
    unlock = read_json(RUN / "panel-unlock-receipt.json")
    if auth.get("phase_b_authorized") is not True or unlock.get("status") != "HELDOUT_PANEL_UNLOCKED_ONCE_AFTER_TRAINING_SEAL":
        raise RuntimeError("evaluation analysis attempted without the authorized one-time panel opening")
    for relative, expected in auth["implementation_bindings"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"authorized analysis implementation drift: {relative}")
    analysis_contract_path = PHASE / "phase-b-analysis-contract-v01.json"
    if sha256_file(analysis_contract_path) != auth["bindings"]["analysis_contract"]["sha256"]:
        raise RuntimeError("frozen analysis contract changed")
    if unlock.get("training_seal_sha256") != sha256_file(RUN / "training-seal-manifest.json"):
        raise RuntimeError("evaluation unlock does not bind the training seal")
    evaluation_receipt_path = RUN / "evaluation" / "evaluation-receipt.json"
    evaluation_receipt = read_json(evaluation_receipt_path)
    predictions_path = RUN / "evaluation" / "predictions.jsonl"
    if evaluation_receipt.get("status") != "FROZEN_TERMINAL_HELDOUT_INFERENCE_COMPLETE" or evaluation_receipt.get("prediction_rows") != 72_000:
        raise RuntimeError("frozen held-out evaluation receipt is incomplete")
    if evaluation_receipt.get("prediction_sha256") != sha256_file(predictions_path) or evaluation_receipt.get("training_seal_sha256") != unlock["training_seal_sha256"]:
        raise RuntimeError("held-out predictions do not reconcile to evaluation/training receipts")
    if evaluation_receipt.get("newtight_access") is not False or evaluation_receipt.get("legacy_evaluation_access") is not False or evaluation_receipt.get("phoenix_access") is not False:
        raise RuntimeError("evaluation receipt claims a prohibited surface")
    predictions = read_jsonl(predictions_path)
    analysis_contract = read_json(analysis_contract_path)
    result = analyze(predictions, analysis_contract)
    result["predictions_sha256"] = sha256_file(predictions_path)
    result["training_seal_sha256"] = sha256_file(RUN / "training-seal-manifest.json")
    result["unlock_receipt_sha256"] = sha256_file(RUN / "panel-unlock-receipt.json")
    output = RUN / "reports" / "v08n-response-matrix-and-primary-analysis.json"
    if output.exists():
        raise FileExistsError("analysis output already exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "primary_gate": result["primary_gate"]["localized_radius_control_support"], "report_sha256": sha256_file(output), "phoenix_access": False}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
