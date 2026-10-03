"""Train and freeze one causal Phase 4A recurrent arm; earlier phase artifacts are read-only."""
from __future__ import annotations

import json
import math
import shutil
import time
from datetime import datetime, timezone

import numpy as np
import torch
from p4_contract import (ARM, NVME, OUTPUT, P2_OUTPUT, PHASE1_OUTPUT, P2_SEED,
                         P3_REFERENCE, SUBSTRATE, default_config, pad_candidates,
                         sha_file, write_json, supervision_abi, verify_inherited,
                         freeze, verify_spec)
import p3_contract as p3
from recurrent import RecurrentCausalGraft, DepthView
from p4_objective import recurrent_objective
from p4_evaluate import motion_diagnostics, inference_latency
from p4_candidate_audit import audit_candidates
from graft.dataset import PackedBank, assert_disjoint
from graft.model import model_for_substrate, forward_batch
from graft.evaluate import predictions, runtime_envelopes
from p2_evaluate import exact_objective, state_statistics
from p3_evaluate import pair_correctness
from reporting import complete_report, endpoint_metrics
from p4_handoff import make_handoff


def cpu_tree(value):
    if torch.is_tensor(value): return value.detach().cpu().clone()
    if isinstance(value, dict): return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, list): return [cpu_tree(v) for v in value]
    return value


def save_checkpoint(path, model, optimizer, epoch, dev_selection, spec_sha):
    temp = path.with_suffix(".tmp")
    torch.save({"state_dict": cpu_tree(model.state_dict()),
        "optimizer_state": cpu_tree(optimizer.state_dict()), "arm": ARM, "epoch": epoch,
        "DEV_final_P2_objective": dev_selection,
        "phase4a_spec_sha256": spec_sha, "T": 4,
        "frozen_backbone": True, "frozen_seed_graft": True}, temp)
    temp.replace(path)


def make_spec(train, dev, audit, seed_model, seed_hash, reference_std):
    p2receipt, p2spec, p3receipt = verify_inherited()
    seed = p2receipt["arms"]["P2-CONSIST"]
    frozen_training = p2spec["training"]
    return {
        "schema": "frozen-fabrique.semantic-graft-phase4a-causal/v1", "arm": ARM,
        "question": "Does shared-weight latent refinement improve the causal P2-CONSIST state/action computation?",
        "substrate": SUBSTRATE, "representation_id": train.representation_id,
        "primary_seed": {"phase": "P2-CONSIST", "artifact": str(P2_SEED),
                         "artifact_sha256": sha_file(P2_SEED), "learned_state_sha256": seed["learned_state_sha256"],
                         "frozen": True},
        "preserved_reference": {"phase": "P3-BALANCED", "artifact": str(P3_REFERENCE),
                                "artifact_sha256": sha_file(P3_REFERENCE), "frozen": True,
                                "merged": False},
        "phase0_lock_sha256": p2spec["phase0_lock_sha256"],
        "phase1_receipt_sha256": p2spec["phase1_receipt_sha256"],
        "phase2_receipt_sha256": sha_file(P2_OUTPUT / "PHASE2-RECEIPT.json"),
        "phase3_receipt_sha256": sha_file(p3.OUTPUT / "PHASE3-RECEIPT.json"),
        "architecture_sha256": p2spec["architecture_sha256"],
        "surface": p2spec["surface"], "latent_dimensions": {"s": 64, "e": 64},
        "candidate_convention": {"m_max": 28, "retain_every_canonical_candidate": True,
            "ordering": "unchanged Phase 0 canonical identity and binding ordinal",
            "padding": "masked global token is always valid; padded candidate state zeroed at every recurrent step"},
        "state_sequence": "Z0=[s0;e1,0..em,0], then one shared R_phi applied exactly four times",
        "recurrent_architecture": {"shared_across_steps": True, "state_width": 64,
            "self_attention_heads": 4, "self_attention_mask": "global token plus valid candidates; padded keys masked",
            "cross_attention_memory": "single cached causal H row, standardized with frozen P2 TRAIN input_mean/std",
            "cross_attention_kdim_vdim": 2048, "ffn_width": 256,
            "update": "Z + FFN(LN(Z + SelfAttn(LN(Z),M) + CrossAttn(LN(Z+U),H)))",
            "iterations": 4, "stochastic_transitions": False, "adaptive_halting": False},
        "trainable": {"parameters": sum(p.numel() for p in seed_model.parameters() if p.requires_grad),
            "groups": ["shared recurrent block", "global recurrent output projection", "candidate recurrent output projection"],
            "inherited_graft_parameters_updated": 0, "typed_readout_heads_updated": 0,
            "backbone_updated": 0},
        "target_contract": supervision_abi(), "objective": {
            "base": "frozen P2-CONSIST objective, including its pair consistency and variance terms; CF dormant",
            "deep_supervision": "L(Z4) + 0.25 * mean(L(Z1),L(Z2),L(Z3)); Z0 has no recurrent loss",
            "raw_latent_renderer_loss": "retired", "intermediate_coefficient": 0.25},
        "training": {"epochs": 20, "TRAIN_rows": len(train), "DEV_rows": len(dev),
            "batch_size": frozen_training["batch_size"], "optimizer": frozen_training["optimizer"],
            "learning_rate": frozen_training["lr"], "minimum_lr": frozen_training["minimum_lr"],
            "weight_decay": frozen_training["weight_decay"], "schedule": frozen_training["schedule"],
            "gradient_clip": frozen_training["gradient_clip"], "seed": p2spec["seed"],
            "TRAIN_order": "same deterministic seed/order contract as P2-CONSIST",
            "renderer_pairs_per_batch": frozen_training["renderer_pairs_per_batch"],
            "checkpoint_selection": "lowest exact DEV P2-CONSIST objective on Z4; earliest epoch on ties",
            "reference_variance_sha256": sha_file(P2_OUTPUT / "TRAIN-untrained-sigma.npy"),
            "reference_std_train_only": True},
        "preflight": {"candidate_audit": audit, "inherited_seed_state_sha256": seed_hash,
                      "P2_reference_std_sha256": sha_file(P2_OUTPUT / "TRAIN-untrained-sigma.npy"),
                      "Phase1_candidate_cap_truncated": False,
                      "protected_TEST_truth_opened": False, "BANK_v2_used": False},
        "target_meanings": "exact causal Phase 2 availability/definitions; no cross-lane reconciliation",
        "no_new_surfaces_or_labels": True, "no_backbone_or_inherited_graft_tuning": True,
    }


def main():
    if (OUTPUT / "PHASE4A-SPEC.json").exists():
        raise ValueError("Phase 4A identity exists; do not overwrite")
    started = time.perf_counter()
    verify_inherited()
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    if not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
    device = "cuda:0"; cfg = default_config()
    train = PackedBank(NVME / "data" / "TRAIN", SUBSTRATE, cfg)
    dev = PackedBank(NVME / "data" / "DEV", SUBSTRATE, cfg)
    assert_disjoint(train, dev)
    if len(train) != 20000 or len(dev) != 2000: raise ValueError("Frozen canonical split changed")
    if train.representation_id != dev.representation_id: raise ValueError("TRAIN/DEV representation mismatch")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    candidate = audit_candidates(train, dev)
    if candidate["maximum"] != 28 or candidate["truncated_candidates"] != 0:
        raise ValueError("Phase 4A requires the full 28-candidate canonical universe")
    p2checkpoint = torch.load(P2_SEED, map_location="cpu", weights_only=True)
    p2spec = json.loads((P2_OUTPUT / "PHASE2-SPEC.json").read_text())
    p2receipt, _p2spec, _p3receipt = verify_inherited()
    torch.manual_seed(p2spec["seed"]); torch.cuda.manual_seed_all(p2spec["seed"])
    seed = model_for_substrate(cfg, SUBSTRATE).to(device)
    seed.load_state_dict(p2checkpoint["state_dict"])
    seed.eval(); seed_hash = p3.state_hash(seed)
    if seed_hash != p2receipt["arms"]["P2-CONSIST"]["learned_state_sha256"]:
        raise ValueError("Reconstructed frozen P2-CONSIST seed differs")
    reference_std = torch.tensor(np.load(P2_OUTPUT / "TRAIN-untrained-sigma.npy"),
                                 device=device, dtype=torch.float32)
    model = RecurrentCausalGraft(seed).to(device)
    parameters = [p for p in model.parameters() if p.requires_grad]
    if len(parameters) == 0 or any(p.requires_grad for p in model.seed.parameters()):
        raise ValueError("Only the recurrent organ/output projections may train")
    # Untrained-forward contract: R0 reproduces the seed and every recurrent state is finite.
    sample = pad_candidates(train.batch(np.arange(2), device))
    with torch.no_grad():
        baseline = forward_batch(seed, sample)
        levels, states = model.forward_states(sample)
        if not all(torch.equal(baseline[k], levels[0][k]) for k in baseline):
            raise ValueError("R0 does not exactly reproduce inherited P2-CONSIST outputs")
        if len(levels) != 5 or not all(torch.isfinite(x).all() for out in levels
                                       for x in out.values() if torch.is_tensor(x)):
            raise ValueError("Untrained T=4 forward is invalid")
        if torch.count_nonzero(states[-1][:, 1:][~sample["candidate_mask"]]).item():
            raise ValueError("Padded recurrent candidate state was not zeroed")
    del levels, states, sample, baseline
    torch.cuda.empty_cache()
    seed_hash_before = p3.state_hash(seed)
    audit = {**candidate, "R0_exactly_matches_P2": True, "T4_untrained_forward_finite": True,
             "padded_states_zero": True, "frozen_seed_state_sha256": seed_hash_before}
    spec = make_spec(train, dev, audit, model, seed_hash_before, reference_std)
    freeze(spec)
    spec_sha = sha_file(OUTPUT / "PHASE4A-SPEC.json")
    root = OUTPUT / ARM; root.mkdir()
    checkpoints = root / "checkpoints"; checkpoints.mkdir()
    training = p2spec["training"]
    optimizer = torch.optim.AdamW(parameters, lr=training["lr"], weight_decay=training["weight_decay"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=20,
                                                           eta_min=training["minimum_lr"])
    order_rng = np.random.default_rng(p2spec["seed"])
    pair_rng = np.random.default_rng(p2spec["seed"] + 1)
    pairs = train.extras["renderer_pairs"]
    history = []; steps = 0; best = math.inf; best_epoch = 0
    training_started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    print(json.dumps({"status": "PHASE4A_FROZEN_TRAINING_STARTED", "arm": ARM,
        "spec_sha256": spec_sha, "seed_sha256": seed_hash_before,
        "trainable_parameters": sum(p.numel() for p in parameters), "T": 4}), flush=True)
    for epoch in range(1, 21):
        epoch_start = time.perf_counter(); model.train(); order = order_rng.permutation(len(train))
        parts = {}; batches = 0; lr = optimizer.param_groups[0]["lr"]
        for position in range(0, len(order), training["batch_size"]):
            batch = pad_candidates(train.batch(order[position:position + training["batch_size"]], device))
            chosen = pairs[pair_rng.choice(len(pairs), training["renderer_pairs_per_batch"], replace=False)]
            left_batch, right_batch = (pad_candidates(train.batch(chosen[:, i], device)) for i in (0, 1))
            left_levels, _ = model.forward_states(left_batch)
            right_levels, _ = model.forward_states(right_batch)
            main_levels, _ = model.forward_states(batch)
            loss, detail = recurrent_objective(main_levels, batch, reference_std,
                (left_levels, right_levels, left_batch, right_batch))
            if not torch.isfinite(loss): raise ValueError("Nonfinite Phase 4A training loss")
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, training["gradient_clip"], error_if_nonfinite=True)
            optimizer.step(); steps += 1; batches += 1
            parts["L_final_Z4"] = parts.get("L_final_Z4", 0.) + detail["L_final_Z4"]
            parts["L_intermediate_mean_Z1_Z3"] = parts.get("L_intermediate_mean_Z1_Z3", 0.) + detail["L_intermediate_mean_Z1_Z3"]
            for depth, terms in detail["depth_terms"].items():
                for key, value in terms.items():
                    if key in ("S", "E", "A", "CF", "pair", "var"):
                        item = f"Z{depth}_{key}"; parts[item] = parts.get(item, 0.) + value
        scheduler.step()
        selector = exact_objective("P2-CONSIST", DepthView(model, 4), dev, device, reference_std)
        checkpoint = checkpoints / f"epoch-{epoch:03d}.pt"
        save_checkpoint(checkpoint, model, optimizer, epoch, selector["total"], spec_sha)
        if selector["total"] < best:
            best, best_epoch = selector["total"], epoch
        row = {"epoch": epoch, "lr": lr, "rows_seen": len(train), "optimizer_steps_total": steps,
            "mean_training_components_by_depth": {k: v / batches for k, v in parts.items()},
            "DEV_Z4_P2_objective": selector, "checkpoint_sha256": sha_file(checkpoint),
            "best_epoch_so_far": best_epoch, "seconds": time.perf_counter() - epoch_start}
        history.append(row); write_json(root / "training-history.json", history)
        print(json.dumps({"epoch": epoch, "DEV_Z4_objective": selector["total"],
            "best_epoch": best_epoch, "seconds": row["seconds"]}), flush=True)
        del main_levels, left_levels, right_levels
    training_seconds = time.perf_counter() - training_started
    training_peak_memory = torch.cuda.max_memory_allocated()
    selected = checkpoints / f"epoch-{best_epoch:03d}.pt"
    shutil.copyfile(selected, root / "best-recurrent.pt")
    best_state = torch.load(root / "best-recurrent.pt", map_location=device, weights_only=True)["state_dict"]
    model.load_state_dict(best_state); model.eval()
    if p3.state_hash(model.seed) != seed_hash_before:
        raise ValueError("Frozen inherited P2 graft changed during recurrent training")
    prior = json.loads((PHASE1_OUTPUT / "TRAIN-trivial-baselines.json").read_text())
    dev_reports = {}; all_rows = {}
    for depth in range(5):
        view = DepthView(model, depth)
        report, rows = complete_report(view, dev, device, prior)
        report["depth"] = depth
        report["global_state_diversity"] = state_statistics(view, dev, device)
        report["pair_correctness"] = pair_correctness(rows, dev.extras["renderer_pairs"]) if depth in (0, 4) else None
        dev_reports[str(depth)] = report; all_rows[str(depth)] = rows
        write_json(root / f"DEV-METRICS-depth-{depth}.json", report)
        if depth in (0, 4):
            digest = sha_file(P2_SEED) if depth == 0 else sha_file(root / "best-recurrent.pt")
            with (root / f"DEV-estimates-depth-{depth}.jsonl").open("x", encoding="utf-8") as stream:
                for envelope in runtime_envelopes(rows, digest, train.representation_id, supervision_abi()):
                    stream.write(json.dumps(envelope, sort_keys=True, allow_nan=False) + "\n")
    # The zero-depth replay is checked against the sealed Phase 2 report.
    p2_baseline = json.loads((P2_OUTPUT / "P2-CONSIST" / "DEV-METRICS.json").read_text())
    for scope in ("global", "candidate"):
        for name, metric in dev_reports["0"][scope].items():
            if metric.get("available") and metric.get("balanced_accuracy") != p2_baseline[scope][name].get("balanced_accuracy"):
                raise ValueError("R0 target metric does not replay Phase 2: " + name)
    if dev_reports["0"]["endpoint"] != p2_baseline["endpoint"]:
        raise ValueError("R0 endpoint report does not replay Phase 2")
    motion = motion_diagnostics(model, dev, device)
    timing = inference_latency(model, dev, device)
    summary = {"depths": {str(t): {"global": dev_reports[str(t)]["global"],
            "candidate": dev_reports[str(t)]["candidate"], "endpoint": dev_reports[str(t)]["endpoint"],
            "D_s": dev_reports[str(t)]["global_state_diversity"]["D_s"],
            "candidate_conditioning": dev_reports[str(t)]["candidate_conditioning"],
            "renderer_correctness": dev_reports[str(t)]["pair_correctness"]}
        for t in range(5)}, "update_magnitude": motion, "inference_latency": timing,
        "P2_R0_bitwise_seed_state_replay": True, "P2_R0_metric_replay": True}
    write_json(OUTPUT / "DEPTH-CURVE.json", summary)
    arm_receipt = {"status": "ARM_COMPLETE", "arm": ARM, "best_epoch": best_epoch,
        "epochs": 20, "full_TRAIN_passes": 20, "optimizer_steps": steps,
        "trainable_recurrent_parameters": sum(p.numel() for p in parameters),
        "frozen_backbone_optimizer_steps": 0, "frozen_seed_graft_optimizer_steps": 0,
        "P2_seed_state_sha256_before_after": seed_hash_before,
        "best_recurrent_artifact_sha256": sha_file(root / "best-recurrent.pt"),
        "DEV_Z4_P2_objective": best, "checkpoint_replay": True,
        "training_seconds": training_seconds,
        "peak_GPU_allocated_bytes": training_peak_memory,
        "depth_curve_sha256": sha_file(OUTPUT / "DEPTH-CURVE.json"),
        "motion_diagnostics_sha256": canon_hash(motion), "latency_diagnostics_sha256": canon_hash(timing)}
    write_json(root / "ARM-RECEIPT.json", arm_receipt)
    handoff = make_handoff(OUTPUT, dev_reports, summary, arm_receipt)
    verify_spec(json.loads((OUTPUT / "PHASE4A-SPEC.json").read_text()))
    receipt = {"status": "CAUSAL_PHASE4A_COMPLETE", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "substrate": SUBSTRATE, "arm": arm_receipt,
        "phase4a_spec_sha256": spec_sha, "architecture_sha256": p2spec["architecture_sha256"],
        "representation_id": train.representation_id, "candidate_convention": spec["candidate_convention"],
        "TRAIN": len(train), "DEV": len(dev), "depths_scored": [0, 1, 2, 3, 4],
        "depth_curve": summary, "total_seconds": time.perf_counter() - started,
        "interpretation": handoff["disposition"],
        "torch_version": str(torch.__version__), "device": torch.cuda.get_device_name(0),
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "no_new_supervision_or_ontology_changes": True,
        "files": {str(p.relative_to(OUTPUT)): sha_file(p) for p in sorted(OUTPUT.rglob("*")) if p.is_file()},
        "scope": "Causal Phase 4A only; one T=4 shared recurrent arm, no causal/encoder winner"}
    write_json(OUTPUT / "PHASE4A-RECEIPT.json", receipt)
    seal = {"status": "PHASE4A_OUTPUTS_SEALED", "receipt_sha256": sha_file(OUTPUT / "PHASE4A-RECEIPT.json"),
        "bindings": {str(p.relative_to(OUTPUT)): sha_file(p) for p in sorted(OUTPUT.rglob("*"))
                     if p.is_file() and p.name != "FINAL-SEAL.json"}}
    write_json(OUTPUT / "FINAL-SEAL.json", seal)
    print(json.dumps({"status": receipt["status"], "best_epoch": best_epoch,
                      "trainable_recurrent_parameters": arm_receipt["trainable_recurrent_parameters"],
                      "seconds": receipt["total_seconds"]}), flush=True)


if __name__ == "__main__": main()
