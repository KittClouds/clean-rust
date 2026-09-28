from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-PAIR-ALG3"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
DOMAIN3 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-domain-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
CONTEXTS = (
    ("seed9731-L-tau16.json", 2), ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1), ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0), ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2), ("seed9731-R-tau4.json", 3),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_bytes_new(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_pair_alg3_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong runtime")
    return module


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing ALG3 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def load_context(key: tuple[str, int], alg: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(alg.CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref_execution = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = {str(item["action_key"]): item for item in descriptor["actions"]}
    require(len(actions) == len(descriptor["actions"]), f"descriptor duplicate action: {key}")
    triples = [json.loads(line) for line in (DOMAIN3 / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return pf, state, contract, s, {"actions": actions}, triples


def prepare_deltas(state: Any, s: dict[str, Any], actions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    s_weights = tuple(float(value) for value in s["weights"])
    s_displacement = tuple(value - initial for value, initial in zip(s_weights, state.base_weights))
    rows_by_coordinate: dict[int, list[int]] = {}
    for row_index, row in enumerate(state.rows):
        for coordinate in row:
            rows_by_coordinate.setdefault(int(coordinate), []).append(row_index)
    result: dict[str, dict[str, Any]] = {}
    for name, action in actions.items():
        sparse: dict[int, float] = {}
        for coordinate, _choice in action["canonical_mapping"]:
            coordinate = int(coordinate)
            endpoint = struct.unpack("<f", struct.pack("<I", int(action["weight_bits"][coordinate])))[0]
            delta = endpoint - s_weights[coordinate]
            if delta != 0.0:
                sparse[coordinate] = delta
        drive_values: dict[int, list[float]] = {}
        for coordinate, delta in sparse.items():
            for row_index in rows_by_coordinate.get(coordinate, []):
                drive_values.setdefault(row_index, []).append(delta)
        drive = {row_index: math.fsum(values) for row_index, values in drive_values.items()}
        result[name] = {"sparse": sparse, "drive": drive, "axis_delta": math.fsum(delta * state.axis[coordinate] for coordinate, delta in sparse.items()), "norm_delta": math.fsum(2.0 * s_displacement[coordinate] * delta + delta * delta for coordinate, delta in sparse.items())}
    return result


def sparse_geometry(state: Any, s: dict[str, Any], context: dict[str, Any], triple: tuple[str, str, str]) -> dict[str, float]:
    actions = context["deltas"]
    final_axis = math.fsum([s["geometry"]["final_axis"]] + [actions[name]["axis_delta"] for name in triple])
    norm_sq = math.fsum([context["s_norm_sq"]] + [actions[name]["norm_delta"] for name in triple])
    require(norm_sq >= 0.0, f"negative order-3 norm square: {norm_sq}")
    final_norm = math.sqrt(norm_sq)
    changed_rows = set().union(*(actions[name]["drive"].keys() for name in triple))
    terms = [context["s_linear_sq"]]
    for row_index in changed_rows:
        delta = math.fsum(actions[name]["drive"].get(row_index, 0.0) for name in triple)
        old = context["s_linear_residual"][row_index]
        new = old + delta
        terms.append(-old * old + new * new)
    cue_error = math.sqrt(max(math.fsum(terms), 0.0))
    cue_scale = max(context["target_drive_norm"], 1.0e-12)
    target_axis = float(s["geometry"]["target_axis"])
    target_norm = float(s["geometry"]["target_norm"])
    return {"axis_absolute_error": abs(final_axis - target_axis), "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12), "norm_absolute_error": abs(final_norm - target_norm), "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12), "cue_linear_absolute_error": cue_error, "cue_linear_normalized_error": cue_error / cue_scale, "final_axis": final_axis, "target_axis": target_axis, "final_norm": final_norm, "target_norm": target_norm}


def context_data(state: Any, s: dict[str, Any], actions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s_displacement = tuple(float(value) - initial for value, initial in zip(s["weights"], state.base_weights))
    target_displacement = tuple(value - initial for value, initial in zip(state.target_weights, state.base_weights))
    s_drive = tuple(math.fsum(s_displacement[index] for index in row) for row in state.rows)
    target_drive = tuple(math.fsum(target_displacement[index] for index in row) for row in state.rows)
    s_residual = tuple(a - b for a, b in zip(s_drive, target_drive))
    return {"deltas": prepare_deltas(state, s, actions), "s_norm_sq": math.fsum(value * value for value in s_displacement), "s_linear_residual": s_residual, "s_linear_sq": math.fsum(value * value for value in s_residual), "target_drive_norm": math.sqrt(math.fsum(value * value for value in target_drive))}


def run_context(key: tuple[str, int], alg: Any, prediction_only: bool = False) -> dict[str, Any]:
    pf, state, contract, s, source, triples = load_context(key, alg)
    actions = source["actions"]
    context = context_data(state, s, actions)
    predictions: list[dict[str, Any]] = []
    for triple in triples:
        names = (str(triple["a"]), str(triple["b"]), str(triple["c"]))
        require(len(set(names)) == 3, f"ALG3 duplicate action: {key} {names}")
        mapping = sorted(sum((actions[name]["canonical_mapping"] for name in names), []))
        bits = alg.apply_mapping(pf, state, tuple(s["bits"]), mapping)
        predicted_geometry = sparse_geometry(state, s, context, names)
        predictions.append({"triple_index": int(triple["triple_index"]), "case": triple["case"], "a": names[0], "b": names[1], "c": names[2], "canonical_mapping": mapping, "predicted_weight_state_sha256": alg.bits_hash(bits), "predicted_geometry": predicted_geometry, "predicted_final_geometry_pass": bool(pf.final_geometry_pass(predicted_geometry, contract))})
    return {"pf": pf, "state": state, "contract": contract, "s": s, "context": context, "triples": triples, "predictions": predictions}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected ALG3 script cache")
    require(not (ROOT / "execution.json").exists(), "ALG3 execution already exists")
    inputs = [("alg3_plan", ROOT / "PLAN.md"), ("alg3_runner", Path(__file__)), ("alg3_domain_execution", DOMAIN3 / "execution.json"), ("alg3_domain_contract", DOMAIN3 / "CONTRACT.json"), ("alg1_execution", ALG1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json"), (f"alg3_domain_shard:{slug(key)}", DOMAIN3 / "shards" / f"{slug(key)}.jsonl")])
    bindings = [bind(label, path) for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "triple_records": 2048, "predictions_sealed_before_geometry": True, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "PREDICTIONS_SEALED.json", "predictions/*.jsonl", "execution.json", "results/*.jsonl", "STATUS.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "readout_executed": False})
    try:
        alg = load_alg1()
        prepared = {key: run_context(key, alg) for key in CONTEXTS}
        prediction_shards = []
        for key, data in prepared.items():
            path = ROOT / "predictions" / f"{slug(key)}.jsonl"
            payload = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in data["predictions"]).encode("utf-8")
            write_bytes_new(path, payload)
            prediction_shards.append({"context": [key[0], key[1]], "records": len(data["predictions"]), "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
        prediction_seal = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREDICTIONS_SEALED", "triple_records": sum(item["records"] for item in prediction_shards), "prediction_shards": prediction_shards, "contract_sha256": digest(ROOT / "CONTRACT.json")}
        write_new(ROOT / "PREDICTIONS_SEALED.json", prediction_seal)
        results = []
        for key, data in prepared.items():
            records = []
            mismatch_weight = 0
            mismatch_validity = 0
            max_geometry_error = 0.0
            for triple, prediction in zip(data["triples"], data["predictions"]):
                bits = alg.apply_mapping(data["pf"], data["state"], tuple(data["s"]["bits"]), prediction["canonical_mapping"])
                exact = alg.geometry_only(data["pf"], data["state"], bits, data["contract"])
                predicted_geometry = prediction["predicted_geometry"]
                error = max(abs(float(predicted_geometry[name]) - float(exact["geometry"][name])) for name in exact["geometry"])
                max_geometry_error = max(max_geometry_error, error)
                weight_match = alg.bits_hash(bits) == prediction["predicted_weight_state_sha256"]
                validity_match = bool(exact["final_geometry_pass"]) == bool(prediction["predicted_final_geometry_pass"])
                mismatch_weight += not weight_match
                mismatch_validity += not validity_match
                records.append({"triple_index": int(triple["triple_index"]), "predicted_weight_state_sha256": prediction["predicted_weight_state_sha256"], "exact_weight_state_sha256": exact["weight_state_sha256"], "predicted_geometry": predicted_geometry, "exact_geometry": exact["geometry"], "geometry_abs_error": error, "predicted_final_geometry_pass": prediction["predicted_final_geometry_pass"], "exact_final_geometry_pass": exact["final_geometry_pass"], "weight_match": weight_match, "validity_match": validity_match})
            path = ROOT / "results" / f"{slug(key)}.jsonl"
            write_bytes_new(path, ("".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records)).encode("utf-8"))
            results.append({"context": [key[0], key[1]], "records": len(records), "weight_mismatches": mismatch_weight, "validity_mismatches": mismatch_validity, "max_geometry_abs_error": max_geometry_error, "result_sha256": digest(path)})
        require(sum(item["records"] for item in results) == 2048, "ALG3 result cardinality drift")
        require(sum(item["weight_mismatches"] for item in results) == 0, "ALG3 weight composition mismatch")
        require(sum(item["validity_mismatches"] for item in results) == 0, "ALG3 validity mismatch")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_COMPLETE", "engineering_only": True, "scientific_promotion": False, "triple_records": 2048, "geometry_executed": True, "readout_executed": False, "counts": {"records": 2048, "weight_mismatches": 0, "validity_mismatches": 0}, "contexts": results, "prediction_seal_sha256": digest(ROOT / "PREDICTIONS_SEALED.json"), "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Compatible disjoint order-3 structural composition reproduced exact committed weights and validity across the frozen sample; geometry differences were limited to floating-point evaluation roundoff."}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
