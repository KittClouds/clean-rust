"""Train SetRank and the matched pointwise control on identical root orders and permutation streams.

Fixed contract (frozen in SPECIFICATION.json before any DEV scoring): seed 0, 12 epochs, AdamW lr 3e-4,
weight decay 0.01, grad clip 1.0, cosine schedule (per step, to 0), root batch 16, FP32, complete candidate
sets per batch, root order and within-root candidate permutations drawn from dedicated seeded generators that
both arms consume identically. Epoch 12 is the scored endpoint; every epoch's checkpoint and DEV/TRAIN
monitoring record is kept, none is used for selection.
"""
import argparse
import json
import math
import time
from pathlib import Path

import torch

from common import OUT, receipt, sha
import data as dd
import losses
import metrics
from model import build, count_params

SEED, EPOCHS, LR, WD, CLIP, BATCH = 0, 12, 3e-4, 0.01, 1.0, 16


def configure():
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision('highest')


@torch.no_grad()
def score(model, D, stats, bs=64):
    """util, leg for every root (CPU float32 [R,171]); padded slots are 0."""
    model.eval()
    R = D['R']
    util = torch.zeros(R, 171)
    leg = torch.zeros(R, 171)
    for i in range(0, R, bs):
        idx = torch.arange(i, min(i + bs, R))
        x, mask, _ = dd.tokens(D, idx, stats)
        u, l = model(x, mask)
        n = x.shape[1]
        util[i:i + len(idx), :n] = (u * mask).float().cpu()
        leg[i:i + len(idx), :n] = (l * mask).float().cpu()
    return util, leg


def compact(m):
    rk = m['ranking']
    return {'selected_top1': rk['unrestricted']['all']['selected']['top1'],
            'selected_MRR': rk['unrestricted']['all']['selected']['MRR'],
            'gold_type_top1': rk['gold_type']['all']['selected']['top1'],
            'gold_type_MRR': rk['gold_type']['all']['selected']['MRR'],
            'pair_acc_pooled': m['same_type_pairs']['pooled_accuracy'],
            'legality_BA_all': m['legality_all_roots']['candidate_BA'],
            'legality_exact_all': m['legality_all_roots']['exact_legal_set_recovery']}


def run_arm(kind, Dtr, Ddev, Ddev_cpu, Dtr_cpu, stats, out, epochs=EPOCHS, batch=BATCH, monitor_train=True):
    configure()
    dev = 'cuda'
    out.mkdir(parents=True, exist_ok=False)
    ck = out / 'checkpoints'
    ck.mkdir()
    model = build(kind, SEED).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    R = Dtr['R']
    steps_per_epoch = math.ceil(R / batch)
    total = steps_per_epoch * epochs
    g_perm = torch.Generator().manual_seed(SEED + 1)
    traj, hashes = [], {}
    N_cpu = Dtr['N'].cpu()

    def record(epoch, train_loss):
        t0 = time.perf_counter()
        path = ck / f'{kind}-epoch{epoch:02d}.pt'
        torch.save({'state_dict': {k: v.cpu() for k, v in model.state_dict().items()}, 'epoch': epoch, 'kind': kind}, path)
        hashes[path.name] = sha(path)
        u, l = score(model, Ddev, stats)
        dm, _ = metrics.evaluate(u, l, Ddev_cpu)
        row = {'epoch': epoch, 'train_loss': train_loss, 'DEV_monitor': compact(dm)}
        msg = (f'[{kind}] epoch {epoch:2d} DEV top1={row["DEV_monitor"]["selected_top1"]:.4f} '
               f'goldtype={row["DEV_monitor"]["gold_type_top1"]:.4f} legExact={row["DEV_monitor"]["legality_exact_all"]:.4f}')
        if monitor_train:
            u, l = score(model, Dtr, stats)
            tm, _ = metrics.evaluate(u, l, Dtr_cpu)
            row['TRAIN_monitor'] = compact(tm)
            msg += f' | TRAIN top1={row["TRAIN_monitor"]["selected_top1"]:.4f}'
        traj.append(row)
        print(msg + (f' | loss={train_loss["total"]:.4f}' if train_loss else ''), flush=True)
        return time.perf_counter() - t0

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    eval_seconds = record(0, None)
    step = 0
    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(R, generator=torch.Generator().manual_seed(SEED * 1000 + epoch))
        agg = {'total': 0.0, 'select': 0.0, 'same_type': 0.0, 'legality': 0.0}
        nb = 0
        for i in range(0, R, batch):
            idx = order[i:i + batch]
            n = N_cpu[idx]
            perm = dd.make_perm(n, int(n.max()), g_perm)
            x, mask, lab = dd.tokens(Dtr, idx.to(dev), stats, perm)
            lr = 0.5 * LR * (1 + math.cos(math.pi * step / total))
            for gp in opt.param_groups:
                gp['lr'] = lr
            u, l = model(x, mask)
            loss, parts = losses.candidate_losses(u, l, lab)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            opt.step()
            step += 1
            nb += 1
            agg['total'] += float(loss.detach())
            for k in ('select', 'same_type', 'legality'):
                agg[k] += float(parts[k])
        eval_seconds += record(epoch, {k: v / nb for k, v in agg.items()})
    seconds = time.perf_counter() - started
    cost = {'arm': kind, 'parameters': count_params(model), 'epochs': epochs, 'steps': step,
            'train_seconds_including_monitoring': seconds, 'monitoring_seconds': eval_seconds,
            'pure_training_seconds': seconds - eval_seconds, 'peak_cuda_memory_bytes': torch.cuda.max_memory_allocated(),
            'device': torch.cuda.get_device_name(0), 'batch_roots': batch, 'steps_per_epoch': steps_per_epoch}
    receipt(out / 'trajectory.json', {'arm': kind, 'trajectory': traj, 'selection_used': False})
    receipt(out / 'cost.json', cost)
    receipt(out / 'checkpoint-hashes.json', hashes)
    return cost


def to_dev(D, dev='cuda'):
    return {k: (v.to(dev) if isinstance(v, torch.Tensor) else v) for k, v in D.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arms', nargs='+', default=['set', 'pointwise'])
    ap.add_argument('--smoke', action='store_true', help='TRAIN-only subset, scratch dir, no DEV contact')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    configure()
    Dtr_cpu = dd.load_split('TRAIN')
    if a.smoke:
        Dtr_cpu = dd.subset(Dtr_cpu, torch.arange(600))
        Ddev_cpu = dd.subset(Dtr_cpu, torch.arange(300, 600))           # stand-in: TRAIN rows, NOT DEV
        Dtr_cpu = dd.subset(Dtr_cpu, torch.arange(0, 300))
        root = Path(a.out)
        stats = dd.fit_standardizer(Dtr_cpu)
    else:
        Ddev_cpu = dd.load_split('DEV')
        root = OUT / 'arms'
        sp = OUT / 'standardizer.pt'
        if sp.exists():
            stats = torch.load(sp)
        else:
            stats = dd.fit_standardizer(Dtr_cpu)
            torch.save(stats, sp)
            receipt(OUT / 'standardizer.json', {'sha256': sha(sp), 'fit': 'TRAIN valid candidates only',
                                                'dims': {k: len(v) for k, v in stats.items()}})
    stats = {k: v.to('cuda') for k, v in stats.items()}
    Dtr, Ddev = to_dev(Dtr_cpu), to_dev(Ddev_cpu)
    costs = {}
    for arm in a.arms:
        costs[arm] = run_arm(arm, Dtr, Ddev, Ddev_cpu, Dtr_cpu, stats, root / arm, epochs=1 if a.smoke else EPOCHS)
    print(json.dumps(costs, indent=1))


if __name__ == '__main__':
    main()
