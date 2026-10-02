#!/usr/bin/env bash
# Pilot 1: no-loop control vs looped LoRA+gate arm. Identical data order/seed/optimizer.
set -u
cd "$(dirname "$0")"
COMMON="--train-corpus corpus/wiki_train.jsonl --val-corpus corpus/wiki_val.jsonl --max-docs 1500 \
  --steps 1500 --batch-size 4 --seq-len 512 --lr 1e-5 --gate-lr-mult 100 --warmup 100 --eval-every 100 --eval-batches 12 --grad-checkpoint --scope lora --lora-rank 32"
python -u -m src.train_loopus $COMMON --N 1 --n-sup 1 --out runs/p1_control_N1 > runs/p1_control_N1.log 2>&1
python -u -m src.train_loopus $COMMON --N 8 --n-sup 3 --gate sigmoid --out runs/p1_loop_N8_sigmoid > runs/p1_loop_N8_sigmoid.log 2>&1
