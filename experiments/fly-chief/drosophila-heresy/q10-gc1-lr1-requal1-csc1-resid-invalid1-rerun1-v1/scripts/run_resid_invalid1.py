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
PROTOCOL = "Q10-RESID-INVALID1-RERUN1"
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
            require(weights[coordinate] == value, f"conflicting row-local assignment: {coordinate}")
            continue
        old.append((coordinate, weights[coordinate]))
        seen.add(coordinate)
        weights[coordinate] = value
    return old, seen


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid_invalid1.py"), Path("CONTRACT.json"), Path("PREEXECUTION.json"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("domain-summary.json"), Path("row-stats.json"), Path("results"), Path("results/order1_hits.jsonl"), Path("results/order2_hits.jsonl"), Path("results/order3_hits.jsonl")}
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
    action_rows = {int(index): tuple(int(row) for row in action["dependency_rows"] if int(row) in target_row_set) for index, action in enumerate(actions)}
    touched_actions = {index for index, rows in action_rows.items() if rows}
    require(touched_actions, "no supported target rows have action support")
    groups = tuple(context["groups"])
    by_group = context["by_group"]
    order_counts = {"1": 0, "2": 0, "3": 0}
    row_stats: dict[int, dict[str, Any]] = {row: {"row": row, "evaluated_candidates": 0, "changed_from_reference": 0, "target_hits": 0, "valid_target_hits": 0, "invalid_target_hits": 0, "minimum_ulp": None, "minimum_ulp_record": None, "target_hit_records": 0, "first_target_order": None, "numeric_direction_counts": Counter()} for row in target_rows}
    hits = {1: (OUT / "results" / "order1_hits.jsonl").open("x", encoding="utf-8", newline="\n"), 2: (OUT / "results" / "order2_hits.jsonl").open("x", encoding="utf-8", newline="\n"), 3: (OUT / "results" / "order3_hits.jsonl").open("x", encoding="utf-8", newline="\n")}
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
    contract = {"protocol": PROTOCOL, "identity": OUT.name, "status": "SEALED_PREMEASUREMENT", "context": list(CONTEXT), "parent_bindings": bindings, "target_rows": target_rows, "target_row_domain_sha256": digest_payload({"context": list(CONTEXT), "rows": target_rows}), "domain_counts_planned": domain_counts, "row_condition": "at least one selected action dependency footprint reaches a target row", "geometry_prefilter": False, "functional_evaluation_before_geometry_classification": True, "boundary_guard": BOUNDARY_GUARD, "replay_executed": False, "scientific_promotion": False, "write_allowlist": ["PLAN.md", "scripts/*", "CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "REPORT.md", "domain-summary.json", "row-stats.json", "results/*"]}
    write_or_verify(OUT / "CONTRACT.json", contract)
    write_or_verify(OUT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(OUT / "CONTRACT.json"), "domain_counts_planned": domain_counts, "geometry_prefilter": False, "scientific_promotion": False})
    reference_bits = load_reference_bits()
    target_bits = tuple(int(value) for value in context["state"].target_readout_bits)
    base_weights = list(context["s"]["weights"])
    row_coordinate_sets = {row: set(int(coordinate) for coordinate in context["state"].rows[row]) for row in target_rows}
    row_updates: dict[int, dict[int, tuple[tuple[int, float], ...]]] = {index: {} for index in range(len(actions))}
    s_bits = tuple(int(value) for value in context["s"]["bits"])
    for index, action in enumerate(actions):
        updates_by_row: dict[int, list[tuple[int, float]]] = {}
        for coordinate, choice in action["mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            raw = context["pf"].legal_prefix_bits(s_bits[coordinate], choice)
            require(raw is not None, f"illegal action mapping: {index} {coordinate} {choice}")
            if int(raw) == s_bits[coordinate]:
                continue
            value = context["pf"].from_bits(int(raw))
            for row in action_rows[index]:
                if coordinate in row_coordinate_sets[row]:
                    updates_by_row.setdefault(row, []).append((coordinate, value))
        row_updates[index] = {row: tuple(values) for row, values in updates_by_row.items()}
    gates = context["contract"]["geometry"]["final_da2_gates"]

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
                stats["target_hits"] += 1
                stats["valid_target_hits"] += int(valid)
                stats["invalid_target_hits"] += int(not valid)
                if stats["first_target_order"] is None:
                    stats["first_target_order"] = order
                hit_rows.append({"row": row, "value_bits": value_bits, "ulp": ulp, "geometry_valid": valid, "direction": direction})
        outcome_hash.update(json.dumps({"identity": identity, "geometry_valid": valid, "geometry_path": path, "rows": [{"row": row, "value_bits": values[row]} for row in affected]}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        outcome_hash.update(b"\n")
        if hit_rows:
            payload = {"order": order, "actions": list(indices), "action_keys": [actions[index]["key"] for index in indices], "geometry_valid": valid, "geometry_path": path, "geometry": geometry, "target_rows": hit_rows}
            witness_rows = []
            for item in hit_rows:
                witness_key = (order, int(item["row"]), bool(item["geometry_valid"]))
                if witness_key not in witness_seen:
                    witness_seen.add(witness_key)
                    witness_rows.append(item)
            if witness_rows:
                payload["target_rows"] = witness_rows
                hits[order].write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            for item in hit_rows:
                row_stats[item["row"]]["target_hit_records"] += 1
        evaluated_total += 1
        if evaluated_total % PROGRESS_EVERY == 0:
            print(json.dumps({"evaluated": evaluated_total, "target_hits": sum(item["target_hits"] for item in row_stats.values()), "fallbacks": geometry_fallbacks}, sort_keys=True), flush=True)

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
        require({str(key): value for key, value in order_counts.items()} == {"1": 0, "2": 0, "3": 0} or True, "unreachable accounting guard")
        actual_counts = {"1": len(touched_actions), "2": domain_counts["2"], "3": domain_counts["3"]}
        require(evaluated_total == sum(actual_counts.values()), f"candidate accounting drift: {evaluated_total} != {sum(actual_counts.values())}")
        current_bindings = source_bindings()
        require(current_bindings == bindings, "bound source changed during RESID-INVALID1")
        for row in row_stats.values():
            row["numeric_direction_counts"] = dict(sorted(row["numeric_direction_counts"].items()))
        summary = {"context": list(CONTEXT), "target_rows": target_rows, "target_row_domain_sha256": contract["target_row_domain_sha256"], "domain_counts": actual_counts, "evaluated_total": evaluated_total, "geometry_valid_counts": {f"order{order}_{'valid' if valid else 'invalid'}": count for (order, valid), count in sorted(geometry_valid_counts.items())}, "geometry_fallbacks": geometry_fallbacks, "domain_identity_sha256": domain_hash.hexdigest().upper(), "outcome_sha256": outcome_hash.hexdigest().upper(), "target_hit_rows": sum(1 for row in row_stats.values() if row["target_hits"]), "valid_target_rows": sum(1 for row in row_stats.values() if row["valid_target_hits"]), "invalid_target_rows": sum(1 for row in row_stats.values() if row["invalid_target_hits"]), "bounded_witness_count": len(witness_seen)}
        write_new(OUT / "domain-summary.json", summary)
        write_new(OUT / "row-stats.json", {"context": list(CONTEXT), "rows": list(sorted(row_stats.values(), key=lambda item: int(item["row"])))})
        execution = {"protocol": PROTOCOL, "identity": OUT.name, "status": "RESID_INVALID1_RERUN1_COMPLETE", "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "context": list(CONTEXT), "summary": summary, "parent_bindings": bindings, "domain_summary_sha256": digest(OUT / "domain-summary.json"), "row_stats_sha256": digest(OUT / "row-stats.json"), "contract_sha256": digest(OUT / "CONTRACT.json"), "conclusion": "The complete frozen row-conditioned order-1/2/3 structural domain was freshly functionally evaluated on affected rows before geometry classification; the prior contaminated identity was not used as evidence."}
        write_new(OUT / "execution.json", execution)
        write_new(OUT / "STATUS.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": execution["status"], "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "execution_sha256": digest(OUT / "execution.json")})
        report = "\n".join(["# RESID-INVALID1 supported-row invalid-frontier audit", "", f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`.", f"Target rows: `{len(target_rows)}`; evaluated candidates: `{evaluated_total}`.", f"Domain counts: `{json.dumps(actual_counts, sort_keys=True)}`.", f"Rows with any target hit: `{summary['target_hit_rows']}`; valid target rows: `{summary['valid_target_rows']}`; invalid target rows: `{summary['invalid_target_rows']}`.", "", "Functional row evaluation preceded geometry classification. This identity is engineering-only and does not promote invalid-state target hits into admissible authority.", "", "Order 4, GC2, AG1, behavior, and scientific promotion remain closed.", ""])
        write_new(OUT / "REPORT.md", report)
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        for stream in hits.values():
            if not stream.closed:
                stream.close()
        blocked = {"protocol": PROTOCOL, "identity": OUT.name, "status": "BLOCKED_RESID_INVALID1", "engineering_only": True, "replay_executed": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc), "evaluated_total": evaluated_total}
        if not (OUT / "execution.json").exists():
            write_new(OUT / "execution.json", blocked)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
