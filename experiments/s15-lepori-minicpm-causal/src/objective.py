"""Training objective for the Lepori causal lane. INHERITED, not redesigned.

This is the causal lane's copy of the contract the encoder lane paid for. The raw latent
invariance term is absent and is forbidden, cross-fabric alignment is forbidden and asserted,
and weighting runs over independent canonical sources rather than head count.

  L = L_S^(3) + L_E^(3) + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var

  L_S^(3)  mean over 4 independent global source groups
  L_E^(3)  mean over 2 independent candidate source groups
  L_g      = (1/|H_g|) sum_h balanced_bce_h        one source unit regardless of alias count
  balanced BCE, pi from TRAIN only
  L_pair   Jensen-Shannon on PREDICTED distributions across renderer pairs, never latent
           distance. Candidate alignment is verified exactly; on failure E and A are omitted
           rather than guessed.
  L_var    explicit variance floor, VICReg-inspired, lane-relative sigma0 from the untrained
           graft over TRAIN. No covariance penalty.
  L_CF     dormant: candidate_supported, candidate_has_counterevidence and
           candidate_requires_missing_information have no admissible canonical source. No label
           is invented to wake it.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F


def assert_no_alignment_term(term_names) -> None:
    forbidden = {"align", "alignment", "distill", "s_c", "s_b", "e_c", "e_b", "cross_agent",
                 "match_latent", "latent_invariance", "R", "L_R"}
    bad = {t for t in term_names if any(f in str(t) for f in forbidden)}
    if bad:
        raise AssertionError(
            f"forbidden term(s) {sorted(bad)}: the raw latent invariance term is RETIRED for "
            f"this lineage and cross-agent alignment is forbidden")


def balanced_bce(logits: torch.Tensor, y: torch.Tensor, pi: float,
                 mask: torch.Tensor | None = None) -> torch.Tensor:
    """-0.5 [ (y/pi) log p + ((1-y)/(1-pi)) log(1-p) ], pi from TRAIN only, softplus form."""
    pi = float(min(max(pi, 1e-6), 1.0 - 1e-6))
    l = 0.5 * ((y / pi) * F.softplus(-logits) + ((1.0 - y) / (1.0 - pi)) * F.softplus(logits))
    if mask is None:
        return l.mean()
    m = mask.float()
    return (l * m).sum() / m.sum().clamp(min=1.0)


def source_group_loss(head_terms) -> torch.Tensor:
    """One source unit: L_g = (1/|H_g|) sum_h L_h. Stops an alias buying extra weight."""
    head_terms = [t for t in head_terms if t is not None]
    if not head_terms:
        return torch.tensor(0.0)
    return torch.stack(head_terms).mean()


def family_balanced_loss(group_losses) -> torch.Tensor:
    if not group_losses:
        return torch.tensor(0.0)
    return torch.stack(list(group_losses)).mean()


def js_bernoulli(p, q, eps=1e-7):
    p = p.clamp(eps, 1 - eps); q = q.clamp(eps, 1 - eps)
    m = 0.5 * (p + q)
    return (0.5 * (p * (p / m).log() + (1 - p) * ((1 - p) / (1 - m)).log())
            + 0.5 * (q * (q / m).log() + (1 - q) * ((1 - q) / (1 - m)).log()))


def js_categorical(p, q, eps=1e-7):
    p = p.clamp_min(eps); q = q.clamp_min(eps)
    p = p / p.sum(-1, keepdim=True); q = q / q.sum(-1, keepdim=True)
    m = 0.5 * (p + q)
    return (0.5 * (p * (p / m).log()).sum(-1) + 0.5 * (q * (q / m).log()).sum(-1))


def prediction_consistency_loss(go_x, go_xt, co_x, co_xt, al_x, al_xt, cand_mask,
                                action_valid, align_ok) -> dict:
    """Renderer consistency enforced on PREDICTIONS, never on latent distance.

    This replaces the encoder lane's raw ||s(x) - s(x-tilde)||^2, whose global minimum is
    constant s. Prediction distributions have no incentive to shrink.
    """
    js = []
    for k, lx in go_x.items():
        lt = go_xt.get(k)
        if lt is None:
            continue
        js.append(js_bernoulli(torch.sigmoid(lx[:, 0]), torch.sigmoid(lt[:, 0])).mean())
    lps = torch.stack(js).mean() if js else torch.tensor(0.0)
    if not align_ok:
        z = torch.tensor(0.0)
        return {"S": lps, "E": z, "A": z, "omitted_E": True, "omitted_A": True}
    per = []
    m = cand_mask > 0
    for k, lx in co_x.items():
        lt = co_xt.get(k)
        if lt is None:
            continue
        per.append(js_bernoulli(torch.sigmoid(lx[m]), torch.sigmoid(lt[m])).mean())
    lpe = torch.stack(per).mean() if per else torch.tensor(0.0)
    if al_x is not None and al_xt is not None and bool(action_valid):
        lpa = js_categorical(torch.softmax(al_x, -1), torch.softmax(al_xt, -1)).mean()
    else:
        lpa = torch.tensor(0.0)
    return {"S": lps, "E": lpe, "A": lpa, "omitted_E": False, "omitted_A": False}


def action_loss(logits: torch.Tensor, a_star: torch.Tensor) -> torch.Tensor:
    """Masked CE over the candidate universe. Abstention worlds contribute nothing."""
    if logits is None:
        return torch.tensor(0.0)
    valid = a_star >= 0
    if not bool(valid.any()):
        return torch.tensor(0.0)
    idx = valid.nonzero().flatten()
    tgt = a_star[idx].clamp(min=0, max=logits.shape[-1] - 1)
    return F.cross_entropy(logits[idx], tgt)


def variance_floor_loss(s: torch.Tensor, sigma0: torch.Tensor) -> torch.Tensor:
    """L_var = mean_k [ max(0, 0.5 sigma0_k - sigma_k) ]^2. Floor only; no covariance penalty."""
    sigma = s.std(dim=0, unbiased=False)
    return (torch.clamp(0.5 * sigma0 - sigma, min=0.0) ** 2).mean()


@dataclass
class LossWeights:
    lambda_S: float = 1.0
    lambda_E: float = 1.0
    lambda_A: float = 0.5
    lambda_CF: float = 0.5
    lambda_pair: float = 0.25
    lambda_var: float = 0.05

    def terms(self):
        return {"S": self.lambda_S, "E": self.lambda_E, "A": self.lambda_A,
                "CF": self.lambda_CF, "pair": self.lambda_pair, "var": self.lambda_var}

    def validate(self):
        assert_no_alignment_term(list(self.terms()))


def total_loss(parts: dict, w: LossWeights):
    w.validate()
    lam = w.terms()
    weighted = {"S": lam["S"] * parts["S"], "E": lam["E"] * parts["E"],
                "A": lam["A"] * parts["A"], "CF": lam["CF"] * parts["CF"],
                "pair": lam["pair"] * (parts["pair_S"] + parts["pair_E"] + parts["pair_A"]),
                "var": lam["var"] * parts["var"]}
    total, detail = None, {}
    for k, v in weighted.items():
        if v is None:
            continue
        term = v if torch.is_tensor(v) else torch.tensor(float(v))
        total = term if total is None else total + term
        detail[k] = float(term.detach())
    return (total if total is not None else torch.tensor(0.0)), detail


def j_select(J_S, J_E):
    """Checkpoint selection over UNIQUE source groups. No action, no renderer, no prior pull."""
    return 0.5 * J_S + 0.5 * J_E


def objective_descriptor(w: LossWeights) -> dict:
    return {
        "abi": "s15-lepori-minicpm/objective-v0.1",
        "L": "L_S^(3) + L_E^(3) + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var",
        "weights": w.terms(),
        "inherited_from": "encoder lane, phases 2-4A",
        "raw_latent_L_R": "ABSENT and forbidden",
        "invariance_enforced_on": "predicted distributions (Jensen-Shannon)",
        "unique_source_weighting": "L_g = (1/|H_g|) sum_h L_h over 6 independent sources",
        "balanced_bce": "pi from TRAIN only; no DEV weights, no focal tuning, no threshold "
                        "tuning, no prevalence clipping",
        "L_var": "explicit variance floor, lane-relative sigma0 from the untrained graft; no "
                 "covariance penalty",
        "L_CF": "dormant; no candidate-support canonical source exists and none is invented",
        "selection": "J_select = 0.5 J_S + 0.5 J_E over unique source groups",
        "cross_agent_alignment": "FORBIDDEN and asserted by assert_no_alignment_term",
    }
