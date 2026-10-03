"""Derive the Q10-GC0 support gate and conflict topology."""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_gc0 as GC0  # noqa: E402


DERIVED_ROOT = ROOT / "qualification" / "derived"
EXECUTION_PATH = ROOT / "qualification" / "execution" / "execution.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def identity_key(identity: list[Any] | tuple[Any, ...]) -> tuple[str, int, int]:
    return (str(identity[0]), int(identity[1]), int(identity[2]))


def endpoint_label(endpoint: str, set_index: int) -> str:
    return f"{endpoint}|set{set_index}"


def load_receipts(contract: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    execution = load_json(EXECUTION_PATH)
    require(execution["protocol"] == "Q10-GC0", "GC0 execution protocol drift")
    require(execution["sample"]["group_count"] == contract["sample"]["expected_group_count"], "GC0 execution sample count drift")
    receipts: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for relative in execution["group_receipts"]:
        path = ROOT / Path(str(relative))
        require(path.is_file(), f"GC0 group receipt missing: {relative}")
        value = load_json(path)
        require(value["protocol"] == "Q10-GC0", f"GC0 group receipt protocol drift: {relative}")
        require(len(value["palette"]) >= 1 and value["palette"][0]["roles"] == ["ZERO"], f"GC0 zero candidate missing: {relative}")
        identities = [str(item["candidate_identity"]) for item in value["palette"]]
        require(len(identities) == len(set(identities)), f"GC0 duplicate candidate identity: {relative}")
        require(value["palette_counts"]["zero_candidates"] == 1, f"GC0 zero count drift: {relative}")
        require(value["palette_counts"]["nonzero_candidates"] == len(value["palette"]) - 1, f"GC0 candidate count drift: {relative}")
        receipts.append(value)
        hashes[str(relative)] = GC0.RH1.CQ.digest(path)
    require(len({identity_key(item["identity"]) for item in receipts}) == len(receipts), "GC0 duplicate group identity")
    return execution, receipts, hashes


def global_support_gate(receipts: list[dict[str, Any]], states: dict[tuple[str, int], Any]) -> dict[str, Any]:
    baseline_mismatch: set[tuple[str, int, int]] = set()
    for (endpoint, set_index), state in states.items():
        baseline_mismatch.update(
            (str(endpoint), int(set_index), int(row))
            for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits))
            if actual != target
        )
    candidate_support: set[tuple[str, int, int]] = set()
    for receipt in receipts:
        endpoint, set_index, _ = receipt["identity"]
        for candidate in receipt["palette"][1:]:
            for row in candidate["support_metadata"]["active_physical_support_rows"]:
                candidate_support.add((str(endpoint), int(set_index), int(row)))
    covered = baseline_mismatch & candidate_support
    uncovered = baseline_mismatch - candidate_support
    outside = candidate_support - baseline_mismatch
    per_endpoint: list[dict[str, Any]] = []
    for key in sorted(states):
        endpoint, set_index = key
        baseline = {item for item in baseline_mismatch if item[:2] == key}
        support = {item for item in candidate_support if item[:2] == key}
        per_endpoint.append(
            {
                "endpoint": endpoint,
                "set_index": int(set_index),
                "baseline_global_mismatch_count": len(baseline),
                "candidate_bearing_physical_support_count": len(support),
                "covered_baseline_mismatch_count": len(baseline & support),
                "uncovered_baseline_mismatch_count": len(baseline - support),
                "coverage_fraction": (len(baseline & support) / len(baseline)) if baseline else 1.0,
            }
        )
    classification = "SUPPORT_COMPLETE" if not uncovered else "SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY"
    return {
        "classification": classification,
        "global_infeasibility_claim": False,
        "gc1_authorized": False,
        "baseline_global_mismatch_count": len(baseline_mismatch),
        "candidate_bearing_physical_support_count": len(candidate_support),
        "covered_baseline_mismatch_count": len(covered),
        "uncovered_baseline_mismatch_count": len(uncovered),
        "candidate_support_outside_baseline_mismatch_count": len(outside),
        "coverage_fraction": (len(covered) / len(baseline_mismatch)) if baseline_mismatch else 1.0,
        "uncovered_baseline_mismatch_keys": [list(item) for item in sorted(uncovered)],
        "candidate_bearing_support_keys": [list(item) for item in sorted(candidate_support)],
        "per_endpoint": per_endpoint,
        "scope": "fixed four-endpoint GC0 sample only",
    }


def conflict_topology(receipts: list[dict[str, Any]], states: dict[tuple[str, int], Any], groups: dict[tuple[str, int, int], Any]) -> dict[str, Any]:
    group_topologies: list[dict[str, Any]] = []
    cross_group: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    total_readout_conflicts = 0
    total_coordinate_conflicts = 0
    for receipt in receipts:
        endpoint, set_index, group_index = identity_key(receipt["identity"])
        state = states[(endpoint, set_index)]
        group = groups[(endpoint, set_index, group_index)]
        coordinate_ids = [int(value) for value in group.coordinates]
        support_by_coordinate = {
            coordinate: sorted(int(row) for row, _ in state.support_counts[coordinate])
            for coordinate in coordinate_ids
        }
        candidates = receipt["palette"]
        mappings = [
            {
                "candidate_identity": str(candidate["candidate_identity"]),
                "mapping": {int(pair[0]): int(pair[1]) for pair in candidate["canonical_mapping"]},
                "readout_bits": [int(value) for value in candidate["exact_readout_bits"]],
            }
            for candidate in candidates
        ]
        physical_rows = sorted({row for values in support_by_coordinate.values() for row in values})
        row_conflicts: list[dict[str, Any]] = []
        for row in physical_rows:
            exact_ids = [item["candidate_identity"] for item in mappings if item["readout_bits"][row] == state.target_readout_bits[row]]
            mismatch_ids = [item["candidate_identity"] for item in mappings if item["readout_bits"][row] != state.target_readout_bits[row]]
            if exact_ids and mismatch_ids:
                total_readout_conflicts += 1
                row_conflicts.append(
                    {
                        "row": int(row),
                        "support_coordinates": [coordinate for coordinate in coordinate_ids if row in support_by_coordinate[coordinate]],
                        "exact_candidate_ids": exact_ids,
                        "mismatch_candidate_ids": mismatch_ids,
                        "type": "readout_exactness_conflict",
                    }
                )
        pair_edges: list[dict[str, Any]] = []
        for left, right in combinations(coordinate_ids, 2):
            shared_rows = sorted(set(support_by_coordinate[left]) & set(support_by_coordinate[right]))
            if not shared_rows:
                continue
            observed_pairs = sorted(
                {
                    (item["mapping"].get(left, 0), item["mapping"].get(right, 0))
                    for item in mappings
                }
            )
            conflict = len(observed_pairs) > 1
            if conflict:
                total_coordinate_conflicts += 1
            pair_edges.append(
                {
                    "left_coordinate": left,
                    "right_coordinate": right,
                    "shared_physical_rows": shared_rows,
                    "observed_prefix_pairs": [list(pair) for pair in observed_pairs],
                    "conflict": conflict,
                    "type": "coordinate_shared_support_prefix_conflict" if conflict else "coordinate_shared_support_edge",
                }
            )
        for candidate in candidates[1:]:
            for coordinate, choice in candidate["canonical_mapping"]:
                if int(choice) != 0:
                    key = (endpoint, set_index, int(coordinate))
                    cross_group.setdefault(key, []).append(
                        {
                            "group_index": group_index,
                            "candidate_identity": candidate["candidate_identity"],
                            "prefix": int(choice),
                        }
                    )
        group_topologies.append(
            {
                "identity": [endpoint, set_index, group_index],
                "zero_candidate_identity": candidates[0]["candidate_identity"],
                "coordinate_readout_edges": [
                    {"coordinate": coordinate, "row": row, "support_edge": True}
                    for coordinate in coordinate_ids
                    for row in support_by_coordinate[coordinate]
                ],
                "readout_conflicts": row_conflicts,
                "coordinate_pair_edges": pair_edges,
                "conflict_counts": {
                    "readout_exactness_conflicts": len(row_conflicts),
                    "coordinate_shared_support_prefix_conflicts": sum(edge["conflict"] for edge in pair_edges),
                },
            }
        )
    cross_group_conflicts = []
    for key, observations in sorted(cross_group.items()):
        prefixes = sorted({int(item["prefix"]) for item in observations})
        if len(prefixes) > 1:
            cross_group_conflicts.append(
                {
                    "endpoint": key[0],
                    "set_index": key[1],
                    "coordinate": key[2],
                    "observed_prefixes": prefixes,
                    "observations": observations,
                    "type": "cross_group_coordinate_prefix_conflict",
                }
            )
    return {
        "protocol": "Q10-GC0",
        "diagnostic_only": True,
        "group_topologies": group_topologies,
        "cross_group_coordinate_prefix_conflicts": cross_group_conflicts,
        "totals": {
            "groups": len(group_topologies),
            "readout_exactness_conflict_rows": total_readout_conflicts,
            "coordinate_shared_support_prefix_conflicts": total_coordinate_conflicts,
            "cross_group_coordinate_prefix_conflicts": len(cross_group_conflicts),
        },
    }


def render_result(summary: dict[str, Any], status: str) -> str:
    gate = summary["global_gate"]
    counts = summary["counts"]
    lines = [
        "# Q10-GC0 result",
        "",
        "Q10-GC0 completed the sealed engineering-only four-endpoint qualification sample.",
        "",
        f"Status: `{status}`.",
        f"Endpoints: {counts['endpoint_count']}; groups/palettes: {counts['group_count']}; zero candidates: {counts['zero_candidate_count']}; nonzero candidates: {counts['nonzero_candidate_count']} of {counts['nonzero_candidate_requested']} requested.",
        f"Exact sequential-f32 evaluations: {counts['exact_unique_evaluations_including_zero']} including zero; {counts['exact_nonzero_replays']} nonzero replays.",
        f"Global sample support gate: `{gate['classification']}`; baseline mismatch rows {gate['baseline_global_mismatch_count']}, covered {gate['covered_baseline_mismatch_count']}, uncovered {gate['uncovered_baseline_mismatch_count']}, coverage {gate['coverage_fraction']:.6f}.",
        "",
        "Every retained entry carries canonical coordinate-id to prefix identity, committed f32 mapping bits, exact readout bits, D/P/G scores, newly damaged exact rows, geometry signatures, and support metadata. Zero candidates and palette shortfalls are preserved explicitly.",
        "",
        "The support result is a sample-scoped diagnostic. Incomplete support does not imply global infeasibility and does not authorize GC1 coalition assembly. Coordinate/readout conflict topology is diagnostic only. No behavioral seed, scientific promotion, or parent write occurred.",
        "",
        f"Conflict diagnostics: {summary['conflicts']['readout_exactness_conflict_rows']} readout-conflict rows, {summary['conflicts']['coordinate_shared_support_prefix_conflicts']} coordinate shared-support conflicts, {summary['conflicts']['cross_group_coordinate_prefix_conflicts']} cross-group coordinate-prefix conflicts.",
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    contract, preexecution = GC0.load_local_contract()
    bindings = GC0.verify_parent_provenance(contract, preexecution)
    execution, receipts, receipt_hashes = load_receipts(contract)
    frozen, states, groups, _, _ = GC0.load_sample(contract)
    require(len(frozen) == len(receipts), "GC0 receipt/sample cardinality drift")
    support = global_support_gate(receipts, states)
    topology = conflict_topology(receipts, states, groups)
    topology_path = DERIVED_ROOT / "conflict-topology.json"
    write_json(topology_path, topology)

    palette_shortfalls = [
        {
            "identity": item["identity"],
            "shortfall": item["palette_counts"]["nonzero_shortfall"],
            "eligible_nonzero_pool": item["candidate_generation"]["eligible_nonzero_pool"],
        }
        for item in receipts
        if item["palette_counts"]["nonzero_shortfall"] > 0
    ]
    status = "GC0_ENGINEERING_COMPLETE_SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY"
    if palette_shortfalls:
        status = "GC0_ENGINEERING_COMPLETE_PALETTE_SHORTFALL_SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY"
    execution["status"] = status
    execution["qualification"] = {
        "global_gate": support,
        "conflict_topology_path": "qualification/derived/conflict-topology.json",
        "gc1_authorized": False,
    }
    execution["group_receipt_sha256"] = receipt_hashes
    execution["execution_derivation"] = {
        "analyzer_sha256": GC0.RH1.CQ.digest(Path(__file__).resolve()),
        "derived_at": "2026-09-18T01:12:34.4358752Z",
    }
    GC0.write_json(EXECUTION_PATH, execution)
    execution_hash = GC0.RH1.CQ.digest(EXECUTION_PATH)
    GC0.write_json(
        ROOT / "qualification" / "execution.json",
        {
            "protocol": "Q10-GC0",
            "identity": "q10-gc0-v1",
            "status": status,
            "execution_receipt": "qualification/execution/execution.json",
            "execution_sha256": execution_hash,
            "plan_sha256": execution["plan_sha256"],
            "contract_sha256": execution["contract_sha256"],
            "scientific_promotion": False,
            "gc1_authorized": False,
        },
    )
    counts = execution["counts"]
    summary = {
        "protocol": "Q10-GC0",
        "identity": "q10-gc0-v1",
        "status": status,
        "plan_sha256": GC0.RH1.CQ.digest(ROOT / "PLAN.md"),
        "contract_sha256": GC0.RH1.CQ.digest(ROOT / "CONTRACT.json"),
        "execution_sha256": execution_hash,
        "parent_bindings_verified": bindings,
        "counts": counts,
        "sample": execution["sample"],
        "palette_status_counts": {
            "PALETTE_COMPLETE": sum(item["status"] == "PALETTE_COMPLETE" for item in receipts),
            "PALETTE_SHORTFALL_PRESERVED": sum(item["status"] == "PALETTE_SHORTFALL_PRESERVED" for item in receipts),
        },
        "palette_shortfalls": palette_shortfalls,
        "group_summaries": [
            {
                "identity": item["identity"],
                "palette_count": len(item["palette"]),
                "nonzero_shortfall": item["palette_counts"]["nonzero_shortfall"],
                "exact_unique_evaluations_including_zero": item["candidate_generation"]["exact_unique_evaluations_including_zero"],
                "termination": item["candidate_generation"]["termination"],
            }
            for item in receipts
        ],
        "global_gate": support,
        "conflicts": topology["totals"],
        "conflict_topology_path": "qualification/derived/conflict-topology.json",
        "firewall": {
            "engineering_only": True,
            "scientific_seed_bundles": 0,
            "behavioral_probe": False,
            "scientific_promotion": False,
            "gc1_authorized": False,
            "parent_writes": False,
        },
    }
    summary_path = DERIVED_ROOT / "SUMMARY.json"
    GC0.write_json(summary_path, summary)
    result_text = render_result(summary, status)
    result_path = DERIVED_ROOT / "RESULT.md"
    result_path.write_text(result_text, encoding="utf-8", newline="\n")
    status_receipt = {
        "protocol": "Q10-GC0",
        "identity": "q10-gc0-v1",
        "status": status,
        "plan_sha256": summary["plan_sha256"],
        "contract_sha256": summary["contract_sha256"],
        "execution_sha256": execution_hash,
        "derived_summary_sha256": GC0.RH1.CQ.digest(summary_path),
        "derived_result_sha256": GC0.RH1.CQ.digest(result_path),
        "conflict_topology_sha256": GC0.RH1.CQ.digest(topology_path),
        "support_gate": support,
        "palette_shortfall_group_count": len(palette_shortfalls),
        "scientific_promotion": False,
        "gc1_authorized": False,
    }
    write_json(DERIVED_ROOT / "STATUS.json", status_receipt)
    return summary


def main() -> int:
    try:
        summary = run()
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Q10-GC0 derivation failed closed: {error}") from error
    print(json.dumps({"status": summary["status"], "groups": summary["counts"]["group_count"], "coverage": summary["global_gate"]["coverage_fraction"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
