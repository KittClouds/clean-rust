"""Shared Phase 0 supervision mathematics.

Both fabrics (causal and bidirectional) use THESE loss semantics. Only the frozen
representation H and the graft geometry differ.

    L = lambda_S * L_S + lambda_E * L_E + lambda_A * L_A + lambda_CF * L_CF + lambda_R * L_R

    L_S   = sum_k  l(s_hat_k,  s*_k)                        semantic, on s
    L_E   = sum_j sum_k l(e_hat_jk, e*_jk)                  candidate epistemic, on e_j
    L_A   = CE(a_hat, a*)                                  action endpoint, NOT the definition of e
    L_CF  = max(0, m - y * [ r(x+, a_j) - r(x-, a_j) ])    truth-changing contrast
    L_R   = ||s(x) - s(x~)||^2 + (1/m) sum_j ||e_j(x) - e_j(x~)||^2

The intended asymmetry:

    semantic change  -> state changes      (L_S, L_E, L_CF)
    renderer change  -> state ~stable      (L_R)

PHASE 0 DISCIPLINE — asserted here in code, not only in prose:

    There is NO cross-agent alignment term. No s_c ~= s_b, no e_j^c ~= e_j^b.
    The two fabrics share this loss and this typed output contract D(.) -> Y.
    Their internal geometry is unconstrained and may differ arbitrarily.
    `assert_no_alignment_term()` fails loudly if an alignment loss is ever added.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F

OBJECTIVE_ABI = "phase0-semantic-interface/objective-v0.1"

# Any of these substrings in a loss-term name is a forbidden cross-agent alignment term.
FORBIDDEN_ALIGNMENT_TOKENS = ("align", "distill", "s_c", "s_b", "e_c", "e_b",
                              "cross_agent", "crossagent", "match_c", "match_b")


def assert_no_alignment_term(term_names) -> None:
    bad = [t for t in term_names
           if any(tok in t.lower() for tok in FORBIDDEN_ALIGNMENT_TOKENS)]
    if bad:
        raise RuntimeError(
            "Phase 0 forbids cross-agent coordinate alignment; offending terms: "
            + ", ".join(bad))


@dataclass
class LossWeights:
    lambda_S: float = 1.0
    lambda_E: float = 1.0
    lambda_A: float = 0.5
    lambda_CF: float = 0.5
    lambda_R: float = 0.25
    margin_m: float = 0.2
    cf_label_y: float = 1.0

    def terms(self) -> dict:
        assert_no_alignment_term(["S", "E", "A", "CF", "R"])
        return {"S": self.lambda_S, "E": self.lambda_E, "A": self.lambda_A,
                "CF": self.lambda_CF, "R": self.lambda_R}


# --------------------------------------------------------------------------- pieces

def semantic_loss(s_hat, s_star, mask=None):
    """L_S. s_hat [B, d_s]; s_star [B, d_s] with NaN for unsupervised channels."""
    t = torch.nan_to_num(s_star, nan=0.0)
    if mask is None:
        mask = (~torch.isnan(s_star)).float()
    l = F.binary_cross_entropy_with_logits(s_hat, t, reduction="none")
    denom = mask.sum().clamp(min=1.0)
    return (l * mask).sum() / denom


def epistemic_loss(e_hat, e_star, cand_mask):
    """L_E. e_hat [B, m, d_e]; e_star [B, m] or [B, m, d_e] NaN where unsupervised;
    cand_mask [B, m]."""
    if e_star.dim() == 2:
        e_star = e_star.unsqueeze(-1).expand_as(e_hat)
    mask = cand_mask.unsqueeze(-1).float().expand_as(e_hat) * (~torch.isnan(e_star)).float()
    l = F.binary_cross_entropy_with_logits(e_hat, torch.nan_to_num(e_star, nan=0.0),
                                            reduction="none")
    return (l * mask).sum() / mask.sum().clamp(min=1.0)


def action_loss(logits, a_star):
    """L_A. logits [B, m, m]: for each row, a distribution over the enumerated candidate set.
    a_star [B]: index of the canonical action, -1 where no action endpoint is defined
    (abstention worlds). Those rows are excluded, not defaulted."""
    if logits.dim() == 3:
        B = logits.shape[0]
        valid = a_star >= 0
        if valid.sum() == 0:
            return logits.sum() * 0.0
        sel = logits[valid].reshape(int(valid.sum()), -1)
        return F.cross_entropy(sel, a_star[valid], reduction="mean")
    valid = a_star >= 0
    if valid.sum() == 0:
        return logits.sum() * 0.0
    return F.cross_entropy(logits[valid], a_star[valid], reduction="mean")


def truth_contrast_loss(r_pos, r_neg, y, margin=0.2):
    """L_CF. Hinge on the ranking of candidate score r(x, a_j) across a truth-changing pair.

    r_pos / r_neg : [P] score of the SAME candidate index j under x+ and x-
    y             : [P] 1.0 if the change should RAISE support, 0.0 if it should LOWER it
    """
    if r_pos.numel() == 0:
        return r_pos.sum() * 0.0
    return F.relu(margin - y * (r_pos - r_neg)).mean()


def renderer_invariance_loss(s_x, s_xt, e_x, e_xt, cand_mask):
    """L_R. Meaning-preserving renderer pair. Both members share the latent world."""
    ls = (s_x - s_xt).pow(2).sum()
    valid = cand_mask.unsqueeze(-1).float()
    le = ((e_x - e_xt).pow(2).sum(-1) * valid.squeeze(-1)).sum()
    m = valid.sum().clamp(min=1.0)
    return ls + le / m


def total_loss(parts: dict, w: LossWeights) -> tuple[torch.Tensor, dict]:
    """Weighted sum. `parts` keys must be a subset of {S, E, A, CF, R}."""
    assert_no_alignment_term(list(parts.keys()))
    lam = w.terms()
    total = None
    detail = {}
    for k, v in parts.items():
        if v is None or k not in lam or lam[k] == 0.0:
            continue
        term = lam[k] * v
        total = term if total is None else total + term
        detail[k] = float(v.detach()) if torch.is_tensor(v) else float(v)
    if total is None:
        total = sum(p.sum() for p in parts.values() if p is not None) * 0.0
    detail["total"] = float(total.detach())
    return total, detail


def objective_descriptor(w: LossWeights) -> dict:
    return {
        "abi": OBJECTIVE_ABI,
        "loss": "L = lambda_S*L_S + lambda_E*L_E + lambda_A*L_A + lambda_CF*L_CF + lambda_R*L_R",
        "terms": {
            "L_S": "sum_k l(s_hat_k, s*_k) — semantic loss on the global state",
            "L_E": "sum_j sum_k l(e_hat_jk, e*_jk) — candidate epistemic loss",
            "L_A": "CE(a_hat, a*) — action ENDPOINT, explicitly not the definition of e",
            "L_CF": "max(0, m - y [r(x+,a_j) - r(x-,a_j)]) — truth-changing contrast, hinge",
            "L_R": "||s(x)-s(x~)||^2 + (1/m) sum_j ||e_j(x)-e_j(x~)||^2 — renderer invariance",
        },
        "weights": w.terms(), "margin_m": w.margin_m,
        "intent": {
            "semantic_change": "state changes (L_S, L_E, L_CF)",
            "renderer_change": "state approximately stable (L_R)",
        },
        "phase0_discipline": {
            "cross_agent_alignment": "FORBIDDEN and absent",
            "shared": "loss semantics and typed output contract D(.) -> Y",
            "not_shared": "internal coordinates; s_c and s_b may differ arbitrarily",
            "enforcement": "assert_no_alignment_term() raises if an alignment term is added",
        },
    }
