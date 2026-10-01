"""Lepori causal lane -- top up the primitive cache to the exhaustive candidate contract.

Inherited lesson #1: a candidate cap is not a formatting detail. On the encoder lane an
m_cap of 24 silently DROPPED every world with more than 24 actions -- 21,016 canonical worlds,
15% of the universe, 567,254 candidates never reachable. So the population contract here is
stated in JOINABLE rows inside build()'s own canonical window, measured against the real
m_max = 28, never assumed.

Writes a NEW cache. The base extraction is never overwritten, so the Phase 0 artifact stays
reproducible and its hash unchanged.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from src.extract_primitives import (BANK, SURFACES, MODEL_ROOT, load_substrate, surface_vectors,
                                    entity_span_vectors, mention_spans, sha_file)

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\primitives")


def usable(world: dict, row: dict, m_cap: int) -> bool:
    """Exactly the filters src/data.py applies, so every row added is actually joinable."""
    cand = world.get("available_actions") or []
    if not cand or len(cand) > m_cap:
        return False
    return bool(row.get("bindings"))


def load_worlds(split: str, want: set[str]) -> dict:
    out = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                w = json.loads(line)
                if w["world_id"] in want:
                    out[w["world_id"]] = w
    return out


def joinable(split: str, path: Path, cap: int, m_cap: int):
    """Mirror build(): first `cap` CANONICAL cache rows, then build()'s own filters."""
    prim = torch.load(path, map_location="cpu", weights_only=False)
    order = [x for x in prim["row_ids"] if "@" not in x][:cap]
    order_set = set(order)
    worlds = load_worlds(split, order_set)
    binds = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["world_id"] in order_set:
                    binds.setdefault(r["world_id"], r.get("bindings") or [])
    kept = []
    for wid in order:
        w = worlds.get(wid)
        if w is None:
            continue
        cand = w.get("available_actions") or []
        if not cand or len(cand) > m_cap or not binds.get(wid):
            continue
        kept.append(wid)
    return kept, order


def reorder(payload: dict, split: str, cap: int, m_cap: int) -> dict:
    """Order the cache so build()'s canonical window is fully usable.

    build() reads the first `cap` CANONICAL row_ids and then applies its own filters, so a
    non-joinable row sitting early silently shrinks the population no matter how many usable
    rows are appended. Order: [joinable canonical] + [non-joinable] + [paired renderer rows].
    Nothing is dropped and no split identity changes.
    """
    ids = list(payload["row_ids"])
    binds = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                binds.setdefault(r["world_id"], r.get("bindings") or [])
    need = {x for x in ids if "@" not in x}
    worlds = load_worlds(split, need)

    def ok(wid):
        w = worlds.get(wid)
        if w is None:
            return False
        cand = w.get("available_actions") or []
        return bool(cand) and len(cand) <= m_cap and bool(binds.get(wid))

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
    for i in range(len(ids)):
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
    out["entity_vectors"] = torch.cat(new_ent, 0) if new_ent else ent[:0]
    out["entity_index"] = new_ei
    out["n_rows"] = len(order)
    out["reorder"] = {"joinable_canonical": len(a), "unjoinable_canonical": len(b),
                      "paired": len(p), "cap": cap, "m_cap": m_cap}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--m-cap", type=int, default=28)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--suffix", default="-full")
    args = ap.parse_args()

    base = OUT / f"{args.split}.pt"
    full = OUT / f"{args.split}{args.suffix}.pt"
    kept, _ = joinable(args.split, full if full.is_file() else base, args.target, args.m_cap)
    print(f"joinable canonical rows in build() window: {len(kept)}; target {args.target}",
          flush=True)
    need = args.target - len(kept)

    old = torch.load(full if full.is_file() else base, map_location="cpu", weights_only=False)
    have = set(old["row_ids"])

    if need <= 0:
        if not full.is_file():
            print("target met by the base cache; nothing to write")
            return 0
        payload = reorder(old, args.split, args.target, args.m_cap)
        torch.save(payload, full)
        kept2, _ = joinable(args.split, full, args.target, args.m_cap)
        print(json.dumps({"written": str(full), "reorder_only": True,
                          "joinable_in_window": len(kept2), "target_met": len(kept2) >= args.target},
                         indent=2))
        return 0 if len(kept2) >= args.target else 1

    # ---- pick additional usable canonical rows not already cached
    wanted = set()
    with (BANK / "inputs" / f"{args.split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                wid = r["world_id"]
                if "@" not in wid and wid not in have:
                    wanted.add(wid)
    worlds = load_worlds(args.split, wanted)
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
            if w is None or not usable(w, r, args.m_cap):
                continue
            picked.append(r)
            if len(picked) >= need:
                break
    print(f"selected {len(picked)} additional usable canonical rows", flush=True)
    if len(picked) < need:
        print(f"WARNING: only {len(picked)} of {need} available")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = load_substrate(device)
    last_layer = max(l for l, _ in SURFACES.values())
    started = time.perf_counter()
    surf_buf = {s: [] for s in SURFACES}
    ent_vecs, ent_offsets, row_ids, labels = [], [], [], []
    for start in range(0, len(picked), args.batch):
        chunk = picked[start:start + args.batch]
        enc = tok([r["input_text"] for r in chunk], return_tensors="pt", padding=True,
                  truncation=True, max_length=args.max_len, return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping").tolist()
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.inference_mode():
            hs = model(**enc, output_hidden_states=True, use_cache=False).hidden_states
        mask = enc["attention_mask"].bool()
        sv = surface_vectors(hs, mask)
        for s in SURFACES:
            surf_buf[s].append(sv[s])
        spans = [mention_spans(r["input_text"], r.get("bindings", [])) for r in chunk]
        ent_vecs.append(entity_span_vectors(hs[last_layer], offsets, spans).cpu())
        for r in chunk:
            row_ids.append(r["world_id"])
            ent_offsets.append((len(row_ids) - 1,
                                [b.get("entity_id") for b in r.get("bindings", [])]))
            labels.append({"world_id": r["world_id"], "decision": r.get("decision"),
                           "surface_family": r.get("surface_family"),
                           "difficulty": r.get("difficulty")})
        if (start // args.batch) % 20 == 0:
            print(f"{args.split} topup {start + len(chunk)}/{len(picked)} "
                  f"{time.perf_counter() - started:.1f}s", flush=True)

    new_surf = {s: torch.cat(v, 0).to(torch.float16) for s, v in surf_buf.items()}
    new_ent = (torch.cat(ent_vecs, 0).to(torch.float16) if ent_vecs
               else old["entity_vectors"][:0])
    n0 = len(old["row_ids"])
    payload = dict(old)
    payload["surfaces"] = {s: torch.cat([old["surfaces"][s], new_surf[s]], 0) for s in SURFACES}
    payload["entity_vectors"] = torch.cat([old["entity_vectors"], new_ent], 0)
    payload["entity_index"] = list(old["entity_index"]) + [(n0 + i, e) for i, (_, e)
                                                           in enumerate(ent_offsets)]
    payload["row_ids"] = list(old["row_ids"]) + row_ids
    payload["labels"] = list(old["labels"]) + labels
    payload["n_rows"] = len(payload["row_ids"])
    payload["topup"] = {"rows_added": len(row_ids), "m_cap": args.m_cap,
                        "source": "BANK-v1 canonical rows only",
                        "elapsed_seconds": round(time.perf_counter() - started, 2),
                        "frozen_base_file_untouched": True}
    payload = reorder(payload, args.split, args.target, args.m_cap)
    torch.save(payload, full)
    kept2, _ = joinable(args.split, full, args.target, args.m_cap)
    canon = len([i for i in payload["row_ids"] if "@" not in i])
    rec = {"written": str(full), "cache_rows": payload["n_rows"],
           "canonical_in_cache": canon, "joinable_in_window": len(kept2),
           "target": args.target, "target_met": len(kept2) >= args.target,
           "rows_added": len(row_ids), "m_cap": args.m_cap,
           "elapsed_seconds": round(time.perf_counter() - started, 1), "device": device}
    print(json.dumps(rec, indent=2))
    return 0 if len(kept2) >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())
