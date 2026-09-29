"""Markdown tables from results/ask-report-<head>.json. Imported by make_results.py; no number in RESULTS.md is typed by hand."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACES = ["middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"]
PRIMARY = "middle_plus_final"
ALPHAS = ["a60", "a50", "a40", "a30", "a20"]
LEVELS = ["0.4", "0.5", "0.6", "0.7"]


def report(head: str) -> dict:
    return json.loads((ROOT / "results" / f"ask-report-{head}.json").read_text(encoding="ascii"))


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def signal_table(r: dict) -> str:
    rows = ["| Surface | AP dedicated | AP existing head | AUROC dedicated | AUROC existing head |", "|---|---|---|---|---|"]
    for s in SURFACES:
        g = r["surfaces"][s]["signal"]
        rows.append(f"| {s}{' (primary)' if s == PRIMARY else ''} | {num(g['dedicated']['ap'])} | {num(g['baseline']['ap'])} | {num(g['dedicated']['auroc'])} | {num(g['baseline']['auroc'])} |")
    return "\n".join(rows)


def matched_table(r: dict) -> str:
    rows = ["| Surface | scorer | " + " | ".join(f"recall @ precision ≥ {p}" for p in LEVELS) + " |", "|---|---|" + "---|" * len(LEVELS)]
    for s in SURFACES:
        for scorer in ("dedicated", "baseline"):
            g = r["surfaces"][s]["signal"][scorer]["recall_at"]
            rows.append(f"| {s} | {scorer if scorer == 'dedicated' else 'existing head'} | " + " | ".join(pct(g[p]) for p in LEVELS) + " |")
    return "\n".join(rows)


def frontier_table(r: dict, surface: str = PRIMARY) -> str:
    rows = ["| α | dedicated: threshold | asks | precision | recall | existing head: threshold | asks | precision | recall |", "|---|---|---|---|---|---|---|---|---|"]
    for tag in ALPHAS:
        a = r["surfaces"][surface]["alphas"][tag]
        d, b = a["dedicated"], a["baseline"]
        rows.append(f"| {int(tag[1:]) / 100:.2f} | {d['threshold_ppm'] or 'omitted'} | {d['hold']['asks']} | {pct(d['hold']['precision'])} | {pct(d['hold']['recall'])} | "
                    f"{b['threshold_ppm'] or 'omitted'} | {b['hold']['asks']} | {pct(b['hold']['precision'])} | {pct(b['hold']['recall'])} |")
    return "\n".join(rows)


def controller_table(r: dict) -> str:
    rows = ["| Surface | controller | correct executed | harmful | harm rate | resolved coverage | correct asks | asks |", "|---|---|---|---|---|---|---|---|"]
    for s in SURFACES:
        c = r["surfaces"][s]["controller"]
        for label, o, asks in (("C1 alone", c["c1_only"], c["c1_ask_outcomes"]), ("C1 + ASK rule", c["combined"], c["combined_ask_outcomes"])):
            rows.append(f"| {s} | {label} | {o['correct_executed']} | {o['harmful']} | {pct(o['harm_rate'])} | {pct(o['coverage'])} | {asks['correct_asks']} | {asks['asks']} |")
    return "\n".join(rows)


def criteria_table(r: dict) -> str:
    rows = ["| Surface | A1 beats existing head | matched-precision wins | A2 usable rule | A3 acting tier intact |", "|---|---|---|---|---|"]
    for s in SURFACES:
        c = r["criteria"][s]
        mark = lambda k: "pass" if c[k] else "**fail**"  # noqa: E731
        rows.append(f"| {s}{' (primary)' if s == PRIMARY else ''} | {mark('A1_beats_existing_head')} | {c['A1_matched_precision_wins']} of 4 | {mark('A2_usable_rule')} | {mark('A3_acting_tier_intact')} |")
    return "\n".join(rows)
