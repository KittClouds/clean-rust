"""Continue the sole authorized R2 panel opening with the trainer's state hash.

The frozen evaluator and trainer used different state-hash encodings.  This
adapter routes the evaluator's checkpoint integrity check through the exact
hash function that created the sealed checkpoints, without changing checkpoint
bytes, inference, metrics, or the single existing panel-opening receipt.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
SOURCE = EXP / "source"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
TRAIN_V01 = RUN / "training-v01"
TRAIN_V02 = RUN / "training-v02"
TRAIN_V03 = RUN / "training-v03"
SCHEDULE = TRAIN_V01 / "schedule"
PANEL = RUN / "panel-v01"
EVAL_V01 = RUN / "evaluation-v01"
EVAL_V02 = RUN / "evaluation-v02"
EVAL_V03 = RUN / "evaluation-v03"
PROVENANCE = RUN / "provenance"
V02_ADAPTER = SOURCE / "execute_q_r2_evaluation_correction_v02.py"
V01_TRAINER = SOURCE / "run_q_r2_training_v01.py"
V02_PREFLIGHT = PROVENANCE / "q-r2-evaluation-correction-preflight-v02.json"
V02_EXECUTION = PROVENANCE / "q-r2-evaluation-correction-execution-v02.json"
V02_OUTER_FAILURE = PROVENANCE / "q-r2-evaluation-correction-failure-v02.json"
V02_EVAL_FAILURE = EVAL_V02 / "evaluation-failure-receipt-v01.json"
V02_EMPTY_PREDICTIONS = EVAL_V02 / "raw-predictions-v01.jsonl"
V03_PREFLIGHT = PROVENANCE / "q-r2-evaluation-correction-preflight-v03.json"
V03_EXECUTION = PROVENANCE / "q-r2-evaluation-correction-execution-v03.json"
V03_FAILURE = PROVENANCE / "q-r2-evaluation-correction-failure-v03.json"
V03_COMPLETION = PROVENANCE / "q-r2-completion-seal-v04.json"
EXPECTED_V02_ADAPTER_SHA256 = "157e397aac307269aab39396617f9aaafd131077cbb6e4bb32dbc571270905bc"
EXPECTED_TRAINER_SHA256 = "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0"
EXPECTED_V02_PREFLIGHT_SHA256 = "3c5bd7b2e37f5d2cb704f580e88a3038a3889272a912cb04a09f572dfebcfb11"
EXPECTED_V02_EXECUTION_SHA256 = "56cef059b3418eb6a07073699ab6e6d1f095f5bb34c2494c33813c9b96861a96"
EXPECTED_V02_FAILURE_SHA256 = "10f0f99d64ed9a44864fb150c1e2902c99cc2468b0b12d601e4c3580e90891d5"
EXPECTED_V02_EVAL_FAILURE_SHA256 = "aa3b6f8de85b3bd9b23b04d333a68dfe323907339e391bf29a3dc2c93cdaec27"
EXPECTED_ORIGINAL_OPENING_SHA256 = "2c291a352b8490ddf63b298a7118ec842cce50654005f27190975d22ef13a8f2"
EXPECTED_TRAINING_SEAL_SHA256 = "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84"
EXPECTED_TRAINING_TREE_SHA256 = "9708a4388923021c9b5d14b0b8dd33868902de61f568a200432f89cfb4cbaa9f"


def sha(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
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


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def verify_previous_attempt() -> dict[str, Any]:
    require(sha(V02_ADAPTER) == EXPECTED_V02_ADAPTER_SHA256
            and sha(V01_TRAINER) == EXPECTED_TRAINER_SHA256,
            "bound v02 adapter or checkpoint-producing trainer source changed")
    for path, expected in ((V02_PREFLIGHT, EXPECTED_V02_PREFLIGHT_SHA256),
                           (V02_EXECUTION, EXPECTED_V02_EXECUTION_SHA256),
                           (V02_OUTER_FAILURE, EXPECTED_V02_FAILURE_SHA256),
                           (V02_EVAL_FAILURE, EXPECTED_V02_EVAL_FAILURE_SHA256)):
        require(path.is_file() and sha(path) == expected, f"v02 failure-chain artifact mismatch: {path.name}")
    preflight = json.loads(V02_PREFLIGHT.read_text(encoding="utf-8"))
    execution = json.loads(V02_EXECUTION.read_text(encoding="utf-8"))
    outer = json.loads(V02_OUTER_FAILURE.read_text(encoding="utf-8"))
    inner = json.loads(V02_EVAL_FAILURE.read_text(encoding="utf-8"))
    require(preflight.get("status") == "Q_R2_SAME_OPENING_CONTINUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION"
            and execution.get("status") == "Q_R2_CONTINUING_WITHIN_EXISTING_SINGLE_OPENING"
            and outer.get("opening_count") == 1 and outer.get("additional_unlock") is False
            and inner.get("exception") == "R2 checkpoint identity/state mismatch: 646142852/COMMON_SHAM_1X/80",
            "v02 attempt was not the expected state-hash mismatch")
    require(V02_EMPTY_PREDICTIONS.is_file() and V02_EMPTY_PREDICTIONS.stat().st_size == 0
            and not (EVAL_V02 / "raw-prediction-hash-tree-v01.json").exists()
            and not (EVAL_V02 / "inference-receipt-v01.json").exists()
            and not (EVAL_V02 / "q-r2-analysis-v01.json").exists(),
            "v02 unexpectedly emitted prediction rows or analysis")
    opening = EVAL_V01 / "panel-opening-receipt-v01.json"
    require(sha(opening) == EXPECTED_ORIGINAL_OPENING_SHA256
            and sha(EVAL_V02 / "panel-opening-receipt-v01.json") == EXPECTED_ORIGINAL_OPENING_SHA256,
            "continuation no longer references the original sole opening receipt")
    training_seal = TRAIN_V03 / "training-seal-manifest.json"
    training_tree = TRAIN_V03 / "checkpoint-hash-tree.json"
    require(sha(training_seal) == EXPECTED_TRAINING_SEAL_SHA256
            and sha(training_tree) == EXPECTED_TRAINING_TREE_SHA256,
            "sealed training artifacts changed between evaluation continuations")
    require(not EVAL_V03.exists() and not V03_PREFLIGHT.exists() and not V03_EXECUTION.exists()
            and not V03_COMPLETION.exists(), "refusing to reuse evaluation-v03 namespace")
    return {"v02_adapter_sha256": sha(V02_ADAPTER), "v02_preflight_sha256": sha(V02_PREFLIGHT),
            "v02_execution_sha256": sha(V02_EXECUTION), "v02_outer_failure_sha256": sha(V02_OUTER_FAILURE),
            "v02_evaluator_failure_sha256": sha(V02_EVAL_FAILURE),
            "empty_prediction_file_bytes": 0, "checkpoint_deserialized_to_cpu": True,
            "inference_head_constructed": False, "forward_passes": 0,
            "opening_receipt_sha256": sha(opening), "opening_count": 1,
            "v03_training_seal_sha256": sha(training_seal), "v03_checkpoint_tree_sha256": sha(training_tree)}


def load_bundle() -> tuple[Any, Any, Any, Any, Any]:
    prior = load(V02_ADAPTER, "q_r2_evaluation_v02_adapter_for_v03")
    routing = load(SOURCE / "execute_q_r2_evaluation_training-v03_adapter_v01.py",
                   "q_r2_evaluation_training_root_router_for_v03")
    evaluator, analyzer, replay = prior.configure_v01_adapter(routing, EVAL_V03)
    trainer = load(V01_TRAINER, "q_r2_checkpoint_state_hash_authority")
    require(sha(V01_TRAINER) == EXPECTED_TRAINER_SHA256, "checkpoint state-hash source identity mismatch")
    evaluator.state_sha = trainer.state_sha
    analyzer.OUTPUT = EVAL_V03
    replay.TRAIN = TRAIN_V03
    replay.EVAL = EVAL_V03
    replay.RECEIPT = EVAL_V03 / "independent-replay-verification-v01.json"
    return prior, evaluator, analyzer, replay, trainer


def preflight() -> dict[str, Any]:
    previous = verify_previous_attempt()
    prior, evaluator, _, _, trainer = load_bundle()
    evaluator.INSTRUMENT_RECEIPT = evaluator.verify_instrument_package()
    packet = evaluator.verify_packet()
    training_seal, checkpoint_lookup = evaluator.verify_training()
    panel = evaluator.verify_panel_seal()
    require(len(checkpoint_lookup) == 120 and training_seal.get("evaluation_panel_opened") is False,
            "v03 preflight checkpoint matrix/training firewall mismatch")
    # Validate the authoritative state-digest implementation on a synthetic CPU fixture.
    fixture = {"weight": __import__("torch").tensor([[1.0, -2.0], [0.5, 3.0]], dtype=__import__("torch").float32)}
    expected = trainer.state_sha(fixture)
    require(len(expected) == 64 and evaluator.state_sha(fixture) == expected,
            "evaluator did not bind the checkpoint-producing state-hash implementation")
    first_entry = checkpoint_lookup[(646142852, "COMMON_SHAM_1X", 80)]
    checkpoint = __import__("torch").load(first_entry["path"], map_location="cpu", weights_only=False)
    observed_checkpoint_state_sha = trainer.state_sha(checkpoint["head_state"])
    require(observed_checkpoint_state_sha == first_entry["head_sha256"] == checkpoint["head_sha256"],
            "trainer-authoritative state hash does not reproduce the sealed step-80 payload")
    return {"identity": "JEV-V08Q-R2-CHECKPOINT-STATE-HASH-CORRECTION-V03",
            "status": "Q_R2_SAME_OPENING_STATE_HASH_PREFLIGHT_PASS_NO_INFERENCE",
            "previous_attempt": previous, "packet": packet, "panel": panel,
            "checkpoint_cells": len(checkpoint_lookup),
            "checkpoint_hash_implementation": {"source_path": str(V01_TRAINER),
                "source_sha256": sha(V01_TRAINER), "function": "run_q_r2_training_v01.state_sha",
                "synthetic_fixture_digest": expected,
                "step80_checkpoint_digest_verified": observed_checkpoint_state_sha,
                "step80_checkpoint_deserialized_to_cpu": True, "inference_head_constructed": False},
            "output_namespace": str(EVAL_V03), "opening_count": 1,
            "additional_unlock": False, "prediction_rows_before_continuation": 0,
            "inference": False, "metrics": False,
            "feature_cache_root_binding_correction_sha256": sha(V02_ADAPTER)}


def seal_completion(replay_result: dict[str, Any]) -> dict[str, Any]:
    paths = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        PROVENANCE / "q-r2-instrument-package-seal-v01.json",
        PANEL / "seals/q-r2-panel-construction-seal-v01.json",
        PANEL / "seals/q-r2-feature-cache-seal-v01.json",
        PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
        TRAIN_V01 / "schedule/schedule-seal.json",
        TRAIN_V03 / "common-prefix-seal-v01.json",
        TRAIN_V03 / "checkpoint-hash-tree.json",
        TRAIN_V03 / "training-seal-manifest.json",
        PROVENANCE / "q-r2-training-input-correction-preflight-v01.json",
        PROVENANCE / "q-r2-device-correction-preflight-v02b.json",
        PROVENANCE / "q-r2-path-correction-preflight-v03b.json",
        PROVENANCE / "q-r2-path-correction-completion-v03.json",
        PROVENANCE / "q-r2-evaluation-routing-preflight-v01.json",
        PROVENANCE / "q-r2-evaluation-routing-execution-v01.json",
        PROVENANCE / "q-r2-evaluation-routing-failure-v01.json",
        PROVENANCE / "q-r2-evaluation-correction-preflight-v02.json",
        PROVENANCE / "q-r2-evaluation-correction-execution-v02.json",
        PROVENANCE / "q-r2-evaluation-correction-failure-v02.json",
        SOURCE / "execute_q_r2_evaluation_training-v03_adapter_v01.py",
        SOURCE / "execute_q_r2_evaluation_correction_v02.py",
        SOURCE / "execute_q_r2_evaluation_correction_v03.py",
        SOURCE / "run_q_r2_training_v01.py",
        EVAL_V01 / "panel-opening-receipt-v01.json",
        EVAL_V01 / "evaluation-failure-receipt-v01.json",
        EVAL_V02 / "panel-opening-receipt-v01.json",
        EVAL_V02 / "evaluation-failure-receipt-v01.json",
        EVAL_V02 / "raw-predictions-v01.jsonl",
        V03_PREFLIGHT,
        V03_EXECUTION,
        EVAL_V03 / "panel-opening-receipt-v01.json",
        EVAL_V03 / "raw-prediction-hash-tree-v01.json",
        EVAL_V03 / "inference-receipt-v01.json",
        EVAL_V03 / "q-r2-analysis-seal-v01.json",
        EVAL_V03 / "independent-replay-verification-v01.json",
        EVAL_V03 / "raw-predictions-v01.jsonl",
        EVAL_V03 / "neighborhood-metrics-v01.jsonl",
        EVAL_V03 / "shared-neighborhood-bootstrap-plan-v01.npy",
        EVAL_V03 / "shared-moderator-seed-resample-plan-v01.npy",
        EVAL_V03 / "q-r2-analysis-v01.json",
        EVAL_V03 / "q-r2-results-v01.md",
    ]
    rows = []
    for path in paths:
        require(path.is_file(), f"Q-R2 v04 completion artifact missing: {path}")
        rows.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    require(len({row["path"] for row in rows}) == len(rows), "duplicate file in Q-R2 v04 completion tree")
    root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(rows, key=lambda item: item["path"])).encode()).hexdigest()
    receipt = {"status": "Q_R2_COMPLETE_RESULT_SEALED", "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
        "evaluation_namespace": str(EVAL_V03), "opening_count": 1,
        "second_unlock": False, "second_opening": False,
        "original_opening_receipt_sha256": EXPECTED_ORIGINAL_OPENING_SHA256,
        "corrections": [
            {"identity": "Q-R2-FEATURE-CACHE-ROOT-BINDING-RECONSTRUCTION-V02",
             "adapter_sha256": sha(SOURCE / "execute_q_r2_evaluation_correction_v02.py"),
             "scientific_contracts_changed": False, "metrics_changed": False},
            {"identity": "Q-R2-TRAINER-CONSISTENT-CHECKPOINT-STATE-HASH-V03",
             "adapter_sha256": sha(Path(__file__).resolve()),
             "state_hash_source_sha256": EXPECTED_TRAINER_SHA256,
             "scientific_contracts_changed": False, "metrics_changed": False},
        ],
        "independent_replay_status": replay_result["status"],
        "artifact_root_sha256": root, "artifact_count": len(rows), "artifacts": rows,
        "training_checkpoint_tree_root_sha256": "db75e29c1ec0295d38ff6d83eff40719f5d4209a81fb84ba45dd46be522ab461",
        "training_runs": 24, "late_continuations": 48, "evaluation_cells": 120,
        "raw_prediction_rows": 960_000, "step120_primary": True, "step100_descriptive": True,
        "seed_population_inference": False, "controller_fitting": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_new(V03_COMPLETION, receipt)
    return receipt


def main() -> int:
    if "--preflight" in sys.argv[1:]:
        require(not V03_PREFLIGHT.exists() and not EVAL_V03.exists(), "Q-R2 v03 output/receipt already exists")
        receipt = preflight()
        write_new(V03_PREFLIGHT, receipt)
        print(json.dumps(receipt, indent=2))
        return 0
    require(V03_PREFLIGHT.is_file() and not V03_EXECUTION.exists() and not V03_COMPLETION.exists()
            and not EVAL_V03.exists(), "Q-R2 v03 continuation is not at its sealed preflight boundary")
    pre = json.loads(V03_PREFLIGHT.read_text(encoding="utf-8"))
    require(pre.get("status") == "Q_R2_SAME_OPENING_STATE_HASH_PREFLIGHT_PASS_NO_INFERENCE"
            and pre.get("previous_attempt", {}).get("opening_count") == 1,
            "Q-R2 v03 state-hash preflight receipt mismatch")
    write_new(V03_EXECUTION, {"identity": "JEV-V08Q-R2-CHECKPOINT-STATE-HASH-CORRECTION-V03",
        "status": "Q_R2_CONTINUING_WITHIN_EXISTING_SINGLE_OPENING",
        "preflight_sha256": sha(V03_PREFLIGHT), "adapter_sha256": sha(Path(__file__).resolve()),
        "original_opening_receipt_sha256": EXPECTED_ORIGINAL_OPENING_SHA256,
        "additional_unlock": False, "opening_count": 1,
        "checkpoint_state_hash_source_sha256": EXPECTED_TRAINER_SHA256,
        "prediction_rows_before_execution": 0, "analysis_contract_unchanged": True})
    prior, evaluator, analyzer, replay, trainer = load_bundle()
    evaluator.INSTRUMENT_RECEIPT = evaluator.verify_instrument_package()
    try:
        evaluator.main()
        require((EVAL_V03 / "inference-receipt-v01.json").is_file(), "complete R2 raw prediction matrix missing")
        analyzer.main()
        replay_result = replay.verify()
        require(replay_result.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS",
                f"independent result replay failed: {replay_result}")
        write_new(EVAL_V03 / "independent-replay-verification-v01.json", replay_result)
        completion = seal_completion(replay_result)
        print(json.dumps({"status": completion["status"], "artifact_root_sha256": completion["artifact_root_sha256"],
            "completion_seal_sha256": sha(V03_COMPLETION), "opening_count": 1,
            "independent_replay": replay_result["status"], "result_path": str(EVAL_V03 / "q-r2-results-v01.md")},
            indent=2), flush=True)
        return 0
    except BaseException as exc:
        failure = PROVENANCE / "q-r2-evaluation-correction-failure-v03.json"
        if not failure.exists():
            write_new(failure, {"identity": "JEV-V08Q-R2-CHECKPOINT-STATE-HASH-CORRECTION-FAILURE-V03",
                "status": "Q_R2_EVALUATION_FAILED_CLOSED_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "opening_count": 1, "additional_unlock": False,
                "prediction_file_bytes": (EVAL_V03 / "raw-predictions-v01.jsonl").stat().st_size
                    if (EVAL_V03 / "raw-predictions-v01.jsonl").exists() else None,
                "automatic_retry": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
