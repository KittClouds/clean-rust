"""Run only R3 balanced common histories through the pre-treatment step-80 fork."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
INPUT = RUN / "calibration-inputs-v03"
PANEL = RUN / "calibration-panel-v02"
FEATURES = RUN / "calibration-features-v01"
PREFLIGHT = RUN / "calibration-preflight-v03"
TRAINING = RUN / "calibration-training-v02"
PHASE_Q = ROOT / "experiments/jev-information-density-v08q"
BASE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
FEATURE_CACHE = BASE / "shared-feature-cache"
CANDIDATE_CACHE = BASE / "phase-b-run-v01/feature-cache"
PROBE_PATH = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
BATCHER_PATH = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
OBJECTIVE_PATH = PHASE_Q / "source/q_weighted_objective_v02.py"
SEED_LABEL = "jev-information-density-v08q-r3-selectivity-v01/calibration-seed/{index}"
PANEL_SEED_LABEL = "jev-information-density-v08q-r3-selectivity-v01/calibration-panel-seed"
FEATURE_KEY = "mean_full@16"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
PROFILE = "name_definition"
SEED_COUNT = 48
HASHES = {
    "run_contract": "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6",
    "analysis_contract": "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64",
    "panel_contract": "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153",
    "primary_source": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "sham_source": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "scope_source": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "batcher": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "objective": "fc412072592857be36b02312d852d08ce3df2bf6fa7b28f8c1d59575c28e1ea4",
    "feature_extractor": "f728ab9677a32ac391d1bfb224251f8cb6bc65a40c4e0246f58cac88c93c2bb2",
    "balanced_primary": "8c75354d6225762e275552fcf279d65fb4870f382405bdbbccc36576a950a859",
    "balanced_sham": "98ec35a78fbf2a65d050b1086bbf6337acaaae743cd4208af89107d235247617",
    "reverse_sham_texts": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "calibration_panel": "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef",
    "calibration_candidates": "cc45c81e2b6d70d222170872e9ddd96e1b48dfe90d26e588d319a34a7f101b33",
    "calibration_panel_receipt": "3a39f9d682096528e534ab4ddefd8516ce9de15abd5c1fbe8d4ff10947c28b64",
    "calibration_admissions": "4fa7d9c7b4ea5049ae39478240b93bf8932368fe04ad781b6ed0b11b079ccf0f",
    "rendered_denylist": "e78c28d14d745c32be65937442682f14fa798aaf4c9b5c6a5bacd94a9619bb86",
}


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def state_sha(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode() + b"\0" + str(tensor.dtype).encode() + b"\0")
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode() + b"\0")
        digest.update(memoryview(tensor.numpy()).cast("B"))
    return digest.hexdigest()


def tree_sha(value: Any) -> str:
    digest = hashlib.sha256()

    def visit(item: Any) -> None:
        if isinstance(item, torch.Tensor):
            tensor = item.detach().cpu().contiguous()
            digest.update(b"tensor\0" + str(tensor.dtype).encode() + b"\0")
            digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode() + b"\0")
            digest.update(memoryview(tensor.numpy()).cast("B"))
        elif isinstance(item, dict):
            digest.update(b"dict\0")
            for key in sorted(item, key=lambda value: (type(value).__name__, repr(value))):
                visit(key)
                visit(item[key])
            digest.update(b"end-dict\0")
        elif isinstance(item, (tuple, list)):
            digest.update(b"tuple\0" if isinstance(item, tuple) else b"list\0")
            for child in item:
                visit(child)
            digest.update(b"end-sequence\0")
        elif item is None or isinstance(item, (bool, int, float, str)):
            digest.update(type(item).__name__.encode() + b"\0")
            digest.update(json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\0")
        else:
            raise TypeError(f"unsupported stable-hash value: {type(item).__name__}")

    visit(value)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temporary.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def seed_value(index: int) -> int:
    return int.from_bytes(hashlib.sha256(SEED_LABEL.format(index=index).encode()).digest()[:4], "little")


def seed_list() -> list[int]:
    values = [seed_value(index) for index in range(SEED_COUNT)]
    require(len(set(values)) == SEED_COUNT, "calibration seed derivation collision")
    return values


def canonical_jsonl(row: Any) -> bytes:
    return (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_index = {str(row["group_id"]): index for index, row in enumerate(primary)}
    require(len(group_index) == 10_000, "calibration primary group identities are not unique")
    ordered = sorted(group_index)
    rows: list[dict[str, Any]] = []
    for epoch in (1, 2):
        shuffled = list(ordered)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for step in range(40):
            groups = shuffled[step * 256 : (step + 1) * 256]
            indices = [group_index[group] for group in groups]
            aux_slots = [int(primary[index]["occurrence_index"]) // 2
                         for index in indices if primary[index]["role"] == "anchor"]
            rows.append({
                "seed": seed, "epoch": epoch, "step": step + 1,
                "global_step": (epoch - 1) * 40 + step + 1,
                "primary_occurrence_indices": indices,
                "primary_group_ids": groups,
                "auxiliary_anchor_batch_slots": aux_slots,
            })
    return rows


def stable_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("xb") as stream:
        for row in rows:
            stream.write(canonical_jsonl(row))
        stream.flush()
        os.fsync(stream.fileno())


def verify_authorities() -> dict[str, Any]:
    contract_paths = {
        "run_contract": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-run-contract-v01.json",
        "analysis_contract": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-analysis-contract-v01.json",
        "panel_contract": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-panel-contract-v01.json",
    }
    for key, path in contract_paths.items():
        require(sha_file(path) == HASHES[key], f"bound Q {key} changed")
    source_paths = {
        "primary_source": BASE / "phase-b-v03-inputs/common-primary-occurrence-manifest.jsonl",
        "sham_source": BASE / "phase-b-v03-inputs/head-input-manifest-B-SHAM.jsonl",
        "scope_source": FEATURE_CACHE / "training-only-feature-scope.jsonl",
        "training_features": FEATURE_CACHE / "shared-training-features.pt",
        "candidate_features": CANDIDATE_CACHE / "candidate-features.pt",
        "candidate_catalog": BASE / "phase-b-v03-inputs/candidate-catalog.json",
        "probe": PROBE_PATH, "batcher": BATCHER_PATH, "objective": OBJECTIVE_PATH,
        "feature_extractor": ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/extract_r3_calibration_features_v01.py",
        "balanced_primary": INPUT / "balanced-primary-occurrences.jsonl",
        "balanced_sham": INPUT / "balanced-sham-events.jsonl",
        "reverse_sham_texts": INPUT / "reverse-sham-texts.jsonl",
        "calibration_panel": PANEL / "calibration-panel-views.jsonl",
        "calibration_candidates": PANEL / "candidate-texts.jsonl",
        "calibration_panel_receipt": PANEL / "panel-generation-receipt.json",
        "calibration_admissions": PANEL / "candidate-admission-receipts.jsonl",
        "rendered_denylist": Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v01\calibration-exclusions-v01\full-rendered-input-hash-denylist.json"),
    }
    observed = {key: sha_file(path) for key, path in source_paths.items()}
    require(observed == {key: HASHES[key] for key in observed}, "bound training/code source changed")
    feature_receipt_path = FEATURES / "feature-extraction-receipt.json"
    feature_receipt = read_json(feature_receipt_path)
    require(feature_receipt.get("status") == "R3_PRETREATMENT_FEATURE_EXTRACTION_PASS", "calibration feature extraction receipt not PASS")
    require(feature_receipt.get("head_loaded") is False and feature_receipt.get("training") is False
            and feature_receipt.get("inference") is False and feature_receipt.get("confirmatory_panel") is False,
            "feature receipt crosses forbidden model boundary")
    return {"contracts": {key: sha_file(path) for key, path in contract_paths.items()},
            "sources": observed, "feature_receipt_sha256": sha_file(feature_receipt_path)}


def verify_feature_cache_and_seal() -> dict[str, Any]:
    receipt_path = FEATURES / "feature-extraction-receipt.json"
    receipt = read_json(receipt_path)
    files = [
        "calibration-panel-state-features.pt", "calibration-candidate-features.pt", "reverse-sham-state-features.pt",
        "calibration-panel-feature-manifest.jsonl", "candidate-feature-manifest.jsonl", "reverse-sham-feature-manifest.jsonl",
        "feature-extraction-receipt.json",
    ]
    entries = []
    for name in files:
        path = FEATURES / name
        require(path.is_file(), f"calibration feature artifact missing: {name}")
        entries.append({"path": name, "bytes": path.stat().st_size, "sha256": sha_file(path)})
    seal_path = FEATURES / "feature-cache-seal-v01.json"
    actual = {path.name for path in FEATURES.iterdir() if path.is_file()}
    allowed = set(files) | ({seal_path.name} if seal_path.exists() else set())
    require(actual == allowed, "unexpected calibration feature artifact in cache")
    panel = torch.load(FEATURES / files[0], map_location="cpu", weights_only=True)["features"]
    candidates = torch.load(FEATURES / files[1], map_location="cpu", weights_only=True)["features"]
    reverse = torch.load(FEATURES / files[2], map_location="cpu", weights_only=True)["features"]
    require(tuple(panel.shape) == (4_000, 2048) and panel.dtype == torch.float32 and panel.is_contiguous() and torch.isfinite(panel).all(), "panel feature tensor invalid")
    require(tuple(candidates.shape) == (16, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous() and torch.isfinite(candidates).all(), "candidate feature tensor invalid")
    require(tuple(reverse.shape) == (2_500, 2048) and reverse.dtype == torch.float32 and reverse.is_contiguous() and torch.isfinite(reverse).all(), "reverse SHAM feature tensor invalid")
    for key, tensor in (("panel", panel), ("candidates", candidates), ("reverse_sham", reverse)):
        expected = receipt["feature_tensors"][key]
        require(tensor_sha(tensor) == expected["tensor_sha256"] and list(tensor.shape) == expected["shape"], f"feature tensor receipt mismatch: {key}")
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda item: item["path"]))
    root = hashlib.sha256(body.encode()).hexdigest()
    seal = {"status": "R3_CALIBRATION_FEATURE_CACHE_SEALED_PRE_HEAD_INITIALIZATION",
            "entries": entries, "entry_count": len(entries), "entries_root_sha256": root,
            "feature_receipt_sha256": sha_file(receipt_path), "panel_shape": list(panel.shape),
            "candidate_shape": list(candidates.shape), "reverse_sham_shape": list(reverse.shape),
            "repeat_max_abs_error": receipt["repeat_smoke"]["max_abs_error"],
            "head_initialized": False, "training": False, "confirmatory_panel": False}
    seal_path = FEATURES / "feature-cache-seal-v01.json"
    if not seal_path.exists():
        write_json(seal_path, seal)
    else:
        existing = read_json(seal_path)
        require(existing == seal, "existing calibration feature seal does not reproduce")
    return {"seal_sha256": sha_file(seal_path), "entries_root_sha256": root,
            "panel_shape": list(panel.shape), "candidate_shape": list(candidates.shape),
            "reverse_sham_shape": list(reverse.shape)}


def load_calibration_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], torch.Tensor, torch.Tensor, torch.Tensor]:
    primary = read_jsonl(INPUT / "balanced-primary-occurrences.jsonl")
    auxiliary = read_jsonl(INPUT / "balanced-sham-events.jsonl")
    reverse_rows = read_jsonl(INPUT / "reverse-sham-texts.jsonl")
    require(len(primary) == 10_000 and len(auxiliary) == 5_000 and len(reverse_rows) == 2_500, "calibration training input counts mismatch")
    require(all(row["occurrence_index"] == index for index, row in enumerate(primary)), "primary occurrence index is not dense")
    require(all(row["event_index"] == index for index, row in enumerate(auxiliary)), "auxiliary event index is not dense")
    require(all(row["feature_scope_index"] == 55_000 + index for index, row in enumerate(reverse_rows)), "reverse SHAM feature indices are not append-only")
    states_pack = torch.load(FEATURE_CACHE / "shared-training-features.pt", map_location="cpu", weights_only=True)
    states = states_pack["features"]
    candidates = torch.load(CANDIDATE_CACHE / "candidate-features.pt", map_location="cpu", weights_only=True)
    reverse = torch.load(FEATURES / "reverse-sham-state-features.pt", map_location="cpu", weights_only=True)["features"]
    require(tuple(states.shape) == (55_000, 2048) and states.dtype == torch.float32 and states.is_contiguous(), "sealed training state tensor invalid")
    require(tuple(candidates.shape) == (48, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous(), "sealed candidate tensor invalid")
    states = torch.cat((states, reverse), dim=0).contiguous()
    require(tuple(states.shape) == (57_500, 2048) and torch.isfinite(states).all(), "augmented calibration state tensor invalid")
    require(torch.isfinite(candidates).all(), "training candidate tensor contains nonfinite values")
    return primary, auxiliary, reverse_rows, states, candidates, reverse


def verify_schedule(primary: list[dict[str, Any]], schedule: list[dict[str, Any]], seeds: list[int]) -> None:
    require(len(schedule) == 48 * 80, "calibration schedule total row count mismatch")
    for seed in seeds:
        rows = [row for row in schedule if row["seed"] == seed]
        require(len(rows) == 80 and [row["global_step"] for row in rows] == list(range(1, 81)), f"schedule step identity mismatch: {seed}")
        for epoch in (1, 2):
            block = [row for row in rows if row["epoch"] == epoch]
            require(len(block) == 40 and [row["step"] for row in block] == list(range(1, 41)), "calibration epoch schedule shape mismatch")
            require(sorted(index for row in block for index in row["primary_occurrence_indices"]) == list(range(10_000)), "primary coverage mismatch")
            require(sorted(index for row in block for index in row["auxiliary_anchor_batch_slots"]) == list(range(5_000)), "auxiliary coverage mismatch")
            for row in block:
                expected_slots = [primary[index]["occurrence_index"] // 2
                                  for index in row["primary_occurrence_indices"] if primary[index]["role"] == "anchor"]
                require(row["auxiliary_anchor_batch_slots"] == expected_slots, "auxiliary-to-anchor slot mismatch")
                expected_count = 16 if row["step"] == 40 else 256
                require(len(row["primary_occurrence_indices"]) == expected_count, "primary batch size mismatch")


def preflight() -> dict[str, Any]:
    require(not PREFLIGHT.exists(), f"refusing existing calibration preflight namespace: {PREFLIGHT}")
    bindings = verify_authorities()
    feature_seal = verify_feature_cache_and_seal()
    primary, auxiliary, reverse_rows, states, candidates, reverse = load_calibration_inputs()
    del reverse_rows, states, candidates, reverse
    seeds = seed_list()
    schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    verify_schedule(primary, schedule, seeds)
    replay_schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    encoded = b"".join(canonical_jsonl(row) for row in schedule)
    require(encoded == b"".join(canonical_jsonl(row) for row in replay_schedule), "schedule independent reconstruction differs")
    PREFLIGHT.mkdir(parents=True, exist_ok=False)
    schedule_path = PREFLIGHT / "step80-schedule.jsonl"
    with schedule_path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    manifest = {
        "status": "R3_PRETREATMENT_CALIBRATION_SCHEDULE_SEALED_PRE_HEAD_INITIALIZATION",
        "identity": "JEV-V08Q-R3-PRETREATMENT-CALIBRATION-V01",
        "seed_derivation": {"label_template": SEED_LABEL, "sha256_prefix_bytes": 4, "byte_order": "little", "seeds": seeds},
        "panel_seed": {"label": PANEL_SEED_LABEL, "seed": 2130503117},
        "schedule": {"sha256": sha_file(schedule_path), "rows": len(schedule), "steps_per_seed": 80,
                     "epochs": 2, "primary_batch_size": 256, "final_batch_size": 16,
                     "checkpoint_step": 80, "optimizer": "AdamW", "lr": 0.002,
                     "weight_decay": 0.01, "betas": [0.9, 0.999], "epsilon": 1e-8,
                     "brier_weight": 0.25, "auxiliary_multiplier": 1.0, "scheduler": None,
                     "polarity": "balanced high_to_low and low_to_high per family", "panel_feedback": False},
        "observational_scope": {"histories": 48, "purpose": "pre-treatment S80 calibration only",
                                "eligible_for_confirmatory_cohort": False,
                                "eligible_for_confirmatory_panel": False,
                                "HALF_branches": 0, "treatment_metrics": False},
        "bindings": bindings,
        "runner_sha256": sha_file(Path(__file__).resolve()),
        "feature_cache": feature_seal,
        "primary_rows": len(primary), "auxiliary_rows": len(auxiliary),
        "calibration_panel_rows": 4_000,
        "head_initialized": False, "training": False, "panel_opened_for_S80": False,
    }
    write_json(PREFLIGHT / "calibration-schedule-manifest.json", manifest)
    tree_entries = []
    for path in sorted(PREFLIGHT.iterdir()):
        if path.is_file():
            tree_entries.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)})
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in tree_entries)
    seal = {"status": "R3_PRETREATMENT_CALIBRATION_INPUTS_AND_SCHEDULE_SEALED",
            "entries": tree_entries, "entry_count": len(tree_entries),
            "entries_root_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "manifest_sha256": sha_file(PREFLIGHT / "calibration-schedule-manifest.json"),
            "schedule_sha256": sha_file(schedule_path),
            "head_initialized": False, "training": False, "panel_opened_for_S80": False}
    write_json(PREFLIGHT / "pretraining-seal.json", seal)
    return {"status": seal["status"], "seed_count": len(seeds), "schedule_rows": len(schedule),
            "schedule_sha256": seal["schedule_sha256"], "pretraining_root_sha256": seal["entries_root_sha256"],
            "head_initialized": False}


def verify_preflight_seal() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], torch.Tensor, torch.Tensor]:
    seal_path = PREFLIGHT / "pretraining-seal.json"
    seal = read_json(seal_path)
    require(seal.get("status") == "R3_PRETREATMENT_CALIBRATION_INPUTS_AND_SCHEDULE_SEALED", "calibration pretraining seal state mismatch")
    entries = seal["entries"]
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    require(hashlib.sha256(body.encode()).hexdigest() == seal["entries_root_sha256"], "calibration pretraining root mismatch")
    for row in entries:
        path = PREFLIGHT / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha_file(path) == row["sha256"], "calibration pretraining artifact drift")
    manifest = read_json(PREFLIGHT / "calibration-schedule-manifest.json")
    require(manifest.get("runner_sha256") == sha_file(Path(__file__).resolve()), "R3 calibration runner changed after preflight seal")
    feature_seal = verify_feature_cache_and_seal()
    require(feature_seal == manifest.get("feature_cache"), "R3 calibration feature cache seal changed after preflight")
    schedule = read_jsonl(PREFLIGHT / "step80-schedule.jsonl")
    require(len(schedule) == 48 * 80 and sha_file(PREFLIGHT / "step80-schedule.jsonl") == manifest["schedule"]["sha256"], "calibration schedule binding mismatch")
    seeds = manifest["seed_derivation"]["seeds"]
    require(seeds == seed_list() and len(set(seeds)) == 48, "calibration seed manifest mismatch")
    primary, auxiliary, reverse_rows, states, candidates, reverse = load_calibration_inputs()
    verify_schedule(primary, schedule, seeds)
    return manifest, primary, auxiliary, schedule, states, candidates


def seed_all(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


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


def capture_rng() -> dict[str, Any]:
    return {"python": random.getstate(), "torch_cpu": torch.get_rng_state().clone(),
            "torch_cuda": [item.cpu().clone() for item in torch.cuda.get_rng_state_all()]}


def save_payload(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as stream:
        torch.save(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return sha_file(path)


def prepare(row: dict[str, Any]) -> dict[str, Any]:
    return {"group_id": row["group_id"], "state_idx": int(row["feature_scope_index"]),
            "candidate_indices": {PROFILE: row["candidate_indices"]}, "gold": row["target"],
            "kind": "choice", "probability_source": "exact_generative_posterior"}


def run_history(seed: int, schedule: list[dict[str, Any]], primary: list[dict[str, Any]],
                auxiliary: list[dict[str, Any]], states: torch.Tensor, candidates: torch.Tensor,
                probe: Any, batcher: Any, objective: Any, out_dir: Path,
                preflight_seal_sha: str) -> dict[str, Any]:
    seed_all(seed)
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.train()
    init_state = clone_cpu(head.state_dict())
    init_sha = state_sha(init_state)
    require(sum(value.numel() for value in init_state.values()) == 590_081, "R3 head parameter count mismatch")
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
                                 betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    seed_rows = [row for row in schedule if int(row["seed"]) == seed]
    require(len(seed_rows) == 80, "R3 per-seed schedule incomplete")
    telemetry_path = out_dir / f"seed-{seed}" / "training-telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True, exist_ok=False)
    with telemetry_path.open("x", encoding="utf-8", newline="\n") as telemetry:
        for item in seed_rows:
            step = int(item["global_step"])
            base_rows = [primary[index] for index in item["primary_occurrence_indices"]]
            aux_rows = [auxiliary[index] for index in item["auxiliary_anchor_batch_slots"]]
            batch = [prepare(row) for row in base_rows] + [prepare(row) for row in aux_rows]
            state, candidate, gold, mask, kinds, sources = batcher.fast_tensor_batch(
                batch, states, candidates, PROFILE, "cuda", reorder=True)
            weights = torch.cat((torch.ones(len(base_rows), device="cuda"), torch.ones(len(aux_rows), device="cuda")))
            optimizer.zero_grad(set_to_none=True)
            logits = head(state, candidate)
            loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
            require(bool(torch.isfinite(loss).item()) and bool(torch.isfinite(brier).item()), f"nonfinite R3 calibration loss {seed}/{step}")
            loss.backward()
            grad_sq = torch.zeros((), device="cuda")
            for parameter in head.parameters():
                if parameter.grad is not None:
                    require(bool(torch.isfinite(parameter.grad).all().item()), f"nonfinite gradient {seed}/{step}")
                    grad_sq += parameter.grad.detach().float().square().sum()
            optimizer.step()
            event = {"seed": seed, "global_step": step, "epoch": item["epoch"], "step_in_epoch": item["step"],
                     "primary_indices": item["primary_occurrence_indices"],
                     "auxiliary_anchor_batch_slots": item["auxiliary_anchor_batch_slots"],
                     "auxiliary_multiplier": 1.0, "loss": float(loss.detach()), "brier": float(brier.detach()),
                     "gradient_norm": float(grad_sq.sqrt()), "panel_opened": False}
            telemetry.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            telemetry.flush()
            os.fsync(telemetry.fileno())
    require(len(telemetry_path.read_text(encoding="utf-8").splitlines()) == 80, "R3 telemetry step count mismatch")
    payload = {
        "status": "R3_COMMON_SHAM_1X_STEP80_CALIBRATION_CHECKPOINT_UNEVALUATED",
        "seed": seed, "global_step": 80, "head_state": clone_cpu(head.state_dict()),
        "optimizer_state": clone_cpu(optimizer.state_dict()),
        "head_sha256": state_sha(head.state_dict()), "initial_head_sha256": init_sha,
        "optimizer_sha256": tree_sha(optimizer.state_dict()), "rng_state": capture_rng(),
        "event_cursor": 80, "auxiliary_multiplier": 1.0,
        "preflight_seal_sha256": preflight_seal_sha,
        "schedule_sha256": sha_file(PREFLIGHT / "step80-schedule.jsonl"),
        "evaluation_panel_opened": False,
    }
    checkpoint_path = telemetry_path.parent / "step-080.pt"
    checkpoint_sha = save_payload(checkpoint_path, payload)
    receipt = {"status": payload["status"], "seed": seed, "checkpoint_path": str(checkpoint_path),
               "checkpoint_sha256": checkpoint_sha, "head_sha256": payload["head_sha256"],
               "optimizer_sha256": payload["optimizer_sha256"], "telemetry_sha256": sha_file(telemetry_path),
               "initial_head_sha256": init_sha, "steps": 80, "auxiliary_multiplier": 1.0,
               "panel_opened": False, "HALF_branch": False}
    write_json(telemetry_path.parent / "checkpoint-receipt.json", receipt)
    del state, candidate, gold, mask, logits, loss, brier, optimizer, head
    torch.cuda.empty_cache()
    return receipt


def eval_s80(checkpoint_path: Path, panel_rows: list[dict[str, Any]], panel_features: torch.Tensor,
             eval_candidates: torch.Tensor, probe: Any) -> dict[str, Any]:
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    require(payload["global_step"] == 80 and payload["status"] == "R3_COMMON_SHAM_1X_STEP80_CALIBRATION_CHECKPOINT_UNEVALUATED", "not a step-80 common-history checkpoint")
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.load_state_dict(payload["head_state"], strict=True)
    head.eval()
    index = {str(row["candidate_semantic_id"]): i for i, row in enumerate(read_jsonl(PANEL / "candidate-texts.jsonl"))}
    by_neighborhood: dict[str, dict[str, Any]] = {}
    with torch.inference_mode():
        for row_index, row in enumerate(panel_rows):
            identity = row["neighborhood_id"]
            item = by_neighborhood.setdefault(identity, {"family": row["family_slug"], "direction": row["direction"], "views": {}})
            item["views"][row["view"]] = (row_index, row)
        cell_values: dict[tuple[str, str], list[float]] = {(family, direction): [] for family in FAMILIES for direction in ("high_to_low", "low_to_high")}
        batch_size = 128
        groups = list(by_neighborhood.items())
        for start in range(0, len(groups), batch_size):
            chunk = groups[start : start + batch_size]
            state_indices: list[int] = []
            candidate_rows: list[list[int]] = []
            for _identity, item in chunk:
                anchor_index, anchor = item["views"]["anchor"]
                fact_index, fact = item["views"]["fact_flip"]
                ids = anchor["candidate_semantic_ids"]
                require(ids == fact["candidate_semantic_ids"], "calibration candidate order changed across paired views")
                old_id, new_id = anchor["old_semantic_id"], anchor["new_semantic_id"]
                require(old_id in index and new_id in index, "calibration role identity missing from candidate feature basis")
                old_slot, new_slot = ids.index(old_id), ids.index(new_id)
                state_indices.extend((anchor_index, fact_index))
                candidate_rows.extend(([index[candidate_id] for candidate_id in ids], [index[candidate_id] for candidate_id in ids]))
            state_tensor = panel_features[torch.tensor(state_indices, dtype=torch.long)].to("cuda")
            candidate_tensor = eval_candidates[torch.tensor(candidate_rows, dtype=torch.long)].to("cuda")
            logits = head(state_tensor, candidate_tensor)
            for local_index, (_identity, item) in enumerate(chunk):
                anchor_logits = logits[2 * local_index]
                fact_logits = logits[2 * local_index + 1]
                anchor_row = item["views"]["anchor"][1]
                old_slot, new_slot = anchor_row["candidate_semantic_ids"].index(anchor_row["old_semantic_id"]), anchor_row["candidate_semantic_ids"].index(anchor_row["new_semantic_id"])
                pair_anchor = float(anchor_logits[new_slot] - anchor_logits[old_slot])
                pair_fact = float(fact_logits[new_slot] - fact_logits[old_slot])
                cell_values[(item["family"], item["direction"])].append(pair_fact - pair_anchor)
    cells = {}
    for key, values in cell_values.items():
        require(len(values) == 250, f"S80 cell support mismatch: {key} {len(values)}")
        cells[f"{key[0]}/{key[1]}"] = {"count": len(values), "mean_S80": sum(values) / len(values)}
    equal_cell_mean = sum(item["mean_S80"] for item in cells.values()) / len(cells)
    result = {"seed": payload["seed"], "step": 80, "S80_role_oriented_equal_cell_mean": equal_cell_mean,
              "family_direction_cells": cells, "panel_neighborhood_count": len(by_neighborhood),
              "target_accuracy_computed": False, "MAP_metrics_computed": False,
              "half_branch": False, "confirmatory": False}
    del head, state_tensor, candidate_tensor, logits
    torch.cuda.empty_cache()
    return result


def execute() -> dict[str, Any]:
    require(not TRAINING.exists(), f"refusing existing calibration training namespace: {TRAINING}")
    manifest, primary, auxiliary, schedule, states, candidates = verify_preflight_seal()
    require(torch.__version__ == "2.11.0+cu128" and torch.cuda.is_available()
            and torch.version.cuda == "12.8" and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080",
            "R3 calibration training runtime mismatch")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False
    require(not torch.are_deterministic_algorithms_enabled(), "R3 inherits non-deterministic algorithm mode")
    states = states.to("cuda")
    candidates = candidates.to("cuda")
    probe = load_module(PROBE_PATH, "r3_calibration_probe")
    batcher = load_module(BATCHER_PATH, "r3_calibration_batcher")
    objective = load_module(OBJECTIVE_PATH, "r3_calibration_objective")
    TRAINING.mkdir(parents=True, exist_ok=False)
    preflight_seal_sha = sha_file(PREFLIGHT / "pretraining-seal.json")
    receipts: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, seed in enumerate(manifest["seed_derivation"]["seeds"], start=1):
        receipt = run_history(seed, schedule, primary, auxiliary, states, candidates,
                              probe, batcher, objective, TRAINING, preflight_seal_sha)
        receipts.append(receipt)
        print(json.dumps({"event": "r3_calibration_common_history_complete", "index": index,
                          "seed": seed, "step80_checkpoint_sha256": receipt["checkpoint_sha256"]}), flush=True)
    require(len(receipts) == SEED_COUNT, "R3 calibration history count mismatch")
    # Seal all training artifacts before any calibration-panel read.
    training_files = []
    for path in sorted(TRAINING.rglob("*")):
        if path.is_file():
            training_files.append({"path": path.relative_to(TRAINING).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    training_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in training_files)
    training_tree_root = hashlib.sha256(training_body.encode()).hexdigest()
    training_seal = {"status": "R3_ALL_48_STEP80_COMMON_HISTORIES_SEALED_BEFORE_CALIBRATION_PANEL_READ",
                     "checkpoint_count": len(receipts), "steps_per_history": 80,
                     "entries": training_files, "entry_count": len(training_files),
                     "entries_root_sha256": training_tree_root,
                     "pretraining_seal_sha256": preflight_seal_sha,
                     "panel_opened_for_S80": False, "training_panel_feedback": False,
                     "HALF_branch": False, "treatment_metrics": False}
    write_json(TRAINING / "step80-training-seal.json", training_seal)

    # S80 is the only permitted calibration-panel read: role-oriented pre-treatment moderator.
    panel_rows = read_jsonl(PANEL / "calibration-panel-views.jsonl")
    panel_features = torch.load(FEATURES / "calibration-panel-state-features.pt", map_location="cpu", weights_only=True)["features"]
    eval_candidates = torch.load(FEATURES / "calibration-candidate-features.pt", map_location="cpu", weights_only=True)["features"]
    s80_rows = [eval_s80(Path(receipt["checkpoint_path"]), panel_rows, panel_features,
                         eval_candidates, probe) for receipt in receipts]
    require([row["seed"] for row in s80_rows] == manifest["seed_derivation"]["seeds"], "S80 output seed order mismatch")
    s80_path = TRAINING / "pretreatment-s80-calibration.jsonl"
    stable_write_jsonl(s80_path, s80_rows)
    values = sorted(float(row["S80_role_oriented_equal_cell_mean"]) for row in s80_rows)
    quantiles = {str(q): float(torch.quantile(torch.tensor(values), q, interpolation="linear")) for q in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)}
    s80_summary = {"status": "R3_PRETREATMENT_S80_CALIBRATION_COMPLETE",
                   "histories": len(values), "role_oriented_definition": "(logit_new-logit_old)_fact - (logit_new-logit_old)_anchor",
                   "aggregation": "equal mean across four fixed families and two polarity directions; 250 neighborhoods per cell",
                   "quantiles_linear": quantiles,
                   "fraction_abs_below_0_01": sum(abs(value) < 0.01 for value in values) / len(values),
                   "fraction_abs_below_0_05": sum(abs(value) < 0.05 for value in values) / len(values),
                   "step80_is_pre_late_treatment": True,
                   "calibration_histories_join_confirmatory_cohort": False,
                   "threshold_or_stratum_selected": False,
                   "HALF_branch": False, "treatment_metrics": False}
    write_json(TRAINING / "pretreatment-s80-calibration-summary.json", s80_summary)
    result_tree = []
    for path in sorted(TRAINING.rglob("*")):
        if path.is_file() and path.name != "calibration-completion-seal.json":
            result_tree.append({"path": path.relative_to(TRAINING).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    final_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in result_tree)
    completion = {"status": "R3_PRETREATMENT_CALIBRATION_COMPLETE_STEP80_ONLY",
                  "entries": result_tree, "entry_count": len(result_tree),
                  "entries_root_sha256": hashlib.sha256(final_body.encode()).hexdigest(),
                  "training_seal_sha256": sha_file(TRAINING / "step80-training-seal.json"),
                  "s80_summary_sha256": sha_file(TRAINING / "pretreatment-s80-calibration-summary.json"),
                  "runtime": {"torch": torch.__version__, "cuda": torch.version.cuda,
                              "device": torch.cuda.get_device_name(0)},
                  "training_wall_seconds": time.perf_counter() - started,
                  "confirmatory_panel_opened": False, "confirmatory_histories": False,
                  "HALF_branch": False, "treatment_metrics": False}
    write_json(TRAINING / "calibration-completion-seal.json", completion)
    return {"status": completion["status"], "history_count": len(receipts),
            "training_tree_root_sha256": training_tree_root,
            "s80_summary": s80_summary,
            "completion_root_sha256": completion["entries_root_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = preflight() if args.preflight else execute()
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
