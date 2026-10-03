"""Q10-GC0-GP1-PAR1 parallel endpoint/set palette runner."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
GP1_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-gc0-gp1-v1/scripts"
F2_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(GP1_SCRIPTS))
sys.path.insert(0, str(F2_SCRIPTS))
sys.path.insert(0, str(GC0_SCRIPTS))
import run_gp1 as BASE  # noqa: E402
import run_rh1 as RH1  # noqa: E402
import run_gc0 as GC0  # noqa: E402

PROTOCOL = "Q10-GC0-GP1-PAR1"
IDENTITY = "q10-gc0-gp1-par1-v1"
PALETTES = ROOT / "qualification" / "palettes.jsonl"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"
_CACHE: dict[str, Any] = {}


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
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "PAR1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "PAR1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "PAR1 PLAN drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "PAR1 PREEXECUTION PLAN drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "PAR1 PREEXECUTION CONTRACT drift")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    result = {}
    for item in contract["parent_bindings"]:
        path = REPO / Path(str(item["path"]))
        require(path.is_file(), f"PAR1 missing parent: {item['label']}")
        actual = digest(path)
        require(actual == str(item["sha256"]).upper(), f"PAR1 parent drift: {item['label']}")
        result[str(item["label"])] = actual
    return result


def worker(task: tuple[str, int]) -> dict[str, Any]:
    if "features" not in _CACHE:
        ra1 = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1/qualification/execution.json")
        allowed = {
            (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(evidence["coordinate"]))
            for item in ra1["raw_group_records"]
            for evidence in item["authority_evidence"]
        }
        _CACHE["features"] = BASE.merged_features(allowed)
        _CACHE["pf5"] = BASE.load_pf5_contract()
        _CACHE["contract"] = load_json(ROOT / "CONTRACT.json")
    _, states, groups = RH1.load_runtime({task})
    state = states[task]
    results = []
    support = set()
    for key in sorted(groups):
        group = groups[key]
        frozen = BASE.frozen_group(group)
        result = GC0.run_group(state, group, frozen, _CACHE["features"], _CACHE["pf5"], _CACHE["contract"])
        require(result["identity"] == [key[0], key[1], key[2]], f"PAR1 group identity drift: {key}")
        results.append(result)
        support.update(int(row) for row in result["physical_support_rows"])
    mismatch = {row for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits)) if actual != target}
    return {"endpoint": task[0], "set_index": task[1], "groups": results, "mismatch_rows": sorted(mismatch), "support_rows": sorted(support)}


def run() -> None:
    contract = load_seal()
    parents = verify_parents(contract)
    ra1 = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1/qualification/execution.json")
    tasks = sorted(tuple(value) for value in ra1["sample"]["endpoint_keys"])
    require(len(tasks) == 14, "PAR1 task count drift")
    PALETTES.parent.mkdir(parents=True, exist_ok=True)
    if PALETTES.exists():
        PALETTES.unlink()
    group_count = palette_count = shortfall_count = exact_declared = replays = 0
    group_status = Counter()
    state_results = []
    with PALETTES.open("w", encoding="utf-8", newline="\n") as handle:
        with concurrent.futures.ProcessPoolExecutor(max_workers=int(contract["execution"]["worker_count"])) as pool:
            for state_result in pool.map(worker, tasks):
                state_results.append(state_result)
                for result in state_result["groups"]:
                    handle.write(json.dumps(result, separators=(",", ":")) + "\n")
                    group_count += 1
                    palette_count += len(result["palette"])
                    shortfall_count += int(result["palette_counts"]["nonzero_shortfall"] > 0)
                    exact_declared += sum(int(item["scores"]["D"]["mismatch_count"] == 0) for item in result["palette"])
                    replays += int(result["candidate_generation"]["exact_nonzero_replays"])
                    group_status[result["status"]] += 1
                handle.flush()
                print(json.dumps({"completed_endpoint_set": [state_result["endpoint"], state_result["set_index"]], "groups": group_count, "replays": replays}, sort_keys=True), flush=True)
    per_state = []
    for item in sorted(state_results, key=lambda value: (value["endpoint"], value["set_index"])):
        mismatch = set(item["mismatch_rows"])
        support = set(item["support_rows"])
        per_state.append({"endpoint": item["endpoint"], "set_index": item["set_index"], "baseline_mismatch_count": len(mismatch), "palette_support_count": len(support), "uncovered_mismatch_count": len(mismatch - support), "uncovered_mismatch_rows": sorted(mismatch - support)})
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "firewall": contract["firewall"], "verified_parent_bindings": parents, "counts": {"endpoint_set_count": len(tasks), "raw_group_count": group_count, "palette_count": palette_count, "exact_nonzero_replays": replays, "groups_with_palette_shortfall": shortfall_count, "candidates_with_exact_declared_rows": exact_declared}, "group_status_counts": dict(group_status), "endpoint_set_results": per_state, "gate": {"all_groups_completed": group_count == 801, "authority_complete": True, "raw_support_complete": all(item["uncovered_mismatch_count"] == 0 for item in per_state), "palette_stream_complete": group_count == 801, "global_assembly_executed": False, "gc1_authorized": False}, "palette_sha256": digest(PALETTES)}
    write_json(EXECUTION, execution)
    summary = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PAR1_ENGINEERING_PALETTE_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "group_status_counts": execution["group_status_counts"], "gate": execution["gate"], "interpretation": "The complete raw-group authority-aware palette was generated by deterministic endpoint/set workers. It does not perform global coalition assembly or scientific testing."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(["# Q10-GC0-GP1-PAR1 result", "", f"Completed raw groups: **{group_count}**.", f"Palette entries including ZERO: **{palette_count}**.", f"Exact nonzero replays: **{replays}**.", f"Raw support gate: **{execution['gate']['raw_support_complete']}**.", "", "Parallelism changed execution scheduling only; exact candidate semantics and candidate identity are inherited unchanged. No global assembly, behavior, or science was run.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "global_assembly_executed": False, "gc1_authorized": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT), "palette_sha256": digest(PALETTES)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
