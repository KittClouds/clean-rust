"""P6 role-binding under an explicit role-superseded interface.

Rendered from BANK-v1 canonical worlds (read-only) into this experiment's directory.
Variants, all over identical latent truth:

  role        : canonical surface, predicate text intact ("A is in B")
  swapped     : subject/object arguments transposed per fact (role text preserved but wrong)
  minimal     : entity mentions only, predicate and role words removed entirely

If bidirectionality solves *access* but the interface must still preserve binding,
then removing role text should collapse directed-edge accuracy for BOTH substrates,
and the encoder should retain more of its edge signal in the role-intact variant than
the causal model does.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch

from src.readout import fit_linear, accuracy
from src.probes import ent_lookup, PRIM, EDGES, auc

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")
RENDER = Path(r"D:\codex-runs\encoder-contrast-01\role-contrasts")


def role_text(f: dict, ents: dict, swapped: bool = False) -> str:
    p = f["pred"]
    a = list(f["args"])
    if swapped and len(a) >= 2:
        a = [a[1], a[0]] + a[2:]
    n = lambda x: ents.get(x, x)
    v = f.get("value")
    if p == "AT":
        return f"{n(a[0])} is in {n(a[1])}"
    if p == "CONNECTED":
        return f"{n(a[0])} connects to {n(a[1])}"
    if p == "STATE":
        return f"{n(a[0])} is {str(v).lower()}"
    if p == "REQUIRES":
        sw = (v or {}).get("switch")
        return f"{n(a[0])} requires {n(sw)}"
    if p == "BLOCKED":
        return f"passage {n(a[0])} to {n(a[1])} is blocked"
    if p == "BEFORE":
        return f"{n(a[0])} is before {n(a[1])}"
    if p == "PART_OF":
        return f"{n(a[0])} is part of {n(a[1])}"
    if p == "ENABLES":
        return f"{n(a[0])} enables {n(a[1])}"
    if p == "OWNS":
        return f"{n(a[0])} owns {n(a[1])}"
    if p == "HAS":
        return f"{n(a[0])} has {n(a[1])}"
    return f"{p}"


def render_variant(w: dict, variant: str, salt: int = 0) -> str:
    ents = {e["id"]: e["name"] for e in w["entities"]}
    facts = [f for f in w["initial_state"] if f["pred"] in EDGES and len(f.get("args", [])) >= 2]
    if variant == "role":
        lines = [role_text(f, ents) for f in facts]
    elif variant == "swapped":
        lines = [role_text(f, ents, swapped=True) for f in facts]
    elif variant == "minimal":
        lines = []
        for f in facts:
            a = f["args"]
            lines.append(f"{ents.get(a[0], a[0])} {ents.get(a[1], a[1])}")
    elif variant in ("role_shuf", "minimal_shuf"):
        # Randomize mention order inside each fact line. This destroys the
        # text-adjacency shortcut, so the ONLY remaining cue for edge direction
        # is the role/position word. Comparing role_shuf vs minimal_shuf
        # therefore isolates role binding from adjacency.
        shuf = variant == "role_shuf"
        lines = []
        for k, f in enumerate(facts):
            a = list(f["args"])
            if random.Random(abs(hash(w["world_id"])) + k * 7919 + salt).random() < 0.5:
                a = [a[1], a[0]] + a[2:]
            if shuf:
                lines.append(role_text(dict(f, args=a), ents))
            else:
                lines.append(f"{ents.get(a[0], a[0])} {ents.get(a[1], a[1])}")
    else:
        raise ValueError(variant)
    goal = w["goal"]
    gl = f"Goal: {goal.get('pred')}({','.join(str(x) for x in goal.get('args', []))})"
    return ". ".join(lines) + ".\n" + gl


def build_split_rows(worlds, variant, salt: int = 0):
    rows = []
    for w in worlds:
        rows.append({"world_id": w["world_id"], "text": render_variant(w, variant, salt),
                     "entities": [{"id": e["id"], "name": e["name"]} for e in w["entities"]]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrates", default="causal,encoder")
    ap.add_argument("--train-cap", type=int, default=6000)
    ap.add_argument("--eval-cap", type=int, default=1500)
    ap.add_argument("--batch", type=int, default=24)
    args = ap.parse_args()

    from src.extract_primitives import load_substrate, mention_spans, entity_span_vectors
    worlds_tr = [json.loads(l) for l in open(BANK / "worlds" / "TRAIN.jsonl", encoding="utf-8")][: args.train_cap]
    worlds_ev = [json.loads(l) for l in open(BANK / "worlds" / "TEST-IID.jsonl", encoding="utf-8")][: args.eval_cap]

    results = {"variants": {}, "definition": {
        "role": "canonical predicate text",
        "swapped": "subject/object transposed",
        "minimal": "entity mentions only, no predicate or role words",
        "role_shuf": "predicate text intact, mention order randomized per fact (kills adjacency cue)",
        "minimal_shuf": "mentions only, order randomized (kills adjacency, leaves no role cue)"}}
    for variant in ("role", "minimal", "role_shuf", "minimal_shuf"):
        for sub in args.substrates.split(","):
            device = "cuda" if torch.cuda.is_available() else "cpu"
            tok, model, root = load_substrate(sub, device)
            n_layers = int(model.config.num_hidden_layers)
            feats = {}
            for tag, ws in (("train", worlds_tr), ("eval", worlds_ev)):
                rows = build_split_rows(ws, variant)
                E = []
                for s in range(0, len(rows), args.batch):
                    chunk = rows[s : s + args.batch]
                    enc = tok([r["text"] for r in chunk], return_tensors="pt", padding=True,
                              truncation=True, max_length=512, return_offsets_mapping=True)
                    offs = enc.pop("offset_mapping")
                    enc = {k: v.to(device) for k, v in enc.items()}
                    with torch.no_grad():
                        hs = model(**enc, output_hidden_states=True).hidden_states[-1]
                    mask = enc["attention_mask"].bool()
                    spans = [mention_spans(r["text"], [{"mention": e["name"]} for e in r["entities"]]) for r in chunk]
                    ev = entity_span_vectors(hs, mask, offs.tolist(), spans)
                    n = 0
                    for r in chunk:
                        k = len(r["entities"])
                        E.append(ev[n : n + k])
                        n += k
                feats[tag] = E
            # per-tag counters: each tag has its own concatenated entity tensor
            look = {}
            for tag, ws in (("train", worlds_tr), ("eval", worlds_ev)):
                running = 0
                for r in build_split_rows(ws, variant):
                    for k, e in enumerate(r["entities"]):
                        look[(tag, r["world_id"], e["id"])] = running + k
                    running += len(r["entities"])
            ent_tr = torch.cat([t for t in feats["train"]], 0).float()
            ent_ev = torch.cat([t for t in feats["eval"]], 0).float()

            def pairs(ws, tag, directed):
                X, y = [], []
                for w in ws:
                    eids = [e["id"] for e in w["entities"]]
                    edges = set()
                    for f in w["initial_state"]:
                        if f["pred"] in EDGES and len(f.get("args", [])) >= 2:
                            a, b = f["args"][0], f["args"][1]
                            if a in eids and b in eids:
                                edges.add((a, b))
                    if not edges:
                        continue
                    rng = random.Random(abs(hash(w["world_id"])) & 0xFFFF)
                    seen = set()
                    negs = []
                    tries = 0
                    while len(negs) < len(edges) and tries < 400:
                        tries += 1
                        a, b = rng.choice(eids), rng.choice(eids)
                        if a == b or (a, b) in edges or (b, a) in edges or (a, b) in seen:
                            continue
                        seen.add((a, b))
                        negs.append((a, b))
                    for a, b in sorted(edges):
                        if directed and (b, a) in edges:
                            continue
                        X.append(((a, b), w["world_id"])); y.append(1)
                        if directed:
                            X.append(((b, a), w["world_id"])); y.append(0)
                    for a, b in negs:
                        X.append(((a, b), w["world_id"])); y.append(0)
                return X, y

            def build(P, tag, E):
                out = []
                for (a, b), wid in P:
                    ia, ib = look.get((tag, wid, a)), look.get((tag, wid, b))
                    if ia is None or ib is None:
                        continue
                    out.append(torch.cat([E[ia], E[ib]]))
                return torch.stack(out) if out else torch.zeros(0, 2048)

            entry = {}
            for task, directed in (("undirected_edge", False), ("directed_edge_role", True)):
                Xtr, ytr = pairs(worlds_tr, "train", directed)
                Xev, yev = pairs(worlds_ev, "eval", directed)
                A, B = build(Xtr, "train", ent_tr), build(Xev, "eval", ent_ev)
                if A.shape[0] < 200 or B.shape[0] < 100:
                    entry[task] = {"status": "insufficient", "n_train": int(A.shape[0]), "n_eval": int(B.shape[0])}
                    continue
                ya, yb = torch.tensor(ytr[: A.shape[0]]), torch.tensor(yev[: B.shape[0]])
                mu, sd = A.mean(0), A.std(0).clamp(min=1e-4)
                net = fit_linear((A - mu) / sd, ya, 2, steps=600)
                with torch.no_grad():
                    p = torch.softmax(net((B - mu) / sd), 1)[:, 1]
                entry[task] = {"auc": auc(yb, p), "acc": accuracy(yb, (p > 0.5).long()),
                               "n_train": int(A.shape[0]), "n_eval": int(B.shape[0])}
            results["variants"].setdefault(variant, {})[sub] = entry
            del model
            torch.cuda.empty_cache()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p6-role-contrast.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
