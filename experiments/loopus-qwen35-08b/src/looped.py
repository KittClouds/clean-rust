"""Looped encoder / reasoning-block / decoder execution for hybrid Qwen3.5.

Design points (all verified by ``tests/test_looped.py``):

* The three blocks *share* the HF model's modules (no weight copies), so weight
  identity with the checkpoint is by construction.
* Masks are dispatched per layer with ``config.layer_types[absolute_index]``.
  Qwen3.5 decoder layers expose ``block_type`` and no ``attention_type``, so the
  LoopUS idiom ``getattr(layer, "attention_type", "full_attention")`` silently
  sends every layer the full-attention mask.
* No KV / recurrent cache anywhere. Re-running gated-delta layers statelessly is
  deterministic. Rotary embeddings, position ids and both mask types are built
  once per batch.
* ``R == 1`` is the exact pretrained forward (the first pass is never gated).
  For ``t >= 2``: ``h_t = gate(f(h_{t-1}), h_{t-1})`` (or plain ``f(h_{t-1})`` when
  no gate is configured).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch
import torch.nn as nn
from torch.utils.checkpoint import checkpoint
from transformers.masking_utils import create_causal_mask, create_recurrent_attention_mask

from .gate import build_gate


@dataclass
class Ctx:
    """Per-batch tensors that are identical across every recursion step."""
    embeds: torch.Tensor
    position_embeddings: tuple[torch.Tensor, torch.Tensor]
    text_position_ids: torch.Tensor
    masks: dict
    attention_mask: torch.Tensor | None


def parse_split(num_layers: int, enc: tuple[int, int], reasoning: tuple[int, int],
                dec: tuple[int, int]) -> tuple[list[int], list[int], list[int]]:
    """Inclusive ``(lo, hi)`` ranges (LoopUS ``0..1`` notation) -> index lists.

    The three ranges must be contiguous and cover every layer exactly once.
    """
    e, r, d = (list(range(lo, hi + 1)) for lo, hi in (enc, reasoning, dec))
    if e + r + d != list(range(num_layers)):
        raise ValueError(f"split {enc}/{reasoning}/{dec} does not partition {num_layers} layers")
    return e, r, d


class LoopedQwen35(nn.Module):
    def __init__(self, hf_model, enc=(0, 1), reasoning=(2, 22), dec=(23, 23),
                 gate: str = "none", gate_kwargs: dict | None = None,
                 grad_checkpoint: bool = False):
        super().__init__()
        self.hf = hf_model                      # registered once; blocks below alias its layers
        self.cfg = hf_model.config
        self.text = hf_model.model
        self.lm_head = hf_model.lm_head
        self.enc_idx, self.rea_idx, self.dec_idx = parse_split(
            self.cfg.num_hidden_layers, tuple(enc), tuple(reasoning), tuple(dec))
        if len(self.cfg.layer_types) != self.cfg.num_hidden_layers:
            raise ValueError("config.layer_types does not cover num_hidden_layers")
        self.gate = build_gate(gate, self.cfg.hidden_size, **(gate_kwargs or {}))
        self.grad_checkpoint = grad_checkpoint
        self._pass = 0                   # index of the recursion pass in flight (per-pass LoRA adapters)
        self._lora_by_layer: dict[int, list] = {}

    # ------------------------------------------------------------------ setup
    def prepare(self, input_ids: torch.Tensor, attention_mask: torch.Tensor | None = None) -> Ctx:
        """Mirror ``Qwen3_5TextModel.forward`` (transformers 5.x) without a cache."""
        embeds = self.text.embed_tokens(input_ids)
        b, t = input_ids.shape
        pos = torch.arange(t, device=embeds.device).view(1, 1, -1).expand(4, b, -1)
        text_pos, rope_pos = pos[0], pos[1:]
        mask_kwargs = dict(config=self.cfg, inputs_embeds=embeds, attention_mask=attention_mask,
                           past_key_values=None, position_ids=text_pos)
        masks = {
            "full_attention": create_causal_mask(**mask_kwargs),
            "linear_attention": create_recurrent_attention_mask(**mask_kwargs),
        }
        return Ctx(embeds, self.text.rotary_emb(embeds, rope_pos), text_pos, masks, attention_mask)

    # ----------------------------------------------------------------- blocks
    def _set_pass(self, i: int, p: int) -> None:
        """Select pass ``p``'s adapters in layer ``i`` (no-op unless the layer has per-pass LoRA)."""
        mods = self._lora_by_layer.get(i)
        if mods is None:
            from .lora import LoRALinear
            mods = [m for m in self.text.layers[i].modules() if isinstance(m, LoRALinear) and m.n_passes > 1]
            self._lora_by_layer[i] = mods
        for m in mods:
            m.cur = p

    def _layer(self, i: int, h: torch.Tensor, ctx: Ctx) -> torch.Tensor:
        layer = self.text.layers[i]
        p = self._pass
        mask = ctx.masks[self.cfg.layer_types[i]]    # dispatch on ABSOLUTE index
        kw = dict(position_embeddings=ctx.position_embeddings, attention_mask=mask,
                  position_ids=ctx.text_position_ids, past_key_values=None, use_cache=False)
        if self.grad_checkpoint and self.training and torch.is_grad_enabled():
            # the pass index is re-applied inside the recomputed function: backward recomputes
            # after the whole forward, when module state would otherwise point at the LAST pass
            def fn(x):
                self._set_pass(i, p)
                return layer(x, **kw)
            return checkpoint(fn, h, use_reentrant=False)
        self._set_pass(i, p)
        return layer(h, **kw)

    def _run(self, idx: Sequence[int], h: torch.Tensor, ctx: Ctx) -> torch.Tensor:
        for i in idx:
            h = self._layer(i, h, ctx)
        return h

    def encode(self, ctx: Ctx) -> torch.Tensor:
        return self._run(self.enc_idx, ctx.embeds, ctx)

    def block(self, h: torch.Tensor, ctx: Ctx) -> torch.Tensor:
        """One application of the shared reasoning block (ungated)."""
        return self._run(self.rea_idx, h, ctx)

    def step(self, h: torch.Tensor, ctx: Ctx, first: bool) -> torch.Tensor:
        """One recursion step; the first pass is never gated (keeps R=1 exact)."""
        if first:
            self._pass = 0
        h_new = self.block(h, ctx)
        self._pass += 1
        if first or self.gate is None:
            return h_new
        return self.gate(h_new, h)

    def decode(self, h: torch.Tensor, ctx: Ctx) -> torch.Tensor:
        """Decoder layers + final RMSNorm. Returns normed hidden (pre LM head)."""
        return self.text.norm(self._run(self.dec_idx, h, ctx))

    def logits(self, normed: torch.Tensor) -> torch.Tensor:
        return self.lm_head(normed)

    # ---------------------------------------------------------------- forward
    def states(self, input_ids: torch.Tensor, attention_mask: torch.Tensor | None = None,
               depths: Sequence[int] = (1,), ctx: Ctx | None = None) -> tuple[dict[int, torch.Tensor], Ctx]:
        """Run the loop once to ``max(depths)``; return ``{depth: recurrent state}``.

        State ``d`` is the post-gate hidden fed to the decoder after ``d`` passes
        through the reasoning block (``d=1`` == ``h_1`` in LoopCD notation).
        """
        ctx = ctx or self.prepare(input_ids, attention_mask)
        want = set(depths)
        h = self.encode(ctx)
        out: dict[int, torch.Tensor] = {}
        for t in range(1, max(want) + 1):
            h = self.step(h, ctx, first=(t == 1))
            if t in want:
                out[t] = h
        return out, ctx

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor | None = None,
                R: int = 1) -> torch.Tensor:
        """Full logits at depth ``R``. Avoid for large vocabularies; see ``readout``."""
        st, ctx = self.states(input_ids, attention_mask, depths=(R,))
        return self.logits(self.decode(st[R], ctx))

    # --------------------------------------------------------------- bookkeeping
    def block_parameters(self):
        for i in self.rea_idx:
            yield from self.text.layers[i].parameters()

    def split_summary(self) -> dict:
        lt = self.cfg.layer_types
        return {
            "encoder": self.enc_idx, "reasoning": self.rea_idx, "decoder": self.dec_idx,
            "reasoning_layer_types": [lt[i] for i in self.rea_idx],
            "n_linear_in_block": sum(lt[i] == "linear_attention" for i in self.rea_idx),
            "n_full_in_block": sum(lt[i] == "full_attention" for i in self.rea_idx),
            "gate": type(self.gate).__name__ if self.gate is not None else None,
        }


def weight_identity(model: LoopedQwen35, state_dict: dict[str, torch.Tensor]) -> dict:
    """Compare live text weights with a checkpoint state dict.

    Handles the ``model.language_model.*`` -> ``model.*`` remap used by the
    Qwen3.5 multimodal checkpoints. Returns worst abs diff and unmatched keys.
    """
    live = {k: v for k, v in model.hf.state_dict().items()}
    remapped = {}
    for k, v in state_dict.items():
        nk = k.replace("model.language_model.", "model.", 1) if k.startswith("model.language_model.") else k
        remapped[nk] = v
    worst, missing, n = 0.0, [], 0
    for k, v in live.items():
        src = remapped.get(k)
        if src is None and k == "lm_head.weight":
            src = remapped.get("model.embed_tokens.weight")      # tied
        if src is None:
            missing.append(k)
            continue
        worst = max(worst, float((v.detach().cpu().float() - src.float()).abs().max()))
        n += 1
    return {"compared": n, "worst_abs_diff": worst, "missing_in_checkpoint": missing}
