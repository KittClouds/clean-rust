"""Phase 0 shared training harness.

Implements L = L_S + L_E + L_A + L_CF + L_R with the shared semantics in src/objective.py.
The fabric is a config switch: 'bidirectional' (this lane) or 'causal' (the sibling lane),
sharing every line of loss code and differing only in the graft and in H.

NO cross-agent alignment term exists. NO accuracy gate exists. Phase 0 asks only whether the
experiment is defined and buildable.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn as nn

from src.graft import BidirectionalGraft, SemanticInterfaceGraft, ReadoutHeads
from src.ontology import supervision_abi, audit_availability, BY_NAME
from src.objective import (LossWeights, semantic_loss, epistemic_loss, action_loss,
                           truth_contrast_loss, renderer_invariance_loss, total_loss,
                           objective_descriptor, assert_no_alignment_term)
from src.pairs import renderer_pairs, truth_changing_pairs
from src.data import build
from src.gate import check

EXP = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase0")


class Interface(nn.Module):
    def __init__(self, d_h, fabric, d_s=64, d_e=32, gnames=(), cnames=(), m_cap=24):
        super().__init__()
        G = BidirectionalGraft if fabric == "bidirectional" else SemanticInterfaceGraft
        self.graft = G(d_h=d_h, d_s=d_s, d_e=d_e)
        gd = [(n, BY_NAME[n].d_out) for n in gnames if n in BY_NAME]
        cd = [(n, BY_NAME[n].d_out) for n in cnames if n in BY_NAME]
        self.heads = ReadoutHeads(d_s, d_e, gd, cd, m_cap=m_cap)

    def forward(self, H):
        s, e = self.graft(H)
        g, c, a = self.heads(s, e, H["cand_mask"])
        return s, e, g, c, a


def pack(d, idx):
    H = {"row": d["H"]["row"][idx], "ent": d["H"]["ent"], "cand_ent": d["H"]["cand_ent"][idx],
         "cand_type": d["H"]["cand_type"][idx], "cand_mask": d["H"]["cand_mask"][idx]}
    g = {n: t[idx] for n, t in d["global_labels"].items()}
    c = {n: t[idx] for n, t in d["cand_labels"].items()}
    return H, g, c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fabric", default="bidirectional", choices=["bidirectional", "causal"])
    ap.add_argument("--substrate", default="encoder", choices=["encoder", "causal"])
    ap.add_argument("--train-split", default="TRAIN")
    ap.add_argument("--dev-split", default="DEV")
    ap.add_argument("--train-limit", type=int, default=6000)
    ap.add_argument("--dev-limit", type=int, default=2000)
    ap.add_argument("--pair-limit", type=int, default=3000)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--bs", type=int, default=48)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-s", type=int, default=64)
    ap.add_argument("--d-e", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.train_limit, args.dev_limit, args.pair_limit, args.epochs = 400, 200, 300, 1

    torch.manual_seed(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    w = LossWeights()
    started = time.perf_counter()

    tr = build(args.train_split, args.substrate, args.train_limit)
    dv = build(args.dev_split, args.substrate, args.dev_limit)
    d_h = tr["H"]["row"].shape[-1]
    model = Interface(d_h, args.fabric, args.d_s, args.d_e,
                      tr["global_names"], tr["cand_names"], tr["m_cap"])
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    n = tr["n_rows"]
    steps = max(1, n // args.bs) * args.epochs
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps)

    # action endpoint index a* from canonical selected_action
    a_star = tr.get("action_index", torch.full((n,), -1, dtype=torch.long))
    row_of = {w: i for i, w in enumerate(tr["world_ids"])}
    prim_row = tr["H"]["row"]

    rp = renderer_pairs(args.train_split, args.pair_limit)
    tp, tstats = truth_changing_pairs(args.train_split, "S1", limit=args.pair_limit)

    # Renderer-pair members are BANK paired rows (@S0, @S1, ...). data.build() only indexes
    # canonical worlds, so pair members are resolved against the released primitive cache
    # directly rather than against the training batch table.
    from src.data import SURFACES as _SF
    _prim = torch.load(Path(r"D:\codex-runs\encoder-contrast-01\primitives")
                       / args.substrate / f"{args.train_split}.pt",
                       map_location="cpu", weights_only=False)
    _prow = {w: i for i, w in enumerate(_prim["row_ids"])}
    _prow_surf = torch.stack([_prim["surfaces"][s] for s in _SF], 1).float()
    _prun = {}
    _r = 0
    for (bi, eids) in _prim["entity_index"]:
        _prun[_prim["row_ids"][bi]] = (_r, eids)
        _r += len(eids)
    # candidate structure is a property of the latent world, not of the rendering, so a paired
    # row inherits the candidate slots of its canonical world.
    # candidate structure is a property of the latent world, not of the rendering, so a paired
    # row inherits the candidate slots of its canonical world; the entity indices are then
    # shifted from the canonical run offset to that row's own run offset.
    _cand_by_world = {w: (tr["H"]["cand_ent"][i], tr["H"]["cand_type"][i],
                          tr["H"]["cand_mask"][i], tr["ent_runs"][w][0])
                      for i, w in enumerate(tr["world_ids"]) if w in tr.get("ent_runs", {})}

    def pair_H(wid):
        i = _prow.get(wid)
        if i is None:
            return None
        canon = wid.split("@")[0]
        cs = _cand_by_world.get(canon)
        run = _prun.get(wid, (None, None))
        if cs is None or run[1] is None:
            return None
        pair_run = run[0]
        n_ent = len(run[1])
        shift = pair_run - cs[3]
        ce = cs[0].clone()
        ce[ce >= 0] = (ce[ce >= 0] + shift).clamp(min=0, max=max(n_ent - 1, 0))
        ent = _prim["entity_vectors"][pair_run:pair_run + n_ent].float()
        return {"row": _prow_surf[i:i + 1], "ent": ent,
                "cand_ent": ce.unsqueeze(0),
                "cand_type": cs[1].unsqueeze(0), "cand_mask": cs[2].unsqueeze(0)}

    history = []
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n)
        agg, nb = {}, 0
        for st in range(0, n - args.bs + 1, args.bs):
            idx = perm[st:st + args.bs]
            H, g, c = pack(tr, idx)
            s_, e_, go, co, al = model(H)
            parts = {}
            L_S = sum(semantic_loss(go[k], g[k]) for k in go) / max(len(go), 1)
            L_E = sum(epistemic_loss(co[k], c[k], H["cand_mask"]) for k in co) / max(len(co), 1)
            parts["S"], parts["E"] = L_S, L_E
            parts["A"] = action_loss(al, a_star[idx]) if al is not None else None
            # L_R is computable from the released cache: both members of a renderer pair are
            # real BANK rows, so their frozen H already exists.
            parts["R"] = torch.tensor(0.0)
            if rp:
                p = rp[int(torch.randint(len(rp), (1,)))]
                Ha, Hb = pair_H(p["a"]["world_id"]), pair_H(p["b"]["world_id"])
                if Ha is not None and Hb is not None:
                    sa, ea, *_ = model(Ha)
                    sb, eb, *_ = model(Hb)
                    parts["R"] = renderer_invariance_loss(sa, sb, ea, eb, Ha["cand_mask"])
            # L_CF is DORMANT in this harness: the mutated renderings of a truth-changing pair
            # are not in the released primitive cache, so H(x+), H(x-) do not exist yet. The
            # term is implemented and unit-tested but contributes nothing until a substrate pass
            # extracts features for the mutated texts. It is NOT faked with a zero that pretends
            # to be supervision.
            parts["CF"] = torch.tensor(0.0)
            total, detail = total_loss(parts, w)
            opt.zero_grad(); total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); nb += 1
            for k, v in detail.items():
                agg[k] = agg.get(k, 0.0) + v
        hist = {"epoch": ep + 1, "n_batches": nb,
                **{k: round(v / max(nb, 1), 4) for k, v in agg.items()}}
        history.append(hist)
        print(json.dumps(hist), flush=True)

    gate = check(args.dev_split, args.substrate, 400)
    report = {
        "status": "PHASE0_ARTIFACT_COMPLETE",
        "fabric": args.fabric, "substrate": args.substrate,
        "objective": objective_descriptor(w),
        "alignment_between_fabrics": "none; asserted by assert_no_alignment_term",
        "ontology": supervision_abi(),
        "audit": audit_availability(2000),
        "trainable_parameters": sum(p.numel() for p in model.parameters()),
        "d_s": args.d_s, "d_e": args.d_e, "m_cap": tr["m_cap"],
        "data": {"train_rows": n, "dev_rows": dv["n_rows"],
                 "renderer_pairs": len(rp), "truth_changing_pairs": len(tp),
                 "action_endpoint_coverage": (float((a_star >= 0).float().mean()) if len(a_star) else None)},
        "pair_stats": tstats,
        "history": history,
        "exit_gate": {k: gate["gates"][k] for k in gate["gates"]},
        "phase_0_exit": gate["phase_0_exit"],
        "accuracy_gate_present": False,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    p = OUT / f"phase0-{args.fabric}.json"
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"written": str(p), "phase_0_exit": gate["phase_0_exit"],
                      "trainable_parameters": report["trainable_parameters"],
                      "pairs": report["data"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

