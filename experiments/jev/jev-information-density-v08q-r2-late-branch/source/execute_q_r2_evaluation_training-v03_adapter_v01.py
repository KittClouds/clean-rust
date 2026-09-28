"""Run the authorized Q-R2 evaluation against the corrected v03 training root.

The frozen evaluator/analysis/replay implementations remain byte-identical.
This adapter only routes their training-root lookup from the empty/failed v01
namespace to the fully sealed v03 namespace and the already-sealed v01 schedule.
It performs a no-inference preflight, then runs the one authorized opening,
all predictions, frozen analysis, independent replay, and terminal sealing.
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
PROVENANCE = RUN / "provenance"
EVAL = RUN / "evaluation-v01"
PREFLIGHT = PROVENANCE / "q-r2-evaluation-routing-preflight-v01.json"
EXECUTION = PROVENANCE / "q-r2-evaluation-routing-execution-v01.json"
FAILURE = PROVENANCE / "q-r2-evaluation-routing-failure-v01.json"
COMPLETION = PROVENANCE / "q-r2-completion-seal-v02.json"
EVALUATOR_PATH = SOURCE / "evaluate_q_r2_panel_v01.py"
ANALYZER_PATH = SOURCE / "analyze_q_r2_results_v01.py"
REPLAY_PATH = SOURCE / "verify_q_r2_results_v01.py"
RUN_SHA = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
ANALYSIS_SHA = "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64"
PACKET_SHA = "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209"
PACKET_ROOT_SHA = "6b3b826fd3c861e1aa9114371f9db68c704fb9c5ad85e5c8c60a93afba527275"
EVALUATOR_SHA = "46ffe3f954dffdc684ed0e0b1623cb48bd67871f08f9c9960f21f3c2995d9b4b"
ANALYZER_SHA = "3f9a87fd059f7ada026a6b9913f6ffdeb1058327322779901422037db667038a"
REPLAY_SHA = "c51073d6ab32cb9a9d8a8c9051a5123b27c7f3840f4e8712f931c640c33ee521"
TRAINING_SEAL_SHA = "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84"
TRAINING_TREE_SHA = "9708a4388923021c9b5d14b0b8dd33868902de61f568a200432f89cfb4cbaa9f"
TRAINING_TREE_ROOT = "db75e29c1ec0295d38ff6d83eff40719f5d4209a81fb84ba45dd46be522ab461"
TRAINING_SEAL_STATUS = "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED"


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
    require(spec is not None and spec.loader is not None, f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def route_training_path(path: Path | str) -> Path:
    value = Path(path)
    try:
        schedule_relative = value.resolve().relative_to((TRAIN_V03 / "schedule").resolve())
    except ValueError:
        schedule_relative = None
    if schedule_relative is not None:
        return SCHEDULE / schedule_relative
    try:
        relative = value.resolve().relative_to(TRAIN_V01.resolve())
    except ValueError:
        return value
    if relative.parts and relative.parts[0] == "schedule":
        return SCHEDULE.joinpath(*relative.parts[1:])
    return TRAIN_V03 / relative


def configure_evaluator(module: Any) -> None:
    module.TRAIN = TRAIN_V03
    original_sha = module.sha
    module.sha = lambda path: original_sha(route_training_path(path))


def configure_analyzer(module: Any) -> None:
    original_sha = module.sha
    original_read_json = module.read_json
    module.sha = lambda path: original_sha(route_training_path(path))
    module.read_json = lambda path: original_read_json(route_training_path(path))


def configure_replay(module: Any) -> None:
    module.TRAIN = TRAIN_V03


def verify_frozen_sources() -> dict[str, str]:
    observed = {"evaluator": sha(EVALUATOR_PATH), "analyzer": sha(ANALYZER_PATH), "replay": sha(REPLAY_PATH)}
    expected = {"evaluator": EVALUATOR_SHA, "analyzer": ANALYZER_SHA, "replay": REPLAY_SHA}
    require(observed == expected, f"frozen analysis/evaluation source hash mismatch: {observed}")
    return observed


def verify_training_bindings() -> dict[str, Any]:
    seal_path = TRAIN_V03 / "training-seal-manifest.json"
    tree_path = TRAIN_V03 / "checkpoint-hash-tree.json"
    require(sha(seal_path) == TRAINING_SEAL_SHA and sha(tree_path) == TRAINING_TREE_SHA,
            "v03 training root no longer matches sealed completion")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    require(seal.get("status") == TRAINING_SEAL_STATUS and seal.get("trained_checkpoint_count") == 120
            and seal.get("seed_count") == 24 and seal.get("continuation_count") == 48
            and seal.get("evaluation_panel_opened") is False and seal.get("training_panel_feedback") is False,
            "v03 training seal status/count/firewall mismatch")
    require(seal.get("run_contract_sha256") == RUN_SHA and seal.get("analysis_contract_sha256") == ANALYSIS_SHA
            and seal.get("packet_sha256") == PACKET_SHA and seal.get("packet_bundle_root_sha256") == PACKET_ROOT_SHA,
            "v03 training contract parent identity mismatch")
    require(tree.get("entries_root_sha256") == TRAINING_TREE_ROOT and tree.get("trained_checkpoint_count") == 120
            and len(tree.get("entries", [])) == tree.get("entry_count"), "v03 checkpoint tree identity mismatch")
    return {"training_seal_sha256": sha(seal_path), "checkpoint_tree_sha256": sha(tree_path),
            "checkpoint_tree_root_sha256": tree["entries_root_sha256"], "trained_checkpoint_count": 120}


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def preflight() -> dict[str, Any]:
    require(not EVAL.exists(), "evaluation-v01 already exists; refusing a second panel opening")
    require(not PREFLIGHT.exists() and not COMPLETION.exists(), "evaluation routing receipt already exists")
    sources = verify_frozen_sources()
    training = verify_training_bindings()
    evaluator = load(EVALUATOR_PATH, "q_r2_evaluator_training_v03_route_preflight")
    configure_evaluator(evaluator)
    evaluator.INSTRUMENT_RECEIPT = evaluator.verify_instrument_package()
    packet = evaluator.verify_packet()
    training_seal, checkpoint_lookup = evaluator.verify_training()
    panel = evaluator.verify_panel_seal()
    require(len(checkpoint_lookup) == 120 and training_seal["evaluation_panel_opened"] is False,
            "non-inference evaluator binding check incomplete")
    return {"identity": "JEV-V08Q-R2-EVALUATION-TRAINING-V03-ROUTING-CORRECTION-V01",
            "status": "Q_R2_EVALUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION",
            "frozen_sources": sources, "training": training, "packet": packet, "panel": panel,
            "checkpoint_cells": len(checkpoint_lookup), "training_path_routing": {
                "checkpoint_and_receipt_root": str(TRAIN_V03), "schedule_root": str(SCHEDULE)},
            "panel_opening_receipt_exists": False, "head_deserialization": False,
            "inference": False, "predictions": False, "metrics": False}


def create_terminal_seal(replay_receipt: dict[str, Any]) -> dict[str, Any]:
    panel_seal = RUN / "panel-v01/seals/q-r2-panel-input-terminal-seal-v01.json"
    artifacts = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        PROVENANCE / "q-r2-instrument-package-seal-v01.json",
        RUN / "panel-v01/seals/q-r2-panel-construction-seal-v01.json",
        RUN / "panel-v01/seals/q-r2-feature-cache-seal-v01.json",
        panel_seal,
        SCHEDULE / "schedule-seal.json",
        TRAIN_V03 / "common-prefix-seal-v01.json",
        TRAIN_V03 / "checkpoint-hash-tree.json",
        TRAIN_V03 / "training-seal-manifest.json",
        PROVENANCE / "q-r2-training-input-correction-preflight-v01.json",
        PROVENANCE / "q-r2-device-correction-preflight-v02b.json",
        PROVENANCE / "q-r2-path-correction-preflight-v03b.json",
        PROVENANCE / "q-r2-path-correction-completion-v03.json",
        PREFLIGHT, EXECUTION,
        EVAL / "panel-opening-receipt-v01.json",
        EVAL / "raw-prediction-hash-tree-v01.json",
        EVAL / "inference-receipt-v01.json",
        EVAL / "q-r2-analysis-seal-v01.json",
        EVAL / "independent-replay-verification-v01.json",
        EVAL / "raw-predictions-v01.jsonl",
        EVAL / "neighborhood-metrics-v01.jsonl",
        EVAL / "shared-neighborhood-bootstrap-plan-v01.npy",
        EVAL / "shared-moderator-seed-resample-plan-v01.npy",
        EVAL / "q-r2-analysis-v01.json",
        EVAL / "q-r2-results-v01.md",
    ]
    rows = []
    for path in artifacts:
        require(path.is_file(), f"terminal artifact missing: {path}")
        rows.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    require(len({row["path"] for row in rows}) == len(rows), "duplicate path in terminal artifact tree")
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(rows, key=lambda item: item["path"]))
    root = hashlib.sha256(body.encode("utf-8")).hexdigest()
    receipt = {"status": "Q_R2_COMPLETE_RESULT_SEALED", "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
        "execution_adapter": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).resolve()),
            "purpose": "route frozen evaluator/analysis/replay training reads to the corrected sealed v03 training root and v01 schedule"},
        "authorization_packet_sha256": PACKET_SHA, "contract_bundle_root_sha256": PACKET_ROOT_SHA,
        "independent_replay_status": replay_receipt["status"],
        "independent_replay_receipt_sha256": sha(EVAL / "independent-replay-verification-v01.json"),
        "artifact_root_sha256": root, "artifact_count": len(rows), "artifacts": rows,
        "training_root": str(TRAIN_V03), "training_checkpoint_tree_root_sha256": TRAINING_TREE_ROOT,
        "panel_open_count": 1, "training_runs": 24, "late_continuations": 48,
        "evaluation_cells": 120, "raw_prediction_rows": 960_000,
        "step120_primary": True, "step100_descriptive": True,
        "seed_population_inference": False, "controller_fitting": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_new(COMPLETION, receipt)
    return receipt


def execute() -> int:
    if PREFLIGHT.exists():
        require(not EXECUTION.exists() and not COMPLETION.exists(), "evaluation execution already recorded")
        bound = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
        require(bound.get("status") == "Q_R2_EVALUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION"
                and bound.get("frozen_sources") == verify_frozen_sources()
                and bound.get("training", {}).get("training_seal_sha256") == sha(TRAIN_V03 / "training-seal-manifest.json"),
                "evaluation preflight receipt stale or mismatched")
    else:
        value = preflight()
        write_new(PREFLIGHT, value)
        print(json.dumps(value, indent=2), flush=True)
        return 0

    evaluation = load(EVALUATOR_PATH, "q_r2_evaluator_training_v03_route")
    configure_evaluator(evaluation)
    write_new(EXECUTION, {"identity": "JEV-V08Q-R2-EVALUATION-TRAINING-V03-ROUTING-CORRECTION-V01",
        "status": "Q_R2_EVALUATION_EXECUTION_STARTED_SINGLE_AUTHORIZED_OPENING",
        "preflight_sha256": sha(PREFLIGHT), "adapter_sha256": sha(Path(__file__).resolve()),
        "training_seal_sha256": sha(TRAIN_V03 / "training-seal-manifest.json"),
        "checkpoint_tree_sha256": sha(TRAIN_V03 / "checkpoint-hash-tree.json"),
        "panel_open_count_before": 0, "head_loading_authorized": True,
        "inference_authorized": True, "analysis_contract_unchanged": True})
    try:
        evaluation.main()
        prediction_tree_path = EVAL / "raw-prediction-hash-tree-v01.json"
        inference_path = EVAL / "inference-receipt-v01.json"
        require(prediction_tree_path.is_file() and inference_path.is_file(), "frozen evaluator did not seal all raw predictions")

        analysis = load(ANALYZER_PATH, "q_r2_analyzer_training_v03_route")
        configure_analyzer(analysis)
        analysis.main()

        replay = load(REPLAY_PATH, "q_r2_independent_replay_training_v03_route")
        configure_replay(replay)
        replay_receipt = replay.verify()
        require(replay_receipt.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS",
                f"independent replay did not pass: {replay_receipt}")
        replay_path = EVAL / "independent-replay-verification-v01.json"
        write_new(replay_path, replay_receipt)
        terminal = create_terminal_seal(replay_receipt)
        print(json.dumps({"status": terminal["status"], "artifact_root_sha256": terminal["artifact_root_sha256"],
            "completion_seal_sha256": sha(COMPLETION), "independent_replay_status": replay_receipt["status"],
            "prediction_sha256": json.loads(prediction_tree_path.read_text(encoding="utf-8"))["raw_predictions"]["sha256"],
            "panel_open_count": 1}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if not FAILURE.exists():
            write_new(FAILURE, {"identity": "JEV-V08Q-R2-EVALUATION-TRAINING-ROOT-ROUTING-FAILURE-V01",
                "status": "Q_R2_EVALUATION_FAILED_CLOSED_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "panel_opening_receipt_exists": (EVAL / "panel-opening-receipt-v01.json").exists(),
                "panel_opened": (EVAL / "panel-opening-receipt-v01.json").exists(),
                "automatic_retry": False, "preflight_sha256": sha(PREFLIGHT),
                "execution_receipt_sha256": sha(EXECUTION)})
        raise


def main() -> int:
    if "--preflight" in sys.argv[1:]:
        value = preflight()
        write_new(PREFLIGHT, value)
        print(json.dumps(value, indent=2))
        return 0
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
