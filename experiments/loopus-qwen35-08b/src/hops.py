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


def train_batches(tok, ks, batch_size: int, seed: int, device="cpu", n_nodes: int = 10, with_ks: bool = False):
    """Endless stream of fresh random examples (no repetition, so no memorisation).
    ``with_ks=True`` yields ``(x, mask, labels, ks)`` for depth-matched supervision."""
    rng = random.Random(seed)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    ks = list(ks)
    while True:
        batch = []
        for _ in range(batch_size):
            prompt, ans, k = make_example(rng, rng.choice(ks), n_nodes)
            batch.append((encode_example(tok, prompt, ans), k))
        x, m, y, kk = collate(batch, pad, device)
        yield (x, m, y, kk) if with_ks else (x, m, y)


def depth_matched(c: int):
    """label_fn for ``train``: at recursion depth t, supervise only examples with k <= c * t."""
    def fn(t, labels, ks):
        keep = (ks <= c * t).to(labels.device)
        return torch.where(keep[:, None], labels, torch.full_like(labels, -100))
    return fn


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
        per["all"] = {"acc": sum(v["acc"] * v["n"] for v in per.values()) / n,
                      "nll": sum(v["nll"] * v["n"] for v in per.values()) / n, "n": n}
        out[d] = per
    return out


@torch.no_grad()
def evaluate_hops_loopcd(model, tok, examples, R: int, omegas=(0.25, 0.5, 1.0), w_max: float = 1.0,
                         batch_size: int = 64, device="cuda"):
    """LoopCD on the hop task at recursion depth ``R`` (reference = h_1, the first recurrent state).

    Variants, all scored by answer accuracy / NLL per k:
      base                      z_R                                   (no contrast)
      logits_w{w}               z' = z_R + w (z_R - z_1)
      hidden_w{w}               h' = h_R + w (h_R - h_1) -> decoder + norm -> LM head
      logits_adaptive / hidden_adaptive    w = w_max * (1 - (p1 - p2)), p from softmax(z_R)
    Returns {variant: {k: {"acc","nll","n"}, "all": {...}}}.
    """
    from .loopcd import adaptive_strength, contrast_hidden

    model.eval()
    w = model.lm_head.weight
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    acc: dict[str, dict[int, list]] = {}

    def add(name, z, tgt, ks):
        lp = torch.log_softmax(z.float(), -1)
        nll = -lp.gather(-1, tgt[:, None]).squeeze(-1)
        cor = z.argmax(-1) == tgt
        for j in range(z.shape[0]):
            a = acc.setdefault(name, {}).setdefault(int(ks[j]), [0.0, 0.0, 0])
            a[0] += float(cor[j]); a[1] += float(nll[j]); a[2] += 1

    for i in range(0, len(examples), batch_size):
        x, m, y, ks = collate(examples[i:i + batch_size], pad, device)
        rows = torch.arange(x.shape[0], device=x.device)
        lens = m.sum(1)
        tgt = x[rows, lens - 1]
        ctx = model.prepare(x, m)
        h = model.encode(ctx)
        st = {}
        for t in range(1, R + 1):
            h = model.step(h, ctx, first=(t == 1))
            if t in (1, R):
                st[t] = h
        n1, nR = model.decode(st[1], ctx), model.decode(st[R], ctx)
        z1 = (n1[rows, lens - 2] @ w.t()).float()
        zR = (nR[rows, lens - 2] @ w.t()).float()
        add("base", zR, tgt, ks)
        for om in omegas:
            add(f"logits_w{om}", zR + om * (zR - z1), tgt, ks)
            hp = model.decode(contrast_hidden(st[1], st[R], om), ctx)
            add(f"hidden_w{om}", (hp[rows, lens - 2] @ w.t()).float(), tgt, ks)
        wa = adaptive_strength(zR, w_max)                        # (B, 1)
        add("logits_adaptive", zR + wa * (zR - z1), tgt, ks)
        # per-example strength must broadcast over (B, T, D): w is (B, 1) -> (B, 1, 1)
        hp = model.decode(contrast_hidden(st[1], st[R], wa[:, :, None]), ctx)
        add("hidden_adaptive", (hp[rows, lens - 2] @ w.t()).float(), tgt, ks)

    out = {}
    for name, per in acc.items():
        d = {k: {"acc": v[0] / v[2], "nll": v[1] / v[2], "n": v[2]} for k, v in sorted(per.items())}
        n = sum(v["n"] for v in d.values())
        d["all"] = {"acc": sum(v["acc"] * v["n"] for v in d.values()) / n,
                    "nll": sum(v["nll"] * v["n"] for v in d.values()) / n, "n": n}
        out[name] = d
    return out
