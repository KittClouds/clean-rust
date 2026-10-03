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
PROTOCOL = "Q10-READ-INC1"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
UPAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-v1"
UPAIR_DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-domain-v1"
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


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_read_inc1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong runtime")
    return module


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing READ-INC1 input: {path}")
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
    rows_by_coordinate: dict[int, set[int]] = {}
    for row_index, row in enumerate(state.rows):
        for coordinate in row:
            rows_by_coordinate.setdefault(int(coordinate), set()).add(row_index)
    pairs = [json.loads(line) for line in (UPAIR / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return pf, state, contract, s, {"actions": actions, "rows_by_coordinate": rows_by_coordinate}, pairs


def run_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, state, contract, s, context, pairs = load_context(key, alg)
    total_affected = 0
    total_rows = 0
    mismatches = 0
    max_affected = 0
    for pair in pairs:
        a_id = str(pair["a"]["action_key"])
        b_id = str(pair["b"]["action_key"])
        a = context["actions"][a_id]
        b = context["actions"][b_id]
        mapping = sorted(a["canonical_mapping"] + b["canonical_mapping"])
        bits = alg.apply_mapping(pf, state, tuple(s["bits"]), mapping)
        changed_coordinates = {int(coordinate) for coordinate, _choice in mapping}
        affected_rows: set[int] = set()
        for coordinate in changed_coordinates:
            affected_rows.update(context["rows_by_coordinate"].get(coordinate, set()))
        incremental = list(s["readout"])
        weights = tuple(pf.from_bits(raw) for raw in bits)
        for row_index in affected_rows:
            incremental[row_index] = int(pf.sequential_bits(state.rows[row_index], weights))
        expected = tuple(int(value) for value in pair["ab"]["readout_bits"])
        if tuple(incremental) != expected:
            mismatches += 1
        total_affected += len(affected_rows)
        total_rows += len(state.rows)
        max_affected = max(max_affected, len(affected_rows))
    return {"context": [key[0], key[1]], "pairs": len(pairs), "readout_mismatches": mismatches, "total_rows": total_rows, "total_affected_rows": total_affected, "mean_affected_fraction": total_affected / max(total_rows, 1), "max_affected_rows": max_affected}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected READ-INC1 script cache")
    require(not (ROOT / "execution.json").exists(), "READ-INC1 execution already exists")
    inputs = [("read_inc1_plan", ROOT / "PLAN.md"), ("read_inc1_runner", Path(__file__)), ("upair_execution", UPAIR / "execution.json"), ("upair_contract", UPAIR / "CONTRACT.json"), ("alg1_execution", ALG1 / "execution.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json"), (f"upair_shard:{slug(key)}", UPAIR / "shards" / f"{slug(key)}.jsonl")])
    bindings = [bind(label, path) for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "pair_records": 17712, "full_pair_replay_performed": False, "incremental_readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    results = []
    try:
        alg = load_alg1()
        for key in CONTEXTS:
            result = run_context(key, alg)
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
        require(sum(item["pairs"] for item in results) == 17712, "READ-INC1 pair cardinality drift")
        require(sum(item["readout_mismatches"] for item in results) == 0, "incremental readout mismatch")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "READ_INC1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "full_pair_replay_performed": False, "incremental_readout_executed": True, "counts": {"contexts": 8, "pairs": sum(item["pairs"] for item in results), "readout_mismatches": sum(item["readout_mismatches"] for item in results), "total_rows": sum(item["total_rows"] for item in results), "total_affected_rows": sum(item["total_affected_rows"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Affected-row exact replay reproduced every authoritative UPAIR1 pair readout bit for bit."}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_READ_INC1", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
