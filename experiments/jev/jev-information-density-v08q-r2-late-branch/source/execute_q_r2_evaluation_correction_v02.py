"""Continue the single authorized R2 opening after a terminal-seal join defect.

The first evaluation invocation wrote the sole opening receipt and failed
before head deserialization/prediction because the terminal panel seal did not
duplicate a feature-cache root already bound by the feature-seal entry.  This
adapter reconstructs that root from the bound feature seal and continues under
the same logical opening, preserving the failed output unchanged.
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
PROVENANCE = RUN / "provenance"
V01_ADAPTER = SOURCE / "execute_q_r2_evaluation_training-v03_adapter_v01.py"
V01_PREFLIGHT = PROVENANCE / "q-r2-evaluation-routing-preflight-v01.json"
V01_OUTER_FAILURE = PROVENANCE / "q-r2-evaluation-routing-failure-v01.json"
V01_EVAL_FAILURE = EVAL_V01 / "evaluation-failure-receipt-v01.json"
V02_PREFLIGHT = PROVENANCE / "q-r2-evaluation-correction-preflight-v02.json"
V02_EXECUTION = PROVENANCE / "q-r2-evaluation-correction-execution-v02.json"
V02_FAILURE = PROVENANCE / "q-r2-evaluation-correction-failure-v02.json"
V02_COMPLETION = PROVENANCE / "q-r2-completion-seal-v03.json"
EXPECTED_V01_ADAPTER_SHA256 = "e20ff7cf064dd3de80c97ef8cc4c0492284b90daac3665b6ef24a85bcc15ed75"
EXPECTED_V01_PREFLIGHT_SHA256 = "b6d2f729e07962a3400d0ee9c5e95cc34282f68aaa42d03085a2e12343060af1"
EXPECTED_V01_OUTER_FAILURE_SHA256 = "0d635ca166eaaaab476a94fc45c955b16b0beeca3f5e9862b34cd8fe3b9d8ce7"
EXPECTED_V01_EVAL_FAILURE_SHA256 = "50cb05ba7ea01dc0259bd88e753122b1be28caaf4121b46ce765a23720f690a2"
EXPECTED_FEATURE_SEAL_SHA256 = "538c136b358a4c55e5e0cab9546c9285cdc59ee8f3bf4adf01b3b253c3b8580f"
EXPECTED_PANEL_TERMINAL_SHA256 = "7b9b36c0fb39ff67b9b02c29034027bb5c1c238699c2a5f07799e8f29e8fb50c"
EXPECTED_TRAINING_SEAL_SHA256 = "02c07a097e92cc37eca024ba44a2d9806409db012f9b0e59914a12c4506a1b84"


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


def verify_incident_and_binding() -> dict[str, Any]:
    require(sha(V01_ADAPTER) == EXPECTED_V01_ADAPTER_SHA256, "v01 evaluation routing adapter changed")
    require(V01_PREFLIGHT.is_file() and sha(V01_PREFLIGHT) == EXPECTED_V01_PREFLIGHT_SHA256,
            "v01 no-inference preflight receipt missing or changed")
    preflight_receipt = json.loads(V01_PREFLIGHT.read_text(encoding="utf-8"))
    require(preflight_receipt.get("status") == "Q_R2_EVALUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION"
            and preflight_receipt.get("head_deserialization") is False
            and preflight_receipt.get("inference") is False,
            "v01 evaluator preflight overstates model contact")
    require(V01_OUTER_FAILURE.is_file() and V01_EVAL_FAILURE.is_file(), "first evaluation failure provenance missing")
    require(sha(V01_OUTER_FAILURE) == EXPECTED_V01_OUTER_FAILURE_SHA256
            and sha(V01_EVAL_FAILURE) == EXPECTED_V01_EVAL_FAILURE_SHA256,
            "first opening failure receipts changed")
    outer = json.loads(V01_OUTER_FAILURE.read_text(encoding="utf-8"))
    inner = json.loads(V01_EVAL_FAILURE.read_text(encoding="utf-8"))
    opening_path = EVAL_V01 / "panel-opening-receipt-v01.json"
    require(outer.get("status") == "Q_R2_EVALUATION_FAILED_CLOSED_ARTIFACTS_PRESERVED"
            and outer.get("panel_opened") is True
            and inner.get("status") == "Q_R2_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED"
            and inner.get("stage") == "panel_materialization_and_join_validation"
            and inner.get("exception") == "'feature_cache_root_sha256'"
            and opening_path.is_file(), "first opening failure is not the expected pre-inference defect")
    opening = json.loads(opening_path.read_text(encoding="utf-8"))
    require(opening.get("status") == "Q_R2_FRESH_PANEL_OPENED_ONCE_AFTER_COMPLETE_TRAINING_SEAL"
            and opening.get("opening_count") == 1
            and opening.get("training_seal_sha256") == EXPECTED_TRAINING_SEAL_SHA256,
            "the single existing panel opening receipt is invalid")
    terminal_path = PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"
    feature_path = PANEL / "seals/q-r2-feature-cache-seal-v01.json"
    require(sha(terminal_path) == EXPECTED_PANEL_TERMINAL_SHA256
            and sha(feature_path) == EXPECTED_FEATURE_SEAL_SHA256,
            "bound panel/feature seal bytes changed")
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    terminal_entry = {row["path"]: row for row in terminal["entries"]}.get("seals/q-r2-feature-cache-seal-v01.json")
    require(terminal_entry is not None and terminal_entry["sha256"] == sha(feature_path)
            and feature.get("status") == "Q_R2_FEATURE_CACHE_SEALED"
            and feature.get("root_sha256") == "dcd67dbc3360df555575b7b4f6048f071c0478918030c2fb12d5d25c2b0f3314",
            "feature-cache root is not uniquely bound by the terminal panel seal")
    feature_entries = feature.get("entries", [])
    terminal_entries = {row["path"]: row["sha256"] for row in terminal["entries"]}
    require(all(terminal_entries.get(row["path"]) == row["sha256"] for row in feature_entries),
            "feature-cache child entries do not match terminal panel entries")
    expected_feature_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(feature_entries, key=lambda item: item["path"])).encode()).hexdigest()
    require(feature.get("root_sha256") == expected_feature_root and "feature_cache_root_sha256" not in terminal,
            "feature-cache root reconstruction is ambiguous or already altered")
    require(not EVAL_V02.exists() and not V02_PREFLIGHT.exists() and not V02_EXECUTION.exists()
            and not V02_COMPLETION.exists(), "refusing to reuse evaluation-v02 namespace/receipts")
    return {"first_opening_receipt_sha256": sha(opening_path),
            "first_outer_failure_sha256": sha(V01_OUTER_FAILURE),
            "first_evaluator_failure_sha256": sha(V01_EVAL_FAILURE),
            "panel_terminal_seal_sha256": sha(terminal_path),
            "feature_cache_seal_sha256": sha(feature_path),
            "feature_cache_root_sha256": feature["root_sha256"],
            "feature_child_entries_verified": len(feature_entries),
            "panel_opening_count_before_continuation": 1,
            "heads_loaded_in_failed_attempt": False,
            "predictions_in_failed_attempt": False,
            "metrics_in_failed_attempt": False}


def configure_v01_adapter(adapter: Any, eval_output: Path) -> tuple[Any, Any, Any]:
    evaluator = load(adapter.EVALUATOR_PATH, "q_r2_evaluator_same_opening_v02")
    analyzer = load(adapter.ANALYZER_PATH, "q_r2_analyzer_same_opening_v02")
    replay = load(adapter.REPLAY_PATH, "q_r2_replay_same_opening_v02")
    adapter.configure_evaluator(evaluator)
    evaluator.OUTPUT = eval_output
    original_read_json = evaluator.read_json
    original_write_json = evaluator.write_json
    terminal_path = evaluator.PANEL_SEAL
    feature_path = evaluator.PANEL / "seals/q-r2-feature-cache-seal-v01.json"
    feature = json.loads(feature_path.read_text(encoding="utf-8"))

    def repaired_read_json(path: Path) -> Any:
        value = original_read_json(path)
        if Path(path).resolve() == terminal_path.resolve():
            require(sha(path) == EXPECTED_PANEL_TERMINAL_SHA256 and sha(feature_path) == EXPECTED_FEATURE_SEAL_SHA256,
                    "sealed panel/feature receipt changed before reconstruction")
            value = dict(value)
            value["feature_cache_root_sha256"] = feature["root_sha256"]
        return value

    def opening_writer(path: Path, value: Any) -> None:
        if Path(path).name == "panel-opening-receipt-v01.json":
            old_opening = EVAL_V01 / "panel-opening-receipt-v01.json"
            require(value.get("panel_root_sha256") == json.loads(old_opening.read_text(encoding="utf-8"))["panel_root_sha256"],
                    "continuation attempted to change panel identity")
            require(not Path(path).exists(), "unexpected duplicate panel-opening receipt in continuation output")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(old_opening.read_bytes())
            return
        original_write_json(path, value)

    evaluator.read_json = repaired_read_json
    evaluator.write_json = opening_writer
    adapter.configure_analyzer(analyzer)
    analyzer.OUTPUT = eval_output
    adapter.configure_replay(replay)
    replay.TRAIN = TRAIN_V03
    replay.EVAL = eval_output
    replay.RECEIPT = eval_output / "independent-replay-verification-v01.json"
    return evaluator, analyzer, replay


def preflight() -> dict[str, Any]:
    incident = verify_incident_and_binding()
    adapter = load(V01_ADAPTER, "q_r2_evaluation_v01_adapter_for_v02")
    evaluator, _, _ = configure_v01_adapter(adapter, EVAL_V02)
    evaluator.INSTRUMENT_RECEIPT = evaluator.verify_instrument_package()
    packet = evaluator.verify_packet()
    train_seal, checkpoint_lookup = evaluator.verify_training()
    panel = evaluator.verify_panel_seal()
    require(len(checkpoint_lookup) == 120 and train_seal.get("evaluation_panel_opened") is False,
            "continuation checkpoint matrix/training firewall mismatch")
    return {"identity": "JEV-V08Q-R2-EVALUATION-CONTINUATION-CORRECTION-V02",
            "status": "Q_R2_SAME_OPENING_CONTINUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION",
            "incident": incident, "packet": packet, "panel": panel,
            "checkpoint_cells": len(checkpoint_lookup), "output_namespace": str(EVAL_V02),
            "logical_panel_opening_count": 1, "second_unlock": False,
            "head_deserialization": False, "inference": False, "predictions": False, "metrics": False,
            "repair": "reconstruct feature_cache_root_sha256 from the exact feature-cache seal whose hash and child entries are already bound by the immutable panel terminal seal"}


def build_completion(replay_result: dict[str, Any]) -> dict[str, Any]:
    paths = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        PROVENANCE / "q-r2-instrument-package-seal-v01.json",
        PANEL / "seals/q-r2-panel-construction-seal-v01.json",
        PANEL / "seals/q-r2-feature-cache-seal-v01.json",
        PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
        SCHEDULE / "schedule-seal.json",
        TRAIN_V03 / "common-prefix-seal-v01.json",
        TRAIN_V03 / "checkpoint-hash-tree.json",
        TRAIN_V03 / "training-seal-manifest.json",
        PROVENANCE / "q-r2-training-input-correction-preflight-v01.json",
        PROVENANCE / "q-r2-device-correction-preflight-v02b.json",
        PROVENANCE / "q-r2-path-correction-preflight-v03b.json",
        PROVENANCE / "q-r2-path-correction-completion-v03.json",
        V01_ADAPTER, V01_PREFLIGHT, V01_OUTER_FAILURE, V01_EVAL_FAILURE,
        EVAL_V01 / "panel-opening-receipt-v01.json",
        V02_PREFLIGHT, V02_EXECUTION,
        EVAL_V02 / "panel-opening-receipt-v01.json",
        EVAL_V02 / "raw-prediction-hash-tree-v01.json",
        EVAL_V02 / "inference-receipt-v01.json",
        EVAL_V02 / "q-r2-analysis-seal-v01.json",
        EVAL_V02 / "independent-replay-verification-v01.json",
        EVAL_V02 / "raw-predictions-v01.jsonl",
        EVAL_V02 / "neighborhood-metrics-v01.jsonl",
        EVAL_V02 / "shared-neighborhood-bootstrap-plan-v01.npy",
        EVAL_V02 / "shared-moderator-seed-resample-plan-v01.npy",
        EVAL_V02 / "q-r2-analysis-v01.json",
        EVAL_V02 / "q-r2-results-v01.md",
    ]
    rows = []
    for path in paths:
        require(path.is_file(), f"R2 terminal file missing: {path}")
        rows.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    require(len({row["path"] for row in rows}) == len(rows), "duplicate file in R2 v03 terminal root")
    root_payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(rows, key=lambda item: item["path"]))
    root = hashlib.sha256(root_payload.encode()).hexdigest()
    receipt = {"status": "Q_R2_COMPLETE_RESULT_SEALED", "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
        "evaluation_namespace": str(EVAL_V02),
        "opening_count": 1,
        "opening_continuation": {"same_original_opening_receipt_sha256": sha(EVAL_V01 / "panel-opening-receipt-v01.json"),
            "second_unlock": False, "second_opening": False,
            "reason": "first authorized opening stopped before head deserialization/prediction; deterministic execution continued with the same sealed panel and original opening receipt"},
        "correction": {"identity": "Q-R2-FEATURE-CACHE-ROOT-BINDING-RECONSTRUCTION-V02",
            "adapter_sha256": sha(Path(__file__).resolve()),
            "scientific_contracts_changed": False, "metric_implementation_changed": False,
            "feature_cache_root_sha256": "dcd67dbc3360df555575b7b4f6048f071c0478918030c2fb12d5d25c2b0f3314"},
        "independent_replay_status": replay_result["status"],
        "artifact_root_sha256": root, "artifact_count": len(rows), "artifacts": rows,
        "training_checkpoint_tree_root_sha256": "db75e29c1ec0295d38ff6d83eff40719f5d4209a81fb84ba45dd46be522ab461",
        "training_runs": 24, "late_continuations": 48, "evaluation_cells": 120,
        "raw_prediction_rows": 960_000, "step120_primary": True, "step100_descriptive": True,
        "seed_population_inference": False, "controller_fitting": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_new(V02_COMPLETION, receipt)
    return receipt


def main() -> int:
    if "--preflight" in sys.argv[1:]:
        require(not V02_PREFLIGHT.exists() and not EVAL_V02.exists(), "v02 output/receipt already exists")
        result = preflight()
        write_new(V02_PREFLIGHT, result)
        print(json.dumps(result, indent=2))
        return 0
    require(V02_PREFLIGHT.is_file(), "R2 v02 evaluation continuation preflight missing")
    require(not V02_EXECUTION.exists() and not V02_COMPLETION.exists() and not EVAL_V02.exists(),
            "R2 v02 evaluation continuation already started")
    pre = json.loads(V02_PREFLIGHT.read_text(encoding="utf-8"))
    require(pre.get("status") == "Q_R2_SAME_OPENING_CONTINUATION_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION"
            and pre.get("incident", {}).get("first_opening_receipt_sha256") == sha(EVAL_V01 / "panel-opening-receipt-v01.json"),
            "R2 v02 preflight/opening binding mismatch")
    write_new(V02_EXECUTION, {"identity": "JEV-V08Q-R2-EVALUATION-CONTINUATION-CORRECTION-V02",
        "status": "Q_R2_CONTINUING_WITHIN_EXISTING_SINGLE_OPENING",
        "preflight_sha256": sha(V02_PREFLIGHT), "adapter_sha256": sha(Path(__file__).resolve()),
        "existing_opening_receipt_sha256": sha(EVAL_V01 / "panel-opening-receipt-v01.json"),
        "panel_open_count_before_continuation": 1, "additional_unlock": False,
        "head_loading": True, "inference": True, "analysis_contract_unchanged": True})
    adapter = load(V01_ADAPTER, "q_r2_evaluation_v01_adapter_for_v02_execution")
    evaluator, analyzer, replay = configure_v01_adapter(adapter, EVAL_V02)
    evaluator.INSTRUMENT_RECEIPT = evaluator.verify_instrument_package()
    try:
        evaluator.main()
        require((EVAL_V02 / "inference-receipt-v01.json").is_file(), "complete raw prediction matrix not sealed")
        analyzer.main()
        replay_result = replay.verify()
        require(replay_result.get("status") == "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS",
                f"independent replay failed: {replay_result}")
        write_new(EVAL_V02 / "independent-replay-verification-v01.json", replay_result)
        completion = build_completion(replay_result)
        print(json.dumps({"status": completion["status"], "artifact_root_sha256": completion["artifact_root_sha256"],
            "completion_seal_sha256": sha(V02_COMPLETION), "opening_count": 1,
            "second_unlock": False, "independent_replay": replay_result["status"],
            "result_path": str(EVAL_V02 / "q-r2-results-v01.md")}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if not V02_FAILURE.exists():
            write_new(V02_FAILURE, {"identity": "JEV-V08Q-R2-EVALUATION-CONTINUATION-FAILURE-V02",
                "status": "Q_R2_EVALUATION_FAILED_CLOSED_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "opening_count": 1, "additional_unlock": False,
                "panel_opening_receipt_exists": (EVAL_V02 / "panel-opening-receipt-v01.json").exists(),
                "predictions_exist": (EVAL_V02 / "raw-predictions-v01.jsonl").exists(),
                "automatic_retry": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
