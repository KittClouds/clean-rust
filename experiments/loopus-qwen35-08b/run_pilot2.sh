#!/usr/bin/env bash
# Pilot 2: force the recurrence open. Pilot 1 (g0=0.05) left the gate closed (mean g 0.0494 after 600
# steps), so depth was inert. Here the gate starts open so depth carries signal and the LoRA must
# learn to make iteration useful. Same data/seed/LR/optimizer as the N=1 control.
set -u
cd "$(dirname "$0")"
COMMON="--train-corpus corpus/wiki_train.jsonl --val-corpus corpus/wiki_val.jsonl --max-docs 1500 \
  --steps 1000 --batch-size 4 --seq-len 512 --lr 1e-5 --gate-lr-mult 100 --warmup 100 --eval-every 100 --eval-batches 12 \
  --grad-checkpoint --scope lora --lora-rank 32 --N 4 --n-sup 2"
python -u -m src.train_loopus $COMMON --gate sigmoid --g0 0.5 --out runs/p2_loop_N4_sig0.5 > runs/p2_loop_N4_sig0.5.log 2>&1
python -u -m src.train_loopus $COMMON --gate loopus --out runs/p2_loop_N4_loopusgate > runs/p2_loop_N4_loopusgate.log 2>&1
