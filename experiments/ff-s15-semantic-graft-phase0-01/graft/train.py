from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch

from .contracts import EXPERIMENT, NVME, SUBSTRATES, canon_hash, default_config, sha_file, supervision_abi, write_json
from .baseline import prior_model, prior_predictions
from .dataset import PackedBank, assert_disjoint, training_normalizer
from .evaluate import evaluate, metrics_for_rows, runtime_envelopes
from .model import SemanticEpistemicGraft, masked_loss


def verify_phase0_lock(lock_path: Path):
    lock = json.loads(lock_path.read_text())
    if lock["status"] != "PHASE0_READY_TO_BEGIN_TRAINING":
        raise ValueError("Phase0 readiness lock missing")
    for relative, digest in lock["package_files"].items():
        if sha_file(EXPERIMENT / relative) != digest:
            raise ValueError(f"frozen package changed: {relative}")
    for name, record in lock["data"].items():
        if sha_file(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"data manifest changed: {name}")
    return lock


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", choices=SUBSTRATES, required=True)
    ap.add_argument("--data", type=Path, default=NVME / "data")
    ap.add_argument("--out", type=Path, default=NVME / "training")
    ap.add_argument("--lock", type=Path, default=NVME / "PHASE0-LOCK.json")
    ap.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    ap.add_argument("--train", action="store_true", help="Enable optimizer steps; absent means preflight forward only")
    args = ap.parse_args()
    cfg = default_config()
    if args.out.resolve().drive.lower() != "c:":
        raise ValueError("training artifacts must be written on C: NVMe")
    lock = verify_phase0_lock(args.lock)
    if lock["config_sha256"] != canon_hash(cfg):
        raise ValueError("training config differs from frozen Phase0 config")
    for split in ("TRAIN", "DEV"):
        if (args.data / split / "manifest.json").resolve() != Path(lock["data"][split]["path"]).resolve():
            raise ValueError("data root is not the locked population")
    torch.manual_seed(cfg["seed"])
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    train = PackedBank(args.data / "TRAIN", args.substrate, cfg)
    dev = PackedBank(args.data / "DEV", args.substrate, cfg)
    assert_disjoint(train, dev)
    if train.representation_id != dev.representation_id:
        raise ValueError("TRAIN/DEV representation contract differs")
    model = SemanticEpistemicGraft(cfg).to(args.device)
    mean, std = training_normalizer(train)
    model.input_mean.copy_(mean.to(args.device)); model.input_std.copy_(std.to(args.device))
    batch = train.batch(np.arange(min(8, len(train))), args.device)
    forward = model(batch["H"], batch["A"], batch["candidate_mask"])
    loss, detail = masked_loss(forward, batch["global_y"], batch["global_available"],
                              batch["candidate_y"], batch["candidate_available"], batch["candidate_mask"])
    if not torch.isfinite(loss):
        raise ValueError("nonfinite preflight loss")
    if not args.train:
        receipt = {"status": "TRAINING_PREFLIGHT_PASS_NO_OPTIMIZER_STEPS",
                   "substrate": args.substrate, "train_rows": len(train), "dev_rows": len(dev),
                   "representation_id": train.representation_id,
                   "phase0_lock_sha256": sha_file(args.lock), "canonical_group_overlap": 0,
                   "parameters": sum(p.numel() for p in model.parameters()),
                   "s_shape": list(forward["s"].shape), "e_shape": list(forward["e"].shape),
                   "masked_loss": float(loss.detach()), "loss_components": detail,
                   "BANK_optimizer_steps": 0, "backbone_optimizer_steps": 0}
        receipt_path = NVME / "checks" / f"preflight-{args.substrate}.json"
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != receipt:
                raise ValueError("previous preflight differs; preserve it and version the new run")
        else:
            write_json(receipt_path, receipt)
        print(json.dumps(receipt, indent=2))
        return
    destination = args.out / args.substrate
    destination.mkdir(parents=True, exist_ok=False)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["training"]["lr"], weight_decay=cfg["training"]["weight_decay"])
    rng = np.random.default_rng(cfg["seed"])
    history = []
    size = cfg["training"]["batch_size"]
    for epoch in range(1, cfg["training"]["epochs"] + 1):
        model.train()
        order = rng.permutation(len(train))
        total = 0.0
        for start in range(0, len(order), size):
            b = train.batch(order[start:start + size], args.device)
            output = model(b["H"], b["A"], b["candidate_mask"])
            loss, _ = masked_loss(output, b["global_y"], b["global_available"], b["candidate_y"], b["candidate_available"], b["candidate_mask"])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["training"]["gradient_clip"])
            opt.step()
            total += float(loss.detach())
        history.append({"epoch": epoch, "mean_batch_loss": total / max(1, int(np.ceil(len(order) / size)))})
        print(json.dumps(history[-1]), flush=True)
    artifact = destination / "graft.pt"
    torch.save({"config": cfg, "state_dict": model.cpu().state_dict(),
                "representation_id": train.representation_id, "supervision_abi": supervision_abi(),
                "phase0_lock_sha256": sha_file(args.lock), "frozen_substrate": True}, artifact)
    model.to(args.device)
    report, rows = evaluate(model, dev, args.device, cfg)
    baseline = prior_model(train)
    write_json(destination / "frequency-baseline.json", baseline)
    report["B0_frequency_action_type"] = metrics_for_rows(prior_predictions(rows, baseline), cfg)
    digest = sha_file(artifact)
    with (destination / "DEV-estimates.jsonl").open("w", encoding="utf-8") as dst:
        for envelope in runtime_envelopes(rows, digest, train.representation_id, supervision_abi()):
            dst.write(json.dumps(envelope, sort_keys=True, allow_nan=False) + "\n")
    write_json(destination / "training-receipt.json", {
        "schema": "frozen-fabrique.graft-training-receipt/v1", "history": history,
        "artifact_sha256": digest, "config_sha256": canon_hash(cfg),
        "phase0_lock_sha256": sha_file(args.lock), "DEV": report,
        "backbone_updated": False, "protected_TEST_truth_accessed": False,
        "runtime_scope": "Typed model estimates only; no System1.5 authority changes",
    })


if __name__ == "__main__":
    main()
