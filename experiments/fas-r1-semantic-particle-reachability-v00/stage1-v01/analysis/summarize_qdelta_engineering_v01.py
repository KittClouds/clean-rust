#!/usr/bin/env python3
"""Verify and summarize completed train/validation-only R1 engineering pilots."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "FAS_R1_STAGE1_ENGINEERING_PILOT_V21"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_artifact(run_dir: Path, name: str) -> Path:
    path = (run_dir / name).resolve()
    if path.parent != run_dir.resolve():
        raise ValueError(f"artifact path escapes its run directory: {name}")
    return path


def verify_file(run_dir: Path, name: str, expected: str) -> Path:
    path = safe_artifact(run_dir, name)
    if not path.is_file() or digest(path) != expected:
        raise ValueError(f"artifact hash mismatch: {path}")
    return path


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize_pilot(run_dir_arg: Path) -> dict[str, Any]:
    run_dir = run_dir_arg.resolve()
    manifest_path = run_dir / "pilot-manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "COMPLETE":
        raise ValueError(f"not a complete {SCHEMA} run: {manifest_path}")
    split = manifest.get("split")
    if split not in {"train", "validation"}:
        raise ValueError(f"closed or unsupported split in {manifest_path}: {split}")
    if manifest.get("qdelta_binary_sha256") is None or manifest.get("qdelta_beta") is None:
        raise ValueError(f"Q-delta identity missing from {manifest_path}")

    conditions = {row["id"] for row in manifest["conditions"]}
    skipped = {(row["task_id"], row["condition"]) for row in manifest["skipped_arms"]}
    rows = manifest["run_rows"]
    pairs = [(row["task_id"], row["condition"]) for row in rows]
    if len(pairs) != len(set(pairs)):
        raise ValueError(f"duplicate task/condition row in {manifest_path}")
    task_ids = {task_id for task_id, _ in pairs} | {task_id for task_id, _ in skipped}
    expected = {(task, condition) for task in task_ids for condition in conditions} - skipped
    if set(pairs) != expected or len(task_ids) != manifest["selected_task_count"]:
        raise ValueError(f"task/condition coverage mismatch in {manifest_path}")

    run_metrics: list[dict[str, Any]] = []
    for row in rows:
        trace = verify_file(run_dir, row["trace_file"], row["trace_sha256"])
        posthoc = verify_file(run_dir, row["posthoc_file"], row["posthoc_sha256"])
        selector = verify_file(run_dir, row["selector_file"], row["selector_sha256"])
        prefix = verify_file(run_dir, row["prefix_file"], row["prefix_sha256"])

        event_count = 0
        raw_duplicates = canonical_duplicates = dynamic_duplicates = 0
        raw_merges = canonical_merges = value_allocations = 0
        value_calls = scored_logits = proposal_calls = 0
        unique_assignments: set[tuple[int, ...]] = set()
        header_seen = footer_seen = False
        for envelope in read_jsonl(trace):
            record = envelope.get("record")
            payload = envelope.get("payload", {})
            if record == "header":
                if header_seen or payload.get("task_id") != row["task_id"]:
                    raise ValueError(f"trace header mismatch: {trace}")
                header_seen = True
                for particle in payload.get("initial_particles", []):
                    unique_assignments.add(tuple(particle["assignment"]))
            elif record == "event":
                event_count += 1
                raw_duplicates += bool(payload.get("raw_duplicate_detected"))
                canonical_duplicates += bool(payload.get("canonical_duplicate_detected"))
                dynamic_duplicates += bool(payload.get("full_dynamic_duplicate"))
                raw_merges += bool(payload.get("raw_merge"))
                canonical_merges += bool(payload.get("canonical_merge"))
                value_allocations += bool(payload.get("value_based_allocation"))
                costs = payload.get("costs") or {}
                value_calls += int(costs.get("value_calls", 0))
                scored_logits += int(costs.get("logits_scored", 0))
                proposal_calls += int(costs.get("proposal_calls", 0))
                assignment = payload.get("assignment_after")
                if assignment is not None:
                    unique_assignments.add(tuple(assignment))
            elif record == "footer":
                if footer_seen:
                    raise ValueError(f"duplicate trace footer: {trace}")
                footer_seen = True
        if not header_seen or not footer_seen or event_count != manifest["transition_budget"]:
            raise ValueError(f"trace is incomplete or under budget: {trace}")

        expansion_rows = [
            record for record in read_jsonl(prefix)
            if record.get("budget_kind") == "expansions"
        ]
        final_rows = [
            record for record in expansion_rows
            if record.get("budget_value") == manifest["transition_budget"]
        ]
        if len(final_rows) != 1 or final_rows[0]["completed_expansions"] != manifest["transition_budget"]:
            raise ValueError(f"final expansion prefix missing: {prefix}")
        final = final_rows[0]
        hits = [
            record["budget_value"] for record in expansion_rows
            if record.get("reachable_excluding_initial")
        ]
        if row["replay_checked"] and not row["replay_passed"]:
            raise ValueError(f"replay failed: {row['task_id']} / {row['condition']}")
        run_metrics.append({
            "task_id": row["task_id"],
            "condition": row["condition"],
            "reached": bool(final["reachable_including_initial"]),
            "selected_valid": bool(final["selected_valid"]),
            "selection_loss": bool(final["reachable_including_initial"]) and not bool(final["selected_valid"]),
            "valid_classes": int(final["distinct_valid_classes_reached"]),
            "first_hit_expansions": min(hits) if hits else None,
            "expansions": int(row["expansions"]),
            "active_cpu_ns": int(row["active_cpu_ns"]),
            "wall_ns": int(row["wall_ns"]),
            "value_calls": value_calls,
            "scored_logits": scored_logits,
            "proposal_calls": proposal_calls,
            "raw_duplicates": raw_duplicates,
            "canonical_duplicates": canonical_duplicates,
            "dynamic_duplicates": dynamic_duplicates,
            "raw_merges": raw_merges,
            "canonical_merges": canonical_merges,
            "value_allocations": value_allocations,
            "unique_assignments": len(unique_assignments),
            "replay_checked": bool(row["replay_checked"]),
            "replay_passed": bool(row["replay_passed"]),
        })

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in run_metrics:
        grouped[row["condition"]].append(row)
    arms = []
    for condition in sorted(grouped):
        group = grouped[condition]
        reached = sum(row["reached"] for row in group)
        selected = sum(row["selected_valid"] for row in group)
        arms.append({
            "condition": condition,
            "n": len(group),
            "reachable": reached,
            "R": reached / len(group),
            "selected_valid": selected,
            "S": selected / len(group),
            "selection_loss": sum(row["selection_loss"] for row in group) / len(group),
            "mean_valid_classes": mean([row["valid_classes"] for row in group]),
            "mean_first_hit_expansions": mean([row["first_hit_expansions"] for row in group if row["first_hit_expansions"] is not None]),
            "mean_active_ms": mean([row["active_cpu_ns"] / 1e6 for row in group]),
            "mean_wall_ms": mean([row["wall_ns"] / 1e6 for row in group]),
            "mean_value_calls": mean([row["value_calls"] for row in group]),
            "mean_qdelta_logits_scored": mean([row["scored_logits"] for row in group]),
            "mean_raw_merges": mean([row["raw_merges"] for row in group]),
            "mean_canonical_merges": mean([row["canonical_merges"] for row in group]),
            "mean_dynamic_duplicates": mean([row["dynamic_duplicates"] for row in group]),
            "mean_value_allocations": mean([row["value_allocations"] for row in group]),
            "mean_unique_assignments": mean([row["unique_assignments"] for row in group]),
            "replay_checked": sum(row["replay_checked"] for row in group),
            "replay_passed": sum(row["replay_passed"] for row in group),
        })

    return {
        "pilot_dir": str(run_dir),
        "pilot_manifest_sha256": digest(manifest_path),
        "split": split,
        "selected_task_count": manifest["selected_task_count"],
        "transition_budget": manifest["transition_budget"],
        "proposal_id": manifest["proposal_id"],
        "proposal_sha256": manifest["proposal_sha256"],
        "qdelta_checkpoint_sha256": manifest["qdelta_checkpoint_sha256"],
        "qdelta_binary_sha256": manifest["qdelta_binary_sha256"],
        "qdelta_manifest_sha256": manifest["qdelta_manifest_sha256"],
        "qdelta_beta": manifest["qdelta_beta"],
        "learned_sample_temperature": manifest["learned_sample_temperature"],
        "v_reach_sha256": manifest["v_reach_sha256"],
        "condition_count": len(conditions),
        "run_row_count": len(run_metrics),
        "skipped_arm_count": len(skipped),
        "all_referenced_artifacts_hash_verified": True,
        "all_traces_full_budget": True,
        "arms": arms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="new JSON summary path")
    parser.add_argument("pilots", nargs="+", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite summary: {args.output}")
    summary = {
        "schema": "FAS_R1_QDELTA_ENGINEERING_SUMMARY_V01",
        "mode": "adaptive engineering readback; train/validation only",
        "pilots": [summarize_pilot(path) for path in args.pilots],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()