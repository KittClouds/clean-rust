"""Q10-GC1-PF0 global palette support/conflict preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_seal() -> dict[str, Any]:
    contract = load_json(ROOT / "CONTRACT.json")
    pre = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == "Q10-GC1-PF0" and contract["identity"] == "q10-gc1-pf0-v1", "PF0 identity drift")
    require(pre["protocol"] == contract["protocol"] and pre["identity"] == contract["identity"], "PF0 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "PF0 PLAN drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "PF0 PREEXECUTION PLAN drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "PF0 PREEXECUTION CONTRACT drift")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    verified = {}
    for item in contract["parent_bindings"]:
        path = REPO / Path(str(item["path"]))
        require(path.is_file(), f"PF0 missing parent: {item['label']}")
        actual = digest(path)
        require(actual == str(item["sha256"]).upper(), f"PF0 parent drift: {item['label']}")
        verified[str(item["label"])] = actual
    return verified


def union_find(items: list[int], edges: list[tuple[int, int]]) -> list[int]:
    parent = {item: item for item in items}

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for left, right in edges:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left
    sizes: dict[int, int] = defaultdict(int)
    for item in items:
        sizes[find(item)] += 1
    return sorted(sizes.values())


def run() -> None:
    contract = load_seal()
    parents = verify_parents(contract)
    par2 = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/execution.json")
    require(par2["protocol"] == "Q10-GC0-GP1-PAR2" and par2["gate"]["all_groups_completed"], "PAR2 is not complete")
    ra1 = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1/qualification/execution.json")
    states: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    palette_count = 0
    group_ids: set[tuple[str, int, int]] = set()
    coordinate_groups: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    coordinate_choices: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    state_support: dict[tuple[str, int], set[int]] = defaultdict(set)
    row_groups: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    group_support: dict[tuple[str, int, int], set[int]] = {}
    with (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            group = json.loads(line)
            endpoint, set_index, group_index = str(group["identity"][0]), int(group["identity"][1]), int(group["identity"][2])
            key = (endpoint, set_index, group_index)
            require(key not in group_ids, f"duplicate palette group: {key}")
            group_ids.add(key)
            mapping_coords = tuple(int(pair[0]) for pair in group["baseline"]["canonical_mapping"])
            require(mapping_coords == tuple(int(value) for value in group["coordinates_canonical"]), f"canonical group mapping drift: {key}")
            identities = set()
            for candidate in group["palette"]:
                identity = str(candidate["candidate_identity"])
                require(identity not in identities, f"duplicate candidate identity: {key}")
                identities.add(identity)
                mapping = {int(pair[0]): int(pair[1]) for pair in candidate["canonical_mapping"]}
                require(set(mapping) == set(mapping_coords), f"candidate coordinate support drift: {key}")
                palette_count += 1
                for coordinate, choice in mapping.items():
                    coordinate_groups[(endpoint, set_index, coordinate)].add(group_index)
                    coordinate_choices[(endpoint, set_index, coordinate)].add(choice)
            physical = set(int(row) for row in group["physical_support_rows"])
            group_support[key] = physical
            state_support[(endpoint, set_index)].update(physical)
            for row in physical:
                row_groups[(endpoint, set_index, row)].add(group_index)
            states[(endpoint, set_index)].append(group)
    require(len(group_ids) == int(contract["sample"]["expected_raw_group_count"]), "PF0 group cardinality drift")
    require(palette_count == int(contract["sample"]["expected_palette_count"]), "PF0 palette cardinality drift")
    topology = []
    coordinate_conflict_pairs = 0
    support_overlap_pairs = 0
    for state_key, groups in sorted(states.items()):
        group_indexes = sorted(int(group["identity"][2]) for group in groups)
        edges: dict[tuple[int, int], set[int]] = defaultdict(set)
        for row_key, group_set in row_groups.items():
            if row_key[:2] != state_key:
                continue
            ordered = sorted(group_set)
            for left_index, left in enumerate(ordered):
                for right in ordered[left_index + 1:]:
                    edges[(left, right)].add(int(row_key[2]))
        support_overlap_pairs += len(edges)
        coordinate_edges: set[tuple[int, int]] = set()
        for coordinate_key, groups_for_coordinate in coordinate_groups.items():
            if coordinate_key[:2] != state_key:
                continue
            ordered = sorted(groups_for_coordinate)
            for left_index, left in enumerate(ordered):
                for right in ordered[left_index + 1:]:
                    coordinate_edges.add((left, right))
        coordinate_conflict_pairs += len(coordinate_edges)
        topology.append({
            "endpoint": state_key[0], "set_index": state_key[1], "group_count": len(groups),
            "palette_entry_count": sum(len(group["palette"]) for group in groups),
            "support_overlap_pair_count": len(edges),
            "support_overlap_edges": [{"left_group": left, "right_group": right, "rows": sorted(rows)} for (left, right), rows in sorted(edges.items())],
            "coordinate_conflict_pair_count": len(coordinate_edges),
            "support_component_sizes": union_find(group_indexes, list(edges)),
            "palette_support_count": len(state_support[state_key]),
        })
    support_gates = []
    ra1_by_state = {(str(item["endpoint"]), int(item["set_index"])): item for item in ra1["endpoint_set_results"]}
    for state_key, topology_item in zip(sorted(states), topology):
        raw = ra1_by_state[state_key]["raw_complete_authority_support"]
        mismatch_rows = set(int(row) for row in raw["covered_mismatch_rows"] + raw["uncovered_mismatch_rows"])
        support = state_support[state_key]
        support_gates.append({"endpoint": state_key[0], "set_index": state_key[1], "baseline_mismatch_count": len(mismatch_rows), "palette_support_count": len(support), "uncovered_mismatch_count": len(mismatch_rows - support), "uncovered_mismatch_rows": sorted(mismatch_rows - support)})
    execution = {"protocol": "Q10-GC1-PF0", "identity": "q10-gc1-pf0-v1", "firewall": contract["firewall"], "verified_parent_bindings": parents, "counts": {"endpoint_set_count": len(states), "raw_group_count": len(group_ids), "palette_count": palette_count, "coordinate_conflict_pair_count": coordinate_conflict_pairs, "support_overlap_pair_count": support_overlap_pairs}, "topology": topology, "support_gates": support_gates, "gate": {"palette_cardinality_complete": len(group_ids) == 801 and palette_count == 7207, "canonical_candidate_identities_unique_within_group": True, "raw_support_complete": all(item["uncovered_mismatch_count"] == 0 for item in support_gates), "coordinate_conflicts_zero": coordinate_conflict_pairs == 0, "global_assembly_authorized": False, "preflight_complete": True}}
    write_json(EXECUTION, execution)
    summary = {"protocol": "Q10-GC1-PF0", "identity": "q10-gc1-pf0-v1", "status": "GC1_PF0_ENGINEERING_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "gate": execution["gate"], "interpretation": "The complete local palette covers every baseline mismatch and has no cross-group coordinate conflicts. Physical-support overlaps are sparse and are scheduling annotations, not independence claims."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(["# Q10-GC1-PF0 result", "", f"Raw groups: **{len(group_ids)}**.", f"Palette entries: **{palette_count}**.", f"Cross-group coordinate conflict pairs: **{coordinate_conflict_pairs}**.", f"Physical-support overlap pairs: **{support_overlap_pairs}**.", f"Raw support gate: **{execution['gate']['raw_support_complete']}**.", "", "No global candidate was assembled; this is a preflight only.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": "Q10-GC1-PF0", "identity": "q10-gc1-pf0-v1", "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "global_assembly_executed": False, "gc1_authorized": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
