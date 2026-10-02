"""Corpus loading and fixed-window batching.

Sources (all local; nothing here needs the network):
  * ``.jsonl`` with an ``input_text`` (or ``text``) field, e.g. BANK-v1 TRAIN.jsonl
  * ``.txt`` / ``.md`` files, or a directory of them
Tokenisation is injected, so the same code serves the real Qwen tokenizer and the
byte-level tokenizer used by the CPU pilot.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Callable, Iterator

import torch

TEXT_KEYS = ("input_text", "text", "content")


def read_texts(path: str | Path, limit: int | None = None, exts=(".txt", ".md")) -> list[str]:
    p = Path(path)
    out: list[str] = []
    if p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.suffix.lower() in exts and f.is_file())
        for f in files:
            out.append(f.read_text(encoding="utf-8", errors="replace"))
    elif p.suffix.lower() == ".jsonl":
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                txt = next((rec[k] for k in TEXT_KEYS if isinstance(rec.get(k), str)), None)
                if txt:
                    out.append(txt)
                if limit and len(out) >= limit:
                    break
    else:
        out.append(p.read_text(encoding="utf-8", errors="replace"))
    return out[:limit] if limit else out


def byte_tokenize(text: str) -> list[int]:
    return list(text.encode("utf-8", errors="replace"))


def pack(texts: list[str], tokenize: Callable[[str], list[int]], seq_len: int,
         sep: int | None = None) -> torch.Tensor:
    """Concatenate (optionally ``sep``-joined) and cut into non-overlapping ``(n, seq_len)`` windows."""
    ids: list[int] = []
    for t in texts:
        ids.extend(tokenize(t))
        if sep is not None:
            ids.append(sep)
    n = len(ids) // seq_len
    return torch.tensor(ids[: n * seq_len], dtype=torch.long).view(n, seq_len)


def load_windows(path: str | Path, tok, seq_len: int, max_docs: int | None = None, cache_dir=None,
                 shuffle_docs_seed: int | None = None) -> torch.Tensor:
    """Tokenise a corpus into packed ``(n, seq_len)`` windows, with a cache keyed on every input.

    Documents are joined with the tokenizer's EOS id so a window can cross an article boundary
    only through an explicit separator. ``shuffle_docs_seed`` shuffles documents before taking
    ``max_docs`` so a truncated corpus is not just the head of the file.
    """
    p = Path(path)
    cache = None
    if cache_dir is not None:
        cache = Path(cache_dir) / f"{p.stem}.L{seq_len}.d{max_docs}.s{shuffle_docs_seed}.{p.stat().st_size}.pt"
        if cache.exists():
            return torch.load(cache)
    texts = read_texts(p)
    if shuffle_docs_seed is not None:
        random.Random(shuffle_docs_seed).shuffle(texts)
    if max_docs:
        texts = texts[:max_docs]
    ids: list[int] = []
    sep = tok.eos_token_id
    enc = tok(texts, add_special_tokens=False)["input_ids"]
    for e in enc:
        ids.extend(e)
        ids.append(sep)
    n = len(ids) // seq_len
    w = torch.tensor(ids[: n * seq_len], dtype=torch.long).view(n, seq_len)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        torch.save(w, cache)
    return w


def split_windows(windows: torch.Tensor, val_frac: float = 0.1, seed: int = 0):
    """Deterministic window-level train/held-out split."""
    g = torch.Generator().manual_seed(seed)
    perm = torch.randperm(windows.shape[0], generator=g)
    n_val = max(1, int(round(val_frac * windows.shape[0])))
    return windows[perm[n_val:]], windows[perm[:n_val]]


def batches(windows: torch.Tensor, batch_size: int, seed: int = 0, epochs: int | None = 1,
            device: str | torch.device = "cpu") -> Iterator[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]:
    """Yield ``(input_ids, attention_mask, labels)``; windows are full so the mask is all ones."""
    rng = random.Random(seed)
    ep = 0
    while epochs is None or ep < epochs:
        order = list(range(windows.shape[0]))
        rng.shuffle(order)
        for i in range(0, len(order) - batch_size + 1, batch_size):
            x = windows[order[i:i + batch_size]].to(device)
            yield x, torch.ones_like(x), x.clone()
        ep += 1
