"""Run the locked R3 balanced cohort and high-to-low bridge through step 120."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
BASE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
INPUT = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-inputs-v03")
TRAIN = RUN / "training-v01"
PREFLIGHT = TRAIN / "preflight-v01"
ARTIFACTS = TRAIN / "artifacts-v01"
PANEL = RUN / "panel-v03"
FEATURES = RUN / "features-v01"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
SCHEDULE_TOOL = EXP / "source/materialize_r3_training_schedule_v01.py"
CALIBRATION_RUNNER = EXP / "source/run_r3_pretreatment_calibration_v01.py"
PROBE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
BATCHER = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
OBJECTIVE = ROOT / "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py"

EXPECTED = {
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "batcher": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "objective": "fc412072592857be36b02312d852d08ce3df2bf6fa7b28f8c1d59575c28e1ea4",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
}
PROFILE = "name_definition"
BRANCHES = (("ONE_X", 1.0), ("HALF", 0.5))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def tree_root(directory: Path, entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        path = directory / entry["path"]
        require(path.is_file() and path.stat().st_size == entry["bytes"]
            and sha_file(path) == entry["sha256"], f"sealed artifact changed: {entry['path']}")
        digest.update(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode())
    return digest.hexdigest()


def metadata_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        digest.update(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode())
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load bound helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_lock() -> dict[str, Any]:
    lock = read_json(LOCK)
    body = {key: value for key, value in lock.items() if key != "contract_bundle_root_sha256"}
    calculated = sha_bytes(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    require(lock.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
        and lock.get("contract_bundle_root_sha256") == calculated, "R3 phase lock invalid")
    for item in lock.get("execution_sources", []):
        require(sha_file(Path(item["path"])) == item["sha256"],
            f"locked execution source drift: {item['name']}")
    for item in lock.get("contracts", []):
        require(sha_file(Path(item["path"])) == item["sha256"], f"locked contract drift: {item['name']}")
    for item in lock.get("sealed_inputs", []):
        require(Path(item["path"]).is_file() and sha_file(Path(item["path"])) == item["sha256"],
            f"locked pre-run input drift: {item['name']}")
    require(any(Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in lock.get("execution_sources", [])), "training runner not bound by R3 lock")
    return lock


def verify_sealed_directory(directory: Path, seal_path: Path, expected_status: str,
                            verify_paths: set[str] | None = None) -> dict[str, Any]:
    seal = read_json(seal_path)
    require(seal.get("status") == expected_status, f"unexpected seal state: {seal_path.name}")
    entries = seal.get("entries", [])
    require(bool(entries) and metadata_root(entries) == seal.get("entries_root_sha256"),
        f"sealed metadata root mismatch: {seal_path.name}")
    selected = {entry["path"] for entry in entries} if verify_paths is None else verify_paths
    entry_map = {entry["path"]: entry for entry in entries}
    require(selected.issubset(entry_map), f"requested verification file absent from seal: {seal_path.name}")
    for name in selected:
        entry = entry_map[name]
        path = directory / name
        require(path.is_file() and path.stat().st_size == entry["bytes"] and sha_file(path) == entry["sha256"],
            f"sealed artifact changed: {name}")
    return seal


def capture_rng() -> dict[str, Any]:
    import random

    return {"python": random.getstate(), "torch_cpu": torch.get_rng_state().clone(),
        "torch_cuda": [value.cpu().clone() for value in torch.cuda.get_rng_state_all()]}


def restore_rng(state: dict[str, Any]) -> None:
    import random

    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in state["torch_cuda"]])


def clone_cpu(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {key: clone_cpu(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clone_cpu(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clone_cpu(item) for item in value)
    return value


def run_steps(cohort: str, seed: int, start: int, stop: int, multiplier: float,
              schedule_rows: list[dict[str, Any]], primary: list[dict[str, Any]],
              auxiliary: list[dict[str, Any]], states: torch.Tensor, candidates: torch.Tensor,
              head: torch.nn.Module, optimizer: torch.optim.Optimizer, helper: Any,
              batcher: Any, objective: Any, telemetry_path: Path,
              checkpoint_dir: Path, branch_name: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    selected = [row for row in schedule_rows if start < int(row["global_step"]) <= stop]
    require(len(selected) == stop - start, f"{cohort}/{seed} schedule slice incomplete: {start}:{stop}")
    telemetry_rows: list[dict[str, Any]] = []
    fork_payload = None
    with telemetry_path.open("xb") as telemetry:
        for item in selected:
            indices = item["primary_occurrence_indices"]
            primary_batch = [primary[index] for index in indices]
            auxiliary_batch = [auxiliary[index] for index in item["auxiliary_anchor_batch_slots"]]
            batch = [helper.prepare(row) for row in primary_batch]
            batch.extend(helper.prepare(row) for row in auxiliary_batch)
            state, candidate, gold, mask, kinds, sources = batcher.fast_tensor_batch(
                batch, states, candidates, PROFILE, "cuda", reorder=True)
            weights = torch.ones(len(batch), device="cuda")
            if auxiliary_batch:
                weights[len(primary_batch):] = multiplier
            optimizer.zero_grad(set_to_none=True)
            logits = head(state, candidate)
            loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
            require(bool(torch.isfinite(loss).item()) and bool(torch.isfinite(brier).item()),
                f"nonfinite loss at {cohort}/{seed}/{item['global_step']}/{branch_name}")
            loss.backward()
            grad_sq = torch.zeros((), device="cuda")
            for parameter in head.parameters():
                if parameter.grad is not None:
                    require(bool(torch.isfinite(parameter.grad).all().item()),
                        f"nonfinite gradient at {cohort}/{seed}/{item['global_step']}/{branch_name}")
                    grad_sq += parameter.grad.detach().float().square().sum()
            optimizer.step()
            torch.cuda.synchronize()
            gradient_norm = float(grad_sq.sqrt().cpu())
            require(math.isfinite(gradient_norm),
                f"nonfinite gradient norm at {cohort}/{seed}/{item['global_step']}/{branch_name}")
            record = {
                "cohort": cohort, "seed": seed, "global_step": int(item["global_step"]),
                "branch": branch_name or "COMMON", "auxiliary_multiplier": multiplier,
                "primary_occurrence_indices": indices,
                "auxiliary_anchor_batch_slots": item["auxiliary_anchor_batch_slots"],
                "primary_rows": len(primary_batch), "auxiliary_rows": len(auxiliary_batch),
                "active_rows": len(batch), "loss": float(loss.detach().cpu()),
                "brier": float(brier.detach().cpu()), "gradient_norm": gradient_norm,
                "panel_opened": False,
            }
            telemetry.write((json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                + "\n").encode("utf-8"))
            telemetry.flush()
            os.fsync(telemetry.fileno())
            telemetry_rows.append(record)
            if item["global_step"] in (100, 120):
                model = {key: value.detach().cpu().clone() for key, value in head.state_dict().items()}
                payload = {"schema": "jev-r3-head-snapshot-v01", "cohort": cohort, "seed": seed,
                    "branch": branch_name, "global_step": int(item["global_step"]), "head_state": model,
                    "head_sha256": helper.state_sha(head.state_dict()),
                    "auxiliary_multiplier": multiplier, "schedule_step_sha256": sha_bytes(
                        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
                    "panel_opened": False}
                checkpoint_path = checkpoint_dir / f"step-{int(item['global_step']):03d}.pt"
                helper.save_payload(checkpoint_path, payload)
            del state, candidate, gold, mask, kinds, sources, logits, loss, brier, weights
        if stop == 80:
            torch.cuda.synchronize()
            fork_payload = {
                "schema": "jev-r3-complete-step80-fork-v01", "cohort": cohort, "seed": seed,
                "global_step": 80, "event_cursor": 80, "auxiliary_multiplier": 1.0,
                "head_state": clone_cpu(head.state_dict()), "optimizer_state": clone_cpu(optimizer.state_dict()),
                "head_sha256": helper.state_sha(head.state_dict()),
                "optimizer_sha256": helper.tree_sha(optimizer.state_dict()),
                "rng_state": capture_rng(), "panel_opened": False,
            }
    return fork_payload, telemetry_rows


def train_history(cohort: str, seed: int, schedule_rows: list[dict[str, Any]],
                  primary: list[dict[str, Any]], auxiliary: list[dict[str, Any]],
                  states: torch.Tensor, candidates: torch.Tensor, helper: Any,
                  batcher: Any, objective: Any) -> dict[str, Any]:
    import random

    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    probe = train_history.probe
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.train()
    init_state = clone_cpu(head.state_dict())
    init_hash = helper.state_sha(init_state)
    require(sum(value.numel() for value in init_state.values()) == 590_081, "R3 head parameter count mismatch")
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
        betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    history_dir = ARTIFACTS / cohort / f"seed-{seed}"
    common_dir = history_dir / "common"
    branch_dir = history_dir / "branches"
    common_dir.mkdir(parents=True, exist_ok=False)
    branch_dir.mkdir(parents=True, exist_ok=False)
    common_schedule = [row for row in schedule_rows if int(row["seed"]) == seed and int(row["global_step"]) <= 80]
    common_fork, common_telemetry = run_steps(cohort, seed, 0, 80, 1.0, common_schedule,
        primary, auxiliary, states, candidates, head, optimizer, helper, batcher, objective,
        common_dir / "training-telemetry.jsonl", common_dir, None)
    require(common_fork is not None and common_fork["head_sha256"] == helper.state_sha(head.state_dict()),
        f"step-80 fork state mismatch: {cohort}/{seed}")
    common_path = common_dir / "step-080.pt"
    common_fork["initial_head_sha256"] = init_hash
    common_fork["schedule_sha256"] = sha_file(PREFLIGHT / ("balanced-schedule.jsonl" if cohort == "balanced" else "bridge-schedule.jsonl"))
    helper.save_payload(common_path, common_fork)
    branches: dict[str, dict[str, str]] = {}
    branch_telemetry_count = 0
    for branch_name, multiplier in BRANCHES:
        head.load_state_dict(common_fork["head_state"], strict=True)
        optimizer.load_state_dict(common_fork["optimizer_state"])
        require(helper.state_sha(head.state_dict()) == common_fork["head_sha256"]
            and helper.tree_sha(optimizer.state_dict()) == common_fork["optimizer_sha256"],
            f"step-80 head/optimizer clone mismatch: {cohort}/{seed}/{branch_name}")
        restore_rng(common_fork["rng_state"])
        one_branch = branch_dir / branch_name
        one_branch.mkdir(parents=False, exist_ok=False)
        branch_schedule = [row for row in schedule_rows if int(row["seed"]) == seed and int(row["global_step"]) > 80]
        _, branch_telemetry = run_steps(cohort, seed, 80, 120, multiplier, branch_schedule,
            primary, auxiliary, states, candidates, head, optimizer, helper, batcher, objective,
            one_branch / "training-telemetry.jsonl", one_branch, branch_name)
        require(len(branch_telemetry) == 40 and [row["global_step"] for row in branch_telemetry] == list(range(81, 121)),
            f"continuation telemetry incomplete: {cohort}/{seed}/{branch_name}")
        for step in (100, 120):
            path = one_branch / f"step-{step:03d}.pt"
            require(path.is_file(), f"missing prescribed checkpoint: {path}")
            branches[branch_name + f"_{step}"] = {"path": str(path), "sha256": sha_file(path)}
        branch_telemetry_count += len(branch_telemetry)
    common_receipt = {"schema": "jev-r3-history-training-receipt-v01", "cohort": cohort, "seed": seed,
        "initial_head_sha256": init_hash, "step80_checkpoint_sha256": sha_file(common_path),
        "step80_head_sha256": common_fork["head_sha256"], "step80_optimizer_sha256": common_fork["optimizer_sha256"],
        "common_steps": 80, "branch_steps_each": 40, "branch_checkpoints": branches,
        "telemetry_rows": len(common_telemetry) + branch_telemetry_count,
        "evaluation_panel_opened": False, "predictions_created": False, "metrics_computed": False}
    receipt_path = history_dir / "history-training-receipt.json"
    write_json(receipt_path, common_receipt)
    del optimizer, head
    torch.cuda.empty_cache()
    return common_receipt


def main() -> int:
    require(not ARTIFACTS.exists(), f"refusing existing R3 training artifacts: {ARTIFACTS}")
    lock = verify_lock()
    panel_seal = verify_sealed_directory(PANEL, PANEL / "seals/r3-panel-seal-v01.json",
        "R3_V03_PANEL_SEALED_FEATURE_EXTRACTION_PENDING", {
            "candidate-texts.jsonl", "r3-panel-inference-manifest.jsonl",
            "r3-panel-texts-target-free-v01.jsonl"})
    feature_seal = read_json(FEATURES / "feature-cache-seal-v01.json")
    require(feature_seal.get("status") == "R3_V03_FEATURE_CACHE_SEALED_TRAINING_PENDING",
        "R3 confirmatory feature cache is not sealed")
    feature_entries = feature_seal.get("entries", [])
    feature_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(feature_entries, key=lambda item: item["path"])
    ).encode()).hexdigest()
    require(feature_root == feature_seal.get("entries_root_sha256"), "R3 feature cache root mismatch")
    for row in feature_entries:
        path = FEATURES / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha_file(path) == row["sha256"],
            f"R3 feature cache artifact changed: {row['path']}")
    preflight_seal = verify_sealed_directory(PREFLIGHT, PREFLIGHT / "pretraining-seal-v01.json",
        "R3_V03_PRETRAINING_INPUTS_AND_SCHEDULE_SEALED")
    preflight_manifest = read_json(PREFLIGHT / "training-schedule-manifest.json")
    require(preflight_manifest.get("lock_bundle_root_sha256") == lock["contract_bundle_root_sha256"],
        "training preflight belongs to another R3 lock")
    require(preflight_manifest.get("panel_seal_sha256") == sha_file(PANEL / "seals/r3-panel-seal-v01.json")
        and preflight_manifest.get("feature_cache_seal_sha256") == sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "training preflight does not bind the sealed panel/features")
    for key, path in (("probe", PROBE), ("batcher", BATCHER), ("objective", OBJECTIVE)):
        require(sha_file(path) == EXPECTED[key], f"frozen training dependency changed: {key}")
    schedule_tool = load_module(SCHEDULE_TOOL, "jev_r3_schedule_tool")
    helper = load_module(CALIBRATION_RUNNER, "jev_r3_training_helper")
    run_contract = read_json(EXP / "contracts/r3-v03-run-contract.json")
    require(sha_file(EXP / "contracts/r3-v03-run-contract.json") ==
        next(row["sha256"] for row in lock["contracts"] if row["name"] == "run"), "run contract changed")
    require(platform.python_version() == "3.13.15" and torch.__version__ == "2.11.0+cu128" and torch.cuda.is_available()
        and torch.version.cuda == "12.8" and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080",
        "R3 training runtime/device identity mismatch")
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    require(torch.backends.cuda.matmul.allow_tf32 is False,
        "R3 runtime CUDA matmul TF32 mode drift")
    require(not torch.are_deterministic_algorithms_enabled(), "R3 runtime deterministic-algorithm mode drift")

    input_paths = {
        "balanced_primary": INPUT / "balanced-primary-occurrences.jsonl",
        "balanced_sham": INPUT / "balanced-sham-events.jsonl",
        "reverse_sham": INPUT / "reverse-sham-texts.jsonl",
        "training_features": BASE / "shared-feature-cache/shared-training-features.pt",
        "candidate_features": BASE / "phase-b-run-v01/feature-cache/candidate-features.pt",
        "reverse_features": FEATURES / "reverse-sham-state-features.pt",
    }
    expected_inputs = preflight_manifest.get("input_bindings", {})
    for name, path in input_paths.items():
        require(name in expected_inputs and sha_file(path) == expected_inputs[name],
            f"R3 training input differs from sealed schedule binding: {name}")
    primary = read_jsonl(input_paths["balanced_primary"])
    auxiliary = read_jsonl(input_paths["balanced_sham"])
    reverse_rows = read_jsonl(input_paths["reverse_sham"])
    require((len(primary), len(auxiliary), len(reverse_rows)) == (10_000, 5_000, 2_500),
        "R3 balanced training inputs have unexpected row counts")
    base_features = torch.load(input_paths["training_features"], map_location="cpu", weights_only=True)["features"]
    reverse_features = torch.load(input_paths["reverse_features"], map_location="cpu", weights_only=True)["features"]
    candidates = torch.load(input_paths["candidate_features"], map_location="cpu", weights_only=True)
    require(tuple(base_features.shape) == (55_000, 2048) and tuple(reverse_features.shape) == (2_500, 2048)
        and tuple(candidates.shape) == (48, 2048), "R3 feature tensor shape mismatch")
    states = torch.cat((base_features, reverse_features), dim=0).contiguous()
    require(tuple(states.shape) == (57_500, 2048) and bool(torch.isfinite(states).all())
        and bool(torch.isfinite(candidates).all()), "R3 state/candidate features invalid")
    seeds = [int(value) for value in read_json(PREFLIGHT / "seed-manifest.json")["seeds"]]
    bridge_indices = [int(value) for value in read_json(PREFLIGHT / "seed-manifest.json")["bridge_indices"]]
    bridge_seeds = [seeds[index] for index in bridge_indices]
    balanced_schedule = read_jsonl(PREFLIGHT / "balanced-schedule.jsonl")
    bridge_schedule = read_jsonl(PREFLIGHT / "bridge-schedule.jsonl")
    bridge_primary = read_jsonl(PREFLIGHT / "bridge-primary-occurrences.jsonl")
    bridge_auxiliary = read_jsonl(PREFLIGHT / "bridge-sham-events.jsonl")
    require(len(seeds) == 192 and len(bridge_seeds) == 24 and len(set(seeds)) == 192,
        "R3 seed cohort identity mismatch")
    schedule_tool.validate_schedule(primary, auxiliary, balanced_schedule, seeds)
    schedule_tool.validate_schedule(bridge_primary, bridge_auxiliary, bridge_schedule, bridge_seeds)
    require(len(balanced_schedule) == 192 * 120 and len(bridge_schedule) == 24 * 120,
        "R3 complete training schedule count mismatch")

    probe = helper.load_module(PROBE, "jev_r3_probe")
    batcher = helper.load_module(BATCHER, "jev_r3_batcher")
    objective = helper.load_module(OBJECTIVE, "jev_r3_objective")
    train_history.probe = probe
    ARTIFACTS.mkdir(parents=True, exist_ok=False)
    all_receipts: list[dict[str, Any]] = []
    initial_hashes: dict[tuple[str, int], str] = {}
    started = time.time()
    cohorts = (("balanced", seeds, primary, auxiliary, balanced_schedule),
        ("high_to_low_bridge", bridge_seeds, bridge_primary, bridge_auxiliary, bridge_schedule))
    total = len(seeds) + len(bridge_seeds)
    completed = 0
    for cohort, cohort_seeds, cohort_primary, cohort_aux, cohort_schedule in cohorts:
        for seed in cohort_seeds:
            receipt = train_history(cohort, seed, cohort_schedule, cohort_primary, cohort_aux,
                states, candidates, helper, batcher, objective)
            initial_hashes[(cohort, seed)] = receipt["initial_head_sha256"]
            all_receipts.append(receipt)
            completed += 1
            print(json.dumps({"status": "R3_TRAINING_PROGRESS", "histories_complete": completed,
                "histories_total": total, "cohort": cohort, "seed": seed,
                "elapsed_seconds": round(time.time() - started, 1)}, separators=(",", ":")), flush=True)
    for seed in bridge_seeds:
        require(initial_hashes[("balanced", seed)] == initial_hashes[("high_to_low_bridge", seed)],
            f"paired balanced/bridge initialization differs for seed {seed}")
    receipts_path = ARTIFACTS / "history-training-receipts.jsonl"
    with receipts_path.open("xb") as stream:
        for receipt in all_receipts:
            stream.write((json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    entries = [{"path": path.relative_to(ARTIFACTS).as_posix(), "bytes": path.stat().st_size,
        "sha256": sha_file(path)} for path in sorted(ARTIFACTS.rglob("*")) if path.is_file()]
    total_telemetry = sum(1 for row in entries if row["path"].endswith("training-telemetry.jsonl"))
    require(len(all_receipts) == 216 and len(entries) >= 216 * 5 and total_telemetry == 648,
        "R3 training artifact cardinality mismatch")
    tree_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    manifest = {"status": "R3_V03_ALL_TRAINING_TRAJECTORIES_SEALED_PRE_EVALUATION",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03-TRAINING", "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "panel_seal_sha256": sha_file(PANEL / "seals/r3-panel-seal-v01.json"),
        "feature_cache_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "pretraining_seal_sha256": sha_file(PREFLIGHT / "pretraining-seal-v01.json"),
        "balanced_histories": 192, "bridge_histories": 24, "paired_initializations_verified": 24,
        "step80_forks": 216, "branch_continuations": 432,
        "saved_checkpoint_steps": [80, 100, 120], "evaluation_checkpoint_cells": 1080,
        "telemetry_files": total_telemetry, "telemetry_steps": 216 * 80 + 432 * 40,
        "head_initialized": True, "training_complete": True, "panel_behavior_opened": False,
        "predictions_created": False, "metrics_computed": False, "entries": entries,
        "entries_root_sha256": sha_bytes(tree_body.encode()), "elapsed_seconds": round(time.time() - started, 3)}
    write_json(ARTIFACTS / "training-manifest.json", manifest)
    seal = {"schema": "jev-r3-training-seal-v01", "status": manifest["status"],
        "entries_root_sha256": manifest["entries_root_sha256"], "entries": entries,
        "manifest_sha256": sha_file(ARTIFACTS / "training-manifest.json"),
        "panel_behavior_opened": False, "predictions_created": False, "metrics_computed": False}
    write_json(ARTIFACTS / "training-seal-v01.json", seal)
    print(json.dumps({"status": manifest["status"], "training_root_sha256": seal["entries_root_sha256"],
        "histories": 216, "telemetry_steps": manifest["telemetry_steps"],
        "evaluation_cells": 1080, "panel_behavior_opened": False,
        "elapsed_seconds": manifest["elapsed_seconds"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
