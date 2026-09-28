"""Metadata-only training-equivalence and frozen-policy mobility audit."""

from __future__ import annotations

import collections
import hashlib
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable

import build_policy_arms as policy
import state_exposure as v08e


ROOT = v08e.ROOT
RUN = Path(r"D:\codex-runs\jev-information-density-v08e")
SEALED = RUN / "sealed-pstar-v01"
REPAIR = RUN / "repair-v01"
OUT = RUN / "policy-mobility-v04"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def choose2(value: int) -> int:
    return value * (value - 1) // 2


def curation_axis_scores(
    features: tuple[tuple[str, ...], ...], counts: list[collections.Counter[str]]
) -> tuple[float, ...]:
    return tuple(
        sum(1.0 / math.sqrt(counts[index][feature]) for feature in values) / len(values)
        for index, values in enumerate(features)
    )


def score_variance_by_class(rows: Iterable[tuple[str, float]]) -> dict[str, Any]:
    """Population ANOVA and strict-score-pair decomposition by loss signature."""
    classes: dict[str, list[Any]] = {}
    global_scores: collections.Counter[float] = collections.Counter()
    count = 0
    total = 0.0
    total_sq = 0.0
    for signature, score in rows:
        score = float(score)
        stat = classes.get(signature)
        if stat is None:
            stat = [0, 0.0, 0.0, score, score, collections.Counter()]
            classes[signature] = stat
        stat[0] += 1
        stat[1] += score
        stat[2] += score * score
        stat[3] = min(stat[3], score)
        stat[4] = max(stat[4], score)
        stat[5][score] += 1
        global_scores[score] += 1
        count += 1
        total += score
        total_sq += score * score

    if not count:
        raise ValueError("cannot decompose an empty score population")
    grand_mean = total / count
    within_ss = 0.0
    between_ss = 0.0
    within_pairs = 0
    within_tied_pairs = 0
    size_histogram: collections.Counter[int] = collections.Counter()
    variable_classes = 0
    records_in_variable_classes = 0
    cross_stratum_classes = 0
    largest = []
    # Gather class strata separately in the data pass in main; keep this pure
    # helper focused on score and pair decompositions for easy unit testing.
    for signature, (n, value_sum, value_sq, low, high, score_counts) in classes.items():
        mean = value_sum / n
        within_ss += max(0.0, value_sq - value_sum * value_sum / n)
        between_ss += n * (mean - grand_mean) ** 2
        size_histogram[n] += 1
        if high > low:
            variable_classes += 1
            records_in_variable_classes += n
        within_pairs += choose2(n)
        within_tied_pairs += sum(choose2(k) for k in score_counts.values())
        largest.append((n, high - low, signature, low, high))

    total_ss = max(0.0, total_sq - total * total / count)
    total_pairs = choose2(count)
    globally_tied_pairs = sum(choose2(n) for n in global_scores.values())
    strict_score_pairs = total_pairs - globally_tied_pairs
    within_strict_pairs = within_pairs - within_tied_pairs
    largest.sort(key=lambda item: (-item[1], -item[0], item[2]))
    sizes = [size for size, classes_at_size in size_histogram.items() for _ in range(classes_at_size)]
    sizes.sort()
    return {
        "group_count": count,
        "signature_class_count": len(classes),
        "singleton_class_count": size_histogram.get(1, 0),
        "repeated_class_count": sum(v for k, v in size_histogram.items() if k > 1),
        "groups_in_repeated_classes": sum(k * v for k, v in size_histogram.items() if k > 1),
        "largest_class_size": max(size_histogram),
        "class_size_histogram": {str(k): v for k, v in sorted(size_histogram.items())},
        "class_size_p50": sizes[(len(sizes) - 1) // 2],
        "class_size_p90": sizes[min(len(sizes) - 1, math.ceil(0.90 * len(sizes)) - 1)],
        "curation_score": {
            "mean": grand_mean,
            "population_variance_total": total_ss / count,
            "population_variance_within_signature": within_ss / count,
            "population_variance_between_signature": between_ss / count,
            "variance_decomposition_residual": (total_ss - within_ss - between_ss) / count,
            "within_variance_fraction": within_ss / total_ss if total_ss else 0.0,
            "between_variance_fraction": between_ss / total_ss if total_ss else 0.0,
            "class_count_with_nonzero_score_range": variable_classes,
            "group_fraction_in_classes_with_nonzero_score_range": records_in_variable_classes / count,
            "largest_within_class_ranges": [
                {"class_sha256": sig, "class_size": n, "score_min": low,
                 "score_max": high, "score_range": spread}
                for n, spread, sig, low, high in largest[:10]
            ],
        },
        "pairwise_rank_discrimination": {
            "all_unordered_group_pairs": total_pairs,
            "pairs_with_strict_score_order": strict_score_pairs,
            "same_signature_pairs": within_pairs,
            "same_signature_pairs_with_strict_score_order": within_strict_pairs,
            "fraction_of_same_signature_pairs_with_strict_score_order": (
                within_strict_pairs / within_pairs if within_pairs else 0.0
            ),
            "fraction_of_strict_score_pairs_within_signature": (
                within_strict_pairs / strict_score_pairs if strict_score_pairs else 0.0
            ),
        },
        "_class_stats": classes,
        "_global_score_counts": global_scores,
    }


def frozen_key(item: Any, score_by_id: dict[str, float], policy_name: str) -> tuple[Any, ...]:
    if policy_name == "random":
        return (policy.digest(policy.RANDOM_SEED, item.group_id), item.group_id)
    if policy_name == "curated":
        return (-score_by_id[item.group_id], policy.digest(policy.CURATED_SEED, item.group_id), item.group_id)
    raise ValueError(f"unknown frozen policy {policy_name}")


def select_by_signature_queues(
    by_stratum: dict[str, list[Any]],
    quotas: dict[str, int],
    score_by_id: dict[str, float],
    policy_name: str,
) -> list[Any]:
    """Exact k-way merge of member queues grouped by supervised signature."""
    chosen = []
    for stratum in sorted(quotas):
        class_queues: dict[str, list[Any]] = collections.defaultdict(list)
        for item in by_stratum[stratum]:
            class_queues[item.supervised_signature_sha256].append(item)
        queues = []
        for signature, members in class_queues.items():
            members.sort(key=lambda item: frozen_key(item, score_by_id, policy_name))
            first = members[0]
            heapq.heappush(
                queues,
                (*frozen_key(first, score_by_id, policy_name), signature, 0, members),
            )
        for _ in range(quotas[stratum]):
            if not queues:
                raise ValueError(f"signature queues exhausted in stratum {stratum}")
            entry = heapq.heappop(queues)
            # Key fields precede the class identifier, member offset, and queue.
            signature, offset, members = entry[-3], entry[-2], entry[-1]
            chosen.append(members[offset])
            next_offset = offset + 1
            if next_offset < len(members):
                item = members[next_offset]
                heapq.heappush(
                    queues,
                    (*frozen_key(item, score_by_id, policy_name), signature, next_offset, members),
                )
    return chosen


def load_manifest_ids(path: Path) -> set[str]:
    return {
        str(json.loads(line)["group_id"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse policy-mobility output: {OUT}")
    contract = v08e.require_v03_integrity()
    pstar_receipt = policy.read_json(SEALED / "integrity-receipt.json")
    profile_path = SEALED / "pstar-profile.json"
    if pstar_receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS":
        raise ValueError("sealed P* status mismatch")
    if sha256(profile_path) != pstar_receipt.get("sealed_profile_sha256"):
        raise ValueError("sealed P* profile hash mismatch")
    profile_body = policy.read_json(profile_path)
    anchor_profile = policy.thaw_profile(profile_body["anchor_profile"])
    all_items, by_stratum, quotas, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile_body["stratum_counts"]
    )
    score_by_id = {
        item.group_id: policy.curation_score(features_by_id[item.group_id], feature_counts)
        for item in all_items
    }
    score_decomposition = score_variance_by_class(
        (item.supervised_signature_sha256, score_by_id[item.group_id]) for item in all_items
    )
    class_stats = score_decomposition.pop("_class_stats")
    global_score_counts = score_decomposition.pop("_global_score_counts")
    axis_score_decomposition = {}
    for axis_index, axis_name in enumerate(policy.AXES):
        axis_result = score_variance_by_class(
            (
                item.supervised_signature_sha256,
                curation_axis_scores(features_by_id[item.group_id], feature_counts)[axis_index],
            )
            for item in all_items
        )
        axis_result.pop("_class_stats")
        axis_result.pop("_global_score_counts")
        axis_score_decomposition[axis_name] = axis_result["curation_score"]

    # The signature class itself is the frozen per-group semantic-loss identity.
    class_strata: dict[str, set[str]] = collections.defaultdict(set)
    class_ordered: dict[str, set[str]] = collections.defaultdict(set)
    class_states: dict[str, set[str]] = collections.defaultdict(set)
    class_selectors: dict[str, set[str]] = collections.defaultdict(set)
    class_roots: dict[str, set[str]] = collections.defaultdict(set)
    for item in all_items:
        signature = item.supervised_signature_sha256
        class_strata[signature].add(item.stratum_id)
        class_ordered[signature].add(item.ordered_signature_sha256)
        class_states[signature].add(item.input_state)
        class_selectors[signature].add(item.input_selector)
        class_roots[signature].add(item.root_id)
    multi_stratum_classes = sum(len(values) > 1 for values in class_strata.values())
    multi_stratum_rows = sum(class_stats[key][0] for key, values in class_strata.items() if len(values) > 1)
    multi_order_classes = sum(len(values) > 1 for values in class_ordered.values())

    def within_class_variation(values_by_class: dict[str, set[str]]) -> dict[str, Any]:
        varying = [key for key, values in values_by_class.items() if len(values) > 1]
        affected_rows = sum(class_stats[key][0] for key in varying)
        return {
            "classes_with_multiple_values": len(varying),
            "rows_in_varying_classes": affected_rows,
            "row_fraction_in_varying_classes": affected_rows / len(all_items),
            "max_distinct_values_in_one_class": max((len(values_by_class[key]) for key in varying), default=1),
        }

    raw_random, raw_curated, _ = policy.select_arms(by_stratum, quotas, feature_counts, features_by_id)
    class_random = select_by_signature_queues(by_stratum, quotas, score_by_id, "random")
    class_curated = select_by_signature_queues(by_stratum, quotas, score_by_id, "curated")
    class_selector_equivalence = {
        "random_selected_ids_exactly_match_raw_frozen_selector": (
            {x.group_id for x in raw_random} == {x.group_id for x in class_random}
        ),
        "curated_selected_ids_exactly_match_raw_frozen_selector": (
            {x.group_id for x in raw_curated} == {x.group_id for x in class_curated}
        ),
        "implementation": "per-stratum per-signature sorted member queues, exact k-way merge; retains each member score/hash/metadata",
        "naive_one_representative_per_class_is_semantics_preserving": False,
    }
    if not all(class_selector_equivalence[key] for key in (
        "random_selected_ids_exactly_match_raw_frozen_selector",
        "curated_selected_ids_exactly_match_raw_frozen_selector",
    )):
        raise AssertionError("class-queue selector changed frozen selection semantics")

    tolerances = {
        "unique_relative_error_max": contract["design"]["profile_constraints"]["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": contract["design"]["profile_constraints"]["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": contract["design"]["profile_constraints"]["extra_family_axis_tv_max"],
    }
    raw_profiles = {
        "random": v08e.core.profile(raw_random),
        "curated": v08e.core.profile(raw_curated),
    }
    random_vs_anchor = v08e.core.profile_check(anchor_profile, raw_profiles["random"], tolerances)
    curated_vs_anchor = v08e.core.profile_check(anchor_profile, raw_profiles["curated"], tolerances)
    pair_profile = v08e.core.profile_check(raw_profiles["random"], raw_profiles["curated"], tolerances)
    policy_distance = v08e.core.exact_training_distance(raw_random, raw_curated)
    score_random = sum(score_by_id[item.group_id] for item in raw_random) / len(raw_random)
    score_curated = sum(score_by_id[item.group_id] for item in raw_curated) / len(raw_curated)

    # Compare the already validated far-apart P* capacity witnesses. This is a
    # mobility control, not a curation/random arm claim.
    ids_a = load_manifest_ids(REPAIR / "best-witness-a-ids.jsonl")
    ids_b = load_manifest_ids(REPAIR / "best-witness-b-ids.jsonl")
    by_id = {item.group_id: item for item in all_items}
    arm_a = [by_id[group_id] for group_id in sorted(ids_a)]
    arm_b = [by_id[group_id] for group_id in sorted(ids_b)]
    capacity_a_check = v08e.core.profile_check(anchor_profile, v08e.core.profile(arm_a), tolerances)
    capacity_b_check = v08e.core.profile_check(anchor_profile, v08e.core.profile(arm_b), tolerances)
    capacity_pair_check = v08e.core.profile_check(v08e.core.profile(arm_a), v08e.core.profile(arm_b), tolerances)
    capacity_distance = v08e.core.exact_training_distance(arm_a, arm_b)
    capacity_score_delta = (
        sum(score_by_id[item.group_id] for item in arm_b) -
        sum(score_by_id[item.group_id] for item in arm_a)
    ) / v08e.TARGET

    # Compact the observed frontier from prior metadata-only attempts.
    witness_report = policy.read_json(RUN / "witness-pair-policy-v01" / "witness-pair-policy-report.json")
    best_witness = witness_report.get("best_profile_valid_probe") or {}
    witness_1000 = next((x for x in witness_report.get("probes", []) if x.get("replacement_count") == 1000), {})
    prior_policy = policy.read_json(RUN / "policy-arms-v01" / "policy-arm-validation.json")
    prior_reservoir = policy.read_json(RUN / "reservoir-policy-v01" / "reservoir-policy-validation.json")
    frontier = {
        "capacity_witness_A_vs_B": {
            "D_train": capacity_distance["exact_training_signature_distance"],
            "D_supervised": capacity_distance["supervised_signature_distance"],
            "A_profile_pass": capacity_a_check["all_pass"],
            "B_profile_pass": capacity_b_check["all_pass"],
            "pair_profile_pass": capacity_pair_check["all_pass"],
            "pair_profile_tvs": {
                "state": capacity_pair_check["state_input"]["occurrence_histogram_tv"],
                "selector": capacity_pair_check["selector_input"]["occurrence_histogram_tv"],
                "root": capacity_pair_check["root"]["occurrence_histogram_tv"],
            },
            "D_train_per_state_tv": (
                capacity_distance["exact_training_signature_distance"] /
                max(capacity_pair_check["state_input"]["occurrence_histogram_tv"], 1e-15)
            ),
            "curation_mean_score_delta_B_minus_A": capacity_score_delta,
            "interpretation": "proves matched-profile learner-visible capacity; not a frozen-policy arm pair",
        },
        "frozen_group_selector_pair": {
            "D_train": policy_distance["exact_training_signature_distance"],
            "curation_mean_score_delta": score_curated - score_random,
            "random_state_tv_vs_Pstar": random_vs_anchor["state_input"]["occurrence_histogram_tv"],
            "curated_state_tv_vs_Pstar": curated_vs_anchor["state_input"]["occurrence_histogram_tv"],
            "random_profile_pass": random_vs_anchor["all_pass"],
            "curated_profile_pass": curated_vs_anchor["all_pass"],
            "pair_profile_pass": pair_profile["all_pass"],
        },
        "reservoir_candidate": {
            "D_train": prior_reservoir.get("treatment", {}).get("D_train"),
            "curation_score_delta": prior_reservoir.get("treatment", {}).get("curation_score_delta"),
            "state_tv": prior_reservoir.get("composition", {}).get("C_vs_anchor", {}).get("state_input", {}).get("occurrence_histogram_tv"),
            "selector_tv": prior_reservoir.get("composition", {}).get("C_vs_anchor", {}).get("selector_input", {}).get("occurrence_histogram_tv"),
            "root_tv": prior_reservoir.get("composition", {}).get("C_vs_anchor", {}).get("root", {}).get("occurrence_histogram_tv"),
            "profile_pass": prior_reservoir.get("composition", {}).get("C_vs_anchor", {}).get("all_pass"),
        },
        "witness_pair_500_swap": {
            "D_train": best_witness.get("D_train"),
            "curation_score_gain_total": best_witness.get("curation_score_gain_total"),
            "D_train_per_replacement": (
                best_witness.get("D_train", 0.0) / best_witness.get("replacement_count", 1)
                if best_witness else None
            ),
            "state_tv": best_witness.get("state_tv"),
            "selector_tv": best_witness.get("selector_tv"),
            "root_tv": best_witness.get("root_tv"),
            "profile_pass": best_witness.get("profile_pass"),
        },
        "witness_pair_1000_swap": {
            "D_train": witness_1000.get("D_train"),
            "curation_score_gain_total": witness_1000.get("curation_score_gain_total"),
            "state_tv": witness_1000.get("state_tv"),
            "profile_pass": witness_1000.get("profile_pass"),
        },
    }

    class_spans = {
        "signature_classes_crossing_strata": multi_stratum_classes,
        "rows_in_cross_stratum_classes": multi_stratum_rows,
        "fraction_rows_in_cross_stratum_classes": multi_stratum_rows / len(all_items),
        "classes_with_multiple_ordered_signatures": multi_order_classes,
        "within_class_profile_contribution_variation": {
            "state_signature": within_class_variation(class_states),
            "selector_input_signature": within_class_variation(class_selectors),
            "root_id": within_class_variation(class_roots),
        },
        "class_metadata_dimensions": {
            "stratum": "stratified member queues are required",
            "state_signature": "member-level profile contribution is retained",
            "selector_input_signature": "member-level profile contribution is retained",
            "root_id": "member-level profile contribution is retained",
            "curation_score": "member-level score is retained",
            "random_priority": "member-level frozen SHA rank is retained",
        },
    }

    result = {
        "status": "POLICY_MOBILITY_AUDITED_NO_MATCHED_ARMS",
        "scope": {
            "eligible_group_count": len(all_items),
            "strata_count": len(quotas),
            "sealed_pstar_sha256": sha256(profile_path),
            "model_contact": False,
            "feature_extraction": False,
            "training_materialized": False,
            "phoenix_access": False,
        },
        "training_equivalence_definition": {
            "primary_key": "supervised_signature_sha256",
            "meaning": "frozen v0.5 per-group semantic-loss identity; includes state/query input, candidate surfaces/targets, view/kind, probability source, loss mode, weights, and candidate-order augmentation semantics",
            "caveat": "bank-selected directed invariance-pair role events are arm-dependent and are handled separately by exact_training_distance; score variance uses the stable per-group supervised identity",
        },
        "curation_score_equivalence_audit": {
            **score_decomposition,
            "per_axis_variance_decomposition": axis_score_decomposition,
        },
        "class_structure": class_spans,
        "class_indexed_selector_equivalence": class_selector_equivalence,
        "policy_mobility_frontier": frontier,
        "policy_construction_decision": {
            "profile_constraints_changed": False,
            "frozen_curation_objective_changed": False,
            "frozen_random_priority_changed": False,
            "learner_visible_D_train_gate": 0.10,
            "matched_policy_arms_ready": False,
            "model_contact_authorized": False,
            "reason": "class-indexed execution reproduces the frozen selectors exactly; available candidates still fail profile or learner-visible treatment requirements",
        },
        "input_artifacts": {
            "pstar_integrity_receipt_sha256": sha256(SEALED / "integrity-receipt.json"),
            "pstar_profile_sha256": sha256(profile_path),
            "capacity_repair_result_sha256": sha256(REPAIR / "repair-result.json"),
            "frozen_policy_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
            "policy_builder_source_sha256": sha256(Path(policy.__file__)),
        },
    }
    OUT.mkdir(parents=True, exist_ok=False)
    report = OUT / "policy-mobility-audit.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "status": result["status"],
        "report_sha256": sha256(report),
        "builder_source_sha256": sha256(Path(__file__)),
        "pstar_profile_sha256": sha256(profile_path),
        "model_contact": False,
        "feature_extraction": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    (OUT / "integrity-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "groups": len(all_items),
        "signature_classes": score_decomposition["signature_class_count"],
        "within_variance_fraction": score_decomposition["curation_score"]["within_variance_fraction"],
        "within_rank_pair_fraction": score_decomposition["pairwise_rank_discrimination"]["fraction_of_strict_score_pairs_within_signature"],
        "class_queue_selectors_exact": all(class_selector_equivalence[k] for k in (
            "random_selected_ids_exactly_match_raw_frozen_selector",
            "curated_selected_ids_exactly_match_raw_frozen_selector",
        )),
        "capacity_D_train": capacity_distance["exact_training_signature_distance"],
        "frozen_policy_D_train": policy_distance["exact_training_signature_distance"],
        "model_contact": False,
        "run_directory": str(OUT),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
