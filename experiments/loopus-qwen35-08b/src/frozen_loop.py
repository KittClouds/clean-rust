"""Frozen-weights looped Qwen3.5-0.8B (the construction behind premise.json).

Recasts a pretrained causal LM into encoder / reasoning-loop / decoder with NO training and
reads real checkpoint weights from disk for the identity gate. The trainable stack lives in
looped.py (LoopedQwen35); this module is the independently-written reference it is checked
against.

Design decisions, and where each comes from
-------------------------------------------
SPLIT (measured, not guessed). LoopUS step 1 is a decomposition guided by staged representation
dynamics, but the LoopUS repo does not ship that analysis -- it hardcodes per-model indices
(encoder 0..1, decoder 27..27 on Qwen3-1.7B). We measured it ourselves (see geometry.json):
on Qwen3.5-0.8B the consecutive-depth cosine distance is
    embeddings->L0 0.022 | L0->L1 0.907 | L2..L22 plateau 0.032..0.209 | L22->L23 0.483
and the raw std explodes 0.23 -> 2.90 on the final transition. That is exactly the three-regime
staged picture: a big transform entering the plateau, a long plateau, then a sharp projection
toward the vocabulary. So
    encoder   = layers 0..1     (before the plateau)
    reasoning = layers 2..22    (the plateau; this is the ONLY part that loops)
    decoder   = layer  23       (the sharp vocabulary projection)
which lands on the same 2 / 21 / 1 shape LoopUS released for Qwen3-1.7B (2 / 25 / 1), but derived
from this model's own geometry instead of copied.

HYBRID LAYERS. 18 of 24 layers are linear_attention (Qwen3_5GatedDeltaNet), 6 are full_attention.
The LoopUS blocks call every layer with one uniform signature and index masks by
`getattr(layer, "attention_type", "full_attention")` -- but on this model every layer reports
`attention_type = None`, so LoopUS would silently route all 24 layers through the full-attention
mask. We dispatch on `config.layer_types[absolute_index]` instead, and build both masks exactly as
`Qwen3_5TextModel.forward` does. Verified safe: with `past_key_values=None` the gated delta net
touches no cache at all, builds its own causal chunk mask internally, and mutates nothing, so
re-running the same stack N times is deterministic and stateless.

NO CACHE ANYWHERE. All loop iterations run with `past_key_values=None`. Reusing a cache across
iterations would append K/V and corrupt the second pass. For teacher-forced evaluation this costs
nothing.

CORRECTNESS GATE. Before any looping claim, `verify_against_hf()` checks that manually running
encoder -> reasoning(1 pass) -> decoder -> norm -> lm_head reproduces the model's own forward
logits. If that fails, nothing else here means anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.masking_utils import create_causal_mask, create_recurrent_attention_mask

ROOT = r"D:\phoenix-models\qwen3.5-0.8b-base"
OUT = Path(__file__).resolve().parents[1]


@dataclass
class Split:
    encoder: tuple[int, int] = (0, 1)      # inclusive
    reasoning: tuple[int, int] = (2, 22)    # inclusive
    decoder: tuple[int, int] = (23, 23)      # inclusive


class LoopedQwen:
    def __init__(self, model, tokenizer, split: Split | None = None, device: str = "cuda"):
        self.model = model
        self.tok = tokenizer
        self.device = device
        # locate the text backbone: Qwen3_5ForCausalLM -> .model ; VL wrapper -> .model.language_model.
        # Evaluated lazily; a plain list comprehension would raise on whichever branch is absent.
        cands = [("model", getattr(model, "model", None)),
                 ("model.language_model",
                  getattr(getattr(model, "model", None), "language_model", None))]
        self.tm, self.holder = None, None
        for name, m in cands:
            if m is not None and hasattr(m, "layers") \
                    and len(m.layers) == model.config.num_hidden_layers:
                self.tm, self.holder = m, name
                break
        if self.tm is None:
            raise RuntimeError("could not locate the text backbone with .layers")
        self.cfg = self.tm.config
        self.split = split or Split()
        self.n_params = sum(p.numel() for p in model.parameters())
        for p in model.parameters():
            p.requires_grad_(False)
        model.eval()

    # ------------------------------------------------------------------ split helpers
    @property
    def n_layers(self):
        return len(self.tm.layers)

    def reasoning_layers(self):
        lo, hi = self.split.reasoning
        return list(range(lo, hi + 1))

    def layer_types_in(self, idxs):
        return [self.cfg.layer_types[i] for i in idxs]

    # ------------------------------------------------------------------ plumbing
    def prepare(self, input_ids, attention_mask):
        """Position ids, rotary embeddings and BOTH attention masks, built once per batch and
        reused across every loop iteration. All are pure functions of position/length/dtype,
        not of hidden states, so reuse is safe (verified against the modeling source)."""
        B, T = input_ids.shape
        pos4 = torch.arange(T, device=self.device).view(1, 1, -1).expand(4, B, -1)
        text_pos = pos4[0]
        rot_pos = pos4[1:]
        h0 = self.tm.embed_tokens(input_ids)
        pe = self.tm.rotary_emb(h0, rot_pos)
        mask_kwargs = {"config": self.cfg, "inputs_embeds": h0,
                       "attention_mask": attention_mask, "past_key_values": None,
                       "position_ids": text_pos}
        masks = {"full_attention": create_causal_mask(**mask_kwargs),
                 "linear_attention": create_recurrent_attention_mask(**mask_kwargs)}
        return h0, pe, masks, text_pos

    def run_stack(self, h, idxs, pe, masks, text_pos):
        """Run layers[idxs] over h. No cache, per-layer mask dispatch on the ABSOLUTE index."""
        for i in idxs:
            layer = self.tm.layers[i]
            h = layer(h,
                      position_embeddings=pe,
                      attention_mask=masks[self.cfg.layer_types[i]],
                      position_ids=text_pos,
                      past_key_values=None)
        return h

    def read_out(self, h, pe, masks, text_pos):
        """decoder + final norm + lm_head -> logits."""
        lo, hi = self.split.decoder
        h = self.run_stack(h, list(range(lo, hi + 1)), pe, masks, text_pos)
        return self.model.lm_head(self.tm.norm(h))

    # ------------------------------------------------------------------ the loop
    @torch.no_grad()
    def forward_states(self, input_ids, attention_mask, R: int = 1):
        """Return ONLY the hidden states [h_enc, h_1, ..., h_R]. No readouts.

        Preferred for anything that must visit every depth: this model's vocabulary is 248,320,
        so one [B, T, V] fp32 readout is ~3 GB at batch 16 and holding one per depth will OOM a
        12 GB card. Hidden states cost ~1/240 of that.
        """
        elo, ehi = self.split.encoder
        h0, pe, masks, text_pos = self.prepare(input_ids, attention_mask)
        h = self.run_stack(h0, list(range(elo, ehi + 1)), pe, masks, text_pos)
        states = [h]
        ridx = self.reasoning_layers()
        for _ in range(R):
            h = self.run_stack(h, ridx, pe, masks, text_pos)
            states.append(h)
        return {"states": states, "pe": pe, "masks": masks, "text_pos": text_pos}

    @torch.no_grad()
    def forward(self, input_ids, attention_mask, R: int = 1, read_all: bool = False):
        """R = number of passes through the reasoning block.

        R=1 reproduces the pretrained computation exactly (that is the unguided baseline).
        R>1 iterates the frozen reasoning block on its own output.

        Returns dict with logits at the final depth, plus (optionally) logits at every depth
        h_enc, h_1..h_R. The h_1..h_R states are what LoopCD consumes as a weak/strong pair.
        """
        elo, ehi = self.split.encoder
        h0, pe, masks, text_pos = self.prepare(input_ids, attention_mask)
        h = self.run_stack(h0, list(range(elo, ehi + 1)), pe, masks, text_pos)
        states = [h]                      # state 0: encoder output, before any reasoning
        ridx = self.reasoning_layers()
        for _ in range(R):
            h = self.run_stack(h, ridx, pe, masks, text_pos)
            states.append(h)              # states[r] == h_r, h_R is final
        logits = self.read_out(h, pe, masks, text_pos)
        out = {"logits": logits, "states": states, "n_states": len(states)}
        if read_all:
            out["logits_by_depth"] = [self.read_out(s, pe, masks, text_pos) for s in states]
        return out

    # ------------------------------------------------------------------ correctness gate
    @torch.no_grad()
    def verify_against_hf(self, input_ids, attention_mask, tol_atol: float = 2e-2):
        """My manual encoder->reasoning->decoder path must equal the model's own forward.

        Two checks, both mandatory before any looping result is believed:
          1. logits agreement with HF's own forward
          2. parameter identity against the on-disk safetensors, because loading a wrapper can
             silently random-initialize weights (the LFM2.5-Encoder-230M lesson)
        """
        mine = self.forward(input_ids, attention_mask, R=1)["logits"].float()
        ref = self.model(input_ids=input_ids, attention_mask=attention_mask,
                         use_cache=False).logits.float()
        d = (mine - ref).abs()
        agree = {"max_abs_diff": float(d.max()), "mean_abs_diff": float(d.mean()),
                 "argmax_agreement": float((mine.argmax(-1) == ref.argmax(-1)).float().mean()),
                 "atol": tol_atol}
        agree["logits_match"] = bool(agree["max_abs_diff"] < tol_atol
                                     and agree["argmax_agreement"] > 0.99)
        return agree


def weight_identity(model, root: str = ROOT) -> dict:
    """Compare live parameters against the checkpoint on disk.

    The checkpoint is a Qwen3_5ForConditionalGeneration, so its keys carry a
    `model.language_model.` prefix, which AutoModelForCausalLM remaps to `model.`. We look the
    disk side up under the ORIGINAL names and the live side under the remapped ones, and we
    check the tied lm_head against the embedding it must equal.
    """
    import json as _json
    from safetensors import safe_open
    rootp = Path(root)
    wmap = _json.loads((rootp / "model.safetensors.index.json").read_text())["weight_map"]
    live = dict(model.named_parameters())
    pairs = [
        ("model.language_model.embed_tokens.weight", "model.embed_tokens.weight"),
        ("model.language_model.norm.weight", "model.norm.weight"),
        ("model.language_model.layers.0.mlp.down_proj.weight",
         "model.layers.0.mlp.down_proj.weight"),
        ("model.language_model.layers.12.linear_attn.in_proj_qkv.weight",
         "model.layers.12.linear_attn.in_proj_qkv.weight"),
        ("model.language_model.layers.23.mlp.down_proj.weight",
         "model.layers.23.mlp.down_proj.weight"),
    ]
    worst, rows = 0.0, []
    for disk_k, live_k in pairs:
        shard = wmap.get(disk_k)
        p = live.get(live_k)
        if shard is None or p is None:
            rows.append({"disk": disk_k, "live": live_k,
                         "status": "missing_disk" if shard is None else "missing_live"})
            continue
        with safe_open(rootp / shard, framework="pt") as f:
            ref = f.get_tensor(disk_k)
        d = float((p.detach().float().cpu() - ref.float()).abs().max())
        worst = max(worst, d)
        rows.append({"disk": disk_k, "live": live_k, "max_abs_diff_vs_disk": d,
                     "disk_norm": round(float(ref.float().norm()), 4),
                     "live_norm": round(float(p.detach().float().norm()), 4)})
    # tied lm_head: config says tie_word_embeddings=true, so it must equal the embedding
    lm, emb = live.get("lm_head.weight"), live.get("model.embed_tokens.weight")
    tied = None
    if lm is not None and emb is not None:
        tied = {"lm_head_equals_embedding": bool(torch.equal(lm.detach().cpu(),
                                                             emb.detach().cpu())),
                "config_tie_word_embeddings": True}
    n_vis = sum(1 for k in live if k.startswith("model.visual"))
    return {"checked": rows, "worst_max_abs_diff": worst,
            "tied_head": tied,
            "vision_tower_loaded": n_vis > 0,
            "n_live_params": len(live),
            "verdict": "EXACT" if worst == 0.0 else ("CLOSE" if worst < 1e-2 else "MISMATCH"),
            "note": "the vision tower is intentionally absent: AutoModelForCausalLM loads the "
                    "text backbone only, which is what we want for a text-only loop"}


def load(root: str = ROOT, device: str = "cuda"):
    tok = AutoTokenizer.from_pretrained(root)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"
    model = AutoModelForCausalLM.from_pretrained(
        root, dtype=torch.bfloat16, low_cpu_mem_usage=True).to(device).eval()
    return LoopedQwen(model, tok, device=device), model


if __name__ == "__main__":
    torch.manual_seed(0)
    lq, model = load()
    wi = weight_identity(model)
    print("weight identity:", wi["verdict"], "worst", wi["worst_max_abs_diff"])
    for r in wi["checked"]:
        print("   ", r)
    print("holder:", lq.holder, "text class:", type(lq.tm).__name__)
    print("split:", lq.split)
    print("reasoning block size:", len(lq.reasoning_layers()))
    print("reasoning layer types:", lq.layer_types_in(lq.reasoning_layers()))
    print("params:", lq.n_params)

    tok = lq.tok
    enc = tok(["The capital of France is", "2 + 2 ="], return_tensors="pt",
              padding=True).to(lq.device)
    ag = lq.verify_against_hf(enc["input_ids"], enc["attention_mask"])
    print("\nCORRECTNESS GATE (manual path vs HF forward):", json.dumps(ag, indent=2))

    rec = {"abi": "loopus-qwen35/looped-v0.1", "root": ROOT, "split": lq.split.__dict__,
           "holder": lq.holder, "text_class": type(lq.tm).__name__,
           "params": lq.n_params,
           "reasoning_block_layers": len(lq.reasoning_layers()),
           "reasoning_layer_types": lq.layer_types_in(lq.reasoning_layers()),
           "weight_identity": wi, "correctness_gate": ag,
           "cache_policy": "past_key_values=None in every iteration; a shared cache would "
                           "append K/V across iterations and corrupt later passes"}
    (OUT / "looped-construction.json").write_text(json.dumps(rec, indent=2) + "\n")
    print("\nwritten:", OUT / "looped-construction.json")
