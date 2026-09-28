from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
BANK = CONSTRUCTION / "scored-bank-v1"
SOURCE_FIXTURES = BANK / "vault" / "task-source-fixtures.json"
SELECTED = CONSTRUCTION / "feasibility"
HARNESS_ROOT = CONSTRUCTION / "task-harnesses"
REPOSITORIES = CONSTRUCTION / "repositories"
STAGING = BANK / "check-staging"
OUTPUT = BANK / "vault" / "candidate-check-results.json"
TARGET_ROOT = Path(r"D:\rdc-e012-target\scored-checks")
FAMILY_HARNESS = {
    "bounded-prefix-copy": "bytes-prefix",
    "cursor-advance-observation": "bytes-cursor-repair-01",
    "composite-frame-field": "bytes-composite-repair-01",
    "wire-endian-contract": "bytes-endian",
    "number-mode-plus-error-site": "serde-numeric-joint-repair-01",
    "repeated-option-policy": "clap-repeat-repair-01",
    "map-order-feature-contract": "serde-map-order-repair-02",
    "conflicting-alias-requirement": "clap-alias",
    "possible-value-validation": "clap-values",
    "stream-byte-offset": "serde-offset-repair-02",
    "help-color-capability": "clap-color-repair-01",
    "raw-number-lossless": "serde-raw-number",
}
FULL_SUITE_FAMILIES = {
    "bounded-prefix-copy", "possible-value-validation",
    "conflicting-alias-requirement", "raw-number-lossless",
}
PREFIX_TEST = r'''
#[test]
fn zero_copy_storage_contract() {
    let input = Bytes::from_static(b"bounded-prefix-storage");
    let expected_ptr = input.as_ptr();
    let prefix = take_prefix(input.clone(), 7);
    assert_eq!(prefix.as_ref(), b"bounded");
    assert_eq!(prefix.as_ptr(), expected_ptr, "prefix must share input storage");
}
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_unified_patch(source: str, patch: str) -> str:
    if "--- a/src/lib.rs" not in patch or "+++ b/src/lib.rs" not in patch:
        raise ValueError("candidate patch does not target only src/lib.rs")
    source_lines = source.splitlines(keepends=True)
    patch_lines = patch.splitlines(keepends=True)
    hunk = next((index for index, line in enumerate(patch_lines) if line.startswith("@@")), None)
    if hunk is None:
        if patch.strip():
            raise ValueError("nonempty candidate patch has no unified hunk")
        return source
    match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", patch_lines[hunk])
    if not match:
        raise ValueError("unsupported unified hunk header")
    source_index = int(match.group(1)) - 1
    output = source_lines[:source_index]
    for line in patch_lines[hunk + 1 :]:
        if line.startswith(("@@", "--- ", "+++ ")):
            break
        marker, payload = line[:1], line[1:]
        if marker == " ":
            if source_index >= len(source_lines) or source_lines[source_index] != payload:
                raise ValueError("candidate patch context does not match frozen task source")
            output.append(source_lines[source_index])
            source_index += 1
        elif marker == "-":
            if source_index >= len(source_lines) or source_lines[source_index] != payload:
                raise ValueError("candidate patch removal does not match frozen task source")
            source_index += 1
        elif marker == "+":
            output.append(payload)
        elif marker == "\\":
            continue
        else:
            raise ValueError(f"unsupported patch line marker {marker!r}")
    output.extend(source_lines[source_index:])
    return "".join(output)


def copy_harness(family: str, trial_root: Path) -> tuple[Path, Path]:
    source = HARNESS_ROOT / FAMILY_HARNESS[family]
    project = trial_root / "project"
    shutil.copytree(source, project)
    manifest = project / "Cargo.toml"
    text = manifest.read_text(encoding="utf-8")
    for repo_id in ("bytes", "clap", "serde-json"):
        original = f'path = "../../repositories/{repo_id}"'
        absolute = (REPOSITORIES / repo_id).as_posix()
        text = text.replace(original, f'path = "{absolute}"')
    manifest.write_text(text, encoding="utf-8", newline="")
    return project, manifest


def add_prefix_contract(project: Path) -> None:
    test_path = project / "tests" / "contract.rs"
    text = test_path.read_text(encoding="utf-8")
    if "fn zero_copy_storage_contract()" in text:
        raise ValueError("prefix contract already present in frozen task source")
    test_path.write_text(text.rstrip() + "\n" + PREFIX_TEST, encoding="utf-8", newline="")


def instrument_task_failure_diagnostics(project: Path, family: str) -> None:
    """Improve cloned-harness failure messages without changing pass/fail behavior."""
    test_path = project / "tests" / "contract.rs"
    text = test_path.read_text(encoding="utf-8")
    if family == "help-color-capability":
        before = 'assert!(configured_color() == expected, "task contract failed");'
        after = 'assert_eq!(configured_color(), expected, "terminal color policy mismatch");'
    elif family == "map-order-feature-contract":
        before = 'assert!(actual.iter().map(String::as_str).eq(expected.iter().copied()), "task contract failed");'
        after = (
            'let actual: Vec<&str> = actual.iter().map(String::as_str).collect();\n'
            '    assert_eq!(actual.as_slice(), expected, "map iteration order mismatch");'
        )
    else:
        return
    if text.count(before) != 1:
        raise ValueError(f"expected one frozen generic assertion in {family} test overlay")
    test_path.write_text(text.replace(before, after), encoding="utf-8", newline="")


def run_case(project: Path, manifest: Path, family: str, case: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET_ROOT / FAMILY_HARNESS[family])
    env["E012_CASE"] = case
    command = ["cargo", "test", "--offline", "--manifest-path", str(manifest), "--test", "contract"]
    if family == "map-order-feature-contract" and case in {"case-02", "case-04"}:
        command.extend(["--features", "preserve_order"])
    result = subprocess.run(
        command,
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = result.stdout + "\n" + result.stderr
    compile_failed = result.returncode != 0 and (
        "could not compile" in combined.lower()
        or "error[E" in combined
        or "failed to parse manifest" in combined.lower()
        or "no matching package" in combined.lower()
    )
    return {
        "case_id": case,
        "command": command,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "compile_failed": compile_failed,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def trial(
    task: dict[str, Any],
    action_id: int | None,
    role: str | None,
    patch_text: str | None,
    check_cases: list[str],
    base: bool = False,
) -> dict[str, Any]:
    family = task["family_name_hidden"]
    with tempfile.TemporaryDirectory(prefix="trial-", dir=STAGING) as name:
        trial_root = Path(name)
        project, manifest = copy_harness(family, trial_root)
        source_path = project / "src" / "lib.rs"
        original = source_path.read_text(encoding="utf-8")
        if not base and patch_text is not None:
            source_path.write_text(apply_unified_patch(original, patch_text), encoding="utf-8", newline="")
        if family == "bounded-prefix-copy":
            add_prefix_contract(project)
        instrument_task_failure_diagnostics(project, family)
        source_digest = digest(source_path.read_bytes())
        test_digest = digest((project / "tests" / "contract.rs").read_bytes())
        checks = [run_case(project, manifest, family, case) for case in check_cases]
        return {
            "task_id": task["task_id"],
            "family_hidden": family,
            "repository_hidden": task["repository_id_hidden"],
            "action_id_hidden": action_id,
            "candidate_role_hidden": role,
            "patch_sha256_hidden": digest(patch_text.encode("utf-8")) if patch_text is not None else None,
            "base_snapshot": base,
            "overlay_source_sha256": source_digest,
            "overlay_test_sha256": test_digest,
            "check_cases": checks,
            "task_candidate_passed": bool(checks) and all(row["passed"] for row in checks),
            "compile_failed": any(row["compile_failed"] for row in checks),
        }


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite scored candidate checks: {OUTPUT}")
    source = json.loads(SOURCE_FIXTURES.read_text(encoding="utf-8"))
    tasks = source["tasks_hidden"]
    STAGING.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    base_rows: list[dict[str, Any]] = []
    expected_rows = 0
    for task in tasks:
        family = task["family_name_hidden"]
        selected_dir = task["feasibility_dir_hidden"]
        feasibility = SELECTED / selected_dir
        role_by_id = {int(k): v for k, v in task["candidate_role_by_action_id_hidden"].items()}
        patches = {
            role: (feasibility / f"candidate-{role_id}.patch").read_text(encoding="utf-8")
            for role, role_id in json.loads((feasibility / "feasibility-summary.json").read_text(encoding="utf-8"))["candidate_ids_hidden_role_map"].items()
        }
        candidate_case_list = task["check_cases"]
        for option in task["candidate_options_hidden"]:
            role = role_by_id[int(option["action"]["id"])]
            result = trial(task, int(option["action"]["id"]), role, patches[role], candidate_case_list)
            rows.append(result)
            expected_rows += 1
        base_rows.append(trial(task, None, None, None, candidate_case_list, base=True))
    if len(rows) != 192 or len(base_rows) != 48:
        raise ValueError(f"expected 192 candidate-task and 48 base-task rows, got {len(rows)} and {len(base_rows)}")
    case_invocations = sum(len(row["check_cases"]) for row in rows)
    base_invocations = sum(len(row["check_cases"]) for row in base_rows)
    if case_invocations != 384 or base_invocations != 96:
        raise ValueError(f"case invocation counts drifted: candidates={case_invocations}, base={base_invocations}")
    if any(row["compile_failed"] for row in rows + base_rows):
        state = "CONSTRUCTION_FAILURE_COMPILER_ERROR"
    else:
        state = "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT"
    output = {
        "schema_version": 1,
        "state": state,
        "model_contact_authorized": False,
        "candidate_task_rows": len(rows),
        "candidate_case_invocations": case_invocations,
        "base_task_rows": len(base_rows),
        "base_case_invocations": base_invocations,
        "candidate_rows": rows,
        "base_rows": base_rows,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "candidate_rows": len(rows), "candidate_case_invocations": case_invocations, "base_rows": len(base_rows), "base_case_invocations": base_invocations, "output": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
