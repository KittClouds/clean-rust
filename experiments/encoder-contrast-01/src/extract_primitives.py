"""ENCODER-CONTRAST-01 primitives extraction.

One pass per substrate over BANK-v1 rows. Extracts row-level surfaces, entity-span
vectors, and (optionally) full token-level states for a fixed subset.

Read-only against BANK-v1. No downstream heads here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch

ENCODER_ROOT = Path(r"D:\codex-runs\encoder-contrast-01\models\LFM2.5-Encoder-230M")
ENCODER_REV = "0b649ad0c684378b03d4d8304f7577a662ab89bc"
CAUSAL_ROOT = Path(r"D:\phoenix-models\lfm2.5-230m-base-9d2be55")
BANK = Path(__file__).resolve().parents[2] / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01")

SURFACES = ["first", "final", "mean", "full_mean", "layer-4", "middle"]


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
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


def load_substrate(kind: str, device: str):
    from transformers import AutoModel, AutoModelForMaskedLM, AutoTokenizer
    root = ENCODER_ROOT if kind == "encoder" else CAUSAL_ROOT
    tok = AutoTokenizer.from_pretrained(root, trust_remote_code=True)
    if kind == "encoder":
        # The published checkpoint's keys are prefixed `lfm2.` and only match
        # Lfm2BidirectionalForMaskedLM. Loading AutoModel here silently
        # random-initializes every weight, so load the MLM wrapper and take .lfm2.
        wrapper = AutoModelForMaskedLM.from_pretrained(root, trust_remote_code=True)
        model = wrapper.lfm2
    else:
        model = AutoModel.from_pretrained(root, trust_remote_code=True)
    model.to(device).eval()
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token if tok.eos_token else tok.unk_token
    return tok, model, root


def last_layers(n_total: int) -> dict[str, int]:
    """Index into hidden_states tuple (len = n_layers+1)."""
    return {"final": n_total - 1, "layer-4": n_total - 5, "middle": n_total // 2}


def surface_vectors(hs: list[torch.Tensor], mask: torch.Tensor, idx: dict[str, int]) -> dict[str, torch.Tensor]:
    """hs: list of [B,T,H]; mask: [B,T] bool of real tokens."""
    mf = mask.unsqueeze(-1).to(hs[-1].dtype)
    lens = mf.sum(1).clamp(min=1)

    def masked_mean(t: torch.Tensor) -> torch.Tensor:
        m = mask.unsqueeze(-1).to(t.dtype)
        return (t * m).sum(1) / m.sum(1).clamp(min=1)

    last = hs[idx["final"]]
    first_idx = mask.float().argmax(dim=1)
    b = torch.arange(last.shape[0], device=last.device)
    last_idx = mask.sum(1) - 1
    out = {
        "first": last[b, first_idx],
        "final": last[b, last_idx],
        "mean": masked_mean(last),
        "layer-4": masked_mean(hs[idx["layer-4"]]),
        "middle": masked_mean(hs[idx["middle"]]),
    }
    # full_mean: mean across all layers of per-layer masked means
    per_layer = torch.stack([masked_mean(h) for h in hs], 0)  # [L,B,H]
    out["full_mean"] = per_layer.mean(0)
    return {k: v.float().cpu() for k, v in out.items()}


def entity_span_vectors(hs_last: torch.Tensor, mask: torch.Tensor, offsets, mentions) -> torch.Tensor:
    """Mean-pool final-layer states over token spans aligned to mention char offsets.

    Returns [n_entities, H]; rows left zero if no span resolved.
    """
    B, T, H = hs_last.shape
    device = hs_last.device
    feats = []
    for b in range(B):
        spans = mentions[b]
        if not spans:
            feats.append(torch.zeros(0, H, device=hs_last.device))
            continue
        rows = []
        for s, e in spans:
            if s is None or e is None:
                rows.append(torch.zeros(H, device=hs_last.device))
                continue
            tok_idx = [t for t in range(T) if offsets[b][t][1] > s and offsets[b][t][0] < e]
            if not tok_idx:
                rows.append(torch.zeros(H, device=hs_last.device))
            else:
                sel = hs_last[b, tok_idx]
                rows.append(sel.mean(0))
        feats.append(torch.stack(rows).to(hs_last.device))
    return torch.cat(feats, 0).float().cpu() if feats else torch.zeros(0, H)


def mention_spans(text: str, bindings: list[dict]) -> list[tuple[int | None, int | None]]:
    spans = []
    for b in bindings:
        m = b.get("mention")
        i = text.find(m) if m else -1
        if i >= 0:
            spans.append((i, i + len(m)))
        else:
            spans.append((None, None))
    return spans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substrate", choices=["encoder", "causal"], required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--token-subset", type=int, default=0, help="store full token states for first N rows")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    src = BANK / "inputs" / f"{args.split}.jsonl" if args.split in ("TRAIN", "DEV") else BANK / "public" / "test-inputs" / f"{args.split}.jsonl"
    if args.split == "TRAIN":
        rows = read_jsonl(src, args.limit)
    else:
        rows = read_jsonl(src, args.limit)
    tok, model, root = load_substrate(args.substrate, device)
    n_layers = int(model.config.num_hidden_layers)
    idx = last_layers(n_layers + 1)
    enc_out = OUT / "primitives" / args.substrate
    enc_out.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    surf_buf = {s: [] for s in SURFACES}
    ent_vecs, ent_offsets, row_ids = [], [], []
    labels = []
    tok_store, tok_rows = [], []
    for start in range(0, len(rows), args.batch):
        chunk = rows[start : start + args.batch]
        texts = [r["input_text"] for r in chunk]
        enc = tok(texts, return_tensors="pt", padding=True, truncation=True, max_length=args.max_len, return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping")
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            out = model(**enc, output_hidden_states=True)
        hs = out.hidden_states
        mask = enc["attention_mask"].bool()
        sv = surface_vectors(list(hs), mask, idx)
        for s in SURFACES:
            surf_buf[s].append(sv[s])
        spans = [mention_spans(r["input_text"], r.get("bindings", [])) for r in chunk]
        ev = entity_span_vectors(hs[idx["final"]], mask, offsets.tolist(), spans)
        ent_vecs.append(ev)
        for local_i, r in enumerate(chunk):
            row_ids.append(r["world_id"])
            # global row index, not within-batch index
            ent_offsets.append((len(row_ids) - 1, [b.get("entity_id") for b in r.get("bindings", [])]))
        for r in chunk:
            labels.append({"world_id": r["world_id"], "decision": r.get("decision"),
                           "surface_family": r.get("surface_family"),
                           "difficulty": r.get("difficulty"),
                           "labels": r.get("labels")})
        if args.token_subset and start + args.batch <= args.token_subset:
            for bi in range(len(chunk)):
                tok_store.append(hs[idx["final"]][bi, : mask[bi].sum()].float().cpu().to(torch.float16))
                tok_rows.append(chunk[bi]["world_id"])
        if (start // args.batch) % 20 == 0:
            done = start + len(chunk)
            print(f"{args.split} {done}/{len(rows)} elapsed={time.perf_counter()-started:.1f}s", flush=True)

    surfaces = {s: torch.cat(surf_buf[s], 0).to(torch.float16) for s in SURFACES}
    ents = torch.cat(ent_vecs, 0).to(torch.float16) if ent_vecs else torch.zeros(0, 1024, dtype=torch.float16)
    payload = {
        "substrate": args.substrate,
        "model_root": str(root),
        "model_revision": ENCODER_REV if args.substrate == "encoder" else "9d2be55",
        "split": args.split,
        "n_rows": len(rows),
        "surfaces": surfaces,
        "entity_vectors": ents,
        "entity_index": ent_offsets,
        "row_ids": row_ids,
        "labels": labels,
        "layer_indices": idx,
        "hidden": int(model.config.hidden_size),
        "n_layers": n_layers,
        "max_len": args.max_len,
    }
    outp = Path(args.out) if args.out else enc_out / f"{args.split}.pt"
    torch.save(payload, outp)
    receipt = {
        "status": "PRIMITIVES_EXTRACTED",
        "substrate": args.substrate,
        "split": args.split,
        "rows": len(rows),
        "surfaces": {s: list(surfaces[s].shape) for s in SURFACES},
        "entity_vectors": list(ents.shape),
        "file": str(outp),
        "sha256": sha_file(outp),
        "elapsed_seconds": time.perf_counter() - started,
        "cuda_peak_bytes": int(torch.cuda.max_memory_allocated()) if device == "cuda" else 0,
        "device": device,
    }
    (enc_out / f"{args.split}-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if tok_store:
        torch.save({"rows": tok_rows, "states": tok_store}, enc_out / f"{args.split}-token-subset.pt")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
