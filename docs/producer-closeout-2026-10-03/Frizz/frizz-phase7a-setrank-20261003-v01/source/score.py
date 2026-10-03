"""Primary scoring: epoch-12 (and initialisation) checkpoints, CPU / FP32 / deterministic, TRAIN and DEV.

These CPU scores are THE scored numbers (the per-epoch GPU numbers in trajectory.json are monitoring records).
Scores are saved so metrics can be recomputed without the model; replay re-derives everything in a fresh process.
"""
import json
import time

import torch

from common import OUT, receipt, sha
import data as dd
import metrics
from model import build
from train import configure, score

ARMS = ('set', 'pointwise')
EPOCHS_SCORED = (0, 12)


def load_model(kind, epoch):
    model = build(kind)
    state = torch.load(OUT / 'arms' / kind / 'checkpoints' / f'{kind}-epoch{epoch:02d}.pt', weights_only=True)
    model.load_state_dict(state['state_dict'])
    return model.eval()


def main():
    configure()
    torch.set_num_threads(4)
    stats = torch.load(OUT / 'standardizer.pt')
    data = {'TRAIN': dd.load_split('TRAIN'), 'DEV': dd.load_split('DEV')}
    (OUT / 'scores').mkdir(exist_ok=True)
    (OUT / 'metrics').mkdir(exist_ok=True)
    timings = {}
    for kind in ARMS:
        for epoch in EPOCHS_SCORED:
            model = load_model(kind, epoch)
            for split, D in data.items():
                t0 = time.perf_counter()
                util, leg = score(model, D, stats)
                seconds = time.perf_counter() - t0
                tag = f'{kind}-epoch{epoch:02d}-{split}'
                path = OUT / 'scores' / f'{tag}.pt'
                torch.save({'util': util, 'leg': leg}, path)
                m, _ = metrics.evaluate(util, leg, D)
                receipt(OUT / 'metrics' / f'{tag}.json', {'arm': kind, 'epoch': epoch, 'split': split, 'device': 'cpu-fp32',
                                                          'scores_sha256': sha(path), 'metrics': m})
                timings[tag] = seconds
                print('scored', tag, f'{seconds:.1f}s', 'top1', m['ranking']['unrestricted']['all']['selected']['top1'], flush=True)
    receipt(OUT / 'scoring-cost.json', {'cpu_scoring_seconds': timings, 'threads': 4})


if __name__ == '__main__':
    main()
