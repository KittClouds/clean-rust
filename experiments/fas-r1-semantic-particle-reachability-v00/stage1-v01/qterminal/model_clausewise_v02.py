"""Clause-local terminal selector with conjunction-aware assignment scoring."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from model import H_FIELDS


def conjunction_log_odds(clause_logits: torch.Tensor, clause_mask: torch.Tensor) -> torch.Tensor:
    """Compose local satisfaction probabilities as one all-clauses event."""
    mask = clause_mask.to(dtype=clause_logits.dtype)
    log_valid = (F.logsigmoid(clause_logits) * mask).sum(dim=1)
    log_valid = torch.minimum(log_valid, torch.full_like(log_valid, -1e-6))
    log_invalid = torch.log(-torch.expm1(log_valid))
    return log_valid - log_invalid


class ClausewiseQTerminal(nn.Module):
    """Score each public constraint against an assignment, then compose them.

    Inference inputs are the same public surface as QTerminal: frozen clause
    embeddings, global embedding, public mention incidence, and assignment.
    The private clause targets used in training are not model inputs.
    """

    def __init__(self, hidden_dim: int = 2048, hidden_size: int = 128, max_roles: int = 6):
        super().__init__()
        if hidden_dim < 1 or hidden_size < 8 or max_roles < 1:
            raise ValueError("model dimensions must be positive and hidden_size at least 8")
        self.hidden_dim = hidden_dim
        self.hidden_size = hidden_size
        self.max_roles = max_roles
        self.clause_projection = nn.Sequential(
            nn.Linear(hidden_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
        )
        self.global_projection = nn.Sequential(
            nn.Linear(hidden_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
        )
        input_size = 2 * hidden_size + 2 * max_roles + 2
        self.clause_head = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.GELU(),
            nn.Linear(hidden_size // 2, 1),
        )

    def forward(self, H: dict[str, torch.Tensor], h_global: torch.Tensor, a: torch.Tensor) -> torch.Tensor:
        """Return the terminal validity log-odds from all per-clause scores."""
        terminal, _ = self.forward_with_clause_logits(H, h_global, a)
        return terminal

    def forward_with_clause_logits(
        self, H: dict[str, torch.Tensor], h_global: torch.Tensor, a: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if set(H) != H_FIELDS:
            missing = sorted(H_FIELDS - set(H))
            extra = sorted(set(H) - H_FIELDS)
            raise ValueError(f"H fields mismatch; missing={missing}, extra={extra}")
        if H["constraint_embeddings"].ndim != 3 or h_global.ndim != 2 or a.ndim != 3:
            raise ValueError("expected H clauses [B,M,D], h_global [B,D], a [B,N,K]")
        batch, clauses, dim = H["constraint_embeddings"].shape
        if dim != self.hidden_dim or h_global.shape != (batch, self.hidden_dim):
            raise ValueError("semantic feature dimension does not match frozen model input")
        if a.shape[0] != batch or a.shape[2] != self.max_roles:
            raise ValueError("assignment role dimension does not match model support")
        if H["constraint_mask"].shape != (batch, clauses):
            raise ValueError("constraint mask shape mismatch")
        if H["entity_incidence"].shape != (batch, clauses, a.shape[1]):
            raise ValueError("entity incidence must align with assignment entities")
        if H["role_incidence"].shape != (batch, clauses, self.max_roles):
            raise ValueError("role incidence must align with role support")
        if H["entity_mask"].shape != (batch, a.shape[1]):
            raise ValueError("entity mask must align with assignment entities")
        if H["role_mask"].shape != (batch, self.max_roles):
            raise ValueError("role mask must align with role support")

        constraint_mask = H["constraint_mask"].bool()
        entity_mask = H["entity_mask"].bool()
        role_mask = H["role_mask"].bool()
        assignment = a.to(dtype=h_global.dtype) * entity_mask.unsqueeze(-1)
        assignment = assignment * role_mask.unsqueeze(1)
        incidence = H["entity_incidence"].to(dtype=h_global.dtype)
        role_incidence = H["role_incidence"].to(dtype=h_global.dtype)
        assigned_roles = torch.bmm(incidence, assignment)
        entity_count = incidence.sum(dim=-1, keepdim=True).clamp_min(1.0)
        role_fraction = assigned_roles / entity_count
        role_count = role_incidence.sum(dim=-1, keepdim=True)
        role_agreement = (assigned_roles * role_incidence).sum(dim=-1, keepdim=True)
        role_agreement = role_agreement / (entity_count * role_count.clamp_min(1.0))
        mention_count = (incidence.sum(dim=-1, keepdim=True) > 0).to(h_global.dtype)

        clause_semantics = self.clause_projection(H["constraint_embeddings"])
        global_semantics = self.global_projection(h_global).unsqueeze(1).expand(-1, clauses, -1)
        clause_features = torch.cat(
            (clause_semantics, global_semantics, role_fraction, role_incidence, role_agreement, mention_count),
            dim=-1,
        )
        clause_logits = self.clause_head(clause_features).squeeze(-1)
        clause_logits = clause_logits.masked_fill(~constraint_mask, 0.0)

        # P(all clauses satisfied) is the product of clause probabilities.
        # Sum log probabilities to preserve the conjunction without averaging
        # away one violated clause among many satisfied ones.
        terminal_log_odds = conjunction_log_odds(clause_logits, constraint_mask)
        return terminal_log_odds, clause_logits
