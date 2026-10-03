"""Phase 7A metrics. Ranking code is the Phase 6A ranking.py (frozen, verbatim) so numbers are comparable with
the sealed independent-scorer references; everything else is new and root-clustered.

Statistical unit = canonical root. Candidate-level pooled numbers are always labelled as such.
"""
import numpy as np
import torch

from common import ACTION_TYPES, BANDS, RELIABLE_ROOTS


# ---------------------------------------------------------------- Phase 6A ranking (verbatim) -------------
def summary(ranks, good, counts, excluded, positive_count=None):
    r = ranks[good].float(); n = int(good.sum())
    return {'eligible_roots': n, 'excluded_by_restriction': int((excluded & good).sum()),
            'mean_rank': float(r.mean()) if n else None,
            'MRR': float(torch.where(excluded[good], 0., r.reciprocal()).mean()) if n else None,
            **{f'top{k}': float(((r <= k) & ~excluded[good]).float().mean()) if n else None for k in (1, 3, 5)},
            'uniform_top1_expectation': float(((torch.ones_like(counts) if positive_count is None else positive_count)[good] / counts[good].float()).mean()) if n else None,
            'root_supported': n >= 200}


def ranking(scores, t, predicted_type=None):
    count = t['mask'].sum(1); result = {}; raw = {}
    gold = t['first_action_type']; eligible = t['selected_eligible']
    for restriction in ('unrestricted', 'gold_type', 'predicted_type'):
        allowed = t['mask'].clone()
        if restriction != 'unrestricted':
            kind = gold if restriction == 'gold_type' else predicted_type
            allowed &= t['types'] == kind[:, None]
        ordered = scores.masked_fill(~allowed, float('-inf')).argsort(dim=1, descending=True, stable=True)
        position = torch.zeros_like(ordered)
        position.scatter_(1, ordered, torch.arange(1, scores.shape[1] + 1)[None, :].expand_as(ordered))
        selected = t['selected'].clamp_min(0)
        missing = ~allowed.gather(1, selected[:, None]).squeeze(1)
        sr = position.gather(1, selected[:, None]).squeeze(1)
        sr = torch.where(missing, count + 1, sr)
        member = t['optimal'] & allowed; empty = ~member.any(1)
        optimal = position.masked_fill(~member, scores.shape[1] + 1).min(1).values
        optimal = torch.where(empty, count + 1, optimal)
        views = {}
        for label, choose in [('all', torch.ones(len(count), dtype=torch.bool)),
                              ('1-28', count <= 28), ('29-64', (count > 28) & (count <= 64)),
                              ('65-128', (count > 64) & (count <= 128)), ('129-171', count > 128)]:
            views[label] = {'selected': summary(sr, eligible & choose, count, missing),
                            'optimal': summary(optimal, t['optimal_eligible'] & choose, count, empty, t['optimal'].sum(1))}
        result[restriction] = views
        raw[restriction] = {'selected_rank': sr, 'optimal_rank': optimal, 'selected_excluded': missing,
                            'optimal_excluded': empty, 'selected_top1': (sr == 1) & ~missing,
                            'optimal_top1': (optimal == 1) & ~empty}
    return result, raw


# ---------------------------------------------------------------- new metrics -------------------------------
def rank_all(util, D):
    """Ranking views for unrestricted and gold-type (diagnostic only); predicted-type view is not used."""
    t = D['targets']
    res, raw = ranking(util, t, predicted_type=t['first_action_type'])
    res.pop('predicted_type'); raw.pop('predicted_type')
    return res, raw


def per_root_vectors(raw, D):
    """Per-root arrays for the bootstrap (all roots; select with D['eligible'])."""
    out = {}
    for r in ('unrestricted', 'gold_type'):
        rank = raw[r]['selected_rank'].float()
        out[f'{r}_top1'] = raw[r]['selected_top1'].float()
        out[f'{r}_mrr'] = torch.where(raw[r]['selected_excluded'], torch.zeros_like(rank), rank.reciprocal())
    return out


def same_type_pairs(util, D):
    """Exhaustive selected-vs-same-type-alternative pair accuracy (ties count 1/2)."""
    t = D['targets']; mask, typ = t['mask'], t['types']
    sel = t['selected'].clamp_min(0); elig = t['selected_eligible']
    s_star = util.gather(1, sel[:, None]).squeeze(1)
    t_star = typ.gather(1, sel[:, None]).squeeze(1)
    onehot = torch.zeros_like(mask); onehot.scatter_(1, sel[:, None], True)
    alt = mask & (typ == t_star[:, None]) & ~onehot & elig[:, None]
    wins = (((s_star[:, None] > util) & alt).float() + 0.5 * ((s_star[:, None] == util) & alt).float()).sum(1)
    n = alt.sum(1).float()
    count = mask.sum(1)
    out = {'pairs': int(n.sum()), 'roots_with_pairs': int((n > 0).sum()),
           'pooled_accuracy': float(wins.sum() / n.sum()) if n.sum() > 0 else None,
           'root_mean_accuracy': float((wins[n > 0] / n[n > 0]).mean()) if (n > 0).any() else None, 'bands': {}}
    for label, lo, hi in BANDS:
        g = (n > 0) & (count >= lo) & (count <= hi)
        out['bands'][label] = {'roots': int(g.sum()), 'pairs': int(n[g].sum()),
                               'pooled_accuracy': float(wins[g].sum() / n[g].sum()) if g.any() else None,
                               'root_mean_accuracy': float((wins[g] / n[g]).mean()) if g.any() else None}
    per_root = torch.where(n > 0, wins / n.clamp_min(1), torch.full_like(n, float('nan')))
    return out, per_root


def legality(leg, D, population='all'):
    t = D['targets']; mask = t['mask']; gold = D['legal']; typ = t['types']
    elig = t['selected_eligible']
    roots = torch.ones_like(elig) if population == 'all' else elig
    pred = (leg > 0) & mask
    g = gold & mask
    r = roots[:, None] & mask
    tp = int((pred & g & r).sum()); fp = int((pred & ~g & r).sum())
    fn = int((~pred & g & r).sum()); tn = int((~pred & ~g & mask & r).sum())
    tpr = tp / max(tp + fn, 1); tnr = tn / max(tn + fp, 1)
    prec = tp / max(tp + fp, 1)
    exact = ((pred == g) | ~mask).all(1)
    inter = (pred & g).sum(1).float(); union = (pred | g).sum(1).float()
    jac = torch.where(union > 0, inter / union.clamp_min(1), torch.ones_like(union))
    nonempty = g.any(1)
    out = {'population_roots': int(roots.sum()), 'candidates': int(r.sum()), 'gold_legal_candidates': tp + fn,
           'candidate_BA': .5 * (tpr + tnr), 'recall': tpr, 'specificity': tnr, 'precision': prec,
           'F1': (2 * prec * tpr / (prec + tpr)) if prec + tpr > 0 else 0.0,
           'exact_legal_set_recovery': float(exact[roots].float().mean()),
           'root_mean_jaccard': float(jac[roots].mean()),
           'root_mean_jaccard_nonempty_gold': float(jac[roots & nonempty].mean()) if (roots & nonempty).any() else None,
           'false_positives_per_root': float((pred & ~g).sum(1)[roots].float().mean()),
           'false_negatives_per_root': float((~pred & g).sum(1)[roots].float().mean()),
           'roots_with_gold_legal': int((roots & nonempty).sum()),
           'exact_among_roots_with_gold_legal': float(exact[roots & nonempty].float().mean()) if (roots & nonempty).any() else None,
           'bands': {}}
    count = mask.sum(1)
    for label, lo, hi in BANDS:
        sel = roots & (count >= lo) & (count <= hi)
        out['bands'][label] = {'roots': int(sel.sum()),
                               'exact_legal_set_recovery': float(exact[sel].float().mean()) if sel.any() else None}
    if population == 'eligible':
        sidx = t['selected'].clamp_min(0)
        out['selected_candidate_retention'] = float(pred.gather(1, sidx[:, None]).squeeze(1)[elig].float().mean())
        t_star = typ.gather(1, sidx[:, None]).squeeze(1)
        same = mask & (typ == t_star[:, None])
        exact_same = ((pred == g) | ~same).all(1)
        out['same_type_exact_legal_set_recovery'] = float(exact_same[elig].float().mean())
        out['same_type_candidates_per_root'] = float(same.sum(1)[elig].float().mean())
    return out, exact.float()


def per_type(raw, D):
    t = D['targets']; res = {}
    for k, name in enumerate(ACTION_TYPES):
        good = t['selected_eligible'] & (t['first_action_type'] == k)
        n = int(good.sum())
        if n == 0:
            res[name] = {'eligible_roots': 0}
            continue
        entry = {'eligible_roots': n, 'root_supported': n >= RELIABLE_ROOTS, 'descriptive_only': n < RELIABLE_ROOTS}
        for r in ('unrestricted', 'gold_type'):
            rank = raw[r]['selected_rank'][good].float(); ex = raw[r]['selected_excluded'][good]
            entry[r] = {'top1': float(raw[r]['selected_top1'][good].float().mean()),
                        'MRR': float(torch.where(ex, torch.zeros_like(rank), rank.reciprocal()).mean())}
        res[name] = entry
    return res


def evaluate(util, leg, D):
    """Everything for one arm on one split (util, leg: [R,171] CPU float tensors)."""
    rk, raw = rank_all(util, D)
    pairs, pair_root = same_type_pairs(util, D)
    leg_all, exact_all = legality(leg, D, 'all')
    leg_el, exact_el = legality(leg, D, 'eligible')
    return {'ranking': rk, 'same_type_pairs': pairs, 'legality_all_roots': leg_all, 'legality_eligible_roots': leg_el,
            'per_action_type': per_type(raw, D)}, {'raw': raw, 'vectors': per_root_vectors(raw, D),
                                                    'exact_legal_all': exact_all, 'pair_root': pair_root}


def paired_bootstrap(a, b, reps=2000, seed=20261003):
    """Paired root-resampling interval for mean(a) - mean(b) (a,b: aligned per-root vectors)."""
    a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64)
    keep = ~(np.isnan(a) | np.isnan(b)); a, b = a[keep], b[keep]
    n = len(a); rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(reps, n))
    d = a[idx].mean(1) - b[idx].mean(1)
    return {'roots': int(n), 'a_mean': float(a.mean()), 'b_mean': float(b.mean()), 'delta': float(a.mean() - b.mean()),
            'ci95': [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            'fraction_resamples_positive': float((d > 0).mean()), 'repetitions': reps, 'seed': seed}
