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

# =====================================================================================
# Phase 2 additive objective terms.
#
# Nothing above this line is modified. Phase 0 and Phase 1 losses stay frozen; these are
# new functions. The Phase 2 contract changes the TRAINING OBJECTIVE ONLY.
# =====================================================================================


def js_divergence_bernoulli(p: torch.Tensor, q: torch.Tensor, eps: float = 1e-7) -> torch.Tensor:
    """Jensen-Shannon divergence between two Bernoulli distributions.

    Used instead of latent distance so that agreement is enforced on PREDICTIONS, which have
    no incentive to shrink. Returns a per-element tensor.
    """
    p = p.clamp(eps, 1.0 - eps)
    q = q.clamp(eps, 1.0 - eps)
    m = 0.5 * (p + q)
    kl_pm = 0.5 * (p * (p / m).log() + (1.0 - p) * ((1.0 - p) / (1.0 - m)).log())
    kl_qm = 0.5 * (q * (q / m).log() + (1.0 - q) * ((1.0 - q) / (1.0 - m)).log())
    return kl_pm + kl_qm


def js_divergence_categorical(p: torch.Tensor, q: torch.Tensor, eps: float = 1e-7) -> torch.Tensor:
    """Row-wise Jensen-Shannon divergence between two categorical distributions [..., C]."""
    p = p.clamp_min(eps)
    q = q.clamp_min(eps)
    p = p / p.sum(-1, keepdim=True)
    q = q / q.sum(-1, keepdim=True)
    m = 0.5 * (p + q)
    kl_pm = 0.5 * (p * (p / m).log()).sum(-1)
    kl_qm = 0.5 * (q * (q / m).log()).sum(-1)
    return kl_pm + kl_qm


def prediction_consistency_loss(go_x, go_xt, co_x, co_xt, al_x, al_xt,
                                cand_mask, action_valid, align_ok) -> dict:
    """L_pair = L_pair,S + L_pair,E + L_pair,A on renderer pairs.

    Consistency is enforced on the predicted distributions of the SUPERVISED heads, never on
    latent distance. This is the replacement for Phase 1's raw ||s(x) - s(x-tilde)||^2.

    `align_ok` is False when exact canonical candidate identity cannot be established for the
    pair; in that case candidate and action consistency are OMITTED rather than guessed, per
    the Phase 2 contract. Global-state consistency is still well defined there because it does
    not depend on candidate correspondence.
    """
    # ---- L_pair,S : global semantic targets, single supervised channel
    js = []
    for k, lx in go_x.items():
        lt = go_xt.get(k)
        if lt is None:
            continue
        if lx.dim() == 1:
            lx = lx.unsqueeze(-1)
            lt = lt.unsqueeze(-1)
        js.append(js_divergence_bernoulli(torch.sigmoid(lx[:, 0]),
                                          torch.sigmoid(lt[:, 0])).mean())
    lps = torch.stack(js).mean() if js else torch.tensor(0.0)

    if not align_ok:
        z = torch.tensor(0.0)
        return {"S": lps, "E": z, "A": z, "omitted_E": True, "omitted_A": True}

    # ---- L_pair,E : candidate targets, over valid aligned candidates only
    per = []
    m = (cand_mask > 0)
    for k, lx in co_x.items():
        lt = co_xt.get(k)
        if lt is None or lx.dim() < 3:
            continue
        if lx.shape[-1] == 1:
            lx = lx.squeeze(-1)
            lt = lt.squeeze(-1)
        per.append(js_divergence_bernoulli(torch.sigmoid(lx[m]), torch.sigmoid(lt[m])).mean())
    lpe = torch.stack(per).mean() if per else torch.tensor(0.0)

    # ---- L_pair,A : endpoint consistency, only where the action contract is preserved
    if al_x is not None and al_xt is not None and bool(action_valid):
        p = torch.softmax(al_x, dim=-1)
        q = torch.softmax(al_xt, dim=-1)
        lpa = js_divergence_categorical(p, q).mean()
    else:
        lpa = torch.tensor(0.0)

    return {"S": lps, "E": lpe, "A": lpa, "omitted_E": False, "omitted_A": False}


def variance_floor_loss(s: torch.Tensor, sigma0: torch.Tensor) -> torch.Tensor:
    """L_var : VICReg-style explicit variance floor on the global state.

        L_var = (1/d_s) * sum_k [ max(0, 0.5*sigma_k^(0) - sigma_k^(batch)) ]^2

    sigma_k^(0) is the per-coordinate standard deviation of s from the UNTRAINED Phase 0
    graft over TRAIN. It is a lane-relative reference: it never compares this lane's scale to
    the sibling lane's, and it does not require any coordinate to encode a named concept.

    Only a floor is applied. There is deliberately no covariance penalty in this phase.
    """
    sigma = s.std(dim=0, unbiased=False)
    short = torch.clamp(0.5 * sigma0 - sigma, min=0.0)
    return (short ** 2).mean()


@dataclass
class Phase2Weights:
    """Frozen Phase 2 weights. L_R is REMOVED; the raw latent invariance term is gone."""
    lambda_S: float = 1.0
    lambda_E: float = 1.0
    lambda_A: float = 0.5
    lambda_CF: float = 0.5
    lambda_pair: float = 0.25
    lambda_var: float = 0.05
    var_floor_ratio: float = 0.5

    def terms(self) -> dict:
        return {"S": self.lambda_S, "E": self.lambda_E, "A": self.lambda_A,
                "CF": self.lambda_CF, "pair": self.lambda_pair, "var": self.lambda_var}

    def validate(self) -> None:
        forbidden = {"R", "L_R", "latent_invariance", "align", "distill", "s_c", "s_b",
                     "e_c", "e_b", "cross_agent"}
        leaked = forbidden & set(self.terms())
        if leaked:
            raise AssertionError(f"Phase 2 objective must not contain {sorted(leaked)}")


def phase2_total_loss(parts: dict, w: Phase2Weights) -> tuple[torch.Tensor, dict]:
    """L^(2) = L_S + L_E + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var.

    `parts` keys: S, E, A, CF, pair_S, pair_E, pair_A, var. L_CF stays masked when canonical
    support-changing supervision is unavailable. No label is ever invented to wake it.
    """
    w.validate()
    lam = w.terms()
    weighted = {"S": lam["S"] * parts["S"], "E": lam["E"] * parts["E"],
                "A": lam["A"] * parts["A"], "CF": lam["CF"] * parts["CF"],
                "pair": lam["pair"] * (parts["pair_S"] + parts["pair_E"] + parts["pair_A"]),
                "var": lam["var"] * parts["var"]}
    total = None
    detail = {}
    for k, v in weighted.items():
        if v is None:
            continue
        term = v if torch.is_tensor(v) else torch.tensor(float(v))
        total = term if total is None else total + term
        detail[k] = float(term.detach())
    if total is None:
        total = torch.tensor(0.0)
    return total, detail


def phase2_objective_descriptor(w: Phase2Weights) -> dict:
    return {
        "abi": "phase2-semantic-interface/objective-v0.1",
        "L": "L_S + L_E + 0.5*L_A + 0.5*L_CF + 0.25*L_pair + 0.05*L_var",
        "weights": w.terms(),
        "var_floor_ratio": w.var_floor_ratio,
        "invariance_enforced_on": "predicted distributions (Jensen-Shannon), not latent distance",
        "raw_latent_L_R": "REMOVED in Phase 2",
        "covariance_penalty": "deliberately absent in this phase",
        "anti_collapse_design": "VICReg-inspired explicit variance floor only; the full "
                                "method is not imported",
        "sigma0_reference": "per-coordinate std of s from the UNTRAINED Phase 0 graft over TRAIN",
        "candidate_alignment": "exact canonical alignment required; on failure E and A "
                               "consistency are omitted, never guessed",
        "cf_state": "dormant if canonical support-changing supervision is unavailable",
        "changed_vs_phase1": ["objective only"],
        "unchanged_vs_phase1": ["substrate", "extraction surfaces", "graft architecture",
                                "latent dimensions", "target ontology", "canonical splits",
                                "availability masks"],
    }

# =====================================================================================
# Phase 3 additive objective terms: supervision geometry.
#
# Nothing above this line is modified. Phase 0/1/2 losses stay frozen.
#
# Two changes, both to supervision geometry rather than to architecture:
#   (1) unique-SOURCE weighting, so aliases and proxies cannot buy extra weight by having
#       their own ontology head;
#   (2) prospectively fixed balanced BCE using TRAIN prevalence only.
# =====================================================================================


def balanced_bce(logits: torch.Tensor, y: torch.Tensor, pi: float,
                 mask: torch.Tensor | None = None) -> torch.Tensor:
    """L^bal = -1/2 [ (y/pi) log p + ((1-y)/(1-pi)) log(1-p) ], pi from TRAIN only.

    Written in the numerically stable softplus form. No DEV-derived weights, no focal
    tuning, no threshold optimisation, no prevalence clipping: pi is bounded away from 0 by
    the TRAIN panel itself (smallest observed prevalence is 0.079).
    """
    pi = float(min(max(pi, 1e-6), 1.0 - 1e-6))
    z = logits
    t = y
    if mask is None:
        l = 0.5 * ((t / pi) * torch.nn.functional.softplus(-z)
                   + ((1.0 - t) / (1.0 - pi)) * torch.nn.functional.softplus(z))
        return l.mean()
    m = mask.float()
    l = 0.5 * ((t / pi) * torch.nn.functional.softplus(-z)
               + ((1.0 - t) / (1.0 - pi)) * torch.nn.functional.softplus(z))
    return (l * m).sum() / m.sum().clamp(min=1.0)


def source_group_loss(head_terms: list, pi: float) -> torch.Tensor:
    """One source unit: L_g = (1/|H_g|) sum_h L_h.

    `head_terms` are the already-computed per-head balanced losses for the heads that read this
    single canonical source. Averaging over H_g is what stops an alias from counting twice.
    """
    if not head_terms:
        return torch.tensor(0.0)
    return torch.stack([t for t in head_terms]).mean()


def family_balanced_loss(group_losses: list) -> torch.Tensor:
    """L_S^(3) or L_E^(3) = (1/|G|) sum_g L_g. Each family is one conceptual block."""
    if not group_losses:
        return torch.tensor(0.0)
    return torch.stack(list(group_losses)).mean()


@dataclass
class Phase3Weights:
    lambda_S: float = 1.0
    lambda_E: float = 1.0
    lambda_A: float = 0.5
    lambda_CF: float = 0.5
    lambda_pair: float = 0.25
    lambda_var: float = 0.05

    def terms(self) -> dict:
        return {"S": self.lambda_S, "E": self.lambda_E, "A": self.lambda_A,
                "CF": self.lambda_CF, "pair": self.lambda_pair, "var": self.lambda_var}

    def validate(self) -> None:
        forbidden = {"R", "L_R", "latent_invariance", "align", "distill", "s_c", "s_b",
                     "e_c", "e_b", "cross_agent"}
        leaked = forbidden & set(self.terms())
        if leaked:
            raise AssertionError(f"raw latent L_R is RETIRED; found {sorted(leaked)}")


def phase3_total_loss(parts: dict, w: Phase3Weights) -> tuple[torch.Tensor, dict]:
    """L^(3) = L_S^(3) + L_E^(3) + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var.

    `parts`: S, E, A, CF, pair_S, pair_E, pair_A, var. L_var is UNCHANGED from Phase 2 even
    though its measured contribution is small: removing it would be a second intervention.
    """
    w.validate()
    lam = w.terms()
    weighted = {
        "S": lam["S"] * parts["S"],
        "E": lam["E"] * parts["E"],
        "A": lam["A"] * parts["A"],
        "CF": lam["CF"] * parts["CF"],
        "pair": lam["pair"] * (parts["pair_S"] + parts["pair_E"] + parts["pair_A"]),
        "var": lam["var"] * parts["var"],
    }
    total, detail = None, {}
    for k, v in weighted.items():
        if v is None:
            continue
        term = v if torch.is_tensor(v) else torch.tensor(float(v))
        total = term if total is None else total + term
        detail[k] = float(term.detach())
    if total is None:
        total = torch.tensor(0.0)
    return total, detail


def j_select(J_S: torch.Tensor | float, J_E: torch.Tensor | float):
    """J_select = 0.5 J_S + 0.5 J_E over UNIQUE source groups.

    Replaces the Phase 1/2 prior-dominated BCE rule. Action accuracy and renderer agreement are
    deliberately NOT part of this criterion.
    """
    return 0.5 * J_S + 0.5 * J_E


def phase3_objective_descriptor(w: Phase3Weights, groups: dict,
                                prevalence: dict) -> dict:
    return {
        "abi": "phase3-semantic-interface/objective-v0.1",
        "L": "L_S^(3) + L_E^(3) + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var",
        "weights": w.terms(),
        "raw_latent_L_R": "RETIRED for this lineage",
        "unique_source_weighting": {
            "rule": "L_g = (1/|H_g|) sum_h L_h, so a source contributes one unit regardless of "
                    "how many alias heads read it",
            "groups": groups,
        },
        "balanced_bce": {
            "formula": "-0.5 * [ (y/pi) log p + ((1-y)/(1-pi)) log(1-p) ]",
            "pi_source": "TRAIN ONLY",
            "train_prevalence": prevalence,
            "dev_derived_weights": False, "focal_tuning": False,
            "threshold_tuning": False, "prevalence_clipping": False,
        },
        "family_balanced_aggregation": "L_S^(3) = mean over independent global source groups; "
                                       "L_E^(3) = mean over independent candidate source groups",
        "selection": "J_select = 0.5 J_S + 0.5 J_E balanced DEV BCE over unique source groups; "
                     "lowest wins; action accuracy and renderer agreement excluded",
        "L_var": "unchanged from Phase 2 despite small measured contribution, to avoid a "
                 "second intervention",
        "cf_state": "dormant unless an already-authorised canonical source exists",
        "changed_vs_phase2": ["unique-source weighting", "balanced BCE", "selection rule"],
        "unchanged_vs_phase2": ["substrate", "extraction surfaces", "graft architecture",
                                "latent dimensions", "target ontology", "canonical splits",
                                "availability masks", "candidate universe m_cap=28",
                                "L_pair", "L_var", "L_CF dormancy"],
    }