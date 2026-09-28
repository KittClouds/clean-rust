"""SALL1: complete exact materialization of the frozen LR1 singleton domain."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
REPO = ROOT.parents[2]
LR1_DIR = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1"
LR1_SCRIPTS = LR1_DIR / "scripts"
sys.path.insert(0, str(LR1_SCRIPTS))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_lr1_case as LR1  # noqa: E402
import run_rh1 as RH1  # noqa: E402

IDENTITY = "q10-gc0-lr1-sall1-v1"
PROTOCOL = "SALL1_COMPLETE_SINGLETON_MATERIALIZATION"
CHUNK = 32


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def sha_records(rows: list[dict]) -> str:
    return hashlib.sha256("\n".join(json.dumps(row, sort_keys=True) for row in rows).encode()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"SALL1 refuses overwrite: {path}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    require(not tmp.exists(), f"SALL1 orphan temporary: {tmp}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_key(case_dir: Path) -> tuple[str, int]:
    stem, set_text = case_dir.name.split("__set", 1)
    return stem + ".json", int(set_text)


def case_name(endpoint: str, set_index: int) -> str:
    return f"{endpoint.replace('.json', '')}__set{set_index}"


def case_dir(endpoint: str, set_index: int) -> Path:
    return ROOT / "cases" / case_name(endpoint, set_index)


def source_cases() -> list[tuple[str, int]]:
    result = []
    for path in sorted((LR1_DIR / "cases").iterdir()):
        if path.is_dir() and (path / "pairs" / "COMPLETE.json").exists():
            result.append(case_key(path))
    require(len(result) == 8, f"SALL1 case cohort drift: {len(result)}")
    return result


def source_bindings() -> list[dict]:
    paths: list[tuple[Path, str]] = [
        (LR1_DIR / "CONTRACT.json", "LR1 contract"),
        (LR1_DIR / "PREEXECUTION.json", "LR1 preexecution"),
        (LR1_SCRIPTS / "lr1_adapter.py", "LR1 adapter"),
        (LR1_SCRIPTS / "run_lr1_case.py", "LR1 case runtime"),
        (REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json", "PF5 contract"),
        (REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json", "PAR8 execution"),
        (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl", "GP1 palettes"),
        (REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pal2-r1-v1/execution.json", "PAL2 reconciliation"),
    ]
    for endpoint, set_index in source_cases():
        cdir = LR1_DIR / "cases" / case_name(endpoint, set_index)
        paths.append((cdir / "singles" / "COMPLETE.json", f"LR1 singles completion {cdir.name}"))
        for chunk in sorted((cdir / "singles").glob("chunk-*.jsonl")):
            paths.append((chunk, f"LR1 singleton chunk {chunk}"))
            paths.append((chunk.with_suffix(".COMPLETE.json"), f"LR1 singleton chunk marker {chunk}"))
        paths.append((LR1_DIR / "inventory" / "singles-domain" / f"{cdir.name}.json", f"LR1 singleton domain {cdir.name}"))
    bindings = []
    for path, label in paths:
        require(path.exists(), f"SALL1 missing source binding: {path}")
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
    return bindings


def prepare() -> None:
    require(not (ROOT / "CONTRACT.json").exists(), f"SALL1 refuses existing identity: {ROOT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "scripts").mkdir(exist_ok=True)
    (ROOT / "cases").mkdir(exist_ok=True)
    bindings = source_bindings()
    plan = """# Q10-GC0-LR1-SALL1: Complete Singleton Materialization\n\nSALL1 exact-replays every one of the 3,696 singleton records in the frozen LR1 domain. It creates a new materialized library without changing LR1, PAL2, MAT1-R1, or any scientific seed.\n\nEach source record is reconstructed from the frozen endpoint, group palette, canonical replacement, and exact LR1 oracle. The receipt stores the committed f32 state mapping, exact sequential-f32 readout, geometry, full row-level changes relative to the invalid LR1 search state, signed constraint vector/action, legality, distinctness, and source/reconstruction hashes.\n\nThe run is checkpointed by immutable 32-record chunks and per-case completion markers. Partial execution is not promoted to coverage. No pair expansion, global assembly, behavior, or scientific interpretation is performed.\n"""
    contract = {
        "identity": IDENTITY,
        "protocol": PROTOCOL,
        "scope": "engineering_only_complete_frozen_lr1_singleton_materialization",
        "source_cases": [case_name(e, s) for e, s in source_cases()],
        "expected_singleton_records": 3696,
        "chunk_size": CHUNK,
        "parent_bindings": bindings,
        "final_gate": "all_source_records_reconstructed_and_verified",
    }
    write_exclusive(ROOT / "PLAN.md", plan)
    write_exclusive(ROOT / "CONTRACT.json", json.dumps(contract, indent=2, sort_keys=True) + "\n")
    write_exclusive(ROOT / "PREEXECUTION.json", json.dumps({"identity": IDENTITY, "protocol": PROTOCOL, "parent_bindings": bindings, "sealed": True}, indent=2, sort_keys=True) + "\n")


def check_parents() -> dict:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(digest(path) == str(binding["sha256"]).upper(), f"SALL1 parent drift: {binding['label']}")
    return contract


def replace_selection(selection: list[tuple[int, str]], group: int, candidate: str) -> list[tuple[int, str]]:
    return [(g, candidate if int(g) == int(group) else identity) for g, identity in selection]


def selected_map(groups: dict[int, dict], selection: list[tuple[int, str]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for group, identity in selection:
        candidate = next(c for c in groups[int(group)]["palette"] if str(c["candidate_identity"]) == str(identity))
        for coordinate, prefix in candidate["canonical_mapping"]:
            coordinate, prefix = int(coordinate), int(prefix)
            require(coordinate not in result or result[coordinate] == prefix, f"SALL1 coordinate conflict {coordinate}")
            result[coordinate] = prefix
    return result


def raw_from_selection(state, groups: dict[int, dict], selection: list[tuple[int, str]]) -> tuple[int, ...]:
    return LR1.weight_bits_of(state, groups, selection)


def linear_drive(state, raw: tuple[int, ...]) -> tuple[float, ...]:
    weights = tuple(RH1.PF5.from_bits(value) for value in raw)
    return tuple(math.fsum(weights[index] - state.target_weights[index] for index in row) for row in state.rows)


def constraint_vector(state, geometry: dict, raw: tuple[int, ...]) -> list[float]:
    target = linear_drive(state, tuple(state.target_weight_bits))
    final = linear_drive(state, raw)
    return [
        float(geometry["final_axis"] - geometry["target_axis"]),
        float(geometry["final_norm"] - geometry["target_norm"]),
        *[float(left - right) for left, right in zip(final, target)],
    ]


def materialized_record(case: str, domain_index: int, group: int, source: dict, state, groups, selection, result, raw, invalid_bits, target_bits, invalid_constraint):
    readout = tuple(A.replay(state.rows, raw))
    mapping = selected_map(groups, selection)
    baseline = tuple(int(value) for value in state.baseline_weight_bits)
    changed = [[i, int(mapping.get(i, 0)), int(after)] for i, (before, after) in enumerate(zip(baseline, raw)) if int(before) != int(after)]
    invalid_mismatch = {i for i, (left, right) in enumerate(zip(invalid_bits, target_bits)) if left != right}
    candidate_mismatch = {i for i, (left, right) in enumerate(zip(readout, target_bits)) if left != right}
    changed_rows = {i for i, (left, right) in enumerate(zip(readout, invalid_bits)) if left != right}
    cv = constraint_vector(state, result["geometry"], raw)
    action = [left - right for left, right in zip(cv, invalid_constraint)]
    source_sha = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest().upper()
    record = {
        "identity": f"{case}|SINGLE|domain={domain_index}",
        "case": case,
        "kind": "SINGLE",
        "domain_index": int(domain_index),
        "group": int(group),
        "from": str(source["from"]),
        "to": str(source["to"]),
        "selection": [[int(g), str(identity)] for g, identity in selection],
        "nonzero_coordinate_prefix": [[int(i), int(k)] for i, k in sorted(mapping.items()) if int(k) != 0],
        "committed_f32_mapping": changed,
        "weight_bits_hash": result["weight_bits_hash"],
        "readout_bits": list(readout),
        "readout_hash": result["readout_hash"],
        "score": result["score"],
        "geometry": result["geometry"],
        "constraint_vector": cv,
        "constraint_action_from_S": action,
        "physical_support_rows": sorted(set(int(row) for row in groups[int(group)]["physical_support_rows"])),
        "readout_changed_rows": sorted(changed_rows),
        "baseline_mismatch_rows": sorted(invalid_mismatch),
        "entry_mismatch_rows": sorted(candidate_mismatch),
        "fixed_from_S_rows": sorted(invalid_mismatch - candidate_mismatch),
        "damaged_from_S_rows": sorted(candidate_mismatch - invalid_mismatch),
        "fixed_from_B_count": int(result["fixed"]),
        "damaged_from_B_count": int(result["damaged"]),
        "final_pass": bool(result["final_pass"]),
        "distinct_baseline": bool(result["distinct_b"]),
        "distinct_target": bool(result["distinct_t"]),
        "legal": True,
        "source_record_sha256": source_sha,
    }
    record["materialization_record_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest().upper()
    return record


def verify_source(record: dict, source: dict) -> None:
    for field in ("weight_hash", "readout_hash", "score", "geometry", "final_pass"):
        left = record["weight_bits_hash"] if field == "weight_hash" else record[field]
        right = source["weight_hash"] if field == "weight_hash" else source[field]
        require(left == right, f"SALL1 source drift {record['case']} domain {record['domain_index']} field {field}")
    require(record["group"] == int(source["group"]), "SALL1 group drift")
    require(record["from"] == str(source["from"]) and record["to"] == str(source["to"]), "SALL1 candidate drift")


def publish_chunk(directory: Path, rows: list[dict]) -> None:
    index = len(list(directory.glob("chunk-*.jsonl")))
    path = directory / f"chunk-{index:04d}.jsonl"
    write_exclusive(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    write_exclusive(directory / f"chunk-{index:04d}.COMPLETE.json", json.dumps({"count": len(rows), "sha256": sha_records(rows)}, indent=2, sort_keys=True) + "\n")


def read_materialized(directory: Path) -> dict[int, dict]:
    done: dict[int, dict] = {}
    for path in sorted(directory.glob("chunk-*.jsonl")):
        marker = directory / f"{path.stem}.COMPLETE.json"
        require(marker.exists(), f"SALL1 chunk without marker: {path}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        check = read_json(marker)
        require(len(rows) == int(check["count"]) and sha_records(rows) == str(check["sha256"]).upper(), f"SALL1 chunk checksum drift: {path}")
        for row in rows:
            index = int(row["domain_index"])
            require(index not in done, f"SALL1 duplicate domain index {index}")
            done[index] = row
    return done


def process_case(endpoint: str, set_index: int, max_records: int, max_minutes: float) -> int:
    start = time.perf_counter()
    state, groups, par8_record, domain, pf5_contract = LR1.load_case(endpoint, set_index)
    case = case_name(endpoint, set_index)
    source_dir = LR1_DIR / "cases" / case
    source = LR1.read_chunks(source_dir / "singles")
    require(len(source) == len(domain), f"SALL1 source/domain mismatch {case}")
    selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8_record["best_search"]["selected_candidates"]]
    context = hashlib.sha256(f"{endpoint}|{set_index}".encode()).hexdigest().upper()
    cache = A.ContextCache()
    invalid_result, _ = A.materialize(state, groups, selection, context, cache, pf5_contract)
    invalid_raw = raw_from_selection(state, groups, selection)
    invalid_bits = tuple(A.replay(state.rows, invalid_raw))
    target_bits = tuple(A.replay(state.rows, tuple(state.target_weight_bits)))
    invalid_constraint = constraint_vector(state, invalid_result["geometry"], invalid_raw)
    out_dir = ROOT / "cases" / case / "singletons"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = read_materialized(out_dir)
    pending = [index for index in range(len(domain)) if index not in done]
    made = 0
    buffer: list[dict] = []
    for index in pending:
        if made >= max_records or (time.perf_counter() - start) / 60.0 >= max_minutes:
            break
        source_row = source[index]
        current_identity = next(identity for group, identity in selection if int(group) == int(source_row["group"]))
        require(current_identity == str(source_row["from"]), f"SALL1 source current-candidate drift {case} domain {index}")
        replacement = str(source_row["to"])
        candidate_selection = replace_selection(selection, int(source_row["group"]), replacement)
        result, _ = A.materialize(state, groups, candidate_selection, context, cache, pf5_contract)
        raw = raw_from_selection(state, groups, candidate_selection)
        record = materialized_record(case, index, int(source_row["group"]), source_row, state, groups, candidate_selection, result, raw, invalid_bits, target_bits, invalid_constraint)
        verify_source(record, source_row)
        buffer.append(record)
        done[index] = record
        made += 1
        if len(buffer) == CHUNK:
            publish_chunk(out_dir, buffer)
            buffer = []
            print(f"{case}: {len(done)}/{len(domain)}", flush=True)
    if buffer:
        publish_chunk(out_dir, buffer)
        print(f"{case}: {len(done)}/{len(domain)}", flush=True)
    if len(done) == len(domain) and not (out_dir / "COMPLETE.json").exists():
        rows = [done[index] for index in range(len(domain))]
        write_exclusive(out_dir / "COMPLETE.json", json.dumps({"count": len(rows), "sha256": sha_records(rows)}, indent=2, sort_keys=True) + "\n")
        print(f"{case}: COMPLETE {len(rows)}", flush=True)
    return made


def finalize(contract: dict) -> None:
    summaries = []
    all_rows: list[dict] = []
    for endpoint, set_index in source_cases():
        case = case_name(endpoint, set_index)
        directory = ROOT / "cases" / case / "singletons"
        rows = read_materialized(directory)
        domain = read_json(LR1_DIR / "inventory" / "singles-domain" / f"{case}.json")
        complete = (directory / "COMPLETE.json").exists()
        if complete:
            marker = read_json(directory / "COMPLETE.json")
            ordered = [rows[index] for index in range(len(domain))]
            require(int(marker["count"]) == len(ordered) and str(marker["sha256"]).upper() == sha_records(ordered), f"SALL1 COMPLETE drift {case}")
            all_rows.extend(ordered)
        summaries.append({"case": case, "expected": len(domain), "materialized": len(rows), "complete": complete})
    total_expected = sum(x["expected"] for x in summaries)
    total_materialized = sum(x["materialized"] for x in summaries)
    execution = {
        "identity": IDENTITY,
        "protocol": PROTOCOL,
        "status": "COMPLETE" if total_materialized == total_expected == 3696 and len(all_rows) == 3696 else "PARTIAL",
        "scope": "engineering_only_exact_singleton_materialization",
        "expected_records": total_expected,
        "materialized_records": total_materialized,
        "source_verified_records": len(all_rows),
        "library_sha256": hashlib.sha256("\n".join(json.dumps(row, sort_keys=True) for row in all_rows).encode()).hexdigest().upper() if all_rows else None,
        "case_summaries": summaries,
        "checks_passed": total_materialized == total_expected == 3696 and len(all_rows) == 3696,
        "global_assembly": False,
        "behavior": False,
        "scientific_promotion": False,
    }
    write_exclusive(ROOT / "execution.json", json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--max-records", type=int, default=128)
    parser.add_argument("--max-minutes", type=float, default=10.0)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
        return
    contract = check_parents()
    if args.finalize:
        finalize(contract)
        return
    cases = source_cases()
    if args.case:
        cases = [item for item in cases if case_name(*item) == args.case]
        require(len(cases) == 1, f"SALL1 unknown case {args.case}")
    made = 0
    for endpoint, set_index in cases:
        made += process_case(endpoint, set_index, args.max_records - made, args.max_minutes)
        if made >= args.max_records:
            break
    print(json.dumps({"identity": IDENTITY, "records_made": made}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
