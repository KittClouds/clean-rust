"""TEST-JOINT interaction decomposition.

BANK-v1 ships JOINT as a single stratum produced by one generator constraint set. To
find whether the encoder's JOINT behaviour is an *interaction* between constituent
shifts rather than a main effect, we re-render fixed TEST-IID latent worlds under
orthogonal shift subsets and measure

    interaction(A,B) = delta(A+B) - (delta(A) + delta(B)) / 2

with delta(X) = encoder_minus_causal on surface S, route exactness, matched rows.

All worlds are the same latent worlds in every cell; only the rendering shifts.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear, accuracy
from src.extract_primitives import load_substrate, mention_spans, entity_span_vectors
from src import shifts as SH

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")

SURFACES = ["first", "final", "mean", "full_mean", "layer-4", "middle"]
COMBOS = [
    ("base", ()),
    ("LEX", ("LEX",)),
    ("TMPL", ("TMPL",)),
    ("ENT", ("ENT",)),
    ("COMP", ("COMP",)),
    ("DEPTH", ("DEPTH",)),
    ("LEX+TMPL", ("LEX", "TMPL")),
    ("ENT+TMPL", ("ENT", "TMPL")),
    ("COMP+DEPTH", ("COMP", "DEPTH")),
    ("LEX+COMP", ("LEX", "COMP")),
    ("TMPL+DEPTH", ("TMPL", "DEPTH")),
    ("ALL", ("LEX", "TMPL", "ENT", "COMP", "DEPTH")),
]


def load_split(substrate, split):
    prim = torch.load(Path(r"D:\codex-runs\encoder-contrast-01\primitives") / substrate / f"{split}.pt",
                      map_location="cpu", weights_only=False)
    truth = {r["world_id"]: r["labels"] for r in
             (json.loads(l) for l in open(BANK / "protected" / "test-truth" / f"{split}.jsonl", encoding="utf-8"))} \
        if split.startswith("TEST-") else None
    rows = []
    for i, wid in enumerate(prim["row_ids"]):
        lab = truth.get(wid) if truth is not None else prim["labels"][i].get("labels")
        if lab:
            rows.append((i, wid, lab))
    return prim, rows


def route_gold(rows):
    out = []
    for i, _w, lab in rows:
        pol = lab.get("policy", {})
        if pol.get("decision") == "ACT" and pol.get("action"):
            out.append((i, json.dumps({"a": pol["action"], "g": pol.get("arguments", {})}, sort_keys=True)))
    return out


def embed_rows(substrate, texts, device, batch=24, max_len=512):
    """Returns list of (per-layer masked means [n_layers,B,H], first [B,H], final [B,H])."""
    tok, model, _ = load_substrate(substrate, device)
    means, firsts, finals = [], [], []
    for s in range(0, len(texts), batch):
        enc = tok(texts[s:s + batch], return_tensors="pt", padding=True, truncation=True,
                  max_length=max_len)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            hs = model(**enc, output_hidden_states=True).hidden_states
        m = enc["attention_mask"].unsqueeze(-1)
        per_layer = []
        for h in hs:
            mh = m.to(h.dtype)
            per_layer.append(((h * mh).sum(1) / mh.sum(1).clamp(min=1)).float().cpu())
        means.append(torch.stack(per_layer, 0))
        last = hs[-1]
        mask = enc["attention_mask"].bool()
        b = torch.arange(last.shape[0], device=last.device)
        firsts.append(last[b, mask.float().argmax(1)].float().cpu())
        finals.append(last[b, mask.sum(1) - 1].float().cpu())
    del model
    torch.cuda.empty_cache()
    return means, firsts, finals


def surfaces_from(means, firsts, finals):
    # means: list of [n_layers, B, H]; cat over batches -> [n_layers, sum_B, H]
    stacked = torch.cat(means, 1)
    full_mean = stacked.mean(0)                            # average across layers -> [sum_B, H]
    layer_m4 = torch.cat([m[-5] for m in means], 0)
    mid = torch.cat([m[means[0].shape[0] // 2] for m in means], 0)
    mean = torch.cat([m[-1] for m in means], 0)              # last-layer masked mean per batch
    first = torch.cat(firsts, 0)
    final = torch.cat(finals, 0)
    return {"first": first, "final": final, "mean": mean, "full_mean": full_mean,
            "layer-4": layer_m4, "middle": mid}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--cap", type=int, default=1200, help="worlds per cell")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    worlds = [json.loads(l) for l in open(BANK / "worlds" / "TEST-IID.jsonl", encoding="utf-8")][: args.cap]
    prim = {}
    gold = {}
    for sub in args.substrates.split(","):
        p, rows = load_split(sub, "TEST-IID")
        prim[sub] = p
        g = {}
        for _i, w, lab in rows:
            pol = lab.get("policy", {})
            if pol.get("decision") == "ACT" and pol.get("action"):
                g[w] = json.dumps({"a": pol["action"], "g": pol.get("arguments", {})}, sort_keys=True)
        gold[sub] = g

    results = {"definition": {
        "delta": "encoder_minus_causal route exactness, same latent worlds, same rows",
        "interaction": "delta(A+B) - (delta(A)+delta(B))/2",
        "combos": [c for c, _ in COMBOS]}, "cells": {}, "interactions": {}}

    cell_scores = {}
    for combo_name, combo in COMBOS:
        rng = random.Random(12345)
        texts, meta = [], []
        for w in worlds:
            if combo_name == "base":
                names = {e["id"]: e["name"] for e in w["entities"]}
                sw, tmpl = w, "S1"
            else:
                sw, names, tmpl = SH.build_shifted(w, combo, random.Random(abs(hash(combo_name)) & 0xFFFF))
            texts.append(SH.render_facts(sw, names, tmpl))
            meta.append(w["world_id"])
        cell = {}
        for sub in args.substrates.split(","):
            means, firsts, finals = embed_rows(sub, texts, device)
            S = surfaces_from(means, firsts, finals)
            for surf in SURFACES:
                X = S[surf]
                mu, sd = X.mean(0), X.std(0).clamp(min=1e-4)
                Z = (X - mu) / sd
                y = torch.tensor([1 if gold[sub].get(w) else 0 for w in meta])
                keep = y == 1
                if keep.sum() < 50:
                    continue
                tr_i = torch.arange(len(meta))[: int(0.7 * len(meta))]
                te_i = torch.arange(len(meta))[int(0.7 * len(meta)):]
                tr_i = tr_i[keep[tr_i]]
                te_i = te_i[keep[te_i]]
                if len(tr_i) < 50 or len(te_i) < 30:
                    continue
                # route exact = argmax over train-seen route classes
                classes = sorted({gold[sub][meta[i]] for i in tr_i.tolist()})
                lmap = {c: k for k, c in enumerate(classes)}
                ytr = torch.tensor([lmap[gold[sub][meta[i]]] for i in tr_i.tolist()])
                net = fit_linear(Z[tr_i], ytr, len(classes), steps=300)
                with torch.no_grad():
                    pred = net(Z[te_i]).argmax(1)
                hit = sum(1 for k, i in enumerate(te_i.tolist()) if classes[pred[k]] == gold[sub][meta[i]])
                cell.setdefault(surf, {})[sub] = hit / max(len(te_i), 1)
            results["cells"][combo_name] = cell
        cell_scores[combo_name] = cell
        d = {s: (cell[s]["encoder"] - cell[s]["causal"]) for s in cell if "causal" in cell[s] and "encoder" in cell[s]}
        print(combo_name, json.dumps({k: round(v, 4) for k, v in d.items()}))

    for combo_name, combo in COMBOS:
        if len(combo) != 2:
            continue
        A, B = combo
        cell = cell_scores[combo_name]
        inter = {}
        for s in cell:
            dA = cell_scores[A].get(s, {}).get("encoder", 0) - cell_scores[A].get(s, {}).get("causal", 0)
            dB = cell_scores[B].get(s, {}).get("encoder", 0) - cell_scores[B].get(s, {}).get("causal", 0)
            dAB = cell[s]["encoder"] - cell[s]["causal"]
            inter[s] = {"delta_A": dA, "delta_B": dB, "delta_AB": dAB,
                        "interaction": dAB - (dA + dB) / 2}
        results["interactions"][combo_name] = inter

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "joint-decomposition.json").write_text(json.dumps(results, indent=2) + "\n")
    print("\nINTERACTIONS (interaction = delta_AB - mean(delta_A, delta_B))")
    for k, v in results["interactions"].items():
        print(" ", k, json.dumps({s: round(x["interaction"], 4) for s, x in v.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
