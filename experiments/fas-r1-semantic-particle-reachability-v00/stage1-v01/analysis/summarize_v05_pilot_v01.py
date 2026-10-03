#!/usr/bin/env python3
"""Summarize a completed V05 Stage1 pilot from its full replayable traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def rate(rows: list[dict[str, Any]], key: str) -> float:
    return sum(bool(row[key]) for row in rows) / len(rows) if rows else math.nan


def average(rows: list[dict[str, Any]], key: str) -> float:
    values = [row[key] for row in rows if row[key] is not None]
    return statistics.fmean(values) if values else math.nan


def quantile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reached = [row["first_hit_expansions"] for row in rows if row["reached_excluding_initial"]]
    return {
        "n": len(rows),
        "reach_including_initial": rate(rows, "reached_including_initial"),
        "reach_after_expansion": rate(rows, "reached_excluding_initial"),
        "selected_valid": rate(rows, "selected_valid"),
        "selection_loss": average(rows, "selection_loss"),
        "mean_valid_classes_reached": average(rows, "valid_classes_reached"),
        "mean_first_hit_expansions_given_hit": statistics.fmean(reached) if reached else None,
        "mean_active_ms": average(rows, "total_active_ns") / 1e6,
        "mean_wall_ms": average(rows, "total_wall_ns") / 1e6,
        "mean_cpu_ms_manifest": average(rows, "active_cpu_ns") / 1e6,
        "mean_wall_ms_manifest": average(rows, "wall_ns") / 1e6,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pilot", type=Path)
    parser.add_argument("worlds", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite analysis output: {args.output}")

    pilot_dir = args.pilot.resolve()
    worlds_dir = args.worlds.resolve()
    manifest_path = pilot_dir / "pilot-manifest.json"
    manifest = read_json(manifest_path)
    if manifest["schema"] != "FAS_R1_STAGE1_ENGINEERING_PILOT_V20":
        raise SystemExit("pilot manifest is not Stage1 V20")
    if manifest["status"] != "COMPLETE":
        raise SystemExit("pilot is not complete")

    starts_path = worlds_dir / "public-search-starts-v05.jsonl"
    starts = {row["task_id"]: row for row in read_jsonl(starts_path)}
    if digest(starts_path) != manifest["search_start_file_sha256"]:
        raise SystemExit("search start sidecar hash disagrees with the pilot manifest")

    run_rows: list[dict[str, Any]] = []
    merge_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"raw_merges": 0, "canonical_merges": 0, "strict_dynamic_duplicates": 0, "retired_particles": 0}
    )
    for run in manifest["run_rows"]:
        task_id = run["task_id"]
        start = starts.get(task_id)
        if start is None:
            raise SystemExit(f"no start sidecar row for {task_id}")

        trace_path = pilot_dir / run["trace_file"]
        with trace_path.open("r", encoding="utf-8") as stream:
            header_record = json.loads(next(stream))
            header = header_record["payload"]
            initial = header["initial_particles"][0]["assignment"]
            if initial != start["assignment"]:
                raise SystemExit(f"initial state differs from sidecar for {task_id}/{run['condition']}")
            trace_events = []
            totals = merge_totals[run["condition"]]
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record["record"] != "event":
                    continue
                event = record["payload"]
                trace_events.append(event)
                totals["raw_merges"] += int(event["raw_merge"])
                totals["canonical_merges"] += int(event["canonical_merge"])
                totals["strict_dynamic_duplicates"] += int(event["full_dynamic_duplicate"])
                totals["retired_particles"] += int(event["merge_retired_particle_id"] is not None)

        posthoc = read_json(pilot_dir / run["posthoc_file"])
        if posthoc["trace_id"] != header["trace_id"] or len(posthoc["events"]) != len(trace_events):
            raise SystemExit(f"posthoc labels do not align with trace for {task_id}/{run['condition']}")
        if not run["replay_checked"] or not run["replay_passed"]:
            raise SystemExit(f"replay did not pass for {task_id}/{run['condition']}")
        if len(trace_events) != manifest["transition_budget"]:
            raise SystemExit(f"trace expansion count differs from budget for {task_id}/{run['condition']}")

        first_hit_expansions = None
        first_hit_active_ns = None
        first_hit_wall_ns = None
        if posthoc["initial_valid"]:
            first_hit_expansions = 0
            first_hit_active_ns = header["initial_completion_active_ns"]
            first_hit_wall_ns = header["initial_completion_wall_ns"]
        else:
            for event, label in zip(trace_events, posthoc["events"], strict=True):
                if label["valid"]:
                    first_hit_expansions = label["event_index"] + 1
                    first_hit_active_ns = event["cumulative_active_ns"]
                    first_hit_wall_ns = event["cumulative_wall_ns"]
                    break

        prefix_rows = [
            row
            for row in read_jsonl(pilot_dir / run["prefix_file"])
            if row["budget_kind"] == "expansions"
            and row["budget_value"] == manifest["transition_budget"]
        ]
        if len(prefix_rows) != 1:
            raise SystemExit(f"expected one maximum-budget prefix for {task_id}/{run['condition']}")
        prefix = prefix_rows[0]
        last_event = trace_events[-1] if trace_events else None
        run_rows.append(
            {
                "condition": run["condition"],
                "task_id": task_id,
                "paired_world_id": run.get("paired_world_id"),
                "density_level": run.get("density_level"),
                "start_kind": run.get("start_kind"),
                "reached_including_initial": prefix["reachable_including_initial"],
                "reached_excluding_initial": prefix["reachable_excluding_initial"],
                "selected_valid": prefix["selected_valid"],
                "selection_loss": bool(
                    prefix["reachable_including_initial"] and not prefix["selected_valid"]
                ),
                "valid_classes_reached": prefix["distinct_valid_classes_reached"],
                "first_hit_expansions": first_hit_expansions,
                "first_hit_active_ns": first_hit_active_ns,
                "first_hit_wall_ns": first_hit_wall_ns,
                "total_active_ns": last_event["cumulative_active_ns"] if last_event else header["initial_completion_active_ns"],
                "total_wall_ns": last_event["cumulative_wall_ns"] if last_event else header["initial_completion_wall_ns"],
                "active_cpu_ns": run["active_cpu_ns"],
                "wall_ns": run["wall_ns"],
                "replay_passed": run["replay_passed"],
                "initial_state_matches": True,
            }
        )

    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_task: dict[tuple[str, str], dict[str, Any]] = {}
    for row in run_rows:
        by_condition[row["condition"]].append(row)
        stratum = f"{row['density_level']}__{row['start_kind']}"
        by_stratum[f"{row['condition']}__{stratum}"].append(row)
        by_task[(row["task_id"], row["condition"])] = row

    paired_to_depth = {}
    for condition in by_condition:
        if condition == "depth":
            continue
        comparisons = [
            (by_task[(task_id, condition)], by_task[(task_id, "depth")])
            for task_id in starts
            if (task_id, condition) in by_task and (task_id, "depth") in by_task
        ]
        differences = [int(left["reached_including_initial"]) - int(right["reached_including_initial"]) for left, right in comparisons]
        paired_to_depth[condition] = {
            "n": len(comparisons),
            "wins": sum(value > 0 for value in differences),
            "ties": sum(value == 0 for value in differences),
            "losses": sum(value < 0 for value in differences),
            "reach_delta": statistics.fmean(differences) if differences else math.nan,
        }

    all_active = [row["total_active_ns"] for row in run_rows]
    all_wall = [row["total_wall_ns"] for row in run_rows]
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    time_curves = {}
    for clock, values, field in (
        ("active", all_active, "first_hit_active_ns"),
        ("wall", all_wall, "first_hit_wall_ns"),
    ):
        budgets = sorted({quantile(values, q) for q in quantiles})
        time_curves[clock] = {
            str(budget): {
                condition: sum(
                    row[field] is not None and row[field] <= budget
                    for row in condition_rows
                )
                / len(condition_rows)
                for condition, condition_rows in by_condition.items()
            }
            for budget in budgets
        }

    source_path = Path(__file__).resolve()
    report = {
        "schema": "FAS_R1_V05_PILOT_ENGINEERING_SUMMARY_V01",
        "pilot_path": str(pilot_dir),
        "pilot_manifest_sha256": digest(manifest_path),
        "worlds_path": str(worlds_dir),
        "search_start_sha256": digest(starts_path),
        "sensor_receipt_sha256": manifest["sensor_receipt_sha256"],
        "analysis_source_path": str(source_path),
        "analysis_source_sha256": digest(source_path),
        "task_count": manifest["selected_task_count"],
        "condition_count": len(manifest["conditions"]),
        "run_count": len(run_rows),
        "transition_budget": manifest["transition_budget"],
        "all_replays_passed": all(row["replay_passed"] for row in run_rows),
        "all_initial_states_match_sidecar": all(row["initial_state_matches"] for row in run_rows),
        "by_condition": {key: summarize(value) for key, value in sorted(by_condition.items())},
        "by_condition_stratum": {key: summarize(value) for key, value in sorted(by_stratum.items())},
        "paired_to_depth": paired_to_depth,
        "time_curve_budget_units": "nanoseconds; global empirical quantiles of completed trace totals",
        "time_curves": time_curves,
        "merge_totals": dict(sorted(merge_totals.items())),
        "run_rows": run_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"tasks={report['task_count']} conditions={report['condition_count']} runs={report['run_count']}")
    print("condition reach / selection / selection-loss / active-ms / wall-ms")
    for condition, summary in report["by_condition"].items():
        print(
            f"{condition:30s} "
            f"{summary['reach_including_initial']:.3f} "
            f"{summary['selected_valid']:.3f} "
            f"{summary['selection_loss']:.3f} "
            f"{summary['mean_active_ms']:.2f} "
            f"{summary['mean_wall_ms']:.2f}"
        )


if __name__ == "__main__":
    main()
