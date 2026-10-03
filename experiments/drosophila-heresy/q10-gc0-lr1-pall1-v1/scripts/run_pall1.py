from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys

REPO = pathlib.Path(r"C:/code land/clean-rust")
ROOT = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pall1-v1"
LR1 = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1"
sys.path.insert(0, str(LR1 / "scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_lr1_case as R  # noqa: E402
import run_rh1 as RH1  # noqa: E402

IDENTITY = "q10-gc0-lr1-pall1-v1"


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def source_cases():
    result = []
    for path in sorted((LR1 / "cases").iterdir()):
        if path.is_dir() and (path / "pairs" / "COMPLETE.json").exists():
            stem, set_text = path.name.split("__set", 1)
            result.append((stem + ".json", int(set_text)))
    require(len(result) == 8, f"PALL1 case drift: {len(result)}")
    return result


def case_name(endpoint: str, set_index: int) -> str:
    return f"{endpoint.replace('.json', '')}__set{set_index}"


def select_replace(selection, replacements):
    replacement_map = {int(group): str(identity) for group, identity in replacements}
    return [(int(group), replacement_map.get(int(group), str(identity))) for group, identity in selection]


def selected_map(groups, selection):
    mapping = {}
    for group, identity in selection:
        candidate = next(c for c in groups[int(group)]["palette"] if str(c["candidate_identity"]) == str(identity))
        for coordinate, prefix in candidate["canonical_mapping"]:
            coordinate, prefix = int(coordinate), int(prefix)
            require(coordinate not in mapping or mapping[coordinate] == prefix, f"PALL1 coordinate conflict {coordinate}")
            mapping[coordinate] = prefix
    return mapping


def raw_from_selection(state, groups, selection):
    return R.weight_bits_of(state, groups, selection)


def linear_drive(state, raw):
    weights = tuple(RH1.PF5.from_bits(x) for x in raw)
    return tuple(math.fsum(weights[i] - state.target_weights[i] for i in row) for row in state.rows)


def constraint_vector(state, geometry, raw):
    target = linear_drive(state, tuple(state.target_weight_bits))
    final = linear_drive(state, raw)
    return [float(geometry["final_axis"] - geometry["target_axis"]), float(geometry["final_norm"] - geometry["target_norm"]), *[float(a - b) for a, b in zip(final, target)]]


def load_case(endpoint, set_index):
    state, groups, par8, _, contract = R.load_case(endpoint, set_index)
    case = case_name(endpoint, set_index)
    source = R.read_chunks(LR1 / "cases" / case / "pairs")
    domain = json.loads((LR1 / "inventory" / "pairs-domain" / f"{case}.json").read_text(encoding="utf-8")) if (LR1 / "inventory" / "pairs-domain" / f"{case}.json").exists() else None
    return case, state, groups, par8, contract, source, domain


def materialize_pair(case, state, groups, selection, row, invalid_bits, target_bits, invalid_constraint, contract):
    a, b = row["a"], row["b"]
    pair_selection = select_replace(selection, [(a["group"], a["to"]), (b["group"], b["to"])])
    result, _ = A.materialize(state, groups, pair_selection, hashlib.sha256(case.encode()).hexdigest().upper(), A.ContextCache(), contract)
    raw = raw_from_selection(state, groups, pair_selection)
    readout = tuple(A.replay(state.rows, raw))
    require(result["readout_hash"] == A.bits_hash(readout), f"PALL1 replay hash drift {case} {row['domain_index']}")
    require(result["weight_bits_hash"] == str(row["weight_hash"]).upper(), f"PALL1 weight drift {case} {row['domain_index']}")
    require(result["readout_hash"] == str(row["readout_hash"]).upper(), f"PALL1 readout drift {case} {row['domain_index']}")
    for field in ("score", "geometry", "final_pass"):
        require(result[field] == row[field], f"PALL1 {field} drift {case} {row['domain_index']}")
    mapping = selected_map(groups, pair_selection)
    baseline = tuple(int(x) for x in state.baseline_weight_bits)
    changed = [[i, int(mapping.get(i, 0)), int(after)] for i, (before, after) in enumerate(zip(baseline, raw)) if int(before) != int(after)]
    s_mismatch = {i for i, (x, y) in enumerate(zip(invalid_bits, target_bits)) if x != y}
    entry_mismatch = {i for i, (x, y) in enumerate(zip(readout, target_bits)) if x != y}
    cv = constraint_vector(state, result["geometry"], raw)
    source_hash = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest().upper()
    return {
        "identity": f"{case}|PAIR_VALID_WORSE|domain={int(row['domain_index'])}",
        "case": case,
        "kind": "PAIR_VALID_WORSE",
        "pair_domain_index": int(row["domain_index"]),
        "a": a,
        "b": b,
        "selection": [[int(g), str(identity)] for g, identity in pair_selection],
        "nonzero_coordinate_prefix": [[int(i), int(k)] for i, k in sorted(mapping.items()) if int(k) != 0],
        "committed_f32_mapping": changed,
        "weight_bits_hash": result["weight_bits_hash"],
        "readout_bits": list(readout),
        "readout_hash": result["readout_hash"],
        "score": result["score"],
        "geometry": result["geometry"],
        "constraint_vector": cv,
        "constraint_action_from_S": [x - y for x, y in zip(cv, invalid_constraint)],
        "physical_support_rows": sorted(set(groups[int(a["group"])] ["physical_support_rows"]) | set(groups[int(b["group"])] ["physical_support_rows"])),
        "readout_changed_from_S_rows": sorted(i for i, (x, y) in enumerate(zip(readout, invalid_bits)) if x != y),
        "S_mismatch_rows": sorted(s_mismatch),
        "entry_mismatch_rows": sorted(entry_mismatch),
        "fixed_from_S_rows": sorted(s_mismatch - entry_mismatch),
        "damaged_from_S_rows": sorted(entry_mismatch - s_mismatch),
        "final_pass": bool(result["final_pass"]),
        "distinct_baseline": bool(result["distinct_b"]),
        "distinct_target": bool(result["distinct_t"]),
        "source_record_sha256": source_hash,
    }


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "qualification").mkdir(exist_ok=True)
    if not (ROOT / "CONTRACT.json").exists():
        bindings = []
        for path, label in [(LR1 / "CONTRACT.json", "LR1 contract"), (LR1 / "PREEXECUTION.json", "LR1 preexecution"), (LR1 / "scripts/lr1_adapter.py", "LR1 adapter"), (LR1 / "scripts/run_lr1_case.py", "LR1 runtime"), (REPO / "experiments/drosophila-heresy/q10-gc0-lr1-sall1-r2-v1/execution.json", "SALL1 execution")]:
            bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
        for endpoint, set_index in source_cases():
            case = case_name(endpoint, set_index)
            cdir = LR1 / "cases" / case / "pairs"
            for path in sorted(cdir.glob("chunk-*.jsonl")) + [cdir / "COMPLETE.json"] + sorted(cdir.glob("chunk-*.COMPLETE.json")):
                bindings.append({"label": f"LR1 pair source {path.name}", "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
        write(ROOT / "PLAN.md", {"identity": IDENTITY, "protocol": "PALL1_VALID_WORSE_PAIR_MATERIALIZATION", "scope": "engineering_only_exact_materialization_of_all_56_valid_worse_lr1_pairs", "no_global_assembly": True, "no_behavior": True})
        write(ROOT / "CONTRACT.json", {"identity": IDENTITY, "protocol": "PALL1_VALID_WORSE_PAIR_MATERIALIZATION", "expected_records": 56, "parent_bindings": bindings})
        write(ROOT / "PREEXECUTION.json", {"identity": IDENTITY, "protocol": "PALL1_VALID_WORSE_PAIR_MATERIALIZATION", "parent_bindings": bindings, "sealed": True})
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.exists() and digest(path) == binding["sha256"], f"PALL1 parent drift {binding['label']}")
    entries = []
    per_case = {}
    for endpoint, set_index in source_cases():
        case, state, groups, par8, pf5_contract, source, domain = load_case(endpoint, set_index)
        selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8["best_search"]["selected_candidates"]]
        invalid_result, _ = A.materialize(state, groups, selection, hashlib.sha256(case.encode()).hexdigest().upper(), A.ContextCache(), pf5_contract)
        invalid_raw = raw_from_selection(state, groups, selection)
        invalid_bits = tuple(A.replay(state.rows, invalid_raw))
        target_bits = tuple(A.replay(state.rows, tuple(state.target_weight_bits)))
        invalid_constraint = constraint_vector(state, invalid_result["geometry"], invalid_raw)
        selected = [row for row in source.values() if row["outcome"] == "VALID_WORSE_NON_SUCCESS"]
        for row in sorted(selected, key=lambda x: int(x["domain_index"])):
            entries.append(materialize_pair(case, state, groups, selection, row, invalid_bits, target_bits, invalid_constraint, pf5_contract))
        per_case[case] = len(selected)
    require(len(entries) == 56, f"PALL1 valid-worse count drift {len(entries)}")
    output = ROOT / "qualification/valid-worse-pairs.jsonl"
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in entries), encoding="utf-8", newline="\n")
    write(ROOT / "qualification/execution.json", {"identity": IDENTITY, "protocol": "PALL1_VALID_WORSE_PAIR_MATERIALIZATION", "status": "COMPLETE", "records": len(entries), "per_case": dict(sorted(per_case.items())), "library_sha256": digest(output), "checks_passed": True, "global_assembly": False, "scientific_promotion": False})
    print(json.dumps({"identity": IDENTITY, "records": len(entries), "per_case": per_case}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
