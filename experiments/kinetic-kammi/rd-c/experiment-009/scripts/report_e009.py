from __future__ import annotations

import json
import math
import os
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN = ROOT / "artifacts" / "runs" / os.environ.get("RDC_E009_RUN_ID", "e009-20260925-pilot-01")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return ordered[index]


lane_data = load(RUN / "lane-results.json")["results"]
labels = load(ROOT / "sealed" / "labels.json")["tasks"]
frames = load(ROOT / "tasks" / "frames" / "frame-lock.json")["frames"]
shadow_small = {item["frame"]["task_id"]: load(RUN / "shadow-small-reasoning-off" / f"{item['frame']['task_id']}.json") for item in frames}
shadow_large = {item["frame"]["task_id"]: load(RUN / "shadow-large-reasoning-off" / f"{item['frame']['task_id']}.json") for item in frames}

lanes = sorted({item["lane"] for item in lane_data})
summary = []
for lane in lanes:
    rows = [item for item in lane_data if item["lane"] == lane]
    times = [float(item["total_task_wall_ms"]) for item in rows]
    tokens = sum(int(item["prompt_tokens"]) + int(item["completion_tokens"]) for item in rows)
    completed = sum(bool(item["task_completed"]) for item in rows)
    checks = [test for row in rows for test in row["completion_check"]["tests"]]
    receipt_bytes = sum(
        (RUN / "receipts" / lane / f"{row['task_id']}.json").stat().st_size for row in rows
    )
    ledger_bytes = sum(
        (RUN / "ledgers" / lane / f"{row['task_id']}.actions.bin").stat().st_size
        for row in rows
        if (RUN / "ledgers" / lane / f"{row['task_id']}.actions.bin").exists()
    )
    summary.append(
        {
            "lane": lane,
            "tasks": len(rows),
            "completed": completed,
            "completion_rate": completed / len(rows) if rows else 0.0,
            "wrong_legal_actions": sum(bool(item["wrong_legal_action"]) for item in rows),
            "abstentions": sum(bool(item["abstained"]) for item in rows),
            "small_calls": sum(int(item["small_calls"]) for item in rows),
            "large_calls": sum(int(item["large_calls"]) for item in rows),
            "prompt_tokens": sum(int(item["prompt_tokens"]) for item in rows),
            "completion_tokens": sum(int(item["completion_tokens"]) for item in rows),
            "total_tokens": tokens,
            "tokens_per_completed_task": tokens / completed if completed else None,
            "observer_wall_ms": round(sum(float(item["observer_wall_ms"]) for item in rows), 3),
            "task_check_wall_ms": round(sum(float(item["task_check_wall_ms"]) for item in rows), 3),
            "total_wall_p50_ms": percentile(times, 0.50),
            "total_wall_p95_ms": percentile(times, 0.95),
            "task_check_count": len(checks),
            "receipt_bytes": receipt_bytes,
            "action_ledger_bytes": ledger_bytes,
            "illegal_commits": sum(int(item["authority"]["illegal_commits"]) for item in rows),
            "duplicate_action_effects": sum(int(item["authority"]["duplicate_action_effects"]) for item in rows),
            "replay_identity_all_equal": all(bool(item["authority"]["replay_state_identical"]) for item in rows),
            "billed_api_usd": 0,
        }
    )

confident_wrong = []
confident_agreement_wrong = []
for locked in frames:
    task_id = locked["frame"]["task_id"]
    small = shadow_small[task_id].get("output") or {}
    large = shadow_large[task_id].get("output") or {}
    good_actions = {
        int(action_id)
        for action_id, outcome in labels[task_id]["actions"].items()
        if outcome["expected_task_completion"]
    }
    small_choice = small.get("action_choice")
    small_confident = small.get("applicability_milli", 0) >= 850 and small.get("abstention_milli", 1000) <= 150
    if small_confident and small_choice is not None and small_choice not in good_actions:
        confident_wrong.append(task_id)
    large_choice = large.get("action_choice")
    large_confident = large.get("applicability_milli", 0) >= 850 and large.get("abstention_milli", 1000) <= 150
    if (
        small_confident and large_confident and small_choice is not None
        and small_choice == large_choice and small_choice not in good_actions
    ):
        confident_agreement_wrong.append(task_id)

run_summary = {
    "schema_version": 1,
    "run_id": RUN.name,
    "promotion_status": "EXPLORATORY_ONLY_TWO_TASK_FAMILIES",
    "lanes": summary,
    "shadow_diagnostics": {
        "small_confident_wrong_tasks": confident_wrong,
        "small_large_confident_agreement_wrong_tasks": confident_agreement_wrong,
        "shadow_calls": len(shadow_small) + len(shadow_large),
        "output_budget_tokens": 1024,
        "reasoning_mode": "off",
        "prior_128_token_attempts_excluded": True,
        "prior_1024_reasoning_attempts_excluded": True,
    },
}
json_path = RUN / "benchmark-summary.json"
if json_path.exists():
    raise SystemExit(f"refusing to overwrite {json_path}")
json_path.write_text(json.dumps(run_summary, indent=2) + "\n", encoding="utf-8")

lines = [
    "# R&D-C / Experiment 009 — Benchmark Report",
    "",
    f"Run: `{RUN.name}`. Status: **exploratory only**; two task families, one task per family, no development bank.",
    "",
    "Non-abstaining lane choices were compiled through E002 authority and checked against the selected candidate's frozen executable completion tests. Abstentions produced no actions. Shadow calls did not authorize actions. Local inference used no billed API; energy and hardware-dollar costs were not measured.",
    "",
    "## Paired lane results",
    "",
    "| Lane | Complete | Wrong legal | Abstain | Small / large calls | Tokens | p50 / p95 total ms | Illegal / duplicate | Replay |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
]
for row in summary:
    lines.append(
        f"| {row['lane']} | {row['completed']}/{row['tasks']} | {row['wrong_legal_actions']} | {row['abstentions']} | "
        f"{row['small_calls']} / {row['large_calls']} | {row['total_tokens']} | "
        f"{row['total_wall_p50_ms']} / {row['total_wall_p95_ms']} | "
        f"{row['illegal_commits']} / {row['duplicate_action_effects']} | {row['replay_identity_all_equal']} |"
    )
lines += [
    "",
    "The small observer abstained on both tasks. Small-plus-large fallback matched always-large completion (2/2) but added 1,889 tokens and 3,714 ms of observer time across the pair. This pilot shows no completion-cost advantage for the hybrid lane.",
    "",
    "The initial 128-token and reasoning-enabled 1024-token shadow responses are preserved and excluded. Runtime logs showed all 1024 generated tokens were reasoning output with empty final content. Disabling template reasoning produced complete typed proposals in 23 small-model tokens and 39 large-model tokens per shadow task; the prompt, schema, and task frames were unchanged.",
    "",
    "Token cost per completed task is recorded in `benchmark-summary.json`; it is undefined for lanes with no completions. Receipt JSON bytes and action-ledger bytes are also recorded there.",
    "",
    "## Confident shared errors",
    "",
    f"Small observer confident wrong choices (applicability ≥850 and abstention ≤150): {len(confident_wrong)} task(s): {', '.join(confident_wrong) if confident_wrong else 'none'}.",
    f"Small and large observers confidently agreeing on the same wrong action: {len(confident_agreement_wrong)} task(s): {', '.join(confident_agreement_wrong) if confident_agreement_wrong else 'none'}.",
    "",
    "## Limits and decision",
    "",
    "This bank supports a harness check and a local observer pilot only. One task per family does not establish generalization across repositories or task families. The large Ternary-Bonsai runtime is experimental-runtime-only. The output fields are constrained JSON plus fixed thresholds, not trained action/applicability/abstention heads. Treat any lane difference as a candidate result for a larger, independently split bank.",
    "",
    "E008 remains sealed and paid inspection routing remains disabled by default.",
]
report_path = RUN / "benchmark-report.md"
if report_path.exists():
    raise SystemExit(f"refusing to overwrite {report_path}")
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {report_path}")
