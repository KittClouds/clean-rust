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


def split_docs(texts: list[str], val_frac: float = 0.2, seed: int = 0) -> tuple[list[str], list[str]]:
    """Deterministic DOCUMENT-level split (no window of a held-out document is ever trained on)."""
    rng = random.Random(seed)
    order = list(range(len(texts)))
    rng.shuffle(order)
    n_val = max(1, int(round(val_frac * len(texts))))
    val = set(order[:n_val])
    return [t for i, t in enumerate(texts) if i not in val], [texts[i] for i in sorted(val)]


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
