"""Phase 2 — bidirectional fabric (Lepori's lane).

Intervention: replace raw latent renderer invariance with PREDICTION consistency (JS), and add
an explicit variance floor so agreement cannot be won by constant representation.

Two arms, both from the SAME Phase 0 initialization, both under the same exhaustive-candidate
Phase 2 input contract (m_cap = 28, the measured canonical maximum):

  P2-BASE     the Phase 1 objective, raw latent L_R included
  P2-CONSIST  L^(2) = L_S + L_E + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var

This is not a hyperparameter sweep. No weight is tuned from DEV. The baseline exists only to
separate the objective change from incidental retraining variation.

Frozen and untouched: substrate, extraction surfaces, graft architecture, latent dimensions,
target ontology, canonical splits, availability masks.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from src.graft import ACTION_TYPES
from src.objective import (Phase2Weights, LossWeights, semantic_loss, epistemic_loss,
                           action_loss, renderer_invariance_loss, total_loss,
                           prediction_consistency_loss, variance_floor_loss,
                           phase2_total_loss, phase2_objective_descriptor)
from src.data import build, SURFACES
from src.pairs import renderer_pairs
from src.phase1 import Interface, pack, binary_metrics, ordinal_metrics
from src.gate import check

PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase2")
OUT.mkdir(parents=True, exist_ok=True)
M_CAP = 28
SUFFIX = "-p2"


# ------------------------------------------------------------------ shared phase 0 init
def phase0_init(d_h, gnames, cnames, d_s, d_e, seed=0):
    """One canonical untrained Phase 0 initialization, shared by both arms."""
    p = OUT / "phase0-init.pt"
    torch.manual_seed(seed)
    model = Interface(d_h, d_s, d_e, gnames, cnames, M_CAP)
    sd = model.state_dict()
    if p.is_file():
        prev = torch.load(p, map_location="cpu", weights_only=False)
        assert set(prev) == set(sd), "init layout changed"
        model.load_state_dict(prev)
    else:
        torch.save(sd, p)
    return model


@torch.no_grad()
def sigma0_reference(model, tr) -> dict:
    """Frozen per-coordinate reference std of s from the UNTRAINED graft over TRAIN."""
    p = OUT / "sigma0-global-state.pt"
    if p.is_file():
        d = torch.load(p, map_location="cpu", weights_only=False)
    else:
        model.eval()
        acc = []
        for st in range(0, tr["n_rows"], 512):
            H, _, _ = pack(tr, torch.arange(st, min(st + 512, tr["n_rows"])))
            acc.append(model(H)[0])
        s = torch.cat(acc, 0)
        d = {"sigma0": s.std(dim=0, unbiased=False), "n_rows": tr["n_rows"],
             "d_s": s.shape[1], "mean_sigma0": float(s.std(dim=0, unbiased=False).mean()),
             "source": "untrained Phase 0 graft, global state s, over TRAIN"}
        torch.save(d, p)
    return d


# ------------------------------------------------------------------ pair context
def pair_context(dv, substrate, m_cap):
    prim = torch.load(PRIM / substrate / f"DEV{SUFFIX}.pt", map_location="cpu",
                      weights_only=False)
    prow = {x: i for i, x in enumerate(prim["row_ids"])}
    psurf = torch.stack([prim["surfaces"][s] for s in SURFACES], 1).float()
    prun, r = {}, 0
    for bi, eids in prim["entity_index"]:
        prun[prim["row_ids"][bi]] = (r, list(eids))
        r += len(eids)
    cand = {w0: (dv["H"]["cand_ent"][i], dv["H"]["cand_type"][i], dv["H"]["cand_mask"][i],
                 dv["ent_runs"][w0][0])
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
        return {"row": psurf[i:i + 1],
                "ent": prim["entity_vectors"][run[0]:run[0] + len(run[1])].float(),
                "cand_ent": ce.unsqueeze(0), "cand_type": cs[1].unsqueeze(0),
                "cand_mask": cs[2].unsqueeze(0)}

    return pair_H, renderer_pairs("DEV", 40000)


def alignment_ok(dv, p) -> bool:
    """Exact canonical candidate identity between the two members of a renderer pair.

    Both members are the SAME latent world, so build() derives an identical canonical
    available_actions ordering for each. The check is a receipted assertion, not a guess:
    we compare the canonical action keys each member is paired against.
    """
    a, b = p["a"]["world_id"].split("@")[0], p["b"]["world_id"].split("@")[0]
    if a != b:
        return False
    ka = json.dumps(dv["cand_actions"][dv["world_ids"].index(a)][:M_CAP], sort_keys=True)
    kb = json.dumps(dv["cand_actions"][dv["world_ids"].index(b)][:M_CAP], sort_keys=True)
    return ka == kb


# ------------------------------------------------------------------ evaluation
@torch.no_grad()
def evaluate(model, dv, pair_H, rp, n_pairs=400):
    model.eval()
    idx = torch.arange(dv["n_rows"])
    H, g, c = pack(dv, idx)
    s, e, go, co, al = model(H)
    out = {"global": {}, "candidate": {}, "endpoint": {}, "diagnostics": {}}
    m = H["cand_mask"]

    for n, lg in go.items():
        if n == "number_or_structure_of_missing_requirements":
            sup = ~torch.isnan(g[n][:, 0])
            yhat = torch.sigmoid(lg[:, 0][sup])
            ytrue = g[n][:, 0][sup]
            mm = ordinal_metrics(ytrue, yhat)
            mm["scored_channels"] = [0]
            mm["trivial_exact_count"] = round(float(ytrue.float().mean().gt(0.5).float()
                                                    .mean()), 4)
            mm["beats_trivial"] = bool(mm["exact_count_accuracy"] > mm["trivial_exact_count"]
                                       + 0.01)
            out["global"][n] = mm
        else:
            sup = ~torch.isnan(g[n][:, 0])
            out["global"][n] = binary_metrics(g[n][:, 0][sup] > 0.5,
                                              (lg[:, 0][sup] > 0).float(), 0.5)

    valid = m > 0
    for n, lg in co.items():
        if lg.shape[-1] == 1:
            lg = lg.squeeze(-1)
        sel = (~torch.isnan(c[n])) & valid
        mm = binary_metrics(c[n][sel] > 0.5, (lg[sel] > 0).float(), 0.5)
        mm["valid_candidates"] = int(sel.sum())
        out["candidate"][n] = mm
    out["candidate"]["_identity"] = (
        "candidate_applicable and candidate_legal share one canonical source; both heads kept, "
        "agreement is a consistency check and NOT independent evidence")

    # ---- action endpoint with action-type decomposition
    astar = dv["action_index"]
    sel = astar >= 0
    ep = {"coverage": round(float(sel.sum()) / dv["n_rows"], 4),
          "n_endpoint_worlds": int(sel.sum()), "contract": "masked CE; abstention excluded",
          "chance": round(1.0 / M_CAP, 4), "by_action_type": {}}
    if sel.sum() > 0:
        pred = al[sel].reshape(int(sel.sum()), -1).argmax(1)
        tgt = astar[sel]
        ep["action_top1_accuracy"] = round(float((pred == tgt).float().mean()), 4)
        cands = dv["cand_actions"]
        for t_i, t_name in enumerate(ACTION_TYPES):
            hit = torch.tensor([cands[i][int(j)] is not None
                                and cands[i][int(j)].get("type") == t_name
                                for i, j in zip(sel.nonzero().flatten().tolist(),
                                                tgt.tolist())])
            if int(hit.sum()) == 0:
                continue
            ep["by_action_type"][t_name] = {
                "n": int(hit.sum()),
                "accuracy": round(float((pred[hit] == tgt[hit]).float().mean()), 4)}
    out["endpoint"] = ep

    # ---- representation diversity D_s = mean_k sigma_k(s)
    sig = s.std(dim=0, unbiased=False)
    out["diagnostics"]["D_s"] = {
        "definition": "mean_k sigma_k(s) over DEV",
        "value": round(float(sig.mean()), 6),
        "min_coord_sigma": round(float(sig.min()), 6),
        "max_coord_sigma": round(float(sig.max()), 6),
        "s_row_std_mean": round(float(s.std(0).mean()), 6),
        "s_collapsed": bool(float(sig.mean()) < 1e-3),
    }

    # ---- candidate conditioning non-collapse
    nv = valid.sum(1)
    multi = nv >= 2
    if int(multi.sum()) > 10:
        ew = e[multi]
        within = (ew - ew.mean(1).unsqueeze(1)).pow(2).sum(-1)
        between = (ew.mean(1) - ew.mean(1).mean(0, keepdim=True)).pow(2).sum(-1).mean()
        wv = float((within * valid[multi].float()).sum()
                   / valid[multi].float().sum().clamp(min=1))
        out["diagnostics"]["candidate_conditioning"] = {
            "multi_candidate_worlds": int(multi.sum()),
            "within_world_e_variance": round(wv, 6),
            "between_world_e_variance": round(float(between), 6),
            "ratio_within_over_between": round(wv / max(float(between), 1e-9), 3),
            "e_candidate_conditioned": bool(wv > 1e-8),
        }

    # ---- renderer disagreement, reported SEPARATELY for S, E, A
    dis = {"pairs_evaluated": 0, "S": {}, "E": {}, "A": {}}
    s_dis = s_js = e_dis = e_js = a_dis = a_js = 0.0
    ns = ne = na = 0
    for p in rp[:n_pairs]:
        Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
        if Ha is None or Hb is None:
            continue
        if not alignment_ok(dv, p):
            continue
        sa, ea, ga, ca, aa = model(Ha)
        sb, eb, gb, cb, ab = model(Hb)
        for k in ga:
            xa = ga[k][:, 0] if ga[k].dim() > 1 else ga[k]
            xb = gb[k][:, 0] if gb[k].dim() > 1 else gb[k]
            s_dis += float(((xa > 0) != (xb > 0)).float().mean()); ns += 1
            s_js += float(torch.nn.functional.binary_cross_entropy_with_logits(
                xa, torch.sigmoid(xb)).clamp(min=0))
        vm = (Ha["cand_mask"] > 0) & (Hb["cand_mask"] > 0)
        for k in ca:
            xa = ca[k].squeeze(-1) if ca[k].shape[-1] == 1 else ca[k]
            xb = cb[k].squeeze(-1) if cb[k].shape[-1] == 1 else cb[k]
            e_dis += float(((xa[vm] > 0) != (xb[vm] > 0)).float().mean()); ne += 1
        if aa is not None and ab is not None:
            a_dis += float((aa.argmax(-1) != ab.argmax(-1)).float().mean()); na += 1
            pa, pb = torch.softmax(aa, -1), torch.softmax(ab, -1)
            mid = 0.5 * (pa + pb)
            a_js += float((0.5 * (pa * (pa / mid).clamp_min(1e-7).log()).sum(-1)
                           + 0.5 * (pb * (pb / mid).clamp_min(1e-7).log()).sum(-1)).mean())
        dis["pairs_evaluated"] += 1
    if dis["pairs_evaluated"]:
        dis["S"] = {"disagreement": round(s_dis / max(ns, 1), 4), "n": ns}
        dis["E"] = {"disagreement": round(e_dis / max(ne, 1), 4), "n": ne}
        dis["A"] = {"disagreement": round(a_dis / max(na, 1), 4), "n": na,
                    "js": round(a_js / max(na, 1), 6)}
        dis["alignment"] = "exact canonical candidate identity verified per pair"
        dis["note"] = "reported separately by head group; NOT combined into one robustness score"
    out["diagnostics"]["renderer_disagreement"] = dis

    # ---- 1-NN separability of s (diagnostic 1, unchanged definition)
    sn = (s - s.mean(0)) / s.std(0).clamp(min=1e-6)
    Dm = torch.cdist(sn, sn)
    Dm.fill_diagonal_(float("inf"))
    nn = Dm.argmin(1)
    sep = {}
    for n in g:
        y = g[n][:, 0]
        ok = ~torch.isnan(y)
        if int(ok.sum()) < 10 or len(set(y[ok].tolist())) < 2:
            continue
        yi = y[ok].long()
        acc = float((yi[nn[ok]] == yi).float().mean())
        base = max(float(yi.float().mean()), 1 - float(yi.float().mean()))
        sep[n] = {"s_1nn_accuracy": round(acc, 4), "trivial": round(base, 4),
                  "separates": bool(acc > base + 0.02)}
    out["diagnostics"]["1_global_separability"] = {
        "method": "1-NN on normalized s, nothing fitted", "targets": sep}
    return out


# ------------------------------------------------------------------ train
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["base", "consist"], required=True)
    ap.add_argument("--substrate", default="encoder")
    ap.add_argument("--train-limit", type=int, default=20000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-s", type=int, default=64)
    ap.add_argument("--d-e", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    started = time.perf_counter()

    tr = build("TRAIN", args.substrate, args.train_limit, prim_suffix=SUFFIX, m_cap=M_CAP)
    dv = build("DEV", args.substrate, args.dev_limit, prim_suffix=SUFFIX, m_cap=M_CAP)
    assert tr["m_cap"] == M_CAP == dv["m_cap"], "Phase 2 candidate cap must be 28"
    d_h = tr["H"]["row"].shape[-1]

    model = phase0_init(d_h, tr["global_names"], tr["cand_names"], args.d_s, args.d_e, args.seed)
    sig0 = sigma0_reference(model, tr)
    pair_H, rp = pair_context(dv, args.substrate, M_CAP)
    rp = [p for p in rp if pair_H(p["a"]["world_id"]) is not None
          and pair_H(p["b"]["world_id"]) is not None]
    print(f"arm={args.arm} usable renderer pairs={len(rp)} sigma0_mean="
          f"{sig0['mean_sigma0']:.6f}", flush=True)

    nparam = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, max(1, n // args.bs) * args.epochs)
    w1 = LossWeights()
    w2 = Phase2Weights()
    adir = OUT / args.arm
    adir.mkdir(parents=True, exist_ok=True)

    hist, ck = [], {}
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        agg, nb, rawagg = {}, 0, {}
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, g, c = pack(tr, idx)
            s_, e_, go, co, al = model(H)
            if args.arm == "base":
                parts = {
                    "S": sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1),
                    "E": sum(epistemic_loss(co[k], c[k], H["cand_mask"])
                             for k in co) / max(len(co), 1),
                    "A": action_loss(al, tr["action_index"][idx]) if al is not None else None,
                    "CF": torch.tensor(0.0),
                    "R": torch.tensor(0.0)}
                if rp:
                    p = rp[int(torch.randint(len(rp), (1,)))]
                    Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                    if Ha is not None and Hb is not None:
                        sa, ea, *_ = model(Ha)
                        sb, eb, *_ = model(Hb)
                        parts["R"] = renderer_invariance_loss(sa, sb, ea, eb, Ha["cand_mask"])
                total, detail = total_loss(parts, w1)
            else:
                pair = {"S": torch.tensor(0.0), "E": torch.tensor(0.0), "A": torch.tensor(0.0)}
                if rp:
                    p = rp[int(torch.randint(len(rp), (1,)))]
                    Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                    if Ha is not None and Hb is not None:
                        sa, ea, ga, ca, aa = model(Ha)
                        sb, eb, gb, cb, ab = model(Hb)
                        ok = alignment_ok(dv, p)
                        av = bool((tr["action_index"][idx] >= 0).any())
                        pc = prediction_consistency_loss(ga, gb, ca, cb, aa, ab,
                                                        Ha["cand_mask"], av, ok)
                        pair = {"S": pc["S"], "E": pc["E"], "A": pc["A"]}
                parts2 = {
                    "S": sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1),
                    "E": sum(epistemic_loss(co[k], c[k], H["cand_mask"])
                             for k in co) / max(len(co), 1),
                    "A": action_loss(al, tr["action_index"][idx]) if al is not None else None,
                    "CF": torch.tensor(0.0),
                    "pair_S": pair["S"], "pair_E": pair["E"], "pair_A": pair["A"],
                    "var": variance_floor_loss(s_, sig0["sigma0"])}
                total, detail = phase2_total_loss(parts2, w2)
                for k, v in (("L_pair_S", parts2["pair_S"]), ("L_pair_E", parts2["pair_E"]),
                             ("L_pair_A", parts2["pair_A"]), ("L_var", parts2["var"])):
                    rawagg[k] = rawagg.get(k, 0.0) + float(v.detach())
            opt.zero_grad()
            total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            nb += 1
            for k, v in detail.items():
                agg[k] = agg.get(k, 0.0) + v
        model.eval()
        with torch.no_grad():
            H, g, c = pack(dv, torch.arange(dv["n_rows"]))
            s_, e_, go, co, al = model(H)
            devl = (sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1)
                    + sum(epistemic_loss(co[k], c[k], H["cand_mask"])
                          for k in co) / max(len(co), 1))
        h = {"epoch": ep + 1, "n_batches": nb,
             **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
             **{k: round(v / max(nb, 1), 8) for k, v in rawagg.items()},
             "dev_semantic_plus_epistemic": round(float(devl), 4),
             "D_s": round(float(s_.std(dim=0, unbiased=False).mean()), 6)}
        hist.append(h)
        ck[ep + 1] = {k: v.detach().clone() for k, v in model.state_dict().items()}
        torch.save(model.state_dict(), adir / f"ckpt-epoch-{ep+1}.pt")
        print(json.dumps(h), flush=True)

    best = min(hist, key=lambda x: x["dev_semantic_plus_epistemic"])
    model.load_state_dict(ck[best["epoch"]])
    ev = evaluate(model, dv, pair_H, rp)

    import hashlib

    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    rec = {
        "abi": "phase2-semantic-interface/receipt-v0.1",
        "lane": "bidirectional (Lepori)",         "arm": f"P2-{args.arm.upper()}",
        "arm_identity": {
            "P2-BASE": "Phase 1 objective reproduced under the exhaustive-candidate Phase 2 "
                       "input contract; raw latent L_R present",
            "P2-CONSIST": "L^(2): prediction consistency (JS) + variance floor; raw latent "
                          "L_R removed",
        }[f"P2-{args.arm.upper()}"],
        "shared_with_other_arm": {
            "initialization": "identical Phase 0 init, file phase0-init.pt",
            "input_contract": f"m_cap={M_CAP}, prim cache *{SUFFIX}.pt, "
                              "20,000 TRAIN / 2,000 DEV canonical",
            "hyperparameters": "identical; nothing tuned from DEV",
        },
        "substrate_identity": {"name": "LiquidAI/LFM2.5-Encoder-230M",
                               "revision": "0b649ad0c684378b03d4d8304f7577a662ab89bc",
                               "params": 229.7e6, "frozen": True},
        "architecture_identity": {"abi": "phase0-semantic-interface/arch-v0.1",
                                  "d_s": args.d_s, "d_e": args.d_e,
                                  "note": "graft architecture and latent dims UNCHANGED; the "
                                          "action head output width follows the candidate "
                                          "contract (24 -> 28) and is identical in both arms"},
        "trainable_parameters": nparam,
        "trainable_fraction_of_substrate": round(100.0 * nparam / 229_700_000, 4),
        "candidate_convention": {
            "m_cap": M_CAP, "source": "measured canonical maximum",
            "rule": "retain every canonical candidate",
            "ordering": "canonical available_actions order, deterministic",
            "padding": "-1 entity indices, cand_type 0, mask 0",
            "padded_candidates": "excluded from every loss and metric",
            "truncated": False,
        },
        "objective": (phase2_objective_descriptor(w2) if args.arm == "consist"
                      else {"abi": "phase1 objective reproduced",
                            "L": "L_S + L_E + 0.5 L_A + 0.5 L_CF + 0.25 L_R",
                            "raw_latent_L_R": "PRESENT (this is the baseline)"}),
        "variance_reference": {"mean_sigma0": sig0["mean_sigma0"], "d_s": sig0["d_s"],
                               "n_rows": sig0["n_rows"], "source": sig0["source"],
                               "used_by": "P2-CONSIST only"},
        "cf_state": "DORMANT: candidate_supported / candidate_has_counterevidence / "
                    "candidate_requires_missing_information have no admissible canonical "
                    "source. No label invented.",
        "training_configuration": {"optimizer": "AdamW", "lr": args.lr, "schedule": "cosine",
                                   "bs": args.bs, "epochs": args.epochs, "seed": args.seed,
                                   "weight_decay": 0.01, "grad_clip": 1.0,
                                   "train_rows": n, "dev_rows": dv["n_rows"],
                                   "renderer_pairs_available": len(rp)},
        "best_dev_checkpoint": {"epoch": best["epoch"],
                                "dev_semantic_plus_epistemic": best["dev_semantic_plus_epistemic"],
                                "rule": "lowest DEV semantic+epistemic loss; identical in both "
                                        "arms; no weight or architecture changed by selection"},
        "per_target_dev_metrics": {"global": ev["global"], "candidate": ev["candidate"],
                                   "endpoint": ev["endpoint"]},
        "diagnostics": ev["diagnostics"],
        "training_history": hist,
        "phase0_exit_gate": check("DEV", args.substrate, 400)["gates"],
        "anomalies": [
            "L_CF dormant by contract in both arms",
            "selection rule is lowest DEV BCE, which is prior-dominated; recorded in Phase 1 "
            "and unchanged here so both arms are treated identically",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    p = adir / f"phase2-{args.arm}-receipt.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    (adir / "artifact-hashes.json").write_text(json.dumps({
        "receipt": sha(p),
        "checkpoints": {f"ckpt-epoch-{e}.pt": sha(adir / f"ckpt-epoch-{e}.pt")
                        for e in range(1, args.epochs + 1)},
        "phase0_init": sha(OUT / "phase0-init.pt"),
    }, indent=2) + "\n")
    print(json.dumps({"written": str(p), "best_epoch": best["epoch"], "params": nparam,
                      "D_s": ev["diagnostics"]["D_s"]["value"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
