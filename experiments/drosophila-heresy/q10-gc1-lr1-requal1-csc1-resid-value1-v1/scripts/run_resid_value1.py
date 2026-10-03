from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "experiments" / "drosophila-heresy"
OUT = Path(__file__).resolve().parents[1]
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"
SINGLE_SCRIPT = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1" / "scripts" / "run_sreplace_singles.py"
FRONT2_SCRIPT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3" / "scripts" / "run_front2.py"
O1 = EXP / "q10-gc1-lr1-requal1-csc1-o1-readmat1-v1"
O2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
O3 = EXP / "q10-gc1-lr1-requal1-csc1-o3-maskmat1-v1"
R1 = EXP / "q10-gc1-lr1-requal1-csc1-resid1-r1-v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module load failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def reference_bits() -> tuple[int, ...]:
    path = O2 / "shards" / f"{SLUG}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                return tuple(int(value) for value in record["readout_bits"])
    raise RuntimeError("order-2 reference record missing")


def ulp(pf: Any, actual: int, target: int) -> int:
    return int(pf.ulp_distance(pf.from_bits(int(actual)), pf.from_bits(int(target))))


def main() -> None:
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid_value1.py"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("row-stats.json")}
    if OUT.exists():
        unexpected = {path.relative_to(OUT) for path in OUT.rglob("*")} - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output paths: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    front2 = load_module(FRONT2_SCRIPT, "q10_resid_value_front2_runtime")
    alg = front2.load_alg1()
    pf, _ = alg.load_modules()
    context = front2.prepare_context(CONTEXT, alg)
    target = tuple(int(value) for value in context["state"].target_readout_bits)
    reference = reference_bits()
    residual_indices = [index for index, (actual, expected) in enumerate(zip(reference, target)) if actual != expected]
    r1 = load_json(R1 / "row-stats.json")
    target_rows = [int(row) for row, value in r1.items() if value["classification"] == "MOVABLE_NOT_TARGETABLE"]
    if len(target_rows) != 29:
        raise RuntimeError(f"MOVABLE_NOT_TARGETABLE cardinality drift: {len(target_rows)}")

    o1_records = O1 / "records.jsonl"
    o2_records = O2 / "shards" / f"{SLUG}.jsonl"
    o3_metadata = O3 / "semantic.jsonl"
    o3_binary = O3 / "semantic.bin"
    schema_path = O3 / "schema.json"
    source_paths = [o1_records, O1 / "execution.json", o2_records, O2 / "execution.json", O3 / "execution.json", schema_path, o3_metadata, o3_binary, R1 / "row-stats.json", R1 / "execution.json", SINGLE_SCRIPT, FRONT2_SCRIPT]
    before = {str(path): digest(path) for path in source_paths}
    schema = load_json(schema_path)
    schema_rows = [int(row) for row in schema["residual_indices"]]
    if schema_rows != residual_indices:
        raise RuntimeError("O3 residual schema does not match current reference")
    row_values: dict[int, dict[int, set[int]]] = {row: {1: set(), 2: set(), 3: set()} for row in target_rows}
    valid_counts = Counter()
    with o1_records.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if (str(record["endpoint"]), int(record["set_index"])) != CONTEXT or not bool(record["final_geometry_pass"]):
                continue
            valid_counts[1] += 1
            bits = tuple(int(value) for value in record["readout_bits"])
            for row in target_rows:
                row_values[row][1].add(bits[row])

    with o2_records.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            valid_counts[2] += 1
            bits = tuple(int(value) for value in record["readout_bits"])
            for row in target_rows:
                row_values[row][2].add(bits[row])

    record_bytes = int(schema["binary_record_bytes"])
    mask_bytes = int(schema["mask_bytes"])
    residual_value_bytes = len(residual_indices) * 4
    with o3_metadata.open("r", encoding="utf-8") as metadata, o3_binary.open("rb") as binary:
        for line in metadata:
            record = json.loads(line)
            valid_counts[3] += 1
            binary.seek(int(record["binary_offset"]) + 2 * mask_bytes)
            payload = binary.read(residual_value_bytes)
            if len(payload) != residual_value_bytes:
                raise RuntimeError("truncated O3 residual payload")
            values = struct.unpack(f"<{len(residual_indices)}I", payload)
            by_row = dict(zip(residual_indices, values))
            for row in target_rows:
                row_values[row][3].add(int(by_row[row]))

    rows_out = []
    pattern_counts: Counter[str] = Counter()
    for row in target_rows:
        target_bit = target[row]
        baseline_bit = reference[row]
        all_values = set().union(*(row_values[row][order] for order in (1, 2, 3)))
        changed_values = all_values - {baseline_bit}
        toward = set()
        away = set()
        equal_distance = set()
        for value in changed_values:
            actual_distance = ulp(pf, value, target_bit)
            baseline_distance = ulp(pf, baseline_bit, target_bit)
            if actual_distance < baseline_distance:
                toward.add(value)
            elif actual_distance > baseline_distance:
                away.add(value)
            else:
                equal_distance.add(value)
        target_hit = target_bit in all_values
        if toward and not away:
            pattern = "TOWARD_ONLY_NO_HIT" if not target_hit else "TOWARD_ONLY"
        elif away and not toward:
            pattern = "AWAY_ONLY"
        elif toward and away:
            pattern = "MIXED_DISTANCE"
        else:
            pattern = "DISTANCE_PLATEAU"
        baseline_value = float(pf.from_bits(baseline_bit))
        target_value = float(pf.from_bits(target_bit))
        below = {value for value in changed_values if float(pf.from_bits(value)) < target_value}
        above = {value for value in changed_values if float(pf.from_bits(value)) > target_value}
        if below and above:
            numeric_side = "TWO_SIDED_NUMERIC"
        elif below or above:
            numeric_side = "ONE_SIDED_NUMERIC"
        else:
            numeric_side = "NUMERIC_SIDE_UNDEFINED"
        first_order: dict[str, int | None] = {}
        for value in sorted(all_values):
            first_order[str(value)] = next((order for order in (1, 2, 3) if value in row_values[row][order]), None)
        min_value = min(all_values, key=lambda value: (ulp(pf, value, target_bit), value))
        rows_out.append({
            "row": row,
            "baseline_bits": baseline_bit,
            "target_bits": target_bit,
            "baseline_value": baseline_value,
            "target_value": target_value,
            "distinct_values_total": len(all_values),
            "distinct_changed_values": len(changed_values),
            "values_by_order": {str(order): sorted(values) for order, values in row_values[row].items()},
            "first_order_by_value": first_order,
            "target_hit": target_hit,
            "minimum_ulp_to_target": ulp(pf, min_value, target_bit),
            "closest_value_bits": min_value,
            "toward_value_count": len(toward),
            "away_value_count": len(away),
            "equal_distance_value_count": len(equal_distance),
            "distance_pattern": pattern,
            "numeric_side_pattern": numeric_side,
        })
        pattern_counts[pattern] += 1

    after = {str(path): digest(path) for path in source_paths}
    if before != after:
        raise RuntimeError("source changed during RESID-VALUE1")
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID-VALUE1",
        "status": "RESID_VALUE1_COMPLETE",
        "context": list(CONTEXT),
        "replay_executed": False,
        "scientific_promotion": False,
        "target_rows": len(target_rows),
        "valid_records_by_order": dict(sorted(valid_counts.items())),
        "pattern_counts": dict(sorted(pattern_counts.items())),
        "parent_sha256": before,
        "row_stats_sha256": None,
    }
    payload = json.dumps({"context": list(CONTEXT), "rows": rows_out}, indent=2, sort_keys=True) + "\n"
    (OUT / "row-stats.json").write_text(payload, encoding="utf-8", newline="\n")
    execution["row_stats_sha256"] = digest(OUT / "row-stats.json")
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({"identity": OUT.name, "status": execution["status"], "replay_executed": False, "scientific_promotion": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = "\n".join([
        "# RESID-VALUE1 reachable-value audit",
        "",
        f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`; analyzed `{len(target_rows)}` movable-but-never-targetable residual rows.",
        f"Valid frontier records: `{json.dumps(dict(sorted(valid_counts.items())), sort_keys=True)}`.",
        f"Distance patterns: `{json.dumps(dict(sorted(pattern_counts.items())), sort_keys=True)}`.",
        "",
        "This is read-only engineering evidence. It does not open order 4 or scientific promotion.",
        "",
    ])
    (OUT / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
