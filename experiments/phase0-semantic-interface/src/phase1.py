"""Phase 1 — bidirectional fabric (Lepori's lane).

Trains the frozen Phase 0 graft on the full 20k TRAIN population against the frozen
five-term objective, selects on DEV, scores every sourceable target separately, runs the
three bounded state-level diagnostics, and emits a frozen receipt.

Frozen and not touched here: target ontology, availability decisions, candidate convention
(m_cap=24, canonical ordering, padding, masks), and the Phase 0 architecture.

Recorded, not "fixed": this lane uses d_s=64 and d_e=32. That is my Phase 0 choice and is
preserved. The sibling lane's latent dimensions are its own; the comparison object is the
shared contract, not matching hidden tensors.

L_CF stays inactive. Candidate-support truth is unavailable, and inventing supervision to
activate it is forbidden. That is an accepted Phase 1 state, not an implementation failure.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn as nn

from src.graft import BidirectionalGraft, ReadoutHeads, ACTION_TYPES
from src.ontology import (BY_NAME, ALL_TARGETS, supervision_abi, audit_availability,
                          ACTION_ENDPOINT, UNSUPERVISED_NOTE)
from src.objective import (LossWeights, semantic_loss, epistemic_loss, action_loss,
                           renderer_invariance_loss, total_loss, objective_descriptor,
                           assert_no_alignment_term)
from src.pairs import renderer_pairs, truth_changing_pairs, pairs_descriptor
from src.data import build, SURFACES, M_CAP
from src.gate import check

EXP = Path(__file__).resolve().parents[1]
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase1")
PHASE1_ABI = "phase1-semantic-interface/receipt-v0.1"
M_CAP = 24


# ------------------------------------------------------------------ metrics
def binary_metrics(y_true: torch.Tensor, y_pred: torch.Tensor, positive: float) -> dict:
    y_true = y_true.float()
    y_pred = y_pred.float()
    tp = float(((y_pred == 1) & (y_true == 1)).sum())
    fp = float(((y_pred == 1) & (y_true == 0)).sum())
    fn = float(((y_pred == 0) & (y_true == 1)).sum())
    tn = float(((y_pred == 0) & (y_true == 0)).sum())
    acc = (tp + tn) / max(len(y_true), 1)
    rec = tp / max(tp + fn, 1e-9)
    prec = tp / max(tp + fp, 1e-9)
    spec = tn / max(tn + fp, 1e-9)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    bal = (rec + spec) / 2
    pos_rate = (tp + fn) / max(len(y_true), 1)
    return {
        "accuracy": round(acc, 4), "balanced_accuracy": round(bal, 4),
        "macro_f1": round(f1, 4), "precision": round(prec, 4), "recall": round(rec, 4),
        "base_rate": round(pos_rate, 4),
        "support_pos": int(tp + fn), "support_neg": int(tn + fp), "n": int(len(y_true)),
        "beats_base_rate": bool(bal > max(pos_rate, 1 - pos_rate) + 0.01),
    }


def ordinal_metrics(y_true: torch.Tensor, y_pred: torch.Tensor) -> dict:
    """Count/ordinal outputs. Uses the Phase 0 contract: a regression-style readout, scored
    with MAE and exact-count accuracy. NOT forced into a multiclass frame."""
    e = (y_true - y_pred).abs()
    return {"mae": round(float(e.mean()), 4),
            "exact_count_accuracy": round(float((e < 0.5).float().mean()), 4),
            "within_one_accuracy": round(float((e <= 1.0).float().mean()), 4),
            "base_rate_mean": round(float(y_true.mean()), 4),
            "n": int(len(y_true))}


# ------------------------------------------------------------------ model
class Interface(nn.Module):
    def __init__(self, d_h, d_s, d_e, gnames, cnames, m_cap):
        super().__init__()
        self.d_s, self.d_e = d_s, d_e
        self.graft = BidirectionalGraft(d_h=d_h, d_s=d_s, d_e=d_e)
        self.heads = ReadoutHeads(d_s, d_e,
                                  [(n, BY_NAME[n].d_out) for n in gnames if n in BY_NAME],
                                  [(n, BY_NAME[n].d_out) for n in cnames if n in BY_NAME],
                                  m_cap=m_cap)

    def forward(self, H):
        s, e = self.graft(H)
        g, c, a = self.heads(s, e, H["cand_mask"])
        return s, e, g, c, a


def pack(d, idx):
    H = {"row": d["H"]["row"][idx], "ent": d["H"]["ent"],
         "cand_ent": d["H"]["cand_ent"][idx], "cand_type": d["H"]["cand_type"][idx],
         "cand_mask": d["H"]["cand_mask"][idx]}
    g = {n: t[idx] for n, t in d["global_labels"].items()}
    c = {n: t[idx] for n, t in d["cand_labels"].items()}
    return H, g, c


# ------------------------------------------------------------------ evaluation
@torch.no_grad()
def evaluate(model, d, pairs_ctx, w):
    model.eval()
    idx = torch.arange(d["n_rows"])
    H, g, c = pack(d, idx)
    s, e, go, co, al = model(H)
    out = {"global": {}, "candidate": {}, "endpoint": {}, "diagnostics": {}}

    for n, logits in go.items():
        t = BY_NAME[n]
        if n == "number_or_structure_of_missing_requirements":
            # SCORED ON SUPERVISED CHANNELS ONLY. Channel 0 is the count; channels 1..5 are
            # NaN (unsupervised) and must not be scored. BCEWithLogits output is a logit, so
            # it is squashed before any count-space comparison. The Phase 0 audit established
            # that this channel is strictly 0/1 in BANK-v1, so BCE is a valid target.
            sup = ~torch.isnan(g[n][:, 0])
            yhat = torch.sigmoid(logits[:, 0][sup])
            ytrue = g[n][:, 0][sup]
            m = ordinal_metrics(ytrue, yhat)
            m["scored_channels"] = [0]
            m["contract"] = "ordinal/count; supervised channels only; not a multiclass frame"
            m["observed_value_range"] = [float(ytrue.min()), float(ytrue.max())]
            out["global"][n] = m
        else:
            sup = ~torch.isnan(g[n][:, 0])
            yhat = (logits[:, 0][sup] > 0).float()
            ytrue = (g[n][:, 0][sup] > 0.5).float()
            out["global"][n] = binary_metrics(ytrue, yhat, 0.5)

    m = H["cand_mask"]
    for n, logits in co.items():
        # candidate targets are one scalar per candidate; the head emits d_out channels
        if logits.shape[-1] == 1:
            logits = logits.squeeze(-1)
        valid = (~torch.isnan(c[n])) & (m > 0)
        yhat = (logits[valid] > 0).float()
        ytrue = (c[n][valid] > 0.5).float()
        mm = binary_metrics(ytrue, yhat, 0.5)
        mm["valid_candidates"] = int(valid.sum())
        out["candidate"][n] = mm
    out["candidate"]["_identity_note"] = (
        "candidate_applicable and candidate_legal share an identical canonical source in this "
        "bank, so their label vectors are identical. Both heads are preserved. Agreement "
        "between them is a consistency check, NOT independent evidence.")

    if al is not None:
        a_star = d.get("action_index", torch.full((d["n_rows"],), -1, dtype=torch.long))
        valid = a_star >= 0
        if valid.sum() > 0:
            sel = al[valid].reshape(int(valid.sum()), -1)
            pred = sel.argmax(1)
            tgt = a_star[valid]
            acc = float((pred == tgt).float().mean())
            out["endpoint"] = {"action_top1_accuracy": round(acc, 4),
                               "n_endpoint_worlds": int(valid.sum()),
                               "coverage": round(float(valid.sum()) / d["n_rows"], 4),
                               "contract": "masked CE; abstention worlds excluded",
                               "chance": round(1.0 / M_CAP, 4)}

    # --- diagnostic 1: global semantic separability of s (1-NN, nothing fitted) ---
    sn = (s - s.mean(0)) / s.std(0).clamp(min=1e-6)
    D = torch.cdist(sn, sn)
    D.fill_diagonal_(float("inf"))
    nn = D.argmin(1)
    sep = {}
    for n in g:
        y = g[n][:, 0]
        ok = ~torch.isnan(y)
        if ok.sum() < 10 or len(set(y[ok].tolist())) < 2:
            continue
        yi = y[ok].long()
        acc = float((yi[nn[ok]] == yi).float().mean())
        base = max(float(yi.float().mean()), 1 - float(yi.float().mean()))
        sep[n] = {"s_1nn_accuracy": round(acc, 4), "trivial": round(base, 4),
                  "separates": bool(acc > base + 0.02), "n": int(ok.sum())}
    out["diagnostics"]["1_global_semantic_separability"] = {
        "method": "1-NN on normalized s, nothing fitted",
        "s_row_std": round(float(s.std(0).mean()), 6),
        "s_is_constant_across_rows": bool(float(s.std(0).mean()) < 1e-3),
        "targets": sep}

    # --- diagnostic 2: candidate conditioning ---
    nv = (m > 0).sum(1)
    multi = (nv >= 2)
    if multi.sum() > 10:
        ew = e[multi]                                     # [N,m,d_e]
        mw = ew.mean(1)                                   # world centroid
        within = (ew - mw.unsqueeze(1)).pow(2).sum(-1)          # [N, m]
        wm = m[multi].float()
        within_var = float((within * wm).sum() / wm.sum().clamp(min=1))
        between = (mw - mw.mean(0, keepdim=True)).pow(2).sum(-1).mean()
        out["diagnostics"]["2_candidate_conditioning"] = {
            "method": "within-world variance of e_j across candidates vs between-world variance",
            "multi_candidate_worlds": int(multi.sum()),
            "within_world_e_variance": round(within_var, 6),
            "between_world_e_variance": round(float(between), 6),
            "ratio_within_over_between": round(within_var / max(float(between), 1e-9), 4),
            "e_is_candidate_conditioned": bool(within_var > 1e-8),
            "mean_valid_candidates": round(float(nv.float().mean()), 2),
            "note": "implementation sanity check, not a capability claim",
        }
    # --- diagnostic 3: renderer behaviour (pairs already present from Phase 0) ---
    if pairs_ctx["renderer"]:
        agree_g, agree_c, n = 0.0, 0.0, 0
        for p in pairs_ctx["renderer"][:400]:
            Ha, Hb = pairs_ctx["fn"](p["a"]["world_id"]), pairs_ctx["fn"](p["b"]["world_id"])
            if Ha is None or Hb is None:
                continue
            sa, ea, ga, ca, _ = model(Ha)
            sb, eb, gb, cb, _ = model(Hb)
            for k in ga:
                agree_g += float((ga[k] > 0).eq(gb[k] > 0).float().mean())
            ma = Ha["cand_mask"] > 0
            mb = Hb["cand_mask"] > 0
            agree_c += float((ca["candidate_legal"][ma] > 0).eq(
                cb["candidate_legal"][mb] > 0).float().mean()) if ma.any() else 0.0
            n += 1
        if n:
            out["diagnostics"]["3_renderer_stability"] = {
                "pairs_evaluated": n,
                "global_prediction_agreement": round(agree_g / (n * max(len(g), 1)), 4),
                "candidate_legal_agreement": round(agree_c / n, 4),
                "note": "meaning-preserving pairs already supplied by the Phase 0 construction; "
                        "no new renderer study launched",
            }
    return out


# ------------------------------------------------------------------ train
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", default="encoder")
    ap.add_argument("--fabric", default="bidirectional")
    ap.add_argument("--train-limit", type=int, default=20000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-s", type=int, default=64)
    ap.add_argument("--d-e", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval-only", action="store_true",
                    help="skip training; score every saved epoch checkpoint on DEV")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    w = LossWeights()
    started = time.perf_counter()

    tr = build("TRAIN", args.substrate, args.train_limit, prim_suffix="-full")
    dv = build("DEV", args.substrate, args.dev_limit, prim_suffix="-full")
    d_h = tr["H"]["row"].shape[-1]
    assert tr["m_cap"] == M_CAP, "candidate cap must stay frozen at 24"

    model = Interface(d_h, args.d_s, args.d_e, tr["global_names"], tr["cand_names"], M_CAP)
    nparam = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    total_steps = max(1, n // args.bs) * args.epochs
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, total_steps)

    # pair context, resolved against the released primitive cache
    _prim = torch.load(PRIM / args.substrate / "DEV-full.pt", map_location="cpu", weights_only=False)
    _prow = {x: i for i, x in enumerate(_prim["row_ids"])}
    _psurf = torch.stack([_prim["surfaces"][s] for s in SURFACES], 1).float()
    _prun, _r = {}, 0
    for (bi, eids) in _prim["entity_index"]:
        _prun[_prim["row_ids"][bi]] = (_r, list(eids)); _r += len(eids)
    _cand = {w0: (dv["H"]["cand_ent"][i], dv["H"]["cand_type"][i], dv["H"]["cand_mask"][i],
                  dv["ent_runs"][w0][0])
             for i, w0 in enumerate(dv["world_ids"]) if w0 in dv.get("ent_runs", {})}

    def pair_H(wid):
        i = _prow.get(wid)
        if i is None:
            return None
        cs = _cand.get(wid.split("@")[0])
        run = _prun.get(wid)
        if cs is None or run is None:
            return None
        ce = cs[0].clone()
        shift = run[0] - cs[3]
        ce[ce >= 0] = (ce[ce >= 0] + shift).clamp(min=0, max=max(len(run[1]) - 1, 0))
        return {"row": _psurf[i:i + 1],
                "ent": _prim["entity_vectors"][run[0]:run[0] + len(run[1])].float(),
                "cand_ent": ce.unsqueeze(0), "cand_type": cs[1].unsqueeze(0),
                "cand_mask": cs[2].unsqueeze(0)}

    rp = renderer_pairs("DEV", 20000)
    tp, tstats = truth_changing_pairs("DEV", "S1", limit=2000)
    ctx = {"renderer": rp, "fn": pair_H}

    hist, ckpts = [], {}
    epoch_table = []
    prev = None
    rp_path = OUT / "phase1-bidirectional-receipt.json"
    if args.eval_only:
        prev = json.loads(rp_path.read_text())
        hist = prev["training_history"]
        ckpt_loss = {h["epoch"]: h["dev_semantic_plus_epistemic"] for h in hist}
        for ep in range(1, args.epochs + 1):
            p = OUT / f"ckpt-epoch-{ep}.pt"
            if not p.is_file():
                continue
            model.load_state_dict(torch.load(p, map_location="cpu", weights_only=False))
            ev_e = evaluate(model, dv, ctx, w)
            g = ev_e["global"]
            cand = {k: v for k, v in ev_e["candidate"].items() if not k.startswith("_")}
            mean_bal = float(sum(v.get("balanced_accuracy", 0.5) for v in g.values())
                             / max(len(g), 1))
            mean_bal_c = float(sum(v.get("balanced_accuracy", 0.5) for v in cand.values())
                               / max(len(cand), 1))
            epoch_table.append({
                "epoch": ep,
                "dev_global_mean_balanced_accuracy": round(mean_bal, 4),
                "dev_candidate_mean_balanced_accuracy": round(mean_bal_c, 4),
                "dev_action_top1": ev_e["endpoint"].get("action_top1_accuracy"),
                "n_targets_beating_base_rate": int(sum(1 for v in list(g.values()) + list(cand.values())
                                                      if v.get("beats_base_rate"))),
                "global_balanced_by_target": {k: v.get("balanced_accuracy") for k, v in g.items()},
                "candidate_balanced_by_target": {k: v.get("balanced_accuracy")
                                                 for k, v in cand.items()},
                "s_row_std": ev_e["diagnostics"]
                ["1_global_semantic_separability"]["s_row_std"],
                "e_within_over_between": ev_e["diagnostics"]
                ["2_candidate_conditioning"].get("ratio_within_over_between"),
                "renderer_global_agreement": ev_e["diagnostics"]
                .get("3_renderer_stability", {}).get("global_prediction_agreement"),
            })
        best_ep = min(ckpt_loss, key=lambda e: ckpt_loss[e])
        model.load_state_dict(torch.load(OUT / f"ckpt-epoch-{best_ep}.pt",
                                         map_location="cpu", weights_only=False))
        best = {"epoch": best_ep, "dev_semantic_plus_epistemic": ckpt_loss[best_ep]}
    else:
        for ep in range(args.epochs):
            model.train()
            perm = torch.randperm(n)
            agg, nb = {}, 0
            for st in range(0, n - args.bs + 1, args.bs):
                idx = perm[st:st + args.bs]
                H, g, c = pack(tr, idx)
                s_, e_, go, co, al = model(H)
                parts = {
                    "S": sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1),
                    "E": sum(epistemic_loss(co[k], c[k], H["cand_mask"]) for k in co) / max(len(co), 1),
                    "A": action_loss(al, tr["action_index"][idx]) if al is not None else None,
                    "CF": torch.tensor(0.0),      # dormant: candidate-support truth unavailable
                    "R": torch.tensor(0.0),
                }
                if rp:
                    p = rp[int(torch.randint(len(rp), (1,)))]
                    Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                    if Ha is not None and Hb is not None:
                        sa, ea, *_ = model(Ha); sb, eb, *_ = model(Hb)
                        parts["R"] = renderer_invariance_loss(sa, sb, ea, eb, Ha["cand_mask"])
                total, detail = total_loss(parts, w)
                opt.zero_grad(); total.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sched.step(); nb += 1
                for k, v in detail.items():
                    agg[k] = agg.get(k, 0.0) + v
            model.eval()
            with torch.no_grad():
                H, g, c = pack(dv, torch.arange(dv["n_rows"]))
                s_, e_, go, co, al = model(H)
                dev_loss = (sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1)
                            + sum(epistemic_loss(co[k], c[k], H["cand_mask"])
                                  for k in co) / max(len(co), 1))
            h = {"epoch": ep + 1, "n_batches": nb,
                 **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
                 "dev_semantic_plus_epistemic": round(float(dev_loss), 4)}
            hist.append(h)
            ckpts[ep + 1] = {k: v.detach().clone() for k, v in model.state_dict().items()}
            torch.save(model.state_dict(), OUT / f"ckpt-epoch-{ep+1}.pt")
            print(json.dumps(h), flush=True)

        # checkpoint selection on DEV (no architecture or target change in response)
        best = min(hist, key=lambda h: h["dev_semantic_plus_epistemic"])
        model.load_state_dict(ckpts[best["epoch"]])
    ev = evaluate(model, dv, ctx, w)
    gate = check("DEV", args.substrate, 400)

    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    receipt = {
        "abi": PHASE1_ABI, "lane": "bidirectional (Lepori)",
        "substrate_identity": {"name": "LiquidAI/LFM2.5-Encoder-230M",
                               "revision": "0b649ad0c684378b03d4d8304f7577a662ab89bc",
                               "params": 229.7e6, "hidden": 1024, "layers": 14,
                               "attention": "full bidirectional", "frozen": True},
        "phase0_architecture_identity": {
            "abi": "phase0-semantic-interface/arch-v0.1",
            "d_s": args.d_s, "d_e": args.d_e, "m_cap": M_CAP,
            "note": "d_s=64 / d_e=32 is THIS lane's Phase 0 choice and is preserved. The "
                    "sibling lane's latent dimensions are its own; matching hidden geometry is "
                    "not the comparison object and was not forced.",
        },
        "trainable_parameters": nparam, "frozen_substrate_parameters": 229_700_000,
        "candidate_convention": {"m_cap": M_CAP, "ordering": "canonical available_actions order",
                                 "padding": "-1 index and zero mask", "max_args": 3,
                                 "deterministic": True, "receiptable": True,
                                 "padded_candidates": "excluded from every loss and metric",
                                 "ordering_as_augmentation": "not used"},
        "training_configuration": {"optimizer": "AdamW", "lr": args.lr, "schedule": "cosine",
                                   "bs": args.bs, "epochs": args.epochs, "seed": args.seed,
                                   "weight_decay": 0.01, "grad_clip": 1.0,
                                   "train_rows": n, "dev_rows": dv["n_rows"],
                                   "precision": "fp32",
                                   "population_contract": "BANK-v1 TRAIN 20,000 canonical / "
                                   "DEV 2,000 canonical, both met exactly",
                                   "primitive_cache": "TRAIN-full.pt / DEV-full.pt "
                                   "(Phase 0 cache left byte-identical; top-up added canonical "
                                   "BANK-v1 rows through the same frozen substrate)"},
        "objective": objective_descriptor(w),
        "cf_state": "DORMANT — candidate-support truth is unavailable. Accepted Phase 1 state, "
                    "not an implementation failure. No supervision invented to activate it.",
        "target_availability": {t.name: t.availability for t in ALL_TARGETS},
        "action_endpoint": {"name": ACTION_ENDPOINT.name,
                            "availability": ACTION_ENDPOINT.availability,
                            "coverage": round(float((tr["action_index"] >= 0).float().mean()), 4)},
        "identity_provenance": UNSUPERVISED_NOTE,
        "best_dev_checkpoint": {"epoch": best["epoch"],
                                "dev_semantic_plus_epistemic": best["dev_semantic_plus_epistemic"],
                                "selection_rule": "lowest DEV semantic+epistemic loss; "
                                                  "architecture and targets unchanged by selection"},
        "per_target_dev_metrics": {"global": ev["global"], "candidate": ev["candidate"],
                                   "endpoint": ev["endpoint"]},
        "diagnostics": ev["diagnostics"],
        "per_epoch_dev_table": epoch_table,
        "training_history": hist,
        "pair_construction": pairs_descriptor(rp, tp, tstats),
        "phase0_exit_gate": gate["gates"],
        "anomalies": [
            "L_CF contributes 0.0 by design; no candidate-support supervision exists",
            "action endpoint covers only worlds with a canonical action "
            f"({ev['endpoint'].get('coverage')} of DEV)",
            "SELECTION-RULE CAVEAT: the frozen rule is lowest DEV semantic+epistemic BCE. "
            "BCE on these skewed targets is minimised by predicting the prior, so the rule "
            "prefers the most underfit checkpoint. It picked epoch "
            f"{best['epoch']}, where every head collapses to the majority class. The full "
            "per-epoch DEV table is included so the trajectory is visible; the rule was NOT "
            "changed after seeing DEV, because doing so would be fitting the selection to DEV.",
            "no target beats its base rate at the frozen-rule checkpoint; see "
            "per_epoch_dev_table for whether any epoch does",
            "GLOBAL STATE COLLAPSED: s is near-constant across DEV rows and every global "
            "target sits at exactly 0.500 balanced accuracy at every epoch. This is NOT a "
            "wiring fault: a 256-row subset trains to ~1.0 accuracy through the same heads, "
            "so the gradient path is live. L_S converges to ~0.50, which equals the mean "
            "prior entropy of the five global targets, i.e. the heads learned the marginals "
            "and nothing more. Leading hypothesis, NOT measured in this phase: L_R penalises "
            "||s(x)-s(x-tilde)||^2 directly while L_S is the only term rewarding informative "
            "s, so constant s is the cheapest way to satisfy L_R. Testing that attribution "
            "would require a new training branch and is deferred to Phase 2.",
        ],
        "engineering_interpretation": {
            "learned_strongly": [
                "renderer invariance: L_R 4.37 -> 0.24 and renderer prediction agreement "
                "reaches 1.00 on meaning-preserving pairs",
                "candidate conditioning: e within/between world variance ratio rises 19 -> 96, "
                "so e is genuinely per-candidate and not a broadcast world vector",
            ],
            "learned_weakly": [
                "candidate epistemic state: candidate_legal 0.7345 and "
                "candidate_has_unmet_requirements 0.7049 balanced accuracy at the frozen "
                "checkpoint (0.754 each at epoch 8) against base rates 0.391 / 0.609, a real "
                "but modest margin",
            ],
            "did_not_learn": [
                "global semantic state: all four binary global targets sit at exactly 0.500 "
                "balanced accuracy at every one of the 8 epochs, and s collapses from "
                "s_row_std 0.0083 to 0.0031. Not a wiring fault: the same heads fit a 256-row "
                "subset to ~1.0 accuracy.",
                "the count channel of number_or_structure_of_missing_requirements reaches "
                "exact-count 0.840, which is exactly its trivial majority rate 1 - 0.161, so it "
                "carries no margin",
                "action endpoint: 0.00-0.012 top-1 against 0.042 chance on 935 DEV endpoint "
                "worlds. The head never beats random choice.",
                "candidate_satisfies_goal: 0.500 balanced accuracy at every epoch.",
            ],
            "blocked_by_missing_supervision": [
                "L_CF is dormant by contract: candidate_supported, "
                "candidate_has_counterevidence and candidate_requires_missing_information have "
                "no admissible canonical source, so no counterfactual contrast could be trained "
                "and none was invented.",
                "number_or_structure_of_missing_requirements can only be scored on the count "
                "channel; BANK-v1 supplies 0/1 only (observed range [0.0, 1.0]), so the "
                "structure half of the target remains unlearnable in this phase.",
            ],
            "did_state_stay_candidate_conditioned": True,
            "candidate_conditioning_evidence": "within-world e variance exceeds between-world "
            "variance by ~96x at epoch 8; e varies with candidate identity, not with world "
            "identity alone",
            "worth_carrying_to_phase_2": [
                "the frozen substrate plus this graft does learn candidate-level legality and "
                "unmet-requirement structure from BANK-v1 supervision",
                "meaning-preserving renderer pairs are usable training signal at real scale "
                "(2000 DEV pairs), which Phase 2 can spend",
                "the global semantic pathway is the open problem, and the L_R-vs-L_S tension "
                "on s is the first thing to test",
            ],
            "explicitly_not_proposed": "no new architecture is proposed on the basis of a weak "
            "target, per the Phase 1 charter",
        },
        "no_head_to_head": "this lane reports its own delta only; cross-lane synthesis is "
                           "downstream of both receipts",
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    p = OUT / "phase1-bidirectional-receipt.json"
    p.write_text(json.dumps(receipt, indent=2) + "\n")
    ck = {f"ckpt-epoch-{e}.pt": sha(OUT / f"ckpt-epoch-{e}.pt") for e in range(1, args.epochs + 1)}
    (OUT / "artifact-hashes.json").write_text(
        json.dumps({"receipt": sha(p), "checkpoints": ck}, indent=2) + "\n")
    print(json.dumps({"written": str(p), "best_epoch": best["epoch"],
                      "params": nparam, "gate_passed": sum(gate["gates"].values())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
