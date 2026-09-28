"""Single-opening Q evaluation: seal the full prediction matrix before metrics."""
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
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
TRAIN = RUN / "training"
OUTPUT = RUN / "evaluation"
INSTRUMENT = RUN / "instrument/q-execution-instrument-seal-v01.json"
DEVICE = "cuda:0"
SEEDS = (2540205348, 2603246505, 3565067208)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
CHECKPOINTS = (40, 80, 100, 120)
EXPECTED_PANEL_ROOT = "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a"
EXPECTED = {
    "run": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
    "panel_seal": "161511e6617ee012b3051590b4a9ce747f79a85228c02649e61ca8a10d080ad6",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tensor_sha(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def state_sha(state: dict[str, torch.Tensor]) -> str:
    h = hashlib.sha256()
    for name, value in sorted(state.items()):
        tensor = value.detach().cpu().contiguous()
        h.update(name.encode("utf-8")); h.update(str(tensor.dtype).encode("ascii"))
        h.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
        h.update(memoryview(tensor.numpy()).cast("B"))
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import sealed code: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_instrument() -> dict[str, Any]:
    seal = read_json(INSTRUMENT)
    require(seal.get("status") == "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION", "Q execution instrument status mismatch")
    root_text = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(seal["entries"], key=lambda x: x["path"]))
    require(hashlib.sha256(root_text.encode("utf-8")).hexdigest() == seal["root_sha256"], "Q execution instrument tree digest mismatch")
    for row in seal["entries"]:
        path = Path(row["path"])
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"Q sealed instrument drift: {path}")
    return seal


def static_preflight() -> dict[str, Any]:
    require(not OUTPUT.exists(), f"Q evaluation identity already exists; refusing repeat: {OUTPUT}")
    instrument = verify_instrument()
    for name, digest in EXPECTED.items():
        path = {
            "run": Q / "contracts/q-run-contract-v02.json",
            "analysis": Q / "contracts/q-analysis-contract-v02.json",
            "addendum": Q / "contracts/q-execution-addendum-v01.json",
            "panel_seal": PANEL / "seals/q-panel-phase-terminal-seal-v01.json",
            "probe": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        }[name]
        require(sha(path) == digest, f"Q evaluation parent identity mismatch: {name}")
    panel_seal = read_json(PANEL / "seals/q-panel-phase-terminal-seal-v01.json")
    require(panel_seal.get("root_sha256") == EXPECTED_PANEL_ROOT and panel_seal.get("head_initialization") is False and panel_seal.get("training") is False, "Q panel seal or pre-opening state changed")
    require(panel_seal.get("heldout_inference") is False, "Q panel was already evaluated")
    require(len(panel_seal.get("entries", [])) == 30, "Q panel terminal tree entry count mismatch")
    for row in panel_seal["entries"]:
        path = PANEL / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"Q held-out sealed input mismatch: {row['path']}")

    seal = read_json(TRAIN / "training-seal-manifest.json")
    tree = read_json(TRAIN / "checkpoint-hash-tree.json")
    require(seal.get("status") == "Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED" and seal.get("run_count") == 12 and seal.get("trained_checkpoint_count") == 48 and seal.get("sealed_object_count") == 51, "Q training seal is incomplete")
    require(seal.get("evaluation_panel_opened") is False and seal.get("evaluation_feedback") is False, "Q training seal reports panel access")
    require(seal.get("execution_instrument_root_sha256") == instrument["root_sha256"], "Q training seal/instrument root mismatch")
    require(tree.get("trained_checkpoint_count") == 48 and tree.get("initial_template_count") == 3 and len(tree.get("entries", [])) == seal.get("entry_count", len(tree.get("entries", []))), "Q checkpoint tree counts mismatch")
    for row in tree["entries"]:
        path = TRAIN / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"Q training tree artifact mismatch: {row['path']}")
    require(seal.get("checkpoint_tree_sha256") == sha(TRAIN / "checkpoint-hash-tree.json"), "Q training seal does not bind checkpoint tree")
    require(seal.get("execution_instrument_root_sha256") == instrument["root_sha256"], "Q training seal/instrument root mismatch")
    require(torch.__version__ == "2.11.0+cu128" and torch.cuda.is_available() and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080" and torch.version.cuda == "12.8" and torch.backends.cuda.matmul.allow_tf32 is False, "Q frozen inference runtime/device mismatch")
    return {
        "status": "Q_PREINFERENCE_IDENTITIES_AND_CHECKPOINT_BYTES_PASS",
        "instrument_root_sha256": instrument["root_sha256"],
        "panel_root_sha256": panel_seal["root_sha256"],
        "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
        "checkpoint_tree_sha256": sha(TRAIN / "checkpoint-hash-tree.json"),
        "training_tree_entries_rehashed": len(tree["entries"]),
        "trained_checkpoints": 48,
        "initial_templates": 3,
        "runtime": {"python": platform.python_version(), "executable": sys.executable, "torch": torch.__version__, "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(), "device": torch.cuda.get_device_name(0)},
        "panel_bodies_or_targets_parsed": False,
        "head_payloads_deserialized": False,
    }


def record_opening(preflight: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json(OUTPUT / "preinference-verification-v01.json", preflight)
    write_json(OUTPUT / "q-panel-opening-receipt-v01.json", {
        "status": "Q_FRESH_PANEL_OPENED_AFTER_COMPLETE_TRAINING_SEAL",
        "opening_count": 1,
        "authorization_source": "explicit user authorization in the current task thread",
        "authorization_scope": "all twelve Q runs, complete sealed prediction matrix, frozen analysis; no NewTight, legacy evaluation, or Phoenix",
        "training_seal_sha256": preflight["training_seal_sha256"],
        "checkpoint_tree_sha256": preflight["checkpoint_tree_sha256"],
        "panel_root_sha256": preflight["panel_root_sha256"],
        "instrument_root_sha256": preflight["instrument_root_sha256"],
        "predictions_or_metrics_exist_at_opening": False,
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    })


def opened_panel_inputs() -> tuple[list[dict[str, Any]], torch.Tensor, torch.Tensor, list[dict[str, Any]], dict[str, Any]]:
    scope_path = PANEL / "panel/panel-feature-scope.jsonl"
    state_manifest_path = PANEL / "features/q-state-feature-manifest.jsonl"
    candidate_manifest_path = PANEL / "features/q-candidate-feature-manifest.jsonl"
    state_path = PANEL / "features/q-state-features.pt"
    candidate_path = PANEL / "features/q-candidate-features.pt"
    selected_path = PANEL / "matching/matched-neutral-selection.jsonl"
    join_path = PANEL / "matching/whole-panel-candidate-join.jsonl"
    seal = read_json(PANEL / "seals/q-panel-phase-terminal-seal-v01.json")
    sealed = {row["path"]: row for row in seal["entries"]}
    paths = [scope_path, state_manifest_path, candidate_manifest_path, state_path, candidate_path, selected_path, join_path]
    for path in paths:
        relative = path.relative_to(PANEL).as_posix()
        row = sealed.get(relative)
        require(row is not None and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"Q opened panel input not bound by seal: {relative}")

    scope = read_jsonl(scope_path)
    state_manifest = read_jsonl(state_manifest_path)
    candidate_manifest = read_jsonl(candidate_manifest_path)
    selected = read_jsonl(selected_path)
    joins = read_jsonl(join_path)
    state_pack = torch.load(state_path, map_location="cpu", weights_only=True)
    candidate_pack = torch.load(candidate_path, map_location="cpu", weights_only=True)
    state = state_pack["features"]
    candidates = candidate_pack["features"]
    require(len(scope) == len(state_manifest) == 22_000 and len(candidate_manifest) == 16 and len(selected) == 2_000 and len(joins) == 8_000, "Q opened panel object counts differ from contract")
    require(tuple(state.shape) == (22_000, 2048) and state.dtype == torch.float32 and state.is_contiguous(), "Q held-out feature tensor shape/dtype mismatch")
    require(tuple(candidates.shape) == (16, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous(), "Q candidate tensor shape/dtype mismatch")
    require(torch.isfinite(state).all().item() and torch.isfinite(candidates).all().item(), "Q panel features contain nonfinite values")
    require(state_pack.get("scope_sha256") == sha(scope_path) and state_pack.get("feature_key") == "mean_full@16", "Q panel-state tensor scope binding mismatch")
    expected_candidate_ids = [row["candidate_semantic_id"] for row in candidate_manifest]
    require(candidate_pack.get("candidate_ids") == expected_candidate_ids, "Q candidate tensor ID order differs from feature manifest")
    require(tensor_sha(state) == read_json(PANEL / "features/q-feature-extraction-receipt.json")["state_tensor"]["tensor_sha256"], "Q state tensor content hash mismatch")
    require(tensor_sha(candidates) == read_json(PANEL / "features/q-feature-extraction-receipt.json")["candidate_tensor"]["tensor_sha256"], "Q candidate tensor content hash mismatch")
    require([row.get("index") for row in scope] == list(range(22_000)) and [row.get("index") for row in state_manifest] == list(range(22_000)), "Q held-out scope/index order mismatch")
    for index, (identity, feature) in enumerate(zip(scope, state_manifest, strict=True)):
        for field in ("index", "neighborhood_id", "family_slug", "role", "episode_id", "input_sha256"):
            if field == "family_slug":
                require(identity.get(field) == feature.get(field), f"Q state feature family binding mismatch at row {index}")
            else:
                require(identity.get(field) == feature.get(field), f"Q state feature identity mismatch at row {index}/{field}")
        require(tensor_sha(state[index]) == feature.get("feature_sha256"), f"Q state feature row hash mismatch: {index}")
    for index, row in enumerate(candidate_manifest):
        require(row.get("index") == index and tensor_sha(candidates[index]) == row.get("feature_sha256"), f"Q candidate feature row hash mismatch: {index}")

    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for row in scope:
        nid = str(row["neighborhood_id"])
        require(nid not in groups or str(row["role"]) not in groups[nid], f"duplicate Q neighborhood role: {nid}/{row['role']}")
        groups.setdefault(nid, {})[str(row["role"])] = row
    require(len(groups) == 2_000 and all(len(rows) == 11 for rows in groups.values()), "Q neighborhood scope is not 2,000×11")
    family_counts = {family: sum(1 for nid in groups if groups[nid]["anchor"]["family_slug"] == family) for family in FAMILIES}
    require(family_counts == {family: 500 for family in FAMILIES}, f"Q family allocation mismatch: {family_counts}")

    selected_by_id = {str(row["neighborhood_id"]): row for row in selected}
    join_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in joins:
        join_by_id.setdefault(str(row["neighborhood_id"]), []).append(row)
    require(len(selected_by_id) == len(join_by_id) == 2_000 and set(selected_by_id) == set(groups) == set(join_by_id), "Q selected-view/candidate joins do not cover exact neighborhoods")
    candidate_index_by_id = {str(row["candidate_semantic_id"]): int(row["index"]) for row in candidate_manifest}
    examples: list[dict[str, Any]] = []
    for family in FAMILIES:
        for nid in sorted(nid for nid in groups if groups[nid]["anchor"]["family_slug"] == family):
            available = groups[nid]
            selection = selected_by_id[nid]
            selected_ids = {"anchor": str(selection["anchor_episode_id"]), "fact_flip": str(selection["fact_episode_id"]), "sham": str(selection["sham_episode_id"]), "matched_neutral": str(selection["matched_neutral_episode_id"])}
            expected_roles = {"anchor": "anchor", "fact_flip": "fact_flip", "sham": "sham", "matched_neutral": str(selection["matched_neutral_role"])}
            candidates_for_nid = sorted(join_by_id[nid], key=lambda row: int(row["candidate_order"]))
            require(len(candidates_for_nid) == 4 and [int(row["candidate_order"]) for row in candidates_for_nid] == [0, 1, 2, 3], f"Q candidate order incomplete: {nid}")
            candidate_ids = [str(row["candidate_semantic_id"]) for row in candidates_for_nid]
            candidate_indices = [int(row["feature_index_storage_only"]) for row in candidates_for_nid]
            require(len(set(candidate_ids)) == len(set(candidate_indices)) == 4 and all(candidate_index_by_id.get(cid) == idx for cid, idx in zip(candidate_ids, candidate_indices, strict=True)), f"Q semantic candidate join mismatch: {nid}")
            for view in VIEWS:
                row = available.get(expected_roles[view])
                require(row is not None and str(row["episode_id"]) == selected_ids[view], f"Q selected episode-role mismatch: {nid}/{view}")
                examples.append({"neighborhood_id": nid, "family_id": str(row["family_id"]), "view": view, "episode_id": selected_ids[view], "state_index": int(row["index"]), "candidate_ids": candidate_ids, "candidate_indices": candidate_indices})
    require(len(examples) == 8_000, "Q selected evaluation view count mismatch")
    return examples, state, candidates, scope, {"family_counts": family_counts, "neighborhoods": 2_000, "views": len(examples), "state_tensor_sha256": tensor_sha(state), "candidate_tensor_sha256": tensor_sha(candidates), "target_rows_parsed": False}


def checkpoint_map(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {str(row["path"]): row for row in tree["entries"]}
    return result


def load_head(probe: Any, path: Path, expected_seed: int, expected_arm: str, step: int, initial_sha: str, index: dict[str, dict[str, Any]] | None) -> tuple[Any, str]:
    if index is not None:
        relative = path.relative_to(TRAIN).as_posix()
        entry = index.get(relative)
        require(entry is not None and sha(path) == entry["sha256"], f"Q checkpoint differs from sealed tree: {relative}")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if expected_arm == "COMMON_INIT":
        state = payload.get("state_dict")
        require(payload.get("seed") == expected_seed and payload.get("state_sha256") == initial_sha and state_sha(state) == initial_sha, "Q initialization template identity mismatch")
    else:
        state = payload.get("head_state")
        require(payload.get("seed") == expected_seed and payload.get("arm") == expected_arm and payload.get("global_step") == step and payload.get("initial_head_sha256") == initial_sha and payload.get("run_contract_sha256") == EXPECTED["run"], f"Q trained checkpoint identity mismatch: {expected_seed}/{expected_arm}/{step}")
        require(state_sha(state) == payload.get("head_sha256"), "Q loaded checkpoint head digest mismatch")
    head = probe.CompatibilityHead(2048, "mlp", 128).to(torch.device(DEVICE))
    require(sum(p.numel() for p in head.parameters()) == 590_081, "Q evaluation head parameter count mismatch")
    head.load_state_dict(state, strict=True)
    head.eval()
    return head, state_sha(state)


def append_cell(stream: Any, examples: list[dict[str, Any]], state_device: torch.Tensor, candidate_device: torch.Tensor, head: Any, seed: int, arm: str, step: int) -> int:
    device = torch.device(DEVICE)
    state_indices = torch.tensor([row["state_index"] for row in examples], dtype=torch.long, device=device)
    candidate_indices = torch.tensor([row["candidate_indices"] for row in examples], dtype=torch.long, device=device)
    written = 0
    with torch.inference_mode():
        for start in range(0, len(examples), 256):
            end = min(start + 256, len(examples))
            batch_states = state_device[state_indices[start:end]]
            batch_candidates = candidate_device[candidate_indices[start:end]]
            logits = head(batch_states, batch_candidates)
            probabilities = torch.softmax(logits, dim=-1).detach().cpu().numpy()
            require(probabilities.shape == (end - start, 4) and np.isfinite(probabilities).all(), "Q inference produced invalid probability matrix")
            require(np.all(np.abs(probabilities.sum(axis=1) - 1.0) <= 1e-6), "Q inference probabilities do not normalize")
            for offset, probability in enumerate(probabilities):
                row = examples[start + offset]
                payload = {"seed": seed, "arm": arm, "global_step": step, "neighborhood_id": row["neighborhood_id"], "family_id": row["family_id"], "view": row["view"], "episode_id": row["episode_id"], "candidate_semantic_ids": row["candidate_ids"], "prediction": [float(value) for value in probability]}
                stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
                written += 1
    stream.flush(); os.fsync(stream.fileno())
    return written


def execute() -> int:
    preflight = static_preflight()
    record_opening(preflight)
    stage = "opened_panel_identity_and_feature_validation"
    try:
        examples, state, candidate_features, _scope, panel_audit = opened_panel_inputs()
        write_json(OUTPUT / "opened-panel-validation-v01.json", {"status": "Q_OPENED_PANEL_IDENTITIES_AND_FEATURES_PASS", "opening_receipt_sha256": sha(OUTPUT / "q-panel-opening-receipt-v01.json"), **panel_audit})
        state_device = state.to(torch.device(DEVICE))
        candidate_device = candidate_features.to(torch.device(DEVICE))
        probe = import_module(ROOT / "experiments/jev-frozen-readout-v01/probe.py", "jev_q_eval_probe")
        tree = read_json(TRAIN / "checkpoint-hash-tree.json")
        tree_index = checkpoint_map(tree)
        template_index = {int(Path(row["path"]).stem.split("-")[-1]): row for row in tree["entries"] if row["path"].startswith("initial-templates/") and row["path"].endswith(".pt")}
        prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
        require(not prediction_path.exists(), "Q raw predictions already exist; opening is one-use")
        prediction_count = 0
        cell_records: list[dict[str, Any]] = []
        started = time.perf_counter()
        with prediction_path.open("x", encoding="utf-8", newline="\n") as stream:
            for seed in SEEDS:
                template_path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
                template_entry = template_index.get(seed)
                require(template_entry is not None and sha(template_path) == template_entry["sha256"], f"Q initial template missing from seal: {seed}")
                template_payload = torch.load(template_path, map_location="cpu", weights_only=True)
                init_sha = str(template_payload["state_sha256"])
                head, loaded_sha = load_head(probe, template_path, seed, "COMMON_INIT", 0, init_sha, None)
                require(loaded_sha == init_sha, "Q initialization digest changed on load")
                count = append_cell(stream, examples, state_device, candidate_device, head, seed, "COMMON_INIT", 0)
                require(count == 8_000, "Q initialization prediction count mismatch")
                prediction_count += count; cell_records.append({"seed": seed, "arm": "COMMON_INIT", "global_step": 0, "checkpoint_sha256": template_entry["sha256"], "rows": count})
                del head, template_payload
                for step in CHECKPOINTS:
                    for arm in ARMS:
                        relative = f"runs/seed-{seed}/{arm}/step-{step:03}.pt"
                        path = TRAIN / relative
                        head, head_digest = load_head(probe, path, seed, arm, step, init_sha, tree_index)
                        count = append_cell(stream, examples, state_device, candidate_device, head, seed, arm, step)
                        require(count == 8_000, f"Q trained prediction count mismatch: {seed}/{arm}/{step}")
                        entry = tree_index[relative]
                        prediction_count += count; cell_records.append({"seed": seed, "arm": arm, "global_step": step, "checkpoint_sha256": entry["sha256"], "head_state_sha256": head_digest, "rows": count})
                        print(json.dumps({"event": "q_prediction_cell_sealed_to_stream", "seed": seed, "arm": arm, "step": step, "cell": len(cell_records), "cells": 51, "rows_total": prediction_count}, separators=(",", ":")), flush=True)
                        del head
        require(len(cell_records) == 51 and prediction_count == 408_000, f"Q full prediction matrix incomplete: cells={len(cell_records)}, rows={prediction_count}")
        pred_hash = sha(prediction_path)
        tree_receipt = {"status": "Q_COMPLETE_RAW_PREDICTION_MATRIX_SEALED_BEFORE_ANALYSIS", "opening_count": 1, "cells": cell_records, "cell_count": 51, "prediction_rows": prediction_count, "raw_prediction": {"path": prediction_path.name, "bytes": prediction_path.stat().st_size, "sha256": pred_hash}, "panel_root_sha256": EXPECTED_PANEL_ROOT, "training_seal_sha256": preflight["training_seal_sha256"], "checkpoint_tree_sha256": preflight["checkpoint_tree_sha256"], "instrument_root_sha256": preflight["instrument_root_sha256"], "analysis_started": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False, "elapsed_seconds": time.perf_counter() - started}
        write_json(OUTPUT / "raw-prediction-hash-tree-v01.json", tree_receipt)
        inference = {"status": "Q_COMPLETE_51_CELL_RESPONSE_MATRIX_PREDICTIONS_SEALED", "opening_count": 1, "prediction_rows": prediction_count, "prediction_sha256": pred_hash, "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"), "training_seal_sha256": preflight["training_seal_sha256"], "panel_root_sha256": EXPECTED_PANEL_ROOT, "all_predictions_before_metrics": True, "target_rows_read_during_inference": False, "checkpoint_selection": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False}
        write_json(OUTPUT / "q-inference-receipt-v01.json", inference)
        print(json.dumps({"status": tree_receipt["status"], "cells": 51, "rows": prediction_count, "prediction_sha256": pred_hash, "elapsed_seconds": round(tree_receipt["elapsed_seconds"], 2)}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        failure = OUTPUT / "q-evaluation-failure-receipt-v01.json"
        if not failure.exists():
            write_json(failure, {"status": "Q_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED", "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc), "opening_count": 1, "automatic_retry": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False, "failed_at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    execute()
