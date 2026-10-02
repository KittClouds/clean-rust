"""Step 1: can we even reach the text backbone, and what is its depth geometry?

LoopUS step 1 is a block decomposition guided by staged representation dynamics: early layers
transform embeddings fast, middle layers sit on a plateau, final layers jump toward the output
vocabulary. The LoopUS repo does NOT ship that analysis -- it hardcodes encoder/reasoning/decoder
indices per model (encoder 0..1, decoder 27..27, reasoning 2..26 on Qwen3-1.7B). So the split has
to be measured here rather than guessed.

Also establishing, before any looping, the structural facts that will decide the implementation:
  * what the text backbone is actually called on Qwen3_5ForConditionalGeneration;
  * the per-layer module types (18 linear_attention vs 6 full_attention);
  * what kwargs each layer type accepts, since the LoopUS blocks call every layer with one
    uniform signature and that will not work here;
  * whether output_hidden_states is populated at every depth.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

ROOT = r"D:\phoenix-models\qwen3.5-0.8b-base"
OUT = Path(__file__).resolve().parents[1]
TEXTS = [
    "The capital of France is Paris, and the capital of Japan is Tokyo.",
    "Move the onyx object from the chamber into the vault, then activate the lantern.",
    "32 * 64 = ",
    "A train leaves at 3pm travelling 60 km/h. How far does it go in 2 hours?",
]


def main() -> int:
    rec = {"abi": "loopus-qwen35/geometry-v0.1", "model_root": ROOT}
    cfg = AutoConfig.from_pretrained(ROOT)
    tc = getattr(cfg, "text_config", cfg)
    rec["config"] = {
        "outer_class": type(cfg).__name__, "outer_model_type": cfg.model_type,
        "text_class": type(tc).__name__, "text_model_type": tc.model_type,
        "num_hidden_layers": tc.num_hidden_layers, "hidden_size": tc.hidden_size,
        "num_attention_heads": tc.num_attention_heads, "num_key_value_heads": tc.num_key_value_heads,
        "head_dim": tc.head_dim, "intermediate_size": tc.intermediate_size,
        "vocab_size": tc.vocab_size, "tie_word_embeddings": cfg.tie_word_embeddings,
        "layer_types": list(tc.layer_types),
        "n_linear": sum(1 for t in tc.layer_types if t == "linear_attention"),
        "n_full": sum(1 for t in tc.layer_types if t == "full_attention"),
        "linear_conv_kernel_dim": getattr(tc, "linear_conv_kernel_dim", None),
        "mtp_num_hidden_layers": getattr(tc, "mtp_num_hidden_layers", None),
    }

    tok = AutoTokenizer.from_pretrained(ROOT)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForCausalLM.from_pretrained(
        ROOT, dtype=torch.bfloat16, low_cpu_mem_usage=True).to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)

    # ---- locate the text backbone and the layer list
    def find_layers(mod, path="", depth=0):
        if depth > 4:
            return None
        for name, child in mod.named_children():
            sub = getattr(child, "layers", None)
            if sub is not None and hasattr(sub, "__len__") and len(sub) == tc.num_hidden_layers:
                return path + "." + name if path else name, sub
            got = find_layers(child, path + "." + name if path else name, depth + 1)
            if got:
                return got
        return None

    found = find_layers(model)
    rec["layer_container"] = None
    if found:
        holder_path, layers = found
        rec["layer_container"] = holder_path
        rec["n_layers_found"] = len(layers)
        rec["per_layer"] = []
        for i, lyr in enumerate(layers):
            entry = {"i": i, "class": type(lyr).__name__,
                     "children": [n for n, _ in lyr.named_children()],
                     "attn_type": getattr(lyr, "attention_type", None)}
            for nm, sub in lyr.named_children():
                entry.setdefault("sub_types", {})[nm] = type(sub).__name__
            rec["per_layer"].append(entry)
        types = [e.get("attn_type") for e in rec["per_layer"]]
        rec["attn_type_matches_config"] = (types == list(tc.layer_types))
        rec["attn_type_sample"] = types

    # ---- forward and harvest hidden states
    enc = tok(TEXTS, return_tensors="pt", padding=True, truncation=True, max_length=256)
    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.inference_mode():
        out = model(**enc, output_hidden_states=True, use_cache=False)
    hs = out.hidden_states
    rec["hidden_states"] = {
        "available": hs is not None,
        "tuple_len": None if hs is None else len(hs),
        "expected": tc.num_hidden_layers + 1,
        "shape_last": None if hs is None else list(hs[-1].shape),
        "any_nan": None if hs is None else any(bool(torch.isnan(h.float()).any())
                                                  for h in hs),
    }
    lm = getattr(model, "lm_head", None)
    rec["lm_head"] = None if lm is None else {"class": type(lm).__name__,
                                             "out_features": getattr(lm, "out_features", None)}

    # ---- staged representation dynamics: cosine distance between CONSECUTIVE depths.
    # Computed on real (non-pad) tokens, averaged over the batch. This is the LoopUS step-1
    # signal, measured here because the repo does not ship it.
    if hs is not None:
        mask = enc["attention_mask"].bool()
        m3 = mask.unsqueeze(-1).float()
        vecs = []
        for h in hs:
            v = h.float()
            vecs.append(((v * m3).sum(1) / m3.sum(1).clamp(min=1)).cpu())   # [B,H] mean over real tokens
        n = len(vecs)
        cons, cos_to_last = [], []
        last = torch.nn.functional.normalize(vecs[-1], dim=-1)
        for i in range(n):
            a = torch.nn.functional.normalize(vecs[i], dim=-1)
            cons.append(None if i == 0 else round(float((a * torch.nn.functional.normalize(
                vecs[i - 1], dim=-1)).sum(-1).mean()), 6))
            cos_to_last.append(round(float((a * last).sum(-1).mean()), 6))
        rec["depth_profile"] = {
            "layer": list(range(n)),
            "cosine_to_previous": cons,
            "cosine_to_final": cos_to_last,
            "raw_std_by_layer": [round(float(v.std()), 4) for v in vecs],
        }
        d = [None if c is None else round(1.0 - c, 6) for c in cons]
        rec["consecutive_distance"] = d
        finite = [(i, x) for i, x in enumerate(d) if x is not None]
        if finite:
            best = max(finite, key=lambda kv: kv[1])[0]
            rec["largest_jump_between_layers"] = [best - 1, best]
            rec["largest_jump_value"] = d[best]
            tail = [(i, x) for i, x in finite if i >= n - 6]
            rec["mean_distance_last6_transitions"] = round(
                sum(x for _, x in tail) / max(len(tail), 1), 6)
            mid = [(i, x) for i, x in finite if 4 <= i <= n - 6]
            rec["mean_distance_middle_transitions"] = round(
                sum(x for _, x in mid) / max(len(mid), 1), 6)
        # per-token-position variability too: linear-attention layers may behave differently
        rec["norm_by_layer"] = [round(float(v.norm(dim=-1).mean()), 3) for v in vecs]

    p = OUT / "geometry.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    keep = {k: rec[k] for k in ("config", "layer_container", "hidden_states", "lm_head")
            if k in rec}
    print(json.dumps(keep, indent=2)[:2600])
    if "attn_type_sample" in rec:
        print("attn_type per layer:", rec["attn_type_sample"])
    if "consecutive_distance" in rec:
        print("\nlayer        :", " ".join(f"{i:5d}" for i in rec["depth_profile"]["layer"]))
        print("cos-to-prev  :", " ".join("  --  " if c is None else f"{c:5.3f}"
                                          for c in rec["consecutive_distance"]))
        print("cos-to-final :", " ".join(f"{c:5.3f}"
                                          for c in rec["depth_profile"]["cosine_to_final"]))
        print("raw std      :", " ".join(f"{s:5.2f}" for s in rec["depth_profile"]["raw_std_by_layer"]))
        print("\nlargest jump between layers:", rec.get("largest_jump_between_layers"),
              "value", rec.get("largest_jump_value"))
        print("mean dist middle transitions:", rec.get("mean_distance_middle_transitions"))
        print("mean dist last-6 transitions:", rec.get("mean_distance_last6_transitions"))
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
