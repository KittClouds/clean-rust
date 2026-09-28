from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
E010 = Path(r"C:\rd-c\experiment-010")
OUT = ROOT / "inputs" / "fresh-integration-bank-v1c"
TARGET = Path(r"D:\cargo-targets\e011-fresh-integration-bank")
RUNTIME_CRATE = ROOT / "repairs" / "producer-order-v1" / "runtime-integration"
HASH_BIN = TARGET / "debug" / "e011-hash.exe"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blake3(data: bytes) -> str:
    result = subprocess.run([str(HASH_BIN), "--stdin"], input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("ascii").strip()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


def make_patch(before: str, after: str, path: str) -> str:
    import difflib

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    if before_lines and not before_lines[-1].endswith(("\n", "\r")):
        before_lines[-1] += "\n"
    if after_lines and not after_lines[-1].endswith(("\n", "\r")):
        after_lines[-1] += "\n"
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def archive_mutated_repo(repo_id: str, source: Path, relative_file: str, old: str, broken: str) -> tuple[Path, str, str]:
    revision = run(["git", "rev-parse", "HEAD"], source, os.environ.copy()).stdout.strip()
    status = run(["git", "status", "--porcelain"], source, os.environ.copy()).stdout
    if status.strip():
        raise RuntimeError(f"source repo {repo_id} is dirty; refusing to build the fresh bank")
    with tempfile.TemporaryDirectory(prefix=f"e011-{repo_id}-") as temp:
        temp_path = Path(temp)
        archive = temp_path / "source.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=source, stdout=output, check=True)
        extracted = temp_path / "repo"
        extracted.mkdir()
        with tarfile.open(archive, "r:") as stream:
            stream.extractall(extracted, filter="data")
        source_file = extracted / relative_file
        contents = source_file.read_text(encoding="utf-8")
        if contents.count(old) != 1:
            raise RuntimeError(f"expected one controlled source anchor in {repo_id}/{relative_file}")
        source_file.write_text(contents.replace(old, broken), encoding="utf-8", newline="")
        snapshot_path = OUT / "repositories" / f"{repo_id}-broken-source.tar"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(snapshot_path, "w", format=tarfile.PAX_FORMAT) as output:
            for path in sorted(extracted.rglob("*")):
                if path.is_file():
                    output.add(path, arcname=path.relative_to(extracted).as_posix(), recursive=False)
        return snapshot_path, revision, sha256(snapshot_path.read_bytes())


def candidate_set(task: dict, broken_text: str, fixed_text: str, wrong_text: str) -> list[dict]:
    rel_file = task["source_file"]
    baseline_contents = task["broken_file_contents"]
    if baseline_contents.count(broken_text) != 1:
        raise RuntimeError(f"expected one broken candidate anchor in {task['task_id']}")
    paths = [
        ("gold", baseline_contents.replace(broken_text, fixed_text), "Apply the focused implementation patch."),
        ("gold_comment", baseline_contents.replace(broken_text, task["comment"] + fixed_text), "Apply the focused patch with a contract comment."),
        ("mutant", baseline_contents.replace(broken_text, wrong_text), "Apply this plausible alternate change."),
        ("keep", baseline_contents, "Retain the current implementation."),
    ]
    rows = []
    for action_id, (variant, replacement, summary) in zip((11, 37, 68, 94), paths, strict=True):
        patch_text = make_patch(baseline_contents, replacement, rel_file)
        patch_path = OUT / "patches" / task["family"] / f"{variant}.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(patch_text, encoding="utf-8", newline="")
        rows.append({
            "action": {"id": action_id, "schema_id": 1},
            "summary": summary,
            "diff_excerpt": patch_text.strip() or "No source changes; keep the broken implementation.",
            "patch_sha256": sha256(patch_text.encode("utf-8")),
            "candidate_variant": variant,
        })
    return rows


def evaluate_candidate(
    bank_root: Path,
    snapshot_path: Path,
    frame: dict,
    candidate: dict,
    task: dict,
    env: dict[str, str],
) -> dict:
    with tempfile.TemporaryDirectory(prefix="e011-candidate-") as temp:
        work = Path(temp) / "repo"
        work.mkdir()
        with tarfile.open(snapshot_path, "r:") as stream:
            stream.extractall(work, filter="data")
        patch_path = bank_root / "patches" / task["family"] / f"{candidate['candidate_variant']}.patch"
        if patch_path.stat().st_size:
            result = run(["git", "apply", str(patch_path)], work, env)
            if result.returncode:
                raise RuntimeError(f"candidate patch failed to apply: {task['task_id']}/{candidate['candidate_variant']}\n{result.stderr}")
        command = ["cargo", "test", "--locked", "--manifest-path", str(work / task["manifest"])]
        command.extend(task["test_args"])
        command.extend([task["test_filter"], "--", "--exact"])
        started = datetime.now(timezone.utc)
        result = run(command, work, env)
        log = result.stdout + result.stderr
        ran = task["test_filter"] in log and ("... ok" in log or "... FAILED" in log)
        if not ran:
            # Compile-time trait checks fail before the test runner announces a test name.
            ran = task["compile_failure_is_test_evidence"] and re.search(r"error\[E\d+\]", log) is not None
        if not ran:
            raise RuntimeError(f"completion check did not run for {task['task_id']}/{candidate['candidate_variant']}\n{log[-2500:]}")
        log_path = bank_root / "precontact" / task["task_id"] / f"{candidate['candidate_variant']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(log, encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "action_id": candidate["action"]["id"],
            "candidate_variant": candidate["candidate_variant"],
            "patch_sha256": candidate["patch_sha256"],
            "test_filter": task["test_filter"],
            "command": command,
            "exit_code": result.returncode,
            "passed": result.returncode == 0,
            "log_sha256": sha256(log.encode("utf-8")),
            "log_path": str(log_path.relative_to(bank_root)).replace("\\", "/"),
            "started_at_utc": started.isoformat(),
        }


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty bank directory: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    subprocess.run(
        ["cargo", "build", "--quiet", "--manifest-path", str(RUNTIME_CRATE / "Cargo.toml"), "--bin", "e011-hash"],
        cwd=RUNTIME_CRATE,
        env=env,
        check=True,
    )

    ripgrep_source = E010 / "repositories" / "ripgrep" / "source"
    turbovec_source = E010 / "repositories" / "turbovec" / "source"
    rg_path = "crates/globset/src/glob.rs"
    rg_contents = (ripgrep_source / rg_path).read_text(encoding="utf-8")
    rg_fixed = "        self.opts.allow_unclosed_class = yes;"
    rg_broken = "        self.opts.allow_unclosed_class = !yes;"
    rg_wrong = "        self.opts.allow_unclosed_class = false;"
    rg_snapshot, rg_revision, rg_snapshot_hash = archive_mutated_repo(
        "ripgrep", ripgrep_source, rg_path, rg_fixed, rg_broken
    )
    rg_broken_contents = rg_contents.replace(rg_fixed, rg_broken)

    tv_path = "turbovec/src/lib.rs"
    tv_contents = (turbovec_source / tv_path).read_text(encoding="utf-8")
    tv_fixed = "#[derive(Debug, Clone, PartialEq)]\npub struct SearchResults {"
    tv_broken = "#[derive(Debug, PartialEq)]\npub struct SearchResults {"
    tv_wrong = "#[derive(Debug, Copy, Clone, PartialEq)]\npub struct SearchResults {"
    tv_snapshot, tv_revision, tv_snapshot_hash = archive_mutated_repo(
        "turbovec", turbovec_source, tv_path, tv_fixed, tv_broken
    )
    tv_broken_contents = tv_contents.replace(tv_fixed, tv_broken)

    tasks = [
        {
            "task_id": "fresh-ripgrep-unclosed-class-single-v1",
            "family": "ripgrep-unclosed-class-opt-in",
            "repository_id": "ripgrep",
            "snapshot": rg_snapshot,
            "snapshot_sha256": rg_snapshot_hash,
            "revision": rg_revision,
            "source_file": rg_path,
            "broken_text": rg_broken,
            "broken_file_contents": rg_broken_contents,
            "fixed_text": rg_fixed,
            "wrong_text": rg_wrong,
            "comment": "        // Preserve the caller's opt-in parser setting.\n",
            "manifest": "Cargo.toml",
            "test_args": ["-p", "globset", "--lib"],
            "test_filter": "glob::tests::allow_unclosed_class_single",
            "prompt": "The caller enables literal handling for an unfinished `[` class. Repair this option so the exact parser test accepts the literal bracket.",
            "evidence": "The task snapshot inverts the allow_unclosed_class setting. The frozen parser test expects an unfinished `[` to compile as a literal when the option is enabled.",
            "compile_failure_is_test_evidence": False,
        },
        {
            "task_id": "fresh-ripgrep-unclosed-class-many-v2",
            "family": "ripgrep-unclosed-class-opt-in",
            "repository_id": "ripgrep",
            "snapshot": rg_snapshot,
            "snapshot_sha256": rg_snapshot_hash,
            "revision": rg_revision,
            "source_file": rg_path,
            "broken_text": rg_broken,
            "broken_file_contents": rg_broken_contents,
            "fixed_text": rg_fixed,
            "wrong_text": rg_wrong,
            "comment": "        // Preserve the caller's opt-in parser setting.\n",
            "manifest": "Cargo.toml",
            "test_args": ["-p", "globset", "--lib"],
            "test_filter": "glob::tests::allow_unclosed_class_many",
            "prompt": "An enabled parser option should treat an unclosed `[abc` sequence as literal text. Choose a patch that restores that behavior in the frozen test.",
            "evidence": "The task snapshot negates the allow_unclosed_class option. The exact parser test checks literal treatment of an unfinished multi-character class.",
            "compile_failure_is_test_evidence": False,
        },
        {
            "task_id": "fresh-turbovec-search-results-clone-contract-v1",
            "family": "turbovec-search-results-clone-contract",
            "repository_id": "turbovec",
            "snapshot": tv_snapshot,
            "snapshot_sha256": tv_snapshot_hash,
            "revision": tv_revision,
            "source_file": tv_path,
            "broken_text": tv_broken,
            "broken_file_contents": tv_broken_contents,
            "fixed_text": tv_fixed,
            "wrong_text": tv_wrong,
            "comment": "/// Cloning owns independent result buffers.\n",
            "manifest": "turbovec/Cargo.toml",
            "test_args": ["-p", "turbovec", "--test", "crate_api"],
            "test_filter": "search_results_clone_is_independent_of_its_source",
            "prompt": "Restore the public result type's clone behavior. The frozen API test mutates a cloned score buffer and requires the original result to stay unchanged.",
            "evidence": "The task snapshot removed Clone from SearchResults. Its frozen API test calls clone, edits the copy, and checks that the source buffer is independent.",
            "compile_failure_is_test_evidence": True,
        },
        {
            "task_id": "fresh-turbovec-search-results-trait-set-v2",
            "family": "turbovec-search-results-clone-contract",
            "repository_id": "turbovec",
            "snapshot": tv_snapshot,
            "snapshot_sha256": tv_snapshot_hash,
            "revision": tv_revision,
            "source_file": tv_path,
            "broken_text": tv_broken,
            "broken_file_contents": tv_broken_contents,
            "fixed_text": tv_fixed,
            "wrong_text": tv_wrong,
            "comment": "/// Cloning owns independent result buffers.\n",
            "manifest": "turbovec/Cargo.toml",
            "test_args": ["-p", "turbovec", "--test", "crate_api"],
            "test_filter": "search_results_implements_the_downstream_derive_set",
            "prompt": "A downstream caller needs to clone a SearchResults value. Repair the missing trait so the compile-time and behavior checks in the exact API test pass.",
            "evidence": "The task snapshot removed Clone from SearchResults. The frozen public API test asserts Debug, Clone, and PartialEq support, then clones and compares the value.",
            "compile_failure_is_test_evidence": True,
        },
    ]

    test_records = []
    frame_rows = []
    labels = {}
    for task in tasks:
        if task["repository_id"] == "ripgrep":
            broken, fixed, wrong = rg_broken, rg_fixed, rg_wrong
        else:
            broken, fixed, wrong = tv_broken, tv_fixed, tv_wrong
        candidates = candidate_set(task, broken, fixed, wrong)
        snapshot_path = task["snapshot"]
        candidate_outcomes = {}
        for candidate in candidates:
            record = evaluate_candidate(OUT, snapshot_path, {}, candidate, task, env)
            test_records.append(record)
            candidate_outcomes[candidate["patch_sha256"]] = {
                "expected_task_completion": bool(record["passed"]),
                "candidate_variant": candidate["candidate_variant"],
                "test_filter": task["test_filter"],
            }
        if not candidate_outcomes[candidates[0]["patch_sha256"]]["expected_task_completion"]:
            raise RuntimeError(f"focused repair failed its exact test: {task['task_id']}")
        if not candidate_outcomes[candidates[1]["patch_sha256"]]["expected_task_completion"]:
            raise RuntimeError(f"commented focused repair failed its exact test: {task['task_id']}")

        source_evidence = task["evidence"]
        evidence_rows = [
            {
                "kind": "source_and_test_contract",
                "source_id": f"{task['repository_id']}/{task['source_file']}::{task['test_filter']}",
                "content_blake3": blake3(source_evidence.encode("utf-8")),
                "content": source_evidence,
            }
        ]
        option_rows = [
            {key: value for key, value in candidate.items() if key != "candidate_variant"}
            for candidate in candidates
        ]
        frame = {
            "schema_id": "rdc-real-coding-observation.v1",
            "task_id": task["task_id"],
            "task_family": task["family"],
            "task_prompt": task["prompt"],
            "repository_revision": task["revision"],
            "snapshot_sha256": task["snapshot_sha256"],
            "evidence": evidence_rows,
            "action_options": option_rows,
        }
        frame_rows.append({
            "frame": frame,
            "blake3": blake3(canonical(frame)),
            "producer_ordinals": list(range(len(option_rows))),
            "repository_id": task["repository_id"],
        })
        labels[task["task_id"]] = {
            "repository_id": task["repository_id"],
            "task_family": task["family"],
            "test_filter": task["test_filter"],
            "actions_by_patch_sha256": candidate_outcomes,
        }

    bank_root = OUT
    frames_lock_path = bank_root / "frame-lock.json"
    frames_lock_path.write_text(
        json.dumps({"schema_version": 1, "frames": frame_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    labels_path = bank_root / "sealed-labels.json"
    labels_path.write_text(
        json.dumps({"schema_version": 1, "state": "SEALED_PRECONTACT", "tasks": labels}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_rows = [
        {
            "task_id": task["task_id"],
            "task_family": task["family"],
            "repository_id": task["repository_id"],
            "snapshot_path": str(task["snapshot"].relative_to(bank_root)).replace("\\", "/"),
            "manifest": task["manifest"],
            "test_args": task["test_args"],
            "test_filter": task["test_filter"],
            "compile_failure_is_task_failure": task["compile_failure_is_test_evidence"],
            "candidate_patch_directory": f"patches/{task['family']}",
        }
        for task in tasks
    ]
    manifest_path = bank_root / "task-manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "tasks": manifest_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    build_receipt = {
        "schema_version": 1,
        "classification": "fresh integration-qualification bank built before E011 model contact",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repositories": {
            "ripgrep": {"revision": rg_revision, "broken_snapshot_sha256": rg_snapshot_hash},
            "turbovec": {"revision": tv_revision, "broken_snapshot_sha256": tv_snapshot_hash},
        },
        "candidate_test_count": len(test_records),
        "all_focused_repairs_pass": all(labels[row["task_id"]]["actions_by_patch_sha256"][row["patch_sha256"]]["expected_task_completion"] for row in test_records if row["candidate_variant"] in ("gold", "gold_comment")),
        "test_records": test_records,
    }
    (bank_root / "bank-build-receipt.json").write_text(
        json.dumps(build_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    frozen = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "bank_id": "e011-fresh-integration-bank-v1c",
        "frame_lock_sha256": sha256(frames_lock_path.read_bytes()),
        "sealed_labels_sha256": sha256(labels_path.read_bytes()),
        "bank_build_receipt_sha256": sha256((bank_root / "bank-build-receipt.json").read_bytes()),
        "task_manifest_sha256": sha256(manifest_path.read_bytes()),
        "system_prompt_sha256": sha256((E010 / "prompts" / "system-observer-v2.txt").read_bytes()),
        "output_schema_sha256": sha256((E010 / "schemas" / "observer-output.v2.json").read_bytes()),
        "bundle_lock_sha256": sha256((E010 / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json").read_bytes()),
        "thresholds_sha256": sha256((E010 / "models" / "bundle-lineage" / "selected-thresholds-v5.json").read_bytes()),
        "thresholds": {"minimum_applicability_milli": 850, "maximum_abstention_milli": 150},
        "task_count": len(frame_rows),
        "repositories": {"ripgrep": 2, "turbovec": 2},
        "presentation_contract": "producer-order ordinal is assigned at frame construction; carry ordinal, restore ascending order before serialization; receipt is bound to task digest and ordered action ID/patch digest pairs",
    }
    freeze_path = bank_root / "bank-freeze.json"
    freeze_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bank": str(bank_root), "tasks": len(frame_rows), "tests": len(test_records), "frame_lock_sha256": frozen["frame_lock_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
