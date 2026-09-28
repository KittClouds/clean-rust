"""Bind raw q diagnostics to every weighted output scope without rescoring."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_summary(summary: dict[str, Any]) -> None:
    required = {"min_q", "max_q", "mean_q", "sum_q", "ess", "count"}
    if not required.issubset(summary):
        raise RuntimeError(f"q diagnostic summary missing fields: {required - set(summary)}")
    if int(summary["count"]) == 0:
        if (
            any(summary[key] is not None for key in ("min_q", "max_q", "mean_q"))
            or float(summary["sum_q"]) != 0.0
            or float(summary["ess"]) != 0.0
        ):
            raise RuntimeError("empty class has nonempty q diagnostics")
        return
    values = [float(summary[key]) for key in ("min_q", "max_q", "mean_q", "sum_q", "ess")]
    if any(value <= 0.0 or not math.isfinite(value) for value in values):
        raise RuntimeError("q diagnostics contain invalid values")
    if int(summary["count"]) < 1:
        raise RuntimeError("weighted score scope has no q observations")


def _scope(raw: dict[str, Any], family: str, key: str) -> dict[str, Any]:
    value = raw[family][str(key)]
    for subgroup in ("all_rows", "target_negative", "target_positive"):
        _validate_summary(value[subgroup])
    return value


def build_map(analysis: dict[str, Any], raw: dict[str, Any], task_manifest: dict[str, Any]) -> dict[str, Any]:
    assignment = {int(block["block_id"]): int(block["assignment_index"]) for block in task_manifest["blocks"]}
    if len(assignment) != 12 or set(assignment) != set(range(309000, 309012)):
        raise RuntimeError("task assignment block map mismatch")
    scopes: dict[str, Any] = {}
    for block in range(309000, 309012):
        q = _scope(raw, "block_scopes", str(block))
        for replicate in range(3):
            for arm in ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled"):
                path = f"primary.block_scores[block={block}].arms[replicate={replicate}][arm={arm}]"
                scopes[path] = {"q_diagnostics": q, "weight_rule": "q=1/p; no modification"}
    for index in range(6):
        q = _scope(raw, "assignment_scopes", str(index))
        for replicate in range(3):
            for arm in ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled"):
                path = f"primary.assignment_scores_by_replicate[replicate={replicate}][arm={arm}][assignment={index}]"
                scopes[path] = {"q_diagnostics": q, "weight_rule": "q=1/p; class-balanced within assignment"}
                psi_path = f"secondary.polarity_and_delivery[assignment={index}/replicate-{replicate}/{arm}]"
                scopes[psi_path] = {
                    "raw_q_diagnostics": q,
                    "psi_weight_rule": "q*m*abs(g)",
                    "delivery_alignment_weight_rule": "unweighted cosine; q is descriptive context only",
                }
        for arm in ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled"):
            scopes[f"primary.assignment_scores_equal_replicate_mean[arm={arm}][assignment={index}]"] = {
                "q_diagnostics": q,
                "weight_rule": "q=1/p; class-balanced within assignment",
            }
    assignment_q = {str(index): _scope(raw, "assignment_scopes", str(index)) for index in range(6)}
    for replicate in range(3):
        for arm in ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled"):
            scopes[f"primary.macro_error_by_replicate[replicate={replicate}][arm={arm}]"] = {
                "six_assignment_q_diagnostics": assignment_q,
                "weight_rule": "six assignment scores equally weighted; each score uses q=1/p within assignment",
            }
            scopes[f"secondary.pooled_all_rows_secondary[replicate={replicate}][arm={arm}]"] = {
                "q_diagnostics": raw["pooled_scope"],
                "weight_rule": "q=1/p; pooled secondary score",
            }
        for epoch in (1, 2, 4, 8, 16, 32, 64, 128, 200):
            for arm in ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled"):
                scopes[f"secondary.checkpoint_diagnostics[epoch={epoch}][arm={arm}][replicate={replicate}]"] = {
                    "six_assignment_q_diagnostics": assignment_q,
                    "weight_rule": "six assignment scores equally weighted; each score uses q=1/p within assignment",
                }
    for index in range(6):
        for contrast in ("Cphi_minus_D", "Cphi_minus_Cphi_unshared", "Cphi_minus_Cphi_shuffled"):
            scopes[f"primary.assignment_contrasts[assignment={index}][{contrast}]"] = {
                "q_diagnostics": assignment_q[str(index)],
                "weight_rule": "difference of assignment-specific class-balanced q=1/p errors",
            }
    for contrast in ("Cphi_minus_D", "Cphi_minus_Cphi_unshared", "Cphi_minus_Cphi_shuffled"):
        scopes[f"primary.replicate_contrasts[{contrast}]"] = {
            "six_assignment_q_diagnostics": assignment_q,
            "weight_rule": "difference of equal-weight six-assignment aggregates; q=1/p inside each assignment",
        }
    return {
        "schema": "F4-PRESENTATION-03-q-weight-diagnostic-map-v0.1",
        "analysis_status": analysis.get("analysis_status"),
        "analysis_sha256": analysis.get("_file_sha256"),
        "raw_weight_diagnostics_sha256": raw.get("_file_sha256"),
        "weight_rule": "q=1/p_inclusion; no trimming, capping, normalization, or winsorization",
        "diagnostic_fields": ["min_q", "max_q", "mean_q", "sum_q", "ESS=(sum_q)^2/sum(q^2)", "count"],
        "score_scope_count": len(scopes),
        "scopes": scopes,
        "assignment_q_diagnostics": assignment_q,
        "block_q_diagnostics": {str(block): _scope(raw, "block_scopes", str(block)) for block in range(309000, 309012)},
        "pooled_q_diagnostics": raw["pooled_scope"],
        "archived_scorer_comparison": "prohibited: archived outputs used different stored-p semantics",
    }


def render_markdown(report: dict[str, Any]) -> str:
    def fmt(value: Any, precision: int = 6) -> str:
        return "n/a" if value is None else f"{float(value):.{precision}g}"

    lines = [
        "# F4-PRESENTATION-03 raw q weight diagnostics",
        "",
        "This companion attaches the unmodified inverse-inclusion diagnostics to each weighted score scope. It does not recompute or change any score.",
        "",
        "Rule: `q = 1/p_inclusion`. No trimming, capping, normalization, or winsorization was applied. ESS is descriptive only.",
        "",
        "Fields: min q, max q, mean q, sum q, ESS, and sampled count. Class-specific values are shown because balanced errors weight classes separately.",
        "",
        "## Assignment scopes",
        "",
        "| Assignment | Rows | min q | max q | mean q | sum q | ESS | Positive ESS | Negative ESS |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, q in sorted(report["assignment_q_diagnostics"].items(), key=lambda item: int(item[0])):
        all_rows, pos, neg = q["all_rows"], q["target_positive"], q["target_negative"]
        lines.append(f"| {key} | {all_rows['count']} | {fmt(all_rows['min_q'], 9)} | {fmt(all_rows['max_q'], 9)} | {fmt(all_rows['mean_q'], 9)} | {fmt(all_rows['sum_q'], 9)} | {fmt(all_rows['ess'])} | {fmt(pos['ess'])} | {fmt(neg['ess'])} |")
    lines += ["", "## Block scopes", "", "| Block | Assignment | Rows | min q | max q | mean q | sum q | ESS | Positive ESS | Negative ESS |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, q in sorted(report["block_q_diagnostics"].items(), key=lambda item: int(item[0])):
        all_rows, pos, neg = q["all_rows"], q["target_positive"], q["target_negative"]
        lines.append(f"| {key} | {all_rows.get('assignment_index', 'see support table')} | {all_rows['count']} | {fmt(all_rows['min_q'], 9)} | {fmt(all_rows['max_q'], 9)} | {fmt(all_rows['mean_q'], 9)} | {fmt(all_rows['sum_q'], 9)} | {fmt(all_rows['ess'])} | {fmt(pos['ess'])} | {fmt(neg['ess'])} |")
    q = report["pooled_q_diagnostics"]
    all_rows, pos, neg = q["all_rows"], q["target_positive"], q["target_negative"]
    lines += ["", "## Pooled scope", "", f"Rows: {all_rows['count']}; min q: {fmt(all_rows['min_q'], 9)}; max q: {fmt(all_rows['max_q'], 9)}; mean q: {fmt(all_rows['mean_q'], 9)}; sum q: {fmt(all_rows['sum_q'], 9)}; ESS: {fmt(all_rows['ess'])}; positive ESS: {fmt(pos['ess'])}; negative ESS: {fmt(neg['ess'])}.", "", f"The machine-readable scope map attaches diagnostics to {report['score_scope_count']} weighted output paths. Equal-weight six-assignment aggregates reference all six assignment-specific q summaries; no pooled reweighting of assignments is implied.", ""]
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parents[2] / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
    validation = root.parent / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1"
    analysis_path = root / "ANALYSIS.json"
    weight_path = validation / "RAW-WEIGHT-DIAGNOSTICS-v0.1.1.json"
    task_path = root.parent / "F4-PRESENTATION-03-ENG1" / "task-bank" / "TASK-BANK-MANIFEST.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    raw = json.loads(weight_path.read_text(encoding="utf-8"))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    analysis["_file_sha256"] = sha_file(analysis_path)
    raw["_file_sha256"] = sha_file(weight_path)
    report = build_map(analysis, raw, task)
    report_path = root / "WEIGHT-DIAGNOSTICS-MAP.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="")
    markdown_path = root / "WEIGHT-DIAGNOSTICS-REPORT.md"
    markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="")
    print(json.dumps({"status": "PASS", "score_scope_count": report["score_scope_count"], "report_sha256": sha_file(markdown_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
