from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
FRONT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-front1-v2"
EXH = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-exh1-v1"
UPAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-v1"
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


def load_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    front_execution = json.loads((FRONT / "execution.json").read_text(encoding="utf-8"))
    exh_execution = json.loads((EXH / "execution.json").read_text(encoding="utf-8"))
    require(front_execution["status"] == "PAIR_FRONT1_COMPLETE_NO_EXACT", "FRONT1 is not the sealed no-exact result")
    require(exh_execution["status"] == "PAIR_EXH1_COMPLETE", "EXH1 is not complete")
    bindings = [
        {"label": "audit_plan", "path": (ROOT / "PLAN.md").relative_to(REPO).as_posix(), "sha256": digest(ROOT / "PLAN.md")},
        {"label": "audit_runner", "path": Path(__file__).relative_to(REPO).as_posix(), "sha256": digest(Path(__file__))},
        {"label": "front_execution", "path": (FRONT / "execution.json").relative_to(REPO).as_posix(), "sha256": digest(FRONT / "execution.json")},
        {"label": "exh_execution", "path": (EXH / "execution.json").relative_to(REPO).as_posix(), "sha256": digest(EXH / "execution.json")},
    ]
    write_new(ROOT / "CONTRACT.json", {"protocol": "Q10-FRONT1-AUDIT", "identity": ROOT.name, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "readout_performed": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": "Q10-FRONT1-AUDIT", "identity": ROOT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    counts = {"front_records": 0, "exh_records": 0, "upair_records": 0, "sample_overlap": 0, "sample_mismatches": 0, "duplicate_front_keys": 0, "frontier_mismatches": 0}
    seen: set[tuple[str, int]] = set()
    for key in CONTEXTS:
        name = slug(key)
        front_rows = load_lines(FRONT / "shards" / f"{name}.jsonl")
        exh_rows = load_lines(EXH / "valid-frontier" / f"{name}.jsonl")
        upair_rows = load_lines(UPAIR / "shards" / f"{name}.jsonl")
        counts["front_records"] += len(front_rows)
        counts["exh_records"] += len(exh_rows)
        counts["upair_records"] += len(upair_rows)
        front_by_source: dict[int, dict[str, Any]] = {}
        for row in front_rows:
            source = int(row["source_uvd0_pair_index"])
            identity = (name, source)
            if identity in seen:
                counts["duplicate_front_keys"] += 1
            seen.add(identity)
            front_by_source[source] = row
        require(len(front_rows) == len(exh_rows), f"frontier cardinality drift: {name}")
        for front, exh in zip(front_rows, exh_rows):
            if int(front["source_uvd0_pair_index"]) != int(exh["source_uvd0_pair_index"]) or front["a"] != exh["a"] or front["b"] != exh["b"] or not front["final_geometry_pass"]:
                counts["frontier_mismatches"] += 1
        for row in upair_rows:
            if not bool(row["ab"]["final_geometry_pass"]):
                continue
            counts["sample_overlap"] += 1
            source = int(row["source_uvd0_pair_index"])
            front = front_by_source.get(source)
            require(front is not None, f"valid UPAIR sample absent from FRONT1: {name} {source}")
            if front["readout_sha256"] != row["ab"]["readout_sha256"] or front["score"] != row["ab"]["score"] or front["geometry"] != row["ab"]["geometry"] or front["target_readout_match"] != (row["ab"]["readout_bits"] == row["ab"].get("target_readout_bits", [])):
                # The target comparison is intentionally excluded: UPAIR1 does not store target bits.
                if front["readout_sha256"] != row["ab"]["readout_sha256"] or front["score"] != row["ab"]["score"] or front["geometry"] != row["ab"]["geometry"]:
                    counts["sample_mismatches"] += 1
    require(counts["front_records"] == 9530, f"FRONT1 record count drift: {counts['front_records']}")
    require(counts["exh_records"] == 9530, f"EXH1 frontier count drift: {counts['exh_records']}")
    require(counts["duplicate_front_keys"] == 0, "duplicate FRONT1 source keys")
    require(counts["frontier_mismatches"] == 0, "FRONT1/EXH1 frontier mismatch")
    require(counts["sample_mismatches"] == 0, "FRONT1/UPAIR1 replay mismatch")
    execution = {"protocol": "Q10-FRONT1-AUDIT", "identity": ROOT.name, "status": "FRONT1_AUDIT_COMPLETE", "engineering_only": True, "scientific_promotion": False, "readout_performed": False, "counts": counts, "parent_sha256": {"front_execution": digest(FRONT / "execution.json"), "exh_execution": digest(EXH / "execution.json")}, "conclusion": "FRONT1 complete order-2 frontier is internally consistent and agrees with every overlapping valid UPAIR1 replay."}
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": "Q10-FRONT1-AUDIT", "identity": ROOT.name, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
