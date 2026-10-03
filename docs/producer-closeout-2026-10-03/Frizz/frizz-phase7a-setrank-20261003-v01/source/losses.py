"""Phase 7A objective: deliberately simple, identical for both arms.

    L = 1.00 * L_select  +  0.50 * L_same_type  +  0.25 * L_legality

  L_select     full-set softmax CE of the logged selected candidate over ALL valid candidates (endpoint-eligible roots)
  L_same_type  softmax CE of the selected candidate over the candidates sharing its action type (eligible roots with
               at least one same-type alternative)
  L_legality   independent legality head, root-normalised balanced BCE: each root's positives and negatives carry
               equal total weight (0.5/0.5; a one-class root carries its whole weight on that class), and every root
               contributes equally regardless of candidate count.

Gold legality never masks the utility softmax. Padding contributes to no loss. Per-term means are over the roots
that actually have that target in the batch; a term with no such root contributes exactly 0.
"""
import torch
import torch.nn.functional as F

W_SELECT, W_SAME, W_LEGAL = 1.0, 0.5, 0.25
FILL = -1e4          # finite (not -inf) so masked rows cannot create NaN gradients


def _masked_lse(u, m):
    return torch.logsumexp(u.masked_fill(~m, FILL), 1)


def candidate_losses(util, leg, lab):
    mask, typ, sel, elig, legal = lab['mask'], lab['type'], lab['sel'], lab['eligible'], lab['legal']
    s_star = (util * sel).sum(1)
    ce = _masked_lse(util, mask) - s_star
    n_e = elig.sum().clamp_min(1)
    l_sel = (ce * elig).sum() / n_e

    t_star = (typ * sel).sum(1)
    same = mask & (typ == t_star[:, None]) & elig[:, None]
    ok = elig & (same.sum(1) > 1)
    ce_same = _masked_lse(util, same) - s_star
    l_same = (ce_same * ok).sum() / ok.sum().clamp_min(1)

    bce = F.binary_cross_entropy_with_logits(leg, legal.float(), reduction='none')
    pos = legal & mask
    neg = ~legal & mask
    npos, nneg = pos.sum(1).float(), neg.sum(1).float()
    wpos = torch.where(npos > 0, torch.where(nneg > 0, 0.5 / npos.clamp_min(1), 1.0 / npos.clamp_min(1)), torch.zeros_like(npos))
    wneg = torch.where(nneg > 0, torch.where(npos > 0, 0.5 / nneg.clamp_min(1), 1.0 / nneg.clamp_min(1)), torch.zeros_like(nneg))
    l_root = (bce * pos * wpos[:, None]).sum(1) + (bce * neg * wneg[:, None]).sum(1)
    l_leg = l_root.mean()

    total = W_SELECT * l_sel + W_SAME * l_same + W_LEGAL * l_leg
    return total, {'select': l_sel.detach(), 'same_type': l_same.detach(), 'legality': l_leg.detach(),
                   'eligible_roots': int(elig.sum()), 'same_type_roots': int(ok.sum())}
