from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from .contracts import ACTION_TYPES, ARGUMENT_ROLES


class SemanticEpistemicGraft(nn.Module):
    """G_phi(H,A)->(s,e_1..e_m). Frozen H; no global confidence output."""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        d, h = config["input_dim"], config["hidden_dim"]
        self.register_buffer("input_mean", torch.zeros(d))
        self.register_buffer("input_std", torch.ones(d))
        self.project_h = nn.Sequential(nn.Linear(d, h), nn.LayerNorm(h), nn.GELU())
        self.semantic_query = nn.Parameter(torch.zeros(1, 1, h))
        nn.init.normal_(self.semantic_query, std=0.02)
        self.semantic_attention = nn.MultiheadAttention(h, config["attention_heads"], batch_first=True)
        self.semantic_slot = nn.Sequential(nn.Linear(h, config["semantic_dim"]), nn.LayerNorm(config["semantic_dim"]), nn.GELU())
        self.action_type = nn.Embedding(len(ACTION_TYPES), config["action_embedding_dim"], padding_idx=0)
        self.argument_slot = nn.Embedding(config["max_entities"] + 1, config["argument_embedding_dim"], padding_idx=0)
        ad = config["action_embedding_dim"] + len(ARGUMENT_ROLES) * config["argument_embedding_dim"]
        self.action_project = nn.Sequential(nn.Linear(ad, h), nn.LayerNorm(h), nn.GELU())
        self.candidate_attention = nn.MultiheadAttention(h, config["attention_heads"], batch_first=True)
        self.epistemic_slot = nn.Sequential(nn.Linear(h * 2 + config["semantic_dim"], h), nn.GELU(),
                                           nn.Linear(h, config["epistemic_dim"]), nn.LayerNorm(config["epistemic_dim"]), nn.GELU())
        self.global_readout = nn.Linear(config["semantic_dim"], 6)
        self.candidate_readout = nn.Linear(config["epistemic_dim"], 7)

    def forward(self, H, A, candidate_mask, token_mask=None):
        if H.ndim == 2:
            H = H.unsqueeze(1)
        if H.ndim != 3 or H.shape[-1] != self.config["input_dim"]:
            raise ValueError("H must be [B,K,input_dim] or the registered single-row [B,input_dim]")
        if A.ndim != 3 or A.shape[-1] != 1 + len(ARGUMENT_ROLES):
            raise ValueError("A must be [B,M,registered_action_fields]")
        if candidate_mask.shape != A.shape[:2]:
            raise ValueError("candidate mask shape mismatch")
        if A.shape[0] != H.shape[0]:
            raise ValueError("H/A batch mismatch")
        if token_mask is None:
            token_mask = torch.ones(H.shape[:2], dtype=torch.bool, device=H.device)
        if token_mask.shape != H.shape[:2] or token_mask.dtype != torch.bool:
            raise ValueError("token mask shape/type mismatch")
        if not token_mask.any(dim=1).all():
            raise ValueError("at least one visible H position is required")
        # The graft cannot backpropagate into a backbone, even when a caller supplies live H.
        hidden = self.project_h((H.detach() - self.input_mean) / self.input_std)
        query = self.semantic_query.expand(H.shape[0], -1, -1)
        global_context, _ = self.semantic_attention(query, hidden, hidden, key_padding_mask=~token_mask, need_weights=False)
        s = self.semantic_slot(global_context[:, 0])
        a = torch.cat((self.action_type(A[:, :, 0]), self.argument_slot(A[:, :, 1:]).flatten(2)), dim=-1)
        query_a = self.action_project(a)
        candidate_context, _ = self.candidate_attention(query_a, hidden, hidden, key_padding_mask=~token_mask, need_weights=False)
        semantic = s.unsqueeze(1).expand(-1, A.shape[1], -1)
        e = self.epistemic_slot(torch.cat((query_a, candidate_context, semantic), dim=-1))
        e = e * candidate_mask.unsqueeze(-1)
        candidate_logits = self.candidate_readout(e) * candidate_mask.unsqueeze(-1)
        return {"s": s, "e": e, "global_logits": self.global_readout(s), "candidate_logits": candidate_logits}


def masked_loss(output: dict, global_y, global_available, candidate_y, candidate_available, candidate_mask):
    gl = output["global_logits"]
    cl = output["candidate_logits"]
    global_terms, candidate_terms = [], []
    for i in range(gl.shape[-1]):
        mask = global_available[:, i]
        if mask.any():
            if i == 5:
                global_terms.append(F.smooth_l1_loss(gl[:, i][mask], global_y[:, i][mask]))
            else:
                global_terms.append(F.binary_cross_entropy_with_logits(gl[:, i][mask], global_y[:, i][mask]))
    for i in range(cl.shape[-1]):
        mask = candidate_available[:, :, i] & candidate_mask
        if mask.any():
            candidate_terms.append(F.binary_cross_entropy_with_logits(cl[:, :, i][mask], candidate_y[:, :, i][mask]))
    zero = gl.sum() * 0.0 + cl.sum() * 0.0
    g = torch.stack(global_terms).mean() if global_terms else zero
    c = torch.stack(candidate_terms).mean() if candidate_terms else zero
    return g + c, {"global": float(g.detach()), "candidate": float(c.detach())}
