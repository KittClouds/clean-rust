"""Phase 0 training harness and evaluation contract.

Trains G_phi on frozen H with canonical supervision. No substrate updates, no VCS
reopening, no new probing program. The harness exists so Phase 0 can hand off an executable
train/eval path; it is not itself a science run.

Losses are per-target BCE, masked so padded candidates contribute nothing. The contract
records, for every declared target, whether the model is expected to be able to learn it
at all, given the audit: four targets have no label array and therefore no head.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn as nn

from src.graft import SemanticInterfaceGraft, ReadoutHeads, arch_descriptor, ACTION_TYPES
from src.ontology import supervision_abi, audit_availability, BY_NAME
from src.data import build

EXP = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase0")
CONTRACT = "phase0-semantic-interface/eval-contract-v0.1"


class Interface(nn.Module):
    def __init__(self, d_h, d_s=64, d_e=32, hidden=256, gnames=(), cnames=()):
        super().__init__()
        self.graft = SemanticInterfaceGraft(d_h=d_h, d_s=d_s, d_e=d_e, hidden=hidden)
        gdims = [(n, BY_NAME[n].d_out) for n in gnames if n in BY_NAME]
        cdims = [(n, BY_NAME[n].d_out) for n in cnames if n in BY_NAME]
        self.heads = ReadoutHeads(d_s, d_e, gdims, cdims)

    def forward(self, H):
        s, e = self.graft(H)
        g, c = self.heads(s, e, H["cand_mask"])
        return s, e, g, c


def masked_bce(logits, target, mask):
    """logits [B, m, d]; target [B, m] or [B, m, d] or [B, d]; mask anything broadcastable."""
    if target.dim() == 1:
        target = target.unsqueeze(-1)
    if target.dim() == 2 and logits.dim() == 3:
        target = target.unsqueeze(-1).expand_as(logits)
    mask = torch.ones_like(logits) if mask is None else \
        (mask.unsqueeze(-1) if mask.dim() == 1 else mask)
    mask = (torch.ones_like(logits) if mask.dim() == logits.dim() - 1
            else mask.expand_as(logits)).float()
    mask = mask * (~torch.isnan(target)).float()
    target = torch.nan_to_num(target, nan=0.0)
    loss = nn.functional.binary_cross_entropy_with_logits(logits, target, reduction="none")
    denom = mask.sum().clamp(min=1.0)
    return (loss * mask).sum() / denom, mask


def make_batch(d, idx):
    H = {"row": d["H"]["row"][idx], "ent": d["H"]["ent"], "cand_ent": d["H"]["cand_ent"][idx],
         "cand_type": d["H"]["cand_type"][idx], "cand_mask": d["H"]["cand_mask"][idx]}
    g = {n: t[idx] for n, t in d["global_labels"].items()}
    c = {n: t[idx] for n, t in d["cand_labels"].items()}
    return H, g, c


def evaluate(model, d, idx):
    model.eval()
    with torch.no_grad():
        H, g, c = make_batch(d, idx)
        s, e, go, co = model(H)
        out = {}
        for n, logits in go.items():
            l, _ = masked_bce(logits, g[n], torch.ones(len(idx)))
            acc = ((logits > 0).float() == g[n]).float().mean()
            out[n] = {"loss": round(float(l), 4), "acc": round(float(acc), 4),
                      "base_rate": round(float(g[n].mean()), 4)}
        m = H["cand_mask"]
        for n, logits in co.items():
            l, _ = masked_bce(logits, c[n], m)
            valid = (~torch.isnan(c[n])).float() * (m > 0).float()
            while valid.dim() < logits.dim():
                valid = valid.unsqueeze(-1)
            if valid.shape != logits.shape:
                valid = valid.expand(logits.shape).contiguous()
            tgt = torch.nan_to_num(c[n], nan=0.0).unsqueeze(-1).expand_as(logits)
            hit = (((logits > 0).float() == tgt).float() * valid).sum() / valid.sum().clamp(min=1)
            out[n] = {"loss": round(float(l), 4), "acc": round(float(hit), 4),
                      "base_rate": round(float((c[n][(m > 0)]).mean()), 4)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", default="causal", choices=["causal", "encoder"])
    ap.add_argument("--train-split", default="TRAIN")
    ap.add_argument("--dev-split", default="DEV")
    ap.add_argument("--train-limit", type=int, default=6000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-s", type=int, default=64)
    ap.add_argument("--d-e", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.train_limit, args.dev_limit, args.epochs = 400, 200, 2

    torch.manual_seed(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    tr = build(args.train_split, args.substrate, args.train_limit)
    dv = build(args.dev_split, args.substrate, args.dev_limit)
    d_h = tr["H"]["row"].shape[-1]

    model = Interface(d_h, d_s=args.d_s, d_e=args.d_e,
                      gnames=tr["global_names"], cnames=tr["cand_names"])
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    steps = max(1, n // args.bs) * args.epochs
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps)
    gnames, cnames = tr["global_names"], tr["cand_names"]

    history = []
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        nb = 0
        for s in range(0, n - args.bs + 1, args.bs):
            idx = perm[s:s + args.bs]
            H, g, c = make_batch(tr, idx)
            s_, e_, go, co = model(H)
            loss = 0.0
            for nm, logits in go.items():
                l, _ = masked_bce(logits, g[nm], torch.ones(len(idx)))
                loss = loss + l
            m = H["cand_mask"]
            for nm, logits in co.items():
                l, _ = masked_bce(logits, c[nm], m)
                loss = loss + l
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += float(loss.detach()); nb += 1
        dv_idx = torch.arange(dv["n_rows"])
        dev = evaluate(model, dv, dv_idx)
        history.append({"epoch": ep + 1, "train_loss": round(tot / max(nb, 1), 4), "dev": dev})
        print(f"epoch {ep+1} train_loss={tot/max(nb,1):.4f} "
              f"dev_acc=" + " ".join(f"{k.split('_')[-1]}:{v['acc']:.3f}" for k, v in dev.items()),
              flush=True)

    npar = sum(p.numel() for p in model.parameters())
    report = {
        "status": "PHASE0_HARNESS_EXECUTABLE",
        "contract": CONTRACT,
        "substrate": args.substrate,
        "arch": arch_descriptor(d_h, args.d_s, args.d_e),
        "ontology": supervision_abi(),
        "audit": audit_availability(2000),
        "trainable_parameters": npar,
        "frozen_substrate_parameters": 0,
        "note": "F_theta is the released primitive cache; the graft never writes to it",
        "data": {"train_rows": tr["n_rows"], "dev_rows": dv["n_rows"],
                 "valid_candidates_train": int(tr["H"]["cand_mask"].sum()),
                 "m_cap": tr["m_cap"], "max_args": tr["max_args"], "surfaces": tr["surfaces"]},
        "targets_without_heads": [t.name for t in BY_NAME.values()
                                  if t.availability == "UNAVAILABLE"],
        "history": history,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    p = OUT / f"phase0-harness-{args.substrate}.json"
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"written": str(p), "trainable_parameters": npar,
                      "targets_without_heads": report["targets_without_heads"],
                      "elapsed": report["elapsed_seconds"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

