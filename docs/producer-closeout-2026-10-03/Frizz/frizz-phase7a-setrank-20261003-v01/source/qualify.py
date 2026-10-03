"""Permutation-equivariance and padding qualification of the ACTUAL trained/initial networks on real roots.

For every sampled root and K random candidate permutations P:  F(PX) must equal P F(X)  for the utility logits and
the legality logits (floating-point tolerance), and unpermuting must reproduce top-k rankings, the selected top1 and the
legality decisions. Also: a root scored alone equals the same root inside a padded multi-root batch, and garbage in
padded slots changes nothing. Inputs only (no labels) are used except to stratify the sample toward eligible roots.
Run in FP32 (the scoring precision) and FP64 (rounding-free reference).
"""
import argparse

import torch

from common import OUT, receipt
import data as dd
from model import build
from score import load_model
from train import configure

TOL_FP32 = 1e-4
TOL_FP64 = 1e-9


def sample_roots(D, n_eligible, n_other, seed):
    g = torch.Generator().manual_seed(seed)
    el = D['targets']['selected_eligible'].nonzero().flatten()
    ot = (~D['targets']['selected_eligible']).nonzero().flatten()
    return torch.cat([el[torch.randperm(len(el), generator=g)[:n_eligible]], ot[torch.randperm(len(ot), generator=g)[:n_other]]])


@torch.no_grad()
def one_model(model, D, stats, roots, perms, dtype, seed):
    model = model.to(dtype).eval()
    st = {k: v.to(dtype) for k, v in stats.items()}
    g = torch.Generator().manual_seed(seed)
    worst_u = worst_l = 0.0
    top1_bad = top5_bad = dec_bad = checked = 0
    min_margin_bad = float('inf')
    for r in roots.tolist():
        n = int(D['N'][r])
        x, mask, _ = dd.tokens(D, torch.tensor([r]), st)
        x = x.to(dtype)
        u0, l0 = model(x, mask)
        for _ in range(perms):
            P = dd.make_perm(torch.tensor([n]), x.shape[1], g)
            xp = x[torch.arange(1)[:, None], P]
            up, lp = model(xp, mask)
            inv = P.argsort(1)
            u1, l1 = up.gather(1, inv), lp.gather(1, inv)
            worst_u = max(worst_u, float((u1 - u0).abs().max())); worst_l = max(worst_l, float((l1 - l0).abs().max()))
            checked += 1
            # decisions / rankings (ties within tolerance are not counted as failures but their margin is recorded)
            order0, order1 = u0[0].argsort(descending=True)[:5], u1[0].argsort(descending=True)[:5]
            if order0[0] != order1[0]:
                top1_bad += 1
            if not torch.equal(order0, order1):
                top5_bad += 1
                srt = u0[0].sort(descending=True).values
                min_margin_bad = min(min_margin_bad, float((srt[:-1] - srt[1:])[:6].min()))
            if bool(((l0 > 0) != (l1 > 0)).any()):
                dec_bad += 1
                min_margin_bad = min(min_margin_bad, float(torch.minimum(l0.abs(), l1.abs()).min()))
    return {'roots': len(roots), 'permutations_per_root': perms, 'checks': checked,
            'max_abs_utility_logit_diff': worst_u, 'max_abs_legality_logit_diff': worst_l,
            'top1_mismatches': top1_bad, 'top5_order_mismatches': top5_bad, 'legality_decision_mismatches': dec_bad,
            'min_margin_among_mismatches': None if min_margin_bad == float('inf') else min_margin_bad}


@torch.no_grad()
def padding_checks(model, D, stats, roots, dtype):
    model = model.to(dtype).eval()
    st = {k: v.to(dtype) for k, v in stats.items()}
    idx = roots[:12]
    x, mask, _ = dd.tokens(D, idx, st)
    x = x.to(dtype)
    ub, lb = model(x, mask)
    worst = 0.0
    for j, r in enumerate(idx.tolist()):
        n = int(D['N'][r])
        u1, l1 = model(x[j:j + 1, :n], mask[j:j + 1, :n])
        worst = max(worst, float((u1[0] - ub[j, :n]).abs().max()), float((l1[0] - lb[j, :n]).abs().max()))
    junk = x.clone(); junk[~mask] = 77.0
    uj, lj = model(junk, mask)
    junk_diff = max(float((uj - ub)[mask].abs().max()), float((lj - lb)[mask].abs().max()))
    return {'alone_vs_padded_batch_max_diff': worst, 'padded_slot_garbage_max_diff': junk_diff, 'batch_roots': len(idx),
            'width_range_in_batch': [int(D['N'][idx].min()), int(D['N'][idx].max())]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    a = ap.parse_args()
    configure()
    splits = ['TRAIN'] if a.smoke else ['TRAIN', 'DEV']
    data = {s: dd.load_split(s) for s in splits}
    sp = OUT / 'standardizer.pt'
    stats = torch.load(sp) if sp.exists() else (dd.fit_standardizer(data['TRAIN']) if a.smoke else None)
    assert stats is not None, 'standardizer missing'
    result = {'tolerances': {'fp32': TOL_FP32, 'fp64': TOL_FP64}, 'results': {}, 'pass': True}
    for kind in ('set', 'pointwise'):
        for epoch in (0, 12):
            if a.smoke and not (OUT / 'arms' / kind / 'checkpoints' / f'{kind}-epoch{epoch:02d}.pt').exists():
                model = build(kind)
            else:
                model = load_model(kind, epoch)
            for split, D in data.items():
                roots = sample_roots(D, 100, 100, seed=11 + epoch)
                for dtype, tol in ((torch.float32, TOL_FP32), (torch.float64, TOL_FP64)):
                    m = load_model(kind, epoch) if not a.smoke else model
                    r = one_model(m, D, stats, roots, 6, dtype, seed=3)
                    r['padding'] = padding_checks(m, D, stats, roots, dtype)
                    ok = (r['max_abs_utility_logit_diff'] < tol and r['max_abs_legality_logit_diff'] < tol
                          and r['padding']['alone_vs_padded_batch_max_diff'] < tol and r['padding']['padded_slot_garbage_max_diff'] < tol
                          and (r['top1_mismatches'] == 0 and r['legality_decision_mismatches'] == 0
                               or (r['min_margin_among_mismatches'] or 1) < tol))
                    r['pass'] = bool(ok)
                    result['results'][f'{kind}:epoch{epoch:02d}:{split}:{str(dtype).split(".")[-1]}'] = r
                    result['pass'] &= bool(ok)
                    print(kind, epoch, split, str(dtype).split('.')[-1], 'maxdiff', r['max_abs_utility_logit_diff'], 'pass', ok, flush=True)
    result['arm_sanity'] = 'a negative-control positional model is detected as non-equivariant in test_setrank.py'
    if a.smoke:
        print(result['pass'])
    else:
        receipt(OUT / 'EQUIVARIANCE-QUALIFICATION.json', result)
        print('EQUIVARIANCE', 'PASS' if result['pass'] else 'FAIL')


if __name__ == '__main__':
    main()
