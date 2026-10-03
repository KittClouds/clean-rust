"""Hierarchical curation-score and signature-mobility audit; metadata only."""

from __future__ import annotations

import collections
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable

import audit_policy_mobility as v04
import build_policy_arms as policy
import state_exposure as v08e


ROOT = v08e.ROOT
RUN = Path(r"D:\codex-runs\jev-information-density-v08e")
SEALED = RUN / "sealed-pstar-v01"
REPAIR = RUN / "repair-v01"
OUT = RUN / "policy-mobility-v05"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _add(stats: dict[Any, list[float]], key: Any, value: float) -> None:
    row = stats.get(key)
    if row is None:
        stats[key] = [1.0, value, value * value]
    else:
        row[0] += 1.0
        row[1] += value
        row[2] += value * value


def _within_ss(stats: dict[Any, list[float]]) -> float:
    return sum(max(0.0, row[2] - row[1] * row[1] / row[0]) for row in stats.values())


def _between_ss(
    child_stats: dict[Any, list[float]], parent_stats: dict[Any, list[float]], child_parent: dict[Any, Any]
) -> float:
    return sum(
        child[0]
        * (child[1] / child[0] - parent_stats[child_parent[key]][1] / parent_stats[child_parent[key]][0]) ** 2
        for key, child in child_stats.items()
    )


def hierarchical_score_variance(
    rows: Iterable[tuple[str, str, str, float]],
) -> dict[str, Any]:
    """Population-variance decomposition: stratum/state/signature/member."""
    iterator = iter(rows)
    first = next(iterator, None)
    if first is None:
        raise ValueError("cannot decompose an empty score population")
    reference = float(first[3])
    strata: dict[str, list[float]] = {}
    state_cells: dict[tuple[str, str], list[float]] = {}
    signature_cells: dict[tuple[str, str, str], list[float]] = {}
    state_parent: dict[tuple[str, str], str] = {}
    signature_parent: dict[tuple[str, str, str], tuple[str, str]] = {}
    total_count = 0
    total_delta = 0.0
    total_delta_sq = 0.0
    for stratum, state, signature, score in itertools.chain((first,), iterator):
        delta = float(score) - reference
        state_key = (stratum, state)
        signature_key = (stratum, state, signature)
        _add(strata, stratum, delta)
        _add(state_cells, state_key, delta)
        _add(signature_cells, signature_key, delta)
        state_parent[state_key] = stratum
        signature_parent[signature_key] = state_key
        total_count += 1
        total_delta += delta
        total_delta_sq += delta * delta

    global_mean = total_delta / total_count
    total_ss = max(0.0, total_delta_sq - total_count * global_mean * global_mean)
    between_stratum = sum(
        row[0] * (row[1] / row[0] - global_mean) ** 2 for row in strata.values()
    )
    within_stratum_between_state = _between_ss(state_cells, strata, state_parent)
    within_state_between_signature = _between_ss(signature_cells, state_cells, signature_parent)
    within_signature = _within_ss(signature_cells)
    components = {
        "between_strata": between_stratum,
        "within_stratum_between_states": within_stratum_between_state,
        "within_state_between_supervised_signatures": within_state_between_signature,
        "within_supervised_signature": within_signature,
    }
    component_total = sum(components.values())
    if abs(component_total - total_ss) > max(1e-9, total_ss * 1e-8):
        raise ArithmeticError(f"hierarchical ANOVA does not close: {component_total} != {total_ss}")

    per_stratum: list[dict[str, Any]] = []
    for stratum, stratum_stats in sorted(strata.items()):
        local_states = {key: row for key, row in state_cells.items() if key[0] == stratum}
        local_sigs = {key: row for key, row in signature_cells.items() if key[0] == stratum}
        state_ss = sum(
            row[0] * (row[1] / row[0] - stratum_stats[1] / stratum_stats[0]) ** 2
            for row in local_states.values()
        )
        state_to_sig_ss = _between_ss(
            local_sigs,
            local_states,
            {key: signature_parent[key] for key in local_sigs},
        )
        within_sig_ss = _within_ss(local_sigs)
        local_total = state_ss + state_to_sig_ss + within_sig_ss
        local_variance = local_total / stratum_stats[0]
        per_stratum.append({
            "stratum_id": stratum,
            "group_count": int(stratum_stats[0]),
            "state_signature_count": len(local_states),
            "supervised_signature_count": len(local_sigs),
            "population_variance": local_variance,
            "components": {
                "between_states": state_ss / stratum_stats[0],
                "within_state_between_supervised_signatures": state_to_sig_ss / stratum_stats[0],
                "within_supervised_signature": within_sig_ss / stratum_stats[0],
            },
            "shares": {
                "between_states": state_ss / local_total if local_total else 0.0,
                "within_state_between_supervised_signatures": state_to_sig_ss / local_total if local_total else 0.0,
                "within_supervised_signature": within_sig_ss / local_total if local_total else 0.0,
            },
        })

    total_variance = total_ss / total_count
    return {
        "population": {
            "group_count": total_count,
            "stratum_count": len(strata),
            "state_stratum_cell_count": len(state_cells),
            "supervised_signature_cell_count": len(signature_cells),
            "population_variance": total_variance,
            "hierarchical_components": {
                name: value / total_count for name, value in components.items()
            },
            "component_shares": {
                name: value / total_ss if total_ss else 0.0 for name, value in components.items()
            },
            "closure_absolute_error": abs(component_total - total_ss) / total_count,
        },
        "per_stratum": per_stratum,
    }


def profile_preserving_cell(item: Any) -> tuple[Any, ...]:
    """Identity of a one-row replacement preserving every profile axis except selector input."""
    return (
        item.stratum_id,
        item.input_state,
        item.root_id,
        item.family_items,
        item.topology,
        item.intervention,
        item.kind,
        item.view,
        item.candidate_count,
        item.open_world,
        item.probability_source,
    )


def summarize_class_mobility(
    items: list[Any], selected_a: set[str], selected_b: set[str], score_by_id: dict[str, float]
) -> dict[str, Any]:
    """Count state-balanced class moves and strict-profile one-swap opportunities."""
    state_cells: dict[tuple[str, str], dict[str, Any]] = {}
    profile_cells: dict[tuple[Any, ...], dict[str, Any]] = {}
    selector_to_signatures: dict[str, set[str]] = collections.defaultdict(set)
    signature_to_selector: dict[str, set[str]] = collections.defaultdict(set)

    for item in items:
        signature = item.supervised_signature_sha256
        selector_to_signatures[item.input_selector].add(signature)
        signature_to_selector[signature].add(item.input_selector)
        state_key = (item.stratum_id, item.input_state)
        state = state_cells.setdefault(state_key, {
            "groups": 0,
            "signatures": set(),
            "selectors": set(),
            "support_by_signature": collections.Counter(),
            "selected_a_by_signature": collections.Counter(),
            "selected_b_by_signature": collections.Counter(),
        })
        state["groups"] += 1
        state["signatures"].add(signature)
        state["selectors"].add(item.input_selector)
        state["support_by_signature"][signature] += 1
        if item.group_id in selected_a:
            state["selected_a_by_signature"][signature] += 1
        if item.group_id in selected_b:
            state["selected_b_by_signature"][signature] += 1

        cell_key = profile_preserving_cell(item)
        cell = profile_cells.setdefault(cell_key, {
            "support_by_signature": collections.Counter(),
            "selected_a_by_signature": collections.Counter(),
            "selected_b_by_signature": collections.Counter(),
            "selected_a_groups": 0,
            "selected_b_groups": 0,
            "support_groups": 0,
            "curated_best_in": {},
            "curated_worst_out": {},
            "random_best_in": {},
            "random_worst_out": {},
        })
        cell["support_groups"] += 1
        cell["support_by_signature"][signature] += 1
        random_key = v04.frozen_key(item, score_by_id, "random")
        curated_key = v04.frozen_key(item, score_by_id, "curated")
        if item.group_id in selected_a:
            cell["selected_a_groups"] += 1
            cell["selected_a_by_signature"][signature] += 1
            if signature not in cell["curated_worst_out"] or curated_key > cell["curated_worst_out"][signature][0]:
                cell["curated_worst_out"][signature] = (curated_key, item)
            if signature not in cell["random_worst_out"] or random_key > cell["random_worst_out"][signature][0]:
                cell["random_worst_out"][signature] = (random_key, item)
        else:
            if signature not in cell["curated_best_in"] or curated_key < cell["curated_best_in"][signature][0]:
                cell["curated_best_in"][signature] = (curated_key, item)
            if signature not in cell["random_best_in"] or random_key < cell["random_best_in"][signature][0]:
                cell["random_best_in"][signature] = (random_key, item)
        if item.group_id in selected_b:
            cell["selected_b_groups"] += 1
            cell["selected_b_by_signature"][signature] += 1

    multi_state_cells = [cell for cell in state_cells.values() if len(cell["signatures"]) > 1]
    state_swap_edges = {"a": 0, "b": 0}
    for cell in state_cells.values():
        for arm in ("a", "b"):
            selected = cell[f"selected_{arm}_by_signature"]
            active = [sig for sig, count in selected.items() if count > 0]
            available = [
                sig for sig, count in cell["support_by_signature"].items()
                if count > selected.get(sig, 0)
            ]
            state_swap_edges[arm] += sum(1 for old in active for new in available if old != new)
    strict_cell_edges_a = 0
    strict_cell_edges_b = 0
    score_improving_edges = 0
    random_improving_edges = 0
    max_score_delta = 0.0
    max_random_delta_hex = None
    strict_cells_with_moves_a = 0
    strict_cells_with_moves_b = 0
    for cell in profile_cells.values():
        support = cell["support_by_signature"]
        for arm in ("a", "b"):
            selected = cell[f"selected_{arm}_by_signature"]
            active = [sig for sig, count in selected.items() if count > 0]
            available = [sig for sig, count in support.items() if count > selected.get(sig, 0)]
            edges = sum(1 for old in active for new in available if old != new)
            if arm == "a":
                strict_cell_edges_a += edges
                strict_cells_with_moves_a += edges > 0
            else:
                strict_cell_edges_b += edges
                strict_cells_with_moves_b += edges > 0

        active_a = [sig for sig, count in cell["selected_a_by_signature"].items() if count > 0]
        available_a = [sig for sig, count in support.items() if count > cell["selected_a_by_signature"].get(sig, 0)]

        for old in active_a:
            outgoing = cell["curated_worst_out"].get(old)
            random_out = cell["random_worst_out"].get(old)
            if outgoing is None or random_out is None:
                continue
            for new in available_a:
                if old == new:
                    continue
                incoming = cell["curated_best_in"].get(new)
                random_in = cell["random_best_in"].get(new)
                if incoming is not None:
                    score_delta = score_by_id[incoming[1].group_id] - score_by_id[outgoing[1].group_id]
                    if score_delta > 0:
                        score_improving_edges += 1
                        max_score_delta = max(max_score_delta, score_delta)
                if random_in is not None and random_in[0] < random_out[0]:
                    random_improving_edges += 1
                    rank_delta = int.from_bytes(random_out[0][0], "big") - int.from_bytes(random_in[0][0], "big")
                    if max_random_delta_hex is None or rank_delta > int(max_random_delta_hex):
                        max_random_delta_hex = str(rank_delta)

    return {
        "selector_input_to_supervised_signature": {
            "selector_input_count": len(selector_to_signatures),
            "selector_inputs_with_multiple_supervised_signatures": sum(len(v) > 1 for v in selector_to_signatures.values()),
            "supervised_signature_count": len(signature_to_selector),
            "signatures_with_multiple_selector_inputs": sum(len(v) > 1 for v in signature_to_selector.values()),
            "mapping_verified_one_to_one": all(len(v) == 1 for v in selector_to_signatures.values())
            and all(len(v) == 1 for v in signature_to_selector.values()),
        },
        "state_stratum_cells": {
            "count": len(state_cells),
            "cells_with_multiple_supervised_signatures": len(multi_state_cells),
            "groups_in_multi_signature_cells": sum(cell["groups"] for cell in multi_state_cells),
            "fraction_groups_in_multi_signature_cells": (
                sum(cell["groups"] for cell in multi_state_cells) / len(items)
            ),
            "signatures_per_cell": {
                "min": min((len(cell["signatures"]) for cell in state_cells.values()), default=0),
                "median": _median([len(cell["signatures"]) for cell in state_cells.values()]),
                "p90": _percentile([len(cell["signatures"]) for cell in state_cells.values()], 0.90),
                "max": max((len(cell["signatures"]) for cell in state_cells.values()), default=0),
            },
        },
        "state_balanced_class_exchange_opportunity": {
            "definition": "one selected supervised-signature occurrence exchanged for an available different signature in the same exact (stratum,state) cell; preserves state count and stratum exactly, but not necessarily the selector occurrence histogram or other profile axes",
            "candidate_signature_exchange_edges_from_capacity_A": state_swap_edges["a"],
            "candidate_signature_exchange_edges_from_capacity_B": state_swap_edges["b"],
        },
        "profile_axis_preserving_exchange_opportunity": {
            "definition": "same as above, additionally fixed root, all family IDs, topology, intervention, kind/view/cardinality/open-world/probability-source; only selector-input multiplicity histogram can change",
            "strict_profile_cells_with_any_exchange_from_A": strict_cells_with_moves_a,
            "strict_profile_cells_with_any_exchange_from_B": strict_cells_with_moves_b,
            "candidate_signature_exchange_edges_from_A": strict_cell_edges_a,
            "candidate_signature_exchange_edges_from_B": strict_cell_edges_b,
            "curation_score_improving_edges_from_A_before_selector_histogram_gate": score_improving_edges,
            "best_single_edge_curation_score_gain": max_score_delta,
            "random_priority_improving_edges_from_A_before_selector_histogram_gate": random_improving_edges,
            "best_single_edge_random_digest_rank_gain_integer": max_random_delta_hex,
            "interpretation_limit": "edge counts are support opportunities, not jointly feasible multi-step policy arms; selector-histogram and exact D_train gates remain to be checked",
        },
    }


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse policy-mobility output: {OUT}")
    contract = v08e.require_v03_integrity()
    receipt = policy.read_json(SEALED / "integrity-receipt.json")
    profile_path = SEALED / "pstar-profile.json"
    if receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS":
        raise ValueError("sealed P* receipt status mismatch")
    if sha256(profile_path) != receipt.get("sealed_profile_sha256"):
        raise ValueError("sealed P* profile hash mismatch")
    profile_body = policy.read_json(profile_path)
    items, _by_stratum, _quotas, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile_body["stratum_counts"]
    )
    scores = {
        item.group_id: policy.curation_score(features_by_id[item.group_id], feature_counts)
        for item in items
    }
    variance_rows = (
        (item.stratum_id, item.input_state, item.supervised_signature_sha256, scores[item.group_id])
        for item in items
    )
    variance = hierarchical_score_variance(variance_rows)

    selected_a = v04.load_manifest_ids(REPAIR / "best-witness-a-ids.jsonl")
    selected_b = v04.load_manifest_ids(REPAIR / "best-witness-b-ids.jsonl")
    if len(selected_a) != v08e.TARGET or len(selected_b) != v08e.TARGET:
        raise ValueError("capacity witness manifest size changed")
    mobility = summarize_class_mobility(items, selected_a, selected_b, scores)

    result = {
        "status": "POLICY_MOBILITY_DECOMPOSITION_COMPLETE_NO_MODEL_CONTACT",
        "scope": {
            "eligible_group_count": len(items),
            "strata_count": len(profile_body["stratum_counts"]),
            "Pstar_profile_sha256": sha256(profile_path),
            "model_contact": False,
            "feature_extraction": False,
            "training_materialized": False,
            "phoenix_access": False,
        },
        "curation_score_hierarchical_variance": variance,
        "class_count_and_balanced_exchange_mobility": mobility,
        "source_receipts": {
            "v08f_audit_report_sha256": sha256(RUN / "policy-mobility-v04" / "policy-mobility-audit.json"),
            "Pstar_profile_sha256": sha256(profile_path),
            "capacity_repair_result_sha256": sha256(REPAIR / "repair-result.json"),
            "curation_policy_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
            "policy_builder_source_sha256": sha256(Path(policy.__file__)),
        },
    }
    OUT.mkdir(parents=True, exist_ok=False)
    report = OUT / "policy-mobility-hierarchical-audit.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {
        "status": result["status"],
        "report_sha256": sha256(report),
        "builder_source_sha256": sha256(Path(__file__)),
        "Pstar_profile_sha256": sha256(profile_path),
        "model_contact": False,
        "feature_extraction": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    (OUT / "integrity-receipt.json").write_text(json.dumps(integrity, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "population_variance_shares": variance["population"]["component_shares"],
        "state_stratum_multi_signature_cells": mobility["state_stratum_cells"]["cells_with_multiple_supervised_signatures"],
        "strict_exchange_edges_A": mobility["profile_axis_preserving_exchange_opportunity"]["candidate_signature_exchange_edges_from_A"],
        "score_improving_edges_A": mobility["profile_axis_preserving_exchange_opportunity"]["curation_score_improving_edges_from_A_before_selector_histogram_gate"],
        "run_directory": str(OUT),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
