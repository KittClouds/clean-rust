"""Phase 2 candidate preflight: measure the true canonical candidate maximum and receipt
exactly what the Phase 1 cap of 24 did to this lane's population.

This is an identity audit, not a scientific gate.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

BANK = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase2")
OUT.mkdir(parents=True, exist_ok=True)
PHASE1_CAP = 24


def audit(split: str) -> dict:
    counts = []
    for line in (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8"):
        if not line.strip():
            continue
        w = json.loads(line)
        if "@" in w["world_id"]:
            continue
        counts.append(len(w.get("available_actions") or []))

    hist = Counter(counts)
    n = len(counts)
    over = [c for c in counts if c > PHASE1_CAP]
    at = [c for c in counts if c == PHASE1_CAP]
    return {
        "split": split,
        "canonical_worlds": n,
        "m_max": max(counts),
        "m_min": min(counts),
        "mean_m": round(sum(counts) / n, 3),
        "phase1_cap": PHASE1_CAP,
        "rows_over_cap": len(over),
        "rows_at_cap": len(at),
        "candidates_lost_to_cap": sum(over) - len(over) * PHASE1_CAP if over else 0,
        "candidates_in_over_cap_rows": sum(over),
        "pct_rows_excluded": round(100.0 * len(over) / n, 4),
        "histogram_top": dict(sorted(hist.items())[-12:]),
        "histogram_above_20": {k: v for k, v in sorted(hist.items()) if k > 20},
    }


def main() -> int:
    a = {s: audit(s) for s in ("TRAIN", "DEV")}
    m_max = max(a[s]["m_max"] for s in a)
    lost_rows = sum(a[s]["rows_over_cap"] for s in a)
    lost_cands = sum(a[s]["candidates_in_over_cap_rows"] for s in a)
    rec = {
        "abi": "phase2-semantic-interface/candidate-preflight-v0.1",
        "lane": "bidirectional (Lepori)",
        "question": "max canonical candidate count over the frozen TRAIN and DEV populations",
        "m_max": m_max,
        "phase1_cap": PHASE1_CAP,
        "phase1_truncated_anything": bool(lost_rows > 0),
        "per_split": a,
        "combined": {
            "canonical_worlds": sum(a[s]["canonical_worlds"] for s in a),
            "rows_excluded_by_cap": lost_rows,
            "candidates_never_reachable": lost_cands,
            "note": "data.build() DROPS a row entirely when len(available_actions) > m_cap, so "
                    "the loss is whole-row exclusion, not partial truncation of a retained row",
        },
        "phase2_contract": {
            "rule": "retain every canonical candidate",
            "m_cap": m_max,
            "padding": "-1 entity indices, cand_type 0, mask 0",
            "ordering": "canonical available_actions order, deterministic",
            "note": "max_args must also be re-measured: cent pads each candidate's entity args",
        },
    }
    # max entity args per action, since cent is padded to that width
    for split in ("TRAIN", "DEV"):
        w_max = 0
        for line in (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8"):
            if not line.strip():
                continue
            w = json.loads(line)
            if "@" in w["world_id"]:
                continue
            ents = {e["id"] for e in w["entities"]}
            for act in (w.get("available_actions") or []):
                n = 0
                for v in (act.get("args") or {}).values():
                    vs = v if isinstance(v, list) else [v]
                    n += sum(1 for x in vs if isinstance(x, str) and x in ents)
                w_max = max(w_max, n)
        rec["phase2_contract"]["max_args_" + split] = w_max
    rec["phase2_contract"]["max_args"] = max(
        rec["phase2_contract"]["max_args_TRAIN"], rec["phase2_contract"]["max_args_DEV"])
    rec["phase2_contract"]["phase1_max_args"] = 3

    p = OUT / "candidate-preflight.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({k: rec[k] for k in
                      ("m_max", "phase1_cap", "phase1_truncated_anything")}, indent=2))
    print(json.dumps(rec["combined"], indent=2))
    print("max_args measured:", rec["phase2_contract"]["max_args"],
          "phase1 used:", rec["phase2_contract"]["phase1_max_args"])
    for s in a:
        print(f"  {s}: m_max={a[s]['m_max']} rows_over_cap={a[s]['rows_over_cap']} "
              f"cands_in_those={a[s]['candidates_in_over_cap_rows']} "
              f"({a[s]['pct_rows_excluded']}%)")
    print("written:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
