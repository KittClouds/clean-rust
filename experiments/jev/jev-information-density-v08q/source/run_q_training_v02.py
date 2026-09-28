"""Frozen Q four-arm training execution; panel labels/features are hash-checked only here."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
INPUT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
STATE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache")
CANDIDATE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\feature-cache")
TRAIN = RUN / "training"
SCHEDULE = RUN / "schedule"
INSTRUMENT = RUN / "instrument/q-execution-instrument-seal-v02.json"
PACKET = RUN / "q-full-execution-packet-v02.json"
SEEDS = (2540205348, 2603246505, 3565067208)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
ORDER = {
    2540205348: ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW"),
    2603246505: ("B-MATCHED", "B-SHAM", "B-SHAM-LOW", "B-DUP"),
    3565067208: ("B-SHAM", "B-SHAM-LOW", "B-DUP", "B-MATCHED"),
}
CHECKPOINTS = (40, 80, 100, 120)
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
HASHES = {
    "run": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "source_root": "5e973916fb62747cde2de51f7deb2e29616ea1ead13ce384dcdb254901d936d3",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
    "panel_root": "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6",
    "panel_seal": "161511e6617ee012b3051590b4a9ce747f79a85228c02649e61ca8a10d080ad6",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "dup": "f6f4ec519a04efeac02962c68c2d2d8ec92cf43d25bb9fd974f168e67c4d3b2b",
    "matched": "bd38446c0328f8092dc3293090fd3041d7be5d53945df6f80fb3770244d87b0d",
    "sham": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "state_scope": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "state_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "loss": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "q_loss": "fc412072592857be36b02312d852d08ce3df2bf6fa7b28f8c1d59575c28e1ea4",
    "schedule": "af6688bd983cb01d113a4122938d71ab217143b7d17a43c25f376e04cf573662",
    "schedule_materializer": "eaa3606972822c7cf21992f8746dc657e0b92658326d76007d39a731c0894721",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def digest_entries(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, value: Any, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with tmp.open("r+b") as f:
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tensor_hash(x: torch.Tensor) -> str:
    a = x.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(a).cast("B")).hexdigest()


def state_hash(state: dict[str, torch.Tensor]) -> str:
    h = hashlib.sha256()
    for name, value in sorted(state.items()):
        a = value.detach().cpu().contiguous()
        h.update(name.encode()); h.update(str(a.dtype).encode()); h.update(json.dumps(list(a.shape)).encode())
        h.update(memoryview(a.numpy()).cast("B"))
    return h.hexdigest()


def clone_cpu(value: Any) -> Any:
    if isinstance(value, torch.Tensor): return value.detach().cpu().clone()
    if isinstance(value, dict): return {k: clone_cpu(v) for k, v in value.items()}
    if isinstance(value, list): return [clone_cpu(v) for v in value]
    if isinstance(value, tuple): return tuple(clone_cpu(v) for v in value)
    return value


def source_paths() -> dict[str, Path]:
    return {
        "primary": INPUT / "common-primary-occurrence-manifest.jsonl",
        "dup": INPUT / "head-input-manifest-B-DUP.jsonl",
        "matched": INPUT / "head-input-manifest-B-MATCHED.jsonl",
        "sham": INPUT / "head-input-manifest-B-SHAM.jsonl",
        "state_scope": STATE / "training-only-feature-scope.jsonl",
        "state_features": STATE / "shared-training-features.pt",
        "candidate_features": CANDIDATE / "candidate-features.pt",
        "candidate_receipt": CANDIDATE / "candidate-feature-receipt.json",
        "candidate_catalog": INPUT / "candidate-catalog.json",
        "state_receipt": STATE / "shared-feature-cache-receipt.json",
    }


def verify_contract_panel_and_sources() -> dict[str, Any]:
    checks = {
        "run": Q / "contracts/q-run-contract-v02.json",
        "analysis": Q / "contracts/q-analysis-contract-v02.json",
        "source_lock": Q / "contracts/q-source-lock-v02.json",
        "addendum": Q / "contracts/q-execution-addendum-v01.json",
    }
    for key, path in checks.items(): need(sha(path) == HASHES[key], f"Q {key} contract hash mismatch")
    instrument = read_json(INSTRUMENT)
    entries = instrument.get("entries", [])
    require_instrument = instrument.get("status") == "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION"
    need(require_instrument and instrument.get("root_sha256") == digest_entries(entries), "Q execution instrument seal/root invalid")
    for item in entries:
        path = Path(item["path"])
        need(path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], f"Q execution instrument source changed: {path}")
    need(sha(Path(__file__).resolve()) == next((item["sha256"] for item in entries if Path(item["path"]).resolve() == Path(__file__).resolve()), None), "Q trainer is not bound by execution instrument seal")
    lock = read_json(checks["source_lock"])
    need(lock["root_sha256"] == HASHES["source_root"] and digest_entries(lock["entries"]) == HASHES["source_root"], "Q source-lock root mismatch")
    for row in lock["entries"]:
        path = Path(row["path"])
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"source-lock entry mismatch: {path}")
    seal_path = PANEL / "seals/q-panel-phase-terminal-seal-v01.json"
    seal = read_json(seal_path)
    need(sha(seal_path) == HASHES["panel_seal"] and seal["root_sha256"] == HASHES["panel_root"], "Q panel root/seal mismatch")
    need(digest_entries(seal["entries"]) == HASHES["panel_root"], "Q panel entry root mismatch")
    for row in seal["entries"]:
        path = PANEL / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"sealed Q panel entry mismatch: {row['path']}")
    for label in ("panel_verification_status", "radius_verification_status"):
        need("PASS" in seal[label], f"Q panel {label} not PASS")
    need(seal["head_initialization"] is False and seal["training"] is False and seal["heldout_inference"] is False, "Q panel seal reports prior training/inference")
    sched_seal = read_json(SCHEDULE / "schedule-seal.json")
    sched_manifest = read_json(SCHEDULE / "fixed-schedule-manifest.json")
    schedule_path = SCHEDULE / "fixed-schedule.jsonl"
    need(sha(schedule_path) == HASHES["schedule"] == sched_seal["schedule_sha256"], "Q schedule mismatch")
    need(sched_manifest["checkpoint_steps"] == list(CHECKPOINTS) and sched_manifest["schedule_rows"] == 360, "Q sparse schedule contract mismatch")
    verify = read_json(SCHEDULE / "independent-verification-v01.json")
    need(verify["status"] == "Q_SPARSE_SCHEDULE_CLEAN_PROCESS_VERIFICATION_PASS" and verify["clean_process_reconstruction"] == "BYTE_IDENTICAL", "Q independent schedule check absent")
    return {"panel_terminal_seal_sha256": sha(seal_path), "panel_root_sha256": seal["root_sha256"], "source_lock_sha256": sha(checks["source_lock"]), "source_lock_entries": len(lock["entries"]), "schedule_sha256": sha(schedule_path), "schedule_rows": 360, "panel_entries_rehashed": len(seal["entries"]), "instrument_seal_sha256": sha(INSTRUMENT), "instrument_root_sha256": instrument["root_sha256"], "evaluation_content_parsed": False}


def verify_execution_packet() -> dict[str, Any]:
    need(PACKET.is_file(), "sealed Q full-execution packet is absent")
    packet = read_json(PACKET)
    need(packet.get("schema") == "jev-v08q-full-execution-packet-v02", "Q execution packet schema mismatch")
    auth = packet.get("authorization", {})
    need(auth.get("phase") == "Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS" and auth.get("explicit_user_authorization") is True, "Q execution packet authorization mismatch")
    need(packet.get("panel_root_sha256") == HASHES["panel_root"] and packet.get("run_contract_sha256") == HASHES["run"] and packet.get("analysis_contract_sha256") == HASHES["analysis"] and packet.get("addendum_sha256") == HASHES["addendum"], "Q execution packet parent mismatch")
    for row in packet.get("implementation_bindings", []):
        path = ROOT / row["path"]
        need(path.is_file() and sha(path) == row["sha256"], f"Q implementation changed after execution packet seal: {row['path']}")
    need(len(packet.get("implementation_bindings", [])) >= 5, "Q execution packet implementation bindings incomplete")
    seal_path = RUN / "q-full-execution-packet-seal-v02.json"
    packet_seal = read_json(seal_path)
    need(packet_seal.get("packet_sha256") == sha(PACKET) and packet_seal.get("packet_root_sha256") == packet.get("packet_root_sha256"), "Q execution packet seal mismatch")
    return {"packet_sha256": sha(PACKET), "packet_seal_sha256": sha(seal_path), "packet_root_sha256": packet.get("packet_root_sha256"), "authorization_phase": auth["phase"], "implementation_binding_count": len(packet["implementation_bindings"])}


def load_training_inputs(probe: Any, trainer: Any) -> tuple[Any, ...]:
    paths = source_paths()
    expected = {"primary": HASHES["primary"], "dup": HASHES["dup"], "matched": HASHES["matched"], "sham": HASHES["sham"], "state_scope": HASHES["state_scope"], "candidate_features": HASHES["candidate_features"], "candidate_catalog": HASHES["candidate_catalog"]}
    for key, value in expected.items(): need(sha(paths[key]) == value, f"Q training source mismatch: {key}")
    source_lock = read_json(Q / "contracts/q-source-lock-v02.json")
    locked_by_hash = {row["sha256"]: row for row in source_lock["entries"]}
    need(paths["state_receipt"].is_file() and paths["candidate_receipt"].is_file(), "Q frozen feature receipts are missing")
    state_receipt_hash = sha(paths["state_receipt"])
    candidate_receipt_hash = sha(paths["candidate_receipt"])
    need(state_receipt_hash in locked_by_hash and candidate_receipt_hash in locked_by_hash, "Q feature receipts are not bound by the sealed source lock")
    state_receipt = read_json(paths["state_receipt"])
    candidate_receipt = read_json(paths["candidate_receipt"])
    primary = read_jsonl(paths["primary"])
    need(len(primary) == 10_000, "Q primary stream row count mismatch")
    arm_rows = {arm: read_jsonl(paths[key]) for arm, key in (("B-DUP", "dup"), ("B-MATCHED", "matched"), ("B-SHAM", "sham"))}
    for arm, rows in arm_rows.items():
        need(len(rows) == 15_000, f"Q manifest length mismatch: {arm}")
        for i, base in enumerate(primary):
            row = rows[i]
            need(row.get("event_kind") == "primary" and row.get("occurrence_index") == i and row.get("group_id") == base["group_id"] and row.get("source_episode_id") == base["episode_id"] and row.get("target_hash") == base["target_hash"] and row.get("candidate_order_hash") == base["candidate_order_hash"] and row.get("candidate_semantic_ids") == base["candidate_semantic_ids"], f"primary identity drift {arm}/{i}")
    for arm, role in (("B-DUP", "anchor_duplicate"), ("B-MATCHED", "matched_neutral"), ("B-SHAM", "certified_sham")):
        for slot, row in enumerate(arm_rows[arm][10_000:]):
            need(row.get("event_kind") == "auxiliary" and row.get("batch_slot") == slot and row.get("auxiliary_source_role") == role and row.get("loss_weight") == 1.0, f"auxiliary binding mismatch {arm}/{slot}")
    fields = ("group_id", "source_episode_id", "target_hash", "candidate_order_hash", "candidate_semantic_ids", "target")
    for other in ("B-MATCHED", "B-SHAM"):
        need(all(arm_rows[other][i].get(k) == arm_rows["B-DUP"][i].get(k) for i in range(10_000) for k in fields), f"primary payload mismatch: {other}")
    aux_identity = [[r["source_episode_id"], r["target_hash"], r["candidate_order_hash"]] for r in arm_rows["B-SHAM"][10_000:]]
    need(aux_identity == [[r["source_episode_id"], r["target_hash"], r["candidate_order_hash"]] for r in arm_rows["B-DUP"][10_000:]] == [[r["source_episode_id"], r["target_hash"], r["candidate_order_hash"]] for r in arm_rows["B-MATCHED"][10_000:]], "auxiliary identities differ across arms")
    scope = read_jsonl(paths["state_scope"])
    need(len(scope) == 55_000 and all(r.get("index") == i for i, r in enumerate(scope)), "Q training scope invalid")
    state_receipt_path = STATE / "shared-feature-cache-receipt.json"
    candidate_receipt_path = CANDIDATE / "candidate-feature-receipt.json"
    need(sha(state_receipt_path) == "d98ae657e28b976f187d4d67e58119ce80496e76c061c90362ac2e50ff7f720e", "state feature receipt hash mismatch")
    need(sha(paths["state_features"]) == "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6", "state feature file hash mismatch")
    state_receipt = read_json(state_receipt_path)
    need(state_receipt["scope"]["content_sha256"] == "40648e3bbf50e25f31e84d7656221171425cb6e71e07d4c07d4dc72650bb228e" and state_receipt["feature_tensor"]["tensor_sha256"] == "d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa", "training cache receipt content binding mismatch")
    need(sha(candidate_receipt_path) == "29f8d67b24fd2a554500e1cfe2e0fe0b4311d32fad7052ad8ffb3464b7835f44", "candidate feature receipt hash mismatch")
    state_pack = torch.load(paths["state_features"], map_location="cpu", weights_only=True)
    states = state_pack["features"]
    need(tuple(states.shape) == (55_000, 2048) and states.dtype == torch.float32 and states.is_contiguous() and tensor_hash(states) == "d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa", "Q state features invalid")
    need(state_pack.get("scope_sha256") == HASHES["state_scope"] and state_pack.get("feature_key") == "mean_full@16", "Q state tensor scope/representation binding mismatch")
    need(state_receipt.get("status") == "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY" and state_receipt.get("scope", {}).get("sha256") == HASHES["state_scope"] and state_receipt.get("feature_tensor", {}).get("sha256") == HASHES["state_features"] and state_receipt.get("feature_tensor", {}).get("tensor_sha256") == "d8f0f12296758f68c55b5e5660572dd48e4e90d1a3a1683844e59765826bafaa" and state_receipt.get("representation", {}).get("feature_key") == "mean_full@16", "Q shared-feature receipt binding mismatch")
    catalog = read_json(paths["candidate_catalog"])
    candidate_ids = [str(r["candidate_semantic_id"]) for r in catalog["rows"]]
    need(len(candidate_ids) == 48 and len(set(candidate_ids)) == 48 and catalog["feature_dimension"] == 2048, "Q candidate catalog invalid")
    need(candidate_receipt.get("status") == "CANDIDATE_FEATURES_VALIDATED" and candidate_receipt.get("feature_file_sha256") == HASHES["candidate_features"] and candidate_receipt.get("tensor_sha256") == "f76e573779152fd3966845a39e29206c333eef388e0511c5f3e07f8f1b46d593" and candidate_receipt.get("shape") == [48, 2048] and candidate_receipt.get("semantic_ids") == candidate_ids, "Q candidate-feature identity/order receipt mismatch")
    need(sha(paths["candidate_features"]) == HASHES["candidate_features"], "candidate feature file hash mismatch")
    candidates = torch.load(paths["candidate_features"], map_location="cpu", weights_only=True)
    need(tuple(candidates.shape) == (48, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous() and tensor_hash(candidates) == "f76e573779152fd3966845a39e29206c333eef388e0511c5f3e07f8f1b46d593", "Q candidate features invalid")
    id_index = {sid: i for i, sid in enumerate(candidate_ids)}
    for arm, rows in arm_rows.items():
        for row in rows:
            need(row["candidate_indices"] == [id_index[x] for x in row["candidate_semantic_ids"]] and row["candidate_mask"] == [True] * 4 and len(row["target"]) == 4, f"candidate join invalid {arm}/{row.get('occurrence_index',row.get('batch_slot'))}")
            need(scope[row["feature_scope_index"]]["episode_id"] == row["source_episode_id"], "feature scope episode mismatch")
    arm_rows["B-SHAM-LOW"] = arm_rows["B-SHAM"]
    schedule = read_jsonl(SCHEDULE / "fixed-schedule.jsonl")
    need(len(schedule) == 360, "Q schedule row count mismatch")
    for seed in SEEDS:
        for epoch in range(1, 4):
            block = sorted((r for r in schedule if r["seed"] == seed and r["epoch"] == epoch), key=lambda x: x["step"])
            need(len(block) == 40 and [r["step"] for r in block] == list(range(1, 41)), f"schedule block mismatch {seed}/{epoch}")
            need(sorted(i for r in block for i in r["primary_occurrence_indices"]) == list(range(10_000)), "Q epoch primary coverage mismatch")
            need(sorted(i for r in block for i in r["auxiliary_anchor_batch_slots"]) == list(range(5_000)), "Q epoch auxiliary coverage mismatch")
            for row in block:
                ids = row["primary_occurrence_indices"]
                need(row["primary_group_ids"] == [primary[i]["group_id"] for i in ids], "Q schedule group ordering mismatch")
                slots = [primary[i]["occurrence_index"] // 2 for i in ids if primary[i]["role"] == "anchor"]
                need(slots == row["auxiliary_anchor_batch_slots"] and len(ids) == (16 if row["step"] == 40 else 256), "Q schedule batch composition mismatch")
                for arm in ARMS:
                    batch_rows = [arm_rows[arm][i] for i in ids] + [arm_rows[arm][10_000 + s] for s in slots]
                    need(len(batch_rows) == len(ids) + len(slots) and all(x["target"] is not None for x in batch_rows), f"Q batch assembly fails {arm}/{seed}/{epoch}/{row['step']}")
    need(torch.cuda.is_available() and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080" and torch.version.cuda == "12.8" and torch.backends.cudnn.version() == 91900 and torch.backends.cuda.matmul.allow_tf32 is False and torch.backends.cudnn.allow_tf32 is True and torch.backends.cudnn.benchmark is False and torch.are_deterministic_algorithms_enabled() is False, "Q frozen FP32 CUDA runtime/device/settings mismatch")
    return states, candidates, primary, schedule, arm_rows, scope, candidate_ids


def prepare(row: dict[str, Any]) -> dict[str, Any]:
    return {"group_id": row["group_id"] if "group_id" in row else row["source_episode_id"], "state_idx": row["feature_scope_index"], "candidate_indices": {"name_definition": row["candidate_indices"]}, "gold": row["target"], "kind": "choice", "probability_source": "exact_generative_posterior"}


def seed_all(seed: int) -> None:
    random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)


def init_templates(probe: Any) -> dict[int, tuple[dict[str, torch.Tensor], str]]:
    root = TRAIN / "initial-templates"
    root.mkdir(parents=True, exist_ok=False)
    result = {}
    for seed in SEEDS:
        seed_all(seed)
        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
        state = clone_cpu(head.state_dict()); digest = state_hash(state)
        need(sum(x.numel() for x in state.values()) == 590_081, "Q head parameter count mismatch")
        path = root / f"seed-{seed}.pt"
        tmp = path.with_suffix(".pt.tmp")
        with tmp.open("xb") as f:
            torch.save({"seed": seed, "state_dict": state, "state_sha256": digest}, f)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        need(path.is_file() and sha(path), "Q initial template was not durably written")
        result[seed] = (state, digest)
        del head; torch.cuda.empty_cache()
    return result


def save_checkpoint(path: Path, head: Any, optimizer: Any, seed: int, arm: str, step: int, init_sha: str, schedule_sha: str) -> str:
    payload = {"seed": seed, "arm": arm, "global_step": step, "head_state": clone_cpu(head.state_dict()), "optimizer_state": clone_cpu(optimizer.state_dict()), "head_sha256": state_hash(head.state_dict()), "initial_head_sha256": init_sha, "schedule_sha256": schedule_sha, "run_contract_sha256": HASHES["run"], "python_rng": random.getstate(), "torch_cpu_rng": torch.get_rng_state().clone(), "cuda_rng": [x.cpu().clone() for x in torch.cuda.get_rng_state_all()], "panel_opened": False}
    torch.save(payload, path)
    return sha(path)


def run_one(probe: Any, trainer: Any, objective: Any, seed: int, arm: str, initial: dict[str, torch.Tensor], init_sha: str, state_cpu: torch.Tensor, cand_cpu: torch.Tensor, primary: list[dict[str, Any]], schedule: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = TRAIN / "runs" / f"seed-{seed}" / arm
    out.mkdir(parents=True, exist_ok=False)
    schedule_sha = sha(SCHEDULE / "fixed-schedule.jsonl")
    run_cfg = {"seed": seed, "arm": arm, "initial_state_sha256": init_sha, "schedule_sha256": schedule_sha, "run_contract_sha256": HASHES["run"], "analysis_contract_sha256": HASHES["analysis"], "addendum_sha256": HASHES["addendum"], "trainer_sha256": sha(Path(__file__).resolve()), "objective_sha256": sha(Q / "source/q_weighted_objective_v02.py"), "same_seed_init_shared": True, "evaluation_panel_opened": False, "evaluation_feedback": False}
    (out / "run-config.json").write_text(json.dumps(run_cfg, indent=2) + "\n", encoding="utf-8")
    seed_all(seed)
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda"); head.load_state_dict(initial, strict=True)
    need(state_hash(head.state_dict()) == init_sha, f"Q paired init differs: {seed}/{arm}")
    opt = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01, betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    state = state_cpu
    candidates = cand_cpu.to("cuda")
    event_path = out / "training-events.jsonl"
    checkpoint_index: list[dict[str, Any]] = []
    start_time = time.perf_counter()
    with event_path.open("x", encoding="utf-8", newline="\n") as telemetry:
        for epoch in range(1, 4):
            block = sorted((r for r in schedule if r["seed"] == seed and r["epoch"] == epoch), key=lambda x: x["step"])
            head.train()
            for sched_row in block:
                step = (epoch - 1) * 40 + sched_row["step"]
                ids = sched_row["primary_occurrence_indices"]
                slots = sched_row["auxiliary_anchor_batch_slots"]
                base = [rows[i] for i in ids]
                aux = [rows[10_000 + s] for s in slots]
                batch = [prepare(r) for r in base] + [prepare(r) for r in aux]
                st, cand, gold, mask, kinds, sources = trainer.fast_tensor_batch(batch, state, candidates, "name_definition", "cuda", reorder=True)
                weights = objective.event_weights(arm, len(base), len(aux), device=st.device)
                expected = torch.cat((torch.ones(len(base), device=st.device), torch.full((len(aux),), 0.5 if arm == "B-SHAM-LOW" else 1.0, device=st.device)))
                need(torch.equal(weights, expected), "Q event-dose weights differ from contract")
                opt.zero_grad(set_to_none=True)
                logits = head(st, cand)
                loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
                need(bool(torch.isfinite(loss).item()) and bool(torch.isfinite(brier).item()), f"nonfinite Q loss at {seed}/{arm}/{step}")
                loss.backward()
                grad_sq = torch.zeros((), device="cuda")
                for p in head.parameters():
                    if p.grad is not None:
                        need(bool(torch.isfinite(p.grad).all().item()), "nonfinite Q gradient")
                        grad_sq += p.grad.detach().float().square().sum()
                opt.step()
                telemetry.write(json.dumps({"event":"optimizer_step","seed":seed,"arm":arm,"epoch":epoch,"global_step":step,"primary_occurrence_indices":ids,"auxiliary_anchor_batch_slots":slots,"primary_count":len(base),"auxiliary_count":len(aux),"loss":float(loss.detach()),"brier":float(brier.detach()),"gradient_norm":float(grad_sq.sqrt()),"evaluation_panel_opened":False}, separators=(",",":"))+"\n")
                telemetry.flush(); os.fsync(telemetry.fileno())
                if step in CHECKPOINTS:
                    name = f"step-{step:03}.pt"; path = out / name
                    ck_sha = save_checkpoint(path, head, opt, seed, arm, step, init_sha, schedule_sha)
                    checkpoint_index.append({"step":step,"path":name,"sha256":ck_sha,"head_sha256":state_hash(head.state_dict())})
                    print(json.dumps({"event":"q_checkpoint","seed":seed,"arm":arm,"step":step,"sha256":ck_sha}, separators=(",",":")), flush=True)
        telemetry.write(json.dumps({"event":"training_complete","steps":120,"panel_opened":False})+"\n")
        telemetry.flush(); os.fsync(telemetry.fileno())
    need([r["step"] for r in checkpoint_index] == list(CHECKPOINTS), f"Q checkpoint cadence mismatch {seed}/{arm}")
    index_path = out / "checkpoint-index.jsonl"
    index_path.write_text("".join(json.dumps(r,separators=(",",":"))+"\n" for r in checkpoint_index), encoding="utf-8")
    integrity = {"status":"Q_TRAINING_COMPLETE_UNEVALUATED","seed":seed,"arm":arm,"optimizer_steps":120,"checkpoint_count":4,"initial_head_sha256":init_sha,"terminal_head_sha256":state_hash(head.state_dict()),"checkpoint_index_sha256":sha(index_path),"telemetry_sha256":sha(event_path),"run_config_sha256":sha(out/"run-config.json"),"schedule_sha256":schedule_sha,"evaluation_panel_opened":False,"elapsed_seconds":time.perf_counter()-start_time}
    (out/"run-integrity.json").write_text(json.dumps(integrity,indent=2)+"\n",encoding="utf-8")
    del head, opt, candidates; torch.cuda.empty_cache()
    return integrity


def tree_entries(root: Path) -> list[dict[str, Any]]:
    return [{"path":p.relative_to(root).as_posix(),"bytes":p.stat().st_size,"sha256":sha(p)} for p in sorted(root.rglob("*")) if p.is_file() and p.name not in {"checkpoint-hash-tree.json","training-seal-manifest.json","execution-progress.json"}]


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("mode", choices=("preflight","run")); args = p.parse_args()
    stage="preflight"
    try:
        packet_receipt = verify_execution_packet()
        parent_receipt = verify_contract_panel_and_sources()
        probe=load_module(ROOT/"experiments/jev-frozen-readout-v01/probe.py","q_probe")
        trainer=load_module(ROOT/"experiments/jev-frozen-scaling-v05/train_v05.py","q_batcher")
        objective=load_module(Q/"source/q_weighted_objective_v02.py","q_objective")
        states,candidates,primary,schedule,arm_rows,scope,candidate_ids=load_training_inputs(probe,trainer)
        need(sha(ROOT/"experiments/jev-frozen-readout-v01/probe.py")==HASHES["probe"] and sha(ROOT/"experiments/jev-frozen-scaling-v05/train_v05.py")==HASHES["loss"],"frozen probe/batcher source mismatch")
        if args.mode=="preflight":
            TRAIN.mkdir(parents=True,exist_ok=False)
            templates={}
            try:
                templates=init_templates(probe)
                need(len({templates[s][1] for s in SEEDS})==3,"seed initial templates unexpectedly collide")
                initial_files=[]
                for seed in SEEDS:
                    path=TRAIN/"initial-templates"/f"seed-{seed}.pt"
                    initial_files.append({"seed":seed,"file_sha256":sha(path),"state_sha256":templates[seed][1]})
                receipt={"status":"Q_TRAINING_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS","execution_packet":packet_receipt,"parents":parent_receipt,"schedule_sha256":sha(SCHEDULE/"fixed-schedule.jsonl"),"trainer_sha256":sha(Path(__file__).resolve()),"probe_sha256":HASHES["probe"],"batcher_sha256":HASHES["loss"],"objective_sha256":HASHES["q_loss"],"head_parameter_count":590081,"paired_initial_templates":initial_files,"input_rows":{"primary":len(primary),"features":list(states.shape),"candidate_features":list(candidates.shape)},"runtime":{"python":sys.version.split()[0],"executable":sys.executable,"torch":torch.__version__,"cuda":torch.version.cuda,"cudnn":torch.backends.cudnn.version(),"device":torch.cuda.get_device_name(0),"matmul_tf32":torch.backends.cuda.matmul.allow_tf32,"cudnn_tf32":torch.backends.cudnn.allow_tf32},"training":False,"evaluation_panel_opened":False,"fresh_panel_prediction_access":False}
                write_json(TRAIN/"training-preflight-receipt-v01.json",receipt)
                print(json.dumps(receipt,indent=2)); return 0
            except BaseException as e:
                write_json(TRAIN/"training-preflight-failure-v01.json",{"status":"Q_PREFLIGHT_FAILED_CLOSED","stage":stage,"exception_type":type(e).__name__,"exception":str(e),"optimizer_steps":0,"panel_opened":False})
                raise
        stage="training"
        preflight=read_json(TRAIN/"training-preflight-receipt-v01.json")
        need(preflight["status"]=="Q_TRAINING_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS" and preflight["trainer_sha256"]==sha(Path(__file__).resolve()) and preflight["execution_packet"]["packet_sha256"]==packet_receipt["packet_sha256"],"Q preflight/code/packet binding mismatch")
        template_payload={}
        for seed in SEEDS:
            row=torch.load(TRAIN/"initial-templates"/f"seed-{seed}.pt",map_location="cpu",weights_only=True)
            template_payload[seed]=(row["state_dict"],row["state_sha256"])
            need(state_hash(row["state_dict"])==row["state_sha256"],"Q template state hash mismatch")
        run_order=[]; run_integrities=[]
        for seed in SEEDS:
            initial,init_sha=template_payload[seed]
            for arm in ORDER[seed]:
                need(arm in ARMS,"unknown arm in frozen schedule")
                integrity=run_one(probe,trainer,objective,seed,arm,initial,init_sha,states,candidates,primary,schedule,arm_rows[arm])
                run_order.append(f"{seed}/{arm}"); run_integrities.append(integrity)
                write_json(TRAIN/"execution-progress.json",{"status":"IN_PROGRESS","completed_order":run_order,"expected_runs":12},replace=True)
                print(json.dumps({"event":"q_run_complete","seed":seed,"arm":arm,"completed":len(run_order),"runs":12},separators=(",",":")),flush=True)
        expected_order=[f"{s}/{a}" for s in SEEDS for a in ORDER[s]]
        need(run_order==expected_order,"Q arm execution order mismatch")
        entries=tree_entries(TRAIN)
        tree={"status":"Q_ALL_TRAINED_STATES_AND_TELEMETRY_HASHED","entry_count":len(entries),"trained_checkpoint_count":48,"initial_template_count":3,"entries":entries}
        write_json(TRAIN/"checkpoint-hash-tree.json",tree)
        seal={"status":"Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED","execution_packet_sha256":packet_receipt["packet_sha256"],"execution_packet_seal_sha256":packet_receipt["packet_seal_sha256"],"run_contract_sha256":HASHES["run"],"analysis_contract_sha256":HASHES["analysis"],"addendum_sha256":HASHES["addendum"],"source_lock_sha256":HASHES["source_lock"],"panel_phase_root_sha256":HASHES["panel_root"],"schedule_sha256":HASHES["schedule"],"training_preflight_sha256":sha(TRAIN/"training-preflight-receipt-v01.json"),"checkpoint_tree_sha256":sha(TRAIN/"checkpoint-hash-tree.json"),"run_count":12,"trained_checkpoint_count":48,"initial_template_count":3,"sealed_object_count":51,"completed_order":run_order,"evaluation_panel_opened":False,"evaluation_feedback":False,"created_at_utc":datetime.now(timezone.utc).isoformat()}
        write_json(TRAIN/"training-seal-manifest.json",seal)
        write_json(TRAIN/"execution-progress.json",{"status":"COMPLETE","completed_order":run_order,"expected_runs":12},replace=True)
        print(json.dumps({"status":seal["status"],"checkpoint_tree_sha256":seal["checkpoint_tree_sha256"],"training_seal_sha256":sha(TRAIN/"training-seal-manifest.json"),"runs":12,"checkpoints":48},indent=2),flush=True)
        return 0
    except BaseException as exc:
        failure=TRAIN/"training-failure-receipt-v01.json"
        if TRAIN.exists() and not failure.exists():
            write_json(failure,{"status":"Q_TRAINING_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED","stage":stage,"exception_type":type(exc).__name__,"exception":str(exc),"panel_opened":False,"automatic_retry":False,"failed_at_utc":datetime.now(timezone.utc).isoformat()})
        raise

if __name__ == "__main__":
    raise SystemExit(main())
