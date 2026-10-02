#!/usr/bin/env bash
# Hop experiment 1 (permutation task): no-loop control vs looped (gate open). Same stream/LoRA/optimizer.
set -u
cd "$(dirname "$0")"
COMMON="--steps 2000 --batch-size 32 --lr 1e-4 --gate-lr-mult 10 --warmup 50 --eval-every 250 --eval-n 200 \
  --k-train 6 --k-eval 8 --eval-depths 1 2 4 8"
python -u -m src.train_hops $COMMON --N 1 --n-sup 1 --gate none --out runs/h1_control_N1 > runs/h1_control_N1.log 2>&1
python -u -m src.train_hops $COMMON --N 4 --n-sup 2 --gate sigmoid --g0 0.5 --out runs/h1_loop_N4_sig0.5 > runs/h1_loop_N4_sig0.5.log 2>&1
