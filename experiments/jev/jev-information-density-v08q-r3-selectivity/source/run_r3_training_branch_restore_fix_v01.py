"""Versioned R3 repair: immutable AdamW fork snapshots across late branches."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
PREVIOUS = EXP / "source/run_r3_training_device_fix_v01.py"
TRAIN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03\training-v01")
ARTIFACTS = TRAIN / "artifacts-v01"
FAILED = TRAIN / "failed-attempt-branch-restore-v01"
FIX_DIR = TRAIN / "execution-fix-v02"
RUNNER_PATH = EXP / "source/run_r3_confirmatory_training_v01.py"

TRACEBACK = r"""Traceback (most recent call last):
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_training_device_fix_v01.py", line 243, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_training_device_fix_v01.py", line 224, in main
    result = runner.main()
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 414, in main
    receipt = train_history(cohort, seed, cohort_schedule, cohort_primary, cohort_aux,
        states, candidates, helper, batcher, objective)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 287, in train_history
    require(helper.state_sha(head.state_dict()) == common_fork["head_sha256"]
    ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        and helper.tree_sha(optimizer.state_dict()) == common_fork["optimizer_sha256"],
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        f"step-80 head/optimizer clone mismatch: {cohort}/{seed}/{branch_name}")
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 76, in require
    raise RuntimeError(message)
RuntimeError: step-80 head/optimizer clone mismatch: balanced/1657290010/HALF
"""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_previous() -> Any:
    spec = importlib.util.spec_from_file_location("jev_r3_device_fix_v01", PREVIOUS)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load prior versioned R3 device adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def optimizer_snapshot_smoke(runner: Any) -> dict[str, Any]:
    helper = runner.load_module(runner.CALIBRATION_RUNNER, "jev_r3_optimizer_snapshot_smoke")
    model = torch.nn.Linear(4, 2).to("cuda")
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=0.01,
        betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    model(torch.ones((1, 4), device="cuda")).square().mean().backward()
    optimizer.step()
    snapshot = runner.clone_cpu(optimizer.state_dict())
    snapshot_hash = helper.tree_sha(snapshot)
    optimizer.load_state_dict(copy.deepcopy(snapshot))
    optimizer.zero_grad(set_to_none=True)
    model(torch.full((1, 4), 2.0, device="cuda")).square().mean().backward()
    optimizer.step()
    source_hash_after_step = helper.tree_sha(snapshot)
    optimizer.load_state_dict(copy.deepcopy(snapshot))
    restored_hash = helper.tree_sha(optimizer.state_dict())
    if source_hash_after_step != snapshot_hash or restored_hash != snapshot_hash:
        raise RuntimeError("deep-copied optimizer snapshot smoke test failed")
    return {"status": "SYNTHETIC_OPTIMIZER_SNAPSHOT_IMMUTABILITY_PASS",
        "snapshot_sha256": snapshot_hash, "snapshot_unchanged_after_branch_step": True,
        "restored_optimizer_matches_snapshot": True, "experimental_rows_read": False,
        "targets_read": False}


def preserve_failed_attempt(previous: Any, lock: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    if FAILED.exists() or FIX_DIR.exists():
        raise RuntimeError("branch-restore provenance namespace already exists; refusing reuse")
    expected = {
        "balanced/seed-1657290010/common/step-080.pt",
        "balanced/seed-1657290010/common/training-telemetry.jsonl",
        "balanced/seed-1657290010/branches/ONE_X/step-100.pt",
        "balanced/seed-1657290010/branches/ONE_X/step-120.pt",
        "balanced/seed-1657290010/branches/ONE_X/training-telemetry.jsonl",
    }
    files = sorted(path for path in ARTIFACTS.rglob("*") if path.is_file())
    observed = {path.relative_to(ARTIFACTS).as_posix() for path in files}
    if observed != expected:
        raise RuntimeError(f"partial training artifact inventory changed: {sorted(observed)}")
    if (TRAIN / "predictions").exists() or (TRAIN / "metrics").exists():
        raise RuntimeError("unexpected evaluation data exists; refusing training restart")

    FAILED.mkdir(parents=True, exist_ok=False)
    shutil.move(str(ARTIFACTS), str(FAILED / "original-artifacts-v01"))
    (FAILED / "traceback.txt").write_text(TRACEBACK, encoding="utf-8", newline="")
    entries = [{"path": path.relative_to(FAILED).as_posix(), "bytes": path.stat().st_size,
        "sha256": sha_file(path)} for path in sorted(p for p in FAILED.rglob("*") if p.is_file())]
    entries_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries).encode()).hexdigest()
    failure = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-TRAIN-ATTEMPT-FAIL02",
        "status": "FAILED_AT_BRANCH_RESTORE_HASH_GUARD",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "prior_device_fix_receipt_sha256": sha_file(previous.FIX_DIR / "device-fix-receipt-v01.json"),
        "locked_runner_sha256": sha_file(RUNNER_PATH),
        "exception": "RuntimeError: step-80 head/optimizer clone mismatch: balanced/1657290010/HALF",
        "completed_training": {"history": "balanced/1657290010", "common_steps": 80,
            "one_x_branch_steps": 40, "half_branch_started": False},
        "panel_or_heldout_targets_opened": False, "predictions_or_metrics_created": False,
        "failed_step80_checkpoint_sha256": sha_file(FAILED / "original-artifacts-v01" / "balanced/seed-1657290010/common/step-080.pt"),
        "diagnosis": "AdamW load_state_dict shared the CPU scalar step tensor with the in-memory fork snapshot; the first branch incremented the snapshot, so restoring the second branch correctly tripped the equality guard.",
        "synthetic_snapshot_smoke": smoke, "entries": entries,
        "entries_root_sha256": entries_root, "traceback_sha256": sha_file(FAILED / "traceback.txt")}
    previous.write_json(FAILED / "attempt-provenance.json", failure)
    previous.write_json(FAILED / "attempt-seal.json", {"status": failure["status"],
        "entries": entries, "entries_root_sha256": entries_root,
        "attempt_provenance_sha256": sha_file(FAILED / "attempt-provenance.json"),
        "traceback_sha256": failure["traceback_sha256"]})
    return failure


def main() -> int:
    previous = load_previous()
    runner = previous.load_runner()
    lock = runner.verify_lock()
    device_smoke = previous.device_smoke_test(runner)
    optimizer_smoke = optimizer_snapshot_smoke(runner)
    smoke = {"device": device_smoke, "optimizer_snapshot": optimizer_smoke}
    failure = preserve_failed_attempt(previous, lock, optimizer_smoke)
    FIX_DIR.mkdir(parents=True, exist_ok=False)
    source_hash = sha_file(Path(__file__).resolve())
    receipt = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-EXECFIX02",
        "status": "BRANCH_RESTORE_REPAIR_SEALED_PRE_RETRAINING",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "locked_trainer_sha256": sha_file(RUNNER_PATH),
        "adapter_source_sha256": source_hash,
        "previous_device_fix_source_sha256": sha_file(PREVIOUS),
        "failed_attempt_seal_sha256": sha_file(FAILED / "attempt-seal.json"),
        "changes": [
            "Keep the immutable 48x2048 candidate feature tensor on CUDA before the locked batcher gathers rows.",
            "Deep-copy the complete CPU optimizer snapshot for each branch restore, preventing AdamW's CPU step tensor from mutating the shared fork snapshot."
        ],
        "training_values_order_schedule_loss_denominator_optimizer_rng": "unchanged",
        "heldout_panel_or_targets_opened": False,
        "synthetic_smoke": smoke}
    previous.write_json(FIX_DIR / "branch-restore-fix-receipt-v01.json", receipt)

    original_run_steps = runner.run_steps
    cuda_candidate_cache: dict[int, torch.Tensor] = {}

    def run_steps_cuda_fix(cohort: str, seed: int, start: int, stop: int, multiplier: float,
            schedule_rows: list[dict[str, Any]], primary: list[dict[str, Any]],
            auxiliary: list[dict[str, Any]], states: torch.Tensor, candidates: torch.Tensor,
            head: torch.nn.Module, optimizer: torch.optim.Optimizer, helper: Any,
            batcher: Any, objective: Any, telemetry_path: Path,
            checkpoint_dir: Path, branch_name: str | None) -> tuple[Any, Any]:
        key = id(candidates)
        candidate_cuda = cuda_candidate_cache.get(key)
        if candidate_cuda is None:
            candidate_cuda = candidates.to("cuda")
            cuda_candidate_cache[key] = candidate_cuda
        return original_run_steps(cohort, seed, start, stop, multiplier, schedule_rows,
            primary, auxiliary, states, candidate_cuda, head, optimizer, helper,
            batcher, objective, telemetry_path, checkpoint_dir, branch_name)

    runner.run_steps = run_steps_cuda_fix
    original_adamw = torch.optim.AdamW

    def adamw_with_isolated_state(*args: Any, **kwargs: Any) -> torch.optim.Optimizer:
        optimizer = original_adamw(*args, **kwargs)
        original_load = optimizer.load_state_dict

        def isolated_load(state_dict: dict[str, Any]) -> Any:
            return original_load(copy.deepcopy(state_dict))

        optimizer.load_state_dict = isolated_load  # type: ignore[method-assign]
        return optimizer

    torch.optim.AdamW = adamw_with_isolated_state  # type: ignore[assignment]
    try:
        result = runner.main()
    finally:
        torch.optim.AdamW = original_adamw
    if result != 0:
        return result

    training_seal = runner.ARTIFACTS / "training-seal-v01.json"
    binding = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-EXECFIX02-TRAINING-BINDING",
        "status": "R3_EXECFIX02_TRAINING_OUTPUT_BOUND", "adapter_source_sha256": source_hash,
        "fix_receipt_sha256": sha_file(FIX_DIR / "branch-restore-fix-receipt-v01.json"),
        "training_seal_sha256": sha_file(training_seal),
        "training_entries_root_sha256": runner.read_json(training_seal)["entries_root_sha256"],
        "panel_behavior_opened": False, "predictions_created": False, "metrics_computed": False}
    previous.write_json(FIX_DIR / "training-output-binding-v01.json", binding)
    print(json.dumps({"status": "R3_V03_TRAINING_EXECFIX02_COMPLETE",
        "training_entries_root_sha256": binding["training_entries_root_sha256"],
        "execution_fix": str(FIX_DIR)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
