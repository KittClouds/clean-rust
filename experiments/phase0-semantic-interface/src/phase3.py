"""Phase 3 — bidirectional fabric (Lepori's lane). P3-BALANCED.

Final objective-only phase. The single intended scientific change is supervision geometry:
unique-SOURCE weighting plus prospectively fixed balanced BCE, together with a balanced
selection rule. No architecture, substrate, surface, head, or supervision change.

Comparator is the frozen Phase 2 CONSIST artifact. No Phase 2 baseline is retrained.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from src.objective import (Phase3Weights, balanced_bce, source_group_loss,
                           family_balanced_loss, phase3_total_loss, phase3_objective_descriptor,
                           j_select, semantic_loss, action_loss, prediction_consistency_loss,
                           variance_floor_loss)
from src.data import build
from src.phase1 import Interface, pack, ordinal_metrics
from src.phase2 import phase0_init, sigma0_reference, pair_context, alignment_ok, OUT, M_CAP
from src.graft import ACTION_TYPES
from src.gate import check

P3 = OUT.parent / "phase3"
P3.mkdir(parents=True, exist_ok=True)
SUFFIX = "-p2"

# Canonical source groups, from src/target_registry.py, verified numerically.
GLOBAL_GROUPS = {
    "SRC-SOLVABILITY": ["solvable"],
    "SRC-GOAL-SATISFIED": ["goal_satisfied"],
    "SRC-MISSING-INFO-PANEL": ["missing_information_present",
                               "number_or_structure_of_missing_requirements"],
    "SRC-CONTRADICTION-PANEL": ["contradiction_present"],
}
CAND_GROUPS = {
    "SRC-CANDIDATE-LEGALITY": ["candidate_legal", "candidate_applicable",
                               "candidate_has_unmet_requirements"],
    "SRC-CANDIDATE-SATISFIES-GOAL": ["candidate_satisfies_goal"],
}
ALIAS = {"candidate_applicable": "candidate_legal",
         "candidate_has_unmet_requirements": "candidate_legal",
         "number_or_structure_of_missing_requirements": "missing_information_present"}
COUNT_TARGET = "number_or_structure_of_missing_requirements"


def head_terms_global(go, g, names, pi, train):
    """Per-head balanced BCE for the heads reading one global source group."""
    out = []
    for n in names:
        lg = go[n]
        y = g[n][:, 0]
        sup = ~torch.isnan(y)
        if not bool(sup.any()):
            continue
        if n == COUNT_TARGET:
            # supervised channels only; channels 1..5 stay masked exactly as in Phase 2
            out.append(balanced_bce(lg[:, 0][sup], y[sup], pi))
        else:
            out.append(balanced_bce(lg[:, 0][sup], y[sup], pi))
    return out


def head_terms_cand(co, c, names, pi_by_head, mask):
    out = []
    for n in names:
        lg = co[n]
        if lg.shape[-1] == 1:
            lg = lg.squeeze(-1)
        y = c[n]
        sel = (~torch.isnan(y)) & mask
        if not bool(sel.any()):
            continue
        # each head's OWN prevalence, so its BCE is properly balanced; the group averaging is
        # what prevents an alias from earning a second unit of weight
        out.append(balanced_bce(lg[sel], y[sel], pi_by_head[n]))
    return out


def eval_head(logit, y, pi_train):
    p = (logit > 0).float()
    t = (y > 0.5).float()
    tp = float(((p == 1) & (t == 1)).sum()); fp = float(((p == 1) & (t == 0)).sum())
    fn = float(((p == 0) & (t == 1)).sum()); tn = float(((p == 0) & (t == 0)).sum())
    rec = tp / max(tp + fn, 1e-9); prec = tp / max(tp + fp, 1e-9)
    spec = tn / max(tn + fp, 1e-9)
    f1p = 2 * prec * rec / max(prec + rec, 1e-9)
    nprec = tn / max(tn + fn, 1e-9); nrec = tn / max(tn + fp, 1e-9)
    f1n = 2 * nprec * nrec / max(nprec + nrec, 1e-9)
    return {
        "balanced_accuracy": round((rec + spec) / 2, 4),
        "accuracy": round((tp + tn) / max(len(t), 1), 4),
        "macro_f1": round((f1p + f1n) / 2, 4),
        "positive_f1": round(f1p, 4), "negative_f1": round(f1n, 4),
        "support_pos": int(tp + fn), "support_neg": int(tn + fp),
        "train_prevalence": round(pi_train, 4),
        "beats_base_rate": bool((rec + spec) / 2 > max(pi_train, 1 - pi_train) + 0.01),
    }


@torch.no_grad()
def evaluate(model, dv, pair_H, rp, pi_g, pi_c, n_pairs=400):
    model.eval()
    H, g, c = pack(dv, torch.arange(dv["n_rows"]))
    s, e, go, co, al = model(H)
    out = {"by_source": {}, "aliases": {}, "endpoint": {}, "diagnostics": {}}
    m = H["cand_mask"]
    valid = m > 0

    for sid, names in GLOBAL_GROUPS.items():
        for n in names:
            y = g[n][:, 0]
            sup = ~torch.isnan(y)
            if n == COUNT_TARGET:
                pr = torch.sigmoid(go[n][:, 0][sup])
                mm = ordinal_metrics(y[sup], pr)
                mm.update({"scored_channels": [0],
                           "train_prevalence": round(pi_g[sid], 4),
                           "trivial_exact_count": round(float(y[sup].float().gt(0.5).float()
                                                              .mean()), 4)})
                mm["beats_trivial"] = bool(mm["exact_count_accuracy"]
                                           > mm["trivial_exact_count"] + 0.01)
                rec = mm
            else:
                rec = eval_head(go[n][:, 0][sup], y[sup], pi_g[sid])
            if n in ALIAS:
                rec = dict(rec, SAME_CANONICAL_SOURCE=ALIAS[n], independent_target=False,
                           note="ABI consistency only; never counted as an independent win")
                out["aliases"][n] = rec
            else:
                out["by_source"][sid] = rec
    for sid, names in CAND_GROUPS.items():
        for n in names:
            lg = co[n]
            if lg.shape[-1] == 1:
                lg = lg.squeeze(-1)
            sel = (~torch.isnan(c[n])) & valid
            rec = eval_head(lg[sel], c[n][sel], pi_c[n])
            rec["valid_candidates"] = int(sel.sum())
            if n in ALIAS:
                rec = dict(rec, SAME_CANONICAL_SOURCE=ALIAS[n], independent_target=False,
                           note="ABI consistency only; never counted as an independent win")
                out["aliases"][n] = rec
            else:
                out["by_source"][sid] = rec

    astar = dv["action_index"]
    sel = astar >= 0
    ep = {"coverage": round(float(sel.sum()) / dv["n_rows"], 4),
          "n_endpoint_worlds": int(sel.sum()), "chance": round(1.0 / M_CAP, 4),
          "contract": "masked CE; abstention excluded; NOT part of checkpoint selection",
          "by_action_type": {}}
    if int(sel.sum()) > 0:
        pred = al[sel].reshape(int(sel.sum()), -1).argmax(1)
        tgt = astar[sel]
        ep["action_top1_accuracy"] = round(float((pred == tgt).float().mean()), 4)
        cands = dv["cand_actions"]
        rows = sel.nonzero().flatten().tolist()
        for t_i, t_name in enumerate(ACTION_TYPES):
            hit = torch.tensor([cands[i][int(j)] is not None
                                and cands[i][int(j)].get("type") == t_name
                                for i, j in zip(rows, tgt.tolist())])
            if int(hit.sum()):
                ep["by_action_type"][t_name] = {
                    "n": int(hit.sum()),
                    "accuracy": round(float((pred[hit] == tgt[hit]).float().mean()), 4)}
    out["endpoint"] = ep

    sig = s.std(dim=0, unbiased=False)
    out["diagnostics"]["D_s"] = {
        "definition": "mean_k sigma_k(s) on DEV",
        "value": round(float(sig.mean()), 6),
        "s_collapsed": bool(float(sig.mean()) < 1e-3),
        "note": "variance rules out collapse; it is NOT evidence the state is useful. Phase 2 "
                "established D_s>0 does not imply semantic discrimination.",
    }
    nv = valid.sum(1)
    multi = nv >= 2
    if int(multi.sum()) > 10:
        ew = e[multi]
        within = (ew - ew.mean(1).unsqueeze(1)).pow(2).sum(-1)
        between = (ew.mean(1) - ew.mean(1).mean(0, keepdim=True)).pow(2).sum(-1).mean()
        wv = float((within * valid[multi].float()).sum()
                   / valid[multi].float().sum().clamp(min=1))
        out["diagnostics"]["candidate_conditioning"] = {
            "within_world_e_variance": round(wv, 6),
            "between_world_e_variance": round(float(between), 6),
            "ratio_within_over_between": round(wv / max(float(between), 1e-9), 3),
            "e_candidate_conditioned": bool(wv > 1e-8),
        }

    # ---- renderer 2x2 correctness decomposition (prevents a constant predictor from scoring well)
    dec = {"pairs_evaluated": 0, "global": {}, "candidate": {}, "action": {},
           "note": "both correct / first only / second only / both wrong / disagreement, per "
                   "target. NOT combined into one aggregate."}
    acc = {}
    for n in names_global_flat():
        acc[n] = [0, 0, 0, 0, 0]
    for n in ("candidate_legal",):
        acc[n] = [0, 0, 0, 0, 0]
    acc["action"] = [0, 0, 0, 0, 0]
    for p in rp[:n_pairs]:
        Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
        if Ha is None or Hb is None or not alignment_ok(dv, p):
            continue
        base = p["a"]["world_id"].split("@")[0]
        gi = dv["world_ids"].index(base)
        _, _, ga, ca, aa = model(Ha)
        _, _, gb, cb, ab = model(Hb)
        for n in acc:
            if n == "action":
                if aa is None or ab is None:
                    continue
                truth = dv["action_index"][gi]
                if truth < 0:
                    continue
                pa = int(aa.reshape(-1, M_CAP).argmax(1)[0])
                pb = int(ab.reshape(-1, M_CAP).argmax(1)[0])
            elif n in ga:
                truth = float(g[n][gi, 0])
                if truth != truth:
                    continue
                la = ga[n].reshape(-1)[0]
                lb = gb[n].reshape(-1)[0]
                pa = int(la > 0); pb = int(lb > 0)
            else:
                continue
            ca_, cb_ = (pa == truth), (pb == truth)
            a_ = acc[n]
            a_[0] += int(ca_ and cb_); a_[1] += int(ca_ and not cb_)
            a_[2] += int(cb_ and not ca_); a_[3] += int(not ca_ and not cb_)
            a_[4] += int(pa != pb)
        dec["pairs_evaluated"] += 1
    for n, a_ in acc.items():
        if sum(a_[:4]) == 0:
            continue
        tot = max(sum(a_[:4]), 1)
        d = {"both_correct": a_[0], "first_only_correct": a_[1], "second_only_correct": a_[2],
             "both_wrong": a_[3], "disagreement": a_[4],
             "pair_accuracy_first": round((a_[0] + a_[1]) / tot, 4),
             "pair_accuracy_second": round((a_[0] + a_[2]) / tot, 4),
             "paired_accuracy": round(a_[0] / tot, 4)}
        dec["action" if n == "action" else ("candidate" if n == "candidate_legal" else "global")][n] = d
    out["diagnostics"]["renderer_correctness_decomposition"] = dec
    return out


def names_global_flat():
    out = []
    for v in GLOBAL_GROUPS.values():
        out.extend(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
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
    assert tr["m_cap"] == M_CAP == dv["m_cap"]
    d_h = tr["H"]["row"].shape[-1]

    model = phase0_init(d_h, tr["global_names"], tr["cand_names"], args.d_s, args.d_e, args.seed)
    sig0 = sigma0_reference(model, tr)
    pair_H, rp = pair_context(dv, args.substrate, M_CAP)
    rp = [p for p in rp if pair_H(p["a"]["world_id"]) is not None
          and pair_H(p["b"]["world_id"]) is not None]

    g, c, mask = tr["global_labels"], tr["cand_labels"], tr["H"]["cand_mask"] > 0
    # TRAIN-ONLY prevalences, one per canonical source
    pi_g = {sid: float((tr["global_labels"][n][:, 0] == 1).float().mean())
            for sid, ns in GLOBAL_GROUPS.items() for n in ns if n != COUNT_TARGET}
    pi_g["SRC-MISSING-INFO-PANEL"] = float(
        (g["missing_information_present"][:, 0] == 1).float().mean())
    pi_c = {n: float((c[n][mask] == 1).float().mean()) for ns in CAND_GROUPS.values()
            for n in ns}
    print(f"P3-BALANCED pairs={len(rp)} sigma0={sig0['mean_sigma0']:.6f}")
    print("TRAIN prevalence: " + "  ".join(f"{k}={v:.4f}" for k, v in pi_g.items()))
    print("TRAIN prevalence (candidate heads): "
          + "  ".join(f"{k}={v:.4f}" for k, v in pi_c.items()), flush=True)

    nparam = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, max(1, n // args.bs) * args.epochs)
    w = Phase3Weights()
    adir = P3 / "balanced"
    adir.mkdir(parents=True, exist_ok=True)

    hist, ck = [], {}
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        agg, nb, raw = {}, 0, {}
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, gg, cc = pack(tr, idx)
            s_, e_, go, co, al = model(H)
            bm = H["cand_mask"] > 0
            gl = [source_group_loss(head_terms_global(go, gg, ns, pi_g[sid], tr), pi_g[sid])
                  for sid, ns in GLOBAL_GROUPS.items()]
            cl = [source_group_loss(head_terms_cand(co, cc, ns, pi_c, bm), pi_c[ns[0]])
                  for sid, ns in CAND_GROUPS.items()]
            pair = {"S": torch.tensor(0.0), "E": torch.tensor(0.0), "A": torch.tensor(0.0)}
            if rp:
                p = rp[int(torch.randint(len(rp), (1,)))]
                Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                if Ha is not None and Hb is not None:
                    sa, ea, ga, ca, aa = model(Ha)
                    sb, eb, gb, cb, ab = model(Hb)
                    pc = prediction_consistency_loss(
                        ga, gb, ca, cb, aa, ab, Ha["cand_mask"],
                        bool((tr["action_index"][idx] >= 0).any()), alignment_ok(dv, p))
                    pair = {"S": pc["S"], "E": pc["E"], "A": pc["A"]}
            parts = {
                "S": family_balanced_loss(gl), "E": family_balanced_loss(cl),
                "A": action_loss(al, tr["action_index"][idx]) if al is not None else None,
                "CF": torch.tensor(0.0),
                "pair_S": pair["S"], "pair_E": pair["E"], "pair_A": pair["A"],
                "var": variance_floor_loss(s_, sig0["sigma0"]),
            }
            total, detail = phase3_total_loss(parts, w)
            opt.zero_grad(); total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); nb += 1
            for k, v in detail.items():
                agg[k] = agg.get(k, 0.0) + v
            for k, v in (("L_pair_S", parts["pair_S"]), ("L_pair_E", parts["pair_E"]),
                         ("L_pair_A", parts["pair_A"]), ("L_var", parts["var"])):
                raw[k] = raw.get(k, 0.0) + float(v.detach())
        # ---- balanced DEV criterion over UNIQUE source groups
        model.eval()
        with torch.no_grad():
            H, gg, cc = pack(dv, torch.arange(dv["n_rows"]))
            s_, e_, go, co, al = model(H)
            dm = H["cand_mask"] > 0
            JS = family_balanced_loss(
                [source_group_loss(head_terms_global(go, gg, ns, pi_g[sid], dv), pi_g[sid])
                 for sid, ns in GLOBAL_GROUPS.items()])
            JE = family_balanced_loss(
                [source_group_loss(head_terms_cand(co, cc, ns, pi_c, dm), pi_c[ns[0]])
                 for ns in CAND_GROUPS.values()])
            J = float(j_select(JS, JE))
        h = {"epoch": ep + 1, "n_batches": nb,
             **{k: round(v / max(nb, 1), 4) for k, v in agg.items()},
             **{k: round(v / max(nb, 1), 8) for k, v in raw.items()},
             "J_S": round(float(JS), 4), "J_E": round(float(JE), 4),
             "J_select": round(J, 4),
             "D_s": round(float(s_.std(dim=0, unbiased=False).mean()), 6)}
        hist.append(h)
        ck[ep + 1] = {k: v.detach().clone() for k, v in model.state_dict().items()}
        torch.save(model.state_dict(), adir / f"ckpt-epoch-{ep+1}.pt")
        print(json.dumps(h), flush=True)

    best = min(hist, key=lambda x: x["J_select"])
    model.load_state_dict(ck[best["epoch"]])
    ev = evaluate(model, dv, pair_H, rp, pi_g, pi_c)

    import hashlib

    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    reg = json.loads((P3 / "target-source-registry.json").read_text())
    rec = {
        "abi": "phase3-semantic-interface/receipt-v0.1",
        "lane": "bidirectional (Lepori)", "arm": "P3-BALANCED",
        "comparator": "frozen Phase 2 CONSIST artifact (NOT retrained)",
        "substrate_identity": {"name": "LiquidAI/LFM2.5-Encoder-230M",
                               "revision": "0b649ad0c684378b03d4d8304f7577a662ab89bc",
                               "frozen": True},
        "architecture_identity": {
            "abi": "phase0-semantic-interface/arch-v0.1", "d_s": args.d_s, "d_e": args.d_e,
            "PHASE2_ARCHITECTURE_UNCHANGED": True,
            "note": "no recurrence, no new attention, no new surfaces, no new heads, no larger "
                    "MLPs, no backbone adaptation, no new supervision",
        },
        "trainable_parameters": nparam,
        "trainable_fraction_of_substrate": round(100.0 * nparam / 229_700_000, 4),
        "candidate_universe": {"m_max": M_CAP, "rule": "retain every canonical candidate",
                               "truncated": False, "prim_suffix": SUFFIX},
        "target_source_registry": {
            "path": "target-source-registry.json",
            "independent_global_groups": reg["independent_global_source_groups"],
            "independent_candidate_groups": reg["independent_candidate_source_groups"],
            "n_independent_sources": reg["n_global_groups"] + reg["n_candidate_groups"],
            "n_ontology_heads": len(reg["registry"]),
            "aliases": {k: v["alias_of"] for k, v in
                        [(r["target_name"], r) for r in reg["registry"]] if v["alias_of"]},
        },
        "objective": phase3_objective_descriptor(w, {**GLOBAL_GROUPS, **CAND_GROUPS},
                                                 {**pi_g, **pi_c}),
        "cf_state": "DORMANT: candidate_supported / candidate_has_counterevidence / "
                    "candidate_requires_missing_information have no canonical BANK-v1 field. "
                    "No label invented.",
        "training_configuration": {"optimizer": "AdamW", "lr": args.lr, "schedule": "cosine",
                                   "bs": args.bs, "epochs": args.epochs, "seed": args.seed,
                                   "weight_decay": 0.01, "grad_clip": 1.0,
                                   "train_rows": n, "dev_rows": dv["n_rows"],
                                   "renderer_pairs_available": len(rp),
                                   "init": "same phase0-init.pt as Phase 2 CONSIST",
                                   "shuffle_order": "seed-reproducible via torch.randperm "
                                                    "after identical init construction"},
        "selection_rule": {
            "criterion": "J_select = 0.5 J_S + 0.5 J_E, balanced DEV BCE over UNIQUE source "
                         "groups; lowest wins",
            "aliases_double_counted": False,
            "action_accuracy_in_selection": False,
            "renderer_agreement_in_selection": False,
            "best_epoch": best["epoch"], "best_J_select": best["J_select"],
            "replaces": "Phase 1/2 lowest ordinary DEV BCE (prior-dominated)",
        },
        "per_source_dev_metrics": ev["by_source"],
        "alias_dev_metrics": ev["aliases"],
        "endpoint_metrics": ev["endpoint"],
        "diagnostics": ev["diagnostics"],
        "training_history": hist,
        "phase0_exit_gate": check("DEV", args.substrate, 400)["gates"],
        "anomalies": [
            "L_CF dormant in this arm; no candidate-support source exists",
            "L_var retained unchanged from Phase 2 despite small measured contribution, to "
            "avoid a second intervention",
            "renderer pairs limited by the 332 paired rows present in the released DEV cache",
        ],
        "protected": {"PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
                      "PHASE0_ARCHITECTURE_UNCHANGED": True,
                      "PHASE0_TARGET_SEMANTICS_UNCHANGED": True,
                      "CANONICAL_SPLITS_UNCHANGED": True,
                      "SUBSTRATE_UNCHANGED": True, "EXTRACTION_SURFACES_UNCHANGED": True},
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    p = adir / "phase3-balanced-receipt.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    (adir / "artifact-hashes.json").write_text(json.dumps({
        "receipt": sha(p),
        "checkpoints": {f"ckpt-epoch-{e}.pt": sha(adir / f"ckpt-epoch-{e}.pt")
                        for e in range(1, args.epochs + 1)},
    }, indent=2) + "\n")
    print(json.dumps({"written": str(p), "best_epoch": best["epoch"],
                      "J_select": best["J_select"], "params": nparam,
                      "D_s": ev["diagnostics"]["D_s"]["value"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
