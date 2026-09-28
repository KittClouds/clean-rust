"""Single-opening P-R2 evaluation of every sealed trajectory checkpoint."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[3]
P_PHASE = ROOT / "experiments/jev-information-density-v08p/phase_b"
R2_WORK = ROOT / "experiments/jev-information-density-v08p-r2"
R2_ROOT = Path(r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2")
PANEL_ROOT = R2_ROOT / "panel"
FEATURE_ROOT = R2_ROOT / "features"
MATCH_ROOT = R2_ROOT / "matching"
TRAIN_ROOT = R2_ROOT / "training"
OUTPUT = R2_ROOT / "evaluation"
RUN_CONTRACT_PATH = P_PHASE / "phase-b-p-run-contract-v01.json"
ANALYSIS_CONTRACT_PATH = P_PHASE / "phase-b-p-analysis-contract-v01.json"
R2_CONTRACT_PATH = R2_WORK / "contracts/r2-execution-contract-v01.json"
ADDENDUM_PATH = R2_WORK / "contracts/p-r2-analysis-addendum-v01.json"
PANEL_MATERIALIZATION = R2_WORK / "provenance/r2-panel-materialization-manifest-v01.json"
PANEL_READY = R2_WORK / "provenance/r2-panel-ready-manifest-v01.json"
PANEL_SEAL = R2_WORK / "provenance/r2-panel-seal-receipt-v01.json"
FINAL_PANEL_AUDIT = R2_ROOT / "panel-audit/r2-final-panel-audit.json"
FEATURE_RECEIPT = FEATURE_ROOT / "r2-feature-extraction-receipt.json"
PRETRAINING_PREFLIGHT = R2_WORK / "provenance/r2-pretraining-preflight-v03.json"
EVALUATOR_CORRECTION_V01 = R2_WORK / "provenance/r2-evaluator-recovery-correction-v01.json"
TARGET_JOIN_CORRECTION_V01 = R2_WORK / "provenance/r2-evaluator-target-join-recovery-v01.json"
SCOPE_INDEX_CORRECTION_V02 = R2_WORK / "provenance/r2-evaluator-scope-index-recovery-v02.json"
EVALUATOR_CORRECTION = SCOPE_INDEX_CORRECTION_V02
TARGET_JOIN_SOURCE = R2_WORK / "runner/r2_panel_target_join.py"
TARGET_JOIN_TEST_SOURCE = R2_WORK / "runner/test_r2_panel_target_join.py"
FAILED_EVALUATOR_ARCHIVE = R2_WORK / "provenance/evaluate_r2_trajectory-pre-target-join-v01.py"
SCOPE_INDEX_EVALUATOR_ARCHIVE = R2_WORK / "provenance/evaluate_r2_trajectory-pre-scope-index-v01.py"
EVALUATION_PREFLIGHT_RECEIPT = R2_WORK / "provenance/r2-evaluation-preflight-v01.json"
EVALUATION_CONTINUATION_PREFLIGHT = R2_WORK / "provenance/r2-evaluation-continuation-preflight-v01.json"
EVALUATION_SCOPE_INDEX_PREFLIGHT = R2_WORK / "provenance/r2-evaluation-scope-index-preflight-v02.json"
TRAIN_SEAL = TRAIN_ROOT / "training-seal-manifest.json"
CHECKPOINT_TREE = TRAIN_ROOT / "checkpoint-hash-tree.json"
OPENING_RECEIPT = OUTPUT / "r2-panel-opening-receipt-v01.json"
FIRST_FAILURE_RECEIPT = OUTPUT / "evaluation-failure-receipt-v01.json"
FIRST_PREFLIGHT_RECEIPT = OUTPUT / "preinference-verification-v01.json"
CONTINUATION_VERIFICATION = OUTPUT / "preinference-continuation-verification-v01.json"
CONTINUATION_RECEIPT = OUTPUT / "preinference-recovery-receipt-v01.json"
SCOPE_INDEX_VERIFICATION = OUTPUT / "preinference-scope-index-verification-v02.json"
SCOPE_INDEX_RECEIPT = OUTPUT / "preinference-scope-index-recovery-receipt-v02.json"
SCOPE_INDEX_FAILURE_RECEIPT = OUTPUT / "evaluation-failure-receipt-v02.json"
POST_SCOPE_INDEX_FAILURE_RECEIPT = OUTPUT / "evaluation-failure-receipt-v03.json"
SCOPE_INDEX_EMPTY_PREDICTION_ARCHIVE = OUTPUT / "failed-attempt-02-empty-predictions-v01.jsonl"
METRIC_SOURCE = ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py"
PROBE_SOURCE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"

EXPECTED = {
    "run_contract": "e345225b4a17fc18eb35fcab24cbe1d72bd0e34bed9de272f927a7be461853e6",
    "analysis_contract": "84111122033fda65c84344317cfe3b50639b23be4c71f480ba665c67a23cc939",
    "r2_contract": "51cd8dee09688f1aae24ff575fa0a181d50b2a6ffc94dc6b7e7ed5b61c58ef14",
    "addendum": "4cd14671ffe7c032864fdc0bd5f75db1d1edea666cc58eb43aae0e6c820d0431",
    "panel_materialization": "565d5e2650db375230fed15eb94471c92a25810c1644d629e7bb9d1490bf4822",
    "panel_ready": "c0d48381356113451bc72f9578204ade4ef7449a75264cd5018a34d002b313ac",
    "panel_seal": "cdd68eee06ef9b4239cfbc3ffbb4f65f18c4ced655e474cba1a3981dbb2c0cb5",
    "final_audit": "328650b3fd638bdf7eb147351e6c897abe8b36899b05af35ef5aa925851c5e89",
    "feature_receipt": "74e701cd87e677c88ea10e0f7a026474ecc7bafab97c021de6c6fcd56c455e09",
    "metric_source": "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4",
    "probe_source": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
}
SEEDS = (3243871208, 669993655, 3076094663)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
CHECKPOINT_STEPS = (40, 80, *range(81, 121))
DEVICE = "cuda:0"
EXPECTED_ROWS = 3_048_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(memoryview(value.numpy()).cast("B"))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"immutable evaluation artifact already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temporary.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import sealed implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def expected_cells() -> list[tuple[int, str, int]]:
    cells: list[tuple[int, str, int]] = []
    for seed in SEEDS:
        cells.append((seed, "COMMON_INIT", 0))
        for step in CHECKPOINT_STEPS:
            cells.extend((seed, arm, step) for arm in ARMS)
    return cells


def verify_source_and_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    paths = {
        "run_contract": RUN_CONTRACT_PATH,
        "analysis_contract": ANALYSIS_CONTRACT_PATH,
        "r2_contract": R2_CONTRACT_PATH,
        "addendum": ADDENDUM_PATH,
        "panel_materialization": PANEL_MATERIALIZATION,
        "panel_ready": PANEL_READY,
        "panel_seal": PANEL_SEAL,
        "final_audit": FINAL_PANEL_AUDIT,
        "feature_receipt": FEATURE_RECEIPT,
        "metric_source": METRIC_SOURCE,
        "probe_source": PROBE_SOURCE,
    }
    hashes = {}
    for key, path in paths.items():
        require(path.is_file(), f"required sealed source is missing: {key}")
        hashes[key] = sha256_file(path)
        require(hashes[key] == EXPECTED[key], f"sealed source hash mismatch: {key}")
    run, analysis, r2 = (read_json(RUN_CONTRACT_PATH), read_json(ANALYSIS_CONTRACT_PATH), read_json(R2_CONTRACT_PATH))
    require(run["training"]["seed_set"]["seeds"] == list(SEEDS), "frozen P seed list changed")
    require(r2["training"]["arms"] == list(ARMS) and r2["training"]["seeds"] == list(SEEDS),
            "R2 arm/seed identity changed")
    require(analysis["evaluation_design"]["expected_prediction_rows"] == EXPECTED_ROWS,
            "frozen P prediction cardinality changed")
    require(len(expected_cells()) == 381, "frozen P evaluation cell inventory is not 381")
    return run, analysis, r2, hashes


def verify_training_tree(run_contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    require(TRAIN_SEAL.is_file() and CHECKPOINT_TREE.is_file(), "sealed R2 training outputs are incomplete")
    preflight = read_json(PRETRAINING_PREFLIGHT)
    seal = read_json(TRAIN_SEAL)
    tree = read_json(CHECKPOINT_TREE)
    require(preflight.get("status") == "P_R2_RECOVERY_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS"
            and preflight.get("head_training_started") is False
            and preflight.get("optimizer_steps_committed_before_recovery") == 0,
            "zero-step recovery preflight did not pass")
    require(seal.get("status") == "P_R2_ALL_NINE_RUNS_COMPLETE_SEALED_UNEVALUATED"
            and seal.get("run_count") == 9 and seal.get("trained_checkpoint_count") == 378
            and seal.get("evaluation_access") is False and seal.get("heldout_panel_opened") is False,
            "R2 training seal has wrong status or boundary")
    require(seal.get("training_preflight_receipt_sha256") == sha256_file(PRETRAINING_PREFLIGHT),
            "training seal does not bind the pre-head preflight")
    require(seal.get("checkpoint_hash_tree_sha256") == sha256_file(CHECKPOINT_TREE),
            "training seal/checkpoint-tree binding mismatch")
    require(tree.get("trained_checkpoint_count") == 378 and tree.get("initial_template_count") == 3,
            "checkpoint tree counts differ from the P schedule")
    require(len([row for row in tree["entries"] if row.get("kind") == "trained_checkpoint"]) == 378,
            "checkpoint tree has the wrong trained checkpoint inventory")
    require(len([row for row in tree["entries"] if row.get("kind") == "initial_template"]) == 3,
            "checkpoint tree has the wrong initialization inventory")
    for item in tree["entries"]:
        path = Path(item["path"])
        require(path.is_file() and path.stat().st_size == item["bytes"] and sha256_file(path) == item["sha256"],
                f"training hash tree entry mismatch: {path}")
    checkpoint_map: dict[tuple[int, str, int], dict[str, Any]] = {}
    template_map: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        template_path = TRAIN_ROOT / "initial-templates" / f"seed-{seed}.pt"
        template_item = next((row for row in tree["entries"] if row.get("kind") == "initial_template"
                              and Path(row["path"]).resolve() == template_path.resolve()), None)
        require(template_item is not None, f"missing sealed initialization template: {seed}")
        paired: set[str] = set()
        for arm in ARMS:
            run_dir = TRAIN_ROOT / "runs" / f"seed-{seed}" / arm
            integrity = read_json(run_dir / "run-integrity.json")
            require(integrity.get("status") == "TRAINING_COMPLETE_UNEVALUATED"
                    and integrity.get("seed") == seed and integrity.get("arm") == arm
                    and integrity.get("optimizer_steps") == 120 and integrity.get("checkpoint_count") == 42
                    and integrity.get("evaluation_access") is False,
                    f"run integrity invalid: {seed}/{arm}")
            paired.add(integrity["initial_head_sha256"])
            index = read_jsonl(run_dir / "checkpoint-index.jsonl")
            require([row["global_step"] for row in index] == list(CHECKPOINT_STEPS),
                    f"checkpoint cadence/index mismatch: {seed}/{arm}")
            for row in index:
                step = int(row["global_step"])
                path = run_dir / row["path"]
                entry = next((item for item in tree["entries"] if item.get("kind") == "trained_checkpoint"
                              and Path(item["path"]).resolve() == path.resolve()), None)
                require(entry is not None and entry["sha256"] == row["sha256"],
                        f"checkpoint missing from sealed tree: {seed}/{arm}/{step}")
                checkpoint_map[(seed, arm, step)] = {
                    "path": str(path), "sha256": row["sha256"],
                    "head_sha256": row["head_sha256"], "initial_head_sha256": integrity["initial_head_sha256"],
                    "seed": seed, "arm": arm, "global_step": step,
                }
        require(len(paired) == 1, f"paired arm initialization mismatch within seed {seed}")
        template_map[seed] = {**template_item, "seed": seed, "state_sha256": next(iter(paired))}
    require(len(checkpoint_map) == 378, "complete checkpoint map does not contain 378 states")
    # Pair identity is verified before evaluation; no metric or prediction is read here.
    return seal, tree, {"checkpoints": list(checkpoint_map.values()), "templates": list(template_map.values())}


def verify_panel_files(panel_ready: dict[str, Any]) -> dict[str, str]:
    manifest = read_json(PANEL_MATERIALIZATION)
    require(manifest.get("status") == "PANEL_CONSTRUCTED_AND_FIVE_FIELD_AUDIT_PASS",
            "R2 panel construction status is not promotable")
    require(manifest["independent_final_audit"]["status"] == "R2_FRESH_PANEL_FINAL_AUDIT_PASS"
            and manifest["independent_final_audit"]["sha256"] == EXPECTED["final_audit"],
            "independent final R2 panel audit is not PASS")
    require(panel_ready.get("status") == "R2_PANEL_READY"
            and panel_ready.get("construction_panel_manifest_sha256") == EXPECTED["panel_materialization"],
            "R2 panel-ready receipt does not bind the sealed materialization")
    panel_hashes = {row["name"]: row["sha256"] for row in manifest["construction_outputs"]}
    panel_hashes.update({
        "fresh-candidate-text-manifest.jsonl": manifest["admission"]["candidate_text_manifest_sha256"],
        "online-admission-log.jsonl": manifest["admission"]["admission_log_sha256"],
        "online-admission-receipt.json": manifest["admission"]["admission_receipt_sha256"],
    })
    for name, digest in panel_hashes.items():
        path = PANEL_ROOT / name
        require(path.is_file() and sha256_file(path) == digest, f"sealed R2 panel byte mismatch: {name}")
    feature_outputs = {Path(row["path"]).name: row["sha256"] for row in panel_ready["feature_outputs"]
                       if str(row["path"]).startswith("features/")}
    for name, digest in feature_outputs.items():
        path = FEATURE_ROOT / name
        require(path.is_file() and sha256_file(path) == digest, f"sealed R2 feature byte mismatch: {name}")
    require(feature_outputs.get("r2-feature-extraction-receipt.json") == EXPECTED["feature_receipt"],
            "R2 feature receipt is not the frozen receipt")
    matching_outputs = {Path(row["path"]).name: row["sha256"] for row in panel_ready["feature_outputs"]
                        if str(row["path"]).startswith("matching/")}
    for name, digest in matching_outputs.items():
        path = MATCH_ROOT / name
        require(path.is_file() and sha256_file(path) == digest, f"sealed R2 matching byte mismatch: {name}")
    return {**{f"panel/{key}": value for key, value in panel_hashes.items()},
            **{f"features/{key}": value for key, value in feature_outputs.items()},
            **{f"matching/{key}": value for key, value in matching_outputs.items()}}


def static_preflight(*, scope_index_continuation: bool = False,
                     require_scope_index_preflight: bool = False) -> dict[str, Any]:
    if scope_index_continuation:
        require(OUTPUT.is_dir(), "pre-inference continuation requires the existing single panel opening")
        require((OUTPUT / "raw-predictions-v01.jsonl").is_file()
                and (OUTPUT / "raw-predictions-v01.jsonl").stat().st_size == 0
                and sha256_file(OUTPUT / "raw-predictions-v01.jsonl")
                == sha256_file(SCOPE_INDEX_EMPTY_PREDICTION_ARCHIVE)
                and not (OUTPUT / "inference-receipt-v01.json").exists()
                and not SCOPE_INDEX_RECEIPT.exists(),
                "continuation lacks the preserved empty prediction file or contains inference output")
    else:
        require(not OUTPUT.exists(), f"R2 evaluation output already exists; no repeat opening: {OUTPUT}")
    run_contract, analysis_contract, r2_contract, source_hashes = verify_source_and_contracts()
    seal, tree, inventory = verify_training_tree(run_contract)
    preflight_hash = sha256_file(PRETRAINING_PREFLIGHT)
    bound_sources = read_json(PRETRAINING_PREFLIGHT)["instrument_source_hashes"]
    correction = read_json(SCOPE_INDEX_CORRECTION_V02)
    evaluator_source_hash = sha256_file(Path(__file__).resolve())
    require(scope_index_continuation, "the initial opening path is sealed; explicit continuation mode is required")
    prior_preflight = read_json(FIRST_PREFLIGHT_RECEIPT)
    opening = read_json(OPENING_RECEIPT)
    first_failure = read_json(FIRST_FAILURE_RECEIPT)
    target_join_correction = read_json(TARGET_JOIN_CORRECTION_V01)
    scope_index_failure = read_json(SCOPE_INDEX_FAILURE_RECEIPT)
    target_join_audit = read_json(OUTPUT / "exact-world-target-join-audit-v01.json")
    require(prior_preflight.get("status") == "P_R2_EVALUATION_PREFLIGHT_PASS_ALL_TRAINING_SEALED"
            and prior_preflight.get("head_payloads_deserialized") is False
            and prior_preflight.get("predictions_created") is False
            and prior_preflight.get("implementation_hashes", {}).get("evaluator")
            == correction.get("prior_opened_evaluator_sha256"),
            "prior pre-inference verification does not match the recovery chain")
    require(opening.get("opening_count") == 1
            and opening.get("preinference_verification_sha256") == sha256_file(FIRST_PREFLIGHT_RECEIPT)
            and opening.get("training_seal_sha256") == sha256_file(TRAIN_SEAL)
            and opening.get("checkpoint_hash_tree_sha256") == sha256_file(CHECKPOINT_TREE),
            "existing opening receipt is not the sole sealed R2 opening")
    require(first_failure.get("status") == "P_R2_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED"
            and first_failure.get("stage") == "opened_fresh_panel_input_validation"
            and first_failure.get("exception_type") == "KeyError"
            and first_failure.get("exception") == "'target'"
            and first_failure.get("panel_opening_receipt_sha256") == sha256_file(OPENING_RECEIPT)
            and first_failure.get("prediction_file_exists") is False,
            "existing failed attempt is not the exact pre-head target-schema stop")
    require(target_join_correction.get("status") == "OUTCOME_BLIND_PREINFERENCE_TARGET_JOIN_RECOVERY"
            and target_join_correction.get("corrected_evaluator_sha256")
            == correction.get("prior_scope_index_evaluator_sha256")
            and target_join_correction.get("predictions_or_metrics_existed_when_authored") is False
            and target_join_correction.get("trained_head_payloads_deserialized_before_recovery_authoring") is False
            and target_join_audit.get("status") == "EXACT_WORLD_TARGET_JOIN_PASS"
            and target_join_audit.get("scope_rows") == 22_000
            and target_join_audit.get("exact_world_rows") == 22_000
            and target_join_audit.get("canonical_rows") == 22_000
            and target_join_audit.get("unique_episode_ids") == 22_000
            and target_join_audit.get("neighborhoods") == 2_000
            and target_join_audit.get("fact_map_flip_count") == 2_000,
            "prior exact-world target join recovery is not sealed and complete")
    require(scope_index_failure.get("status") == "P_R2_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED"
            and scope_index_failure.get("exception")
            == "selected panel episode lacks feature-scope row: v08n-eval_v08p_r2-exposure_control-000000/anchor"
            and scope_index_failure.get("panel_opening_receipt_sha256") == sha256_file(OPENING_RECEIPT)
            and scope_index_failure.get("prediction_file_exists") is True
            and scope_index_failure.get("stage") == "opened_fresh_panel_input_validation"
            and sha256_file(SCOPE_INDEX_EMPTY_PREDICTION_ARCHIVE)
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "second failed attempt is not the preserved pre-forward empty-output failure")
    panel_manifest = read_json(PANEL_MATERIALIZATION)
    panel_file_hashes = {row["name"]: row["sha256"] for row in panel_manifest["construction_outputs"]}
    correction_failure = correction.get("failure_disposition", {})
    require(correction.get("status") == "OUTCOME_BLIND_PREINFERENCE_SCOPE_INDEX_RECOVERY"
            and correction.get("pretraining_preflight_v03_sha256") == preflight_hash
            and correction.get("original_training_evaluator_sha256") == bound_sources.get("evaluator")
            and correction.get("prior_correction_target_join_sha256") == sha256_file(TARGET_JOIN_CORRECTION_V01)
            and correction.get("prior_scope_failure_sha256") == sha256_file(SCOPE_INDEX_FAILURE_RECEIPT)
            and correction.get("prior_empty_prediction_sha256") == sha256_file(SCOPE_INDEX_EMPTY_PREDICTION_ARCHIVE)
            and correction.get("prior_scope_index_evaluator_sha256")
            == target_join_correction.get("corrected_evaluator_sha256")
            and correction.get("prior_preinference_verification_sha256") == sha256_file(FIRST_PREFLIGHT_RECEIPT)
            and correction.get("prior_opening_receipt_sha256") == sha256_file(OPENING_RECEIPT)
            and correction.get("prior_opened_evaluator_sha256")
            == prior_preflight["implementation_hashes"]["evaluator"]
            and correction.get("scope_index_evaluator_archive_sha256")
            == sha256_file(SCOPE_INDEX_EVALUATOR_ARCHIVE)
            and correction.get("corrected_evaluator_sha256") == evaluator_source_hash
            and correction.get("target_join_adapter_sha256") == sha256_file(TARGET_JOIN_SOURCE)
            and correction.get("target_join_test_sha256") == sha256_file(TARGET_JOIN_TEST_SOURCE)
            and correction.get("target_join_audit_v01_sha256")
            == sha256_file(OUTPUT / "exact-world-target-join-audit-v01.json")
            and correction.get("panel_feature_scope_sha256") == panel_file_hashes.get("panel-feature-scope.jsonl")
            and correction.get("exact_episode_source_sha256") == panel_file_hashes.get("panel-exact-world-episodes.jsonl")
            and correction.get("canonical_schema_source_sha256") == panel_file_hashes.get("panel-canonical-episodes.jsonl")
            and correction.get("evaluation_metric_source_sha256") == source_hashes["metric_source"]
            and correction.get("analysis_metric_source_sha256") == bound_sources.get("metric_analyzer")
            and correction_failure.get("raw_prediction_rows_existed_when_authored") == 0
            and correction_failure.get("common_init_head_deserialized_before_failure") is True
            and correction_failure.get("metric_function_entered_before_failure") is True
            and correction_failure.get("model_forward_or_predictions_existed_when_authored") is False
            and correction.get("scientific_contract_changed") is False,
            "pre-inference scope-index correction receipt/source binding failed")
    if require_scope_index_preflight:
        require(SCOPE_INDEX_VERIFICATION.is_file() and EVALUATION_SCOPE_INDEX_PREFLIGHT.is_file(),
                "whole-panel scope-index preflight is missing")
        scope_preflight = read_json(SCOPE_INDEX_VERIFICATION)
        require(scope_preflight.get("status") == "P_R2_SCOPE_INDEX_PREFLIGHT_PASS_NO_HEADS"
                and scope_preflight.get("opening_count") == 1
                and scope_preflight.get("head_payloads_deserialized") is False
                and scope_preflight.get("predictions_created") is False
                and scope_preflight.get("selected_view_episode_join_count") == 8_000
                and scope_preflight.get("input_verification_sha256")
                == sha256_file(EVALUATION_SCOPE_INDEX_PREFLIGHT),
                "whole-panel scope-index preflight receipt is invalid")
        require(scope_preflight.get("exact_world_target_join_audit_sha256")
                == sha256_file(OUTPUT / "exact-world-target-join-audit-v02.json"),
                "scope-index preflight target-join audit binding mismatch")
    expected_local = {
        "trainer": R2_WORK / "runner/train_r2.py",
        "evaluator": Path(__file__).resolve(),
        "analysis": R2_WORK / "runner/analyze_r2_trajectory.py",
        "analysis_adapter": R2_WORK / "runner/r2_analysis_adapter.py",
        "analysis_test": R2_WORK / "runner/test_r2_trajectory_analysis.py",
        "evaluator_test": R2_WORK / "runner/test_r2_evaluator.py",
        "trajectory_helper": P_PHASE / "trajectory_analysis.py",
        "metric_analyzer": ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
    }
    for key, path in expected_local.items():
        actual_hash = sha256_file(path) if path.is_file() else None
        if key == "evaluator":
            valid = (bound_sources.get(key) == correction["original_training_evaluator_sha256"]
                     and actual_hash == correction["corrected_evaluator_sha256"])
        else:
            valid = actual_hash is not None and bound_sources.get(key) == actual_hash
        require(valid, f"pre-run instrument source binding failed: {key}")
    panel_ready = read_json(PANEL_READY)
    panel_manifest = read_json(PANEL_MATERIALIZATION)
    require(panel_ready.get("status") == "R2_PANEL_READY"
            and panel_manifest.get("status") == "PANEL_CONSTRUCTED_AND_FIVE_FIELD_AUDIT_PASS",
            "R2 panel is not sealed/ready")
    expected_panel_hashes = {row["name"]: row["sha256"] for row in panel_manifest["construction_outputs"]}
    expected_panel_hashes.update({
        "fresh-candidate-text-manifest.jsonl": panel_manifest["admission"]["candidate_text_manifest_sha256"],
        "online-admission-log.jsonl": panel_manifest["admission"]["admission_log_sha256"],
        "online-admission-receipt.json": panel_manifest["admission"]["admission_receipt_sha256"],
    })
    panel_hashes = {f"panel/{name}": digest for name, digest in expected_panel_hashes.items()}
    panel_hashes.update({f"features/{Path(row['path']).name}": row["sha256"]
                         for row in panel_ready["feature_outputs"] if str(row["path"]).startswith("features/")})
    panel_hashes.update({f"matching/{Path(row['path']).name}": row["sha256"]
                         for row in panel_ready["feature_outputs"] if str(row["path"]).startswith("matching/")})
    feature_receipt = read_json(FEATURE_RECEIPT)
    require(feature_receipt.get("status") == "R2_FROZEN_PANEL_FEATURES_SEALED"
            and feature_receipt["repeat_smoke"]["max_abs_error"] == 0.0
            and feature_receipt["state_tensor"]["shape"] == [22_000, 2_048]
            and feature_receipt["candidate_tensor"]["shape"] == [16, 2_048],
            "R2 frozen feature extraction receipt is incomplete")
    runtime = {
        "python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__,
        "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "compute_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
        "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_tf32": torch.backends.cudnn.allow_tf32,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    expected_runtime = feature_receipt["runtime"]
    require(runtime["python"] == expected_runtime["python"] and runtime["torch"] == expected_runtime["torch"]
            and runtime["numpy"] == expected_runtime["numpy"] and runtime["cuda"] == expected_runtime["cuda"]
            and runtime["cudnn"] == expected_runtime["cudnn"] and runtime["device"] == expected_runtime["device"]
            and runtime["compute_capability"] == expected_runtime["compute_capability"],
            "evaluation runtime/device differs from frozen R2 extraction runtime")
    require(torch.cuda.is_available() and runtime["matmul_tf32"] is False,
            "frozen evaluation CUDA/TF32 requirements failed")
    return {
        "status": "P_R2_EVALUATION_PREFLIGHT_PASS_ALL_TRAINING_SEALED",
        "identity": r2_contract["identity"],
        "run_contract_sha256": source_hashes["run_contract"],
        "analysis_contract_sha256": source_hashes["analysis_contract"],
        "r2_contract_sha256": source_hashes["r2_contract"],
        "addendum_sha256": source_hashes["addendum"],
        "training_seal_sha256": sha256_file(TRAIN_SEAL),
        "checkpoint_hash_tree_sha256": sha256_file(CHECKPOINT_TREE),
        "pretraining_instrument_receipt_sha256": preflight_hash,
        "checkpoint_count": len(inventory["checkpoints"]), "template_count": len(inventory["templates"]),
        "panel_ready_manifest_sha256": source_hashes["panel_ready"],
        "panel_materialization_sha256": source_hashes["panel_materialization"],
        "feature_receipt_sha256": source_hashes["feature_receipt"],
        "evaluator_correction_receipt_sha256": sha256_file(EVALUATOR_CORRECTION),
        "expected_panel_and_evaluation_input_hashes": panel_hashes,
        "checkpoint_inventory": inventory["checkpoints"], "template_inventory": inventory["templates"],
        "implementation_hashes": {**source_hashes, **{key: sha256_file(path) for key, path in expected_local.items()}},
        "runtime": runtime, "head_payloads_deserialized": False,
        "panel_records_or_targets_parsed": False, "predictions_created": False,
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
    }


def record_panel_opening(preflight: dict[str, Any]) -> str:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    preflight_path = OUTPUT / "preinference-verification-v01.json"
    write_json(preflight_path, preflight)
    receipt_path = OUTPUT / "r2-panel-opening-receipt-v01.json"
    write_json(receipt_path, {
        "status": "P_R2_FRESH_PANEL_OPENED_AFTER_COMPLETE_TRAINING_SEAL",
        "identity": "v0.8P-R2 late-transition localization fresh-panel trajectory evaluation",
        "opening_count": 1,
        "authorization_source": "explicit user authorization in active conversation",
        "preinference_verification_sha256": sha256_file(preflight_path),
        "training_seal_sha256": preflight["training_seal_sha256"],
        "checkpoint_hash_tree_sha256": preflight["checkpoint_hash_tree_sha256"],
        "panel_ready_manifest_sha256": preflight["panel_ready_manifest_sha256"],
        "feature_receipt_sha256": preflight["feature_receipt_sha256"],
        "prediction_rows": EXPECTED_ROWS, "cells": 381,
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    return sha256_file(receipt_path)


def load_panel_inputs() -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]],
                                  dict[str, dict[str, Any]], torch.Tensor, torch.Tensor,
                                  dict[str, int], dict[str, list[str]], dict[str, Any]]:
    opened_hashes = verify_panel_files(read_json(PANEL_READY))
    scope_rows = read_jsonl(PANEL_ROOT / "panel-feature-scope.jsonl")
    exact_episode_rows = read_jsonl(PANEL_ROOT / "panel-exact-world-episodes.jsonl")
    canonical_episode_rows = read_jsonl(PANEL_ROOT / "panel-canonical-episodes.jsonl")
    neighborhood_rows = read_jsonl(PANEL_ROOT / "panel-neighborhoods.jsonl")
    candidate_text_rows = read_jsonl(PANEL_ROOT / "fresh-candidate-text-manifest.jsonl")
    candidate_rows = read_jsonl(FEATURE_ROOT / "r2-candidate-feature-manifest.jsonl")
    state_feature_rows = read_jsonl(FEATURE_ROOT / "r2-state-feature-manifest.jsonl")
    selected_rows = read_jsonl(MATCH_ROOT / "matched-neutral-selection.jsonl")
    join_rows = read_jsonl(MATCH_ROOT / "whole-panel-candidate-join.jsonl")
    require(len(scope_rows) == 22_000 and len(exact_episode_rows) == 22_000
            and len(canonical_episode_rows) == 22_000 and len(neighborhood_rows) == 2_000
            and len(candidate_text_rows) == 16
            and len(candidate_rows) == 16
            and len(state_feature_rows) == 22_000 and len(selected_rows) == 2_000 and len(join_rows) == 8_000,
            "R2 opened panel/feature/join cardinality mismatch")

    text_schema_orders: dict[str, list[str]] = {}
    for row in sorted(candidate_text_rows, key=lambda item: (str(item["schema_family_id"]),
                                                              int(item["candidate_order"]))):
        slug = str(row["schema_family_id"]).split(":")[-1]
        text_schema_orders.setdefault(slug, []).append(str(row["candidate_semantic_id"]))
    require(set(text_schema_orders) == set(FAMILIES)
            and all(len(rows) == 4 for rows in text_schema_orders.values()),
            "R2 exact target join has incomplete candidate semantic order")
    target_join_module = import_module(TARGET_JOIN_SOURCE, "jev_r2_panel_target_join")
    target_join_audit = target_join_module.attach_exact_world_targets(
        scope_rows, exact_episode_rows, canonical_episode_rows, text_schema_orders,
    )

    state_pack = torch.load(FEATURE_ROOT / "r2-state-features.pt", map_location="cpu", weights_only=True)
    candidate_pack = torch.load(FEATURE_ROOT / "r2-candidate-features.pt", map_location="cpu", weights_only=True)
    state_features = state_pack["features"]
    candidate_features = candidate_pack["features"].to("cuda")
    require(state_features.shape == (22_000, 2_048) and state_features.dtype == torch.float32
            and state_features.is_contiguous() and torch.isfinite(state_features).all().item(),
            "R2 opened state feature tensor shape/dtype/layout/finiteness mismatch")
    require(candidate_features.shape == (16, 2_048) and candidate_features.dtype == torch.float32
            and candidate_features.is_contiguous() and torch.isfinite(candidate_features).all().item(),
            "R2 opened candidate feature tensor shape/dtype/layout/finiteness mismatch")
    candidate_feature_receipt = read_json(FEATURE_RECEIPT)
    require(tensor_sha256(state_features) == candidate_feature_receipt["state_tensor"]["tensor_sha256"]
            and tensor_sha256(candidate_features) == candidate_feature_receipt["candidate_tensor"]["tensor_sha256"],
            "R2 opened feature tensor content hash mismatch")

    target_join_module = import_module(TARGET_JOIN_SOURCE, "jev_r2_panel_target_join")
    scope_by_neighborhood, roles_by_neighborhood = target_join_module.index_scope_rows(scope_rows)
    for index, row in enumerate(scope_rows):
        require(row.get("index") == index, "R2 feature scope index/order mismatch")
        nid = str(row["neighborhood_id"])
        episode = str(row["episode_id"])
        role = str(row["role"])
        require(len(row["target"]) == 4 and abs(sum(float(v) for v in row["target"]) - 1.0) <= 1e-12,
                f"R2 target is invalid: {nid}/{role}")
        feature_meta = state_feature_rows[index]
        require(feature_meta.get("index") == index and feature_meta.get("episode_id") == episode
                and feature_meta.get("neighborhood_id") == nid and feature_meta.get("family_id") == row.get("family_id")
                and feature_meta.get("role") == role and feature_meta.get("input_sha256") == row.get("input_sha256")
                and feature_meta.get("feature_key") == "mean_full@16"
                and feature_meta.get("feature_sha256") == hashlib.sha256(
                    memoryview(state_features[index].contiguous().numpy()).cast("B")).hexdigest(),
                f"R2 state feature identity row mismatch: {nid}/{role}")
    require(len(scope_by_neighborhood) == 2_000 and len(roles_by_neighborhood) == 2_000
            and all(len(rows) == 11 for rows in scope_by_neighborhood.values())
            and all(len(rows) == 11 for rows in roles_by_neighborhood.values()),
            "R2 scope does not resolve 2000 complete 11-role neighborhoods")

    candidate_rows.sort(key=lambda row: int(row["index"]))
    require([int(row["index"]) for row in candidate_rows] == list(range(16)),
            "R2 candidate storage index is not a complete manifest ordering")
    candidate_index: dict[str, int] = {}
    schema_orders: dict[str, list[str]] = {}
    schema_by_slug: dict[str, str] = {}
    for row in candidate_rows:
        schema_id = str(row["schema_family_id"])
        slug = schema_id.split(":")[-1]
        semantic_id = str(row["candidate_semantic_id"])
        require(row.get("feature_key") == "mean_full@16" and semantic_id not in candidate_index,
                "duplicate or wrong-feature candidate semantic identity")
        candidate_index[semantic_id] = int(row["index"])
        candidate_vector_hash = hashlib.sha256(
            memoryview(candidate_features[int(row["index"])].detach().cpu().contiguous().numpy()).cast("B")
        ).hexdigest()
        require(row.get("feature_sha256") == candidate_vector_hash,
                f"R2 candidate feature row hash mismatch: {semantic_id}")
        schema_orders.setdefault(slug, []).append(semantic_id)
        require(slug not in schema_by_slug or schema_by_slug[slug] == schema_id,
                f"schema slug is ambiguous: {slug}")
        schema_by_slug[slug] = schema_id
    for slug, ids in schema_orders.items():
        rows = sorted((row for row in candidate_rows if row["schema_family_id"] == schema_by_slug[slug]),
                      key=lambda row: int(row["candidate_order"]))
        require(len(ids) == 4 and [int(row["candidate_order"]) for row in rows] == [0, 1, 2, 3],
                f"candidate order is incomplete for schema {slug}")
        schema_orders[slug] = [str(row["candidate_semantic_id"]) for row in rows]
    require(set(schema_orders) == set(FAMILIES) and len(candidate_index) == 16,
            "R2 candidate basis does not cover exact four held-out schemas")
    require(schema_orders == text_schema_orders,
            "feature candidate order differs from the target join's sealed semantic catalog")
    text_catalog = {(str(row["schema_family_id"]), str(row["candidate_semantic_id"])): row
                    for row in candidate_text_rows}
    require(len(text_catalog) == 16, "R2 candidate text catalog has duplicate semantic keys")
    for row in candidate_rows:
        text_row = text_catalog.get((str(row["schema_family_id"]), str(row["candidate_semantic_id"])))
        require(text_row is not None and int(text_row["candidate_order"]) == int(row["candidate_order"])
                and text_row["text_sha256"] == row["input_text_sha256"],
                "R2 feature/text candidate semantic binding mismatch")

    join_by_neighborhood: dict[str, list[dict[str, Any]]] = {}
    for row in join_rows:
        nid = str(row["neighborhood_id"])
        join_by_neighborhood.setdefault(nid, []).append(row)
    require(set(join_by_neighborhood) == set(scope_by_neighborhood)
            and all(len(rows) == 4 for rows in join_by_neighborhood.values()),
            "R2 exact candidate join does not cover all neighborhoods")
    for nid, rows in join_by_neighborhood.items():
        rows.sort(key=lambda row: int(row["candidate_order"]))
        expected_ids = schema_orders[str(rows[0]["schema_family_id"]).split(":")[-1]]
        require([int(row["candidate_order"]) for row in rows] == [0, 1, 2, 3]
                and [str(row["candidate_semantic_id"]) for row in rows] == expected_ids
                and all(row.get("join_key") == "schema_family_id+candidate_semantic_id" for row in rows),
                f"R2 exact schema/candidate join differs from authoritative catalog: {nid}")
        for row in rows:
            feature = candidate_rows[candidate_index[str(row["candidate_semantic_id"])]]
            require(feature["schema_family_id"] == row["schema_family_id"]
                    and int(feature["index"]) == int(row["feature_index_storage_only"])
                    and feature["feature_sha256"] == row["feature_sha256"],
                    f"R2 join feature identity mismatch: {nid}/{row['candidate_semantic_id']}")

    selection = {str(row["neighborhood_id"]): row for row in selected_rows}
    require(len(selection) == 2_000 and set(selection) == set(scope_by_neighborhood),
            "matched-neutral selection has duplicate/missing neighborhood IDs")
    neighborhoods: dict[str, dict[str, Any]] = {}
    panel_rows: list[dict[str, Any]] = []
    for raw in neighborhood_rows:
        nid = str(raw["neighborhood_id"])
        slug = str(raw["family_slug"])
        require(nid not in neighborhoods and slug in schema_by_slug, f"unknown/duplicate R2 neighborhood: {nid}")
        roles = roles_by_neighborhood[nid]
        selected = selection[nid]
        require(selected.get("family_slug") == slug and str(selected["matched_neutral_episode_id"]) in {
            str(row["episode_id"]) for row in roles.values()}, f"matched-neutral selection join mismatch: {nid}")
        wanted = {
            "anchor": roles["anchor"]["episode_id"],
            "fact_flip": roles["fact_flip"]["episode_id"],
            "sham": roles["sham"]["episode_id"],
            "matched_neutral": selected["matched_neutral_episode_id"],
        }
        require(wanted["matched_neutral"] == roles[str(selected["matched_neutral_role"])]["episode_id"],
                f"selected neutral role/episode identity mismatch: {nid}")
        family_id = str(raw["family_id"])
        anchor_scope = roles["anchor"]
        panel_rows.append({
            "neighborhood_id": nid, "family_id": family_id,
            "template_id": anchor_scope.get("template_id"),
            "anchor_episode_id": wanted["anchor"], "fact_episode_id": wanted["fact_flip"],
            "sham_episode_id": wanted["sham"], "matched_neutral_episode_id": wanted["matched_neutral"],
        })
        neighborhoods[nid] = {"schema_family_id": schema_by_slug[slug], "family_id": family_id,
                              "family_slug": slug, "template_id": anchor_scope.get("template_id")}
    require(len(panel_rows) == 2_000 and len({row["neighborhood_id"] for row in panel_rows}) == 2_000,
            "R2 panel rows do not resolve to 2000 unique neighborhoods")
    require(set(neighborhoods) == set(scope_by_neighborhood),
            "R2 neighborhood manifest and feature scope identity sets differ")
    family_counts = {family: sum(row["family_id"].split(":")[-1] == family for row in panel_rows)
                     for family in FAMILIES}
    require(all(count == 500 for count in family_counts.values()), "R2 opened panel family allocation mismatch")
    for panel in panel_rows:
        views = roles_by_neighborhood[panel["neighborhood_id"]]
        anchor_target = views["anchor"]["target"]
        for role in ("sham", "matched_neutral"):
            target = views[role]["target"] if role in views else views[str(selection[panel["neighborhood_id"]]["matched_neutral_role"])]["target"]
            require(max(abs(float(a) - float(b)) for a, b in zip(anchor_target, target, strict=True)) <= 1e-12,
                    f"R2 invariant target changed: {panel['neighborhood_id']}/{role}")
        fact_target = views["fact_flip"]["target"]
        old = max(range(4), key=lambda i: (float(anchor_target[i]), -i))
        new = max(range(4), key=lambda i: (float(fact_target[i]), -i))
        require(old != new, f"R2 fact target does not change MAP: {panel['neighborhood_id']}")
    return panel_rows, scope_by_neighborhood, neighborhoods, state_features, candidate_features, candidate_index, schema_orders, {
        "state_feature_rows": len(state_feature_rows), "candidate_feature_rows": len(candidate_rows),
        "join_rows": len(join_rows), "family_counts": family_counts,
        "exact_world_target_join": target_join_audit, "opened_input_hashes": opened_hashes,
    }


def load_head(path: Path, expected_sha: str, *, seed: int, arm: str, step: int,
              probe: Any, expected_state_sha: str | None = None) -> tuple[Any, str]:
    require(sha256_file(path) == expected_sha, f"checkpoint bytes changed before inference: {path}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    require(payload.get("seed") == seed, f"checkpoint seed mismatch: {path}")
    if step == 0:
        state = payload.get("state_dict")
        state_sha = payload.get("state_sha256")
    else:
        require(payload.get("arm") == arm and payload.get("global_step") == step,
                f"checkpoint treatment/step mismatch: {path}")
        state = payload.get("head_state")
        state_sha = payload.get("head_sha256")
        require(payload.get("schedule_sha256") == EXPECTED_SCHEDULE_SHA,
                f"checkpoint schedule identity mismatch: {path}")
    require(isinstance(state, dict) and state_digest(state) == state_sha,
            f"checkpoint head-state hash mismatch: {path}")
    if expected_state_sha is not None:
        require(state_sha == expected_state_sha, f"checkpoint index/head state mismatch: {path}")
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.load_state_dict(state, strict=True)
    require(sum(parameter.numel() for parameter in head.parameters()) == 590_081,
            "loaded P-R2 head parameter count differs from contract")
    return head, state_sha


EXPECTED_SCHEDULE_SHA = "455d2f8fd709cb0c617f652f7b4ed447fcaaaa30e3e8d2ff1c5cadf358480933"


def scope_index_preflight_only() -> None:
    preflight = static_preflight(scope_index_continuation=True)
    panel_rows, scope_by_neighborhood, _neighborhoods, _state_features, _candidate_features, _candidate_index, _schema_order, input_audit = load_panel_inputs()
    required_view_fields = ("anchor_episode_id", "fact_episode_id", "sham_episode_id",
                            "matched_neutral_episode_id")
    joined_views = 0
    for panel in panel_rows:
        nid = str(panel["neighborhood_id"])
        episode_scope = scope_by_neighborhood[nid]
        for field in required_view_fields:
            episode_id = str(panel[field])
            require(episode_id in episode_scope,
                    f"selected panel episode missing from exact episode scope index: {nid}/{field}")
            joined_views += 1
    require(joined_views == 8_000, f"selected view join cardinality mismatch: {joined_views}")
    target_join = input_audit["exact_world_target_join"]
    require(target_join.get("status") == "EXACT_WORLD_TARGET_JOIN_PASS"
            and target_join.get("neighborhoods") == 2_000
            and target_join.get("fact_map_flip_count") == 2_000,
            "whole-panel exact target join did not pass")
    target_join_receipt = OUTPUT / "exact-world-target-join-audit-v02.json"
    write_json(target_join_receipt, {
        **target_join,
        "selected_view_episode_join_count": joined_views,
        "scope_lookup_key": "episode_id within neighborhood_id",
        "role_lookup_used_only_for_semantic_checks": True,
        "head_payloads_deserialized": False,
        "predictions_created": False,
    })
    workspace_receipt = {
        "status": "P_R2_SCOPE_INDEX_PREFLIGHT_PASS_NO_HEADS",
        "opening_count": 1,
        "opening_receipt_sha256": sha256_file(OPENING_RECEIPT),
        "prior_failures": {
            "target_schema_failure_sha256": sha256_file(FIRST_FAILURE_RECEIPT),
            "scope_index_failure_sha256": sha256_file(SCOPE_INDEX_FAILURE_RECEIPT),
            "empty_prediction_archive_sha256": sha256_file(SCOPE_INDEX_EMPTY_PREDICTION_ARCHIVE),
        },
        "training_seal_sha256": preflight["training_seal_sha256"],
        "checkpoint_hash_tree_sha256": preflight["checkpoint_hash_tree_sha256"],
        "panel_ready_manifest_sha256": preflight["panel_ready_manifest_sha256"],
        "feature_receipt_sha256": preflight["feature_receipt_sha256"],
        "scope_index_correction_sha256": sha256_file(EVALUATOR_CORRECTION),
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "target_join_adapter_sha256": sha256_file(TARGET_JOIN_SOURCE),
        "panel_input_audit": input_audit,
        "selected_view_episode_join_count": joined_views,
        "head_payloads_deserialized": False,
        "predictions_created": False,
        "newtight": False,
        "phoenix_access": False,
    }
    require(not EVALUATION_SCOPE_INDEX_PREFLIGHT.exists()
            and not SCOPE_INDEX_VERIFICATION.exists(),
            "scope-index preflight artifacts already exist; refusing overwrite")
    write_json(EVALUATION_SCOPE_INDEX_PREFLIGHT, workspace_receipt)
    write_json(SCOPE_INDEX_VERIFICATION, {
        **workspace_receipt,
        "input_verification_sha256": sha256_file(EVALUATION_SCOPE_INDEX_PREFLIGHT),
        "exact_world_target_join_audit_sha256": sha256_file(target_join_receipt),
    })
    print(json.dumps({
        "status": "P_R2_SCOPE_INDEX_PREFLIGHT_PASS_NO_HEADS",
        "selected_view_episode_join_count": joined_views,
        "target_join_audit_sha256": sha256_file(target_join_receipt),
        "preflight_sha256": sha256_file(SCOPE_INDEX_VERIFICATION),
        "head_payloads_deserialized": False,
        "predictions_created": False,
    }, separators=(",", ":"), flush=True))


def execute(*, continuation: bool = False) -> None:
    preflight = static_preflight(scope_index_continuation=continuation,
                                 require_scope_index_preflight=continuation)
    stage = "opened_fresh_panel_input_validation"
    started = time.perf_counter()
    opening_sha: str | None = None
    try:
        if continuation:
            require(not SCOPE_INDEX_RECEIPT.exists(),
                    "scope-index continuation receipt already exists; refusing overwrite")
            opening_sha = sha256_file(OPENING_RECEIPT)
            write_json(SCOPE_INDEX_RECEIPT, {
                "status": "P_R2_PREINFERENCE_SCOPE_INDEX_RECOVERY_CONTINUATION",
                "opening_count": 1,
                "original_opening_receipt_sha256": opening_sha,
                "original_failure_receipt_sha256": sha256_file(FIRST_FAILURE_RECEIPT),
                "prior_scope_failure_receipt_sha256": sha256_file(SCOPE_INDEX_FAILURE_RECEIPT),
                "continuation_preflight_sha256": sha256_file(SCOPE_INDEX_VERIFICATION),
                "target_join_correction_sha256": sha256_file(EVALUATOR_CORRECTION),
                "heads_loaded_before_continuation": False, "predictions_created_before_continuation": False,
                "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            })
        else:
            opening_sha = record_panel_opening(preflight)
        panel_rows, scope, neighborhoods, state_features, candidate_features, candidate_index, schema_order, input_audit = load_panel_inputs()
        target_join_receipt = OUTPUT / "exact-world-target-join-audit-v02.json"
        require(target_join_receipt.is_file()
                and read_json(target_join_receipt).get("status") == input_audit["exact_world_target_join"].get("status")
                and read_json(target_join_receipt).get("target_vectors_sha256")
                == input_audit["exact_world_target_join"].get("target_vectors_sha256")
                and read_json(target_join_receipt).get("selected_view_episode_join_count") == 8_000,
                "whole-panel target/episode index audit differs from pre-head preflight")
        evaluator = import_module(METRIC_SOURCE, "jev_r2_frozen_metric_evaluator")
        probe = import_module(PROBE_SOURCE, "jev_r2_frozen_probe")
        checkpoint_lookup = {(int(row["seed"]), str(row["arm"]), int(row["global_step"])): row
                             for row in preflight["checkpoint_inventory"]}
        template_map = {int(row["seed"]): row for row in preflight["template_inventory"]}
        pred_path = OUTPUT / "raw-predictions-v01.jsonl"
        if pred_path.exists() and (not continuation or pred_path.stat().st_size != 0):
            raise FileExistsError("R2 prediction output already exists; no evaluation retry")
        rows_by_cell: dict[str, int] = {}
        checkpoint_records: list[dict[str, Any]] = []
        with pred_path.open("a" if continuation else "x", encoding="utf-8", newline="\n") as stream:
            for seed in SEEDS:
                template = template_map[seed]
                head, state_sha = load_head(Path(template["path"]), template["sha256"], seed=seed,
                                            arm="COMMON_INIT", step=0, probe=probe)
                try:
                    raw, _diagnostics = evaluator.metrics_for_run(
                        seed, "COMMON_INIT", head, panel_rows, scope, neighborhoods,
                        state_features, candidate_features, candidate_index, schema_order, DEVICE,
                    )
                    require(len(raw) == 8_000, f"common initialization output count mismatch: {seed}")
                    for row in raw:
                        row.update({"global_step": 0, "checkpoint_label": "COMMON_INIT",
                                    "checkpoint_sha256": template["sha256"], "head_state_sha256": state_sha})
                        validate_prediction(row)
                        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    stream.flush(); os.fsync(stream.fileno())
                    cell = f"{seed}/COMMON_INIT/0"
                    rows_by_cell[cell] = len(raw)
                    checkpoint_records.append({"seed": seed, "arm": "COMMON_INIT", "global_step": 0,
                                               "checkpoint_sha256": template["sha256"], "head_state_sha256": state_sha})
                    print(json.dumps({"event": "r2_cell_predictions_written", "seed": seed, "arm": "COMMON_INIT",
                                      "global_step": 0, "rows": len(raw),
                                      "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")),
                          flush=True)
                finally:
                    del head
                    torch.cuda.empty_cache()
                for step in CHECKPOINT_STEPS:
                    epoch = 1 if step == 40 else 2 if step == 80 else 3
                    for arm in ARMS:
                        entry = checkpoint_lookup[(seed, arm, step)]
                        head, state_sha = load_head(Path(entry["path"]), entry["sha256"], seed=seed,
                                                    arm=arm, step=step, probe=probe,
                                                    expected_state_sha=entry["head_sha256"])
                        try:
                            raw, _diagnostics = evaluator.metrics_for_run(
                                seed, arm, head, panel_rows, scope, neighborhoods,
                                state_features, candidate_features, candidate_index, schema_order, DEVICE,
                            )
                            require(len(raw) == 8_000, f"prediction count mismatch: {seed}/{arm}/{step}")
                            for row in raw:
                                row.update({"global_step": step, "epoch": epoch,
                                            "checkpoint_label": f"step-{step:03d}",
                                            "checkpoint_sha256": entry["sha256"], "head_state_sha256": state_sha})
                                validate_prediction(row)
                                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                            stream.flush(); os.fsync(stream.fileno())
                            cell = f"{seed}/{arm}/{step}"
                            rows_by_cell[cell] = len(raw)
                            checkpoint_records.append({"seed": seed, "arm": arm, "global_step": step,
                                                       "checkpoint_sha256": entry["sha256"],
                                                       "head_state_sha256": state_sha})
                            print(json.dumps({"event": "r2_cell_predictions_written", "seed": seed, "arm": arm,
                                              "global_step": step, "rows": len(raw),
                                              "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")),
                                  flush=True)
                        finally:
                            del head
                            torch.cuda.empty_cache()
        require(len(rows_by_cell) == 381 and sum(rows_by_cell.values()) == EXPECTED_ROWS
                and all(count == 8_000 for count in rows_by_cell.values()),
                f"R2 response matrix incomplete: {len(rows_by_cell)} cells / {sum(rows_by_cell.values())} rows")
        expected_keys = [f"{seed}/{arm}/{step}" for seed, arm, step in expected_cells()]
        require(list(rows_by_cell) == expected_keys, "R2 inference cell order differs from the sealed contract")
        prediction_sha = sha256_file(pred_path)
        tree = {
            "status": "P_R2_COMPLETE_RAW_PREDICTION_MATRIX_SEALED_BEFORE_METRICS",
            "identity": "v0.8P-R2 late-transition localization fresh-panel trajectory evaluation",
            "prediction_rows": EXPECTED_ROWS, "cell_count": 381, "rows_by_cell": rows_by_cell,
            "raw_predictions": {"path": str(pred_path), "sha256": prediction_sha, "bytes": pred_path.stat().st_size},
            "checkpoint_cells": checkpoint_records,
            "training_seal_sha256": preflight["training_seal_sha256"],
            "checkpoint_hash_tree_sha256": preflight["checkpoint_hash_tree_sha256"],
            "panel_opening_receipt_sha256": opening_sha,
            "preinference_recovery_receipt_sha256": sha256_file(SCOPE_INDEX_RECEIPT)
            if continuation else None,
            "exact_world_target_join_audit_sha256": sha256_file(target_join_receipt),
            "panel_ready_manifest_sha256": preflight["panel_ready_manifest_sha256"],
            "feature_receipt_sha256": preflight["feature_receipt_sha256"],
            "opened_input_audit": input_audit,
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        tree_path = OUTPUT / "raw-prediction-hash-tree-v01.json"
        write_json(tree_path, tree)
        write_json(OUTPUT / "inference-receipt-v01.json", {
            "status": "P_R2_ALL_381_CELLS_INFERRED_AND_RAW_PREDICTIONS_SEALED",
            "opening_count": 1, "prediction_hash_tree_sha256": sha256_file(tree_path),
            "prediction_sha256": prediction_sha, "prediction_rows": EXPECTED_ROWS,
            "checkpoint_cells": 381, "trained_checkpoints": 378, "common_init_baselines": 3,
            "preinference_recovery_receipt_sha256": sha256_file(SCOPE_INDEX_RECEIPT)
            if continuation else None,
            "exact_world_target_join_audit_sha256": sha256_file(target_join_receipt),
            "predictions_before_metrics": True, "checkpoint_selection": False, "training": False,
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "elapsed_seconds": time.perf_counter() - started,
        })
        print(json.dumps({"status": "P_R2_RAW_PREDICTIONS_SEALED", "rows": EXPECTED_ROWS,
                          "sha256": prediction_sha, "tree_sha256": sha256_file(tree_path),
                          "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")), flush=True)
    except BaseException as exc:
        failure_path = OUTPUT / ("evaluation-failure-receipt-v03.json" if continuation
                                 else "evaluation-failure-receipt-v01.json")
        if OUTPUT.exists() and not failure_path.exists():
            write_json(failure_path, {
                "status": "P_R2_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "panel_opening_receipt_sha256": opening_sha,
                "preinference_recovery_receipt_sha256": sha256_file(SCOPE_INDEX_RECEIPT)
                if continuation and SCOPE_INDEX_RECEIPT.exists() else None,
                "prediction_file_exists": (OUTPUT / "raw-predictions-v01.jsonl").exists(),
                "automatic_retry": False, "newtight": False, "phoenix_access": False,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        raise


def validate_prediction(row: dict[str, Any]) -> None:
    prediction = np.asarray(row["prediction"], dtype=np.float64)
    gold = np.asarray(row["gold"], dtype=np.float64)
    require(prediction.shape == (4,) and gold.shape == (4,) and np.isfinite(prediction).all()
            and np.isfinite(gold).all() and abs(float(prediction.sum()) - 1.0) <= 1e-6
            and abs(float(gold.sum()) - 1.0) <= 1e-12,
            f"non-finite/non-normalized prediction or target row: {row.get('neighborhood_id')}/{row.get('view')}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--scope-index-preflight-only", action="store_true")
    parser.add_argument("--continue-preinference-scope-index", action="store_true")
    args = parser.parse_args()
    if args.scope_index_preflight_only:
        scope_index_preflight_only()
        return 0
    if args.continue_preinference_scope_index:
        execute(continuation=True)
        return 0
    if args.preflight_only:
        result = static_preflight()
        require(not EVALUATION_PREFLIGHT_RECEIPT.exists(),
                "evaluation preflight receipt already exists; refusing overwrite")
        write_json(EVALUATION_PREFLIGHT_RECEIPT, result)
        print(json.dumps({"status": result["status"],
                          "receipt": str(EVALUATION_PREFLIGHT_RECEIPT),
                          "receipt_sha256": sha256_file(EVALUATION_PREFLIGHT_RECEIPT),
                          "panel_records_or_targets_parsed": False,
                          "head_payloads_deserialized": False,
                          "predictions_created": False}, separators=(",", ":")))
        return 0
    static_preflight()
    execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
