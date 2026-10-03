"""SetRank (full candidate self-attention) and its matched pointwise control.

Both: input projection 365 -> 128; two pre-LayerNorm residual blocks; final LayerNorm; a utility head and a
legality head (128 -> 1 each). No positional or candidate-index encoding anywhere.

  set      block = x + MHSA(LN(x), 4 heads x 32, padding-masked, no causal mask), then x + FFN_256(LN(x))
  pointwise block = x + FFN_a(LN(x)),                                         then x + FFN_256(LN(x))

The pointwise block replaces the attention sub-layer by a candidate-independent FFN whose width ``a`` makes the
trainable parameter count match (a = 256: within 0.1 %). Attention is written out with matmul + softmax (N <= 171,
so dense N^2 is cheap) which keeps every op deterministic and exposes the attention maps for diagnostics.
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from data import TOKEN_DIM

NEG = -1e9


class FFN(nn.Module):
    def __init__(self, d, width):
        super().__init__()
        self.up = nn.Linear(d, width)
        self.down = nn.Linear(width, d)

    def forward(self, x):
        return self.down(F.gelu(self.up(x)))


class SetAttention(nn.Module):
    def __init__(self, d, heads):
        super().__init__()
        assert d % heads == 0
        self.h, self.hd = heads, d // heads
        self.qkv = nn.Linear(d, 3 * d)
        self.proj = nn.Linear(d, d)

    def forward(self, x, key_mask, want_attn=False):
        b, n, d = x.shape
        q, k, v = self.qkv(x).view(b, n, 3, self.h, self.hd).permute(2, 0, 3, 1, 4)
        att = (q @ k.transpose(-1, -2)) / math.sqrt(self.hd)
        att = att.masked_fill(~key_mask[:, None, None, :], NEG)      # padding keys receive no attention
        w = att.softmax(-1)
        out = (w @ v).transpose(1, 2).reshape(b, n, d)
        return self.proj(out), (w if want_attn else None)


class Block(nn.Module):
    def __init__(self, kind, d, heads, ff, pointwise_width):
        super().__init__()
        self.kind = kind
        self.ln1 = nn.LayerNorm(d)
        self.mix = SetAttention(d, heads) if kind == 'set' else FFN(d, pointwise_width)
        self.ln2 = nn.LayerNorm(d)
        self.ff = FFN(d, ff)

    def forward(self, x, key_mask, want_attn=False):
        if self.kind == 'set':
            y, w = self.mix(self.ln1(x), key_mask, want_attn)
        else:
            y, w = self.mix(self.ln1(x)), None
        x = x + y
        return x + self.ff(self.ln2(x)), w


class CandidateNet(nn.Module):
    def __init__(self, kind, d_in=TOKEN_DIM, d=128, heads=4, ff=256, layers=2, pointwise_width=256):
        super().__init__()
        assert kind in ('set', 'pointwise')
        self.kind = kind
        self.inp = nn.Linear(d_in, d)
        self.blocks = nn.ModuleList([Block(kind, d, heads, ff, pointwise_width) for _ in range(layers)])
        self.norm = nn.LayerNorm(d)
        self.util = nn.Linear(d, 1)
        self.leg = nn.Linear(d, 1)

    def forward(self, x, key_mask, internals=False):
        h = self.inp(x)
        hs, atts = [h], []
        for blk in self.blocks:
            h, w = blk(h, key_mask, internals)
            hs.append(h)
            atts.append(w)
        z = self.norm(h)
        util, leg = self.util(z).squeeze(-1), self.leg(z).squeeze(-1)
        if internals:
            return util, leg, {'hidden': hs, 'attn': atts}
        return util, leg


def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def build(kind, seed=0):
    torch.manual_seed(seed)
    return CandidateNet(kind)
