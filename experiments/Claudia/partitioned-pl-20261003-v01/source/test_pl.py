"""Brute-force verification of the grouped / partitioned Plackett-Luce likelihood (the key engineering gate)."""
import itertools
import math

import pytest
import torch

import pl

torch.use_deterministic_algorithms(True)


def brute_nll(scores, group):
    """-log P(ordered partition) by enumerating EVERY total order of the valid candidates and summing the PL probability of
    those consistent with the partition (groups appear in non-decreasing order along the permutation)."""
    idx = [i for i, g in enumerate(group) if g >= 0]
    w = {i: math.exp(float(scores[i])) for i in idx}
    total = 0.0
    for perm in itertools.permutations(idx):
        gs = [group[i] for i in perm]
        if any(gs[t] > gs[t + 1] for t in range(len(gs) - 1)):
            continue
        p, left = 1.0, sum(w.values())
        for i in perm:
            p *= w[i] / left
            left -= w[i]
        total += p
    return -math.log(total)


def rand_case(n, groups, seed):
    g = torch.Generator().manual_seed(seed)
    s = torch.randn(n, generator=g, dtype=torch.float64) * 1.5
    return s, list(groups)


CASES = {
    'single candidate': [0],
    'two partitions': [0, 1, 1, 1],
    'three partitions': [0, 1, 1, 2, 2, 2],
    'empty middle partition': [0, 2, 2, 2, 2],
    'all candidates tied': [0, 0, 0, 0],
    'one candidate per partition': [0, 1, 2, 3],
    'several members each': [0, 0, 1, 1, 1, 2, 2],
    'group sizes 2/3/1': [0, 0, 1, 1, 1, 2],
}


@pytest.mark.parametrize('name', list(CASES))
def test_grouped_pl_matches_brute_force_enumeration(name):
    groups = CASES[name]
    for seed in range(4):
        s, g = rand_case(len(groups), groups, seed)
        got = pl.grouped_pl_nll(s[None], torch.tensor(g)[None])[0]
        assert abs(float(got) - brute_nll(s, g)) < 1e-9, (name, seed)


def test_empty_middle_partition_equals_compacted_groups():
    s, _ = rand_case(5, [0] * 5, 1)
    a = pl.grouped_pl_nll(s[None], torch.tensor([[0, 2, 2, 2, 2]]))
    b = pl.grouped_pl_nll(s[None], torch.tensor([[0, 1, 1, 1, 1]]))
    assert torch.allclose(a, b, atol=1e-12)


def test_all_tied_has_probability_one_and_single_candidate_zero():
    s, _ = rand_case(4, [0] * 4, 0)
    assert abs(float(pl.grouped_pl_nll(s[None], torch.zeros(1, 4, dtype=torch.long))[0])) < 1e-9
    assert abs(float(pl.grouped_pl_nll(s[None, :1], torch.zeros(1, 1, dtype=torch.long))[0])) < 1e-12


def test_selected_first_then_rest_is_exactly_cross_entropy():
    """The only identifiable total order from group semantics is 'selected first'; on it ListMLE == softmax CE == grouped PL."""
    for seed in range(5):
        s, _ = rand_case(7, [0] * 7, seed)
        g = torch.tensor([[0, 1, 1, 1, 1, 1, 1]])
        sel = torch.zeros(1, 7, dtype=torch.bool); sel[0, 0] = True
        ce = pl.ce_nll(s[None], torch.ones(1, 7, dtype=torch.bool), sel)
        assert torch.allclose(pl.grouped_pl_nll(s[None], g), ce, atol=1e-12)
        brute = -float(s[0] - torch.logsumexp(s, 0))
        assert abs(float(ce[0]) - brute) < 1e-12


def test_one_candidate_per_partition_equals_listmle():
    s, _ = rand_case(5, [0] * 5, 3)
    got = pl.grouped_pl_nll(s[None], torch.arange(5)[None])
    ref = -sum(float(s[i] - torch.logsumexp(s[i:], 0)) for i in range(5))
    assert abs(float(got[0]) - ref) < 1e-10


def test_permutation_and_padding_invariance():
    s, g = rand_case(6, CASES['three partitions'], 2)
    base = pl.grouped_pl_nll(s[None], torch.tensor(g)[None])
    perm = torch.randperm(6, generator=torch.Generator().manual_seed(0))
    assert torch.allclose(pl.grouped_pl_nll(s[perm][None], torch.tensor(g)[perm][None]), base, atol=1e-12)
    # padding: extra excluded slots with garbage scores (group -1) change nothing
    sp = torch.cat([s, torch.tensor([50.0, -50.0, 7.0], dtype=torch.float64)])
    gp = torch.tensor(g + [-1, -1, -1])
    assert torch.allclose(pl.grouped_pl_nll(sp[None], gp[None]), base, atol=1e-12)
    # batch of different widths (padding differs per row) equals each row alone
    s2, g2 = rand_case(4, CASES['two partitions'], 5)
    pad = 6 - 4
    batch_s = torch.stack([s, torch.cat([s2, torch.zeros(pad, dtype=torch.float64)])])
    batch_g = torch.stack([torch.tensor(g), torch.tensor(g2 + [-1] * pad)])
    out = pl.grouped_pl_nll(batch_s, batch_g)
    assert abs(float(out[0] - base[0])) < 1e-12
    assert abs(float(out[1]) - brute_nll(s2, g2)) < 1e-9


def test_batched_rows_with_different_partition_shapes_match_brute_force():
    rows = [[0, 1, 1, 2, 2], [0, 2, 2, 2, 2], [0, 0, 0, 0, 0], [0, 1, 2, 3, 3], [0, 1, 1, 1, 1]]
    g = torch.Generator().manual_seed(9)
    s = torch.randn(len(rows), 5, generator=g, dtype=torch.float64)
    out = pl.grouped_pl_nll(s, torch.tensor(rows))
    for i, r in enumerate(rows):
        assert abs(float(out[i]) - brute_nll(s[i], r)) < 1e-9


def test_gradient_is_finite_nonzero_and_matches_brute_force_autograd():
    groups = CASES['several members each']
    s, g = rand_case(len(groups), groups, 4)
    s = s.clone().requires_grad_(True)
    loss = pl.grouped_pl_nll(s[None], torch.tensor(g)[None])[0]
    loss.backward()
    assert torch.isfinite(s.grad).all() and s.grad.abs().sum() > 1e-6
    s2 = s.detach().clone().requires_grad_(True)
    idx = list(range(len(groups)))
    w = torch.exp(s2)
    total = 0
    for perm in itertools.permutations(idx):
        gs = [groups[i] for i in perm]
        if any(gs[t] > gs[t + 1] for t in range(len(gs) - 1)):
            continue
        p, left = 1.0, w.sum()
        for i in perm:
            p = p * w[i] / left
            left = left - w[i]
        total = total + p
    (-torch.log(total)).backward()
    assert torch.allclose(s.grad, s2.grad, atol=1e-9)


def test_float32_training_precision_and_no_nan_with_extreme_scores():
    g = torch.Generator().manual_seed(1)
    s = (torch.randn(8, 12, generator=g) * 30).requires_grad_(True)           # large dynamic range
    grp = torch.tensor([[0] + [1] * 3 + [2] * 8] * 8)
    loss = pl.grouped_pl_nll(s, grp).sum()
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(s.grad).all()
    ref = pl.grouped_pl_nll(s.detach().double(), grp)
    assert torch.allclose(pl.grouped_pl_nll(s.detach(), grp).double(), ref, rtol=1e-4, atol=1e-3)


def test_listmle_random_extension_is_a_valid_total_order_nll_and_never_a_fixed_sort():
    s, g = rand_case(6, CASES['three partitions'], 6)
    gen = torch.Generator().manual_seed(0)
    draws = [float(pl.listmle_random_extension_nll(s[None], torch.tensor(g)[None], gen)[0]) for _ in range(300)]
    assert len(set(round(d, 6) for d in draws)) > 5                              # ties are re-ordered every call
    # each draw is the exact NLL of some consistent total order, so it is >= the marginal NLL (Jensen / union bound)
    assert min(draws) >= brute_nll(s, g) - 1e-9
    # E[-log P(order)] >= -log E[P(order)] = marginal when orders are drawn uniformly: check the Jensen gap is strictly positive
    assert sum(draws) / len(draws) > brute_nll(s, g) + 1e-3
    # a fully ordered list (one per partition) has a single extension: ListMLE == grouped PL
    s2, _ = rand_case(4, [0] * 4, 8)
    a = pl.listmle_random_extension_nll(s2[None], torch.arange(4)[None], gen)
    assert abs(float(a[0]) - float(pl.grouped_pl_nll(s2[None], torch.arange(4)[None])[0])) < 1e-12


def test_listmle_padding_is_inert():
    s, g = rand_case(5, [0, 1, 1, 2, 2], 7)
    sp = torch.cat([s, torch.tensor([9.0, -9.0], dtype=torch.float64)])
    gp = torch.tensor(g + [-1, -1])
    a = pl.listmle_random_extension_nll(s[None], torch.tensor(g)[None], torch.Generator().manual_seed(3))
    b = pl.listmle_random_extension_nll(sp[None], gp[None], torch.Generator().manual_seed(3))
    assert abs(float(a) - float(b)) < 1e-9


def test_oversized_group_is_refused_rather_than_approximated():
    with pytest.raises(ValueError):
        pl.grouped_pl_nll(torch.zeros(1, 14), torch.tensor([[0] * 13 + [1]]), max_group=12)


def test_last_group_is_never_enumerated_even_when_huge():
    """Regression: the final group (here 122 illegal candidates) has probability 1 and must not trigger the subset DP."""
    g = torch.Generator().manual_seed(0)
    s = torch.randn(2, 130, generator=g, dtype=torch.float64)
    group = torch.tensor([[0] + [1] * 3 + [2] * 126, [0] + [1] * 5 + [2] * 124])
    out = pl.grouped_pl_nll(s, group)                      # would raise for the 126-member last group before the fix
    # reference: P1 softmax, then exact DP on P2 against the illegal rest, computed independently by brute force on a reduced case
    s_small = torch.randn(7, generator=g, dtype=torch.float64)
    big = pl.grouped_pl_nll(torch.cat([s_small, torch.zeros(0, dtype=torch.float64)])[None], torch.tensor([[0, 1, 1, 2, 2, 2, 2]]))
    assert abs(float(big[0]) - brute_nll(s_small, [0, 1, 1, 2, 2, 2, 2])) < 1e-9 and torch.isfinite(out).all()


def test_truncated_listmle_keeps_only_the_legal_prefix_and_bounds_the_marginal():
    s, g = rand_case(7, [0, 1, 1, 2, 2, 2, 2], 11)
    gen = torch.Generator().manual_seed(2)
    trunc = [float(pl.listmle_random_extension_nll(s[None], torch.tensor(g)[None], gen, truncate_after=1)[0]) for _ in range(200)]
    full = [float(pl.listmle_random_extension_nll(s[None], torch.tensor(g)[None], torch.Generator().manual_seed(2))[0]) for _ in range(1)]
    marginal = brute_nll(s, g)
    assert min(trunc) >= marginal - 1e-9                   # one ordered prefix is one term of the marginal sum
    assert len(set(round(t, 6) for t in trunc)) == 2       # only the order of the two legal-other candidates varies
    assert full[0] > min(trunc)                            # the full list also pays for ordering the tied tail
