"""Phase 0 architecture: the trainable graft G_phi(H, A) -> (s, e_1..e_m).

Frozen substrate output H is whatever the released primitives expose: row surfaces plus
per-entity mention-span vectors. The graft never sees labels.

Design constraints taken directly from the charter:
  * s and e_j are DISTINCT slots. There is no global confidence head.
  * d_s and d_e are free. They are NOT the target count. Supervision constrains what must
    be linearly readable from the slots, not the slot dimension.
  * e_j is CANDIDATE-CONDITIONED: it is a function of the candidate a_j, not of the world
    alone. A graft that produced one e_j and copied it m times would violate the ontology.
"""
from __future__ import annotations

import torch
import torch.nn as nn

ARCH_ABI = "phase0-semantic-interface/arch-v0.1"

ACTION_TYPES = ["MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER",
                "OPEN", "CLOSE", "SELECT", "ASSIGN", "REQUEST", "VERIFY", "WAIT", "NOOP"]


class SemanticInterfaceGraft(nn.Module):
    """G_phi.

    H is a dict of frozen substrate outputs:
        row      : [B, n_surface, d_h]     per-row surface vectors
        ent      : [E, d_h]                per-entity span vectors
        ent_ptr  : [B, n_ent_max]          entity index per row, padded with -1
        cand_ent : [B, m, n_arg]           entity index per candidate argument slot, -1 pad
        cand_type: [B, m]                  action type id
        cand_mask: [B, m]                  valid-candidate mask

    Outputs:
        s   : [B, d_s]      global semantic state
        e   : [B, m, d_e]   candidate-conditioned epistemic state, one per candidate
    """

    def __init__(self, d_h: int = 1024, n_surface: int = 6, n_types: int = len(ACTION_TYPES),
                 d_s: int = 64, d_e: int = 32, hidden: int = 256, dropout: float = 0.1):
        super().__init__()
        self.d_s, self.d_e = d_s, d_e
        self.row_proj = nn.Sequential(
            nn.Linear(n_surface * d_h, hidden), nn.GELU(), nn.LayerNorm(hidden))
        # candidate encoder sees: row state, its own argument entity vectors, type embedding
        self.type_emb = nn.Embedding(n_types, 32)
        self.arg_proj = nn.Linear(3 * d_h + 32, hidden)
        self.cand_proj = nn.Sequential(nn.GELU(), nn.LayerNorm(hidden))
        self.to_s = nn.Sequential(nn.Linear(hidden, d_s), nn.GELU(), nn.Dropout(dropout))
        # e_j is conditioned on s, so the epistemic slot is explicitly candidate x world
        self.to_e = nn.Sequential(nn.Linear(hidden + d_s, d_e), nn.GELU(), nn.Dropout(dropout))

    def forward(self, H: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
        B, m = H["cand_type"].shape
        r = self.row_proj(H["row"].reshape(B, -1))                       # [B, hidden]
        s = self.to_s(r)                                                  # [B, d_s]

        # gather argument entity vectors; 3 slots padded to zeros when absent
        E = H["ent"]
        cand_ent = H["cand_ent"]                                          # [B, m, 3]
        gathered = []
        for slot in range(cand_ent.shape[-1]):
            idx = cand_ent[:, :, slot].clamp(min=0)
            v = E[idx]                                                    # [B, m, d_h]
            valid = (cand_ent[:, :, slot] >= 0).unsqueeze(-1).float()
            gathered.append(v * valid)
        a = torch.cat(gathered + [self.type_emb(H["cand_type"])], dim=-1)
        c = self.cand_proj(self.arg_proj(a))                             # [B, m, hidden]
        e = self.to_e(torch.cat([c, s.unsqueeze(1).expand(-1, m, -1)], dim=-1))
        # pad candidates keep a defined state but are masked out of every loss
        e = e * H["cand_mask"].unsqueeze(-1).float()
        return s, e


class BidirectionalGraft(nn.Module):
    """Lepori's fabric: full-context + entity-local state -> candidate-conditioned encoder graft.

    Same contract as the causal graft, different nervous system. NO alignment between the two
    is imposed; see src/objective.py.
    """

    def __init__(self, d_h: int = 1024, n_surface: int = 6, n_types: int = len(ACTION_TYPES),
                 d_s: int = 64, d_e: int = 32, hidden: int = 256, dropout: float = 0.1,
                 n_layers: int = 2):
        super().__init__()
        self.fabric = "bidirectional"
        self.d_s, self.d_e = d_s, d_e
        self.row_proj = nn.Sequential(
            nn.Linear(n_surface * d_h, hidden), nn.GELU(), nn.LayerNorm(hidden))
        # a small attention-style mixer over surfaces: full-context aggregation
        self.surf_proj = nn.Linear(d_h, hidden)
        self.mixer = nn.ModuleList([
            nn.MultiheadAttention(hidden, num_heads=4, batch_first=True) for _ in range(n_layers)])
        self.mix_norm = nn.ModuleList([nn.LayerNorm(hidden) for _ in range(n_layers)])
        self.type_emb = nn.Embedding(n_types, 32)
        self.arg_proj = nn.Linear(3 * d_h + 32, hidden)
        self.cand_proj = nn.Sequential(nn.GELU(), nn.LayerNorm(hidden))
        self.to_s = nn.Sequential(nn.Linear(hidden, d_s), nn.GELU(), nn.Dropout(dropout))
        self.to_e = nn.Sequential(nn.Linear(hidden + d_s, d_e), nn.GELU(), nn.Dropout(dropout))

    def forward(self, H):
        B, S, d = H["row"].shape
        r = self.row_proj(H["row"].reshape(B, -1)).unsqueeze(1)      # [B,1,hidden]
        # each surface is projected into the shared width so it can act as context tokens
        ctx = self.surf_proj(H["row"])                               # [B,S,hidden]
        ctx = ctx + ctx.mean(1, keepdim=True)
        for attn, nrm in zip(self.mixer, self.mix_norm):
            a, _ = attn(ctx, r, r)
            r = nrm(r + a)
        r = r.reshape(B, -1, r.shape[-1]).mean(1)                    # [B, hidden]
        s = self.to_s(r)
        E = H["ent"]
        cand_ent = H["cand_ent"]
        gathered = []
        for slot in range(cand_ent.shape[-1]):
            idx = cand_ent[:, :, slot].clamp(min=0)
            v = E[idx]
            v = v * (cand_ent[:, :, slot] >= 0).unsqueeze(-1).float()
            gathered.append(v)
        a = torch.cat(gathered + [self.type_emb(H["cand_type"])], dim=-1)
        c = self.cand_proj(self.arg_proj(a))
        e = self.to_e(torch.cat([c, s.unsqueeze(1).expand(-1, c.shape[1], -1)], dim=-1))
        m = H["cand_mask"]
        return s, e * m.unsqueeze(-1).float()


class ReadoutHeads(nn.Module):
    """Per-target linear readouts. Global targets read from s; candidate targets read
    y_hat_j = W e_j. Targets marked unavailable in the ontology get NO head."""

    def __init__(self, d_s: int, d_e: int, global_names, candidate_names,
                 m_cap: int = 24, action_endpoint: bool = True):
        super().__init__()
        self.global_names = [n for n, _ in global_names]
        self.candidate_names = [n for n, _ in candidate_names]
        self.g_heads = nn.ModuleDict({n: nn.Linear(d_s, d) for n, d in global_names})
        self.c_heads = nn.ModuleDict({n: nn.Linear(d_e, d) for n, d in candidate_names})
        # L_A: CE over the enumerated candidate set, read off the candidate slot only.
        self.action_head = nn.Linear(d_e, m_cap) if action_endpoint else None
        self.m_cap = m_cap

    def forward(self, s, e, cand_mask):
        g = {n: self.g_heads[n](s) for n in self.global_names}
        c = {}
        for n, head in self.c_heads.items():
            o = head(e)
            c[n] = o * cand_mask.unsqueeze(-1).float()
        a = self.action_head(e) * cand_mask.unsqueeze(-1).float() if self.action_head else None
        return g, c, a


def arch_descriptor(d_h: int = 1024, d_s: int = 64, d_e: int = 32) -> dict:
    return {
        "abi": ARCH_ABI,
        "frozen_substrate": "F_theta(x) -> H (release primitives: 6 row surfaces + entity spans)",
        "trainable_graft": "G_phi(H, A) -> (s, e_1..e_m)",
        "d_h": d_h, "d_s": d_s, "d_e": d_e,
        "slots": {
            "s": "global semantic state, task/world properties",
            "e_j": "candidate-conditioned epistemic state, support state of candidate a_j",
        },
        "invariants": [
            "s and e_j are distinct slots; no single global confidence head",
            "e_j is a function of (world, candidate); not a broadcast copy of a world vector",
            "d_s and d_e are free and are not the target count",
            "padded candidates are masked out of every loss",
        ],
        "readout": "y_hat_j = W e_j (candidate) ; y_hat = H s (global)",
    }


def count_parameters(model: nn.Module) -> dict:
    g = sum(p.numel() for p in model.graft.parameters()) if hasattr(model, "graft") else 0
    r = sum(p.numel() for p in model.heads.parameters()) if hasattr(model, "heads") else 0
    return {"graft": g, "readouts": r, "total": g + r}
