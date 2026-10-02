"""Serial k-hop pointer following: a task where one forward pass cannot suffice for large k.

Why this exists. On generic next-token loss the one-pass state is already good, and pilot 1/2 showed
the deep-supervision objective is then satisfied by the lazy solution "iterations >= 2 do nothing"
(the block becomes idempotent). To test whether a looped Qwen3.5 can *use* depth, the task has to
need serial computation. Here every node has one outgoing edge; the answer is the node reached after
k steps, so k is the number of dependent lookups.

    "H>C Q>H C>K ...\nStart Q, 3 steps ->"   ->   " K"

Training uses k in 1..K_TRAIN; evaluation also covers larger k (depth extrapolation).
Loss is on the single answer token only (labels are -100 elsewhere).
"""
from __future__ import annotations

import random
import string

import torch

LETTERS = list(string.ascii_uppercase)


def make_example(rng: random.Random, k: int, n_nodes: int = 10, perm: bool = True) -> tuple[str, str, int]:
    """Returns (prompt, answer, k). The graph is a random PERMUTATION of ``n_nodes`` letters.

    A permutation (``perm=True``) has no merging paths, so the k-step answer is uniform over the
    nodes (chance = 1/n_nodes) and cannot be guessed from where long walks end up. A random
    function (``perm=False``) falls into short cycles, which let a one-pass model score ~50% on
    large k without composing anything -- measured, and the reason permutations are the default.
    """
    nodes = rng.sample(LETTERS, n_nodes)
    if perm:
        tgt = nodes[:]
        rng.shuffle(tgt)
        nxt = dict(zip(nodes, tgt))
    else:
        nxt = {a: rng.choice(nodes) for a in nodes}
    edges = [f"{a}>{nxt[a]}" for a in nodes]
    rng.shuffle(edges)
    start = rng.choice(nodes)
    cur = start
    for _ in range(k):
        cur = nxt[cur]
    return " ".join(edges) + f"\nStart {start}, {k} steps ->", " " + cur, k


def encode_example(tok, prompt: str, answer: str) -> list[int]:
    """Prompt ids + exactly one answer id. The answer must be a single token."""
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    a = tok(answer, add_special_tokens=False)["input_ids"]
    if len(a) != 1:
        raise ValueError(f"answer {answer!r} is {len(a)} tokens, expected 1")
    return p + a


def build_set(tok, n: int, ks, seed: int, n_nodes: int = 10) -> list[tuple[list[int], int]]:
    """``n`` examples with k drawn uniformly from ``ks``. Returns [(ids, k)]."""
    rng = random.Random(seed)
    ks = list(ks)
    out = []
    for _ in range(n):
        k = rng.choice(ks)
        prompt, ans, _ = make_example(rng, k, n_nodes)
        out.append((encode_example(tok, prompt, ans), k))
    return out


def collate(batch, pad_id: int, device="cpu"):
    """Right-pad. labels = -100 except the answer token (last real token of each row).

    Returns x, attention_mask, labels, ks.
    """
    T = max(len(ids) for ids, _ in batch)
    B = len(batch)
    x = torch.full((B, T), pad_id, dtype=torch.long)
    m = torch.zeros((B, T), dtype=torch.long)
    y = torch.full((B, T), -100, dtype=torch.long)
    for i, (ids, _) in enumerate(batch):
        n = len(ids)
        x[i, :n] = torch.tensor(ids)
        m[i, :n] = 1
        y[i, n - 1] = ids[-1]
    ks = torch.tensor([k for _, k in batch])
    return x.to(device), m.to(device), y.to(device), ks


def train_batches(tok, ks, batch_size: int, seed: int, device="cpu", n_nodes: int = 10):
    """Endless stream of fresh random examples (no repetition, so no memorisation)."""
    rng = random.Random(seed)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    ks = list(ks)
    while True:
        batch = []
        for _ in range(batch_size):
            prompt, ans, k = make_example(rng, rng.choice(ks), n_nodes)
            batch.append((encode_example(tok, prompt, ans), k))
        x, m, y, _ = collate(batch, pad, device)
        yield x, m, y


@torch.no_grad()
def evaluate_hops(model, tok, examples, depths, batch_size: int = 64, device="cuda"):
    """Per-(depth, k) answer accuracy and NLL. One recursion trajectory serves all depths.

    Returns {depth: {k: {"acc", "nll", "n"}, "all": {...}}}.
    """
    model.eval()
    w = model.lm_head.weight
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    depths = sorted(set(depths))
    acc = {d: {} for d in depths}
    for i in range(0, len(examples), batch_size):
        chunk = examples[i:i + batch_size]
        x, m, y, ks = collate(chunk, pad, device)
        lens = m.sum(1)                                   # answer sits at index len-1; predicted from len-2
        ctx = model.prepare(x, m)
        h = model.encode(ctx)
        for t in range(1, depths[-1] + 1):
            h = model.step(h, ctx, first=(t == 1))
            if t not in depths:
                continue
            normed = model.decode(h, ctx)
            rows = torch.arange(x.shape[0], device=x.device)
            z = (normed[rows, lens - 2] @ w.t()).float()   # (B, V)
            tgt = x[rows, lens - 1]
            lp = torch.log_softmax(z, -1)
            nll = -lp.gather(-1, tgt[:, None]).squeeze(-1)
            correct = z.argmax(-1) == tgt
            for j in range(x.shape[0]):
                a = acc[t].setdefault(int(ks[j]), [0.0, 0.0, 0])
                a[0] += float(correct[j]); a[1] += float(nll[j]); a[2] += 1
    out = {}
    for d in depths:
        per = {k: {"acc": v[0] / v[2], "nll": v[1] / v[2], "n": v[2]} for k, v in sorted(acc[d].items())}
        n = sum(v["n"] for v in per.values())
        per["all"] = {"acc": sum(v["acc"] * v["n"] for v in per.values() if v is not per.get("all")) / n,
                      "nll": sum(v["nll"] * v["n"] for v in per.values() if v is not per.get("all")) / n, "n": n}
        out[d] = per
    return out
