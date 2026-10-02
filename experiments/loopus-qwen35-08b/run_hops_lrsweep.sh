#!/usr/bin/env bash
# Hop-task LR sweep on the no-loop control (N=1).
cd "$(dirname "$0")"
for LR in 3e-5 1e-4 3e-4; do
  python -u -m src.train_hops --N 1 --n-sup 1 --steps 500 --eval-every 125 --lr $LR --gate none \
    --eval-depths 1 --eval-n 100 --out runs/hlr_$LR > runs/hlr_$LR.log 2>&1
done
