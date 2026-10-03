"""Versioned receipt-only repair for the completed causal Phase 4A run.

The frozen run finished training and DEV evaluation, then hit a missing hash-helper
import while assembling receipts. This script preserves all fitted bytes and only
completes the absent packaging artifacts; it never steps the optimizer.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from p4_contract import (ARM, OUTPUT, NVME, P2_OUTPUT, PHASE1_OUTPUT, P2_SEED,
                         P3_REFERENCE, SUBSTRATE, default_config, pad_candidates,
                         sha_file, write_json, supervision_abi, verify_inherited,
                         verify_spec, state_hash, canon_hash)
from p4_handoff import make_handoff
from recurrent import RecurrentCausalGraft
from p4_objective import recurrent_objective
from graft.dataset import PackedBank
from graft.model import model_for_substrate


def memory_replay(train, spec, best_checkpoint):
    """Measure a representative saved-optimizer training-step peak without updating weights."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable for the declared training-step memory replay")
    device = "cuda:0"
    cfg = default_config()
    seed_ckpt = torch.load(P2_SEED, map_location="cpu", weights_only=True)
    seed = model_for_substrate(cfg, SUBSTRATE).to(device)
    seed.load_state_dict(seed_ckpt["state_dict"])
    model = RecurrentCausalGraft(seed).to(device)
    checkpoint = torch.load(best_checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    training = spec["training"]
    optimizer = torch.optim.AdamW(params, lr=training["learning_rate"],
                                  weight_decay=training["weight_decay"])
    optimizer.load_state_dict(checkpoint["optimizer_state"])

    seed_value = int(training["seed"])
    order = np.random.default_rng(seed_value).permutation(len(train))
    pair_rng = np.random.default_rng(seed_value + 1)
    batch_size = int(training["batch_size"])
    main = pad_candidates(train.batch(order[:batch_size], device))
    pairs = train.extras["renderer_pairs"]
    chosen = pairs[pair_rng.choice(len(pairs), int(training["renderer_pairs_per_batch"]), replace=False)]
    left, right = (pad_candidates(train.batch(chosen[:, i], device)) for i in (0, 1))
    reference_std = torch.tensor(np.load(P2_OUTPUT / "TRAIN-untrained-sigma.npy"),
                                 device=device, dtype=torch.float32)
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.synchronize(device)
    torch.cuda.reset_peak_memory_stats(device)
    left_levels, _ = model.forward_states(left)
    right_levels, _ = model.forward_states(right)
    main_levels, _ = model.forward_states(main)
    loss, _ = recurrent_objective(main_levels, main, reference_std,
                                  (left_levels, right_levels, left, right))
    if not torch.isfinite(loss):
        raise ValueError("Memory replay produced a nonfinite objective")
    loss.backward()
    torch.cuda.synchronize(device)
    peak = int(torch.cuda.max_memory_allocated(device))
    return {"peak_GPU_allocated_bytes": peak,
            "basis": "representative Phase 4A forward/backward replay at selected checkpoint with its saved AdamW state; no optimizer step",
            "batch_rows": len(main["H"]), "renderer_pair_count": len(chosen),
            "optimizer_state_restored": True, "optimizer_step_performed": False,
            "loss_finite": True}


def main():
    if (OUTPUT / "PHASE4A-RECEIPT.json").exists() or (OUTPUT / "FINAL-SEAL.json").exists():
        raise ValueError("Final receipt already exists; preserve this output identity")
    start = time.perf_counter()
    spec = json.loads((OUTPUT / "PHASE4A-SPEC.json").read_text())
    verify_spec(spec)
    p2receipt, p2spec, _p3receipt = verify_inherited()
    require_seed = p2receipt["arms"]["P2-CONSIST"]["learned_state_sha256"]
    if sha_file(P2_SEED) != spec["primary_seed"]["artifact_sha256"]:
        raise ValueError("P2-CONSIST seed artifact changed")
    if sha_file(P3_REFERENCE) != spec["preserved_reference"]["artifact_sha256"]:
        raise ValueError("P3-BALANCED reference artifact changed")
    candidate = json.loads((OUTPUT / "CANDIDATE-AUDIT.json").read_text())
    if candidate["maximum"] != 28 or candidate["truncated_candidates"] != 0:
        raise ValueError("Saved candidate audit does not satisfy the frozen exhaustive contract")

    history_path = OUTPUT / ARM / "training-history.json"
    history = json.loads(history_path.read_text())
    if len(history) != 20 or [row["epoch"] for row in history] != list(range(1, 21)):
        raise ValueError("Saved training history is incomplete")
    best_row = min(history, key=lambda row: (row["DEV_Z4_P2_objective"]["total"], row["epoch"]))
    best_epoch = int(best_row["epoch"])
    best_path = OUTPUT / ARM / "best-recurrent.pt"
    expected_best_path = OUTPUT / ARM / "checkpoints" / f"epoch-{best_epoch:03d}.pt"
    best_sha = sha_file(best_path)
    if best_sha != sha_file(expected_best_path) or best_sha != best_row["checkpoint_sha256"]:
        raise ValueError("Selected checkpoint is not the frozen minimum-DEV checkpoint")

    curve_path = OUTPUT / "DEPTH-CURVE.json"
    curve = json.loads(curve_path.read_text())
    if set(curve["depths"]) != {"0", "1", "2", "3", "4"}:
        raise ValueError("Saved depth curve is incomplete")
    for depth in range(5):
        metrics_path = OUTPUT / ARM / f"DEV-METRICS-depth-{depth}.json"
        estimates_path = OUTPUT / ARM / f"DEV-estimates-depth-{depth}.jsonl"
        if not metrics_path.is_file():
            raise ValueError(f"Missing saved depth metrics: Z{depth}")
        if depth in (0, 4) and not estimates_path.is_file():
            raise ValueError(f"Missing runtime estimate envelopes: Z{depth}")
    if not curve.get("P2_R0_bitwise_seed_state_replay") or not curve.get("P2_R0_metric_replay"):
        raise ValueError("Saved R0 replay flags do not pass")

    train = PackedBank(NVME / "data" / "TRAIN", SUBSTRATE, default_config())
    memory = memory_replay(train, spec, best_path)
    epoch_seconds = float(sum(float(row["seconds"]) for row in history))
    optimizer_steps = int(history[-1]["optimizer_steps_total"])
    model = torch.load(best_path, map_location="cpu", weights_only=True)
    from recurrent import RecurrentCausalGraft
    seed_model = model_for_substrate(default_config(), SUBSTRATE)
    seed_model.load_state_dict(torch.load(P2_SEED, map_location="cpu", weights_only=True)["state_dict"])
    wrapper = RecurrentCausalGraft(seed_model)
    wrapper.load_state_dict(model["state_dict"])
    if state_hash(wrapper.seed) != require_seed:
        raise ValueError("Saved recurrent artifact changed its inherited P2 seed")

    arm_receipt = {"status": "ARM_COMPLETE", "arm": ARM, "best_epoch": best_epoch,
        "epochs": 20, "full_TRAIN_passes": 20, "optimizer_steps": optimizer_steps,
        "trainable_recurrent_parameters": int(spec["trainable"]["parameters"]),
        "frozen_backbone_optimizer_steps": 0, "frozen_seed_graft_optimizer_steps": 0,
        "P2_seed_state_sha256_before_after": require_seed,
        "best_recurrent_artifact_sha256": best_sha,
        "DEV_Z4_P2_objective": float(best_row["DEV_Z4_P2_objective"]["total"]),
        "checkpoint_replay": True,
        "training_seconds": epoch_seconds,
        "training_time_measurement_basis": "sum of the 20 saved per-epoch elapsed durations; small per-epoch history-write/console overhead is excluded",
        "peak_GPU_allocated_bytes": memory["peak_GPU_allocated_bytes"],
        "peak_GPU_measurement_basis": memory["basis"],
        "memory_replay": memory,
        "depth_curve_sha256": sha_file(curve_path),
        "motion_diagnostics_sha256": canon_hash(curve["update_magnitude"]),
        "latency_diagnostics_sha256": canon_hash(curve["inference_latency"]),
        "posttraining_receipt_repair": "Finalization only; no checkpoint or optimizer update was performed"}
    write_json(OUTPUT / ARM / "ARM-RECEIPT.json", arm_receipt)

    reports = {str(depth): json.loads((OUTPUT / ARM / f"DEV-METRICS-depth-{depth}.json").read_text())
               for depth in range(5)}
    handoff = make_handoff(OUTPUT, reports, curve, arm_receipt)
    handoff["training_time_measurement_basis"] = arm_receipt["training_time_measurement_basis"]
    handoff["peak_GPU_measurement_basis"] = memory["basis"]
    write_json(OUTPUT / "PHASE4A-HANDOFF.json", handoff)
    handoff_md = OUTPUT / "PHASE4A-HANDOFF.md"
    with handoff_md.open("a", encoding="utf-8") as stream:
        stream.write("\n**Memory measurement:** the figure above is a representative training-step replay at the selected checkpoint; the original run did not persist its CUDA high-water mark. No optimizer update was performed during the replay.\n")
        stream.write("\n**Training-time measurement:** the reported time is the sum of saved epoch durations; per-epoch history-write and console overhead is excluded.\n")

    repair = {"status": "POSTTRAIN_FINALIZATION_REPAIR_COMPLETE",
        "repair_id": "R4-CAUSAL-POSTTRAIN-FINALIZATION-v1",
        "repair_script": str(Path(__file__).resolve()),
        "repair_script_sha256": sha_file(Path(__file__).resolve()),
        "reason": "The completed training/evaluation process stopped at receipt construction because canon_hash was not imported.",
        "scientific_identity_changed": False, "training_repeated": False,
        "best_checkpoint_sha256": best_sha, "best_epoch": best_epoch,
        "optimizer_step_performed_during_repair": False,
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "repair_elapsed_seconds": time.perf_counter() - start}
    write_json(OUTPUT / "POSTTRAIN-REPAIR-RECEIPT.json", repair)

    verify_spec(spec)
    receipt = {"status": "CAUSAL_PHASE4A_COMPLETE", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "substrate": SUBSTRATE, "arm": arm_receipt,
        "phase4a_spec_sha256": sha_file(OUTPUT / "PHASE4A-SPEC.json"),
        "architecture_sha256": spec["architecture_sha256"],
        "representation_id": train.representation_id,
        "candidate_convention": spec["candidate_convention"],
        "TRAIN": 20000, "DEV": 2000, "depths_scored": [0, 1, 2, 3, 4],
        "depth_curve": curve, "total_seconds": epoch_seconds,
        "total_time_measurement_basis": arm_receipt["training_time_measurement_basis"],
        "interpretation": handoff["disposition"],
        "torch_version": str(torch.__version__), "device": torch.cuda.get_device_name(0),
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "no_new_supervision_or_ontology_changes": True,
        "receipt_repair": repair,
        "files": {str(path.relative_to(OUTPUT)): sha_file(path)
                  for path in sorted(OUTPUT.rglob("*")) if path.is_file()},
        "scope": "Causal Phase 4A only; one T=4 shared recurrent arm, no causal/encoder winner"}
    write_json(OUTPUT / "PHASE4A-RECEIPT.json", receipt)
    seal = {"status": "PHASE4A_OUTPUTS_SEALED",
        "receipt_sha256": sha_file(OUTPUT / "PHASE4A-RECEIPT.json"),
        "bindings": {str(path.relative_to(OUTPUT)): sha_file(path)
                     for path in sorted(OUTPUT.rglob("*"))
                     if path.is_file() and path.name != "FINAL-SEAL.json"}}
    write_json(OUTPUT / "FINAL-SEAL.json", seal)
    print(json.dumps({"status": receipt["status"], "repair": repair["repair_id"],
        "best_epoch": best_epoch, "epoch_seconds_sum": epoch_seconds,
        "peak_memory_replay_bytes": memory["peak_GPU_allocated_bytes"],
        "interpretation": handoff["disposition"]}, indent=2))


if __name__ == "__main__":
    main()
