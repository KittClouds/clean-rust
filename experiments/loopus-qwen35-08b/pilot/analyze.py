"""Summarise pilot result JSONs into markdown tables (results/PILOT_TABLES.md)."""
import json
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "results"
runs = {}
for f in sorted(R.glob("pilot_*_s*.json")):
    if f.name == "pilot_pretrain.json":
        continue
    j = json.loads(f.read_text())
    runs[(j["variant"], j["seed"])] = j

lines = []
P = lines.append
pre = json.loads((R / "pilot_pretrain.json").read_text())
P(f"Toy base: {pre['params']/1e6:.2f}M-param hybrid Qwen3.5 (8 layers, 3:1 linear:full), byte-level, "
  f"held-out bpc {pre['log'][-1]['heldout_bpc']:.3f} (NLL {pre['log'][-1]['heldout_nll']:.3f}).\n")

depths = sorted({int(d) for j in runs.values() for d in j["eval"]["depths"]})
P("### Held-out NLL by loop depth R (lower is better; nats/byte)\n")
P("| variant | seed | " + " | ".join(f"R={d}" for d in depths) + " |")
P("|---|---|" + "|".join("---" for _ in depths) + "|")
for (name, seed), j in runs.items():
    row = [f"{j['eval']['depths'][str(d)]['nll']:.3f}" if str(d) in j["eval"]["depths"] else "" for d in depths]
    P(f"| {name} | {seed} | " + " | ".join(row) + " |")

P("\n### Hidden-state norm growth (state norm at R / norm at R=1)\n")
P("| variant | " + " | ".join(f"R={d}" for d in depths if d > 1) + " |")
P("|---|" + "|".join("---" for d in depths if d > 1) + "|")
for (name, seed), j in runs.items():
    n1 = j["eval"]["depths"]["1"]["state_norm"]
    P(f"| {name} (s{seed}) | " + " | ".join(f"{j['eval']['depths'][str(d)]['state_norm']/n1:.2f}x" for d in depths if d > 1) + " |")

ctrl = next((j for (n, s), j in runs.items() if n == "control_noloop"), None)
if ctrl:
    c = ctrl["eval"]["depths"]["1"]["nll"]
    P(f"\n### Gain vs the no-loop continued-training control (control NLL {c:.4f}; negative = better than control)\n")
    P("| variant | seed | best R | NLL at best R | NLL(best) - control | NLL(R=1) - control |")
    P("|---|---|---|---|---|---|")
    for (name, seed), j in runs.items():
        if name.startswith("frozen") or name == "control_noloop":
            continue
        ds = j["eval"]["depths"]
        best = min(ds, key=lambda d: ds[d]["nll"])
        P(f"| {name} | {seed} | {best} | {ds[best]['nll']:.4f} | {ds[best]['nll']-c:+.4f} | {ds['1']['nll']-c:+.4f} |")

P("\n### LoopCD (training-free contrast) - ΔNLL vs plain h_R at the same depth (negative = LoopCD helps)\n")
P("| variant | R | premise h_R beats h_1 | best strategy | ΔNLL |")
P("|---|---|---|---|---|")
for (name, seed), j in runs.items():
    cd = j["eval"].get("loopcd")
    if not cd:
        continue
    for d in ("4", "8"):
        if d not in j["eval"]["depths"]:
            continue
        cands = {k: v[d]["delta_nll_vs_hR"] for k, v in cd.items() if d in v}
        k = min(cands, key=cands.get)
        prem = j["eval"]["premise_hR_beats_h1"].get(d)
        P(f"| {name} (s{seed}) | {d} | {prem} | {k} | {cands[k]:+.4f} |")

P("\n### Confidence early exit (best trained loop variants)\n")
for (name, seed), j in runs.items():
    ad = j.get("adaptive")
    if not ad or name in ("control_noloop",):
        continue
    P(f"**{name} (s{seed})**\n")
    P("| threshold | mean exit depth | NLL | top-1 |")
    P("|---|---|---|---|")
    for thr, r in ad.items():
        P(f"| {thr} | {r['mean_exit_depth']:.2f} | {r['nll']:.4f} | {r['top1']:.3f} |")
    P("")
(R / "PILOT_TABLES.md").write_text("\n".join(lines))
print("\n".join(lines))
