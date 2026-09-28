from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-ALG1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-alg1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN_ROOT / "closures/twin-a/repo"
PF5_SCRIPTS = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
BUILDER_ROOT = DOMAIN_ROOT / "scripts"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
SINGLES_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-singles-v1"
UPAIR_DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-domain-v1"
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


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def object_hash(value: Any) -> str:
    return digest_bytes(canonical(value))


def bits_hash(values: tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


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


def apply_mapping(pf: Any, state: Any, source_bits: tuple[int, ...], mapping: list[list[int]]) -> tuple[int, ...]:
    bits = list(source_bits)
    seen: set[int] = set()
    for coordinate, choice in mapping:
        coordinate, choice = int(coordinate), int(choice)
        require(coordinate not in seen, f"duplicate action coordinate: {coordinate}")
        seen.add(coordinate)
        raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, f"illegal action prefix: {coordinate} {choice}")
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
        "weight_state_sha256": bits_hash(bits),
        "readout_sha256": bits_hash(readout),
        "score": score_dict(pf, readout, state.target_readout_bits),
        "geometry": geometry,
        "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract)),
    }


def geometry_only(pf: Any, state: Any, bits: tuple[int, ...], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    weights = tuple(pf.from_bits(raw) for raw in bits)
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {
        "bits": bits,
        "weights": weights,
        "weight_state_sha256": bits_hash(bits),
        "geometry": geometry,
        "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract)),
    }


def f32_additive(pf: Any, left: int, right: int, subtract: int) -> int:
    value = pf.f32(pf.from_bits(left) + pf.from_bits(right))
    return int(pf.bits(pf.f32(value - pf.from_bits(subtract))))


def linear_vector(state: Any, weights: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(math.fsum(weights[index] - state.base_weights[index] for index in row) for row in state.rows)


def signed_constraint(state: Any, result: dict[str, Any]) -> dict[str, Any]:
    geometry = result["geometry"]
    final_drive = linear_vector(state, result["weights"])
    target_drive = tuple(float(value) for value in state.target_drive)
    linear_residual = tuple(a - b for a, b in zip(final_drive, target_drive))
    return {
        "axis_residual": float(geometry["final_axis"] - geometry["target_axis"]),
        "norm_residual": float(geometry["final_norm"] - geometry["target_norm"]),
        "linear_residual": linear_residual,
    }


def verify_reference(pf: Any, state: Any, ref_result: dict[str, Any], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    s_bits = apply_mapping(pf, state, tuple(state.baseline_weight_bits), ref_result["best_search"]["canonical_mapping"])
    s = replay(pf, state, s_bits, pf5_contract)
    expected = ref_result["best_search"]
    require(s["weight_state_sha256"] == str(expected["weight_state_sha256"]).upper(), f"S weight drift: {state.key}")
    require(s["readout_sha256"] == str(expected["readout_sha256"]).upper(), f"S readout drift: {state.key}")
    require(s["score"] == expected["score"] and s["geometry"] == expected["geometry"], f"S receipt drift: {state.key}")
    require(not s["final_geometry_pass"], f"S unexpectedly valid: {state.key}")
    return s


def action_key(group: int, to: str) -> str:
    return f"{group}:{to}"


def action_record(pf: Any, state: Any, s: dict[str, Any], row: dict[str, Any], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    mapping = [[int(c), int(choice)] for c, choice in row["canonical_mapping"]]
    bits = apply_mapping(pf, state, s["bits"], mapping)
    result = replay(pf, state, bits, pf5_contract)
    require(result["weight_state_sha256"] == str(row["weight_state_sha256"]).upper(), f"singleton action weight drift: {state.key} {row['group']} {row['to']}")
    require(result["readout_sha256"] == str(row["readout_sha256"]).upper(), f"singleton action readout drift: {state.key} {row['group']} {row['to']}")
    return {
        "group": int(row["group"]),
        "to": str(row["to"]),
        "action_key": action_key(int(row["group"]), str(row["to"])),
        "canonical_mapping": mapping,
        "weight_state_sha256": result["weight_state_sha256"],
        "readout_sha256": result["readout_sha256"],
        "weight_bits": list(result["bits"]),
        "readout_bits": list(result["readout"]),
        "score": result["score"],
        "score_key": list(score_key(result["score"])),
        "geometry": result["geometry"],
        "constraint": signed_constraint(state, result),
        "final_geometry_pass": bool(result["final_geometry_pass"]),
    }


def prediction(pf: Any, state: Any, s: dict[str, Any], a: dict[str, Any], b: dict[str, Any], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    structural_bits = list(s["bits"])
    seen: set[int] = set()
    for action in (a, b):
        for coordinate, choice in action["canonical_mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            require(coordinate not in seen, f"pair coordinate conflict: {coordinate}")
            seen.add(coordinate)
            raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
            require(raw is not None, f"pair structural prefix illegal: {coordinate} {choice}")
            structural_bits[coordinate] = int(raw)
    structural_bits = tuple(structural_bits)
    additive_weight_bits = tuple(f32_additive(pf, aa, bb, ss) for aa, bb, ss in zip(a["weight_bits"], b["weight_bits"], s["bits"]))
    additive_readout_bits = tuple(f32_additive(pf, aa, bb, ss) for aa, bb, ss in zip(a["readout_bits"], b["readout_bits"], s["readout_bits"]))
    structural = geometry_only(pf, state, structural_bits, pf5_contract)
    additive_geometry = geometry_only(pf, state, additive_weight_bits, pf5_contract)
    return {
        "structural_composition": {
            "weight_state_sha256": bits_hash(structural_bits),
            "readout_not_replayed": True,
            "geometry": structural["geometry"],
            "final_geometry_pass": structural["final_geometry_pass"],
        },
        "f32_additive_formula": {
            "operator": "f32(f32(A+B)-S), componentwise over weight and readout bit values decoded as f32",
            "weight_state_sha256": bits_hash(additive_weight_bits),
            "readout_sha256": bits_hash(additive_readout_bits),
            "readout_bits": list(additive_readout_bits),
            "score": score_dict(pf, additive_readout_bits, state.target_readout_bits),
            "score_key": list(score_key(score_dict(pf, additive_readout_bits, state.target_readout_bits))),
            "geometry": additive_geometry["geometry"],
            "final_geometry_pass": additive_geometry["final_geometry_pass"],
        },
    }


def load_context(key: tuple[str, int]) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    pf, builder = load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref["results"] if str(item["endpoint"]) == key[0] and int(item["set_index"]) == key[1])
    s = verify_reference(pf, state, ref_result, pf5_contract)
    singleton_rows = {}
    for row in json.loads((SINGLES_ROOT / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8")):
        singleton_rows[action_key(int(row["group"]), str(row["to"]))] = row
    require(len(singleton_rows) == len(json.loads((SINGLES_ROOT / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8"))), f"singleton duplicate identity: {key}")
    sample_rows = [json.loads(line) for line in (UPAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return pf, builder, state, pf5_contract, s, {"singleton_rows": singleton_rows, "sample_rows": sample_rows}


def run_context(key: tuple[str, int]) -> dict[str, Any]:
    pf, _builder, state, pf5_contract, s, source = load_context(key)
    actions: dict[str, dict[str, Any]] = {}
    for action_id, row in sorted(source["singleton_rows"].items()):
        actions[action_id] = action_record(pf, state, s, row, pf5_contract)
    require(len(actions) > 0, f"no singleton actions: {key}")
    descriptor_payload = {
        "context": [key[0], key[1]],
        "state": {"weight_state_sha256": s["weight_state_sha256"], "readout_sha256": s["readout_sha256"], "score": s["score"], "geometry": s["geometry"], "constraint": signed_constraint(state, s)},
        "actions": [actions[action_id] for action_id in sorted(actions)],
    }
    predictions = []
    for row in source["sample_rows"]:
        a_id = action_key(int(row["a"]["group"]), str(row["a"]["to"]))
        b_id = action_key(int(row["b"]["group"]), str(row["b"]["to"]))
        require(a_id in actions and b_id in actions, f"sample action missing: {key} {row['sample_pair_index']}")
        pred = prediction(pf, state, s, actions[a_id], actions[b_id], pf5_contract)
        predictions.append({
            "sample_pair_index": int(row["sample_pair_index"]),
            "source_uvd0_pair_index": int(row["source_uvd0_pair_index"]),
            "case": row["case"],
            "a": row["a"],
            "b": row["b"],
            "predictions": pred,
        })
    descriptor_path = ROOT / "descriptors" / f"{slug(key)}.json"
    prediction_path = ROOT / "predictions" / f"{slug(key)}.jsonl"
    write_new(descriptor_path, descriptor_payload)
    prediction_bytes = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in predictions).encode("utf-8")
    write_bytes_new(prediction_path, prediction_bytes)
    return {
        "context": [key[0], key[1]],
        "actions": len(actions),
        "predictions": len(predictions),
        "descriptor_sha256": digest(descriptor_path),
        "prediction_sha256": digest(prediction_path),
        "structural_valid_predictions": sum(bool(item["predictions"]["structural_composition"]["final_geometry_pass"]) for item in predictions),
        "additive_valid_predictions": sum(bool(item["predictions"]["f32_additive_formula"]["final_geometry_pass"]) for item in predictions),
        "structural_additive_weight_hash_disagreements": sum(item["predictions"]["structural_composition"]["weight_state_sha256"] != item["predictions"]["f32_additive_formula"]["weight_state_sha256"] for item in predictions),
    }


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing ALG1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "CONTRACT.json").exists(), "ALG1 contract already exists")
    require(not (ROOT / "execution.json").exists(), "ALG1 execution already exists")
    inputs = [
        ("alg1_plan", ROOT / "PLAN.md"),
        ("alg1_runner", Path(__file__)),
        ("singleton_execution", SINGLES_ROOT / "execution.json"),
        ("upair_domain_contract", UPAIR_DOMAIN_ROOT / "CONTRACT.json"),
        ("upair_domain_execution", UPAIR_DOMAIN_ROOT / "execution.json"),
        ("reference_execution", REF_ROOT / "execution.json"),
        ("pf5_contract", PF5_CONTRACT),
    ]
    for key in KEYS:
        inputs.append((f"singleton_shard:{slug(key)}", SINGLES_ROOT / "shards" / f"{slug(key)}.jsonl"))
        inputs.append((f"upair_domain_shard:{slug(key)}", UPAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl"))
    bindings = [bind(label, path) for label, path in inputs]
    contract = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "SEALED_PREMEASUREMENT",
        "parent_bindings": bindings,
        "domain": {"sample_pairs": 17712, "contexts": 8, "pair_outcomes_consulted": False},
        "operator": "f32(f32(A+B)-S), componentwise over decoded f32 values",
        "structural_prediction": "apply disjoint canonical mappings to frozen S bits; no pair readout replay",
        "pair_replay_performed": False,
        "scientific_promotion": False,
        "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "descriptors/*.json", "predictions/*.jsonl"],
    }
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "pair_replay_performed": False, "pair_outcomes_consulted": False})
    results = []
    try:
        for key in KEYS:
            results.append(run_context(key))
            print(json.dumps(results[-1], sort_keys=True), flush=True)
        require(sum(item["predictions"] for item in results) == 17712, "ALG1 prediction cardinality drift")
        execution = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": "ALG1_COMPLETE",
            "engineering_only": True,
            "scientific_promotion": False,
            "pair_replay_performed": False,
            "pair_outcomes_consulted": False,
            "counts": {"contexts": 8, "singleton_actions": sum(item["actions"] for item in results), "predictions": sum(item["predictions"] for item in results)},
            "contexts": results,
            "contract_sha256": digest(ROOT / "CONTRACT.json"),
            "predictions_sealed_before_upair_replay": True,
        }
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG1", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
