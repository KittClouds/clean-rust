from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
VMAT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-v6"
R1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-r1-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
RUNNER = ROOT / "scripts/run_pred1.py"
PLAN = ROOT / "PLAN.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def binding(label: str, path: Path) -> dict[str, object]:
    return {
        "label": label,
        "path": path.relative_to(REPO).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def main() -> int:
    contexts = [
        "seed9731-L-tau16__set2",
        "seed9731-L-tau4__set3",
        "seed9731-R-tau16__set1",
        "seed9731-R-tau16__set3",
        "seed9731-R-tau4__set0",
        "seed9731-R-tau4__set1",
        "seed9731-R-tau4__set2",
        "seed9731-R-tau4__set3",
    ]
    parent_paths = [
        ("vmat_contract", VMAT / "CONTRACT.json"),
        ("vmat_execution", VMAT / "execution.json"),
        ("vmat_domain_manifest", VMAT / "domain-manifest.json"),
        ("vmat_finalizer", REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-finalizer-v1/REPORT.json"),
        ("r1_contract", R1 / "CONTRACT.json"),
        ("r1_report", R1 / "REPORT.json"),
        ("domain_execution", DOMAIN / "execution.json"),
        ("reference_execution", REF / "execution.json"),
        ("pred1_plan", PLAN),
        ("pred1_runner", RUNNER),
    ]
    input_paths = list(parent_paths)
    for context in contexts:
        input_paths.append((f"domain_shard:{context}", DOMAIN / "shards" / f"{context}.jsonl"))
        input_paths.append((f"vmat_shard:{context}", VMAT / "shards" / f"{context}.jsonl"))
        input_paths.append((f"vmat_state_index:{context}", VMAT / "sidecars" / context / "state-index.jsonl"))
        for filename in (
            "constraint-gate.f64bin",
        ):
            input_paths.append((f"vmat_sidecar:{context}:{filename}", VMAT / "sidecars" / context / filename))
    for label, path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"missing bound input: {path}")
    bindings = [binding(label, path) for label, path in input_paths]
    contract = {
        "protocol": "Q10-CSC1-PRED1",
        "identity": "q10-gc1-lr1-requal1-csc1-pred1-v1",
        "status": "SEALED_PREMEASUREMENT",
        "replay_performed": False,
        "scientific_promotion": False,
        "domain": {
            "pair_records": 4999,
            "contexts": contexts,
            "split": "sha256(context|pair_index|direction) first eight bytes modulo five equals zero",
            "candidate_pool": "held-out directional observations only",
        },
        "parent_bindings": bindings,
        "write_allowlist": [
            "CONTRACT.json",
            "PREEXECUTION.json",
            "REPORT.json",
        ],
        "no_replay": True,
    }
    contract_path = ROOT / "CONTRACT.json"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    preexecution = {
        "protocol": "Q10-CSC1-PRED1",
        "identity": "q10-gc1-lr1-requal1-csc1-pred1-v1",
        "status": "PREEXECUTION_SEALED",
        "contract_sha256": digest(contract_path),
        "domain_manifest_sha256": digest(VMAT / "domain-manifest.json"),
        "input_binding_count": len(bindings),
        "expected_output": "REPORT.json",
        "replay_performed": False,
        "scientific_promotion": False,
    }
    (ROOT / "PREEXECUTION.json").write_text(json.dumps(preexecution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
