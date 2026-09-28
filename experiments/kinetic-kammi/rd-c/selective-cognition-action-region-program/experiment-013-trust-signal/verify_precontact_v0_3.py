#!/usr/bin/env python3
"""Verify the E013 v0.3 precontact seal; reads artifacts and writes one receipt."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program")
EXP = ROOT / "experiment-013-trust-signal"
LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.json"
OUT = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.json"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {}
    actual = {}
    paths = lock["artifact_paths"]
    expected = lock["upstream_artifacts_sha256"]
    checks["path_hash_key_sets_match"] = set(paths) == set(expected)
    for key, path_text in paths.items():
        path = Path(path_text)
        if not path.is_file():
            actual[key] = None
            checks[f"exists:{key}"] = False
            continue
        digest = sha256(path)
        actual[key] = digest
        checks[f"exists:{key}"] = True
        checks[f"sha256:{key}"] = digest == expected[key]
    raw = json.loads(Path(paths["e012_raw_yield_json"]).read_text(encoding="utf-8"))
    projections = json.loads(Path(paths["feasibility_json"]).read_text(encoding="utf-8"))
    checks["e012_raw_yield_counts"] = (
        raw["counts"]["all"]["correct"] == 7
        and raw["counts"]["all"]["wrong"] == 11
        and raw["counts"]["all"]["null"] == 30
        and raw["counts"]["empty_valid_set"]["wrong"] == 2
    )
    checks["development_size_and_T5_feasibility"] = any(
        row["bank"] == "development" and row["tasks"] == 864
        and row["scenario"] == "E012_pessimistic"
        and row["prob_T5_at_least_100_correct_and_100_wrong"] > 0.99
        for row in projections["banks"]
    )
    checks["confirmation_size_and_support"] = any(
        row["tasks"] == 1120 and row["scenario"] == "E012_pessimistic"
        and row["rho_70_probability_at_least_93"] > 0.98
        for row in projections["confirmation_gate_support"]
    )
    checks["exact_gate_minimums"] = (
        projections["exact_gate_minimum_support"][0]["minimum_n"] == 59
        and projections["exact_gate_minimum_support"][1]["minimum_n"] == 93
    )
    checks["contact_and_ownership_boundary"] = (
        lock["model_contact_authorized"] is False
        and lock["model_contact_performed"] is False
        and lock["positive_control"]["model_contact_authorized"] is True
        and lock["positive_control"]["run_status"] == "NOT_RUN"
        and lock["banks"]["owner"] == "USER"
        and lock["banks"]["development"]["status"] == "NOT_BUILT_BY_AGENT"
        and lock["banks"]["confirmation"]["status"] == "NOT_BUILT_BY_AGENT"
    )
    checks["state"] = lock["state"] == "SEALED_PRECONTACT_DESIGN_ONLY"
    result = {
        "schema_version": 1,
        "artifact_id": "E013-PRECONTACT-VERIFICATION-v0.3",
        "state": "PASS" if all(checks.values()) else "FAIL",
        "lock_sha256": sha256(LOCK),
        "checks": checks,
        "checked_artifact_sha256": actual,
        "model_contact_performed": False,
        "banks_built_by_agent": False,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "checks": checks, "receipt": str(OUT)}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
