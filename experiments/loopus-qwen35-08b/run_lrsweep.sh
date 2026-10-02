#!/usr/bin/env bash
# LR sweep on the no-loop control (N=1): which LoRA lr improves held-out NLL instead of wrecking it?
cd "$(dirname "$0")"
for LR in 3e-6 1e-5 3e-5; do
  python -u -m src.train_loopus --train-corpus corpus/wiki_train.jsonl --val-corpus corpus/wiki_val.jsonl --max-docs 1500 \
    --steps 200 --batch-size 4 --seq-len 512 --lr $LR --warmup 20 --eval-every 50 --eval-batches 12 --grad-checkpoint \
    --scope lora --lora-rank 32 --N 1 --n-sup 1 --out runs/lr_$LR > runs/lr_$LR.log 2>&1
done
