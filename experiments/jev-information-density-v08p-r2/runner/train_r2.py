"""Frozen P-R2 head-only training runner.

Training reads only the sealed common primary/arm manifests, the sealed
training-only LFM state cache, the sealed 48-vector candidate catalog/cache,
and the R2 fixed schedule. It has no held-out-panel or E1 data loader.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import random
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
P_PHASE = ROOT / "experiments/jev-information-density-v08p/phase_b"
R2_WORK = ROOT / "experiments/jev-information-density-v08p-r2"
R2_ROOT = Path(r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2")
INPUT_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
STATE_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache")
CANDIDATE_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\feature-cache")
TRAIN_ROOT = R2_ROOT / "training"
SCHEDULE_ROOT = R2_ROOT / "schedule"
PANEL_ROOT = R2_ROOT / "panel"
FEATURE_ROOT = R2_ROOT / "features"
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
SEEDS = (3243871208, 669993655, 3076094663)
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
EXPECTED = {
    "run_contract": "e345225b4a17fc18eb35fcab24cbe1d72bd0e34bed9de272f927a7be461853e6",
    "analysis_contract": "84111122033fda65c84344317cfe3b50639b23be4c71f480ba665c67a23cc939",
    "r2_contract": "51cd8dee09688f1aae24ff575fa0a181d50b2a6ffc94dc6b7e7ed5b61c58ef14",
    "addendum": "4cd14671ffe7c032864fdc0bd5f75db1d1edea666cc58eb43aae0e6c820d0431",
    "panel_ready": "c0d48381356113451bc72f9578204ade4ef7449a75264cd5018a34d002b313ac",
    "schedule": "455d2f8fd709cb0c617f652f7b4ed447fcaaaa30e3e8d2ff1c5cadf358480933",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "B-DUP": "f6f4ec519a04efeac02962c68c2d2d8ec92cf43d25bb9fd974f168e67c4d3b2b",
    "B-MATCHED": "bd38446c0328f8092dc3293090fd3041d7be5d53945df6f80fb3770244d87b0d",
    "B-SHAM": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "state_scope": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "state_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "state_tensor": "d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "candidate_tensor": "f76e573779152fd3966845a39e29206c333eef388e0511c5f3e07f8f1b46d593",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "loss": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "metric": "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70",
    "trajectory_helper": "706b8987b3fd637d03f07a0efffe34efde6370dbb4ae6c9b94f66bbb42b3ca70",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(value).cast("B")).hexdigest()


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists() or path.exists():
        raise RuntimeError(f"refusing to overwrite run artifact: {path}")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with tmp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def replace_json(path: Path, value: Any) -> None:
    """Atomically update the explicitly mutable execution-progress receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with tmp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def atomic_torch_save(value: Any, path: Path) -> str:
    if path.exists():
        raise RuntimeError(f"checkpoint path already exists: {path}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        raise RuntimeError(f"temporary checkpoint exists; preserve and review: {tmp}")
    torch.save(value, tmp)
    with tmp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    digest = sha256_file(tmp)
    os.replace(tmp, path)
    if sha256_file(path) != digest:
        raise RuntimeError(f"durable checkpoint hash mismatch: {path}")
    return digest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load required frozen implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    expected = contract["runtime_environment"]
    actual = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": torch.__version__,
        "transformers": importlib.metadata.version("transformers"),
        "tokenizers": importlib.metadata.version("tokenizers"),
        "numpy": importlib.metadata.version("numpy"),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "compute_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
    }
    for key, value in actual.items():
        require(value == expected[key], f"runtime mismatch {key}: {value!r} != {expected[key]!r}")
    require(torch.cuda.is_available(), "contracted CUDA device unavailable")
    require(torch.backends.cuda.matmul.allow_tf32 is False, "CUDA matmul TF32 must be disabled")
    require(torch.backends.cudnn.allow_tf32 is True, "cuDNN TF32 state differs from frozen runtime")
    require(torch.backends.cudnn.benchmark is False, "cuDNN benchmark must remain disabled")
    require(torch.are_deterministic_algorithms_enabled() is False,
            "deterministic-algorithm setting differs from frozen runtime")
    return actual


def load_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {
        "run_contract": P_PHASE / "phase-b-p-run-contract-v01.json",
        "analysis_contract": P_PHASE / "phase-b-p-analysis-contract-v01.json",
        "r2_contract": R2_WORK / "contracts/r2-execution-contract-v01.json",
        "addendum": R2_WORK / "contracts/p-r2-analysis-addendum-v01.json",
        "panel_ready": R2_WORK / "provenance/r2-panel-ready-manifest-v01.json",
    }
    for name, path in paths.items():
        require(path.is_file() and sha256_file(path) == EXPECTED[name], f"sealed binding mismatch: {name}")
    run = read_json(paths["run_contract"])
    analysis = read_json(paths["analysis_contract"])
    r2 = read_json(paths["r2_contract"])
    addendum = read_json(paths["addendum"])
    require(run["training"]["seed_set"]["seeds"] == list(SEEDS), "seed set differs from P")
    require(r2["training"]["arms"] == list(ARMS) and r2["training"]["seeds"] == list(SEEDS),
            "R2 arm/seed contract mismatch")
    require(r2["training"]["total_steps"] == 120 and r2["training"]["trained_checkpoints"] == 378,
            "R2 schedule/checkpoint count mismatch")
    require(analysis["evaluation_design"]["expected_prediction_rows"] == 3_048_000,
            "analysis response-matrix contract mismatch")
    require(addendum["preoutcome_status"]["trajectory_outcomes_observed"] is False,
            "analysis addendum is not pre-outcome")
    return run, analysis, r2


def import_frozen_components() -> tuple[Any, Any]:
    probe_path = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
    loss_path = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
    require(sha256_file(probe_path) == EXPECTED["probe"], "frozen head implementation hash mismatch")
    require(sha256_file(loss_path) == EXPECTED["loss"], "frozen loss/batching implementation hash mismatch")
    return load_module("jev_r2_frozen_probe", probe_path), load_module("jev_r2_frozen_loss", loss_path)


def source_bindings() -> dict[str, str]:
    return {
        "common_primary_manifest": sha256_file(INPUT_ROOT / "common-primary-occurrence-manifest.jsonl"),
        "candidate_catalog": sha256_file(INPUT_ROOT / "candidate-catalog.json"),
        "training_state_scope": sha256_file(STATE_ROOT / "training-only-feature-scope.jsonl"),
        "training_state_features": sha256_file(STATE_ROOT / "shared-training-features.pt"),
        "training_candidate_features": sha256_file(CANDIDATE_ROOT / "candidate-features.pt"),
        "training_candidate_feature_receipt": sha256_file(CANDIDATE_ROOT / "candidate-feature-receipt.json"),
        "fixed_schedule": sha256_file(SCHEDULE_ROOT / "fixed-schedule.jsonl"),
        "fixed_schedule_seal": sha256_file(SCHEDULE_ROOT / "r2-schedule-seal-v01.json"),
    }


def verify_preupdate_restart_state() -> dict[str, Any]:
    """Bind both retained zero-step failures and prove restart uses the same seeds."""
    prior_preflight = R2_WORK / "provenance/r2-pretraining-preflight-v01.json"
    require(prior_preflight.is_file()
            and sha256_file(prior_preflight) == "142cd2ab5b83686803b57a753a92f3cddad7b46ecd33a39c861093fffd624046",
            "original pretraining preflight identity changed")
    recovery_preflight = R2_WORK / "provenance/r2-pretraining-preflight-v02.json"
    require(recovery_preflight.is_file()
            and sha256_file(recovery_preflight) == "c3e82243a877fdc70eb905dda899c542dca9ea4d421490ec271c0740578cf5e4",
            "first recovery preflight identity changed")

    root_failure = TRAIN_ROOT / "training-failure-receipt.json"
    require(root_failure.is_file(), "retained pre-update failure receipt is absent")
    root_failure_obj = read_json(root_failure)
    require(root_failure_obj.get("status") == "P_R2_TRAINING_FAILED_CLOSED"
            and root_failure_obj.get("exception_type") == "KeyError"
            and root_failure_obj.get("exception") == "'source_episode_id'"
            and root_failure_obj.get("completed_runs") == []
            and root_failure_obj.get("evaluation_access") is False,
            "retained failure is not the known zero-step event-packing failure")

    attempt_parent = TRAIN_ROOT / "attempts/seed-3243871208/B-DUP"
    attempts = sorted(path for path in attempt_parent.glob("attempt-*") if path.is_dir())
    require(len(attempts) == 2, "unexpected prior attempt set; cannot certify exact restart")
    attempt_records = []
    observed_errors = set()
    for attempt in attempts:
        attempt_failure = read_json(attempt / "failure-receipt.json")
        events = read_jsonl(attempt / "training-events.jsonl")
        checkpoint_files = sorted(attempt.glob("step-*.pt"))
        error = attempt_failure.get("exception")
        observed_errors.add(error)
        require(attempt_failure.get("status") == "ATTEMPT_FAILED_RETAINED"
                and attempt_failure.get("seed") == 3243871208
                and attempt_failure.get("arm") == "B-DUP"
                and attempt_failure.get("exception_type") == "KeyError"
                and error in {"'source_episode_id'", "'candidate_indices'"}
                and attempt_failure.get("attempt_path") == str(attempt)
                and attempt_failure.get("last_checkpoint_step") == 0
                and events == [{
                    "event": "run_start", "seed": 3243871208, "arm": "B-DUP",
                    "initial_head_sha256": "a3685a8db4f1cca239590aa6c992bde8d5fb140c36045e5450d5d68e2ec88166",
                    "resume_global_step": 0, "evaluation_access": False,
                }]
                and not checkpoint_files and not (attempt / "checkpoint-index.jsonl").exists(),
                f"prior attempt contains a committed step/checkpoint or unexpected event: {attempt}")
        attempt_files = sorted(path for path in attempt.iterdir() if path.is_file())
        require({path.name for path in attempt_files} == {
            "failure-receipt.json", "run-config.json", "training-events.jsonl",
        }, f"prior attempt artifact set differs from its failure receipt: {attempt}")
        attempt_records.append({
            "path": str(attempt),
            "files": [{"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
                      for path in attempt_files],
            "optimizer_steps_committed": 0,
            "checkpoint_count": 0,
            "failure_exception": error,
        })
    require(observed_errors == {"'source_episode_id'", "'candidate_indices'"},
            "prior zero-step failures do not match the two recorded event-packing defects")

    templates = []
    template_root = TRAIN_ROOT / "initial-templates"
    for seed in SEEDS:
        path = template_root / f"seed-{seed}.pt"
        require(path.is_file(), f"paired initialization template missing: {seed}")
        payload = torch.load(path, map_location="cpu", weights_only=True)
        state = payload["state_dict"]
        digest = state_digest(state)
        require(payload.get("seed") == seed and payload.get("state_sha256") == digest
                and sum(value.numel() for value in state.values()) == 590_081,
                f"retained paired initialization template invalid: {seed}")
        templates.append({"seed": seed, "path": str(path), "file_sha256": sha256_file(path),
                          "state_sha256": digest})

    return {
        "status": "ZERO_OPTIMIZER_STEPS_EXACT_INITIALIZATION_RESTART",
        "superseded_preflight_v01_sha256": sha256_file(prior_preflight),
        "superseded_preflight_v02_sha256": sha256_file(recovery_preflight),
        "root_failure_receipt": {"path": str(root_failure), "sha256": sha256_file(root_failure)},
        "prior_zero_step_attempts": attempt_records,
        "paired_initial_templates": templates,
        "evaluation_access": False,
    }


def verify_bound_preupdate_evidence(evidence: dict[str, Any]) -> None:
    """Recheck the immutable zero-step incident even on an exact later resume."""
    require(evidence.get("status") == "ZERO_OPTIMIZER_STEPS_EXACT_INITIALIZATION_RESTART",
            "pre-update restart evidence status mismatch")
    prior_preflight = R2_WORK / "provenance/r2-pretraining-preflight-v01.json"
    require(sha256_file(prior_preflight) == evidence["superseded_preflight_v01_sha256"],
            "superseded preflight changed after recovery seal")
    recovery_preflight = R2_WORK / "provenance/r2-pretraining-preflight-v02.json"
    require(sha256_file(recovery_preflight) == evidence["superseded_preflight_v02_sha256"],
            "first recovery preflight changed after restart seal")
    root_failure = Path(evidence["root_failure_receipt"]["path"])
    require(sha256_file(root_failure) == evidence["root_failure_receipt"]["sha256"],
            "original zero-step failure receipt changed")
    for attempt_record in evidence["prior_zero_step_attempts"]:
        attempt = Path(attempt_record["path"])
        current_files = sorted(path for path in attempt.iterdir() if path.is_file())
        recorded_files = attempt_record["files"]
        require([path.name for path in current_files] == [row["name"] for row in recorded_files],
                "original failed-attempt file set changed")
        for path, record in zip(current_files, recorded_files, strict=True):
            require(path.stat().st_size == record["bytes"] and sha256_file(path) == record["sha256"],
                    f"original failed-attempt artifact changed: {path.name}")


def verify_training_inputs(run_contract: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor, list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    input_receipt = INPUT_ROOT / "execution-inputs-receipt.json"
    input_tree = INPUT_ROOT / "execution-inputs-hash-tree.json"
    require(input_receipt.is_file() and sha256_file(input_receipt) == "c022befafd49a1e317f692ff3b6f7efcccd11aee98285ca5f0071f6edbaf817c",
            "sealed v0.8N training-input receipt mismatch")
    require(input_tree.is_file(), "sealed v0.8N training-input hash tree is absent")
    receipt_obj = read_json(input_receipt)
    require(receipt_obj["common_primary_manifest"]["sha256"] == EXPECTED["primary"],
            "input receipt primary binding mismatch")

    primary_path = INPUT_ROOT / "common-primary-occurrence-manifest.jsonl"
    require(sha256_file(primary_path) == EXPECTED["primary"], "common primary manifest hash mismatch")
    primary = read_jsonl(primary_path)
    require(len(primary) == 10_000, "common primary manifest row count mismatch")
    require(all(row.get("occurrence_index") == i and row.get("source_partition") == "train"
                for i, row in enumerate(primary)), "primary stream identity/source partition mismatch")
    require(all(row.get("role") == ("anchor" if i % 2 == 0 else "fact_flip")
                for i, row in enumerate(primary)), "primary anchor/fact row layout mismatch")
    require(len({row["episode_id"] for row in primary}) == 10_000, "primary episode IDs are not unique")

    arm_rows: dict[str, list[dict[str, Any]]] = {}
    for arm in ARMS:
        path = INPUT_ROOT / f"head-input-manifest-{arm}.jsonl"
        require(sha256_file(path) == EXPECTED[arm], f"arm input hash mismatch: {arm}")
        rows = read_jsonl(path)
        require(len(rows) == 15_000, f"arm input row count mismatch: {arm}")
        for i, source in enumerate(primary):
            row = rows[i]
            require(row.get("event_kind") == "primary" and row.get("occurrence_index") == i,
                    f"primary occurrence mismatch {arm}/{i}")
            require(row.get("group_id") == source["group_id"]
                    and row.get("source_episode_id") == source["episode_id"]
                    and row.get("target_hash") == source["target_hash"]
                    and row.get("candidate_order_hash") == source["candidate_order_hash"]
                    and row.get("candidate_semantic_ids") == source["candidate_semantic_ids"],
                    f"common primary payload mismatch {arm}/{i}")
        expected_role = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral",
                         "B-SHAM": "certified_sham"}[arm]
        for slot, row in enumerate(rows[10_000:]):
            require(row.get("event_kind") == "auxiliary" and row.get("batch_slot") == slot
                    and row.get("auxiliary_source_role") == expected_role,
                    f"auxiliary identity/role mismatch {arm}/{slot}")
            require(row.get("loss_weight") == 1.0 and len(row.get("target", [])) == 4
                    and abs(sum(row["target"]) - 1.0) <= 1e-12,
                    f"auxiliary weight/target invalid {arm}/{slot}")
            require(row.get("normalization") == "(N_base*L_base + N_aux*L_aux)/(N_base + N_aux)",
                    f"auxiliary reduction semantics mismatch {arm}/{slot}")
        arm_rows[arm] = rows

    catalog_path = INPUT_ROOT / "candidate-catalog.json"
    require(sha256_file(catalog_path) == EXPECTED["candidate_catalog"], "candidate catalog hash mismatch")
    catalog = read_json(catalog_path)
    candidate_ids = [row["candidate_semantic_id"] for row in catalog["rows"]]
    require(len(candidate_ids) == 48 and len(set(candidate_ids)) == 48
            and catalog["feature_dimension"] == 2048, "candidate catalog shape/identity mismatch")
    id_to_index = {value: i for i, value in enumerate(candidate_ids)}
    for arm, rows in arm_rows.items():
        for row in rows:
            semantic_ids = row["candidate_semantic_ids"]
            require(len(semantic_ids) == 4 and len(set(semantic_ids)) == 4,
                    f"candidate IDs/mask cardinality mismatch {arm}/{row.get('occurrence_index')}")
            require(row["candidate_indices"] == [id_to_index[value] for value in semantic_ids],
                    f"candidate feature-index semantic join mismatch {arm}/{row.get('occurrence_index')}")
            require(row["candidate_mask"] == [True] * 4 and len(row["target"]) == 4,
                    f"candidate mask/target width mismatch {arm}/{row.get('occurrence_index')}")

    scope_path = STATE_ROOT / "training-only-feature-scope.jsonl"
    state_path = STATE_ROOT / "shared-training-features.pt"
    cache_receipt_path = STATE_ROOT / "shared-feature-cache-receipt.json"
    require(sha256_file(scope_path) == EXPECTED["state_scope"], "training feature scope hash mismatch")
    require(sha256_file(state_path) == EXPECTED["state_features"], "training feature tensor file hash mismatch")
    scope_rows = read_jsonl(scope_path)
    require(len(scope_rows) == 55_000 and all(row.get("index") == i for i, row in enumerate(scope_rows)),
            "training feature scope count/index mismatch")
    cache_receipt = read_json(cache_receipt_path)
    require(sha256_file(cache_receipt_path) == "d98ae657e28b976f187d4d67e58119ce80496e76c061c90362ac2e50ff7f720e",
            "training feature scope receipt hash mismatch")
    require(cache_receipt["feature_tensor"]["tensor_sha256"] == EXPECTED["state_tensor"],
            "training feature tensor identity mismatch")
    cache = torch.load(state_path, map_location="cpu", weights_only=True)
    require(cache.get("feature_key") == FEATURE_KEY,
            "training feature cache key does not match the sealed representation contract")
    require(cache.get("scope_content_sha256") == cache_receipt["scope"]["content_sha256"],
            "training feature cache scope identity mismatch")
    state_features = cache["features"]
    require(state_features.shape == (55_000, 2048) and state_features.dtype == torch.float32
            and state_features.is_contiguous() and torch.isfinite(state_features).all().item(),
            "training state feature tensor shape/dtype/layout/finite check failed")
    require(tensor_sha256(state_features) == EXPECTED["state_tensor"], "training state tensor content hash mismatch")

    candidate_path = CANDIDATE_ROOT / "candidate-features.pt"
    candidate_receipt_path = CANDIDATE_ROOT / "candidate-feature-receipt.json"
    require(sha256_file(candidate_path) == EXPECTED["candidate_features"], "candidate feature file hash mismatch")
    require(sha256_file(candidate_receipt_path) == "29f8d67b24fd2a554500e1cfe2e0fe0b4311d32fad7052ad8ffb3464b7835f44",
            "candidate feature receipt hash mismatch")
    candidate_receipt = read_json(candidate_receipt_path)
    candidate_features = torch.load(candidate_path, map_location="cpu", weights_only=True)
    require(candidate_features.shape == (48, 2048) and candidate_features.dtype == torch.float32
            and candidate_features.is_contiguous() and torch.isfinite(candidate_features).all().item(),
            "candidate tensor shape/dtype/layout/finite check failed")
    require(candidate_receipt["semantic_ids"] == candidate_ids
            and candidate_receipt["tensor_sha256"] == EXPECTED["candidate_tensor"]
            and tensor_sha256(candidate_features) == EXPECTED["candidate_tensor"],
            "candidate tensor semantic ordering/content mismatch")
    for arm, rows in arm_rows.items():
        for row in rows:
            scope = scope_rows[row["feature_scope_index"]]
            require(scope["episode_id"] == row["source_episode_id"],
                    f"state feature scope join mismatch {arm}/{row['occurrence_index'] if row['event_kind']=='primary' else row['batch_slot']}")
            if row["event_kind"] == "primary":
                primary_row = primary[row["occurrence_index"]]
                require(scope["input_sha256"] == primary_row["input_sha256"],
                        f"primary feature input binding mismatch {arm}/{row['occurrence_index']}")
            else:
                require(scope.get("neighborhood_id") == row["neighborhood_id"],
                        f"auxiliary feature neighborhood binding mismatch {arm}/{row['batch_slot']}")

    schedule_path = SCHEDULE_ROOT / "fixed-schedule.jsonl"
    schedule_seal_path = SCHEDULE_ROOT / "r2-schedule-seal-v01.json"
    require(sha256_file(schedule_path) == EXPECTED["schedule"], "P-R2 schedule hash mismatch")
    schedule_seal = read_json(schedule_seal_path)
    require(schedule_seal["status"] == "P_R2_SCHEDULE_SEALED_PRE_INITIALIZATION"
            and schedule_seal["schedule_sha256"] == EXPECTED["schedule"], "schedule seal mismatch")
    schedule = read_jsonl(schedule_path)
    require(len(schedule) == 360, "schedule row count mismatch")
    for seed in SEEDS:
        for epoch in (1, 2, 3):
            block = sorted((row for row in schedule if row["seed"] == seed and row["epoch"] == epoch),
                           key=lambda row: row["step"])
            require(len(block) == 40 and [row["step"] for row in block] == list(range(1, 41)),
                    f"schedule seed/epoch step count mismatch {seed}/{epoch}")
            indices = [index for row in block for index in row["primary_occurrence_indices"]]
            slots = [slot for row in block for slot in row["auxiliary_anchor_batch_slots"]]
            require(sorted(indices) == list(range(10_000)) and sorted(slots) == list(range(5_000)),
                    f"schedule event coverage mismatch {seed}/{epoch}")
            for row in block:
                ids = row["primary_occurrence_indices"]
                require(bool(row["auxiliary_anchor_batch_slots"]),
                        f"empty auxiliary schedule slot {seed}/{epoch}/{row['step']}")
                require(row["primary_group_ids"] == [primary[index]["group_id"] for index in ids],
                        f"schedule group/occurrence join mismatch {seed}/{epoch}/{row['step']}")
                slots_for_batch = [primary[index]["occurrence_index"] // 2 for index in ids
                                   if primary[index]["role"] == "anchor"]
                require(row["auxiliary_anchor_batch_slots"] == slots_for_batch,
                        f"schedule auxiliary order mismatch {seed}/{epoch}/{row['step']}")
    return state_features, candidate_features, primary, schedule, arm_rows, {"scope_rows": scope_rows, "catalog": catalog}


def prepare_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        # dict.get evaluates its default eagerly; primary rows have group_id
        # but intentionally do not carry source_episode_id under this name.
        "group_id": row["group_id"] if "group_id" in row else row["source_episode_id"],
        "state_idx": row["feature_scope_index"],
        "candidate_indices": {PROFILE: row["candidate_indices"]},
        "gold": row["target"],
        "kind": "choice",
        "probability_source": "exact_generative_posterior",
    }


def verify_scheduled_batch_materialization(
    trainer: Any,
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    primary: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    arm_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Exercise every frozen training batch join/gather without a head or update."""
    checked_batches = 0
    checked_events = 0
    for spec in schedule:
        indices = spec["primary_occurrence_indices"]
        slots = spec["auxiliary_anchor_batch_slots"]
        step_label = f"{spec['epoch']}/{spec['step']}"
        for arm in ARMS:
            rows = arm_rows[arm]
            base = [rows[index] for index in indices]
            require([row["group_id"] for row in base] == spec["primary_group_ids"],
                    f"preflight primary group order mismatch {arm}/{spec['seed']}/{step_label}")
            anchor_slots = [primary[index]["occurrence_index"] // 2 for index in indices
                            if primary[index]["role"] == "anchor"]
            require(slots == anchor_slots and len(slots) == spec["active_auxiliary_count"],
                    f"preflight auxiliary slot mismatch {arm}/{spec['seed']}/{step_label}")
            auxiliary = [rows[10_000 + slot] for slot in slots]
            for source_slot, row in zip(slots, auxiliary, strict=True):
                require(row["batch_slot"] == source_slot
                        and row["neighborhood_id"] == primary[2 * source_slot]["neighborhood_id"],
                        f"preflight auxiliary pointer mismatch {arm}/{spec['seed']}/{step_label}/{source_slot}")
            events = [prepare_event(row) for row in base]
            events.extend(prepare_event(row) for row in auxiliary)
            states, candidates, gold, mask, kinds, sources = trainer.fast_tensor_batch(
                events, state_features, candidate_features, PROFILE, "cpu", reorder=True,
            )
            count = len(events)
            require(tuple(states.shape) == (count, 2048)
                    and tuple(candidates.shape) == (count, 4, 2048)
                    and tuple(gold.shape) == (count, 4) and tuple(mask.shape) == (count, 4)
                    and bool(mask.all().item()) and len(kinds) == count and len(sources) == count,
                    f"preflight materialized batch shape/mask mismatch {arm}/{spec['seed']}/{step_label}")
            checked_batches += 1
            checked_events += count
    require(checked_batches == len(schedule) * len(ARMS), "preflight did not cover every scheduled arm batch")
    return {"status": "PASS", "scheduled_arm_batches": checked_batches,
            "materialized_events": checked_events, "model_forward_or_optimizer_step": False}


def cpu_clone(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {key: cpu_clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [cpu_clone(item) for item in value]
    if isinstance(value, tuple):
        return tuple(cpu_clone(item) for item in value)
    return value


def synthetic_self_test(probe: Any, trainer: Any) -> dict[str, Any]:
    """Exercise pairing and exact optimizer/RNG checkpoint continuation on CPU fixtures."""
    primary_event = {
        "group_id": "fixture-group",
        "feature_scope_index": 0,
        "candidate_indices": {PROFILE: [0, 1, 2, 3]},
        "target": [0.7, 0.1, 0.1, 0.1],
        "kind": "choice",
        "probability_source": "exact_generative_posterior",
    }
    auxiliary_event = {
        "source_episode_id": "fixture-episode",
        "feature_scope_index": 1,
        "candidate_indices": {PROFILE: [0, 1, 2, 3]},
        "target": [0.1, 0.7, 0.1, 0.1],
        "kind": "choice",
        "probability_source": "exact_generative_posterior",
    }
    require(prepare_event(primary_event)["group_id"] == "fixture-group"
            and prepare_event(auxiliary_event)["group_id"] == "fixture-episode",
            "event identity normalization failed on primary/auxiliary fixtures")
    seed = 1729
    arm_hashes = []
    for _arm in ARMS:
        seed_everything(seed)
        head = probe.CompatibilityHead(2048, "mlp", 128)
        arm_hashes.append(state_digest(head.state_dict()))
        require(sum(parameter.numel() for parameter in head.parameters()) == 590_081,
                "synthetic head parameter count differs from frozen architecture")
    require(len(set(arm_hashes)) == 1, "paired initialization fixture differs by arm")

    states = torch.arange(8 * 2048, dtype=torch.float32).reshape(8, 2048) / 10_000.0
    candidates = torch.arange(4 * 2048, dtype=torch.float32).reshape(4, 2048) / 8_000.0
    event = {"state_idx": 1, "candidate_indices": {PROFILE: [0, 1, 2, 3]},
             "gold": [0.7, 0.1, 0.1, 0.1], "kind": "choice",
             "probability_source": "exact_generative_posterior"}
    batch = [event, {**event, "state_idx": 3, "gold": [0.1, 0.7, 0.1, 0.1]}]

    def make_head_optimizer(initial: dict[str, torch.Tensor]):
        head_local = probe.CompatibilityHead(2048, "mlp", 128)
        head_local.load_state_dict(initial, strict=True)
        opt_local = torch.optim.AdamW(head_local.parameters(), lr=0.002, weight_decay=0.01,
                                      betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
        return head_local, opt_local

    def update(head_local: Any, opt_local: Any) -> float:
        st, cand, gold, mask, kinds, sources = trainer.fast_tensor_batch(
            batch, states, candidates, PROFILE, "cpu", reorder=True)
        opt_local.zero_grad(set_to_none=True)
        logits = head_local(st, cand)
        loss, _brier = trainer.v05_loss(logits, gold, mask, kinds, sources, 0.25)
        loss.backward()
        opt_local.step()
        return float(loss.detach())

    seed_everything(seed)
    base_template = probe.CompatibilityHead(2048, "mlp", 128)
    initial = cpu_clone(base_template.state_dict())
    seed_everything(seed + 1)
    uninterrupted, optimizer_a = make_head_optimizer(initial)
    first_loss = update(uninterrupted, optimizer_a)
    second_loss = update(uninterrupted, optimizer_a)

    seed_everything(seed + 1)
    resumed, optimizer_b = make_head_optimizer(initial)
    update(resumed, optimizer_b)
    payload = {
        "head": cpu_clone(resumed.state_dict()),
        "optimizer": cpu_clone(optimizer_b.state_dict()),
        "python_rng": random.getstate(),
        "torch_cpu_rng": torch.get_rng_state().clone(),
    }
    import io
    buf = io.BytesIO()
    torch.save(payload, buf)
    buf.seek(0)
    restored = torch.load(buf, map_location="cpu", weights_only=False)
    resumed2, optimizer_c = make_head_optimizer(initial)
    resumed2.load_state_dict(restored["head"], strict=True)
    optimizer_c.load_state_dict(restored["optimizer"])
    random.setstate(restored["python_rng"])
    torch.set_rng_state(restored["torch_cpu_rng"])
    resumed_second_loss = update(resumed2, optimizer_c)
    require(math.isfinite(first_loss) and second_loss == resumed_second_loss,
            "synthetic checkpoint resume changed loss/update arithmetic")
    require(state_digest(uninterrupted.state_dict()) == state_digest(resumed2.state_dict()),
            "synthetic checkpoint continuation changed final head state")
    require(state_digest({str(i): p for i, p in enumerate(uninterrupted.parameters())})
            == state_digest({str(i): p for i, p in enumerate(resumed2.parameters())}),
            "synthetic checkpoint continuation parameter digest mismatch")
    return {"status": "PASS", "paired_init_hash": arm_hashes[0], "head_parameters": 590_081,
            "checkpoint_continuation_exact_cpu_fixture": True,
            "first_step_loss": first_loss, "second_step_loss": second_loss}


def seed_order(contract: dict[str, Any]) -> dict[int, tuple[str, ...]]:
    explicit = contract["training"]["execution_order"]
    return {int(seed): tuple(arms) for seed, arms in explicit.items()}


def save_checkpoint(path: Path, *, head: Any, optimizer: Any, seed: int, arm: str, epoch: int,
                    global_step: int, schedule_hash: str, last_occurrence: int, last_aux_slot: int,
                    initial_hash: str, run_contract_hash: str) -> str:
    payload = {
        "protocol": "jev-information-density/v0.8p-r2-online-freshness-admission-v01",
        "seed": seed, "arm": arm, "epoch": epoch, "global_step": global_step,
        "head_state": cpu_clone(head.state_dict()),
        "optimizer_state": cpu_clone(optimizer.state_dict()),
        "python_rng_state": random.getstate(),
        "torch_cpu_rng_state": torch.get_rng_state().clone(),
        "cuda_rng_states": [state.cpu().clone() for state in torch.cuda.get_rng_state_all()],
        "schedule_sha256": schedule_hash,
        "last_committed_occurrence_index": last_occurrence,
        "last_committed_auxiliary_slot": last_aux_slot,
        "initial_head_sha256": initial_hash,
        "head_sha256": state_digest(head.state_dict()),
        "run_contract_sha256": run_contract_hash,
        "evaluation_access": False,
        "backbone_frozen": True,
    }
    return atomic_torch_save(payload, path)


def restore_checkpoint(path: Path, head: Any, optimizer: Any, *, seed: int, arm: str,
                       schedule_hash: str, initial_hash: str) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    require(payload.get("seed") == seed and payload.get("arm") == arm
            and payload.get("schedule_sha256") == schedule_hash
            and payload.get("initial_head_sha256") == initial_hash,
            f"resume checkpoint identity mismatch: {path}")
    require(state_digest(payload["head_state"]) == payload["head_sha256"], "resume checkpoint head digest mismatch")
    head.load_state_dict(payload["head_state"], strict=True)
    optimizer.load_state_dict(payload["optimizer_state"])
    random.setstate(payload["python_rng_state"])
    torch.set_rng_state(payload["torch_cpu_rng_state"])
    torch.cuda.set_rng_state_all(payload["cuda_rng_states"])
    return payload


def run_one(run_contract: dict[str, Any], probe: Any, trainer: Any, *, seed: int, arm: str,
            initial_state: dict[str, torch.Tensor], state_features: torch.Tensor,
            candidate_features: torch.Tensor, primary: list[dict[str, Any]],
            schedule: list[dict[str, Any]], arm_rows: list[dict[str, Any]],
            schedule_hash: str, initial_hash: str) -> dict[str, Any]:
    run_dir = TRAIN_ROOT / "runs" / f"seed-{seed}" / arm
    require(not run_dir.exists(), f"final run path already exists without validated completion: {run_dir}")
    attempt_root = TRAIN_ROOT / "attempts" / f"seed-{seed}" / arm
    prior_attempts = sorted(attempt_root.glob("attempt-*")) if attempt_root.exists() else []
    resume_payload = None
    resume_source = None
    resume_source_attempt = None
    resume_index_rows: list[dict[str, Any]] = []
    for prior in prior_attempts:
        checkpoints = sorted(prior.glob("step-*.pt"), key=lambda p: int(p.stem.split("-")[1]))
        if checkpoints:
            index_path = prior / "checkpoint-index.jsonl"
            index_rows = read_jsonl(index_path) if index_path.exists() else []
            require(len(index_rows) == len(checkpoints), f"resume checkpoint index is incomplete: {prior}")
            for item in index_rows:
                candidate = prior / item["path"]
                require(candidate in checkpoints and candidate.is_file()
                        and item.get("sha256") == sha256_file(candidate),
                        f"resume checkpoint is not receipt-validated: {candidate}")
            candidate = checkpoints[-1]
            item = next(row for row in index_rows if row.get("path") == candidate.name)
            loaded = torch.load(candidate, map_location="cpu", weights_only=False)
            require(loaded.get("schedule_sha256") == schedule_hash and loaded.get("seed") == seed
                    and loaded.get("arm") == arm and loaded.get("initial_head_sha256") == initial_hash
                    and state_digest(loaded.get("head_state", {})) == loaded.get("head_sha256"),
                    "resume checkpoint schedule/identity/state mismatch")
            step = int(loaded.get("global_step", -1))
            require(step == int(item.get("global_step", -2)), "resume checkpoint/index step mismatch")
            expected_prefix = ([40] if step >= 40 else []) + ([80] if step >= 80 else [])
            expected_prefix.extend(range(81, min(step, 120) + 1))
            require([row["global_step"] for row in index_rows] == expected_prefix,
                    f"resume checkpoint prefix is incomplete: {prior}")
            if resume_payload is None or step > int(resume_payload["global_step"]):
                resume_payload, resume_source = loaded, candidate
                resume_source_attempt = prior
                resume_index_rows = index_rows
        events = prior / "training-events.jsonl"
        committed = [row for row in read_jsonl(events) if row.get("event") == "optimizer_step"] if events.exists() else []
        if not checkpoints:
            require(not committed,
                    f"attempt has committed optimizer steps without a checkpoint; stop for review: {prior}")

    attempt_root.mkdir(parents=True, exist_ok=True)
    attempt = attempt_root / f"attempt-{uuid.uuid4().hex}"
    attempt.mkdir(parents=False, exist_ok=False)
    run_config = {
        "r2_execution_contract_sha256": EXPECTED["r2_contract"],
        "p_run_contract_sha256": EXPECTED["run_contract"],
        "p_analysis_contract_sha256": EXPECTED["analysis_contract"],
        "analysis_addendum_sha256": EXPECTED["addendum"],
        "trainer_sha256": sha256_file(Path(__file__).resolve()),
        "schedule_sha256": schedule_hash,
        "seed": seed, "arm": arm, "initial_head_sha256": initial_hash,
        "primary_manifest_sha256": EXPECTED["primary"],
        "arm_manifest_sha256": EXPECTED[arm],
        "initialization_paired_across_arms": True,
        "evaluation_access": False, "newtight_access": False, "phoenix_access": False,
        "resumed_from": str(resume_source) if resume_source else None,
        "resume_source_attempt": str(resume_source_attempt) if resume_source_attempt else None,
    }
    write_json(attempt / "run-config.json", run_config)
    events_path = attempt / "training-events.jsonl"
    checkpoint_index = attempt / "checkpoint-index.jsonl"
    if resume_payload is not None:
        assert resume_source is not None and resume_source_attempt is not None
        copied_rows = []
        for row in resume_index_rows:
            source_path = resume_source_attempt / row["path"]
            target_path = attempt / row["path"]
            shutil.copyfile(source_path, target_path)
            require(sha256_file(target_path) == row["sha256"],
                    f"copied resume checkpoint changed bytes: {target_path}")
            copied_rows.append(row)
        write_json(attempt / "resume-receipt.json", {
            "status": "EXACT_VALIDATED_CHECKPOINT_RESUME",
            "seed": seed, "arm": arm, "global_step": int(resume_payload["global_step"]),
            "checkpoint_path": str(resume_source), "checkpoint_sha256": sha256_file(resume_source),
            "source_attempt": str(resume_source_attempt),
            "source_checkpoint_index_sha256": sha256_file(resume_source_attempt / "checkpoint-index.jsonl"),
            "source_training_events_sha256": sha256_file(resume_source_attempt / "training-events.jsonl"),
            "copied_checkpoint_prefix": copied_rows,
        })
        with checkpoint_index.open("w", encoding="utf-8", newline="\n") as stream:
            for row in copied_rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.load_state_dict(initial_state, strict=True)
    require(state_digest(head.state_dict()) == initial_hash, f"paired init mismatch {seed}/{arm}")
    optimizer_cfg = run_contract["training"]["optimizer"]
    optimizer = torch.optim.AdamW(
        head.parameters(), lr=optimizer_cfg["learning_rate"],
        betas=tuple(optimizer_cfg["betas"]), eps=optimizer_cfg["epsilon"],
        weight_decay=optimizer_cfg["weight_decay"], amsgrad=optimizer_cfg["amsgrad"],
    )
    start_step = 0
    if resume_payload is not None:
        head.load_state_dict(resume_payload["head_state"], strict=True)
        optimizer.load_state_dict(resume_payload["optimizer_state"])
        random.setstate(resume_payload["python_rng_state"])
        torch.set_rng_state(resume_payload["torch_cpu_rng_state"])
        torch.cuda.set_rng_state_all(resume_payload["cuda_rng_states"])
        start_step = int(resume_payload["global_step"])
    else:
        seed_everything(seed)

    aux_events = [prepare_event(row) for row in arm_rows[10_000:]]
    started = time.perf_counter()
    append_jsonl(events_path, {"event": "run_start", "seed": seed, "arm": arm,
                               "initial_head_sha256": initial_hash, "resume_global_step": start_step,
                               "evaluation_access": False})
    try:
        for epoch in range(1, 4):
            head.train()
            epoch_schedule = sorted((row for row in schedule if row["epoch"] == epoch), key=lambda x: x["step"])
            require(len(epoch_schedule) == 40, f"epoch schedule length mismatch {seed}/{arm}/{epoch}")
            for slot_index, spec in enumerate(epoch_schedule, start=1):
                global_step = (epoch - 1) * 40 + slot_index
                if global_step <= start_step:
                    continue
                ids = spec["primary_occurrence_indices"]
                slots = spec["auxiliary_anchor_batch_slots"]
                # The common stream defines ordering; the arm manifest carries
                # the bound feature/candidate payload consumed by the trainer.
                base = [arm_rows[index] for index in ids]
                require([row["group_id"] for row in base] == spec["primary_group_ids"],
                        f"primary batch order drift {seed}/{arm}/{global_step}")
                anchor_slots = [primary[index]["occurrence_index"] // 2 for index in ids
                                if primary[index]["role"] == "anchor"]
                require(slots == anchor_slots and len(slots) == spec["active_auxiliary_count"],
                        f"auxiliary placement drift {seed}/{arm}/{global_step}")
                aux = [arm_rows[10_000 + index] for index in slots]
                for source_slot, row in zip(slots, aux, strict=True):
                    require(row["batch_slot"] == source_slot
                            and row["neighborhood_id"] == primary[2 * source_slot]["neighborhood_id"],
                            f"auxiliary source pointer mismatch {seed}/{arm}/{global_step}/{source_slot}")
                batch = [prepare_event(row) for row in base] + [prepare_event(row) for row in aux]
                states, candidates, gold, mask, kinds, sources = trainer.fast_tensor_batch(
                    batch, state_features, candidate_features, PROFILE, "cuda", reorder=True,
                )
                optimizer.zero_grad(set_to_none=True)
                logits = head(states, candidates)
                loss, brier = trainer.v05_loss(logits, gold, mask, kinds, sources, 0.25)
                require(torch.isfinite(loss).item() and torch.isfinite(brier).item(),
                        f"non-finite loss {seed}/{arm}/{global_step}")
                loss.backward()
                grad_sq = torch.zeros((), device="cuda")
                for parameter in head.parameters():
                    if parameter.grad is not None:
                        require(torch.isfinite(parameter.grad).all().item(),
                                f"non-finite gradient {seed}/{arm}/{global_step}")
                        grad_sq += parameter.grad.detach().float().square().sum()
                grad_norm = float(torch.sqrt(grad_sq).detach().cpu())
                optimizer.step()
                loss_value = float(loss.detach().cpu())
                append_jsonl(events_path, {
                    "event": "optimizer_step", "seed": seed, "arm": arm,
                    "epoch": epoch, "epoch_step": slot_index, "global_step": global_step,
                    "primary_occurrence_indices": ids,
                    "auxiliary_anchor_batch_slots": slots,
                    "primary_event_count": len(base), "auxiliary_event_count": len(aux),
                    "loss": loss_value, "brier_component": float(brier.detach().cpu()),
                    "gradient_norm": grad_norm, "learning_rate": optimizer.param_groups[0]["lr"],
                    "cuda_allocated_bytes": int(torch.cuda.memory_allocated()),
                    "evaluation_access": False,
                })
                save = global_step in (40, 80) or 81 <= global_step <= 120
                if save:
                    checkpoint_path = attempt / f"step-{global_step:03d}.pt"
                    checkpoint_hash = save_checkpoint(
                        checkpoint_path, head=head, optimizer=optimizer, seed=seed, arm=arm,
                        epoch=epoch, global_step=global_step, schedule_hash=schedule_hash,
                        last_occurrence=int(ids[-1]), last_aux_slot=int(slots[-1]),
                        initial_hash=initial_hash, run_contract_hash=EXPECTED["run_contract"],
                    )
                    append_jsonl(checkpoint_index, {
                        "global_step": global_step, "epoch": epoch, "epoch_step": slot_index,
                        "path": checkpoint_path.name, "sha256": checkpoint_hash,
                        "head_sha256": state_digest(head.state_dict()),
                        "last_committed_occurrence_index": int(ids[-1]),
                    })
                    print(json.dumps({"event": "checkpoint_sealed", "seed": seed, "arm": arm,
                                      "global_step": global_step, "sha256": checkpoint_hash}, separators=(",", ":")),
                          flush=True)
        expected_steps = 120 - start_step
        committed_steps = [row for row in read_jsonl(events_path) if row.get("event") == "optimizer_step"]
        require(len(committed_steps) == expected_steps, f"optimizer-step count mismatch {seed}/{arm}")
        checkpoint_rows = read_jsonl(checkpoint_index)
        require(len(checkpoint_rows) == 42 and [row["global_step"] for row in checkpoint_rows]
                == [40, 80, *range(81, 121)], f"checkpoint cadence mismatch {seed}/{arm}")
        append_jsonl(events_path, {"event": "run_training_complete", "seed": seed, "arm": arm,
                                   "evaluation_access": False})
        integrity = {
            "status": "TRAINING_COMPLETE_UNEVALUATED", "seed": seed, "arm": arm,
            "initial_head_sha256": initial_hash, "terminal_head_sha256": state_digest(head.state_dict()),
            "optimizer_steps": 120, "checkpoint_count": 42,
            "checkpoint_index_sha256": sha256_file(checkpoint_index),
            "training_events_sha256": sha256_file(events_path),
            "run_config_sha256": sha256_file(attempt / "run-config.json"),
            "resume_receipt_sha256": sha256_file(attempt / "resume-receipt.json") if (attempt / "resume-receipt.json").exists() else None,
            "resume_global_step": start_step,
            "schedule_sha256": schedule_hash, "backbone_frozen": True,
            "evaluation_access": False, "newtight_access": False, "phoenix_access": False,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(attempt / "run-integrity.json", integrity)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        if run_dir.exists():
            raise RuntimeError(f"run destination appeared during training: {run_dir}")
        os.replace(attempt, run_dir)
        return integrity
    except BaseException as exc:
        failure = {
            "status": "ATTEMPT_FAILED_RETAINED", "seed": seed, "arm": arm,
            "exception_type": type(exc).__name__, "exception": str(exc),
            "attempt_path": str(attempt), "last_checkpoint_step": start_step,
            "evaluation_access": False, "phoenix_access": False,
        }
        failure_path = attempt / "failure-receipt.json"
        if not failure_path.exists():
            write_json(failure_path, failure)
        raise


def create_initial_templates(run_contract: dict[str, Any], probe: Any) -> dict[int, tuple[dict[str, torch.Tensor], str]]:
    template_root = TRAIN_ROOT / "initial-templates"
    template_root.mkdir(parents=True, exist_ok=True)
    result: dict[int, tuple[dict[str, torch.Tensor], str]] = {}
    for seed in SEEDS:
        seed_everything(seed)
        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
        state = cpu_clone(head.state_dict())
        digest = state_digest(state)
        require(sum(value.numel() for value in state.values()) == 590_081, "initial head parameter count mismatch")
        path = template_root / f"seed-{seed}.pt"
        require(not path.exists(), f"initial template already exists: {path}")
        h = atomic_torch_save({"seed": seed, "state_dict": state, "state_sha256": digest}, path)
        require(h == sha256_file(path), "initial template durable hash mismatch")
        result[seed] = (state, digest)
        del head
        torch.cuda.empty_cache()
    return result


def build_training_seal(order: list[str], integrity_rows: list[dict[str, Any]], run_contract: dict[str, Any],
                        source_hashes: dict[str, str], preflight_sha: str) -> dict[str, Any]:
    checkpoint_entries: list[dict[str, Any]] = []
    telemetry_entries: list[dict[str, Any]] = []
    for seed in SEEDS:
        template = TRAIN_ROOT / "initial-templates" / f"seed-{seed}.pt"
        checkpoint_entries.append({"path": str(template), "sha256": sha256_file(template), "bytes": template.stat().st_size,
                                   "kind": "initial_template", "seed": seed})
    for seed in SEEDS:
        for arm in ARMS:
            run_dir = TRAIN_ROOT / "runs" / f"seed-{seed}" / arm
            integrity = read_json(run_dir / "run-integrity.json")
            require(integrity.get("status") == "TRAINING_COMPLETE_UNEVALUATED" and integrity.get("checkpoint_count") == 42,
                    f"run completeness seal failed: {seed}/{arm}")
            index = read_jsonl(run_dir / "checkpoint-index.jsonl")
            require(len(index) == 42, f"checkpoint index count mismatch: {seed}/{arm}")
            for item in index:
                path = run_dir / item["path"]
                require(path.is_file() and sha256_file(path) == item["sha256"],
                        f"checkpoint hash mismatch: {seed}/{arm}/{item['global_step']}")
                checkpoint_entries.append({"path": str(path), "sha256": item["sha256"],
                                           "bytes": path.stat().st_size, "kind": "trained_checkpoint",
                                           "seed": seed, "arm": arm, "global_step": item["global_step"]})
            for filename, kind in (("training-events.jsonl", "training_telemetry"),
                                   ("checkpoint-index.jsonl", "checkpoint_index"),
                                   ("run-config.json", "run_config"),
                                   ("run-integrity.json", "run_integrity")):
                file = run_dir / filename
                entry = {"path": str(file), "sha256": sha256_file(file), "bytes": file.stat().st_size,
                         "kind": kind, "seed": seed, "arm": arm}
                if kind == "training_telemetry":
                    telemetry_entries.append(entry)
                checkpoint_entries.append(entry)
    checkpoint_tree = {"status": "P_R2_ALL_CHECKPOINTS_HASHED", "entry_count": len(checkpoint_entries),
                       "trained_checkpoint_count": 378, "initial_template_count": 3,
                       "entries": checkpoint_entries}
    telemetry_tree = {"status": "P_R2_ALL_TRAINING_TELEMETRY_HASHED", "entry_count": len(telemetry_entries),
                      "entries": telemetry_entries}
    return {
        "status": "P_R2_ALL_NINE_RUNS_COMPLETE_SEALED_UNEVALUATED",
        "protocol": run_contract["protocol"],
        "identity": "v0.8P-R2-late-transition-localization-v01",
        "run_contract_sha256": EXPECTED["run_contract"],
        "analysis_contract_sha256": EXPECTED["analysis_contract"],
        "analysis_addendum_sha256": EXPECTED["addendum"],
        "r2_execution_contract_sha256": EXPECTED["r2_contract"],
        "training_preflight_receipt_sha256": preflight_sha,
        "schedule_sha256": EXPECTED["schedule"],
        "source_hashes": source_hashes,
        "run_count": 9, "seed_count": 3, "trained_checkpoint_count": 378,
        "initial_template_count": 3, "completed_order": order,
        "checkpoint_entries": len(checkpoint_entries), "telemetry_entries": len(telemetry_entries),
        "evaluation_access": False, "heldout_panel_opened": False,
        "newtight_access": False, "legacy_evaluation_access": False, "phoenix_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "run"))
    args = parser.parse_args()
    run_contract, analysis_contract, r2_contract = load_contracts()
    runtime = verify_runtime(run_contract)
    probe, trainer = import_frozen_components()
    state_cpu, candidate_cpu, primary, schedule, arm_rows, _metadata = verify_training_inputs(run_contract)
    schedule_hash = sha256_file(SCHEDULE_ROOT / "fixed-schedule.jsonl")
    hashes = source_bindings()
    require(hashes["fixed_schedule"] == schedule_hash == EXPECTED["schedule"], "schedule source binding mismatch")
    event_adapter_validation = verify_scheduled_batch_materialization(
        trainer, state_cpu, candidate_cpu, primary, schedule, arm_rows,
    )

    if args.mode == "preflight":
        synthetic = synthetic_self_test(probe, trainer)
        recovery = verify_preupdate_restart_state()
        instrument_paths = {
            "trainer": Path(__file__).resolve(),
            "evaluator": R2_WORK / "runner/evaluate_r2_trajectory.py",
            "analysis": R2_WORK / "runner/analyze_r2_trajectory.py",
            "analysis_adapter": R2_WORK / "runner/r2_analysis_adapter.py",
            "analysis_test": R2_WORK / "runner/test_r2_trajectory_analysis.py",
            "evaluator_test": R2_WORK / "runner/test_r2_evaluator.py",
            "trajectory_helper": P_PHASE / "trajectory_analysis.py",
            "metric_analyzer": ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
        }
        require(all(path.is_file() for path in instrument_paths.values()),
                "complete P-R2 instrument source set is not materialized")
        instrument_source_hashes = {key: sha256_file(path) for key, path in instrument_paths.items()}
        receipt_path = R2_WORK / "provenance/r2-pretraining-preflight-v03.json"
        require(not receipt_path.exists(), "pretraining receipt already exists; refusing overwrite")
        receipt = {
            "status": "P_R2_RECOVERY_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS",
            "supersedes_preflight_v01_sha256": recovery["superseded_preflight_v01_sha256"],
            "supersedes_preflight_v02_sha256": recovery["superseded_preflight_v02_sha256"],
            "preupdate_restart_evidence": recovery,
            "scheduled_batch_materialization": event_adapter_validation,
            "run_contract_sha256": EXPECTED["run_contract"],
            "analysis_contract_sha256": EXPECTED["analysis_contract"],
            "analysis_addendum_sha256": EXPECTED["addendum"],
            "r2_execution_contract_sha256": EXPECTED["r2_contract"],
            "r2_panel_ready_manifest_sha256": EXPECTED["panel_ready"],
            "schedule_sha256": schedule_hash,
            "trainer_sha256": sha256_file(Path(__file__).resolve()),
            "probe_sha256": EXPECTED["probe"], "loss_batcher_sha256": EXPECTED["loss"],
            "metric_implementation_sha256": EXPECTED["metric"],
            "trajectory_helper_sha256": EXPECTED["trajectory_helper"],
            "analysis_adapter_sha256": sha256_file(R2_WORK / "runner/r2_analysis_adapter.py"),
            "synthetic_test_sha256": sha256_file(R2_WORK / "runner/test_r2_trajectory_analysis.py"),
            "analysis_addendum": "outcome-blind and sealed before head initialization",
            "source_hashes": hashes,
            "instrument_source_hashes": instrument_source_hashes,
            "runtime": runtime,
            "synthetic_tests": synthetic,
            "primary_rows": len(primary), "schedule_rows": len(schedule),
            "arm_manifest_rows": {arm: len(arm_rows[arm]) for arm in ARMS},
            "state_feature_shape": list(state_cpu.shape), "candidate_feature_shape": list(candidate_cpu.shape),
            "head_initialized_for_experiment": True,
            "head_training_started": False,
            "optimizer_steps_committed_before_recovery": 0,
            "synthetic_head_fixture_only": True,
            "heldout_panel_or_features_read": False,
            "E1_access": False, "newtight_access": False, "phoenix_access": False,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(receipt_path, receipt)
        print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path),
                          "schedule_sha256": schedule_hash, "synthetic_test": synthetic["status"],
                          "head_training": False}, separators=(",", ":")))
        return 0

    preflight_path = R2_WORK / "provenance/r2-pretraining-preflight-v03.json"
    require(preflight_path.is_file(), "sealed recovery preflight is required before restart")
    preflight = read_json(preflight_path)
    preflight_sha = sha256_file(preflight_path)
    require(preflight["status"] == "P_R2_RECOVERY_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS"
            and preflight["trainer_sha256"] == sha256_file(Path(__file__).resolve())
            and preflight["schedule_sha256"] == schedule_hash,
            "pretraining seal/code/schedule mismatch")
    verify_bound_preupdate_evidence(preflight["preupdate_restart_evidence"])
    require(preflight["scheduled_batch_materialization"] == event_adapter_validation,
            "scheduled batch materialization differs from the sealed preflight")
    TRAIN_ROOT.mkdir(parents=True, exist_ok=True)
    state_features = state_cpu.to("cuda")
    candidate_features = candidate_cpu.to("cuda")
    require(torch.backends.cuda.matmul.allow_tf32 is False, "TF32 matmul enabled after input materialization")
    template_root = TRAIN_ROOT / "initial-templates"
    template_paths = [template_root / f"seed-{seed}.pt" for seed in SEEDS]
    if any(path.exists() for path in template_paths):
        require(all(path.is_file() for path in template_paths),
                "partial initial-template set; preserve artifacts and fail closed")
        templates = {}
        for seed, path in zip(SEEDS, template_paths, strict=True):
            payload = torch.load(path, map_location="cpu", weights_only=True)
            state = payload["state_dict"]
            digest = state_digest(state)
            require(payload.get("seed") == seed and payload.get("state_sha256") == digest
                    and sum(t.numel() for t in state.values()) == 590_081,
                    f"initial template identity mismatch: {path}")
            templates[seed] = (state, digest)
    else:
        templates = create_initial_templates(run_contract, probe)
    expected_templates = preflight["preupdate_restart_evidence"]["paired_initial_templates"]
    actual_templates = [
        {"seed": seed, "file_sha256": sha256_file(template_root / f"seed-{seed}.pt"),
         "state_sha256": templates[seed][1]}
        for seed in SEEDS
    ]
    require(actual_templates == [
        {"seed": row["seed"], "file_sha256": row["file_sha256"], "state_sha256": row["state_sha256"]}
        for row in expected_templates
    ], "initial templates differ from the sealed pre-update restart basis")
    order_spec = seed_order(r2_contract)
    completed: list[str] = []
    integrities: list[dict[str, Any]] = []
    schedule_rows_by_seed = {seed: [row for row in schedule if row["seed"] == seed] for seed in SEEDS}
    try:
        for seed in SEEDS:
            initial_state, initial_hash = templates[seed]
            for arm in order_spec[seed]:
                run_dir = TRAIN_ROOT / "runs" / f"seed-{seed}" / arm
                if run_dir.exists():
                    integrity_path = run_dir / "run-integrity.json"
                    require(integrity_path.is_file(), f"existing run is not sealed complete: {run_dir}")
                    integrity = read_json(integrity_path)
                    require(integrity.get("status") == "TRAINING_COMPLETE_UNEVALUATED"
                            and integrity.get("seed") == seed and integrity.get("arm") == arm
                            and integrity.get("initial_head_sha256") == initial_hash
                            and integrity.get("optimizer_steps") == 120
                            and integrity.get("checkpoint_count") == 42,
                            f"existing completed run identity mismatch: {run_dir}")
                    index = read_jsonl(run_dir / "checkpoint-index.jsonl")
                    require(len(index) == 42 and all(
                        (run_dir / row["path"]).is_file()
                        and sha256_file(run_dir / row["path"]) == row["sha256"] for row in index),
                        f"existing completed run checkpoint tree mismatch: {run_dir}")
                    completed.append(f"{seed}/{arm}")
                    integrities.append({"seed": seed, "arm": arm, **integrity})
                    print(json.dumps({"event": "run_already_sealed", "seed": seed, "arm": arm,
                                      "completed_runs": len(completed), "evaluation_access": False}, separators=(",", ":")),
                          flush=True)
                    continue
                seed_everything(seed)
                integrity = run_one(
                    run_contract, probe, trainer, seed=seed, arm=arm,
                    initial_state=initial_state, state_features=state_features,
                    candidate_features=candidate_features, primary=primary,
                    schedule=schedule_rows_by_seed[seed], arm_rows=arm_rows[arm],
                    schedule_hash=schedule_hash, initial_hash=initial_hash,
                )
                require(integrity["initial_head_sha256"] == initial_hash,
                        f"paired initialization drift for {seed}/{arm}")
                integrities.append({"seed": seed, "arm": arm, **integrity})
                completed.append(f"{seed}/{arm}")
                replace_json(TRAIN_ROOT / "execution-order-progress.json", {
                    "status": "IN_PROGRESS", "authorized_order": [f"{s}/{a}" for s in SEEDS for a in order_spec[s]],
                    "completed_order": completed,
                })
                print(json.dumps({"event": "run_complete", "seed": seed, "arm": arm,
                                  "completed_runs": len(completed), "evaluation_access": False}, separators=(",", ":")),
                      flush=True)
        expected_order = [f"{seed}/{arm}" for seed in SEEDS for arm in order_spec[seed]]
        require(completed == expected_order, "global run execution order mismatch")
        write_json(TRAIN_ROOT / "execution-order.json", {
            "status": "COMPLETE", "authorized_order": expected_order, "completed_order": completed,
        })
        replace_json(TRAIN_ROOT / "execution-order-progress.json", {
            "status": "COMPLETE", "authorized_order": expected_order, "completed_order": completed,
        })
        seal = build_training_seal(completed, integrities, run_contract, hashes, preflight_sha)
        # Build the trees independently from the completed on-disk run manifests.
        checkpoint_entries = []
        telemetry_entries = []
        for path in sorted((TRAIN_ROOT / "initial-templates").glob("*.pt")):
            checkpoint_entries.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
                                       "kind": "initial_template"})
        for seed in SEEDS:
            for arm in ARMS:
                run_dir = TRAIN_ROOT / "runs" / f"seed-{seed}" / arm
                for item in sorted(run_dir.iterdir()):
                    if not item.is_file():
                        continue
                    entry = {"path": str(item), "sha256": sha256_file(item), "bytes": item.stat().st_size,
                             "seed": seed, "arm": arm}
                    if item.name.startswith("step-") and item.suffix == ".pt":
                        entry.update({"kind": "trained_checkpoint", "global_step": int(item.stem.split("-")[1])})
                    else:
                        entry["kind"] = item.name
                    checkpoint_entries.append(entry)
                    if item.name == "training-events.jsonl":
                        telemetry_entries.append(entry)
                attempt_root = TRAIN_ROOT / "attempts" / f"seed-{seed}" / arm
                if attempt_root.exists():
                    for attempt_file in sorted(attempt_root.glob("attempt-*/*")):
                        if not attempt_file.is_file():
                            continue
                        entry = {"path": str(attempt_file), "sha256": sha256_file(attempt_file),
                                 "bytes": attempt_file.stat().st_size, "seed": seed, "arm": arm,
                                 "kind": "preserved_failed_attempt_artifact"}
                        checkpoint_entries.append(entry)
                        if attempt_file.name == "training-events.jsonl":
                            telemetry_entries.append(entry)
        require(sum(row["kind"] == "trained_checkpoint" for row in checkpoint_entries) == 378,
                "checkpoint hash tree does not contain 378 trained states")
        checkpoint_tree_path = TRAIN_ROOT / "checkpoint-hash-tree.json"
        telemetry_tree_path = TRAIN_ROOT / "training-telemetry-hash-tree.json"
        for root_file in (TRAIN_ROOT / "execution-order.json", TRAIN_ROOT / "execution-order-progress.json",
                          TRAIN_ROOT / "training-failure-receipt.json"):
            if root_file.is_file():
                checkpoint_entries.append({"path": str(root_file), "sha256": sha256_file(root_file),
                                           "bytes": root_file.stat().st_size, "kind": root_file.name})
        write_json(checkpoint_tree_path, {"status": "P_R2_ALL_CHECKPOINTS_HASHED", "trained_checkpoint_count": 378,
                                          "initial_template_count": 3, "entry_count": len(checkpoint_entries),
                                          "entries": checkpoint_entries})
        write_json(telemetry_tree_path, {"status": "P_R2_ALL_TRAINING_TELEMETRY_HASHED",
                                         "entry_count": len(telemetry_entries), "entries": telemetry_entries})
        seal["checkpoint_hash_tree_sha256"] = sha256_file(checkpoint_tree_path)
        seal["training_telemetry_hash_tree_sha256"] = sha256_file(telemetry_tree_path)
        seal["execution_order_sha256"] = sha256_file(TRAIN_ROOT / "execution-order.json")
        seal_path = TRAIN_ROOT / "training-seal-manifest.json"
        write_json(seal_path, seal)
        print(json.dumps({"status": seal["status"], "runs": 9, "trained_checkpoints": 378,
                          "initial_templates": 3, "training_seal": str(seal_path),
                          "evaluation_access": False}, separators=(",", ":")), flush=True)
    except BaseException as exc:
        failure = TRAIN_ROOT / "training-failure-receipt.json"
        if not failure.exists():
            write_json(failure, {"status": "P_R2_TRAINING_FAILED_CLOSED", "exception_type": type(exc).__name__,
                                 "exception": str(exc), "completed_runs": completed,
                                 "evaluation_access": False, "phoenix_access": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
