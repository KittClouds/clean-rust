"""Derive LA1 summary, result prose, and status from immutable LA1 receipts."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
import run_la1 as LA1  # noqa: E402


ENDPOINT_NAMES = (
    "W0",
    "historical_authority_h16",
    "authority_h32_early_ranks_1_16",
    "authority_h32_late_only_ranks_17_32",
    "authority_h32_full",
)
DOMAINS = ("D", "P", "G")
SCORE_FIELDS = LA1.SCORE_FIELDS

MECHANISM_CLASSES = (
    "LATE_INDEPENDENT",
    "LATE_CONTEXTUAL",
    "EARLY_CONFIGURATION_IMPROVED",
    "GEOMETRY_BALANCING_DOMINANT",
    "MIXED",
    "UNRESOLVED",
)

# This policy is derived-only. It is intentionally separate from the sealed
# execution contract and never changes raw endpoint or row-interaction data.
CLASSIFICATION_POLICY = {
    "version": "LA1-DERIVED-MECHANISM-CLASS-V1",
    "status": "descriptive_only_derived_receipt",
    "score_relation": "strict lexicographic comparison of the four-field D/P/G score tuple",
    "score_fields": list(SCORE_FIELDS),
    "thresholds": {
        "domain_score_min_count": 2,
        "interaction_support_min_rows": 1,
        "interaction_zero_required_for_late_independent": True,
        "geometry_full_to_counterfactual_max_ratio": 0.5,
        "geometry_error_metric": "max(abs(axis_normalized_signed), abs(norm_normalized_signed), cue_linear_normalized_abs)",
    },
    "rules": [
        {
            "label": "LATE_INDEPENDENT",
            "rule": "full beats early in at least 2 of D/P/G, late-only beats W0 in at least 2 of D/P/G, and exact interaction support is zero",
        },
        {
            "label": "LATE_CONTEXTUAL",
            "rule": "full beats early in at least 2 of D/P/G, late-only beats W0 in zero domains, and exact interaction support is at least 1 row",
        },
        {
            "label": "EARLY_CONFIGURATION_IMPROVED",
            "rule": "early beats historical h16 in at least 2 of D/P/G, full beats early in at most 1 domain, and late-only beats W0 in at most 1 domain",
        },
        {
            "label": "GEOMETRY_BALANCING_DOMINANT",
            "rule": "actual full passes, both early and late-only diagnostic geometry flags fail, full geometry error is at most 0.5 times each counterfactual error, and no stronger score rule applies",
        },
        {
            "label": "MIXED",
            "rule": "two or more strong rules apply, or no strong rule applies and one comparison has both better and worse domains",
        },
        {
            "label": "UNRESOLVED",
            "rule": "no strong rule or declared mixed pattern is defensible from the receipts",
        },
    ],
    "precedence": "evaluate the first four evidence rules, use MIXED for multiple evidence flags or an otherwise unresolved cross-domain conflict, then UNRESOLVED",
    "morphology_separation": "preserve the existing support/sign morphology label unchanged; it is not the mechanism class",
    "scientific_status": "no biological, behavioral, or scientific interpretation",
}


def validate_prefix_map(endpoint: dict[str, Any], label: str) -> None:
    mapping = [(int(pair[0]), int(pair[1])) for pair in endpoint["canonical_prefix_map"]]
    LA1.require(mapping == sorted(mapping), f"{label} prefix map is not sorted")
    LA1.require(len({coordinate for coordinate, _ in mapping}) == len(mapping), f"{label} prefix map duplicates coordinates")
    changed = {int(pair[0]): int(pair[1]) for pair in endpoint["changed_weight_bits"]}
    LA1.require(all(coordinate in dict(mapping) for coordinate in changed), f"{label} changed-bit coordinate outside prefix map")


def validate_interaction(receipt: dict[str, Any]) -> None:
    rows = receipt["row_interaction"]
    LA1.require(rows, f"empty row interaction: {receipt['identity']}")
    LA1.require(LA1.json_digest(rows) == receipt["row_interaction_sha256"], f"row interaction hash mismatch: {receipt['identity']}")
    for row in rows:
        base = float(row["W0_value"])
        early = float(row["authority_h32_early_value"])
        late = float(row["authority_h32_late_only_value"])
        full = float(row["authority_h32_full_value"])
        expected = full - early - late + base
        LA1.require(row["interaction_I"] == expected, f"row interaction replay mismatch: {receipt['identity']} row={row['row']}")
        for name in ("W0", "historical_authority_h16", "authority_h32_early", "authority_h32_late_only", "authority_h32_full"):
            value = LA1.PF5.from_bits(int(row[f"{name}_bits"]))
            LA1.require(value == float(row[f"{name}_value"]), f"row f32 value/bit mismatch: {receipt['identity']} row={row['row']} {name}")


def score_relation(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_key = LA1.score_key(left)
    right_key = LA1.score_key(right)
    if left_key < right_key:
        return "BETTER"
    if left_key > right_key:
        return "WORSE"
    return "TIE"


def endpoint_comparison(receipt: dict[str, Any], left_name: str, right_name: str) -> dict[str, Any]:
    left = receipt["endpoints"][left_name]
    right = receipt["endpoints"][right_name]
    domains: dict[str, Any] = {}
    for domain in DOMAINS:
        relation = score_relation(left["scores"][domain], right["scores"][domain])
        domains[domain] = {
            "left_endpoint": left_name,
            "right_endpoint": right_name,
            "left_score": left["scores"][domain],
            "right_score": right["scores"][domain],
            "relation": relation,
        }
    relations = [item["relation"] for item in domains.values()]
    return {
        "left_endpoint": left_name,
        "right_endpoint": right_name,
        "domains": domains,
        "better_domain_count": relations.count("BETTER"),
        "worse_domain_count": relations.count("WORSE"),
        "tie_domain_count": relations.count("TIE"),
        "cross_domain_conflict": "BETTER" in relations and "WORSE" in relations,
    }


def geometry_error(endpoint: dict[str, Any]) -> float:
    debt = endpoint["geometry_debt"]
    return max(
        abs(float(debt["axis_normalized_signed"])),
        abs(float(debt["norm_normalized_signed"])),
        float(debt["cue_linear_normalized_abs"]),
    )


def classify_group(receipt: dict[str, Any]) -> dict[str, Any]:
    comparisons = {
        "early_vs_historical_h16": endpoint_comparison(
            receipt,
            "authority_h32_early_ranks_1_16",
            "historical_authority_h16",
        ),
        "full_vs_early_direct_late": endpoint_comparison(
            receipt,
            "authority_h32_full",
            "authority_h32_early_ranks_1_16",
        ),
        "late_only_vs_W0": endpoint_comparison(
            receipt,
            "authority_h32_late_only_ranks_17_32",
            "W0",
        ),
    }
    interaction_rows = receipt["row_interaction"]
    interaction_support = [row for row in interaction_rows if row["interaction_I"] != 0.0]
    errors = {
        name: geometry_error(receipt["endpoints"][name])
        for name in (
            "W0",
            "historical_authority_h16",
            "authority_h32_early_ranks_1_16",
            "authority_h32_late_only_ranks_17_32",
            "authority_h32_full",
        )
    }
    early_historical = comparisons["early_vs_historical_h16"]
    full_early = comparisons["full_vs_early_direct_late"]
    late_base = comparisons["late_only_vs_W0"]
    strong_flags: list[str] = []
    if (
        full_early["better_domain_count"] >= 2
        and late_base["better_domain_count"] >= 2
        and len(interaction_support) == 0
    ):
        strong_flags.append("LATE_INDEPENDENT")
    if (
        full_early["better_domain_count"] >= 2
        and late_base["better_domain_count"] == 0
        and len(interaction_support) >= 1
    ):
        strong_flags.append("LATE_CONTEXTUAL")
    if (
        early_historical["better_domain_count"] >= 2
        and full_early["better_domain_count"] <= 1
        and late_base["better_domain_count"] <= 1
    ):
        strong_flags.append("EARLY_CONFIGURATION_IMPROVED")
    geometry_rule = (
        receipt["endpoints"]["authority_h32_full"]["final_geometry_pass"] is True
        and receipt["endpoints"]["authority_h32_early_ranks_1_16"]["diagnostic_geometry_pass"] is False
        and receipt["endpoints"]["authority_h32_late_only_ranks_17_32"]["diagnostic_geometry_pass"] is False
        and errors["authority_h32_full"] <= 0.5 * errors["authority_h32_early_ranks_1_16"]
        and errors["authority_h32_full"] <= 0.5 * errors["authority_h32_late_only_ranks_17_32"]
        and not strong_flags
    )
    if geometry_rule:
        strong_flags.append("GEOMETRY_BALANCING_DOMINANT")
    unresolved_conflict = not strong_flags and any(
        comparison["cross_domain_conflict"] for comparison in comparisons.values()
    )
    if len(strong_flags) >= 2 or unresolved_conflict:
        mechanism_class = "MIXED"
    elif len(strong_flags) == 1:
        mechanism_class = strong_flags[0]
    else:
        mechanism_class = "UNRESOLVED"
    return {
        "mechanism_class": mechanism_class,
        "evidence_flags": strong_flags,
        "score_comparisons": comparisons,
        "geometry_error_metric": errors,
        "geometry_debt": {
            name: receipt["endpoints"][name]["geometry_debt"] for name in errors
        },
        "row_interaction": {
            "sha256": receipt["row_interaction_sha256"],
            "exact_receipt_reused": True,
            "support_rows": len(interaction_support),
            "declared_support_rows": sum(row["declared"] for row in interaction_support),
            "physical_support_rows": sum(row["physical_support"] for row in interaction_support),
            "positive_rows": sum(row["interaction_I"] > 0.0 for row in interaction_support),
            "negative_rows": sum(row["interaction_I"] < 0.0 for row in interaction_support),
        },
        "descriptive_only": True,
        "unresolved": mechanism_class == "UNRESOLVED",
    }


def load_and_validate(execution_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    execution = LA1.load_json(execution_path)
    LA1.require(execution.get("status") == "LA1_RAW_EXECUTION_COMPLETE", "derived qualification requires a full LA1 raw execution")
    LA1.require(execution.get("selection_complete") is True, "LA1 raw selection is incomplete")
    LA1.require(int(execution.get("selected_group_count", -1)) == int(execution.get("full_selected_group_count", -2)), "LA1 selected count drift")
    contract, preexecution, hashes = LA1.verify_provenance()
    LA1.require(execution.get("source_hashes") == hashes, "LA1 execution source hash drift")
    LA1.require(execution.get("la1_plan_sha256") == LA1.digest(ROOT / "PLAN.md"), "LA1 execution plan hash drift")
    LA1.require(execution.get("la1_contract_sha256") == LA1.digest(ROOT / "CONTRACT.json"), "LA1 execution contract hash drift")
    selection_path = execution_path.parent / "selection.json"
    LA1.require(selection_path.is_file(), "missing LA1 selection receipt")
    selection = LA1.load_json(selection_path)
    LA1.require(selection.get("status") == "LA1_SELECTION_DERIVED_FROM_F2_RECEIPTS", "selection receipt status drift")
    LA1.require(int(selection.get("selected_group_count", -1)) == int(execution["full_selected_group_count"]), "selection count drift")
    LA1.require(selection.get("selected_groups_for_this_run") == [item["identity"] for item in execution["group_receipts"]], "selection/execution identity drift")
    evaluated_selected = [item["identity"] for item in selection["evaluated_primary_groups"] if item["authority_h32_strictly_beats_h16"]]
    LA1.require(evaluated_selected == selection["selected_groups_for_this_run"], "receipt-derived selection was not preserved")
    receipts: list[dict[str, Any]] = []
    for reference in execution["group_receipts"]:
        path = ROOT / Path(reference["path"])
        LA1.require(path.is_file(), f"missing LA1 group receipt: {reference['identity']}")
        LA1.require(LA1.digest(path) == reference["sha256"], f"LA1 group receipt hash drift: {reference['identity']}")
        receipt = LA1.load_json(path)
        LA1.require(receipt.get("identity") == reference["identity"], f"LA1 group identity drift: {reference['identity']}")
        LA1.require(receipt.get("scope", {}).get("morphology_descriptive_only") is True, f"morphology scope drift: {reference['identity']}")
        LA1.require(receipt.get("integrity", {}).get("same_baseline") is True, f"baseline integrity missing: {reference['identity']}")
        LA1.require(receipt.get("integrity", {}).get("exact_sequential_f32_replay") is True, f"sequential replay flag missing: {reference['identity']}")
        LA1.require(set(receipt.get("endpoints", {})) == set(ENDPOINT_NAMES), f"endpoint set drift: {reference['identity']}")
        for name in ENDPOINT_NAMES:
            endpoint = receipt["endpoints"][name]
            validate_prefix_map(endpoint, f"{reference['identity']} {name}")
            LA1.require(endpoint["independent_f32_replay"] is True, f"independent replay flag missing: {reference['identity']} {name}")
            for domain in DOMAINS:
                score = endpoint["scores"][domain]
                LA1.require(all(field in score for field in SCORE_FIELDS), f"incomplete {domain} score: {reference['identity']} {name}")
            geometry = endpoint["final_geometry"]
            LA1.require(all(math.isfinite(float(value)) for value in geometry.values()), f"non-finite geometry: {reference['identity']} {name}")
        LA1.require(receipt["endpoints"]["W0"]["final_geometry_pass"] is True, f"W0 geometry failed: {reference['identity']}")
        LA1.require(receipt["endpoints"]["historical_authority_h16"]["final_geometry_pass"] is True, f"historical h16 geometry failed: {reference['identity']}")
        LA1.require(receipt["endpoints"]["authority_h32_full"]["final_geometry_pass"] is True, f"full h32 geometry failed: {reference['identity']}")
        for name in LA1.COUNTERFACTUAL_ENDPOINTS:
            LA1.require(receipt["endpoints"][name]["geometry_gate_role"] == "diagnostic_only", f"counterfactual geometry role drift: {reference['identity']} {name}")
        validate_interaction(receipt)
        receipts.append(receipt)
    LA1.require(len(receipts) == int(execution["selected_group_count"]), "LA1 receipt cardinality drift")
    return {"execution": execution, "selection": selection, "contract": contract, "preexecution": preexecution, "hashes": hashes}, receipts


def summarize_scores(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ENDPOINT_NAMES:
        result[name] = {}
        for domain in DOMAINS:
            values = [receipt["endpoints"][name]["scores"][domain] for receipt in receipts]
            result[name][domain] = {
                "n": len(values),
                "mismatch_count_mean": mean(int(value["mismatch_count"]) for value in values),
                "total_ulp_distance_mean": mean(int(value["total_ulp_distance"]) for value in values),
                "residual_l2_mean": mean(float(value["residual_l2"]) for value in values),
                "maximum_absolute_residual_mean": mean(float(value["maximum_absolute_residual"]) for value in values),
            }
    return result


def group_summary(receipt: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": receipt["identity"],
        "coordinates_total": receipt["coordinates_total"],
        "selection": receipt["selection"],
        "morphology": receipt["morphology"],
        "mechanism_classification": classification,
        "endpoints": {
            name: {
                "scores": receipt["endpoints"][name]["scores"],
                "final_geometry": receipt["endpoints"][name]["final_geometry"],
                "geometry_debt": receipt["endpoints"][name]["geometry_debt"],
                "final_geometry_pass": receipt["endpoints"][name]["final_geometry_pass"],
                "diagnostic_geometry_pass": receipt["endpoints"][name]["diagnostic_geometry_pass"],
                "geometry_gate_role": receipt["endpoints"][name]["geometry_gate_role"],
                "weight_bits_sha256": receipt["endpoints"][name]["weight_bits_sha256"],
                "readout_bits_sha256": receipt["endpoints"][name]["readout_bits_sha256"],
            }
            for name in ENDPOINT_NAMES
        },
        "row_interaction_sha256": receipt["row_interaction_sha256"],
    }


def build_summary(context: dict[str, Any], receipts: list[dict[str, Any]], execution_path: Path) -> dict[str, Any]:
    execution = context["execution"]
    labels = Counter(receipt["morphology"]["label"] for receipt in receipts)
    classifications = [classify_group(receipt) for receipt in receipts]
    mechanism_counts = {
        label: sum(item["mechanism_class"] == label for item in classifications)
        for label in MECHANISM_CLASSES
    }
    return {
        "protocol": "Q10-PF6-RH1-LA1",
        "identity": "q10-rh1-la1-v1",
        "status": "ENGINEERING_LA1_COMPLETE_NO_SCIENTIFIC_PROMOTION",
        "source_execution": str(execution_path.relative_to(ROOT)).replace("\\", "/"),
        "source_execution_sha256": LA1.digest(execution_path),
        "source_selection_sha256": LA1.digest(execution_path.parent / "selection.json"),
        "source_hashes": context["hashes"],
        "selected_group_count": len(receipts),
        "selection_rule": context["contract"]["selection"],
        "score_domains": context["contract"]["score_domains"],
        "endpoint_score_aggregates": summarize_scores(receipts),
        "derived_classification_policy": CLASSIFICATION_POLICY,
        "derived_classification_policy_sha256": LA1.json_digest(CLASSIFICATION_POLICY),
        "mechanism_class_counts": mechanism_counts,
        "geometry_gate": {
            "actual_endpoints": list(LA1.ACTUAL_ENDPOINTS),
            "actual_endpoints_all_pass": all(
                receipt["endpoints"][name]["final_geometry_pass"]
                for receipt in receipts
                for name in LA1.ACTUAL_ENDPOINTS
            ),
            "counterfactual_diagnostic_pass_counts": {
                name: sum(receipt["endpoints"][name]["diagnostic_geometry_pass"] for receipt in receipts)
                for name in LA1.COUNTERFACTUAL_ENDPOINTS
            },
            "counterfactual_failure_is_non_blocking": True,
        },
        "morphology_labels": {
            "counts": dict(sorted(labels.items())),
            "descriptive_only": True,
        },
        "groups": [group_summary(receipt, classification) for receipt, classification in zip(receipts, classifications)],
        "integrity": {
            "all_group_receipts_verified": True,
            "all_baselines_match": all(receipt["integrity"]["same_baseline"] for receipt in receipts),
            "all_exact_replays_verified": all(receipt["integrity"]["exact_sequential_f32_replay"] for receipt in receipts),
            "actual_endpoint_geometry_hard_gate_pass": all(
                receipt["integrity"]["actual_endpoint_geometry_hard_gate_pass"] for receipt in receipts
            ),
        },
        "scope": {
            "engineering_only": True,
            "behavioral_probe": False,
            "scientific_promotion": False,
            "biological_or_behavioral_finding": False,
            "morphology_descriptive_only": True,
            "mechanism_class_descriptive_only": True,
        },
    }


def fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def build_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Q10-RH1-LA1 result",
        "",
        f"LA1 reconstructed `{summary['selected_group_count']}` receipt-selected primary groups.",
        "",
        "This is an engineering audit of exact f32 endpoint decomposition. It contains no biological, behavioral, or scientific promotion claim.",
        "",
        "## Selection",
        "",
        "A group entered the audit when `authority__h32.chosen.D` was strictly lexicographically better than `authority__h16.chosen.D` on `(mismatch_count, total_ulp_distance, residual_l2, maximum_absolute_residual)`.",
        "",
        "| group | coordinates | authority h16 D | authority h32 D | morphology | mechanism class |",
        "|---|---:|---|---|---|---|",
    ]
    for group in summary["groups"]:
        lines.append(
            f"| `{group['identity'][0]}:{group['identity'][1]}:{group['identity'][2]}` | {group['coordinates_total']} | {group['selection']['authority_h16_declared_score']} | {group['selection']['authority_h32_declared_score']} | `{group['morphology']['label']}` | `{group['mechanism_classification']['mechanism_class']}` |"
        )
    lines.extend([
        "",
        "## Derived mechanism classification",
        "",
        "`mechanism_class` is a descriptive-only derived label. It does not alter the sealed raw execution, describe behavior, or support a biological or scientific claim. The existing `morphology.label` remains the separate support/sign shape label for row-wise interaction.",
        "",
        f"Policy `{summary['derived_classification_policy']['version']}` uses strict lexicographic D/P/G score relations, exact row interaction, and recorded geometry debt/pass flags. The policy digest is `{summary['derived_classification_policy_sha256']}`.",
        "",
        "| mechanism class | count |",
        "|---|---:|",
    ])
    for label in MECHANISM_CLASSES:
        lines.append(f"| `{label}` | {summary['mechanism_class_counts'][label]} |")
    lines.extend([
        "",
        "The deterministic rules are:",
    ])
    for rule in summary["derived_classification_policy"]["rules"]:
        lines.append(f"- `{rule['label']}`: {rule['rule']}")
    lines.extend([
        "",
        "Each group record preserves the three requested D/P/G comparisons, exact interaction support and hash, and all endpoint geometry debt. A class is `UNRESOLVED` when these receipt metrics do not provide a defensible rule match.",
        "",
        "## D/P/G score aggregates",
        "",
        "Means are across selected groups. D is the declared group-row search domain; P is physical support; G is the whole endpoint. The exact per-group scores are in `SUMMARY.json` and the group receipts.",
        "",
        "| endpoint | domain | mean mismatches | mean ULP | mean residual L2 | mean max residual |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for name in ENDPOINT_NAMES:
        for domain in DOMAINS:
            item = summary["endpoint_score_aggregates"][name][domain]
            lines.append(
                f"| `{name}` | `{domain}` | {fmt(item['mismatch_count_mean'])} | {fmt(item['total_ulp_distance_mean'])} | {fmt(item['residual_l2_mean'])} | {fmt(item['maximum_absolute_residual_mean'])} |"
            )
    geometry = summary["geometry_gate"]
    lines.extend([
        "",
        "## Geometry and interaction",
        "",
        f"Inherited/actual endpoints W0, historical authority h16, and full authority h32 passed their hard geometry gate for all {summary['selected_group_count']} groups: `{geometry['actual_endpoints_all_pass']}`.",
        f"Counterfactual early diagnostic pass count: `{geometry['counterfactual_diagnostic_pass_counts']['authority_h32_early_ranks_1_16']}/{summary['selected_group_count']}`; late-only diagnostic pass count: `{geometry['counterfactual_diagnostic_pass_counts']['authority_h32_late_only_ranks_17_32']}/{summary['selected_group_count']}`. Counterfactual failures are recorded and are non-blocking by contract.",
        "",
        "For every endpoint row, the receipt records exact f32 bits and values and computes `I = (full-base)-(early-base)-(late-base)`. Morphology labels describe support and sign shape of I only; they are marked descriptive-only in the receipts.",
        "",
        "The exact committed prefix maps are canonical coordinate-to-prefix lists sorted by coordinate id. Geometry metrics, signed normalized debt, endpoint hashes, row interactions, and per-group D/P/G scores are preserved in the JSON receipts.",
        "",
    ])
    return "\n".join(lines)


def derive(execution_path: Path, output_dir: Path) -> dict[str, Any]:
    context, receipts = load_and_validate(execution_path.resolve())
    output_dir = LA1.output_path(ROOT, output_dir)
    summary = build_summary(context, receipts, execution_path.resolve())
    summary_path = output_dir / "SUMMARY.json"
    result_path = output_dir / "RESULT.md"
    status_path = output_dir / "STATUS.json"
    LA1.write_json(summary_path, summary)
    result_path.write_text(build_markdown(summary), encoding="utf-8", newline="\n")
    status = {
        "protocol": "Q10-PF6-RH1-LA1",
        "identity": "q10-rh1-la1-v1",
        "status": "ENGINEERING_LA1_COMPLETE_NO_SCIENTIFIC_PROMOTION",
        "raw_execution_sha256": summary["source_execution_sha256"],
        "selection_sha256": summary["source_selection_sha256"],
        "derived_summary_sha256": LA1.digest(summary_path),
        "derived_result_sha256": LA1.digest(result_path),
        "classification_policy_sha256": summary["derived_classification_policy_sha256"],
        "mechanism_class_counts": summary["mechanism_class_counts"],
        "mechanism_class_descriptive_only": True,
        "plan_sha256": LA1.digest(ROOT / "PLAN.md"),
        "contract_sha256": LA1.digest(ROOT / "CONTRACT.json"),
        "preexecution_sha256": LA1.digest(ROOT / "PREEXECUTION.json"),
        "selected_group_count": summary["selected_group_count"],
        "actual_endpoint_geometry_hard_gate_pass": summary["geometry_gate"]["actual_endpoints_all_pass"],
        "counterfactual_geometry_failures_non_blocking": True,
        "scientific_promotion": False,
        "behavioral_probe": False,
        "morphology_descriptive_only": True,
    }
    LA1.write_json(status_path, status)
    print(json.dumps(status, indent=2))
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="derive the Q10-RH1-LA1 report from raw receipts")
    parser.add_argument("--execution", type=Path, default=ROOT / "qualification" / "execution" / "execution.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "qualification" / "derived")
    args = parser.parse_args()
    try:
        derive(args.execution, args.output_dir)
    except (LA1.LA1Error, OSError, KeyError, TypeError, ValueError) as error:
        print(f"Q10-RH1-LA1 derivation failed closed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
