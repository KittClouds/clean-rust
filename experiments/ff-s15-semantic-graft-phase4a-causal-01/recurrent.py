"""One shared four-step recurrent organ over the frozen causal typed graft state."""
from __future__ import annotations

import torch
from torch import nn

from graft.model import forward_batch as frozen_forward


class SharedRecurrentBlock(nn.Module):
    def __init__(self, state_dim: int = 64, memory_dim: int = 2048, heads: int = 4,
                 feedforward_dim: int = 256):
        super().__init__()
        self.self_norm = nn.LayerNorm(state_dim)
        self.self_attention = nn.MultiheadAttention(state_dim, heads, batch_first=True)
        self.cross_norm = nn.LayerNorm(state_dim)
        self.cross_attention = nn.MultiheadAttention(
            state_dim, heads, kdim=memory_dim, vdim=memory_dim, batch_first=True)
        self.update_norm = nn.LayerNorm(state_dim)
        self.feedforward = nn.Sequential(nn.Linear(state_dim, feedforward_dim), nn.GELU(),
                                         nn.Linear(feedforward_dim, state_dim))

    def forward(self, z, memory, token_mask):
        normalized = self.self_norm(z)
        u, _ = self.self_attention(normalized, normalized, normalized,
                                   key_padding_mask=~token_mask, need_weights=False)
        c, _ = self.cross_attention(self.cross_norm(z + u), memory, memory,
                                    need_weights=False)
        updated = z + self.feedforward(self.update_norm(z + u + c))
        return updated * token_mask.unsqueeze(-1).to(updated.dtype)


class RecurrentCausalGraft(nn.Module):
    """Frozen P2-CONSIST causal graft plus trainable recurrence/output projections."""
    def __init__(self, frozen_model, iterations: int = 4):
        super().__init__()
        if frozen_model.use_entity_local:
            raise ValueError("Phase 4A causal arm requires the causal frozen graft")
        self.seed = frozen_model
        for parameter in self.seed.parameters():
            parameter.requires_grad_(False)
        self.seed.eval()
        self.iterations = iterations
        config = frozen_model.config
        self.state_dim = int(config["semantic_dim"])
        if self.state_dim != int(config["epistemic_dim"]):
            raise ValueError("Causal typed slots must be width-compatible for [s;e] recurrence")
        self.memory_dim = int(config["input_dim"])
        self.recurrent = SharedRecurrentBlock(self.state_dim, self.memory_dim,
                                              int(config["attention_heads"]))
        self.global_output = nn.Linear(self.state_dim, int(config["semantic_dim"]))
        self.candidate_output = nn.Linear(self.state_dim, int(config["epistemic_dim"]))
        with torch.no_grad():
            self.global_output.weight.copy_(torch.eye(self.state_dim))
            self.global_output.bias.zero_()
            self.candidate_output.weight.copy_(torch.eye(self.state_dim))
            self.candidate_output.bias.zero_()

    def train(self, mode: bool = True):
        super().train(mode)
        self.seed.eval()
        return self

    def encode_seed(self, batch):
        with torch.no_grad():
            output = frozen_forward(self.seed, batch)
            z0 = torch.cat((output["s"].unsqueeze(1), output["e"]), dim=1)
            mask = torch.cat((torch.ones_like(batch["candidate_mask"][:, :1]),
                              batch["candidate_mask"]), dim=1)
            # The same frozen TRAIN normalizer used by the inherited graft defines H memory.
            memory = ((batch["H"].detach() - self.seed.input_mean) /
                      self.seed.input_std).unsqueeze(1)
        return z0, memory.detach(), mask, output

    def refine_one(self, z, memory, token_mask):
        return self.recurrent(z, memory, token_mask)

    def outputs_from_state(self, z, batch, depth: int):
        if depth == 0:
            return frozen_forward(self.seed, batch)
        s = self.global_output(z[:, 0])
        e = self.candidate_output(z[:, 1:])
        e = e * batch["candidate_mask"].unsqueeze(-1).to(e.dtype)
        return {"s": s, "e": e, "global_logits": self.seed.global_readout(s),
                "candidate_logits": self.seed.candidate_readout(e) * batch["candidate_mask"].unsqueeze(-1),
                "action_logits": self.seed.action_endpoint(e).squeeze(-1).masked_fill(
                    ~batch["candidate_mask"], -1e9)}

    def forward_states(self, batch):
        z, memory, mask, seed_output = self.encode_seed(batch)
        states = [z]
        for _ in range(self.iterations):
            z = self.refine_one(z, memory, mask)
            states.append(z)
        outputs = [seed_output] + [self.outputs_from_state(state, batch, depth)
                                   for depth, state in enumerate(states[1:], 1)]
        return outputs, states

    def forward_at_depth(self, batch, depth: int):
        if depth < 0 or depth > self.iterations:
            raise ValueError("requested recurrent depth is outside the frozen T=4 ladder")
        if depth == 0:
            return frozen_forward(self.seed, batch)
        z, memory, mask, seed_output = self.encode_seed(batch)
        for _ in range(depth):
            z = self.refine_one(z, memory, mask)
        return self.outputs_from_state(z, batch, depth)

    def forward(self, h, actions, candidate_mask, token_mask=None,
                entity_local=None, entity_available=None):
        batch = {"H": h, "A": actions, "candidate_mask": candidate_mask}
        return self.forward_at_depth(batch, self.iterations)


class DepthView(nn.Module):
    """Read-only adapter for existing target reports at one already-trained depth."""
    def __init__(self, recurrent_model: RecurrentCausalGraft, depth: int):
        super().__init__()
        self.model = recurrent_model
        self.depth = depth

    def forward(self, h, actions, candidate_mask, token_mask=None,
                entity_local=None, entity_available=None):
        batch = {"H": h, "A": actions, "candidate_mask": candidate_mask}
        return self.model.forward_at_depth(batch, self.depth)

