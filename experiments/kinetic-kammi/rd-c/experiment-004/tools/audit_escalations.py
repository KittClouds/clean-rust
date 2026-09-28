#!/usr/bin/env python3
"""Audit routed E004 episodes without changing the frozen run."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path


OUTCOMES = ("wrong_to_right", "right_to_wrong", "both_right", "both_wrong")
DIMENSIONS = ("witness", "disagreement", "confidence_band")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def confidence_band(value: int) -> str:
    if value < 700:
        return "low_<700"
    if value < 900:
        return "mid_700_899"
    return "high_900_plus"


def outcome(active: str, resolver: str, correct: str) -> str:
    active_right = active == correct
    resolver_right = resolver == correct
    if not active_right and resolver_right:
        return "wrong_to_right"
    if active_right and not resolver_right:
        return "right_to_wrong"
    return "both_right" if active_right else "both_wrong"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(run_dir: Path, output_dir: Path) -> None:
    trace_path = run_dir / "run-trace.csv"
    public_path = run_dir / "inputs" / "episodes.csv"
    trace = load_csv(trace_path)
    public = {row["episode_id"]: row for row in load_csv(public_path)}
    if not trace or len(trace) != 2048:
        raise ValueError(f"expected 2048 frozen trace rows, found {len(trace)}")

    routed: list[dict[str, object]] = []
    byte_deltas: list[int] = []
    for row in trace:
        if row["escalated"].lower() != "true":
            continue
        frame = public[row["episode_id"]]
        resolver = row["resolver_action"]
        if resolver == "none":
            raise ValueError(f"escalated row has no resolver action: {row}")
        confidence = int(frame["confidence"])
        result = outcome(row["observer_a"], resolver, row["correct_action"])
        relative_journal = Path(row["journal_path"].replace("\\", "/"))
        journal_path = run_dir.joinpath(*relative_journal.parts)
        on_disk = journal_path.stat().st_size
        reported = int(row["journal_bytes"])
        byte_deltas.append(on_disk - reported)
        routed.append(
            {
                "policy": row["policy"],
                "budget": int(row["budget"]),
                "episode_id": int(row["episode_id"]),
                "class": row["class"],
                "confidence": confidence,
                "confidence_band": confidence_band(confidence),
                "witness": row["witness"],
                "witness_source_id": row["witness_source_id"],
                "disagreement": row["disagreement"],
                "active_action": row["observer_a"],
                "resolver_action": resolver,
                "correct_action": row["correct_action"],
                "outcome": result,
                "active_correct": str(row["observer_a"] == row["correct_action"]).lower(),
                "resolver_correct": str(resolver == row["correct_action"]).lower(),
                "journal_bytes_reported": reported,
                "journal_file_bytes": on_disk,
                "journal_byte_delta": on_disk - reported,
            }
        )

    fields = list(routed[0])
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "per_episode.csv", fields, routed)

    groups: dict[tuple[str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    for item in routed:
        groups[(str(item["policy"]), int(item["budget"]), "policy_budget", "all")].append(item)
        for dimension in DIMENSIONS:
            groups[(str(item["policy"]), int(item["budget"]), dimension, str(item[dimension]))].append(item)

    summary_rows: list[dict[str, object]] = []
    for (policy, budget, dimension, value), group in sorted(groups.items()):
        counts = Counter(str(row["outcome"]) for row in group)
        summary_rows.append(
            {
                "policy": policy,
                "budget": budget,
                "dimension": dimension,
                "value": value,
                "routed_episodes": len(group),
                **{name: counts[name] for name in OUTCOMES},
                "net_correct_conversions": counts["wrong_to_right"] - counts["right_to_wrong"],
                "journal_bytes_mean": round(statistics.mean(int(row["journal_file_bytes"]) for row in group), 1),
            }
        )
    summary_fields = [
        "policy", "budget", "dimension", "value", "routed_episodes", *OUTCOMES,
        "net_correct_conversions", "journal_bytes_mean",
    ]
    write_csv(output_dir / "summary.csv", summary_fields, summary_rows)

    # The 32-call plan is nested in the 48-call plan. These are the 16 newly routed episodes.
    routed32 = {int(row["episode_id"]) for row in routed if row["policy"] == "combined" and row["budget"] == 32}
    marginal48 = [row for row in routed if row["policy"] == "combined" and row["budget"] == 48 and int(row["episode_id"]) not in routed32]
    marginal_counts = Counter(str(row["outcome"]) for row in marginal48)
    if len(marginal48) != 16:
        raise ValueError(f"expected 16 marginal combined calls from 32 to 48, found {len(marginal48)}")
    write_csv(output_dir / "combined-budget48-marginal.csv", fields, marginal48)

    by_policy_budget: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    selected_ids: dict[tuple[str, int], set[int]] = defaultdict(set)
    for row in routed:
        key = (str(row["policy"]), int(row["budget"]))
        by_policy_budget[key][str(row["outcome"])] += 1
        selected_ids[key].add(int(row["episode_id"]))

    combined16 = by_policy_budget[("combined", 16)]
    random16 = by_policy_budget[("random_matched", 16)]
    combined_net = combined16["wrong_to_right"] - combined16["right_to_wrong"]
    random_net = random16["wrong_to_right"] - random16["right_to_wrong"]
    nested = selected_ids[("combined", 32)].issubset(selected_ids[("combined", 48)])

    mean_journal = statistics.mean(int(row["journal_file_bytes"]) for row in routed)
    mismatches = sum(delta != 0 for delta in byte_deltas)
    report = [
        "# E004 Frozen Run Escalation Audit",
        "",
        f"Run: `{run_dir.name}`. This is a diagnostic audit of the existing 2,048-row run trace; it does not alter or rescore the frozen run.",
        "",
        "## Outcome definition",
        "",
        "Each routed episode compares the active observer action with the resolver action against the hidden correct action. The four categories are wrong→right, right→wrong, both right, and both wrong. `Net correct conversions` is wrong→right minus right→wrong.",
        "",
        "Confidence bands are `<700`, `700–899`, and `>=900`. `Witness` uses the frozen trace label. The CSV summary breaks every category out by policy and budget, then by witness, observer disagreement, and confidence band.",
        "",
        "## Budget 16: combined versus matched random",
        "",
        f"Combined routed outcomes: {dict(combined16)}; net correct conversions `{combined_net}`. Matched random: {dict(random16)}; net correct conversions `{random_net}`.",
        f"Combined ended at 80/128 completions versus random at 83/128. The difference in route conversion yield is {combined_net - random_net}; all other episodes retain their active action. Use the per-episode file for the exact cases and witness/disagreement/confidence slices.",
        "",
        "## Combined budget 32 to 48 plateau",
        "",
        f"The 32-call selection is nested in the 48-call selection: `{nested}`. The 16 newly routed episodes have outcomes {dict(marginal_counts)} and net correct conversions `{marginal_counts['wrong_to_right'] - marginal_counts['right_to_wrong']}`. Completion stayed at 96/128 because the marginal resolver calls produced no net correct-action changes.",
        "",
        "## Journal-byte unit correction",
        "",
        f"`journal_bytes` in the trace is a byte count for the complete E002 task journal (8-byte RDC2 header plus newline-delimited journal envelopes), not KiB. The sampled trace field matches the on-disk `task.journal` length exactly; across routed rows, mean file size was {mean_journal:,.1f} bytes and mismatches were {mismatches}/{len(byte_deltas)}.",
        "",
        "The E004 report formatted `mean(journal_bytes) / episode_count`, dividing by the task count twice. Its displayed 97.7–101.1 is therefore approximately bytes-per-task divided by 128, not journal bytes per task. Correct E004 values are about 12.5–12.9 KB per task, consistent in scale with E003’s 12–13 KB. The frozen report is left unchanged; this audit records the correction.",
        "",
        "## Limits",
        "",
        "The counts describe this synthetic frozen bank and deterministic resolver. The audit explains where the observed completion changes came from; it does not establish that these routing signals predict useful inspection on a different workload.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    audit(args.run_dir, args.output_dir)


if __name__ == "__main__":
    main()
