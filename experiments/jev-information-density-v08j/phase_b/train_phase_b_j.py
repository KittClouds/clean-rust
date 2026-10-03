"""Four-arm objective-graph training for v0.8J, without evaluation access."""

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
import torch.nn.functional as F


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-b-v01")
PHASE_A_RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01")
PHASE_A_PARENT = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
CONTRACT_PATH = CODE / "phase-b-v01-contract.json"
AUTH_PATH = RUN / "preflight/model-contact-authorization.json"
FEATURES_PATH = RUN / "feature-cache/phase-b-train-features.pt"
FEATURE_RECEIPT_PATH = RUN / "feature-cache/extraction-receipt.json"
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("J00", "J10", "J01", "J11")
SCHEDULE = {
    0: ("J00", "J11", "J10", "J01"),
    1: ("J11", "J00", "J01", "J10"),
    2: ("J10", "J01", "J11", "J00"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode("utf-8"))
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_bindings() -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    contract = read_json(CONTRACT_PATH)
    contract_hash = sha256_file(CONTRACT_PATH)
    auth = read_json(AUTH_PATH)
    require(auth["status"] == "PASS" and auth["training_authorized"] is True, "training authorization absent")
    require(auth["contract_sha256"] == contract_hash, "contract changed after preflight")
    require(auth["objective_graph_sha256"] == contract["objective_graph_sha256"], "objective graph authorization drift")
    require(auth["source_code_sha256"]["train_phase_b_j.py"] == sha256_file(Path(__file__)), "trainer code drift after preflight")
    require(auth["source_code_sha256"]["probe.py"] == sha256_file(ROOT / "experiments/jev-frozen-readout-v01/probe.py"), "probe helper drift after preflight")
    require(auth["source_code_sha256"]["train_v05.py"] == sha256_file(ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"), "trainer helper drift after preflight")
    require(auth["source_code_sha256"]["extract_lfm.py"] == sha256_file(ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"), "LFM adapter drift after preflight")
    receipt = read_json(FEATURE_RECEIPT_PATH)
    require(receipt["status"] == "FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY", "training-only feature receipt absent")
    require(receipt["objective_graph_sha256"] == contract["objective_graph_sha256"], "feature graph binding drift")
    require(receipt["phase_a_identity"] == "phase-a-v01-clean", "feature Phase-A identity drift")
    require(receipt["evaluation_bodies_opened"] is False and receipt["phoenix_access"] is False, "feature boundary crossed")
    require(sha256_file(FEATURES_PATH) == receipt["feature_cache"]["sha256"], "feature cache hash drift")
    probe = load_module("jev_v08j_probe", ROOT / "experiments/jev-frozen-readout-v01/probe.py")
    trainer = load_module("jev_v08j_train_v05", ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py")
    return contract, auth, probe, trainer


def load_training_data(probe: Any, auth: dict[str, Any]) -> dict[str, Any]:
    cache = torch.load(FEATURES_PATH, map_location="cpu", weights_only=True)
    require(cache["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "feature revision drift")
    require(cache["hidden_dim"] == 2048 and cache["layer_count"] == 16 and cache["backbone_frozen"] is True, "feature identity drift")
    state = cache["features"]["state"][FEATURE_KEY]
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY]
    require(state.dtype == torch.float32 and candidates.dtype == torch.float32, "feature dtype drift")
    primary = read_jsonl(PHASE_A_PARENT / "materialized/F100-groups.jsonl")
    sham = read_jsonl(PHASE_A_RUN / "inputs/sham-views.jsonl")
    triplets = read_jsonl(PHASE_A_RUN / "inputs/triplets.jsonl")
    require(len(primary) == 100000 and len(sham) == 5000 and len(triplets) == 5000, "training input count drift")
    require(sha256_file(PHASE_A_PARENT / "materialized/F100-groups.jsonl") == auth["verified_primary_bank_sha256"], "F100 input drift after preflight")
    require(sha256_file(PHASE_A_RUN / "inputs/sham-views.jsonl") == auth["verified_sham_views_sha256"], "sham input drift after preflight")
    require(sha256_file(PHASE_A_RUN / "inputs/triplets.jsonl") == auth["verified_triplets_sha256"], "triplet input drift after preflight")
    primary.sort(key=lambda row: row["group_id"])
    by_primary = {row["group_id"]: row for row in primary}
    by_sham = {row["group_id"]: row for row in sham}
    require(len(by_primary) == 100000 and len(by_sham) == 5000, "training IDs are not unique")
    triplet_rows = []
    for item in triplets:
        anchor = by_primary.get(item["anchor_group_id"])
        fact = by_primary.get(item["fact_flip_group_id"])
        sham_row = by_sham.get(item["sham_group_id"])
        require(anchor is not None and fact is not None and sham_row is not None, f"triplet row missing: {item['anchor_id']}")
        triplet_rows.append({"meta": item, "anchor": anchor, "fact_flip": fact, "sham": sham_row})
    existing_pairs = probe.invariant_pairs(primary, "train")
    require(len(existing_pairs) == 4982, f"inherited invariance pair count changed: {len(existing_pairs)}")
    return {"cache": cache, "state": state, "candidates": candidates, "primary": primary, "triplets": triplet_rows, "existing_pairs": existing_pairs}


def triplet_edge_loss(logits: torch.Tensor, masks: list[torch.Tensor], count: int) -> torch.Tensor:
    if count == 0:
        return torch.zeros((), device=logits.device)
    losses = []
    for index in range(count):
        left = logits[2 * index][masks[2 * index]]
        right = logits[2 * index + 1][masks[2 * index + 1]]
        left_probability = F.softmax(left, dim=0)
        right_probability = F.softmax(right, dim=0)
        losses.append(F.kl_div(left_probability.log(), right_probability, reduction="batchmean"))
    return torch.stack(losses).mean()


def initialize_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train_arm(data: dict[str, Any], probe: Any, trainer: Any, contract: dict[str, Any],
              seed_index: int, arm: str, initial_state: dict[str, torch.Tensor], device: str) -> dict[str, Any]:
    seed = SEEDS[seed_index]
    run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "protocol": contract["protocol"], "seed": seed, "arm": arm,
        "objective_graph_sha256": contract["objective_graph_sha256"],
        "feature_cache_sha256": sha256_file(FEATURES_PATH),
        "head": "dynamic_mlp_compatibility", "projection_width": 128,
        "trainable_parameters": 590081, "loss": "existing_v08i_L3_plus_factorial_events",
        "brier_weight": 0.25, "existing_invariance_weight": 0.10, "new_edge_weight": 0.10,
        "existing_invariance_max_pairs_per_step": 16, "epochs": 3, "batch_size_groups": 256,
        "optimizer": "AdamW", "learning_rate": 0.002, "weight_decay": 0.01,
        "scheduler": "none", "gradient_clipping": "none", "primary_groups": 100000,
        "triplets": 5000, "paired_initialization": True, "evaluation_access": False,
    }
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
    primary = data["primary"]
    triplet_by_anchor = {row["anchor"]["group_id"]: row for row in data["triplets"]}
    flags = contract["arms"][arm]
    events = run_dir / "training-events.jsonl"
    history = []
    start_all = time.perf_counter()
    for epoch in range(3):
        shuffled = list(primary)
        random.Random(seed + epoch).shuffle(shuffled)
        head.train()
        totals: Counter[str] = Counter()
        step_count = 0
        for start in range(0, len(shuffled), 256):
            batch = shuffled[start : start + 256]
            state_batch, candidate_batch, gold, mask, kinds, sources = trainer.fast_tensor_batch(batch, state, candidates, PROFILE, device, reorder=True)
            active = [triplet_by_anchor[row["group_id"]] for row in batch if row["group_id"] in triplet_by_anchor]
            relation_items = []
            for item in active:
                relation_items.extend((item["anchor"], item["sham"]))
            if relation_items:
                rel_state, rel_candidate, rel_gold, rel_mask, rel_kinds, rel_sources = trainer.fast_tensor_batch(relation_items, state, candidates, PROFILE, device, reorder=False)
            else:
                rel_state = rel_candidate = rel_gold = rel_mask = rel_kinds = rel_sources = None
            optimizer.zero_grad(set_to_none=True)
            base_logits = head(state_batch, candidate_batch)
            base_loss, brier = trainer.v05_loss(base_logits, gold, mask, kinds, sources, 0.25)
            existing_loss = trainer.vectorized_invariant_loss(head, data["existing_pairs"], state, candidates, PROFILE, device)
            if relation_items:
                relation_logits = head(rel_state, rel_candidate)
                sham_count = len(active)
                sham_logits = relation_logits[1::2]
                sham_loss, _ = trainer.v05_loss(sham_logits, rel_gold[1::2], rel_mask[1::2], rel_kinds[1::2], rel_sources[1::2], 0.25)
                new_edge = triplet_edge_loss(relation_logits, [row for row in rel_mask], sham_count)
            else:
                sham_count = 0
                sham_loss = torch.zeros((), device=device)
                new_edge = torch.zeros((), device=device)
            base_count = len(batch)
            existing_count = min(16, len(data["existing_pairs"]))
            edge_weight = 0.10
            treatment_numerator = base_loss * base_count
            treatment_denominator = base_count
            if flags["sham_pointwise"]:
                treatment_numerator = treatment_numerator + sham_loss * sham_count
                treatment_denominator = treatment_denominator + sham_count
            if flags["anchor_sham_invariance"]:
                treatment_numerator = treatment_numerator + edge_weight * new_edge * sham_count
                treatment_denominator = treatment_denominator + edge_weight * sham_count
            loss = treatment_numerator / treatment_denominator + 0.10 * existing_loss
            loss.backward()
            gradients = [parameter.grad.detach().norm(2) for parameter in head.parameters() if parameter.grad is not None]
            grad_norm = float(torch.linalg.vector_norm(torch.stack(gradients), 2).detach().cpu()) if gradients else 0.0
            optimizer.step()
            count = len(batch)
            totals["count"] += count
            totals["loss"] += float(loss.detach().cpu()) * count
            totals["base_loss"] += float(base_loss.detach().cpu()) * count
            totals["existing_invariance"] += float(existing_loss.detach().cpu()) * count
            totals["sham_loss"] += float(sham_loss.detach().cpu()) * count
            totals["new_edge"] += float(new_edge.detach().cpu()) * count
            step_count += 1
            append_event(events, {"event": "training_step", "epoch": epoch + 1, "step": step_count, "steps_in_epoch": math.ceil(len(shuffled) / 256), "groups": count, "active_triplets": sham_count, "loss": float(loss.detach().cpu()), "base_loss": float(base_loss.detach().cpu()), "existing_invariance": float(existing_loss.detach().cpu()), "sham_loss": float(sham_loss.detach().cpu()), "new_edge": float(new_edge.detach().cpu()), "gradient_norm": grad_norm, "learning_rate": optimizer.param_groups[0]["lr"], "evaluation_access": False})
        summary = {key: totals[key] / max(1, totals["count"]) for key in ("loss", "base_loss", "existing_invariance", "sham_loss", "new_edge")}
        summary.update({"epoch": epoch + 1, "groups": int(totals["count"]), "optimizer_steps": step_count, "active_triplets_total": sum(1 for row in shuffled if row["group_id"] in triplet_by_anchor)})
        history.append(summary)
        torch.save({"head_state": head.state_dict(), "optimizer_state": optimizer.state_dict(), "initial_head_sha256": initial_sha, "config_sha256": config_hash, "epoch": epoch + 1}, run_dir / f"checkpoint-epoch-{epoch + 1}.pt")
    terminal_sha = score_digest(head.state_dict())
    report = {"status": "TRAINING_COMPLETE_NO_EVALUATION", "protocol": contract["protocol"], "arm": arm, "seed": seed, "config_sha256": config_hash, "initial_head_sha256": initial_sha, "terminal_head_sha256": terminal_sha, "history": history, "trainable_parameters": sum(parameter.numel() for parameter in head.parameters()), "primary_groups": len(primary), "triplets": len(data["triplets"]), "existing_invariance_pairs": len(data["existing_pairs"]), "existing_invariance_events_per_step": 16, "evaluation_access": False, "phoenix_access": False, "wall_seconds": time.perf_counter() - start_all}
    write_json(report_path, report)
    return report


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    contract, auth, probe, trainer = verify_bindings()
    data = load_training_data(probe, auth)
    results = []
    for seed_index, seed in enumerate(SEEDS):
        initialize_seed(seed)
        template = probe.CompatibilityHead(data["cache"]["hidden_dim"], "mlp", 128).to(device)
        template_state = copy.deepcopy(template.state_dict())
        paired_digest = score_digest(template_state)
        for arm in SCHEDULE[seed_index]:
            report = train_arm(data, probe, trainer, contract, seed_index, arm, template_state, device)
            require(report["initial_head_sha256"] == paired_digest, f"paired initialization mismatch: seed {seed}/{arm}")
            results.append({"seed": seed, "arm": arm, "status": report["status"], "terminal_head_sha256": report["terminal_head_sha256"]})
    write_json(RUN / "reports/training-execution-summary.json", {"status": "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "protocol": contract["protocol"], "contract_sha256": sha256_file(CONTRACT_PATH), "runs": results, "evaluation_access": False, "phoenix_access": False})
    print(json.dumps({"status": "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "runs": len(results), "summary": str(RUN / "reports/training-execution-summary.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
