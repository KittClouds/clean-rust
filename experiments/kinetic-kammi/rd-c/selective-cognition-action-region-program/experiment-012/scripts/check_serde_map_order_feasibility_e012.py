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
HARNESS = CONSTRUCTION / "task-harnesses" / "serde-map-order"
TARGET = CONSTRUCTION / "target" / "serde-json-harness"
OUTPUT = CONSTRUCTION / "feasibility" / "serde-map-order"
SOURCE = HARNESS / "src" / "lib.rs"
CASES = {"case-01": False, "case-02": True, "case-03": False, "case-04": True}
ANCHOR = "    // E012 candidate slot.\n    Some(object.keys().cloned().collect())"
CANDIDATES = {
    "preserve_order_only": '''    #[cfg(feature = "preserve_order")]
    { Some(object.keys().cloned().collect()) }
    #[cfg(not(feature = "preserve_order"))]
    { None }''',
    "sorted_profile_only": '''    #[cfg(not(feature = "preserve_order"))]
    { Some(object.keys().cloned().collect()) }
    #[cfg(feature = "preserve_order")]
    { None }''',
    "canonical_sort": "    let mut object = object.clone();\n    object.sort_keys();\n    Some(object.keys().cloned().collect())",
    "reverse_native": "    Some(object.keys().rev().cloned().collect())",
}


def run_case(case: str, preserve_order: bool) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    env["E012_CASE"] = case
    command = ["cargo", "test", "--offline", "--manifest-path", str(HARNESS / "Cargo.toml")]
    if preserve_order:
        command.extend(["--features", "preserve_order"])
    command.extend(["--test", "contract", "--", "--exact", "check_contract"])
    return subprocess.run(command, cwd=HARNESS, env=env, capture_output=True, text=True, encoding="utf-8")


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite feasibility output: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    original = SOURCE.read_text(encoding="utf-8")
    if original.count(ANCHOR) != 1:
        raise SystemExit("candidate anchor is absent or ambiguous")
    rng = random.Random(20260925 ^ 0x5E2D3A71)
    ids = rng.sample(range(20000, 65000), len(CANDIDATES))
    id_by_role = dict(zip(CANDIDATES, ids, strict=True))
    matrix: dict[str, dict[str, bool]] = {}
    records: list[dict] = []
    hashes = {"base": hashlib.sha256(original.encode()).hexdigest()}
    try:
        for role, body in CANDIDATES.items():
            patched = original.replace(ANCHOR, body, 1)
            hashes[role] = hashlib.sha256(patched.encode()).hexdigest()
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True), patched.splitlines(keepends=True),
                fromfile="a/src/lib.rs", tofile="b/src/lib.rs", n=3,
            ))
            (OUTPUT / f"candidate-{id_by_role[role]}.patch").write_text(diff, encoding="utf-8", newline="")
            SOURCE.write_text(patched, encoding="utf-8", newline="")
            matrix[role] = {}
            for case, feature_on in CASES.items():
                result = run_case(case, feature_on)
                passed = result.returncode == 0
                matrix[role][case] = passed
                records.append({
                    "candidate_id": id_by_role[role], "candidate_role_hidden": role,
                    "case_id": case, "preserve_order": feature_on, "exit_code": result.returncode,
                    "passed": passed, "stdout": result.stdout, "stderr": result.stderr,
                })
    finally:
        SOURCE.write_text(original, encoding="utf-8", newline="")
    baseline: dict[str, bool] = {}
    for case, feature_on in CASES.items():
        result = run_case(case, feature_on)
        baseline[case] = result.returncode == 0
        records.append({
            "candidate_id": None, "candidate_role_hidden": "base_snapshot", "case_id": case,
            "preserve_order": feature_on, "exit_code": result.returncode,
            "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr,
        })
    summary = {
        "schema_version": 1, "state": "OFFLINE_FEASIBILITY_ONLY",
        "model_contact_authorized": False, "family": "map-order-feature-contract",
        "candidate_ids_hidden_role_map": id_by_role, "baseline_pass_by_case": baseline,
        "candidate_pass_matrix_hidden_roles": matrix, "code_sha256": hashes,
        "intended_contract": "Preserve input order with preserve_order enabled and emit lexical order without it; the typed Cargo feature state is the context channel.",
    }
    (OUTPUT / "candidate-test-records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "feasibility-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": baseline, "candidate_matrix": matrix, "candidate_ids": id_by_role}, indent=2))


if __name__ == "__main__":
    main()
