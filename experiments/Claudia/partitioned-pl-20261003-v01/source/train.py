"""Train the three matched arms (CE / vanilla PL / partitioned PL) from IDENTICAL initial weights on IDENTICAL data order.

Fixed contract (frozen in SPECIFICATION.json before any DEV scoring): seed S (0 primary), 12 epochs, AdamW lr 3e-4,
weight decay 0.01, grad clip 1.0, cosine to 0 per step (no warmup), root batch 32, FP32, complete candidate sets, canonical
candidate order (the scorer is candidate-independent), training population = the endpoint-eligible TRAIN roots (1,333).
Epoch 12 is the scored endpoint; every epoch is recorded (checkpoint + DEV/TRAIN monitoring) and none is used for selection.
"""
import argparse
import json
import math
import time

import torch

from common import ALL_ARMS, OUT, receipt, run_dir, sha
import data as dd
import losses
import metrics
from model import build, count_params

EPOCHS, LR, WD, CLIP, BATCH = 12, 3e-4, 0.01, 1.0, 32


def configure():
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision('highest')


def eligible_subset(D):
    return dd.subset(D, D['targets']['selected_eligible'].nonzero().flatten())


@torch.no_grad()
def score(model, D, stats, bs=64):
    """Utility for every root (CPU float32 [R,171]); padded slots are 0."""
    model.eval()
    R = D['R']
    util = torch.zeros(R, 171)
    for i in range(0, R, bs):
        idx = torch.arange(i, min(i + bs, R))
        x, mask, _ = dd.tokens(D, idx, stats)
        util[i:i + len(idx), :x.shape[1]] = (model(x, mask) * mask).float().cpu()
    return util


def compact(m, part):
    rk = m['ranking']
    f, s = part['full'], part['same_type']
    return {'selected_top1': rk['unrestricted']['all']['selected']['top1'], 'selected_MRR': rk['unrestricted']['all']['selected']['MRR'],
            'gold_type_top1': rk['gold_type']['all']['selected']['top1'], 'gold_type_MRR': rk['gold_type']['all']['selected']['MRR'],
            'pair_acc_pooled': m['same_type_pairs']['pooled_accuracy'],
            'sel_gt_legal_other': f['selected_gt_legal_other']['root_mean'], 'sel_gt_illegal': f['selected_gt_illegal']['root_mean'],
            'legal_other_gt_illegal': f['legal_other_gt_illegal']['root_mean'],
            'same_type_sel_gt_legal_other': s['selected_gt_legal_other']['root_mean'],
            'reduced_full_ordering': f['reduced_full_ordering']['rate']}


def evaluate_compact(util, D):
    m, ex = metrics.evaluate(util, D)
    return compact(m, m['partition_order'])


def init_hash(model):
    h = torch.cat([p.detach().flatten().cpu() for p in model.parameters()])
    return sha_tensor(h)


def sha_tensor(t):
    import hashlib
    return hashlib.sha256(t.numpy().tobytes()).hexdigest()


def run_arm(arm, seed, Dtr, Ddev, Dtr_cpu, Ddev_cpu, stats, out, epochs=EPOCHS):
    configure()
    dev = 'cuda'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'checkpoints').mkdir()
    model = build(seed).to(dev)
    init = init_hash(model)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    R = Dtr['R']
    steps_per_epoch = math.ceil(R / BATCH)
    total = steps_per_epoch * epochs
    gen = torch.Generator().manual_seed(seed + 17)                 # only the vanilla-PL arm consumes it
    traj, hashes = [], {}

    def record(epoch, train_loss):
        t0 = time.perf_counter()
        path = out / 'checkpoints' / f'{arm}-epoch{epoch:02d}.pt'
        torch.save({'state_dict': {k: v.cpu() for k, v in model.state_dict().items()}, 'epoch': epoch, 'arm': arm}, path)
        hashes[path.name] = sha(path)
        row = {'epoch': epoch, 'train_loss': train_loss,
               'DEV_monitor': evaluate_compact(score(model, Ddev, stats), Ddev_cpu),
               'TRAIN_monitor': evaluate_compact(score(model, Dtr, stats), Dtr_cpu)}
        traj.append(row)
        d, t = row['DEV_monitor'], row['TRAIN_monitor']
        print(f'[{arm}] epoch {epoch:2d} DEV top1={d["selected_top1"]:.4f} goldtype={d["gold_type_top1"]:.4f} MRR={d["selected_MRR"]:.4f} '
              f'| TRAIN top1={t["selected_top1"]:.4f} reduced-order={t["reduced_full_ordering"]:.3f}'
              + (f' | loss={train_loss["total"]:.4f}' if train_loss else ''), flush=True)
        return time.perf_counter() - t0

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    monitor_seconds = record(0, None)
    step = 0
    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(R, generator=torch.Generator().manual_seed(seed * 1000 + epoch))
        agg = {'total': 0.0, 'full': 0.0, 'same_type': 0.0, 'selected_ce_monitor': 0.0}
        nb = 0
        for i in range(0, R, BATCH):
            idx = order[i:i + BATCH]
            x, mask, lab = dd.tokens(Dtr, idx.to(dev), stats)
            lr = 0.5 * LR * (1 + math.cos(math.pi * step / total))
            for gp in opt.param_groups:
                gp['lr'] = lr
            util = model(x, mask)
            loss, parts = losses.arm_loss(arm, util, lab, gen)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            opt.step()
            step += 1
            nb += 1
            agg['total'] += float(loss.detach())
            for k in ('full', 'same_type', 'selected_ce_monitor'):
                agg[k] += float(parts[k])
        monitor_seconds += record(epoch, {k: v / nb for k, v in agg.items()})
    seconds = time.perf_counter() - started
    cost = {'arm': arm, 'seed': seed, 'parameters': count_params(model), 'epochs': epochs, 'steps': step,
            'initial_weights_sha256': init, 'train_seconds_including_monitoring': seconds, 'monitoring_seconds': monitor_seconds,
            'pure_training_seconds': seconds - monitor_seconds, 'peak_cuda_memory_bytes': torch.cuda.max_memory_allocated(),
            'device': torch.cuda.get_device_name(0), 'batch_roots': BATCH, 'steps_per_epoch': steps_per_epoch}
    receipt(out / 'trajectory.json', {'arm': arm, 'trajectory': traj, 'selection_used': False})
    receipt(out / 'cost.json', cost)
    receipt(out / 'checkpoint-hashes.json', hashes)
    return cost


def to_dev(D, dev='cuda'):
    return {k: (v.to(dev) if isinstance(v, torch.Tensor) else v) for k, v in D.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--arms', nargs='+', default=list(ALL_ARMS))
    a = ap.parse_args()
    configure()
    full_tr = dd.load_split('TRAIN')
    sp = OUT / 'standardizer.pt'
    if sp.exists():
        stats = torch.load(sp)
    else:
        stats = dd.fit_standardizer(full_tr)                     # TRAIN-only, all 12,000 roots
        torch.save(stats, sp)
        receipt(OUT / 'standardizer.json', {'sha256': sha(sp), 'fit': 'TRAIN valid candidates only (12,000 roots)',
                                            'dims': {k: len(v) for k, v in stats.items()}})
    Dtr_cpu = eligible_subset(full_tr)
    Ddev_cpu = eligible_subset(dd.load_split('DEV'))
    stats = {k: v.to('cuda') for k, v in stats.items()}
    Dtr, Ddev = to_dev(Dtr_cpu), to_dev(Ddev_cpu)
    print(f'training roots {Dtr_cpu["R"]} (eligible TRAIN); DEV eligible roots {Ddev_cpu["R"]}', flush=True)
    root = run_dir(a.seed) / 'arms'
    costs = {}
    for arm in a.arms:
        costs[arm] = run_arm(arm, a.seed, Dtr, Ddev, Dtr_cpu, Ddev_cpu, stats, root / arm)
    inits = {v['initial_weights_sha256'] for v in costs.values()}
    print(json.dumps({k: {x: v[x] for x in ('parameters', 'pure_training_seconds', 'initial_weights_sha256')} for k, v in costs.items()}, indent=1))
    assert len(inits) == 1 or len(a.arms) == 1, 'arms must share initial weights'


if __name__ == '__main__':
    main()
