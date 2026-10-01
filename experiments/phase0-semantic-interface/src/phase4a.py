"""Phase 4A — bidirectional fabric (Lepori's lane).

Adds model-internal iterative computation only: one trainable shared recurrent block R_phi
refining the inherited typed state

    Z_0 = [s_0 ; e_1,0 ; ... ; e_m,0]        (1 + m tokens, padded candidates masked)

    U_t = SelfAttn_phi(LN(Z_t), M)
    C_t = CrossAttn_phi(LN(Z_t + U_t), H)
    Z_{t+1} = Z_t + FFN_phi(LN(Z_t + U_t + C_t))

The SAME R_phi runs at every iteration, T=4. No stochastic transitions, no adaptive halting, no
IHA, no LoRA, no new substrate layers, no new surfaces.

Frozen: the backbone, the inherited Phase 3 graft producing Z_0, and the typed output heads.
Trained: R_phi only. The question is whether extra computation over an already-earned state adds
capability, not whether the state can be relearned.

Because the block is shared, Z_1..Z_3 are reported at inference without selecting among them, so
one training run yields the depth curve 0 -> 1 -> 2 -> 3 -> 4.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn as nn

from src.objective import (Phase3Weights, phase3_total_loss, phase3_objective_descriptor,
                           j_select, source_group_loss, family_balanced_loss, action_loss,
                           prediction_consistency_loss, variance_floor_loss)
from src.data import build
from src.phase1 import Interface, pack, ordinal_metrics
from src.phase3 import GLOBAL_GROUPS, CAND_GROUPS, ALIAS, COUNT_TARGET
from src.phase3 import head_terms_global, head_terms_cand, eval_head
from src.phase2 import pair_context, alignment_ok, M_CAP
from src.graft import ACTION_TYPES

P4 = Path(r"D:\codex-runs\encoder-contrast-01\phase4a")
P4.mkdir(parents=True, exist_ok=True)
P3DIR = Path(r"D:\codex-runs\encoder-contrast-01\phase3\balanced")
SUFFIX = "-p2"
T_STEPS = 4
INTERMEDIATE_COEF = 0.25          # frozen, not tuned from DEV


# ------------------------------------------------------------------ memory gather
def gather_memory(d, idx):
    """Reread the frozen substrate memory H for a batch of rows.

    Memory tokens = the 6 pooled surface vectors followed by the row's entity-span vectors: the
    exact tensors the frozen substrate produced. Nothing new is extracted.
    """
    ent = d["H"]["ent"]
    row = d["H"]["row"][idx]
    runs, ns = [], []
    for i in idx.tolist():
        r, n = d["ent_runs"][d["world_ids"][i]]
        runs.append(r)
        ns.append(n)
    runs, ns = torch.tensor(runs), torch.tensor(ns)
    E = max(int(ns.max()), 1)
    ar = torch.arange(E)
    pos = (runs.unsqueeze(1) + ar.unsqueeze(0)).clamp(max=max(ent.shape[0] - 1, 0))
    emask = (ar.unsqueeze(0) < ns.unsqueeze(1)).float()
    emem = ent[pos] * emask.unsqueeze(-1).float()
    mem = torch.cat([row, emem], 1)
    mmask = torch.cat([torch.ones(len(idx), row.shape[1]), emask], 1)
    return mem, mmask


# ------------------------------------------------------------------ recurrent organ
class RecurrentRefinement(nn.Module):
    def __init__(self, d_z: int, d_h: int, n_heads: int = 8, d_ff: int | None = None,
                 dropout: float = 0.1):
        super().__init__()
        d_ff = d_ff or 4 * d_z
        self.mem_proj = nn.Linear(d_h, d_z)
        self.ln_s = nn.LayerNorm(d_z)
        self.self_attn = nn.MultiheadAttention(d_z, n_heads, batch_first=True, dropout=dropout)
        self.ln_c = nn.LayerNorm(d_z)
        self.cross_attn = nn.MultiheadAttention(d_z, n_heads, batch_first=True, dropout=dropout)
        self.ln_f = nn.LayerNorm(d_z)
        self.ffn = nn.Sequential(nn.Linear(d_z, d_ff), nn.GELU(), nn.Dropout(dropout),
                                 nn.Linear(d_ff, d_z))
        self.drop = nn.Dropout(dropout)

    def forward(self, Z, zmask, mem, mmask):
        kp_z, kp_m = ~zmask.bool(), ~mmask.bool()
        u = self.self_attn(self.ln_s(Z), self.ln_s(Z), self.ln_s(Z),
                           key_padding_mask=kp_z, need_weights=False)[0]
        z1 = Z + self.drop(u)
        M = self.mem_proj(mem)
        c = self.cross_attn(self.ln_c(z1), M, M, key_padding_mask=kp_m, need_weights=False)[0]
        z2 = z1 + self.drop(c)
        return z2 + self.ffn(self.ln_f(z2))


class RecurrentGraft(nn.Module):
    """Z_0 tokens are 64-dim: the global token is s_0 itself, candidate tokens are e_j lifted by a
    trainable input projection. Reading back applies a trainable output projection so the FROZEN
    heads receive exactly the d_s=64 / d_e=32 they were built for. At t=0 the raw frozen s_0/e_0
    are used directly, so R0 reproduces the seed artifact exactly."""

    def __init__(self, base: Interface, d_s: int, d_e: int, m_cap: int,
                 T: int = T_STEPS, **kw):
        super().__init__()
        self.base = base
        self.T, self.d_s, self.d_e, self.m_cap = T, d_s, d_e, m_cap
        self.in_e = nn.Linear(d_e, d_s)      # trainable interface projection, part of R_phi
        self.out_e = nn.Linear(d_s, d_e)     # trainable readout projection
        self.block = RecurrentRefinement(d_s, base.graft.row_proj[0].in_features // 6, **kw)

    def freeze_inherited(self):
        for p in self.base.parameters():
            p.requires_grad_(False)
        return self

    def z0(self, H):
        s, e = self.base.graft(H)
        return torch.cat([s.unsqueeze(1), self.in_e(e)], 1)

    def rollout(self, H, mem, mmask, collect=True):
        Z = self.z0(H)
        zmask = torch.cat([torch.ones(Z.shape[0], 1), (H["cand_mask"] > 0).float()], 1)
        states, deltas, cur = ([Z] if collect else []), [], Z
        for _ in range(self.T):
            nxt = self.block(cur, zmask, mem, mmask)
            deltas.append(float((nxt - cur).pow(2).mean().sqrt()))
            cur = nxt
            if collect:
                states.append(cur)
        return (states if collect else [cur]), deltas

    def read(self, Z, H, depth=0):
        B = Z.shape[0]
        if depth == 0:
            s, e = self.base.graft(H)
            s, e = s, e * H["cand_mask"].unsqueeze(-1)
        else:
            s = Z[:, 0, :self.d_s]
            e = self.out_e(Z[:, 1:, :]) * H["cand_mask"].unsqueeze(-1)
        g, c, a = self.base.heads(s, e, H["cand_mask"])
        return s, e, g, c, a

    def term(self, Z, H, gg, cc, a_idx, pi_g, pi_c, sig0, depth):
        """Frozen Phase 3 supervision semantics, evaluated at this depth."""
        bm = H["cand_mask"] > 0
        _, _, go, co, al = self.read(Z, H, depth)
        gl = [source_group_loss(head_terms_global(go, gg, ns, pi_g[sid], None), pi_g[sid])
              for sid, ns in GLOBAL_GROUPS.items()]
        cl = [source_group_loss(head_terms_cand(co, cc, ns, pi_c, bm), pi_c[ns[0]])
              for sid, ns in CAND_GROUPS.items()]
        A = action_loss(al, a_idx) if al is not None else None
        parts = {"S": family_balanced_loss(gl), "E": family_balanced_loss(cl), "A": A,
                 "CF": torch.tensor(0.0), "pair_S": torch.tensor(0.0),
                 "pair_E": torch.tensor(0.0), "pair_A": torch.tensor(0.0),
                 "var": variance_floor_loss(Z[:, 0, :self.d_s], sig0)}
        return parts, gl, cl


def balanced_criterion(parts, gl, cl):
    return float(j_select(family_balanced_loss(gl), family_balanced_loss(cl)))


# ------------------------------------------------------------------ evaluation
@torch.no_grad()
def evaluate(model, dv, tr, pair_H, rp, pi_g, pi_c, sig0, n_pairs=332):
    model.eval()
    idx = torch.arange(dv["n_rows"])
    H, gg, cc = pack(dv, idx)
    mem, mmask = gather_memory(dv, idx)
    states, deltas = model.rollout(H, mem, mmask)
    valid = H["cand_mask"] > 0
    astar = dv["action_index"]
    sel = astar >= 0
    rows = sel.nonzero().flatten().tolist()
    cands = dv["cand_actions"]

    per_depth = []
    for t, Z in enumerate(states):
        s, e, go, co, al = model.read(Z, H, t)
        rec = {"t": t, "sources": {}, "aliases": {}, "endpoint": {}, "diagnostics": {}}
        for sid, names in GLOBAL_GROUPS.items():
            for n in names:
                y = gg[n][:, 0]
                sup = ~torch.isnan(y)
                if n == COUNT_TARGET:
                    pr = torch.sigmoid(go[n][:, 0][sup])
                    mm = ordinal_metrics(y[sup], pr)
                    mm.update({"scored_channels": [0], "train_prevalence": round(pi_g[sid], 4),
                               "trivial_exact_count": round(float(
                                   y[sup].float().gt(0.5).float().mean()), 4)})
                    mm["beats_trivial"] = bool(mm["exact_count_accuracy"]
                                               > mm["trivial_exact_count"] + 0.01)
                    r = mm
                else:
                    r = eval_head(go[n][:, 0][sup], y[sup], pi_g[sid])
                if n in ALIAS:
                    r = dict(r, SAME_CANONICAL_SOURCE=ALIAS[n], independent_target=False)
                    rec["aliases"][n] = r
                else:
                    rec["sources"][sid] = r
        for sid, names in CAND_GROUPS.items():
            for n in names:
                lg = co[n]
                if lg.shape[-1] == 1:
                    lg = lg.squeeze(-1)
                v = (~torch.isnan(cc[n])) & valid
                r = eval_head(lg[v], cc[n][v], pi_c[n])
                r["valid_candidates"] = int(v.sum())
                if n in ALIAS:
                    r = dict(r, SAME_CANONICAL_SOURCE=ALIAS[n], independent_target=False)
                    rec["aliases"][n] = r
                else:
                    rec["sources"][sid] = r
        ep = {"chance": round(1.0 / M_CAP, 4), "n_endpoint_worlds": int(sel.sum()),
              "coverage": round(float(sel.sum()) / dv["n_rows"], 4),
              "by_action_type": {}, "folded_into_state_score": False}
        if int(sel.sum()) > 0:
            pred = al[sel].reshape(int(sel.sum()), -1).argmax(1)
            tgt = astar[sel]
            ep["action_top1_accuracy"] = round(float((pred == tgt).float().mean()), 4)
            for t_name in ACTION_TYPES:
                hit = torch.tensor([cands[i][int(j)] is not None
                                    and cands[i][int(j)].get("type") == t_name
                                    for i, j in zip(rows, tgt.tolist())])
                if int(hit.sum()):
                    ep["by_action_type"][t_name] = {
                        "n": int(hit.sum()),
                        "accuracy": round(float((pred[hit] == tgt[hit]).float().mean()), 4)}
        rec["endpoint"] = ep
        sig = s.std(dim=0, unbiased=False)
        rec["diagnostics"]["D_s"] = round(float(sig.mean()), 6)
        nv = valid.sum(1)
        multi = nv >= 2
        ew = e[multi]
        within = (ew - ew.mean(1).unsqueeze(1)).pow(2).sum(-1)
        between = (ew.mean(1) - ew.mean(1).mean(0, keepdim=True)).pow(2).sum(-1).mean()
        wv = float((within * valid[multi].float()).sum() / valid[multi].float().sum().clamp(min=1))
        rec["diagnostics"]["candidate_conditioning"] = {
            "ratio_within_over_between": round(wv / max(float(between), 1e-9), 3),
            "within_world_e_variance": round(wv, 6),
            "e_candidate_conditioned": bool(wv > 1e-8)}
        per_depth.append(rec)

    # renderer 2x2 correctness at t=0 and t=4
    rend = {}
    for t in (0, T_STEPS):
        acc = {}
        for n in [x for v in GLOBAL_GROUPS.values() for x in v] + ["candidate_legal"]:
            acc[n] = [0, 0, 0, 0, 0]
        acc["action"] = [0, 0, 0, 0, 0]
        npair = 0
        for p in rp[:n_pairs]:
            Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
            if Ha is None or Hb is None or not alignment_ok(dv, p):
                continue
            base_id = p["a"]["world_id"].split("@")[0]
            gi = dv["world_ids"].index(base_id)
            ma, mka = gather_memory(dv, torch.tensor([gi]))
            mb, mkb = gather_memory(dv, torch.tensor([gi]))
            za = model.rollout(Ha, ma, mka)[0][t]
            zb = model.rollout(Hb, mb, mkb)[0][t]
            _, _, ga, ca, aa = model.read(za, Ha, t)
            _, _, gb, cb, ab = model.read(zb, Hb, t)
            for n in acc:
                if n == "action":
                    truth = dv["action_index"][gi]
                    if truth < 0:
                        continue
                    pa = int(aa.reshape(-1, M_CAP).argmax(1)[0])
                    pb = int(ab.reshape(-1, M_CAP).argmax(1)[0])
                elif n in ga:
                    truth = float(gg[n][gi, 0])
                    if truth != truth:
                        continue
                    pa = int(ga[n].reshape(-1)[0] > 0)
                    pb = int(gb[n].reshape(-1)[0] > 0)
                else:
                    lg_a = ca[n].squeeze(-1) if ca[n].shape[-1] == 1 else ca[n]
                    truth = float(cc[n][gi, 0])
                    if truth != truth or not bool(valid[gi, 0]):
                        continue
                    pa = int(lg_a[0, 0] > 0)
                    pb = int(cb[n].squeeze(-1)[0, 0] > 0) if cb[n].shape[-1] == 1 \
                        else int(cb[n][0, 0] > 0)
                ca_, cb_ = (pa == truth), (pb == truth)
                a_ = acc[n]
                a_[0] += int(ca_ and cb_); a_[1] += int(ca_ and not cb_)
                a_[2] += int(cb_ and not ca_); a_[3] += int(not ca_ and not cb_)
                a_[4] += int(pa != pb)
            npair += 1
        rend[f"t{t}"] = {"pairs": npair, "per_target": {
            n: {"both_correct": a[0], "first_only_correct": a[1], "second_only_correct": a[2],
                "both_wrong": a[3], "disagreement": a[4],
                "paired_accuracy": round(a[0] / max(sum(a[:4]), 1), 4)}
            for n, a in acc.items() if sum(a[:4]) > 0}}

    # ---- compute diagnostics
    idx_b = torch.arange(min(256, dv["n_rows"]))
    Hb, _, _ = pack(dv, idx_b)
    memb, mmaskb = gather_memory(dv, idx_b)
    comp = {"trainable_recurrent_parameters": sum(q.numel() for n_, q in model.named_parameters()
                                              if not n_.startswith("base.")),
            "frozen_inherited_parameters": sum(p.numel() for p in model.base.parameters()),
            "d_z": model.block.mem_proj.out_features, "T": model.T,
            "update_magnitude_delta_t": [round(x, 6) for x in deltas],
            "note": "Delta_t = RMS(Z_{t+1} - Z_t) on the full DEV population"}
    with torch.no_grad():
        for _ in range(2):
            model.rollout(Hb, memb, mmaskb)
        ts = []
        for _ in range(8):
            t0 = time.perf_counter()
            model.rollout(Hb, memb, mmaskb, collect=False)
            ts.append((time.perf_counter() - t0) * 1000.0)
        ts.sort()
        comp["inference_latency_batch256_ms"] = {
            "per_step_median": round(ts[len(ts) // 2] / T_STEPS, 3),
            "total_T4_median": round(ts[len(ts) // 2], 3)}
    comp["training_seconds"] = None
    comp["peak_gpu_bytes"] = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
    return per_depth, rend, comp


def build_receipt(args, model, tr, dv, seed_path, n_train, n_frozen, hist, best, per_depth,
                  rend, comp, pi_g, pi_c, w, elapsed):
    import hashlib

    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    comp["training_seconds"] = round(elapsed, 2)
    reg = json.loads((P4.parent / "phase3" / "target-source-registry.json").read_text())
    gsrc = [s for s in GLOBAL_GROUPS]
    csrc = [s for s in CAND_GROUPS]
    rec = {
        "abi": "phase4a-semantic-interface/receipt-v0.1",
        "lane": "bidirectional (Lepori)", "arm": "R4 (shared-weight recurrent refinement)",
        "question": "Can shared-weight recurrent latent refinement turn the state already "
                    "accessible to this frozen substrate into better global semantic and action "
                    "computation?",
        "carry_forward": {
            "seed_artifact": str(seed_path),
            "seed_sha256": sha(seed_path),
            "why_this_seed": "P3-BALANCED is the terminal objective-only construction for this "
                             "lane and preserves the strongest earned candidate capability "
                             "while establishing the global-path failure. P2-CONSIST is preserved "
                             "unmerged as a frozen reference.",
            "frozen_reference_not_merged": "P2-CONSIST",
            "inherited_graft_frozen": True, "output_heads_frozen": True,
            "backbone_frozen": True,
            "trained_parameters": "R_phi only",
        },
        "candidate_universe": {"m_max": M_CAP, "rule": "retain every canonical candidate",
                               "truncated": False},
        "recurrent_state": {
            "Z_0": "[s_0 ; e_1,0 ; ... ; e_m,0]", "tokens": 1 + M_CAP, "d_z": comp["d_z"],
            "padded_candidates": "masked in self-attention and excluded from every loss",
            "block": "LN -> SelfAttn -> residual; LN -> CrossAttn(frozen H) -> residual; "
                     "LN -> FFN -> residual",
            "shared_across_depths": True, "T": T_STEPS,
            "cross_attention_memory": "the 6 pooled surface vectors plus the row's entity-span "
                                      "vectors, i.e. the frozen substrate outputs; nothing new "
                                      "extracted",
            "excluded": ["stochastic transitions", "adaptive halting", "IHA", "LoRA",
                         "new substrate layers", "new feature surfaces", "parallel particles",
                         "state merging", "sparse expansion", "backbone tuning", "self-play"],
        },
        "training_objective": {
            "form": "L_recurrent = L(Z_4) + 0.25 * (1/3) * sum_{t=1..3} L(Z_t)",
            "intermediate_coefficient": INTERMEDIATE_COEF,
            "tuned_from_DEV": False,
            "Z_0_receives_recurrent_loss": False,
            "per_depth_loss": "the frozen Phase 3 objective: unique-source balanced BCE, 0.5 L_A, "
                              "0.5 L_CF (dormant), 0.25 L_pair, 0.05 L_var",
            "objective_redesign": False,
        },
        "training_configuration": {"optimizer": "AdamW", "lr": args.lr, "schedule": "cosine",
                                   "bs": args.bs, "epochs": args.epochs, "seed": args.seed,
                                   "grad_clip": 1.0, "n_heads": args.heads,
                                   "train_rows": tr["n_rows"], "dev_rows": dv["n_rows"]},
        "selection": {"criterion": "J_select at t=4, the frozen Phase 3 rule",
                      "best_epoch": best["epoch"], "no_depth_selected": True,
                      "note": "Z_1..Z_3 are reported at inference without selecting among them"},
        "results_by_depth": per_depth,
        "training_history": hist,
        "renderer_correctness_by_depth": rend,
        "computational_diagnostics": comp,
        "compute_depth_curve_note": "one training run, shared block, depths 0..4 all reported; "
                                    "no depth sweep and no per-depth selection",
        "protected": {"PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
                      "BACKBONE_TUNED": False, "NEW_SURFACES": False, "NEW_TARGETS": False,
                      "NEW_SUPERVISION": False, "CANONICAL_SPLITS_UNCHANGED": True,
                      "CROSS_LANE_ONTOLOGY_RECONCILIATION": "deferred, per phase charter"},
        "elapsed_seconds": round(elapsed, 2),
    }
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", default="encoder")
    ap.add_argument("--seed-epoch", type=int, default=1)
    ap.add_argument("--train-limit", type=int, default=20000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-s", type=int, default=64)
    ap.add_argument("--d-e", type=int, default=32)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    tr = build("TRAIN", args.substrate, args.train_limit, prim_suffix=SUFFIX, m_cap=M_CAP)
    dv = build("DEV", args.substrate, args.dev_limit, prim_suffix=SUFFIX, m_cap=M_CAP)
    d_h = tr["H"]["row"].shape[-1]
    d_z = args.d_s

    base = Interface(d_h, args.d_s, args.d_e, tr["global_names"], tr["cand_names"], M_CAP)
    seed_path = P3DIR / f"ckpt-epoch-{args.seed_epoch}.pt"
    base.load_state_dict(torch.load(seed_path, map_location="cpu", weights_only=False))
    model = RecurrentGraft(base, args.d_s, args.d_e, M_CAP, T=T_STEPS,
                           n_heads=args.heads).freeze_inherited()

    sig0p = P4 / "sigma0.pt"
    if sig0p.is_file():
        sig0 = torch.load(sig0p, map_location="cpu", weights_only=False)
    else:
        with torch.no_grad():
            s0 = []
            for st in range(0, tr["n_rows"], 512):
                H, _, _ = pack(tr, torch.arange(st, min(st + 512, tr["n_rows"])))
                s0.append(base.graft(H)[0])
            sig0 = torch.cat(s0, 0).std(dim=0, unbiased=False)
        torch.save(sig0, sig0p)

    pair_H, rp = pair_context(dv, args.substrate, M_CAP)
    rp = [p for p in rp if pair_H(p["a"]["world_id"]) is not None
          and pair_H(p["b"]["world_id"]) is not None]

    g, c, mask = tr["global_labels"], tr["cand_labels"], tr["H"]["cand_mask"] > 0
    pi_g = {sid: float((g[n][:, 0] == 1).float().mean())
            for sid, ns in GLOBAL_GROUPS.items() for n in ns if n != COUNT_TARGET}
    pi_g["SRC-MISSING-INFO-PANEL"] = float(
        (g["missing_information_present"][:, 0] == 1).float().mean())
    pi_c = {n: float((c[n][mask] == 1).float().mean()) for ns in CAND_GROUPS.values()
            for n in ns}
    w = Phase3Weights()

    train_p = [p for p in model.parameters() if p.requires_grad]
    n_train = sum(p.numel() for p in train_p)
    n_frozen = sum(p.numel() for p in model.parameters() if not p.requires_grad)
    opt = torch.optim.AdamW(train_p, lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, max(1, n // args.bs) * args.epochs)
    print(f"seed={seed_path.name} d_z={d_z} T={T_STEPS} recurrent_trainable={n_train} "
          f"inherited_frozen={n_frozen} pairs={len(rp)}", flush=True)

    hist, ck = [], {}
    for ep in range(args.epochs):
        model.train()
        model.base.eval()
        perm = torch.randperm(n)
        agg, nb, dsum, dn = {}, 0, [0.0] * T_STEPS, 0
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, gg, cc = pack(tr, idx)
            mem, mmask = gather_memory(tr, idx)
            states, deltas = model.rollout(H, mem, mmask)
            tot, det = None, {}
            for i, Z in enumerate(states[1:]):
                weight = 1.0 if i == T_STEPS - 1 else INTERMEDIATE_COEF / (T_STEPS - 1)
                parts, gl, cl = model.term(Z, H, gg, cc, tr["action_index"][idx],
                                           pi_g, pi_c, sig0, i + 1)
                if rp:
                    p = rp[int(torch.randint(len(rp), (1,)))]
                    Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                    if Ha is not None and Hb is not None:
                        gi = dv["world_ids"].index(p["a"]["world_id"].split("@")[0])
                        mA, kA = gather_memory(dv, torch.tensor([gi]))
                        zA = model.rollout(Ha, mA, kA)[0][i + 1]
                        zB = model.rollout(Hb, mA, kA)[0][i + 1]
                        _, _, ga, ca, aa = model.read(zA, Ha, i + 1)
                        _, _, gb, cb, ab = model.read(zB, Hb, i + 1)
                        pc = prediction_consistency_loss(
                            ga, gb, ca, cb, aa, ab, Ha["cand_mask"],
                            bool((tr["action_index"][idx] >= 0).any()), alignment_ok(dv, p))
                        parts.update({"pair_S": pc["S"], "pair_E": pc["E"], "pair_A": pc["A"]})
                t_i, d_i = phase3_total_loss(parts, w)
                t_i = t_i * weight
                tot = t_i if tot is None else tot + t_i
                for k, v in d_i.items():
                    det[k] = det.get(k, 0.0) + v * weight
            opt.zero_grad()
            tot.backward()
            torch.nn.utils.clip_grad_norm_(train_p, 1.0)
            opt.step()
            sched.step()
            nb += 1
            for k, v in det.items():
                agg[k] = agg.get(k, 0.0) + v
            for i, dlt in enumerate(deltas):
                dsum[i] += dlt
            dn += 1
        model.eval()
        with torch.no_grad():
            Hidx = torch.arange(dv["n_rows"])
            Hd, ggd, ccd = pack(dv, Hidx)
            memd, mmaskd = gather_memory(dv, Hidx)
            sd, dd = model.rollout(Hd, memd, mmaskd)
            J = []
            for t, Z in enumerate(sd):
                _, gl, cl = model.term(Z, Hd, ggd, ccd, dv["action_index"], pi_g,
                                       pi_c, sig0, t)
                J.append(round(balanced_criterion(None, gl, cl), 4))
        h = {"epoch": ep + 1, "n_batches": nb,
             **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
             "delta_t": [round(x / max(dn, 1), 6) for x in dsum],
             "J_select_by_depth": J}
        hist.append(h)
        ck[ep + 1] = {k[len("block."):]: v.detach().clone()
                      for k, v in model.state_dict().items() if k.startswith("block.")}
        torch.save(ck[ep + 1], P4 / f"ckpt-epoch-{ep+1}.pt")
        print(json.dumps(h), flush=True)

    best = min(hist, key=lambda x: x["J_select_by_depth"][-1])
    model.block.load_state_dict(ck[best["epoch"]])
    print(f"best epoch {best['epoch']} selected on J_select at t=4", flush=True)

    per_depth, rend, comp = evaluate(model, dv, tr, pair_H, rp, pi_g, pi_c, sig0)
    rec = build_receipt(args, model, tr, dv, seed_path, n_train, n_frozen, hist, best,
                        per_depth, rend, comp, pi_g, pi_c, w, time.perf_counter() - started)
    p = P4 / "phase4a-receipt.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    (P4 / "artifact-hashes.json").write_text(json.dumps({
        "receipt": __import__("hashlib").sha256(p.read_bytes()).hexdigest(),
        "checkpoints": {f"ckpt-epoch-{e}.pt":
                        __import__("hashlib").sha256((P4 / f"ckpt-epoch-{e}.pt")
                                                     .read_bytes()).hexdigest()
                        for e in range(1, args.epochs + 1)},
    }, indent=2) + "\n")
    print(json.dumps({"written": str(p), "best_epoch": best["epoch"],
                      "recurrent_trainable": n_train}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
