"""Compact shared Q_terminal classifier with the frozen (H, h_global, a) API."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


H_FIELDS = {
    "constraint_embeddings",
    "constraint_mask",
    "entity_incidence",
    "role_incidence",
    "entity_mask",
    "role_mask",
}


class QTerminal(nn.Module):
    """Predict assignment validity using semantic features and assignment only.

    Public input signature is deliberately only ``(H, h_global, a)``. ``H``
    contains constraint vectors, masks, and public entity/role incidence.
    ``a`` is one-hot over roles, with all-zero rows on entity padding.
    """

    def __init__(self, hidden_dim: int = 2048, hidden_size: int = 128, max_roles: int = 6):
        super().__init__()
        if hidden_dim < 1 or hidden_size < 8 or max_roles < 1:
            raise ValueError("model dimensions must be positive and hidden_size at least 8")
        self.hidden_dim = hidden_dim
        self.hidden_size = hidden_size
        self.max_roles = max_roles

        self.constraint_projection = nn.Sequential(
            nn.Linear(hidden_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
        )
        self.constraint_fusion = nn.Sequential(
            nn.Linear(hidden_size + 2 * max_roles + 1, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Linear(hidden_size, hidden_size),
            nn.GELU(),
        )
        self.constraint_attention = nn.Linear(hidden_size, 1)
        self.global_projection = nn.Sequential(
            nn.Linear(hidden_dim, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
        )
        self.output = nn.Sequential(
            nn.Linear(2 * hidden_size + max_roles, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, H: dict[str, torch.Tensor], h_global: torch.Tensor, a: torch.Tensor) -> torch.Tensor:
        """Return one raw validity logit per assignment, shape ``[B]``."""
        if set(H) != H_FIELDS:
            missing = sorted(H_FIELDS - set(H))
            extra = sorted(set(H) - H_FIELDS)
            raise ValueError(f"H fields mismatch; missing={missing}, extra={extra}")
        if H["constraint_embeddings"].ndim != 3 or h_global.ndim != 2 or a.ndim != 3:
            raise ValueError("expected H clauses [B,M,D], h_global [B,D], a [B,N,K]")
        batch, clauses, dim = H["constraint_embeddings"].shape
        if dim != self.hidden_dim or h_global.shape != (batch, self.hidden_dim):
            raise ValueError("semantic feature dimension does not match the frozen model input")
        if a.shape[0] != batch or a.shape[2] != self.max_roles:
            raise ValueError("assignment role dimension does not match model support")
        if H["constraint_mask"].shape != (batch, clauses):
            raise ValueError("constraint mask shape mismatch")
        if H["entity_incidence"].shape != (batch, clauses, a.shape[1]):
            raise ValueError("entity incidence must align with task entities")
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

        entity_incidence = H["entity_incidence"].to(dtype=h_global.dtype)
        role_incidence = H["role_incidence"].to(dtype=h_global.dtype)
        assigned_roles = torch.bmm(entity_incidence, assignment)
        entity_count = entity_incidence.sum(dim=-1, keepdim=True).clamp_min(1.0)
        role_fraction = assigned_roles / entity_count
        role_count = role_incidence.sum(dim=-1, keepdim=True)
        role_agreement = (assigned_roles * role_incidence).sum(dim=-1, keepdim=True)
        role_agreement = role_agreement / (entity_count * role_count.clamp_min(1.0))

        clause_semantics = self.constraint_projection(H["constraint_embeddings"])
        clause_features = torch.cat(
            (clause_semantics, role_fraction, role_incidence, role_agreement), dim=-1
        )
        clause_states = self.constraint_fusion(clause_features)
        attention_logits = self.constraint_attention(clause_states).squeeze(-1)
        attention_logits = attention_logits.masked_fill(~constraint_mask, torch.finfo(attention_logits.dtype).min)
        attention = torch.softmax(attention_logits, dim=-1).unsqueeze(-1)
        attention = attention * constraint_mask.unsqueeze(-1).to(attention.dtype)
        attention = attention / attention.sum(dim=1, keepdim=True).clamp_min(1.0)
        pooled_constraints = torch.sum(clause_states * attention, dim=1)
        global_state = self.global_projection(h_global)

        active_assignment = assignment * entity_mask.unsqueeze(-1)
        entity_count_total = entity_mask.sum(dim=1, keepdim=True).clamp_min(1).to(h_global.dtype)
        role_histogram = active_assignment.sum(dim=1) / entity_count_total
        logits = self.output(torch.cat((pooled_constraints, global_state, role_histogram), dim=-1))
        return logits.squeeze(-1)
