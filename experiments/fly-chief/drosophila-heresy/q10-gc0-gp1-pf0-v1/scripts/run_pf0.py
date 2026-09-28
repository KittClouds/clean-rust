"""Q10-GC0-GP1-PF0 full-palette workload preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2 = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
sys.path.insert(0, str(F2))
import run_rh1 as RH1  # noqa: E402

PROTOCOL = "Q10-GC0-GP1-PF0"
IDENTITY = "q10-gc0-gp1-pf0-v1"
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
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "PF0 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "PF0 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "PF0 PLAN drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "PF0 PREEXECUTION PLAN drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "PF0 PREEXECUTION CONTRACT drift")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    result = {}
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file(), f"PF0 missing parent: {item['label']}")
        actual = digest(path)
        require(actual == str(item["sha256"]).upper(), f"PF0 parent drift: {item['label']}")
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
            require(key not in result, f"PF0 duplicate merged feature: {key}")
            require(bool(item.get("complete")), f"PF0 incomplete feature: {key}")
            result[key] = item
    return result


def group_stratum(size: int) -> str:
    if size == 1:
        return "raw_size_1"
    if size <= 3:
        return "raw_size_2_3"
    if size <= 7:
        return "raw_size_4_7"
    if size <= 16:
        return "raw_size_8_16"
    if size <= 31:
        return "rh1_secondary_size_17_31"
    return "rh1_primary_size_32_plus"


def authority_rank(group: Any, features: dict[tuple[str, int, int, int], dict[str, Any]]) -> list[int]:
    key = (str(group.key[0]), int(group.key[1]), int(group.group_index))
    records = []
    for coordinate in group.coordinates:
        feature = features[(key[0], key[1], key[2], int(coordinate))]
        records.append(feature)
    records.sort(key=lambda item: (
        -int(item["helpful_row_count"]),
        -int(item["helpful_ulp_burden"]),
        float(item["first_helpful_scale_median"]) if item["first_helpful_scale_median"] is not None else float("inf"),
        -int(item["declared_row_count"]),
        int(item["coordinate"]),
    ))
    return [int(item["coordinate"]) for item in records]


def exact_eval(state: Any, group: Any, prefix: tuple[int, ...]) -> tuple[int, ...]:
    weight_bits = RH1.weight_bits_for(state, group, prefix)
    weights = tuple(RH1.PF5.from_bits(raw) for raw in weight_bits)
    return tuple(int(value) for value in RH1.PF5.readout_bits(state.rows, weights))


def select_benchmark_groups(groups: dict[tuple[str, int, int], Any], count: int) -> list[tuple[str, int, int]]:
    ordered = sorted(groups, key=lambda key: (len(groups[key].coordinates), key))
    selected = []
    strata_seen: set[str] = set()
    for key in ordered:
        label = group_stratum(len(groups[key].coordinates))
        if label not in strata_seen:
            selected.append(key)
            strata_seen.add(label)
    for key in ordered:
        if len(selected) >= count:
            break
        if key not in selected:
            selected.append(key)
    return selected[:count]


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
    require(len(states) == 14 and len(groups) == 801, "PF0 runtime sample cardinality drift")
    require(len(features) == int(contract["sample"]["expected_raw_coordinate_context_count"]), "PF0 merged authority coverage drift")
    sizes = Counter(len(group.coordinates) for group in groups.values())
    horizons = Counter(min(32, len(group.coordinates)) for group in groups.values())
    max_replays = len(groups) * int(contract["candidate_generation"]["max_unique_replays_per_group"])
    benchmark_keys = select_benchmark_groups(groups, int(contract["candidate_generation"]["benchmark_group_count"]))
    benchmark = []
    for key in benchmark_keys:
        group = groups[key]
        state = states[(key[0], key[1])]
        ranking = authority_rank(group, features)
        prefix = [0] * len(group.coordinates)
        coordinate = ranking[0]
        index = list(group.coordinates).index(coordinate)
        prefix[index] = -1
        start = time.perf_counter_ns()
        zero_bits = exact_eval(state, group, tuple(0 for _ in group.coordinates))
        nonzero_bits = exact_eval(state, group, tuple(prefix))
        elapsed = time.perf_counter_ns() - start
        require(len(zero_bits) == len(state.rows) and len(nonzero_bits) == len(state.rows), f"PF0 readout cardinality drift: {key}")
        benchmark.append({
            "endpoint": key[0], "set_index": key[1], "group_index": key[2],
            "group_size": len(group.coordinates), "stratum": group_stratum(len(group.coordinates)),
            "horizon": min(32, len(group.coordinates)), "timed_exact_evaluations": 2,
            "elapsed_ns": elapsed, "readout_row_count": len(state.rows),
            "nonzero_coordinate": coordinate,
        })
    execution = {
        "protocol": PROTOCOL, "identity": IDENTITY, "firewall": contract["firewall"],
        "verified_parent_bindings": parents,
        "counts": {"endpoint_set_count": len(states), "raw_group_count": len(groups), "merged_authority_context_count": len(features), "max_unique_replays": max_replays},
        "group_size_distribution": dict(sorted(sizes.items())),
        "horizon_distribution": dict(sorted(horizons.items())),
        "benchmark_selection": [list(key) for key in benchmark_keys],
        "benchmark_results": benchmark,
        "gate": {"authority_complete": True, "raw_group_complete": True, "preflight_complete": True, "candidate_generation_executed": False, "gc1_authorized": False},
    }
    write_json(EXECUTION, execution)
    summary = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PF0_ENGINEERING_PREFLIGHT_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": execution["counts"], "group_size_distribution": execution["group_size_distribution"], "horizon_distribution": execution["horizon_distribution"], "benchmark_results": benchmark, "gate": execution["gate"], "interpretation": "The full raw-group authority table is complete. The next palette run has a sealed replay ceiling and a real sequential-f32 cost sample; no palette or GC1 candidate was generated."}
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(["# Q10-GC0-GP1-PF0 result", "", f"Raw groups: **{len(groups)}**.", f"Merged authority contexts: **{len(features)}**.", f"Max exact candidate replay ceiling: **{max_replays}**.", "", "This preflight executed only two exact readouts for each of twelve fixed benchmark groups. It did not generate candidate palettes or authorize GC1.", ""]), encoding="utf-8", newline="\n")
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "gc1_authorized": False, "candidate_generation_executed": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
