"""Versioned Qwen-only artifact boundaries; no historical output mutation."""
from pathlib import Path
import hashlib
import json
import sys

import torch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OLD = REPO / 'experiments/s15-lepori-minicpm-causal'
BANK = REPO / 'experiments/ff-s15-bank-01/releases/BANK-v1'
OLD_PRIM = Path('D:/codex-runs/encoder-contrast-01/lepori-causal-minicpm/primitives')
MODEL = Path('D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base')
OUT = Path('C:/phoenix-target-overgraph/s15-qwen-two-run-20261001-v02')
REVISION = 'dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68'
SURFACES = ['lt@24', 'mf@24', 'ms@24', 'mf@18', 'mf@12', 'mf@6']
sys.path.insert(0, str(OLD))
from src.graft import Interface  # pure architecture; no historical run imports
from src.ontology import GLOBAL_GROUPS, CAND_GROUPS, COUNT_TARGET
from src.objective import balanced_bce, js_bernoulli, js_categorical, variance_floor_loss


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def receipt(path, value):
    """Create-only receipts; completed identities are never silently overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def read_jsonl(path, wanted):
    rows = {}
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            wid = row['world_id']
            if wid in wanted:
                if wid in rows:
                    raise ValueError(f'duplicate row {wid}')
                rows[wid] = row
    if rows.keys() != wanted:
        raise ValueError(f'missing {len(wanted - rows.keys())} input rows')
    return rows


def old_ids(split):
    if split not in ('TRAIN', 'DEV'):
        raise ValueError('TRAIN/DEV only')
    p = torch.load(OLD_PRIM / f'{split}-full.pt', mmap=True, weights_only=False)
    ids = list(p['row_ids'])
    if len(ids) != len(set(ids)) or any(not x.startswith(split + ':') for x in ids):
        raise ValueError('invalid historical split identity')
    return ids


def masked_forward(model, H):
    s, e, g, c, a, bank = model(H)
    return s, e, g, c, a.masked_fill(~H['cand_mask'].bool(), -1e9), bank
