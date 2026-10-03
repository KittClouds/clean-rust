from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "experiments" / "drosophila-heresy"
OUT = Path(__file__).resolve().parents[1]
SINGLE = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1"
ORDER2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
ORDER3 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3"
ORDER3_AUDIT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-audit-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def inspect_array_shard(path: Path) -> tuple[int, int, int]:
    records = load_json(path)
    if not isinstance(records, list):
        raise RuntimeError(f"expected JSON array: {path}")
    bits = sum(isinstance(record, dict) and "readout_bits" in record for record in records)
    hashes = sum(isinstance(record, dict) and "readout_sha256" in record for record in records)
    return len(records), bits, hashes


def inspect_jsonl(path: Path) -> tuple[int, int, int]:
    records = bits = hashes = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise RuntimeError(f"non-object at {path}:{line_number}")
            records += 1
            bits += int("readout_bits" in record)
            hashes += int("readout_sha256" in record)
    return records, bits, hashes


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"),
            Path("scripts"),
            Path("scripts/audit_readout_coverage.py"),
            Path("execution.json"),
            Path("STATUS.json"),
            Path("REPORT.md"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    parent_execs = [
        SINGLE / "execution.json",
        ORDER2 / "execution.json",
        ORDER3 / "execution.json",
        ORDER3_AUDIT / "execution.json",
    ]
    for path in parent_execs:
        if not path.exists():
            raise RuntimeError(f"missing parent: {path}")

    source_paths = list(parent_execs)
    singleton_rows = singleton_bits = singleton_hashes = 0
    for path in sorted((SINGLE / "shards").glob("*.jsonl")):
        source_paths.append(path)
        rows, bits, hashes = inspect_array_shard(path)
        singleton_rows += rows
        singleton_bits += bits
        singleton_hashes += hashes

    order2_rows = order2_bits = order2_hashes = 0
    for path in sorted((ORDER2 / "shards").glob("*.jsonl")):
        source_paths.append(path)
        rows, bits, hashes = inspect_jsonl(path)
        order2_rows += rows
        order2_bits += bits
        order2_hashes += hashes

    order3_rows = order3_bits = order3_hashes = 0
    for path in sorted((ORDER3 / "results").rglob("*.jsonl")):
        source_paths.append(path)
        rows, bits, hashes = inspect_jsonl(path)
        order3_rows += rows
        order3_bits += bits
        order3_hashes += hashes

    before = {str(path): sha256(path) for path in source_paths}
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID1-COVERAGE",
        "status": "RESID1_BLOCKED_READOUT_VECTOR_COVERAGE",
        "engineering_only": True,
        "replay_executed": False,
        "scientific_promotion": False,
        "parent_execution_sha256": {str(path): sha256(path) for path in parent_execs},
        "coverage": {
            "order1": {
                "records": singleton_rows,
                "records_with_readout_bits": singleton_bits,
                "records_with_readout_sha256": singleton_hashes,
            },
            "order2": {
                "records": order2_rows,
                "records_with_readout_bits": order2_bits,
                "records_with_readout_sha256": order2_hashes,
            },
            "order3": {
                "records": order3_rows,
                "records_with_readout_bits": order3_bits,
                "records_with_readout_sha256": order3_hashes,
            },
        },
        "conclusion": {
            "order1_row_level_residual_analysis": "BLOCKED",
            "order2_row_level_residual_analysis": "AVAILABLE",
            "order3_row_level_residual_analysis": "BLOCKED",
            "reason": "order1 and order3 retain readout hashes but not complete readout vectors",
        },
    }

    after = {str(path): sha256(path) for path in source_paths}
    if before != after:
        raise RuntimeError("source file changed during coverage audit")

    with (OUT / "execution.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(execution, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (OUT / "STATUS.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump({
            "identity": OUT.name,
            "status": execution["status"],
            "replay_executed": False,
            "scientific_promotion": False,
        }, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (OUT / "REPORT.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# RESID1 readout coverage audit\n\n")
        handle.write("This was a read-only receipt audit. No replay or residual interpretation was performed.\n\n")
        handle.write("| Order | Records | Full `readout_bits` | `readout_sha256` | Residual row analysis |\n")
        handle.write("|---:|---:|---:|---:|---|\n")
        for order in (1, 2, 3):
            row = execution["coverage"][f"order{order}"]
            availability = execution["conclusion"][f"order{order}_row_level_residual_analysis"].title()
            handle.write(f"| {order} | {row['records']} | {row['records_with_readout_bits']} | {row['records_with_readout_sha256']} | {availability} |\n")
        handle.write("\nOrder-3 residual reachability and near-frontier mismatch-mask audits are blocked by receipt coverage. A readout hash identifies a vector but does not reveal its row-level mismatch mask. Producing missing vectors requires a separately sealed materialization or replay identity.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"READOUT_COVERAGE_FAILED: {exc}", file=sys.stderr)
        raise
