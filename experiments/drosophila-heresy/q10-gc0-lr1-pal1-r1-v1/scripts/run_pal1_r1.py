"""Build and audit the augmented per-case PAL1 candidate library."""
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
    require(not path.exists(), f"PAL1-R1 refuses overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"PAL1-R1 orphan temporary file: {temporary}")
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


def raw_from_mapping(state, mapping: list[list[int]]) -> tuple[int, ...]:
    raw = [int(x) for x in state.baseline_weight_bits]
    for row in mapping:
        raw[int(row[0])] = int(row[2])
    return tuple(raw)


def score(bits, target_bits):
    return A.score_of(tuple(bits), tuple(target_bits))


def make_entry(case, state, groups, target_readout, kind, groups_used, selection, mapping, readout_bits, geometry, source):
    raw = raw_from_mapping(state, mapping)
    invalid_bits = source["invalid_bits"]
    target_bits = target_readout
    baseline_mismatch = {i for i, (x, y) in enumerate(zip(invalid_bits, target_bits)) if x != y}
    entry_mismatch = {i for i, (x, y) in enumerate(zip(readout_bits, target_bits)) if x != y}
    changed = {i for i, (x, y) in enumerate(zip(readout_bits, invalid_bits)) if x != y}
    support = sorted({row for group in groups_used for row in groups[group]["physical_support_rows"]})
    cv = constraint_vector(state, geometry, raw)
    svec = source["invalid_constraint"]
    action = [a - b for a, b in zip(cv, svec)]
    identity = f"{case}|{kind}|" + ",".join(f"{g}:{i}" for g, i in selection)
    return {
        "entry_identity": identity,
        "case": case,
        "kind": kind,
        "groups": sorted(int(x) for x in groups_used),
        "selection": [[int(g), str(i)] for g, i in selection],
        "canonical_mapping": mapping,
        "committed_f32_mapping": [[int(x[0]), int(x[1]), int(x[2])] for x in mapping],
        "weight_bits_hash": A.bits_hash(raw),
        "readout_bits": list(readout_bits),
        "readout_hash": A.bits_hash(tuple(readout_bits)),
        "score": score(readout_bits, target_bits),
        "geometry": geometry,
        "constraint_vector": cv,
        "constraint_action_from_S": action,
        "physical_support_rows": support,
        "readout_changed_rows": sorted(changed),
        "baseline_mismatch_rows": sorted(baseline_mismatch),
        "entry_mismatch_rows": sorted(entry_mismatch),
        "fixed_baseline_rows": sorted(baseline_mismatch - entry_mismatch),
        "newly_damaged_rows": sorted(entry_mismatch - baseline_mismatch),
        "source": source["source"],
    }


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"PAL1-R1 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"PAL1-R1 parent drift: {binding['label']}")

    mat_path = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-mat1-r1-v1/qualification/materialized-pairs.jsonl"
    mat_records = [json.loads(line) for line in mat_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(mat_records) == 201, f"PAL1-R1 pair source drift: {len(mat_records)}")
    by_case: dict[str, list[dict]] = defaultdict(list)
    for record in mat_records:
        by_case[case_name(record["endpoint"], int(record["set_index"]))].append(record)

    contexts = {}
    entries_by_case: dict[str, list[dict]] = {}
    for case, pair_records in sorted(by_case.items()):
        endpoint = pair_records[0]["endpoint"]
        set_index = int(pair_records[0]["set_index"])
        state, groups, _, _, _ = LR1.load_case(endpoint, set_index)
        target_readout = tuple(A.replay(state.rows, tuple(state.target_weight_bits)))
        invalid_state = pair_records[0]["states"]["invalid_search"]
        source_common = {
            "invalid_bits": tuple(invalid_state["readout_bits"]),
            "invalid_constraint": constraint_vector(state, invalid_state["geometry"], tuple(state.baseline_weight_bits)),
            "source": {"type": "derived_from_case", "case": case},
        }
        contexts[case] = (state, groups, target_readout, source_common)
        entries: dict[str, dict] = {}

        for group_index in sorted(groups):
            zero = next(c for c in groups[group_index]["palette"] if "ZERO" in c.get("roles", []))
            mapping = [[int(x[0]), int(x[1]), int(x[2])] for x in zero["committed_f32_mapping"]]
            entry = make_entry(case, state, groups, target_readout, "ZERO", [group_index], [(group_index, str(zero["candidate_identity"]))], mapping, tuple(zero["exact_readout_bits"]), zero["geometry"], {**source_common, "type": "ZERO", "candidate_identity": str(zero["candidate_identity"])})
            entries[entry["entry_identity"]] = entry

        case_dir = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/cases" / case
        single_rows = LR1.read_chunks(case_dir / "singles")
        for row in single_rows.values():
            if row["outcome"] != "VALID_ADVANTAGE_PRESERVED":
                continue
            group_index = int(row["group"])
            candidate = next(c for c in groups[group_index]["palette"] if str(c["candidate_identity"]) == str(row["to"]))
            bits = tuple(int(x) for x in candidate["exact_readout_bits"])
            require(A.bits_hash(bits) == str(row["readout_hash"]).upper(), f"PAL1-R1 singleton readout drift: {case} {row['domain_index']}")
            mapping = [[int(x[0]), int(x[1]), int(x[2])] for x in candidate["committed_f32_mapping"]]
            entry = make_entry(case, state, groups, target_readout, "SINGLE", [group_index], [(group_index, str(row["to"]))], mapping, bits, candidate["geometry"], {**source_common, "type": "SINGLE", "domain_index": int(row["domain_index"]), "candidate_identity": str(row["to"]), "receipt": row})
            entries[entry["entry_identity"]] = entry

        for record in pair_records:
            pair_state = record["states"]["pair_ab"]
            a, b = record["source"]["a"], record["source"]["b"]
            mapping = [[int(x[0]), int(x[1]), int(x[2])] for x in pair_state["committed_f32_mapping"]]
            entry = make_entry(case, state, groups, target_readout, "PAIR", [int(a["group"]), int(b["group"])], [(int(x[0]), str(x[1])) for x in pair_state["selection"]], mapping, tuple(pair_state["readout_bits"]), pair_state["geometry"], {**source_common, "type": "PAIR", "pair_domain_index": int(record["pair_domain_index"]), "mat1_record_hash": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest().upper()})
            entries[entry["entry_identity"]] = entry
        entries_by_case[case] = [entries[key] for key in sorted(entries)]

    case_summaries = []
    conflict_edges = []
    for case, entries in sorted(entries_by_case.items()):
        state, groups, target_readout, source_common = contexts[case]
        support_union = set()
        effect_union = set()
        baseline_mismatch = set()
        action_vectors = []
        group_edges = 0
        coordinate_edges = 0
        for entry in entries:
            support_union.update(entry["physical_support_rows"])
            effect_union.update(entry["readout_changed_rows"])
            baseline_mismatch.update(entry["baseline_mismatch_rows"])
            if entry["kind"] != "ZERO":
                action_vectors.append(entry["constraint_action_from_S"])
        for i, left in enumerate(entries):
            left_map = {int(x[0]): int(x[1]) for x in left["canonical_mapping"]}
            for right in entries[i + 1:]:
                if set(left["groups"]) & set(right["groups"]):
                    group_edges += 1
                    reason = "group_overlap"
                else:
                    right_map = {int(x[0]): int(x[1]) for x in right["canonical_mapping"]}
                    reason = "coordinate_conflict" if any(k in right_map and right_map[k] != v for k, v in left_map.items()) else None
                    if reason:
                        coordinate_edges += 1
                if reason:
                    conflict_edges.append({"case": case, "left": left["entry_identity"], "right": right["entry_identity"], "reason": reason})
        case_summaries.append({
            "case": case,
            "entry_counts": dict(Counter(entry["kind"] for entry in entries)),
            "entry_count": len(entries),
            "baseline_mismatch_count": len(baseline_mismatch),
            "physical_support_union_count": len(support_union),
            "baseline_mismatch_outside_physical_support": sorted(baseline_mismatch - support_union),
            "readout_effect_union_count": len(effect_union),
            "baseline_mismatch_outside_readout_effect_union": sorted(baseline_mismatch - effect_union),
            "group_conflict_edges": group_edges,
            "coordinate_conflict_edges": coordinate_edges,
            "constraint_action_rank": vector_rank(action_vectors),
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
        "scope": "derived_read_only_augmented_palette_support_audit",
        "entries": len(all_entries),
        "source_pair_motifs": 201,
        "source_singleton_advantages": 58,
        "zero_entries": sum(1 for x in all_entries if x["kind"] == "ZERO"),
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
