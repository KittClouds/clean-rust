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
        self.use_entity_local = config.get("use_entity_local", False)
        if self.use_entity_local:
            self.register_buffer("local_mean", torch.zeros(config["entity_local_dim"]))
            self.register_buffer("local_std", torch.ones(config["entity_local_dim"]))
            self.local_context = nn.Linear(config["entity_local_dim"], h)
            self.local_role = nn.Linear(config["entity_local_dim"], config["entity_role_dim"])
        self.project_h = nn.Sequential(nn.Linear(d, h), nn.LayerNorm(h), nn.GELU())
        self.semantic_query = nn.Parameter(torch.zeros(1, 1, h))
        nn.init.normal_(self.semantic_query, std=0.02)
        self.semantic_attention = nn.MultiheadAttention(h, config["attention_heads"], batch_first=True)
        self.semantic_slot = nn.Sequential(nn.Linear(h, config["semantic_dim"]), nn.LayerNorm(config["semantic_dim"]), nn.GELU())
        self.action_type = nn.Embedding(len(ACTION_TYPES), config["action_embedding_dim"], padding_idx=0)
        self.argument_slot = nn.Embedding(config["max_entities"] + 1, config["argument_embedding_dim"], padding_idx=0)
        ad = config["action_embedding_dim"] + len(ARGUMENT_ROLES) * config["argument_embedding_dim"]
        if self.use_entity_local:
            ad += len(ARGUMENT_ROLES) * config["entity_role_dim"]
        self.action_project = nn.Sequential(nn.Linear(ad, h), nn.LayerNorm(h), nn.GELU())
        self.candidate_attention = nn.MultiheadAttention(h, config["attention_heads"], batch_first=True)
        self.epistemic_slot = nn.Sequential(nn.Linear(h * 2 + config["semantic_dim"], h), nn.GELU(),
                                           nn.Linear(h, config["epistemic_dim"]), nn.LayerNorm(config["epistemic_dim"]), nn.GELU())
        self.global_readout = nn.Linear(config["semantic_dim"], 6)
        self.candidate_readout = nn.Linear(config["epistemic_dim"], 7)
        self.action_endpoint = nn.Linear(config["epistemic_dim"], 1)

    def forward(self, H, A, candidate_mask, token_mask=None, entity_local=None, entity_available=None):
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
        local = None
        if self.use_entity_local:
            if entity_local is None or entity_available is None:
                raise ValueError("encoder fabric requires masked entity-local inputs")
            if entity_local.shape[:2] != entity_available.shape or entity_local.shape[0] != H.shape[0]:
                raise ValueError("entity-local shape mismatch")
            if entity_local.shape[-1] != self.config["entity_local_dim"] or entity_available.dtype != torch.bool:
                raise ValueError("entity-local width/type mismatch")
            if entity_available[:, 0].any():
                raise ValueError("entity-local ordinal zero is unavailable padding")
            local = (entity_local.detach() - self.local_mean) / self.local_std
            local = local.masked_fill(~entity_available.unsqueeze(-1), 0)
            hidden = torch.cat((hidden, self.local_context(local)), dim=1)
            token_mask = torch.cat((token_mask, entity_available), dim=1)
        query = self.semantic_query.expand(H.shape[0], -1, -1)
        global_context, _ = self.semantic_attention(query, hidden, hidden, key_padding_mask=~token_mask, need_weights=False)
        s = self.semantic_slot(global_context[:, 0])
        a = torch.cat((self.action_type(A[:, :, 0]), self.argument_slot(A[:, :, 1:]).flatten(2)), dim=-1)
        if local is not None:
            batch_index = torch.arange(A.shape[0], device=A.device)[:, None, None]
            gathered = local[batch_index, A[:, :, 1:]]
            valid = entity_available[batch_index, A[:, :, 1:]]
            role = self.local_role(gathered).masked_fill(~valid.unsqueeze(-1), 0)
            a = torch.cat((a, role.flatten(2)), dim=-1)
        query_a = self.action_project(a)
        candidate_context, _ = self.candidate_attention(query_a, hidden, hidden, key_padding_mask=~token_mask, need_weights=False)
        semantic = s.unsqueeze(1).expand(-1, A.shape[1], -1)
        e = self.epistemic_slot(torch.cat((query_a, candidate_context, semantic), dim=-1))
        e = e * candidate_mask.unsqueeze(-1)
        candidate_logits = self.candidate_readout(e) * candidate_mask.unsqueeze(-1)
        action_logits = self.action_endpoint(e).squeeze(-1).masked_fill(~candidate_mask, -1e9)
        return {"s": s, "e": e, "global_logits": self.global_readout(s),
                "candidate_logits": candidate_logits, "action_logits": action_logits}


def model_for_substrate(config, substrate):
    own = dict(config)
    own["use_entity_local"] = substrate == "encoder_base"
    own["fabric"] = "bidirectional" if own["use_entity_local"] else "causal_late"
    return SemanticEpistemicGraft(own)


def forward_batch(model, batch):
    return model(batch["H"], batch["A"], batch["candidate_mask"],
                 entity_local=batch.get("entity_local"), entity_available=batch.get("entity_available"))


def masked_loss(output: dict, global_y, global_available, candidate_y, candidate_available, candidate_mask):
    """Compatibility helper for older mask tests; delegates to the shared objective."""
    from .contracts import default_config
    from .objective import shared_objective
    n = len(global_y)
    batch = {"global_y": global_y, "global_available": global_available,
             "candidate_y": candidate_y, "candidate_available": candidate_available,
             "candidate_mask": candidate_mask,
             "action_target": torch.full((n,), -1, dtype=torch.long, device=global_y.device),
             "action_available": torch.zeros(n, dtype=torch.bool, device=global_y.device)}
    return shared_objective(output, batch, default_config())
