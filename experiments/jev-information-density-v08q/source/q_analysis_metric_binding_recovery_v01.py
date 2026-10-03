"""Bind the frozen Q neighborhood metric to its authoritative sealed source."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
OUTPUT = RUN / "evaluation-continuation-v01"
PACKET = RUN / "q-full-execution-packet-v05.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v05.json"
PRED_TREE = OUTPUT / "raw-prediction-hash-tree-v01.json"
INFERENCE = OUTPUT / "inference-receipt-v01.json"
ANALYSIS = Q / "source/analyze_q_results_v05.py"
ANALYSIS_PREFLIGHT = RUN / "q-analysis-binding-recovery-preflight-v01.json"
ANALYSIS_COMPLETION = RUN / "q-analysis-binding-recovery-completion-v01.json"
VERIFY_RECEIPT = RUN / "q-evaluation-recovery-independent-verification-v01.json"
EXPECTED = {
    "packet": "bd263ce025146b9c57c8eebabd46336c28d6367078d153ec145b68ca7e9c177c",
    "packet_seal": "35279fddacabb4fae94a7e3f4400682e25721f03638c1a2282f5700532f21081",
    "evaluator": "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4",
    "neighborhood_metric": "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot import frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate() -> None:
    need(sha(PACKET) == EXPECTED["packet"] and sha(PACKET_SEAL) == EXPECTED["packet_seal"],
         "sealed Q execution packet identity changed")
    packet = read_json(PACKET)
    bindings = {row["path"]: row["sha256"] for row in packet["implementation_bindings"]}
    evaluator_path = ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py"
    metric_path = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
    need(bindings.get("experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py") == EXPECTED["evaluator"]
         and sha(evaluator_path) == EXPECTED["evaluator"], "sealed Q inference-metric source mismatch")
    need(bindings.get("experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py") == EXPECTED["neighborhood_metric"]
         and sha(metric_path) == EXPECTED["neighborhood_metric"], "sealed Q neighborhood-metric source mismatch")
    need(sha(ANALYSIS) == next(row["sha256"] for row in packet["implementation_bindings"]
                               if row["path"] == "experiments/jev-information-density-v08q/source/analyze_q_results_v05.py"),
         "frozen Q analysis implementation changed")
    tree = read_json(PRED_TREE)
    inference = read_json(INFERENCE)
    prediction = OUTPUT / "raw-predictions-v01.jsonl"
    need(tree.get("status") == "Q_COMPLETE_408000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS"
         and tree.get("execution_packet_sha256") == EXPECTED["packet"]
         and tree.get("prediction_rows") == 408_000 and tree.get("panel_open_count") == 1
         and sha(prediction) == tree.get("raw_predictions", {}).get("sha256"),
         "sealed Q prediction tree invalid")
    need(inference.get("status") == "Q_ALL_51_CELLS_INFERRED_AND_SEALED"
         and inference.get("prediction_sha256") == sha(prediction)
         and inference.get("panel_open_count") == 1,
         "Q inference receipt does not match the sealed predictions")
    failure_path = OUTPUT / "analysis-failure-receipt-v01.json"
    failure = read_json(failure_path)
    need(failure.get("status") == "Q_ANALYSIS_FAILED_CLOSED_PARTIAL_OUTPUTS_PRESERVED"
         and failure.get("stage") == "prediction_seal_preflight"
         and failure.get("exception") == "Q frozen metric implementation hash mismatch",
         "analysis failure is not the expected pre-metric binding typo")
    forbidden = ("neighborhood-metrics-v01.jsonl", "shared-bootstrap-resample-plan-v01.npy",
                 "q-response-analysis-v01.json", "q-analysis-seal-v01.json")
    need(not any((OUTPUT / name).exists() for name in forbidden),
         "analysis outputs already exist; refusing to reuse or overwrite")
    need(not ANALYSIS_PREFLIGHT.exists() and not ANALYSIS_COMPLETION.exists(),
         "Q analysis correction receipt already exists")
    receipt = {"status": "Q_ANALYSIS_METRIC_BINDING_PREFLIGHT_PASS",
               "adapter_sha256": sha(Path(__file__).resolve()),
               "execution_packet_sha256": EXPECTED["packet"],
               "frozen_analysis_sha256": sha(ANALYSIS),
               "authoritative_metric_path": str(metric_path),
               "authoritative_metric_sha256": EXPECTED["neighborhood_metric"],
               "separate_evaluator_metric_path": str(evaluator_path),
               "separate_evaluator_metric_sha256": EXPECTED["evaluator"],
               "prediction_sha256": sha(prediction), "prediction_rows": 408_000,
               "metric_rows_written_before_failure": False, "behavioral_values_read_by_preflight": False,
               "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(ANALYSIS_PREFLIGHT, receipt)
    print(json.dumps(receipt, indent=2))


def analyze() -> None:
    preflight = read_json(ANALYSIS_PREFLIGHT)
    need(preflight.get("status") == "Q_ANALYSIS_METRIC_BINDING_PREFLIGHT_PASS"
         and preflight.get("adapter_sha256") == sha(Path(__file__).resolve()),
         "Q analysis binding preflight/adapter mismatch")
    module = load_module(ANALYSIS, "q_analysis_frozen_v05_binding_recovery")
    module.OUTPUT = OUTPUT
    # The frozen constant points to evaluate_phase_b_v01.py, but this call and
    # result field refer to analyze_phase_b_v01.py. Both are packet-bound.
    module.ANALYZER_SHA = EXPECTED["neighborhood_metric"]
    status = int(module.main())
    if status != 0:
        raise RuntimeError(f"frozen Q analysis failed with status {status}")
    seal_path = OUTPUT / "q-analysis-seal-v01.json"
    seal = read_json(seal_path)
    result = read_json(OUTPUT / "q-response-analysis-v01.json")
    need(seal.get("status") == "Q_ANALYSIS_OUTPUTS_SEALED"
         and seal.get("panel_open_count") == 1
         and seal.get("metric_implementation_sha256") == EXPECTED["neighborhood_metric"]
         and result.get("metric_implementation_sha256") == EXPECTED["neighborhood_metric"],
         "frozen Q analysis output seal/metric source identity mismatch")
    write_json(ANALYSIS_COMPLETION, {
        "status": "Q_FROZEN_ANALYSIS_COMPLETE_WITH_CORRECT_PACKET_BOUND_METRIC_IDENTITY",
        "adapter_sha256": sha(Path(__file__).resolve()),
        "analysis_seal_sha256": sha(seal_path),
        "analysis_root_sha256": seal["analysis_root_sha256"],
        "raw_prediction_sha256": sha(OUTPUT / "raw-predictions-v01.jsonl"),
        "metric_implementation_sha256": EXPECTED["neighborhood_metric"],
        "panel_open_count": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
    })


def verify() -> None:
    need(read_json(ANALYSIS_COMPLETION).get("status") ==
         "Q_FROZEN_ANALYSIS_COMPLETE_WITH_CORRECT_PACKET_BOUND_METRIC_IDENTITY",
         "Q analysis is not sealed")
    module = load_module(Q / "source/verify_q_full_execution_v05.py", "q_verify_frozen_v05_metric_recovery")
    module.EVAL = OUTPUT
    module.RECEIPT = VERIFY_RECEIPT
    status = int(module.main())
    if status != 0:
        raise RuntimeError(f"independent Q verification failed with status {status}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: q_analysis_metric_binding_recovery_v01.py {preflight|analyze|verify}")
    stage = sys.argv[1]
    actions = {"preflight": validate, "analyze": analyze, "verify": verify}
    if stage not in actions:
        raise SystemExit(f"unknown stage: {stage}")
    actions[stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
