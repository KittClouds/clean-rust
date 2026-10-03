from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-PAIR-EXH1"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
UVD0 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-uvd0-v1"
UPAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
CONTEXTS = (
    "seed9731-L-tau16__set2",
    "seed9731-L-tau4__set3",
    "seed9731-R-tau16__set1",
    "seed9731-R-tau16__set3",
    "seed9731-R-tau4__set0",
    "seed9731-R-tau4__set1",
    "seed9731-R-tau4__set2",
    "seed9731-R-tau4__set3",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


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


def write_bytes_new(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def slug_key(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def key_from_slug(slug: str) -> tuple[str, int]:
    endpoint, set_text = slug.rsplit("__set", 1)
    return endpoint + ".json", int(set_text)


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_pair_exh1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prepare_context(key: tuple[str, int], alg: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref_execution = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, pf5_contract)
    s_weights = tuple(pf.from_bits(raw) for raw in s["bits"])
    s_displacement = tuple(value - initial for value, initial in zip(s_weights, state.base_weights))
    target_displacement = tuple(value - initial for value, initial in zip(state.target_weights, state.base_weights))
    s_drive = tuple(math.fsum(s_displacement[index] for index in row) for row in state.rows)
    target_drive = tuple(math.fsum(target_displacement[index] for index in row) for row in state.rows)
    s_linear_residual = tuple(final - target for final, target in zip(s_drive, target_drive))
    actions: dict[str, dict[str, Any]] = {}
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug_key(key)}.json").read_text(encoding="utf-8"))
    rows_by_coordinate: dict[int, list[int]] = defaultdict(list)
    for row_index, row in enumerate(state.rows):
        for coordinate in row:
            rows_by_coordinate[int(coordinate)].append(row_index)
    for item in descriptor["actions"]:
        sparse: dict[int, float] = {}
        for coordinate, _choice in item["canonical_mapping"]:
            coordinate = int(coordinate)
            delta = pf.from_bits(int(item["weight_bits"][coordinate])) - s_weights[coordinate]
            if delta != 0.0:
                sparse[coordinate] = delta
        drive_values: dict[int, list[float]] = defaultdict(list)
        for coordinate, delta in sparse.items():
            for row_index in rows_by_coordinate[coordinate]:
                drive_values[row_index].append(delta)
        drive = {row_index: math.fsum(values) for row_index, values in drive_values.items()}
        axis_delta = math.fsum(delta * state.axis[coordinate] for coordinate, delta in sparse.items())
        norm_delta = math.fsum(2.0 * s_displacement[coordinate] * delta + delta * delta for coordinate, delta in sparse.items())
        actions[str(item["action_key"])] = {"group": int(item["group"]), "to": str(item["to"]), "mapping": item["canonical_mapping"], "sparse": sparse, "drive": dict(drive), "axis_delta": axis_delta, "norm_delta": norm_delta}
    u_pair_rows = {}
    for line in (UPAIR / "shards" / f"{slug_key(key)}.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        u_pair_rows[int(item["source_uvd0_pair_index"])] = item
    return pf, state, pf5_contract, s, actions, {
        "s_weights": s_weights,
        "s_displacement": s_displacement,
        "s_norm_sq": math.fsum(value * value for value in s_displacement),
        "s_linear_residual": s_linear_residual,
        "s_linear_sq": math.fsum(value * value for value in s_linear_residual),
        "target_drive_norm": math.sqrt(math.fsum(value * value for value in target_drive)),
        "validation": u_pair_rows,
    }


def fast_geometry(pf: Any, state: Any, s: dict[str, Any], context: dict[str, Any], a: dict[str, Any], b: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    overlap = a["sparse"].keys() & b["sparse"].keys()
    require(not overlap, f"fast evaluator coordinate overlap: {sorted(overlap)}")
    final_axis = math.fsum((s["geometry"]["final_axis"], a["axis_delta"], b["axis_delta"]))
    final_norm_sq = math.fsum((context["s_norm_sq"], a["norm_delta"], b["norm_delta"]))
    require(final_norm_sq >= 0.0, f"negative composed norm square: {final_norm_sq}")
    final_norm = math.sqrt(final_norm_sq)

    changed_rows = a["drive"].keys() | b["drive"].keys()
    cue_terms = [context["s_linear_sq"]]
    for row_index in changed_rows:
        delta = math.fsum((a["drive"].get(row_index, 0.0), b["drive"].get(row_index, 0.0)))
        old_residual = context["s_linear_residual"][row_index]
        new_residual = old_residual + delta
        cue_terms.append(-old_residual * old_residual + new_residual * new_residual)
    cue_sq = math.fsum(cue_terms)
    require(cue_sq >= -1.0e-15, f"negative composed cue square: {cue_sq}")
    cue_error = math.sqrt(max(cue_sq, 0.0))
    cue_scale = max(context["target_drive_norm"], 1.0e-12)
    target_axis = float(s["geometry"]["target_axis"])
    target_norm = float(s["geometry"]["target_norm"])
    geometry = {
        "axis_absolute_error": abs(final_axis - target_axis),
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12),
        "norm_absolute_error": abs(final_norm - target_norm),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12),
        "cue_linear_absolute_error": cue_error,
        "cue_linear_normalized_error": cue_error / cue_scale,
        "final_axis": final_axis,
        "target_axis": target_axis,
        "final_norm": final_norm,
        "target_norm": target_norm,
    }
    return {"geometry": geometry, "final_geometry_pass": bool(pf.final_geometry_pass(geometry, contract))}


def geometry_error(expected: dict[str, Any], actual: dict[str, Any]) -> float:
    return max(abs(float(expected[name]) - float(actual[name])) for name in expected)


def run_context(key: tuple[str, int]) -> dict[str, Any]:
    alg = load_alg1()
    pf, state, pf5_contract, s, actions, context = prepare_context(key, alg)
    uvd0_rows = [json.loads(line) for line in (UVD0 / "shards" / f"{slug_key(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    valid_records = []
    degree: dict[str, int] = defaultdict(int)
    validation_count = 0
    validation_mismatch = 0
    max_geometry_error = 0.0
    for row in uvd0_rows:
        a_id = f"{int(row['a']['group'])}:{str(row['a']['to'])}"
        b_id = f"{int(row['b']['group'])}:{str(row['b']['to'])}"
        require(a_id in actions and b_id in actions, f"missing action descriptor: {key} {row['pair_index']}")
        result = fast_geometry(pf, state, s, context, actions[a_id], actions[b_id], pf5_contract)
        source_pair_index = int(row["pair_index"])
        reference = context["validation"].get(source_pair_index)
        if reference is not None:
            validation_count += 1
            expected_geometry = reference["ab"]["geometry"]
            max_geometry_error = max(max_geometry_error, geometry_error(expected_geometry, result["geometry"]))
            if bool(reference["ab"]["final_geometry_pass"]) != bool(result["final_geometry_pass"]):
                validation_mismatch += 1
        if result["final_geometry_pass"]:
            valid_records.append({"exh1_pair_index": len(valid_records), "source_uvd0_pair_index": source_pair_index, "case": key, "a": row["a"], "b": row["b"], "geometry": result["geometry"], "final_geometry_pass": True})
            degree[a_id] += 1
            degree[b_id] += 1
    require(validation_count == len(context["validation"]), f"validation coverage drift: {key} {validation_count} != {len(context['validation'])}")
    require(validation_mismatch == 0, f"fast validity mismatch against UPAIR1: {key} count={validation_mismatch}")
    shard = ROOT / "valid-frontier" / f"{slug_key(key)}.jsonl"
    degree_path = ROOT / "degrees" / f"{slug_key(key)}.json"
    write_bytes_new(shard, "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in valid_records).encode("utf-8"))
    write_new(degree_path, dict(sorted(degree.items())))
    return {"context": [key[0], key[1]], "parent_pairs": len(uvd0_rows), "valid_pairs": len(valid_records), "validation_pairs": validation_count, "validation_mismatches": validation_mismatch, "max_geometry_abs_error": max_geometry_error, "frontier_sha256": digest(shard), "degree_sha256": digest(degree_path), "min_valid_degree": min(degree.values(), default=0), "max_valid_degree": max(degree.values(), default=0), "nonzero_degree_actions": sum(value > 0 for value in degree.values())}


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing EXH1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "EXH1 execution already exists")
    inputs = [("exh1_plan", ROOT / "PLAN.md"), ("exh1_runner", Path(__file__)), ("uvd0_execution", UVD0 / "execution.json"), ("uvd0_contract", UVD0 / "CONTRACT.json"), ("upair_execution", UPAIR / "execution.json"), ("alg1_execution", ALG1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for context in CONTEXTS:
        inputs.extend([(f"uvd0_shard:{context}", UVD0 / "shards" / f"{context}.jsonl"), (f"upair_shard:{context}", UPAIR / "shards" / f"{context}.jsonl"), (f"alg1_descriptor:{context}", ALG1 / "descriptors" / f"{context}.json")])
    bindings = [bind(label, path) for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "parent_census_pairs": 840704, "validation_parent_pairs": 17712, "pair_replay_performed": False, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "valid-frontier/*.jsonl", "degrees/*.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "pair_replay_performed": False, "readout_executed": False})
    results = []
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_context, key_from_slug(context)) for context in CONTEXTS]
            for future in futures:
                result = future.result()
                results.append(result)
                print(json.dumps(result, sort_keys=True), flush=True)
        require(sum(item["parent_pairs"] for item in results) == 840704, "EXH1 parent cardinality drift")
        require(sum(item["validation_pairs"] for item in results) == 17712, "EXH1 validation cardinality drift")
        require(sum(item["validation_mismatches"] for item in results) == 0, "EXH1 validation mismatch")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PAIR_EXH1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "readout_executed": False, "counts": {"contexts": 8, "parent_pairs": sum(item["parent_pairs"] for item in results), "valid_pairs": sum(item["valid_pairs"] for item in results), "validation_pairs": sum(item["validation_pairs"] for item in results), "validation_mismatches": sum(item["validation_mismatches"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "frontier_ready_for_front1": True}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "readout_executed": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_PAIR_EXH1", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "readout_executed": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
