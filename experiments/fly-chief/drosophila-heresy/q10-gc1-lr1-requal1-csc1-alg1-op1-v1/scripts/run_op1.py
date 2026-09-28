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
UPAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-v1"
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-domain-v1"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
PF5 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/closures/twin-a/repo/experiments/drosophila-heresy/q10-pf5-v1/scripts/run_q10_pf5.py"
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
    return digest_bytes(path.read_bytes())


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def slug_to_key(slug: str) -> tuple[str, int]:
    endpoint, set_text = slug.rsplit("__set", 1)
    return endpoint + ".json", int(set_text)


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_csc1_alg1_op1_runtime", ALG1 / "scripts/run_alg1.py")
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def op_bits(pf: Any, name: str, a: int, b: int, s: int) -> int:
    def add(x: int, y: int) -> int:
        return int(pf.bits(pf.f32(pf.from_bits(x) + pf.from_bits(y))))

    def sub(x: int, y: int) -> int:
        return int(pf.bits(pf.f32(pf.from_bits(x) - pf.from_bits(y))))

    if name == "A+B-S":
        return sub(add(a, b), s)
    if name == "A+(B-S)":
        return add(a, sub(b, s))
    if name == "(A-S)+B":
        return add(sub(a, s), b)
    if name == "S+(A-S)+(B-S)":
        return add(add(s, sub(a, s)), sub(b, s))
    if name == "S+((A-S)+(B-S))":
        return add(s, add(sub(a, s), sub(b, s)))
    raise RuntimeError(f"unknown operator: {name}")


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "OP1 execution already exists")
    alg = load_alg1()
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(alg.CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    ref_execution = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    pf5_contract = json.loads((alg.PF5_CONTRACT).read_text(encoding="utf-8"))
    bindings = []
    for label, path in (("op1_plan", ROOT / "PLAN.md"), ("op1_runner", Path(__file__)), ("upair_execution", UPAIR / "execution.json"), ("upair_contract", UPAIR / "CONTRACT.json"), ("alg1_execution", ALG1 / "execution.json"), ("domain_execution", DOMAIN / "execution.json"), ("reference_execution", REF / "execution.json"), ("pf5_script", PF5)):
        require(path.is_file(), f"missing OP1 input: {path}")
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    contract = {"protocol": "Q10-CSC1-ALG1-OP1", "identity": ROOT.name, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "operators": ["A+B-S", "A+(B-S)", "(A-S)+B", "S+(A-S)+(B-S)", "S+((A-S)+(B-S))"], "pair_replay_performed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "REPORT.json", "context-records.jsonl"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": "Q10-CSC1-ALG1-OP1", "identity": ROOT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "pair_replay_performed": False})
    operators = tuple(contract["operators"])
    context_results = []
    records = []
    try:
        for context in CONTEXTS:
            key = slug_to_key(context)
            state = states[key]
            ref_result = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
            s = alg.verify_reference(pf, state, ref_result, pf5_contract)
            path = UPAIR / "shards" / f"{context}.jsonl"
            counts = {name: 0 for name in operators}
            exact_by_operator = {name: 0 for name in operators}
            pair_count = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                pair = json.loads(line)
                pair_count += 1
                a = tuple(int(value) for value in pair["a"]["readout_bits"])
                b = tuple(int(value) for value in pair["b"]["readout_bits"])
                actual = tuple(int(value) for value in pair["ab"]["readout_bits"])
                for name in operators:
                    predicted = tuple(op_bits(pf, name, aa, bb, ss) for aa, bb, ss in zip(a, b, s["readout"]))
                    match = predicted == actual
                    counts[name] += sum(x == y for x, y in zip(predicted, actual))
                    exact_by_operator[name] += int(match)
            context_results.append({"context": context, "pairs": pair_count, "row_match_counts": counts, "exact_readout_hash_matches": exact_by_operator})
            print(json.dumps(context_results[-1], sort_keys=True), flush=True)
        report = {"protocol": "Q10-CSC1-ALG1-OP1", "identity": ROOT.name, "status": "OP1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "contexts": context_results, "counts": {"contexts": len(context_results), "pairs": sum(item["pairs"] for item in context_results)}, "operators": list(operators), "parent_sha256": {"upair_execution": digest(UPAIR / "execution.json"), "upair_contract": digest(UPAIR / "CONTRACT.json"), "alg1_execution": digest(ALG1 / "execution.json")}}
        write_new(ROOT / "REPORT.json", report)
        write_new(ROOT / "execution.json", report)
        write_new(ROOT / "STATUS.json", {"protocol": "Q10-CSC1-ALG1-OP1", "identity": ROOT.name, "status": "OP1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": "Q10-CSC1-ALG1-OP1", "identity": ROOT.name, "status": "BLOCKED_OP1", "engineering_only": True, "scientific_promotion": False, "pair_replay_performed": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": context_results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
