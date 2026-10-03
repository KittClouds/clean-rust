"""Q10-GC0-GP1 streaming full raw-group palette runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(F2_SCRIPTS))
sys.path.insert(0, str(GC0_SCRIPTS))
import run_rh1 as RH1  # noqa: E402
import run_gc0 as GC0  # noqa: E402

PROTOCOL = "Q10-GC0-GP1"
IDENTITY = "q10-gc0-gp1-v1"
PALETTES = ROOT / "qualification" / "palettes.jsonl"
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
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "GP1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "GP1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "GP1 PLAN drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "GP1 PREEXECUTION PLAN drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "GP1 PREEXECUTION CONTRACT drift")
    require(bool(pre["parent_bindings_sealed"]), "GP1 parent seal missing")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    result = {}
    for item in contract["parent_bindings"]:
        path = REPO / Path(str(item["path"]))
        require(path.is_file(), f"GP1 missing parent: {item['label']}")
        actual = digest(path)
        require(actual == str(item["sha256"]).upper(), f"GP1 parent drift: {item['label']}")
        result[str(item["label"])] = actual
    return result


def merged_features(allowed: set[tuple[str, int, int, int]]) -> dict[tuple[str, int, int, int], dict[str, Any]]:
    paths = [
        REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl",
        REPO / "experiments/drosophila-heresy/q10-gc0-ac3-v1/qualification/expanded_features.jsonl",
    ]
    result = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            key = (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(item["coordinate"]))
            if key not in allowed:
                continue
            require(key not in result, f"GP1 duplicate authority feature: {key}")
            require(bool(item.get("complete")), f"GP1 incomplete authority feature: {key}")
            result[key] = item
    require(set(result) == allowed, f"GP1 authority context coverage drift: {len(allowed - set(result))}")
    return result


def frozen_group(group: Any) -> dict[str, Any]:
    return {
        "identity": [str(group.key[0]), int(group.key[1]), int(group.group_index)],
        "rows": [int(value) for value in group.rows],
        "coordinates": [int(value) for value in group.coordinates],
        "domains": [[int(choice) for choice in domain] for domain in group.domains],
    }


def load_pf5_contract() -> dict[str, Any]:
    return load_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")


def run() -> None:
    contract = load_seal()
    parents = verify_parents(contract)
    ra1 = load_json(REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1/qualification/execution.json")
    allowed = {
        (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(evidence["coordinate"]))
        for item in ra1["raw_group_records"]
        for evidence in item["authority_evidence"]
    }
    features = merged_features(allowed)
    keys = {tuple(value) for value in ra1["sample"]["endpoint_keys"]}
    _, states, groups = RH1.load_runtime(keys)
    require(len(states) == 14 and len(groups) == 801, "GP1 runtime sample cardinality drift")
    require(len(features) == 27075, "GP1 authority feature cardinality drift")
    pf5_contract = load_pf5_contract()
    PALETTES.parent.mkdir(parents=True, exist_ok=True)
    if PALETTES.exists():
        PALETTES.unlink()
    group_count = 0
    palette_count = 0
    shortfall_count = 0
    exact_declared_count = 0
    replay_count = 0
    support_by_state: dict[tuple[str, int], set[int]] = defaultdict(set)
    group_status = Counter()
    with PALETTES.open("w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(groups):
            group = groups[key]
            frozen = frozen_group(group)
            state = states[(key[0], key[1])]
            result = GC0.run_group(state, group, frozen, features, pf5_contract, contract)
            require(result["identity"] == [key[0], key[1], key[2]], f"GP1 group identity drift: {key}")
            require(result["palette"][0]["roles"] == ["ZERO"], f"GP1 zero candidate drift: {key}")
            handle.write(json.dumps(result, separators=(",", ":")) + "\n")
            handle.flush()
            group_count += 1
            palette_count += len(result["palette"])
            shortfall_count += int(result["palette_counts"]["nonzero_shortfall"] > 0)
            exact_declared_count += sum(int(item["scores"]["D"]["mismatch_count"] == 0) for item in result["palette"])
            replay_count += int(result["candidate_generation"]["exact_nonzero_replays"])
            group_status[result["status"]] += 1
            support_by_state[(key[0], key[1])].update(int(row) for row in result["physical_support_rows"])
            if group_count % 10 == 0 or group_count == len(groups):
                print(json.dumps({"progress_groups": group_count, "replays": replay_count}, sort_keys=True), flush=True)
    per_state = []
    for key in sorted(states):
        state = states[key]
        mismatch = {row for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits)) if actual != target}
        support = support_by_state[key]
        per_state.append({"endpoint": key[0], "set_index": key[1], "baseline_mismatch_count": len(mismatch), "palette_support_count": len(support), "uncovered_mismatch_count": len(mismatch - support), "uncovered_mismatch_rows": sorted(mismatch - support)})
    execution = {
        "protocol": PROTOCOL, "identity": IDENTITY, "firewall": contract["firewall"], "verified_parent_bindings": parents,
        "counts": {"endpoint_set_count": len(states), "raw_group_count": group_count, "palette_count": palette_count, "exact_nonzero_replays": replay_count, "groups_with_palette_shortfall": shortfall_count, "candidates_with_exact_declared_rows": exact_declared_count},
        "group_status_counts": dict(group_status), "endpoint_set_results": per_state,
        "gate": {"all_groups_completed": group_count == 801, "authority_complete": True, "raw_support_complete": all(item["uncovered_mismatch_count"] == 0 for item in per_state), "palette_stream_complete": True, "global_assembly_executed": False, "gc1_authorized": False},
        "palette_sha256": digest(PALETTES),
    }
    write_json(EXECUTION, execution)
    summary = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "GP1_ENGINEERING_PALETTE_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "group_status_counts": execution["group_status_counts"], "gate": execution["gate"], "interpretation": "The complete raw-group authority-aware palette was generated with exact sequential-f32 replay. This is a local palette artifact only; no global assembly or behavior was run."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(["# Q10-GC0-GP1 result", "", f"Completed raw groups: **{group_count}**.", f"Palette entries including ZERO: **{palette_count}**.", f"Exact nonzero replays: **{replay_count}**.", f"Raw support gate: **{execution['gate']['raw_support_complete']}**.", "", "This qualifies a local candidate palette only. It does not run global coalition assembly, GC1, behavior, or science.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "global_assembly_executed": False, "gc1_authorized": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT), "palette_sha256": digest(PALETTES)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
