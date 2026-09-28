from __future__ import annotations

import copy
import difflib
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
SOURCE_REPO = Path(r"C:\code land\clean-rust")
DEV_ROOT = ROOT / "tasks" / "expanded" / "dev-bank-v4"
TASK_PREFIX = "dev"
FAMILY = "gpui-animated-gradient-text-contracts"
PACKAGE_PATH = "phoenix-native/crates/gpui-animated-gradient-text"
PACKAGE_NAME = "gpui-animated-gradient-text"
REPO_REVISION = "9a88547372cd35f8dc31f026f0cd8dd8fca8e641"
TARGET = Path(r"D:\cargo-targets\rdc-e009-expanded\dev")

CASES = [
    {
        "family": "cyclic-palette-seam",
        "source": "src/palette.rs",
        "test": "palette::tests::auto_positions_leave_a_cyclic_seam_interval",
        "base_mutate": lambda text: text.replace(
            "index as f32 / count as f32",
            "index as f32 / (count - 1) as f32",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "index as f32 / count as f32",
            "index as f32 / (count + 1) as f32",
            1,
        ),
        "mutant_excerpt": "Use `index as f32 / (count + 1) as f32` for automatic stop spacing.",
        "mutant_summary": "Use a denominator of color_count + 1 for automatic stop spacing.",
        "keep_excerpt": "The current task snapshot divides each stop index by color_count - 1.",
        "keep_summary": "Leave the current automatic stop denominator unchanged.",
        "gold_summary": "Restore stop spacing by dividing each index by the palette's stop count.",
        "gold_excerpt": "Use `index as f32 / count as f32`; this leaves a final interval for the cyclic wrap.",
        "comment_summary": "Restore count-based stop spacing and document the final cyclic interval.",
        "comment_excerpt": "Restores `index / count` and adds a comment explaining the wrap interval.",
        "source_evidence": (
            "The current task snapshot divides each automatic stop index by color_count - 1, placing the final stop "
            "at 1. The frozen test requires three positions 0, 1/3, and 2/3 and a shared sample at 0 and 1."
        ),
        "easy_prompt": (
            "Repair the cyclic gradient stop regression. For three colors, positions must be [0, 1/3, 2/3] "
            "and sample(0) must equal sample(1). Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair the cyclic palette's automatic stop placement. Read the frozen test's exact expected positions "
            "and wrap behavior before choosing between the offered denominator changes. Either passing repair is valid."
        ),
    },
    {
        "family": "unicode-fill-boundaries",
        "source": "src/fills.rs",
        "test": "fills::tests::grapheme_ranges_never_split_composed_text",
        "base_mutate": lambda text: text.replace(
            "if !grapheme_aligned {",
            "if grapheme_aligned {",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "    if !grapheme_aligned {\n        return Err(TextRangeError::NotGraphemeBoundary);\n    }\n",
            "",
            1,
        ),
        "mutant_excerpt": "Remove the branch that returns NotGraphemeBoundary for split grapheme ranges.",
        "mutant_summary": "Remove the explicit grapheme-alignment error branch.",
        "keep_excerpt": "The current task snapshot rejects aligned ranges and accepts misaligned grapheme ranges.",
        "keep_summary": "Keep the current range-validation condition.",
        "gold_summary": "Restore the validation branch so only split grapheme ranges are rejected.",
        "gold_excerpt": "Return `NotGraphemeBoundary` only when `grapheme_aligned` is false.",
        "comment_summary": "Restore grapheme-boundary validation and document the split-range rule.",
        "comment_excerpt": "Restores the original conditional and adds a comment about user-perceived graphemes.",
        "source_evidence": (
            "The current task snapshot returns an error for a range aligned to both grapheme boundaries and does not "
            "reject a UTF-8-aligned range that splits a composed grapheme. The frozen test covers both cases."
        ),
        "easy_prompt": (
            "Repair Unicode fill-range validation. A complete composed grapheme must be accepted, while a byte range "
            "that splits it must return NotGraphemeBoundary. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair the range validator using the frozen Unicode test. Both offsets in the failing range are valid "
            "UTF-8 positions, but the range still splits one user-perceived grapheme. Either passing repair is valid."
        ),
    },
    {
        "family": "unicode-pointer-selection",
        "source": "src/text.rs",
        "test": "text::tests::pointer_indexes_snap_to_whole_graphemes",
        "base_mutate": lambda text: text.replace(
            ".saturating_sub(1)\n            .min(self.grapheme_count().saturating_sub(1));",
            ".saturating_sub(0)\n            .min(self.grapheme_count().saturating_sub(1));",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            ".saturating_sub(1)\n            .min(self.grapheme_count().saturating_sub(1));",
            ".saturating_sub(2)\n            .min(self.grapheme_count().saturating_sub(1));",
            1,
        ),
        "mutant_excerpt": "Use `.saturating_sub(2)` when mapping the lower byte position to a grapheme index.",
        "mutant_summary": "Subtract two from the lower-bound grapheme offset count.",
        "keep_excerpt": "The current task snapshot advances an interior byte position to the following grapheme.",
        "keep_summary": "Keep the current pointer-to-grapheme index calculation.",
        "gold_summary": "Snap an interior pointer to the grapheme that contains it.",
        "gold_excerpt": "Use `partition_point(...).saturating_sub(1)` to select the containing grapheme start.",
        "comment_summary": "Snap to the containing grapheme and document the pointer-boundary behavior.",
        "comment_excerpt": "Restores the containing-grapheme index and adds a short explanatory comment.",
        "source_evidence": (
            "The current task snapshot maps an interior byte position to the next grapheme start. The frozen test "
            "starts and ends inside a joined astronaut emoji and requires selection of the entire emoji."
        ),
        "easy_prompt": (
            "Repair pointer-to-text selection. When both pointer positions land inside a joined astronaut emoji, "
            "the selected byte range must cover the whole emoji grapheme. Choose a patch that passes the test."
        ),
        "ambiguous_prompt": (
            "Repair pointer-to-text selection using the frozen test. The inputs are interior byte positions, not "
            "grapheme boundaries; use them to infer which grapheme offset the start index must select."
        ),
    },
    {
        "family": "color-interpolation-endpoints",
        "source": "src/color.rs",
        "test": "color::tests::interpolation_preserves_endpoints_in_every_space",
        "base_mutate": lambda text: text.replace(
            "amount.clamp(0.0, 1.0)",
            "amount.clamp(0.01, 0.99)",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "amount.clamp(0.0, 1.0)",
            "amount.clamp(0.1, 0.9)",
            1,
        ),
        "mutant_excerpt": "Clamp the interpolation amount to 0.1..0.9.",
        "mutant_summary": "Use a narrower interpolation clamp from 0.1 to 0.9.",
        "keep_excerpt": "The current task snapshot clamps the amount to 0.01..0.99, so neither exact endpoint is reachable.",
        "keep_summary": "Keep the current restricted interpolation range.",
        "gold_summary": "Restore inclusive clamping at both interpolation endpoints.",
        "gold_excerpt": "Clamp with `amount.clamp(0.0, 1.0)` to preserve the first and last colors exactly.",
        "comment_summary": "Restore inclusive endpoint clamping and document the endpoint guarantee.",
        "comment_excerpt": "Restores the 0.0..1.0 clamp and adds a note that endpoints remain exact.",
        "source_evidence": (
            "The current task snapshot clamps interpolation to 0.01..0.99. The frozen test checks that amount 0 "
            "returns the first color and amount 1 returns the second in sRGB, linear sRGB, and Oklab."
        ),
        "easy_prompt": (
            "Repair color interpolation endpoints. Amount 0 must return the first color and amount 1 the second in "
            "sRGB, linear sRGB, and Oklab. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair endpoint clamping from the frozen test. The correct range must admit both 0 and 1 exactly, while "
            "still bounding values outside the interval. Either passing repair is valid."
        ),
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot_with_task_fault(archive: bytes, member_name: str, faulty_text: str) -> bytes:
    source_buffer = io.BytesIO(archive)
    output_buffer = io.BytesIO()
    with tarfile.open(fileobj=source_buffer, mode="r:") as source_tar:
        with tarfile.open(fileobj=output_buffer, mode="w") as output_tar:
            for member in source_tar.getmembers():
                if member.name == member_name:
                    changed = copy.copy(member)
                    changed_bytes = faulty_text.encode("utf-8")
                    changed.size = len(changed_bytes)
                    output_tar.addfile(changed, io.BytesIO(changed_bytes))
                elif member.isfile():
                    source_file = source_tar.extractfile(member)
                    if source_file is None:
                        raise RuntimeError(f"cannot read source archive member {member.name}")
                    output_tar.addfile(member, source_file)
                else:
                    output_tar.addfile(member)
    return output_buffer.getvalue()


def run_test(manifest: Path, test: str, log_path: Path, features: tuple[str, ...] = ()) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    # Cargo identifies path packages by name and version inside a shared target
    # directory. Clean this package before each candidate so one patch cannot
    # accidentally reuse another candidate's executable.
    clean = subprocess.run(
        ["cargo", "clean", "--manifest-path", str(manifest), "-p", PACKAGE_NAME],
        cwd=manifest.parent,
        env=env,
        text=True,
        capture_output=True,
    )
    if clean.returncode != 0:
        raise RuntimeError(f"cargo clean failed before completion check: {clean.stdout}\n{clean.stderr}")
    command = [
        "cargo", "test", "--manifest-path", str(manifest),
        "-p", PACKAGE_NAME,
    ]
    if features:
        command.extend(["--features", ",".join(features)])
    command.extend(["--lib", test, "--", "--exact"])
    completed = subprocess.run(command, cwd=manifest.parent, env=env, text=True, capture_output=True)
    output = completed.stdout + completed.stderr
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8", newline="\n")
    passed = completed.returncode == 0 and "test result: ok. 1 passed;" in output
    failed_as_expected = (
        completed.returncode == 101
        and re.search(rf"test\s+{re.escape(test)}\s+\.\.\. FAILED", output) is not None
        and "test result: FAILED. 0 passed; 1 failed;" in output
    )
    if completed.returncode not in (0, 101):
        raise RuntimeError(f"unexpected cargo exit {completed.returncode}: {command}\n{output[-2000:]}")
    if completed.returncode == 101 and not failed_as_expected:
        raise RuntimeError(f"completion test did not execute and fail as expected: {command}\n{output[-3000:]}")
    return {
        "command": command,
        "exit_code": completed.returncode,
        "passed": passed,
        "failed_as_expected": failed_as_expected,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
        "log_sha256": sha256(output.encode("utf-8")),
    }


def main() -> None:
    if DEV_ROOT.exists():
        raise SystemExit(f"refusing to overwrite frozen development bank: {DEV_ROOT}")
    actual_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SOURCE_REPO, text=True
    ).strip()
    if actual_revision != REPO_REVISION:
        raise SystemExit(f"source HEAD changed: expected {REPO_REVISION}, found {actual_revision}")

    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", REPO_REVISION, PACKAGE_PATH],
        cwd=SOURCE_REPO,
    )
    source_lock = subprocess.check_output(
        ["git", "show", f"{REPO_REVISION}:phoenix-native/Cargo.lock"],
        cwd=SOURCE_REPO,
    )
    tmp = Path(tempfile.mkdtemp(prefix="rdc-e009-git-archive-"))
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(archive), mode="r:") as package_tar:
            package_tar.extractall(tmp, filter="data")
        extracted = tmp / PACKAGE_PATH
        if not (extracted / "Cargo.toml").is_file():
            raise SystemExit("clean commit archive did not contain the expected package")

        for case in CASES:
            family_root = DEV_ROOT / "families" / case["family"]
            family_root.mkdir(parents=True, exist_ok=False)
            (family_root / "source-snapshot.tar").write_bytes(archive)
            source_file = extracted / case["source"]
            base_text = source_file.read_text(encoding="utf-8")
            faulty_text = case["base_mutate"](base_text)
            mutant_text = case["alternate_mutate"](base_text)
            if faulty_text == base_text or mutant_text == base_text or faulty_text == mutant_text:
                raise SystemExit(f"fault or alternate candidate did not match exact source in {case['family']}")
            task_archive = snapshot_with_task_fault(
                archive,
                f"{PACKAGE_PATH}/{case['source']}",
                faulty_text,
            )
            (family_root / "snapshot.tar").write_bytes(task_archive)
            task_snapshot_sha256 = sha256(task_archive)

            variants = {
                "keep": faulty_text,
                "gold": base_text,
                "gold_comment": "// E009 candidate: behavior-preserving repair note.\n" + base_text,
                "mutant": mutant_text,
            }
            variant_records: dict[str, dict] = {}
            for variant, changed_text in variants.items():
                candidate_root = family_root / "candidates" / variant
                package_dir = candidate_root / "crates" / PACKAGE_NAME
                shutil.copytree(extracted, package_dir)
                changed_path = package_dir / case["source"]
                changed_path.write_text(changed_text, encoding="utf-8", newline="\n")
                (candidate_root / "Cargo.toml").write_text(
                    "[workspace]\nresolver = \"2\"\nmembers = [\"crates/gpui-animated-gradient-text\"]\n\n"
                    "[workspace.package]\nversion = \"0.1.0\"\nedition = \"2021\"\n"
                    "license = \"MIT OR Apache-2.0\"\nrust-version = \"1.85\"\n",
                    encoding="utf-8",
                    newline="\n",
                )
                (candidate_root / "Cargo.lock").write_bytes(source_lock)
                if variant == "keep":
                    patch = b""
                else:
                    diff = difflib.unified_diff(
                        faulty_text.splitlines(keepends=True),
                        changed_text.splitlines(keepends=True),
                        fromfile=f"a/{case['source']}",
                        tofile=f"b/{case['source']}",
                    )
                    patch = "".join(diff).encode("utf-8")
                patch_path = family_root / f"{variant}.patch"
                patch_path.write_bytes(patch)
                variant_records[variant] = {
                    "candidate_root": str(candidate_root.relative_to(ROOT)).replace("\\", "/"),
                    "manifest": str((candidate_root / "Cargo.toml").relative_to(ROOT)).replace("\\", "/"),
                    "patch": str(patch_path.relative_to(ROOT)).replace("\\", "/"),
                    "patch_sha256": sha256(patch),
                }

            results: dict[str, dict] = {}
            for variant, item in variant_records.items():
                manifest = ROOT / item["manifest"]
                results[variant] = run_test(
                    manifest,
                    case["test"],
                    family_root / "completion" / f"{variant}.log",
                    tuple(case.get("features", ())),
                )
            if (
                not results["keep"]["failed_as_expected"]
                or not results["gold"]["passed"]
                or not results["gold_comment"]["passed"]
                or not results["mutant"]["failed_as_expected"]
            ):
                raise SystemExit(f"completion checks did not separate repair and harmful choices: {case['family']} {results}")

            case["snapshot_sha256"] = task_snapshot_sha256
            case["variants"] = variant_records
            case["results"] = results
            case["source_text"] = base_text

        frame_inputs: list[dict] = []
        labels: dict[str, dict] = {}
        candidate_lock = {"schema_version": 1, "repository_revision": REPO_REVISION, "families": {}}
        for case_index, case in enumerate(CASES):
            family = case["family"]
            candidate_lock["families"][family] = {
                "snapshot_sha256": case["snapshot_sha256"],
                "test_filter": case["test"],
                "features": list(case.get("features", ())),
                "variants": case["variants"],
            }
            family_labels = {
                variant: {
                    "expected_task_completion": case["results"][variant]["passed"],
                    "completion_log_sha256": case["results"][variant]["log_sha256"],
                }
                for variant in ("keep", "gold", "gold_comment", "mutant")
            }
            for replicate, difficulty in enumerate(("easy", "ambiguous"), start=1):
                task_id = f"{TASK_PREFIX}-{family}-{difficulty}-{replicate:02d}"
                rng = random.Random(9009 + case_index * 19 + replicate)
                variants_order = ["keep", "gold", "gold_comment", "mutant"]
                rng.shuffle(variants_order)
                action_ids = [11, 37, 68, 94]
                options = []
                for action_id, variant in zip(action_ids, variants_order, strict=True):
                    record = case["variants"][variant]
                    if variant == "keep":
                        summary = case["keep_summary"]
                        excerpt = case["keep_excerpt"]
                    elif variant == "gold":
                        summary = case["gold_summary"]
                        excerpt = case["gold_excerpt"]
                    elif variant == "gold_comment":
                        summary = case["comment_summary"]
                        excerpt = case["comment_excerpt"]
                    else:
                        summary = case["mutant_summary"]
                        excerpt = case["mutant_excerpt"]
                    options.append(
                        {
                            "action": {"id": action_id, "schema_id": 1},
                            "summary": summary,
                            "diff_excerpt": excerpt,
                            "patch_sha256": record["patch_sha256"],
                        }
                    )
                prompt_key = "easy_prompt" if difficulty == "easy" else "ambiguous_prompt"
                frame_inputs.append(
                    {
                        "schema_id": "rdc-real-coding-observation.v1",
                        "task_id": task_id,
                        "task_family": family,
                        "task_prompt": case[prompt_key],
                        "repository_revision": REPO_REVISION,
                        "snapshot_sha256": case["snapshot_sha256"],
                        "evidence": [
                            {
                                "kind": "source_excerpt",
                                "source_id": f"{PACKAGE_PATH}/{case['source']}",
                                "content_blake3": "",
                                "content": case["source_evidence"],
                            },
                            {
                                "kind": "baseline_tool_result",
                                "source_id": f"cargo-test-{case['test']}-frozen-base",
                                "content_blake3": "",
                                "content": (
                                    f"Task snapshot {case['snapshot_sha256']}: exact test `{case['test']}` ran on the current snapshot "
                                    "and failed 1/1. No candidate repair has been executed in this episode."
                                ),
                            },
                        ],
                        "action_options": options,
                    }
                )
                labels[task_id] = {
                    "family": family,
                    "difficulty": difficulty,
                    "completion_check": f"exact Rust unit test `{case['test']}` must run and pass",
                    "actions_by_patch_sha256": {
                        case["variants"][variant]["patch_sha256"]: label
                        for variant, label in family_labels.items()
                    },
                }

        bank_dir = ROOT / "tasks" / "expanded"
        bank_dir.mkdir(parents=True, exist_ok=True)
        unlocked_path = DEV_ROOT / "frames-unlocked.json"
        write_json(unlocked_path, {"frames": frame_inputs})
        frame_lock_path = DEV_ROOT / "frame-lock.json"
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"
        subprocess.run(
            [
                "cargo", "run", "--quiet", "--manifest-path", str(ROOT / "Cargo.toml"),
                "--bin", "e009-freeze-frames", "--", str(unlocked_path), str(frame_lock_path),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        write_json(DEV_ROOT / "candidate-lock.json", candidate_lock)
        write_json(
            DEV_ROOT / "sealed-labels.json",
            {
                "schema_version": 1,
                "access": "scoring only; generated from frozen source tests before observer contact",
                "source_repository_revision": REPO_REVISION,
                "tasks": labels,
            },
        )
        inputs = {
            "source_repository_revision": REPO_REVISION,
            "source_archive_sha256": sha256(archive),
            "source_cargo_lock_sha256": sha256(source_lock),
            "bank_builder_source_sha256": sha256(Path(__file__).read_bytes()),
            "task_spec_source_sha256": sha256(Path(sys.argv[0]).resolve().read_bytes()),
            "family_count": len(CASES),
            "task_count": len(frame_inputs),
            "task_families": [case["family"] for case in CASES],
            "bank_role": TASK_PREFIX,
            "task_snapshot_policy": "clean commit source plus a single controlled injected regression; labels from exact existing unit tests",
            "completion_checks": {
                case["family"]: {
                    "test_filter": case["test"],
                    "keep": case["results"]["keep"],
                    "gold": case["results"]["gold"],
                    "gold_comment": case["results"]["gold_comment"],
                    "mutant": case["results"]["mutant"],
                    "keep": case["results"]["keep"],
                }
                for case in CASES
            },
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(DEV_ROOT / "bank-build-receipt.json", inputs)
        print(f"frozen {len(frame_inputs)} {TASK_PREFIX} tasks across {len(CASES)} task families")
        print(frame_lock_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
