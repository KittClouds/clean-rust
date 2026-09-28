"""Execute 24 common SHAM-1x prefixes and 48 exact-state late branches."""

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
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
TRAIN = RUN / "training-v01"
ARTIFACTS = TRAIN / "trajectories"
SCHEDULE = TRAIN / "schedule"
INPUT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
STATE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache")
CANDIDATE = INPUT.parent / "phase-b-run-v01/feature-cache"
PANEL = RUN / "panel-v01"
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
BRANCHES = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
FIELDS = ("group_id", "source_episode_id", "target_hash", "candidate_order_hash", "candidate_semantic_ids", "target")
HASHES = {
    "run": "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6",
    "analysis": "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64",
    "panel": "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153",
    "packet": "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "sham": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "state_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "state_scope": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "state_receipt": "d98ae657e28b976f187d4d67e58119ce80496e76c061c90362ac2e50ff7f720e",
    "candidate_receipt": "29f8d67b24fd2a554500e1cfe2e0fe0b4311d32fad7052ad8ffb3464b7835f44",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "batcher": "52033950dab23835c13f4aa74a2f0d5867aec754f8a139a63a739a36b0cb62b9",
    "objective": "fc412072592857be36b02312d852d08ce3df2bf6fa7b28f8c1d59575c28e1ea4",
}


def sha(path: Path) -> str:
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
    """Stable recursive digest for optimizer/RNG payloads; no pickle metadata."""
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
        elif isinstance(item, (list, tuple)):
            digest.update(b"list\0" if isinstance(item, list) else b"tuple\0")
            for child in item:
                visit(child)
            digest.update(b"end-sequence\0")
        elif item is None or isinstance(item, (bool, int, float, str)):
            digest.update(type(item).__name__.encode() + b"\0")
            digest.update(json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\0")
        else:
            raise TypeError(f"unsupported value in stable state digest: {type(item).__name__}")

    visit(value)
    return digest.hexdigest()


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def verify_authorities() -> dict[str, Any]:
    run_path = EXP / "contracts/q-r2-run-contract-v01.json"
    analysis_path = EXP / "contracts/q-r2-analysis-contract-v01.json"
    panel_contract = EXP / "contracts/q-r2-panel-contract-v01.json"
    packet_path = EXP / "seals/q-r2-phase-packet-seal-v01.json"
    for path, key in ((run_path, "run"), (analysis_path, "analysis"), (panel_contract, "panel"), (packet_path, "packet")):
        need(sha(path) == HASHES[key], f"R2 {key} authority changed")
    packet = read_json(packet_path)
    need(packet.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION", "R2 packet not authorized")
    for row in packet["contracts"]:
        target = EXP / row["path"]
        need(target.stat().st_size == row["bytes"] and sha(target) == row["sha256"], f"contract bundle drift: {row['path']}")
    return {"packet_sha256": HASHES["packet"], "packet_root_sha256": packet["contract_bundle_root_sha256"]}


def verify_instrument() -> dict[str, Any]:
    verifier = load_module(EXP / "source/verify_q_r2_instrument_package_v01.py", "r2_instrument_verify_train")
    return verifier.verify()


def verify_panel_input_seal() -> dict[str, Any]:
    seal_path = PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"
    seal = read_json(seal_path)
    need(seal.get("status") == "Q_R2_PANEL_INPUTS_SEALED_TRAINING_PENDING", "R2 panel input seal state mismatch")
    payload = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(seal["entries"], key=lambda r: r["path"]))
    root = hashlib.sha256(payload.encode()).hexdigest()
    need(root == seal.get("root_sha256"), "R2 panel input root mismatch")
    for row in seal["entries"]:
        path = PANEL / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], f"R2 panel input changed: {row['path']}")
    need(seal.get("head_initialization") is False and seal.get("training") is False and seal.get("inference") is False, "panel seal overstates model contact")
    return {"seal_sha256": sha(seal_path), "root_sha256": root, "entry_count": len(seal["entries"])}


def load_frozen_sources() -> tuple[Any, Any, Any, torch.Tensor, torch.Tensor, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    paths = {
        "primary": INPUT / "common-primary-occurrence-manifest.jsonl",
        "sham": INPUT / "head-input-manifest-B-SHAM.jsonl",
        "state_scope": STATE / "training-only-feature-scope.jsonl",
        "state_features": STATE / "shared-training-features.pt",
        "candidate_features": CANDIDATE / "candidate-features.pt",
        "candidate_catalog": INPUT / "candidate-catalog.json",
        "state_receipt": STATE / "shared-feature-cache-receipt.json",
        "candidate_receipt": CANDIDATE / "candidate-feature-receipt.json",
    }
    for key in ("primary", "sham", "state_scope", "state_features", "candidate_features", "candidate_catalog", "state_receipt", "candidate_receipt"):
        expected = HASHES[key]
        need(sha(paths[key]) == expected, f"bound Q training input changed: {key}")
    primary = read_jsonl(paths["primary"])
    sham_rows = read_jsonl(paths["sham"])
    scope = read_jsonl(paths["state_scope"])
    catalog = read_json(paths["candidate_catalog"])
    need(len(primary) == 10_000 and len(sham_rows) == 15_000 and len(scope) == 55_000, "training source row count mismatch")
    need(all(row.get("index") == i for i, row in enumerate(scope)), "training feature scope index mismatch")
    for i, base in enumerate(primary):
        row = sham_rows[i]
        need(row.get("event_kind") == "primary" and row.get("occurrence_index") == i, f"SHAM primary stream row drift: {i}")
        for field in FIELDS:
            key = "source_episode_id" if field == "source_episode_id" else field
            base_key = "episode_id" if field == "source_episode_id" else field
            need(row.get(key) == base.get(base_key), f"common primary payload drift: row {i}/{field}")
    auxiliary = sham_rows[10_000:]
    need(all(row.get("event_kind") == "auxiliary" and row.get("auxiliary_source_role") == "certified_sham"
             and row.get("loss_weight") == 1.0 for row in auxiliary), "B-SHAM auxiliary payload identity mismatch")
    candidate_ids = [str(row["candidate_semantic_id"]) for row in catalog["rows"]]
    need(len(candidate_ids) == 48 and len(set(candidate_ids)) == 48 and catalog.get("feature_dimension") == 2048, "training candidate catalog schema mismatch")
    state_receipt, candidate_receipt = read_json(paths["state_receipt"]), read_json(paths["candidate_receipt"])
    need(state_receipt.get("status") == "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY"
         and candidate_receipt.get("status") == "CANDIDATE_FEATURES_VALIDATED", "training feature receipt state mismatch")
    state_pack = torch.load(paths["state_features"], map_location="cpu", weights_only=True)
    states = state_pack["features"]
    candidates = torch.load(paths["candidate_features"], map_location="cpu", weights_only=True)
    need(tuple(states.shape) == (55_000, 2048) and states.dtype == torch.float32 and states.is_contiguous() and torch.isfinite(states).all(), "training state tensor invalid")
    need(tuple(candidates.shape) == (48, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous() and torch.isfinite(candidates).all(), "candidate tensor invalid")
    need(state_pack.get("feature_key") == "mean_full@16" and candidate_receipt.get("semantic_ids") == candidate_ids, "training feature identity/order mismatch")
    probe_path = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
    batcher_path = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
    objective_path = Q / "source/q_weighted_objective_v02.py"
    need(sha(probe_path) == HASHES["probe"] and sha(batcher_path) == HASHES["batcher"] and sha(objective_path) == HASHES["objective"], "frozen head/batcher/loss source changed")
    probe = load_module(probe_path, "r2_frozen_probe")
    batcher = load_module(batcher_path, "r2_frozen_batcher")
    objective = load_module(objective_path, "r2_frozen_q_objective")
    schedule = read_jsonl(SCHEDULE / "fixed-schedule.jsonl")
    schedule_manifest = read_json(SCHEDULE / "fixed-schedule-manifest.json")
    schedule_seal = read_json(SCHEDULE / "schedule-seal.json")
    need(len(schedule) == 2_880 and sha(SCHEDULE / "fixed-schedule.jsonl") == schedule_seal["schedule_sha256"] == schedule_manifest["schedule_sha256"], "R2 schedule seal mismatch")
    need(schedule_manifest["seeds"] == list(SEEDS) and schedule_manifest["checkpoints"] == [80, 100, 120], "R2 schedule manifest scope mismatch")
    for seed in SEEDS:
        rows = [row for row in schedule if int(row["seed"]) == seed]
        need(len(rows) == 120 and [row["global_step"] for row in rows] == list(range(1, 121)), f"R2 per-seed schedule mismatch: {seed}")
        for row in rows:
            ids = row["primary_occurrence_indices"]
            need(row["primary_group_ids"] == [primary[i]["group_id"] for i in ids], "schedule group ordering mismatch")
            expected_slots = [primary[i]["occurrence_index"] // 2 for i in ids if primary[i]["role"] == "anchor"]
            need(row["auxiliary_anchor_batch_slots"] == expected_slots, "schedule auxiliary-slot binding mismatch")
    return probe, batcher, objective, states, candidates, primary, auxiliary, scope, schedule, {"candidate_ids": candidate_ids, "state_scope_sha256": sha(paths["state_scope"])}


def prepare(row: dict[str, Any]) -> dict[str, Any]:
    return {"group_id": row.get("group_id", row["source_episode_id"]), "state_idx": int(row["feature_scope_index"]),
            "candidate_indices": {"name_definition": row["candidate_indices"]}, "gold": row["target"],
            "kind": "choice", "probability_source": "exact_generative_posterior"}


def seed_all(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def capture_rng() -> dict[str, Any]:
    return {"python": random.getstate(), "torch_cpu": torch.get_rng_state().clone(),
            "torch_cuda": [state.cpu().clone() for state in torch.cuda.get_rng_state_all()]}


def restore_rng(state: dict[str, Any]) -> None:
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"])
    torch.cuda.set_rng_state_all(state["torch_cuda"])


def save_payload(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("xb") as stream:
        torch.save(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    return sha(path)


def make_checkpoint(seed: int, label: str, step: int, head: Any, optimizer: Any, init_sha: str,
                    schedule_sha: str, event_cursor: int, branch_weight: float) -> dict[str, Any]:
    return {"seed": seed, "branch": label, "global_step": step, "head_state": clone_cpu(head.state_dict()),
            "optimizer_state": clone_cpu(optimizer.state_dict()), "head_sha256": state_sha(head.state_dict()),
            "initial_head_sha256": init_sha, "schedule_sha256": schedule_sha, "event_cursor": event_cursor,
            "branch_auxiliary_multiplier": branch_weight, "rng_state": capture_rng(),
            "run_contract_sha256": HASHES["run"], "evaluation_panel_opened": False}


def train_steps(seed: int, branch: str, weight: float, start: int, end: int, head: Any, optimizer: Any,
                batcher: Any, objective: Any, states: torch.Tensor, candidates: torch.Tensor,
                primary: list[dict[str, Any]], auxiliary: list[dict[str, Any]], schedule: list[dict[str, Any]],
                telemetry_path: Path, checkpoints: list[dict[str, Any]], init_sha: str,
                schedule_sha: str) -> None:
    mode = "x" if not telemetry_path.exists() else "a"
    with telemetry_path.open(mode, encoding="utf-8", newline="\n") as telemetry:
        for item in schedule:
            step = int(item["global_step"])
            if not start <= step <= end:
                continue
            base_rows = [primary[i] for i in item["primary_occurrence_indices"]]
            aux_rows = [auxiliary[i] for i in item["auxiliary_anchor_batch_slots"]]
            batch = [prepare(row) for row in base_rows] + [prepare(row) for row in aux_rows]
            st, cand, gold, mask, kinds, sources = batcher.fast_tensor_batch(batch, states, candidates, "name_definition", "cuda", reorder=True)
            weights = torch.cat((torch.ones(len(base_rows), device=st.device), torch.full((len(aux_rows),), weight, device=st.device)))
            need(weights.shape[0] == len(batch) and torch.isfinite(weights).all(), "R2 event weight vector invalid")
            optimizer.zero_grad(set_to_none=True)
            logits = head(st, cand)
            loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
            need(bool(torch.isfinite(loss).item()) and bool(torch.isfinite(brier).item()), f"nonfinite loss at {seed}/{branch}/{step}")
            loss.backward()
            grad_sq = torch.zeros((), device="cuda")
            for parameter in head.parameters():
                if parameter.grad is not None:
                    need(bool(torch.isfinite(parameter.grad).all().item()), "nonfinite gradient")
                    grad_sq += parameter.grad.detach().float().square().sum()
            optimizer.step()
            telemetry.write(json.dumps({"event": "optimizer_step", "seed": seed, "branch": branch, "step": step,
                "primary_indices": item["primary_occurrence_indices"], "auxiliary_slots": item["auxiliary_anchor_batch_slots"],
                "primary_count": len(base_rows), "auxiliary_count": len(aux_rows), "auxiliary_multiplier": weight,
                "loss": float(loss.detach()), "brier": float(brier.detach()), "gradient_norm": float(grad_sq.sqrt()),
                "panel_opened": False}, separators=(",", ":")) + "\n")
            if step in (80, 100, 120):
                if step == 80 and branch != "COMMON_SHAM_1X":
                    continue
                if step in (100, 120) and branch == "COMMON_SHAM_1X":
                    continue
                path = checkpoints[0]["path_for_step"](step)
                payload = make_checkpoint(seed, branch, step, head, optimizer, init_sha, schedule_sha,
                                          step, weight)
                digest = save_payload(path, payload)
                checkpoints.append({"step": step, "path": str(path), "sha256": digest,
                                    "head_sha256": payload["head_sha256"], "branch": branch})
            telemetry.flush()
            os.fsync(telemetry.fileno())


def runtime_gate() -> dict[str, Any]:
    need(torch.__version__ == "2.11.0+cu128" and torch.cuda.is_available(), "frozen CUDA/PyTorch runtime mismatch")
    need(torch.version.cuda == "12.8" and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080", "frozen GPU identity mismatch")
    need(torch.backends.cuda.matmul.allow_tf32 is False and torch.backends.cudnn.allow_tf32 is True
         and torch.backends.cudnn.benchmark is False and torch.are_deterministic_algorithms_enabled() is False,
         "frozen precision/determinism settings mismatch")
    return {"torch": torch.__version__, "cuda": torch.version.cuda, "device": torch.cuda.get_device_name(0),
            "tf32_matmul": torch.backends.cuda.matmul.allow_tf32, "cudnn_tf32": torch.backends.cudnn.allow_tf32}


def self_test() -> None:
    logits = torch.tensor([[0.2, -0.1, 0.3, -0.4], [0.1, 0.5, -0.2, 0.0]], dtype=torch.float32)
    gold = torch.tensor([[0.1, 0.2, 0.6, 0.1], [0.25, 0.25, 0.25, 0.25]], dtype=torch.float32)
    mask = torch.ones_like(gold, dtype=torch.bool)
    objective = load_module(Q / "source/q_weighted_objective_v02.py", "r2_objective_smoke")
    one = objective.event_weights("B-SHAM", 1, 1, device=torch.device("cpu"))
    half = objective.event_weights("B-SHAM-LOW", 1, 1, device=torch.device("cpu"))
    kinds = ["choice", "choice"]
    sources = ["exact_generative_posterior", "exact_generative_posterior"]
    l1, _ = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, one)
    l2, _ = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, half)
    assert torch.isfinite(l1) and torch.isfinite(l2) and not torch.equal(one, half)
    assert len(SEEDS) == 24 and len(set(SEEDS)) == 24
    print("R2 paired-training synthetic smoke PASS")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    stage = "preflight"
    try:
        authority = verify_authorities()
        instrument = verify_instrument()
        panel_binding = verify_panel_input_seal()
        runtime = runtime_gate()
        loaded = load_frozen_sources()
        probe, batcher, objective, states, candidates, primary, auxiliary, scope, schedule, input_meta = loaded
        manifest = read_json(SCHEDULE / "fixed-schedule-manifest.json")
        branch_order = manifest["branch_order_by_seed"]
        need(set(int(key) for key in branch_order) == set(SEEDS), "branch-order map seed set mismatch")
        if args.preflight:
            print(json.dumps({"status": "Q_R2_TRAINING_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION", "authority": authority,
                "instrument": instrument, "panel_input": panel_binding, "runtime": runtime,
                "primary_rows": len(primary), "auxiliary_rows": len(auxiliary), "feature_shape": list(states.shape),
                "candidate_shape": list(candidates.shape), "schedule_rows": len(schedule), "seeds": len(SEEDS),
                "head_initialization": False, "optimizer_steps": 0, "panel_opened": False}, indent=2))
            return 0
        need(not ARTIFACTS.exists(), f"refusing pre-existing R2 trajectory artifacts: {ARTIFACTS}")
        need(not (TRAIN / "training-seal-manifest.json").exists(), "R2 training seal already exists")
        ARTIFACTS.mkdir(parents=True, exist_ok=False)
        templates = ARTIFACTS / "initial-templates"
        templates.mkdir()
        prefixes = ARTIFACTS / "common-prefixes"
        prefixes.mkdir()
        continuations = ARTIFACTS / "continuations"
        continuations.mkdir()
        schedule_sha = sha(SCHEDULE / "fixed-schedule.jsonl")
        prefix_receipts: dict[int, dict[str, Any]] = {}
        initial_states: dict[int, tuple[dict[str, torch.Tensor], str, Path]] = {}
        for seed in SEEDS:
            seed_all(seed)
            head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
            initial = clone_cpu(head.state_dict())
            init_sha = state_sha(initial)
            need(sum(t.numel() for t in initial.values()) == 590_081, "R2 head parameter-count mismatch")
            template_path = templates / f"seed-{seed}.pt"
            template_sha = save_payload(template_path, {"seed": seed, "state_dict": initial, "state_sha256": init_sha})
            initial_states[seed] = (initial, init_sha, template_path)
            prefix_dir = prefixes / f"seed-{seed}"
            prefix_dir.mkdir()
            optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
                betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
            telemetry = prefix_dir / "training-events.jsonl"
            index: list[dict[str, Any]] = []
            step_rows = [row for row in schedule if int(row["seed"]) == seed]
            callbacks = [{"path_for_step": lambda step, d=prefix_dir: d / f"step-{step:03}.pt"}]
            stage = "common_prefix"
            train_steps(seed, "COMMON_SHAM_1X", 1.0, 1, 80, head, optimizer, batcher, objective,
                        states, candidates, primary, auxiliary, step_rows, telemetry, callbacks, init_sha, schedule_sha)
            need(len(callbacks) == 2 and callbacks[1]["step"] == 80, f"step80 checkpoint missing: {seed}")
            fork_path = callbacks[1]["path"]
            fork = torch.load(fork_path, map_location="cpu", weights_only=False)
            need(fork.get("global_step") == 80 and fork.get("branch") == "COMMON_SHAM_1X"
                 and fork.get("head_sha256") == state_sha(fork["head_state"]), f"step80 fork state invalid: {seed}")
            prefix_receipts[seed] = {"seed": seed, "initial_sha256": init_sha, "template_sha256": template_sha,
                "step80_path": str(fork_path), "step80_sha256": sha(fork_path), "step80_head_sha256": fork["head_sha256"],
                "telemetry_sha256": sha(telemetry), "optimizer_state_sha256": tree_sha(fork["optimizer_state"]),
                "common_prefix_steps": 80, "panel_opened": False}
            del head, optimizer, states, candidates
            torch.cuda.empty_cache()
            # Retain CPU feature tensors for the next seed without duplicating the cache.
            states = loaded[3]
            candidates = loaded[4]
            print(json.dumps({"event": "q_r2_common_prefix_complete", "seed": seed, "step80_sha256": sha(fork_path)}), flush=True)
        write_json(TRAIN / "common-prefix-seal-v01.json", {"status": "Q_R2_ALL_24_COMMON_PREFIXES_SEALED",
            "prefixes": prefix_receipts, "count": 24, "schedule_sha256": schedule_sha,
            "panel_opened": False, "branches_started": False})

        branch_receipts: list[dict[str, Any]] = []
        for seed_index, seed in enumerate(SEEDS):
            prefix = prefix_receipts[seed]
            fork = torch.load(Path(prefix["step80_path"]), map_location="cpu", weights_only=False)
            ordered_branches = branch_order[str(seed)]
            for branch in ordered_branches:
                weight = 1.0 if branch == "LATE_SHAM_1X" else 0.5
                branch_dir = continuations / f"seed-{seed}" / branch
                branch_dir.mkdir(parents=True)
                # Construct modules, then restore the complete shared step-80 RNG state.
                head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                head.load_state_dict(fork["head_state"], strict=True)
                optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
                    betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
                optimizer.load_state_dict(fork["optimizer_state"])
                need(state_sha(head.state_dict()) == fork["head_sha256"], "branch head did not clone step80 state")
                need(state_sha(head.state_dict()) == prefix["step80_head_sha256"], "paired fork head hash mismatch")
                need(tree_sha(optimizer.state_dict()) == prefix["optimizer_state_sha256"],
                     "branch optimizer state did not clone the step80 state")
                restore_rng(fork["rng_state"])
                branch_rng_sha = tree_sha(capture_rng())
                need(branch_rng_sha == tree_sha(fork["rng_state"]), "branch RNG state did not restore exactly")
                telemetry = branch_dir / "training-events.jsonl"
                index: list[dict[str, Any]] = []
                step_rows = [row for row in schedule if int(row["seed"]) == seed]
                callbacks = [{"path_for_step": lambda step, d=branch_dir: d / f"step-{step:03}.pt"}]
                stage = f"late_branch_{branch}"
                train_steps(seed, branch, weight, 81, 120, head, optimizer, batcher, objective,
                    states, candidates, primary, auxiliary, step_rows, telemetry, callbacks,
                    prefix["initial_sha256"], schedule_sha)
                need([row["step"] for row in callbacks[1:]] == [100, 120], f"branch checkpoint cadence mismatch: {seed}/{branch}")
                receipt = {"status": "Q_R2_BRANCH_COMPLETE_UNEVALUATED", "seed": seed, "branch": branch, "weight": weight, "fork_step": 80,
                    "fork_sha256": prefix["step80_sha256"], "fork_head_sha256": prefix["step80_head_sha256"],
                    "fork_optimizer_sha256": prefix["optimizer_state_sha256"], "fork_rng_sha256": branch_rng_sha,
                    "step100_sha256": callbacks[1]["sha256"], "step120_sha256": callbacks[2]["sha256"],
                    "step100_head_sha256": callbacks[1]["head_sha256"], "step120_head_sha256": callbacks[2]["head_sha256"],
                    "telemetry_sha256": sha(telemetry), "training_steps": 40,
                    "schedule_sha256": schedule_sha, "evaluation_panel_opened": False}
                write_json(branch_dir / "branch-receipt.json", receipt)
                branch_receipts.append(receipt)
                del head, optimizer, fork
                torch.cuda.empty_cache()
                fork = torch.load(Path(prefix["step80_path"]), map_location="cpu", weights_only=False)
                print(json.dumps({"event": "q_r2_branch_complete", "seed": seed, "branch": branch,
                    "step100_sha256": receipt["step100_sha256"], "step120_sha256": receipt["step120_sha256"]}), flush=True)

        need(len(branch_receipts) == 48, "R2 continuation count mismatch")
        need(not any(row.get("panel_opened", False) for row in prefix_receipts.values()), "evaluation opened during common prefixes")
        entries = []
        for path in sorted(ARTIFACTS.rglob("*")):
            if path.is_file():
                entries.append({"path": path.relative_to(TRAIN).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
        tree_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
        tree_root = hashlib.sha256(tree_body.encode()).hexdigest()
        checkpoint_count = 24 + 48 * 2
        tree = {"status": "Q_R2_COMPLETE_CHECKPOINT_AND_TELEMETRY_TREE_SEALED",
            "entries": entries, "entry_count": len(entries), "entries_root_sha256": tree_root,
            "shared_step80_checkpoints": 24, "late_branch_checkpoints": 96,
            "trained_checkpoint_count": checkpoint_count, "prefix_count": 24, "continuation_count": 48,
            "panel_opened": False, "evaluation": False}
        write_json(TRAIN / "checkpoint-hash-tree.json", tree)
        common_seal_sha = sha(TRAIN / "common-prefix-seal-v01.json")
        seal = {"status": "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED",
            "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
            "run_contract_sha256": HASHES["run"], "analysis_contract_sha256": HASHES["analysis"],
            "packet_sha256": authority["packet_sha256"], "packet_bundle_root_sha256": authority["packet_root_sha256"],
            "panel_input_seal_sha256": panel_binding["seal_sha256"], "panel_input_root_sha256": panel_binding["root_sha256"],
            "instrument_seal_sha256": instrument["seal_sha256"], "instrument_entries_root_sha256": instrument["entries_root_sha256"],
            "schedule_sha256": schedule_sha, "common_prefix_seal_sha256": common_seal_sha,
            "checkpoint_tree_sha256": sha(TRAIN / "checkpoint-hash-tree.json"), "checkpoint_tree_root_sha256": tree_root,
            "seed_count": 24, "prefix_count": 24, "continuation_count": 48,
            "step80_checkpoints": 24, "step100_checkpoints": 48, "step120_checkpoints": 48,
            "trained_checkpoint_count": checkpoint_count, "artifact_entry_count": len(entries),
            "training_panel_feedback": False, "evaluation_panel_opened": False,
            "runtime": runtime, "created_at_utc": datetime.now(timezone.utc).isoformat()}
        write_json(TRAIN / "training-seal-manifest.json", seal)
        print(json.dumps({"status": seal["status"], "checkpoint_tree_root_sha256": tree_root,
            "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"), "prefixes": 24,
            "continuations": 48, "checkpoints": checkpoint_count}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if TRAIN.exists() and not (TRAIN / "training-failure-receipt-v01.json").exists():
            write_json(TRAIN / "training-failure-receipt-v01.json", {"status": "Q_R2_TRAINING_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "panel_opened": False, "automatic_retry": False, "failed_at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
