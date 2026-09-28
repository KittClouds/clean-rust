from __future__ import annotations

import difflib
import hashlib
import json
import os
import random
import subprocess
from pathlib import Path


ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
HARNESS = CONSTRUCTION / "task-harnesses" / "clap-repeat"
TARGET = CONSTRUCTION / "target" / "clap-harness"
OUTPUT = CONSTRUCTION / "feasibility" / "clap-repeat"
SOURCE = HARNESS / "src" / "lib.rs"
CASES = ("case-01", "case-02", "case-03", "case-04")

CANDIDATES = {
    "append_all": {
        "action": "    let command = Command::new(\"demo\")\n        .arg(Arg::new(\"tag\").long(\"tag\").action(ArgAction::Append));",
        "retrieval": "    matches\n        .get_many::<String>(\"tag\")\n        .map(|values| values.cloned().collect())\n        .unwrap_or_default()",
    },
    "last_value_wins": {
        "action": "    let command = Command::new(\"demo\")\n        .args_override_self(true)\n        .arg(Arg::new(\"tag\").long(\"tag\").action(ArgAction::Set));",
        "retrieval": "    matches\n        .get_many::<String>(\"tag\")\n        .map(|values| values.cloned().collect())\n        .unwrap_or_default()",
    },
    "first_value_only": {
        "action": "    let command = Command::new(\"demo\")\n        .arg(Arg::new(\"tag\").long(\"tag\").action(ArgAction::Append));",
        "retrieval": "    matches\n        .get_many::<String>(\"tag\")\n        .and_then(|values| values.next().cloned())\n        .into_iter()\n        .collect()",
    },
    "single_occurrence_only": {
        "action": "    let command = Command::new(\"demo\")\n        .arg(Arg::new(\"tag\").long(\"tag\").action(ArgAction::Set));",
        "retrieval": "    matches\n        .get_many::<String>(\"tag\")\n        .map(|values| values.cloned().collect())\n        .unwrap_or_default()",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_case(case: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    env["E012_CASE"] = case
    return subprocess.run(
        ["cargo", "test", "--offline", "--manifest-path", str(HARNESS / "Cargo.toml"),
         "--test", "contract", "--", "--exact", "check_contract"],
        cwd=HARNESS,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite feasibility output: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    original = SOURCE.read_text(encoding="utf-8")
    action_anchor = "    // E012 candidate slot.\n    let command = Command::new(\"demo\")\n        .arg(Arg::new(\"tag\").long(\"tag\").action(ArgAction::Set));"
    retrieval_anchor = "    matches\n        .get_many::<String>(\"tag\")\n        .map(|values| values.cloned().collect())\n        .unwrap_or_default()"
    if original.count(action_anchor) != 1 or original.count(retrieval_anchor) != 1:
        raise SystemExit("candidate anchors are absent or ambiguous")
    rng = random.Random(20260925 ^ 0xC1A9)
    ids = rng.sample(range(20000, 65000), len(CANDIDATES))
    id_by_role = dict(zip(CANDIDATES, ids, strict=True))
    matrix: dict[str, dict[str, bool]] = {}
    records: list[dict] = []
    code_hashes = {"base": sha256(original.encode("utf-8"))}

    try:
        for role, replacement in CANDIDATES.items():
            patched = original.replace(action_anchor, replacement["action"], 1)
            patched = patched.replace(retrieval_anchor, replacement["retrieval"], 1)
            code_hashes[role] = sha256(patched.encode("utf-8"))
            patch = "".join(difflib.unified_diff(
                original.splitlines(keepends=True), patched.splitlines(keepends=True),
                fromfile="a/src/lib.rs", tofile="b/src/lib.rs", n=3,
            ))
            (OUTPUT / f"candidate-{id_by_role[role]}.patch").write_text(patch, encoding="utf-8", newline="")
            SOURCE.write_text(patched, encoding="utf-8", newline="")
            matrix[role] = {}
            for case in CASES:
                result = run_case(case)
                passed = result.returncode == 0
                matrix[role][case] = passed
                records.append({
                    "candidate_id": id_by_role[role], "candidate_role_hidden": role,
                    "case_id": case, "exit_code": result.returncode, "passed": passed,
                    "stdout": result.stdout, "stderr": result.stderr,
                })
    finally:
        SOURCE.write_text(original, encoding="utf-8", newline="")

    baseline: dict[str, bool] = {}
    for case in CASES:
        result = run_case(case)
        baseline[case] = result.returncode == 0
        records.append({
            "candidate_id": None, "candidate_role_hidden": "base_snapshot",
            "case_id": case, "exit_code": result.returncode,
            "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr,
        })

    summary = {
        "schema_version": 1, "state": "OFFLINE_FEASIBILITY_ONLY",
        "model_contact_authorized": False, "family": "repeated-option-policy",
        "candidate_ids_hidden_role_map": id_by_role, "baseline_pass_by_case": baseline,
        "candidate_pass_matrix_hidden_roles": matrix, "code_sha256": code_hashes,
        "intended_positive_sets": {
            "case-01": ["append_all"], "case-02": ["last_value_wins"],
            "case-03": ["append_all"], "case-04": ["last_value_wins"],
        },
    }
    (OUTPUT / "candidate-test-records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "feasibility-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": baseline, "candidate_matrix": matrix, "candidate_ids": id_by_role}, indent=2))


if __name__ == "__main__":
    main()
