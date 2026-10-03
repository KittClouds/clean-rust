"""Fresh-process replay of one seed. Re-derives everything from frozen inputs + checkpoints and compares with the receipts.

1. frozen source files unchanged since SPECIFICATION.json     2. every consumed frozen input re-hashed (INPUT-IDENTITY.json)
3. every checkpoint re-hashed                                  4. all scores recomputed on CPU/FP32 and compared with the saved
scores and recorded metrics (TRAIN-eligible and DEV-eligible, initialisation and epoch 12, every arm)
5. the paired bootstrap comparison recomputed                  6. the invariance qualification receipt must have passed
"""
import argparse
import json
import sys

import torch

from common import ALL_ARMS, OUT, SOURCE, read, receipt, run_dir, sha
import metrics
from compare import PAIRS, PART, SCALARS, SEED
from score import EPOCHS_SCORED, load_eval_sets, load_model
from train import configure, score

TOL = 1e-9


def deep_diff(a, b, path='', out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append((path, 'keys', sorted(set(a) ^ set(b))[:5]))
        for k in a:
            if k in b:
                deep_diff(a[k], b[k], f'{path}/{k}', out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, 'len', (len(a), len(b))))
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f'{path}[{i}]', out)
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or abs(a - b) > TOL:
            out.append((path, 'float', (a, b)))
    elif a != b:
        out.append((path, 'value', (a, b)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    configure()
    torch.set_num_threads(4)
    rd = run_dir(a.seed)
    report = {'seed': a.seed, 'checks': {}, 'status': 'PENDING'}
    spec = read(OUT / 'SPECIFICATION.json')
    for name, digest in spec['source_hashes'].items():
        if sha(SOURCE / name) != digest:
            raise ValueError(f'frozen source drift since specification: {name}')
    report['checks']['frozen_source_files_unchanged'] = len(spec['source_hashes'])
    ident = read(OUT / 'INPUT-IDENTITY.json')
    for name, v in ident['consumed'].items():
        if sha(v['path']) != v['sha256']:
            raise ValueError(f'frozen input drift: {name}')
    report['checks']['consumed_inputs_rehashed'] = len(ident['consumed'])
    n_ck = 0
    for arm in ALL_ARMS:
        for name, digest in read(rd / 'arms' / arm / 'checkpoint-hashes.json').items():
            if sha(rd / 'arms' / arm / 'checkpoints' / name) != digest:
                raise ValueError(f'checkpoint drift: {name}')
            n_ck += 1
    report['checks']['checkpoints_rehashed'] = n_ck
    if sha(OUT / 'standardizer.pt') != read(OUT / 'standardizer.json')['sha256']:
        raise ValueError('standardizer drift')
    stats = torch.load(OUT / 'standardizer.pt')
    data = load_eval_sets()
    max_diff, diffs, ex = 0.0, [], {}
    for arm in ALL_ARMS:
        for epoch in EPOCHS_SCORED:
            model = load_model(arm, epoch, a.seed)
            for split, D in data.items():
                tag = f'{arm}-epoch{epoch:02d}-{split}'
                util = score(model, D, stats)
                saved = torch.load(rd / 'scores' / f'{tag}.pt')['util']
                max_diff = max(max_diff, float((util - saved).abs().max()))
                m, extras = metrics.evaluate(util, D)
                rec = read(rd / 'metrics' / f'{tag}.json')
                if rec['scores_sha256'] != sha(rd / 'scores' / f'{tag}.pt'):
                    raise ValueError('score file drift ' + tag)
                diffs += deep_diff(json.loads(json.dumps(m)), rec['metrics'], tag)
                if split == 'DEV' and epoch == 12:
                    ex[arm] = extras
                print('replayed', tag, flush=True)
    report['checks']['max_abs_score_difference_vs_saved'] = max_diff
    report['checks']['metric_differences'] = len(diffs)
    saved_cmp = read(rd / 'COMPARISON.json')['comparisons']
    cmp_diffs = []
    for x, y in PAIRS:
        boot = {name: metrics.paired_bootstrap(ex[x]['vectors'][key].numpy(), ex[y]['vectors'][key].numpy(), seed=SEED) for name, key in SCALARS.items()}
        for k in PART:
            boot[k] = metrics.paired_bootstrap(ex[x]['partition_vectors'][k].numpy(), ex[y]['partition_vectors'][k].numpy(), seed=SEED)
        cmp_diffs += deep_diff(json.loads(json.dumps(boot)), {k: saved_cmp[f'{x}__minus__{y}']['bootstrap'][k] for k in boot}, f'{x}-{y}')
    report['checks']['comparison_differences'] = len(cmp_diffs)
    qual = read(rd / 'INVARIANCE-QUALIFICATION.json')
    report['checks']['invariance_receipt_passed'] = bool(qual['pass'])
    alld = diffs + cmp_diffs
    report['first_differences'] = [str(d) for d in alld[:10]]
    ok = (not alld) and max_diff <= 1e-6 and qual['pass']
    report['status'] = 'PASS' if ok else 'FAIL'
    receipt(rd / 'REPLAY.json', report)
    print('REPLAY', report['status'], report['checks'])
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
