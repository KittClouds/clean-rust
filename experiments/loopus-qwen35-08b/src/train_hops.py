"""Train / evaluate the looped Qwen3.5 on serial k-hop pointer following.

One CLI covers every arm of the experiment:
  * zero-shot pretrained:   --steps 0 --gate none               (format unseen: ~chance)
  * no-loop control:        --N 1 --n-sup 1                      (LoRA fine-tune, depth 1 only)
  * looped:                 --N 4 --n-sup 2 --gate sigmoid --g0 0.5

All arms see the same example stream (seeded) and the same LoRA/optimizer settings.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import torch

from . import hops as H
from .train_loopus import ConfidenceHead, TrainCfg, build_model, save_trainable, set_trainable, train


def fmt_table(res: dict, ks) -> str:
    rows = []
    for d, per in res.items():
        cells = " ".join(f"{per[k]['acc']*100:5.1f}" if k in per else "   - " for k in ks)
        rows.append(f"    R={d:<2d} all={per['all']['acc']*100:5.1f} | k: {cells}")
    return "\n".join(rows)


def main():
    from transformers import AutoModelForCausalLM, AutoTokenizer

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"D:\phoenix-models\qwen3.5-0.8b-base")
    ap.add_argument("--k-train", type=int, default=6, help="train on k in 1..K")
    ap.add_argument("--k-eval", type=int, default=8, help="evaluate k in 1..K (beyond k-train = extrapolation)")
    ap.add_argument("--n-nodes", type=int, default=10)
    ap.add_argument("--eval-n", type=int, default=200, help="eval examples per k")
    ap.add_argument("--eval-depths", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--gate", default="sigmoid", choices=["loopus", "sigmoid", "none"])
    ap.add_argument("--g0", type=float, default=0.5)
    ap.add_argument("--scope", default="lora", choices=["gate", "lora"])
    ap.add_argument("--lora-rank", type=int, default=32)
    ap.add_argument("--N", type=int, default=4)
    ap.add_argument("--n-sup", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--gate-lr-mult", type=float, default=100.0)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--lr-min-frac", type=float, default=0.1)
    ap.add_argument("--beta", type=float, default=1.0)
    ap.add_argument("--conf-weight", type=float, default=0.1)
    ap.add_argument("--depth-matched", type=int, default=0,
                    help="c>0: at depth t supervise only examples with k <= c*t (latent-CoT-style curriculum)")
    ap.add_argument("--grad-checkpoint", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint", help="eval-only: load a trained arm (use with --steps 0)")
    ap.add_argument("--init-from", help="warm-start LoRA + confidence head from a checkpoint, then train "
                                        "(new modules such as a gate keep their fresh init)")
    ap.add_argument("--loopcd-depths", type=int, nargs="*", default=[],
                    help="eval-only: also run the LoopCD sweep at these recursion depths")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda"
    tok = AutoTokenizer.from_pretrained(a.model)
    hf = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16).to(dev)
    gate_kwargs = {"g0": a.g0} if a.gate == "sigmoid" else None
    if a.checkpoint:
        from .train_loopus import load_checkpoint
        model, conf, _ = load_checkpoint(hf, a.checkpoint, dev)
    else:
        model = build_model(hf, a.gate, a.scope, a.lora_rank, None, a.grad_checkpoint, gate_kwargs)
        conf = ConfidenceHead(hf.config.hidden_size).to(dev)
    if a.init_from:
        from .train_loopus import load_trainable
        load_trainable(model, conf, a.init_from, map_location=dev)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = TrainCfg(n_reasoning_steps=a.N, n_supervision=min(a.n_sup, a.N), lr=a.lr, gate_lr_mult=a.gate_lr_mult,
                   warmup=a.warmup, lr_min_frac=a.lr_min_frac, beta=a.beta, conf_weight=a.conf_weight,
                   seed=a.seed, log_every=25, scope=a.scope)
    meta = dict(vars(a), gate_kwargs=gate_kwargs, lora_alpha=None, cfg=asdict(cfg), task="hops")
    (out / "args.json").write_text(json.dumps(meta, indent=2))

    ks = list(range(1, a.k_eval + 1))
    # eval set: fixed seed, disjoint from the training stream (different seed; fresh random graphs)
    eval_ex = H.build_set(tok, a.eval_n * len(ks), ks, seed=10_000 + a.seed, n_nodes=a.n_nodes)
    n_tr = sum(p.numel() for p in set_trainable(model, a.scope)) if a.steps > 0 else 0
    if a.steps == 0:
        for p in model.parameters():
            p.requires_grad_(False)
    print(f"trainable params: {n_tr/1e6:.2f}M   eval examples: {len(eval_ex)}", flush=True)
    elog = (out / "eval_log.jsonl").open("a", encoding="utf-8")

    def run_eval(step: int, train_loss=None):
        res = H.evaluate_hops(model, tok, eval_ex, a.eval_depths, device=dev)
        elog.write(json.dumps({"step": step, "train_loss": train_loss, "res": {str(d): v for d, v in res.items()}}) + "\n")
        elog.flush()
        print(f"[eval] step {step}  (test accuracy %, by hop count k; k>{a.k_train} never trained)\n"
              + fmt_table(res, ks), flush=True)

    if a.steps == 0:
        run_eval(0)
        for R in a.loopcd_depths:
            cd = H.evaluate_hops_loopcd(model, tok, eval_ex, R, device=dev)
            (out / f"loopcd_R{R}.json").write_text(json.dumps(cd, indent=2))
            print(f"[loopcd] R={R} (reference h_1); accuracy % by variant, then by k", flush=True)
            for name, per in cd.items():
                cells = " ".join(f"{per[k]['acc']*100:5.1f}" if k in per else "   - " for k in ks)
                print(f"    {name:<16s} all={per['all']['acc']*100:5.1f} nll={per['all']['nll']:.3f} | k: {cells}", flush=True)
        return

    def on_step(step: int, rec: dict) -> None:
        if step % a.eval_every == 0 or step == a.steps - 1:
            run_eval(step, rec["loss"])
            save_trainable(model, conf, str(out / "trainable.pt"), meta)

    batches = H.train_batches(tok, list(range(1, a.k_train + 1)), a.batch_size, a.seed, dev, a.n_nodes,
                              with_ks=a.depth_matched > 0)
    hist = train(model, conf, batches, a.steps, cfg, on_step=on_step,
                 label_fn=H.depth_matched(a.depth_matched) if a.depth_matched > 0 else None)
    save_trainable(model, conf, str(out / "trainable.pt"), meta)
    (out / "history.json").write_text(json.dumps({"cfg": asdict(cfg), "history": hist}))
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
