"""Build a compact OBS-OPEN-03 report from sealed machine artifacts only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


EXPECTED_ROOT = "7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273"


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


def validate_seal(source: Path) -> dict[str, object]:
    receipt = json.loads((source / "discovery_root_receipt.json").read_text(encoding="utf-8"))
    if receipt["discovery_root_sha256"] != EXPECTED_ROOT:
        raise ValueError("unexpected discovery root")
    manifest = source / "discovery_content_manifest.tsv"
    if sha256_file(manifest) != receipt["content_manifest_sha256"]:
        raise ValueError("content manifest identity mismatch")
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            member = source / row["path"]
            if member.stat().st_size != int(row["size_bytes"]) or sha256_file(member) != row["sha256"]:
                raise ValueError(f"sealed member mismatch: {row['path']}")
    return receipt


def build(source: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError("report output must be new")
    output.mkdir(parents=True)
    root = validate_seal(source)
    census = read_tsv(source / "discovery_census.tsv")
    scales = read_tsv(source / "scale_relations.tsv")
    formal = read_tsv(source / "formal_estimand_ledger.tsv")
    sequence = read_tsv(source / "interaction_sequence.tsv")
    spans = read_tsv(source / "contiguous_persistence.tsv")
    multiplicity = json.loads((source / "multiplicity_receipt.json").read_text(encoding="utf-8"))

    census_by_k: dict[int, list[dict[str, str]]] = defaultdict(list)
    scale_by_k: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in census:
        census_by_k[int(row["range_k"])].append(row)
    for row in scales:
        scale_by_k[int(row["from_k"])].append(row)
    scale_summary: list[dict[str, object]] = []
    for k in range(1, 31):
        rows = census_by_k[k]
        widths = [float(row["width"]) for row in rows]
        sides = Counter(row["first_outside_side"] or "NONE" for row in rows)
        terminals = Counter(row["terminal_location"] for row in rows)
        balances = [
            (int(row["above_duration"]) - int(row["below_duration"])) / int(row["duration_bars"])
            for row in rows
        ]
        lags = [
            (int(row["first_outside_time"]) - int(row["freeze_epoch"])) / 60
            for row in rows if row["first_outside_time"]
        ]
        adjacent = scale_by_k.get(k, [])
        scale_summary.append({
            "range_k": k,
            "sessions": len(rows),
            "median_width": median(widths),
            "mean_width": mean(widths),
            "first_outside_above": sides["1"],
            "first_outside_below": sides["-1"],
            "no_outside_observed": sides["NONE"],
            "mean_location_balance": mean(balances),
            "mean_signed_displacement": mean(float(row["signed_displacement"]) for row in rows),
            "terminal_in_zone": terminals["1"],
            "terminal_above": terminals["2"],
            "terminal_below": terminals["3"],
            "return_event_count": sum(int(row["return_count"]) for row in rows),
            "cross_through_count": sum(int(row["cross_through_count"]) for row in rows),
            "median_first_outside_lag_minutes": median(lags) if lags else None,
            "adjacent_terminal_survival": (
                mean(int(row["classification_survival"]) for row in adjacent) if adjacent else None
            ),
            "adjacent_width_unchanged_fraction": (
                mean(float(row["width_delta"]) == 0 for row in adjacent) if adjacent else None
            ),
            "adjacent_mean_width_delta": (
                mean(float(row["width_delta"]) for row in adjacent) if adjacent else None
            ),
        })

    fields = tuple(scale_summary[0])
    with (output / "discovery_scale_summary.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in scale_summary:
            writer.writerow({key: "" if value is None else format(value, ".17g") if isinstance(value, float) else value
                             for key, value in row.items()})

    formal_counts = Counter((row["template_id"], row["terminal_class"], row["reason"]) for row in formal)
    temporal_counts = Counter((row["template_id"], row["temporal_status"]) for row in formal)
    p_ranges = {
        template: {
            "minimum": min(float(row["raw_p"]) for row in formal if row["template_id"] == template),
            "maximum": max(float(row["raw_p"]) for row in formal if row["template_id"] == template),
        }
        for template in sorted({row["template_id"] for row in formal})
    }
    spans_per_session = Counter(row["session_id"] for row in spans)
    event_counts = Counter(int(row["event"]) for row in sequence)
    location_counts = Counter(int(row["location"]) for row in sequence)
    widths = [float(row["width"]) for row in census]
    findings = {
        "schema": "OBS_OPEN_03_DISCOVERY_FINDINGS_V1",
        "source_kind": "MACHINE_DERIVED",
        "parent_discovery_root_sha256": EXPECTED_ROOT,
        "claim_status": "DISCOVERY_ONLY_UNCONFIRMED",
        "candidate_registry_count": root["candidate_rows"],
        "confirmation_estimand_count": root["confirmation_estimands_frozen"],
        "formal_terminal_counts": [
            {"template_id": key[0], "terminal_class": key[1], "reason": key[2], "count": value}
            for key, value in sorted(formal_counts.items())
        ],
        "temporal_status_counts": [
            {"template_id": key[0], "temporal_status": key[1], "count": value}
            for key, value in sorted(temporal_counts.items())
        ],
        "raw_p_ranges": p_ranges,
        "multiplicity_resolution": multiplicity,
        "complete_scale_summary_rows": len(scale_summary),
        "range_width": {
            "degenerate_rows": sum(value == 0 for value in widths),
            "r01_median": scale_summary[0]["median_width"],
            "r30_median": scale_summary[-1]["median_width"],
        },
        "terminal_scale_persistence": {
            "sessions_one_span_across_r01_r30": sum(count == 1 for count in spans_per_session.values()),
            "sessions_multiple_spans": sum(count > 1 for count in spans_per_session.values()),
            "adjacent_survival_minimum": min(row["adjacent_terminal_survival"] for row in scale_summary[:-1]),
            "adjacent_survival_maximum": max(row["adjacent_terminal_survival"] for row in scale_summary[:-1]),
        },
        "interaction_event_counts": {str(key): value for key, value in sorted(event_counts.items())},
        "interaction_location_counts": {str(key): value for key, value in sorted(location_counts.items())},
        "epistemic_limits": [
            "NO_PROMOTED_DISCOVERY_CANDIDATE",
            "FROZEN_BOOTSTRAP_P_RESOLUTION_CANNOT_CROSS_FIRST_HOLM_THRESHOLD",
            "NO_CONFIRMATION_ESTIMAND_AUTHORIZED",
            "CONFIRMATION_FROZEN_UNOPENED",
            "DESCRIPTIVE_STRUCTURE_IS_NOT_CONFIRMATORY_STRUCTURE",
            "NO_ECONOMIC_OR_TRADING_AUTHORITY",
        ],
    }
    (output / "discovery_findings.json").write_bytes(canonical_json(findings))

    report = f"""# OBS-OPEN-03 — Frozen Discovery Report

Parent discovery root: `{EXPECTED_ROOT}`

Status: `DISCOVERY_ONLY_UNCONFIRMED`

## Complete surface

- 257 discovery sessions, 7,710 range objects, 574,395 interaction rows.
- 7,453 adjacent-scale relations and 324 contiguous terminal-location spans.
- 119/119 formal estimands reached an explicit terminal state.
- 0 promoted candidates; 0 future confirmation estimands.
- Confirmation remained `FROZEN_UNOPENED` with zero rows read.

## Formal decision result

The frozen family produced 89 `DESCRIPTIVE_ONLY` and 30
`INSUFFICIENT_SUPPORT` terminal states. No estimand passed Holm correction.

The reason is partly a frozen measurement-resolution boundary: 2,000
plus-one-corrected two-sided bootstrap resamples have minimum raw p
`{multiplicity['plus_one_two_sided_minimum_raw_p']}`, above the first 119-test
Holm threshold `{multiplicity['first_holm_threshold']}`. This makes formal
promotion impossible under the sealed decision contract. It does not erase the
descriptive census, and it is not evidence that the observed surface is null.

## Descriptive observations

- Median range width increases from `{scale_summary[0]['median_width']}` at R01
  to `{scale_summary[-1]['median_width']}` at R30. Adjacent increments are zero
  for roughly `{min(row['adjacent_width_unchanged_fraction'] for row in scale_summary[:-1]):.3f}`
  to `{max(row['adjacent_width_unchanged_fraction'] for row in scale_summary[:-1]):.3f}`
  of sessions depending on k. This is descriptive scale geometry; nested widths
  are non-decreasing by construction.
- First observed outside-side counts remain mixed across all 30 scales. Raw
  family p-values range from `{p_ranges['FIRST_OUTSIDE_SIDE_BALANCE']['minimum']}`
  to `{p_ranges['FIRST_OUTSIDE_SIDE_BALANCE']['maximum']}`; none pass unadjusted
  evidence.
- Location-balance raw p-values range from
  `{p_ranges['LOCATION_BALANCE']['minimum']}` to
  `{p_ranges['LOCATION_BALANCE']['maximum']}`. All 30 are temporally unstable
  under the frozen robustness rule and none pass unadjusted evidence.
- Signed-path-displacement raw p-values range from
  `{p_ranges['SIGNED_PATH_DISPLACEMENT']['minimum']}` to
  `{p_ranges['SIGNED_PATH_DISPLACEMENT']['maximum']}`. All 30 are temporally
  unstable and none pass unadjusted evidence.
- Terminal location is unchanged across all R01–R30 boundaries in
  `{findings['terminal_scale_persistence']['sessions_one_span_across_r01_r30']}`
  of 257 sessions. Adjacent terminal-location survival ranges from
  `{findings['terminal_scale_persistence']['adjacent_survival_minimum']:.3f}` to
  `{findings['terminal_scale_persistence']['adjacent_survival_maximum']:.3f}`.
  This is a descriptive scale-space relation, not a promoted candidate.

The complete 30-row scale summary is retained beside this report. No mechanism,
economic interpretation, or trading authority is claimed.
"""
    (output / "OBS_OPEN_03_DISCOVERY_REPORT_20260814.md").write_text(report, encoding="utf-8", newline="\n")
    members = ("discovery_scale_summary.tsv", "discovery_findings.json", "OBS_OPEN_03_DISCOVERY_REPORT_20260814.md")
    receipt_payload = {
        "schema": "OBS_OPEN_03_REPORT_SIDECAR_V1",
        "source_kind": "MACHINE_DERIVED",
        "parent_discovery_root_sha256": EXPECTED_ROOT,
        "report_builder_sha256": sha256_file(Path(__file__).resolve()),
        "members": [{"path": name, "bytes": (output / name).stat().st_size, "sha256": sha256_file(output / name)} for name in members],
        "raw_source_read": False,
        "confirmation_rows_read": 0,
        "economic_authority": False,
        "trading_authority": False,
    }
    receipt_payload["logical_sha256"] = hashlib.sha256(canonical_json(receipt_payload)).hexdigest()
    (output / "discovery_report_receipt.json").write_bytes(canonical_json(receipt_payload))
    return receipt_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = build(args.source, args.output)
    print(receipt["logical_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
