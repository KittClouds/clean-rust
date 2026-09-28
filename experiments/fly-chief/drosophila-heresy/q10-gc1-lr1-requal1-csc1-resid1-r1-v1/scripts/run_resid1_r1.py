from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
SINGLE_SCRIPT = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1" / "scripts" / "run_sreplace_singles.py"
O1 = EXP / "q10-gc1-lr1-requal1-csc1-o1-readmat1-v1"
O2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
O3 = EXP / "q10-gc1-lr1-requal1-csc1-o3-maskmat1-v1"
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_target_bits() -> tuple[int, ...]:
    spec = importlib.util.spec_from_file_location("q10_resid1_current_runtime", SINGLE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("current runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    pf, builder = module.load_modules()
    _, data = builder.fresh_lineage(module.CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == CONTEXT)
    return tuple(int(value) for value in state.target_readout_bits)


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid1_r1.py"),
            Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"),
            Path("row-stats.json"), Path("co-attainment.json"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    o1_exec_path = O1 / "execution.json"
    o1_records_path = O1 / "records.jsonl"
    o2_exec_path = O2 / "execution.json"
    o2_records_path = O2 / "shards" / f"{SLUG}.jsonl"
    o3_exec_path = O3 / "execution.json"
    o3_semantic_path = O3 / "semantic.jsonl"
    o3_bin_path = O3 / "semantic.bin"
    o3_schema_path = O3 / "schema.json"
    source_paths = [o1_exec_path, o1_records_path, o2_exec_path, o2_records_path, o3_exec_path, o3_semantic_path, o3_bin_path, o3_schema_path, SINGLE_SCRIPT]
    before = {str(path): sha256(path) for path in source_paths}
    o1_exec = load_json(o1_exec_path)
    o2_exec = load_json(o2_exec_path)
    o3_exec = load_json(o3_exec_path)
    if o1_exec.get("status") != "O1_READMAT1_COMPLETE":
        raise RuntimeError("O1 materialization is not complete")
    if o2_exec.get("status") != "PAIR_FRONT1_COMPLETE_NO_EXACT":
        raise RuntimeError("order-2 frontier is not complete")
    if o3_exec.get("status") != "O3_MASKMAT1_COMPLETE":
        raise RuntimeError("O3 mask materialization is not complete")
    target = load_target_bits()
    schema = load_json(o3_schema_path)
    width = int(schema["readout_width"])
    residual_indices = [int(value) for value in schema["residual_indices"]]
    residual_set = set(residual_indices)
    if width != len(target) or len(residual_indices) != 123:
        raise RuntimeError("semantic schema does not match current target width")
    reference_bits = None
    with o2_records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                reference_bits = tuple(int(value) for value in record["readout_bits"])
                break
    if reference_bits is None:
        raise RuntimeError("order-2 reference record missing")
    reference_mismatch = {index for index, (actual, expected) in enumerate(zip(reference_bits, target)) if actual != expected}
    if reference_mismatch != residual_set:
        raise RuntimeError("reference residual set does not match O3 schema")

    row_stats = {
        str(index): {
            "reference_index": index,
            "ever_changed_from_reference": False,
            "ever_target_exact": False,
            "first_target_order": None,
            "changed_count_by_order": {"1": 0, "2": 0, "3": 0},
            "target_exact_count_by_order": {"1": 0, "2": 0, "3": 0},
            "best_mismatch_count_when_target": None,
            "minimum_damaged_correct_rows_when_target": None,
        }
        for index in residual_indices
    }
    co_attainment = [[0 for _ in residual_indices] for _ in residual_indices]
    aggregate = {str(order): {"records": 0, "valid": 0, "states_with_target_residual": 0} for order in (1, 2, 3)}

    def consume(order: int, bits: tuple[int, ...], mismatch_count: int, damaged_count: int) -> None:
        key = str(order)
        aggregate[key]["records"] += 1
        aggregate[key]["valid"] += 1
        target_rows = [index for index in residual_indices if bits[index] == target[index]]
        if target_rows:
            aggregate[key]["states_with_target_residual"] += 1
        target_row_set = set(target_rows)
        for left_index, row_index in enumerate(residual_indices):
            row = row_stats[str(row_index)]
            if bits[row_index] != reference_bits[row_index]:
                row["ever_changed_from_reference"] = True
                row["changed_count_by_order"][key] += 1
            if row_index in target_row_set:
                row["ever_target_exact"] = True
                row["target_exact_count_by_order"][key] += 1
                if row["first_target_order"] is None or order < row["first_target_order"]:
                    row["first_target_order"] = order
                best = row["best_mismatch_count_when_target"]
                row["best_mismatch_count_when_target"] = mismatch_count if best is None else min(best, mismatch_count)
                min_damage = row["minimum_damaged_correct_rows_when_target"]
                row["minimum_damaged_correct_rows_when_target"] = damaged_count if min_damage is None else min(min_damage, damaged_count)
            for right_index in range(left_index + 1, len(residual_indices)):
                if row_index in target_row_set and residual_indices[right_index] in target_row_set:
                    co_attainment[left_index][right_index] += 1
                    co_attainment[right_index][left_index] += 1

    with o1_records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if (str(record["endpoint"]), int(record["set_index"])) != CONTEXT or not record["final_geometry_pass"]:
                continue
            bits = tuple(int(value) for value in record["readout_bits"])
            mismatch = {index for index, (actual, expected) in enumerate(zip(bits, target)) if actual != expected}
            damaged = (set(range(width)) - residual_set) & mismatch
            consume(1, bits, len(mismatch), len(damaged))

    with o2_records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            bits = tuple(int(value) for value in record["readout_bits"])
            mismatch = {index for index, (actual, expected) in enumerate(zip(bits, target)) if actual != expected}
            damaged = (set(range(width)) - residual_set) & mismatch
            consume(2, bits, len(mismatch), len(damaged))

    record_bytes = int(schema["binary_record_bytes"])
    mask_bytes = int(schema["mask_bytes"])
    residual_value_bytes = len(residual_indices) * 4
    with o3_semantic_path.open("r", encoding="utf-8") as metadata, o3_bin_path.open("rb") as binary:
        for line in metadata:
            record = json.loads(line)
            offset = int(record["binary_offset"])
            binary.seek(offset)
            payload = binary.read(record_bytes)
            if len(payload) != record_bytes:
                raise RuntimeError("truncated O3 semantic payload")
            mismatch_mask = payload[:mask_bytes]
            changed_mask = payload[mask_bytes:2 * mask_bytes]
            residual_payload = payload[2 * mask_bytes:]
            if len(residual_payload) != residual_value_bytes:
                raise RuntimeError("O3 residual payload width mismatch")
            residual_values = struct.unpack(f"<{len(residual_indices)}I", residual_payload)
            target_rows = []
            changed_rows = set()
            for position, row_index in enumerate(residual_indices):
                if residual_values[position] == target[row_index]:
                    target_rows.append(row_index)
                if changed_mask[row_index >> 3] & (1 << (row_index & 7)):
                    changed_rows.add(row_index)
            mismatch_count = int(record["mismatch_count"])
            damaged_count = int(record["damaged_reference_correct_count"])
            for position, row_index in enumerate(residual_indices):
                if mismatch_mask[row_index >> 3] & (1 << (row_index & 7)):
                    continue
            # The compact payload carries exact residual values and the full
            # mismatch mask; reconstruct a target-comparable residual vector.
            synthetic = list(target)
            for position, row_index in enumerate(residual_indices):
                synthetic[row_index] = residual_values[position]
            consume(3, tuple(synthetic), mismatch_count, damaged_count)

    for row_index, row in row_stats.items():
        if not row["ever_changed_from_reference"]:
            row["classification"] = "NO_EFFECT_AUTHORITY"
        elif not row["ever_target_exact"]:
            row["classification"] = "MOVABLE_NOT_TARGETABLE"
        elif row["best_mismatch_count_when_target"] <= len(residual_set):
            row["classification"] = "TARGETABLE_AND_COMPATIBLE"
        else:
            row["classification"] = "TARGETABLE_WITH_COLLATERAL_LOCK"

    source_after = {str(path): sha256(path) for path in source_paths}
    if before != source_after:
        raise RuntimeError("source changed during RESID1-R1")
    class_counts: dict[str, int] = {}
    first_order_counts: dict[str, int] = {}
    for row in row_stats.values():
        class_counts[row["classification"]] = class_counts.get(row["classification"], 0) + 1
        order = row["first_target_order"]
        first_order_counts[str(order) if order is not None else "never"] = first_order_counts.get(str(order) if order is not None else "never", 0) + 1
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID1-R1",
        "status": "RESID1_R1_COMPLETE",
        "engineering_only": True,
        "replay_executed": False,
        "scientific_promotion": False,
        "context": list(CONTEXT),
        "parent_sha256": {str(path): sha256(path) for path in source_paths},
        "reference_mismatch_count": len(residual_set),
        "orders": aggregate,
        "classification_counts": class_counts,
        "first_target_order_counts": first_order_counts,
        "co_attainment_nonzero_pairs": sum(1 for i in range(len(residual_indices)) for j in range(i + 1, len(residual_indices)) if co_attainment[i][j] > 0),
        "co_attainment_max": max(max(row) for row in co_attainment),
        "row_stats_sha256": None,
        "co_attainment_sha256": None,
    }
    (OUT / "row-stats.json").write_text(json.dumps(row_stats, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "co-attainment.json").write_text(json.dumps({"residual_indices": residual_indices, "matrix": co_attainment}, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    execution["row_stats_sha256"] = sha256(OUT / "row-stats.json")
    execution["co_attainment_sha256"] = sha256(OUT / "co-attainment.json")
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": OUT.name,
        "status": execution["status"],
        "replay_executed": False,
        "scientific_promotion": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = [
        "# RESID1-R1 residual authority audit",
        "",
        "Read-only row-level analysis of the 123 residual rows in `R tau4 set3`.",
        "",
        f"Classification counts: `{json.dumps(class_counts, sort_keys=True)}`.",
        f"First targetable order counts: `{json.dumps(first_order_counts, sort_keys=True)}`.",
        "",
        f"The co-attainment matrix has {execution['co_attainment_nonzero_pairs']} nonzero off-diagonal pairs; maximum co-attainment count is {execution['co_attainment_max']}.",
        "",
        "This is engineering evidence about the tested valid frontiers. It does not establish biological mechanism or open order 4.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RESID1_R1_FAILED: {exc}", file=sys.stderr)
        raise
