"""Q10-GC1-PAR2 validated group-level global coalition assembler."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2 = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0 = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(F2))
sys.path.insert(0, str(GC0))
import run_rh1 as RH1  # noqa: E402
import run_gc0 as GC0RUN  # noqa: E402

PROTOCOL = "Q10-GC1-PAR3"
IDENTITY = "q10-gc1-par3-v1"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"
_CACHE: dict[str, Any] = {}
LEGAL_CHOICES = frozenset((0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16))


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


def bits_hash(values: list[int] | tuple[int, ...]) -> str:
    payload = b"".join(int(value).to_bytes(4, "little", signed=False) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def load_seal() -> dict[str, Any]:
    contract = load_json(ROOT / "CONTRACT.json")
    pre = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "GC1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "GC1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "GC1 PLAN drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "GC1 PREEXECUTION PLAN drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "GC1 PREEXECUTION CONTRACT drift")
    require(contract["sealed_runner_sha256"] == digest(Path(__file__)), "GC1 sealed runner drift")
    require(pre["runner_sha256"] == digest(Path(__file__)), "GC1 PREEXECUTION runner drift")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    result = {}
    for item in contract["parent_bindings"]:
        path = REPO / Path(str(item["path"]))
        require(path.is_file(), f"GC1 missing parent: {item['label']}")
        actual = digest(path)
        require(actual == str(item["sha256"]).upper(), f"GC1 parent drift: {item['label']}")
        result[str(item["label"])] = actual
    return result


def compact_palettes() -> dict[tuple[str, int], list[dict[str, Any]]]:
    path = REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
    result: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        group = json.loads(line)
        key = (str(group["identity"][0]), int(group["identity"][1]))
        candidates = []
        for candidate in group["palette"]:
            candidates.append({
                "candidate_identity": str(candidate["candidate_identity"]),
                "roles": list(candidate["roles"]),
                "canonical_mapping": [[int(pair[0]), int(pair[1])] for pair in candidate["canonical_mapping"]],
                "committed_f32_mapping": [[int(pair[0]), int(pair[1]), int(pair[2])] for pair in candidate["committed_f32_mapping"]],
            })
        result.setdefault(key, []).append({
            "group_index": int(group["identity"][2]),
            "coordinates": [int(value) for value in group["coordinates_canonical"]],
            "physical_support_rows": [int(value) for value in group["physical_support_rows"]],
            "baseline_p": group["baseline"]["scores"]["P"],
            "palette": candidates,
        })
    return result


def validate_candidate(state: Any, group: dict[str, Any], candidate: dict[str, Any]) -> None:
    coordinates = tuple(int(value) for value in group["coordinates"])
    canonical = tuple((int(pair[0]), int(pair[1])) for pair in candidate["canonical_mapping"])
    committed = tuple((int(pair[0]), int(pair[1]), int(pair[2])) for pair in candidate["committed_f32_mapping"])
    require(canonical == tuple(sorted(canonical)), "GC1 canonical mapping is not coordinate sorted")
    require(committed == tuple(sorted(committed)), "GC1 committed mapping is not coordinate sorted")
    require(tuple(pair[0] for pair in canonical) == coordinates, "GC1 canonical coordinate coverage drift")
    require(tuple(pair[0] for pair in committed) == coordinates, "GC1 committed coordinate coverage drift")
    mapping = {coordinate: choice for coordinate, choice in canonical}
    require(len(mapping) == len(coordinates), "GC1 duplicate canonical coordinate")
    require(RH1.CQ.state_identity(mapping) == str(candidate["candidate_identity"]), "GC1 candidate identity drift")
    for coordinate, choice, committed_bits in committed:
        require(mapping[coordinate] == choice, f"GC1 canonical/committed choice drift: {coordinate}")
        require(choice in LEGAL_CHOICES, f"GC1 illegal prefix choice: {choice}")
        require(bool(state.permitted[coordinate]) and coordinate in state.interior, f"GC1 candidate coordinate outside permitted interior: {coordinate}")
        expected = RH1.PF5.legal_prefix_bits(int(state.baseline_weight_bits[coordinate]), choice)
        require(expected is not None and int(expected) == committed_bits, f"GC1 committed f32 byte drift: {coordinate}")
        if choice == 0:
            require(committed_bits == int(state.baseline_weight_bits[coordinate]), "GC1 ZERO byte drift")

    if candidate["roles"] == ["ZERO"]:
        require(all(choice == 0 for _, choice in canonical), "GC1 ZERO choice drift")
        require(all(bits == int(state.baseline_weight_bits[coordinate]) for coordinate, _, bits in committed), "GC1 ZERO committed-byte drift")


def validate_palette_library(states: dict[tuple[str, int], Any] | None, palettes: dict[tuple[str, int], list[dict[str, Any]]], contract: dict[str, Any]) -> dict[str, int]:
    expected_groups = int(contract["sample"]["expected_raw_group_count"])
    expected_palettes = int(contract["sample"]["expected_palette_count"])
    require(sum(len(groups) for groups in palettes.values()) == expected_groups, "GC1 raw group count drift")
    require(sum(len(group["palette"]) for groups in palettes.values() for group in groups) == expected_palettes, "GC1 palette count drift")
    zero_count = 0
    candidate_count = 0
    for task, groups in palettes.items():
        if states is not None:
            require(task in states, f"GC1 palette state missing runtime: {task}")
        seen_groups = set()
        for group in groups:
            group_index = int(group["group_index"])
            require(group_index not in seen_groups, "GC1 duplicate group index")
            seen_groups.add(group_index)
            zeros = [candidate for candidate in group["palette"] if candidate["roles"] == ["ZERO"]]
            require(len(zeros) == 1, "GC1 ZERO candidate cardinality drift")
            identities = [str(candidate["candidate_identity"]) for candidate in group["palette"]]
            require(len(identities) == len(set(identities)), "GC1 duplicate candidate identity within group")
            zero_count += 1
            candidate_count += len(group["palette"])
            for candidate in group["palette"]:
                if states is not None:
                    validate_candidate(states[task], group, candidate)
        require(len(seen_groups) == len(groups), "GC1 group coverage drift")
    return {"raw_group_count": sum(len(groups) for groups in palettes.values()), "palette_count": candidate_count, "zero_candidate_count": zero_count}


def validate_group_topology(state: Any, group: dict[str, Any], raw_group: Any) -> None:
    require(tuple(group["coordinates"]) == tuple(raw_group.coordinates), "GC1 palette/runtime coordinate topology drift")
    expected_support = sorted({int(row_index) for coordinate in raw_group.coordinates for row_index, _ in state.support_counts[coordinate]})
    require([int(row) for row in group["physical_support_rows"]] == expected_support, "GC1 palette/runtime physical-support topology drift")
    baseline = GC0RUN.score_rows(state.baseline_readout_bits, state.target_readout_bits, expected_support)
    require(baseline == group["baseline_p"], "GC1 palette/runtime baseline score drift")


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def geometry_and_debt(state: Any, weight_bits: tuple[int, ...], pf5_contract: dict[str, Any]) -> tuple[dict[str, Any], tuple[float, float, float]]:
    weights = tuple(RH1.PF5.from_bits(raw) for raw in weight_bits)
    geometry = RH1.PF5.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    axis_scale = max(abs(state.target_axis), 1.0e-12)
    norm_scale = max(state.target_norm, 1.0e-12)
    debt = ((geometry["final_axis"] - geometry["target_axis"]) / axis_scale, (geometry["final_norm"] - geometry["target_norm"]) / norm_scale, float(geometry["cue_linear_normalized_error"]))
    require(all(math.isfinite(float(value)) for value in debt), "GC1 non-finite geometry debt")
    return geometry, debt


def evaluate(state: Any, weight_bits: tuple[int, ...], selected: tuple[tuple[int, str], ...], active_groups: int, pf5_contract: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    readout = tuple(int(value) for value in RH1.PF5.readout_bits(state.rows, tuple(RH1.PF5.from_bits(raw) for raw in weight_bits)))
    score = GC0RUN.score_rows(readout, state.target_readout_bits, range(len(state.rows)))
    geometry, debt = geometry_and_debt(state, weight_bits, pf5_contract)
    guard = contract["intermediate_geometry_guardrails"]
    guard_pass = abs(debt[0]) <= float(guard["axis_normalized_abs"]) and abs(debt[1]) <= float(guard["norm_normalized_abs"]) and abs(debt[2]) <= float(guard["cue_linear_normalized_abs"])
    final_pass = RH1.PF5.final_geometry_pass(geometry, pf5_contract)
    return {"weight_bits": weight_bits, "readout_bits": readout, "score": score, "debt": debt, "geometry": geometry, "guard_pass": guard_pass, "final_pass": final_pass, "selected": selected, "active_groups": active_groups}


def rank_state(item: dict[str, Any]) -> tuple[Any, ...]:
    debt = item["debt"]
    return (score_key(item["score"]), abs(float(debt[0])) + abs(float(debt[1])) + abs(float(debt[2])), int(item["active_groups"]), item["selected"])


def select_beam(candidates: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=rank_state)
    exploit_width = int(contract["assembly"]["exploit_width"])
    explore_width = int(contract["assembly"]["explore_width"])
    beam_width = int(contract["assembly"]["beam_width"])
    require(exploit_width + explore_width == beam_width, "GC1 beam lane widths drift")
    exploit = ordered[:exploit_width]
    selected = list(exploit)
    seen = {item["selected"] for item in selected}
    buckets = {}
    for item in ordered[exploit_width:]:
        debt = item["debt"]
        bucket = (round(debt[0] * 4096), round(debt[1] * 4096), round(debt[2] * 4096), item["active_groups"])
        if bucket not in buckets:
            buckets[bucket] = item
    for item in sorted(buckets.values(), key=rank_state)[:explore_width]:
        if len(selected) >= beam_width:
            break
        if item["selected"] not in seen:
            selected.append(item)
            seen.add(item["selected"])
    return selected


def assemble_state(task: tuple[str, int], groups: list[dict[str, Any]], state: Any, pf5_contract: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    # The PF0 topology established zero coordinate overlap. Still verify each
    # selected mapping at application time so a parent artifact cannot silently
    # change the conflict semantics.
    coordinate_owner: dict[int, int] = {}
    for group in groups:
        for coordinate in group["coordinates"]:
            previous = coordinate_owner.setdefault(int(coordinate), int(group["group_index"]))
            require(previous == int(group["group_index"]), f"GC1 coordinate conflict in state {task}: {coordinate}")
    ordered_groups = sorted(groups, key=lambda group: (-int(group["baseline_p"]["total_ulp_distance"]), -int(group["baseline_p"]["mismatch_count"]), len(group["palette"]), -len(group["physical_support_rows"]), int(group["group_index"])))
    beam = [evaluate(state, tuple(int(value) for value in state.baseline_weight_bits), tuple(), 0, pf5_contract, contract)]
    trace = []
    exact_evaluations = 1
    best_valid = beam[0] if beam[0]["final_pass"] else None
    for round_index, group in enumerate(ordered_groups, start=1):
        expanded = []
        for parent in beam:
            for candidate in group["palette"]:
                bits = list(parent["weight_bits"])
                for coordinate, choice, committed_bits in candidate["committed_f32_mapping"]:
                    old = bits[coordinate]
                    if old != int(state.baseline_weight_bits[coordinate]) and old != committed_bits:
                        raise RuntimeError(f"GC1 same-coordinate conflicting committed bytes: {task} {coordinate}")
                    bits[coordinate] = committed_bits
                selected = parent["selected"] + ((int(group["group_index"]), str(candidate["candidate_identity"])),)
                active_groups = parent["active_groups"] + int(candidate["roles"] != ["ZERO"])
                item = evaluate(state, tuple(bits), selected, active_groups, pf5_contract, contract)
                exact_evaluations += 1
                if item["guard_pass"] or candidate["roles"] == ["ZERO"]:
                    expanded.append(item)
                if item["final_pass"] and (best_valid is None or rank_state(item) < rank_state(best_valid)):
                    best_valid = item
        require(expanded, f"GC1 beam became empty: {task} round {round_index}")
        beam = select_beam(expanded, contract)
        current_best = min(beam, key=rank_state)
        trace.append({"round": round_index, "group_index": int(group["group_index"]), "expanded": len(expanded), "beam": len(beam), "best_mismatch": int(current_best["score"]["mismatch_count"]), "best_ulp": int(current_best["score"]["total_ulp_distance"]), "best_valid_mismatch": None if best_valid is None else int(best_valid["score"]["mismatch_count"])})
    best_search = min(beam, key=rank_state)
    best_search = complete_item(best_search, ordered_groups)
    completed_best_valid = None if best_valid is None else complete_item(best_valid, ordered_groups)
    result_item = completed_best_valid if completed_best_valid is not None else best_search
    return {
        "endpoint": task[0], "set_index": task[1], "group_count": len(groups), "group_order": [int(group["group_index"]) for group in ordered_groups], "exact_evaluations": exact_evaluations,
        "best_search": summarize(best_search), "best_final_geometry_valid": completed_best_valid is not None, "best_valid": None if completed_best_valid is None else summarize(completed_best_valid), "trace": trace,
        "status": "EXACT_GLOBAL_TARGET_REACHED" if result_item["score"]["mismatch_count"] == 0 and result_item["final_pass"] else "PARTIAL_GLOBAL_FEASIBILITY",
    }


def complete_item(item: dict[str, Any], ordered_groups: list[dict[str, Any]]) -> dict[str, Any]:
    selected = list(item["selected"])
    seen = {int(group_index) for group_index, _ in selected}
    for group in ordered_groups:
        group_index = int(group["group_index"])
        if group_index in seen:
            continue
        zero = [candidate for candidate in group["palette"] if candidate["roles"] == ["ZERO"]]
        require(len(zero) == 1, "GC1 missing ZERO fill")
        selected.append((group_index, str(zero[0]["candidate_identity"])))
    require(len(selected) == len(ordered_groups), "GC1 incomplete global candidate mapping")
    active_groups = sum(1 for group_index, identity in selected if identity != zero_identity(ordered_groups, group_index))
    canonical: dict[int, int] = {}
    for group_index, identity in selected:
        group = next(group for group in ordered_groups if int(group["group_index"]) == int(group_index))
        candidate = next(candidate for candidate in group["palette"] if str(candidate["candidate_identity"]) == identity)
        for coordinate, choice in candidate["canonical_mapping"]:
            previous = canonical.setdefault(int(coordinate), int(choice))
            require(previous == int(choice), "GC1 completed mapping conflict")
    completed = dict(item)
    completed["selected"] = tuple(selected)
    completed["active_groups"] = active_groups
    completed["canonical_mapping"] = tuple(sorted(canonical.items()))
    return completed


def zero_identity(ordered_groups: list[dict[str, Any]], group_index: int) -> str:
    for group in ordered_groups:
        if int(group["group_index"]) == int(group_index):
            zero = [candidate for candidate in group["palette"] if candidate["roles"] == ["ZERO"]]
            require(len(zero) == 1, "GC1 missing ZERO identity")
            return str(zero[0]["candidate_identity"])
    raise RuntimeError(f"GC1 unknown group for ZERO identity: {group_index}")


def summarize(item: dict[str, Any]) -> dict[str, Any]:
    selected = [{"group_index": int(group_index), "candidate_identity": identity} for group_index, identity in item["selected"]]
    mapping = []
    for group_index, identity in item["selected"]:
        mapping.append([int(group_index), identity])
    return {"score": item["score"], "geometry": item["geometry"], "debt": list(item["debt"]), "final_geometry_pass": bool(item["final_pass"]), "intermediate_guard_pass": bool(item["guard_pass"]), "active_group_count": int(item["active_groups"]), "selected_candidates": selected, "selected_candidate_identity_map": mapping, "canonical_mapping": [[int(coordinate), int(choice)] for coordinate, choice in item["canonical_mapping"]], "weight_state_sha256": bits_hash(item["weight_bits"]), "readout_sha256": bits_hash(item["readout_bits"]), "global_mismatch_count": int(item["score"]["mismatch_count"])}


def worker(task: tuple[str, int]) -> dict[str, Any]:
    if "palettes" not in _CACHE:
        _CACHE["palettes"] = compact_palettes()
        _CACHE["contract"] = load_json(ROOT / "CONTRACT.json")
        _CACHE["pf5"] = load_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    _, states, raw_groups = RH1.load_runtime({task})
    state = states[task]
    groups = _CACHE["palettes"].get(task, [])
    require(groups, f"GC1 missing palette state: {task}")
    for group in groups:
        key = (task[0], task[1], int(group["group_index"]))
        require(key in raw_groups, f"GC1 missing runtime raw group: {key}")
        validate_group_topology(state, group, raw_groups[key])
        for candidate in group["palette"]:
            validate_candidate(state, group, candidate)
    return assemble_state(task, groups, state, _CACHE["pf5"], _CACHE["contract"])


def run() -> None:
    contract = load_seal()
    parents = verify_parents(contract)
    palettes = compact_palettes()
    library_counts = validate_palette_library(None, palettes, contract)
    par2_execution = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/execution.json")
    par2_status = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/derived/STATUS.json")
    require(par2_execution["protocol"] == "Q10-GC0-GP1-PAR2" and par2_status["status"] == "PAR2_ENGINEERING_PALETTE_COMPLETE", "GC1 PAR2 parent identity/status drift")
    require(par2_execution["gate"]["all_groups_completed"] and par2_execution["gate"]["palette_stream_complete"] and par2_execution["gate"]["authority_complete"] and par2_execution["gate"]["raw_support_complete"], "GC1 PAR2 parent gate not qualified")
    require(not par2_execution["gate"]["gc1_authorized"] and not par2_execution["gate"]["global_assembly_executed"], "GC1 PAR2 parent firewall drift")
    require(par2_execution["counts"]["raw_group_count"] == library_counts["raw_group_count"], "GC1 PAR2 group count drift")
    require(par2_execution["counts"]["palette_count"] == library_counts["palette_count"], "GC1 PAR2 palette count drift")
    pf0 = load_json(REPO / "experiments/drosophila-heresy/q10-gc1-pf0-v1/qualification/execution.json")
    require(pf0["gate"]["raw_support_complete"] and pf0["gate"]["coordinate_conflicts_zero"], "GC1 PF0 gate not qualified")
    require(pf0["gate"]["preflight_complete"] and pf0["gate"]["palette_cardinality_complete"] and pf0["gate"]["canonical_candidate_identities_unique_within_group"], "GC1 PF0 parent gate not qualified")
    require(len(pf0["support_gates"]) == int(contract["sample"]["expected_endpoint_set_count"]), "GC1 PF0 endpoint/set count drift")
    require(all(int(item["uncovered_mismatch_count"]) == 0 for item in pf0["support_gates"]), "GC1 PF0 support gap")
    tasks = sorted((str(item["endpoint"]), int(item["set_index"])) for item in pf0["support_gates"])
    results = []
    _CACHE["palettes"] = palettes
    _CACHE["contract"] = contract
    _CACHE["pf5"] = load_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    with concurrent.futures.ProcessPoolExecutor(max_workers=int(contract["assembly"]["worker_count"])) as pool:
        for result in pool.map(worker, tasks, chunksize=1):
            results.append(result)
            print(json.dumps({"completed_endpoint_set": [result["endpoint"], result["set_index"]], "status": result["status"], "mismatch": result["best_search"]["global_mismatch_count"]}, sort_keys=True), flush=True)
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "firewall": contract["firewall"], "runner_sha256": digest(Path(__file__)), "plan_sha256": digest(ROOT / "PLAN.md"), "contract_sha256": digest(ROOT / "CONTRACT.json"), "verified_parent_bindings": parents, "library_counts": library_counts, "domains": {"whole_endpoint_primary": "G", "declared_group_rows": "D", "physical_support_rows": "P"}, "counts": {"endpoint_set_count": len(results), "exact_global_target_count": sum(item["status"] == "EXACT_GLOBAL_TARGET_REACHED" for item in results), "partial_global_count": sum(item["status"] == "PARTIAL_GLOBAL_FEASIBILITY" for item in results), "exact_evaluations": sum(int(item["exact_evaluations"]) for item in results)}, "endpoint_set_results": results, "gate": {"all_endpoint_sets_completed": len(results) == int(contract["sample"]["expected_endpoint_set_count"]), "global_assembly_executed": True, "scientific_promotion": False, "behavioral_probe": False, "gc1_authorized": False}}
    write_json(EXECUTION, execution)
    summary = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "GC1_ENGINEERING_ASSEMBLY_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "library_counts": library_counts, "gate": execution["gate"], "interpretation": "Global palette assembly was executed with exact sequential-f32 replay, validated baseline-relative candidate bytes, complete ZERO-filled endpoint mappings, and a fixed group beam. Results are constructor evidence only; no behavior or science was run."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(["# Q10-GC1-PAR2 result", "", f"Endpoint/set states completed: **{len(results)}**.", f"Exact global targets: **{execution['counts']['exact_global_target_count']}**.", f"Partial global assemblies: **{execution['counts']['partial_global_count']}**.", f"Exact global evaluations: **{execution['counts']['exact_evaluations']}**.", "", "This is engineering-only global assembly with validated candidates and complete endpoint mappings. No behavioral or scientific promotion occurred.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "gc1_authorized": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
