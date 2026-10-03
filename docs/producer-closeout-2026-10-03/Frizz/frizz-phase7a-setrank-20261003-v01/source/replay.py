"""Fresh-process replay. Re-derives everything from frozen inputs + checkpoints and compares with the recorded receipts.

1. re-hash every consumed frozen input against INPUT-IDENTITY.json
2. re-hash every checkpoint against checkpoint-hashes.json
3. re-score DEV (and TRAIN) on CPU/FP32 from the checkpoints; compare with the saved scores and recorded metrics
4. recompute the paired bootstrap comparison from the recomputed scores; compare with COMPARISON.json
5. require the equivariance qualification receipt to have passed
"""
import json
import sys

import torch

from common import OUT, SOURCE, read, receipt, sha
import data as dd
import metrics
from compare import SEEDS
from score import ARMS, EPOCHS_SCORED, load_model
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
    configure()
    torch.set_num_threads(4)
    report = {'checks': {}, 'status': 'PENDING'}
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
    for kind in ARMS:
        for name, digest in read(OUT / 'arms' / kind / 'checkpoint-hashes.json').items():
            if sha(OUT / 'arms' / kind / 'checkpoints' / name) != digest:
                raise ValueError(f'checkpoint drift: {name}')
            n_ck += 1
    report['checks']['checkpoints_rehashed'] = n_ck
    stats = torch.load(OUT / 'standardizer.pt')
    if sha(OUT / 'standardizer.pt') != read(OUT / 'standardizer.json')['sha256']:
        raise ValueError('standardizer drift')
    data = {'TRAIN': dd.load_split('TRAIN'), 'DEV': dd.load_split('DEV')}
    max_score_diff = 0.0
    diffs = []
    recomputed = {}
    for kind in ARMS:
        for epoch in EPOCHS_SCORED:
            model = load_model(kind, epoch)
            for split, D in data.items():
                tag = f'{kind}-epoch{epoch:02d}-{split}'
                util, leg = score(model, D, stats)
                saved = torch.load(OUT / 'scores' / f'{tag}.pt')
                max_score_diff = max(max_score_diff, float((util - saved['util']).abs().max()), float((leg - saved['leg']).abs().max()))
                m, _ = metrics.evaluate(util, leg, D)
                rec = read(OUT / 'metrics' / f'{tag}.json')
                if rec['scores_sha256'] != sha(OUT / 'scores' / f'{tag}.pt'):
                    raise ValueError('score file drift ' + tag)
                diffs += deep_diff(json.loads(json.dumps(m)), rec['metrics'], tag)
                recomputed[tag] = (util, leg)
                print('replayed', tag, flush=True)
    report['checks']['max_abs_score_difference_vs_saved'] = max_score_diff
    report['checks']['metric_differences'] = len(diffs)
    # comparison replay (DEV, epoch 12)
    D = data['DEV']; el = D['targets']['selected_eligible']
    ex = {}
    for kind in ARMS:
        util, leg = recomputed[f'{kind}-epoch12-DEV']
        ex[kind] = metrics.evaluate(util, leg, D)[1]
    saved_cmp = read(OUT / 'COMPARISON.json')['bootstrap']
    redo = {}
    for key, name in (('unrestricted_top1', 'selected_top1'), ('unrestricted_mrr', 'selected_MRR'),
                      ('gold_type_top1', 'gold_type_top1'), ('gold_type_mrr', 'gold_type_MRR')):
        redo[name] = metrics.paired_bootstrap(ex['set']['vectors'][key][el].numpy(), ex['pointwise']['vectors'][key][el].numpy(), seed=SEEDS['top1'])
    redo['legality_exact_set_all_3000_roots'] = metrics.paired_bootstrap(ex['set']['exact_legal_all'].numpy(), ex['pointwise']['exact_legal_all'].numpy(), seed=SEEDS['top1'])
    cmp_diffs = deep_diff(json.loads(json.dumps(redo)), {k: saved_cmp[k] for k in redo}, 'COMPARISON')
    report['checks']['comparison_differences'] = len(cmp_diffs)
    eq = read(OUT / 'EQUIVARIANCE-QUALIFICATION.json')
    report['checks']['equivariance_receipt_passed'] = bool(eq['pass'])
    all_diffs = diffs + cmp_diffs
    report['first_differences'] = [str(d) for d in all_diffs[:10]]
    ok = (not all_diffs) and max_score_diff <= 1e-6 and eq['pass']
    report['status'] = 'PASS' if ok else 'FAIL'
    receipt(OUT / 'REPLAY.json', report)
    print('REPLAY', report['status'], report['checks'])
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
