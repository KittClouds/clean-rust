from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from s12_math import canonical_json, entry, tree_root


RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
FINAL_SEAL = RUN / "s12-final-seal-v01.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_tree(base: Path, seal: dict[str, Any]) -> bool:
    actual = [entry(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    return actual == sorted(seal["entries"], key=lambda item: item["path"]) and tree_root(actual) == seal["root_sha256"]


def main() -> int:
    if FINAL_SEAL.exists():
        seal = read_json(FINAL_SEAL)
        if not verify_tree(RUN, seal):
            raise RuntimeError("existing S12 final seal failed verification")
        print(json.dumps({"final_result_root_sha256": seal["root_sha256"], "entries": len(seal["entries"]), "already_sealed": True}, indent=2))
        return 0
    execution = read_json(RUN / "execution-receipt-v01.json")
    raw = read_json(RUN / "raw-v01" / "raw-seal-v01.json")
    analysis = read_json(RUN / "analysis-v01" / "analysis-seal-v01.json")
    verification = read_json(RUN / "independent-verification-v01.json")
    if execution.get("complete") is not True or verification.get("complete") is not True:
        raise RuntimeError("S12 execution or independent verification is incomplete")
    if execution.get("raw_output_root_sha256") != raw.get("root_sha256"):
        raise RuntimeError("S12 execution receipt does not bind current raw seal")
    if verification.get("raw_output_root_sha256") != raw.get("root_sha256") or verification.get("analysis_root_sha256") != analysis.get("root_sha256"):
        raise RuntimeError("S12 independent verifier does not bind current result roots")
    result = read_json(RUN / "analysis-v01" / "s12-analysis-result-v01.json")
    dispositions = {
        site["site_index"]: site["selective_causal_dependence_supported"]
        for site in result["primary"]["sites"]
    }
    disposition = {
        "disposition_id": "FAS_S12_FINAL_DISPOSITION_V01",
        "complete": True,
        "S12_EXECUTION_COMPLETE": True,
        "S12_RAW_OUTPUT_SEALED": True,
        "S12_ANALYSIS_COMPLETE": True,
        "S12_INDEPENDENT_VERIFICATION_PASS": True,
        "FAS00_DISPOSITION_MODIFIED": False,
        "selective_causal_dependence_by_site": dispositions,
        "primary_results": result["primary"],
        "claim_scope": result["claim_scope"],
        "terminal_states": {"S12_COMPLETE": True, "S12_STOP": True},
    }
    disposition_path = RUN / "s12-final-disposition-v01.json"
    disposition_path.write_bytes(canonical_json(disposition) + b"\n")
    files = [
        path for path in RUN.rglob("*")
        if path.is_file()
        and path != FINAL_SEAL
        and "__pycache__" not in path.parts
        and path.suffix.lower() != ".pyc"
    ]
    entries = [entry(path, RUN) for path in files]
    entries.sort(key=lambda item: item["path"])
    seal = {
        "seal_id": "FAS_S12_FINAL_RESULT_TREE_V01",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "entry_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in entries),
    }
    FINAL_SEAL.write_bytes(canonical_json(seal) + b"\n")
    reloaded = read_json(FINAL_SEAL)
    if not verify_tree(RUN, reloaded):
        raise RuntimeError("S12 final result tree failed immediate verification")
    print(json.dumps({"final_result_root_sha256": reloaded["root_sha256"], "entries": len(entries), "total_bytes": seal["total_bytes"], "already_sealed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
