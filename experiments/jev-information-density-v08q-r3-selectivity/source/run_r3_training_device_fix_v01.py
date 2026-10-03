"""Versioned device-placement repair for the locked R3 training runner.

The frozen runner and scientific inputs remain untouched. This adapter keeps
the small candidate catalog resident on CUDA before invoking the locked batcher.
"""

from __future__ import annotations

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
TRAIN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03\training-v01")
FAILED = TRAIN / "failed-attempt-device-mismatch-v01"
FIX_DIR = TRAIN / "execution-fix-v01"
ARTIFACTS = TRAIN / "artifacts-v01"
RUNNER_PATH = EXP / "source/run_r3_confirmatory_training_v01.py"
LOCK_PATH = EXP / "seals/r3-phase-packet-seal-v01.json"

TRACEBACK = r"""Traceback (most recent call last):
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 464, in <module>
    raise SystemExit(main())
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 414, in main
    receipt = train_history(cohort, seed, cohort_schedule, cohort_primary, cohort_aux,
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 273, in train_history
    common_fork, common_telemetry = run_steps(cohort, seed, 0, 80, 1.0, common_schedule,
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 195, in run_steps
    logits = head(state, candidate)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1779, in _wrapped_call_impl
    return self._call_impl(*args, **kwargs)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1790, in _call_impl
    result = forward_call(*args, **kwargs)
  File "C:\code land\clean-rust\experiments\jev-frozen-readout-v01\probe.py", line 415, in forward
    candidate_projection = self.candidate_projection(candidate)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1779, in _wrapped_call_impl
    return self._call_impl(*args, **kwargs)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1790, in _call_impl
    return forward_call(*args, **kwargs)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\linear.py", line 134, in forward
    return F.linear(input, self.weight, self.bias)
RuntimeError: Expected all tensors to be on the same device, but got mat2 is on cuda:0, different from other tensors on cpu (when checking argument in method wrapper_CUDA_mm)
"""

TRACEBACK_COMPLETE = r"""Traceback (most recent call last):
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 464, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 414, in main
    receipt = train_history(cohort, seed, cohort_schedule, cohort_primary, cohort_aux,
        states, candidates, helper, batcher, objective)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 273, in train_history
    common_fork, common_telemetry = run_steps(cohort, seed, 0, 80, 1.0, common_schedule,
                                    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        primary, auxiliary, states, candidates, head, optimizer, helper, batcher, objective,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        common_dir / "training-telemetry.jsonl", common_dir, None)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity\source\run_r3_confirmatory_training_v01.py", line 195, in run_steps
    logits = head(state, candidate)
             ^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1779, in _wrapped_call_impl
    return self._call_impl(*args, **kwargs)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1790, in _call_impl
    return forward_call(*args, **kwargs)
           ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\code land\clean-rust\experiments\jev-frozen-readout-v01\probe.py", line 415, in forward
    candidate_projection = self.candidate_projection(candidate)
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1779, in _wrapped_call_impl
    return self._call_impl(*args, **kwargs)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\module.py", line 1790, in _call_impl
    return forward_call(*args, **kwargs)
           ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\shuga\AppData\Local\Programs\Python\Python313\Lib\site-packages\torch\nn\modules\linear.py", line 134, in forward
    return F.linear(input, self.weight, self.bias)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Expected all tensors to be on the same device, but got mat2 is on cuda:0, different from other tensors on cpu (when checking argument in method wrapper_CUDA_mm)
"""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("jev_r3_locked_training_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact locked R3 training runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def device_smoke_test(runner: Any) -> dict[str, Any]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable for the authorized R3 training run")
    batcher = runner.load_module(runner.BATCHER, "jev_r3_device_fix_smoke_batcher")
    probe = runner.load_module(runner.PROBE, "jev_r3_device_fix_smoke_probe")
    state_features = torch.zeros((1, 2048), dtype=torch.float32)
    candidate_features_cpu = torch.zeros((4, 2048), dtype=torch.float32)
    candidate_features = candidate_features_cpu.to("cuda")
    group = {"state_idx": 0, "candidate_indices": {runner.PROFILE: [0, 1, 2, 3]},
        "gold": [0.1, 0.2, 0.3, 0.4], "kind": "synthetic", "probability_source": "fixture"}
    state, candidate, _gold, _mask, _kinds, _sources = batcher.fast_tensor_batch(
        [group], state_features, candidate_features, runner.PROFILE, "cuda", reorder=True)
    if state.device.type != "cuda" or candidate.device.type != "cuda":
        raise RuntimeError("device smoke test did not place scorer inputs on CUDA")
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.eval()
    with torch.inference_mode():
        logits = head(state, candidate)
    torch.cuda.synchronize()
    if tuple(logits.shape) != (1, 4) or not bool(torch.isfinite(logits).all()):
        raise RuntimeError("synthetic scorer forward failed after candidate placement fix")
    return {"status": "SYNTHETIC_DEVICE_SMOKE_PASS", "state_device": str(state.device),
        "candidate_device": str(candidate.device), "logit_shape": list(logits.shape),
        "experimental_rows_read": False, "targets_read": False}


def preserve_failed_attempt(lock: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    if FAILED.exists() or FIX_DIR.exists():
        raise RuntimeError("R3 device-fix provenance namespace already exists; refusing reuse")
    telemetry = ARTIFACTS / "balanced/seed-1657290010/common/training-telemetry.jsonl"
    files = sorted(path for path in ARTIFACTS.rglob("*") if path.is_file())
    if len(files) != 1 or files[0] != telemetry or telemetry.stat().st_size != 0:
        raise RuntimeError("failed invocation artifacts differ from observed zero-step attempt")
    if any(path.name.endswith(".pt") for path in ARTIFACTS.rglob("*")):
        raise RuntimeError("failed invocation unexpectedly left a checkpoint")
    if any((TRAIN / name).exists() for name in ("predictions", "metrics", "evaluation")):
        raise RuntimeError("unexpected evaluation artifact exists; cannot continue hotfix")

    FAILED.mkdir(parents=True, exist_ok=False)
    (FAILED / "original-artifacts-v01").parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ARTIFACTS), str(FAILED / "original-artifacts-v01"))
    (FAILED / "traceback.txt").write_text(TRACEBACK_COMPLETE, encoding="utf-8", newline="")
    file_entries = []
    for path in sorted(p for p in FAILED.rglob("*") if p.is_file()):
        file_entries.append({"path": path.relative_to(FAILED).as_posix(),
            "bytes": path.stat().st_size, "sha256": sha_file(path)})
    root_text = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in file_entries)
    root = hashlib.sha256(root_text.encode()).hexdigest()
    failure = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-TRAIN-ATTEMPT-FAIL01",
        "status": "FAILED_BEFORE_FIRST_OPTIMIZER_STEP_DEVICE_MISMATCH",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "locked_runner_sha256": sha_file(RUNNER_PATH),
        "exception": "RuntimeError: Expected all tensors to be on the same device; candidate tensor on CPU, model on CUDA",
        "stage": "first balanced history, first scheduled training step, scorer forward",
        "optimizer_steps_completed": 0, "head_initialized": True,
        "training_examples_loaded": True, "training_loss_computed": False,
        "backward_or_optimizer_step": False, "heldout_panel_or_targets_opened": False,
        "predictions_or_metrics_created": False, "smoke_test": smoke,
        "preserved_files": file_entries, "preserved_entries_root_sha256": root,
        "traceback_sha256": sha_file(FAILED / "traceback.txt")}
    write_json(FAILED / "attempt-provenance.json", failure)
    failure_seal = {"status": failure["status"], "entries": file_entries,
        "entries_root_sha256": root, "attempt_provenance_sha256": sha_file(FAILED / "attempt-provenance.json"),
        "traceback_sha256": failure["traceback_sha256"]}
    write_json(FAILED / "attempt-seal.json", failure_seal)
    return failure


def main() -> int:
    runner = load_runner()
    lock = runner.verify_lock()
    smoke = device_smoke_test(runner)
    failure = preserve_failed_attempt(lock, smoke)
    FIX_DIR.mkdir(parents=True, exist_ok=False)
    source_hash = sha_file(Path(__file__).resolve())
    fix_receipt = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-EXECFIX01",
        "status": "DEVICE_PLACEMENT_REPAIR_SEALED_PRE_RETRAINING",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "locked_trainer_sha256": sha_file(RUNNER_PATH), "adapter_source_sha256": source_hash,
        "failure_seal_sha256": sha_file(FAILED / "attempt-seal.json"),
        "change": "Keep the immutable 48x2048 candidate feature table on CUDA for each run_steps invocation before the locked batcher gathers candidate rows.",
        "values_or_order_changed": False, "training_schedule_changed": False,
        "loss_or_denominator_changed": False, "optimizer_or_rng_changed": False,
        "panel_or_evaluation_touched": False, "synthetic_smoke": smoke}
    write_json(FIX_DIR / "device-fix-receipt-v01.json", fix_receipt)

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
    runner.ARTIFACTS = ARTIFACTS
    result = runner.main()
    if result != 0:
        return result
    training_seal = ARTIFACTS / "training-seal-v01.json"
    binding = {"identity": "JEV-V08Q-R3-SELECTIVITY-V03-EXECFIX01-TRAINING-BINDING",
        "status": "R3_DEVICE_FIX_TRAINING_OUTPUT_BOUND",
        "adapter_source_sha256": source_hash,
        "fix_receipt_sha256": sha_file(FIX_DIR / "device-fix-receipt-v01.json"),
        "training_seal_sha256": sha_file(training_seal),
        "training_entries_root_sha256": runner.read_json(training_seal)["entries_root_sha256"],
        "panel_behavior_opened": False, "predictions_created": False, "metrics_computed": False}
    write_json(FIX_DIR / "training-output-binding-v01.json", binding)
    print(json.dumps({"status": "R3_V03_TRAINING_DEVICE_FIX_EXECUTION_COMPLETE",
        "training_entries_root_sha256": binding["training_entries_root_sha256"],
        "execution_fix": str(FIX_DIR)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
