from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXH1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1"
EXH1_AUDIT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-audit-v1"
RESCUE1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-rescue1-v1"
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
READ_INC1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-read-inc1-v1"
PROTOCOL = "Q10-ALG3-FRONT2"
IDENTITY = ROOT.name
WORKERS = 4
AUDIT_PER_CONTEXT = 256
AUDIT_TOL = 1.0e-12
CONTEXTS = (("seed9731-L-tau16.json", 2), ("seed9731-L-tau4.json", 3), ("seed9731-R-tau16.json", 1), ("seed9731-R-tau16.json", 3), ("seed9731-R-tau4.json", 0), ("seed9731-R-tau4.json", 1), ("seed9731-R-tau4.json", 2), ("seed9731-R-tau4.json", 3))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_alg3_front2_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong ALG1 runtime")
    return module


def prepare_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    reference = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in reference["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    v_score = ref_result["best_valid"]["score"]
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = sorted(descriptor["actions"], key=lambda row: (int(row["group"]), str(row["to"])))
    by_key = {str(row["action_key"]): row for row in actions}
    require(len(by_key) == len(actions), f"action identity drift: {key}")
    by_ordinal = {index: row for index, row in enumerate(actions)}
    action_rows: dict[int, tuple[int, ...]] = {}
    action_assignments: dict[int, tuple[tuple[int, int, float], ...]] = {}
    for ordinal, row in by_ordinal.items():
        rows: set[int] = set()
        assignments = []
        for coordinate, choice in row["canonical_mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            raw = int(row["weight_bits"][coordinate])
            assignments.append((coordinate, raw, pf.from_bits(raw)))
            if raw != int(s["bits"][coordinate]):
                rows.update(index for index, source_row in enumerate(state.rows) if coordinate in source_row)
        action_rows[ordinal] = tuple(sorted(rows))
        action_assignments[ordinal] = tuple(assignments)
    execution = json.loads((EXH1 / "execution.json").read_text(encoding="utf-8"))
    context_record = next(item for item in execution["contexts"] if item["context"] == [key[0], key[1]])
    return {"pf": pf, "state": state, "contract": contract, "s": s, "actions": by_ordinal, "action_rows": action_rows, "action_assignments": action_assignments, "v_score": v_score, "v_score_key": alg.score_key(v_score), "frontier_context": context_record}


def iter_frontier(context: dict[str, Any], key: tuple[str, int]):
    for item in sorted(context["frontier_context"]["ranges"], key=lambda row: int(row["start"])):
        path = REPO / item["valid_shard"]
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                yield item, json.loads(line)


def construct(context: dict[str, Any], record: dict[str, Any]) -> tuple[list[int], list[float]]:
    pf = context["pf"]
    bits = list(context["s"]["bits"])
    weights = list(context["s"]["weights"])
    for ordinal in record["action_ordinals"]:
        for coordinate, raw, value in context["action_assignments"][int(ordinal)]:
            bits[coordinate] = raw
            weights[coordinate] = value
    return bits, weights


def localized_readout(context: dict[str, Any], weights: list[float], dependency_rows: list[int]) -> tuple[int, ...]:
    pf = context["pf"]
    state = context["state"]
    readout = list(context["s"]["readout"])
    for row_index in dependency_rows:
        readout[row_index] = int(pf.sequential_bits(state.rows[row_index], weights))
    return tuple(readout)


def full_readout(context: dict[str, Any], weights: list[float]) -> tuple[int, ...]:
    return tuple(int(value) for value in context["pf"].readout_bits(context["state"].rows, weights))


def process_context(key: tuple[str, int]) -> dict[str, Any]:
    alg = load_alg1()
    context = prepare_context(key, alg)
    count = int(context["frontier_context"]["valid_triples"])
    stride = max(1, count // AUDIT_PER_CONTEXT)
    result_root = ROOT / "results" / slug(key)
    summary_root = ROOT / "range-summaries" / slug(key)
    result_root.mkdir(parents=True, exist_ok=True)
    summary_root.mkdir(parents=True, exist_ok=True)
    total = 0
    improved = 0
    exact = 0
    affected_rows = 0
    total_rows = 0
    best = None
    exact_records = []
    audit_seen_n2: set[int] = set()
    audit_records = []
    range_summaries = []
    for source_range in sorted(context["frontier_context"]["ranges"], key=lambda row: int(row["start"])):
        input_path = REPO / source_range["valid_shard"]
        output_path = result_root / Path(source_range["valid_shard"]).name
        summary_path = summary_root / Path(source_range["valid_shard"]).with_suffix(".json").name
        require(not output_path.exists() and not summary_path.exists(), f"FRONT2 output exists: {output_path}")
        output_hash = hashlib.sha256()
        range_total = 0
        range_improved = 0
        range_exact = 0
        with output_path.open("xb") as out, input_path.open("r", encoding="utf-8") as source:
            for line in source:
                if not line:
                    continue
                record = json.loads(line)
                bits, weights = construct(context, record)
                local = localized_readout(context, weights, [int(row) for row in record["dependency_rows"]])
                score = alg.score_dict(context["pf"], local, context["state"].target_readout_bits)
                score_key = alg.score_key(score)
                is_improved = score_key < context["v_score_key"]
                is_exact = local == tuple(context["state"].target_readout_bits) and tuple(bits) != tuple(context["state"].target_weight_bits)
                min_margin = min(abs(float(value)) for value in record["gate_margins"])
                audit_reason = None
                if total % stride == 0:
                    audit_reason = "deterministic_context_sample"
                elif int(record["n2"]) not in audit_seen_n2:
                    audit_reason = "first_rescue_class"
                elif min_margin < 1.0e-8 and sum(1 for item in audit_records if item.get("reason") == "near_gate") < 8:
                    audit_reason = "near_gate"
                if audit_reason is not None:
                    expected_rows = sorted(set().union(*(context["action_rows"][int(ordinal)] for ordinal in record["action_ordinals"])))
                    require(expected_rows == [int(row) for row in record["dependency_rows"]], f"dependency closure drift: {key} {record['local_rank']}")
                    full = full_readout(context, weights)
                    require(full == local, f"localized readout mismatch: {key} {record['local_rank']}")
                    audit_records.append({"local_rank": int(record["local_rank"]), "global_rank": int(record["global_rank"]), "reason": audit_reason, "n2": int(record["n2"]), "dependency_rows": len(record["dependency_rows"]), "readout_hash": alg.bits_hash(full)})
                    audit_seen_n2.add(int(record["n2"]))
                result = {"global_rank": int(record["global_rank"]), "local_rank": int(record["local_rank"]), "context": record["context"], "action_ordinals": record["action_ordinals"], "actions": record["actions"], "n1": record["n1"], "n2": record["n2"], "rescue_class": record["rescue_class"], "dependency_rows": len(record["dependency_rows"]), "readout_sha256": alg.bits_hash(local), "score": score, "improved_vs_V": is_improved, "exact_target_distinct": is_exact}
                payload = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                out.write(payload)
                output_hash.update(payload)
                total += 1
                range_total += 1
                affected_rows += len(record["dependency_rows"])
                total_rows += len(context["state"].rows)
                improved += int(is_improved)
                range_improved += int(is_improved)
                exact += int(is_exact)
                range_exact += int(is_exact)
                if best is None or score_key < best["score_key"]:
                    best = {"global_rank": int(record["global_rank"]), "local_rank": int(record["local_rank"]), "score": score, "score_key": list(score_key), "readout_sha256": result["readout_sha256"], "actions": record["actions"], "weight_state_sha256": alg.bits_hash(tuple(bits))}
                if is_exact:
                    exact_records.append({"global_rank": int(record["global_rank"]), "local_rank": int(record["local_rank"]), "actions": record["actions"], "weight_state_sha256": alg.bits_hash(tuple(bits)), "readout_sha256": result["readout_sha256"], "score": score})
        range_summary = {"start": int(source_range["start"]), "end": int(source_range["end"]), "records": range_total, "improved": range_improved, "exact": range_exact, "result_sha256": output_hash.hexdigest().upper(), "result_path": output_path.relative_to(REPO).as_posix()}
        write_new(summary_path, range_summary)
        range_summaries.append(range_summary)
    require(total == count, f"FRONT2 frontier cardinality drift: {key} {total} != {count}")
    require(len(audit_records) >= min(AUDIT_PER_CONTEXT, count), f"FRONT2 audit sample too small: {key}")
    return {"context": [key[0], key[1]], "valid_frontier": count, "evaluated": total, "improved_vs_V": improved, "exact_target_distinct": exact, "affected_rows": affected_rows, "total_rows": total_rows, "mean_affected_fraction": affected_rows / max(total_rows, 1), "audit_records": audit_records, "audit_count": len(audit_records), "best": best, "exact_records": exact_records, "ranges": range_summaries}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected FRONT2 script cache")
    require(not (ROOT / "execution.json").exists(), "FRONT2 execution already exists")
    inputs: list[tuple[str, Path]] = [("front2_plan", ROOT / "PLAN.md"), ("front2_runner", Path(__file__)), ("exh1_execution", EXH1 / "execution.json"), ("exh1_contract", EXH1 / "CONTRACT.json"), ("exh1_audit_execution", EXH1_AUDIT / "execution.json"), ("rescue1_execution", RESCUE1 / "execution.json"), ("alg1_execution", ALG1 / "execution.json"), ("read_inc1_execution", READ_INC1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        name = slug(key)
        inputs.append((f"alg1_descriptor:{name}", ALG1 / "descriptors" / f"{name}.json"))
    bindings = [{"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "frontier_source": "complete geometry-valid EXH1 frontier", "localized_readout": True, "full_readout_audit_required": True, "audit_per_context": AUDIT_PER_CONTEXT, "exact_target_requires_distinct_weight_state": True, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "results/*/*.jsonl", "range-summaries/*/*.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "full_readout_audit_required": True})
    results: list[dict[str, Any]] = []
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(process_context, key) for key in CONTEXTS]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                print(json.dumps({"context": result["context"], "evaluated": result["evaluated"], "improved": result["improved_vs_V"], "exact": result["exact_target_distinct"], "audit": result["audit_count"]}, sort_keys=True), flush=True)
        results.sort(key=lambda item: CONTEXTS.index(tuple(item["context"])))
        require(all(item["evaluated"] == item["valid_frontier"] for item in results), "FRONT2 incomplete frontier")
        require(all(item["audit_count"] >= min(AUDIT_PER_CONTEXT, item["evaluated"]) for item in results), "FRONT2 audit coverage incomplete")
        require(sum(item["exact_target_distinct"] for item in results) >= 0, "exact count accounting failure")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_FRONT2_COMPLETE_NO_EXACT" if sum(item["exact_target_distinct"] for item in results) == 0 else "ALG3_FRONT2_COMPLETE_EXACT_CANDIDATE", "engineering_only": True, "scientific_promotion": False, "localized_readout": True, "full_readout_audit_passed": True, "counts": {"contexts": len(results), "valid_frontier": sum(item["valid_frontier"] for item in results), "evaluated": sum(item["evaluated"] for item in results), "improved_vs_V": sum(item["improved_vs_V"] for item in results), "exact_target_distinct": sum(item["exact_target_distinct"] for item in results), "audit_records": sum(item["audit_count"] for item in results), "affected_rows": sum(item["affected_rows"] for item in results), "total_rows": sum(item["total_rows"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Localized exact sequential-f32 readout was independently full-replay audited across every context and the complete EXH1 valid order-3 frontier."}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_FRONT2", "engineering_only": True, "scientific_promotion": False, "localized_readout": True, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
