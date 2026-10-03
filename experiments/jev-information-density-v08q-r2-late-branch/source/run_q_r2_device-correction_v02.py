"""Versioned R2 restart adapter for the frozen feature-device mismatch.

The frozen batcher creates candidate-index tensors on the candidate feature
tensor's device, but the runner loaded the small shared candidate catalog on
CPU.  This adapter keeps all scientific inputs and the frozen trainer intact,
moves the 48x2048 candidate feature matrix to the already-contracted CUDA
device once, and writes this attempt to a fresh versioned output namespace.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
TRAIN_V01 = RUN / "training-v01"
TRAIN_V02 = RUN / "training-v02"
SCHEDULE = TRAIN_V01 / "schedule"
PROVENANCE = RUN / "provenance"
TRAINER = EXP / "source/run_q_r2_training_v01.py"
JOIN_ADAPTER = EXP / "source/run_q_r2_training_input-correction_v01.py"
JOIN_RECEIPT = PROVENANCE / "q-r2-training-input-correction-preflight-v01.json"
PRECHECK_V02 = PROVENANCE / "q-r2-device-correction-preflight-v02.json"
PRECHECK = PROVENANCE / "q-r2-device-correction-preflight-v02b.json"
FAILURE = PROVENANCE / "q-r2-device-correction-failure-v02.json"
COMPLETION = PROVENANCE / "q-r2-device-correction-completion-v02.json"
EXPECTED_JOIN_ADAPTER_SHA256 = "4cdd6234f5e23e833f195385895e974ec71f539b13d4ed0ab0ed3e74de7e5ac6"
EXPECTED_TRAINER_SHA256 = "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0"
EXPECTED_RUN_SHA256 = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
EXPECTED_ANALYSIS_SHA256 = "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64"
EXPECTED_PANEL_SHA256 = "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153"
EXPECTED_PACKET_SHA256 = "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def patch_candidate_device(trainer: Any) -> None:
    original_loader = trainer.load_frozen_sources

    def load_frozen_sources() -> tuple[Any, ...]:
        loaded = original_loader()
        if "--preflight" in sys.argv[1:]:
            return loaded
        require(torch.cuda.is_available(), "contracted CUDA device unavailable")
        values = list(loaded)
        cpu_candidates = values[4]
        require(tuple(cpu_candidates.shape) == (48, 2048) and cpu_candidates.dtype == torch.float32
                and cpu_candidates.is_contiguous() and bool(torch.isfinite(cpu_candidates).all()),
                "candidate feature matrix changed before device transfer")
        cpu_hash = trainer.tensor_sha(cpu_candidates)
        cuda_candidates = cpu_candidates.to(device="cuda", non_blocking=False).contiguous()
        require(tuple(cuda_candidates.shape) == (48, 2048) and cuda_candidates.dtype == torch.float32
                and bool(torch.isfinite(cuda_candidates).all()), "CUDA candidate matrix invalid")
        roundtrip_hash = trainer.tensor_sha(cuda_candidates.cpu())
        require(cpu_hash == roundtrip_hash, "candidate feature bytes changed during device transfer")
        values[4] = cuda_candidates
        return tuple(values)

    trainer.load_frozen_sources = load_frozen_sources


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_authorities(join_adapter: Any) -> dict[str, Any]:
    require(sha(TRAINER) == EXPECTED_TRAINER_SHA256, "frozen trainer source changed")
    require(sha(JOIN_ADAPTER) == EXPECTED_JOIN_ADAPTER_SHA256, "v01 join correction source changed")
    receipt = json.loads(JOIN_RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "Q_R2_TRAINING_INPUT_JOIN_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and receipt.get("adapter_sha256") == EXPECTED_JOIN_ADAPTER_SHA256
            and receipt.get("frozen_trainer_sha256") == EXPECTED_TRAINER_SHA256,
            "v01 target/candidate join preflight identity mismatch")
    require(not TRAIN_V02.exists(), "refusing to reuse R2 training-v02 output namespace")
    require(not TRAIN_V02.exists() and not COMPLETION.exists(), "refusing to reuse v02 output namespace")
    return {"join_receipt_sha256": sha(JOIN_RECEIPT), "adapter_sha256": EXPECTED_JOIN_ADAPTER_SHA256,
            "trainer_sha256": EXPECTED_TRAINER_SHA256, "preexisting_failed_attempt": str(TRAIN_V01 / "trajectories")}


def synthetic_device_smoke(trainer: Any) -> dict[str, Any]:
    batcher = load(ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py", "q_r2_device_smoke_batcher")
    state = torch.zeros((2, 2048), dtype=torch.float32, device="cpu")
    candidates = torch.arange(48 * 2048, dtype=torch.float32).reshape(48, 2048).to("cuda")
    row = {"group_id": "synthetic", "state_idx": 1,
           "candidate_indices": {"name_definition": [0, 1, 2, 3]},
           "gold": [0.1, 0.2, 0.3, 0.4], "kind": "choice",
           "probability_source": "exact_generative_posterior"}
    state_out, candidate_out, gold, mask, _, _ = batcher.fast_tensor_batch(
        [row], state, candidates, "name_definition", "cuda", reorder=True)
    devices = {str(t.device) for t in (state_out, candidate_out, gold, mask)}
    require(devices == {"cuda:0"} and tuple(candidate_out.shape) == (1, 4, 2048),
            "synthetic batch did not resolve to the contracted CUDA device")
    require(torch.equal(gold.cpu(), torch.tensor([[0.4, 0.3, 0.2, 0.1]])), "candidate reorder smoke mismatch")
    return {"status": "PASS", "device": "cuda:0", "candidate_shape": list(candidate_out.shape),
            "head_initialized": False, "optimizer_steps": 0}


def run() -> int:
    preflight = "--preflight" in sys.argv[1:]
    self_test = "--self-test" in sys.argv[1:]
    join_adapter = load(JOIN_ADAPTER, "q_r2_v01_input_join_adapter")
    trainer = join_adapter.load_module(TRAINER)
    join_adapter.install_join_adapter(trainer)
    patch_candidate_device(trainer)
    if self_test:
        print(json.dumps(synthetic_device_smoke(trainer), indent=2))
        return 0

    authorities = verify_authorities(join_adapter)
    trainer.RUN = RUN
    trainer.TRAIN = TRAIN_V02
    trainer.ARTIFACTS = TRAIN_V02 / "trajectories"
    trainer.SCHEDULE = SCHEDULE

    if preflight:
        require(not PRECHECK.exists(), "v02b correction preflight receipt already exists")
        sys.argv = [str(TRAINER), "--preflight"]
        status = trainer.main()
        require(status == 0, "frozen training preflight failed under v02 adapter")
        receipt = {"identity": "JEV-V08Q-R2-CANDIDATE-DEVICE-CORRECTION-V02",
            "status": "Q_R2_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION",
            "reason": "frozen batcher places candidate-index tensors on candidate feature device; exact sealed candidate matrix is now transferred once to the already-contracted CUDA device",
            "failed_v01_attempt": {"training_output_namespace": str(TRAIN_V01),
                "partial_artifact_tree_sha256": "PENDING_HASHED_BELOW", "optimizer_steps": 0,
                "panel_opened": False, "preserved_unchanged": True},
            "run_contract_sha256": EXPECTED_RUN_SHA256, "analysis_contract_sha256": EXPECTED_ANALYSIS_SHA256,
            "panel_contract_sha256": EXPECTED_PANEL_SHA256, "phase_packet_sha256": EXPECTED_PACKET_SHA256,
            "v01_join_preflight_receipt_sha256": authorities["join_receipt_sha256"],
            "v01_join_adapter_sha256": authorities["adapter_sha256"],
            "frozen_trainer_sha256": authorities["trainer_sha256"],
            "adapter_sha256": sha(Path(__file__).resolve()),
            "superseded_v02_preflight_receipt_sha256": sha(PRECHECK_V02),
            "earlier_launch_attempt": {
                "status": "NO_TRAINING_STARTED",
                "reason": "adapter incorrectly treated its successful preflight receipt as evidence that a launch had already occurred",
                "head_initialized": False, "optimizer_steps": 0, "panel_opened": False,
            },
            "device_smoke": synthetic_device_smoke(trainer),
            "new_training_output_namespace": str(TRAIN_V02),
            "schedule_path": str(SCHEDULE / "fixed-schedule.jsonl"),
            "schedule_sha256": sha(SCHEDULE / "fixed-schedule.jsonl"),
            "head_initialized": False, "optimizer_steps": 0, "panel_opened": False,
            "predictions": False, "metrics": False}
        failure_tree = []
        old_artifacts = TRAIN_V01 / "trajectories"
        if old_artifacts.exists():
            for path in sorted(old_artifacts.rglob("*")):
                if path.is_file():
                    failure_tree.append({"path": path.relative_to(TRAIN_V01).as_posix(),
                                         "bytes": path.stat().st_size, "sha256": sha(path)})
        root_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in failure_tree)
        receipt["failed_v01_attempt"]["partial_artifact_tree_sha256"] = hashlib.sha256(root_body.encode()).hexdigest()
        receipt["failed_v01_attempt"]["partial_artifact_entries"] = failure_tree
        write_new(PRECHECK, receipt)
        print(json.dumps(receipt, indent=2))
        return 0

    require(PRECHECK.is_file(), "v02 device-correction preflight receipt is missing")
    pre = json.loads(PRECHECK.read_text(encoding="utf-8"))
    require(pre.get("status") == "Q_R2_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and pre.get("adapter_sha256") == sha(Path(__file__).resolve())
            and pre.get("frozen_trainer_sha256") == sha(TRAINER)
            and pre.get("v01_join_adapter_sha256") == sha(JOIN_ADAPTER), "v02 correction preflight identity mismatch")
    sys.argv = [str(TRAINER)]
    try:
        status = trainer.main()
        require(status == 0, "frozen trainer returned nonzero status")
    except BaseException as exc:
        if not FAILURE.exists():
            write_new(FAILURE, {"identity": "JEV-V08Q-R2-DEVICE-CORRECTION-FAILURE-V02",
                "status": "Q_R2_TRAINING_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "training_output_namespace": str(TRAIN_V02), "adapter_sha256": sha(Path(__file__).resolve()),
                "head_initialization_may_have_occurred": TRAIN_V02.exists(),
                "panel_opened": False, "automatic_retry": False})
        raise
    seal_path = TRAIN_V02 / "training-seal-manifest.json"
    tree_path = TRAIN_V02 / "checkpoint-hash-tree.json"
    require(seal_path.is_file() and tree_path.is_file(), "R2 training completion seal is incomplete")
    completion = {"identity": "JEV-V08Q-R2-DEVICE-CORRECTION-COMPLETION-V02",
        "status": "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED",
        "preflight_receipt_sha256": sha(PRECHECK), "adapter_sha256": sha(Path(__file__).resolve()),
        "training_seal_sha256": sha(seal_path), "checkpoint_tree_sha256": sha(tree_path),
        "checkpoint_tree_root_sha256": json.loads(tree_path.read_text(encoding="utf-8"))["entries_root_sha256"],
        "head_initialization": True, "training_complete": True, "panel_opened": False,
        "evaluation": False, "predictions": False, "metrics": False}
    write_new(COMPLETION, completion)
    print(json.dumps(completion, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
