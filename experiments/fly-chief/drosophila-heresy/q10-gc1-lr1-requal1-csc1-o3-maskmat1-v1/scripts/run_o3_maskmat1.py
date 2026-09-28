from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
FRONT2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3"
FRONT2_SCRIPT = FRONT2 / "scripts" / "run_front2.py"
FRONT2_AUDIT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-audit-v1"
LOCQUAL = EXP / "q10-gc1-lr1-requal1-csc1-o3-locqual1-v1"
FRONT1 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
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


def pack_mask(indices: set[int], width: int) -> bytes:
    result = bytearray((width + 7) // 8)
    for index in indices:
        result[index >> 3] |= 1 << (index & 7)
    return bytes(result)


def load_front2_runtime() -> Any:
    spec = importlib.util.spec_from_file_location("q10_o3_maskmat_front2_runtime", FRONT2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("FRONT2 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.IDENTITY != "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3":
        raise RuntimeError("wrong FRONT2 runtime identity")
    return module


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"), Path("scripts"), Path("scripts/run_o3_maskmat1.py"),
            Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"),
            Path("schema.json"), Path("semantic.jsonl"), Path("semantic.bin"),
            Path("row-stats.json"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    front2_exec_path = FRONT2 / "execution.json"
    front2_audit_path = FRONT2_AUDIT / "execution.json"
    locqual_path = LOCQUAL / "execution.json"
    front1_shard = FRONT1 / "shards" / f"{SLUG}.jsonl"
    source_paths = [front2_exec_path, front2_audit_path, locqual_path, FRONT2_SCRIPT, front1_shard]
    front2_execution = load_json(front2_exec_path)
    front2_context = next(item for item in front2_execution["contexts"] if tuple(item["context"]) == CONTEXT)
    order3_result_ranges = {int(item["start"]): item for item in front2_context["ranges"]}
    front2_source_ranges: list[dict[str, Any]] = []
    exh1_execution = load_json(EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1" / "execution.json")
    exh1_context = next(item for item in exh1_execution["contexts"] if tuple(item["context"]) == CONTEXT)
    for item in exh1_context["ranges"]:
        source = {"start": int(item["start"]), "end": int(item["end"]), "valid_shard": item["valid_shard"]}
        front2_source_ranges.append(source)
        source_paths.append(ROOT / item["valid_shard"])
    for item in front2_context["ranges"]:
        source_paths.append(ROOT / item["result_path"])
    source_before = {str(path): sha256(path) for path in source_paths}
    locqual = load_json(locqual_path)
    if locqual.get("status") != "O3_LOCQUAL1_COMPLETE":
        raise RuntimeError("O3 localized-readout qualification is not complete")
    if int(locqual["localized_audit_records"]) != 1621 or int(locqual["independent_full_replay_samples"]) != 14:
        raise RuntimeError("localized-readout qualification cardinality drift")
    if front2_execution.get("status") != "ALG3_FRONT2_COMPLETE_NO_EXACT":
        raise RuntimeError("FRONT2 is not complete")
    if int(front2_context["evaluated"]) != 225429:
        raise RuntimeError("unexpected target-context frontier size")

    front1_reference = None
    with front1_shard.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                front1_reference = record
                break
    if front1_reference is None:
        raise RuntimeError("order-2 reference record 0 missing")

    alg = load_front2_runtime().load_alg1()
    front2_module = load_front2_runtime()
    context = front2_module.prepare_context(CONTEXT, alg)
    target = tuple(int(value) for value in context["state"].target_readout_bits)
    reference_bits = tuple(int(value) for value in front1_reference["readout_bits"])
    if len(reference_bits) != len(target):
        raise RuntimeError("reference/target readout length mismatch")
    reference_hash = alg.bits_hash(reference_bits)
    if reference_hash != str(front2_context["best"]["readout_sha256"]).upper():
        raise RuntimeError("order-2 reference is not the FRONT2 best readout")
    residual = {index for index, (actual, expected) in enumerate(zip(reference_bits, target)) if actual != expected}
    if len(residual) != 123:
        raise RuntimeError(f"reference residual count changed: {len(residual)}")

    width = len(target)
    mask_bytes = (width + 7) // 8
    residual_indices = sorted(residual)
    semantic_records = []
    row_stats = {
        str(index): {"ever_changed_from_reference": False, "ever_target_exact": False, "changed_count": 0, "target_exact_count": 0}
        for index in residual_indices
    }
    result_count = improved_count = exact_count = parity_count = 0
    with (OUT / "semantic.bin").open("wb") as binary, (OUT / "semantic.jsonl").open("w", encoding="utf-8", newline="\n") as metadata:
        for source_range in sorted(front2_source_ranges, key=lambda item: item["start"]):
            expected_range = order3_result_ranges[source_range["start"]]
            source_path = ROOT / source_range["valid_shard"]
            result_path = ROOT / expected_range["result_path"]
            with source_path.open("r", encoding="utf-8") as source_stream, result_path.open("r", encoding="utf-8") as result_stream:
                for source_line, result_line in zip(source_stream, result_stream):
                    source = json.loads(source_line)
                    expected = json.loads(result_line)
                    if source["action_ordinals"] != expected["action_ordinals"] or source["global_rank"] != expected["global_rank"]:
                        raise RuntimeError("source/result action identity drift")
                    bits, weights = front2_module.construct(context, source)
                    local = front2_module.localized_readout(context, weights, [int(row) for row in source["dependency_rows"]])
                    readout_hash = alg.bits_hash(local)
                    if readout_hash != str(expected["readout_sha256"]).upper():
                        raise RuntimeError(f"localized readout hash drift at rank {source['global_rank']}")
                    score = alg.score_dict(context["pf"], local, target)
                    if score != expected["score"]:
                        raise RuntimeError(f"localized score drift at rank {source['global_rank']}")
                    mismatch = {index for index, (actual, target_value) in enumerate(zip(local, target)) if actual != target_value}
                    changed = {index for index, (actual, reference_value) in enumerate(zip(local, reference_bits)) if actual != reference_value}
                    repaired = residual - mismatch
                    damaged = (set(range(width)) - residual) & mismatch
                    for index in residual:
                        row = row_stats[str(index)]
                        if index in changed:
                            row["ever_changed_from_reference"] = True
                            row["changed_count"] += 1
                        if local[index] == target[index]:
                            row["ever_target_exact"] = True
                            row["target_exact_count"] += 1
                    mismatch_payload = pack_mask(mismatch, width)
                    changed_payload = pack_mask(changed, width)
                    residual_payload = b"".join(struct.pack("<I", int(local[index])) for index in residual_indices)
                    offset = binary.tell()
                    binary.write(mismatch_payload)
                    binary.write(changed_payload)
                    binary.write(residual_payload)
                    record = {
                        "semantic_index": result_count,
                        "binary_offset": offset,
                        "global_rank": int(source["global_rank"]),
                        "local_rank": int(source["local_rank"]),
                        "action_ordinals": [int(value) for value in source["action_ordinals"]],
                        "readout_sha256": readout_hash,
                        "score": score,
                        "mismatch_count": len(mismatch),
                        "repaired_reference_residual_count": len(repaired),
                        "changed_reference_residual_count": len(residual & changed),
                        "damaged_reference_correct_count": len(damaged),
                        "improved_vs_V": bool(expected["improved_vs_V"]),
                    }
                    metadata.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                    result_count += 1
                    improved_count += int(expected["improved_vs_V"])
                    exact_count += int(expected["exact_target_distinct"])
                    parity_count += 1
            if source_range["end"] - source_range["start"] != expected_range["end"] - expected_range["start"]:
                raise RuntimeError("range extent mismatch")

    if result_count != 225429:
        raise RuntimeError(f"materialized record count mismatch: {result_count}")
    source_after = {str(path): sha256(path) for path in source_paths}
    if source_before != source_after:
        raise RuntimeError("source changed during O3-MASKMAT1")
    (OUT / "schema.json").write_text(json.dumps({
        "readout_width": width,
        "mask_bytes": mask_bytes,
        "residual_indices": residual_indices,
        "binary_record_bytes": mask_bytes * 2 + len(residual_indices) * 4,
        "binary_layout": ["mismatch_mask_bytes", "changed_from_reference_mask_bytes", "residual_output_bits_u32_le"],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "row-stats.json").write_text(json.dumps(row_stats, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-O3-MASKMAT1",
        "status": "O3_MASKMAT1_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "replay_executed": True,
        "context": list(CONTEXT),
        "parent_sha256": {str(path): sha256(path) for path in source_paths},
        "reference": {
            "source_frontier_pair_index": 0,
            "readout_sha256": reference_hash,
            "mismatch_count": len(residual),
            "residual_indices": residual_indices,
        },
        "counts": {
            "records": result_count,
            "parity_checked": parity_count,
            "improved_vs_V": improved_count,
            "exact_target_distinct": exact_count,
            "targetable_reference_residual_rows": sum(int(row["ever_target_exact"]) for row in row_stats.values()),
            "movable_reference_residual_rows": sum(int(row["ever_changed_from_reference"]) for row in row_stats.values()),
        },
        "semantic_bin_sha256": sha256(OUT / "semantic.bin"),
        "semantic_jsonl_sha256": sha256(OUT / "semantic.jsonl"),
        "row_stats_sha256": sha256(OUT / "row-stats.json"),
    }
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": OUT.name,
        "status": execution["status"],
        "replay_executed": True,
        "scientific_promotion": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "REPORT.md").write_text(
        "# O3-MASKMAT1\n\n"
        f"Materialized {result_count} exact order-3 semantic records for `R tau4 set3` using the qualified localized readout path. The frozen reference has {len(residual)} residual rows.\n\n"
        f"The artifact stores exact mismatch and changed-from-reference bitsets plus raw output bits for the 123 residual rows. Localized readout parity was checked for all {parity_count} records against the existing FRONT2 hashes and scores.\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"O3_MASKMAT1_FAILED: {exc}", file=sys.stderr)
        raise
