"""Resume the single authorized Q evaluation after a root-level join bug."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
ORIGINAL_EVAL = RUN / "evaluation"
CONTINUATION = RUN / "evaluation-continuation-v01"
PREFLIGHT = RUN / "q-evaluation-recovery-preflight-v01.json"
COMPLETION = RUN / "q-evaluation-recovery-completion-v01.json"
VERIFY_RECEIPT = RUN / "q-evaluation-recovery-independent-verification-v01.json"
PACKET = RUN / "q-full-execution-packet-v05.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v05.json"
TRAIN_SEAL = RUN / "training/training-seal-manifest.json"
CHECKPOINT_TREE = RUN / "training/checkpoint-hash-tree.json"
OPENING = ORIGINAL_EVAL / "panel-opening-receipt-v01.json"
INITIAL_FAILURE = ORIGINAL_EVAL / "evaluation-failure-receipt-v01.json"
FEATURE_RECEIPT = PANEL / "features/q-feature-extraction-receipt.json"
FEATURE_SEAL = PANEL / "seals/q-feature-cache-seal-v01.json"
PANEL_SEAL = PANEL / "seals/q-panel-phase-terminal-seal-v01.json"
CONTRACT = {
    "run": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
    "packet": "bd263ce025146b9c57c8eebabd46336c28d6367078d153ec145b68ca7e9c177c",
    "packet_seal": "35279fddacabb4fae94a7e3f4400682e25721f03638c1a2282f5700532f21081",
    "train_seal": "de350a3256d617747617657a59088344ef8e7ed24258725be8018e7ec5a195b8",
    "checkpoint_tree": "fba32f8e8e9833c19ec0d9037f54cccde2b5471ed1c891559a03aa34311bdcb7",
    "panel_root": "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6",
    "panel_seal": "161511e6617ee012b3051590b4a9ce747f79a85228c02649e61ca8a10d080ad6",
    "feature_receipt": "0040b7ab456c476a5163b27360573b134751a8bb94cae5169929653789d9088f",
    "feature_seal": "82ec9062983670c09973d98a32ba8f502692eeddbfe786f34bd8337da7d67542",
    "construction_root": "b9f77d7536c038964ac3fc77c52c495c04492ae443518a34f1c5e1efaf6ed2a2",
    "construction_seal": "e7fe0942d116979d3c41a0d80fdbe80e6eb44dd320d27608ff37d96c7c136ff3",
    "evaluator": "d629df1b12a3497ce3fd35e9dcb3718934a934834a534f4883f89759975abb33",
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
    path.parent.mkdir(parents=True, exist_ok=True)
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


def entries_root(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                    for row in sorted(entries, key=lambda item: item["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def verify_feature_root_hierarchy() -> dict[str, Any]:
    panel_seal = read_json(PANEL_SEAL)
    feature_seal = read_json(FEATURE_SEAL)
    feature = read_json(FEATURE_RECEIPT)
    terminal_entries = {row["path"]: row for row in panel_seal["entries"]}
    need(sha(PANEL_SEAL) == CONTRACT["panel_seal"]
         and panel_seal.get("root_sha256") == CONTRACT["panel_root"],
         "sealed terminal panel identity changed")
    need(sha(FEATURE_SEAL) == CONTRACT["feature_seal"]
         and terminal_entries.get("seals/q-feature-cache-seal-v01.json", {}).get("sha256") == CONTRACT["feature_seal"],
         "feature-cache seal is not bound by the terminal panel seal")
    need(sha(FEATURE_RECEIPT) == CONTRACT["feature_receipt"]
         and terminal_entries.get("features/q-feature-extraction-receipt.json", {}).get("sha256") == CONTRACT["feature_receipt"],
         "feature receipt is not bound by the terminal panel seal")
    need(feature.get("status") == "Q_FROZEN_PANEL_FEATURE_EXTRACTION_PASS"
         and feature.get("panel_root_sha256") == feature_seal.get("panel_construction_root_sha256") == CONTRACT["construction_root"],
         "feature receipt does not bind the sealed pre-feature construction root")
    need(feature.get("panel_seal_sha256") == feature_seal.get("panel_seal_sha256") == CONTRACT["construction_seal"],
         "feature receipt does not bind its construction seal")
    construction_seal = PANEL / "seals/q-panel-construction-seal-v01.json"
    need(sha(construction_seal) == CONTRACT["construction_seal"]
         and terminal_entries.get("seals/q-panel-construction-seal-v01.json", {}).get("sha256") == CONTRACT["construction_seal"],
         "pre-feature construction seal identity mismatch")
    need(entries_root(feature_seal.get("entries", [])) == feature_seal.get("root_sha256"),
         "feature-cache subtree root mismatch")
    return {"terminal_panel_root_sha256": panel_seal["root_sha256"],
            "pre_feature_construction_root_sha256": feature["panel_root_sha256"],
            "feature_cache_seal_sha256": sha(FEATURE_SEAL),
            "feature_receipt_sha256": sha(FEATURE_RECEIPT),
            "construction_seal_sha256": sha(construction_seal),
            "interpretation": "The evaluator compared the pre-feature construction root to the post-feature terminal root."}


def verify_existing_opening() -> dict[str, Any]:
    need(ORIGINAL_EVAL.is_dir() and not CONTINUATION.exists(),
         "evaluation continuation namespace is not clean")
    names = sorted(path.name for path in ORIGINAL_EVAL.iterdir())
    need(names == ["evaluation-failure-receipt-v01.json", "panel-opening-receipt-v01.json"],
         f"unexpected artifacts in the first evaluation attempt: {names}")
    opening = read_json(OPENING)
    failure = read_json(INITIAL_FAILURE)
    need(opening.get("status") == "Q_FRESH_PANEL_OPENED_ONCE_AFTER_ALL_TRAINING_STATES_SEALED"
         and opening.get("opening_count") == 1
         and opening.get("execution_packet_sha256") == CONTRACT["packet"]
         and opening.get("panel_seal_sha256") == CONTRACT["panel_seal"]
         and opening.get("panel_root_sha256") == CONTRACT["panel_root"]
         and opening.get("training_seal_sha256") == CONTRACT["train_seal"]
         and opening.get("checkpoint_tree_sha256") == CONTRACT["checkpoint_tree"],
         "existing opening receipt does not identify this sealed run")
    need(failure.get("status") == "Q_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED"
         and failure.get("stage") == "single_panel_materialization"
         and failure.get("exception") == "Q feature receipt parent mismatch"
         and failure.get("panel_opened") is True,
         "initial evaluation failure is not the exact pre-inference root-binding defect")
    need(sha(OPENING) == "d2fa3102fa362dd580cf990a0a2bc98c0c8d64c1bde4a61c377915fda7b583d5"
         and sha(INITIAL_FAILURE) == "f621ea33723dc23f234d3a7ba11b97f1c6111d8ef34d0631a9d485f39bd89376",
         "first-opening provenance bytes changed")
    return {"opening_count": 1, "opening_receipt_sha256": sha(OPENING),
            "failed_attempt_receipt_sha256": sha(INITIAL_FAILURE),
            "failure_stage": failure["stage"], "head_load_reached": False,
            "prediction_artifacts_present": False}


def preflight() -> None:
    for path, expected in ((PACKET, CONTRACT["packet"]), (PACKET_SEAL, CONTRACT["packet_seal"]),
                           (TRAIN_SEAL, CONTRACT["train_seal"]), (CHECKPOINT_TREE, CONTRACT["checkpoint_tree"])):
        need(sha(path) == expected, f"Q sealed parent changed: {path.name}")
    packet = read_json(PACKET)
    bindings = {row["path"]: row["sha256"] for row in packet["implementation_bindings"]}
    eval_path = Q / "source/evaluate_q_panel_v05.py"
    need(bindings.get("experiments/jev-information-density-v08q/source/evaluate_q_panel_v05.py") == CONTRACT["evaluator"]
         and sha(eval_path) == CONTRACT["evaluator"], "frozen evaluator identity mismatch")
    train = read_json(TRAIN_SEAL)
    need(train.get("status") == "Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED"
         and train.get("run_count") == 12 and train.get("trained_checkpoint_count") == 48
         and train.get("evaluation_panel_opened") is False and train.get("evaluation_feedback") is False,
         "training seal is not the complete unevaluated Q run")
    opening = verify_existing_opening()
    geometry = verify_feature_root_hierarchy()
    if PREFLIGHT.exists():
        raise FileExistsError(PREFLIGHT)
    receipt = {"status": "Q_EVALUATOR_ROOT_BINDING_REPAIR_PREFLIGHT_PASS",
               "adapter_sha256": sha(Path(__file__).resolve()),
               "execution_packet_sha256": CONTRACT["packet"], "evaluator_sha256": CONTRACT["evaluator"],
               "training_seal_sha256": CONTRACT["train_seal"], "checkpoint_tree_sha256": CONTRACT["checkpoint_tree"],
               "opening": opening, "feature_root_hierarchy": geometry,
               "correction": "Compare feature.panel_root_sha256 to the sealed pre-feature construction root, not the terminal panel root.",
               "head_loaded": False, "inference": False,
               "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(PREFLIGHT, receipt)
    print(json.dumps(receipt, indent=2))


def run_evaluation() -> None:
    need(PREFLIGHT.is_file() and read_json(PREFLIGHT).get("status") == "Q_EVALUATOR_ROOT_BINDING_REPAIR_PREFLIGHT_PASS",
         "Q recovery preflight missing or failed")
    need(sha(Path(__file__).resolve()) == read_json(PREFLIGHT).get("adapter_sha256", sha(Path(__file__).resolve())),
         "Q recovery adapter changed after preflight")
    need(not CONTINUATION.exists(), "Q continuation output already exists")
    module = load_module(Q / "source/evaluate_q_panel_v05.py", "q_eval_frozen_v05_recovery")
    module.OUTPUT = CONTINUATION
    original_need = module.need
    original_write_json = module.write_json
    opening_copied = False
    correction_seen = False

    def need_adapter(condition: bool, message: str) -> None:
        nonlocal correction_seen
        if not condition and message == "Q feature receipt parent mismatch":
            verify_feature_root_hierarchy()
            correction_seen = True
            return
        original_need(condition, message)

    def write_adapter(path: Path, value: dict[str, Any]) -> None:
        nonlocal opening_copied
        path = Path(path)
        if path == CONTINUATION / "panel-opening-receipt-v01.json":
            expected = read_json(OPENING)
            for key in ("status", "opening_count", "execution_packet_sha256", "execution_packet_seal_sha256",
                        "panel_root_sha256", "panel_seal_sha256", "training_seal_sha256",
                        "checkpoint_tree_sha256", "panel_parse_before_training_seal", "heldout_feedback_during_training"):
                if value.get(key) != expected.get(key):
                    raise RuntimeError(f"continued opening receipt differs in bound field: {key}")
            shutil.copyfile(OPENING, path)
            opening_copied = True
            return
        original_write_json(path, value)

    module.need = need_adapter
    module.write_json = write_adapter
    status = int(module.main())
    if status != 0 or not opening_copied or not correction_seen:
        raise RuntimeError(f"Q evaluator continuation incomplete: status={status}, opening_copy={opening_copied}, correction={correction_seen}")
    tree_path = CONTINUATION / "raw-prediction-hash-tree-v01.json"
    inference_path = CONTINUATION / "inference-receipt-v01.json"
    tree = read_json(tree_path)
    need(tree.get("status") == "Q_COMPLETE_408000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS"
         and tree.get("prediction_rows") == 408_000 and tree.get("panel_open_count") == 1,
         "Q complete prediction tree invalid")
    completion = {"status": "Q_SINGLE_OPENING_EVALUATION_CONTINUED_AND_PREDICTIONS_SEALED",
                  "execution_packet_sha256": CONTRACT["packet"], "opening_count": 1,
                  "original_opening_receipt_sha256": sha(OPENING),
                  "original_failure_receipt_sha256": sha(INITIAL_FAILURE),
                  "adapter_sha256": sha(Path(__file__).resolve()),
                  "frozen_evaluator_sha256": CONTRACT["evaluator"],
                  "feature_receipt_sha256": CONTRACT["feature_receipt"],
                  "feature_cache_seal_sha256": CONTRACT["feature_seal"],
                  "prediction_tree_sha256": sha(tree_path), "prediction_sha256": tree["raw_predictions"]["sha256"],
                  "inference_receipt_sha256": sha(inference_path), "prediction_rows": 408_000,
                  "head_loaded": True, "analysis_started": False,
                  "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(COMPLETION, completion)
    print(json.dumps(completion, indent=2), flush=True)


def analyze() -> None:
    need(read_json(COMPLETION).get("status") == "Q_SINGLE_OPENING_EVALUATION_CONTINUED_AND_PREDICTIONS_SEALED",
         "Q raw predictions are not sealed")
    module = load_module(Q / "source/analyze_q_results_v05.py", "q_analysis_frozen_v05_recovery")
    module.OUTPUT = CONTINUATION
    status = int(module.main())
    if status != 0:
        raise RuntimeError(f"frozen Q analysis failed with status {status}")


def verify() -> None:
    module = load_module(Q / "source/verify_q_full_execution_v05.py", "q_verify_frozen_v05_recovery")
    module.EVAL = CONTINUATION
    module.RECEIPT = VERIFY_RECEIPT
    status = int(module.main())
    if status != 0:
        raise RuntimeError(f"independent Q verification failed with status {status}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: q_eval_root_binding_recovery_v01.py {preflight|evaluate|analyze|verify}")
    stage = sys.argv[1]
    {"preflight": preflight, "evaluate": run_evaluation, "analyze": analyze, "verify": verify}.get(stage, lambda: None)()
    if stage not in {"preflight", "evaluate", "analyze", "verify"}:
        raise SystemExit(f"unknown stage: {stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
