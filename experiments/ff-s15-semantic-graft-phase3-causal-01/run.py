"""One complete causal P3-BALANCED arm, using frozen P2 artifacts only as comparator."""
from __future__ import annotations

import json
import math
import shutil
import time
from datetime import datetime, timezone
from p3_contract import (OUTPUT, P2_OUTPUT, PHASE1_OUTPUT, SUBSTRATE, ARM, NVME,
                         default_config, pad_candidates, state_hash, sha_file, write_json,
                         supervision_abi, verify_prior, freeze, verify_spec)
import numpy as np
import torch
from audit import build_registry, candidate_audit
from p3_objective import objective
from p3_evaluate import selection_metric, enrich_metrics, pair_correctness
from p2_evaluate import state_statistics, pair_summary
from graft.dataset import PackedBank, assert_disjoint
from graft.model import model_for_substrate, forward_batch
from graft.evaluate import predictions, runtime_envelopes
from reporting import per_target, endpoint_metrics, complete_report


def cpu_tree(value):
    if torch.is_tensor(value): return value.detach().cpu().clone()
    if isinstance(value, dict): return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, list): return [cpu_tree(v) for v in value]
    return value


def save_checkpoint(path, model, opt, epoch, selection, spec):
    temp = path.with_suffix(".tmp")
    torch.save({"state_dict": cpu_tree(model.state_dict()), "optimizer_state": cpu_tree(opt.state_dict()),
        "fabric_config": model.config, "arm": ARM, "epoch": epoch, "DEV_selection": selection,
        "phase3_spec_sha256": sha_file(OUTPUT / "PHASE3-SPEC.json"),
        "supervision_abi": supervision_abi(), "representation_id": spec["representation_id"],
        "initial_state_sha256": spec["initial_state_sha256"], "frozen_backbone": True}, temp)
    temp.replace(path)


def main():
    if (OUTPUT / "PHASE3-SPEC.json").exists():
        raise ValueError("Frozen/completed identity exists; never overwrite")
    started = time.perf_counter()
    _, old_spec = verify_prior()
    torch.set_num_threads(4)
    torch.manual_seed(old_spec["seed"]); torch.cuda.manual_seed_all(old_spec["seed"])
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False; torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(False); torch.backends.cuda.enable_mem_efficient_sdp(False)
    if not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
    cfg = default_config(); device = "cuda:0"
    train = PackedBank(NVME / "data" / "TRAIN", SUBSTRATE, cfg)
    dev = PackedBank(NVME / "data" / "DEV", SUBSTRATE, cfg)
    assert_disjoint(train, dev)
    if len(train) != 20000 or len(dev) != 2000: raise ValueError("Population changed")
    if train.representation_id != old_spec["representation_id"] or dev.representation_id != train.representation_id:
        raise ValueError("Frozen representation identity differs")
    registry = build_registry(train, dev)
    candidates = candidate_audit(train, dev)
    spec = freeze(registry, candidates)
    initial = torch.load(P2_OUTPUT / "PHASE0-INITIALIZATION.pt", map_location="cpu", weights_only=True)
    reference = torch.tensor(np.load(P2_OUTPUT / "TRAIN-untrained-sigma.npy"), device=device)
    root = OUTPUT / ARM; root.mkdir(exist_ok=False)
    checkpoints = root / "checkpoints"; checkpoints.mkdir()
    # Same construction and RNG state as P2-CONSIST: seed reset, construct, then load initial.
    torch.manual_seed(spec["seed"]); torch.cuda.manual_seed_all(spec["seed"])
    model = model_for_substrate(cfg, SUBSTRATE).to(device)
    model.load_state_dict(initial["state_dict"])
    if state_hash(model) != spec["initial_state_sha256"]: raise ValueError("Initialization mismatch")
    tc = spec["training"]; prevalence = spec["TRAIN_prevalence"]
    opt = torch.optim.AdamW(model.parameters(), lr=tc["lr"], weight_decay=tc["weight_decay"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=tc["max_epochs"], eta_min=tc["minimum_lr"])
    rng = np.random.default_rng(spec["seed"]); prng = np.random.default_rng(spec["seed"] + 1)
    pairs = train.extras["renderer_pairs"]
    history = []; best = math.inf; best_epoch = 0; steps = 0
    torch.cuda.reset_peak_memory_stats()
    print(json.dumps({"status": "P3_FROZEN_TRAINING_STARTED", "spec_sha256": sha_file(OUTPUT / "PHASE3-SPEC.json"),
                      "TRAIN_prevalence": prevalence}), flush=True)
    for epoch in range(1, tc["max_epochs"] + 1):
        epoch_start = time.perf_counter(); model.train(); order = rng.permutation(len(train))
        parts = {}; batches = 0; lr = opt.param_groups[0]["lr"]
        for position in range(0, len(order), tc["batch_size"]):
            b = pad_candidates(train.batch(order[position:position + tc["batch_size"]], device))
            chosen = pairs[prng.choice(len(pairs), tc["renderer_pairs_per_batch"], replace=False)]
            l, r = (pad_candidates(train.batch(chosen[:, i], device)) for i in (0, 1))
            renderer = (forward_batch(model, l), forward_batch(model, r), l, r)
            loss, detail = objective(forward_batch(model, b), b, reference, prevalence, renderer)
            if not torch.isfinite(loss): raise ValueError("Nonfinite training loss")
            opt.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), tc["gradient_clip"], error_if_nonfinite=True)
            opt.step(); steps += 1; batches += 1
            for k, v in detail.items(): parts[k] = parts.get(k, 0.) + v
        scheduler.step()
        selection = selection_metric(model, dev, device, prevalence)
        rows = predictions(model, dev, device, 128)
        target = enrich_metrics(per_target(rows), registry)
        endpoint = endpoint_metrics(rows); diversity = state_statistics(model, dev, device)
        checkpoint = checkpoints / f"epoch-{epoch:03d}.pt"
        save_checkpoint(checkpoint, model, opt, epoch, selection, spec)
        if selection["J_select"] < best: best, best_epoch = selection["J_select"], epoch
        record = {"epoch": epoch, "lr": lr, "rows_seen": len(train), "optimizer_steps_total": steps,
            "training_mean_batch_components": {k: v / batches for k, v in parts.items()},
            "DEV_selection": selection, "DEV_targets": target, "DEV_endpoint": endpoint,
            "DEV_state_diversity": diversity, "checkpoint_sha256": sha_file(checkpoint),
            "best_epoch_so_far": best_epoch, "seconds": time.perf_counter() - epoch_start}
        history.append(record); write_json(root / "training-history.json", history)
        print(json.dumps({"epoch": epoch, "J_select": selection["J_select"], "best_epoch": best_epoch,
                          "action_accuracy": endpoint["accuracy"], "MOVE": endpoint["by_target_action_type"].get("MOVE"),
                          "D_s": diversity["D_s"], "seconds": record["seconds"]}), flush=True)
    artifact = root / "best-graft.pt"
    shutil.copyfile(checkpoints / f"epoch-{best_epoch:03d}.pt", artifact)
    model.load_state_dict(torch.load(artifact, map_location=device, weights_only=True)["state_dict"])
    prior = json.loads((PHASE1_OUTPUT / "TRAIN-trivial-baselines.json").read_text())
    report, rows = complete_report(model, dev, device, prior)
    enrich_metrics(report, registry)
    report["global_state_diversity"] = state_statistics(model, dev, device)
    report["TRAIN_global_state_diversity"] = state_statistics(model, train, device)
    report["renderer_JS"] = pair_summary(model, dev, device)
    report["balanced_DEV_selection"] = selection_metric(model, dev, device, prevalence)
    report["pair_correctness"] = pair_correctness(rows, dev.extras["renderer_pairs"])
    write_json(root / "DEV-METRICS.json", report)
    write_json(root / "PAIR-CORRECTNESS.json", report["pair_correctness"])
    digest = sha_file(artifact)
    with (root / "DEV-estimates.jsonl").open("x", encoding="utf-8") as stream:
        for row in runtime_envelopes(rows, digest, train.representation_id, supervision_abi()):
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    clone = model_for_substrate(cfg, SUBSTRATE).to(device)
    clone.load_state_dict(torch.load(artifact, map_location=device, weights_only=True)["state_dict"])
    model.eval(); clone.eval(); b = pad_candidates(dev.batch(np.arange(8), device))
    with torch.no_grad():
        a, c = forward_batch(model, b), forward_batch(clone, b)
        if not all(torch.equal(a[k], c[k]) for k in a): raise ValueError("Checkpoint replay differs")
    arm_receipt = {"arm": ARM, "best_epoch": best_epoch, "epochs": len(history), "optimizer_steps": steps,
        "full_TRAIN_passes": len(history), "initial_state_sha256": spec["initial_state_sha256"],
        "artifact_sha256": digest, "learned_state_sha256": state_hash(model), "DEV_selection": best,
        "trainable_parameters": sum(p.numel() for p in model.parameters()),
        "peak_GPU_allocated_bytes": torch.cuda.max_memory_allocated(), "backbone_optimizer_steps": 0,
        "deterministic_checkpoint_replay": True}
    write_json(root / "ARM-RECEIPT.json", arm_receipt)
    # Frozen comparator inference, no optimizer and no new model selection.
    clone.load_state_dict(torch.load(P2_OUTPUT / "P2-CONSIST" / "best-graft.pt", map_location=device, weights_only=True)["state_dict"])
    old_rows = predictions(clone, dev, device, 128)
    old_pairs = pair_correctness(old_rows, dev.extras["renderer_pairs"])
    write_json(OUTPUT / "P2-CONSIST-PAIR-CORRECTNESS.json", old_pairs)
    old_report = json.loads((P2_OUTPUT / "P2-CONSIST" / "DEV-METRICS.json").read_text())
    # Check unchanged comparator predictions reproduce frozen target/endpoint scores.
    replay_targets = per_target(old_rows)
    for scope in ("global", "candidate"):
        for name, metric in replay_targets[scope].items():
            key = "mae" if "mae" in metric else "accuracy"
            if metric.get("available") and metric[key] != old_report[scope][name][key]:
                raise ValueError("Comparator score replay differs: " + name)
    if endpoint_metrics(old_rows) != old_report["endpoint"]: raise ValueError("Comparator endpoint replay differs")
    from compare import make_comparison
    comparison = make_comparison(old_report, report, old_pairs, registry, arm_receipt)
    write_json(OUTPUT / "COMPARISON.json", comparison)
    verify_spec(spec)
    receipt = {"status": "CAUSAL_PHASE3_COMPLETE", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "substrate": SUBSTRATE, "arm": arm_receipt, "phase3_spec_sha256": sha_file(OUTPUT / "PHASE3-SPEC.json"),
        "architecture_sha256": spec["architecture_sha256"], "representation_id": spec["representation_id"],
        "latent_dimensions": spec["latent_dimensions"], "candidate_convention": spec["candidate_convention"],
        "TRAIN": len(train), "DEV": len(dev), "total_seconds": time.perf_counter() - started,
        "torch_version": str(torch.__version__), "device": torch.cuda.get_device_name(0),
        "sourceability_caveat": registry["identity_audit"],
        "exit_gate": {k: k not in ("PROTECTED_TEST_TRUTH_OPENED", "BANK_V2_USED") for k in (
            "TARGET_SOURCE_REGISTRY_COMPLETE", "CANONICAL_SOURCE_ALIASES_RECORDED", "CANDIDATE_UNIVERSE_EXHAUSTIVE",
            "BALANCED_TRAIN_WEIGHTS_TRAIN_ONLY", "P3_BALANCED_RUN_COMPLETE", "BALANCED_SELECTION_RULE_FROZEN",
            "ALL_AVAILABLE_TARGETS_SCORED", "PAIR_CORRECTNESS_DECOMPOSITION_DONE", "PHASE2_ARCHITECTURE_UNCHANGED",
            "PROTECTED_TEST_TRUTH_OPENED", "BANK_V2_USED", "PHASE3_RECEIPT_COMPLETE")},
        "files": {str(p.relative_to(OUTPUT)): sha_file(p) for p in sorted(OUTPUT.rglob("*")) if p.is_file()},
        "scope": "Causal-only objective repair; unresolved targets remain masked; no cross-lane source-equivalence or qualification claim"}
    write_json(OUTPUT / "PHASE3-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "best_epoch": best_epoch, "seconds": receipt["total_seconds"]}), flush=True)


if __name__ == "__main__": main()
