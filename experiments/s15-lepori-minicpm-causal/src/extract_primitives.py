"""Lepori causal lane -- BANK-v1 primitive extraction for MiniCPM5-1B-Base.

One pass over BANK-v1 rows. Produces the six declared causal surfaces plus entity-span vectors.

Read-only against BANK-v1. No downstream heads here, no supervision, no protected split.

Design notes that come from the parked encoder lineage, not from taste:
  * the six surfaces are DEPTH-DIVERSE (layers 6/12/18/24), because this substrate's validated
    affordance is a full internal stack; the encoder lane's surfaces were all near-final;
  * every surface is stored already per-surface normalised, because MiniCPM's hidden scale
    varies ~6x with depth and unnormalised cross-surface mixing lets shallow surfaces dominate;
  * candidate handling is NOT decided here. The candidate universe is measured from canonical
    BANK truth and the cap is 28, never a typed constant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

REPO = Path(__file__).resolve().parents[2]          # -> .../experiments
BANK = REPO / "ff-s15-bank-01" / "releases" / "BANK-v1"
MODEL_ROOT = Path(r"D:\codex-runs\jev-zero-training-recon-v01\models\minicpm5-1b-base")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\primitives")

# validated depths -> (layer_index, pooling) for the six declared surfaces
SURFACES = {
    "lt@24": (24, "last_token"),
    "mf@24": (24, "mean_full"),
    "ms@24": (24, "mean_suffix"),
    "mf@18": (18, "mean_full"),
    "mf@12": (12, "mean_full"),
    "mf@6": (6, "mean_full"),
}
SUFFIX_WINDOW = 16


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_jsonl(p: Path, limit: int | None = None):
    out = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            if line.strip():
                out.append(json.loads(line))
    return out


def load_substrate(device: str):
    tok = AutoTokenizer.from_pretrained(str(MODEL_ROOT), local_files_only=True, use_fast=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token or tok.unk_token
    tok.padding_side = "right"
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_ROOT), local_files_only=True, dtype=torch.bfloat16,
        low_cpu_mem_usage=True).to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)
    return tok, model


def pooled(h: torch.Tensor, mask: torch.Tensor, how: str) -> torch.Tensor:
    """h [B,T,H]; mask [B,T] bool of real tokens. Returns [B,H] float32."""
    lens = mask.sum(1)
    if how == "last_token":
        idx = (lens - 1).clamp(min=0)
        return h[torch.arange(h.shape[0], device=h.device), idx].float()
    rows = []
    for i in range(h.shape[0]):
        end = int(lens[i])
        start = max(0, end - SUFFIX_WINDOW) if how == "mean_suffix" else 0
        rows.append(h[i, start:end].float().mean(0))
    return torch.stack(rows)


def surface_vectors(hs, mask) -> dict[str, torch.Tensor]:
    out = {}
    for name, (layer, how) in SURFACES.items():
        v = pooled(hs[layer], mask, how)
        # per-surface standardisation: MiniCPM hidden scale varies ~6x with depth
        out[name] = ((v - v.mean(0)) / v.std(0).clamp(min=1e-6)).cpu()
    return out


def mention_spans(text: str, bindings: list[dict]):
    spans = []
    for b in bindings:
        m = b.get("mention")
        i = text.find(m) if m else -1
        spans.append((i, i + len(m)) if i >= 0 else (None, None))
    return spans


def entity_span_vectors(h_last, offsets, mentions):
    """Mean-pool final-depth states over mention token spans. [n_entities, H] float32."""
    B, T, H = h_last.shape
    feats = []
    for b in range(B):
        spans = mentions[b]
        if not spans:
            feats.append(torch.zeros(0, H, device=h_last.device))
            continue
        rows = []
        for s, e in spans:
            if s is None:
                rows.append(torch.zeros(H, device=h_last.device))
                continue
            tok_idx = [t for t in range(T)
                       if offsets[b][t][1] > s and offsets[b][t][0] < e]
            rows.append(h_last[b, tok_idx].float().mean(0) if tok_idx
                        else torch.zeros(H, device=h_last.device))
        feats.append(torch.stack(rows))
    return torch.cat(feats, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--out-name", default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    src = BANK / "inputs" / f"{args.split}.jsonl"
    rows = read_jsonl(src, args.limit)
    tok, model = load_substrate(device)
    n_layers = int(model.config.num_hidden_layers)
    OUT.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    surf_buf = {s: [] for s in SURFACES}
    ent_vecs, ent_offsets, row_ids, labels = [], [], [], []
    last_layer = max(l for l, _ in SURFACES.values())
    for start in range(0, len(rows), args.batch):
        chunk = rows[start:start + args.batch]
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
        for r in chunk:
            labels.append({"world_id": r["world_id"], "decision": r.get("decision"),
                           "surface_family": r.get("surface_family"),
                           "difficulty": r.get("difficulty")})
        if (start // args.batch) % 20 == 0:
            print(f"{args.split} {start + len(chunk)}/{len(rows)} "
                  f"{time.perf_counter() - started:.1f}s", flush=True)

    surfaces = {s: torch.cat(v, 0).to(torch.float16) for s, v in surf_buf.items()}
    ents = torch.cat(ent_vecs, 0).to(torch.float16) if ent_vecs else torch.zeros(0, 1536)
    payload = {
        "substrate": "minicpm5-1b-base", "model_root": str(MODEL_ROOT),
        "fabric": "causal", "split": args.split, "n_rows": len(rows),
        "surfaces": surfaces, "entity_vectors": ents, "entity_index": ent_offsets,
        "row_ids": row_ids, "labels": labels,
        "hidden": int(model.config.hidden_size), "n_layers": n_layers,
        "surface_defs": {k: {"layer": v[0], "pooling": v[1]} for k, v in SURFACES.items()},
        "per_surface_normalised": True,
        "max_len": args.max_len,
    }
    name = args.out_name or args.split
    outp = OUT / f"{name}.pt"
    torch.save(payload, outp)
    receipt = {
        "status": "PRIMITIVES_EXTRACTED", "split": args.split, "rows": len(rows),
        "substrate": "minicpm5-1b-base", "hidden": payload["hidden"],
        "n_layers": n_layers, "surfaces": {s: list(surfaces[s].shape) for s in SURFACES},
        "surface_layers": {k: v["layer"] for k, v in payload["surface_defs"].items()},
        "entity_vectors": list(ents.shape), "file": str(outp), "sha256": sha_file(outp),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "cuda_peak_bytes": int(torch.cuda.max_memory_allocated()) if device == "cuda" else 0,
        "device": device, "per_surface_normalised": True,
    }
    (OUT / f"{name}-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
