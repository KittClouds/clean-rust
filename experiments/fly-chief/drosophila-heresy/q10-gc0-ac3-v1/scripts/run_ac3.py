"""Q10-GC0-AC3 authority expansion for RA1 raw PF5 contexts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
AC2_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/scripts"
sys.path.insert(0, str(F2_SCRIPTS))
sys.path.insert(0, str(AC2_SCRIPTS))
import run_rh1 as RH1  # noqa: E402
import run_ac2 as AC2  # noqa: E402

PROTOCOL = "Q10-GC0-AC3"
IDENTITY = "q10-gc0-ac3-v1"
DECLARED_PREFIXES = tuple(AC2.PREFIX_DOMAIN)
EXPANDED_EFFECTS = ROOT / "qualification" / "expanded_effects.jsonl"
EXPANDED_FEATURES = ROOT / "qualification" / "expanded_features.jsonl"
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


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def load_local_seal() -> dict[str, Any]:
    contract = load_json(ROOT / "CONTRACT.json")
    preexecution = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "AC3 local identity drift")
    require(preexecution["protocol"] == PROTOCOL and preexecution["identity"] == IDENTITY, "AC3 PREEXECUTION identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "AC3 PLAN hash drift")
    require(preexecution["plan_sha256"] == digest(ROOT / "PLAN.md"), "AC3 PREEXECUTION PLAN drift")
    require(preexecution["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "AC3 PREEXECUTION CONTRACT drift")
    require(bool(preexecution["parent_bindings_sealed"]), "AC3 parent seal missing")
    return contract


def verify_parents(contract: dict[str, Any]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        path = REPO / Path(str(binding["path"]))
        require(path.is_file(), f"missing AC3 parent: {binding['label']}")
        actual = digest(path)
        require(actual == str(binding["sha256"]).upper(), f"AC3 parent drift: {binding['label']}")
        verified[str(binding["label"])] = actual
    return verified


def load_ac2_tables() -> tuple[dict[tuple[str, int, int, int], dict[str, Any]], dict[tuple[str, int, int], dict[str, Any]]]:
    feature_path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"
    effect_path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/effects.jsonl"
    features: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    effects: dict[tuple[str, int, int], dict[str, Any]] = {}
    for line in feature_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(item["coordinate"]))
        require(key not in features, f"duplicate AC2 feature: {key}")
        features[key] = item
    for line in effect_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["endpoint"]), int(item["set_index"]), int(item["coordinate"]))
        require(key not in effects, f"duplicate AC2 effect: {key}")
        effects[key] = item
    return features, effects


def load_ra1(contract: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[str, int, int], dict[str, Any]]]:
    ra1_root = REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1"
    execution = load_json(ra1_root / "qualification/execution.json")
    require(execution["protocol"] == "Q10-GC0-RA1", "RA1 execution identity drift")
    require(execution["gate"]["raw_support_complete"], "RA1 raw support gate was not complete")
    records = {}
    for item in execution["raw_group_records"]:
        key = (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]))
        require(key not in records, f"duplicate RA1 group record: {key}")
        records[key] = item
    require(len(records) == int(contract["sample"]["expected_raw_group_count"]), "RA1 group count drift")
    return execution, records


def support_rows(state: Any, coordinate: int) -> list[int]:
    rows = []
    for row, count in state.support_counts[coordinate]:
        if int(count):
            rows.append(int(row))
    return rows


def finite_effect(record: dict[str, Any], support_count: int) -> bool:
    if int(record.get("support_row_count", -1)) != support_count:
        return False
    if not bool(record.get("prefix_domain_complete")) or not bool(record.get("physical_support_complete")):
        return False
    legal = [int(item["choice"]) for item in record.get("legal_prefixes", [])]
    illegal = [int(value) for value in record.get("illegal_prefixes", [])]
    if len(legal) != len(set(legal)) or len(illegal) != len(set(illegal)):
        return False
    if set(legal) | set(illegal) != set(DECLARED_PREFIXES) or set(legal) & set(illegal):
        return False
    for prefix in record.get("legal_prefixes", []):
        if len(prefix.get("effect_bits", [])) != support_count:
            return False
        if any(not isinstance(value, int) or not 0 <= value <= 0xFFFF_FFFF for value in prefix["effect_bits"]):
            return False
        if any(not math.isfinite(float(value)) for value in prefix.get("geometry", {}).values()):
            return False
    return True


def derive_feature(state: Any, group: Any, effect: dict[str, Any]) -> dict[str, Any]:
    support = [int(value) for value in effect["support_rows"]]
    declared = sorted(set(int(value) for value in group.rows) & set(support))
    positions = {row: index for index, row in enumerate(support)}
    helpful: set[int] = set()
    first: dict[int, int] = {}
    collateral: list[int] = []
    for prefix in effect["legal_prefixes"]:
        choice = int(prefix["choice"])
        effect_bits = prefix["effect_bits"]
        collateral_count = 0
        for row in declared:
            baseline = int(state.baseline_readout_bits[row])
            target = int(state.target_readout_bits[row])
            actual = int(effect_bits[positions[row]])
            before = AC2.PF5.ulp_distance(AC2.PF5.from_bits(baseline), AC2.PF5.from_bits(target))
            after = AC2.PF5.ulp_distance(AC2.PF5.from_bits(actual), AC2.PF5.from_bits(target))
            if after < before:
                helpful.add(row)
                first.setdefault(row, abs(choice))
            if before == 0 and actual != baseline:
                collateral_count += 1
        collateral.append(collateral_count)
    burden = sum(
        AC2.PF5.ulp_distance(AC2.PF5.from_bits(state.baseline_readout_bits[row]), AC2.PF5.from_bits(state.target_readout_bits[row]))
        for row in helpful
    )
    return {
        "endpoint": state.key[0],
        "set_index": int(state.key[1]),
        "group_index": int(group.group_index),
        "coordinate": int(effect["coordinate"]),
        "declared_row_count": len(declared),
        "helpful_row_count": len(helpful),
        "helpful_ulp_burden": burden,
        "first_helpful_scale_median": statistics.median(first.values()) if first else None,
        "helpful_rows": sorted(helpful),
        "minimum_collateral_exact_support_rows": min(collateral, default=0),
        "legal_prefixes": [int(item["choice"]) for item in effect["legal_prefixes"]],
        "illegal_prefixes": [int(value) for value in effect["illegal_prefixes"]],
        "complete": True,
    }


def run_expansion(contract: dict[str, Any], ra1_records: dict[tuple[str, int, int], dict[str, Any]], ac2_features: dict[Any, Any], ac2_effects: dict[Any, Any]) -> dict[str, Any]:
    keys = {tuple(value) for value in contract["sample"].get("endpoint_keys", [])}
    if not keys:
        keys = {(str(item["endpoint"]), int(item["set_index"])) for item in ra1_records.values()}
    _, states, groups_by_key = RH1.load_runtime(keys)
    require(len(states) == int(contract["sample"]["expected_endpoint_set_count"]), "AC3 runtime state count drift")
    targets = []
    for key, group_record in sorted(ra1_records.items()):
        endpoint, set_index, group_index = key
        runtime_group = groups_by_key[key]
        require(list(runtime_group.coordinates) == group_record["coordinate_ids"], f"RA1/runtime coordinates drift: {key}")
        evidence = {int(item["coordinate"]): item for item in group_record["authority_evidence"]}
        for coordinate in runtime_group.coordinates:
            status = str(evidence[int(coordinate)]["status"])
            if status != "complete":
                targets.append((endpoint, set_index, group_index, int(coordinate)))
    require(len(targets) == int(contract["sample"]["expected_expansion_contexts"]), "AC3 expansion target count drift")
    new_effects: dict[tuple[str, int, int], dict[str, Any]] = {}
    new_features: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    replayed_pairs = 0
    reused_effects = 0
    legal_prefix_count = 0
    for endpoint, set_index, group_index, coordinate in targets:
        state = states[(endpoint, set_index)]
        group = groups_by_key[(endpoint, set_index, group_index)]
        effect_key = (endpoint, set_index, coordinate)
        if effect_key in ac2_effects:
            effect = ac2_effects[effect_key]
            reused_effects += 1
        else:
            rows = support_rows(state, coordinate)
            require(rows, f"AC3 coordinate has no support: {effect_key}")
            effect = AC2.build_pair_record(state, coordinate, rows)
            new_effects[effect_key] = effect
            replayed_pairs += 1
        require(finite_effect(effect, len(support_rows(state, coordinate))), f"AC3 incomplete effect: {effect_key}")
        legal_prefix_count += len(effect["legal_prefixes"])
        feature_key = (endpoint, set_index, group_index, coordinate)
        feature = derive_feature(state, group, effect)
        new_features[feature_key] = feature
    require(len(new_features) == len(targets), "AC3 feature-key collision")
    EXPANDED_EFFECTS.parent.mkdir(parents=True, exist_ok=True)
    with EXPANDED_EFFECTS.open("w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(new_effects):
            handle.write(json.dumps(new_effects[key], separators=(",", ":")) + "\n")
    with EXPANDED_FEATURES.open("w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(new_features):
            handle.write(json.dumps(new_features[key], separators=(",", ":")) + "\n")
    complete_support_by_state: dict[tuple[str, int], set[int]] = {key: set() for key in states}
    raw_support_by_state: dict[tuple[str, int], set[int]] = {key: set() for key in states}
    for (endpoint, set_index, group_index), group in groups_by_key.items():
        state = states[(endpoint, set_index)]
        for coordinate in group.coordinates:
            support = set(support_rows(state, int(coordinate)))
            raw_support_by_state[(endpoint, set_index)].update(support)
            complete_support_by_state[(endpoint, set_index)].update(support)
    per_state = []
    for key in sorted(states):
        state = states[key]
        mismatch = {row for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits)) if actual != target}
        raw = raw_support_by_state[key]
        complete = complete_support_by_state[key]
        per_state.append({
            "endpoint": key[0], "set_index": key[1], "baseline_mismatch_count": len(mismatch),
            "raw_support_count": len(raw), "complete_authority_support_count": len(complete),
            "raw_uncovered_mismatch_count": len(mismatch - raw),
            "complete_uncovered_mismatch_count": len(mismatch - complete),
        })
    return {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "firewall": contract["firewall"],
        "counts": {
            "endpoint_set_count": len(states),
            "raw_group_count": len(groups_by_key),
            "raw_coordinate_context_count": len(targets) + int(contract["sample"]["expected_complete_ac2_contexts"]),
            "reused_complete_ac2_contexts": int(contract["sample"]["expected_complete_ac2_contexts"]),
            "expansion_contexts": len(targets),
            "new_feature_records": len(new_features),
            "new_effect_records": len(new_effects),
            "reused_effect_records": reused_effects,
            "replayed_effect_records": replayed_pairs,
            "new_legal_prefix_records": legal_prefix_count,
        },
        "input_hashes": {
            "ra1_execution_sha256": digest(REPO / "experiments/drosophila-heresy/q10-gc0-ra1-v1/qualification/execution.json"),
            "ac2_features_sha256": digest(REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"),
            "ac2_effects_sha256": digest(REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/effects.jsonl"),
        },
        "output_hashes": {"expanded_features_sha256": digest(EXPANDED_FEATURES), "expanded_effects_sha256": digest(EXPANDED_EFFECTS)},
        "endpoint_set_results": per_state,
        "gate": {
            "expanded_records_complete": len(new_features) == len(targets),
            "merged_authority_context_complete": True,
            "raw_support_complete": all(item["raw_uncovered_mismatch_count"] == 0 for item in per_state),
            "complete_authority_support_equals_raw_support": all(item["complete_uncovered_mismatch_count"] == 0 for item in per_state),
        },
    }


def write_derived(contract: dict[str, Any], verified: dict[str, str], execution: dict[str, Any]) -> None:
    summary = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "AC3_ENGINEERING_COMPLETE_AUTHORITY_COMPLETE" if execution["gate"]["complete_authority_support_equals_raw_support"] else "AC3_ENGINEERING_INCOMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "counts": execution["counts"],
        "gate": execution["gate"],
        "verified_parent_bindings": verified,
        "interpretation": "AC3 expands AC2 authority observations to the RA1 raw-group context set. This qualifies the authority instrument only; it does not construct a global endpoint or authorize GC1.",
    }
    write_json(SUMMARY, summary)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        "\n".join([
            "# Q10-GC0-AC3 result", "",
            "AC3 is an engineering-only authority expansion. Existing AC2 observations were reused immutably; missing raw-group contexts were measured with exact sequential-f32 prefix replay.", "",
            f"- Raw contexts: **{execution['counts']['raw_coordinate_context_count']}**.",
            f"- Reused complete AC2 contexts: **{execution['counts']['reused_complete_ac2_contexts']}**.",
            f"- Newly measured contexts: **{execution['counts']['expansion_contexts']}**.",
            f"- New effect/feature records: **{execution['counts']['new_effect_records']} / {execution['counts']['new_feature_records']}**.",
            f"- Merged authority context complete: **{execution['gate']['merged_authority_context_complete']}**.",
            f"- Complete-authority support equals raw support: **{execution['gate']['complete_authority_support_equals_raw_support']}**.",
            "",
            "This is an instrument qualification. It does not authorize GC1, claim constructor optimality, or promote a scientific result.", "",
        ]), encoding="utf-8", newline="\n")
    status = {
        "protocol": PROTOCOL, "identity": IDENTITY, "status": summary["status"],
        "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False,
        "gc1_authorized": False, "execution_sha256": digest(EXECUTION),
        "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT),
        "expanded_effects_sha256": digest(EXPANDED_EFFECTS), "expanded_features_sha256": digest(EXPANDED_FEATURES),
    }
    write_json(STATUS, status)


def run() -> None:
    contract = load_local_seal()
    verified = verify_parents(contract)
    ac2_features, ac2_effects = load_ac2_tables()
    ra1_execution, ra1_records = load_ra1(contract)
    require(ra1_execution["counts"]["complete_unique_pairs"] == int(contract["sample"]["expected_complete_ac2_contexts"]), "RA1 complete-context count drift")
    execution = run_expansion(contract, ra1_records, ac2_features, ac2_effects)
    execution["verified_parent_bindings"] = verified
    write_json(EXECUTION, execution)
    write_derived(contract, verified, execution)
    print(json.dumps(load_json(STATUS), indent=2, sort_keys=True))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
