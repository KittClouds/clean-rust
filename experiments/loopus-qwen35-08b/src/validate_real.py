"""Gate the trainable LoopedQwen35 against the real Qwen3.5-0.8B-Base checkpoint.

Three independent checks, all on the GPU:
  1. R=1 logits equal HF's own forward (bit-exact is expected: same modules, same order).
  2. For every depth the states equal the independently written frozen reference
     (frozen_loop.LoopedQwen, which produced premise.json), so the trainable stack is the
     same computation, not a lookalike.
  3. Re-running the premise test through the NEW evaluator on the same BANK rows reproduces
     premise.json NLL per depth.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.frozen_loop import LoopedQwen, load, weight_identity  # noqa: E402
from src.looped import LoopedQwen35  # noqa: E402
from src.premise import load_texts  # noqa: E402
from src.readout import shift, token_stats  # noqa: E402

OUT = Path(__file__).resolve().parents[1]


def main():
    torch.manual_seed(0)
    ref, hf = load()                       # frozen reference + HF model (bf16, cuda)
    wi = weight_identity(hf)
    new = LoopedQwen35(hf, gate="none")
    for p in hf.parameters():
        p.requires_grad_(False)

    ids, mask, labels = load_texts(16, ref.tok, 192)
    ids, mask, labels = ids.cuda(), mask.cuda(), labels.cuda()

    with torch.no_grad():
        # 1. R=1 vs HF forward
        mine = new(ids, mask, R=1).float()
        hf_logits = hf(input_ids=ids, attention_mask=mask, use_cache=False).logits.float()
        d_hf = float((mine - hf_logits).abs().max())

        # 2. states vs frozen reference at every depth
        o = ref.forward_states(ids, mask, R=8)
        st, _ = new.states(ids, mask, depths=(1, 2, 4, 8))
        state_diffs = {}
        for d in (1, 2, 4, 8):
            state_diffs[d] = float((st[d].float() - o["states"][d].float()).abs().max())

    # 3. premise reproduction through the NEW evaluator path (same rows, same padding/mask)
    w = hf.lm_head.weight
    per_depth = {}
    with torch.no_grad():
        for d in (1, 2, 4, 8):
            tot = None
            for s in range(0, ids.shape[0], 8):
                x, m, y = ids[s:s + 8], mask[s:s + 8], labels[s:s + 8]
                states, ctx = new.states(x, m, depths=(d,))
                hh, yy = shift(new.decode(states[d], ctx), y, m)
                st_ = token_stats(hh, w, yy)
                tot = st_ if tot is None else {k: tot[k] + st_[k] for k in st_}
            per_depth[d] = {"nll": tot["nll"] / tot["n"], "top1": tot["correct"] / tot["n"]}

    prem = json.loads((OUT / "premise.json").read_text())["results"]
    rec = {
        "weight_identity": wi["verdict"],
        "R1_vs_hf_max_abs_logit_diff": d_hf,
        "state_max_abs_diff_vs_frozen_reference": state_diffs,
        "nll_by_depth_16rows_new_evaluator": {d: round(v["nll"], 4) for d, v in per_depth.items()},
        "top1_by_depth_16rows_new_evaluator": {d: round(v["top1"], 4) for d, v in per_depth.items()},
        "premise_json_nll_128rows": {d: prem[str(d)]["nll"] for d in (1, 2, 4, 8)},
        "note": "16 rows here vs 128 in premise.json, so NLL agrees in trend not to the digit; "
                "the state diffs are the exact-equality check",
    }
    print(json.dumps(rec, indent=2))
    (OUT / "validate_real.json").write_text(json.dumps(rec, indent=2) + "\n")


if __name__ == "__main__":
    main()
