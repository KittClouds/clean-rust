"""Causal graft for the Lepori lane.

Deliberately boring architecture:

    MiniCPM hidden stack
          -> 6 typed surface projections   u_i = P_i(x_i)      (one per surface, NOT shared)
          -> global semantic state         s   = rho_s([u_1..u_6])
          -> candidate-conditioned states  e_j = rho_e([c_j ; s])
          -> typed heads + action endpoint

Design points, each traceable to an inherited lesson rather than taste:

  * ONE PROJECTOR PER SURFACE. The six surfaces are different representation surfaces of the
    same input, not six interchangeable measurements of one quantity, and their raw scales
    differ (1.38 to 4.50 std across surfaces). A shared projector across depths would impose a
    false equivalence between them. Separate P_i keep each surface's geometry its own.

  * EXPLICIT SURFACE MEMORY BANK. The six u_i are returned alongside s, not consumed and
    discarded, so a later intervention can reread them without reworking the base interface.

  * NO RECURRENCE, NO IHA, NO LORA, NO STOCHASTICITY, no cross-surface attention. This phase
    establishes whether the machine learns, and the encoder lane already showed what a generic
    token mixer does to candidate differentiation.

  * CANDIDATE REPRESENTATION IS ENTITY-ANCHORED. c_j gathers the entity-span vectors the
    candidate's arguments reference, at final depth where a causal mention is context-complete.
    This is the substrate-specific affordance, and it is what makes e_j candidate-conditioned
    rather than a broadcast world vector.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from src.data import SURFACES, ACTION_TYPES

D_S = 64
D_E = 32
D_U = 128          # per-surface projected width


class SurfaceProjections(nn.Module):
    """Six independent small projections, one per surface. No shared weights across depth."""

    def __init__(self, d_h: int, d_u: int = D_U):
        super().__init__()
        self.d_u = d_u
        self.proj = nn.ModuleList([
            nn.Sequential(nn.LayerNorm(d_h), nn.Linear(d_h, d_u), nn.GELU())
            for _ in SURFACES])

    def forward(self, x):
        """x [B, 6, d_h] -> u [B, 6, d_u]"""
        return torch.stack([p(x[:, i]) for i, p in enumerate(self.proj)], 1)


class CausalGraft(nn.Module):
    def __init__(self, d_h: int, d_s: int = D_S, d_e: int = D_E, d_u: int = D_U,
                 n_types: int = len(ACTION_TYPES), n_args: int = 3):
        super().__init__()
        self.fabric = "causal"
        self.d_s, self.d_e, self.d_u = d_s, d_e, d_u
        self.surfaces = SurfaceProjections(d_h, d_u)
        self.rho_s = nn.Sequential(
            nn.LayerNorm(len(SURFACES) * d_u), nn.Linear(len(SURFACES) * d_u, 256),
            nn.GELU(), nn.LayerNorm(256), nn.Linear(256, d_s))
        # c_j: candidate args -> entity-span vectors at final depth, plus action-type embedding
        self.type_emb = nn.Embedding(n_types, 32)
        self.arg_proj = nn.Sequential(
            nn.LayerNorm(n_args * d_h + 32), nn.Linear(n_args * d_h + 32, 256), nn.GELU(),
            nn.LayerNorm(256))
        self.rho_e = nn.Sequential(
            nn.Linear(256 + d_s, 256), nn.GELU(), nn.LayerNorm(256), nn.Linear(256, d_e))

    def candidate_states(self, H):
        """Entity-anchored per-candidate representation c_j. [B, m, 256]"""
        E, cand_ent = H["ent"], H["cand_ent"]
        gathered = []
        for slot in range(cand_ent.shape[-1]):
            idx = cand_ent[:, :, slot].clamp(min=0)
            v = E[idx] * (cand_ent[:, :, slot] >= 0).unsqueeze(-1).float()
            gathered.append(v)
        a = torch.cat(gathered + [self.type_emb(H["cand_type"])], dim=-1)
        return self.arg_proj(a)

    def forward(self, H):
        """Returns (s, e, surface_bank). surface_bank is the explicit u_i memory bank."""
        u = self.surfaces(H["row"])                                   # [B, 6, d_u]
        s = self.rho_s(u.reshape(u.shape[0], -1))                     # [B, d_s]
        c = self.candidate_states(H)                                  # [B, m, 256]
        e = self.rho_e(torch.cat([c, s.unsqueeze(1).expand(-1, c.shape[1], -1)], -1))
        m = H["cand_mask"].unsqueeze(-1).float()
        return s, e * m, u


class ReadoutHeads(nn.Module):
    """Typed output semantics, unchanged from the shared contract. No new target heads."""

    def __init__(self, d_s: int, d_e: int, global_names, cand_names, m_cap: int):
        super().__init__()
        self.global_names = list(global_names)
        self.cand_names = list(cand_names)
        self.g = nn.ModuleDict({n: nn.Linear(d_s, _dout(n)) for n in self.global_names})
        self.c = nn.ModuleDict({n: nn.Linear(d_e, 1) for n in self.cand_names})
        # ONE LOGIT PER CANDIDATE. The action endpoint is a choice among the candidate set, so
        # it must be a [B, m] scorer with masked CE over m classes. Emitting m*m_cap logits and
        # comparing an argmax over the flattened tensor against a single candidate index is the
        # wrong shape: it silently turns the endpoint into an m*m_cap-way classifier in which
        # only m_cap classes are ever correct, and it makes the chance rate 1/(m*m_cap) instead
        # of 1/m. Corrected here at the source.
        self.a = nn.Linear(d_e, 1)

    def forward(self, s, e, cand_mask):
        g = {n: self.g[n](s) for n in self.global_names}
        c = {n: self.c[n](e).squeeze(-1) for n in self.cand_names}
        return g, c, self.a(e).squeeze(-1) * cand_mask


def _dout(name: str) -> int:
    from src.ontology import BY_NAME
    return BY_NAME[name].d_out


class Interface(nn.Module):
    def __init__(self, d_h: int, d_s: int, d_e: int, global_names, cand_names, m_cap: int,
                 d_u: int = D_U):
        super().__init__()
        self.graft = CausalGraft(d_h, d_s, d_e, d_u)
        self.heads = ReadoutHeads(d_s, d_e, global_names, cand_names, m_cap)

    def forward(self, H):
        s, e, bank = self.graft(H)
        g, c, a = self.heads(s, e, H["cand_mask"])
        return s, e, g, c, a, bank


def architecture_descriptor(d_h: int, d_s: int = D_S, d_e: int = D_E, d_u: int = D_U) -> dict:
    return {
        "abi": "s15-lepori-minicpm/causal-graft-v0.1",
        "d_h": d_h, "d_s": d_s, "d_e": d_e, "d_u": d_u,
        "surfaces": SURFACES,
        "per_surface_projections": True,
        "shared_projector_across_depths": False,
        "surface_memory_bank_exposed": True,
        "global_state": "rho_s over the concatenation of all six u_i",
        "candidate_state": "rho_e over [entity-anchored candidate repr ; global state]",
        "excluded": ["recurrence", "IHA / cross-head mixing", "LoRA", "stochastic transitions",
                     "cross-surface attention", "backbone adaptation"],
    }
