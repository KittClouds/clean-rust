from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "task-bank-plan.json"
BANK_NAME = "heldout-bank-v1"
BANK = ROOT / "tasks" / BANK_NAME
TARGET_ROOT = Path(r"D:\cargo-targets\rdc-e010\bank")
HASH_BIN = Path(r"D:\cargo-targets\rdc-e010\hash-tools\release\e010-artifact-hash.exe")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def blake3_bytes(data: bytes) -> str:
    temp = ROOT / "artifacts" / "hash-input.tmp"
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(data)
    result = subprocess.run([str(HASH_BIN), str(temp)], check=True, capture_output=True, text=True)
    return result.stdout.rstrip("\r\n").split("\t", 1)[1]


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(source: Path, *args: str) -> str:
    result = run(["git", "-C", str(source), *args], ROOT)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed in {source}: {result.stderr}")
    return result.stdout.strip()


def archive_repo(repo_id: str, repo: dict) -> tuple[str, str, Path, Path]:
    source = ROOT / repo["source_path"]
    if git(source, "status", "--porcelain"):
        raise RuntimeError(f"source checkout has uncommitted changes: {source}")
    revision = git(source, "rev-parse", "HEAD")
    archive = BANK / "repositories" / f"{repo_id}-{revision}.tar"
    archive.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", revision],
        cwd=ROOT,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"git archive failed for {repo_id}: {result.stderr.decode(errors='replace')}")
    archive.write_bytes(result.stdout)
    return revision, sha256(result.stdout), archive, source


def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:") as handle:
        handle.extractall(destination, filter="data")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    old_bytes = old.replace("\n", newline).encode("utf-8")
    count = raw.count(old_bytes)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact occurrence in {path}, found {count}")
    new_bytes = new.replace("\n", newline).encode("utf-8")
    path.write_bytes(raw.replace(old_bytes, new_bytes, 1))


def family_snapshot_hash(root: Path, output: Path) -> str:
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as handle:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in {".git", "target", ".venv", "__pycache__"} for part in relative.parts):
                continue
            info = handle.gettarinfo(str(path), arcname=relative.as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with path.open("rb") as stream:
                handle.addfile(info, stream)
    return sha256(output.read_bytes())


def patch_bytes(before: str, after: str, relative_file: str) -> bytes:
    if before == after:
        return b""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{relative_file}",
        tofile=f"b/{relative_file}",
        lineterm="\n",
    )
    output = "".join(lines)
    if not output.endswith("\n"):
        output += "\n"
    return output.encode("utf-8")


def copy_snapshot(source: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(".git", "target", ".venv", "__pycache__", "tmp")
    shutil.copytree(source, destination, ignore=ignored)


def test_command(manifest: Path, package: str, case: dict) -> list[str]:
    command = ["cargo", "test", "--locked", "--manifest-path", str(manifest), "--package", package]
    command.extend(case.get("features", []))
    command.extend(case["test_args"])
    command.extend([case["test_filter"], "--", "--exact"])
    return command


def run_exact_test(manifest: Path, package: str, case: dict, target: Path) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    clean = run(["cargo", "clean", "--manifest-path", str(manifest), "--package", package], manifest.parent, env)
    if clean.returncode:
        raise RuntimeError(f"cargo clean failed for {manifest}: {clean.stderr[-2000:]}")
    command = test_command(manifest, package, case)
    result = run(command, manifest.parent, env)
    output = result.stdout + result.stderr
    test_re = rf"test\s+{re.escape(case['test_filter'])}\s+\.\.\.\s+(?:ok|FAILED)"
    if re.search(test_re, output) is None:
        raise RuntimeError(f"exact test did not run ({case['family']}):\n{output[-3000:]}")
    return {
        "command": command,
        "exit_code": result.returncode,
        "passed": result.returncode == 0 and "test result: ok. 1 passed;" in output,
        "output": output,
        "output_sha256": sha256(output.encode("utf-8")),
    }


def excerpt(text: str, needle: str, radius: int = 2) -> str:
    lines = text.splitlines()
    needle_line = next((i for i, line in enumerate(lines) if needle.strip() in line), None)
    if needle_line is None:
        return "\n".join(lines[:8])
    low = max(0, needle_line - radius)
    high = min(len(lines), needle_line + radius + 1)
    return "\n".join(lines[low:high])


def build_family(repo_id: str, repo: dict, case: dict, revision: str, archive_sha256: str, source: Path, archive: Path, labels: dict, candidate_families: dict, build_checks: dict, repo_case_target: Path) -> list[dict]:
    family = case["family"]
    family_root = BANK / "families" / family
    if family_root.exists():
        raise RuntimeError(f"bank family already exists: {family_root}")
    family_root.mkdir(parents=True)
    family_source = family_root / "source-broken"
    extract_archive(archive, family_source)
    source_file = family_source / case["file"]
    original_source = source_file.read_text(encoding="utf-8")
    if original_source.count(case["old"]) != 1:
        raise RuntimeError(f"source anchor does not match exactly once: {family}/{case['file']}")
    replace_once(source_file, case["old"], case["broken"], f"inject {family}")
    broken_source = source_file.read_text(encoding="utf-8")
    snapshot_tar = family_root / "source-snapshot.tar"
    snapshot_sha = family_snapshot_hash(family_source, snapshot_tar)

    baseline = run_exact_test(
        family_source / repo["workspace_manifest"],
        case.get("package_name", repo.get("package_name")),
        case,
        repo_case_target,
    )
    if baseline["passed"]:
        raise RuntimeError(f"injected regression did not fail its exact test: {family}")
    baseline_log = family_root / "completion" / "baseline.log"
    baseline_log.parent.mkdir(parents=True)
    baseline_log.write_text(baseline["output"], encoding="utf-8", newline="\n")

    candidate_variants = {
        "keep": broken_source,
        "gold": broken_source.replace(case["broken"], case["gold"], 1),
        "gold_comment": broken_source.replace(case["broken"], case["gold"], 1),
        "mutant": broken_source.replace(case["broken"], case["mutant"], 1),
    }
    if broken_source.count(case["broken"]) != 1:
        raise RuntimeError(f"broken source anchor does not match exactly once: {family}")
    if candidate_variants["gold_comment"] == broken_source or candidate_variants["mutant"] == broken_source:
        raise RuntimeError(f"candidate replacement did not change source for {family}")
    anchor = case["comment_anchor"]
    if candidate_variants["gold_comment"].count(anchor) != 1:
        raise RuntimeError(f"comment anchor does not match exactly once for {family}")
    candidate_variants["gold_comment"] = candidate_variants["gold_comment"].replace(
        anchor, case["comment"] + anchor, 1
    )
    candidate_info: dict[str, dict] = {}
    for variant, candidate_source in candidate_variants.items():
        candidate_root = family_root / "candidates" / variant
        copy_snapshot(family_source, candidate_root)
        candidate_file = candidate_root / case["file"]
        candidate_file.write_text(candidate_source, encoding="utf-8", newline="\n")
        patch = patch_bytes(broken_source, candidate_source, case["file"])
        patch_path = family_root / f"{variant}.patch"
        patch_path.write_bytes(patch)
        patch_hash = sha256(patch)
        manifest = candidate_root / repo["workspace_manifest"]
        test = run_exact_test(
            manifest,
            case.get("package_name", repo.get("package_name")),
            case,
            repo_case_target,
        )
        expected = variant in {"gold", "gold_comment"}
        if test["passed"] != expected:
            log_path = family_root / "completion" / f"{variant}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(test["output"], encoding="utf-8", newline="\n")
            raise RuntimeError(f"unexpected exact test result for {family}/{variant}: expected {expected}, got {test['passed']}\n{test['output'][-2500:]}")
        completion_log = family_root / "completion" / f"{variant}.log"
        completion_log.parent.mkdir(parents=True, exist_ok=True)
        completion_log.write_text(test["output"], encoding="utf-8", newline="\n")
        candidate_info[variant] = {
            "candidate_root": candidate_root.relative_to(ROOT).as_posix(),
            "manifest": manifest.relative_to(ROOT).as_posix(),
            "patch": patch_path.relative_to(ROOT).as_posix(),
            "patch_sha256": patch_hash,
            "passed": test["passed"],
            "command": test["command"],
            "completion_log": completion_log.relative_to(ROOT).as_posix(),
            "completion_log_sha256": sha256(test["output"].replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")),
        }
        build_checks.setdefault(family, {})[variant] = {
            **{key: value for key, value in candidate_info[variant].items() if key not in {"candidate_root", "manifest", "patch"}},
            "failed_as_expected": not test["passed"],
        }

    baseline_text = baseline["output"].replace("\r\n", "\n").replace("\r", "\n")
    public_test_output = baseline_text.replace(str(family_source), "<frozen-repository-snapshot>")
    public_test_output = public_test_output.replace(str(TARGET_ROOT / repo_id), "<cargo-target>")
    public_test_output = public_test_output[-2200:]
    source_excerpt = excerpt(broken_source, case["broken"])
    source_rel = case["file"]
    baseline_evidence = f"Exact test `{case['test_filter']}` failed on the frozen snapshot. Candidate patches have not been run in this task.\n{public_test_output}"
    evidence = [
        {
            "kind": "source_excerpt",
            "source_id": source_rel,
            "content_blake3": blake3_bytes(source_excerpt.encode("utf-8")),
            "content": source_excerpt,
        },
        {
            "kind": "baseline_tool_result",
            "source_id": f"cargo-test::{case['test_filter']}",
            "content_blake3": blake3_bytes(baseline_evidence.encode("utf-8")),
            "content": baseline_evidence,
        },
    ]
    task_frames: list[dict] = []
    action_ids = [11, 37, 68, 94]
    variant_descriptions = {
        "gold": ("Apply the focused source change shown here.", "The patch restores the targeted implementation behavior."),
        "gold_comment": ("Apply the source change and add a contract comment.", "The patch changes the implementation and documents its intended behavior."),
        "mutant": ("Apply this alternative change in the same code path.", "The patch changes the targeted expression to a different behavior."),
        "keep": ("Leave the current implementation unchanged.", "No source line changes are included."),
    }
    for prompt_index, prompt in enumerate(case["prompts"], 1):
        task_id = f"{repo_id}-{family}-v{prompt_index}"
        order = list(candidate_info)
        random.Random(int(sha256(task_id.encode("utf-8"))[:16], 16)).shuffle(order)
        actions = []
        action_to_patch: dict[str, dict] = {}
        for position, variant in enumerate(order):
            item = candidate_info[variant]
            action_id = action_ids[position]
            patch_text = (family_root / f"{variant}.patch").read_text(encoding="utf-8")
            diff = "\n".join(line for line in patch_text.splitlines() if line.startswith(("@@", "+", "-")) and not line.startswith(("+++", "---")))
            summary, fallback_excerpt = variant_descriptions[variant]
            option = {
                "action": {"id": action_id, "schema_id": 1},
                "summary": summary,
                "diff_excerpt": diff[:700] if diff else fallback_excerpt,
                "patch_sha256": item["patch_sha256"],
            }
            actions.append(option)
            action_to_patch[str(action_id)] = {"variant": variant, "patch_sha256": item["patch_sha256"]}
            labels.setdefault(task_id, {"actions_by_patch_sha256": {}, "difficulty": "heldout"})
            labels[task_id]["actions_by_patch_sha256"][item["patch_sha256"]] = {
                "expected_task_completion": item["passed"],
                "candidate_variant": variant,
            }
        frame = {
            "schema_id": "rdc-real-coding-observation.v1",
            "task_id": task_id,
            "task_family": family,
            "repository_id": repo_id,
            "task_variant": prompt_index,
            "task_prompt": prompt,
            "repository_revision": revision,
            "snapshot_sha256": snapshot_sha,
            "evidence": evidence,
            "action_options": actions,
        }
        task_frames.append(frame)
        action_to_patch.clear()
    candidate_families[family] = {
        "repository_id": repo_id,
        "repository_revision": revision,
        "snapshot_sha256": snapshot_sha,
        "test_filter": case["test_filter"],
        "test_args": case["test_args"],
        "package_name": case.get("package_name", repo.get("package_name")),
        "features": case.get("features", []),
        "variants": candidate_info,
    }
    return task_frames


def tree_hash(directory: Path, excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.name not in excluded):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    if BANK.exists():
        raise SystemExit(f"refusing to overwrite an existing bank: {BANK}")
    plan = read_json(PLAN)
    if len(plan["repositories"]) != 2 or sum(len(item["families"]) for item in plan["repositories"].values()) != 8:
        raise SystemExit("E010 requires two repositories and exactly four families in each")
    BANK.mkdir(parents=True)
    labels: dict[str, dict] = {}
    candidate_families: dict[str, dict] = {}
    build_checks: dict[str, dict] = {}
    frames: list[dict] = []
    repository_locks: dict[str, dict] = {}

    for repo_id, repo in plan["repositories"].items():
        revision, archive_sha, archive, source = archive_repo(repo_id, repo)
        repository_locks[repo_id] = {
            "source_path": repo["source_path"],
            "revision": revision,
            "archive": archive.relative_to(ROOT).as_posix(),
            "archive_sha256": archive_sha,
            "working_tree_clean": True,
        }
        for case in repo["families"]:
            target = TARGET_ROOT / repo_id
            target.mkdir(parents=True, exist_ok=True)
            frames.extend(build_family(repo_id, repo, case, revision, archive_sha, source, archive, labels, candidate_families, build_checks, target))
            print(f"precontact validated {case['family']}: baseline and 4 candidate tests")

    frame_lock = {
        "schema_version": 1,
        "bank_role": "heldout-only-cross-repository-transfer",
        "frames": [],
    }
    for frame in frames:
        frame_bytes = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        frame_lock["frames"].append({"frame": frame, "blake3": blake3_bytes(frame_bytes)})
    bank_root = BANK
    write_json(bank_root / "frame-lock.json", frame_lock)
    write_json(bank_root / "frames-unlocked.json", {"frames": frames})
    write_json(bank_root / "sealed-labels.json", {"schema_version": 1, "tasks": labels})
    revision_digest = sha256(json.dumps({key: value["revision"] for key, value in repository_locks.items()}, sort_keys=True).encode("utf-8"))
    candidate_lock = {
        "schema_version": 1,
        "repository_revision": f"multi-repository:{revision_digest}",
        "repositories": repository_locks,
        "families": candidate_families,
    }
    write_json(bank_root / "candidate-lock.json", candidate_lock)
    write_json(bank_root / "split-manifest.json", {
        "schema_version": 1,
        "design": "2 repositories x 4 families per repository x 2 prompt variants",
        "development_bank": None,
        "heldout_task_count": len(frames),
        "repository_unit": list(repository_locks),
        "selection_source": "pre-contact committed repository source and test inventory",
        "observer_outputs_consulted": False,
    })
    receipt = {
        "schema_version": 1,
        "source_repositories": repository_locks,
        "source_archive_sha256": {key: value["archive_sha256"] for key, value in repository_locks.items()},
        "family_count": len(candidate_families),
        "task_count": len(frames),
        "families_by_repository": {repo_id: [case["family"] for case in repo["families"]] for repo_id, repo in plan["repositories"].items()},
        "task_snapshot_policy": "clean commit archive plus one controlled production-code regression per family",
        "completion_checks": build_checks,
        "precontact_labels_created": True,
        "observer_outputs_consulted": False,
    }
    write_json(bank_root / "bank-build-receipt.json", receipt)
    freeze = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": plan["run_id"],
        "repository_locks": repository_locks,
        "sha256": {
            "frame_lock": sha256((bank_root / "frame-lock.json").read_bytes()),
            "candidate_lock": sha256((bank_root / "candidate-lock.json").read_bytes()),
            "sealed_labels": sha256((bank_root / "sealed-labels.json").read_bytes()),
            "bank_build_receipt": sha256((bank_root / "bank-build-receipt.json").read_bytes()),
            "builder": sha256(Path(__file__).read_bytes()),
            "plan": sha256(PLAN.read_bytes()),
        },
        "bank_tree_sha256_excluding_freeze": tree_hash(bank_root, {"bank-freeze.json"}),
        "task_count": len(frames),
        "direct_action_error_tolerance": 0,
        "thresholds_fitted_on_e010": False,
    }
    write_json(bank_root / "bank-freeze.json", freeze)
    print(json.dumps({"bank": str(bank_root), "task_count": len(frames), "freeze": freeze}, indent=2))


if __name__ == "__main__":
    main()
