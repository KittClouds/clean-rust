"""Primary scoring: initialisation + epoch-12 checkpoints of every arm, CPU / FP32 / deterministic, eligible TRAIN and DEV roots.

These CPU scores are THE scored numbers (per-epoch GPU numbers in trajectory.json are monitoring records). Scores are saved
so every metric can be recomputed without a model; replay re-derives everything in a fresh process.
"""
import argparse
import time

import torch

from common import ALL_ARMS, OUT, receipt, run_dir, sha
import data as dd
import metrics
from model import build
from train import configure, eligible_subset, score

EPOCHS_SCORED = (0, 12)


def load_model(arm, epoch, seed):
    model = build(seed)
    state = torch.load(run_dir(seed) / 'arms' / arm / 'checkpoints' / f'{arm}-epoch{epoch:02d}.pt', weights_only=True)
    model.load_state_dict(state['state_dict'])
    return model.eval()


def load_eval_sets():
    return {'TRAIN': eligible_subset(dd.load_split('TRAIN')), 'DEV': eligible_subset(dd.load_split('DEV'))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    configure()
    torch.set_num_threads(4)
    stats = torch.load(OUT / 'standardizer.pt')
    data = load_eval_sets()
    rd = run_dir(a.seed)
    (rd / 'scores').mkdir(exist_ok=True)
    (rd / 'metrics').mkdir(exist_ok=True)
    timings = {}
    for arm in ALL_ARMS:
        for epoch in EPOCHS_SCORED:
            model = load_model(arm, epoch, a.seed)
            for split, D in data.items():
                t0 = time.perf_counter()
                util = score(model, D, stats)
                seconds = time.perf_counter() - t0
                tag = f'{arm}-epoch{epoch:02d}-{split}'
                path = rd / 'scores' / f'{tag}.pt'
                torch.save({'util': util}, path)
                m, _ = metrics.evaluate(util, D)
                receipt(rd / 'metrics' / f'{tag}.json', {'arm': arm, 'epoch': epoch, 'split': split, 'seed': a.seed, 'roots': D['R'],
                                                         'device': 'cpu-fp32', 'scores_sha256': sha(path), 'metrics': m})
                timings[tag] = seconds
                print('scored', tag, f'{seconds:.1f}s top1', round(m['ranking']['unrestricted']['all']['selected']['top1'], 4), flush=True)
    receipt(rd / 'scoring-cost.json', {'cpu_scoring_seconds': timings, 'threads': 4})


if __name__ == '__main__':
    main()
