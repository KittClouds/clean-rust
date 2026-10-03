from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-PAIR-FRONT1"
IDENTITY = ROOT.name
EXH1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-exh1-v1"
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
CONTEXTS = (
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
    spec = importlib.util.spec_from_file_location("q10_pair_front1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong exact replay runtime")
    return module


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing FRONT1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def load_context(key: tuple[str, int], alg: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(alg.CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref_execution = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    valid_score_key = list(alg.score_key(ref_result["best_valid"]["score"]))
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = {str(item["action_key"]): item for item in descriptor["actions"]}
    require(len(actions) == len(descriptor["actions"]), f"ALG1 action duplicate: {key}")
    frontier = [json.loads(line) for line in (EXH1 / "valid-frontier" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return pf, state, contract, s, {"valid_score_key": valid_score_key, "target_bits": tuple(state.target_weight_bits), "actions": actions}, frontier


def run_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, state, contract, s, metadata, frontier = load_context(key, alg)
    records: list[dict[str, Any]] = []
    exact_record: dict[str, Any] | None = None
    for frontier_row in frontier:
        a_id = f"{int(frontier_row['a']['group'])}:{str(frontier_row['a']['to'])}"
        b_id = f"{int(frontier_row['b']['group'])}:{str(frontier_row['b']['to'])}"
        require(a_id in metadata["actions"] and b_id in metadata["actions"], f"EXH1 action descriptor missing: {key} {a_id} {b_id}")
        mapping = sorted(metadata["actions"][a_id]["canonical_mapping"] + metadata["actions"][b_id]["canonical_mapping"])
        bits = alg.apply_mapping(pf, state, tuple(s["bits"]), mapping)
        result = alg.replay(pf, state, bits, contract)
        require(result["final_geometry_pass"], f"EXH1 validity drift at {key} {frontier_row['source_uvd0_pair_index']}")
        geometry_error = max(abs(float(frontier_row["geometry"][name]) - float(result["geometry"][name])) for name in result["geometry"])
        exact_alternative = result["readout"] == tuple(state.target_readout_bits) and tuple(bits) != metadata["target_bits"]
        score_key = list(alg.score_key(result["score"]))
        outcome = "EXACT_ALTERNATIVE" if exact_alternative else ("VALID_ADVANTAGE_PRESERVED" if tuple(score_key) < tuple(metadata["valid_score_key"]) else "VALID_WORSE_NON_SUCCESS")
        record = {
            "frontier_pair_index": int(frontier_row["exh1_pair_index"]),
            "source_uvd0_pair_index": int(frontier_row["source_uvd0_pair_index"]),
            "case": frontier_row["case"],
            "a": frontier_row["a"],
            "b": frontier_row["b"],
            "canonical_mapping": mapping,
            "weight_state_sha256": result["weight_state_sha256"],
            "readout_bits": list(result["readout"]),
            "readout_sha256": result["readout_sha256"],
            "score": result["score"],
            "score_key": score_key,
            "geometry": result["geometry"],
            "frontier_geometry_abs_error": geometry_error,
            "final_geometry_pass": True,
            "target_readout_match": result["readout"] == tuple(state.target_readout_bits),
            "target_weight_match": tuple(bits) == metadata["target_bits"],
            "outcome": outcome,
        }
        records.append(record)
        if exact_alternative:
            exact_record = record
            break
    shard = ROOT / "shards" / f"{slug(key)}.jsonl"
    payload = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records).encode("utf-8")
    write_bytes_new(shard, payload)
    return {
        "context": [key[0], key[1]],
        "frontier_records": len(frontier),
        "evaluated_records": len(records),
        "valid_evaluated": len(records),
        "better_than_V": sum(item["outcome"] == "VALID_ADVANTAGE_PRESERVED" for item in records),
        "exact_alternative": sum(item["outcome"] == "EXACT_ALTERNATIVE" for item in records),
        "max_frontier_geometry_abs_error": max((item["frontier_geometry_abs_error"] for item in records), default=0.0),
        "shard": shard.name,
        "shard_sha256": digest(shard),
        "exact_record": exact_record,
        "complete_context": exact_record is None and len(records) == len(frontier),
    }


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected FRONT1 script cache")
    require(not (ROOT / "execution.json").exists(), "FRONT1 execution already exists")
    exh_execution = EXH1 / "execution.json"
    require(json.loads(exh_execution.read_text(encoding="utf-8"))["status"] == "PAIR_EXH1_COMPLETE", "EXH1 is not complete")
    inputs = [("front1_plan", ROOT / "PLAN.md"), ("front1_runner", Path(__file__)), ("exh1_contract", EXH1 / "CONTRACT.json"), ("exh1_execution", exh_execution), ("alg1_execution", ALG1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        inputs.append((f"exh1_frontier:{slug(key)}", EXH1 / "valid-frontier" / f"{slug(key)}.jsonl"))
    bindings = [bind(label, path) for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "frontier_pairs": 9530, "pair_replay_performed": False, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "frontier_pairs": 9530, "pair_replay_performed": False, "readout_executed": False})
    results: list[dict[str, Any]] = []
    alg = load_alg1()
    try:
        for key in CONTEXTS:
            result = run_context(key, alg)
            results.append(result)
            print(json.dumps({k: v for k, v in result.items() if k != "exact_record"}, sort_keys=True), flush=True)
            if result["exact_record"] is not None:
                execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "EXACT_ALTERNATIVE_FOUND", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": True, "readout_executed": True, "stopped_on_first_exact": True, "counts": {"frontier_pairs": 9530, "evaluated_pairs": sum(item["evaluated_records"] for item in results), "valid_evaluated": sum(item["valid_evaluated"] for item in results), "better_than_V": sum(item["better_than_V"] for item in results), "exact_alternative": 1}, "contexts": results, "exact_candidate": result["exact_record"], "contract_sha256": digest(ROOT / "CONTRACT.json")}
                write_new(ROOT / "execution.json", execution)
                write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
                print(json.dumps(execution, indent=2, sort_keys=True))
                return 0
        require(sum(item["frontier_records"] for item in results) == 9530, "FRONT1 frontier cardinality drift")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PAIR_FRONT1_COMPLETE_NO_EXACT", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": True, "readout_executed": True, "stopped_on_first_exact": False, "counts": {"frontier_pairs": 9530, "evaluated_pairs": sum(item["evaluated_records"] for item in results), "valid_evaluated": sum(item["valid_evaluated"] for item in results), "better_than_V": sum(item["better_than_V"] for item in results), "exact_alternative": 0}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "order2_frontier_exhausted": True}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_PAIR_FRONT1", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": bool(results), "readout_executed": bool(results), "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
