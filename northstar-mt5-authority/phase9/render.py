from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd


def pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def markdown_table(frame: pd.DataFrame, columns: list[str], limit: int | None = None) -> list[str]:
    shown = frame[columns].head(limit) if limit else frame[columns]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for _, row in shown.iterrows():
        values = []
        for column in columns:
            value = row[column]
            if isinstance(value, float):
                value = f"{value:.4g}"
            values.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def write_markdown(result: dict, path: Path) -> None:
    s = result["summary"]
    d = s["diagnostics"]
    coverage = result["coverage"]
    continuous = result["continuous"]
    lines = [
        "# RG2 Phase 9 — coverage and QC", "",
        f"**Decision: `{s['phase9_decision']}`**", "",
        "This report describes dataset geometry only. It contains no strategy labels, win rate, feature selection, or model.", "",
        "## Corpus integrity", "",
        f"- Status: **{s['status']}**",
        f"- Runs: {s['runs']} across {s['instruments']} instruments and {s['data_sources']} data source",
        f"- Observed bars: {s['observed_bars']:,} ({s['observed_bar_hours']:.1f} bar-hours)",
        f"- Scheduled window span: {s['scheduled_span_hours']:.1f} hours",
        f"- Data gaps: {s['unexpected_data_gaps']} unexpected; profile bar delta {s['profile_bar_gap']}",
        f"- Replay: {s['replay_status']} ({s['replay_count']} exact duplicate)",
        f"- Replay canonical hash agreement: {s['replay_hash_agreement']}",
        f"- Relational invariant failures: {len(s['relational_invariant_failures'])}",
        f"- Corpus fingerprint: `{s['corpus_fingerprint']}`", "",
        f"- Semantic result hash: `{s['semantic_result_sha256']}`", "",
        "## Population", "",
        f"- Nodes: {s['nodes_created']:,} created; {s['nodes_retired']:,} retired; {s['nodes_persisted_at_cutoff']:,} persisted at cutoff",
        f"- Events: {s['events']:,}", f"- Attempts: {s['attempts']:,}",
        f"- Episodes: {s['episodes']:,} ({s['episodes_resolved']:,} resolved, {s['episodes_right_censored']:,} right-censored; {pct(s['episode_censoring_rate'])})",
        f"- Transits: {s['transits']:,}",
        f"- Behavioral episode resolutions: {s['behavioral_resolutions']:,} ({pct(s['behavioral_resolution_share'])})", "",
        "## Principal geometry finding", "",
        f"- `NODE_RETIRED`: {d['node_retired_resolved']:,} resolved + {d['node_retired_censored']:,} censored/provisional rows; {pct(d['node_retired_share_of_resolved'])} of resolved episodes.",
        f"- Those resolved retirement episodes begin on nodes with median age **{d['node_retired_node_age_median_seconds']:.0f}s**, median width **{d['node_retired_width_median_atr']:.3f} ATR**, and median duration **{d['node_retired_duration_median_seconds']:.0f}s**; {d['node_retired_under_1h_count']:,}/{d['node_retired_resolved']:,} begin before node age one hour.",
        f"- `TIMEOUT`: {d['timeout_resolved']:,} resolved + {d['timeout_censored']:,} censored/provisional rows; {pct(d['timeout_share_of_resolved'])} of resolved episodes.",
        f"- Those resolved timeout episodes begin on nodes with median age **{d['timeout_node_age_median_seconds']/3600:.2f}h**, median width **{d['timeout_width_median_atr']:.3f} ATR**, and median duration **{d['timeout_duration_median_seconds']/3600:.2f}h**; {d['timeout_over_1atr_count']:,}/{d['timeout_resolved']:,} are wider than 1 ATR.",
        f"- Structurally retired nodes have median observed lifetime **{d['retired_node_lifetime_median_seconds']/3600:.2f}h**. Nodes persisted at cutoff have median observed age **{d['persisted_node_observed_age_median_seconds']/3600:.2f}h** and remain censored.",
        "- This separation is descriptive. It does not establish whether lifecycle churn or grammar thresholds should change.", "",
    ]
    for title, unit, dimension in [
        ("Instrument coverage", "episode", "instrument"), ("Regional coverage", "episode", "initial_region"),
        ("Auction resolutions", "episode", "resolution"), ("Attempt ordinal", "attempt", "ordinal"),
        ("Producer combinations", "attempt", "producer_combo"), ("Node lifecycle", "node", "lifecycle"),
    ]:
        table = coverage[(coverage.unit == unit) & (coverage.dimension == dimension)].sort_values("count", ascending=False).copy()
        table["share"] = table["share"].map(pct)
        table["censoring_rate"] = table["censoring_rate"].map(pct)
        lines += [f"## {title}", ""] + markdown_table(table, ["value", "count", "share", "censored_count", "censoring_rate"]) + [""]

    selected = ["duration_seconds", "penetration_atr", "approach_efficiency", "inside_seconds",
                "node_width_atr", "node_age_seconds", "start_median_sigma",
                "feature_price_from_cog_sigma", "feature_cog_median_gap_sigma",
                "feature_regional_sigma_log_change_per_bar", "distance_atr"]
    table = continuous[continuous.metric.isin(selected)].copy()
    lines += ["## Continuous distributions", ""] + markdown_table(
        table, ["unit", "metric", "count", "missing_count", "censoring_rate", "p05", "median", "p95", "mean", "std"]
    ) + [""]

    readiness = result["readiness"]
    lines += ["## Question-readiness ledger", ""] + markdown_table(
        readiness, ["question", "unit", "evidence_count", "readiness", "reason"]
    ) + ["", "## QC interpretation", "",
        "- The corpus is coherent and replay-stable.",
        "- Node retirement and timeout dominate episode resolution; that is a semantic coverage finding, not a trading result.",
        "- Right-censored episodes may retain their latest provisional resolution. Completed behavioral evidence excludes those rows.",
        "- Extreme regional cells and accepted/retest outcomes remain too sparse for conditional research.",
        "- Percentages in coverage tables always retain counts and unit-specific censoring rates.",
        "- Persisted nodes at cutoff are censored lifecycle observations, not inferred retirements.", "",
        "## Output contract", "",
        "The adjacent CSV/JSON artifacts contain the full coverage, cross-coverage, missingness, continuous-distribution, node-lifecycle, run-QC, and readiness tables.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _html_table(frame: pd.DataFrame, columns: list[str], limit: int = 40) -> str:
    rows = []
    for _, row in frame[columns].head(limit).iterrows():
        cells = "".join(f"<td>{html.escape(str(row[c]))}</td>" for c in columns)
        rows.append(f"<tr>{cells}</tr>")
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _bar_table(frame: pd.DataFrame) -> str:
    maximum = max(frame["count"].max(), 1)
    rows = []
    for _, row in frame.iterrows():
        width = 100 * row["count"] / maximum
        rows.append(
            f"<div class='barrow'><span>{html.escape(str(row['value']))}</span>"
            f"<div class='track'><i style='width:{width:.2f}%'></i></div>"
            f"<b>{int(row['count']):,}</b><em>{100*row['share']:.2f}% · cens {100*row['censoring_rate']:.2f}%</em></div>"
        )
    return "".join(rows)


def write_html(result: dict, path: Path) -> None:
    s, coverage = result["summary"], result["coverage"]
    panels = []
    for title, unit, dimension in [
        ("Instrument", "episode", "instrument"), ("Region", "episode", "initial_region"),
        ("Resolution", "episode", "resolution"), ("Producer combination", "attempt", "producer_combo"),
    ]:
        table = coverage[(coverage.unit == unit) & (coverage.dimension == dimension)].sort_values("count", ascending=False)
        panels.append(f"<section><h2>{title}</h2>{_bar_table(table)}</section>")
    readiness = _html_table(result["readiness"], ["question", "evidence_count", "readiness", "reason"])
    continuous = result["continuous"].copy()
    continuous = continuous[continuous.metric.isin(["duration_seconds", "penetration_atr", "approach_efficiency",
        "inside_seconds", "node_width_atr", "node_age_seconds", "start_median_sigma", "distance_atr"])]
    continuous = continuous.round(4)
    continuous_table = _html_table(continuous, ["unit", "metric", "count", "missing_count", "censoring_rate", "p05", "median", "p95"])
    payload = html.escape(json.dumps(s, indent=2))
    document = f"""<!doctype html><html><head><meta charset='utf-8'><title>RG2 Phase 9</title>
<style>
body{{background:#0b1110;color:#dce9e4;font:14px system-ui;margin:0}}main{{max-width:1450px;margin:auto;padding:28px}}
h1{{font-size:28px}}h2{{font-size:17px;color:#72e2c2}}.decision{{color:#ffc767}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
.card,section{{background:#121b19;border:1px solid #263a35;border-radius:8px;padding:14px}}.card b{{display:block;font-size:22px;color:#fff}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}}
.barrow{{display:grid;grid-template-columns:180px 1fr 65px 150px;gap:8px;align-items:center;margin:7px 0}}.track{{height:9px;background:#26332f;border-radius:8px;overflow:hidden}}.track i{{display:block;height:100%;background:#4bd5ae}}em{{color:#82928d;font-style:normal;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border-bottom:1px solid #25332f;padding:7px;text-align:left}}th{{color:#72e2c2}}pre{{white-space:pre-wrap;color:#91a29d}}@media(max-width:900px){{.cards,.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>RG2 Phase 9 — dataset geometry</h1><p class='decision'><b>{s['phase9_decision']}</b></p>
<p>No strategy labels · no win rate · no feature selection · no model</p><div class='cards'>
<div class='card'><b>{s['runs']}</b>runs</div><div class='card'><b>{s['nodes_created']:,}</b>nodes</div>
<div class='card'><b>{s['events']:,}</b>events</div><div class='card'><b>{s['attempts']:,}</b>attempts</div>
<div class='card'><b>{s['episodes']:,}</b>episodes</div><div class='card'><b>{s['transits']:,}</b>transits</div></div>
<div class='grid'>{''.join(panels)}</div><section><h2>Continuous distributions</h2>{continuous_table}</section>
<section><h2>Question readiness</h2>{readiness}</section><section><h2>Machine summary</h2><pre>{payload}</pre></section>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")
