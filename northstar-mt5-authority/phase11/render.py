from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame[columns].copy()
    for column in view.select_dtypes(include="number"):
        view[column] = view[column].map(lambda value: "" if pd.isna(value) else f"{value:.4f}" if isinstance(value, float) else str(value))
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = ["| " + " | ".join(str(value) for value in row) + " |" for row in view.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *rows])


def write_markdown(result: dict[str, Any], path: Path) -> None:
    summary = result["summary"]
    targets = result["target_summary"]
    metrics = result["model_metrics"]
    dependence = result["dependence"]
    candidates = result["candidate_protocol"]
    gate_rows = []
    for target, gate in result["model_gates"].items():
        gate_rows.append({
            "target": target, "status": gate["status"],
            "grouped_logloss_improvement": gate["grouped_logloss_improvement"],
            "forward_logloss_improvement": gate["forward_logloss_improvement"],
            "instrument_transfer_logloss_improvement": gate["instrument_transfer_logloss_improvement"],
        })
    lines = [
        "# Phase 11 — Empirical Structure Report",
        "",
        f"Status: **{summary['status']}**  ",
        f"Corpus: `{summary['corpus_sha256']}`  ",
        f"Reserved holdout windows touched: **{summary['holdout_windows_touched']}**",
        "",
        "This report describes market-behavior targets only. It contains no trade labels, expectancy,",
        "position sizing, or holdout evaluation. Attempts are resampled and validated by run; they are",
        "never treated as independently shuffled rows.",
        "",
        "## Target geometry",
        "",
        _markdown_table(targets, [
            "target", "eligible", "analyzable", "positive", "negative", "censored",
            "rate", "censoring_rate", "runs", "episodes", "median_time_seconds",
        ]),
        "",
        "## Dependence and effective sample size",
        "",
        _markdown_table(dependence, [
            "target", "cluster_unit", "rows", "clusters", "mean_cluster_size", "icc",
            "design_effect", "effective_n",
        ]),
        "",
        "## Hard baselines",
        "",
        _markdown_table(metrics, [
            "target", "split_type", "model", "rows", "prevalence", "log_loss", "brier",
            "auc", "average_precision", "ece_10",
        ]),
        "",
        "## Nonlinear challenger gates",
        "",
        _markdown_table(pd.DataFrame(gate_rows), [
            "target", "status", "grouped_logloss_improvement", "forward_logloss_improvement",
            "instrument_transfer_logloss_improvement",
        ]),
        "",
        "## Candidate protocol",
        "",
        _markdown_table(candidates, [
            "target", "status", "selected_model_class", "holdout_authorized", "reason",
        ]),
        "",
        "## Latent-state gate",
        "",
        "```json",
        __import__("json").dumps(result["latent_gate"], indent=2),
        "```",
        "",
        "## Interpretation boundary",
        "",
        "Observed separation is exploratory evidence of empirical structure, not a trading edge.",
        "No model is authorized for the reserved holdout until its class and evaluation protocol are frozen.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(result: dict[str, Any], path: Path) -> None:
    summary = result["summary"]
    targets = result["target_summary"]
    metrics = result["model_metrics"]
    dependence = result["dependence"]
    candidates = result["candidate_protocol"]
    def table(frame: pd.DataFrame, columns: list[str]) -> str:
        return frame[columns].to_html(index=False, border=0, classes="data", float_format=lambda x: f"{x:.4f}")
    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Phase 11 Empirical Structure</title>
<style>
body{{background:#0b0f13;color:#dce6e2;font:14px system-ui;margin:32px;max-width:1500px}}
h1,h2{{color:#62e6c4}} .card{{background:#121a1d;border:1px solid #263438;border-radius:10px;padding:18px;margin:18px 0}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{padding:7px;border-bottom:1px solid #263438;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{color:#f3bd58;position:sticky;top:0;background:#121a1d}}
.pass{{color:#62e6c4}} code{{color:#b7c8ff}} .warning{{color:#f3bd58}}
</style></head><body>
<h1>Phase 11 — Empirical Structure</h1>
<div class="card"><b class="pass">{html.escape(summary['status'])}</b><br>
Corpus <code>{html.escape(summary['corpus_sha256'])}</code><br>
Holdout windows touched: <b>{summary['holdout_windows_touched']}</b><br>
Frozen research candidates: <b>{summary['frozen_research_candidates']}</b></div>
<p class="warning">Market behavior only. No win/loss labels, strategy expectancy, or holdout evaluation.</p>
<h2>Target geometry</h2><div class="card">{table(targets, ['target','eligible','analyzable','positive','negative','censored','rate','censoring_rate','runs','episodes','median_time_seconds'])}</div>
<h2>Dependence</h2><div class="card">{table(dependence, ['target','cluster_unit','rows','clusters','mean_cluster_size','icc','design_effect','effective_n'])}</div>
<h2>Grouped and forward baselines</h2><div class="card">{table(metrics, ['target','split_type','model','rows','prevalence','log_loss','brier','auc','average_precision','ece_10'])}</div>
<h2>Candidate protocol</h2><div class="card">{table(candidates, ['target','status','selected_model_class','holdout_authorized','reason'])}</div>
<h2>Latent-state gate</h2><div class="card"><pre>{html.escape(__import__('json').dumps(result['latent_gate'], indent=2))}</pre></div>
<p>Attempts remain grouped by run for validation and block-bootstrap uncertainty. Episode terminal receipts are not used as whole-episode outcomes.</p>
</body></html>"""
    path.write_text(document, encoding="utf-8")
