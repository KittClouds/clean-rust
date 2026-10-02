#!/usr/bin/env bash
# Hop experiment 3: DEPTH-MATCHED supervision. At recursion depth t only examples with k <= c*t
# are supervised (c=4 ~ the one-pass ceiling measured in exp 1/2 controls). Depth 1 therefore
# cannot be asked to solve hard examples, so accuracy on k>4 must come from later passes.
# Compared against the exp-2 N=1 control (same stream/LoRA/optimizer, k<=12).
set -u
cd "$(dirname "$0")"
python -u -m src.train_hops --steps 1500 --batch-size 32 --lr 1e-4 --gate-lr-mult 10 --warmup 50 --eval-every 250 --eval-n 100 \
  --k-train 12 --k-eval 16 --eval-depths 1 2 3 4 --N 3 --n-sup 2 --gate sigmoid --g0 0.5 --depth-matched 4 \
  --out runs/h3_dm4_N3 > runs/h3_dm4_N3.log 2>&1
