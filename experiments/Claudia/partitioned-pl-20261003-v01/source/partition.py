"""Partition-order diagnostics: how well do scores respect  P1 (selected) > P2 (other legal) > P3 (illegal)?

Defined on endpoint-eligible roots, in the full candidate universe and inside the selected candidate's action type
("same-type"). Gold legality defines the partitions for EVALUATION only; the scorer never sees it.

Pair rates are P(score of the better-partition member > score of the worse-partition member), ties counting 1/2, reported
both pooled over pairs and as a root mean (the root is the statistical unit; pairs are not independent samples).

Ordering of a whole root (min/max formulation; "all P1 > all P2 > all P3" is the same event):
  boundary 12  : score(P1) > max(P2)                         (needs P2 non-empty)
  boundary 23  : min(P2) > max(P3)                           (needs P2, P3 non-empty)
  boundary 13  : score(P1) > max(P3)                         (only when P2 is empty: the valid reduced sequence P1 > P3)
  reduced full : every boundary that exists for the root holds (valid reduced partition sequence)
  strict 3-part: roots with all three partitions non-empty and both boundaries holding
"""
import torch


def _universe(D, same_type):
    t = D['targets']
    mask, typ = t['mask'], t['types']
    sel = t['selected'].clamp_min(0)
    onehot = torch.zeros_like(mask)
    onehot.scatter_(1, sel[:, None], True)
    if same_type:
        t_star = typ.gather(1, sel[:, None]).squeeze(1)
        mask = mask & (typ == t_star[:, None])
    legal = D['legal'] & mask
    p1 = onehot & mask
    p2 = legal & ~onehot
    p3 = mask & ~D['legal']
    return p1, p2, p3


def _pair_rate(util, A, Bm, chunk=64):
    """Per-root (wins, pairs) for a in A, b in B: a > b (ties 1/2)."""
    wins = util.new_zeros(len(util))
    n = (A.sum(1) * Bm.sum(1)).float()
    for i in range(0, len(util), chunk):
        s = util[i:i + chunk]
        d = s[:, :, None] - s[:, None, :]
        w = ((d > 0).float() + 0.5 * (d == 0).float()) * A[i:i + chunk, :, None] * Bm[i:i + chunk, None, :]
        wins[i:i + chunk] = w.sum((1, 2))
    return wins, n


def _summarise(wins, n):
    ok = n > 0
    return {'roots': int(ok.sum()), 'pairs': int(n.sum()),
            'pooled': float(wins.sum() / n.sum()) if n.sum() > 0 else None,
            'root_mean': float((wins[ok] / n[ok]).mean()) if ok.any() else None}, \
        torch.where(ok, wins / n.clamp_min(1), torch.full_like(wins, float('nan')))


def partition_metrics(util, D):
    """Returns (summary dict, per-root vectors for the bootstrap). ``util`` [R,171] CPU float."""
    out, vec = {}, {}
    for scope, same in (('full', False), ('same_type', True)):
        p1, p2, p3 = _universe(D, same)
        s = util.masked_fill(~(p1 | p2 | p3), float('nan'))
        entry = {}
        for name, A, Bm in (('selected_gt_legal_other', p1, p2), ('selected_gt_illegal', p1, p3), ('legal_other_gt_illegal', p2, p3)):
            w, n = _pair_rate(util, A.float(), Bm.float())
            entry[name], vec[f'{scope}:{name}'] = _summarise(w, n)
        if scope == 'full':
            w, n = _pair_rate(util, (p1 | p2).float(), p3.float())
            entry['legal_gt_illegal_all_legal_auc'], vec['full:legal_gt_illegal_auc'] = _summarise(w, n)
        neg, pos = float('-inf'), float('inf')
        s1 = util.masked_fill(~p1, neg).max(1).values
        max2 = util.masked_fill(~p2, neg).max(1).values
        min2 = util.masked_fill(~p2, pos).min(1).values
        max3 = util.masked_fill(~p3, neg).max(1).values
        has2, has3 = p2.any(1), p3.any(1)
        b12 = s1 > max2
        b23 = min2 > max3
        b13 = s1 > max3
        applies12, applies23, applies13 = has2, has2 & has3, ~has2 & has3
        reduced_applies = applies12 | applies23 | applies13
        reduced_ok = (~applies12 | b12) & (~applies23 | b23) & (~applies13 | b13)
        strict_applies = has2 & has3
        strict_ok = b12 & b23

        def rate(ok, applies):
            return {'roots': int(applies.sum()), 'rate': float(ok[applies].float().mean()) if applies.any() else None}
        entry['boundary_P1_over_P2'] = rate(b12, applies12)
        entry['boundary_P2_over_P3'] = rate(b23, applies23)
        entry['boundary_P1_over_P3_when_P2_empty'] = rate(b13, applies13)
        entry['reduced_full_ordering'] = rate(reduced_ok, reduced_applies)
        entry['strict_three_partition_ordering'] = rate(strict_ok, strict_applies)
        out[scope] = entry
        nan = torch.full((len(util),), float('nan'))
        vec[f'{scope}:reduced_full_ordering'] = torch.where(reduced_applies, reduced_ok.float(), nan)
        vec[f'{scope}:strict_three_partition_ordering'] = torch.where(strict_applies, strict_ok.float(), nan)
        vec[f'{scope}:boundary_P1_over_P2'] = torch.where(applies12, b12.float(), nan)
        vec[f'{scope}:boundary_P2_over_P3'] = torch.where(applies23, b23.float(), nan)
    return out, vec
