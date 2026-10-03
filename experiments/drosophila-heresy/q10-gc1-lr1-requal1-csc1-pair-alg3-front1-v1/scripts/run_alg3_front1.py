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
PROTOCOL = "Q10-PAIR-ALG3-FRONT1"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
ALG3 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-v1"
DOMAIN3 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-domain-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
CONTEXTS = (("seed9731-L-tau16.json", 2), ("seed9731-L-tau4.json", 3), ("seed9731-R-tau16.json", 1), ("seed9731-R-tau16.json", 3), ("seed9731-R-tau4.json", 0), ("seed9731-R-tau4.json", 1), ("seed9731-R-tau4.json", 2), ("seed9731-R-tau4.json", 3))


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
    spec = importlib.util.spec_from_file_location("q10_alg3_front1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong runtime")
    return module


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing ALG3-FRONT1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def run_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(alg.CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    ref_execution = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = {str(item["action_key"]): item for item in descriptor["actions"]}
    domain = [json.loads(line) for line in (DOMAIN3 / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    result_rows = [json.loads(line) for line in (ALG3 / "results" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    valid_indexes = {int(row["triple_index"]) for row in result_rows if bool(row["exact_final_geometry_pass"])}
    frontier = [row for row in domain if int(row["triple_index"]) in valid_indexes]
    require(len(frontier) == len(valid_indexes), f"ALG3 valid frontier drift: {key}")
    records = []
    for triple in frontier:
        names = (str(triple["a"]), str(triple["b"]), str(triple["c"]))
        mapping = sorted(sum((actions[name]["canonical_mapping"] for name in names), []))
        bits = alg.apply_mapping(pf, state, tuple(s["bits"]), mapping)
        replay = alg.replay(pf, state, bits, contract)
        require(replay["final_geometry_pass"], f"ALG3 validity drift: {key} {triple['triple_index']}")
        exact = replay["readout"] == tuple(state.target_readout_bits) and tuple(bits) != tuple(state.target_weight_bits)
        records.append({"triple_index": int(triple["triple_index"]), "case": triple["case"], "a": names[0], "b": names[1], "c": names[2], "canonical_mapping": mapping, "weight_state_sha256": replay["weight_state_sha256"], "readout_sha256": replay["readout_sha256"], "readout_bits": list(replay["readout"]), "score": replay["score"], "geometry": replay["geometry"], "final_geometry_pass": True, "target_readout_match": replay["readout"] == tuple(state.target_readout_bits), "target_weight_match": tuple(bits) == tuple(state.target_weight_bits), "exact_alternative": exact})
        if exact:
            break
    path = ROOT / "shards" / f"{slug(key)}.jsonl"
    write_bytes_new(path, ("".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records)).encode("utf-8"))
    return {"context": [key[0], key[1]], "frontier_records": len(frontier), "evaluated_records": len(records), "better_than_V": sum(1 for item in records if tuple(alg.score_key(item["score"])) < tuple(alg.score_key(ref_result["best_valid"]["score"]))), "exact_alternative": sum(bool(item["exact_alternative"]) for item in records), "shard": path.name, "shard_sha256": digest(path), "stopped_on_exact": any(item["exact_alternative"] for item in records)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected ALG3-FRONT1 script cache")
    require(not (ROOT / "execution.json").exists(), "ALG3-FRONT1 execution already exists")
    require(json.loads((ALG3 / "execution.json").read_text(encoding="utf-8"))["status"] == "ALG3_COMPLETE", "ALG3 is not complete")
    inputs = [("alg3_front1_plan", ROOT / "PLAN.md"), ("alg3_front1_runner", Path(__file__)), ("alg3_execution", ALG3 / "execution.json"), ("alg3_domain_execution", DOMAIN3 / "execution.json"), ("alg1_execution", ALG1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg3_domain_shard:{slug(key)}", DOMAIN3 / "shards" / f"{slug(key)}.jsonl"), (f"alg3_result:{slug(key)}", ALG3 / "results" / f"{slug(key)}.jsonl"), (f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json")])
    bindings = [bind(label, path) for label, path in inputs]
    write_new(ROOT / "CONTRACT.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "sample_valid_triples": 20, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    results = []
    try:
        alg = load_alg1()
        for key in CONTEXTS:
            result = run_context(key, alg)
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
            if result["stopped_on_exact"]:
                break
        exact = sum(item["exact_alternative"] for item in results)
        evaluated = sum(item["evaluated_records"] for item in results)
        frontier = sum(item["frontier_records"] for item in results)
        require(exact <= 1, "multiple exact alternatives encountered before stop")
        require(exact == 0 or evaluated <= frontier, "ALG3-FRONT1 evaluation accounting drift")
        status = "ALG3_FRONT1_EXACT_ALTERNATIVE_FOUND" if exact else "ALG3_FRONT1_COMPLETE_NO_EXACT"
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": status, "engineering_only": True, "scientific_promotion": False, "readout_executed": True, "stopped_on_first_exact": bool(exact), "counts": {"frontier_records": frontier, "evaluated_records": evaluated, "better_than_V": sum(item["better_than_V"] for item in results), "exact_alternative": exact}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json")}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": status, "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_FRONT1", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
