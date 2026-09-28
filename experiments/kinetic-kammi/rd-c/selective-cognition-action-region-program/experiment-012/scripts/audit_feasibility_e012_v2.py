from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
FEASIBILITY = CONSTRUCTION / "feasibility"
OUTPUT = CONSTRUCTION / "feasibility-audit-v2.json"
SELECTED = {
    "bytes/wire-endian-contract": "bytes-endian",
    "bytes/bounded-prefix-copy": "bytes-prefix",
    "bytes/cursor-advance-observation": "bytes-cursor-repair-01",
    "bytes/composite-frame-field": "bytes-composite-repair-01",
    "clap/repeated-option-policy": "clap-repeat-repair-01",
    "clap/possible-value-validation": "clap-values",
    "clap/help-color-capability": "clap-color-repair-01",
    "clap/conflicting-alias-requirement": "clap-alias",
    "serde-json/stream-byte-offset": "serde-offset-repair-02",
    "serde-json/number-mode-plus-error-site": "serde-numeric-joint-repair-01",
    "serde-json/map-order-feature-contract": "serde-map-order-repair-02",
    "serde-json/raw-number-lossless": "serde-raw-number",
}
EXECUTION_EVIDENCE_FAMILIES = {
    "bytes/cursor-advance-observation",
    "bytes/composite-frame-field",
    "serde-json/stream-byte-offset",
    "serde-json/number-mode-plus-error-site",
}
ABSTENTION_FAMILIES = {
    "clap/conflicting-alias-requirement",
    "serde-json/raw-number-lossless",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite feasibility audit: {OUTPUT}")
    family_rows: list[dict] = []
    total_candidate_rows = 0
    total_baseline_rows = 0
    for family, trial in SELECTED.items():
        directory = FEASIBILITY / trial
        summary_path = directory / "feasibility-summary.json"
        records_path = directory / "candidate-test-records.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        records = json.loads(records_path.read_text(encoding="utf-8"))
        if summary.get("state") != "OFFLINE_FEASIBILITY_ONLY":
            raise RuntimeError(f"{family}: wrong feasibility state")
        if summary.get("model_contact_authorized") is not False:
            raise RuntimeError(f"{family}: feasibility record does not preserve no-contact boundary")
        candidate_ids = set(summary["candidate_ids_hidden_role_map"].values())
        if len(candidate_ids) != 4:
            raise RuntimeError(f"{family}: expected four distinct candidate IDs")
        if len(records) != 20:
            raise RuntimeError(f"{family}: expected 16 candidate and 4 base case rows, found {len(records)}")
        candidate_records = [row for row in records if row.get("candidate_id") is not None]
        baseline_records = [row for row in records if row.get("candidate_id") is None]
        if len(candidate_records) != 16 or len(baseline_records) != 4:
            raise RuntimeError(f"{family}: incomplete candidate/base matrix")
        if {row["candidate_id"] for row in candidate_records} != candidate_ids:
            raise RuntimeError(f"{family}: recorded candidate IDs disagree with the summary")
        if len({row["case_id"] for row in baseline_records}) != 4:
            raise RuntimeError(f"{family}: baseline cases are not distinct")
        if family in EXECUTION_EVIDENCE_FAMILIES:
            if any(summary["baseline_pass_by_case"].values()):
                raise RuntimeError(f"{family}: base snapshot unexpectedly passes a check")
            for row in baseline_records:
                output = row.get("stdout", "") + row.get("stderr", "")
                if "left:" not in output or "right:" not in output or "task contract failed" in output:
                    raise RuntimeError(f"{family}/{row['case_id']}: pre-action trace lacks observed and expected values")

        assertion_failures = 0
        for row in records:
            output = row.get("stdout", "") + row.get("stderr", "")
            if "could not compile" in output or "error[E" in output:
                raise RuntimeError(f"{family}/{row['candidate_role_hidden']}/{row['case_id']}: compile failure in selected set")
            expected_marker = "test check_contract ... ok" if row["passed"] else "test check_contract ... FAILED"
            if expected_marker not in output:
                raise RuntimeError(f"{family}/{row['candidate_role_hidden']}/{row['case_id']}: test did not reach assertion outcome")
            assertion_failures += not row["passed"]
        total_candidate_rows += len(candidate_records)
        total_baseline_rows += len(baseline_records)
        matrix = summary["candidate_pass_matrix_hidden_roles"]
        all_cases = {row["case_id"] for row in baseline_records}
        fully_passing = sorted(
            role for role, per_case in matrix.items()
            if set(per_case) == all_cases and all(per_case.values())
        )
        if family in ABSTENTION_FAMILIES and fully_passing:
            raise RuntimeError(f"{family}: abstention family has a fully passing offered action")
        if family == "clap/possible-value-validation" and not fully_passing:
            raise RuntimeError("possible-value family lacks an exact full-contract candidate")
        family_rows.append({
            "family": family,
            "selected_trial": trial,
            "baseline_pass_count": sum(summary["baseline_pass_by_case"].values()),
            "candidate_case_rows": len(candidate_records),
            "baseline_case_rows": len(baseline_records),
            "assertion_failure_rows": assertion_failures,
            "fully_passing_candidate_roles_hidden": fully_passing,
            "summary_sha256": sha256(summary_path),
            "records_sha256": sha256(records_path),
        })

    if len(family_rows) != 12 or total_candidate_rows != 192 or total_baseline_rows != 48:
        raise RuntimeError("selected feasibility coverage is not 12 families / 192 candidates / 48 baselines")
    audit = {
        "schema_version": 1,
        "experiment": "E012 Prospective Frame Decomposition",
        "state": "OFFLINE_FEASIBILITY_AUDIT_PASS",
        "model_contact_authorized": False,
        "scored_task_frames_created": False,
        "selected_family_count": len(family_rows),
        "candidate_case_rows": total_candidate_rows,
        "baseline_case_rows": total_baseline_rows,
        "candidate_compile_errors": 0,
        "all_failed_selected_cases_reached_contract_assertion": True,
        "abstention_positive_families_checked": sorted(ABSTENTION_FAMILIES),
        "families": family_rows,
        "preserved_failed_trials": [
            "clap-color", "serde-offset", "clap-repeat", "serde-map-order", "serde-map-order-repair-01",
            "bytes-cursor", "bytes-composite", "serde-offset-repair-01", "serde-numeric-joint"
        ],
        "execution_evidence_families_checked": sorted(EXECUTION_EVIDENCE_FAMILIES),
        "decision": "All 12 locked families have executable feasibility fixtures and the declared E_x families expose observed-versus-expected traces; proceed to scored-task fixture construction only.",
    }
    OUTPUT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": audit["state"], "families": len(family_rows),
                      "candidate_rows": total_candidate_rows, "baseline_rows": total_baseline_rows}, indent=2))


if __name__ == "__main__":
    main()
