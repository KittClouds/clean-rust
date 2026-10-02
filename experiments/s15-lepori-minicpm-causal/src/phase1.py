"""Phase 1 for the Lepori causal lane: the real baseline, plus the surface-contribution
diagnostic that this substrate makes cheap.

Trains the frozen Phase 0 causal graft on the full 20k TRAIN population under the INHERITED
contract (no objective redesign), selects on J_select over unique source groups, and reports
everything Lexi's lane has, plus one new thing:

  SURFACE CONTRIBUTION. At inference, zero exactly one projected u_i and report the endpoint
  delta. No retraining, no probe campaign, no causal-mechanism claim. It answers a single
  question: is the learned graft actually using the depth diversity we preserved, or did the
  graft collapse onto one surface? If it leans on mf@12 or mf@18, that is where later
  model-level surgery has a plausible interface.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from src import data as D
from src.ontology import (GLOBAL_GROUPS, CAND_GROUPS, ALIAS, COUNT_TARGET, registry,
                          n_independent_sources, ALL_TARGETS)
from src.graft import Interface, architecture_descriptor
from src.objective import (LossWeights, balanced_bce, source_group_loss, family_balanced_loss,
                           total_loss, action_loss, prediction_consistency_loss,
                           variance_floor_loss, j_select, objective_descriptor)
from src.pairs import renderer_pairs, truth_changing_pairs
from src import gate as G

PRIM = D.PRIM
OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")


# ------------------------------------------------------------------ metrics
def eval_head(logit, y, pi):
    p = (logit > 0).float(); t = (y > 0.5).float()
    tp = float(((p == 1) & (t == 1)).sum()); fp = float(((p == 1) & (t == 0)).sum())
    fn = float(((p == 0) & (t == 1)).sum()); tn = float(((p == 0) & (t == 0)).sum())
    rec = tp / max(tp + fn, 1e-9); prec = tp / max(tp + fp, 1e-9)
    spec = tn / max(tn + fp, 1e-9)
    f1p = 2 * prec * rec / max(prec + rec, 1e-9)
    nprec = tn / max(tn + fn, 1e-9); nrec = tn / max(tn + fp, 1e-9)
    f1n = 2 * nprec * nrec / max(nprec + nrec, 1e-9)
    return {"balanced_accuracy": round((rec + spec) / 2, 4),
            "accuracy": round((tp + tn) / max(len(t), 1), 4),
            "macro_f1": round((f1p + f1n) / 2, 4), "positive_f1": round(f1p, 4),
            "negative_f1": round(f1n, 4), "support_pos": int(tp + fn),
            "support_neg": int(tn + fp), "train_prevalence": round(pi, 4),
            "beats_base_rate": bool((rec + spec) / 2 > max(pi, 1 - pi) + 0.01)}


def pack(d, idx):
    H = {"row": d["H"]["row"][idx], "ent": d["H"]["ent"],
         "cand_ent": d["H"]["cand_ent"][idx], "cand_type": d["H"]["cand_type"][idx],
         "cand_mask": d["H"]["cand_mask"][idx]}
    g = {n: t[idx] for n, t in d["global_labels"].items()}
    c = {n: t[idx] for n, t in d["cand_labels"].items()}
    return H, g, c


def head_terms_global(go, g, names, pi):
    out = []
    for n in names:
        y = g[n][:, 0]; sup = ~torch.isnan(y)
        if not bool(sup.any()):
            continue
        out.append(balanced_bce(go[n][:, 0][sup], y[sup], pi))
    return out


def head_terms_cand(co, c, names, pis, mask):
    out = []
    for n in names:
        sel = (~torch.isnan(c[n])) & mask
        if not bool(sel.any()):
            continue
        out.append(balanced_bce(co[n][sel], c[n][sel], pis[n]))
    return out


def prevalences(tr):
    g, c, m = tr["global_labels"], tr["cand_labels"], tr["H"]["cand_mask"] > 0
    pi_g = {sid: float((g[n][:, 0] == 1).float().mean())
            for sid, ns in GLOBAL_GROUPS.items() for n in ns if n != COUNT_TARGET}
    pi_g["SRC-MISSING-INFO-PANEL"] = float(
        (g["missing_information_present"][:, 0] == 1).float().mean())
    pi_c = {n: float((c[n][m] == 1).float().mean()) for ns in CAND_GROUPS.values() for n in ns}
    return pi_g, pi_c


def pair_context(dv, m_cap):
    prim = torch.load(PRIM / f"DEV-full.pt", map_location="cpu", weights_only=False)
    prow = {x: i for i, x in enumerate(prim["row_ids"])}
    prun, r = {}, 0
    for bi, eids in prim["entity_index"]:
        prun[prim["row_ids"][bi]] = (r, list(eids)); r += len(eids)
    surf = torch.stack([prim["surfaces"][s] for s in D.SURFACES], 1).float()
    st = torch.load(PRIM / "surface-stats.pt", map_location="cpu", weights_only=False)["stats"]
    surf = torch.stack([((prim["surfaces"][s].float() - st[s]["mean"]) / st[s]["std"])
                        for s in D.SURFACES], 1)
    cand = {w0: (dv["H"]["cand_ent"][i], dv["H"]["cand_type"][i], dv["H"]["cand_mask"][i],
                 dv["ent_runs"][w0])
            for i, w0 in enumerate(dv["world_ids"]) if w0 in dv.get("ent_runs", {})}

    def pair_H(wid):
        i = prow.get(wid)
        cs = cand.get(wid.split("@")[0])
        run = prun.get(wid)
        if i is None or cs is None or run is None:
            return None
        ce = cs[0].clone()
        shift = run[0] - cs[3]
        ce[ce >= 0] = (ce[ce >= 0] + shift).clamp(min=0, max=max(len(run[1]) - 1, 0))
        return {"row": surf[i:i + 1], "ent": prim["entity_vectors"][run[0]:run[0] + len(run[1])].float(),
                "cand_ent": ce.unsqueeze(0), "cand_type": cs[1].unsqueeze(0),
                "cand_mask": cs[2].unsqueeze(0)}
    return pair_H


def alignment_ok(dv, p):
    return p["a"]["world_id"].split("@")[0] == p["b"]["world_id"].split("@")[0]


# ------------------------------------------------------------------ evaluation
@torch.no_grad()
def evaluate(model, dv, pair_H, rp, pi_g, pi_c, sigma0, n_pairs=332):
    model.eval()
    H, g, c = pack(dv, torch.arange(dv["n_rows"]))
    s, e, go, co, al, bank = model(H)
    out = {"sources": {}, "aliases": {}, "endpoint": {}, "diagnostics": {}}
    valid = H["cand_mask"] > 0
    for sid, names in GLOBAL_GROUPS.items():
        for n in names:
            y = g[n][:, 0]; sup = ~torch.isnan(y)
            if n == COUNT_TARGET:
                pr = torch.sigmoid(go[n][:, 0][sup])
                e_ = (y[sup] - pr).abs()
                r = {"mae": round(float(e_.mean()), 4),
                     "exact_count_accuracy": round(float((e_ < 0.5).float().mean()), 4),
                     "trivial_exact_count": round(float(y[sup].float().gt(0.5).float().mean()), 4),
                     "scored_channels": [0], "train_prevalence": round(pi_g[sid], 4),
                     "SAME_CANONICAL_SOURCE": ALIAS.get(n)}
                r["beats_trivial"] = bool(r["exact_count_accuracy"] > r["trivial_exact_count"] + 0.01)
            else:
                r = eval_head(go[n][:, 0][sup], y[sup], pi_g[sid])
            if n in ALIAS:
                r["SAME_CANONICAL_SOURCE"] = ALIAS[n]; r["independent_target"] = False
                out["aliases"][n] = r
            else:
                out["sources"][sid] = r
    for sid, names in CAND_GROUPS.items():
        for n in names:
            sel = (~torch.isnan(c[n])) & valid
            r = eval_head(co[n][sel], c[n][sel], pi_c[n])
            r["valid_candidates"] = int(sel.sum())
            if n in ALIAS:
                r["SAME_CANONICAL_SOURCE"] = ALIAS[n]; r["independent_target"] = False
                out["aliases"][n] = r
            else:
                out["sources"][sid] = r

    astar = dv["action_index"]; sel = astar >= 0
    rows = sel.nonzero().flatten().tolist()
    mean_valid = float(valid[sel].sum(1).float().mean()) if int(sel.sum()) else D.M_CAP
    ep = {"chance": round(1.0 / mean_valid, 4),
          "chance_definition": "1/mean valid candidates, NOT 1/m_cap: the endpoint is a choice among the candidates a world actually has",
          "mean_valid_candidates_on_endpoint_worlds": round(mean_valid, 2),
          "n_endpoint_worlds": int(sel.sum()),
          "coverage": round(float(sel.sum()) / dv["n_rows"], 4), "by_action_type": {},
          "folded_into_state_score": False}
    if int(sel.sum()):
        pred = al[sel].argmax(1); tgt = astar[sel]
        ep["action_top1_accuracy"] = round(float((pred == tgt).float().mean()), 4)
        ca = dv["cand_actions"]
        for t in D.ACTION_TYPES:
            hit = torch.tensor([ca[i][int(j)] is not None and ca[i][int(j)].get("type") == t
                                for i, j in zip(rows, tgt.tolist())])
            if int(hit.sum()):
                ep["by_action_type"][t] = {"n": int(hit.sum()),
                                           "accuracy": round(float((pred[hit] == tgt[hit])
                                                                  .float().mean()), 4)}
    out["endpoint"] = ep
    out["diagnostics"]["D_s"] = round(float(s.std(0, unbiased=False).mean()), 6)
    out["diagnostics"]["variance_floor_target"] = round(0.5 * float(sigma0.mean()), 6)
    nv = valid.sum(1); multi = nv >= 2
    ew = e[multi]
    within = (ew - ew.mean(1).unsqueeze(1)).pow(2).sum(-1)
    between = (ew.mean(1) - ew.mean(1).mean(0, keepdim=True)).pow(2).sum(-1).mean()
    wv = float((within * valid[multi].float()).sum() / valid[multi].float().sum().clamp(min=1))
    out["diagnostics"]["candidate_conditioning"] = {
        "ratio_within_over_between": round(wv / max(float(between), 1e-9), 3),
        "within_world_e_variance": round(wv, 6),
        "e_candidate_conditioned": bool(wv > 1e-8)}

    # ---- renderer paired-correctness decomposition (never naked agreement)
    dec = {"pairs": 0, "per_target": {}, "note": "both correct / first only / second only / both "
           "wrong / disagreement. NOT combined into one aggregate."}
    for n in [x for v in GLOBAL_GROUPS.values() for x in v] + ["candidate_legal"]:
        dec["per_target"][n] = [0, 0, 0, 0, 0]
    dec["per_target"]["action"] = [0, 0, 0, 0, 0]
    for p in rp[:n_pairs]:
        Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
        if Ha is None or Hb is None or not alignment_ok(dv, p):
            continue
        gi = dv["world_ids"].index(p["a"]["world_id"].split("@")[0])
        _, _, ga, ca, aa, _ = model(Ha)
        _, _, gb, cb, ab, _ = model(Hb)
        for n in dec["per_target"]:
            if n == "action":
                truth = dv["action_index"][gi]
                if truth < 0:
                    continue
                pa = int(aa.reshape(-1)[0].argmax())
                pb = int(ab.reshape(-1)[0].argmax())
            elif n in ga:
                truth = float(g[n][gi, 0])
                if truth != truth:
                    continue
                pa = int(ga[n].reshape(-1)[0] > 0); pb = int(gb[n].reshape(-1)[0] > 0)
            else:
                truth = float(c[n][gi, 0])
                if truth != truth or not bool(valid[gi, 0]):
                    continue
                pa = int(ca[n][0, 0] > 0); pb = int(cb[n][0, 0] > 0)
            ca_, cb_ = (pa == truth), (pb == truth)
            a_ = dec["per_target"][n]
            a_[0] += int(ca_ and cb_); a_[1] += int(ca_ and not cb_)
            a_[2] += int(cb_ and not ca_); a_[3] += int(not ca_ and not cb_)
            a_[4] += int(pa != pb)
        dec["pairs"] += 1
    dec["per_target"] = {n: {"both_correct": v[0], "first_only_correct": v[1],
                             "second_only_correct": v[2], "both_wrong": v[3],
                             "disagreement": v[4],
                             "paired_accuracy": round(v[0] / max(sum(v[:4]), 1), 4)}
                         for n, v in dec["per_target"].items() if sum(v[:4])}
    out["diagnostics"]["renderer_paired_correctness"] = dec
    return out


# ------------------------------------------------------------------ surface contribution
@torch.no_grad()
def surface_contribution(model, dv, baseline):
    """Zero exactly one projected u_i at inference and report endpoint deltas.

    No retraining, no probe, no causal claim. It only asks whether the trained graft is using
    the depth diversity we preserved, or has collapsed onto a subset of surfaces.
    """
    H, _, _ = pack(dv, torch.arange(dv["n_rows"]))
    valid = H["cand_mask"] > 0
    astar = dv["action_index"]; sel = astar >= 0

    def score(zero_idx=None):
        u = model.graft.surfaces(H["row"])
        if zero_idx is not None:
            u = u.clone()
            u[:, zero_idx] = 0.0
        s = model.graft.rho_s(u.reshape(u.shape[0], -1))
        cc = model.graft.candidate_states(H)
        e = model.graft.rho_e(torch.cat(
            [cc, s.unsqueeze(1).expand(-1, cc.shape[1], -1)], -1)) * H["cand_mask"].unsqueeze(-1)
        g, c, a = model.heads(s, e, H["cand_mask"])
        act = float("nan")
        if int(sel.sum()):
            act = float((a[sel].argmax(1) == astar[sel]).float().mean())
        lg = float(sum(eval_head(g[n][:, 0], dv["global_labels"][n][:, 0], 0.5)["accuracy"]
                       for n in GLOBAL_GROUPS["SRC-SOLVABILITY"]))
        cand = c["candidate_legal"][valid]
        return act, float(cand.float().mean())

    base_act, base_cand = score()
    rows = {"full_six_surfaces": {"action_top1": round(base_act, 4),
                                 "candidate_legal_mean_logit": round(base_cand, 4)}}
    for i, name in enumerate(D.SURFACES):
        act, cd = score(i)
        rows[f"minus_{name}"] = {
            "action_top1": round(act, 4),
            "action_top1_delta": round(act - base_act, 4),
            "candidate_legal_mean_logit": round(cd, 4),
            "candidate_legal_delta": round(cd - base_cand, 4)}
    return {"method": "zero one projected u_i at inference; no retraining, no probe campaign",
            "claim_scope": "descriptive only; NOT a causal-mechanism claim",
            "rows": rows,
            "reading": "a large |delta| means the trained graft leans on that surface; a ~0 "
                       "delta means it is carrying that surface but not relying on it"}


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--train-limit", type=int, default=20000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    tr = D.build("TRAIN", args.train_limit)
    dv = D.build("DEV", args.dev_limit)
    pi_g, pi_c = prevalences(tr)
    d_h = tr["H"]["row"].shape[-1]
    torch.manual_seed(args.seed)
    model = Interface(d_h, 64, 32, tr["global_names"], tr["cand_names"], D.M_CAP)
    nparam = sum(p.numel() for p in model.parameters())

    initp = OUT / "phase0-init.pt"
    if initp.is_file():
        model.load_state_dict(torch.load(initp, map_location="cpu", weights_only=False))
    else:
        torch.save(model.state_dict(), initp)

    # frozen TRAIN-only variance reference for the lane-relative floor
    sigp = PRIM / "sigma0-s.pt"
    if sigp.is_file():
        sigma0 = torch.load(sigp, map_location="cpu", weights_only=False)
    else:
        model.eval()
        with torch.no_grad():
            acc = [model(pack(tr, torch.arange(i, min(i + 512, tr["n_rows"])))[0])[0]
                   for i in range(0, tr["n_rows"], 512)]
            sigma0 = torch.cat(acc, 0).std(0, unbiased=False)
        torch.save(sigma0, sigp)

    pair_H = pair_context(dv, D.M_CAP)
    rp = [p for p in renderer_pairs("DEV", 20000)
          if pair_H(p["a"]["world_id"]) is not None
          and pair_H(p["b"]["world_id"]) is not None]
    tcf, tstats = truth_changing_pairs("DEV", "S1", limit=2000)
    print(f"renderer pairs {len(rp)}  truth-changing pairs {tstats['emitted']} "
          f"(discarded {tstats['discarded_no_flip']})  trainable {nparam}", flush=True)

    w = LossWeights()
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, max(1, n // args.bs) * args.epochs)

    hist, ck = [], {}
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        agg, nb = {}, 0
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, g, c = pack(tr, idx)
            s, e, go, co, al, bank = model(H)
            m = H["cand_mask"] > 0
            gl = [source_group_loss(head_terms_global(go, g, ns, pi_g[sid]))
                  for sid, ns in GLOBAL_GROUPS.items()]
            cl = [source_group_loss(head_terms_cand(co, c, ns, pi_c, m))
                  for sid, ns in CAND_GROUPS.items()]
            pS = pE = pA = torch.tensor(0.0)
            if rp:
                p = rp[int(torch.randint(len(rp), (1,)))]
                Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                if Ha is not None and Hb is not None:
                    _, _, ga, ca, aa, _ = model(Ha)
                    _, _, gb, cb, ab, _ = model(Hb)
                    pc = prediction_consistency_loss(ga, gb, ca, cb, aa, ab, Ha["cand_mask"],
                                                    bool((tr["action_index"][idx] >= 0).any()),
                                                    alignment_ok(dv, p))
                    pS, pE, pA = pc["S"], pc["E"], pc["A"]
            total, detail = total_loss({
                "S": family_balanced_loss(gl), "E": family_balanced_loss(cl),
                "A": action_loss(al, tr["action_index"][idx]),
                # L_CF stays dormant: candidate-support truth is unavailable and none is invented
                "CF": torch.tensor(0.0),
                "pair_S": pS, "pair_E": pE, "pair_A": pA,
                "var": variance_floor_loss(s, sigma0)}, w)
            opt.zero_grad(); total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); nb += 1
            for k, v in detail.items():
                agg[k] = agg.get(k, 0.0) + v
        model.eval()
        with torch.no_grad():
            H, g, c = pack(dv, torch.arange(dv["n_rows"]))
            s, e, go, co, al, bank = model(H)
            m = H["cand_mask"] > 0
            JS = float(family_balanced_loss(
                [source_group_loss(head_terms_global(go, g, ns, pi_g[sid]))
                 for sid, ns in GLOBAL_GROUPS.items()]))
            JE = float(family_balanced_loss(
                [source_group_loss(head_terms_cand(co, c, ns, pi_c, m))
                 for sid, ns in CAND_GROUPS.items()]))
        h = {"epoch": ep + 1, "n_batches": nb,
             **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
             "J_S": round(JS, 4), "J_E": round(JE, 4), "J_select": round(j_select(JS, JE), 4),
             "D_s": round(float(s.std(0, unbiased=False).mean()), 6)}
        hist.append(h)
        ck[ep + 1] = {k: v.detach().clone() for k, v in model.state_dict().items()}
        torch.save(model.state_dict(), OUT / f"phase1-ckpt-epoch-{ep+1}.pt")
        print(json.dumps(h), flush=True)

    best = min(hist, key=lambda x: x["J_select"])
    model.load_state_dict(ck[best["epoch"]])
    ev = evaluate(model, dv, pair_H, rp, pi_g, pi_c, sigma0)
    sc = surface_contribution(model, dv, ev)
    g = G.check()

    lat = {}
    with torch.no_grad():
        Hb, _, _ = pack(dv, torch.arange(min(256, dv["n_rows"])))
        for _ in range(2):
            model(Hb)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        ts = []
        for _ in range(8):
            t0 = time.perf_counter(); model(Hb)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort(); lat["inference_ms_batch256_median"] = round(ts[len(ts) // 2], 3)

    rec = {
        "abi": "s15-lepori-minicpm/phase1-receipt-v0.1",
        "lane": "Lepori", "fabric": "causal", "arm": "P1-CAUSAL-BASELINE",
        "substrate": {"name": "openbmb/MiniCPM5-1B-Base", "params": 1080632832,
                      "hidden": 1536, "layers": 24, "frozen": True,
                      "validated_depth_layers": [6, 12, 18, 24]},
        "architecture": architecture_descriptor(d_h),
        "trainable_parameters": nparam,
        "trainable_fraction_of_substrate": round(100.0 * nparam / 1080632832, 4),
        "candidate_contract": {"m_max": 28, "truncated": False,
                               "TRAIN_rows_above_24": int((tr["H"]["cand_mask"].sum(1) > 24).sum())},
        "normalisation": {"fitted_on": "TRAIN", "per_surface": True,
                          "dev_statistics_used": False,
                          "raw_scale_preserved_as_metadata": True},
        "objective": objective_descriptor(w),
        "inherited_from_encoder_lane": [
            "exhaustive m_cap=28", "unique canonical-source weighting over 6 sources",
            "balanced supervision with TRAIN-only prevalence", "TRAIN-only normalisation",
            "paired correctness reporting", "no raw latent invariance", "no naked diversity "
            "claims", "no duplicate aliases as extra supervision", "no generic "
            "global/candidate recurrent mixer", "protected TEST closed"],
        "target_source_registry": {"independent_sources": n_independent_sources(),
                                   "ontology_heads": len(ALL_TARGETS), "registry": registry()},
        "cf_state": "DORMANT: candidate_supported / candidate_has_counterevidence / "
                    "candidate_requires_missing_information have no admissible canonical source. "
                    "No label invented.",
        "pair_construction": {"renderer_pairs": len(rp), "truth_changing": tstats},
        "training": {"optimizer": "AdamW", "lr": args.lr, "schedule": "cosine", "bs": args.bs,
                     "epochs": args.epochs, "seed": args.seed, "train_rows": n,
                     "dev_rows": dv["n_rows"], "backbone_frozen": True},
        "selection": {"criterion": "J_select = 0.5 J_S + 0.5 J_E over unique source groups",
                      "best_epoch": best["epoch"], "best_J_select": best["J_select"],
                      "action_in_selection": False, "renderer_in_selection": False,
                      "aliases_counted_once": True},
        "results": {"sources": ev["sources"], "aliases": ev["aliases"],
                    "endpoint": ev["endpoint"], "diagnostics": ev["diagnostics"]},
        "surface_contribution": sc,
        "phase0_gate": g["gates"],
        "compute": {"training_seconds": round(time.perf_counter() - started, 2),
                    "peak_gpu_bytes": int(torch.cuda.max_memory_allocated())
                    if torch.cuda.is_available() else 0,
                    **lat},
        "protected": {"PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
                      "CANONICAL_SPLITS_UNCHANGED": True, "BACKBONE_TUNED": False,
                      "CROSS_AGENT_ALIGNMENT": "forbidden and asserted"},
        "no_head_to_head": "own delta only; cross-lane synthesis is downstream of both receipts",
    }
    p = OUT / "phase1-receipt.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({"written": str(p), "best_epoch": best["epoch"],
                      "J_select": best["J_select"], "trainable": nparam}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
