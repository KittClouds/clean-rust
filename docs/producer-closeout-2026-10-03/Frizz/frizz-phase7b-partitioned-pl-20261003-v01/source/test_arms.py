import math

import pytest
import torch

import losses
import pl
from model import build, count_params
from test_pl import brute_nll

torch.use_deterministic_algorithms(True)


def batch(seed=0, B=4, N=9, dtype=torch.float64):
    g = torch.Generator().manual_seed(seed)
    mask = torch.ones(B, N, dtype=torch.bool)
    mask[1, 7:] = False
    mask[2, 6:] = False
    typ = torch.randint(0, 3, (B, N), generator=g)
    legal = torch.rand(B, N, generator=g) < 0.4
    sel = torch.zeros(B, N, dtype=torch.bool)
    for b in range(B):
        j = int(torch.nonzero(legal[b] & mask[b])[0]) if (legal[b] & mask[b]).any() else 0
        legal[b, j] = True
        sel[b, j] = True
    util = (torch.randn(B, N, generator=g, dtype=dtype) * 1.2).requires_grad_(True)
    return util, {'mask': mask, 'type': typ, 'sel': sel, 'legal': legal & mask}


def per_root_brute(util, lab, arm):
    out_full, out_same = [], []
    for b in range(util.shape[0]):
        mask, sel, legal, typ = lab['mask'][b], lab['sel'][b], lab['legal'][b], lab['type'][b]
        s = util[b].detach()

        if arm == 'ce':
            def grp(valid):  # selected first, everything else one tied group
                return [(-1 if not valid[i] else 0 if sel[i] else 1) for i in range(len(s))]
        else:
            def grp(valid):
                return [(-1 if not valid[i] else 0 if sel[i] else 1 if legal[i] else 2) for i in range(len(s))]
        t_star = int(typ[sel][0])
        same_valid = mask & (typ == t_star)
        out_full.append(brute_nll(s, grp(mask)))
        out_same.append((brute_nll(s, grp(same_valid)), int(same_valid.sum()) > 1))
    return out_full, out_same


@pytest.mark.parametrize('arm', ['ce', 'partitioned_pl'])
def test_arm_loss_equals_brute_force_marginalisation(arm):
    util, lab = batch()
    total, parts = losses.arm_loss(arm, util, lab)
    full, same = per_root_brute(util, lab, arm)
    n = sum(1 for _, ok in same if ok)
    ref = sum(full) / len(full) + 0.5 * sum(v for v, ok in same if ok) / max(n, 1)
    assert abs(float(total) - ref) < 1e-9 and parts['same_type_roots'] == n


def test_partitioned_equals_ce_when_there_are_no_other_legal_candidates():
    util, lab = batch(seed=3)
    lab['legal'] = lab['sel'].clone()                                  # only the selected candidate is legal
    a, _ = losses.arm_loss('ce', util, lab)
    c, _ = losses.arm_loss('partitioned_pl', util, lab)
    assert abs(float(a) - float(c)) < 1e-9


def test_partitioned_differs_from_ce_when_other_legal_candidates_exist_and_is_larger():
    util, lab = batch(seed=1)
    a, _ = losses.arm_loss('ce', util, lab)
    c, _ = losses.arm_loss('partitioned_pl', util, lab)
    assert float(c) > float(a) + 1e-3                                   # more ordering events -> larger NLL


def test_vanilla_pl_is_a_noisy_upper_bound_of_the_partitioned_nll():
    util, lab = batch(seed=2)
    c, _ = losses.arm_loss('partitioned_pl', util, lab)
    gen = torch.Generator().manual_seed(0)
    vals = [float(losses.arm_loss('vanilla_pl', util, lab, gen)[0]) for _ in range(200)]
    assert min(vals) >= float(c) - 1e-9 and len(set(round(v, 6) for v in vals)) > 20
    assert sum(vals) / len(vals) > float(c)


@pytest.mark.parametrize('arm', ['ce', 'vanilla_pl', 'partitioned_pl'])
def test_gradients_finite_nonzero_and_padding_inert(arm):
    util, lab = batch(seed=5)
    total, _ = losses.arm_loss(arm, util, lab, torch.Generator().manual_seed(1))
    total.backward()
    assert torch.isfinite(util.grad).all() and util.grad.abs().sum() > 1e-6
    assert util.grad[~lab['mask']].abs().sum() == 0                     # padded candidates receive no gradient


def test_arms_share_initialisation_and_parameter_count():
    a, b, c = build(0), build(0), build(0)
    for pa, pb, pc in zip(a.parameters(), b.parameters(), c.parameters()):
        assert torch.equal(pa, pb) and torch.equal(pa, pc)
    assert count_params(a) == 365 * 128 + 128 + 128 * 64 + 64 + 64 + 1


def test_partition_groups_labels():
    mask = torch.tensor([[1, 1, 1, 1, 0]], dtype=torch.bool)
    legal = torch.tensor([[1, 1, 0, 1, 0]], dtype=torch.bool)
    sel = torch.tensor([[0, 1, 0, 0, 0]], dtype=torch.bool)
    assert losses.partition_groups(mask, legal, sel).tolist() == [[1, 0, 2, 1, -1]]
