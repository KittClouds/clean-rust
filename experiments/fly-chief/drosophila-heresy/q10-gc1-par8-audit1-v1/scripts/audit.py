"""Q10-GC1-PAR8-AUDIT1 independent receipt reconstruction."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
RH1_DIR = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0_DIR = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(RH1_DIR))
sys.path.insert(0, str(GC0_DIR))
import run_rh1 as RH1  # noqa: E402
import run_gc0 as GC0RUN  # noqa: E402

PROTOCOL = "Q10-GC1-PAR8-AUDIT1"
IDENTITY = "q10-gc1-par8-audit1-v1"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def bits_hash(values: tuple[int, ...]) -> str:
    payload = b"".join(int(value).to_bytes(4, "little", signed=False) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def parent_path(contract: dict[str, Any], label: str) -> Path:
    matches = [item for item in contract["parent_bindings"] if item["label"] == label]
    require(len(matches) == 1, f"AUDIT1 parent binding cardinality drift: {label}")
    return REPO / Path(str(matches[0]["path"]))


def verify_seal() -> dict[str, Any]:
    contract = read_json(ROOT / "CONTRACT.json")
    pre = read_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "AUDIT1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "AUDIT1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "AUDIT1 plan drift")
    require(contract["runner_sha256"] == digest(Path(__file__)) and contract["sealed_runner_sha256"] == digest(Path(__file__)), "AUDIT1 sealed runner drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "AUDIT1 PREEXECUTION plan drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "AUDIT1 PREEXECUTION contract drift")
    require(pre["runner_sha256"] == digest(Path(__file__)), "AUDIT1 PREEXECUTION runner drift")
    require(contract["firewall"]["write_root"] == str(ROOT.relative_to(REPO)).replace("\\", "/"), "AUDIT1 write-root drift")
    require(pre["parent_bindings_sealed"] and pre["status"] == "PREEXECUTION_SEALED_NO_EXECUTION" and not pre["execution_started"] and not pre["result_exposure"], "AUDIT1 firewall drift")
    for item in contract["parent_bindings"]:
        path = REPO / Path(str(item["path"]))
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"AUDIT1 parent drift: {item['label']}")
    return contract


def load_palettes(path: Path) -> dict[tuple[str, int], dict[int, dict[str, Any]]]:
    result: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        group = json.loads(line)
        task = (str(group["identity"][0]), int(group["identity"][1]))
        group_index = int(group["identity"][2])
        require(group_index not in result.setdefault(task, {}), "AUDIT1 duplicate palette group")
        result[task][group_index] = group
    return result


def candidate_for(group: dict[str, Any], identity: str) -> dict[str, Any]:
    matches = [item for item in group["palette"] if str(item["candidate_identity"]) == identity]
    require(len(matches) == 1, f"AUDIT1 candidate identity missing/duplicate: {identity}")
    return matches[0]


def reconstruct(task: tuple[str, int], receipt: dict[str, Any], state: Any, palette_groups: dict[int, dict[str, Any]], pf5: dict[str, Any]) -> dict[str, Any]:
    valid = receipt["best_valid"]
    require(valid is not None and valid["final_geometry_pass"] is True, f"AUDIT1 missing valid selected state: {task}")
    selected = valid["selected_candidates"]
    expected_group_ids = set(palette_groups)
    selected_group_ids = {int(item["group_index"]) for item in selected}
    require(selected_group_ids == expected_group_ids, f"AUDIT1 incomplete ZERO-filled group mapping: {task}")
    canonical: dict[int, int] = {}
    baseline = [int(value) for value in state.baseline_weight_bits]
    for selected_item in selected:
        group_index = int(selected_item["group_index"])
        candidate = candidate_for(palette_groups[group_index], str(selected_item["candidate_identity"]))
        group_coordinates = tuple(int(value) for value in palette_groups[group_index]["coordinates_canonical"])
        mapping = tuple((int(pair[0]), int(pair[1])) for pair in candidate["canonical_mapping"])
        require(tuple(pair[0] for pair in mapping) == group_coordinates, f"AUDIT1 group canonical coverage drift: {task} {group_index}")
        require(RH1.CQ.state_identity(dict(mapping)) == str(candidate["candidate_identity"]), f"AUDIT1 candidate identity drift: {task} {group_index}")
        committed_mapping = tuple((int(pair[0]), int(pair[1]), int(pair[2])) for pair in candidate["committed_f32_mapping"])
        require(tuple(pair[0] for pair in committed_mapping) == group_coordinates, f"AUDIT1 group committed coverage drift: {task} {group_index}")
        if candidate["roles"] == ["ZERO"]:
            require(all(choice == 0 for _, choice in mapping), f"AUDIT1 ZERO prefix drift: {task} {group_index}")
        for coordinate, choice in mapping:
            previous = canonical.setdefault(coordinate, choice)
            require(previous == choice, f"AUDIT1 same-coordinate prefix conflict: {task} {coordinate}")
        for coordinate, choice, committed_bits in committed_mapping:
            expected_bits = RH1.PF5.legal_prefix_bits(baseline[coordinate], int(choice))
            require(expected_bits is not None and int(expected_bits) == int(committed_bits), f"AUDIT1 committed byte drift: {task} {coordinate}")
            if int(choice) == 0:
                require(int(committed_bits) == baseline[coordinate], f"AUDIT1 ZERO byte drift: {task} {coordinate}")
    receipt_mapping = tuple((int(pair[0]), int(pair[1])) for pair in valid["canonical_mapping"])
    require(receipt_mapping == tuple(sorted(canonical.items())), f"AUDIT1 receipt canonical mapping drift: {task}")
    bits = list(baseline)
    for coordinate, choice in receipt_mapping:
        expected_bits = RH1.PF5.legal_prefix_bits(bits[coordinate], choice)
        require(expected_bits is not None, f"AUDIT1 illegal prefix: {task} {coordinate} {choice}")
        bits[coordinate] = int(expected_bits)
    weight_bits = tuple(bits)
    weights = tuple(RH1.PF5.from_bits(raw) for raw in weight_bits)
    readout_bits = tuple(int(value) for value in RH1.PF5.readout_bits(state.rows, weights))
    score = GC0RUN.score_rows(readout_bits, state.target_readout_bits, range(len(state.rows)))
    require(score == valid["score"], f"AUDIT1 score drift: {task}")
    geometry = RH1.PF5.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    require(geometry == valid["geometry"], f"AUDIT1 geometry drift: {task}")
    final_pass = RH1.PF5.final_geometry_pass(geometry, pf5)
    require(final_pass, f"AUDIT1 final geometry failure: {task}")
    require(bits_hash(weight_bits) == str(valid["weight_state_sha256"]).upper(), f"AUDIT1 weight hash drift: {task}")
    require(bits_hash(readout_bits) == str(valid["readout_sha256"]).upper(), f"AUDIT1 readout hash drift: {task}")
    stored_audit = receipt["independent_audit"]
    require(stored_audit["weight_state_sha256"] == bits_hash(weight_bits), f"AUDIT1 stored audit weight drift: {task}")
    require(stored_audit["readout_sha256"] == bits_hash(readout_bits), f"AUDIT1 stored audit readout drift: {task}")
    rejected_search = receipt["best_search"]["final_geometry_pass"] is False
    return {"endpoint": task[0], "set_index": task[1], "selected_group_count": len(selected), "mismatch_count": int(score["mismatch_count"]), "total_ulp_distance": int(score["total_ulp_distance"]), "final_geometry_pass": final_pass, "weight_state_sha256": bits_hash(weight_bits), "readout_sha256": bits_hash(readout_bits), "best_search_rejected_for_geometry": rejected_search}


def run() -> None:
    contract = verify_seal()
    par8_execution = read_json(parent_path(contract, "par8_execution"))
    par8_status = read_json(parent_path(contract, "par8_status"))
    require(par8_execution["protocol"] == "Q10-GC1-PAR8" and par8_execution["identity"] == "q10-gc1-par8-v1", "AUDIT1 PAR8 identity drift")
    require(par8_execution["gate"]["all_endpoint_sets_completed"] and par8_execution["gate"]["scientific_promotion"] is False and par8_execution["gate"]["behavioral_probe"] is False, "AUDIT1 PAR8 gate drift")
    require(par8_status["execution_sha256"] == digest(parent_path(contract, "par8_execution")), "AUDIT1 PAR8 execution hash drift")
    palettes = load_palettes(parent_path(contract, "par2_palettes"))
    tasks = {(str(item["endpoint"]), int(item["set_index"])) for item in par8_execution["endpoint_set_results"]}
    _, states, _ = RH1.load_runtime(tasks)
    pf5 = read_json(parent_path(contract, "pf5_contract"))
    audited = []
    for receipt in par8_execution["endpoint_set_results"]:
        task = (str(receipt["endpoint"]), int(receipt["set_index"]))
        audited.append(reconstruct(task, receipt, states[task], palettes[task], pf5))
    require(len(audited) == 14 and all(item["final_geometry_pass"] for item in audited), "AUDIT1 incomplete audit")
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "parent_par8_execution_sha256": digest(parent_path(contract, "par8_execution")), "counts": {"endpoint_set_count": len(audited), "reconstructed_valid_count": sum(item["final_geometry_pass"] for item in audited), "best_search_geometry_rejected_count": sum(item["best_search_rejected_for_geometry"] for item in audited)}, "endpoint_set_results": audited, "gate": {"receipt_semantics_complete": True, "independent_reconstruction_complete": True, "all_final_geometry_valid": True, "search_executed": False, "behavioral_probe": False, "scientific_promotion": False}}
    write_json(EXECUTION, execution)
    summary = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PAR8_RECEIPT_RECONSTRUCTION_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "gate": execution["gate"], "interpretation": "All PAR8 best_valid global mappings were independently reconstructed from the sealed palette and runtime. Lower-mismatch best_search states were retained only as rejected diagnostics when they failed final geometry. No new search or behavioral probe was run."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join([f"# {PROTOCOL} result", "", f"Reconstructed endpoint/set states: **{len(audited)}**.", f"Final-geometry-valid reconstructions: **{sum(item['final_geometry_pass'] for item in audited)}**.", f"Best-search states rejected for final geometry: **{execution['counts']['best_search_geometry_rejected_count']}**.", "", "Receipt-only engineering audit; no search, behavior, or scientific promotion occurred.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
