"""Real-data invariance qualification of every arm's scorer (initialisation and epoch 12).

The scorer is candidate-independent, so it must be (a) invariant to candidate order (scores permute with the candidates) and
(b) invariant to padding / batch composition. Checked on all eligible roots of TRAIN and DEV in FP32 and FP64 (tolerances
1e-5 / 1e-10). Together with the grouped-PL brute-force tests (test_pl.py) this is the engineering gate before interpretation.
"""
import argparse

import torch

from common import ALL_ARMS, OUT, receipt, run_dir
import data as dd
from score import load_eval_sets, load_model
from train import configure

TOL = {torch.float32: 1e-5, torch.float64: 1e-10}


@torch.no_grad()
def check(model, D, stats, dtype, seed=5, n_roots=120):
    model = model.to(dtype).eval()
    st = {k: v.to(dtype) for k, v in stats.items()}
    g = torch.Generator().manual_seed(seed)
    roots = torch.randperm(D['R'], generator=g)[:n_roots]
    x, mask, _ = dd.tokens(D, roots, st)
    x = x.to(dtype)
    base = model(x, mask)
    perm = dd.make_perm(D['N'][roots], x.shape[1], g)
    xp = x[torch.arange(len(roots))[:, None], perm]
    perm_diff = float((model(xp, mask).gather(1, perm.argsort(1)) - base)[mask].abs().max())
    worst = 0.0
    for j in range(len(roots)):
        n = int(D['N'][roots[j]])
        alone = model(x[j:j + 1, :n], mask[j:j + 1, :n])
        worst = max(worst, float((alone[0] - base[j, :n]).abs().max()))
    junk = x.clone()
    junk[~mask] = 55.0
    junk_diff = float((model(junk, mask) - base)[mask].abs().max())
    return {'roots': len(roots), 'candidate_permutation_max_diff': perm_diff, 'alone_vs_padded_batch_max_diff': worst,
            'padded_slot_garbage_max_diff': junk_diff,
            'pass': bool(max(perm_diff, worst, junk_diff) < TOL[dtype])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    configure()
    stats = torch.load(OUT / 'standardizer.pt')
    data = load_eval_sets()
    result = {'tolerances': {'fp32': 1e-5, 'fp64': 1e-10}, 'results': {}, 'pass': True}
    for arm in ALL_ARMS:
        for epoch in (0, 12):
            for split, D in data.items():
                for dtype in (torch.float32, torch.float64):
                    r = check(load_model(arm, epoch, a.seed), D, stats, dtype)
                    result['results'][f'{arm}:epoch{epoch:02d}:{split}:{str(dtype).split(".")[-1]}'] = r
                    result['pass'] &= r['pass']
    receipt(run_dir(a.seed) / 'INVARIANCE-QUALIFICATION.json', result)
    print('INVARIANCE', 'PASS' if result['pass'] else 'FAIL', max(r['candidate_permutation_max_diff'] for r in result['results'].values()))


if __name__ == '__main__':
    main()
