"""Phase 1B stage 1: recoverability of goal-relative candidate semantics.

The Phase 1 graft and the substrate are FROZEN. Only newly attached diagnostic readouts are
trained, and only the readouts. The question is narrow:

    Can MiniCPM acquire goal-relative candidate semantics through the interface it already has?

PROSPECTIVELY FIXED, before any result is seen, and identical for every arm:

  readout family (all one-logit-per-candidate, read only from frozen representations)
    prod      the production head itself, no training            [reference only]
    linear    Linear(d_in, 1)
    mlp       Linear(d_in, 64) -> GELU -> Linear(64, 1)

  input representation
    e_j       the trained graft's candidate state, d_in = 32
    c_j       the candidate/entity representation feeding rho_e, d_in = 256
    cs        [c_j ; s], d_in = 320
    e_untrained  the SAME e_j architecture from the untrained graft, d_in = 32

  optimisation, identical for every trained arm
    AdamW lr 1e-3, weight decay 0.01, cosine, bs 64, 4 epochs, grad clip 1.0, seed 0,
    balanced BCE with TRAIN-only prevalence, masked to valid candidates

  two controls, because a negative result is only informative if the readout family is
  demonstrably capable and the floor is demonstrably at chance
    CONTROL-CAPABLE   the same readout family on e_j predicting candidate_legal, which the
                      production head already solves at 0.7495
    CONTROL-FLOOR     the same readout family on the untrained graft's e_j predicting
                      candidate_satisfies_goal

  reporting
    primary   DEV balanced accuracy at the FINAL epoch
    secondary DEV balanced accuracy at the best-by-TRAIN-loss epoch
    NO selection among readouts on DEV. Beats-base-rate uses the same pre-registered margin
    (balanced accuracy must exceed max(pi, 1-pi) by more than 0.01).

Localisation tree, as specified: if a new head on e_j works, the state already contains the
distinction and the production head or its optimisation failed. If e_j fails but c_j succeeds,
rho_e is destroying it. If [c_j;s] succeeds but c_j does not, goal context exists in s and is
not being integrated. If all fail, the exposed representation does not make the distinction
accessible under these frozen readouts.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn as nn

from src import data as D
from src.phase1 import Interface, pack, eval_head, prevalences
from src.ontology import CAND_GROUPS

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
TARGET = "candidate_satisfies_goal"
LEGAL = "candidate_legal"
PRE = {"optimiser": "AdamW", "lr": 1e-3, "weight_decay": 0.01, "schedule": "cosine",
       "batch": 64, "epochs": 4, "grad_clip": 1.0, "seed": 0,
       "loss": "balanced BCE, TRAIN-only prevalence, masked to valid candidates",
       "primary_metric": "DEV balanced accuracy at final epoch",
       "secondary_metric": "DEV balanced accuracy at best-by-TRAIN-loss epoch",
       "dev_selection_among_readouts": False,
       "beats_base_rate_margin": 0.01}


class Readout(nn.Module):
    def __init__(self, d_in: int, kind: str):
        super().__init__()
        self.kind = kind
        self.net = (nn.Linear(d_in, 1) if kind == "linear"
                    else nn.Sequential(nn.Linear(d_in, 64), nn.GELU(), nn.Linear(64, 1)))

    def forward(self, x):
        return self.net(x).squeeze(-1)


@torch.no_grad()
def representations(model, d, bs=512):
    """Cache the frozen representations once, so every readout arm sees identical inputs."""
    model.eval()
    e, c, s, m = [], [], [], []
    for i in range(0, d["n_rows"], bs):
        idx = torch.arange(i, min(i + bs, d["n_rows"]))
        H, _, _ = pack(d, idx)
        u = model.graft.surfaces(H["row"])
        s_i = model.graft.rho_s(u.reshape(u.shape[0], -1))
        c_i = model.graft.candidate_states(H)
        e_i = model.graft.rho_e(torch.cat(
            [c_i, s_i.unsqueeze(1).expand(-1, c_i.shape[1], -1)], -1)) * H["cand_mask"].unsqueeze(-1)
        e.append(e_i.half()); c.append(c_i.half()); s.append(s_i.half()); m.append(H["cand_mask"])
    return (torch.cat(e), torch.cat(c), torch.cat(s), torch.cat(m))


def which(arm, e, c, s):
    if arm == "e_j":
        return e
    if arm == "c_j":
        return c
    if arm == "cs":
        return torch.cat([c, s.unsqueeze(1).expand(-1, c.shape[1], -1)], -1)
    raise KeyError(arm)


@torch.no_grad()
def _train_loss(r, x, y, mask, pi, rows=4096):
    """Balanced BCE on a fixed TRAIN subsample, so 'best by TRAIN loss' is a real quantity
    rather than the last minibatch's loss."""
    r.eval()
    sel_rows = torch.linspace(0, x.shape[0] - 1, min(rows, x.shape[0])).long()
    xb, yb, mb = x[sel_rows].float(), y[sel_rows], mask[sel_rows]
    logit = r(xb) * mb
    # padded slots carry NaN labels; NaN * 0 is still NaN and one NaN poisons the whole sum,
    # which silently turns the readout into a constant predictor. Zero them and rely on the mask.
    t = torch.nan_to_num(yb, nan=0.0)
    l = 0.5 * ((t / pi) * nn.functional.softplus(-logit)
               + ((1 - t) / (1 - pi)) * nn.functional.softplus(logit))
    return float((l * mb).sum() / mb.sum().clamp(min=1))


def train_readout(x_tr, y_tr, mask_tr, d_in, kind, epochs=4):
    torch.manual_seed(PRE["seed"])
    r = Readout(d_in, kind)
    opt = torch.optim.AdamW(r.parameters(), lr=PRE["lr"], weight_decay=PRE["weight_decay"])
    n = x_tr.shape[0]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, max(1, n // PRE["batch"]) * epochs)
    pi = float((y_tr[mask_tr.bool()] > 0.5).float().mean())
    best, best_state, best_ep = float("inf"), {k: v.detach().clone()
                                               for k, v in r.state_dict().items()}, 0
    for ep in range(epochs):
        r.train()
        perm = torch.randperm(n)
        for st in range(0, n - PRE["batch"] + 1, PRE["batch"]):
            idx = perm[st:st + PRE["batch"]]
            xb = x_tr[idx].float()
            yb = y_tr[idx]
            mb = mask_tr[idx]
            logit = r(xb) * mb
            # padded slots carry NaN labels; NaN * 0 is still NaN and one NaN poisons the whole
            # sum, silently turning the readout into a constant predictor. Zero them, and rely on
            # the mask to exclude those slots.
            t = torch.nan_to_num(yb, nan=0.0)
            l = 0.5 * ((t / pi) * nn.functional.softplus(-logit)
                       + ((1 - t) / (1 - pi)) * nn.functional.softplus(logit))
            loss = (l * mb).sum() / mb.sum().clamp(min=1)
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(r.parameters(), PRE["grad_clip"])
            opt.step(); sched.step()
        tr_loss = _train_loss(r, x_tr, y_tr, mask_tr, pi)
        if tr_loss < best:
            best, best_ep = tr_loss, ep + 1
            best_state = {k: v.detach().clone() for k, v in r.state_dict().items()}
    return r, best_state, best, best_ep, pi


@torch.no_grad()
def score(r, x, y, mask, pi):
    r.eval()
    sel = (~torch.isnan(y)) & (mask > 0)
    logit = r(x.float()) * mask
    return eval_head(logit[sel.bool()], y[sel.bool()], pi)


def main() -> int:
    rec_all = json.loads((OUT / "phase1-receipt.json").read_text())
    ep = rec_all["selection"]["best_epoch"]
    tr = D.build("TRAIN", 20000)
    dv = D.build("DEV", 2000)
    d_h = tr["H"]["row"].shape[-1]
    pi_g, pi_c = prevalences(tr)

    trained = Interface(d_h, 64, 32, tr["global_names"], tr["cand_names"], D.M_CAP)
    trained.load_state_dict(torch.load(OUT / f"phase1-ckpt-epoch-{ep}.pt",
                                       map_location="cpu", weights_only=False))
    trained.eval()
    for p_ in trained.parameters():
        p_.requires_grad_(False)

    torch.manual_seed(PRE["seed"])
    fresh = Interface(d_h, 64, 32, tr["global_names"], tr["cand_names"], D.M_CAP)
    fresh.eval()
    for p_ in fresh.parameters():
        p_.requires_grad_(False)

    print("caching frozen representations ...", flush=True)
    e_tr, c_tr, s_tr, m_tr = representations(trained, tr)
    e_dv, c_dv, s_dv, m_dv = representations(trained, dv)
    e_tr_u, _, _, _ = representations(fresh, tr)
    e_dv_u, _, _, _ = representations(fresh, dv)
    print("done", e_tr.shape, c_tr.shape, flush=True)

    arms = [("e_j", "linear", TARGET, "primary"),
            ("e_j", "mlp", TARGET, "primary"),
            ("c_j", "linear", TARGET, "primary"),
            ("c_j", "mlp", TARGET, "primary"),
            ("cs", "linear", TARGET, "primary"),
            ("cs", "mlp", TARGET, "primary"),
            ("e_j", "linear", LEGAL, "CONTROL-CAPABLE"),
            ("e_j", "mlp", LEGAL, "CONTROL-CAPABLE"),
            ("c_j", "mlp", LEGAL, "CONTROL-CAPABLE"),
            ("e_untrained", "mlp", LEGAL, "CONTROL-FLOOR"),
            ("e_untrained", "mlp", TARGET, "CONTROL-FLOOR")]

    results = {}
    for arm, kind, target, role in arms:
        xtr = which(arm, e_tr, c_tr, s_tr) if arm != "e_untrained" else e_tr_u
        xdv = which(arm, e_dv, c_dv, s_dv) if arm != "e_untrained" else e_dv_u
        ytr = tr["cand_labels"][target]
        ydv = dv["cand_labels"][target]
        r, best_state, best_loss, best_ep, pi = train_readout(
            xtr, ytr, m_tr, xtr.shape[-1], kind)
        fin = score(r, xdv, ydv, m_dv, pi)
        r.load_state_dict(best_state)
        bst = score(r, xdv, ydv, m_dv, pi)
        key = f"{arm}|{kind}|{target}"
        results[key] = {"role": role, "arm": arm, "readout": kind, "target": target,
                        "d_in": int(xtr.shape[-1]),
                        "train_prevalence": round(pi, 4),
                        "final_epoch": fin, "best_train_loss_epoch": bst,
                        "best_train_loss": round(best_loss, 5), "best_epoch": best_ep}
        print(f"  {key:38s} balAcc final {fin['balanced_accuracy']:.4f}  "
              f"best {bst['balanced_accuracy']:.4f}  beats {fin['beats_base_rate']}", flush=True)

    # pre-registered sensitivity: is 4 probe epochs simply too few? fixed in advance, reported,
    # never used to select among arms.
    sens = {}
    for arm, kind, target in (("e_j", "mlp", TARGET), ("c_j", "mlp", TARGET)):
        xtr = which(arm, e_tr, c_tr, s_tr)
        xdv = which(arm, e_dv, c_dv, s_dv)
        ytr, ydv = tr["cand_labels"][target], dv["cand_labels"][target]
        r, st, bl, be, pi = train_readout(xtr, ytr, m_tr, xtr.shape[-1], kind, epochs=12)
        f12 = score(r, xdv, ydv, m_dv, pi)
        r.load_state_dict(st)
        b12 = score(r, xdv, ydv, m_dv, pi)
        sens[f"{arm}|{kind}|{target}|12ep"] = {"final_epoch": f12,
                                              "best_train_loss_epoch": b12,
                                              "best_epoch": be}
        print(f"  SENSITIVITY {arm}|{kind}|{target} 12 epochs  final "
              f"{f12['balanced_accuracy']:.4f}  best {b12['balanced_accuracy']:.4f}", flush=True)

    # production-head reference, no training
    with torch.no_grad():
        _, _, _, co, _, _ = trained(pack(dv, torch.arange(dv["n_rows"]))[0])
    prod = {}
    for t in (TARGET, LEGAL):
        sel = ((~torch.isnan(dv["cand_labels"][t])) & (m_dv > 0)).bool()
        prod[t] = eval_head(co[t][sel], dv["cand_labels"][t][sel], pi_c[t])
        print(f"  PRODUCTION HEAD {t:26s} balAcc {prod[t]['balanced_accuracy']:.4f}")

    b = lambda k: results[k]["final_epoch"]["balanced_accuracy"]
    tree = {
        "does_a_new_head_on_e_j_work": max(b("e_j|linear|" + TARGET),
                                           b("e_j|mlp|" + TARGET)) > 0.55,
        "does_c_j_work_if_e_j_fails": max(b("c_j|linear|" + TARGET),
                                          b("c_j|mlp|" + TARGET)) > 0.55,
        "does_cs_work_if_c_j_fails": max(b("cs|linear|" + TARGET),
                                         b("cs|mlp|" + TARGET)) > 0.55,
        "CONTROL-CAPABLE_legality_from_trained_e_j": b("e_j|mlp|" + LEGAL),
        "CONTROL-CAPABLE_legality_from_c_j": b("c_j|mlp|" + LEGAL),
        "CONTROL-FLOOR_legality_from_UNTRAINED_e_j": b("e_untrained|mlp|" + LEGAL),
        "CONTROL-FLOOR_target_from_UNTRAINED_e_j": b("e_untrained|mlp|" + TARGET),
        "sensitivity_12_epochs": {k: v["final_epoch"]["balanced_accuracy"]
                                  for k, v in sens.items()},
        "verdict": None,
    }
    if tree["does_a_new_head_on_e_j_work"]:
        tree["verdict"] = ("RECOVERABLE IN THE STATE. A new readout on the frozen e_j recovers the "
                           "distinction, so e_j already contains it and the production head or its "
                           "optimisation failed. This is a supervision/optimisation problem, not an "
                           "interface problem.")
    elif tree["does_c_j_work_if_e_j_fails"]:
        tree["verdict"] = ("RHO_E IS DESTROYING IT. The distinction is present in c_j but absent "
                           "from e_j, so the projection rho_e discards it.")
    elif tree["does_cs_work_if_c_j_fails"]:
        tree["verdict"] = ("GOAL CONTEXT EXISTS IN s BUT IS NOT INTEGRATED. [c_j;s] recovers the "
                           "distinction while c_j alone does not, so the global state carries "
                           "goal-relative information the candidate path is not using.")
    else:
        tree["verdict"] = ("NOT ACCESSIBLE UNDER THESE FROZEN READOUTS. No arm on e_j, c_j or "
                           "[c_j;s] recovers the distinction. Note the capability control: the same "
                           "readout family solves candidate_legal from e_j, so the readout code is "
                           "not the limitation. Either the representation does not linearly or "
                           "shallowly encode it, or the optimisation needed is beyond a 4-epoch "
                           "linear/MLP probe.")

    out = {"abi": "s15-lepori-minicpm/recoverability-v0.1",
           "stage": "Phase 1B stage 1 -- recoverability, graft and substrate FROZEN",
           "question": "Can MiniCPM acquire goal-relative candidate semantics through the "
                       "interface it already has?",
           "frozen_checkpoint": {"phase1_best_epoch": ep,
                                 "file": f"phase1-ckpt-epoch-{ep}.pt",
                                 "trainable_in_this_stage": "diagnostic readouts only"},
           "prospectively_fixed": PRE,
           "production_head_reference": prod,
           "arms": results,
           "sensitivity_longer_probe": {
               "why": "pre-registered check that 4 probe epochs is not simply too few; reported, "
                      "never used to select among arms",
               "arms": sens},
           "localisation_tree": tree,
           "claim_scope": "diagnostic readouts on frozen representations; this localises where a "
                          "distinction is or is not accessible, and is not a capability result",
           "next_stage_gate": "if the tree says recoverable or rho_e is destroying it, run Phase 1B "
                              "stage 2: same graft architecture, candidate_legal as preservation "
                              "target, candidate_satisfies_goal as primary, global heads and action "
                              "loss OUT of the experiment. Do NOT reconnect the action head until "
                              "the goal-relative channel is genuinely alive."}
    p = OUT / "recoverability.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print("\n" + "=" * 88)
    print("LOCALISATION TREE")
    for k, v in tree.items():
        print(f"  {k}: {v}")
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
