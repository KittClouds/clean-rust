#!/usr/bin/env bash
# Depth test (exp 6). Is there ANY benefit from 2x depth on the 26-node task, with and without weight sharing?
# Both arms warm-start from the exp-4 control (one-pass ceiling k~4), same stream/lr/steps as exp 5, loss at the FINAL
# depth only, FULL backprop through both passes, no gate (plain stacking). Comparator = exp-5 continued control (R=1).
#   A: separate LoRA adapter per pass (upper bound: a 2x deeper network)     B: shared adapters (a true loop)
# Pre-registered criterion (same as exp 5): R=2 accuracy beats continued-control R=1 by >= 5 pts averaged over k=5..8.
set -u
cd "$(dirname "$0")"
COMMON="--n-nodes 26 --steps 1000 --batch-size 16 --lr 5e-5 --warmup 50 --eval-every 250 --eval-n 100 \
  --k-train 12 --k-eval 16 --eval-depths 1 2 --seed 1 --init-from runs/h4_control_N1/trainable.pt \
  --N 2 --gate none --bptt --grad-checkpoint"
python -u -m src.train_hops $COMMON --lora-passes 2 --out runs/h6_A_perpass > runs/h6_A_perpass.log 2>&1
python -u -m src.train_hops $COMMON --lora-passes 1 --out runs/h6_B_shared > runs/h6_B_shared.log 2>&1
