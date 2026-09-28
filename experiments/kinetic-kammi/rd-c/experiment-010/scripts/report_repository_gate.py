from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts" / "runs" / "e010-20260925-cross-repo-01"
BANK = ROOT / "tasks" / "heldout-bank-v1"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def main() -> None:
    frame_lock = read_json(BANK / "frame-lock.json")
    frames = {item["frame"]["task_id"]: item["frame"] for item in frame_lock["frames"]}
    lane_data = read_json(RUN / "lane-results.json")["results"]
    repositories = sorted({frame["repository_id"] for frame in frames.values()})
    repository_labels = {repository: f"Repo {chr(ord('A') + index)} ({repository})" for index, repository in enumerate(repositories)}
    output: dict[str, dict] = {}
    for repository in repositories:
        task_ids = {task_id for task_id, frame in frames.items() if frame["repository_id"] == repository}
        rows = [row for row in lane_data if row["task_id"] in task_ids]
        by_lane = {name: [row for row in rows if row["lane"] == name] for name in (
            "hand-written", "small", "small-then-large-on-abstention", "always-large"
        )}
        small = by_lane["small"]
        direct = [row for row in small if row["selected_action_id"] is not None]
        direct_successes = sum(row["task_completed"] for row in direct)
        direct_errors = len(direct) - direct_successes
        direct_wrong_legal_actions = sum(row["wrong_legal_action"] for row in direct)
        hybrid = by_lane["small-then-large-on-abstention"]
        large = by_lane["always-large"]
        hybrid_complete = sum(row["task_completed"] for row in hybrid)
        large_complete = sum(row["task_completed"] for row in large)
        hybrid_large_calls = sum(row["large_calls"] for row in hybrid)
        baseline_large_calls = sum(row["large_calls"] for row in large)
        all_authority = [row["authority"] for row in rows]
        authority_clean = all(
            receipt["illegal_commits"] == 0
            and receipt["duplicate_action_effects"] == 0
            and receipt["replay_state_identical"] is True
            for receipt in all_authority
        )
        metrics = {
            "task_count": len(task_ids),
            "direct_small_actions": len(direct),
            "direct_small_successes": direct_successes,
            "direct_small_errors": direct_errors,
            "direct_small_wrong_legal_actions": direct_wrong_legal_actions,
            "small_coverage": rate(len(direct), len(task_ids)),
            "direct_action_precision": rate(direct_successes, len(direct)),
            "hybrid_completions": hybrid_complete,
            "always_large_completions": large_complete,
            "hybrid_large_calls": hybrid_large_calls,
            "always_large_calls": baseline_large_calls,
            "large_calls_avoided": baseline_large_calls - hybrid_large_calls,
            "hybrid_total_tokens": sum(row["total_tokens"] for row in hybrid),
            "always_large_total_tokens": sum(row["total_tokens"] for row in large),
            "hybrid_total_elapsed_ms": round(sum(row["total_elapsed_wall_ms"] for row in hybrid), 3),
            "always_large_total_elapsed_ms": round(sum(row["total_elapsed_wall_ms"] for row in large), 3),
            "authority_clean_all_lanes": authority_clean,
            "hybrid_retains_completion": hybrid_complete >= large_complete,
            "displaces_large_call": hybrid_large_calls < baseline_large_calls,
            "zero_direct_action_errors": direct_errors == 0,
        }
        metrics["repository_gate_pass"] = all(
            metrics[key] for key in (
                "hybrid_retains_completion",
                "displaces_large_call",
                "zero_direct_action_errors",
                "authority_clean_all_lanes",
            )
        )
        metrics["families"] = sorted({frames[task_id]["task_family"] for task_id in task_ids})
        metrics["report_label"] = repository_labels[repository]
        output[repository] = metrics

    pooled = {
        "task_count": sum(item["task_count"] for item in output.values()),
        "small_coverage": rate(sum(item["direct_small_actions"] for item in output.values()), sum(item["task_count"] for item in output.values())),
        "direct_action_precision": rate(sum(item["direct_small_successes"] for item in output.values()), sum(item["direct_small_actions"] for item in output.values())),
        "hybrid_completions": sum(item["hybrid_completions"] for item in output.values()),
        "always_large_completions": sum(item["always_large_completions"] for item in output.values()),
        "hybrid_large_calls": sum(item["hybrid_large_calls"] for item in output.values()),
        "always_large_calls": sum(item["always_large_calls"] for item in output.values()),
        "large_calls_avoided": sum(item["large_calls_avoided"] for item in output.values()),
        "hybrid_total_tokens": sum(item["hybrid_total_tokens"] for item in output.values()),
        "always_large_total_tokens": sum(item["always_large_total_tokens"] for item in output.values()),
        "hybrid_total_elapsed_ms": round(sum(item["hybrid_total_elapsed_ms"] for item in output.values()), 3),
        "always_large_total_elapsed_ms": round(sum(item["always_large_total_elapsed_ms"] for item in output.values()), 3),
        "interpretation": "pooled descriptive totals only; repository gates are evaluated independently",
    }
    gate = all(item["repository_gate_pass"] for item in output.values())
    report = [
        "# E010 repository-level switchboard report",
        "",
        "Promotion is evaluated independently for each repository. Repo A is ripgrep; Repo B is turbovec. Each has four task families expressed in two prompt variants (eight scored prompts); the repository is the transfer unit, and pooled totals are descriptive.",
        "",
        "| Repository | Small coverage | Direct precision | Hybrid | Always large | Large calls avoided | Direct errors | Authority / replay | Gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for repository, item in output.items():
        report.append(
            f"| {repository_labels[repository]} | {pct(item['small_coverage'])} ({item['direct_small_actions']}/{item['task_count']}) | "
            f"{pct(item['direct_action_precision'])} ({item['direct_small_successes']}/{item['direct_small_actions']}) | "
            f"{item['hybrid_completions']}/{item['task_count']} | {item['always_large_completions']}/{item['task_count']} | "
            f"{item['large_calls_avoided']} | {item['direct_small_errors']} | {item['authority_clean_all_lanes']} | "
            f"{'PASS' if item['repository_gate_pass'] else 'FAIL'} |"
        )
    report.extend([
        "",
        "## Repository-level measured efficiency",
        "",
        "Times include the selected candidate test and authority receipt. Tokens include the invoked observer calls.",
        "",
        "| Repository | Hybrid / always-large tokens | Hybrid / always-large elapsed (s) |",
        "| --- | ---: | ---: |",
    ])
    for repository, item in output.items():
        report.append(
            f"| {repository_labels[repository]} | {item['hybrid_total_tokens']:,} / {item['always_large_total_tokens']:,} | "
            f"{item['hybrid_total_elapsed_ms'] / 1000:.2f} / {item['always_large_total_elapsed_ms'] / 1000:.2f} |"
        )
    report.extend([
        "",
        "## Pooled descriptive totals",
        "",
        f"Hybrid completion: {pooled['hybrid_completions']}/{pooled['task_count']} versus always-large {pooled['always_large_completions']}/{pooled['task_count']}; "
        f"small direct coverage {pct(pooled['small_coverage'])}; direct precision {pct(pooled['direct_action_precision'])}; "
        f"large calls avoided {pooled['large_calls_avoided']}; tokens hybrid/always-large {pooled['hybrid_total_tokens']}/{pooled['always_large_total_tokens']}; "
        f"elapsed milliseconds hybrid/always-large {pooled['hybrid_total_elapsed_ms']:.1f}/{pooled['always_large_total_elapsed_ms']:.1f}.",
        "",
        f"## Preregistered outcome: {'PASS' if gate else 'FAIL'}",
        "",
        "The gate requires, in each repository: hybrid completion at least equal to always-large, at least one displaced large call, zero wrong direct small actions, and zero illegal commits, duplicate effects, or replay mismatches.",
        "",
    ])
    (RUN / "repository-level-report.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    reporter_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (RUN / "repository-gate.json").write_text(json.dumps({"schema_version": 1, "reporter_sha256": reporter_sha256, "gate_pass": gate, "repository_order": repository_labels, "repositories": output, "pooled_descriptive": pooled}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"gate_pass": gate, "repositories": output}, indent=2))


if __name__ == "__main__":
    main()
