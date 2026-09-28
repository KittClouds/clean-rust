"""Materialize and audit the frozen LR1 successful-pair cohort.

This runner performs no search and writes only inside its own MAT1 root.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
LR1_SCRIPT = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"
sys.path.insert(0, str(LR1_SCRIPT))
sys.dont_write_bytecode = True
import run_lr1_case as LR1  # noqa: E402
import lr1_adapter as A  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"MAT1 refuses overwrite: {path}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    require(not tmp.exists(), f"MAT1 orphan temporary file: {tmp}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def replace_selection(selection: list[tuple[int, str]], group: int, identity: str):
    return [(g, identity if g == group else candidate) for g, candidate in selection]


def as_float_vector(raw: tuple[int, ...]) -> tuple[float, ...]:
    return tuple(A.f(value) for value in raw)


def l2(values) -> float:
    return math.sqrt(math.fsum(value * value for value in values))


def linear_drive(state, raw: tuple[int, ...]) -> tuple[float, ...]:
    weights = as_float_vector(raw)
    target = tuple(state.target_weights)
    return tuple(math.fsum(weights[index] - target[index] for index in row) for row in state.rows)


def signed_geometry(state, geometry: dict, raw: tuple[int, ...]) -> dict:
    target_linear = linear_drive(state, tuple(state.target_weight_bits))
    final_linear = linear_drive(state, raw)
    linear_debt = [a - b for a, b in zip(final_linear, target_linear)]
    return {
        "axis_debt": float(geometry["final_axis"] - geometry["target_axis"]),
        "norm_debt": float(geometry["final_norm"] - geometry["target_norm"]),
        "linear_drive_debt": linear_debt,
    }


def state_record(state, result: dict, raw: tuple[int, ...], selection, groups: dict) -> dict:
    baseline = tuple(int(value) for value in state.baseline_weight_bits)
    selected_map = {}
    for group_index, identity in selection:
        candidate = next(
            c for c in groups[group_index]["palette"]
            if str(c["candidate_identity"]) == str(identity)
        )
        for coordinate, prefix in candidate["canonical_mapping"]:
            selected_map[int(coordinate)] = int(prefix)
    changed = []
    for coordinate, (before, after) in enumerate(zip(baseline, raw)):
        if int(before) != int(after):
            changed.append([coordinate, int(selected_map.get(coordinate, 0)), int(after)])
    return {
        "selection": [[int(g), str(identity)] for g, identity in selection],
        "nonzero_coordinate_prefix": [[i, k] for i, k in sorted(selected_map.items()) if k != 0],
        "committed_f32_mapping": changed,
        "weight_bits_hash": result["weight_bits_hash"],
        "readout_bits": list(A.replay(state.rows, raw)),
        "readout_hash": result["readout_hash"],
        "score": result["score"],
        "geometry": result["geometry"],
        "signed_geometry": signed_geometry(state, result["geometry"], raw),
        "final_pass": bool(result["final_pass"]),
        "distinct_from_baseline": bool(result["distinct_b"]),
        "distinct_from_target": bool(result["distinct_t"]),
    }


def vector_interaction(left, a, b, base):
    return [x - y - z + w for x, y, z, w in zip(left, a, b, base)]


def vector_metrics(values) -> dict:
    abs_values = [abs(value) for value in values]
    return {
        "l0": sum(value != 0.0 for value in values),
        "l1": math.fsum(abs_values),
        "l2": l2(values),
        "linf": max(abs_values, default=0.0),
    }


def gate_signature(result: dict, thresholds: dict) -> list[str]:
    geometry = result["geometry"]
    return [
        key for key in ("axis_normalized_error", "norm_normalized_error", "cue_linear_normalized_error")
        if float(geometry[key]) > float(thresholds[key])
    ]


def load_rows(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("chunk-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


def verify_parents(contract: dict) -> None:
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"MAT1 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"MAT1 parent drift: {binding['label']}")


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    verify_parents(contract)
    output = ROOT / "qualification"
    output.mkdir(parents=True, exist_ok=True)
    execution_path = output / "execution.json"
    pairs_path = output / "materialized-pairs.jsonl"
    require(not execution_path.exists() and not pairs_path.exists(), "MAT1 output already exists")

    records = []
    verification_failures = []
    source_pairs = 0
    source_successes = 0
    case_counts = {}

    lr1_root = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1"
    for case_dir in sorted((lr1_root / "cases").iterdir()):
        if not case_dir.is_dir() or not (case_dir / "pairs" / "COMPLETE.json").exists():
            continue
        endpoint = case_dir.name.split("__set")[0] + ".json"
        set_index = int(case_dir.name.split("__set")[1])
        state, groups, par8_record, _, pf5_contract = LR1.load_case(endpoint, set_index)
        thresholds = LR1.thr_of(pf5_contract)
        search_selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8_record["best_search"]["selected_candidates"]]
        valid_selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8_record["best_valid"]["selected_candidates"]]
        context = hashlib.sha256(f"{endpoint}|{set_index}".encode()).hexdigest().upper()
        cache = A.ContextCache()
        search_result, _ = A.materialize(state, groups, search_selection, context, cache, pf5_contract)
        valid_result, _ = A.materialize(state, groups, valid_selection, context, cache, pf5_contract)
        raw_search = LR1.weight_bits_of(state, groups, search_selection)
        raw_valid = LR1.weight_bits_of(state, groups, valid_selection)
        baseline_result = {
            "weight_bits_hash": A.bits_hash(tuple(state.baseline_weight_bits)),
            "readout_hash": A.bits_hash(A.replay(state.rows, tuple(state.baseline_weight_bits))),
            "score": A.score_of(A.replay(state.rows, tuple(state.baseline_weight_bits)), A.replay(state.rows, tuple(state.target_weight_bits))),
            "geometry": LR1.RH1.PF5.geometry_metrics(state.rows, as_float_vector(tuple(state.baseline_weight_bits)), state.base_weights, state.target_weights, state.axis),
            "final_pass": False, "distinct_b": False, "distinct_t": True,
        }
        target_result = {
            "weight_bits_hash": A.bits_hash(tuple(state.target_weight_bits)),
            "readout_hash": A.bits_hash(A.replay(state.rows, tuple(state.target_weight_bits))),
            "score": A.score_of(A.replay(state.rows, tuple(state.target_weight_bits)), A.replay(state.rows, tuple(state.target_weight_bits))),
            "geometry": LR1.RH1.PF5.geometry_metrics(state.rows, state.target_weights, state.base_weights, state.target_weights, state.axis),
            "final_pass": True, "distinct_b": True, "distinct_t": False,
        }
        baseline_state = state_record(state, baseline_result, tuple(state.baseline_weight_bits), [], groups)
        invalid_state = state_record(state, search_result, raw_search, search_selection, groups)
        valid_state = state_record(state, valid_result, raw_valid, valid_selection, groups)
        singles = {int(row["domain_index"]): row for row in load_rows(case_dir / "singles")}
        pair_rows = [row for row in load_rows(case_dir / "pairs") if row["outcome"] == "VALID_ADVANTAGE_PRESERVED"]
        source_pairs += len(load_rows(case_dir / "pairs"))
        source_successes += len(pair_rows)
        case_counts[case_dir.name] = len(pair_rows)
        for pair in pair_rows:
            a = pair["a"]
            b = pair["b"]
            a_source = singles[int(a["domain_index"])]
            b_source = singles[int(b["domain_index"])]
            require(str(a_source["to"]) == str(a["to"]), "MAT1 singleton A identity drift")
            require(str(b_source["to"]) == str(b["to"]), "MAT1 singleton B identity drift")
            sel_a = replace_selection(search_selection, int(a["group"]), str(a["to"]))
            sel_b = replace_selection(search_selection, int(b["group"]), str(b["to"]))
            sel_ab = replace_selection(sel_a, int(b["group"]), str(b["to"]))
            result_a, _ = A.materialize(state, groups, sel_a, context, cache, pf5_contract)
            result_b, _ = A.materialize(state, groups, sel_b, context, cache, pf5_contract)
            result_ab, _ = A.materialize(state, groups, sel_ab, context, cache, pf5_contract)
            raw_a = LR1.weight_bits_of(state, groups, sel_a)
            raw_b = LR1.weight_bits_of(state, groups, sel_b)
            raw_ab = LR1.weight_bits_of(state, groups, sel_ab)
            checks = [
                (result_a["weight_bits_hash"], a_source["weight_hash"], "single_a_weight"),
                (result_b["weight_bits_hash"], b_source["weight_hash"], "single_b_weight"),
                (result_ab["weight_bits_hash"], pair["weight_hash"], "pair_weight"),
                (result_ab["readout_hash"], pair["readout_hash"], "pair_readout"),
                (result_ab["score"], pair["score"], "pair_score"),
                (result_ab["geometry"], pair["geometry"], "pair_geometry"),
            ]
            failed = [label for got, expected, label in checks if got != expected]
            if failed:
                verification_failures.append({"case": case_dir.name, "pair_index": pair["domain_index"], "fields": failed})
                continue
            state_a = state_record(state, result_a, raw_a, sel_a, groups)
            state_b = state_record(state, result_b, raw_b, sel_b, groups)
            state_ab = state_record(state, result_ab, raw_ab, sel_ab, groups)
            readout_s = as_float_vector(tuple(state_a["readout_bits"]))
            readout_a = as_float_vector(tuple(state_a["readout_bits"]))
            readout_b = as_float_vector(tuple(state_b["readout_bits"]))
            readout_ab = as_float_vector(tuple(state_ab["readout_bits"]))
            readout_interaction = vector_interaction(readout_ab, readout_a, readout_b, readout_s)
            linear_s = state_record(state, search_result, raw_search, search_selection, groups)["signed_geometry"]["linear_drive_debt"]
            linear_a = state_a["signed_geometry"]["linear_drive_debt"]
            linear_b = state_b["signed_geometry"]["linear_drive_debt"]
            linear_ab = state_ab["signed_geometry"]["linear_drive_debt"]
            linear_interaction = vector_interaction(linear_ab, linear_a, linear_b, linear_s)
            weights_s = as_float_vector(raw_search)
            weights_a = as_float_vector(raw_a)
            weights_b = as_float_vector(raw_b)
            weights_ab = as_float_vector(raw_ab)
            weight_interaction = vector_interaction(weights_ab, weights_a, weights_b, weights_s)
            axis_interaction = state_ab["signed_geometry"]["axis_debt"] - state_a["signed_geometry"]["axis_debt"] - state_b["signed_geometry"]["axis_debt"] + invalid_state["signed_geometry"]["axis_debt"]
            norm_interaction = state_ab["signed_geometry"]["norm_debt"] - state_a["signed_geometry"]["norm_debt"] - state_b["signed_geometry"]["norm_debt"] + invalid_state["signed_geometry"]["norm_debt"]
            additive_readout = [x + y - z for x, y, z in zip(readout_a, readout_b, readout_s)]
            target_readout = as_float_vector(tuple(state.target_weight_bits))
            pair_closer_rows = sum(abs(actual - target) < abs(predicted - target) for actual, predicted, target in zip(readout_ab, additive_readout, target_readout))
            records.append({
                "case": case_dir.name,
                "endpoint": endpoint,
                "set_index": set_index,
                "pair_domain_index": int(pair["domain_index"]),
                "source": {"a": a, "b": b, "single_a": a_source, "single_b": b_source, "pair": pair},
                "states": {"baseline": baseline_state, "invalid_search": invalid_state, "historical_valid": valid_state, "single_a": state_a, "single_b": state_b, "pair_ab": state_ab},
                "interactions": {
                    "weight_sparse": [[i, value] for i, value in enumerate(weight_interaction) if value != 0.0],
                    "weight_metrics": vector_metrics(weight_interaction),
                    "readout": readout_interaction,
                    "readout_metrics": vector_metrics(readout_interaction),
                    "linear_drive": linear_interaction,
                    "linear_drive_metrics": vector_metrics(linear_interaction),
                    "axis": axis_interaction,
                    "norm": norm_interaction,
                    "pair_closer_than_additive_rows": pair_closer_rows,
                },
                "component_gate_signatures": {"single_a": gate_signature(result_a, thresholds), "single_b": gate_signature(result_b, thresholds), "pair_ab": gate_signature(result_ab, thresholds)},
                "component_geometry_class": "BOTH_COMPONENTS_INVALID" if not a_source["final_pass"] and not b_source["final_pass"] else ("ONE_COMPONENT_VALID" if bool(a_source["final_pass"]) != bool(b_source["final_pass"]) else "BOTH_COMPONENTS_VALID"),
                "reconstruction": {"lr1_identity": "q10-gc1-cancel1-lr1-v1", "mat1_runner": digest(Path(__file__)), "parents_verified": True},
            })
    require(source_pairs == 3753, f"MAT1 source pair count drift: {source_pairs}")
    require(source_successes == 201, f"MAT1 successful pair count drift: {source_successes}")
    require(not verification_failures, f"MAT1 reconstruction failures: {verification_failures[:3]}")
    write_exclusive(pairs_path, "".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    execution = {
        "protocol": contract["protocol"],
        "identity": contract["identity"],
        "scope": "engineering_only_materialization_no_search",
        "source_pair_records": source_pairs,
        "successful_pairs": source_successes,
        "case_counts": case_counts,
        "verification_failures": verification_failures,
        "records_sha256": digest(pairs_path),
        "parents_unchanged": True,
        "checks_passed": True,
    }
    write_exclusive(execution_path, json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
