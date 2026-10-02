#!/usr/bin/env bash
# Hop experiment 4: shortcut-resistant task (26 nodes). Control first; depth-matching constant c is then
# set PROSPECTIVELY from the control's measured one-pass ceiling = largest k (contiguous from k=1) with
# >=90% accuracy at R=1 on the final eval (floor 2). Then the depth-matched loop arm. Same stream/LoRA/optimizer.
set -u
cd "$(dirname "$0")"
COMMON="--n-nodes 26 --steps 1500 --batch-size 16 --lr 1e-4 --gate-lr-mult 10 --warmup 50 --eval-every 250 --eval-n 100 \
  --k-train 12 --k-eval 16 --eval-depths 1 2 3 4"
python -u -m src.train_hops $COMMON --N 1 --n-sup 1 --gate none --out runs/h4_control_N1 > runs/h4_control_N1.log 2>&1
C=$(python - <<'PY'
import json
last = [json.loads(l) for l in open("runs/h4_control_N1/eval_log.jsonl")][-1]["res"]["1"]
c = 0
for k in range(1, 17):
    if last.get(str(k), {}).get("acc", 0) >= 0.9: c = k
    else: break
print(max(c, 2))
PY
)
echo "PROSPECTIVE c=$C (control one-pass ceiling)" > runs/h4_c.txt
python -u -m src.train_hops $COMMON --N 4 --n-sup 2 --gate sigmoid --g0 0.5 --depth-matched $C --out runs/h4_dm_N4 > runs/h4_dm_N4.log 2>&1
