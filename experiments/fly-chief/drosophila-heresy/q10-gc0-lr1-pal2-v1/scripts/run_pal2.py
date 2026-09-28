"""Exact materialization and support audit for the augmented PAL2 library."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
LR1_SCRIPT = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"
RH1_SCRIPT = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0_SCRIPT = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(LR1_SCRIPT))
sys.path.insert(0, str(RH1_SCRIPT))
sys.path.insert(0, str(GC0_SCRIPT))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_lr1_case as LR1  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"PAL2 refuses overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"PAL2 orphan temporary file: {temporary}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def f32(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def linear_drive(state, raw: tuple[int, ...]) -> tuple[float, ...]:
    weights = [f32(x) for x in raw]
    target = tuple(state.target_weights)
    return tuple(math.fsum(weights[i] - target[i] for i in row) for row in state.rows)


def constraint_vector(state, geometry: dict, raw: tuple[int, ...]) -> list[float]:
    target_linear = linear_drive(state, tuple(state.target_weight_bits))
    final_linear = linear_drive(state, raw)
    return [
        float(geometry["final_axis"] - geometry["target_axis"]),
        float(geometry["final_norm"] - geometry["target_norm"]),
        *[float(a - b) for a, b in zip(final_linear, target_linear)],
    ]


def l2(values) -> float:
    return math.sqrt(math.fsum(x * x for x in values))


def vector_rank(vectors: list[list[float]], tolerance: float = 1e-12) -> int:
    basis: list[list[float]] = []
    for source in vectors:
        v = [float(x) for x in source]
        for b in basis:
            scale = math.fsum(x * y for x, y in zip(v, b))
            v = [x - scale * y for x, y in zip(v, b)]
        norm = l2(v)
        if norm > tolerance:
            basis.append([x / norm for x in v])
    return len(basis)


def case_name(endpoint: str, set_index: int) -> str:
    return f"{endpoint.replace('.json', '')}__set{set_index}"


def replace_selection(selection, group: int, identity: str):
    return [(int(g), identity if int(g) == group else str(candidate)) for g, candidate in selection]


def raw_from_selection(state, groups, selection):
    return LR1.weight_bits_of(state, groups, selection)


def raw_from_mapping(state, mapping):
    raw = [int(x) for x in state.baseline_weight_bits]
    for coordinate, _, bits in mapping:
        raw[int(coordinate)] = int(bits)
    return tuple(raw)


def selected_map(groups, selection):
    result = {}
    for group, identity in selection:
        candidate = next(c for c in groups[int(group)]["palette"] if str(c["candidate_identity"]) == str(identity))
        for coordinate, prefix in candidate["canonical_mapping"]:
            result[int(coordinate)] = int(prefix)
    return result


def materialized_entry(case, state, groups, target_readout, invalid_bits, invalid_constraint, kind, groups_used, selection, result, raw, source):
    readout = tuple(A.replay(state.rows, raw))
    baseline = tuple(int(x) for x in state.baseline_weight_bits)
    mapping = selected_map(groups, selection)
    changed = [[i, int(mapping.get(i, 0)), int(after)] for i, (before, after) in enumerate(zip(baseline, raw)) if int(before) != int(after)]
    target_mismatch = {i for i, (x, y) in enumerate(zip(invalid_bits, target_readout)) if x != y}
    entry_mismatch = {i for i, (x, y) in enumerate(zip(readout, target_readout)) if x != y}
    changed_rows = {i for i, (x, y) in enumerate(zip(readout, invalid_bits)) if x != y}
    cv = constraint_vector(state, result["geometry"], raw)
    action = [x - y for x, y in zip(cv, invalid_constraint)]
    support = sorted({row for group in groups_used for row in groups[int(group)]["physical_support_rows"]})
    identity = f"{case}|{kind}|" + ",".join(f"{int(g)}:{i}" for g, i in selection)
    return {
        "entry_identity": identity,
        "case": case,
        "kind": kind,
        "groups": sorted(int(x) for x in groups_used),
        "selection": [[int(g), str(i)] for g, i in selection],
        "nonzero_coordinate_prefix": [[i, k] for i, k in sorted(mapping.items()) if k != 0],
        "committed_f32_mapping": changed,
        "weight_bits_hash": result["weight_bits_hash"],
        "readout_bits": list(readout),
        "readout_hash": result["readout_hash"],
        "score": result["score"],
        "geometry": result["geometry"],
        "constraint_vector": cv,
        "constraint_action_from_S": action,
        "physical_support_rows": support,
        "readout_changed_rows": sorted(changed_rows),
        "baseline_mismatch_rows": sorted(target_mismatch),
        "entry_mismatch_rows": sorted(entry_mismatch),
        "fixed_baseline_rows": sorted(target_mismatch - entry_mismatch),
        "newly_damaged_rows": sorted(entry_mismatch - target_mismatch),
        "source": source,
    }


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"PAL2 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"PAL2 parent drift: {binding['label']}")

    mat_path = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-mat1-r1-v1/qualification/materialized-pairs.jsonl"
    mat_records = [json.loads(line) for line in mat_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(mat_records) == 201, f"PAL2 pair source drift: {len(mat_records)}")
    pair_by_case = defaultdict(list)
    for record in mat_records:
        pair_by_case[case_name(record["endpoint"], int(record["set_index"]))].append(record)

    all_cases = []
    lr1_cases = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/cases"
    for case_dir in sorted(lr1_cases.iterdir()):
        if not case_dir.is_dir() or not (case_dir / "pairs" / "COMPLETE.json").exists():
            continue
        stem, set_text = case_dir.name.split("__set", 1)
        all_cases.append((stem + ".json", int(set_text)))
    require(len(all_cases) == 8, f"PAL2 case cohort drift: {len(all_cases)}")

    entries_by_case = {}
    contexts = {}
    singleton_count = 0
    zero_count = 0
    for endpoint, set_index in all_cases:
        case = case_name(endpoint, set_index)
        state, groups, par8_record, _, pf5_contract = LR1.load_case(endpoint, set_index)
        search_selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8_record["best_search"]["selected_candidates"]]
        context = hashlib.sha256(f"{endpoint}|{set_index}".encode()).hexdigest().upper()
        cache = A.ContextCache()
        invalid_result, _ = A.materialize(state, groups, search_selection, context, cache, pf5_contract)
        invalid_raw = raw_from_selection(state, groups, search_selection)
        invalid_bits = tuple(A.replay(state.rows, invalid_raw))
        invalid_constraint = constraint_vector(state, invalid_result["geometry"], invalid_raw)
        target_readout = tuple(A.replay(state.rows, tuple(state.target_weight_bits)))
        contexts[case] = (state, groups, target_readout, invalid_bits, invalid_constraint)
        entries = {}

        for group_index in sorted(groups):
            zero = next(c for c in groups[group_index]["palette"] if "ZERO" in c.get("roles", []))
            identity = str(zero["candidate_identity"])
            selection = replace_selection(search_selection, group_index, identity)
            result, _ = A.materialize(state, groups, selection, context, cache, pf5_contract)
            raw = raw_from_selection(state, groups, selection)
            entry = materialized_entry(case, state, groups, target_readout, invalid_bits, invalid_constraint, "ZERO", [group_index], selection, result, raw, {"type": "ZERO", "candidate_identity": identity})
            entries[entry["entry_identity"]] = entry
            zero_count += 1

        case_dir = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/cases" / case
        for row in LR1.read_chunks(case_dir / "singles").values():
            if row["outcome"] != "VALID_ADVANTAGE_PRESERVED":
                continue
            group_index = int(row["group"])
            selection = replace_selection(search_selection, group_index, str(row["to"]))
            result, _ = A.materialize(state, groups, selection, context, cache, pf5_contract)
            raw = raw_from_selection(state, groups, selection)
            require(result["weight_bits_hash"] == str(row["weight_hash"]).upper(), f"PAL2 singleton weight drift: {case} {row['domain_index']}")
            require(result["readout_hash"] == str(row["readout_hash"]).upper(), f"PAL2 singleton readout drift: {case} {row['domain_index']}")
            require(result["score"] == row["score"] and result["geometry"] == row["geometry"] and result["final_pass"] == bool(row["final_pass"]), f"PAL2 singleton receipt drift: {case} {row['domain_index']}")
            entry = materialized_entry(case, state, groups, target_readout, invalid_bits, invalid_constraint, "SINGLE", [group_index], selection, result, raw, {"type": "SINGLE", "domain_index": int(row["domain_index"]), "candidate_identity": str(row["to"]), "receipt": row})
            entries[entry["entry_identity"]] = entry
            singleton_count += 1

        for record in pair_by_case.get(case, []):
            pair_state = record["states"]["pair_ab"]
            a, b = record["source"]["a"], record["source"]["b"]
            entry = {
                "entry_identity": f"{case}|PAIR|pair={int(record['pair_domain_index'])}",
                "case": case,
                "kind": "PAIR",
                "groups": sorted([int(a["group"]), int(b["group"])]),
                "selection": pair_state["selection"],
                "nonzero_coordinate_prefix": pair_state["nonzero_coordinate_prefix"],
                "committed_f32_mapping": pair_state["committed_f32_mapping"],
                "weight_bits_hash": pair_state["weight_bits_hash"],
                "readout_bits": pair_state["readout_bits"],
                "readout_hash": pair_state["readout_hash"],
                "score": pair_state["score"],
                "geometry": pair_state["geometry"],
                "constraint_vector": [],
                "physical_support_rows": sorted(set(groups[int(a["group"])]["physical_support_rows"]) | set(groups[int(b["group"])]["physical_support_rows"])),
                "readout_changed_rows": sorted(i for i, (x, y) in enumerate(zip(pair_state["readout_bits"], invalid_bits)) if x != y),
                "baseline_mismatch_rows": sorted(i for i, (x, y) in enumerate(zip(invalid_bits, target_readout)) if x != y),
                "entry_mismatch_rows": sorted(i for i, (x, y) in enumerate(zip(pair_state["readout_bits"], target_readout)) if x != y),
                "source": {"type": "PAIR", "pair_domain_index": int(record["pair_domain_index"]), "mat1_record_hash": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest().upper()},
            }
            raw_pair = raw_from_mapping(state, pair_state["committed_f32_mapping"])
            pair_cv = constraint_vector(state, pair_state["geometry"], raw_pair)
            entry["constraint_vector"] = pair_cv
            entry["constraint_action_from_S"] = [x - y for x, y in zip(pair_cv, invalid_constraint)]
            entry["fixed_baseline_rows"] = sorted(set(entry["baseline_mismatch_rows"]) - set(entry["entry_mismatch_rows"]))
            entry["newly_damaged_rows"] = sorted(set(entry["entry_mismatch_rows"]) - set(entry["baseline_mismatch_rows"]))
            entries[entry["entry_identity"]] = entry
        entries_by_case[case] = [entries[key] for key in sorted(entries)]

    case_summaries = []
    conflict_edges = []
    for case, entries in sorted(entries_by_case.items()):
        _, _, _, _, _ = contexts[case]
        support_union = set()
        effect_union = set()
        baseline_mismatch = set()
        actions = []
        group_edges = coordinate_edges = 0
        for entry in entries:
            support_union.update(entry["physical_support_rows"])
            effect_union.update(entry["readout_changed_rows"])
            baseline_mismatch.update(entry["baseline_mismatch_rows"])
            if entry["kind"] != "ZERO":
                actions.append(entry["constraint_action_from_S"])
        for i, left in enumerate(entries):
            left_map = {int(x[0]): int(x[1]) for x in left["nonzero_coordinate_prefix"]}
            for right in entries[i + 1:]:
                if set(left["groups"]) & set(right["groups"]):
                    group_edges += 1
                    reason = "group_overlap"
                else:
                    right_map = {int(x[0]): int(x[1]) for x in right["nonzero_coordinate_prefix"]}
                    reason = "coordinate_conflict" if any(k in right_map and right_map[k] != v for k, v in left_map.items()) else None
                    if reason:
                        coordinate_edges += 1
                if reason:
                    conflict_edges.append({"case": case, "left": left["entry_identity"], "right": right["entry_identity"], "reason": reason})
        case_summaries.append({
            "case": case,
            "entry_counts": dict(Counter(x["kind"] for x in entries)),
            "entry_count": len(entries),
            "baseline_mismatch_count": len(baseline_mismatch),
            "physical_support_union_count": len(support_union),
            "baseline_mismatch_outside_physical_support": sorted(baseline_mismatch - support_union),
            "readout_effect_union_count": len(effect_union),
            "baseline_mismatch_outside_readout_effect_union": sorted(baseline_mismatch - effect_union),
            "group_conflict_edges": group_edges,
            "coordinate_conflict_edges": coordinate_edges,
            "constraint_action_rank": vector_rank(actions),
        })

    output = ROOT / "qualification"
    output.mkdir(parents=True, exist_ok=True)
    entry_path = output / "augmented-library.jsonl"
    case_path = output / "case-support-conflict.jsonl"
    edge_path = output / "conflict-edges.jsonl"
    execution_path = output / "execution.json"
    all_entries = [entry for case in sorted(entries_by_case) for entry in entries_by_case[case]]
    write_exclusive(entry_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in all_entries))
    write_exclusive(case_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in case_summaries))
    write_exclusive(edge_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in conflict_edges))
    execution = {
        "identity": contract["identity"],
        "protocol": contract["protocol"],
        "scope": "engineering_only_exact_augmented_palette_support_audit",
        "entries": len(all_entries),
        "source_pair_motifs": 201,
        "source_singleton_advantages": singleton_count,
        "zero_entries": zero_count,
        "cases": len(case_summaries),
        "case_summaries": case_summaries,
        "conflict_edges": len(conflict_edges),
        "augmented_library_sha256": digest(entry_path),
        "case_support_sha256": digest(case_path),
        "conflict_edges_sha256": digest(edge_path),
        "checks_passed": True,
        "global_assembly": False,
    }
    write_exclusive(execution_path, json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
