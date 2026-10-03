"""Post-hoc, no-training inference over every sealed v0.8N head epoch."""

from __future__ import annotations

import argparse
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


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "experiments/jev-information-density-v08n/phase_b/o"
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
E1_SOURCE = PHASE / "e1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
E1_BASIS = Path(r"D:\codex-runs\jev-information-density-v08n-e1\v0.8N-E1-heldout-candidate-basis-v01")
E1_RESULT = Path(r"D:\codex-runs\jev-information-density-v08n-e1\v0.8N-E1-postregistered-repaired-heldout-evaluation-v01")
OUTPUT = Path(r"D:\codex-runs\jev-information-density-v08o\v0.8O-capability-trajectory-cartography-v01")
RUN_CONTRACT = SOURCE / "phase-b-o-run-contract-v01.json"
ANALYSIS_CONTRACT = SOURCE / "phase-b-o-analysis-contract-v01.json"

RUN_CONTRACT_SHA256 = "65ef673fb488758de23043656ecfb85bce9035919f0a1acd3a1b7668d153d5a3"
ANALYSIS_CONTRACT_SHA256 = "d3b022f20c16dd11e0923b8d52940d6f6d88cde5d68dfe739085213c13ecb4bf"
TRAINING_SEAL_SHA256 = "43932fc963b150167972e81b1c1bb93f6989e9b93faa65ab1eee3ecf55c7b727"
CHECKPOINT_TREE_SHA256 = "add6dfd013c936b100e7cbdb205018bf91b95e91ed11ca854b26aed998c66923"
PANEL_SEAL_SHA256 = "425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614"
PANEL_TREE_SHA256 = "fc0adf7f8d1b9a10914dd9aa85282a42b0cd4bbe185f8b09710498b556d0f08f"
E1_RESULT_SEAL_SHA256 = "a23b3a6dc90a739888ae8d1cab440ac6c8f6ed23dd12b26c1bfd7786cd56ce68"
E1_BASIS_SEAL_SHA256 = "f3469f326200d1c097969be1d36741e2b01cc7542911ce79c5b240dc5b6c2b33"
E1_JOIN_SHA256 = "5d9b851b61a305091a6489df6f7a3b09b02dd70c043d2554f17e9487f6544003"
FROZEN_EVALUATOR_SHA256 = "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"
FROZEN_ANALYZER_SHA256 = "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70"
FROZEN_PROBE_SHA256 = "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1"
DEVICE = "cuda:0"
SEEDS = (20260927, 20260928, 20260929)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
EPOCHS = (0, 1, 2, 3)
EXPECTED_PREDICTIONS = 288_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def import_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def static_preflight() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"v0.8O output identity exists; no repeat opening: {OUTPUT}")
    if not RUN_CONTRACT.is_file() or not ANALYSIS_CONTRACT.is_file():
        raise FileNotFoundError("v0.8O run or analysis contract is missing")
    if RUN_CONTRACT_SHA256 and sha256_file(RUN_CONTRACT) != RUN_CONTRACT_SHA256:
        raise RuntimeError("v0.8O run contract hash mismatch")
    if sha256_file(ANALYSIS_CONTRACT) != ANALYSIS_CONTRACT_SHA256:
        raise RuntimeError("v0.8O analysis contract hash mismatch")

    run_contract = read_json(RUN_CONTRACT)
    analysis_contract = read_json(ANALYSIS_CONTRACT)
    if run_contract["authorization"]["opening_count"] != 3 or run_contract["evaluation_design"]["expected_prediction_rows"] != EXPECTED_PREDICTIONS:
        raise RuntimeError("v0.8O evaluation cardinality/opening contract drift")
    if analysis_contract["input_requirements"]["rows"] != EXPECTED_PREDICTIONS:
        raise RuntimeError("v0.8O analysis row contract drift")

    # The frozen E1 verifier checks all parent seals and byte-hashes all 81
    # training-tree entries without deserializing a head. Redirect only its
    # output-exists guard to this fresh O identity.
    e1_runner = import_module(E1_SOURCE / "run_e1_postregistered_evaluation_v01.py", "jev_v08o_e1_parent_verifier")
    e1_runner.OUTPUT = OUTPUT
    e1_parent_check = e1_runner.static_preflight()
    if e1_parent_check["training_hash_tree_entries_rehashed"] != 81:
        raise RuntimeError("the parent verifier did not rehash all 81 sealed training entries")

    # Bind the full epoch inventory and three initialization templates by
    # metadata and file bytes only. No checkpoint payload is deserialized here.
    tree_path = RUN / "checkpoint-hash-tree.json"
    tree = read_json(tree_path)
    training_seal = read_json(RUN / "training-seal-manifest.json")
    if sha256_file(tree_path) != CHECKPOINT_TREE_SHA256 or sha256_file(RUN / "training-seal-manifest.json") != TRAINING_SEAL_SHA256:
        raise RuntimeError("training seal or checkpoint tree drift")
    checkpoint_entries = [item for item in tree["entries"] if Path(item["path"]).name in ("epoch-1.pt", "epoch-2.pt", "epoch-3-terminal.pt")]
    if len(checkpoint_entries) != 27:
        raise RuntimeError(f"expected 27 sealed epoch checkpoints, found {len(checkpoint_entries)}")
    checkpoint_map: dict[str, dict[str, Any]] = {}
    epoch_name = {1: "epoch-1.pt", 2: "epoch-2.pt", 3: "epoch-3-terminal.pt"}
    for seed in SEEDS:
        for arm in ARMS:
            integrity_path = RUN / "runs" / f"seed-{seed}" / arm / "run-integrity.json"
            integrity = read_json(integrity_path)
            if integrity.get("status") != "TRAINING_COMPLETE_UNEVALUATED" or integrity.get("evaluation_access") is not False:
                raise RuntimeError(f"run status/boundary drift: {seed}/{arm}")
            expected_init = integrity["initial_head_sha256"]
            if not expected_init:
                raise RuntimeError(f"missing initialization digest: {seed}/{arm}")
            for epoch in (1, 2, 3):
                path = RUN / "runs" / f"seed-{seed}" / arm / epoch_name[epoch]
                entry = next((row for row in checkpoint_entries if Path(row["path"]).resolve() == path.resolve()), None)
                run_item = next((row for row in integrity["epoch_checkpoints"] if row["path"] == path.name), None)
                if entry is None or run_item is None or entry["sha256"] != run_item["sha256"]:
                    raise RuntimeError(f"epoch checkpoint is not consistently sealed: {seed}/{arm}/{epoch}")
                if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
                    raise RuntimeError(f"epoch checkpoint bytes differ from training seal: {seed}/{arm}/{epoch}")
                key = f"{seed}/{arm}/epoch-{epoch}"
                checkpoint_map[key] = {"path": str(path), "sha256": entry["sha256"], "bytes": entry["bytes"], "seed": seed, "arm": arm, "epoch": epoch, "initial_head_sha256": expected_init}
    if len(checkpoint_map) != 27:
        raise RuntimeError("epoch checkpoint identity map is incomplete")

    initial_map: dict[str, dict[str, Any]] = {}
    for seed in SEEDS:
        template_path = RUN / "head-templates" / f"seed-{seed}.pt"
        entry = next((row for row in tree["entries"] if Path(row["path"]).resolve() == template_path.resolve()), None)
        if entry is None or template_path.stat().st_size != entry["bytes"] or sha256_file(template_path) != entry["sha256"]:
            raise RuntimeError(f"shared initialization template is not sealed: {seed}")
        run_hashes = {read_json(RUN / "runs" / f"seed-{seed}" / arm / "run-integrity.json")["initial_head_sha256"] for arm in ARMS}
        if len(run_hashes) != 1:
            raise RuntimeError(f"paired arm initializations differ for seed {seed}")
        text_hashes = {(RUN / "runs" / f"seed-{seed}" / arm / "initial-head-template.sha256").read_text(encoding="ascii").strip() for arm in ARMS}
        if len(text_hashes) != 1 or text_hashes != run_hashes:
            raise RuntimeError(f"paired initialization sidecars disagree for seed {seed}")
        initial_map[str(seed)] = {"path": str(template_path), "sha256": entry["sha256"], "bytes": entry["bytes"], "state_sha256": next(iter(run_hashes))}

    panel_seal_path = PANEL / "seal/seal-manifest.json"
    panel_tree_path = PANEL / "seal/heldout-panel-hash-tree.json"
    firewall_path = PANEL / "seal/evaluation-firewall-lock.json"
    if sha256_file(panel_seal_path) != PANEL_SEAL_SHA256 or sha256_file(panel_tree_path) != PANEL_TREE_SHA256:
        raise RuntimeError("held-out panel seal/hash tree identity drift")
    if sha256_file(firewall_path) != "79d25ac82fba1bc6332e16d8bc5f877fadd11cccaed5ef3f07eacfe5e1877da2":
        raise RuntimeError("held-out panel firewall record drift")
    if sha256_file(E1_RESULT / "e1-result-seal-v01.json") != E1_RESULT_SEAL_SHA256:
        raise RuntimeError("E1 result seal identity drift")
    if sha256_file(E1_BASIS / "e1-candidate-basis-seal-v01.json") != E1_BASIS_SEAL_SHA256:
        raise RuntimeError("E1 candidate basis seal identity drift")
    if sha256_file(E1_BASIS / "target-free-schema-candidate-join-v01.jsonl") != E1_JOIN_SHA256:
        raise RuntimeError("E1 target-free exact join identity drift")

    source_bindings = {
        "runner": SOURCE / "run_v08o_trajectory_inference_v01.py",
        "analysis": SOURCE / "analyze_v08o_trajectory_v01.py",
        "frozen_evaluator": ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py",
        "frozen_analyzer": ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
        "head_definition": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
    }
    source_hashes = {key: sha256_file(path) for key, path in source_bindings.items() if path.is_file()}
    if set(source_hashes) != set(source_bindings):
        raise FileNotFoundError("a bound O or frozen implementation source is missing")
    if source_hashes["frozen_evaluator"] != FROZEN_EVALUATOR_SHA256 or source_hashes["frozen_analyzer"] != FROZEN_ANALYZER_SHA256 or source_hashes["head_definition"] != FROZEN_PROBE_SHA256:
        raise RuntimeError("frozen evaluator, metric, or head source drift")

    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("frozen E1 inference runtime/device unavailable or changed")
    if torch.backends.cuda.matmul.allow_tf32 is not False:
        raise RuntimeError("TF32 setting differs from frozen E1 inference runtime")
    runtime = {
        "python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__,
        "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "device_identity": torch.cuda.get_device_name(0), "runtime_device_locator": DEVICE,
        "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_tf32": torch.backends.cudnn.allow_tf32,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    return {
        "status": "V08O_METADATA_PREFLIGHT_PASS_NO_HEAD_DESERIALIZATION",
        "run_contract_sha256": sha256_file(RUN_CONTRACT), "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
        "source_hashes": source_hashes, "runtime": runtime,
        "parent_e1_verifier_status": e1_parent_check["status"],
        "training_seal_sha256": TRAINING_SEAL_SHA256, "checkpoint_hash_tree_sha256": CHECKPOINT_TREE_SHA256,
        "checkpoint_count": len(checkpoint_map), "checkpoints": [checkpoint_map[key] for key in sorted(checkpoint_map)],
        "initialization_templates": initial_map, "panel_seal_sha256": PANEL_SEAL_SHA256,
        "panel_hash_tree_sha256": PANEL_TREE_SHA256, "e1_result_seal_sha256": E1_RESULT_SEAL_SHA256,
        "candidate_basis_seal_sha256": E1_BASIS_SEAL_SHA256, "join_manifest_sha256": E1_JOIN_SHA256,
        "panel_bodies_or_targets_read": False, "checkpoint_payloads_deserialized": False,
        "predictions_or_o_metrics_created": False, "opening_count_before_o": 2,
    }


def record_opening(preflight: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(OUTPUT / "preinference-verification-v01.json", preflight)
    receipt = {
        "status": "V08O_POSTHOC_EVALUATION_OPENING_AUTHORIZED_AND_RECORDED",
        "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
        "opening_count": 3,
        "prior_openings": [
            {"count": 1, "status": "ORIGINAL_PHASE_B_EVALUATOR_FAILED_BEFORE_HEAD_LOAD", "receipt_sha256": "e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0"},
            {"count": 2, "status": "POSTREGISTERED_E1_TERMINAL_EVALUATION_SEALED", "receipt_sha256": "8400f4013ad34670d540dcfa6a5ba0a3796465a5123b4995e2198af60b74c6ca"}
        ],
        "authorization_source": "explicit user authorization in the active conversation",
        "run_contract_sha256": preflight["run_contract_sha256"],
        "analysis_contract_sha256": preflight["analysis_contract_sha256"],
        "preinference_verification_sha256": sha256_file(OUTPUT / "preinference-verification-v01.json"),
        "checkpoint_count": 27, "initialization_template_count": 3,
        "checkpoint_inventory": preflight["checkpoints"],
        "initialization_templates": preflight["initialization_templates"],
        "heldout_panel_seal_sha256": PANEL_SEAL_SHA256,
        "candidate_basis_seal_sha256": E1_BASIS_SEAL_SHA256,
        "target_free_join_sha256": E1_JOIN_SHA256,
        "metric_implementation_hashes": {
            "frozen_evaluator": preflight["source_hashes"]["frozen_evaluator"],
            "frozen_analyzer": preflight["source_hashes"]["frozen_analyzer"],
            "head_definition": preflight["source_hashes"]["head_definition"],
            "o_runner": preflight["source_hashes"]["runner"],
            "o_analysis": preflight["source_hashes"]["analysis"]
        },
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        "o_predictions_or_metrics_exist_at_opening": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat()
    }
    write_json_exclusive(OUTPUT / "v08o-opening-receipt-v01.json", receipt)


def load_checkpoint(path: Path, seed: int, arm: str, epoch: int, expected_file_hash: str, expected_init_hash: str) -> tuple[dict[str, torch.Tensor], str]:
    if sha256_file(path) != expected_file_hash:
        raise RuntimeError(f"checkpoint changed after O preflight: {seed}/{arm}/{epoch}")
    if epoch == 0:
        payload = torch.load(path, map_location="cpu", weights_only=True)
        if payload.get("seed") != seed or payload.get("state_sha256") != expected_init_hash:
            raise RuntimeError(f"initialization template identity mismatch: seed {seed}")
        state = payload.get("state_dict")
    else:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("seed") != seed or payload.get("arm") != arm or payload.get("epoch") != epoch:
            raise RuntimeError(f"checkpoint payload identity mismatch: {seed}/{arm}/{epoch}")
        if payload.get("initial_head_sha256") != expected_init_hash:
            raise RuntimeError(f"checkpoint paired initialization digest mismatch: {seed}/{arm}/{epoch}")
        state = payload.get("head_state")
    if not isinstance(state, dict) or state_digest(state) != (expected_init_hash if epoch == 0 else payload.get("terminal_head_sha256")):
        raise RuntimeError(f"head-state digest mismatch: {seed}/{arm}/{epoch}")
    return state, state_digest(state)


def execute() -> None:
    preflight = static_preflight()
    record_opening(preflight)
    stage = "opened_panel_input_validation"
    try:
        e1_runner = import_module(E1_SOURCE / "run_e1_postregistered_evaluation_v01.py", "jev_v08o_e1_input_loader")
        panel_rows, scope, neighborhoods, eval_features, candidate_features, candidate_index, schema_ids, panel_audit = e1_runner.verify_opened_panel()
        write_json_exclusive(OUTPUT / "opened-input-validation-v01.json", {
            "status": "V08O_E1_INPUTS_AND_SCHEMA_JOINS_PASS",
            "opening_receipt_sha256": sha256_file(OUTPUT / "v08o-opening-receipt-v01.json"),
            **panel_audit
        })
        if len(panel_rows) != 2000 or tuple(eval_features.shape) != (22000, 2048) or tuple(candidate_features.shape) != (16, 2048):
            raise RuntimeError("opened E1 input dimensions differ from sealed contract")

        stage = "all_epoch_checkpoint_inference"
        evaluator = import_module(PHASE / "evaluate_phase_b_v01.py", "jev_v08o_frozen_evaluator")
        probe = import_module(ROOT / "experiments/jev-frozen-readout-v01/probe.py", "jev_v08o_frozen_probe")
        device = torch.device(DEVICE)
        eval_features = eval_features.to(device)
        candidate_features = candidate_features.to(device)
        checkpoint_map = {f"{item['seed']}/{item['arm']}/epoch-{item['epoch']}": item for item in preflight["checkpoints"]}
        init_map = preflight["initialization_templates"]
        predictions_path = OUTPUT / "raw-predictions-v01.jsonl"
        diagnostics_path = OUTPUT / "input-geometry-diagnostics-v01.jsonl"
        if predictions_path.exists() or diagnostics_path.exists():
            raise FileExistsError("O raw output already exists; automatic restart is forbidden")
        counts: dict[str, int] = {}
        started = time.perf_counter()
        with predictions_path.open("x", encoding="utf-8", newline="\n") as pred_stream, diagnostics_path.open("x", encoding="utf-8", newline="\n") as diag_stream:
            for seed in SEEDS:
                init = init_map[str(seed)]
                for epoch in EPOCHS:
                    for arm in ARMS:
                        key = f"{seed}/{arm}/epoch-{epoch}"
                        if epoch == 0:
                            path = Path(init["path"])
                            digest = str(init["sha256"])
                            init_digest = str(init["state_sha256"])
                        else:
                            item = checkpoint_map[key]
                            path, digest, init_digest = Path(item["path"]), str(item["sha256"]), str(item["initial_head_sha256"])
                        state, state_hash = load_checkpoint(path, seed, arm, epoch, digest, init_digest)
                        head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
                        head.load_state_dict(state, strict=True)
                        if sum(parameter.numel() for parameter in head.parameters()) != 590_081:
                            raise RuntimeError("head parameter count differs from sealed 590,081")
                        raw_rows, diag_rows = evaluator.metrics_for_run(
                            seed, arm, head, panel_rows, scope, neighborhoods, eval_features,
                            candidate_features, candidate_index, schema_ids, DEVICE
                        )
                        if len(raw_rows) != 8000 or len(diag_rows) != 2000:
                            raise RuntimeError(f"unexpected output count for {key}")
                        for row in raw_rows:
                            row["epoch"] = epoch
                            row["checkpoint_sha256"] = digest
                            row["head_state_sha256"] = state_hash
                            prediction = np.asarray(row["prediction"], dtype=np.float64)
                            if prediction.shape != (4,) or not np.isfinite(prediction).all() or abs(float(prediction.sum()) - 1.0) > 1e-6:
                                raise RuntimeError(f"invalid prediction output in {key}")
                            pred_stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        for row in diag_rows:
                            row["epoch"] = epoch
                            row["checkpoint_sha256"] = digest
                            diag_stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        pred_stream.flush(); os.fsync(pred_stream.fileno())
                        diag_stream.flush(); os.fsync(diag_stream.fileno())
                        counts[key] = len(raw_rows)
                        print(json.dumps({"event": "v08o_cell_predictions_written", "seed": seed, "arm": arm, "epoch": epoch,
                                          "rows": len(raw_rows), "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")), flush=True)
                        del head, state, raw_rows, diag_rows
        count_total = sum(counts.values())
        if len(counts) != 36 or count_total != EXPECTED_PREDICTIONS or any(value != 8000 for value in counts.values()):
            raise RuntimeError(f"incomplete O response matrix: {len(counts)} cells/{count_total} rows")

        # The first aggregate metric analysis happens only after all 288,000
        # prediction rows are durable and the complete prediction tree is sealed.
        prediction_sha = sha256_file(predictions_path)
        diagnostic_sha = sha256_file(diagnostics_path)
        hash_tree = {
            "status": "V08O_ALL_EPOCH_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS",
            "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
            "prediction_rows": count_total, "cell_count": len(counts), "rows_by_cell": counts,
            "files": {
                predictions_path.name: {"sha256": prediction_sha, "bytes": predictions_path.stat().st_size},
                diagnostics_path.name: {"sha256": diagnostic_sha, "bytes": diagnostics_path.stat().st_size}
            },
            "checkpoint_sha256_by_cell": {key: (init_map[str(int(key.split("/")[0]))]["sha256"] if "/epoch-0" in key else checkpoint_map[key]["sha256"]) for key in sorted(counts)},
            "training_seal_sha256": TRAINING_SEAL_SHA256, "checkpoint_hash_tree_sha256": CHECKPOINT_TREE_SHA256,
            "panel_seal_sha256": PANEL_SEAL_SHA256, "candidate_basis_seal_sha256": E1_BASIS_SEAL_SHA256,
            "target_free_join_sha256": E1_JOIN_SHA256,
            "opening_receipt_sha256": sha256_file(OUTPUT / "v08o-opening-receipt-v01.json"),
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat()
        }
        write_json_exclusive(OUTPUT / "raw-prediction-hash-tree-v01.json", hash_tree)
        write_json_exclusive(OUTPUT / "inference-receipt-v01.json", {
            "status": "V08O_27_CHECKPOINTS_PLUS_INITIALIZATION_BASELINES_EVALUATED",
            "opening_count": 3, "prediction_hash_tree_sha256": sha256_file(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "prediction_sha256": prediction_sha, "prediction_rows": count_total,
            "checkpoint_count": 27, "initialization_baseline_cells": 9,
            "checkpoint_selection": False, "training": False,
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "elapsed_seconds": time.perf_counter() - started
        })
        print(json.dumps({"event": "V08O_RAW_PREDICTIONS_SEALED", "rows": count_total,
                          "prediction_sha256": prediction_sha,
                          "tree_sha256": sha256_file(OUTPUT / "raw-prediction-hash-tree-v01.json")}, separators=(",", ":")), flush=True)
    except Exception as exc:
        failure = {
            "status": "V08O_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
            "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
            "opening_receipt_sha256": sha256_file(OUTPUT / "v08o-opening-receipt-v01.json") if (OUTPUT / "v08o-opening-receipt-v01.json").exists() else None,
            "prediction_file_exists": (OUTPUT / "raw-predictions-v01.jsonl").exists(),
            "automatic_retry": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "failed_at_utc": datetime.now(timezone.utc).isoformat()
        }
        if OUTPUT.exists() and not (OUTPUT / "failure-disposition-v01.json").exists():
            write_json_exclusive(OUTPUT / "failure-disposition-v01.json", failure)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--execute-authorized-o", action="store_true")
    args = parser.parse_args()
    if args.preflight_only == args.execute_authorized_o:
        parser.error("choose exactly one of --preflight-only or --execute-authorized-o")
    if args.preflight_only:
        print(json.dumps(static_preflight(), indent=2, ensure_ascii=False))
        return 0
    execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
