"""Phase0 verification: unit suite, synthetic optimizer smoke, and bounded CPU timing."""
from __future__ import annotations

import io
import json
import time
import unittest
from pathlib import Path

import numpy as np
import torch

from .contracts import (CANDIDATE_AVAILABLE, EXPERIMENT, GLOBAL_AVAILABLE, NVME,
                        canon_hash, default_config, sha_file, write_json)
from .model import model_for_substrate, forward_batch
from .objective import shared_objective


def synthetic_smoke(config, substrate="causal_base"):
    torch.manual_seed(config["seed"])
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    model = model_for_substrate(config, substrate)
    H = torch.randn(8, config["input_dim"], requires_grad=True)
    H_before = H.detach().clone()
    A = torch.randint(1, 6, (8, 12, 5))
    A[:, :, 1:] = torch.randint(0, 9, (8, 12, 4))
    mask = torch.ones(8, 12, dtype=torch.bool)
    gm = torch.tensor([GLOBAL_AVAILABLE] * 8)
    cm = torch.tensor([[CANDIDATE_AVAILABLE] * 12] * 8)
    gy = torch.randint(0, 2, (8, 6)).float()
    cy = torch.randint(0, 2, (8, 12, 7)).float()
    batch = {"H": H, "A": A, "candidate_mask": mask,
             "global_y": gy, "global_available": gm,
             "candidate_y": cy, "candidate_available": cm,
             "action_target": torch.arange(8) % 12,
             "action_available": torch.ones(8, dtype=torch.bool)}
    if model.use_entity_local:
        batch["entity_local"] = torch.randn(8, 9, 1024, requires_grad=True)
        batch["entity_available"] = torch.ones(8, 9, dtype=torch.bool)
        batch["entity_available"][:, 0] = False
    rendered = {**batch, "H": H.detach() + .01 * torch.randn_like(H)}
    opt = torch.optim.AdamW(model.parameters(), lr=config["training"]["lr"])
    before = model.project_h[0].weight.detach().clone()
    losses = []
    for _ in range(5):
        out = forward_batch(model, batch)
        render_out = forward_batch(model, rendered)
        loss, detail = shared_objective(out, batch, config, renderer=(out, render_out, mask, mask))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["training"]["gradient_clip"])
        opt.step()
        losses.append(float(loss.detach()))
    assert all(np.isfinite(losses)), "smoke produced nonfinite loss"
    assert not torch.equal(before, model.project_h[0].weight), "graft did not update"
    assert H.grad is None and torch.equal(H_before, H.detach()), "frozen H changed"
    if model.use_entity_local:
        assert batch["entity_local"].grad is None, "encoder local cache backpropagated"
    model.eval()
    with torch.no_grad():
        first = forward_batch(model, batch)
        second = forward_batch(model, batch)
        assert torch.equal(first["e"], second["e"]), "inference not deterministic"
        buffer = io.BytesIO()
        torch.save(model.state_dict(), buffer)
        buffer.seek(0)
        clone = model_for_substrate(config, substrate).eval()
        clone.load_state_dict(torch.load(buffer, weights_only=True))
        assert torch.equal(first["e"], forward_batch(clone, batch)["e"]), "checkpoint replay changed predictions"
        bench_H = torch.randn(32, config["input_dim"])
        bench_A = A[:1].expand(32, -1, -1).contiguous()
        bench_mask = mask[:1].expand(32, -1).contiguous()
        bench = {"H": bench_H, "A": bench_A, "candidate_mask": bench_mask}
        if model.use_entity_local:
            bench["entity_local"] = batch["entity_local"][:1].expand(32, -1, -1).contiguous()
            bench["entity_available"] = batch["entity_available"][:1].expand(32, -1).contiguous()
        for _ in range(8):
            forward_batch(model, bench)
        timings = []
        for _ in range(30):
            start = time.perf_counter()
            forward_batch(model, bench)
            timings.append((time.perf_counter() - start) * 1000)
    return {"synthetic_optimizer_steps": 5, "BANK_optimizer_steps": 0,
            "fabric": model.config["fabric"], "loss_components": detail,
            "finite_losses": losses, "frozen_H_unchanged": True,
            "deterministic_inference_and_checkpoint_replay": True,
            "graft_parameters": sum(p.numel() for p in model.parameters()),
            "graft_parameter_bytes_fp32": 4 * sum(p.numel() for p in model.parameters()),
            "benchmark": {"device": "CPU", "torch_threads": 4, "batch": 32,
                          "candidates_per_row": 12, "warmup": 8, "repeats": 30,
                          "median_ms": float(np.median(timings)), "p95_ms": float(np.quantile(timings, .95)),
                          "scope": "graft only, cached H; excludes backbone extraction and disk I/O"}}


def main():
    cfg = default_config()
    suite = unittest.defaultTestLoader.discover(str(EXPERIMENT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    smokes = {s: synthetic_smoke(cfg, s) for s in ("causal_base", "encoder_base")}
    receipt = {"status": "PHASE0_CHECKS_PASS", "unit_tests": result.testsRun,
               "config_sha256": canon_hash(cfg), "smoke": smokes["causal_base"], "fabric_smokes": smokes,
               "torch_version": torch.__version__, "numpy_version": np.__version__,
               "source_files": {str(p.relative_to(EXPERIMENT)): sha_file(p)
                                for p in sorted(EXPERIMENT.rglob("*.py"))},
               "protected_TEST_truth_accessed": False}
    write_json(NVME / "checks" / "verification.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
