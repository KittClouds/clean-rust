"""Candidate-token ABI and root-complete batching for the Phase 7A SetRank / pointwise comparison.

Token for candidate j of a root (365 dims), assembled ONLY from frozen, sealed, observable material:

    x_j = [ cs_j (320) ; e_j (32) ; action-type one-hot (9) ; argument-slot presence (4) ]

    cs_j  = [ c_j (256) ; s (64) ]   trained-E candidate state concatenated with the shared root-context state
                                     (exactly the 'cs' surface of Phase 6A/6B: features(cache,'cs'))
    e_j   = trained-E integrated candidate state (32)
    type  = canonical action type of the candidate text (observable)
    pres  = (cand_ent >= 0) per argument slot: whether the slot is filled. Entity IDs are NEVER features.

cs and e are standardised with TRAIN-only per-dimension statistics (identically for both arms).
Never inputs: legality / satisfies-goal labels, selected or optimal identity, transition distance, simulator
state, candidate IDs, candidate position. Those appear only as supervision/evaluation targets.
"""
import os

import torch

from common import BRIDGE, MAX_N, P6A

TOKEN_DIM = 365
CS_DIM, E_DIM, TYPE_DIM, PRES_DIM = 320, 32, 9, 4


def load_split(split, device='cpu'):
    """Primary-render, root-aligned frozen arrays for TRAIN or DEV. Asserts every alignment.

    P7A_SMOKE=1 (rehearsal only) substitutes disjoint TRAIN slices (roots 0-599 as 'TRAIN', 600-1199 as 'DEV')
    so the whole pipeline can be exercised with no DEV contact."""
    if os.environ.get('P7A_SMOKE'):
        full = _load_split('TRAIN', 'cpu')
        sl = torch.arange(0, 600) if split == 'TRAIN' else torch.arange(600, 1200)
        out = subset(full, sl)
        return {k: (v.to(device) if isinstance(v, torch.Tensor) else v) for k, v in out.items()} if device != 'cpu' else out
    return _load_split(split, device)


def _load_split(split, device='cpu'):
    ds = torch.load(BRIDGE / f'{split}-dataset.pt', weights_only=False)
    ca = torch.load(P6A / f'E-trained-{split}.pt', weights_only=False)
    tg = torch.load(P6A / f'{split}-targets.pt', weights_only=False)
    ix = ds['pairs'][:, 0]
    mask = ca['mask']
    n = mask.sum(1)
    assert len(ix) == mask.shape[0] == (12000 if split == 'TRAIN' else 3000)
    assert bool((mask == ds['H']['cand_mask'][ix]).all()) and bool((mask == tg['mask']).all())
    assert bool((mask == (torch.arange(MAX_N)[None, :] < n[:, None])).all()), 'valid candidates must be a prefix'
    assert [ds['canonical_ids'][int(i)] for i in ix] == tg['canonical_ids'], 'root alignment'
    legal = ds['candidate']['candidate_legal'][ix] > 0.5
    assert bool((legal == (ca['candidate']['candidate_legal'] > 0.5)).all())
    assert not bool((legal & ~mask).any())
    ctype = ds['H']['cand_type'][ix].long()
    assert int(ctype[mask].min()) >= 0 and int(ctype[mask].max()) < TYPE_DIM
    pres = ds['H']['cand_ent'][ix] >= 0
    out = {
        'split': split, 'R': len(ix), 'mask': mask, 'N': n,
        'c': ca['c'], 's': ca['s'], 'e': ca['e'],                      # float16 as cached
        'type': ctype, 'pres': pres, 'legal': legal,                   # legal = supervision/eval only
        'sel_pos': tg['selected_positive'], 'eligible': tg['selected_eligible'],
        'selected': tg['selected'], 'optimal': tg['optimal'], 'opt_eligible': tg['optimal_eligible'],
        'first_type': tg['first_action_type'], 'canonical_ids': tg['canonical_ids'],
        'targets': tg,
    }
    del ds, ca
    return {k: (v.to(device) if isinstance(v, torch.Tensor) else v) for k, v in out.items()} if device != 'cpu' else out


def fit_standardizer(train):
    """TRAIN-only per-dimension mean/std over valid candidates (s is root-level; counted per candidate)."""
    m = train['mask']
    c = train['c'][m].float()
    e = train['e'][m].float()
    s = train['s'][:, None, :].expand(-1, MAX_N, -1)[m].float()
    stats = {}
    for name, v in (('c', c), ('s', s), ('e', e)):
        stats[name + '_mu'] = v.mean(0)
        stats[name + '_sd'] = v.std(0).clamp_min(1e-4)
    return stats


def tokens(D, idx, stats, perm=None):
    """Complete-root batch -> (x [B,N,365] float32, key_mask [B,N], labels dict). ``perm`` permutes the
    valid candidates within each root (padding stays last)."""
    dev = D['c'].device
    idx = idx.to(dev)
    nmax = int(D['N'][idx].max())
    pos = torch.arange(nmax, device=dev)[None, :].expand(len(idx), -1)
    if perm is not None:
        pos = perm.to(dev)
    row = idx[:, None]

    def g(a):
        return a[row, pos]

    mask = g(D['mask'])
    c = (g(D['c']).float() - stats['c_mu']) / stats['c_sd']
    e = (g(D['e']).float() - stats['e_mu']) / stats['e_sd']
    s = ((D['s'][idx].float() - stats['s_mu']) / stats['s_sd'])[:, None, :].expand(-1, nmax, -1)
    ctype = g(D['type'])
    onehot = torch.nn.functional.one_hot(ctype, TYPE_DIM).float()
    x = torch.cat([c, s, e, onehot, g(D['pres']).float()], -1)
    x = x * mask[..., None]
    assert x.shape[-1] == TOKEN_DIM
    labels = {'mask': mask, 'type': ctype, 'legal': g(D['legal']), 'sel': g(D['sel_pos']),
              'eligible': D['eligible'][idx]}
    return x, mask, labels


def make_perm(n, nmax, gen):
    """Random within-root permutation of the n valid slots; padding slots stay in place at the end."""
    r = torch.rand(len(n), nmax, generator=gen)
    ar = torch.arange(nmax)[None, :]
    r = torch.where(ar < n[:, None].cpu(), r, 2.0 + ar.float() / nmax)
    return r.argsort(1)


def subset(D, idx):
    """Root subset (smoke tests / qualification samples). Slices every per-root array and the targets dict."""
    idx = torch.as_tensor(idx)
    R = D['R']

    def cut(v):
        if isinstance(v, torch.Tensor) and v.shape[:1] == (R,):
            return v[idx.to(v.device)]
        if isinstance(v, list) and len(v) == R:
            return [v[int(i)] for i in idx]
        if isinstance(v, dict):
            return {a: cut(b) for a, b in v.items()}
        return v

    out = {k: cut(v) for k, v in D.items()}
    out['R'] = len(idx)
    return out
