#!/usr/bin/env bash
# Hop experiment 5: post-train an ALREADY-CAPABLE one-pass model into a loop (what LoopUS does), 26 nodes.
# Both arms warm-start from the exp-4 control (one-pass ceiling k~4, 1500 steps), train 1000 more steps on the same
# stream (seed 1), same LoRA/optimizer/lr. Arm A: control continued (N=1). Arm B: depth-matched loop, c=4 (the
# prospective constant from exp 4), N=3, gate g0=0.5.
# Pre-registered criterion: loop best-R accuracy exceeds continued-control R=1 by >= 5 pts averaged over k=5..8.
set -u
cd "$(dirname "$0")"
COMMON="--n-nodes 26 --steps 1000 --batch-size 16 --lr 5e-5 --gate-lr-mult 10 --warmup 50 --eval-every 250 --eval-n 100 \
  --k-train 12 --k-eval 16 --eval-depths 1 2 3 4 --seed 1 --init-from runs/h4_control_N1/trainable.pt"
python -u -m src.train_hops $COMMON --N 1 --n-sup 1 --gate none --out runs/h5_control_cont > runs/h5_control_cont.log 2>&1
python -u -m src.train_hops $COMMON --N 3 --n-sup 2 --gate sigmoid --g0 0.5 --depth-matched 4 --out runs/h5_dm_loop > runs/h5_dm_loop.log 2>&1
