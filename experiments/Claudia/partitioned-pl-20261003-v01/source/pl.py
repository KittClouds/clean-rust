"""Ranking likelihoods for the Claudia partitioned-PL experiment. Everything here is exact; nothing sorts tied candidates.

Plackett-Luce (PL): draw candidates without replacement, each draw proportional to w = exp(score) among those left.

* ``ce_nll``              softmax cross-entropy of one named candidate  (= PL probability that it is drawn first).
* ``grouped_pl_nll``      NLL of an ORDERED PARTITION  G_0 > G_1 > ... > G_K : the probability that the first |G_0| PL draws are
                          exactly G_0 (in ANY internal order), then the next |G_1| draws are exactly G_1 (any internal order), ...
                          The internal ordering of every group is marginalised exactly, never fixed. The last non-empty group
                          contributes probability 1 (it is whatever remains).
* ``listmle_random_extension_nll``  conventional ListMLE (NLL of one total order) evaluated on a RANDOM LINEAR EXTENSION of the
                          partition order, redrawn on every call. Used only for the "vanilla PL" reference arm: when only group
                          semantics exist, the single identifiable total order is "selected first", on which ListMLE is exactly CE.

Marginalisation (per non-last group G, rest = all later groups, W_rest = sum of their weights, w(.) = summed weights):
    P(G first, any order) = exp f(G),   f(empty) = 0,
    f(D) = logsumexp_{i in D} [ f(D \\ i) + s_i - log( W_rest + w(G \\ (D \\ i)) ) ]
A subset DP in the log domain: only positive terms are summed, so there is no inclusion-exclusion cancellation. Cost 2^|G| |G|;
on this bank |G| <= 8 (legal-other candidates), so the DP is exact and cheap. ``max_group`` guards the exponential.
"""
import torch

FILL = -1e4          # finite stand-in for log(0): keeps masked entries from creating NaN gradients


def ce_nll(scores, valid, sel):
    """-log softmax_{valid}(scores)[sel]; ``sel`` bool one-hot [B,N]; returns [B]."""
    lse = torch.logsumexp(scores.masked_fill(~valid, FILL), 1)
    return lse - (scores * sel).sum(1)


def grouped_pl_nll(scores, group, max_group=12):
    """scores [B,N]; group [B,N] long: 0 = best group, larger = worse, -1 = excluded (padding / outside the universe)."""
    B, N = scores.shape
    total = scores.new_zeros(B)
    if not bool((group >= 0).any()):
        return total
    for k in range(int(group.max()) + 1):
        rest = group > k
        applies = rest.any(1)                         # a group with nothing after it has probability 1: never enumerated
        in_k = (group == k) & applies[:, None]
        size = in_k.sum(1)
        m = int(size.max())
        if m == 0:
            continue
        if m > max_group:
            raise ValueError(f'group of {m} members exceeds max_group={max_group}')
        applies = applies & (size > 0)
        log_w_rest = torch.logsumexp(scores.masked_fill(~rest, FILL), 1)
        order = torch.argsort((~in_k).to(torch.uint8), dim=1, stable=True)[:, :m]      # members first
        a = scores.gather(1, order)
        present = in_k.gather(1, order)
        a = torch.where(present, a, torch.full_like(a, FILL))
        n_states, full = 1 << m, (1 << m) - 1
        lw = [torch.full((B,), FILL, dtype=scores.dtype, device=scores.device)]      # log w(D)
        for D in range(1, n_states):
            lw.append(torch.logaddexp(lw[D & (D - 1)], a[:, (D & -D).bit_length() - 1]))
        rem = [torch.logaddexp(log_w_rest, lw[full ^ D]) for D in range(n_states)]   # log( W_rest + w(G \ D) )
        f = [torch.zeros(B, dtype=scores.dtype, device=scores.device)]
        for D in range(1, n_states):
            f.append(torch.logsumexp(torch.stack([f[D ^ (1 << i)] + a[:, i] - rem[D ^ (1 << i)]
                                                  for i in range(m) if D >> i & 1]), 0))
        bits = (present.long() << torch.arange(m, device=scores.device)).sum(1)       # which slots are real members
        logp = torch.stack(f)[bits, torch.arange(B, device=scores.device)]
        total = total - torch.where(applies, logp, torch.zeros_like(logp))
    return total


def listmle_random_extension_nll(scores, group, generator, truncate_after=None):
    """ListMLE NLL of a uniformly random linear extension of the group order (fresh draw per call, never a fixed sort).

    ``truncate_after=g`` keeps only the list positions whose group id is <= g (supplementary 'truncated' variant: the tail of
    tied candidates is left as the unordered remainder instead of being randomly ordered)."""
    B, N = scores.shape
    valid = group >= 0
    noise = torch.rand(B, N, generator=generator).to(scores.device)
    key = torch.where(valid, group.to(scores.dtype) + 0.999 * noise.to(scores.dtype), torch.full_like(scores, 1e9))
    order = key.argsort(1)
    s = scores.gather(1, order)
    v = valid.gather(1, order)
    s = torch.where(v, s, torch.full_like(s, FILL))
    tail = torch.flip(torch.logcumsumexp(torch.flip(s, [1]), 1), [1])               # log sum_{u >= t} exp(s_u)
    keep = v if truncate_after is None else v & (group.gather(1, order) <= truncate_after)
    return -((s - tail) * keep).sum(1)
