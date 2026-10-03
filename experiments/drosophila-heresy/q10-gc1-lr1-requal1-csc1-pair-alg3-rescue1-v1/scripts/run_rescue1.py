from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXH1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1"
AUDIT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-audit-v1"
PROTOCOL = "Q10-ALG3-RESCUE1"
IDENTITY = ROOT.name


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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


def run() -> dict[str, Any]:
    execution = json.loads((EXH1 / "execution.json").read_text(encoding="utf-8"))
    audit = json.loads((AUDIT / "execution.json").read_text(encoding="utf-8"))
    require(execution["status"] == "ALG3_EXH1_COMPLETE", "EXH1 is not complete")
    require(audit["status"] == "EXH1_AUDIT_COMPLETE", "EXH1 audit is not complete")
    total = 0
    global_n1 = Counter()
    global_n2 = Counter()
    global_pattern = Counter()
    global_joint = Counter()
    contexts = []
    for context in execution["contexts"]:
        name = f"{context['context'][0].removesuffix('.json')}__set{context['context'][1]}"
        n1 = Counter()
        n2 = Counter()
        pattern = Counter()
        joint = Counter()
        valid = 0
        for item in context["ranges"]:
            shard = REPO / item["valid_shard"]
            with shard.open("r", encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    value_n1 = int(record["n1"])
                    value_n2 = int(record["n2"])
                    bits = "".join("1" if bool(value) else "0" for value in record["pair_valid_bits"])
                    require(value_n2 == bits.count("1"), f"n2/pair-bit drift: {shard}")
                    require(record["rescue_class"] == {3: "PAIRWISE_VALID_TRIANGLE", 2: "ONE_PAIR_RESCUED", 1: "TWO_PAIR_RESCUED", 0: "PURE_HIGHER_ORDER_RESCUE"}[value_n2], f"rescue class drift: {shard}")
                    valid += 1
                    n1[value_n1] += 1
                    n2[value_n2] += 1
                    pattern[bits] += 1
                    joint[f"n1={value_n1},n2={value_n2}"] += 1
        require(valid == int(context["valid_triples"]), f"context valid count drift: {name}")
        total += valid
        global_n1.update(n1)
        global_n2.update(n2)
        global_pattern.update(pattern)
        global_joint.update(joint)
        contexts.append({"context": context["context"], "valid_triples": valid, "n1": dict(sorted(n1.items())), "n2": dict(sorted(n2.items())), "pair_valid_patterns": dict(sorted(pattern.items())), "n1_n2": dict(sorted(joint.items()))})
    require(total == int(execution["counts"]["valid_triples"]), "global rescue total drift")
    higher_order = int(global_n2[0])
    pairwise = int(global_n2[3])
    return {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_RESCUE1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "readout_executed": False, "parent_exh1_execution_sha256": digest(EXH1 / "execution.json"), "parent_exh1_audit_sha256": digest(AUDIT / "execution.json"), "counts": {"valid_triples": total, "n1": dict(sorted(global_n1.items())), "n2": dict(sorted(global_n2.items())), "pair_valid_patterns": dict(sorted(global_pattern.items())), "n1_n2": dict(sorted(global_joint.items())), "pure_higher_order_rescue": higher_order, "pairwise_valid_triangles": pairwise}, "contexts": contexts, "conclusion": "Read-only aggregation of the complete EXH1 valid frontier; n2=0 is the exact pure higher-order rescue stratum within the declared order-3 structural domain."}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "RESCUE1 execution already exists")
    write_new(ROOT / "CONTRACT.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parents": {"exh1_execution": {"path": EXH1.relative_to(REPO).as_posix(), "sha256": digest(EXH1 / "execution.json")}, "exh1_audit": {"path": AUDIT.relative_to(REPO).as_posix(), "sha256": digest(AUDIT / "execution.json")}}, "read_only": True, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    try:
        result = run()
        write_new(ROOT / "execution.json", result)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": result["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_RESCUE1", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        write_new(ROOT / "execution.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
