"""Derive auditable summaries from a completed RH1-F2 execution.

This script never changes raw execution receipts. It keeps declared-row (D),
physical-support (P), and whole-endpoint (G) score domains separate and
reports primary and secondary cohorts independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXECUTION = ROOT / "qualification" / "execution" / "execution.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def score(row: dict[str, Any], domain: str) -> tuple[int, int, float, float]:
    value = row["chosen"][domain]
    return (
        int(value["mismatch_count"]),
        int(value["total_ulp_distance"]),
        float(value["residual_l2"]),
        float(value["maximum_absolute_residual"]),
    )


def summarize(rows: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    values = [score(row, domain) for row in rows]
    return {
        "n": len(rows),
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "exact_declared_target_count": sum(bool(row["exact_declared_target"]) for row in rows),
        "mismatch_count_mean": statistics.mean(value[0] for value in values),
        "mismatch_count_median": statistics.median(value[0] for value in values),
        "total_ulp_distance_mean": statistics.mean(value[1] for value in values),
        "residual_l2_mean": statistics.mean(value[2] for value in values),
        "residual_l2_median": statistics.median(value[2] for value in values),
        "maximum_absolute_residual_mean": statistics.mean(value[3] for value in values),
        "newly_damaged_exact_physical_rows_mean": statistics.mean(
            int(row["collateral"]["chosen_newly_damaged_exact_physical_rows"]) for row in rows
        ),
        "global_mismatch_change_mean": statistics.mean(
            int(row["collateral"]["global_mismatch_change"]) for row in rows
        ),
    }


def pairwise(
    rows_by_key: dict[tuple[Any, ...], dict[tuple[str, int], dict[str, Any]]],
    cohort: str,
    left: tuple[str, int],
    right: tuple[str, int],
    domain: str,
) -> dict[str, Any]:
    pairs = []
    for group_key, arms in rows_by_key.items():
        if arms.get(("residual", 16), {}).get("cohort") != cohort:
            continue
        if left in arms and right in arms:
            pairs.append((group_key, arms[left], arms[right]))
    left_wins = right_wins = ties = 0
    mismatch_delta: list[int] = []
    l2_delta: list[float] = []
    for _, left_row, right_row in pairs:
        left_score = score(left_row, domain)
        right_score = score(right_row, domain)
        if left_score < right_score:
            left_wins += 1
        elif right_score < left_score:
            right_wins += 1
        else:
            ties += 1
        mismatch_delta.append(right_score[0] - left_score[0])
        l2_delta.append(right_score[2] - left_score[2])
    result: dict[str, Any] = {
        "cohort": cohort,
        "left": {"ranking": left[0], "horizon": left[1]},
        "right": {"ranking": right[0], "horizon": right[1]},
        "domain": domain,
        "n": len(pairs),
        "left_wins": left_wins,
        "right_wins": right_wins,
        "ties": ties,
    }
    if pairs:
        result["mean_right_minus_left_mismatch_count"] = statistics.mean(mismatch_delta)
        result["mean_right_minus_left_residual_l2"] = statistics.mean(l2_delta)
    return result


def trajectory_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    after_eight = during_13_16 = 0
    best_rounds: list[int] = []
    for row in rows:
        previous: tuple[int, int, float, float] | None = None
        improvements: list[int] = []
        for point in row["trajectory"]:
            value = point.get("best_valid", {}).get("D")
            if not value:
                continue
            current = (
                int(value["mismatch_count"]),
                int(value["total_ulp_distance"]),
                float(value["residual_l2"]),
                float(value["maximum_absolute_residual"]),
            )
            if previous is not None and current < previous:
                round_index = int(point["round"])
                improvements.append(round_index)
            previous = current
        if any(round_index > 8 for round_index in improvements):
            after_eight += 1
        if any(13 <= round_index <= 16 for round_index in improvements):
            during_13_16 += 1
        if improvements:
            best_rounds.append(max(improvements))
    return {
        "groups_with_strict_valid_improvement_after_round_8": after_eight,
        "groups_with_strict_valid_improvement_during_rounds_13_to_16": during_13_16,
        "last_improvement_round_mean": statistics.mean(best_rounds) if best_rounds else None,
        "last_improvement_round_median": statistics.median(best_rounds) if best_rounds else None,
    }


def rank_migration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [entry for row in rows for entry in row.get("rank_migration", [])]
    migrations = [int(entry["rank_migration"]) for entry in entries]
    return {
        "n_nonzero_coordinates": len(entries),
        "mean_residual_minus_authority_rank": statistics.mean(migrations) if migrations else None,
        "median_residual_minus_authority_rank": statistics.median(migrations) if migrations else None,
        "negative_count": sum(value < 0 for value in migrations),
        "positive_count": sum(value > 0 for value in migrations),
        "zero_count": sum(value == 0 for value in migrations),
        "residual_rank_greater_than_16_count": sum(int(entry["residual_rank"]) > 16 for entry in entries),
        "authority_rank_greater_than_16_count": sum(int(entry["authority_rank"]) > 16 for entry in entries),
    }


def load_and_validate(execution_path: Path) -> tuple[dict[str, Any], dict[tuple[Any, ...], dict[tuple[str, int], dict[str, Any]]], list[str]]:
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    rows = execution["results"]
    grouped: dict[tuple[Any, ...], dict[tuple[str, int], dict[str, Any]]] = defaultdict(dict)
    issues: list[str] = []
    for row in rows:
        key = tuple(row["identity"])
        arm = (str(row["ranking"]), int(row["horizon"]))
        if arm in grouped[key]:
            issues.append(f"duplicate arm {key} {arm}")
        grouped[key][arm] = row
        if not bool(row["final_geometry_pass"]):
            issues.append(f"final geometry failed {key} {arm}")
        if row["independent_audit"] != row["final_geometry"]:
            issues.append(f"independent audit mismatch {key} {arm}")
    if len(rows) != 220 or len(grouped) != 55:
        issues.append(f"cardinality drift rows={len(rows)} groups={len(grouped)}")
    if execution.get("primary_groups_processed") != 32 or execution.get("secondary_groups_processed") != 23:
        issues.append("execution cohort count drift")
    for key, arms in grouped.items():
        if len(arms) != 4:
            issues.append(f"arm cardinality drift {key}: {len(arms)}")
            continue
        cohort = next(iter(row["cohort"] for row in arms.values()))
        coordinates = {int(row["coordinates_total"]) for row in arms.values()}
        if len(coordinates) != 1:
            issues.append(f"coordinate count drift {key}")
        count = next(iter(coordinates))
        expected = {("residual", 16), ("authority", 16)}
        expected |= {("residual", 32), ("authority", 32)} if count >= 32 else {
            ("residual", count), ("authority", count)
        }
        if set(arms) != expected:
            issues.append(f"arm/horizon drift {key}: actual={sorted(arms)} expected={sorted(expected)}")
        if cohort not in {"primary", "secondary"}:
            issues.append(f"unknown cohort {key}: {cohort}")
    return execution, grouped, issues


def provenance_findings() -> dict[str, Any]:
    contract_path = ROOT / "CONTRACT.json"
    preexecution_path = ROOT / "PREEXECUTION.json"
    runner_path = ROOT / "scripts" / "run_rh1.py"
    pf5_contract_path = REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    preexecution = json.loads(preexecution_path.read_text(encoding="utf-8"))
    features_path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"
    with features_path.open(encoding="utf-8") as handle:
        first_feature = json.loads(handle.readline())
    source = runner_path.read_text(encoding="utf-8")
    has_named_field = 'item["declared_support_count"]' in source
    uses_actual_field = 'item["declared_row_count"]' in source
    return {
        "contract_authority_order": contract["ranking"]["authority"],
        "feature_fields_sample": sorted(first_feature),
        "runner_uses_declared_row_count": uses_actual_field,
        "runner_uses_declared_support_count": has_named_field,
        "authority_mapping_issue": (
            "contract declares declared_support_count_desc but AC2 features and runner use declared_row_count"
            if "declared_support_count_desc" in contract["ranking"]["authority"] and uses_actual_field and not has_named_field
            else None
        ),
        "code_hashes_at_audit": {
            "rh1_runner": digest(runner_path),
            "pf5_contract": digest(pf5_contract_path),
        },
        "preexecution_bound_labels": sorted(
            binding["label"] for binding in contract["parent_bindings"]
        ),
        "missing_preexecution_provenance_fields": [
            field for field in ("rh1_runner_sha256", "pf5_contract_sha256")
            if not preexecution.get(field)
        ],
        "preexecution_provenance_matches": {
            "rh1_runner": preexecution.get("rh1_runner_sha256", "").upper() == digest(runner_path),
            "pf5_contract": preexecution.get("pf5_contract_sha256", "").upper() == digest(pf5_contract_path),
        },
    }


def build_report(execution: dict[str, Any], grouped: dict[tuple[Any, ...], dict[tuple[str, int], dict[str, Any]]], issues: list[str]) -> dict[str, Any]:
    rows = execution["results"]
    by_cohort = {
        cohort: [row for row in rows if row["cohort"] == cohort]
        for cohort in ("primary", "secondary")
    }
    provenance = provenance_findings()
    authority_mapping_issue = provenance["authority_mapping_issue"]
    authority_factor_gated = bool(
        authority_mapping_issue
        or provenance["missing_preexecution_provenance_fields"]
        or not all(provenance["preexecution_provenance_matches"].values())
    )
    summary: dict[str, Any] = {
        "protocol": execution["protocol"],
        "raw_execution_status": execution["status"],
        "raw_execution_sha256": digest(EXECUTION),
        "groups": len(grouped),
        "arms": len(rows),
        "cohorts": {},
        "integrity": {"issues": issues, "issue_count": len(issues)},
        "provenance_findings": provenance,
        "interpretation_status": "ENGINEERING_DESCRIPTIVE_ONLY_AUTHORITY_FACTOR_GATED" if authority_factor_gated else "ENGINEERING_FACTORIAL_COMPLETE_NO_SCIENTIFIC_PROMOTION",
        "authority_factor_gated": authority_factor_gated,
        "scientific_promotion": False,
    }
    for cohort, cohort_rows in by_cohort.items():
        arm_summary: dict[str, Any] = {}
        for ranking in ("residual", "authority"):
            horizons = sorted({int(row["horizon"]) for row in cohort_rows if row["ranking"] == ranking})
            for horizon in horizons:
                selected = [row for row in cohort_rows if row["ranking"] == ranking and int(row["horizon"]) == horizon]
                arm_summary[f"{ranking}__h{horizon}"] = {
                    domain: summarize(selected, domain) for domain in ("D", "P", "G")
                }
                arm_summary[f"{ranking}__h{horizon}"]["trajectory"] = trajectory_summary(selected)
        pairs: list[dict[str, Any]] = []
        if cohort == "primary":
            pair_specs = [
                (("residual", 16), ("residual", 32), "horizon_residual"),
                (("authority", 16), ("authority", 32), "horizon_authority"),
                (("residual", 16), ("authority", 16), "ranking_h16"),
                (("residual", 32), ("authority", 32), "ranking_h32"),
            ]
        else:
            pair_specs = []
            for ranking in ("residual", "authority"):
                for key, arms in grouped.items():
                    if arms.get(("residual", 16), {}).get("cohort") != cohort:
                        continue
                    natural = [h for (r, h) in arms if r == ranking and h != 16]
                    if len(natural) == 1:
                        # Pairing with a variable horizon is summarized below per group.
                        pass
                # The variable-horizon comparison is assembled separately.
        for left, right, label in pair_specs:
            for domain in ("D", "P", "G"):
                item = pairwise(grouped, cohort, left, right, domain)
                item["comparison"] = label
                pairs.append(item)
        if cohort == "secondary":
            for ranking in ("residual", "authority"):
                for domain in ("D", "P", "G"):
                    values = []
                    for key, arms in grouped.items():
                        baseline = arms.get((ranking, 16))
                        natural_keys = [(r, h) for (r, h) in arms if r == ranking and h != 16]
                        if baseline is None or len(natural_keys) != 1 or baseline["cohort"] != cohort:
                            continue
                        natural = arms[natural_keys[0]]
                        left_score, right_score = score(baseline, domain), score(natural, domain)
                        values.append((left_score, right_score))
                    pairs.append({
                        "comparison": f"natural_horizon_vs_h16_{ranking}",
                        "cohort": cohort,
                        "domain": domain,
                        "n": len(values),
                        "h16_wins": sum(left < right for left, right in values),
                        "natural_horizon_wins": sum(right < left for left, right in values),
                        "ties": sum(left == right for left, right in values),
                        "mean_natural_minus_h16_mismatch_count": statistics.mean(right[0] - left[0] for left, right in values) if values else None,
                        "mean_natural_minus_h16_residual_l2": statistics.mean(right[2] - left[2] for left, right in values) if values else None,
                    })
        cohort_summary: dict[str, Any] = {
            "groups": len({tuple(row["identity"]) for row in cohort_rows}),
            "arms": len(cohort_rows),
            "coordinates_total_distribution": dict(sorted(Counter(int(row["coordinates_total"]) for row in cohort_rows if row["ranking"] == "residual" and int(row["horizon"]) == 16).items())),
            "arms": arm_summary,
            "paired_comparisons": pairs,
        }
        if cohort == "primary":
            authority_h16 = [row for row in cohort_rows if row["ranking"] == "authority" and int(row["horizon"]) == 16]
            cohort_summary["authority_h16_rank_migration"] = rank_migration_summary(authority_h16)
        summary["cohorts"][cohort] = cohort_summary
    return summary


def markdown(report: dict[str, Any]) -> str:
    primary = report["cohorts"]["primary"]
    lines = [
        "# RH1-F2 derived execution report",
        "",
        f"Raw execution: `{report['raw_execution_status']}`; {report['groups']} groups and {report['arms']} arm receipts.",
        "",
        "This is an engineering-only derivative. No behavioral or scientific promotion is authorized.",
        "",
        "## Integrity",
        "",
        f"Interpretation status: `{report['interpretation_status']}`.",
        "",
        f"Structural receipt issues: `{report['integrity']['issue_count']}`; all raw final geometry checks were required to pass before this report was generated.",
        "",
        (
            "The authority factor is gated by a provenance or contract mismatch; inspect `provenance_findings` in SUMMARY.json."
            if report["authority_factor_gated"]
            else "The authority factor is bound to the complete AC2 `declared_row_count` feature and the RH1 runner/PF5 contract hashes are sealed in preexecution."
        ),
        "",
        "## Primary cohort",
        "",
        "The primary cohort contains 32 groups. The D-domain results are the search objective; P and G are diagnostics.",
        "",
    ]
    for name in ("residual__h16", "residual__h32", "authority__h16", "authority__h32"):
        arm = primary["arms"][name]["D"]
        lines.append(
            f"- `{name}`: exact {arm['exact_declared_target_count']}/32, mean D mismatches {arm['mismatch_count_mean']:.3f}, mean D L2 {arm['residual_l2_mean']:.3e}."
        )
    migration = primary["authority_h16_rank_migration"]
    lines.append(
        f"- Authority h16 used {migration['n_nonzero_coordinates']} nonzero coordinates; mean residual-rank minus authority-rank was {migration['mean_residual_minus_authority_rank']:.2f}, with {migration['residual_rank_greater_than_16_count']} used coordinates originally below the residual rank-16 cutoff."
    )
    lines.append(
        f"- At h32, mean P mismatches were {primary['arms']['residual__h32']['P']['mismatch_count_mean']:.3f} for residual ordering and {primary['arms']['authority__h32']['P']['mismatch_count_mean']:.3f} for authority ordering; whole-endpoint G remains a diagnostic only."
    )
    lines.extend([
        "",
        "Lexicographic D-domain paired comparisons:",
        "",
    ])
    for item in primary["paired_comparisons"]:
        if item["domain"] == "D":
            lines.append(
                f"- `{item['comparison']}`: left wins {item.get('left_wins', item.get('h16_wins', 0))}, right wins {item.get('right_wins', item.get('natural_horizon_wins', 0))}, ties {item['ties']}; mean right-minus-left mismatches {item.get('mean_right_minus_left_mismatch_count', item.get('mean_natural_minus_h16_mismatch_count')):.3f}."
            )
    lines.extend([
        "",
        "## Secondary cohort",
        "",
        "The 23 secondary groups are summarized separately with each long arm ending at its available coordinate horizon.",
        "",
    ])
    secondary = report["cohorts"]["secondary"]
    for name in sorted(secondary["arms"]):
        if name.endswith("__h16"):
            arm = secondary["arms"][name]["D"]
            lines.append(f"- `{name}`: exact {arm['exact_declared_target_count']}/23, mean D mismatches {arm['mismatch_count_mean']:.3f}.")
    for ranking in ("residual", "authority"):
        long_arms = [
            arm for name, arm in secondary["arms"].items()
            if name.startswith(ranking + "__") and not name.endswith("__h16")
        ]
        if long_arms:
            exact = sum(arm["D"]["exact_declared_target_count"] for arm in long_arms)
            n = sum(arm["D"]["n"] for arm in long_arms)
            mm = sum(arm["D"]["mismatch_count_mean"] * arm["D"]["n"] for arm in long_arms) / n
            lines.append(f"- `{ranking}__natural_horizon`: exact {exact}/23, weighted mean D mismatches {mm:.3f}.")
    lines.extend([
        "",
        "The immutable execution and all derived JSON remain the source of numerical detail; this report does not convert any engineering result into a scientific finding.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution", type=Path, default=EXECUTION)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "qualification" / "derived")
    args = parser.parse_args()
    execution, grouped, issues = load_and_validate(args.execution)
    report = build_report(execution, grouped, issues)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "SUMMARY.json"
    result_path = args.output_dir / "RESULT.md"
    status_path = args.output_dir / "STATUS.json"
    summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(markdown(report), encoding="utf-8")
    status = {
        "protocol": "Q10-PF6-RH1-F2",
        "status": report["interpretation_status"],
        "raw_execution_sha256": report["raw_execution_sha256"],
        "derived_summary_sha256": digest(summary_path),
        "scientific_promotion": False,
        "authority_factor_gated": report["authority_factor_gated"],
        "structural_issue_count": report["integrity"]["issue_count"],
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
