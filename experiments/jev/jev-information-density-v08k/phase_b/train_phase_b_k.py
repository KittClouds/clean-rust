"""Paired K-DUP/K-SHAM frozen-head training for v0.8K."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean")
PARENT = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
J_PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01")
CONTRACT = CODE / "phase-b-v01-contract.json"
AUTH = RUN / "preflight/model-contact-authorization.json"
FEATURES = RUN / "feature-cache/phase-b-train-features.pt"
FEATURE_RECEIPT = RUN / "feature-cache/extraction-receipt.json"
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("K-DUP", "K-SHAM")
SCHEDULE = (("K-DUP", "K-SHAM"), ("K-SHAM", "K-DUP"), ("K-DUP", "K-SHAM"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_event(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def initialize_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def verify_bindings() -> tuple[dict[str, Any], Any, Any]:
    contract = read_json(CONTRACT)
    auth = read_json(AUTH)
    require(auth["status"] == "PASS" and auth["training_authorized"] is True, "K training authorization absent")
    require(auth["contract_sha256"] == sha256_file(CONTRACT), "K contract drift after preflight")
    require(auth["objective_graph_sha256"] == contract["objective_graph_sha256"], "K graph drift")
    require(auth["source_code_sha256"]["train_phase_b_k.py"] == sha256_file(Path(__file__)), "K trainer drift after preflight")
    receipt = read_json(FEATURE_RECEIPT)
    require(receipt["status"] == "FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY", "K feature receipt absent")
    require(receipt["objective_graph_sha256"] == contract["objective_graph_sha256"], "K feature graph drift")
    require(receipt["phase_a_identity"] == "phase-a-v01-clean", "K feature identity drift")
    require(receipt["evaluation_bodies_opened"] is False and receipt["phoenix_access"] is False, "K feature boundary crossed")
    require(sha256_file(FEATURES) == receipt["feature_cache"]["sha256"], "K feature cache drift")
    probe = load_module("jev_v08k_probe", ROOT / "experiments/jev-frozen-readout-v01/probe.py")
    trainer = load_module("jev_v08k_train_v05", ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py")
    return contract, probe, trainer


def load_training_data(probe: Any) -> dict[str, Any]:
    cache = torch.load(FEATURES, map_location="cpu", weights_only=True)
    require(cache["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "feature revision drift")
    require(cache["hidden_dim"] == 2048 and cache["layer_count"] == 16 and cache["backbone_frozen"] is True, "feature identity drift")
    state = cache["features"]["state"][FEATURE_KEY]
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY]
    require(state.dtype == torch.float32 and candidates.dtype == torch.float32, "feature dtype drift")
    primary = read_jsonl(PARENT / "materialized/F100-groups.jsonl")
    triplets = read_jsonl(PHASE_A / "inputs/triplets.jsonl")
    dup_events = read_jsonl(PHASE_A / "inputs/dup-auxiliary-events.jsonl")
    sham_events = read_jsonl(PHASE_A / "inputs/sham-auxiliary-events.jsonl")
    sham_rows = read_jsonl(J_PHASE_A / "inputs/sham-views.jsonl")
    require(len(primary) == 100000 and len(triplets) == 5000 and len(dup_events) == 5000 and len(sham_events) == 5000, "K training input count drift")
    auth = read_json(AUTH)
    require(sha256_file(J_PHASE_A / "inputs/sham-views.jsonl") == auth["verified_sham_training_source_sha256"], "sealed sham source drift")
    require(all(row.get("split") == "train" for row in sham_rows), "sham source is not training-only")
    require(sha256_file(PARENT / "materialized/F100-groups.jsonl") == read_json(PHASE_A / "phase-a-receipt.json")["primary_bank"]["sha256"], "F100 drift")
    require(sha256_file(PHASE_A / "inputs/dup-auxiliary-events.jsonl") == read_json(PHASE_A / "phase-a-receipt.json")["arms"]["K-DUP"]["auxiliary_events_sha256"], "DUP event drift")
    require(sha256_file(PHASE_A / "inputs/sham-auxiliary-events.jsonl") == read_json(PHASE_A / "phase-a-receipt.json")["arms"]["K-SHAM"]["auxiliary_events_sha256"], "SHAM event drift")
    primary.sort(key=lambda row: row["group_id"])
    by_primary = {row["group_id"]: row for row in primary}
    by_sham = {row["group_id"]: row for row in sham_rows}
    require(len(by_primary) == 100000 and len(by_sham) == 5000, "training row identity drift")
    dup_by_triplet = {row["triplet_id"]: row for row in dup_events}
    sham_by_triplet = {row["triplet_id"]: row for row in sham_events}
    triplet_rows = []
    for item in triplets:
        dup = dup_by_triplet[item["triplet_id"]]
        sham_event = sham_by_triplet[item["triplet_id"]]
        anchor = by_primary.get(item["anchor_group_id"])
        fact = by_primary.get(item["fact_flip_group_id"])
        sham = by_sham.get(sham_event["source_group_id"])
        require(anchor is not None and fact is not None and sham is not None, f"triplet row missing: {item['triplet_id']}")
        require(dup["source_group_id"] == anchor["group_id"], "DUP source is not anchor")
        require(sham_event["source_group_id"] == sham["group_id"], "SHAM source is not sham view")
        triplet_rows.append({"meta": item, "anchor": anchor, "fact_flip": fact, "sham": sham})
    existing_pairs = probe.invariant_pairs(primary, "train")
    require(len(existing_pairs) == 4982, f"inherited pair count drift: {len(existing_pairs)}")
    return {"cache": cache, "state": state, "candidates": candidates, "primary": primary, "triplets": triplet_rows, "existing_pairs": existing_pairs}


def train_arm(data: dict[str, Any], probe: Any, trainer: Any, contract: dict[str, Any], seed_index: int, arm: str, initial_state: dict[str, torch.Tensor], device: str) -> dict[str, Any]:
    seed = SEEDS[seed_index]
    run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {"protocol": contract["protocol"], "seed": seed, "arm": arm, "objective_graph_sha256": contract["objective_graph_sha256"], "feature_cache_sha256": sha256_file(FEATURES), "head": "dynamic_mlp_compatibility", "projection_width": 128, "trainable_parameters": 590081, "loss": "existing_v08i_L3_pointwise_auxiliary", "brier_weight": 0.25, "existing_invariance_weight": 0.10, "auxiliary_weight": 1.0, "epochs": 3, "batch_size_groups": 256, "optimizer": "AdamW", "learning_rate": 0.002, "weight_decay": 0.01, "scheduler": "none", "gradient_clipping": "none", "primary_groups": 100000, "triplets": 5000, "auxiliary_events": 5000, "auxiliary_source_role": "anchor" if arm == "K-DUP" else "sham", "paired_initialization": True, "evaluation_access": False}
    config_hash = sha256_json(config)
    config_path = run_dir / "run-config.json"
    if config_path.exists():
        require(read_json(config_path)["config_sha256"] == config_hash, f"run config drift: {seed_index}/{arm}")
    else:
        write_json(config_path, {**config, "config_sha256": config_hash})
    report_path = run_dir / "run-report.json"
    if report_path.exists():
        report = read_json(report_path)
        require(report["status"] == "TRAINING_COMPLETE_NO_EVALUATION", f"unexpected existing run: {seed_index}/{arm}")
        return report

    state = data["state"].to(device)
    candidates = data["candidates"].to(device)
    head = probe.CompatibilityHead(data["cache"]["hidden_dim"], "mlp", 128).to(device)
    head.load_state_dict(copy.deepcopy(initial_state))
    initial_sha = score_digest(head.state_dict())
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01)
    triplet_by_anchor = {row["anchor"]["group_id"]: row for row in data["triplets"]}
    events = run_dir / "training-events.jsonl"
    history = []
    start_all = time.perf_counter()
    for epoch in range(3):
        shuffled = list(data["primary"])
        random.Random(seed + epoch).shuffle(shuffled)
        head.train()
        totals: Counter[str] = Counter()
        step_count = 0
        for start in range(0, len(shuffled), 256):
            batch = shuffled[start : start + 256]
            state_batch, candidate_batch, gold, mask, kinds, sources = trainer.fast_tensor_batch(batch, state, candidates, PROFILE, device, reorder=True)
            active = [triplet_by_anchor[row["group_id"]] for row in batch if row["group_id"] in triplet_by_anchor]
            shared_rows = []
            for item in active:
                shared_rows.extend((item["anchor"], item["fact_flip"], item["sham"]))
            optimizer.zero_grad(set_to_none=True)
            base_logits = head(state_batch, candidate_batch)
            base_loss, _ = trainer.v05_loss(base_logits, gold, mask, kinds, sources, 0.25)
            existing_loss = trainer.vectorized_invariant_loss(head, data["existing_pairs"], state, candidates, PROFILE, device)
            if shared_rows:
                shared_state, shared_candidate, shared_gold, shared_mask, shared_kinds, shared_sources = trainer.fast_tensor_batch(shared_rows, state, candidates, PROFILE, device, reorder=False)
                shared_logits = head(shared_state, shared_candidate)
                source_index = 0 if arm == "K-DUP" else 2
                aux_logits = shared_logits[source_index::3]
                aux_gold = shared_gold[source_index::3]
                aux_mask = shared_mask[source_index::3]
                aux_kinds = shared_kinds[source_index::3]
                aux_sources = shared_sources[source_index::3]
                aux_loss, _ = trainer.v05_loss(aux_logits, aux_gold, aux_mask, aux_kinds, aux_sources, 0.25)
            else:
                aux_loss = torch.zeros((), device=device)
            count = len(batch)
            aux_count = len(active)
            loss = (base_loss * count + aux_loss * aux_count) / max(1, count + aux_count) + 0.10 * existing_loss
            loss.backward()
            gradients = [parameter.grad.detach().norm(2) for parameter in head.parameters() if parameter.grad is not None]
            grad_norm = float(torch.linalg.vector_norm(torch.stack(gradients), 2).detach().cpu()) if gradients else 0.0
            optimizer.step()
            totals["count"] += count
            for key, value in (("loss", loss), ("base_loss", base_loss), ("aux_loss", aux_loss), ("existing_invariance", existing_loss)):
                totals[key] += float(value.detach().cpu()) * count
            step_count += 1
            append_event(events, {"event": "training_step", "epoch": epoch + 1, "step": step_count, "steps_in_epoch": math.ceil(len(shuffled) / 256), "groups": count, "active_triplets": aux_count, "loss": float(loss.detach().cpu()), "base_loss": float(base_loss.detach().cpu()), "aux_loss": float(aux_loss.detach().cpu()), "existing_invariance": float(existing_loss.detach().cpu()), "gradient_norm": grad_norm, "learning_rate": optimizer.param_groups[0]["lr"], "evaluation_access": False})
        history.append({"epoch": epoch + 1, "groups": int(totals["count"]), "optimizer_steps": step_count, "active_triplets_total": sum(1 for row in shuffled if row["group_id"] in triplet_by_anchor), **{key: totals[key] / max(1, totals["count"]) for key in ("loss", "base_loss", "aux_loss", "existing_invariance")}})
        torch.save({"head_state": head.state_dict(), "optimizer_state": optimizer.state_dict(), "initial_head_sha256": initial_sha, "config_sha256": config_hash, "epoch": epoch + 1}, run_dir / f"checkpoint-epoch-{epoch + 1}.pt")
    report = {"status": "TRAINING_COMPLETE_NO_EVALUATION", "protocol": contract["protocol"], "arm": arm, "seed": seed, "config_sha256": config_hash, "initial_head_sha256": initial_sha, "terminal_head_sha256": score_digest(head.state_dict()), "history": history, "trainable_parameters": sum(parameter.numel() for parameter in head.parameters()), "primary_groups": len(data["primary"]), "triplets": len(data["triplets"]), "auxiliary_events": 5000, "existing_invariance_pairs": len(data["existing_pairs"]), "evaluation_access": False, "phoenix_access": False, "wall_seconds": time.perf_counter() - start_all}
    write_json(report_path, report)
    return report


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    contract, probe, trainer = verify_bindings()
    data = load_training_data(probe)
    results = []
    for seed_index, seed in enumerate(SEEDS):
        initialize_seed(seed)
        template = probe.CompatibilityHead(data["cache"]["hidden_dim"], "mlp", 128).to(device)
        template_state = copy.deepcopy(template.state_dict())
        paired_digest = score_digest(template_state)
        for arm in SCHEDULE[seed_index]:
            report = train_arm(data, probe, trainer, contract, seed_index, arm, template_state, device)
            require(report["initial_head_sha256"] == paired_digest, f"paired initialization mismatch: {seed}/{arm}")
            results.append({"seed": seed, "arm": arm, "status": report["status"], "terminal_head_sha256": report["terminal_head_sha256"]})
    write_json(RUN / "reports/training-execution-summary.json", {"status": "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "protocol": contract["protocol"], "contract_sha256": sha256_file(CONTRACT), "runs": results, "run_count": len(results), "checkpoint_count": len(results) * 3, "evaluation_access": False, "phoenix_access": False})
    print(json.dumps({"status": "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "runs": len(results), "summary": str(RUN / "reports/training-execution-summary.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
