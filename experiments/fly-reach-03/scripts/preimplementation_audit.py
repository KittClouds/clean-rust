"""FLY-REACH-03 authority gate.

This audit reads only the sealed machine contract, seal manifest, and named
REACH-02 receipts. It does not scrape historical Markdown for settings and it
does not create a runner, seed namespace, or measured namespace.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_CONTRACT_SHA256 = (
    "6beb47c4784a7d6e37a91e45688dd86e50b15291a8f0dbf07c56c71aefbe47a7"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def artifact_entry(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = root / entry["path"]
    actual = {
        "path": entry["path"],
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256(path) if path.is_file() else None,
        "expected_sha256": entry.get("sha256"),
    }
    actual["matches"] = (
        actual["exists"]
        and actual["sha256"] == entry.get("sha256")
        and actual["bytes"] == entry.get("bytes")
    )
    return actual


def main() -> int:
    study = Path(__file__).resolve().parents[1]
    repo = study.parents[1]
    seal_path = study / "MATH-CONTRACT-v0.3-SEAL.json"
    seal = read_json(seal_path)
    controlling_contract = study / "MATH-CONTRACT-v0.3-AUTHORITATIVE.md"

    checks: dict[str, Any] = {}
    checks["contract_sha256"] = {
        "expected": EXPECTED_CONTRACT_SHA256,
        "actual": sha256(controlling_contract),
        "pass": sha256(controlling_contract) == EXPECTED_CONTRACT_SHA256,
    }
    checks["seal_schema"] = {
        "actual": seal.get("schema"),
        "pass": seal.get("schema") == "FLY-REACH-03-v0.3-precode-seal-v2",
    }
    checks["seal_status"] = {
        "status": seal.get("status"),
        "execution_authorized": seal.get("execution_authorized"),
        "implementation_authorized": seal.get("implementation_authorized"),
        "pass": (
            seal.get("status") == "SEALED_PRE_CODE"
            and seal.get("execution_authorized") is False
            and seal.get("implementation_authorized") is False
        ),
    }

    machine = read_json(study / "math-objects-v0.3.json")
    checks["machine_semantics"] = {
        "schema": machine.get("schema"),
        "version": machine.get("version"),
        "pass": (
            machine.get("schema") == "FLY-REACH-03-math-objects-v0.3"
            and machine.get("version") == "0.3"
            and machine.get("execution_authorized") is False
        ),
    }

    controlling_entries = [
        artifact_entry(study, entry) for entry in seal["controlling_artifacts"]
    ]
    historical_entries = [
        artifact_entry(study, entry)
        for entry in seal["incorporated_historical_artifacts"]
    ]
    receipt_entries = [
        artifact_entry(repo, entry)
        for entry in seal["authoritative_reach02_receipts"]
    ]
    checks["controlling_artifacts"] = controlling_entries
    checks["historical_artifacts"] = historical_entries
    checks["reach02_receipts"] = receipt_entries
    checks["artifact_hashes"] = {
        "pass": all(
            item["matches"]
            for group in (controlling_entries, historical_entries, receipt_entries)
            for item in group
        )
    }

    run1 = repo / "experiments/fly-reach-02/artifacts/REACH02-RUN1/REACH02-RUN1-NONPROMOTABLE-RECEIPT.json"
    run1_receipt = read_json(run1) if run1.is_file() else {}
    checks["run1_boundary"] = {
        "path": str(run1),
        "receipt_status": run1_receipt.get("status"),
        "nonpromotable": run1_receipt.get("non_promotable"),
        "pass": (
            run1_receipt.get("non_promotable") is True
            or "NONPROMOTABLE" in str(run1_receipt.get("status", ""))
        ),
    }

    forbidden = [
        study / "executor",
        study / "inputs/measured",
        study / "seeds",
        study / "runs",
        study / "artifacts/measured",
    ]
    forbidden_state = [
        {"path": str(path), "exists": path.exists()} for path in forbidden
    ]
    checks["fresh_namespace"] = {
        "paths": forbidden_state,
        "pass": not any(item["exists"] for item in forbidden_state),
    }

    checks["historical_markdown_not_scraped"] = {
        "pass": True,
        "basis": "sealed JSON and named receipt hashes only",
    }
    checks["pass"] = all(
        [
            checks["contract_sha256"]["pass"],
            checks["seal_schema"]["pass"],
            checks["seal_status"]["pass"],
            checks["machine_semantics"]["pass"],
            checks["artifact_hashes"]["pass"],
            checks["run1_boundary"]["pass"],
            checks["fresh_namespace"]["pass"],
        ]
    )

    output_dir = study / "artifacts/preimplementation"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "schema": "FLY-REACH-03-preimplementation-audit-v1",
        "study_id": "FLY-REACH-03",
        "status": "PASS" if checks["pass"] else "STOP",
        "checks": checks,
        "no_runner_or_measurement_namespace_created": checks["fresh_namespace"]["pass"],
    }
    output_path = output_dir / "REACH03-PREIMPLEMENTATION-AUDIT.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "path": str(output_path)}, sort_keys=True))
    return 0 if checks["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
