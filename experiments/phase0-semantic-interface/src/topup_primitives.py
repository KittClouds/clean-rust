"""Top up the released primitive cache to a full canonical BANK-v1 population.

Phase 0 exported 20,000 TRAIN / 2,000 DEV substrate rows, but those windows were interleaved
with paired (renderer) rows, so only 16,668 / 1,668 of them were canonical. The Phase 1
population contract is TRAIN = 20,000 canonical and DEV = 2,000 canonical.

This extends the cache with additional CANONICAL rows from the same BANK-v1 split files, using
the same frozen substrate, the same six surfaces, and the same entity-span extraction as
Phase 0. It writes a NEW file and never overwrites the Phase 0 artifact, so the frozen Phase 0
result stays reproducible and its hash unchanged.

Not touched: substrate weights, split identity, target semantics, candidate convention, the
protected/test split (never read), and BANK-v2 (never read).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[3]
EXTRACTOR = REPO / "experiments" / "encoder-contrast-01" / "src" / "extract_primitives.py"
BANK = REPO / "experiments" / "ff-s15-bank-01" / "releases" / "BANK-v1"
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")


def load_extractor():
    spec = importlib.util.spec_from_file_location("extract_primitives", EXTRACTOR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def usable(world: dict, row: dict) -> bool:
    """Exactly the filters src/data.py applies, so every row we add is actually joinable.

    Mirrors build(): world must be in the cache and the inputs file, must have a non-empty
    available_actions list of at most m_cap, and the row must carry entity bindings. build()
    does NOT require bindings to be a subset of the world's entity list (unbound args simply
    pad to -1), so neither do we.
    """
    cand = world.get("available_actions") or []
    if not cand or len(cand) > 24:
        return False
    return bool(row.get("bindings"))


def joinable(split: str, prim_path: Path, cap: int) -> tuple[int, list[str]]:
    """Mirror src.data.build exactly: take the first `cap` CANONICAL cache rows and count
    how many of those survive build()'s filters. Returns (kept, that ordered id list)."""
    prim = torch.load(prim_path, map_location="cpu", weights_only=False)
    order = [x for x in prim["row_ids"] if "@" not in x][:cap]
    order_set = set(order)
    worlds = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                w = json.loads(line)
                if w["world_id"] in order_set:
                    worlds[w["world_id"]] = w
    binds = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["world_id"] in order_set:
                    binds.setdefault(r["world_id"], r.get("bindings") or [])
    kept = 0
    for wid in order:
        w = worlds.get(wid)
        if w is None:
            continue
        cand = w.get("available_actions") or []
        if not cand or len(cand) > 24 or not binds.get(wid):
            continue
        kept += 1
    return kept, order



def reorder(payload: dict, split: str, cap: int) -> dict:
    """Deterministically order the cache so that build()'s canonical window is fully usable.

    build() reads the first `cap` CANONICAL row_ids and then applies its own join filters, so
    a non-joinable row sitting early in the window silently shrinks the population no matter
    how many usable rows are appended. We therefore order the cache:
        [joinable canonical] + [non-joinable canonical] + [paired renderer rows]
    preserving relative order within each group. Nothing is dropped and no split identity
    changes; paired rows are retained so Phase 0 renderer pairs still resolve.
    """
    ids = list(payload["row_ids"])
    binds = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                binds.setdefault(r["world_id"], r.get("bindings") or [])
    need = {x for x in ids if "@" not in x}
    worlds = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                w = json.loads(line)
                if w["world_id"] in need:
                    worlds[w["world_id"]] = w

    def ok(wid):
        w = worlds.get(wid)
        if w is None:
            return False
        cand = w.get("available_actions") or []
        return bool(cand) and len(cand) <= 24 and bool(binds.get(wid))

    a, b, p = [], [], []
    for wid in ids:
        if "@" in wid:
            p.append(wid)
        elif ok(wid):
            a.append(wid)
        else:
            b.append(wid)
    order = a + b + p
    pos = {wid: i for i, wid in enumerate(order)}

    old_ei = dict(payload["entity_index"])
    ent = payload["entity_vectors"]
    start, acc = [], 0
    for i in range(len(ids)):                       # entity span start per OLD row index
        start.append(acc)
        acc += len(old_ei[i])
    new_ent, new_ei = [], []
    for i, wid in enumerate(order):
        o = pos[wid]
        e = list(old_ei[o])
        new_ent.append(ent[start[o]:start[o] + len(e)])
        new_ei.append((i, e))
    out = dict(payload)
    out["row_ids"] = order
    out["surfaces"] = {s: payload["surfaces"][s][torch.tensor([pos[w] for w in order])]
                       for s in payload["surfaces"]}
    out["entity_vectors"] = (torch.cat(new_ent, 0) if new_ent
                             else payload["entity_vectors"][:0])
    out["entity_index"] = new_ei
    out["n_rows"] = len(order)
    out["reorder"] = {"joinable_canonical": len(a), "unjoinable_canonical": len(b),
                      "paired": len(p), "cap": cap}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", default="encoder")
    ap.add_argument("--split", required=True)
    ap.add_argument("--target-canonical", type=int, required=True)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--out-suffix", default="-full")
    args = ap.parse_args()

    ex = load_extractor()
    base = PRIM / args.substrate / f"{args.split}.pt"
    full = PRIM / args.substrate / f"{args.split}{args.out_suffix}.pt"
    # the population contract is measured in JOINABLE rows inside build()'s canonical window
    already, _ = joinable(args.split, full if full.is_file() else base, args.target_canonical)
    print(f"joinable canonical rows in build() window: {already}; "
          f"target {args.target_canonical}", flush=True)
    need = args.target_canonical - already
    if need <= 0:
        # population already met; still normalise the ordering so build()'s window is exact
        if not full.is_file():
            print("target met by the frozen Phase 0 cache; nothing to write")
            return 0
        payload = reorder(torch.load(full, map_location="cpu", weights_only=False),
                          args.split, args.target_canonical)
        torch.save(payload, full)
        final, _ = joinable(args.split, full, args.target_canonical)
        print(json.dumps({"written": str(full), "reorder_only": True,
                          "joinable_in_window": final, "target": args.target_canonical,
                          "target_met": final >= args.target_canonical}, indent=2))
        return 0 if final >= args.target_canonical else 1

    old = torch.load(base, map_location="cpu", weights_only=False)
    have = set(old["row_ids"])
    if full.is_file():
        prev = torch.load(full, map_location="cpu", weights_only=False)
        have = set(prev["row_ids"])
        old = prev
    print(f"cache rows {len(old['row_ids'])}, {len(have)} unique ids; need {need} more",
          flush=True)

    # stream worlds once, keeping only the ids we might need
    wanted = set()
    with (BANK / "inputs" / f"{args.split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            wid = r["world_id"]
            if "@" in wid or wid in have:
                continue
            wanted.add(wid)
    worlds = {}
    with (BANK / "worlds" / f"{args.split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            w = json.loads(line)
            wid = w["world_id"]
            if wid in wanted and wid not in have:
                worlds[wid] = w
                if len(worlds) >= need * 4:      # read-ahead for the usability filter
                    break
    print(f"worlds available for top-up: {len(worlds)}", flush=True)

    picked = []
    with (BANK / "inputs" / f"{args.split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            wid = r["world_id"]
            if wid in have or "@" in wid:
                continue
            w = worlds.get(wid)
            if w is None or not usable(w, r):
                continue
            picked.append(r)
            if len(picked) >= need:
                break
    print(f"selected {len(picked)} usable canonical rows", flush=True)
    if len(picked) < need:
        print(f"WARNING: only {len(picked)} of {need} available")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model, root = ex.load_substrate(args.substrate, device)
    n_layers = int(model.config.num_hidden_layers)
    idx = ex.last_layers(n_layers + 1)

    started = time.perf_counter()
    surf_buf = {s: [] for s in ex.SURFACES}
    ent_vecs, ent_offsets, row_ids, labels = [], [], [], []
    for start in range(0, len(picked), args.batch):
        chunk = picked[start:start + args.batch]
        enc = tok([r["input_text"] for r in chunk], return_tensors="pt", padding=True,
                  truncation=True, max_length=args.max_len, return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping")
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            hs = model(**enc, output_hidden_states=True).hidden_states
        mask = enc["attention_mask"].bool()
        sv = ex.surface_vectors(list(hs), mask, idx)
        for s in ex.SURFACES:
            surf_buf[s].append(sv[s])
        spans = [ex.mention_spans(r["input_text"], r.get("bindings", [])) for r in chunk]
        ent_vecs.append(ex.entity_span_vectors(hs[idx["final"]], mask, offsets.tolist(), spans))
        for r in chunk:
            row_ids.append(r["world_id"])
            ent_offsets.append((len(row_ids) - 1,
                                [b.get("entity_id") for b in (r.get("bindings") or [])]))
            labels.append({"world_id": r["world_id"], "decision": r.get("decision"),
                           "surface_family": r.get("surface_family"),
                           "difficulty": r.get("difficulty"), "labels": r.get("labels")})
        if start % (args.batch * 20) == 0:
            print(f"{args.split} {start + len(chunk)}/{len(picked)} "
                  f"{time.perf_counter() - started:.1f}s", flush=True)

    new_surf = {s: torch.cat(surf_buf[s], 0).to(torch.float16) for s in ex.SURFACES}
    new_ent = torch.cat(ent_vecs, 0).to(torch.float16) if ent_vecs else old["entity_vectors"][:0]

    n0 = len(old["row_ids"])
    payload = dict(old)
    payload["surfaces"] = {s: torch.cat([old["surfaces"][s], new_surf[s]], 0) for s in ex.SURFACES}
    payload["entity_vectors"] = torch.cat([old["entity_vectors"], new_ent], 0)
    payload["entity_index"] = list(old["entity_index"]) + [(n0 + i, e) for i, (_, e) in
                                                          enumerate(ent_offsets)]
    payload["row_ids"] = list(old["row_ids"]) + row_ids
    payload["labels"] = list(old["labels"]) + labels
    payload["n_rows"] = len(payload["row_ids"])
    payload["topup"] = {"rows_added": len(row_ids), "split": args.split,
                        "substrate": args.substrate, "source": "BANK-v1 canonical rows only",
                        "elapsed_seconds": round(time.perf_counter() - started, 2),
                        "frozen_phase0_file_untouched": True}
    payload = reorder(payload, args.split, args.target_canonical)

    outp = full
    torch.save(payload, outp)
    final, _ = joinable(args.split, outp, args.target_canonical)
    canon = len([i for i in payload["row_ids"] if "@" not in i])
    print(json.dumps({"written": str(outp), "cache_rows": payload["n_rows"],
                      "canonical_in_cache": canon, "joinable_in_window": final,
                      "target": args.target_canonical, "target_met": final >= args.target_canonical,
                      "elapsed": round(time.perf_counter() - started, 1),
                      "cuda": device}, indent=2))
    return 0 if final >= args.target_canonical else 1


if __name__ == "__main__":
    raise SystemExit(main())
