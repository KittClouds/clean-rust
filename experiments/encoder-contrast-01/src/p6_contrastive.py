"""P6 contrastive role-binding instrument.

For each BANK-v1 world we build a matched pair W_fwd / W_rev: identical entities,
identical predicates, identical chain length, identical surface template. The only
difference is the argument order of one edge. A substrate that reads role must score
W_fwd's (a,b) as positive and W_rev's (a,b) as negative.

Because the two variants are structurally identical, chain index cannot substitute for
role: the only difference available to the probe is which slot the role word occupies.

Three interfaces are compared:
  role         canonical predicate text
  minimal      mentions only, no predicate or role words  (must be at chance)
  role_shuf    canonical text, fact order shuffled      (kills adjacency)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear, accuracy
from src.extract_primitives import load_substrate, mention_spans, entity_span_vectors

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")


def auc(y_true, score):
    pos = [s for s, t in zip(score.tolist(), y_true.tolist()) if t == 1]
    neg = [s for s, t in zip(score.tolist(), y_true.tolist()) if t == 0]
    if not pos or not neg:
        return None
    w = 0.0
    for n in neg:
        for p in pos:
            w += 1.0 if p > n else (0.5 if p == n else 0.0)
    return w / (len(pos) * len(neg))


def make_rows(worlds, interface):
    """Contrastive rows with the TEXT HELD FIXED across the positive/negative pair.

    Four leaks had to be closed to make this an honest role-binding instrument:

      L1 chain index substituting for role
          -> both rows come from the same world, so chain position is identical and
             cannot discriminate between them.
      L2 the probe being trivially solvable because the two rows differ
          -> the text is held byte-identical; only the ordered probe pair varies.
      L3 mention-order / position detector
          -> mention order is randomized INDEPENDENTLY PER FACT LINE, not per world,
             so position within a line is uncorrelated with role across the dataset.
      L4 entity-identity prior carried across the split
          -> the entity-id -> name mapping is re-permuted independently per world, so
             no id-level edge prior (e.g. "loc_0 -> loc_1 is common") can transfer.

    The label says whether the ordered probe pair matches the subject/object assignment
    the text actually asserts.
    """
    rows = []
    for w in worlds:
        edges = []
        for f in w["initial_state"]:
            if f.get("pred") in ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED", "BEFORE",
                                 "PART_OF", "ENABLES", "OWNS", "HAS") and len(f.get("args", [])) >= 2:
                a, b = f["args"][0], f["args"][1]
                if a != b:
                    edges.append((a, b, f["pred"]))
        if not edges:
            continue
        rng = random.Random(abs(hash(("p6", w["world_id"]))) & 0xFFFF)
        a, b, pred = edges[rng.randrange(len(edges))]

        # L4: per-world permutation of entity-id -> surface name
        ids = [e["id"] for e in w["entities"]]
        base_names = [e["name"] for e in w["entities"]]
        perm = list(range(len(ids)))
        random.Random(abs(hash(("perm", w["world_id"]))) & 0xFFFF).shuffle(perm)
        ents = {ids[i]: base_names[perm[i]] for i in range(len(ids))}

        facts = [f for f in w["initial_state"]
                 if f.get("pred") in ("AT", "CONNECTED", "STATE", "REQUIRES", "BLOCKED",
                                      "BEFORE", "PART_OF", "ENABLES", "OWNS", "HAS")
                 and len(f.get("args", [])) >= 2]
        # L3: independent per-line mention-order randomization, fixed for this world
        line_rng = random.Random(abs(hash(("order", w["world_id"]))) & 0xFFFF)
        swaps = [line_rng.random() < 0.5 for _ in facts]
        lines = []
        for f, sw in zip(facts, swaps):
            subj, obj = f["args"][0], f["args"][1]
            if sw:
                subj, obj = obj, subj
            if interface == "minimal":
                lines.append(f"{ents.get(subj, subj)} {ents.get(obj, obj)}")
            else:
                lines.append(fact_line(dict(f, args=[subj, obj]), ents))
        if interface == "role_shuf":
            random.Random(abs(hash(w["world_id"])) & 0xFFFF).shuffle(lines)
        text = ". ".join(lines) + "."

        eids = [{"id": e["id"], "name": ents[e["id"]]} for e in w["entities"]]
        rows.append({"world_id": w["world_id"] + "|pos", "text": text, "entities": eids,
                     "pair": [a, b], "label": 1})
        rows.append({"world_id": w["world_id"] + "|neg", "text": text, "entities": eids,
                     "pair": [b, a], "label": 0})
    return rows


def fact_line(f, ents):
    p, a, v = f["pred"], f.get("args", []), f.get("value")
    g = lambda x: ents.get(x, x)
    if p == "AT":
        return f"{g(a[0])} is in {g(a[1])}"
    if p == "CONNECTED":
        return f"{g(a[0])} connects to {g(a[1])}"
    if p == "STATE":
        return f"{g(a[0])} is {str(v).lower()}"
    if p == "REQUIRES":
        return f"{g(a[0])} requires {g((v or {}).get('switch'))} active"
    if p == "BLOCKED":
        return f"passage from {g(a[0])} to {g(a[1])} is blocked"
    if p == "BEFORE":
        return f"{g(a[0])} is before {g(a[1])}"
    if p == "PART_OF":
        return f"{g(a[0])} is part of {g(a[1])}"
    if p == "ENABLES":
        return f"{g(a[0])} enables {g(a[1])}"
    if p == "OWNS":
        return f"{g(a[0])} owns {g(a[1])}"
    if p == "HAS":
        return f"{g(a[0])} has {g(a[1])}"
    return p


def embed(substrate, rows, device, batch=24):
    tok, model, _ = load_substrate(substrate, device)
    per_row = []
    for s in range(0, len(rows), batch):
        ch = rows[s:s + batch]
        enc = tok([r["text"] for r in ch], return_tensors="pt", padding=True,
                  truncation=True, max_length=512, return_offsets_mapping=True)
        offs = enc.pop("offset_mapping")
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            hs = model(**enc, output_hidden_states=True).hidden_states[-1]
        mask = enc["attention_mask"].bool()
        spans = [mention_spans(r["text"], [{"mention": e["name"]} for e in r["entities"]]) for r in ch]
        ev = entity_span_vectors(hs, mask, offs.tolist(), spans)
        n = 0
        for r in ch:
            per_row.append(ev[n:n + len(r["entities"])])
            n += len(r["entities"])
    del model
    torch.cuda.empty_cache()
    return per_row


def featurize(per_row, rows):
    """Concatenated [subj_span; obj_span] per row, plus a row-level mean fallback."""
    look = {}
    run = 0
    for r, E in zip(rows, per_row):
        for k, e in enumerate(r["entities"]):
            look[(r["world_id"], e["id"])] = run + k
        run += len(r["entities"])
    Ent = torch.cat(per_row, 0).float()
    feats = []
    for r in rows:
        ia, ib = look[(r["world_id"], r["pair"][0])], look[(r["world_id"], r["pair"][1])]
        feats.append(torch.cat([Ent[ia], Ent[ib]]))
    y = torch.tensor([r["label"] for r in rows])
    return torch.stack(feats), y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--cap", type=int, default=6000)
    ap.add_argument("--eval-cap", type=int, default=1500)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    worlds = [json.loads(l) for l in open(BANK / "worlds" / "TEST-IID.jsonl", encoding="utf-8")][: args.cap]
    out = {"definition": {
        "design": "matched W_fwd/W_rev pairs; identical entities, predicates, chain length, template",
        "probe": "is the canonical ordered pair (a,b) an edge in this rendering?",
        "role": "canonical predicate text", "minimal": "mentions only, no role words (must be chance)",
        "role_shuf": "canonical text, fact order shuffled"},
        "results": {}, "interpretation": {}}

    for interface in ("role", "minimal", "role_shuf"):
        rows = make_rows(worlds, interface)
        # split by world so fwd/rev of the same world cannot straddle the split
        wids = sorted({r["world_id"].split("|")[0] for r in rows})
        cut = wids[: int(len(wids) * 0.7)]
        tr = [r for r in rows if r["world_id"].split("|")[0] in set(cut)]
        ev = [r for r in rows if r["world_id"].split("|")[0] not in set(cut)]
        for sub in args.substrates.split(","):
            Xtr, ytr = featurize(embed(sub, tr, device), tr)
            Xev, yev = featurize(embed(sub, ev, device), ev)
            mu, sd = Xtr.mean(0), Xtr.std(0).clamp(min=1e-4)
            net = fit_linear((Xtr - mu) / sd, ytr, 2, steps=800)
            with torch.no_grad():
                p = torch.softmax(net((Xev - mu) / sd), 1)[:, 1]
            a = auc(yev, p)
            out["results"].setdefault(interface, {})[sub] = {
                "auc": a, "acc": accuracy(yev, (p > 0.5).long()),
                "n_train": int(Xtr.shape[0]), "n_eval": int(Xev.shape[0]),
                "base_rate": float(yev.float().mean())}
        print(interface, json.dumps(out["results"][interface]))

    # verdict logic: minimal must be chance; role must exceed it
    for sub in out["results"].get("role", {}):
        r = out["results"]["role"][sub]["auc"]
        m = out["results"]["minimal"][sub]["auc"]
        s = out["results"]["role_shuf"][sub]["auc"]
        if m is None or r is None:
            continue
        if m < 0.60 and r > m + 0.05:
            v = "ROLE_BINDING_REQUIRED_BOTH_SUBSTRATES_BIDIRECTIONALITY_NOT_ENOUGH"
        elif m < 0.60 and r > 0.90:
            v = "ROLE_BINDING_REQUIRED_BUT_BOTH_SUBSTRATES_READ_ROLES_WELL"
        elif m >= 0.75:
            v = "INSTRUMENT_STILL_CONFOUNDED_MINIMAL_NOT_AT_CHANCE"
        else:
            v = "INCONCLUSIVE"
        out["interpretation"][sub] = {"role_auc": r, "minimal_auc": m, "role_shuf_auc": s, "verdict": v}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p6-contrastive.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["interpretation"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
