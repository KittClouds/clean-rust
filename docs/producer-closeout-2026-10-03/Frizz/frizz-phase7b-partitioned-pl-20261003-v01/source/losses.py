"""The three matched training objectives. Identical supervision QUANTITY; only the likelihood geometry differs.

All arms: L = 1.0 * L_full + 0.5 * L_same_type, root-mean (every training root is an endpoint-eligible EXECUTE root).

  ce              L_full = CE of the selected candidate over all valid candidates
                  L_same = CE of the selected candidate over the candidates sharing its action type
  vanilla_pl      L_full = ListMLE NLL of a random linear extension of  {selected} > {other legal} > {illegal}  (fresh draw per call)
                  L_same = the same inside the selected candidate's action type
  vanilla_pl_truncated (SUPPLEMENTARY reference) ListMLE on a random linear extension kept only through the legal candidates
                  (selected, then other legal in random order); the illegal tail stays an unordered remainder
  partitioned_pl  L_full = exact grouped-PL NLL of  P1={selected} > P2={other legal} > P3={illegal}  (internal orders marginalised)
                  L_same = the same inside the selected candidate's action type (illegal/legal flags of same-type candidates)

Gold legality is used ONLY to build the TRAIN partitions of the vanilla / partitioned arms (and never at inference).
Selected and optimal coincide on this population and form ONE top partition (never double-counted). The same-type term
averages over roots whose type contains at least one other candidate (identical denominator for every arm). No legality head.
"""
import torch

import pl

W_FULL, W_SAME = 1.0, 0.5


def partition_groups(valid, legal, sel):
    """0 = selected, 1 = other legal, 2 = illegal, -1 = outside the universe."""
    g = torch.full(valid.shape, -1, dtype=torch.long, device=valid.device)
    g = torch.where(valid & ~legal, torch.full_like(g, 2), g)
    g = torch.where(valid & legal, torch.full_like(g, 1), g)
    return torch.where(valid & sel, torch.zeros_like(g), g)


def _nll(arm, util, valid, legal, sel, gen):
    if arm == 'ce':
        return pl.ce_nll(util, valid, sel)
    g = partition_groups(valid, legal, sel)
    if arm == 'partitioned_pl':
        return pl.grouped_pl_nll(util, g)
    if arm == 'vanilla_pl':
        return pl.listmle_random_extension_nll(util, g, gen)
    if arm == 'vanilla_pl_truncated':                 # supplementary reference, not part of the survival rule
        return pl.listmle_random_extension_nll(util, g, gen, truncate_after=1)
    raise ValueError(arm)


def arm_loss(arm, util, lab, gen=None):
    mask, typ, sel, legal = lab['mask'], lab['type'], lab['sel'], lab['legal']
    full = _nll(arm, util, mask, legal, sel, gen)
    t_star = (typ * sel).sum(1)
    same_valid = mask & (typ == t_star[:, None])
    has_same = same_valid.sum(1) > 1
    same = _nll(arm, util, same_valid, legal, sel, gen)
    l_full = full.mean()
    l_same = (same * has_same).sum() / has_same.sum().clamp_min(1)
    total = W_FULL * l_full + W_SAME * l_same
    with torch.no_grad():                                         # common-currency monitor: selected-CE of THIS arm's scores
        ce_monitor = pl.ce_nll(util, mask, sel).mean()
    return total, {'full': l_full.detach(), 'same_type': l_same.detach(), 'selected_ce_monitor': ce_monitor,
                   'same_type_roots': int(has_same.sum())}
