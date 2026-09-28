from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
FRONT1 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
FRONT1_SCRIPT = FRONT1 / "scripts" / "run_front1.py"
ALG1_EXEC = EXP / "q10-gc1-lr1-requal1-csc1-alg1-v2" / "execution.json"
SINGLE_EXEC = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1" / "execution.json"
CONTEXT = ("seed9731-R-tau4.json", 3)
SHARD = FRONT1 / "shards" / "seed9731-R-tau4__set3.jsonl"


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
    spec = importlib.util.spec_from_file_location("q10_resid0_front1_runtime", FRONT1_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("current runtime loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.IDENTITY != "q10-gc1-lr1-requal1-csc1-pair-front1-v2":
        raise RuntimeError("unexpected runtime identity")
    alg = module.load_alg1()
    _pf, state, _contract, _s, _metadata, _frontier = module.load_context(CONTEXT, alg)
    return tuple(int(value) for value in state.target_readout_bits)


def mismatch_indices(bits: tuple[int, ...], target: tuple[int, ...]) -> frozenset[int]:
    return frozenset(index for index, (actual, expected) in enumerate(zip(bits, target)) if actual != expected)


def mask_hash(mask: frozenset[int]) -> str:
    return hashlib.sha256(json.dumps(sorted(mask), separators=(",", ":")).encode()).hexdigest().upper()


def hamming_summary(masks: list[frozenset[int]]) -> dict[str, Any]:
    distances: list[int] = []
    for index, left in enumerate(masks):
        for right in masks[index + 1 :]:
            distances.append(len(left.symmetric_difference(right)))
    if not distances:
        return {"pairs": 0, "minimum": 0, "maximum": 0, "mean": 0.0, "median": 0.0}
    return {
        "pairs": len(distances),
        "minimum": min(distances),
        "maximum": max(distances),
        "mean": mean(distances),
        "median": median(distances),
    }


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"),
            Path("scripts"),
            Path("scripts/run_resid0_o2.py"),
            Path("execution.json"),
            Path("STATUS.json"),
            Path("REPORT.md"),
            Path("records.jsonl"),
            Path("row-stats.json"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    source_paths = [FRONT1 / "execution.json", FRONT1_SCRIPT, SHARD, ALG1_EXEC, SINGLE_EXEC]
    source_before = {str(path): sha256(path) for path in source_paths}
    front1_execution = load_json(FRONT1 / "execution.json")
    if front1_execution.get("status") != "PAIR_FRONT1_COMPLETE_NO_EXACT":
        raise RuntimeError("order-2 frontier is not complete")
    target = load_target_bits()

    records: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    with SHARD.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if tuple(record["case"]) != CONTEXT:
                raise RuntimeError(f"wrong context at line {line_number}")
            index = int(record["frontier_pair_index"])
            if index in seen_indices:
                raise RuntimeError(f"duplicate frontier index: {index}")
            seen_indices.add(index)
            bits = tuple(int(value) for value in record["readout_bits"])
            if len(bits) != len(target):
                raise RuntimeError(f"readout length mismatch at index {index}")
            records.append({"source": record, "bits": bits, "score_key": tuple(record["score_key"])})

    if len(records) != 1438:
        raise RuntimeError(f"unexpected order-2 context count: {len(records)}")
    records.sort(key=lambda item: (item["score_key"], int(item["source"]["frontier_pair_index"])))
    reference = records[0]
    reference_bits = reference["bits"]
    residual = mismatch_indices(reference_bits, target)
    if len(residual) != 123:
        raise RuntimeError(f"reference residual count changed: {len(residual)}")

    correct_reference = set(range(len(target))) - set(residual)
    row_stats = {
        str(index): {
            "reference_index": index,
            "ever_changed_from_reference": False,
            "ever_target_exact": False,
            "changed_count": 0,
            "target_exact_count": 0,
        }
        for index in sorted(residual)
    }
    masks: list[frozenset[int]] = []
    record_lines: list[str] = []
    for item in records:
        source = item["source"]
        bits = item["bits"]
        mask = mismatch_indices(bits, target)
        changed = frozenset(index for index, (actual, reference_value) in enumerate(zip(bits, reference_bits)) if actual != reference_value)
        repaired = residual - mask
        damaged = correct_reference & mask
        residual_changed = residual & changed
        for index in residual:
            state = row_stats[str(index)]
            if index in changed:
                state["ever_changed_from_reference"] = True
                state["changed_count"] += 1
            if bits[index] == target[index]:
                state["ever_target_exact"] = True
                state["target_exact_count"] += 1
        masks.append(mask)
        record_lines.append(json.dumps({
            "frontier_pair_index": int(source["frontier_pair_index"]),
            "score_key": list(item["score_key"]),
            "mismatch_count": len(mask),
            "mismatch_mask_sha256": mask_hash(mask),
            "repaired_reference_residual_count": len(repaired),
            "changed_reference_residual_count": len(residual_changed),
            "damaged_reference_correct_count": len(damaged),
            "net_mismatch_delta": len(mask) - len(residual),
        }, sort_keys=True, separators=(",", ":")))

    source_after = {str(path): sha256(path) for path in source_paths}
    if source_before != source_after:
        raise RuntimeError("source changed during RESID0-O2")

    targetable = [int(index) for index, state in row_stats.items() if state["ever_target_exact"]]
    movable = [int(index) for index, state in row_stats.items() if state["ever_changed_from_reference"]]
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID0-O2",
        "status": "RESID0_O2_COMPLETE",
        "engineering_only": True,
        "replay_executed": False,
        "scientific_promotion": False,
        "context": list(CONTEXT),
        "parent_sha256": {str(path): sha256(path) for path in source_paths},
        "target_readout_length": len(target),
        "reference": {
            "frontier_pair_index": int(reference["source"]["frontier_pair_index"]),
            "score_key": list(reference["score_key"]),
            "mismatch_count": len(residual),
            "residual_indices": sorted(residual),
            "readout_sha256": reference["source"]["readout_sha256"],
        },
        "frontier": {
            "records": len(records),
            "unique_mismatch_masks": len({mask_hash(mask) for mask in masks}),
            "targetable_reference_residual_rows": len(targetable),
            "movable_reference_residual_rows": len(movable),
            "never_moved_reference_residual_rows": len(residual) - len(movable),
            "never_targetable_reference_residual_rows": len(residual) - len(targetable),
            "mask_hamming": hamming_summary(masks),
        },
        "row_stats": row_stats,
    }
    (OUT / "records.jsonl").write_text("\n".join(record_lines) + "\n", encoding="utf-8", newline="\n")
    (OUT / "row-stats.json").write_text(json.dumps(row_stats, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": OUT.name,
        "status": execution["status"],
        "replay_executed": False,
        "scientific_promotion": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = [
        "# RESID0-O2 residual audit",
        "",
        "Read-only analysis of the complete order-2 valid frontier for `R tau4 set3`.",
        "",
        f"The frozen reference has {len(residual)} mismatches and score `{list(reference['score_key'])}`.",
        "",
        f"Across {len(records)} valid order-2 states, {len(targetable)} of the 123 residual rows reach their target value at least once, and {len(movable)} change relative to the reference. {len(residual) - len(movable)} never move in this frontier.",
        "",
        f"The frontier contains {len({mask_hash(mask) for mask in masks})} distinct mismatch masks. Pairwise mask Hamming statistics: `{json.dumps(hamming_summary(masks), sort_keys=True)}`.",
        "",
        "This is an order-2 control only. It does not classify order-3 residual authority and does not infer global reachability beyond the selected frontier.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RESID0_O2_FAILED: {exc}", file=sys.stderr)
        raise
