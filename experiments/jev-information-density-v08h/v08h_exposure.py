"""Reconstruct v0.8H training-multiset and treatment exposure anatomy."""

from __future__ import annotations

import collections
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from v08h_core import (
    canonical,
    categorical_tv,
    distribution_geometry,
    weighted_categorical,
    weighted_numeric,
)


def _multi_features(rows: list[tuple[dict[str, Any], float]], axis: str) -> dict[str, float]:
    counts: dict[str, float] = defaultdict(float)
    for row, weight in rows:
        values = row["_meta"]["coverage_features"].get(axis, [])
        values = sorted(set(str(value) for value in values))
        if values:
            for value in values:
                counts[value] += weight / len(values)
    return counts


def _metadata_value(row: dict[str, Any], key: str) -> Any:
    meta = row["_meta"]
    if key.startswith("family:"):
        return meta["family_ids"].get(key.split(":", 1)[1], "<missing>")
    if key == "decision_type":
        return row["view"]
    if key == "adapter_kind":
        return row["kind"]
    if key == "candidate_cardinality":
        return int(row["candidate_cardinality"])
    if key == "probability_source":
        return row["probability_source"]
    if key == "authority":
        return row["authority"]
    if key == "source_family":
        return meta["source_family"]
    if key == "open_world":
        return bool(row["open_world"])
    if key == "state_multiplicity":
        return int(row["_state_multiplicity"])
    if key == "root_multiplicity":
        return int(row["_root_multiplicity"])
    if key == "signature_multiplicity":
        return int(row["_signature_multiplicity"])
    if key == "same_parent_competitors":
        return int(row["_same_parent_competitors"])
    if key == "_hierarchy":
        return int(row["_hierarchy"])
    if key == "gold_top1_position":
        return int(row["_geometry"]["gold_top1_position"])
    if key == "gold_top2_position":
        return int(row["_geometry"]["gold_top2_position"])
    return "<missing>"


def _numeric_value(row: dict[str, Any], key: str) -> float:
    if key in row["_geometry"]:
        return float(row["_geometry"][key])
    return float(_metadata_value(row, key))


def _compare_categorical(rplus: list[tuple[dict[str, Any], float]],
                         cplus: list[tuple[dict[str, Any], float]],
                         keys: list[str]) -> dict[str, Any]:
    output = {}
    for key in keys:
        left = weighted_categorical([str(_metadata_value(row, key)) for row, _ in rplus],
                                    [weight for _, weight in rplus])
        right = weighted_categorical([str(_metadata_value(row, key)) for row, _ in cplus],
                                     [weight for _, weight in cplus])
        output[key] = {
            "random_enriched": left,
            "curated_enriched": right,
            "total_variation": categorical_tv(left["counts"], right["counts"]),
        }
    return output


def _compare_numeric(rplus: list[tuple[dict[str, Any], float]],
                     cplus: list[tuple[dict[str, Any], float]],
                     keys: list[str]) -> dict[str, Any]:
    output = {}
    for key in keys:
        left = weighted_numeric([_numeric_value(row, key) for row, _ in rplus],
                                [weight for _, weight in rplus])
        right = weighted_numeric([_numeric_value(row, key) for row, _ in cplus],
                                 [weight for _, weight in cplus])
        output[key] = {
            "random_enriched": left,
            "curated_enriched": right,
            "mean_delta_curated_minus_random": (
                right["mean"] - left["mean"] if left.get("mass") and right.get("mass") else None
            ),
        }
    return output


def _signature_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["_meta"]["training_signature"]].append(row)
    return result


def _decorate_arm(rows: list[dict[str, Any]], score_components: dict[str, dict[str, float]],
                  policy_scores: dict[str, float], arm: str) -> dict[str, Any]:
    state_counts = Counter(row["_meta"]["state_signature"] for row in rows)
    root_counts = Counter(row["_meta"]["root_id"] for row in rows)
    signature_counts = Counter(row["_meta"]["training_signature"] for row in rows)
    semantic_counts: Counter[str] = Counter()
    structural_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    for row in rows:
        for feature in row["_meta"]["coverage_features"].get("redundancy", []):
            feature = str(feature)
            if feature.startswith("semantic:"):
                semantic_counts[feature] += 1
            elif feature.startswith("structural:"):
                structural_counts[feature] += 1
            elif feature.startswith("text:"):
                text_counts[feature] += 1
    for row in rows:
        meta = row["_meta"]
        local = meta["coverage_features"].get("local_discrimination", [])
        row["_same_parent_competitors"] = _feature_int(local, "same_parent_competitors", default=-1)
        row["_hierarchy"] = _feature_int(local, "hierarchy", default=-1)
        row["_state_multiplicity"] = state_counts[meta["state_signature"]]
        row["_root_multiplicity"] = root_counts[meta["root_id"]]
        row["_signature_multiplicity"] = signature_counts[meta["training_signature"]]
        row["_geometry"] = distribution_geometry(row)
        row["_policy_components"] = score_components[row["group_id"]]
        row["_policy_score"] = policy_scores[row["group_id"]]
        redundancy = meta["coverage_features"].get("redundancy", [])
        row["_semantic_recurrence"] = _feature_occurrence(redundancy, "semantic:", semantic_counts)
        row["_structural_recurrence"] = _feature_occurrence(redundancy, "structural:", structural_counts)
        row["_text_recurrence"] = _feature_occurrence(redundancy, "text:", text_counts)
    return {
        "state_counts": state_counts,
        "root_counts": root_counts,
        "signature_counts": signature_counts,
        "semantic_counts": semantic_counts,
        "structural_counts": structural_counts,
        "text_counts": text_counts,
        "arm": arm,
    }


def _feature_int(values: list[Any], prefix: str, default: int) -> int:
    for value in values:
        text = str(value)
        if text.startswith(prefix + ":"):
            try:
                return int(text.split(":", 1)[1])
            except ValueError:
                return default
    return default


def _feature_occurrence(values: list[Any], prefix: str, counts: Counter[str]) -> int:
    selected = [str(value) for value in values if str(value).startswith(prefix)]
    return max((counts[value] for value in selected), default=0)


def _enriched_mass(groups: dict[str, list[dict[str, Any]]],
                   deltas: Counter[str]) -> list[tuple[dict[str, Any], float]]:
    """Allocate each signature's exact excess mass uniformly over its arm rows."""
    output = []
    for signature, amount in deltas.items():
        if amount <= 0:
            continue
        members = groups.get(signature, [])
        if not members:
            raise ValueError(f"positive signature excess has no selected concrete rows: {signature}")
        weight = amount / len(members)
        output.extend((row, weight) for row in members)
    return output


def _histogram(values: Iterable[int]) -> dict[str, int]:
    counts = Counter(int(value) for value in values)
    return {str(key): counts[key] for key in sorted(counts)}


def _numeric_bins(rows: list[tuple[dict[str, Any], float]], field: str,
                  cuts: list[float]) -> dict[str, float]:
    bins: dict[str, float] = defaultdict(float)
    for row, weight in rows:
        value = _numeric_value(row, field)
        index = 0
        while index < len(cuts) and value > cuts[index]:
            index += 1
        low = "-inf" if index == 0 else str(cuts[index - 1])
        high = "+inf" if index == len(cuts) else str(cuts[index])
        bins[f"({low},{high}]" if index else f"[{low},{high}]"] += weight
    return dict(sorted(bins.items()))


def _weighted_axis(rows: list[tuple[dict[str, Any], float]], axis: str) -> dict[str, Any]:
    counts = _multi_features(rows, axis)
    mass = sum(counts.values())
    proportions = {key: value / mass for key, value in sorted(counts.items())} if mass else {}
    return {"incidence_mass": mass, "feature_counts": counts, "feature_proportions": proportions}


def build_treatment(context: dict[str, Any]) -> dict[str, Any]:
    random_rows = context["random_rows"]
    curated_rows = context["curated_rows"]
    random_groups = _signature_groups(random_rows)
    curated_groups = _signature_groups(curated_rows)
    counts_r: Counter[str] = Counter({key: len(value) for key, value in random_groups.items()})
    counts_c: Counter[str] = Counter({key: len(value) for key, value in curated_groups.items()})
    if counts_r != context["counts_random"] or counts_c != context["counts_curated"]:
        raise ValueError("row-reconstructed exact training-signature counts differ from preflight counters")
    signatures = counts_r.keys() | counts_c.keys()
    common = {signature: min(counts_r.get(signature, 0), counts_c.get(signature, 0))
              for signature in signatures}
    r_delta = Counter({signature: counts_r[signature] - counts_c[signature]
                       for signature in signatures if counts_r[signature] > counts_c[signature]})
    c_delta = Counter({signature: counts_c[signature] - counts_r[signature]
                       for signature in signatures if counts_c[signature] > counts_r[signature]})
    common_mass = sum(common.values())
    r_plus_mass, c_plus_mass = sum(r_delta.values()), sum(c_delta.values())
    if r_plus_mass != c_plus_mass:
        raise ValueError("equal-size arm signature excess mass does not conserve")
    signature_l1 = r_plus_mass + c_plus_mass
    n = len(random_rows)
    computed_distance = 0.5 * signature_l1 / n
    if abs(computed_distance - context["D_train"]) > 1e-12:
        raise ValueError("treatment signature decomposition does not reconcile D_train")

    arm_stats = {
        "random": _decorate_arm(random_rows, context["score_components"], context["policy_scores"], "random"),
        "curated": _decorate_arm(curated_rows, context["score_components"], context["policy_scores"], "curated"),
    }
    rplus = _enriched_mass(random_groups, r_delta)
    cplus = _enriched_mass(curated_groups, c_delta)
    for rows in (rplus, cplus):
        for row, weight in rows:
            row["_enriched_weight"] = weight

    raw_r = {row["group_id"] for row in random_rows}
    raw_c = {row["group_id"] for row in curated_rows}
    shared_raw_ids = raw_r & raw_c
    shared_signature_classes = sum(1 for signature in signatures
                                   if counts_r.get(signature, 0) == counts_c.get(signature, 0))
    changed_signature_classes = sum(1 for signature in signatures
                                    if counts_r.get(signature, 0) != counts_c.get(signature, 0))
    only_r = sum(1 for signature in signatures if counts_r.get(signature, 0) > 0 and counts_c.get(signature, 0) == 0)
    only_c = sum(1 for signature in signatures if counts_c.get(signature, 0) > 0 and counts_r.get(signature, 0) == 0)
    anatomy = {
        "status": "PASS_RECONCILED",
        "unit": "exact_v0.5_training_signature_multiset; supervised signature plus selected directed invariance-pair role events; occurrence multiplicity preserved",
        "groups_per_arm": n,
        "raw_group_ids_shared": len(shared_raw_ids),
        "raw_group_id_jaccard": len(shared_raw_ids) / len(raw_r | raw_c),
        "unique_signatures_random": len(counts_r),
        "unique_signatures_curated": len(counts_c),
        "signature_classes_equal_count": shared_signature_classes,
        "signature_classes_changed_count": changed_signature_classes,
        "signature_classes_only_random": only_r,
        "signature_classes_only_curated": only_c,
        "common_training_mass": common_mass,
        "random_enriched_mass": r_plus_mass,
        "curated_enriched_mass": c_plus_mass,
        "treatment_active_fraction_per_arm": r_plus_mass / n,
        "signature_count_l1": signature_l1,
        "D_train_reconstructed": computed_distance,
        "expected_D_train": context["contract"]["expected"]["D_train"],
        "D_supervised_signature_only": context["D_supervised"],
        "expected_D_supervised_signature_only": context["contract"]["expected"]["D_supervised_only"],
        "selected_invariance_pair_counts": context["invariance_pair_counts"],
        "training_multiset_sha256": context["training_multiset_hashes"],
        "reconciliation_error": computed_distance - context["contract"]["expected"]["D_train"],
        "count_mass_conservation": {
            "random": sum(counts_r.values()),
            "curated": sum(counts_c.values()),
            "common_plus_random_enriched": common_mass + r_plus_mass,
            "common_plus_curated_enriched": common_mass + c_plus_mass,
        },
        "enriched_signature_class_counts": {
            "random": len(r_delta), "curated": len(c_delta),
        },
        "raw_id_vs_signature_note": "Raw row overlap is provenance telemetry. Equal exact-training-signature row substitutions are common model-visible mass; only exact-signature count excess contributes to sealed D_train. The base supervised-only distance is reported separately.",
        "allocation_note": "Within each changed signature class, one-sided excess is distributed uniformly over selected concrete rows for variable metadata summaries. Those summaries are descriptive allocation conventions, not uniquely identified row-level matches.",
    }

    categorical_keys = [
        "decision_type", "adapter_kind", "probability_source", "authority", "candidate_cardinality",
        "open_world", "source_family", "family:world_or_topology_family", "family:ontology_family",
        "family:schema_composition_family", "family:candidate_set_construction_family",
        "family:definition_template_family", "family:intervention_family", "gold_top1_position",
        "gold_top2_position",
    ]
    numeric_keys = [
        "entropy_nats", "max_probability", "top_two_margin", "effective_count",
        "one_hot_distance", "normalized_entropy", "decision_alternatives",
        "state_multiplicity", "root_multiplicity", "signature_multiplicity",
        "same_parent_competitors",
    ]
    common_distribution = _compare_categorical(rplus, cplus, categorical_keys)
    common_distribution.update(_compare_numeric(rplus, cplus, numeric_keys))
    for axis in ("local_discrimination", "probability_geometry", "redundancy", "semantic_novelty", "structural_coverage"):
        left, right = _weighted_axis(rplus, axis), _weighted_axis(cplus, axis)
        common_distribution[f"coverage_features:{axis}"] = {
            "random_enriched": left,
            "curated_enriched": right,
            "total_variation": categorical_tv(left["feature_counts"], right["feature_counts"]),
        }

    full_counts_by_view = {
        "random": dict(sorted(Counter(row["view"] for row in random_rows).items())),
        "curated": dict(sorted(Counter(row["view"] for row in curated_rows).items())),
    }
    enriched_by_view = {
        "random": dict(sorted(Counter({view: sum(weight for row, weight in rplus if row["view"] == view)
                                        for view in {row["view"] for row, _ in rplus}}).items())),
        "curated": dict(sorted(Counter({view: sum(weight for row, weight in cplus if row["view"] == view)
                                        for view in {row["view"] for row, _ in cplus}}).items())),
    }
    per_view = {}
    for view in ("choice", "independent_applicability", "ordinal_score"):
        left = [(row, weight) for row, weight in rplus if row["view"] == view]
        right = [(row, weight) for row, weight in cplus if row["view"] == view]
        per_view[view] = {
            "full_bank_counts": {"random": full_counts_by_view["random"].get(view, 0),
                                 "curated": full_counts_by_view["curated"].get(view, 0)},
            "enriched_mass": {"random": sum(weight for _, weight in left),
                              "curated": sum(weight for _, weight in right)},
            "random_enriched_geometry": _geometry_profile(left),
            "curated_enriched_geometry": _geometry_profile(right),
        }

    score_report = _curation_score_report(context, rplus, cplus)
    state_root_report = _state_root_report(random_rows, curated_rows, rplus, cplus, arm_stats)
    redundancy_report = _redundancy_report(random_rows, curated_rows, rplus, cplus, arm_stats)
    decision_type_report = {
        "full_bank_counts": full_counts_by_view,
        "frozen_profile_counts_match": full_counts_by_view["random"] == full_counts_by_view["curated"],
        "enriched_mass": enriched_by_view,
        "by_type": per_view,
        "note": "The profile matches total view counts; treatment-active signature mass is reported separately.",
    }

    return {
        "treatment_multiset_anatomy": anatomy,
        "decision_type_exposure": decision_type_report,
        "target_probability_geometry": {
            "overall": {"random_enriched": _geometry_profile(rplus),
                        "curated_enriched": _geometry_profile(cplus)},
            "by_decision_type": per_view,
            "entropy_bins_descriptive_only": {
                "fixed_edges_nats": [0.0, 0.25, 0.5, 1.0, 1.5, 2.0],
                "random_enriched": _numeric_bins(rplus, "entropy_nats", [0.25, 0.5, 1.0, 1.5, 2.0]),
                "curated_enriched": _numeric_bins(cplus, "entropy_nats", [0.25, 0.5, 1.0, 1.5, 2.0]),
                "interpretation": "predeclared descriptive fixed bins; not used for selection or inference",
            },
        },
        "local_discrimination_exposure": {
            "coverage_feature_shift": common_distribution["coverage_features:local_discrimination"],
            "same_parent_competitors": common_distribution["same_parent_competitors"],
            "candidate_cardinality": common_distribution["candidate_cardinality"],
            "hierarchy_depth": _compare_numeric(rplus, cplus, ["_hierarchy"]),
            "by_view": _local_by_view(rplus, cplus),
        },
        "redundancy_and_reinforcement": redundancy_report,
        "state_root_treatment_map": state_root_report,
        "curation_component_decomposition": score_report,
        "treatment_distributions": common_distribution,
        "enriched_rows": {"random": rplus, "curated": cplus},
        "arm_stats": arm_stats,
    }


def _geometry_profile(rows: list[tuple[dict[str, Any], float]]) -> dict[str, Any]:
    keys = ["entropy_nats", "max_probability", "top_two_margin", "effective_count",
            "one_hot_distance", "normalized_entropy", "decision_alternatives"]
    output = {key: weighted_numeric([float(row["_geometry"][key]) for row, _ in rows],
                                    [weight for _, weight in rows]) for key in keys}
    output["gold_top1_position"] = weighted_categorical(
        [str(row["_geometry"]["gold_top1_position"]) for row, _ in rows], [weight for _, weight in rows]
    )
    if rows and rows[0][0]["kind"] == "independent":
        output["positive_gold_mass_fraction"] = sum(
            weight for row, weight in rows if row["_geometry"]["binary_gold_class"] == 1
        ) / max(1e-12, sum(weight for _, weight in rows))
    return output


def _local_by_view(rplus: list[tuple[dict[str, Any], float]],
                   cplus: list[tuple[dict[str, Any], float]]) -> dict[str, Any]:
    output = {}
    for view in ("choice", "independent_applicability", "ordinal_score"):
        left = [(row, w) for row, w in rplus if row["view"] == view]
        right = [(row, w) for row, w in cplus if row["view"] == view]
        output[view] = _compare_numeric(left, right, ["same_parent_competitors", "candidate_cardinality"])
    return output


def _score_stats(weighted_rows: list[tuple[dict[str, Any], float]], key: str) -> dict[str, Any]:
    return weighted_numeric([float(row["_policy_components"][key]) for row, _ in weighted_rows],
                            [weight for _, weight in weighted_rows])


def _curation_score_report(context: dict[str, Any],
                           rplus: list[tuple[dict[str, Any], float]],
                           cplus: list[tuple[dict[str, Any], float]]) -> dict[str, Any]:
    policy = context["policy"]
    components = list(policy.AXES)
    random_rows, curated_rows = context["random_rows"], context["curated_rows"]
    full_random = sum(context["policy_scores"][row["group_id"]] for row in random_rows) / len(random_rows)
    full_curated = sum(context["policy_scores"][row["group_id"]] for row in curated_rows) / len(curated_rows)
    random_priority_quality = sum(
        1.0 - int.from_bytes(policy.digest(policy.RANDOM_SEED, row["group_id"]), "big") / (1 << 256)
        for row in random_rows
    ) / len(random_rows)
    enriched = {}
    for component in components:
        left = _score_stats(rplus, component)
        right = _score_stats(cplus, component)
        enriched[component] = {
            "random_enriched": left,
            "curated_enriched": right,
            "mean_delta_curated_minus_random": right.get("mean", 0.0) - left.get("mean", 0.0),
        }
    r_score = weighted_numeric([context["policy_scores"][row["group_id"]] for row, _ in rplus],
                               [weight for _, weight in rplus])
    c_score = weighted_numeric([context["policy_scores"][row["group_id"]] for row, _ in cplus],
                               [weight for _, weight in cplus])
    frozen_result_path = Path(context["manifest"]["lineage_receipts"]["v08f_policy_arm_result"]["path"])
    from v08h_core import read_json
    frozen_result = read_json(frozen_result_path)
    expected_c = frozen_result["curated_arm_search"]["objective_mean_final"]
    expected_r = frozen_result["random_arm_search"]["objective_mean_final"]
    if abs(full_curated - expected_c) > 1e-12 or abs(random_priority_quality - expected_r) > 1e-12:
        raise ValueError(
            "exact frozen policy replay mismatch: "
            f"curated curation score {full_curated}/{expected_c}; "
            f"random priority quality {random_priority_quality}/{expected_r}"
        )
    return {
        "source": context["policy_receipt"],
        "component_names_and_weights": {name: 1.0 / len(components) for name in components},
        "reconstruction_validation": {
            "curated_full_bank_mean_replayed": full_curated,
            "curated_sealed_mean": expected_c,
            "random_priority_quality_replayed": random_priority_quality,
            "random_priority_quality_sealed_mean": expected_r,
            "random_curation_score_mean_descriptive_only": full_random,
            "absolute_tolerance": 1e-12,
            "status": "PASS_EXACT_FROZEN_SCORER_REPLAY",
        },
        "full_bank": {
            "random_curation_score_mean_descriptive": full_random,
            "curated_curation_score_mean": full_curated,
            "curated_minus_random_curation_score": full_curated - full_random,
            "random_frozen_priority_quality_mean": random_priority_quality,
        },
        "enriched_mass": {"random": r_score, "curated": c_score},
        "components": enriched,
        "interpretation": "Per-axis values replay the exact frozen v0.8 score implementation over the pinned full eligible metadata support; this is not a new curation score.",
    }


def _hist_tv(left: Counter[int], right: Counter[int]) -> float:
    total_l, total_r = sum(left.values()), sum(right.values())
    if not total_l or not total_r:
        return 0.0 if total_l == total_r else 1.0
    keys = left.keys() | right.keys()
    return 0.5 * sum(abs(left.get(key, 0) / total_l - right.get(key, 0) / total_r) for key in keys)


def _state_root_report(random_rows: list[dict[str, Any]], curated_rows: list[dict[str, Any]],
                       rplus: list[tuple[dict[str, Any], float]],
                       cplus: list[tuple[dict[str, Any], float]], arm_stats: dict[str, Any]) -> dict[str, Any]:
    states_r, states_c = arm_stats["random"]["state_counts"], arm_stats["curated"]["state_counts"]
    roots_r, roots_c = arm_stats["random"]["root_counts"], arm_stats["curated"]["root_counts"]
    state_set_r, state_set_c = set(states_r), set(states_c)
    root_set_r, root_set_c = set(roots_r), set(roots_c)
    sig_state: dict[str, str] = {}
    for row in random_rows + curated_rows:
        signature = row["_meta"]["training_signature"]
        state = row["_meta"]["state_signature"]
        if signature in sig_state and sig_state[signature] != state:
            raise ValueError("exact training signature unexpectedly maps to multiple shared-state signatures")
        sig_state[signature] = state
    sigs_r, sigs_c = _signature_groups(random_rows), _signature_groups(curated_rows)
    by_state_r: dict[str, Counter[str]] = defaultdict(Counter)
    by_state_c: dict[str, Counter[str]] = defaultdict(Counter)
    for signature, count in arm_stats["random"]["signature_counts"].items():
        by_state_r[sig_state[signature]][signature] += count
    for signature, count in arm_stats["curated"]["signature_counts"].items():
        by_state_c[sig_state[signature]][signature] += count
    common_states = state_set_r & state_set_c
    state_signature_composition_changed = sum(
        by_state_r[state] != by_state_c[state] for state in common_states
    )
    state_active_r: Counter[str] = Counter()
    state_active_c: Counter[str] = Counter()
    root_active_r: Counter[str] = Counter()
    root_active_c: Counter[str] = Counter()
    for row, weight in rplus:
        state_active_r[row["_meta"]["state_signature"]] += weight
        root_active_r[row["_meta"]["root_id"]] += weight
    for row, weight in cplus:
        state_active_c[row["_meta"]["state_signature"]] += weight
        root_active_c[row["_meta"]["root_id"]] += weight
    active_mass_r, active_mass_c = sum(state_active_r.values()), sum(state_active_c.values())
    shared_state_fraction_r = sum(value for key, value in state_active_r.items() if key in common_states) / max(1e-12, active_mass_r)
    shared_state_fraction_c = sum(value for key, value in state_active_c.items() if key in common_states) / max(1e-12, active_mass_c)
    shared_roots = root_set_r & root_set_c
    shared_root_fraction_r = sum(value for key, value in root_active_r.items() if key in shared_roots) / max(1e-12, sum(root_active_r.values()))
    shared_root_fraction_c = sum(value for key, value in root_active_c.items() if key in shared_roots) / max(1e-12, sum(root_active_c.values()))

    state_score: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"random": [], "curated": []})
    for arm, rows in (("random", random_rows), ("curated", curated_rows)):
        for row in rows:
            state_score[row["_meta"]["state_signature"]][arm].append(float(row["_policy_score"]))
    state_rows = []
    for state in sorted(state_set_r | state_set_c):
        left, right = state_score[state]["random"], state_score[state]["curated"]
        state_rows.append({
            "state_signature": state,
            "random_occurrences": states_r.get(state, 0),
            "curated_occurrences": states_c.get(state, 0),
            "random_enriched_mass": state_active_r.get(state, 0.0),
            "curated_enriched_mass": state_active_c.get(state, 0.0),
            "random_mean_frozen_policy_score": sum(left) / len(left) if left else None,
            "curated_mean_frozen_policy_score": sum(right) / len(right) if right else None,
            "score_mean_delta_curated_minus_random": (
                sum(right) / len(right) - sum(left) / len(left) if left and right else None
            ),
            "signature_class_count_random": len(by_state_r[state]),
            "signature_class_count_curated": len(by_state_c[state]),
            "signature_composition_changed": by_state_r[state] != by_state_c[state],
        })
    state_rows.sort(key=lambda item: (-(item["random_enriched_mass"] + item["curated_enriched_mass"]), item["state_signature"]))

    root_rows = []
    for root in sorted(root_set_r | root_set_c):
        root_rows.append({
            "root_id": root,
            "random_occurrences": roots_r.get(root, 0),
            "curated_occurrences": roots_c.get(root, 0),
            "random_enriched_mass": root_active_r.get(root, 0.0),
            "curated_enriched_mass": root_active_c.get(root, 0.0),
        })
    root_rows.sort(key=lambda item: (-(item["random_enriched_mass"] + item["curated_enriched_mass"]), item["root_id"]))
    return {
        "state_identity": {
            "definition": "state_input_sha256 from the frozen signature index",
            "random_unique": len(state_set_r), "curated_unique": len(state_set_c),
            "shared": len(common_states), "random_only": len(state_set_r - state_set_c),
            "curated_only": len(state_set_c - state_set_r),
            "jaccard": len(common_states) / max(1, len(state_set_r | state_set_c)),
            "state_multiplicity_histogram_random": _histogram(states_r.values()),
            "state_multiplicity_histogram_curated": _histogram(states_c.values()),
            "state_multiplicity_histogram_tv": _hist_tv(Counter(Counter(states_r.values())), Counter(Counter(states_c.values()))),
            "different_exact_training_signature_composition_within_shared_states": state_signature_composition_changed,
            "fraction_of_random_enriched_mass_on_shared_state_ids": shared_state_fraction_r,
            "fraction_of_curated_enriched_mass_on_shared_state_ids": shared_state_fraction_c,
            "shared_state_occurrence_mass_by_signature_reconciliation": "Proportional per-class excess allocation as declared in contract.",
            "per_state_policy_and_treatment_map": state_rows,
        },
        "root_identity": {
            "random_unique": len(root_set_r), "curated_unique": len(root_set_c),
            "shared": len(shared_roots), "random_only": len(root_set_r - root_set_c),
            "curated_only": len(root_set_c - root_set_r),
            "jaccard": len(shared_roots) / max(1, len(root_set_r | root_set_c)),
            "root_multiplicity_histogram_random": _histogram(roots_r.values()),
            "root_multiplicity_histogram_curated": _histogram(roots_c.values()),
            "root_multiplicity_histogram_tv": _hist_tv(Counter(Counter(roots_r.values())), Counter(Counter(roots_c.values()))),
            "fraction_of_random_enriched_mass_on_shared_root_ids": shared_root_fraction_r,
            "fraction_of_curated_enriched_mass_on_shared_root_ids": shared_root_fraction_c,
            "per_root_active_mass_top_250": root_rows[:250],
            "all_root_active_mass": root_rows,
        },
        "exact_active_mass_by_state": {
            "random_enriched": dict(sorted(state_active_r.items())),
            "curated_enriched": dict(sorted(state_active_c.items())),
        },
    }


def _redundancy_report(random_rows: list[dict[str, Any]], curated_rows: list[dict[str, Any]],
                       rplus: list[tuple[dict[str, Any], float]],
                       cplus: list[tuple[dict[str, Any], float]], arm_stats: dict[str, Any]) -> dict[str, Any]:
    def arm_summary(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        stats = arm_stats[name]
        sig_hist = Counter(stats["signature_counts"].values())
        state_hist = Counter(stats["state_counts"].values())
        root_hist = Counter(stats["root_counts"].values())
        repeated = sum(count for count in stats["signature_counts"].values() if count > 1)
        return {
            "group_count": len(rows),
            "unique_exact_training_signatures": len(stats["signature_counts"]),
            "groups_in_repeated_signature_classes": repeated,
            "fraction_groups_in_repeated_signature_classes": repeated / len(rows),
            "signature_multiplicity_histogram": _histogram(sig_hist.elements()),
            "state_multiplicity_histogram": _histogram(state_hist.elements()),
            "root_multiplicity_histogram": _histogram(root_hist.elements()),
            "unique_semantic_redundancy_features": len(stats["semantic_counts"]),
            "unique_structural_redundancy_features": len(stats["structural_counts"]),
            "unique_text_redundancy_features": len(stats["text_counts"]),
            "semantic_recurrence_occurrences_gt1": sum(1 for value in stats["semantic_counts"].values() if value > 1),
            "structural_recurrence_occurrences_gt1": sum(1 for value in stats["structural_counts"].values() if value > 1),
            "text_recurrence_occurrences_gt1": sum(1 for value in stats["text_counts"].values() if value > 1),
        }
    enrichment = {}
    for key, field in (("signature_multiplicity", "_signature_multiplicity"),
                       ("state_multiplicity", "_state_multiplicity"),
                       ("root_multiplicity", "_root_multiplicity"),
                       ("semantic_recurrence", "_semantic_recurrence"),
                       ("structural_recurrence", "_structural_recurrence"),
                       ("text_recurrence", "_text_recurrence")):
        left = weighted_numeric([float(row[field]) for row, _ in rplus], [w for _, w in rplus])
        right = weighted_numeric([float(row[field]) for row, _ in cplus], [w for _, w in cplus])
        enrichment[key] = {"random_enriched": left, "curated_enriched": right,
                           "mean_delta_curated_minus_random": right.get("mean", 0) - left.get("mean", 0)}
    axes = {}
    for axis in ("redundancy", "semantic_novelty", "structural_coverage", "local_discrimination"):
        left = _weighted_axis(rplus, axis)
        right = _weighted_axis(cplus, axis)
        axes[axis] = {"random_enriched": left, "curated_enriched": right,
                      "total_variation": categorical_tv(left["feature_counts"], right["feature_counts"])}
    return {
        "full_bank": {"random": arm_summary("random", random_rows),
                      "curated": arm_summary("curated", curated_rows)},
        "enriched_mass": enrichment,
        "feature_axes": axes,
        "interpretation": "Repeated distinctions may be useful reinforcement; no direction is assumed from a redundancy label alone.",
    }
