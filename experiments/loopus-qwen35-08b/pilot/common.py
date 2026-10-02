"""Shared setup for the CPU pilot: byte-level corpus from repo markdown + toy hybrid Qwen3.5.

The pilot rehearses the recipe (frozen-loop failure -> gated deep-supervision post-training ->
LoopCD / early exit) on a model small enough for 4 CPU cores. It does NOT test transfer to
Qwen3.5-0.8B; it de-risks the mechanics and the controls.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from transformers import Qwen3_5ForCausalLM, Qwen3_5TextConfig  # noqa: E402

SEQ = 128
SEP = 255                      # never occurs in UTF-8 text; 0 is the pad id
SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def toy_config(h: int = 256, layers: int = 8) -> Qwen3_5TextConfig:
    return Qwen3_5TextConfig(
        vocab_size=256, hidden_size=h, intermediate_size=3 * h, num_hidden_layers=layers,
        num_attention_heads=4, num_key_value_heads=2, head_dim=h // 4,
        linear_key_head_dim=h // 8, linear_value_head_dim=h // 4,
        linear_num_key_heads=2, linear_num_value_heads=4,
        max_position_embeddings=512, tie_word_embeddings=True, pad_token_id=0)


def corpus_files() -> list[Path]:
    skip = {".git", "vendor", "target", "loopus-qwen35-08b"}
    fs = [p for p in REPO.rglob("*.md") if not (set(p.parts) & skip)]
    return sorted(fs)


def is_heldout(p: Path) -> bool:
    return int(hashlib.sha1(str(p.relative_to(REPO)).encode()).hexdigest(), 16) % 10 == 0


def load_windows(seq: int = SEQ, max_train_bytes: int | None = None):
    """File-level split: held-out documents never appear in training windows."""
    tr, ho = [], []
    for p in corpus_files():
        b = list(p.read_bytes()) + [SEP]
        (ho if is_heldout(p) else tr).append(b)

    def pack(docs, cap=None):
        ids = [t for d in docs for t in d]
        if cap:
            ids = ids[:cap]
        n = len(ids) // seq
        return torch.tensor(ids[: n * seq], dtype=torch.long).view(n, seq)

    return pack(tr, max_train_bytes), pack(ho)


def new_pretrained(path: str | Path | None = None) -> Qwen3_5ForCausalLM:
    m = Qwen3_5ForCausalLM(toy_config())
    if path is not None:
        m.load_state_dict(torch.load(path, map_location="cpu"))
    return m
