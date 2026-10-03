import math

import numpy as np
import pytest
import torch

import losses
import metrics
from data import TOKEN_DIM, make_perm
from model import CandidateNet, build, count_params

torch.use_deterministic_algorithms(True)


def _batch(b=3, nmax=11, seed=0):
    g = torch.Generator().manual_seed(seed)
    n = torch.tensor([11, 7, 4][:b])
    x = torch.randn(b, nmax, TOKEN_DIM, generator=g)
    mask = torch.arange(nmax)[None, :] < n[:, None]
    return x * mask[..., None], mask, n


@pytest.mark.parametrize('kind', ['set', 'pointwise'])
def test_permutation_equivariance_and_padding_invariance(kind):
    m = build(kind).double().eval()
    x, mask, n = _batch()
    x = x.double()
    with torch.no_grad():
        u, l = m(x, mask)
        for seed in range(5):
            P = make_perm(n, x.shape[1], torch.Generator().manual_seed(seed))
            xp = x[torch.arange(len(n))[:, None], P]
            up, lp = m(xp, mask)                                   # permuted valid slots stay a prefix
            inv = P.argsort(1)
            assert torch.allclose(up.gather(1, inv)[mask], u[mask], atol=1e-10)
            assert torch.allclose(lp.gather(1, inv)[mask], l[mask], atol=1e-10)
        # padding invariance: a root alone (tight) equals the same root inside a wider padded batch,
        # and garbage in padded slots changes nothing
        for b in range(len(n)):
            nb = int(n[b])
            ub, lb = m(x[b:b + 1, :nb], mask[b:b + 1, :nb])
            assert torch.allclose(ub[0], u[b, :nb], atol=1e-10) and torch.allclose(lb[0], l[b, :nb], atol=1e-10)
        junk = x.clone(); junk[~mask] = 123.0
        uj, lj = m(junk, mask)
        assert torch.allclose(uj[mask], u[mask], atol=1e-10)


def test_set_model_candidates_actually_interact_and_pointwise_do_not():
    x, mask, n = _batch()
    for kind, interacts in (('set', True), ('pointwise', False)):
        m = build(kind).eval()
        with torch.no_grad():
            u, _ = m(x, mask)
            x2 = x.clone(); x2[0, 5] += 3.0                          # change ONE candidate
            u2, _ = m(x2, mask)
        others = torch.ones(x.shape[1], dtype=torch.bool); others[5] = False
        moved = (u2[0][others & mask[0]] - u[0][others & mask[0]]).abs().max().item()
        assert (moved > 1e-6) == interacts, (kind, moved)


def test_order_detector_catches_a_positional_model():
    """Negative control: the equivariance test must FAIL for a model that sees candidate position."""
    class Positional(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.base = build('set').double(); self.pos = torch.nn.Parameter(torch.randn(32, TOKEN_DIM).double())
        def forward(self, x, mask):
            return self.base(x + self.pos[: x.shape[1]][None], mask)
    m = Positional().eval()
    x, mask, n = _batch(); x = x.double()
    P = make_perm(n, x.shape[1], torch.Generator().manual_seed(1))
    with torch.no_grad():
        u, _ = m(x, mask); up, _ = m(x[torch.arange(len(n))[:, None], P], mask)
    assert not torch.allclose(up.gather(1, P.argsort(1))[mask], u[mask], atol=1e-6)


def test_parameter_counts_are_matched_within_half_a_percent():
    a, b = count_params(build('set')), count_params(build('pointwise'))
    assert abs(a - b) / a < 0.005, (a, b)


def test_make_perm_permutes_valid_prefix_only():
    n = torch.tensor([5, 3, 7]); P = make_perm(n, 9, torch.Generator().manual_seed(0))
    for i, k in enumerate(n.tolist()):
        assert sorted(P[i, :k].tolist()) == list(range(k)) and P[i, k:].tolist() == list(range(k, 9))


def _lab(mask, typ, sel_idx, elig, legal):
    B, N = mask.shape
    sel = torch.zeros(B, N, dtype=torch.bool)
    for b, j in enumerate(sel_idx):
        if elig[b]: sel[b, j] = True
    return {'mask': mask, 'type': typ, 'sel': sel, 'eligible': torch.tensor(elig), 'legal': legal}


def test_losses_match_brute_force():
    g = torch.Generator().manual_seed(0)
    B, N = 3, 6
    mask = torch.tensor([[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 0], [1, 1, 1, 0, 0, 0]], dtype=torch.bool)
    typ = torch.tensor([[0, 0, 1, 1, 1, 2], [0, 1, 1, 0, 0, 0], [2, 2, 2, 0, 0, 0]])
    legal = torch.tensor([[1, 0, 0, 1, 0, 0], [0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 0, 0]], dtype=torch.bool)
    util, leg = torch.randn(B, N, generator=g), torch.randn(B, N, generator=g)
    lab = _lab(mask, typ, [3, 2, 0], [True, True, False], legal)
    total, parts = losses.candidate_losses(util, leg, lab)
    # brute force
    ce1 = -math.log(math.exp(util[0, 3]) / sum(math.exp(util[0, j]) for j in range(6)))
    ce2 = -math.log(math.exp(util[1, 2]) / sum(math.exp(util[1, j]) for j in range(4)))
    sel = (ce1 + ce2) / 2
    s1 = [2, 3, 4]; s2 = [1, 2]                                      # same-type sets (type 1 in both roots)
    ce1s = -math.log(math.exp(util[0, 3]) / sum(math.exp(util[0, j]) for j in s1))
    ce2s = -math.log(math.exp(util[1, 2]) / sum(math.exp(util[1, j]) for j in s2))
    same = (ce1s + ce2s) / 2

    def bce(z, y): return -(y * math.log(1 / (1 + math.exp(-z))) + (1 - y) * math.log(1 - 1 / (1 + math.exp(-z))))
    roots = []
    for b in range(3):
        idx = [j for j in range(N) if mask[b, j]]
        pos = [j for j in idx if legal[b, j]]; neg = [j for j in idx if not legal[b, j]]
        wp = (0.5 if neg else 1.0) / max(len(pos), 1); wn = (0.5 if pos else 1.0) / max(len(neg), 1)
        roots.append(sum(wp * bce(float(leg[b, j]), 1) for j in pos) + sum(wn * bce(float(leg[b, j]), 0) for j in neg))
    leg_l = sum(roots) / 3
    assert abs(float(parts['select']) - sel) < 1e-5 and abs(float(parts['same_type']) - same) < 1e-5
    assert abs(float(parts['legality']) - leg_l) < 1e-5
    assert abs(float(total) - (sel + 0.5 * same + 0.25 * leg_l)) < 1e-5
    assert parts['eligible_roots'] == 2 and parts['same_type_roots'] == 2


def test_loss_ignores_padding_and_ineligible_roots_and_handles_no_eligible():
    mask = torch.tensor([[1, 1, 1, 0], [1, 1, 0, 0]], dtype=torch.bool)
    typ = torch.zeros(2, 4, dtype=torch.long); legal = torch.zeros(2, 4, dtype=torch.bool)
    util = torch.randn(2, 4, requires_grad=True); leg = torch.randn(2, 4, requires_grad=True)
    lab = _lab(mask, typ, [0, 0], [False, False], legal)
    total, parts = losses.candidate_losses(util, leg, lab)
    total.backward()
    assert float(parts['select']) == 0.0 and float(parts['same_type']) == 0.0 and torch.isfinite(total)
    assert util.grad[~mask].abs().sum() == 0 and leg.grad[~mask].abs().sum() == 0
    assert util.grad.abs().sum() == 0                                  # no eligible root -> utility untouched


def _D():
    mask = torch.tensor([[1, 1, 1, 1, 0], [1, 1, 1, 0, 0], [1, 1, 1, 1, 1]], dtype=torch.bool)
    types = torch.tensor([[0, 0, 1, 0, 0], [1, 1, 0, 0, 0], [2, 2, 2, 2, 2]])
    selected = torch.tensor([1, 0, -1]); elig = selected >= 0
    sp = torch.zeros(3, 5, dtype=torch.bool); sp[0, 1] = True; sp[1, 0] = True
    first = torch.tensor([0, 1, -1])
    legal = torch.tensor([[0, 1, 0, 1, 0], [1, 0, 0, 0, 0], [0, 0, 0, 0, 0]], dtype=torch.bool)
    t = {'mask': mask, 'selected': selected, 'selected_positive': sp, 'selected_eligible': elig, 'optimal': sp.clone(),
         'optimal_eligible': elig.clone(), 'types': types, 'first_action_type': first}
    return {'targets': t, 'legal': legal}


def test_ranking_pairs_and_legality_metrics_on_a_hand_computed_case():
    D = _D()
    util = torch.tensor([[0.9, 0.5, 2.0, 0.1, 0], [3.0, 1.0, 2.0, 0, 0], [0, 0, 0, 0, 0.]])
    res, raw = metrics.rank_all(util, D)
    # root0: selected idx1 (score .5): order 2(2.0) 0(.9) 1(.5) 3 -> rank 3 unrestricted; type 0 set {0,1,3}: .9,.5,.1 -> rank 2
    # root1: selected idx0 (3.0) -> rank 1; type 1 set {0,1}: rank 1
    assert raw['unrestricted']['selected_rank'][:2].tolist() == [3, 1]
    assert raw['gold_type']['selected_rank'][:2].tolist() == [2, 1]
    assert res['unrestricted']['all']['selected']['top1'] == 0.5 and abs(res['unrestricted']['all']['selected']['MRR'] - (1 / 3 + 1) / 2) < 1e-6
    assert res['gold_type']['all']['selected']['top1'] == 0.5 and res['unrestricted']['all']['selected']['eligible_roots'] == 2
    pairs, per = metrics.same_type_pairs(util, D)
    # root0 same-type alternatives of idx1: {0 (.9>.5 -> loss), 3 (.5>.1 -> win)}; root1: {1 (3>1 win)}
    assert pairs['pairs'] == 3 and abs(pairs['pooled_accuracy'] - 2 / 3) < 1e-6 and pairs['roots_with_pairs'] == 2
    assert abs(pairs['root_mean_accuracy'] - (0.5 + 1.0) / 2) < 1e-6
    leg = torch.tensor([[-1, 1, 1, -1, 0], [1, -1, -1, 0, 0], [-1, -1, -1, -1, -1.]])
    out_all, exact = metrics.legality(leg, D, 'all')
    # root0 pred {1,2} gold {1,3}; root1 pred {0} gold {0}; root2 pred {} gold {}
    assert exact.tolist() == [0.0, 1.0, 1.0] and abs(out_all['exact_legal_set_recovery'] - 2 / 3) < 1e-6
    assert out_all['false_positives_per_root'] == pytest.approx(1 / 3) and out_all['false_negatives_per_root'] == pytest.approx(1 / 3)
    assert out_all['root_mean_jaccard'] == pytest.approx((1 / 3 + 1 + 1) / 3)
    out_el, _ = metrics.legality(leg, D, 'eligible')
    assert out_el['selected_candidate_retention'] == 1.0 and out_el['population_roots'] == 2


def test_bootstrap_is_paired_and_reproducible():
    a = np.array([1, 1, 1, 0, 1, 1, 0, 1.]); b = np.array([0, 1, 0, 0, 1, 0, 0, 1.])
    r1 = metrics.paired_bootstrap(a, b, reps=500, seed=1); r2 = metrics.paired_bootstrap(a, b, reps=500, seed=1)
    assert r1 == r2 and r1['delta'] == pytest.approx(0.375) and r1['ci95'][0] <= 0.375 <= r1['ci95'][1]
    assert metrics.paired_bootstrap(a, a, reps=200)['ci95'] == [0.0, 0.0]


def test_one_training_step_runs_and_changes_weights():
    from losses import candidate_losses
    m = build('set'); opt = torch.optim.AdamW(m.parameters(), lr=1e-3)
    x, mask, n = _batch()
    typ = torch.zeros(3, 11, dtype=torch.long)
    lab = _lab(mask, typ, [2, 1, 0], [True, True, True], torch.zeros(3, 11, dtype=torch.bool))
    w0 = m.util.weight.detach().clone()
    u, l = m(x, mask); total, _ = candidate_losses(u, l, lab); total.backward(); opt.step()
    assert not torch.equal(w0, m.util.weight) and torch.isfinite(total)
