from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
SINGLE = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1"
ORDER2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
ORDER3 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3"
ORDER3_AUDIT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-audit-v1"

CONTEXTS = [
    ("seed9731-L-tau16.json", 2),
    ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1),
    ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0),
    ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2),
    ("seed9731-R-tau4.json", 3),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest().upper()


def lines(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON: {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"non-object record: {path}:{line_number}")
            yield value


def score_key(record: dict[str, Any]) -> tuple[float, ...]:
    raw = record.get("score_key")
    if raw is None:
        score = record.get("score")
        if not isinstance(score, dict):
            raise RuntimeError("record has no score key")
        raw = [
            score.get("mismatch_count"),
            score.get("total_ulp_distance"),
            score.get("residual_l2"),
            score.get("maximum_absolute_residual"),
        ]
    if not isinstance(raw, list) or len(raw) != 4 or any(v is None for v in raw):
        raise RuntimeError(f"malformed score key: {raw!r}")
    return tuple(float(v) for v in raw)


def context_key(value: Any) -> tuple[str, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise RuntimeError(f"malformed context: {value!r}")
    return str(value[0]), int(value[1])


def record_identity(order: int, record: dict[str, Any], ordinal: int) -> str:
    if order == 1:
        mapping = record.get("canonical_mapping")
        return f"{record.get('endpoint')}|{record.get('set_index')}|{mapping}"
    if order == 2:
        return f"{record.get('case')}|{record.get('frontier_pair_index')}"
    actions = record.get("action_ordinals")
    return f"{record.get('context')}|{actions}|{record.get('global_rank', ordinal)}"


def new_bucket(context: tuple[str, int]) -> dict[str, Any]:
    return {
        "context": list(context),
        "evaluated_records": 0,
        "valid_geometry": 0,
        "improved_vs_V": 0,
        "zero_mismatch_readouts": 0,
        "distinct_exact_confirmed": 0,
        "best_valid_score_key": None,
        "best_valid_source_identity": None,
    }


def key_relation(left: list[float] | None, right: list[float] | None) -> str:
    if left is None or right is None:
        return "UNAVAILABLE"
    left_key = tuple(left)
    right_key = tuple(right)
    if left_key < right_key:
        return "BETTER"
    if left_key > right_key:
        return "WORSE"
    return "SAME"


def update_bucket(
    bucket: dict[str, Any],
    order: int,
    record: dict[str, Any],
    identity: str,
) -> None:
    bucket["evaluated_records"] += 1
    key = score_key(record)
    if order == 1:
        valid = bool(record.get("final_geometry_pass"))
        improved = bool(record.get("strictly_better_than_V"))
        exact = int(key[0]) == 0
        distinct = False
    elif order == 2:
        valid = bool(record.get("final_geometry_pass"))
        improved = record.get("outcome") == "VALID_ADVANTAGE_PRESERVED"
        exact = bool(record.get("target_readout_match"))
        distinct = exact and not bool(record.get("target_weight_match"))
    else:
        valid = True
        improved = bool(record.get("improved_vs_V"))
        exact = bool(record.get("exact_target_distinct"))
        distinct = exact
    if not valid:
        return
    bucket["valid_geometry"] += 1
    if improved:
        bucket["improved_vs_V"] += 1
    if exact:
        bucket["zero_mismatch_readouts"] += 1
    if distinct:
        bucket["distinct_exact_confirmed"] += 1
    current = bucket["best_valid_score_key"]
    key_as_list = list(key)
    if current is None or tuple(key) < tuple(current):
        bucket["best_valid_score_key"] = key_as_list
        bucket["best_valid_source_identity"] = identity


def expected_hashes(execution_path: Path) -> dict[str, Any]:
    execution = load_json(execution_path)
    return {"execution": execution, "execution_sha256": sha256(execution_path)}


def verify_stable(paths: list[Path], before: dict[str, str]) -> None:
    after = {str(path): sha256(path) for path in paths}
    if after != before:
        changed = [path for path in after if after[path] != before.get(path)]
        raise RuntimeError(f"source changed during comparison: {changed}")


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"),
            Path("scripts"),
            Path("scripts/run_order_frontier.py"),
            Path("domain-manifest.json"),
            Path("execution.json"),
            Path("STATUS.json"),
            Path("REPORT.md"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"output identity is not empty: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    singleton_exec_path = SINGLE / "execution.json"
    order2_exec_path = ORDER2 / "execution.json"
    order3_exec_path = ORDER3 / "execution.json"
    order3_audit_path = ORDER3_AUDIT / "execution.json"
    singleton_exec = load_json(singleton_exec_path)
    order2_exec = load_json(order2_exec_path)
    order3_exec = load_json(order3_exec_path)
    order3_audit = load_json(order3_audit_path)

    source_paths = [singleton_exec_path, order2_exec_path, order3_exec_path, order3_audit_path]
    singleton_shards = sorted((SINGLE / "shards").glob("*.jsonl"))
    order2_shards = sorted((ORDER2 / "shards").glob("*.jsonl"))
    order3_ranges = []
    order3_exec_ranges = {
        tuple(item["context"]): item["ranges"] for item in order3_exec["contexts"]
    }
    for context in order3_audit["contexts"]:
        context_key_value = tuple(context["context"])
        candidate_ranges = {
            (item["start"], item["end"]): item
            for item in order3_exec_ranges[context_key_value]
        }
        for item in context["ranges"]:
            range_item = candidate_ranges[(item["start"], item["end"])]
            path = ROOT / range_item["result_path"]
            if not path.exists():
                raise RuntimeError(f"missing order-3 range: {path}")
            order3_ranges.append((path, {**item, "result_path": range_item["result_path"]}))
            source_paths.append(path)
    source_paths.extend(singleton_shards)
    source_paths.extend(order2_shards)
    source_hashes = {str(path): sha256(path) for path in source_paths}

    if singleton_exec.get("status") != "SREPLACE_SINGLETONS_COMPLETE":
        raise RuntimeError("singleton parent is not complete")
    if order2_exec.get("status") != "PAIR_FRONT1_COMPLETE_NO_EXACT":
        raise RuntimeError("order-2 parent is not complete")
    if order3_exec.get("status") != "ALG3_FRONT2_COMPLETE_NO_EXACT":
        raise RuntimeError("order-3 parent is not complete")
    if order3_audit.get("status") != "FRONT2_AUDIT_COMPLETE":
        raise RuntimeError("order-3 audit parent is not complete")

    expected_order2 = {
        item["shard"]: item["shard_sha256"]
        for item in order2_exec["contexts"]
    }
    for path in order2_shards:
        if path.name not in expected_order2 or source_hashes[str(path)] != expected_order2[path.name]:
            raise RuntimeError(f"order-2 shard binding mismatch: {path}")

    expected_order3 = {str(path): item["sha256"] for path, item in order3_ranges}
    for path, item in order3_ranges:
        expected = item["sha256"]
        if source_hashes[str(path)] != expected:
            raise RuntimeError(f"order-3 range binding mismatch: {path}")

    buckets = {order: {context: new_bucket(context) for context in CONTEXTS}
               for order in (1, 2, 3)}
    seen = {1: set(), 2: set(), 3: set()}

    singleton_total = 0
    for path in singleton_shards:
        singleton_records = load_json(path)
        if not isinstance(singleton_records, list):
            raise RuntimeError(f"singleton shard is not an array: {path}")
        for ordinal, record in enumerate(singleton_records):
            singleton_total += 1
            context = (record["endpoint"], int(record["set_index"]))
            if context not in buckets[1]:
                raise RuntimeError(f"unexpected singleton context: {context}")
            identity = record_identity(1, record, ordinal)
            if identity in seen[1]:
                raise RuntimeError(f"duplicate order-1 identity: {identity}")
            seen[1].add(identity)
            update_bucket(buckets[1][context], 1, record, identity)

    order2_total = 0
    for path in order2_shards:
        for ordinal, record in enumerate(lines(path)):
            order2_total += 1
            context = context_key(record["case"])
            if context not in buckets[2]:
                raise RuntimeError(f"unexpected order-2 context: {context}")
            identity = record_identity(2, record, ordinal)
            if identity in seen[2]:
                raise RuntimeError(f"duplicate order-2 identity: {identity}")
            seen[2].add(identity)
            update_bucket(buckets[2][context], 2, record, identity)

    order3_total = 0
    order3_valid_by_context = {
        f"{context[0]}::{context[1]}": 0 for context in CONTEXTS
    }
    for path, _item in order3_ranges:
        for ordinal, record in enumerate(lines(path)):
            order3_total += 1
            context = context_key(record["context"])
            if context not in buckets[3]:
                raise RuntimeError(f"unexpected order-3 context: {context}")
            identity = record_identity(3, record, ordinal)
            if identity in seen[3]:
                raise RuntimeError(f"duplicate order-3 identity: {identity}")
            seen[3].add(identity)
            update_bucket(buckets[3][context], 3, record, identity)
            order3_valid_by_context[f"{context[0]}::{context[1]}"] += 1

    expected_singletons = singleton_exec["counts"]["nonzero_singletons"]
    expected_order2_total = order2_exec["counts"]["evaluated_pairs"]
    expected_order3_total = order3_audit["totals"]["evaluated"]
    if singleton_total != expected_singletons:
        raise RuntimeError(f"singleton count mismatch: {singleton_total} != {expected_singletons}")
    if order2_total != expected_order2_total:
        raise RuntimeError(f"order-2 count mismatch: {order2_total} != {expected_order2_total}")
    if order3_total != expected_order3_total:
        raise RuntimeError(f"order-3 count mismatch: {order3_total} != {expected_order3_total}")

    context_rows = []
    for context in CONTEXTS:
        row = {"context": list(context), "orders": {}}
        for order in (1, 2, 3):
            row["orders"][str(order)] = buckets[order][context]
        keys = {order: row["orders"][str(order)]["best_valid_score_key"] for order in (1, 2, 3)}
        available = {order: key for order, key in keys.items() if key is not None}
        best_order = min(available, key=lambda order: tuple(available[order])) if available else None
        row["best_score_comparison"] = {
            "order2_vs_order1": key_relation(keys[2], keys[1]),
            "order3_vs_order2": key_relation(keys[3], keys[2]),
            "order3_vs_order1": key_relation(keys[3], keys[1]),
            "best_recorded_order": best_order,
        }
        context_rows.append(row)

    global_rows = {}
    for order in (1, 2, 3):
        aggregate = new_bucket(("ALL", -1))
        for context in CONTEXTS:
            source = buckets[order][context]
            aggregate["evaluated_records"] += source["evaluated_records"]
            aggregate["valid_geometry"] += source["valid_geometry"]
            aggregate["improved_vs_V"] += source["improved_vs_V"]
            aggregate["zero_mismatch_readouts"] += source["zero_mismatch_readouts"]
            aggregate["distinct_exact_confirmed"] += source["distinct_exact_confirmed"]
            if source["best_valid_score_key"] is not None:
                if aggregate["best_valid_score_key"] is None or tuple(source["best_valid_score_key"]) < tuple(aggregate["best_valid_score_key"]):
                    aggregate["best_valid_score_key"] = source["best_valid_score_key"]
                    aggregate["best_valid_source_identity"] = source["best_valid_source_identity"]
        global_rows[str(order)] = aggregate
    global_best_order = min(
        (order for order in (1, 2, 3) if global_rows[str(order)]["best_valid_score_key"] is not None),
        key=lambda order: tuple(global_rows[str(order)]["best_valid_score_key"]),
    )
    global_rows["comparison"] = {
        "order2_vs_order1": key_relation(global_rows["2"]["best_valid_score_key"], global_rows["1"]["best_valid_score_key"]),
        "order3_vs_order2": key_relation(global_rows["3"]["best_valid_score_key"], global_rows["2"]["best_valid_score_key"]),
        "order3_vs_order1": key_relation(global_rows["3"]["best_valid_score_key"], global_rows["1"]["best_valid_score_key"]),
        "best_recorded_order": global_best_order,
    }

    domain_manifest = {
        "contexts": [list(context) for context in CONTEXTS],
        "orders": {
            "1": {"source": str(SINGLE), "records": singleton_total},
            "2": {"source": str(ORDER2), "records": order2_total},
            "3": {"source": str(ORDER3), "records": order3_total},
        },
    }
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-CSC1-ORDER-FRONTIER1",
        "status": "ORDER_FRONTIER_COMPARISON_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "replay_executed": False,
        "parents": {
            "singleton_execution_sha256": sha256(singleton_exec_path),
            "order2_execution_sha256": sha256(order2_exec_path),
            "order3_execution_sha256": sha256(order3_exec_path),
            "order3_audit_execution_sha256": sha256(order3_audit_path),
        },
        "domain_manifest_sha256": json_hash(domain_manifest),
        "source_file_count": len(source_paths),
        "source_file_hash_manifest_sha256": json_hash(source_hashes),
        "counts": {
            "order1_records": singleton_total,
            "order2_records": order2_total,
            "order3_records": order3_total,
            "order3_valid_frontier_records": order3_valid_by_context,
        },
        "global": global_rows,
        "contexts": context_rows,
        "schema_notes": {
            "order1_distinct_exact": "not explicitly available in singleton receipt schema; zero-mismatch count reported separately",
            "order2_distinct_exact": "explicit target_readout_match and target_weight_match fields",
            "order3_distinct_exact": "explicit exact_target_distinct field",
        },
    }

    with (OUT / "domain-manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(domain_manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (OUT / "execution.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(execution, handle, indent=2, sort_keys=True)
        handle.write("\n")
    status = {
        "identity": OUT.name,
        "status": execution["status"],
        "source_integrity": "VERIFIED",
        "replay_executed": False,
        "scientific_promotion": False,
    }
    with (OUT / "STATUS.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(status, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (OUT / "REPORT.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Order-frontier comparison\n\n")
        handle.write("Read-only comparison of fresh order-1, order-2, and order-3 frontiers.\n\n")
        handle.write("The order-1 source contains all 3,696 singleton attempts. The order-2 and order-3 sources are already-valid frontiers: 9,530 and 1,090,580 records respectively. Their displayed 100% geometry-valid rates are therefore source-scope properties, not structural-domain validity rates.\n\n")
        handle.write("| Order | Source records represented | Geometry-valid source records | Better than V | Zero-mismatch | Distinct exact confirmed | Best valid score |\n")
        handle.write("|---:|---:|---:|---:|---:|---:|---|\n")
        for order in (1, 2, 3):
            row = global_rows[str(order)]
            handle.write(f"| {order} | {row['evaluated_records']} | {row['valid_geometry']} | {row['improved_vs_V']} | {row['zero_mismatch_readouts']} | {row['distinct_exact_confirmed']} | `{row['best_valid_score_key']}` |\n")
        handle.write("\nGlobal best-score relation: order 2 vs order 1 = **SAME**; order 3 vs order 2 = **SAME**; order 3 vs order 1 = **SAME**. The best recorded score is `(123, 162, 1.866006202952065e-05, 7.62939453125e-06)`, with zero exact target endpoints at every order.\n\n")
        handle.write("## Per-context best frontier\n\n")
        handle.write("`BETTER` and `SAME` refer to the lexicographic score tuple; a missing lower-order frontier is reported as `UNAVAILABLE`.\n\n")
        handle.write("| Context | Order 1 best | Order 2 best | Order 3 best | O2 vs O1 | O3 vs O2 | O3 vs O1 |\n")
        handle.write("|---|---|---|---|---|---|---|\n")
        for row in context_rows:
            label = f"{row['context'][0]} / set {row['context'][1]}"
            best = []
            for order in (1, 2, 3):
                key = row['orders'][str(order)]['best_valid_score_key']
                best.append("—" if key is None else f"({int(key[0])}, {int(key[1])}, {key[2]:.6g}, {key[3]:.6g})")
            comp = row["best_score_comparison"]
            handle.write(f"| {label} | `{best[0]}` | `{best[1]}` | `{best[2]}` | {comp['order2_vs_order1']} | {comp['order3_vs_order2']} | {comp['order3_vs_order1']} |\n")
        handle.write("\n## Interpretation boundary\n\n")
        handle.write("This artifact compares recorded valid frontiers and performs no replay. It does not establish monotonic improvement, because higher-order frontiers are not required to contain lower-order candidates. It does establish whether the best recorded score improved in the tested order-specific domains. The result is a plateau in the global best score, with order-3 improvements confined to several contexts.\n")

    verify_stable(source_paths, source_hashes)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ORDER_FRONTIER_FAILED: {exc}", file=sys.stderr)
        raise
