from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import os
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "experiments" / "drosophila-heresy"
OUT = Path(__file__).resolve().parents[1]
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"
EXH1_SCRIPT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1" / "scripts" / "run_exh1.py"
ALG1 = EXP / "q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts" / "run_alg1.py"
DOMAIN = EXP / "q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures" / "twin-a" / "repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = EXP / "q10-gc1-lr1-requal1-par8-ref1-v1"
O2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
SUPPORT1 = EXP / "q10-gc1-lr1-requal1-csc1-resid-support1-v1"
PRIM_GAP1 = EXP / "q10-gc1-lr1-requal1-csc1-prim-gap1-v1"
PROTOCOL = "Q10-RESID-INVALID1-R2"
BOUNDARY_GUARD = 1.0e-12
PROGRESS_EVERY = 250_000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def digest_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_or_verify(path: Path, value: Any) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        require(existing == value, f"sealed premeasurement artifact drift: {path}")
        return
    write_new(path, value)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module load failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_bindings() -> list[dict[str, Any]]:
    paths = [
        ("exh1_runner", EXH1_SCRIPT),
        ("alg1_runner", ALG1_SCRIPT),
        ("alg1_descriptor", ALG1 / "descriptors" / f"{SLUG}.json"),
        ("alg1_execution", ALG1 / "execution.json"),
        ("pf5_contract", PF5_CONTRACT),
        ("reference_execution", REF / "execution.json"),
        ("o2_frontier", O2 / "shards" / f"{SLUG}.jsonl"),
        ("support1_execution", SUPPORT1 / "execution.json"),
        ("support1_rows", SUPPORT1 / "row-stats.json"),
        ("prim_gap1_execution", PRIM_GAP1 / "execution.json"),
        ("prim_gap1_rows", PRIM_GAP1 / "row-stats.json"),
        ("false_positive_rerun_execution", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "execution.json"),
        ("false_positive_rerun_domain", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "domain-summary.json"),
        ("false_positive_rerun_order2_witnesses", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "results/order2_hits.jsonl"),
        ("false_positive_rerun_order3_witnesses", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "results/order3_hits.jsonl"),
        ("false_positive_reconciliation_execution", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-reconcile1-v1" / "execution.json"),
        ("false_positive_reconciliation", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-reconcile1-v1" / "reconciliation.json"),
        ("false_positive_rerun_execution", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "execution.json"),
        ("false_positive_reconciliation", EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-reconcile1-v1" / "reconciliation.json"),
    ]
    return [{"label": label, "path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in paths]


def load_reference_bits() -> tuple[int, ...]:
    path = O2 / "shards" / f"{SLUG}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                return tuple(int(value) for value in record["readout_bits"])
    raise RuntimeError("order-2 reference record missing")


def fast_geometry(exh: Any, context: dict[str, Any], indices: tuple[int, ...]) -> dict[str, float]:
    actions = context["actions"]
    s_geometry = context["s"]["geometry"]
    final_axis = float(s_geometry["final_axis"]) + math.fsum(actions[index]["axis_delta"] for index in indices)
    norm_sq = context["baseline_norm_sq"] + math.fsum(actions[index]["norm_delta"] for index in indices)
    require(norm_sq >= 0.0, "negative fast norm square")
    cue_sq = context["baseline_linear_sq"] + math.fsum(actions[index]["action_q"] for index in indices)
    for left, right in itertools.combinations(indices, 2):
        cue_sq += 2.0 * context["pair_dot"][left][right]
    require(cue_sq >= 0.0, "negative fast cue square")
    final_norm = math.sqrt(norm_sq)
    cue_error = math.sqrt(cue_sq)
    target_axis = float(s_geometry["target_axis"])
    target_norm = float(s_geometry["target_norm"])
    cue_scale = max(float(context["target_drive_norm"]), 1.0e-12)
    geometry = {
        "axis_absolute_error": abs(final_axis - target_axis),
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12),
        "norm_absolute_error": abs(final_norm - target_norm),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12),
        "cue_linear_absolute_error": cue_error,
        "cue_linear_normalized_error": cue_error / cue_scale,
        "final_axis": final_axis,
        "target_axis": target_axis,
        "final_norm": final_norm,
        "target_norm": target_norm,
    }
    require(all(math.isfinite(float(value)) for value in geometry.values()), "nonfinite geometry")
    return geometry


def near_boundary(exh: Any, geometry: dict[str, float], gates: dict[str, float]) -> bool:
    margins = exh.margins(geometry, gates)
    return any(abs(float(value)) <= BOUNDARY_GUARD for value in margins)


def apply_row_updates(weights: list[float], updates: tuple[tuple[int, float], ...]) -> tuple[list[tuple[int, float]], set[int]]:
    old: list[tuple[int, float]] = []
    seen: set[int] = set()
    for coordinate, value in updates:
        coordinate = int(coordinate)
        if coordinate in seen:
            raise RuntimeError(f"duplicate coordinate assignment violates canonical mapping semantics: {coordinate}")
        old.append((coordinate, weights[coordinate]))
        seen.add(coordinate)
        weights[coordinate] = value
    return old, seen


def canonical_mapping(actions: list[dict[str, Any]], indices: tuple[int, ...]) -> list[list[int]]:
    mapping: list[list[int]] = []
    seen: set[int] = set()
    for index in indices:
        for coordinate, choice in actions[index]["mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            require(coordinate not in seen, f"incompatible duplicate action coordinate: {coordinate}")
            seen.add(coordinate)
            mapping.append([coordinate, choice])
    mapping.sort(key=lambda item: item[0])
    return mapping


def row_local_value(context: dict[str, Any], actions: list[dict[str, Any]], indices: tuple[int, ...], row: int) -> int:
    """Execute one row using the same baseline-relative prefix semantics as ALG1.apply_mapping."""
    pf = context["pf"]
    state = context["state"]
    baseline_bits = tuple(int(value) for value in state.baseline_weight_bits)
    start_weights = list(context["s"]["weights"])
    row_coordinates = set(int(value) for value in state.rows[row])
    assigned: set[int] = set()
    for coordinate, choice in canonical_mapping(actions, indices):
        raw = pf.legal_prefix_bits(baseline_bits[coordinate], choice)
        require(raw is not None, f"canonical baseline prefix is illegal: {coordinate} {choice}")
        if coordinate in row_coordinates:
            require(coordinate not in assigned, f"duplicate row-local coordinate: {coordinate}")
            assigned.add(coordinate)
            start_weights[coordinate] = pf.from_bits(int(raw))
    return int(pf.sequential_bits(state.rows[row], start_weights))


def legacy_row_local_value(context: dict[str, Any], actions: list[dict[str, Any]], indices: tuple[int, ...], row: int) -> int:
    """Regression-only reproduction of the rejected invalid-state-relative prefix bug."""
    pf = context["pf"]
    state = context["state"]
    start_bits = tuple(context["s"]["bits"])
    start_weights = list(context["s"]["weights"])
    row_coordinates = set(int(value) for value in state.rows[row])
    for coordinate, choice in canonical_mapping(actions, indices):
        raw = pf.legal_prefix_bits(start_bits[coordinate], choice)
        require(raw is not None, f"legacy regression prefix illegal: {coordinate} {choice}")
        if coordinate in row_coordinates:
            start_weights[coordinate] = pf.from_bits(int(raw))
    return int(pf.sequential_bits(state.rows[row], start_weights))


def full_candidate(exh: Any, alg: Any, context: dict[str, Any], indices: tuple[int, ...]) -> dict[str, Any]:
    mapping = canonical_mapping(context["actions"], indices)
    bits = alg.apply_mapping(context["pf"], context["state"], tuple(context["s"]["bits"]), mapping)
    result = alg.replay(context["pf"], context["state"], bits, context["contract"])
    geometry, valid = exh.full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], indices, context["contract"])
    require(result["geometry"] == geometry, f"full-replay geometry mismatch: {indices}")
    require(bool(result["final_geometry_pass"]) == bool(valid), f"full-replay validity mismatch: {indices}")
    return {**result, "geometry": geometry, "final_geometry_pass": bool(valid), "canonical_mapping": mapping}


def regression_preflight(exh: Any, alg: Any, context: dict[str, Any]) -> dict[str, Any]:
    cases = [
        {"actions": (15, 409), "row": 36, "expected_bits": 1092185578, "legacy_false_target_bits": 1092185579},
        {"actions": (292, 357, 428), "row": 695, "expected_bits": 1103757538, "legacy_false_target_bits": 1103757536},
    ]
    results = []
    for case in cases:
        candidate = full_candidate(exh, alg, context, case["actions"])
        row = int(case["row"])
        local_bits = row_local_value(context, context["actions"], case["actions"], row)
        legacy_bits = legacy_row_local_value(context, context["actions"], case["actions"], row)
        require(int(candidate["readout"][row]) == int(case["expected_bits"]), f"full-replay regression fixture changed: row {row}")
        require(local_bits == int(case["expected_bits"]), f"correct row-local semantics failed regression: row {row}")
        require(legacy_bits == int(case["legacy_false_target_bits"],), f"legacy bug fixture drift: row {row}")
        require(local_bits != legacy_bits, f"baseline-relative regression did not distinguish semantics: row {row}")
        require(candidate["final_geometry_pass"], f"regression state geometry changed: row {row}")
        results.append({"actions": list(case["actions"]), "row": row, "expected_bits": local_bits, "legacy_bug_bits": legacy_bits, "legacy_false_target_reproduced_and_rejected": True, "full_weight_sha256": candidate["weight_state_sha256"], "full_readout_sha256": candidate["readout_sha256"], "geometry_valid": candidate["final_geometry_pass"]})
    return {"status": "PASS", "cases": results}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    prepare_only = sys.argv[1:] == ["--prepare"]
    require(not sys.argv[1:] or prepare_only, "supported invocation is --prepare or no arguments for execution")
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid_invalid1_r2.py"), Path("tests"), Path("tests/test_action_mapping_semantics.py"), Path("CONTRACT.json"), Path("PREEXECUTION.json"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("domain-summary.json"), Path("row-stats.json"), Path("parity-audit.json"), Path("results"), Path("results/order1_hits.jsonl"), Path("results/order2_hits.jsonl"), Path("results/order3_hits.jsonl")}
    if OUT.exists():
        unexpected = {path.relative_to(OUT) for path in OUT.rglob("*")} - allowed
        require(not unexpected, f"unexpected output paths: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()
        (OUT / "results").mkdir()

    bindings = source_bindings()
    support_rows = json.loads((SUPPORT1 / "row-stats.json").read_text(encoding="utf-8"))["rows"]
    target_classes = {"SUPPORTED_SINGLETON_SILENT", "AUTHORITY_PRESENT_OUTSIDE_VALID_FRONTIER"}
    target_rows = sorted(int(row["row"]) for row in support_rows if row["support_classification"] in target_classes or (row["support_classification"] == "VALID_FRONTIER_AUTHORITY_OBSERVED" and row["resid1_classification"] == "MOVABLE_NOT_TARGETABLE"))
    require(len(target_rows) == 57, f"target-row cardinality drift: {len(target_rows)}")
    domain_hash = hashlib.sha256()
    target_row_set = set(target_rows)
    exh = load_module(EXH1_SCRIPT, "q10_resid_invalid1_exh1_runtime")
    alg = exh.load_alg1()
    context = exh.prepare_context(CONTEXT, alg)
    actions = context["actions"]
    regression = regression_preflight(exh, alg, context)
    action_rows = {int(index): tuple(int(row) for row in action["dependency_rows"] if int(row) in target_row_set) for index, action in enumerate(actions)}
    touched_actions = {index for index, rows in action_rows.items() if rows}
    require(touched_actions, "no supported target rows have action support")
    groups = tuple(context["groups"])
    by_group = context["by_group"]
    group_coordinates = {group: set(int(coordinate) for coordinate, _choice in actions[by_group[group][0]]["mapping"]) for group in groups}
    for left_index, left in enumerate(groups):
        for right in groups[left_index + 1:]:
            require(not (group_coordinates[left] & group_coordinates[right]), f"action groups are not coordinate-disjoint: {left} {right}")
    order_counts = {"1": 0, "2": 0, "3": 0}
    row_stats: dict[int, dict[str, Any]] = {row: {"row": row, "evaluated_candidates": 0, "changed_from_reference": 0, "confirmed_valid_target_witnesses": 0, "confirmed_invalid_target_witnesses": 0, "minimum_ulp": None, "minimum_ulp_record": None, "first_target_order": None, "numeric_direction_counts": Counter()} for row in target_rows}
    hits: dict[int, Any] = {}
    witness_seen: set[tuple[int, int, bool]] = set()
    outcome_hash = hashlib.sha256()
    geometry_valid_counts = Counter()
    geometry_fallbacks = 0
    evaluated_total = 0
    domain_counts = {"1": len(touched_actions), "2": 0, "3": 0}
    for left, right in itertools.combinations(groups, 2):
        total = len(by_group[left]) * len(by_group[right])
        touched = sum(1 for a in by_group[left] for b in by_group[right] if a in touched_actions or b in touched_actions)
        domain_counts["2"] += touched
    for left, right, third in itertools.combinations(groups, 3):
        touched = sum(1 for a in by_group[left] for b in by_group[right] for c in by_group[third] if a in touched_actions or b in touched_actions or c in touched_actions)
        domain_counts["3"] += touched
    rerun_summary = json.loads((EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1" / "domain-summary.json").read_text(encoding="utf-8"))
    implementation_bindings = {"runner_sha256": digest(Path(__file__)), "regression_test_sha256": digest(OUT / "tests" / "test_action_mapping_semantics.py"), "plan_sha256": digest(OUT / "PLAN.md")}
    contract = {"protocol": PROTOCOL, "identity": OUT.name, "status": "SEALED_PREMEASUREMENT", "context": list(CONTEXT), "parent_bindings": bindings, "implementation_bindings": implementation_bindings, "target_rows": target_rows, "target_row_domain_sha256": digest_payload({"context": list(CONTEXT), "rows": target_rows}), "domain_counts_planned": domain_counts, "expected_domain_identity_sha256": rerun_summary["domain_identity_sha256"], "row_condition": "at least one selected action dependency footprint reaches one of 57 fixed residual rows", "action_semantics": "every prefix is resolved against the frozen baseline bits; candidate state starts from frozen S and receives the canonical mapping", "action_group_coordinate_disjointness_verified": True, "geometry_prefilter": False, "functional_evaluation_before_geometry_classification": True, "boundary_guard": BOUNDARY_GUARD, "target_hit_policy": "all row-local target-equality candidates are full-replayed; only the first confirmed witness per row and geometry class is reported", "nonhit_parity_policy": "full readout parity on the first deterministic candidate in each observed order x geometry x target-distance x support-class x prefix-scale stratum", "near_target_ulp_threshold": 8, "regression_preflight": regression, "replay_executed": False, "scientific_promotion": False, "write_allowlist": ["PLAN.md", "scripts/*", "tests/*", "CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "REPORT.md", "domain-summary.json", "row-stats.json", "parity-audit.json", "results/*"]}
    write_or_verify(OUT / "CONTRACT.json", contract)
    write_or_verify(OUT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(OUT / "CONTRACT.json"), "domain_counts_planned": domain_counts, "expected_domain_identity_sha256": rerun_summary["domain_identity_sha256"], "regression_preflight": regression, "geometry_prefilter": False, "scientific_promotion": False})
    if prepare_only:
        print(json.dumps({"protocol": PROTOCOL, "identity": OUT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(OUT / "CONTRACT.json"), "domain_counts_planned": domain_counts, "regression_preflight": regression}, indent=2, sort_keys=True))
        return 0
    hits = {1: (OUT / "results" / "order1_hits.jsonl").open("x", encoding="utf-8", newline="\n"), 2: (OUT / "results" / "order2_hits.jsonl").open("x", encoding="utf-8", newline="\n"), 3: (OUT / "results" / "order3_hits.jsonl").open("x", encoding="utf-8", newline="\n")}
    reference_bits = load_reference_bits()
    target_bits = tuple(int(value) for value in context["state"].target_readout_bits)
    base_weights = list(context["s"]["weights"])
    row_coordinate_sets = {row: set(int(coordinate) for coordinate in context["state"].rows[row]) for row in target_rows}
    row_updates: dict[int, dict[int, tuple[tuple[int, float], ...]]] = {index: {} for index in range(len(actions))}
    s_bits = tuple(int(value) for value in context["s"]["bits"])
    baseline_bits = tuple(int(value) for value in context["state"].baseline_weight_bits)
    for index, action in enumerate(actions):
        updates_by_row: dict[int, list[tuple[int, float]]] = {}
        for coordinate, choice in action["mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            raw = context["pf"].legal_prefix_bits(baseline_bits[coordinate], choice)
            require(raw is not None, f"illegal action mapping: {index} {coordinate} {choice}")
            if int(raw) == s_bits[coordinate]:
                continue
            value = context["pf"].from_bits(int(raw))
            for row in action_rows[index]:
                if coordinate in row_coordinate_sets[row]:
                    updates_by_row.setdefault(row, []).append((coordinate, value))
        row_updates[index] = {row: tuple(values) for row, values in updates_by_row.items()}
    gates = context["contract"]["geometry"]["final_da2_gates"]
    support_rows_by_id = {int(item["row"]): item for item in support_rows}
    parity_samples: dict[str, dict[str, Any]] = {}
    confirmed_witnesses: set[tuple[int, bool]] = set()
    parity_full_replay_cache: dict[tuple[int, ...], dict[str, Any]] = {}

    def parity_stratum(order: int, indices: tuple[int, ...], affected: list[int], values: dict[int, int], valid: bool) -> str:
        minimum_ulp = min(int(context["pf"].ulp_distance(context["pf"].from_bits(values[row]), context["pf"].from_bits(target_bits[row]))) for row in affected)
        distance = "near_0_8" if minimum_ulp <= 8 else "far_gt8"
        classes = sorted({str(support_rows_by_id[row]["support_classification"]) for row in affected})
        support_class = "+".join(classes)
        maximum_prefix = max((abs(int(choice)) for index in indices for _coordinate, choice in actions[index]["mapping"]), default=0)
        prefix_scale = "zero" if maximum_prefix == 0 else ("1_2" if maximum_prefix <= 2 else ("4_8" if maximum_prefix <= 8 else "16"))
        return f"o{order}|{'valid' if valid else 'invalid'}|{distance}|{support_class}|{prefix_scale}"

    def verify_full_candidate(indices: tuple[int, ...], affected: list[int], local_values: dict[int, int], expected_valid: bool) -> dict[str, Any]:
        cached = parity_full_replay_cache.get(indices)
        if cached is None:
            cached = full_candidate(exh, alg, context, indices)
            parity_full_replay_cache[indices] = cached
        require(bool(cached["final_geometry_pass"]) == bool(expected_valid), f"full geometry validity disagrees with fast classification: {indices}")
        for row in affected:
            require(int(cached["readout"][row]) == int(local_values[row]), f"local/full readout row mismatch: {indices} row {row}")
        return cached

    def evaluate(order: int, indices: tuple[int, ...]) -> None:
        nonlocal evaluated_total, geometry_fallbacks
        affected = sorted(set().union(*(action_rows[index] for index in indices)))
        require(affected, "row-conditioned candidate has empty affected-row set")
        values: dict[int, int] = {}
        weights = base_weights
        for row in affected:
            updates: list[tuple[int, float]] = []
            for index in indices:
                updates.extend(row_updates[index].get(row, ()))
            old, _seen = apply_row_updates(weights, tuple(updates))
            value = int(context["pf"].sequential_bits(context["state"].rows[row], weights))
            values[row] = value
            for coordinate, previous in reversed(old):
                weights[coordinate] = previous
        identity = {"order": order, "actions": list(indices)}
        domain_hash.update(struct.pack("<B" + "I" * order, order, *indices))
        geometry = fast_geometry(exh, context, indices)
        path = "fast"
        valid = bool(context["pf"].final_geometry_pass(geometry, context["contract"]))
        if near_boundary(exh, geometry, gates):
            geometry, valid = exh.full_geometry(alg, context["pf"], context["state"], context["s"], actions, indices, context["contract"])
            path = "authoritative_full"
            geometry_fallbacks += 1
        geometry_valid_counts[order, valid] += 1
        stratum = parity_stratum(order, indices, affected, values, valid)
        if stratum not in parity_samples:
            parity_samples[stratum] = {"order": order, "actions": list(indices), "affected_rows": affected, "local_values": {str(row): values[row] for row in affected}, "geometry_valid": valid}
        hit_rows: list[dict[str, Any]] = []
        for row, value_bits in values.items():
            stats = row_stats[row]
            target = value_bits == target_bits[row]
            changed = value_bits != reference_bits[row]
            actual = context["pf"].from_bits(value_bits)
            target_value = context["pf"].from_bits(target_bits[row])
            ulp = int(context["pf"].ulp_distance(actual, target_value))
            stats["evaluated_candidates"] += 1
            stats["changed_from_reference"] += int(changed)
            if stats["minimum_ulp"] is None or ulp < stats["minimum_ulp"]:
                stats["minimum_ulp"] = ulp
                stats["minimum_ulp_record"] = {"order": order, "actions": list(indices), "value_bits": value_bits, "geometry_valid": valid}
            direction = "equal" if actual == target_value else ("toward_numeric" if (actual - target_value) * (context["pf"].from_bits(reference_bits[row]) - target_value) < 0 else "away_or_same_side")
            stats["numeric_direction_counts"][direction] += 1
            if target:
                hit_rows.append({"row": row, "value_bits": value_bits, "ulp": ulp, "geometry_valid": valid, "direction": direction})
        outcome_hash.update(json.dumps({"identity": identity, "geometry_valid": valid, "geometry_path": path, "rows": [{"row": row, "value_bits": values[row]} for row in affected]}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        outcome_hash.update(b"\n")
        if hit_rows:
            confirmed_rows = []
            full = verify_full_candidate(indices, affected, values, valid)
            for item in hit_rows:
                witness_key = (int(item["row"]), bool(valid))
                if witness_key in confirmed_witnesses:
                    continue
                require(int(full["readout"][int(item["row"])]) == target_bits[int(item["row"])], f"target proposal failed full replay: row {item['row']} {indices}")
                confirmed_witnesses.add(witness_key)
                witness_seen.add((order, int(item["row"]), bool(valid)))
                row = row_stats[int(item["row"])]
                field = "confirmed_valid_target_witnesses" if valid else "confirmed_invalid_target_witnesses"
                row[field] += 1
                if row["first_target_order"] is None or order < row["first_target_order"]:
                    row["first_target_order"] = order
                confirmed_rows.append(item)
            if confirmed_rows:
                payload = {"order": order, "actions": list(indices), "action_keys": [actions[index]["key"] for index in indices], "canonical_mapping_sha256": digest_payload(canonical_mapping(actions, indices)), "weight_state_sha256": full["weight_state_sha256"], "readout_sha256": full["readout_sha256"], "score": full["score"], "geometry_valid": full["final_geometry_pass"], "geometry": full["geometry"], "full_readout_verified": True, "target_rows": confirmed_rows}
                hits[order].write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        evaluated_total += 1
        if evaluated_total % PROGRESS_EVERY == 0:
            print(json.dumps({"evaluated": evaluated_total, "confirmed_target_witnesses": len(confirmed_witnesses), "fallbacks": geometry_fallbacks}, sort_keys=True), flush=True)

    try:
        for index in sorted(touched_actions):
            evaluate(1, (index,))
        for left, right in itertools.combinations(groups, 2):
            for a in by_group[left]:
                for b in by_group[right]:
                    if a in touched_actions or b in touched_actions:
                        evaluate(2, (a, b))
        for left, right, third in itertools.combinations(groups, 3):
            for a in by_group[left]:
                for b in by_group[right]:
                    for c in by_group[third]:
                        if a in touched_actions or b in touched_actions or c in touched_actions:
                            evaluate(3, (a, b, c))
        for stream in hits.values():
            stream.close()
        parity_results = []
        for stratum, sample in sorted(parity_samples.items()):
            indices = tuple(int(value) for value in sample["actions"])
            affected = [int(value) for value in sample["affected_rows"]]
            local_values = {int(row): int(value) for row, value in sample["local_values"].items()}
            full = verify_full_candidate(indices, affected, local_values, bool(sample["geometry_valid"]))
            parity_results.append({"stratum": stratum, "actions": list(indices), "affected_row_count": len(affected), "full_readout_sha256": full["readout_sha256"], "weight_state_sha256": full["weight_state_sha256"], "score": full["score"], "geometry_valid": full["final_geometry_pass"], "all_affected_rows_bitwise_equal": True})
        actual_counts = {"1": len(touched_actions), "2": domain_counts["2"], "3": domain_counts["3"]}
        require(evaluated_total == sum(actual_counts.values()), f"candidate accounting drift: {evaluated_total} != {sum(actual_counts.values())}")
        require(domain_hash.hexdigest().upper() == contract["expected_domain_identity_sha256"], "frozen domain identity hash drift")
        current_bindings = source_bindings()
        require(current_bindings == bindings, "bound source changed during RESID-INVALID1-R2")
        classification_counts: Counter[str] = Counter()
        for row in row_stats.values():
            row["numeric_direction_counts"] = dict(sorted(row["numeric_direction_counts"].items()))
            has_valid_target = row["confirmed_valid_target_witnesses"] > 0
            has_invalid_target = row["confirmed_invalid_target_witnesses"] > 0
            if has_valid_target:
                row["classification"] = "TARGETABLE_IN_VALID_FRONTIER"
            elif has_invalid_target:
                row["classification"] = "TARGETABLE_ONLY_OUTSIDE_VALID_FRONTIER"
            elif row["changed_from_reference"] == 0:
                row["classification"] = "NO_EFFECT_THROUGH_ORDER3"
            else:
                row["classification"] = "MOVABLE_NOT_TARGETABLE_THROUGH_ORDER3"
            classification_counts[row["classification"]] += 1
        parity_audit = {"protocol": "RESID-INVALID1-R2-PARITY", "sample_selection": "first enumerated candidate in each predeclared observed stratum", "strata_dimensions": ["order", "geometry validity", "minimum affected-row target ULP <=8 vs >8", "support-class signature", "maximum prefix scale bucket"], "candidate_count": len(parity_results), "full_readout_mismatches": 0, "samples": parity_results}
        write_new(OUT / "parity-audit.json", parity_audit)
        summary = {"context": list(CONTEXT), "target_rows": target_rows, "target_row_domain_sha256": contract["target_row_domain_sha256"], "domain_counts": actual_counts, "evaluated_total": evaluated_total, "geometry_valid_counts": {f"order{order}_{'valid' if valid else 'invalid'}": count for (order, valid), count in sorted(geometry_valid_counts.items())}, "geometry_fallbacks": geometry_fallbacks, "domain_identity_sha256": domain_hash.hexdigest().upper(), "outcome_sha256": outcome_hash.hexdigest().upper(), "classification_counts": dict(sorted(classification_counts.items())), "confirmed_target_rows": sum(1 for row in row_stats.values() if row["confirmed_valid_target_witnesses"] or row["confirmed_invalid_target_witnesses"]), "confirmed_valid_target_rows": sum(1 for row in row_stats.values() if row["confirmed_valid_target_witnesses"]), "confirmed_invalid_target_rows": sum(1 for row in row_stats.values() if row["confirmed_invalid_target_witnesses"]), "full_replay_candidate_count": len(parity_full_replay_cache), "deterministic_parity_strata": len(parity_results), "parity_audit_sha256": digest(OUT / "parity-audit.json"), "confirmed_witness_count": len(witness_seen)}
        write_new(OUT / "domain-summary.json", summary)
        write_new(OUT / "row-stats.json", {"context": list(CONTEXT), "rows": list(sorted(row_stats.values(), key=lambda item: int(item["row"])))})
        execution = {"protocol": PROTOCOL, "identity": OUT.name, "status": "RESID_INVALID1_R2_COMPLETE", "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "context": list(CONTEXT), "summary": summary, "parent_bindings": bindings, "implementation_bindings": {"runner_sha256": digest(Path(__file__)), "regression_test_sha256": digest(OUT / "tests" / "test_action_mapping_semantics.py"), "plan_sha256": digest(OUT / "PLAN.md")}, "regression_preflight": regression, "domain_summary_sha256": digest(OUT / "domain-summary.json"), "row_stats_sha256": digest(OUT / "row-stats.json"), "parity_audit_sha256": digest(OUT / "parity-audit.json"), "contract_sha256": digest(OUT / "CONTRACT.json"), "conclusion": "Complete frozen order-1/2/3 domain evaluated with baseline-relative canonical action semantics; every reported target witness and every deterministic parity sample passed full replay."}
        write_new(OUT / "execution.json", execution)
        write_new(OUT / "STATUS.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": execution["status"], "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "execution_sha256": digest(OUT / "execution.json")})
        report = "\n".join(["# Q10-RESID-INVALID1-R2", "", f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`.", f"Target rows: `{len(target_rows)}`; evaluated candidates: `{evaluated_total}`.", f"Domain counts: `{json.dumps(actual_counts, sort_keys=True)}`; domain hash matches the frozen identity.", f"Full-replay-confirmed target rows: `{summary['confirmed_target_rows']}` (valid: `{summary['confirmed_valid_target_rows']}`, invalid: `{summary['confirmed_invalid_target_rows']}`).", f"Target witnesses were full-state reconstructed and replayed; deterministic non-hit parity strata passed: `{len(parity_results)}`; mismatches: `0`.", "", "Action prefixes were resolved against frozen baseline bits. The two prior false-positive witnesses are permanent regression fixtures and the legacy semantics reproduced their incorrect bits while the corrected evaluator matched full replay.", "", "This is engineering-only. It does not promote invalid-state target hits into admissible authority. Order 4, GC2, AG1, behavior, and scientific promotion remain closed.", ""])
        write_new(OUT / "REPORT.md", report)
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        for stream in hits.values():
            if not stream.closed:
                stream.close()
        blocked = {"protocol": PROTOCOL, "identity": OUT.name, "status": "BLOCKED_RESID_INVALID1_R2", "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc), "evaluated_total": evaluated_total}
        if not (OUT / "execution.json").exists():
            write_new(OUT / "execution.json", blocked)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
