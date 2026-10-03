"""Descriptive attention / representation-change diagnostics. Not causal explanations.

Per root (the unit), averaged over roots:
  * normalised attention entropy per layer/head  (H / log n_valid)
  * attention mass to self / same-action-type (other) / different-type, vs the base rate of such keys
  * selected-query mass on legal vs illegal keys (eligible roots), vs the base rate of legal keys among the others
  * candidate-count dependence (bands)
  * representation change  ||h^(L) - h^(0)|| / ||h^(0)||  after each block, and cosine, for BOTH arms
"""
import torch

from common import OUT, BANDS, receipt
import data as dd
from score import load_model
from train import configure


@torch.no_grad()
def run(kind, epoch, D, stats, bs=32):
    model = load_model(kind, epoch)
    R = D['R']
    mask_all = D['targets']['mask']
    typ_all = D['targets']['types']
    legal_all = D['legal']
    sel_all = D['targets']['selected'].clamp_min(0)
    elig = D['targets']['selected_eligible']
    count = mask_all.sum(1)
    L = len(model.blocks)
    heads = 4
    rec = {k: [torch.full((R, L, heads), float('nan')) for _ in range(1)][0] for k in
           ('entropy', 'self', 'same_type', 'diff_type', 'base_same_type', 'sel_legal', 'sel_illegal', 'base_legal')}
    change = torch.full((R, L), float('nan')); cosine = torch.full((R, L), float('nan'))
    for i in range(0, R, bs):
        idx = torch.arange(i, min(i + bs, R))
        x, mask, _ = dd.tokens(D, idx, stats)
        _, _, info = model(x, mask, internals=True)
        n = x.shape[1]
        typ = typ_all[idx, :n]; legal = legal_all[idx, :n]
        h0 = info['hidden'][0]
        for l in range(L):
            hl = info['hidden'][l + 1]
            ch = ((hl - h0).norm(dim=-1) / h0.norm(dim=-1).clamp_min(1e-9))
            cs = torch.nn.functional.cosine_similarity(hl, h0, dim=-1)
            for b in range(len(idx)):
                v = mask[b]
                change[idx[b], l] = ch[b][v].mean(); cosine[idx[b], l] = cs[b][v].mean()
            w = info['attn'][l]
            if w is None:
                continue
            for b in range(len(idx)):
                nb = int(mask[b].sum())
                wb = w[b, :, :nb, :nb]                                   # (H, n, n)
                ent = -(wb * wb.clamp_min(1e-12).log()).sum(-1) / max(torch.log(torch.tensor(float(nb))), 1e-9)
                rec['entropy'][idx[b], l] = ent.mean(-1)
                tb = typ[b, :nb]; same = (tb[:, None] == tb[None, :])
                eye = torch.eye(nb, dtype=torch.bool)
                same_o = same & ~eye; diff = ~same
                rec['self'][idx[b], l] = (wb * eye).sum(-1).mean(-1)
                rec['same_type'][idx[b], l] = (wb * same_o).sum(-1).mean(-1)
                rec['diff_type'][idx[b], l] = (wb * diff).sum(-1).mean(-1)
                rec['base_same_type'][idx[b], l] = (same_o.float().sum(-1) / max(nb - 1, 1)).mean()
                if bool(elig[idx[b]]):
                    j = int(sel_all[idx[b]])
                    lb = legal[b, :nb]; others = torch.ones(nb, dtype=torch.bool); others[j] = False
                    rec['sel_legal'][idx[b], l] = (wb[:, j, :] * (lb & others)).sum(-1)
                    rec['sel_illegal'][idx[b], l] = (wb[:, j, :] * (~lb & others)).sum(-1)
                    rec['base_legal'][idx[b], l] = (lb & others).float().sum() / max(nb - 1, 1)
    return rec, change, cosine, count, elig


def agg(t, sel=None):
    t = t if sel is None else t[sel]
    return torch.nanmean(t, 0) if t.numel() else t


def main():
    configure()
    stats = torch.load(OUT / 'standardizer.pt')
    D = dd.load_split('DEV')
    out = {'note': 'descriptive only; attention weights are not causal explanations', 'arms': {}}
    for kind in ('set', 'pointwise'):
        for epoch in (0, 12):
            rec, change, cosine, count, elig = run(kind, epoch, D, stats)
            entry = {'representation_change_relative_L2_by_layer': agg(change).tolist(),
                     'representation_cosine_to_input_projection_by_layer': agg(cosine).tolist()}
            if kind == 'set':
                for k, v in rec.items():
                    sel = elig if k in ('sel_legal', 'sel_illegal', 'base_legal') else None
                    entry[k + '_by_layer_head'] = agg(v, sel).tolist()
                entry['bands'] = {}
                for label, lo, hi in BANDS:
                    g = (count >= lo) & (count <= hi)
                    entry['bands'][label] = {'roots': int(g.sum()),
                                             'normalised_entropy_by_layer_head': agg(rec['entropy'], g).tolist(),
                                             'same_type_mass_by_layer_head': agg(rec['same_type'], g).tolist(),
                                             'base_same_type_rate_by_layer': agg(rec['base_same_type'], g).mean(-1).tolist(),
                                             'representation_change_by_layer': agg(change, g).tolist()}
            out['arms'][f'{kind}:epoch{epoch:02d}'] = entry
            print('diagnosed', kind, epoch, flush=True)
    receipt(OUT / 'ATTENTION-DIAGNOSTICS.json', out)


if __name__ == '__main__':
    main()
