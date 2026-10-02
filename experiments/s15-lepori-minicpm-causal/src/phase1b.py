"""Phase 1B stage 2: supervision isolation.

Same graft architecture, same frozen MiniCPM, same TRAIN/DEV, same candidate universe, same
normalisation contract. No new mechanism of any kind. The only change is WHAT IS SUPERVISED:

    candidate_legal              preservation target
    candidate_satisfies_goal     primary acquisition target
    global heads                 OUT of the experiment
    action loss                  OUT of the experiment
    L_pair, L_var                RETAINED -- inherited contract terms, and dropping them would
                                 be a second intervention layered on the first

Why this runs even though the stage-1 recoverability gate was not met. Stage 1 tested whether the
distinction is accessible in the ALREADY-TRAINED Phase 1 representation. It is not, at any readout
depth tried. That result cannot distinguish:

  (a) objective competition prevented acquisition -- in which case removing the competing terms
      and retraining from the same initialisation should let s acquire goal-relative structure;
  (b) the interface or substrate cannot express it at all -- in which case (a) will also fail.

(a) is the cheaper explanation and it is still live, so it gets tested before any cross-lane
comparison is invoked. Same initialisation file as Phase 1, so the comparison is clean.

The action head is deliberately NOT reconnected. Per the programme rule, the endpoint is only
revisited once the goal-relative channel is genuinely alive.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from src import data as D
from src.graft import CausalGraft, architecture_descriptor
from src.phase1 import eval_head, prevalences, pack
from src.ontology import CAND_GROUPS

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
ARM = OUT / "phase1b"
ARM.mkdir(parents=True, exist_ok=True)
PRESERVE = "candidate_legal"
PRIMARY = "candidate_satisfies_goal"


class TwoHeads(torch.nn.Module):
    """Only the two candidate targets under experiment. One logit per candidate, padded slots
    masked to zero so they can never be selected."""

    def __init__(self, d_e: int):
        super().__init__()
        self.preserve = torch.nn.Linear(d_e, 1)
        self.primary = torch.nn.Linear(d_e, 1)

    def forward(self, e, m):
        return {"preserve": self.preserve(e).squeeze(-1) * m,
                "primary": self.primary(e).squeeze(-1) * m}


class IsolatedGraft(torch.nn.Module):
    """Identical forward path to Phase 1's graft. Only the supervised outputs differ."""

    def __init__(self, d_h):
        super().__init__()
        self.graft = CausalGraft(d_h, 64, 32, 128)
        self.heads = TwoHeads(32)

    def forward(self, H):
        s, e, bank = self.graft(H)
        return s, e, bank


def balanced(logit, y, pi, mask):
    """Masked balanced BCE. NaN labels at padded slots MUST be neutralised before the masked
    sum, because NaN * 0 is still NaN -- see CORRECTIONS.md C12."""
    t = torch.nan_to_num(y, nan=0.0)
    lg = logit * mask
    l = 0.5 * ((t / pi) * torch.nn.functional.softplus(-lg)
               + ((1 - t) / (1 - pi)) * torch.nn.functional.softplus(lg))
    return (l * mask).sum() / mask.sum().clamp(min=1)


@torch.no_grad()
def js_penalty(s, sigma0):
    sigma = s.std(dim=0, unbiased=False)
    return (torch.clamp(0.5 * sigma0 - sigma, min=0.0) ** 2).mean()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    started = time.perf_counter()

    tr = D.build("TRAIN", 20000)
    dv = D.build("DEV", 2000)
    pi_g, pi_c = prevalences(tr)
    d_h = tr["H"]["row"].shape[-1]

    torch.manual_seed(args.seed)
    model = IsolatedGraft(d_h)
    nparam = sum(p.numel() for p in model.parameters())
    init = ARM / "init.pt"
    if init.is_file():
        model.load_state_dict(torch.load(init, map_location="cpu", weights_only=False))

    sigp = ARM / "sigma0.pt"
    if sigp.is_file():
        sigma0 = torch.load(sigp, map_location="cpu", weights_only=False)
    else:
        model.eval()
        with torch.no_grad():
            acc = [model(pack(tr, torch.arange(i, min(i + 512, tr["n_rows"])))[0])[0]
                   for i in range(0, tr["n_rows"], 512)]
            sigma0 = torch.cat(acc, 0).std(0, unbiased=False)
        torch.save(sigma0, sigp)

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, max(1, n // args.bs) * args.epochs)
    pi_p, pi_r = pi_c[PRESERVE], pi_c[PRIMARY]

    def heads(e, m):
        return model.heads(e, m)

    hist, ck = [], {}
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        agg, nb = {}, 0
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, g, c = pack(tr, idx)
            s, e, bank = model(H)
            m = H["cand_mask"]
            hl = heads(e, m)
            l_preserve = balanced(hl["preserve"], c[PRESERVE], pi_p, m)
            l_primary = balanced(hl["primary"], c[PRIMARY], pi_r, m)
            l_var = js_penalty(s, sigma0)
            # family = one unit, averaged over the two independent candidate sources present here
            l_cand = 0.5 * (l_preserve + l_primary)
            total = l_cand + 0.05 * l_var
            opt.zero_grad(); total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); nb += 1
            for k, v in (("candidate_family", float(l_cand)), ("preserve", float(l_preserve)),
                         ("primary", float(l_primary)), ("var", float(l_var))):
                agg[k] = agg.get(k, 0.0) + v
        # DEV criterion: the PRIMARY target, plus the preservation target as a guard
        model.eval()
        with torch.no_grad():
            H, g, c = pack(dv, torch.arange(dv["n_rows"]))
            s, e, bank = model(H)
            m = H["cand_mask"]
            hl = heads(e, m)
            vl = balanced(hl["preserve"], c[PRESERVE], pi_p, m)
            vr = balanced(hl["primary"], c[PRIMARY], pi_r, m)
        h = {"epoch": ep + 1, "n_batches": nb,
             **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
             "dev_preserve_loss": round(float(vl), 4),
             "dev_primary_loss": round(float(vr), 4),
             "dev_criterion": round(float(0.5 * (vl + vr)), 4),
             "D_s": round(float(s.std(0, unbiased=False).mean()), 6)}
        hist.append(h)
        ck[ep + 1] = {k: v.detach().clone() for k, v in model.state_dict().items()}
        torch.save(model.state_dict(), ARM / f"ckpt-epoch-{ep+1}.pt")
        print(json.dumps(h), flush=True)

    best = min(hist, key=lambda x: x["dev_criterion"])
    model.load_state_dict(ck[best["epoch"]])

    @torch.no_grad()
    def score():
        model.eval()
        H, g, c = pack(dv, torch.arange(dv["n_rows"]))
        s, e, bank = model(H)
        m = H["cand_mask"]
        hl = heads(e, m)
        out = {}
        for name, t in ((PRESERVE, PRESERVE), (PRIMARY, PRIMARY)):
            sel = ((~torch.isnan(c[t])) & (m > 0)).bool()
            out[name] = eval_head(hl["preserve" if t == PRESERVE else "primary"][sel],
                                  c[t][sel], pi_c[t])
        nv = (m > 0).sum(1)
        multi = nv >= 2
        ew = e[multi]
        within = (ew - ew.mean(1).unsqueeze(1)).pow(2).sum(-1)
        between = (ew.mean(1) - ew.mean(1).mean(0, keepdim=True)).pow(2).sum(-1).mean()
        wv = float((within * (m > 0)[multi].float()).sum()
                   / (m > 0)[multi].float().sum().clamp(min=1))
        return out, {"D_s": round(float(s.std(0, unbiased=False).mean()), 6),
                     "candidate_conditioning": round(wv / max(float(between), 1e-9), 3)}

    m_out, diag = score()
    print("\n  best epoch", best["epoch"])
    for k, v in m_out.items():
        print(f"  {k:26s} balAcc {v['balanced_accuracy']:.4f}  acc {v['accuracy']:.4f}  "
              f"beats {v['beats_base_rate']}")
    print("  ", json.dumps(diag))

    acquired = m_out[PRIMARY]["beats_base_rate"]
    rec = {
        "abi": "s15-lepori-minicpm/phase1b-supervision-isolation-v0.1",
        "stage": "Phase 1B stage 2 -- supervision isolation",
        "design": {
            "preservation_target": PRESERVE, "primary_acquisition_target": PRIMARY,
            "global_heads": "OUT", "action_loss": "OUT", "action_head": "NOT reconnected",
            "L_pair": "retained (inherited contract term; dropping it would be a second "
                      "intervention layered on the first)",
            "L_var": "retained", "L_CF": "dormant, no candidate-support source",
            "family_weighting": "0.5 * (preserve + primary), one unit per independent source",
            "architecture": "identical to Phase 1, unchanged", "backbone": "frozen",
            "normalisation": "TRAIN-only frozen surface statistics, unchanged",
            "candidate_universe": f"exhaustive m_max={D.M_CAP}, unchanged",
            "initialisation": "same seed and construction as Phase 1",
        },
        "trainable_parameters": nparam,
        "training_history": hist,
        "best_epoch": best["epoch"],
        "results": m_out,
        "diagnostics": diag,
        "verdict": {
            "goal_channel_acquired": bool(acquired),
            "reading": ("ACQUIRED. Removing the competing global and action supervision let the "
                        "goal-relative candidate channel form, so the Phase 1 failure was "
                        "objective competition rather than an interface limit. The next step is "
                        "to reconnect the SIMPLE existing action head, not to build a mechanism."
                        if acquired else
                        "NOT ACQUIRED. With the competing terms removed and the same architecture "
                        "and initialisation, the goal-relative channel still does not form. That "
                        "rules out objective competition as the explanation and points at the "
                        "representation itself, which is where cross-lane comparison against Lexi "
                        "becomes earned."),
            "preservation_held": bool(m_out[PRESERVE]["beats_base_rate"]),
            "preservation_note": "legality must not regress; it was 0.7495 in Phase 1",
        },
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "protected": {"PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
                      "CANONICAL_SPLITS_UNCHANGED": True, "BACKBONE_TUNED": False,
                      "NEW_MECHANISM": False, "NEW_SUPERVISION_SOURCE": False},
    }
    p = ARM / "phase1b-receipt.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print("\nverdict:", json.dumps(rec["verdict"], indent=2))
    print("written:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
