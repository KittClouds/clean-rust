"""Fresh current-lineage S-replacement singleton requalification.

The measured operation starts from the fresh PAR8 reference S state and
replaces exactly one raw group with one current palette candidate.  It never
reads historical LR1 results and never opens pair replay.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "REQUAL1-SREPLACE-SINGLES"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-singles-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_ROOT = DOMAIN_ROOT / "closures/twin-a"
CLOSURE_REPO = CLOSURE_ROOT / "repo"
BUILDER_ROOT = DOMAIN_ROOT / "scripts"
PF5_SCRIPTS = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
PALETTE = CLOSURE_REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
DOMAIN_EXECUTION = DOMAIN_ROOT / "execution.json"
SMOKE_EXECUTION = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-smoke-v1/execution.json"
SINGLES_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-singles-v1"
SINGLES_EXECUTION = SINGLES_ROOT / "execution.json"
PARITY_EXECUTION = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-parity-v1/execution.json"
KEYS = (
    ("seed9731-L-tau16.json", 2),
    ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1),
    ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0),
    ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2),
    ("seed9731-R-tau4.json", 3),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def bits_hash(values: list[int] | tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def object_hash(value: Any) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    require(not tmp.exists(), f"orphan temporary output exists: {tmp}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def case_slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_modules() -> tuple[Any, Any]:
    sys.path.insert(0, str(PF5_SCRIPTS))
    pf = importlib.import_module("run_q10_pf5")
    sys.path.insert(0, str(BUILDER_ROOT))
    builder = importlib.import_module("build_domain_closure")
    require(Path(pf.__file__).resolve() == (PF5_SCRIPTS / "run_q10_pf5.py").resolve(), "wrong PF5 module loaded")
    return pf, builder


def score_dict(pf: Any, actual: tuple[int, ...], target: tuple[int, ...]) -> dict[str, Any]:
    residuals = [pf.from_bits(a) - pf.from_bits(t) for a, t in zip(actual, target)]
    return {
        "mismatch_count": sum(a != t for a, t in zip(actual, target)),
        "total_ulp_distance": sum(pf.ulp_distance(pf.from_bits(a), pf.from_bits(t)) for a, t in zip(actual, target)),
        "residual_l2": math.sqrt(math.fsum(value * value for value in residuals)),
        "maximum_absolute_residual": max((abs(value) for value in residuals), default=0.0),
    }


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def mapping_bits(pf: Any, state: Any, mapping: list[list[int]]) -> tuple[int, ...]:
    bits = list(int(value) for value in state.baseline_weight_bits)
    seen: set[int] = set()
    for coordinate, choice in mapping:
        coordinate, choice = int(coordinate), int(choice)
        require(coordinate not in seen, f"duplicate mapping coordinate: {coordinate}")
        seen.add(coordinate)
        require(bool(state.permitted[coordinate]) and coordinate in state.interior, f"mapping outside permitted interior: {coordinate}")
        raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, f"illegal mapping prefix: {coordinate} {choice}")
        bits[coordinate] = int(raw)
    return tuple(bits)


def replay(pf: Any, state: Any, bits: tuple[int, ...], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    weights = tuple(pf.from_bits(raw) for raw in bits)
    readout = tuple(int(value) for value in pf.readout_bits(state.rows, weights))
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {
        "bits": bits,
        "weights": weights,
        "readout": readout,
        "readout_sha256": bits_hash(readout),
        "weight_state_sha256": bits_hash(bits),
        "score": score_dict(pf, readout, state.target_readout_bits),
        "geometry": geometry,
        "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract)),
    }


def qlinear(state: Any, weights: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(math.fsum(weights[index] - state.target_weights[index] for index in row) for row in state.rows)


def signed_axis(state: Any, geometry: dict[str, Any]) -> float:
    return (float(geometry["final_axis"]) - float(geometry["target_axis"])) / max(abs(float(geometry["target_axis"])), 1.0e-12)


def sign(value: float) -> int:
    return 1 if value > 0.0 else (-1 if value < 0.0 else 0)


def source_manifest() -> dict[str, Any]:
    paths = [
        ROOT / "PLAN.md",
        ROOT / "CONTRACT.json",
        Path(__file__),
        REF_ROOT / "execution.json",
        DOMAIN_ROOT / "execution.json",
        DOMAIN_ROOT / "closures/twin-a/MANIFEST.json",
        DOMAIN_ROOT / "closures/twin-a/DERIVED.json",
        SINGLES_EXECUTION,
        PARITY_EXECUTION,
        SMOKE_EXECUTION,
        PALETTE,
        PF5_CONTRACT,
        BUILDER_ROOT / "build_domain_closure.py",
        REF_ROOT / "scripts/run_ref.py",
        SINGLES_ROOT / "scripts/run_singles.py",
    ]
    entries = []
    for path in paths:
        require(path.is_file(), f"missing manifest input: {path}")
        entries.append({"path": path.relative_to(REPO).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
    for slug in sorted(json.loads(SINGLES_EXECUTION.read_text(encoding="utf-8"))["shard_hashes"]):
        path = SINGLES_ROOT / "shards" / f"{slug}.jsonl"
        require(path.is_file(), f"missing singleton shard: {path}")
        entries.append({"path": path.relative_to(REPO).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
    return {"protocol": PROTOCOL, "identity": IDENTITY, "entries": entries, "manifest_sha256": object_hash(entries)}


def load_inputs() -> tuple[Any, Any, dict[str, Any], dict[tuple[str, int], Any], dict[tuple[str, int, int], dict[str, Any]], dict[tuple[str, int, int, str], dict[str, Any]], dict[str, Any]]:
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "PLAN hash drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "runner hash drift")
    bindings = {str(item["label"]): item for item in contract["parent_bindings"]}
    for label, item in bindings.items():
        path = REPO / Path(str(item["path"]))
        require(path.is_file(), f"missing parent: {label}")
        require(digest(path) == str(item["sha256"]).upper(), f"parent drift: {label}")
    ref = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    domain = json.loads(DOMAIN_EXECUTION.read_text(encoding="utf-8"))
    smoke = json.loads(SMOKE_EXECUTION.read_text(encoding="utf-8"))
    singles = json.loads(SINGLES_EXECUTION.read_text(encoding="utf-8"))
    parity = json.loads(PARITY_EXECUTION.read_text(encoding="utf-8"))
    require(ref["status"] == "REQUAL1_PAR8_REFERENCE_COMPLETE", "fresh reference is not complete")
    require(domain["status"] == "DOMAIN_READY_FOR_SMOKE", "fresh domain status drift")
    require(smoke["status"] == "SMOKE_PASS", "fresh smoke gate drift")
    require(singles["status"] == "SINGLES_COMPLETE", "fresh singleton parent is not complete")
    require(parity["status"] == "PARITY_PASS", "fresh parity gate drift")
    require(ref["counts"]["endpoint_set_count"] == 8 and ref["counts"]["raw_group_count"] == 462, "fresh reference cardinality drift")
    require(singles["counts"]["nonzero_singletons"] == 3696, "fresh singleton cardinality drift")
    require(domain["counts"]["candidate_records_checked"] == 3696, "fresh palette cardinality drift")
    pf, builder = load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    groups = {key: {int(group.group_index): group for group in data["groups"][key]} for key in KEYS}
    require(set(states) == set(KEYS), "fresh state coverage drift")
    require(all(len(groups[key]) > 0 for key in KEYS), "fresh group coverage drift")
    palettes: dict[tuple[str, int, int], dict[str, Any]] = {}
    for line in PALETTE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["identity"][0]), int(item["identity"][1]), int(item["identity"][2]))
        if key[:2] in KEYS:
            palettes[key] = item
    require(len(palettes) == 462, "fresh palette group coverage drift")
    singleton_rows: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for key in KEYS:
        path = SINGLES_ROOT / "shards" / f"{case_slug(key)}.jsonl"
        expected_hash = str(singles["shard_hashes"][case_slug(key)]).upper()
        require(digest(path) == expected_hash, f"singleton shard hash drift: {key}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        require(len(rows) == len(groups[key]) * 8, f"singleton shard count drift: {key}")
        for row in rows:
            row_key = (str(row["endpoint"]), int(row["set_index"]), int(row["group"]), str(row["to"]))
            require(row_key not in singleton_rows, f"duplicate singleton row: {row_key}")
            singleton_rows[row_key] = row
    require(len(singleton_rows) == 3696, "singleton row index cardinality drift")
    return pf, builder, {"contract": contract, "ref": ref, "domain": domain, "smoke": smoke, "singles": singles, "parity": parity}, states, groups, palettes, singleton_rows


def verify_reference(pf: Any, state: Any, result: dict[str, Any], pf5_contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    s = result["best_search"]
    v = result["best_valid"]
    s_bits = mapping_bits(pf, state, s["canonical_mapping"])
    v_bits = mapping_bits(pf, state, v["canonical_mapping"])
    s_replayed = replay(pf, state, s_bits, pf5_contract)
    v_replayed = replay(pf, state, v_bits, pf5_contract)
    for label, expected, actual in (("S", s, s_replayed), ("V", v, v_replayed)):
        require(actual["weight_state_sha256"] == str(expected["weight_state_sha256"]).upper(), f"{label} weight hash drift: {state.key}")
        require(actual["readout_sha256"] == str(expected["readout_sha256"]).upper(), f"{label} readout hash drift: {state.key}")
        require(actual["score"] == expected["score"], f"{label} score drift: {state.key}")
        require(actual["geometry"] == expected["geometry"], f"{label} geometry drift: {state.key}")
        require(actual["final_geometry_pass"] is bool(expected["final_geometry_pass"]), f"{label} gate drift: {state.key}")
    require(not s_replayed["final_geometry_pass"] and v_replayed["final_geometry_pass"], f"S/V gate state drift: {state.key}")
    require(s_bits != v_bits, f"S/V identity drift: {state.key}")
    return s_replayed, v_replayed


def run_context(args: tuple[str, int, str]) -> tuple[tuple[str, int], list[dict[str, Any]]]:
    endpoint, set_index, repo_text = args
    sys.dont_write_bytecode = True
    pf, builder = load_modules()
    repo = Path(repo_text)
    _, data = builder.fresh_lineage(repo, pf)
    key = (endpoint, set_index)
    state = next(item for item in data["states"] if item.key == key)
    groups = {int(group.group_index): group for group in data["groups"][key]}
    ref = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref["results"] if str(item["endpoint"]) == endpoint and int(item["set_index"]) == set_index)
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    s_replayed, v_replayed = verify_reference(pf, state, ref_result, pf5_contract)
    s_map = {int(c): int(choice) for c, choice in ref_result["best_search"]["canonical_mapping"]}
    s_weights = s_replayed["weights"]
    s_qlinear = qlinear(state, s_weights)
    s_axis = signed_axis(state, s_replayed["geometry"])
    v_key = score_key(v_replayed["score"])
    target = tuple(state.target_readout_bits)
    palette_rows = {}
    for line in PALETTE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if str(item["identity"][0]) == endpoint and int(item["identity"][1]) == set_index:
            palette_rows[int(item["identity"][2])] = item
    single_rows = {}
    single_path = SINGLES_ROOT / "shards" / f"{case_slug(key)}.jsonl"
    for row in json.loads(single_path.read_text(encoding="utf-8")):
        single_rows[(int(row["group"]), str(row["to"]))] = row
    output: list[dict[str, Any]] = []
    for group_index in sorted(groups):
        group = groups[group_index]
        item = palette_rows.get(group_index)
        require(item is not None, f"missing palette group: {key} {group_index}")
        baseline_id = str(item["baseline"]["candidate_identity"])
        nonzero = [candidate for candidate in item["palette"] if str(candidate["candidate_identity"]) != baseline_id]
        require(len(nonzero) == 8, f"nonzero palette count drift: {key} {group_index}")
        group_coordinates = tuple(int(c) for c in group.coordinates)
        for candidate in nonzero:
            to_id = str(candidate["candidate_identity"])
            source = single_rows.get((group_index, to_id))
            require(source is not None, f"missing fresh singleton source row: {key} {group_index} {to_id}")
            canonical = [[int(c), int(choice)] for c, choice in candidate["canonical_mapping"]]
            require(tuple(c for c, _ in canonical) == group_coordinates, f"candidate topology drift: {key} {group_index}")
            require(source["canonical_mapping"] == canonical and str(source["to"]) == to_id, f"singleton source identity drift: {key} {group_index}")
            baseline_bits = list(state.baseline_weight_bits)
            for coordinate, choice, committed in candidate["committed_f32_mapping"]:
                coordinate, choice, committed = int(coordinate), int(choice), int(committed)
                expected = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
                require(expected is not None and int(expected) == committed, f"palette committed byte drift: {key} {group_index} {coordinate}")
                baseline_bits[coordinate] = committed
            require(bits_hash(baseline_bits) == str(source["weight_state_sha256"]).upper(), f"singleton source weight drift: {key} {group_index}")
            candidate_bits = list(s_replayed["bits"])
            for coordinate, choice, committed in candidate["committed_f32_mapping"]:
                coordinate = int(coordinate)
                require(coordinate in group_coordinates, f"candidate coordinate outside group: {key} {group_index}")
                candidate_bits[coordinate] = int(committed)
            candidate_bits = tuple(candidate_bits)
            candidate_replayed = replay(pf, state, candidate_bits, pf5_contract)
            fixed = sum(a != t and b == t for a, b, t in zip(s_replayed["readout"], candidate_replayed["readout"], target))
            damaged = sum(a == t and b != t for a, b, t in zip(s_replayed["readout"], candidate_replayed["readout"], target))
            ql = qlinear(state, candidate_replayed["weights"])
            d_lin = tuple(a - b for a, b in zip(ql, s_qlinear))
            opp = -math.fsum(a * b for a, b in zip(d_lin, s_qlinear))
            d_axis = signed_axis(state, candidate_replayed["geometry"]) - s_axis
            gates = pf5_contract["geometry"]["final_da2_gates"]
            ratios = {
                "axis": float(candidate_replayed["geometry"]["axis_normalized_error"]) / float(gates["axis_normalized_abs"]),
                "norm": float(candidate_replayed["geometry"]["norm_normalized_error"]) / float(gates["norm_normalized_abs"]),
                "linear": float(candidate_replayed["geometry"]["cue_linear_normalized_error"]) / float(gates["cue_linear_normalized_abs"]),
            }
            changed = sum(a != b for a, b in zip(s_replayed["bits"], candidate_bits))
            output.append({
                "endpoint": endpoint,
                "set_index": set_index,
                "group": group_index,
                "from": baseline_id,
                "to": to_id,
                "source_singleton_weight_state_sha256": str(source["weight_state_sha256"]).upper(),
                "source_singleton_readout_sha256": str(source["readout_sha256"]).upper(),
                "canonical_mapping": canonical,
                "replacement_changed_coordinate_count": changed,
                "weight_state_sha256": candidate_replayed["weight_state_sha256"],
                "readout_sha256": candidate_replayed["readout_sha256"],
                "score": candidate_replayed["score"],
                "score_key": list(score_key(candidate_replayed["score"])),
                "historical_valid_score_key": list(v_key),
                "strictly_better_than_V": score_key(candidate_replayed["score"]) < v_key,
                "geometry": candidate_replayed["geometry"],
                "final_geometry_pass": candidate_replayed["final_geometry_pass"],
                "fixed": fixed,
                "damaged": damaged,
                "d_axis": d_axis,
                "opp": opp,
                "ratios": ratios,
                "max_ratio": max(ratios.values()),
                "excess": sum(max(0.0, value - 1.0) for value in ratios.values()),
                "bucket": [group_index, sign(d_axis), sign(opp)],
            })
    require(len(output) == len(groups) * 8, f"context cardinality drift: {key}")
    return key, output


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "S-replacement execution already exists")
    pf, builder, inputs, states, groups, palettes, singleton_rows = load_inputs()
    manifest = source_manifest()
    write_new(ROOT / "ROOT_MANIFEST.json", manifest)
    all_rows: dict[str, list[dict[str, Any]]] = {}
    try:
        closure = str(CLOSURE_REPO)
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_context, (key[0], key[1], closure)) for key in KEYS]
            for future in futures:
                key, rows = future.result()
                slug = case_slug(key)
                all_rows[slug] = rows
                write_new(ROOT / "shards" / f"{slug}.jsonl", rows)
                print(json.dumps({"context": [key[0], key[1]], "status": "SREPLACE_SINGLETONS_COMPLETE", "records": len(rows)}, sort_keys=True), flush=True)
        ordered = [row for key in KEYS for row in all_rows[case_slug(key)]]
        require(len(ordered) == 3696, f"total cardinality drift: {len(ordered)}")
        shard_hashes = {slug: digest(ROOT / "shards" / f"{slug}.jsonl") for slug in sorted(all_rows)}
        valid = sum(bool(row["final_geometry_pass"]) for row in ordered)
        advantage = sum(bool(row["final_geometry_pass"] and row["strictly_better_than_V"]) for row in ordered)
        execution = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": "SREPLACE_SINGLETONS_COMPLETE",
            "engineering_only": True,
            "scientific_promotion": False,
            "behavioral_probe": False,
            "pair_replay_executed": False,
            "historical_lr1_results_used_as_evidence": False,
            "semantics": "fresh S-replacement: replace one group in fresh invalid S, compare against fresh valid V",
            "contexts": [[key[0], key[1]] for key in KEYS],
            "counts": {"contexts": 8, "groups": 462, "nonzero_singletons": len(ordered), "valid_geometry": valid, "valid_strictly_better_than_V": advantage},
            "parent_execution_sha256": {"reference": digest(REF_ROOT / "execution.json"), "domain": digest(DOMAIN_EXECUTION), "smoke": digest(SMOKE_EXECUTION), "singles": digest(SINGLES_EXECUTION), "parity": digest(PARITY_EXECUTION)},
            "closure": {"manifest_sha256": digest(CLOSURE_ROOT / "MANIFEST.json"), "derived_sha256": digest(CLOSURE_ROOT / "DERIVED.json")},
            "palette_sha256": digest(PALETTE),
            "pf5_contract_sha256": digest(PF5_CONTRACT),
            "source_manifest_sha256": manifest["manifest_sha256"],
            "shard_hashes": shard_hashes,
        }
        write_new(ROOT / "execution.json", execution)
        status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "pair_replay_executed": False, "execution_sha256": digest(ROOT / "execution.json")}
        write_new(ROOT / "STATUS.json", status)
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_SREPLACE_SINGLETONS", "engineering_only": True, "scientific_promotion": False, "pair_replay_executed": False, "error_type": type(exc).__name__, "error": str(exc), "completed_shards": sorted(all_rows)}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
