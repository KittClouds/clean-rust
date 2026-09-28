"""Q10-GC0-UB1 raw-group physical-support audit.

This runner imports the sealed RH1-F2 loader, which imports the sealed PF5
runtime. It performs no candidate replay and writes only below q10-gc0-ub1-v1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1"
F2_SCRIPTS = F2_ROOT / "scripts"
sys.path.insert(0, str(F2_SCRIPTS))
import run_rh1 as RH1  # noqa: E402


PROTOCOL = "Q10-GC0-UB1"
IDENTITY = "q10-gc0-ub1-v1"
GC0_ROOT = REPO / "experiments/drosophila-heresy/q10-gc0-v1"
OUTPUT = ROOT / "qualification" / "execution.json"
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


def bits_hash(values: Iterable[int]) -> str:
    payload = b"".join(struct.pack("<I", int(value) & 0xFFFF_FFFF) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def endpoint_key(value: Iterable[Any]) -> tuple[str, int]:
    endpoint, set_index = tuple(value)
    return str(endpoint), int(set_index)


def key_list(key: tuple[str, int]) -> list[Any]:
    return [key[0], key[1]]


def identity_label(key: tuple[str, int]) -> str:
    return f"{key[0]}|set{key[1]}"


def load_local_seal() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = load_json(ROOT / "CONTRACT.json")
    preexecution = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "UB1 contract identity drift")
    require(preexecution["protocol"] == PROTOCOL and preexecution["identity"] == IDENTITY, "UB1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "UB1 PLAN hash drift")
    require(preexecution["plan_sha256"] == digest(ROOT / "PLAN.md"), "UB1 PREEXECUTION PLAN drift")
    require(preexecution["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "UB1 CONTRACT hash drift")
    require(contract["plan_sha256"] == preexecution["plan_sha256"], "UB1 local plan binding drift")
    return contract, preexecution


def verify_gc0_nested_bindings() -> dict[str, str]:
    gc0_contract_path = GC0_ROOT / "CONTRACT.json"
    gc0_preexecution_path = GC0_ROOT / "PREEXECUTION.json"
    gc0_contract = load_json(gc0_contract_path)
    gc0_preexecution = load_json(gc0_preexecution_path)
    require(gc0_contract["protocol"] == "Q10-GC0" and gc0_contract["identity"] == "q10-gc0-v1", "GC0 parent identity drift")
    expected = {str(item["label"]): str(item["sha256"]).upper() for item in gc0_contract["parent_bindings"]}
    sealed = {str(label): str(value).upper() for label, value in gc0_preexecution["sealed_parent_sha256"].items()}
    require(expected == sealed, "GC0 nested parent seal drift")
    verified: dict[str, str] = {}
    for binding in gc0_contract["parent_bindings"]:
        relative = Path(str(binding["path"]))
        require(not relative.is_absolute(), f"GC0 nested parent path is absolute: {relative}")
        path = REPO / relative
        actual = digest(path)
        expected_hash = str(binding["sha256"]).upper()
        require(actual == expected_hash, f"GC0 nested parent drift: {binding['label']}")
        verified[str(binding["label"])] = actual
    return verified


def verify_parent_bindings(contract: dict[str, Any], preexecution: dict[str, Any]) -> dict[str, str]:
    expected = {str(item["label"]): str(item["sha256"]).upper() for item in contract["parent_bindings"]}
    sealed = {str(label): str(value).upper() for label, value in preexecution["sealed_parent_sha256"].items()}
    require(expected == sealed, "UB1 parent binding labels or hashes drifted")
    verified: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        relative = Path(str(binding["path"]))
        require(not relative.is_absolute(), f"UB1 parent path is absolute: {relative}")
        path = REPO / relative
        require(path.is_file(), f"UB1 parent is missing: {binding['label']}")
        actual = digest(path)
        require(actual == expected[str(binding["label"])], f"UB1 parent drift: {binding['label']}")
        verified[str(binding["label"])] = actual
    verified.update({f"gc0_nested_{label}": value for label, value in verify_gc0_nested_bindings().items()})
    return verified


def verify_sample(contract: dict[str, Any]) -> list[tuple[str, int]]:
    sample = contract["sample"]
    gc0 = load_json(GC0_ROOT / "CONTRACT.json")
    expected_keys = [endpoint_key(value) for value in sample["endpoint_keys"]]
    gc0_keys = [endpoint_key(value) for value in gc0["sample"]["endpoint_keys"]]
    require(expected_keys == gc0_keys, "UB1 sample differs from sealed GC0 sample")
    require(len(expected_keys) == len(set(expected_keys)), "UB1 sample contains duplicate endpoint/set keys")
    require(len(expected_keys) == int(sample["expected_endpoint_set_count"]) == 14, "UB1 sample cardinality drift")
    require(len({key[0] for key in expected_keys}) == int(sample["expected_endpoint_count"]) == 4, "UB1 endpoint cardinality drift")
    require(sample["selection_is_sealed"] and sample["selection_is_not_post_outcome"], "UB1 selection firewall drift")
    return expected_keys


def support_for_coordinates(state: Any, coordinates: Iterable[int]) -> set[int]:
    support: set[int] = set()
    for coordinate_value in coordinates:
        coordinate = int(coordinate_value)
        require(0 <= coordinate < len(state.support_counts), f"support coordinate out of range: {coordinate}")
        for row_value, count_value in state.support_counts[coordinate]:
            row = int(row_value)
            count = int(count_value)
            require(0 <= row < len(state.rows), f"support row out of range: {row}")
            require(count >= 0, f"negative support count: {coordinate} {row}")
            if count:
                support.add(row)
    return support


def mismatch_records(state: Any, rows: Iterable[int]) -> list[dict[str, int]]:
    records = []
    for row_value in sorted({int(row) for row in rows}):
        records.append(
            {
                "row": row_value,
                "baseline_bits": int(state.baseline_readout_bits[row_value]),
                "target_bits": int(state.target_readout_bits[row_value]),
            }
        )
    return records


def coverage(mismatch: set[int], support: set[int]) -> dict[str, Any]:
    covered = mismatch & support
    uncovered = mismatch - support
    return {
        "physical_support_count": len(support),
        "physical_support_rows": sorted(support),
        "baseline_mismatch_count": len(mismatch),
        "covered_mismatch_count": len(covered),
        "uncovered_mismatch_count": len(uncovered),
        "coverage_fraction": (len(covered) / len(mismatch)) if mismatch else 1.0,
        "covered_mismatch_rows": sorted(covered),
        "uncovered_mismatch_rows": sorted(uncovered),
    }


def add_bit_identities(value: dict[str, Any], state: Any, mismatch: set[int]) -> None:
    baseline = tuple(int(item) for item in state.baseline_readout_bits)
    target = tuple(int(item) for item in state.target_readout_bits)
    value["baseline_readout_bits_sha256"] = bits_hash(baseline)
    value["target_readout_bits_sha256"] = bits_hash(target)
    value["mismatch_identity_sha256"] = json_hash(mismatch_records(state, mismatch))
    value["mismatch_rows"] = mismatch_records(state, mismatch)


def strata_for(contract: dict[str, Any], size: int) -> list[dict[str, Any]]:
    result = []
    for item in contract["group_size_strata"]:
        maximum = item["maximum"]
        if size >= int(item["minimum"]) and (maximum is None or size <= int(maximum)):
            result.append(item)
    require(len(result) == 1, f"raw group size has no unique stratum: {size}")
    return result


def raw_group_record(state: Any, group: Any) -> tuple[dict[str, Any], set[int]]:
    coordinates = tuple(int(value) for value in group.coordinates)
    rows = tuple(int(value) for value in group.rows)
    require(coordinates and len(coordinates) == len(set(coordinates)), f"raw group coordinate identity drift: {group.group_index}")
    require(len(rows) == len(set(rows)), f"raw group declared rows duplicated: {group.group_index}")
    physical = support_for_coordinates(state, coordinates)
    record = {
        "group_index": int(group.group_index),
        "group_size": len(coordinates),
        "declared_row_count": len(rows),
        "declared_rows": list(rows),
        "coordinate_ids": list(coordinates),
        "physical_support_count": len(physical),
        "physical_support_rows": sorted(physical),
        "helpful_row_count": len(tuple(group.helpful_rows)),
        "no_helpful_row_count": len(tuple(group.no_helpful_rows)),
    }
    return record, physical


def stratum_record(contract: dict[str, Any], state: Any, groups: list[Any], mismatch: set[int]) -> dict[str, Any]:
    size = len(groups[0].coordinates) if groups else 0
    del size
    strata = []
    for definition in contract["group_size_strata"]:
        minimum = int(definition["minimum"])
        maximum = definition["maximum"]
        selected = [
            group for group in groups
            if len(group.coordinates) >= minimum and (maximum is None or len(group.coordinates) <= int(maximum))
        ]
        support: set[int] = set()
        for group in selected:
            support.update(support_for_coordinates(state, group.coordinates))
        result = coverage(mismatch, support)
        result.update(
            {
                "label": str(definition["label"]),
                "minimum_group_size": minimum,
                "maximum_group_size": maximum,
                "rh1_eligible": bool(definition["rh1_eligible"]),
                "raw_group_count": len(selected),
                "group_size_distribution": dict(sorted(Counter(len(group.coordinates) for group in selected).items())),
            }
        )
        result["covered_mismatch_rows"] = mismatch_records(state, set(result["covered_mismatch_rows"]))
        result["uncovered_mismatch_rows"] = mismatch_records(state, set(result["uncovered_mismatch_rows"]))
        strata.append(result)
    return {str(item["label"]): item for item in strata}


def audit_state(contract: dict[str, Any], key: tuple[str, int], state: Any, groups: list[Any], frozen: list[dict[str, Any]]) -> dict[str, Any]:
    require(tuple(state.key) == key, f"state key drift: {key}")
    computed_baseline = tuple(RH1.PF5.readout_bits(state.rows, state.baseline_weights))
    loaded_baseline = tuple(int(value) for value in state.baseline_readout_bits)
    target = tuple(int(value) for value in state.target_readout_bits)
    require(computed_baseline == loaded_baseline, f"baseline sequential-f32 bits drift: {key}")
    require(len(loaded_baseline) == len(target) == len(state.rows), f"readout cardinality drift: {key}")
    mismatch = {row for row, (actual, expected) in enumerate(zip(loaded_baseline, target)) if actual != expected}
    require(all(0 <= value <= 0xFFFF_FFFF for value in loaded_baseline + target), f"readout bit range drift: {key}")
    require([int(group.group_index) for group in groups] == list(range(len(groups))), f"raw group index sequence drift: {key}")

    inventory = []
    raw_support: set[int] = set()
    for group in groups:
        record, support = raw_group_record(state, group)
        inventory.append(record)
        raw_support.update(support)

    raw_coverage = coverage(mismatch, raw_support)
    raw_coverage["covered_mismatch_rows"] = mismatch_records(state, set(raw_coverage["covered_mismatch_rows"]))
    raw_coverage["uncovered_mismatch_rows"] = mismatch_records(state, set(raw_coverage["uncovered_mismatch_rows"]))
    raw_coverage["upper_bound_classification"] = "COMPLETE_SUPPORT" if not mismatch - raw_support else "SUPPORT_INCOMPLETE"
    raw_coverage["support_identity_sha256"] = json_hash(sorted(raw_support))

    rh1_support: set[int] = set()
    for frozen_group in frozen:
        rh1_support.update(support_for_coordinates(state, frozen_group["coordinates"]))
    rh1_coverage = coverage(mismatch, rh1_support)
    rh1_coverage["covered_mismatch_rows"] = mismatch_records(state, set(rh1_coverage["covered_mismatch_rows"]))
    rh1_coverage["uncovered_mismatch_rows"] = mismatch_records(state, set(rh1_coverage["uncovered_mismatch_rows"]))
    rh1_coverage["support_identity_sha256"] = json_hash(sorted(rh1_support))

    mismatch_value = mismatch_records(state, mismatch)
    endpoint_result = {
        "endpoint": key[0],
        "set_index": key[1],
        "identity": identity_label(key),
        "row_count": len(state.rows),
        "coordinate_count": len(state.baseline_weight_bits),
        "raw_group_count": len(groups),
        "group_size_distribution": dict(sorted(Counter(len(group.coordinates) for group in groups).items())),
        "raw_group_inventory": inventory,
        "baseline_readout_verified": True,
        "baseline_readout_bits_sha256": bits_hash(loaded_baseline),
        "target_readout_bits_sha256": bits_hash(target),
        "mismatch_identity_sha256": json_hash(mismatch_value),
        "mismatch_rows": mismatch_value,
        "raw_group_upper_bound": raw_coverage,
        "coverage_by_group_size_stratum": stratum_record(contract, state, groups, mismatch),
        "rh1_55_group_support_comparison": {
            "projected_group_count": len(frozen),
            "group_size_distribution": dict(sorted(Counter(int(item["coordinates_total"]) for item in frozen).items())),
            **rh1_coverage,
        },
    }
    return endpoint_result


def render_result(execution: dict[str, Any]) -> str:
    gate = execution["raw_group_upper_bound"]
    lines = [
        "# Q10-GC0-UB1 result",
        "",
        "This sealed audit used the actual RH1-F2/PF5 runtime loader and `support_counts` for every raw group in the fixed Q10-GC0 sample.",
        "",
        f"Status: `{execution['status']}`.",
        f"Raw-group upper bound: `{gate['classification']}`; mismatch rows {gate['baseline_mismatch_count']}, covered {gate['covered_mismatch_count']}, uncovered {gate['uncovered_mismatch_count']}, coverage {gate['coverage_fraction']:.6f}.",
        f"Loaded states: {execution['counts']['endpoint_set_count']}; raw groups: {execution['counts']['raw_group_count']}; RH1 sample projection: {execution['counts']['rh1_sample_group_count']} of {execution['counts']['rh1_full_group_count']} groups.",
        "",
        "Per endpoint/set:",
        "",
        "| endpoint/set | raw groups | union support | mismatches | covered | uncovered | fraction | RH1 covered/fraction |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in execution["endpoint_set_results"]:
        raw = item["raw_group_upper_bound"]
        rh1 = item["rh1_55_group_support_comparison"]
        lines.append(
            f"| `{item['identity']}` | {item['raw_group_count']} | {raw['physical_support_count']} | {raw['baseline_mismatch_count']} | {raw['covered_mismatch_count']} | {raw['uncovered_mismatch_count']} | {raw['coverage_fraction']:.6f} | {rh1['covered_mismatch_count']}/{rh1['coverage_fraction']:.6f} |"
        )
    lines.extend(
        [
            "",
            "The raw-group result is a physical-support upper bound. It does not establish a candidate palette, behavioral effect, scientific finding, or GC1 authorization.",
            "",
            "Exact row and bit identities, group inventories, size-stratum coverage, and RH1 comparison rows are in `qualification/execution.json` and `qualification/derived/SUMMARY.json`.",
        ]
    )
    if gate["classification"] == "SUPPORT_INCOMPLETE":
        lines.extend(
            [
                "",
                "Because raw support remains incomplete, this is a constructor partition bottleneck diagnostic rather than a global infeasibility claim.",
            ]
        )
    return "\n".join(lines) + "\n"


def run_audit(mode: str) -> dict[str, Any]:
    contract, preexecution = load_local_seal()
    bindings = verify_parent_bindings(contract, preexecution)
    all_keys = verify_sample(contract)
    keys = all_keys if mode == "full" else all_keys[:1]
    key_set = set(keys)
    _, states, raw_groups = RH1.load_runtime(key_set)
    require(set(states) == key_set, "PF5 loader did not return exactly the sealed sample keys")
    groups_by_key: dict[tuple[str, int], list[Any]] = {key: [] for key in keys}
    for group in raw_groups.values():
        require(tuple(group.key) in key_set, f"PF5 returned group outside selected sample: {group.key}")
        groups_by_key[tuple(group.key)].append(group)
    for key in keys:
        groups_by_key[key].sort(key=lambda group: int(group.group_index))
        require(groups_by_key[key], f"PF5 returned no raw groups: {key}")

    primary, secondary = RH1.frozen_groups()
    all_frozen = primary + secondary
    require(len(all_frozen) == int(contract["sample"]["expected_full_rh1_group_count"]), "RH1 full group count drift")
    frozen_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {key: [] for key in keys}
    for frozen_group in all_frozen:
        key = (str(frozen_group["endpoint"]), int(frozen_group["set_index"]))
        if key in key_set:
            frozen_by_key[key].append(frozen_group)
            runtime_group = raw_groups.get((key[0], key[1], int(frozen_group["group_index"])))
            require(runtime_group is not None, f"RH1 frozen group missing from PF5 raw groups: {key} {frozen_group['group_index']}")
            require(tuple(runtime_group.rows) == tuple(frozen_group["rows"]), f"RH1 frozen row identity drift: {key} {frozen_group['group_index']}")
            require(set(runtime_group.coordinates) == set(frozen_group["coordinates"]), f"RH1 frozen coordinate identity drift: {key} {frozen_group['group_index']}")
    if mode == "full":
        require(sum(len(value) for value in frozen_by_key.values()) == int(contract["sample"]["expected_frozen_rh1_group_count"]), "RH1 sample projection count drift")

    endpoint_results = [audit_state(contract, key, states[key], groups_by_key[key], frozen_by_key[key]) for key in keys]
    global_mismatch: set[tuple[str, int, int]] = set()
    raw_covered: set[tuple[str, int, int]] = set()
    raw_uncovered: set[tuple[str, int, int]] = set()
    rh1_covered: set[tuple[str, int, int]] = set()
    raw_support: set[tuple[str, int, int]] = set()
    for item in endpoint_results:
        key = (item["endpoint"], int(item["set_index"]))
        mismatch = {(key[0], key[1], int(record["row"])) for record in item["mismatch_rows"]}
        covered = {(key[0], key[1], int(record["row"])) for record in item["raw_group_upper_bound"]["covered_mismatch_rows"]}
        uncovered = {(key[0], key[1], int(record["row"])) for record in item["raw_group_upper_bound"]["uncovered_mismatch_rows"]}
        global_mismatch.update(mismatch)
        raw_covered.update(covered)
        raw_uncovered.update(uncovered)
        rh1_covered.update((key[0], key[1], int(record["row"])) for record in item["rh1_55_group_support_comparison"]["covered_mismatch_rows"])
        raw_support.update((key[0], key[1], int(row)) for row in item["raw_group_upper_bound"]["physical_support_rows"])
        require(mismatch == covered | uncovered and not (covered & uncovered), f"UB1 endpoint coverage partition drift: {key}")

    raw_classification = "COMPLETE_SUPPORT" if not raw_uncovered else "SUPPORT_INCOMPLETE"
    constructor_diagnostic = (
        "NONE_RAW_SUPPORT_COMPLETE"
        if raw_classification == "COMPLETE_SUPPORT"
        else "CONSTRUCTOR_PARTITION_BOTTLENECK"
        if len(raw_uncovered) > len(global_mismatch) / 2
        else "SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY"
    )
    global_gate = {
        "classification": raw_classification,
        "baseline_mismatch_count": len(global_mismatch),
        "covered_mismatch_count": len(raw_covered),
        "uncovered_mismatch_count": len(raw_uncovered),
        "coverage_fraction": (len(raw_covered) / len(global_mismatch)) if global_mismatch else 1.0,
        "union_physical_support_count": len(raw_support),
        "uncovered_mismatch_identities": [list(value) for value in sorted(raw_uncovered)],
        "constructor_partition_diagnostic": constructor_diagnostic,
        "global_infeasibility_claim": False,
        "gc1_authorized": False,
    }
    status = f"UB1_ENGINEERING_COMPLETE_{raw_classification}"
    if mode == "smoke":
        status = f"UB1_SMOKE_COMPLETE_{raw_classification}"
    counts = {
        "endpoint_set_count": len(endpoint_results),
        "raw_group_count": sum(item["raw_group_count"] for item in endpoint_results),
        "rh1_sample_group_count": sum(item["rh1_55_group_support_comparison"]["projected_group_count"] for item in endpoint_results),
        "rh1_full_group_count": len(all_frozen),
        "baseline_mismatch_count": len(global_mismatch),
        "raw_covered_mismatch_count": len(raw_covered),
        "raw_uncovered_mismatch_count": len(raw_uncovered),
        "rh1_sample_covered_mismatch_count": len(rh1_covered),
    }
    execution = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": status,
        "run_scope": mode,
        "plan_sha256": digest(ROOT / "PLAN.md"),
        "contract_sha256": digest(ROOT / "CONTRACT.json"),
        "preexecution_sha256": digest(ROOT / "PREEXECUTION.json"),
        "parent_bindings_verified": bindings,
        "sample": {"endpoint_keys": [key_list(key) for key in keys], "full_sample_endpoint_keys": [key_list(key) for key in all_keys]},
        "counts": counts,
        "raw_group_upper_bound": global_gate,
        "endpoint_set_results": endpoint_results,
        "firewall": {
            "engineering_only": True,
            "scientific_promotion": False,
            "behavioral_probe": False,
            "gc1_authorized": False,
            "candidate_palette_generation": False,
            "parent_writes": False,
        },
    }
    require(execution["firewall"]["scientific_promotion"] is False, "scientific promotion firewall drift")
    require(execution["firewall"]["behavioral_probe"] is False, "behavioral probe firewall drift")
    require(execution["firewall"]["gc1_authorized"] is False, "GC1 authorization firewall drift")
    if mode == "full":
        write_json(OUTPUT, execution)
        execution_hash = digest(OUTPUT)
        summary = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": status,
            "plan_sha256": execution["plan_sha256"],
            "contract_sha256": execution["contract_sha256"],
            "execution_sha256": execution_hash,
            "counts": counts,
            "raw_group_upper_bound": global_gate,
            "endpoint_set_results": endpoint_results,
            "firewall": execution["firewall"],
        }
        write_json(SUMMARY, summary)
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text(render_result(execution), encoding="utf-8", newline="\n")
        status_receipt = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": status,
            "plan_sha256": execution["plan_sha256"],
            "contract_sha256": execution["contract_sha256"],
            "preexecution_sha256": execution["preexecution_sha256"],
            "execution_sha256": execution_hash,
            "summary_sha256": digest(SUMMARY),
            "result_sha256": digest(RESULT),
            "raw_group_upper_bound": global_gate,
            "scientific_promotion": False,
            "behavioral_probe": False,
            "gc1_authorized": False,
        }
        write_json(STATUS, status_receipt)
    else:
        smoke_path = ROOT / "qualification" / "smoke" / "execution.json"
        write_json(smoke_path, execution)
    return execution


def main() -> int:
    parser = argparse.ArgumentParser(description="run Q10-GC0-UB1 support-only audit")
    parser.add_argument("--mode", choices=("smoke", "full"), default="full")
    args = parser.parse_args()
    try:
        execution = run_audit(args.mode)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Q10-GC0-UB1 failed closed: {error}") from error
    gate = execution["raw_group_upper_bound"]
    print(json.dumps({
        "status": execution["status"],
        "mode": execution["run_scope"],
        "endpoint_sets": execution["counts"]["endpoint_set_count"],
        "raw_groups": execution["counts"]["raw_group_count"],
        "baseline_mismatches": gate["baseline_mismatch_count"],
        "covered": gate["covered_mismatch_count"],
        "uncovered": gate["uncovered_mismatch_count"],
        "classification": gate["classification"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
