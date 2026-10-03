"""Resume R3 training from complete, hash-verified histories after process loss.

The locked trainer, schedule, objective, and scientific inputs are unchanged.
Completed histories are byte-copied into a fresh training output namespace;
only absolute artifact paths in copied receipts are rebound. Incomplete
histories are preserved as interrupted-attempt provenance and rerun from the
same seed and initialization.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
TRAIN = RUN / "training-v01"
SOURCE_ARTIFACTS = TRAIN / "artifacts-v01"
RESUME_ROOT = TRAIN / "account-switch-resume-v01"
OUTPUT_ARTIFACTS = RESUME_ROOT / "artifacts-v01"
INTERRUPTED = RESUME_ROOT / "interrupted-history-attempts"
INVOCATIONS = RESUME_ROOT / "invocations"
FIX_DIR = TRAIN / "execution-fix-v03-account-switch-resume-v01"
RUNNER_PATH = EXP / "source/run_r3_confirmatory_training_v01.py"
V02_PATH = EXP / "source/run_r3_training_branch_restore_fix_v01.py"
LOCK_PATH = EXP / "seals/r3-phase-packet-seal-v01.json"
AGGREGATE_NAMES = ("history-training-receipts.jsonl", "training-manifest.json", "training-seal-v01.json")
BRANCHES = ("ONE_X", "HALF")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def inventory(root: Path) -> list[dict[str, Any]]:
    return [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
        "sha256": sha_file(path)} for path in sorted(root.rglob("*")) if path.is_file()]


def inventory_root(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    return sha_bytes(body.encode())


def expected_history_files() -> set[str]:
    expected = {"common/step-080.pt", "common/training-telemetry.jsonl"}
    for branch in BRANCHES:
        expected.update({f"branches/{branch}/step-100.pt", f"branches/{branch}/step-120.pt",
            f"branches/{branch}/training-telemetry.jsonl"})
    expected.add("history-training-receipt.json")
    return expected


def validate_telemetry(path: Path, cohort: str, seed: int, branch: str,
                       expected_steps: list[int], multiplier: float) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(len(lines) == len(expected_steps), f"telemetry row count mismatch: {path}")
    for index, line in enumerate(lines):
        row = json.loads(line)
        require(row.get("cohort") == cohort and int(row.get("seed", -1)) == seed
            and row.get("branch") == branch and int(row.get("global_step", -1)) == expected_steps[index]
            and float(row.get("auxiliary_multiplier", -1)) == multiplier
            and row.get("panel_opened") is False and math.isfinite(float(row["loss"]))
            and math.isfinite(float(row["brier"])) and math.isfinite(float(row["gradient_norm"])),
            f"telemetry identity/value mismatch: {path}:{index + 1}")


def validate_complete_history(directory: Path, cohort: str, seed: int) -> dict[str, Any]:
    require(directory.is_dir(), f"complete history directory missing: {directory}")
    observed = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
    require(observed == expected_history_files(),
        f"history artifact set differs from contract for {cohort}/{seed}: {sorted(observed)}")
    receipt = read_json(directory / "history-training-receipt.json")
    require(receipt.get("schema") == "jev-r3-history-training-receipt-v01"
        and receipt.get("cohort") == cohort and int(receipt.get("seed", -1)) == seed
        and receipt.get("common_steps") == 80 and receipt.get("branch_steps_each") == 40
        and receipt.get("telemetry_rows") == 160 and receipt.get("evaluation_panel_opened") is False
        and receipt.get("predictions_created") is False and receipt.get("metrics_computed") is False,
        f"history receipt mismatch: {cohort}/{seed}")
    common = directory / "common/step-080.pt"
    require(sha_file(common) == receipt.get("step80_checkpoint_sha256"),
        f"step-80 checkpoint receipt mismatch: {cohort}/{seed}")
    validate_telemetry(directory / "common/training-telemetry.jsonl", cohort, seed, "COMMON",
        list(range(1, 81)), 1.0)
    branch_checkpoints = receipt.get("branch_checkpoints", {})
    require(set(branch_checkpoints) == {f"{branch}_{step}" for branch in BRANCHES for step in (100, 120)},
        f"branch checkpoint receipt keys mismatch: {cohort}/{seed}")
    for branch, multiplier in (("ONE_X", 1.0), ("HALF", 0.5)):
        validate_telemetry(directory / f"branches/{branch}/training-telemetry.jsonl", cohort, seed,
            branch, list(range(81, 121)), multiplier)
        for step in (100, 120):
            rel = f"branches/{branch}/step-{step:03d}.pt"
            item = branch_checkpoints[f"{branch}_{step}"]
            path = directory / rel
            require(path.is_file() and sha_file(path) == item.get("sha256"),
                f"branch checkpoint digest mismatch: {cohort}/{seed}/{branch}/{step}")
            recorded_path = Path(item.get("path", "")).resolve()
            expected_path = path.resolve()
            require(recorded_path == expected_path,
                f"checkpoint receipt path mismatch: {cohort}/{seed}/{branch}/{step}")
    return receipt


def source_state(runner: Any, helper: Any) -> dict[str, Any]:
    seeds_doc = runner.read_json(runner.PREFLIGHT / "seed-manifest.json")
    seeds = [int(value) for value in seeds_doc["seeds"]]
    bridge_indices = [int(value) for value in seeds_doc["bridge_indices"]]
    bridge_seeds = [seeds[index] for index in bridge_indices]
    require(len(seeds) == 192 and len(set(seeds)) == 192 and len(bridge_seeds) == 24,
        "sealed seed manifest shape mismatch")
    expected_prefix = seeds[:132]
    source_balanced = SOURCE_ARTIFACTS / "balanced"
    history_dirs = sorted(source_balanced.glob("seed-*"), key=lambda path: path.name)
    require(len(history_dirs) == 133 and not (SOURCE_ARTIFACTS / "high_to_low_bridge").exists(),
        "interrupted original tree no longer matches the account-switch boundary")
    complete: dict[tuple[str, int], dict[str, Any]] = {}
    for index, seed in enumerate(expected_prefix):
        directory = source_balanced / f"seed-{seed}"
        require(directory.is_dir(), f"missing completed prefix history at index {index}: {seed}")
        receipt = validate_complete_history(directory, "balanced", seed)
        complete[("balanced", seed)] = receipt
    expected_partial_seed = seeds[132]
    partial = source_balanced / f"seed-{expected_partial_seed}"
    require(partial.is_dir() and not (partial / "history-training-receipt.json").exists(),
        "expected interrupted next history does not match the schedule")
    partial_files = {path.relative_to(partial).as_posix() for path in partial.rglob("*") if path.is_file()}
    expected_partial_files = {
        "common/step-080.pt", "common/training-telemetry.jsonl",
        "branches/ONE_X/step-100.pt", "branches/ONE_X/step-120.pt",
        "branches/ONE_X/training-telemetry.jsonl", "branches/HALF/training-telemetry.jsonl",
    }
    half_telemetry_path = partial / "branches/HALF/training-telemetry.jsonl"
    half_lines = half_telemetry_path.read_text(encoding="utf-8").splitlines()
    require(0 <= len(half_lines) <= 40, "interrupted HALF branch telemetry exceeds its schedule")
    if len(half_lines) >= 20:
        expected_partial_files.add("branches/HALF/step-100.pt")
    if len(half_lines) >= 40:
        expected_partial_files.add("branches/HALF/step-120.pt")
    require(partial_files == expected_partial_files,
        f"unreceipted history has an unexpected partial state: {sorted(partial_files)}")
    validate_telemetry(partial / "common/training-telemetry.jsonl", "balanced", expected_partial_seed,
        "COMMON", list(range(1, 81)), 1.0)
    validate_telemetry(partial / "branches/ONE_X/training-telemetry.jsonl", "balanced", expected_partial_seed,
        "ONE_X", list(range(81, 121)), 1.0)
    validate_telemetry(half_telemetry_path, "balanced", expected_partial_seed, "HALF",
        list(range(81, 81 + len(half_lines))), 0.5)
    require((partial / "common/step-080.pt").is_file(), "partial common checkpoint absent")
    for step in (100, 120):
        require((partial / f"branches/ONE_X/step-{step:03d}.pt").is_file(),
            "partial ONE_X checkpoint absent")
    expected_source_files = 132 * len(expected_history_files()) + len(expected_partial_files)
    source_entries = inventory(SOURCE_ARTIFACTS)
    require(len(source_entries) == expected_source_files,
        f"source attempt file count mismatch: {len(source_entries)} != {expected_source_files}")
    return {"seeds": seeds, "bridge_seeds": bridge_seeds, "complete": complete,
        "partial_seed": expected_partial_seed, "partial_path": partial,
        "source_entries": source_entries, "source_entries_root_sha256": inventory_root(source_entries)}


def validate_resume_output(runner: Any, seeds: list[int], bridge_seeds: list[int]) -> dict[tuple[str, int], dict[str, Any]]:
    completed: dict[tuple[str, int], dict[str, Any]] = {}
    cohort_specs = (("balanced", seeds), ("high_to_low_bridge", bridge_seeds))
    for cohort, cohort_seeds in cohort_specs:
        cohort_dir = OUTPUT_ARTIFACTS / cohort
        if not cohort_dir.exists():
            continue
        observed_dirs = {path.name for path in cohort_dir.iterdir() if path.is_dir()}
        allowed = {f"seed-{seed}" for seed in cohort_seeds}
        require(observed_dirs.issubset(allowed), f"unexpected history directory in resume output: {cohort}")
        for seed in cohort_seeds:
            directory = cohort_dir / f"seed-{seed}"
            if not directory.exists():
                continue
            receipt_path = directory / "history-training-receipt.json"
            if receipt_path.is_file():
                try:
                    completed[(cohort, seed)] = validate_complete_history(directory, cohort, seed)
                except (OSError, ValueError, KeyError, RuntimeError, TypeError):
                    # A copy interrupted before receipt path rebinding is not a
                    # completed history. Preserve it, then import again from the
                    # byte-verified source rather than failing or trusting it.
                    continue
    # Completed histories must form a prefix of the exact frozen loop order.
    seen_missing = False
    for cohort, cohort_seeds in cohort_specs:
        for seed in cohort_seeds:
            key = (cohort, seed)
            if key not in completed:
                seen_missing = True
            else:
                require(not seen_missing, f"resumed histories are not a contiguous schedule prefix: {key}")
    return completed


def preserve_incomplete_resume_dirs(invocation: int, seeds: list[int], bridge_seeds: list[int],
                                    completed: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    moved: list[dict[str, Any]] = []
    for cohort, cohort_seeds in (("balanced", seeds), ("high_to_low_bridge", bridge_seeds)):
        cohort_dir = OUTPUT_ARTIFACTS / cohort
        if not cohort_dir.exists():
            continue
        for directory in list(cohort_dir.iterdir()):
            if not directory.is_dir():
                continue
            seed = int(directory.name.removeprefix("seed-"))
            if (cohort, seed) in completed:
                continue
            entries = inventory(directory)
            destination = INTERRUPTED / f"invocation-{invocation:03d}" / directory.relative_to(OUTPUT_ARTIFACTS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            require(not destination.exists(), f"interrupted output archive exists: {destination}")
            shutil.move(str(directory), str(destination))
            moved.append({"source_relative_path": directory.relative_to(OUTPUT_ARTIFACTS).as_posix(),
                "archive_path": str(destination), "entries": entries, "entries_root_sha256": inventory_root(entries)})
    return moved


def rebind_history_receipt(receipt: dict[str, Any], destination: Path) -> dict[str, Any]:
    rebound = copy.deepcopy(receipt)
    for branch in BRANCHES:
        for step in (100, 120):
            key = f"{branch}_{step}"
            rebound["branch_checkpoints"][key]["path"] = str(
                destination / f"branches/{branch}/step-{step:03d}.pt")
    return rebound


def validate_final_seal(runner: Any) -> bool:
    seal_path = OUTPUT_ARTIFACTS / "training-seal-v01.json"
    manifest_path = OUTPUT_ARTIFACTS / "training-manifest.json"
    if not seal_path.exists():
        return False
    seal = read_json(seal_path)
    manifest = read_json(manifest_path)
    require(seal.get("status") == "R3_V03_ALL_TRAINING_TRAJECTORIES_SEALED_PRE_EVALUATION"
        and sha_file(manifest_path) == seal.get("manifest_sha256")
        and manifest.get("training_complete") is True and manifest.get("panel_behavior_opened") is False,
        "existing resumed final training seal is inconsistent")
    entries = seal.get("entries", [])
    root = hashlib.sha256("".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in entries).encode()).hexdigest()
    require(root == seal.get("entries_root_sha256") and len(entries) >= 216 * 5,
        "existing resumed training root is malformed")
    for row in entries:
        path = OUTPUT_ARTIFACTS / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha_file(path) == row["sha256"],
            f"sealed resumed training file changed: {row['path']}")
    return True


def main() -> int:
    runner = load_module(RUNNER_PATH, "jev_r3_locked_training_runner_resume")
    lock = runner.verify_lock()
    helper = load_module(runner.CALIBRATION_RUNNER, "jev_r3_resume_training_helper")
    original_artifacts = runner.ARTIFACTS
    require(original_artifacts == SOURCE_ARTIFACTS, "locked training source namespace changed")
    state = source_state(runner, helper)

    RESUME_ROOT.mkdir(parents=True, exist_ok=True)
    INVOCATIONS.mkdir(parents=True, exist_ok=True)
    FIX_DIR.mkdir(parents=True, exist_ok=True)
    invocation = 1 + sum(1 for _ in INVOCATIONS.glob("invocation-*-preflight.json"))
    out_complete = validate_resume_output(runner, state["seeds"], state["bridge_seeds"])
    moved_partial = preserve_incomplete_resume_dirs(invocation, state["seeds"], state["bridge_seeds"], out_complete)
    # A prior interrupted finalization is derived metadata, not a history. Preserve it
    # outside the evaluator's artifact root so the locked aggregate writer can replay.
    if OUTPUT_ARTIFACTS.exists() and not validate_final_seal(runner):
        for name in AGGREGATE_NAMES:
            path = OUTPUT_ARTIFACTS / name
            if path.exists():
                archive = INTERRUPTED / f"invocation-{invocation:03d}" / "finalization" / name
                archive.parent.mkdir(parents=True, exist_ok=True)
                require(not archive.exists(), f"finalization provenance destination exists: {archive}")
                shutil.move(str(path), str(archive))

    adapter_hash = sha_file(Path(__file__).resolve())
    source_entries = state["source_entries"]
    preflight = {"identity": "JEV-V08Q-R3-ACCOUNT-SWITCH-RESUME-PREFLIGHT",
        "status": "PASS_PRE_OUTCOME_HISTORY_RESUME", "invocation": invocation,
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "locked_trainer_sha256": sha_file(RUNNER_PATH), "adapter_source_sha256": adapter_hash,
        "source_artifacts_path": str(SOURCE_ARTIFACTS),
        "source_artifacts_entries": source_entries,
        "source_artifacts_entries_root_sha256": state["source_entries_root_sha256"],
        "completed_source_histories": 132, "next_history_index": 132,
        "next_history_seed": state["partial_seed"],
        "partial_history_source_path": str(state["partial_path"]),
        "partial_history_files": sorted(path.relative_to(state["partial_path"]).as_posix()
            for path in state["partial_path"].rglob("*") if path.is_file()),
        "partial_history_disposition": "PRESERVED_UNCHANGED; SAME_SEED_RERUN_FROM_INITIALIZATION",
        "prior_preflight_failure_logs": [{"path": str(path), "bytes": path.stat().st_size,
            "sha256": sha_file(path)} for path in sorted((RESUME_ROOT / "preflight-failure-001").glob("*.log"))],
        "resumed_output_path": str(OUTPUT_ARTIFACTS),
        "already_complete_resume_histories": len(out_complete),
        "incomplete_resume_histories_archived": moved_partial,
        "panel_opened": False, "heldout_targets_read": False,
        "predictions_created": False, "metrics_computed": False}
    preflight_path = INVOCATIONS / f"invocation-{invocation:03d}-preflight.json"
    write_json_new(preflight_path, preflight)

    if not validate_final_seal(runner):
        # Create this invocation's output root through the locked trainer; completed
        # histories are copied lazily at the first scheduled history boundary.
        runner.ARTIFACTS = OUTPUT_ARTIFACTS
        original_train_history = runner.train_history
        copied_keys: set[tuple[str, int]] = set(out_complete)
        imported_source_keys: set[tuple[str, int]] = set()
        first_call = True
        started = time.time()

        def resumable_train_history(cohort: str, seed: int, schedule_rows: list[dict[str, Any]],
                primary: list[dict[str, Any]], auxiliary: list[dict[str, Any]], states: torch.Tensor,
                candidates: torch.Tensor, history_helper: Any, batcher: Any, objective: Any) -> dict[str, Any]:
            nonlocal first_call
            if first_call:
                first_call = False
                for key, source_receipt in state["complete"].items():
                    cohort_name, history_seed = key
                    destination = OUTPUT_ARTIFACTS / cohort_name / f"seed-{history_seed}"
                    if destination.exists():
                        require(key in out_complete, f"unexpected preexisting destination history: {key}")
                        continue
                    source = SOURCE_ARTIFACTS / cohort_name / f"seed-{history_seed}"
                    require(not destination.exists(), f"resume destination already exists: {destination}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source, destination)
                    rebound = rebind_history_receipt(source_receipt, destination)
                    receipt_path = destination / "history-training-receipt.json"
                    receipt_path.write_text(json.dumps(rebound, ensure_ascii=False, indent=2,
                        allow_nan=False) + "\n", encoding="utf-8")
                    copied_keys.add(key)
                    imported_source_keys.add(key)
                    validate_complete_history(destination, cohort_name, history_seed)
                print(json.dumps({"status": "R3_RESUME_HISTORY_IMPORT_COMPLETE",
                    "histories_imported": len(imported_source_keys),
                    "histories_already_in_resume": len(out_complete),
                    "output_root": str(OUTPUT_ARTIFACTS)}, separators=(",", ":")), flush=True)

            key = (cohort, seed)
            destination = OUTPUT_ARTIFACTS / cohort / f"seed-{seed}"
            if destination.exists() and (destination / "history-training-receipt.json").is_file():
                receipt = validate_complete_history(destination, cohort, seed)
                print(json.dumps({"status": "R3_TRAINING_HISTORY_REUSED",
                    "cohort": cohort, "seed": seed}, separators=(",", ":")), flush=True)
                return receipt
            if destination.exists():
                raise RuntimeError(f"incomplete resume history was not archived: {destination}")
            receipt = original_train_history(cohort, seed, schedule_rows, primary, auxiliary,
                states, candidates, history_helper, batcher, objective)
            return receipt

        runner.train_history = resumable_train_history
        original_require = runner.require
        output_str = str(OUTPUT_ARTIFACTS)

        def resume_require(condition: bool, message: str) -> None:
            if message == f"refusing existing R3 training artifacts: {OUTPUT_ARTIFACTS}" and OUTPUT_ARTIFACTS.exists():
                return
            return original_require(condition, message)

        runner.require = resume_require
        original_mkdir = Path.mkdir

        def resume_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
            if str(path.resolve()) == output_str and path.exists() and kwargs.get("exist_ok") is False:
                return None
            return original_mkdir(path, *args, **kwargs)

        Path.mkdir = resume_mkdir  # type: ignore[assignment]
        original_run_steps = runner.run_steps
        candidate_cuda_cache: dict[int, torch.Tensor] = {}

        def run_steps_cuda_fix(cohort: str, seed: int, start: int, stop: int, multiplier: float,
                schedule_rows: list[dict[str, Any]], primary: list[dict[str, Any]],
                auxiliary: list[dict[str, Any]], states: torch.Tensor, candidates: torch.Tensor,
                head: torch.nn.Module, optimizer: torch.optim.Optimizer, step_helper: Any,
                batcher: Any, objective: Any, telemetry_path: Path,
                checkpoint_dir: Path, branch_name: str | None) -> tuple[Any, Any]:
            key = id(candidates)
            if key not in candidate_cuda_cache:
                candidate_cuda_cache[key] = candidates.to("cuda")
            return original_run_steps(cohort, seed, start, stop, multiplier, schedule_rows,
                primary, auxiliary, states, candidate_cuda_cache[key], head, optimizer,
                step_helper, batcher, objective, telemetry_path, checkpoint_dir, branch_name)

        runner.run_steps = run_steps_cuda_fix
        original_adamw = torch.optim.AdamW

        def adamw_isolated(*args: Any, **kwargs: Any) -> torch.optim.Optimizer:
            optimizer = original_adamw(*args, **kwargs)
            load_state = optimizer.load_state_dict

            def isolated_load(state_dict: dict[str, Any]) -> Any:
                return load_state(copy.deepcopy(state_dict))

            optimizer.load_state_dict = isolated_load  # type: ignore[method-assign]
            return optimizer

        torch.optim.AdamW = adamw_isolated  # type: ignore[assignment]
        try:
            result = runner.main()
        finally:
            torch.optim.AdamW = original_adamw
            Path.mkdir = original_mkdir  # type: ignore[assignment]
            runner.require = original_require
            runner.run_steps = original_run_steps
            runner.train_history = original_train_history
        require(result == 0, f"locked trainer returned nonzero status: {result}")
        require(validate_final_seal(runner), "locked trainer did not produce a valid final seal")
        training_elapsed = round(time.time() - started, 3)
    else:
        training_elapsed = 0.0

    seal_path = OUTPUT_ARTIFACTS / "training-seal-v01.json"
    binding = {"identity": "JEV-V08Q-R3-EXECFIX03-TRAINING-BINDING",
        "status": "R3_EXECFIX03_RESUMED_TRAINING_OUTPUT_BOUND",
        "adapter_source_sha256": adapter_hash,
        "invocation_preflight_sha256": sha_file(preflight_path),
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "training_seal_sha256": sha_file(seal_path),
        "training_entries_root_sha256": read_json(seal_path)["entries_root_sha256"],
        "original_interrupted_attempt_root_sha256": state["source_entries_root_sha256"],
        "source_histories_reused": 132, "same_seed_partial_history_rerun": state["partial_seed"],
        "panel_opened": False, "predictions_created": False, "metrics_computed": False,
        "training_elapsed_this_invocation_seconds": training_elapsed}
    binding_path = FIX_DIR / "training-output-binding-v01.json"
    if binding_path.exists():
        existing = read_json(binding_path)
        require(existing.get("training_seal_sha256") == binding["training_seal_sha256"]
            and existing.get("training_entries_root_sha256") == binding["training_entries_root_sha256"],
            "existing execution-fix binding points to another training root")
    else:
        write_json_new(binding_path, binding)
    invocation_completion = {"identity": "JEV-V08Q-R3-ACCOUNT-SWITCH-RESUME-COMPLETION",
        "status": "R3_V03_TRAINING_COMPLETE_RESUMED_AND_SEALED",
        "preflight_sha256": sha_file(preflight_path), "training_binding_sha256": sha_file(binding_path),
        "training_seal_sha256": sha_file(seal_path),
        "training_entries_root_sha256": read_json(seal_path)["entries_root_sha256"],
        "panel_opened": False, "predictions_created": False, "metrics_computed": False}
    write_json_new(INVOCATIONS / f"invocation-{invocation:03d}-completion.json", invocation_completion)
    print(json.dumps({"status": invocation_completion["status"],
        "training_entries_root_sha256": invocation_completion["training_entries_root_sha256"],
        "resume_output": str(OUTPUT_ARTIFACTS), "execution_fix": str(FIX_DIR)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
