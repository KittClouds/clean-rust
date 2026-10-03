"""Audit the causal `first` coordinate on TEST-JOINT.

Observation under audit: on causal, route exactness at the `first` coordinate is 0.349 on
IID and 0.361 on JOINT — it does not degrade at all, while `mean`/`full_mean` collapse
(0.600 -> 0.164, 0.607 -> 0.158). A causal first-token state is a prefix summary, so this
deserves explanation before it is interpreted as "early representations generalize better".

The audit is deliberately label-blind first: what is even present at that position?
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

import torch

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\results")


def read_jsonl(p, limit=None):
    out = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=3000)
    ap.add_argument("--batch", type=int, default=24)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    from src.extract_primitives import load_substrate

    tok, model, _ = load_substrate("causal", device)

    report = {"audit": "causal first-coordinate, IID vs JOINT", "splits": {}}
    for split in ("TEST-IID", "TEST-JOINT"):
        rows = read_jsonl(BANK / "public" / "test-inputs" / f"{split}.jsonl", args.cap)
        stats = {"n": len(rows), "char_len": [], "token_len": [], "surface": Counter(),
                 "first_token_id": Counter(), "first_token_str": Counter(),
                 "n_lines": [], "entities_in_prefix": [], "prefix_has_goal": 0,
                 "prefix_has_predicate": 0}
        PREDS = ["connects to", "is in", "requires", "blocked", "is before",
                 "part of", "enables", "owns", "Goal:"]
        for s in range(0, len(rows), args.batch):
            ch = rows[s:s + args.batch]
            enc = tok([r["input_text"] for r in ch], return_tensors="pt", padding=True,
                      truncation=True, max_length=512)
            ids = enc["input_ids"]
            att = enc["attention_mask"]
            for k, r in enumerate(ch):
                n = int(att[k].sum())
                toks = ids[k][:n].tolist()
                stats["token_len"].append(n)
                stats["char_len"].append(len(r["input_text"]))
                stats["surface"][r.get("surface_family", "?")] += 1
                stats["first_token_id"][toks[0]] += 1
                stats["first_token_str"][tok.decode([toks[0]]).strip()] += 1
                stats["n_lines"].append(r["input_text"].count("\n") + 1)
                head = tok.decode(toks[:12])
                stats["entities_in_prefix"].append(
                    sum(1 for e in r.get("bindings", []) if (e.get("mention") or "") in head))
                if "Goal" in head:
                    stats["prefix_has_goal"] += 1
                if any(p in head for p in PREDS):
                    stats["prefix_has_predicate"] += 1
        summ = lambda L: (round(sum(L) / len(L), 2) if L else 0)
        report["splits"][split] = {
            "n": stats["n"],
            "mean_tokens": summ(stats["token_len"]),
            "mean_chars": summ(stats["char_len"]),
            "mean_lines": summ(stats["n_lines"]),
            "surface_mix": dict(stats["surface"].most_common()),
            "distinct_first_tokens": len(stats["first_token_str"]),
            "top_first_tokens": dict(stats["first_token_str"].most_common(5)),
            "mean_entities_in_first_12_tokens": summ(stats["entities_in_prefix"]),
            "frac_prefix_contains_goal": round(stats["prefix_has_goal"] / max(len(rows), 1), 4),
            "frac_prefix_contains_predicate": round(stats["prefix_has_predicate"] / max(len(rows), 1), 4),
        }

    # label-blind counterfactual: does shuffling text order change first-token identity?
    # and is first-token identity at all predictive of the label?
    report["conclusion_pending"] = True
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "first-coordinate-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
