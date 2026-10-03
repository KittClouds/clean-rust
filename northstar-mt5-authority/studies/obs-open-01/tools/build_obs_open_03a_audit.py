"""OBS-OPEN-03A observer-geometry and inferential-resolution audit.

Only sealed OBS-OPEN-03 products are admissible. This audit does not read raw
source bars, confirmation observations, or economic data, and it never changes
the original discovery decisions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence


DISCOVERY_ROOT = "7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273"
ALPHA = 0.05
FORMAL_TESTS = 119
BOOTSTRAP_RESAMPLES = 2000


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fields})


def validate_sealed_discovery(source: Path) -> dict[str, object]:
    receipt = json.loads((source / "discovery_root_receipt.json").read_text(encoding="utf-8"))
    if receipt["discovery_root_sha256"] != DISCOVERY_ROOT:
        raise ValueError("unexpected OBS-OPEN-03 discovery root")
    manifest = source / "discovery_content_manifest.tsv"
    if sha256_file(manifest) != receipt["content_manifest_sha256"]:
        raise ValueError("discovery content manifest mismatch")
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            member = source / row["path"]
            if member.stat().st_size != int(row["size_bytes"]) or sha256_file(member) != row["sha256"]:
                raise ValueError(f"sealed discovery member mismatch: {row['path']}")
    if receipt["confirmation_rows_read"] != 0 or receipt["confirmation_status"] != "FROZEN_UNOPENED":
        raise ValueError("confirmation firewall authority mismatch")
    return receipt


def estimand_classification(formal: Sequence[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in formal:
        template = row["template_id"]
        k = int(row["range_k"])
        if template == "WIDTH_DELTA_ADJACENT":
            classification = "OBSERVER_CONSTRAINED"
            value_authority = "EMPIRICAL_MAGNITUDE_WITH_OBSERVER_IMPLIED_NONNEGATIVE_DOMAIN"
            constraint = "NESTED_RANGES_FORCE_WIDTH_K_PLUS_1_GTE_WIDTH_K"
            alias_group = ""
        elif template == "SIGNED_PATH_DISPLACEMENT":
            group = math.ceil(k / 5)
            classification = "OBSERVER_CONSTRAINED"
            value_authority = "EMPIRICAL_GROUP_VALUE_WITH_OBSERVER_IMPLIED_FIVE_SCALE_ALIAS"
            constraint = "COMPLETED_M5_ELIGIBILITY_QUANTIZES_PATH_START"
            alias_group = f"SIGNED_DISPLACEMENT_M5_START_G{group:02d}"
        elif template == "FIRST_OUTSIDE_SIDE_BALANCE":
            classification = "EMPIRICAL"
            value_authority = "EMPIRICAL_SIGNED_SIDE_AMONG_ELIGIBLE_OUTSIDE_OBSERVATIONS"
            constraint = "NESTED_ZONE_AND_SHORTENING_HORIZON_CONSTRAIN_ELIGIBILITY_NOT_SIDE"
            alias_group = ""
        elif template == "LOCATION_BALANCE":
            classification = "EMPIRICAL"
            value_authority = "EMPIRICAL_LOCATION_OCCUPANCY_CONTRAST"
            constraint = "BOUNDED_MINUS_ONE_TO_PLUS_ONE_WITH_NESTED_ZONE_AND_QUANTIZED_HORIZON"
            alias_group = ""
        else:
            raise ValueError(f"unknown formal template: {template}")
        rows.append({
            "estimand_id": row["estimand_id"],
            "source_kind": "MACHINE_DERIVED",
            "template_id": template,
            "range_k": k,
            "adjacent_to_k": row["adjacent_to_k"],
            "geometry_class": classification,
            "value_authority": value_authority,
            "observer_constraint": constraint,
            "observer_alias_group": alias_group,
            "original_terminal_class": row["terminal_class"],
            "original_reason": row["reason"],
            "original_temporal_status": row["temporal_status"],
            "original_decision_changed": False,
        })
    return rows


def invariant_checks(
    census: Sequence[dict[str, str]],
    scales: Sequence[dict[str, str]],
    formal: Sequence[dict[str, str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    scale_by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in census:
        by_session[row["session_id"]].append(row)
    for row in scales:
        scale_by_session[row["session_id"]].append(row)
    for rows in by_session.values():
        rows.sort(key=lambda item: int(item["range_k"]))
    for rows in scale_by_session.values():
        rows.sort(key=lambda item: int(item["from_k"]))

    failures = Counter()
    transition_sessions = 0
    one_span_sessions = 0
    no_outside_monotone = 0
    signed_alias_comparisons = 0
    for session_id, rows in sorted(by_session.items()):
        if len(rows) != 30:
            failures["R01_R30_COMPLETE"] += 1
            continue
        # These are exact decimal authority fields. Using Decimal prevents the
        # audit itself from introducing binary-floating equality semantics.
        highs = [Decimal(row["range_high"]) for row in rows]
        lows = [Decimal(row["range_low"]) for row in rows]
        widths = [Decimal(row["width"]) for row in rows]
        midpoints = [Decimal(row["midpoint"]) for row in rows]
        if any(right < left for left, right in zip(highs, highs[1:])):
            failures["HIGH_NONDECREASING"] += 1
        if any(right > left for left, right in zip(lows, lows[1:])):
            failures["LOW_NONINCREASING"] += 1
        if any(right < left for left, right in zip(widths, widths[1:])):
            failures["WIDTH_NONDECREASING"] += 1
        for index in range(29):
            if widths[index + 1] == widths[index] and (
                highs[index + 1] != highs[index] or lows[index + 1] != lows[index] or midpoints[index + 1] != midpoints[index]
            ):
                failures["ZERO_DELTA_FREEZES_GEOMETRY"] += 1
        for group in range(6):
            block = rows[group * 5:(group + 1) * 5]
            expected_bars = 77 - group
            if any(int(row["duration_bars"]) != expected_bars for row in block):
                failures["M5_DURATION_ALIAS"] += 1
            displacements = {row["signed_displacement"] for row in block}
            signed_alias_comparisons += 4
            if len(displacements) != 1:
                failures["SIGNED_DISPLACEMENT_ALIAS"] += 1
        terminals = [int(row["terminal_location"]) for row in rows]
        changes = sum(left != right for left, right in zip(terminals, terminals[1:]))
        transition_sessions += changes > 0
        one_span_sessions += changes == 0
        if changes > 1:
            failures["TERMINAL_AT_MOST_ONE_TRANSITION"] += 1
        seen_in_zone = False
        initial_side = next((value for value in terminals if value != 1), None)
        for value in terminals:
            if value == 1:
                seen_in_zone = True
            elif seen_in_zone or (initial_side is not None and value != initial_side):
                failures["TERMINAL_NESTED_TRANSITION_DOMAIN"] += 1
                break
        absent = [not row["first_outside_time"] for row in rows]
        if any(left and not right for left, right in zip(absent, absent[1:])):
            failures["NO_OUTSIDE_MONOTONE"] += 1
        else:
            no_outside_monotone += 1
        if any(Decimal(row["width_delta"]) < 0 for row in scale_by_session[session_id]):
            failures["WIDTH_DELTA_NONNEGATIVE"] += 1

    signed_formal: dict[int, dict[str, str]] = {
        int(row["range_k"]): row for row in formal if row["template_id"] == "SIGNED_PATH_DISPLACEMENT"
    }
    for group in range(6):
        block = [signed_formal[k] for k in range(group * 5 + 1, group * 5 + 6)]
        if len({(row["point_estimate"], row["raw_p"], row["lower_95"], row["upper_95"]) for row in block}) != 1:
            failures["SIGNED_FORMAL_ALIAS"] += 1

    checks = [
        {
            "invariant_id": "NESTED_RANGE_GEOMETRY",
            "source_kind": "MACHINE_DERIVED",
            "derivation_basis": "ARTIFACT_DECLARED_OBSERVER_SEMANTICS",
            "statement": "high nondecreasing, low nonincreasing, width nondecreasing across k",
            "scientific_role": "OBSERVER_IMPLIED",
            "corpus_check": "PASS" if not any(failures[key] for key in ("HIGH_NONDECREASING", "LOW_NONINCREASING", "WIDTH_NONDECREASING")) else "FAIL",
        },
        {
            "invariant_id": "NONNEGATIVE_WIDTH_DELTA",
            "source_kind": "MACHINE_DERIVED",
            "derivation_basis": "ARTIFACT_DECLARED_OBSERVER_SEMANTICS",
            "statement": "width(k+1)-width(k) >= 0",
            "scientific_role": "OBSERVER_IMPLIED",
            "corpus_check": "PASS" if not failures["WIDTH_DELTA_NONNEGATIVE"] else "FAIL",
        },
        {
            "invariant_id": "FIVE_SCALE_M5_START_ALIAS",
            "source_kind": "MACHINE_DERIVED",
            "derivation_basis": "ARTIFACT_DECLARED_OBSERVER_SEMANTICS",
            "statement": "ceil(k/5) fixes first eligible completed M5 bar; path duration and signed displacement alias in six five-scale groups",
            "scientific_role": "OBSERVER_IMPLIED",
            "corpus_check": "PASS" if not failures["M5_DURATION_ALIAS"] and not failures["SIGNED_DISPLACEMENT_ALIAS"] else "FAIL",
        },
        {
            "invariant_id": "TERMINAL_NESTED_ABSORPTION",
            "source_kind": "MACHINE_DERIVED",
            "derivation_basis": "ARTIFACT_DECLARED_OBSERVER_SEMANTICS",
            "statement": "fixed terminal close may remain outside or enter the expanding zone once; it cannot leave or cross side as k increases",
            "scientific_role": "OBSERVER_IMPLIED",
            "corpus_check": "PASS" if not failures["TERMINAL_AT_MOST_ONE_TRANSITION"] and not failures["TERMINAL_NESTED_TRANSITION_DOMAIN"] else "FAIL",
        },
        {
            "invariant_id": "NO_OUTSIDE_MONOTONE",
            "source_kind": "MACHINE_DERIVED",
            "derivation_basis": "ARTIFACT_DECLARED_OBSERVER_SEMANTICS",
            "statement": "if no outside close exists at k, none can appear at k+1 under complete shared coverage",
            "scientific_role": "OBSERVER_IMPLIED",
            "corpus_check": "PASS" if not failures["NO_OUTSIDE_MONOTONE"] else "FAIL",
        },
    ]
    if failures:
        meaningful = {key: value for key, value in failures.items() if value}
        if meaningful:
            raise ValueError(f"observer invariant verification failed: {meaningful}")
    summary = {
        "sessions_checked": len(by_session),
        "one_terminal_span_sessions": one_span_sessions,
        "two_terminal_span_sessions": transition_sessions,
        "no_outside_monotonic_sessions": no_outside_monotone,
        "signed_displacement_alias_comparisons": signed_alias_comparisons,
        "formal_signed_alias_groups": 6,
        "formal_signed_duplicate_estimands_beyond_group_representatives": 24,
    }
    return checks, summary


def resolution_receipt() -> dict[str, object]:
    minimum_p = 2 / (BOOTSTRAP_RESAMPLES + 1)
    first_holm = ALPHA / FORMAL_TESTS
    arithmetic_touch_floor = math.ceil((2 * FORMAL_TESTS / ALPHA) - 1)
    return {
        "schema": "OBS_OPEN_03A_INFERENTIAL_RESOLUTION_V1",
        "source_kind": "MACHINE_DERIVED",
        "parent_discovery_root_sha256": DISCOVERY_ROOT,
        "formal_test_count": FORMAL_TESTS,
        "alpha": ALPHA,
        "frozen_bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "two_sided_plus_one_minimum_p": minimum_p,
        "first_holm_threshold": first_holm,
        "first_holm_rejection_reachable": minimum_p <= first_holm,
        "arithmetic_minimum_resamples_to_touch_first_holm_threshold": arithmetic_touch_floor,
        "arithmetic_floor_status": "BOUNDARY_ONLY_NOT_OPERATIONAL_SELECTION",
        "future_operational_resample_count": None,
        "future_selection_requirement": "PREDECLARED_NUMERICAL_PRECISION_CRITERION_IN_NEW_EXPLORATORY_PROTOCOL",
        "discovery_decisions_changed": False,
        "original_candidate_registry_changed": False,
        "post_discovery_extension_authorized": False,
        "confirmation_access_authorized": False,
    }


def build(source: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError("audit output must be new")
    output.mkdir(parents=True)
    discovery = validate_sealed_discovery(source)
    census = read_tsv(source / "discovery_census.tsv")
    scales = read_tsv(source / "scale_relations.tsv")
    formal = read_tsv(source / "formal_estimand_ledger.tsv")
    if len(census) != 7710 or len(scales) != 7453 or len(formal) != 119:
        raise ValueError("sealed discovery cardinality mismatch")

    classifications = estimand_classification(formal)
    counts = Counter(row["geometry_class"] for row in classifications)
    write_tsv(
        output / "estimand_geometry_classification.tsv",
        tuple(classifications[0]),
        classifications,
    )
    invariants, corpus_summary = invariant_checks(census, scales, formal)
    (output / "observer_invariants.json").write_bytes(canonical_json({
        "schema": "OBS_OPEN_03A_OBSERVER_INVARIANTS_V1",
        "parent_discovery_root_sha256": DISCOVERY_ROOT,
        "invariants": invariants,
        "corpus_verification": corpus_summary,
        "raw_source_read": False,
        "confirmation_rows_read": 0,
    }))
    resolution = resolution_receipt()
    (output / "inferential_resolution_receipt.json").write_bytes(canonical_json(resolution))

    findings = {
        "schema": "OBS_OPEN_03A_FINDINGS_V1",
        "source_kind": "MACHINE_DERIVED",
        "parent_discovery_root_sha256": DISCOVERY_ROOT,
        "classification_counts": dict(sorted(counts.items())),
        "classification_semantics": {
            "OBSERVER_IMPLIED": "NUMERIC_VALUE_DERIVABLE_WITHOUT_OBSERVED_PROCESS_VALUES",
            "OBSERVER_CONSTRAINED": "OBSERVER_FIXES_DOMAIN_OR_ALIAS_RELATION_BUT_EMPIRICAL_DEGREES_REMAIN",
            "EMPIRICAL": "NO_EXACT_OBSERVER_IDENTITY_PROVEN_FOR_NUMERIC_VALUE",
        },
        "observer_implied_formal_estimands": 0,
        "observer_constrained_formal_estimands": counts["OBSERVER_CONSTRAINED"],
        "empirical_formal_estimands": counts["EMPIRICAL"],
        "observer_implied_relations_are_recorded_separately": True,
        "signed_displacement_formal_tests": 30,
        "signed_displacement_observer_alias_groups": 6,
        "signed_displacement_redundant_test_instances": 24,
        "observer_distinct_formal_upper_bound": 95,
        "multiplicity_family_retroactively_changed": False,
        "terminal_persistence_decomposition": {
            "observer_implied": "at most one terminal-location transition across R01-R30",
            "empirical": corpus_summary,
        },
        "inferential_resolution": resolution,
        "original_candidate_count": discovery["candidate_rows"],
        "original_rejection_count": discovery["rejection_rows"],
        "confirmation_status": "FROZEN_UNOPENED",
        "confirmation_rows_read": 0,
        "economic_authority": False,
        "trading_authority": False,
    }
    (output / "obs_open_03a_findings.json").write_bytes(canonical_json(findings))

    report = f"""# OBS-OPEN-03A - Observer Geometry and Inferential Resolution Audit

Parent discovery root: `{DISCOVERY_ROOT}`

Status: `SEALED_PRODUCTS_ONLY / CONFIRMATION_UNOPENED`

## Estimand geometry

- `OBSERVER_IMPLIED`: 0 formal estimands. The formal values are not completely
  fixed by the observer, although several relations among them are.
- `OBSERVER_CONSTRAINED`: {counts['OBSERVER_CONSTRAINED']} estimands.
- `EMPIRICAL`: {counts['EMPIRICAL']} estimands.

All 29 adjacent width-delta estimands are observer-constrained: nesting forces
their sign domain to be nonnegative, while zero frequency and magnitude remain
empirical. All 30 signed-displacement estimands are observer-constrained by the
completed-M5 clock. They collapse into six five-scale path-start groups, leaving
24 observer-implied duplicate test instances. The 30 first-outside-side and 30
location-balance estimands remain empirical under their declared eligibility
and bounded-domain contracts.

## Observer invariants

The sealed corpus exactly satisfies the derived nested-range invariants:

- range high is nondecreasing, range low is nonincreasing, and width is
  nondecreasing across k;
- adjacent width delta cannot be negative;
- completed-M5 eligibility aliases k into six path-start groups;
- terminal location can enter the expanding zone at most once and cannot leave
  it or cross to the opposite outside side as k increases;
- absence of an outside close is monotone under expanding nested boundaries and
  shortening observation horizons.

Therefore the previously observed terminal persistence is partly imposed by the
observer. The empirical residue is the split: {corpus_summary['one_terminal_span_sessions']}
sessions never changed terminal location and {corpus_summary['two_terminal_span_sessions']}
changed once across R01-R30.

## Inferential resolution

For 119 tests at alpha 0.05, the first Holm threshold is
`{resolution['first_holm_threshold']}`. With 2,000 two-sided plus-one bootstrap
resamples, minimum p is `{resolution['two_sided_plus_one_minimum_p']}` and cannot
reach that threshold.

`B_min = {resolution['arithmetic_minimum_resamples_to_touch_first_holm_threshold']}`
is recorded only as the arithmetic floor required to touch the first Holm
boundary. It is not an operational recommendation or a selected future
resample count. Any later count must be chosen prospectively from an explicit
numerical-precision criterion in a new post-discovery exploratory protocol.

No OBS-OPEN-03 decision was changed. No confirmation claim was created. The 69
confirmation sessions remain `FROZEN_UNOPENED`.
"""
    (output / "OBS_OPEN_03A_AUDIT_20260814.md").write_text(report, encoding="utf-8", newline="\n")

    members = (
        "estimand_geometry_classification.tsv",
        "observer_invariants.json",
        "inferential_resolution_receipt.json",
        "obs_open_03a_findings.json",
        "OBS_OPEN_03A_AUDIT_20260814.md",
    )
    manifest_rows = [{"path": name, "size_bytes": (output / name).stat().st_size, "sha256": sha256_file(output / name)} for name in members]
    write_tsv(output / "obs_open_03a_content_manifest.tsv", ("path", "size_bytes", "sha256"), manifest_rows)
    root_payload = {
        "schema": "OBS_OPEN_03A_ROOT_V1",
        "source_kind": "MACHINE_DERIVED",
        "parent_discovery_root_sha256": DISCOVERY_ROOT,
        "audit_builder_sha256": sha256_file(Path(__file__).resolve()),
        "content_manifest_sha256": sha256_file(output / "obs_open_03a_content_manifest.tsv"),
        "formal_estimands_classified": len(classifications),
        "classification_counts": dict(sorted(counts.items())),
        "raw_source_read": False,
        "confirmation_rows_read": 0,
        "confirmation_status": "FROZEN_UNOPENED",
        "original_discovery_decisions_changed": False,
        "economic_authority": False,
        "trading_authority": False,
    }
    root_payload["obs_open_03a_root_sha256"] = hashlib.sha256(canonical_json(root_payload)).hexdigest()
    (output / "obs_open_03a_root_receipt.json").write_bytes(canonical_json(root_payload))
    return root_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = build(args.source, args.output)
    print(receipt["obs_open_03a_root_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
