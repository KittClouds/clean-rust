from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-UPAIR1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-upair1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
ALG1_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1_ROOT / "scripts/run_alg1.py"
UPAIR_DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-domain-v1"
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN_ROOT / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
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


def action_key(group: int, to: str) -> str:
    return f"{group}:{to}"


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_csc1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "cannot load ALG1 runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong ALG1 runtime")
    return module


def interaction(values_ab: tuple[float, ...], values_a: tuple[float, ...], values_b: tuple[float, ...], values_s: tuple[float, ...]) -> dict[str, Any]:
    terms = tuple(ab - a - b + s for ab, a, b, s in zip(values_ab, values_a, values_b, values_s))
    abs_values = tuple(abs(value) for value in terms)
    return {
        "nonzero_count": sum(value != 0.0 for value in terms),
        "zero_count": sum(value == 0.0 for value in terms),
        "l1": math.fsum(abs_values),
        "l2": math.sqrt(math.fsum(value * value for value in terms)),
        "max_abs": max(abs_values, default=0.0),
    }


def signed_geometry_interaction(alg: Any, state: Any, ab: dict[str, Any], a: dict[str, Any], b: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    values = [alg.signed_constraint(state, item) for item in (s, a, b, ab)]
    s_value, a_value, b_value, ab_value = values
    linear = tuple(ab_value["linear_residual"][i] - a_value["linear_residual"][i] - b_value["linear_residual"][i] + s_value["linear_residual"][i] for i in range(len(ab_value["linear_residual"])))
    return {
        "axis": ab_value["axis_residual"] - a_value["axis_residual"] - b_value["axis_residual"] + s_value["axis_residual"],
        "norm": ab_value["norm_residual"] - a_value["norm_residual"] - b_value["norm_residual"] + s_value["norm_residual"],
        "linear": {"nonzero_count": sum(value != 0.0 for value in linear), "l2": math.sqrt(math.fsum(value * value for value in linear)), "max_abs": max((abs(value) for value in linear), default=0.0)},
    }


def load_context(key: tuple[str, int], alg: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(alg.CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref_execution = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if str(item["endpoint"]) == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, pf5_contract)
    descriptor = json.loads((ALG1_ROOT / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = {str(item["action_key"]): item for item in descriptor["actions"]}
    require(len(actions) == int(descriptor["actions"].__len__()), f"ALG1 descriptor duplicates: {key}")
    predictions = {}
    for line in (ALG1_ROOT / "predictions" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        predictions[int(item["sample_pair_index"])] = item
    sample_rows = [json.loads(line) for line in (UPAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    require(len(predictions) == len(sample_rows), f"prediction/domain cardinality drift: {key}")
    return pf, state, pf5_contract, s, actions, {"predictions": predictions, "sample_rows": sample_rows}


def replay_ab(alg: Any, pf: Any, state: Any, bits: tuple[int, ...], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    return alg.replay(pf, state, bits, pf5_contract)


def run_context(key: tuple[str, int]) -> dict[str, Any]:
    alg = load_alg1()
    pf, state, pf5_contract, s, actions, source = load_context(key, alg)
    predictions = source["predictions"]
    records = []
    target = tuple(int(value) for value in state.target_readout_bits)
    ref_execution = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if str(item["endpoint"]) == key[0] and int(item["set_index"]) == key[1])
    historical_valid_score_key = list(alg.score_key(ref_result["best_valid"]["score"]))
    valid_bits = alg.apply_mapping(pf, state, tuple(state.baseline_weight_bits), ref_result["best_valid"]["canonical_mapping"])
    for row in source["sample_rows"]:
        index = int(row["sample_pair_index"])
        a_id = action_key(int(row["a"]["group"]), str(row["a"]["to"]))
        b_id = action_key(int(row["b"]["group"]), str(row["b"]["to"]))
        a = actions[a_id]
        b = actions[b_id]
        pred = predictions[index]
        require(pred["a"] == row["a"] and pred["b"] == row["b"], f"ALG1/sample identity drift: {key} {index}")
        ab_bits = list(s["bits"])
        seen: set[int] = set()
        for action in (a, b):
            for coordinate, choice in action["canonical_mapping"]:
                coordinate, choice = int(coordinate), int(choice)
                require(coordinate not in seen, f"pair coordinate conflict: {key} {index} {coordinate}")
                seen.add(coordinate)
                raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
                require(raw is not None, f"pair prefix illegal: {key} {index} {coordinate}")
                ab_bits[coordinate] = int(raw)
        ab = replay_ab(alg, pf, state, tuple(ab_bits), pf5_contract)
        s_for_interaction = {"weights": tuple(pf.from_bits(raw) for raw in s["bits"]), "geometry": s["geometry"]}
        a_for_interaction = {"weights": tuple(pf.from_bits(raw) for raw in a["weight_bits"]), "geometry": a["geometry"]}
        b_for_interaction = {"weights": tuple(pf.from_bits(raw) for raw in b["weight_bits"]), "geometry": b["geometry"]}
        structural_prediction = pred["predictions"]["structural_composition"]
        additive_prediction = pred["predictions"]["f32_additive_formula"]
        outcome = "EXACT_ALTERNATIVE" if ab["readout"] == target and ab["final_geometry_pass"] and tuple(ab["bits"]) != tuple(s["bits"]) and tuple(ab["bits"]) != valid_bits else ("VALID_ADVANTAGE_PRESERVED" if ab["final_geometry_pass"] and alg.score_key(ab["score"]) < tuple(historical_valid_score_key) else ("VALID_WORSE_NON_SUCCESS" if ab["final_geometry_pass"] else "INVALID_NON_SUCCESS"))
        records.append({
            "sample_pair_index": index,
            "source_uvd0_pair_index": int(row["source_uvd0_pair_index"]),
            "case": row["case"],
            "application_base": "fresh_S",
            "a": {"action_key": a_id, "group": int(row["a"]["group"]), "to": str(row["a"]["to"]), "weight_state_sha256": a["weight_state_sha256"], "readout_sha256": a["readout_sha256"], "readout_bits": a["readout_bits"], "score": a["score"], "geometry": a["geometry"], "final_geometry_pass": a["final_geometry_pass"]},
            "b": {"action_key": b_id, "group": int(row["b"]["group"]), "to": str(row["b"]["to"]), "weight_state_sha256": b["weight_state_sha256"], "readout_sha256": b["readout_sha256"], "readout_bits": b["readout_bits"], "score": b["score"], "geometry": b["geometry"], "final_geometry_pass": b["final_geometry_pass"]},
            "ab": {"canonical_mapping": sorted(a["canonical_mapping"] + b["canonical_mapping"]), "weight_bits_hash": ab["weight_state_sha256"], "readout_bits": list(ab["readout"]), "readout_sha256": ab["readout_sha256"], "score": ab["score"], "score_key": list(alg.score_key(ab["score"])), "geometry": ab["geometry"], "final_geometry_pass": ab["final_geometry_pass"]},
            "predictions": {"structural": structural_prediction, "f32_additive": additive_prediction, "structural_weight_match": ab["weight_state_sha256"] == structural_prediction["weight_state_sha256"], "f32_additive_weight_match": ab["weight_state_sha256"] == additive_prediction["weight_state_sha256"], "f32_additive_readout_match": ab["readout_sha256"] == additive_prediction["readout_sha256"], "structural_geometry_match": ab["geometry"] == structural_prediction["geometry"], "structural_validity_match": bool(ab["final_geometry_pass"]) == bool(structural_prediction["final_geometry_pass"])},
            "interactions": {"readout": interaction(tuple(ab["readout"]), tuple(a["readout_bits"]), tuple(b["readout_bits"]), tuple(s["readout"])), "geometry": signed_geometry_interaction(alg, state, ab, a_for_interaction, b_for_interaction, s_for_interaction)},
            "historical_valid_score_key": historical_valid_score_key,
            "outcome": outcome,
        })
    output = ROOT / "shards" / f"{slug(key)}.jsonl"
    payload = "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records).encode("utf-8")
    write_bytes_new(output, payload)
    return {
        "context": [key[0], key[1]],
        "records": len(records),
        "shard": output.name,
        "shard_sha256": digest(output),
        "valid": sum(bool(item["ab"]["final_geometry_pass"]) for item in records),
        "better_than_V": sum(item["outcome"] == "VALID_ADVANTAGE_PRESERVED" for item in records),
        "exact_alternative": sum(item["outcome"] == "EXACT_ALTERNATIVE" for item in records),
        "structural_weight_matches": sum(bool(item["predictions"]["structural_weight_match"]) for item in records),
        "structural_geometry_matches": sum(bool(item["predictions"]["structural_geometry_match"]) for item in records),
        "structural_validity_matches": sum(bool(item["predictions"]["structural_validity_match"]) for item in records),
        "additive_weight_matches": sum(bool(item["predictions"]["f32_additive_weight_match"]) for item in records),
        "additive_readout_matches": sum(bool(item["predictions"]["f32_additive_readout_match"]) for item in records),
        "readout_interaction_nonzero_pairs": sum(item["interactions"]["readout"]["nonzero_count"] > 0 for item in records),
    }


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing UPAIR1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected UPAIR1 script cache")
    require(not (ROOT / "execution.json").exists(), "UPAIR1 execution already exists")
    inputs = [("upair1_plan", ROOT / "PLAN.md"), ("upair1_runner", Path(__file__)), ("alg1_contract", ALG1_ROOT / "CONTRACT.json"), ("alg1_execution", ALG1_ROOT / "execution.json"), ("upair_domain_contract", UPAIR_DOMAIN_ROOT / "CONTRACT.json"), ("upair_domain_execution", UPAIR_DOMAIN_ROOT / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF_ROOT / "execution.json")]
    for key in KEYS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1_ROOT / "descriptors" / f"{slug(key)}.json"), (f"alg1_predictions:{slug(key)}", ALG1_ROOT / "predictions" / f"{slug(key)}.jsonl"), (f"upair_domain_shard:{slug(key)}", UPAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl")])
    bindings = [bind(label, path) for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "sample_pairs": 17712, "pair_replay_performed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "pair_replay_performed": False, "scientific_promotion": False})
    results = []
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_context, key) for key in KEYS]
            for future in futures:
                result = future.result()
                results.append(result)
                print(json.dumps(result, sort_keys=True), flush=True)
        require(sum(item["records"] for item in results) == 17712, "UPAIR1 cardinality drift")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "UPAIR1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": True, "pair_outcomes_consulted": True, "counts": {"contexts": 8, "pair_records": sum(item["records"] for item in results), "valid": sum(item["valid"] for item in results), "better_than_V": sum(item["better_than_V"] for item in results), "exact_alternative": sum(item["exact_alternative"] for item in results), "readout_interaction_nonzero_pairs": sum(item["readout_interaction_nonzero_pairs"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "alg1_predictions_consumed": True}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": True, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_UPAIR1", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": bool(results), "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
