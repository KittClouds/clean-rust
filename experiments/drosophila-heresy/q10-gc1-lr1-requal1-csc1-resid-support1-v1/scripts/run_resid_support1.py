from __future__ import annotations

import hashlib
import importlib.util
import json
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


def load_reference_bits() -> tuple[int, ...]:
    path = O2 / "shards" / f"{SLUG}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                return tuple(int(value) for value in record["readout_bits"])
    raise RuntimeError("order-2 reference frontier record missing")


def main() -> None:
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid_support1.py"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("row-stats.json"), Path("support-summary.json")}
    if OUT.exists():
        unexpected = {path.relative_to(OUT) for path in OUT.rglob("*")} - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output paths: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    front2 = load_module(FRONT2_SCRIPT, "q10_resid_support_front2_runtime")
    alg = front2.load_alg1()
    context = front2.prepare_context(CONTEXT, alg)
    state = context["state"]
    reference_bits = load_reference_bits()
    target_bits = tuple(int(value) for value in state.target_readout_bits)
    action_rows = {int(ordinal): tuple(int(row) for row in rows) for ordinal, rows in context["action_rows"].items()}
    action_keys = {int(ordinal): str(row["action_key"]) for ordinal, row in context["actions"].items()}
    residual_indices = [index for index, (actual, target) in enumerate(zip(reference_bits, target_bits)) if actual != target]
    if len(residual_indices) != 123:
        raise RuntimeError(f"reference residual count changed: {len(residual_indices)}")

    o1_records = O1 / "records.jsonl"
    r1_rows = load_json(R1 / "row-stats.json")
    source_paths = [o1_records, O1 / "execution.json", R1 / "row-stats.json", R1 / "execution.json", O2 / "execution.json", O2 / "shards" / f"{SLUG}.jsonl", O3 / "execution.json", O3 / "schema.json", O3 / "semantic.jsonl", SINGLE_SCRIPT, FRONT2_SCRIPT]
    before = {str(path): digest(path) for path in source_paths}

    action_stats = {row: {"dependency_action_count": 0, "singleton_changed_count": 0, "singleton_target_count": 0, "singleton_valid_changed_count": 0, "singleton_valid_target_count": 0} for row in residual_indices}
    for ordinal, rows in action_rows.items():
        for row in rows:
            if row in action_stats:
                action_stats[row]["dependency_action_count"] += 1

    singleton_records = 0
    singleton_context_records = 0
    with o1_records.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            singleton_records += 1
            if (str(record["endpoint"]), int(record["set_index"])) != CONTEXT:
                continue
            singleton_context_records += 1
            bits = tuple(int(value) for value in record["readout_bits"])
            valid = bool(record["final_geometry_pass"])
            key = f"{int(record['group'])}:{record['to']}"
            if key not in set(action_keys.values()):
                raise RuntimeError(f"singleton action identity absent from descriptor: {key}")
            for row in residual_indices:
                changed = bits[row] != reference_bits[row]
                target = bits[row] == target_bits[row]
                stats = action_stats[row]
                stats["singleton_changed_count"] += int(changed)
                stats["singleton_target_count"] += int(target)
                stats["singleton_valid_changed_count"] += int(valid and changed)
                stats["singleton_valid_target_count"] += int(valid and target)

    if singleton_context_records != len(action_rows):
        raise RuntimeError(f"singleton context cardinality drift: {singleton_context_records} != {len(action_rows)}")

    rows_out = []
    class_counts: Counter[str] = Counter()
    for row in residual_indices:
        stats = action_stats[row]
        r1 = r1_rows[str(row)]
        if stats["dependency_action_count"] == 0:
            classification = "NO_PRIMITIVE_DEPENDENCY_SUPPORT"
        elif stats["singleton_changed_count"] == 0:
            classification = "SUPPORTED_SINGLETON_SILENT"
        elif not bool(r1["ever_changed_from_reference"]):
            classification = "AUTHORITY_PRESENT_OUTSIDE_VALID_FRONTIER"
        else:
            classification = "VALID_FRONTIER_AUTHORITY_OBSERVED"
        class_counts[classification] += 1
        rows_out.append({
            "row": row,
            "resid1_classification": r1["classification"],
            "dependency_action_count": stats["dependency_action_count"],
            "singleton_changed_count": stats["singleton_changed_count"],
            "singleton_target_count": stats["singleton_target_count"],
            "singleton_valid_changed_count": stats["singleton_valid_changed_count"],
            "singleton_valid_target_count": stats["singleton_valid_target_count"],
            "valid_frontier_changed": bool(r1["ever_changed_from_reference"]),
            "valid_frontier_targetable": bool(r1["ever_target_exact"]),
            "support_classification": classification,
        })

    after = {str(path): digest(path) for path in source_paths}
    if before != after:
        raise RuntimeError("source changed during RESID-SUPPORT1")

    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID-SUPPORT1",
        "status": "RESID_SUPPORT1_COMPLETE",
        "context": list(CONTEXT),
        "replay_executed": False,
        "scientific_promotion": False,
        "reference_residual_rows": len(residual_indices),
        "singleton_records_total": singleton_records,
        "singleton_records_context": singleton_context_records,
        "primitive_action_count": len(action_rows),
        "support_class_counts": dict(sorted(class_counts.items())),
        "parent_sha256": before,
        "row_stats_sha256": None,
        "support_summary_sha256": None,
    }
    row_payload = json.dumps({"context": list(CONTEXT), "rows": rows_out}, indent=2, sort_keys=True) + "\n"
    summary_payload = json.dumps({"context": list(CONTEXT), "action_rows": {str(k): list(v) for k, v in action_rows.items()}, "action_keys": action_keys}, indent=2, sort_keys=True) + "\n"
    (OUT / "row-stats.json").write_text(row_payload, encoding="utf-8", newline="\n")
    (OUT / "support-summary.json").write_text(summary_payload, encoding="utf-8", newline="\n")
    execution["row_stats_sha256"] = digest(OUT / "row-stats.json")
    execution["support_summary_sha256"] = digest(OUT / "support-summary.json")
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({"identity": OUT.name, "status": execution["status"], "replay_executed": False, "scientific_promotion": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = "\n".join([
        "# RESID-SUPPORT1 primitive-support decomposition",
        "",
        f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`; residual rows: `{len(residual_indices)}`; singleton actions: `{len(action_rows)}`.",
        f"Support classifications: `{json.dumps(dict(sorted(class_counts.items())), sort_keys=True)}`.",
        "",
        "The audit is read-only. Authority observed only in invalid singleton states is not promoted to geometry-excluded authority without targeted invalid compound readout evidence.",
        "",
        "Order 4, GC2, AG1, behavior, and scientific promotion remain closed.",
        "",
    ])
    (OUT / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
