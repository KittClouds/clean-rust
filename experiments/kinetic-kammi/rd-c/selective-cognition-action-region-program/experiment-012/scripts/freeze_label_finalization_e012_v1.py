from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
OUT = ROOT / "bank" / "construction-01" / "label-finalization-lock-v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite label-finalization lock")
    output_paths = [
        BANK / "vault" / "task-source-fixtures-final-v1.json",
        BANK / "vault" / "candidate-check-labels-final-v1.json",
        BANK / "vault" / "label-finalization-report-v1.json",
    ]
    if any(path.exists() for path in output_paths):
        raise SystemExit("finalized labels already exist")
    raw_source = BANK / "vault" / "task-source-fixtures.json"
    raw_checks = BANK / "vault" / "candidate-check-results.json"
    run_lock = ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.2.json"
    task_lock = ROOT / "bank" / "construction-01" / "task-construction-lock-v1.1.json"
    report = json.loads(raw_checks.read_text(encoding="utf-8"))
    if report.get("state") != "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT":
        raise SystemExit("consistent candidate check results are required")
    if any(row["compile_failed"] for row in report["candidate_rows"] + report["base_rows"]):
        raise SystemExit("compiler failures prevent label finalization")
    outcome_groups: dict[tuple[str, str, str, str, str], set[bool]] = defaultdict(set)
    for row in report["candidate_rows"] + report["base_rows"]:
        for case in row["check_cases"]:
            key = (row["family_hidden"], row["overlay_manifest_sha256"], row["overlay_source_sha256"], row["overlay_test_sha256"], case["case_id"])
            outcome_groups[key].add(bool(case["passed"]))
    if any(len(values) != 1 for values in outcome_groups.values()):
        raise SystemExit("same-input case outcome conflicts remain")
    scored_lock = json.loads(run_lock.read_text(encoding="utf-8"))
    if scored_lock["source_fixture_sha256"] != digest(raw_source):
        raise SystemExit("raw task source fixture drifted from scored-check lock")
    if digest(BANK / "attempts" / "scored-check-results-attempt-02-quarantined.json") != scored_lock["quarantined_result_sha256"]:
        raise SystemExit("quarantined attempt-02 evidence drifted")

    paths = [
        ROOT / "amendments" / "bank-amendment-08.md",
        ROOT / "amendments" / "bank-amendment-08.json",
        ROOT / "scripts" / "finalize_task_labels_e012_v1.py",
        ROOT / "scripts" / "freeze_label_finalization_e012_v1.py",
        ROOT / "scripts" / "build_task_sources_e012_v1.py",
        task_lock,
        run_lock,
        raw_source,
        raw_checks,
        BANK / "attempts" / "scored-check-attempt-02-audit.json",
        BANK / "attempts" / "scored-check-results-attempt-02-quarantined.json",
    ]
    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
        for path in paths
    ]
    body = {
        "schema_version": 1,
        "state": "FROZEN_LABEL_FINALIZATION_BEFORE_DERIVATION",
        "model_contact_authorized": False,
        "task_source_sha256": digest(raw_source),
        "raw_candidate_check_results_sha256": digest(raw_checks),
        "same_input_case_groups": len(outcome_groups),
        "same_input_case_conflicts": 0,
        "finalizer": "scripts/finalize_task_labels_e012_v1.py",
        "finalizer_sha256": digest(ROOT / "scripts" / "finalize_task_labels_e012_v1.py"),
        "files": files,
        "sha256_self_excluded": True,
    }
    OUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": body["state"], "inputs": len(files), "lock": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
