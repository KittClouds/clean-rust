#!/usr/bin/env bash
# Hop experiment 2: put training demand BEYOND one-pass capacity (k up to 12; eval to 16).
# Exp. 1 (k<=6) showed one pass can learn k<=5-6, so depth had no gradient pressure and iterations
# collapsed to identity. Same stream/LoRA/optimizer for both arms.
set -u
cd "$(dirname "$0")"
COMMON="--steps 2000 --batch-size 32 --lr 1e-4 --gate-lr-mult 10 --warmup 50 --eval-every 250 --eval-n 100 \
  --k-train 12 --k-eval 16 --eval-depths 1 2 3 4 6"
python -u -m src.train_hops $COMMON --N 1 --n-sup 1 --gate none --out runs/h2_control_N1 > runs/h2_control_N1.log 2>&1
python -u -m src.train_hops $COMMON --N 3 --n-sup 2 --gate sigmoid --g0 0.5 --out runs/h2_loop_N3_sig0.5 > runs/h2_loop_N3_sig0.5.log 2>&1
