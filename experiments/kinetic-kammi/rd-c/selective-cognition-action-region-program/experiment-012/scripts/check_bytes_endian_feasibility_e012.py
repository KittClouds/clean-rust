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
HARNESS = CONSTRUCTION / "task-harnesses" / "bytes-endian"
TARGET = CONSTRUCTION / "target" / "bytes-harness"
OUTPUT = CONSTRUCTION / "feasibility" / "bytes-endian"
SOURCE = HARNESS / "src" / "lib.rs"
CASES = ("case-01", "case-02", "case-03", "case-04")
MARKER = "    // The frozen task snapshot drops the requested word.\n    let _ = value;"

CANDIDATES = {
    "emit_big_endian_word": "    out.put_u16(value);",
    "emit_little_endian_word": "    out.put_u16_le(value);",
    "emit_zero_word": "    out.put_u16(0);",
    "emit_word_with_extra_byte": "    out.put_u16(value);\n    out.put_u8(0);",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite feasibility output: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    original = SOURCE.read_text(encoding="utf-8")
    if original.count(MARKER) != 1:
        raise SystemExit("candidate insertion marker is absent or ambiguous")
    lock = json.loads((CONSTRUCTION / "family-design-lock-v1.json").read_text(encoding="utf-8"))
    if lock["state"] != "FROZEN_BEFORE_TASK_FIXTURES" or lock["model_contact_authorized"]:
        raise SystemExit("family design is not frozen or model contact is unexpectedly authorized")

    rng = random.Random(20260925 ^ 0xE012)
    ids = rng.sample(range(20000, 65000), len(CANDIDATES))
    id_by_role = dict(zip(CANDIDATES, ids, strict=True))
    matrix: dict[str, dict[str, bool]] = {}
    code_hashes: dict[str, str] = {"base": sha256(original.encode("utf-8"))}
    records: list[dict] = []

    try:
        for role, body in CANDIDATES.items():
            patched = original.replace(MARKER, body, 1)
            code_hashes[role] = sha256(patched.encode("utf-8"))
            patch = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    patched.splitlines(keepends=True),
                    fromfile="a/src/lib.rs",
                    tofile="b/src/lib.rs",
                    n=3,
                )
            )
            (OUTPUT / f"candidate-{id_by_role[role]}.patch").write_text(patch, encoding="utf-8", newline="")
            SOURCE.write_text(patched, encoding="utf-8", newline="")
            matrix[role] = {}
            for case in CASES:
                env = os.environ.copy()
                env["CARGO_TARGET_DIR"] = str(TARGET)
                env["E012_CASE"] = case
                result = subprocess.run(
                    ["cargo", "test", "--offline", "--manifest-path", str(HARNESS / "Cargo.toml"),
                     "--test", "contract", "--", "--exact", "check_contract"],
                    cwd=HARNESS,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                passed = result.returncode == 0
                matrix[role][case] = passed
                records.append(
                    {
                        "candidate_id": id_by_role[role],
                        "candidate_role_hidden": role,
                        "case_id": case,
                        "exit_code": result.returncode,
                        "passed": passed,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
    finally:
        SOURCE.write_text(original, encoding="utf-8", newline="")

    baseline: dict[str, bool] = {}
    for case in CASES:
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(TARGET)
        env["E012_CASE"] = case
        result = subprocess.run(
            ["cargo", "test", "--offline", "--manifest-path", str(HARNESS / "Cargo.toml"),
             "--test", "contract", "--", "--exact", "check_contract"],
            cwd=HARNESS,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        baseline[case] = result.returncode == 0
        records.append(
            {
                "candidate_id": None,
                "candidate_role_hidden": "base_snapshot",
                "case_id": case,
                "exit_code": result.returncode,
                "passed": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )

    summary = {
        "schema_version": 1,
        "state": "OFFLINE_FEASIBILITY_ONLY",
        "model_contact_authorized": False,
        "family": "wire-endian-contract",
        "candidate_ids_hidden_role_map": id_by_role,
        "baseline_pass_by_case": baseline,
        "candidate_pass_matrix_hidden_roles": matrix,
        "code_sha256": code_hashes,
        "records_path": "candidate-test-records.json",
        "intended_positive_sets": {
            "case-01": ["emit_big_endian_word"],
            "case-02": ["emit_little_endian_word"],
            "case-03": ["emit_little_endian_word"],
            "case-04": ["emit_big_endian_word"],
        },
    }
    (OUTPUT / "candidate-test-records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "feasibility-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"baseline": baseline, "candidate_matrix": matrix, "candidate_ids": id_by_role}, indent=2))


if __name__ == "__main__":
    main()
