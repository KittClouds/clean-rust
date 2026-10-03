"""Q10-GC0-RA1 raw-group authority coverage audit.

This is a metadata-only qualification.  It loads the sealed PF5/RH1 runtime,
checks raw-group support, and compares each raw-group coordinate with the
sealed AC2 feature/effect observations.  It never replays a prefix, builds a
candidate, runs GC1, or writes outside this protocol root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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

PROTOCOL = "Q10-GC0-RA1"
IDENTITY = "q10-gc0-ra1-v1"
OUTPUT = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"

DECLARED_PREFIXES = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)


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


def json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def endpoint_key(value: Iterable[Any]) -> tuple[str, int]:
    endpoint, set_index = tuple(value)
    return str(endpoint), int(set_index)


def key_list(key: tuple[str, int]) -> list[Any]:
    return [key[0], key[1]]


def load_local_seal() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = load_json(ROOT / "CONTRACT.json")
    preexecution = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "RA1 contract identity drift")
    require(preexecution["protocol"] == PROTOCOL and preexecution["identity"] == IDENTITY, "RA1 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "RA1 PLAN hash drift")
    require(preexecution["plan_sha256"] == digest(ROOT / "PLAN.md"), "RA1 PREEXECUTION PLAN drift")
    require(preexecution["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "RA1 PREEXECUTION CONTRACT drift")
    require(bool(preexecution.get("parent_bindings_sealed")), "RA1 parent-binding seal missing")
    sample = contract["sample"]
    require(bool(sample["selection_is_sealed"]) and bool(sample["selection_is_not_post_outcome"]), "RA1 selection firewall drift")
    return contract, preexecution


def verify_parent_bindings(contract: dict[str, Any]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        label = str(binding["label"])
        relative = Path(str(binding["path"]))
        require(not relative.is_absolute(), f"RA1 parent path is absolute: {label}")
        path = REPO / relative
        require(path.is_file(), f"RA1 parent missing: {label}")
        actual = digest(path)
        expected = str(binding["sha256"]).upper()
        require(actual == expected, f"RA1 parent drift: {label}")
        verified[label] = actual
    return verified


def verify_sample(contract: dict[str, Any]) -> list[tuple[str, int]]:
    keys = [endpoint_key(value) for value in contract["sample"]["endpoint_keys"]]
    require(len(keys) == len(set(keys)), "RA1 sample endpoint/set duplicate")
    require(len(keys) == int(contract["sample"]["expected_endpoint_set_count"]) == 14, "RA1 sample set count drift")
    require(len({key[0] for key in keys}) == int(contract["sample"]["expected_endpoint_count"]) == 4, "RA1 sample endpoint count drift")
    require(int(contract["sample"]["expected_raw_group_count"]) == 801, "RA1 raw-group expectation drift")
    return keys


def load_authority() -> tuple[dict[tuple[str, int, int, int], dict[str, Any]], dict[tuple[str, int, int], dict[str, Any]]]:
    feature_path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"
    effect_path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/effects.jsonl"
    features: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    effects: dict[tuple[str, int, int], dict[str, Any]] = {}
    for line in feature_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(item["coordinate"]))
        require(key not in features, f"duplicate AC2 feature record: {key}")
        features[key] = item
    for line in effect_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["endpoint"]), int(item["set_index"]), int(item["coordinate"]))
        require(key not in effects, f"duplicate AC2 effect record: {key}")
        effects[key] = item
    return features, effects


def support_for_coordinates(state: Any, coordinates: Iterable[int]) -> set[int]:
    result: set[int] = set()
    for value in coordinates:
        coordinate = int(value)
        require(0 <= coordinate < len(state.support_counts), f"support coordinate out of range: {coordinate}")
        for row_value, count_value in state.support_counts[coordinate]:
            row, count = int(row_value), int(count_value)
            require(0 <= row < len(state.rows), f"support row out of range: {coordinate} {row}")
            require(count >= 0, f"negative support count: {coordinate} {row}")
            if count:
                result.add(row)
    return result


def mismatch_rows(state: Any) -> set[int]:
    baseline = tuple(int(value) for value in state.baseline_readout_bits)
    target = tuple(int(value) for value in state.target_readout_bits)
    require(len(baseline) == len(target), "readout cardinality drift")
    return {row for row, (actual, expected) in enumerate(zip(baseline, target)) if actual != expected}


def stratum(contract: dict[str, Any], size: int) -> str:
    matches = []
    for item in contract["group_size_strata"]:
        maximum = item["maximum"]
        if size >= int(item["minimum"]) and (maximum is None or size <= int(maximum)):
            matches.append(str(item["label"]))
    require(len(matches) == 1, f"raw group size has no unique stratum: {size}")
    return matches[0]


def finite_effects(effect: dict[str, Any]) -> bool:
    if not bool(effect.get("finite_effects")):
        return False
    for item in effect.get("legal_prefixes", []):
        for value in item.get("effect_bits", []):
            if not isinstance(value, int) or not 0 <= value <= 0xFFFF_FFFF:
                return False
        geometry = item.get("geometry", {})
        if any(not math.isfinite(float(value)) for value in geometry.values()):
            return False
    return True


def classify_authority(
    state: Any,
    endpoint: str,
    set_index: int,
    group_index: int,
    coordinate: int,
    features: dict[tuple[str, int, int, int], dict[str, Any]],
    effects: dict[tuple[str, int, int], dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    feature_key = (endpoint, set_index, group_index, coordinate)
    effect_key = (endpoint, set_index, coordinate)
    feature = features.get(feature_key)
    effect = effects.get(effect_key)
    evidence = {"feature_present": feature is not None, "effect_present": effect is not None}
    if feature is None and effect is None:
        return "missing", evidence
    complete = True
    if feature is None or effect is None:
        complete = False
    else:
        legal_feature = tuple(int(value) for value in feature.get("legal_prefixes", []))
        illegal_feature = tuple(int(value) for value in feature.get("illegal_prefixes", []))
        legal_effect = tuple(int(item["choice"]) for item in effect.get("legal_prefixes", []))
        complete &= bool(feature.get("complete"))
        complete &= len(legal_feature) == len(set(legal_feature))
        complete &= len(illegal_feature) == len(set(illegal_feature))
        complete &= not set(legal_feature) & set(illegal_feature)
        complete &= set(legal_feature) | set(illegal_feature) == set(DECLARED_PREFIXES)
        complete &= set(legal_effect) == set(legal_feature)
        complete &= bool(effect.get("prefix_domain_complete"))
        complete &= bool(effect.get("physical_support_complete"))
        complete &= finite_effects(effect)
        current_support = len(support_for_coordinates(state, [coordinate]))
        effect_support_rows = effect.get("support_rows", [])
        effect_support_count = len(effect_support_rows) if isinstance(effect_support_rows, list) else int(effect_support_rows)
        complete &= effect_support_count == current_support
        complete &= int(effect.get("support_row_count", -1)) == current_support
        evidence.update(
            {
                "feature_complete": bool(feature.get("complete")),
                "effect_prefix_domain_complete": bool(effect.get("prefix_domain_complete")),
                "effect_physical_support_complete": bool(effect.get("physical_support_complete")),
                "effect_finite": finite_effects(effect),
                "feature_legal_prefix_count": len(legal_feature),
                "effect_legal_prefix_count": len(legal_effect),
                "current_support_row_count": current_support,
                "effect_support_row_count": int(effect.get("support_row_count", effect_support_count)),
            }
        )
    return ("complete" if complete else "partial"), evidence


def coverage(mismatch: set[int], support: set[int]) -> dict[str, Any]:
    covered = mismatch & support
    uncovered = mismatch - support
    return {
        "physical_support_count": len(support),
        "baseline_mismatch_count": len(mismatch),
        "covered_mismatch_count": len(covered),
        "uncovered_mismatch_count": len(uncovered),
        "coverage_fraction": (len(covered) / len(mismatch)) if mismatch else 1.0,
        "covered_mismatch_rows": sorted(covered),
        "uncovered_mismatch_rows": sorted(uncovered),
    }


def audit(contract: dict[str, Any], keys: list[tuple[str, int]], features: dict[Any, Any], effects: dict[Any, Any]) -> dict[str, Any]:
    _, states, groups_by_key = RH1.load_runtime(set(keys))
    require(len(states) == len(keys), f"runtime state count drift: {len(states)}")
    raw_group_records: list[dict[str, Any]] = []
    endpoint_results: list[dict[str, Any]] = []
    strata_totals: dict[str, Counter[str]] = {}
    total_coordinate_records = 0
    complete_records = partial_records = missing_records = 0
    unique_pair_states: dict[tuple[str, int, int], set[str]] = {}
    for key in keys:
        state = states[key]
        groups = [groups_by_key[(key[0], key[1], index)] for index in sorted(index for endpoint, set_index, index in groups_by_key if endpoint == key[0] and set_index == key[1])]
        require(len(groups) > 0, f"no raw groups for {key}")
        mismatch = mismatch_rows(state)
        all_support: set[int] = set()
        complete_support: set[int] = set()
        partial_support: set[int] = set()
        state_records = []
        for group in groups:
            coordinates = tuple(int(value) for value in group.coordinates)
            declared_rows = tuple(int(value) for value in group.rows)
            physical = support_for_coordinates(state, coordinates)
            all_support.update(physical)
            statuses = []
            evidence_by_coordinate = []
            for coordinate in coordinates:
                status, evidence = classify_authority(state, key[0], key[1], int(group.group_index), coordinate, features, effects)
                statuses.append(status)
                evidence_by_coordinate.append({"coordinate": coordinate, "status": status, **evidence})
                total_coordinate_records += 1
                if status == "complete":
                    complete_records += 1
                    complete_support.update(support_for_coordinates(state, [coordinate]))
                elif status == "partial":
                    partial_records += 1
                    partial_support.update(support_for_coordinates(state, [coordinate]))
                else:
                    missing_records += 1
                unique_pair_states.setdefault((key[0], key[1], coordinate), set()).add(status)
            label = stratum(contract, len(coordinates))
            strata_totals.setdefault(label, Counter())["groups"] += 1
            strata_totals[label].update({"complete_coordinate_records": statuses.count("complete"), "partial_coordinate_records": statuses.count("partial"), "missing_coordinate_records": statuses.count("missing")})
            state_record = {
                "group_index": int(group.group_index),
                "stratum": label,
                "group_size": len(coordinates),
                "declared_rows": list(declared_rows),
                "coordinate_ids": list(coordinates),
                "physical_support_rows": sorted(physical),
                "physical_support_count": len(physical),
                "authority_counts": dict(Counter(statuses)),
                "all_coordinates_complete": all(status == "complete" for status in statuses),
                "authority_evidence": evidence_by_coordinate,
            }
            state_records.append(state_record)
            raw_group_records.append({"endpoint": key[0], "set_index": key[1], **state_record})
        result = coverage(mismatch, all_support)
        complete_cov = coverage(mismatch, complete_support)
        partial_cov = coverage(mismatch, partial_support)
        result.update(
            {
                "endpoint": key[0],
                "set_index": key[1],
                "raw_group_count": len(groups),
                "raw_coordinate_record_count": sum(len(group.coordinates) for group in groups),
                "raw_complete_authority_support": complete_cov,
                "raw_partial_authority_support": partial_cov,
                "group_size_strata": {
                    label: {
                        "raw_group_count": sum(1 for item in state_records if item["stratum"] == label),
                        "group_size_distribution": dict(sorted(Counter(item["group_size"] for item in state_records if item["stratum"] == label).items())),
                    }
                    for label in sorted({item["stratum"] for item in state_records})
                },
                "mismatch_identity_sha256": json_hash(sorted(mismatch)),
            }
        )
        endpoint_results.append(result)
    pair_status_counter = Counter()
    for statuses in unique_pair_states.values():
        if statuses == {"complete"}:
            pair_status_counter["complete"] += 1
        elif statuses == {"missing"}:
            pair_status_counter["missing"] += 1
        else:
            pair_status_counter["partial"] += 1
    require(len(raw_group_records) == int(contract["sample"]["expected_raw_group_count"]), "RA1 raw group count drift")
    require(len(features) == int(contract["expected"]["ac2_feature_records"]), "RA1 AC2 feature count drift")
    require(len(effects) == int(contract["expected"]["ac2_effect_records"]), "RA1 AC2 effect count drift")
    result = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "firewall": contract["firewall"],
        "sample": {"endpoint_keys": [key_list(key) for key in keys], "endpoint_set_count": len(keys)},
        "counts": {
            "endpoint_set_count": len(keys),
            "raw_group_count": len(raw_group_records),
            "raw_coordinate_record_count": total_coordinate_records,
            "unique_endpoint_set_coordinate_pair_count": len(unique_pair_states),
            "complete_coordinate_records": complete_records,
            "partial_coordinate_records": partial_records,
            "missing_coordinate_records": missing_records,
            "complete_unique_pairs": pair_status_counter["complete"],
            "partial_unique_pairs": pair_status_counter["partial"],
            "missing_unique_pairs": pair_status_counter["missing"],
            "ac2_feature_records": len(features),
            "ac2_effect_records": len(effects),
        },
        "authority_contract": {
            "declared_prefix_vocabulary": list(DECLARED_PREFIXES),
            "complete_definition": contract["authority"]["complete_requires"],
            "feature_hash": digest(REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"),
            "effect_hash": digest(REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/effects.jsonl"),
        },
        "endpoint_set_results": endpoint_results,
        "strata_totals": {label: dict(values) for label, values in sorted(strata_totals.items())},
        "raw_group_records": raw_group_records,
        "gate": {
            "raw_support_complete": all(item["uncovered_mismatch_count"] == 0 for item in endpoint_results),
            "all_raw_coordinate_pairs_complete": pair_status_counter["partial"] == 0 and pair_status_counter["missing"] == 0,
            "complete_authority_support_equals_raw_support": all(item["raw_complete_authority_support"]["uncovered_mismatch_count"] == 0 for item in endpoint_results),
        },
    }
    return result


def derive_summary(execution: dict[str, Any], verified: dict[str, str]) -> dict[str, Any]:
    counts = execution["counts"]
    gate = execution["gate"]
    status = "RA1_ENGINEERING_COMPLETE_AUTHORITY_INCOMPLETE"
    if gate["all_raw_coordinate_pairs_complete"] and gate["complete_authority_support_equals_raw_support"]:
        status = "RA1_ENGINEERING_COMPLETE_AUTHORITY_COMPLETE"
    return {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": status,
        "engineering_only": True,
        "scientific_promotion": False,
        "counts": counts,
        "gate": gate,
        "interpretation": (
            "The raw PF5 group partition was audited against sealed AC2 authority observations. "
            "Authority coverage is contextual and must be expanded before a full raw-group authority-aware palette "
            "unless every raw coordinate pair is complete and complete-authority support covers the raw support."
        ),
        "verified_parent_bindings": verified,
    }


def render_result(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    gate = summary["gate"]
    return "\n".join(
        [
            "# Q10-GC0-RA1 result",
            "",
            "RA1 is an engineering-only raw-group authority coverage audit. It did not generate candidates, replay prefixes, run GC1, probe behavior, or promote science.",
            "",
            f"- Raw groups audited: **{counts['raw_group_count']}** across **{counts['endpoint_set_count']}** endpoint/set states.",
            f"- Raw group-coordinate records: **{counts['raw_coordinate_record_count']}**; unique endpoint/set/coordinate pairs: **{counts['unique_endpoint_set_coordinate_pair_count']}**.",
            f"- Authority records classified complete/partial/missing: **{counts['complete_coordinate_records']} / {counts['partial_coordinate_records']} / {counts['missing_coordinate_records']}**.",
            f"- Unique-pair classifications complete/partial/missing: **{counts['complete_unique_pairs']} / {counts['partial_unique_pairs']} / {counts['missing_unique_pairs']}**.",
            "",
            "## Gates",
            "",
            f"- Raw PF5 support complete: **{gate['raw_support_complete']}**.",
            f"- Every raw coordinate pair has complete AC2 authority: **{gate['all_raw_coordinate_pairs_complete']}**.",
            f"- Complete-authority support equals raw support: **{gate['complete_authority_support_equals_raw_support']}**.",
            "",
            "A false authority-completeness gate is an authority-measurement limitation, not a global infeasibility claim. A future authority expansion must measure the missing or partial raw-group coordinate contexts before a full authority-aware palette is treated as qualified.",
            "",
        ]
    )


def run() -> None:
    contract, _ = load_local_seal()
    verified = verify_parent_bindings(contract)
    keys = verify_sample(contract)
    features, effects = load_authority()
    execution = audit(contract, keys, features, effects)
    execution["verified_parent_bindings"] = verified
    write_json(OUTPUT, execution)
    summary = derive_summary(execution, verified)
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(render_result(summary), encoding="utf-8", newline="\n")
    status = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": summary["status"],
        "engineering_only": True,
        "scientific_promotion": False,
        "behavioral_probe": False,
        "gc1_authorized": False,
        "execution_sha256": digest(OUTPUT),
        "summary_sha256": digest(SUMMARY),
        "result_sha256": digest(RESULT),
        "raw_support_complete": execution["gate"]["raw_support_complete"],
        "authority_complete": execution["gate"]["all_raw_coordinate_pairs_complete"],
    }
    write_json(STATUS, status)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
