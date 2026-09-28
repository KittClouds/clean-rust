"""R2 v03 restart adapter for checkpoint-path hashing compatibility.

The v01 trainer records a checkpoint callback path as `str`, then passes that
string to a hashing helper that expects `Path`.  This adapter makes the helper
accept either representation without changing checkpoint bytes or training
semantics, retains the earlier failures, and uses a clean training-v03 output
namespace.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
TRAIN_V01 = RUN / "training-v01"
TRAIN_V02 = RUN / "training-v02"
TRAIN_V03 = RUN / "training-v03"
SCHEDULE = TRAIN_V01 / "schedule"
PROVENANCE = RUN / "provenance"
TRAINER = EXP / "source/run_q_r2_training_v01.py"
DEVICE_ADAPTER = EXP / "source/run_q_r2_device-correction_v02.py"
JOIN_ADAPTER = EXP / "source/run_q_r2_training_input-correction_v01.py"
V02_PREFLIGHT = PROVENANCE / "q-r2-device-correction-preflight-v02b.json"
V02_FAILURE = PROVENANCE / "q-r2-device-correction-failure-v02.json"
V03_OLD_PREFLIGHT = PROVENANCE / "q-r2-path-correction-preflight-v03.json"
V03_PREFLIGHT = PROVENANCE / "q-r2-path-correction-preflight-v03b.json"
V03_FAILURE = PROVENANCE / "q-r2-path-correction-failure-v03.json"
V03_COMPLETION = PROVENANCE / "q-r2-path-correction-completion-v03.json"
EXPECTED_TRAINER_SHA256 = "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0"
EXPECTED_DEVICE_ADAPTER_SHA256 = "cdee8cfa3fbc77a7cc3d452d6864f6acea9a1b0bcdd2827c965baf5a11493c73"
EXPECTED_JOIN_ADAPTER_SHA256 = "4cdd6234f5e23e833f195385895e974ec71f539b13d4ed0ab0ed3e74de7e5ac6"
EXPECTED_RUN_SHA256 = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
EXPECTED_ANALYSIS_SHA256 = "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64"
EXPECTED_PANEL_SHA256 = "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153"
EXPECTED_PACKET_SHA256 = "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209"
EXPECTED_V03_OLD_ADAPTER_SHA256 = "80f64b95ba6fdfa51a6e7059d1211f90191e00680c919ce1c503c929d75c3dd3"


def sha(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def file_tree(root: Path) -> tuple[list[dict[str, Any]], str]:
    rows = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in rows)
    return rows, hashlib.sha256(body.encode()).hexdigest()


def load_bundle() -> tuple[Any, Any, Any]:
    spec = importlib.util.spec_from_file_location("q_r2_v02_device_adapter", DEVICE_ADAPTER)
    require(spec is not None and spec.loader is not None, "cannot load v02 device adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    join = module.load(JOIN_ADAPTER, "q_r2_v01_join_adapter_for_v03")
    trainer = join.load_module(TRAINER)
    join.install_join_adapter(trainer)
    module.patch_candidate_device(trainer)
    original_sha = trainer.sha
    trainer.sha = lambda path: original_sha(Path(path))
    return module, join, trainer


def verify_predecessors() -> dict[str, Any]:
    require(sha(TRAINER) == EXPECTED_TRAINER_SHA256, "frozen trainer hash mismatch")
    require(sha(DEVICE_ADAPTER) == EXPECTED_DEVICE_ADAPTER_SHA256, "v02 device adapter hash mismatch")
    require(sha(JOIN_ADAPTER) == EXPECTED_JOIN_ADAPTER_SHA256, "v01 input adapter hash mismatch")
    pre = json.loads(V02_PREFLIGHT.read_text(encoding="utf-8"))
    require(pre.get("status") == "Q_R2_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and pre.get("adapter_sha256") == EXPECTED_DEVICE_ADAPTER_SHA256,
            "v02 device preflight binding mismatch")
    require(V02_FAILURE.is_file(), "v02 failed-attempt receipt missing")
    failed_rows, failed_root = file_tree(TRAIN_V02)
    require(failed_rows and not (TRAIN_V02 / "training-seal-manifest.json").exists(),
            "v02 attempt is empty or unexpectedly sealed as complete")
    old_preflight = json.loads(V03_OLD_PREFLIGHT.read_text(encoding="utf-8"))
    require(old_preflight.get("status") == "Q_R2_PATH_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and old_preflight.get("current_adapter_sha256") == EXPECTED_V03_OLD_ADAPTER_SHA256,
            "prior v03 preflight receipt identity mismatch")
    require(not TRAIN_V03.exists() and not V03_COMPLETION.exists(), "refusing to reuse v03 training output namespace")
    return {"trainer_sha256": EXPECTED_TRAINER_SHA256,
            "device_adapter_sha256": EXPECTED_DEVICE_ADAPTER_SHA256,
            "join_adapter_sha256": EXPECTED_JOIN_ADAPTER_SHA256,
            "v02_preflight_receipt_sha256": sha(V02_PREFLIGHT),
            "v02_failure_receipt_sha256": sha(V02_FAILURE),
            "superseded_v03_preflight_receipt_sha256": sha(V03_OLD_PREFLIGHT),
            "v02_partial_tree_sha256": failed_root,
            "v02_partial_tree_entries": failed_rows}


def run() -> int:
    preflight = "--preflight" in sys.argv[1:]
    launch_check = "--launch-precheck" in sys.argv[1:]
    device_adapter, join_adapter, trainer = load_bundle()
    previous = verify_predecessors()
    trainer.RUN = RUN
    trainer.TRAIN = TRAIN_V03
    trainer.ARTIFACTS = TRAIN_V03 / "trajectories"
    trainer.SCHEDULE = SCHEDULE

    if preflight:
        require(not V03_PREFLIGHT.exists(), "v03b preflight receipt already exists")
        sys.argv = [str(TRAINER), "--preflight"]
        status = trainer.main()
        require(status == 0, "training preflight failed under v03 path adapter")
        schedule_path = SCHEDULE / "fixed-schedule.jsonl"
        receipt = {"identity": "JEV-V08Q-R2-PATH-HASH-ADAPTER-V03",
            "status": "Q_R2_PATH_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION",
            "execution_defect": "step80 checkpoint callback returns a string path; frozen trainer sha helper requires Path",
            "repair": "coerce hash-helper input with pathlib.Path; checkpoint payload and bytes unchanged",
            "previous_failed_attempts": previous,
            "run_contract_sha256": EXPECTED_RUN_SHA256,
            "analysis_contract_sha256": EXPECTED_ANALYSIS_SHA256,
            "panel_contract_sha256": EXPECTED_PANEL_SHA256,
            "phase_packet_sha256": EXPECTED_PACKET_SHA256,
            "v02_device_adapter_sha256": sha(DEVICE_ADAPTER),
            "v01_join_adapter_sha256": sha(JOIN_ADAPTER),
            "frozen_trainer_sha256": sha(TRAINER),
            "current_adapter_sha256": sha(Path(__file__).resolve()),
            "schedule_sha256": sha(schedule_path),
            "output_namespace": str(TRAIN_V03),
            "head_initialized": False, "optimizer_steps": 0,
            "panel_opened": False, "predictions": False, "metrics": False}
        with V03_PREFLIGHT.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(receipt, indent=2))
        return 0

    pre = json.loads(V03_PREFLIGHT.read_text(encoding="utf-8"))
    require(pre.get("status") == "Q_R2_PATH_DEVICE_AND_INPUT_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and pre.get("current_adapter_sha256") == sha(Path(__file__).resolve()),
            "v03 preflight receipt does not bind this adapter")
    if launch_check:
        print(json.dumps({"status": "Q_R2_LAUNCH_BINDINGS_PASS_NO_HEAD_INITIALIZATION",
            "preflight_receipt_sha256": sha(V03_PREFLIGHT),
            "adapter_sha256": sha(Path(__file__).resolve()),
            "new_output_namespace_absent": not TRAIN_V03.exists(),
            "head_initialized": False, "optimizer_steps": 0, "panel_opened": False}, indent=2))
        return 0
    sys.argv = [str(TRAINER)]
    try:
        status = trainer.main()
        require(status == 0, "frozen trainer returned nonzero status")
    except BaseException as exc:
        if not V03_FAILURE.exists():
            rows, root = file_tree(TRAIN_V03)
            receipt = {"identity": "JEV-V08Q-R2-PATH-ADAPTER-FAILURE-V03",
                "status": "Q_R2_TRAINING_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "partial_tree_sha256": root, "partial_tree_entries": rows,
                "output_namespace": str(TRAIN_V03), "panel_opened": False,
                "automatic_retry": False}
            with V03_FAILURE.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        raise
    training_seal = TRAIN_V03 / "training-seal-manifest.json"
    checkpoint_tree = TRAIN_V03 / "checkpoint-hash-tree.json"
    require(training_seal.is_file() and checkpoint_tree.is_file(), "v03 training seals incomplete")
    tree = json.loads(checkpoint_tree.read_text(encoding="utf-8"))
    completion = {"identity": "JEV-V08Q-R2-PATH-ADAPTER-COMPLETION-V03",
        "status": "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED",
        "preflight_receipt_sha256": sha(V03_PREFLIGHT),
        "adapter_sha256": sha(Path(__file__).resolve()),
        "training_seal_sha256": sha(training_seal),
        "checkpoint_tree_sha256": sha(checkpoint_tree),
        "checkpoint_tree_root_sha256": tree["entries_root_sha256"],
        "head_initialization": True, "training_complete": True,
        "panel_opened": False, "evaluation": False, "predictions": False, "metrics": False}
    with V03_COMPLETION.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(completion, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(completion, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
