"""Frozen OBS-OPEN-03 discovery execution.

This executable reads only the bounded discovery prefix, applies the sealed
OBS-OPEN-02 + R1 + R2 contracts, and emits deterministic D-drive artifacts.
It never opens confirmation observations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping, Sequence

from obs_open_02_confirmation_guard import PartitionGuard
from obs_open_02r1_familywise_rules import (
    SupportSnapshot,
    bootstrap_summary,
    expand_estimand_ids,
    holm_bonferroni,
    support_pass,
    temporal_status,
)
from obs_open_02r2_data_quality import (
    HEADER,
    bounded_prefix_lines,
    load_metadata,
    minute_epoch,
)
from obs_open_02r2_semantics import (
    LOCATION_ABOVE,
    LOCATION_BELOW,
    LOCATION_IN_ZONE,
    PathBar,
    adjacent_relations,
    contiguous_terminal_spans,
    describe_path,
    emit_confirmation_estimand,
)


UNIVERSE_ROOT = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235"
PROTOCOL_ROOT = "141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5"
R1_ROOT = "dc8826042d490c5b1e868b836f4c187af8e2baedf9454d11b2be2a5a5aae3da7"
R2_ROOT = "9f7a011d5f31b498f713b6a2459c36af19dc2e388736678919cf8344f937d234"
SOURCE_PREFIX_SHA256 = "6dde69a9ae069b95f49e1759fb5feb595dc22b04e76534f8c6cd15caa3b4249e"

EVENT_IN_ZONE = 1
EVENT_FIRST_ABOVE = 2
EVENT_PERSIST_ABOVE = 3
EVENT_FAILED_ABOVE = 4
EVENT_RETURN_ABOVE = 5
EVENT_FIRST_BELOW = 6
EVENT_PERSIST_BELOW = 7
EVENT_FAILED_BELOW = 8
EVENT_RETURN_BELOW = 9
EVENT_CROSS_ABOVE_TO_BELOW = 10
EVENT_CROSS_BELOW_TO_ABOVE = 11


@dataclass(frozen=True)
class SourceBar:
    epoch: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Session:
    session_id: str
    civil_date: str
    offset_minutes: int
    start_epoch: int
    area_end_epoch: int


@dataclass(frozen=True)
class Estimand:
    estimand_id: str
    template_id: str
    range_k: int
    adjacent_to_k: int | None
    representation: str
    session_value_definition: str
    eligibility_definition: str


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return format(value, ".17g")
    return str(value)


class TsvWriter:
    def __init__(self, path: Path, fields: Sequence[str]) -> None:
        self.handle = path.open("w", newline="", encoding="utf-8")
        self.fields = tuple(fields)
        self.writer = csv.DictWriter(
            self.handle, fieldnames=self.fields, delimiter="\t", lineterminator="\n",
            extrasaction="raise",
        )
        self.writer.writeheader()
        self.rows = 0

    def write(self, row: Mapping[str, object]) -> None:
        self.writer.writerow({key: scalar(row.get(key)) for key in self.fields})
        self.rows += 1

    def close(self) -> None:
        self.handle.close()


def verify_parent_authority(repo: Path, partition: Path) -> PartitionGuard:
    seal = repo / "studies/obs-open-01/qualification/universe/obs-open-02r2-seal"
    root = json.loads((seal / "obs_open_02r2_root_receipt.json").read_text(encoding="utf-8"))
    expected = {
        "universe_root_sha256": UNIVERSE_ROOT,
        "protocol_root_sha256": PROTOCOL_ROOT,
        "r1_root_sha256": R1_ROOT,
        "r2_root_sha256": R2_ROOT,
    }
    for key, value in expected.items():
        if root.get(key) != value:
            raise ValueError(f"R2 authority mismatch: {key}")
    if root.get("data_quality_outcome") != "PASS":
        raise ValueError("discovery source quality is not qualified")
    manifest = seal / "obs_open_02r2_content_manifest.tsv"
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            member = repo / row["path"]
            if member.stat().st_size != int(row["size_bytes"]) or sha256_file(member) != row["sha256"]:
                raise ValueError(f"R2 seal member mismatch: {row['path']}")
    guard = PartitionGuard.from_manifest(partition)
    if len(guard.discovery_session_ids) != 257 or len(guard.confirmation_session_ids) != 69:
        raise ValueError("partition cardinality mismatch")
    return guard


def session_table(discovery: Sequence[dict[str, str]]) -> tuple[Session, ...]:
    rows: list[Session] = []
    for row in discovery:
        day = date.fromisoformat(row["civil_date"])
        offset = int(row["server_offset_minutes"])
        start = minute_epoch(day, time(9, 30), offset)
        rows.append(Session(row["session_id"], row["civil_date"], offset, start, start + 390 * 60))
    return tuple(sorted(rows, key=lambda item: item.session_id))


def load_discovery_bars(
    source: Path,
    sessions: Sequence[Session],
    safe_rows: int,
    total_rows: int,
) -> tuple[dict[str, list[SourceBar]], dict[str, list[SourceBar]], str]:
    m1_owner: dict[int, str] = {}
    m5_owner: dict[int, str] = {}
    for session in sessions:
        for index in range(30):
            m1_owner[session.start_epoch + index * 60] = session.session_id
        for index in range(79):
            m5_owner[session.start_epoch + index * 300] = session.session_id
    m1: dict[str, list[SourceBar]] = defaultdict(list)
    m5: dict[str, list[SourceBar]] = defaultdict(list)
    digest = hashlib.sha256()
    stream = bounded_prefix_lines(source, safe_rows, total_rows)
    header = next(stream)
    digest.update(header)
    if tuple(header.decode("utf-8-sig").rstrip("\r\n").split("\t")) != HEADER:
        raise ValueError("source schema mismatch")
    for raw in stream:
        digest.update(raw)
        parts = raw.decode("utf-8").rstrip("\r\n").split("\t")
        if len(parts) != len(HEADER):
            raise ValueError("source row width mismatch")
        row = dict(zip(HEADER, parts))
        epoch = int(row["server_epoch"])
        timeframe = row["timeframe"]
        owner = m1_owner.get(epoch) if timeframe == "M1" else m5_owner.get(epoch) if timeframe == "M5" else None
        if owner is None:
            continue
        bar = SourceBar(epoch, *(Decimal(row[key]) for key in ("open", "high", "low", "close")))
        (m1 if timeframe == "M1" else m5)[owner].append(bar)
    prefix_hash = digest.hexdigest()
    if prefix_hash != SOURCE_PREFIX_SHA256:
        raise ValueError("discovery source prefix hash mismatch")
    for session in sessions:
        if len(m1[session.session_id]) != 30 or len(m5[session.session_id]) != 79:
            raise ValueError(f"source coverage mismatch: {session.session_id}")
        m1[session.session_id].sort(key=lambda bar: bar.epoch)
        m5[session.session_id].sort(key=lambda bar: bar.epoch)
    return dict(m1), dict(m5), prefix_hash


def classify(close: Decimal, high: Decimal, low: Decimal) -> int:
    if close > high:
        return LOCATION_ABOVE
    if close < low:
        return LOCATION_BELOW
    return LOCATION_IN_ZONE


def interaction_path(bars: Sequence[SourceBar], high: Decimal, low: Decimal, freeze: int, end: int) -> list[PathBar]:
    result: list[PathBar] = []
    previous = 0
    outside_run = 0
    previous_epoch = 0
    for bar in bars:
        if bar.epoch < freeze or bar.epoch + 300 > end:
            continue
        if previous_epoch and bar.epoch - previous_epoch != 300:
            raise ValueError("qualified M5 path lost continuity")
        location = classify(bar.close, high, low)
        if location == LOCATION_IN_ZONE:
            if previous == LOCATION_ABOVE:
                event = EVENT_FAILED_ABOVE if outside_run == 1 else EVENT_RETURN_ABOVE
            elif previous == LOCATION_BELOW:
                event = EVENT_FAILED_BELOW if outside_run == 1 else EVENT_RETURN_BELOW
            else:
                event = EVENT_IN_ZONE
        elif location == LOCATION_ABOVE:
            event = (
                EVENT_PERSIST_ABOVE if previous == LOCATION_ABOVE else
                EVENT_CROSS_BELOW_TO_ABOVE if previous == LOCATION_BELOW else
                EVENT_FIRST_ABOVE
            )
        else:
            event = (
                EVENT_PERSIST_BELOW if previous == LOCATION_BELOW else
                EVENT_CROSS_ABOVE_TO_BELOW if previous == LOCATION_ABOVE else
                EVENT_FIRST_BELOW
            )
        if location == LOCATION_IN_ZONE:
            outside_run = 0
        elif location == previous:
            outside_run += 1
        else:
            outside_run = 1
        result.append(PathBar(bar.epoch, float(bar.close), location, event, outside_run))
        previous = location
        previous_epoch = bar.epoch
    return result


def estimands() -> tuple[Estimand, ...]:
    rows: list[Estimand] = []
    for k in range(1, 30):
        rows.append(Estimand(
            f"WIDTH_DELTA_ADJACENT_K{k:02d}_TO_K{k+1:02d}", "WIDTH_DELTA_ADJACENT", k, k + 1,
            "OBSOPEN02_GEOMETRY_RAW_V1", "width(k+1)-width(k)",
            "ELIGIBLE geometry at both adjacent k",
        ))
    specs = (
        ("FIRST_OUTSIDE_SIDE_BALANCE", "OBSOPEN02_INTERACTION_SEQUENCE_V1", "first outside side in {-1,+1}", "at least one outside close"),
        ("LOCATION_BALANCE", "OBSOPEN02_INTERACTION_SEQUENCE_V1", "(above_duration-below_duration)/duration_bars", "at least one eligible M5 candle"),
        ("SIGNED_PATH_DISPLACEMENT", "OBSOPEN02_CONTINUOUS_PATH_V1", "last eligible close-first eligible close", "at least two eligible M5 candles"),
    )
    for template, representation, value_def, eligibility in specs:
        for k in range(1, 31):
            rows.append(Estimand(f"{template}_K{k:02d}", template, k, None, representation, value_def, eligibility))
    result = tuple(rows)
    if tuple(row.estimand_id for row in result) != expand_estimand_ids():
        raise ValueError("formal estimand expansion mismatch")
    return result


def sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def support_snapshot(values: Mapping[str, float], session_by_id: Mapping[str, Session]) -> SupportSnapshot:
    months = Counter(session_by_id[sid].civil_date[:7] for sid in values)
    regimes = Counter(session_by_id[sid].offset_minutes for sid in values)
    supported_months = [count for count in months.values() if count >= 10]
    supported_regimes = [regimes[offset] for offset in (120, 180) if regimes[offset] >= 20]
    return SupportSnapshot(
        len(values), len(supported_months), min(supported_months, default=0),
        len(supported_regimes), min(supported_regimes, default=0),
    )


def temporal_receipt(values: Mapping[str, float], session_by_id: Mapping[str, Session], aggregate: float) -> dict[str, object]:
    by_month: dict[str, list[float]] = defaultdict(list)
    by_regime: dict[int, list[float]] = defaultdict(list)
    for sid, value in values.items():
        session = session_by_id[sid]
        by_month[session.civil_date[:7]].append(value)
        by_regime[session.offset_minutes].append(value)
    supported_months = sorted(month for month, vals in by_month.items() if len(vals) >= 10)
    month_rows = [{"id": month, "n": len(by_month[month]), "estimate": mean(by_month[month]), "supported": True}
                  for month in supported_months]
    regime_rows = [{"id": str(offset), "n": len(by_regime[offset]),
                    "estimate": mean(by_regime[offset]) if by_regime[offset] else None,
                    "supported": len(by_regime[offset]) >= 20} for offset in (120, 180)]
    lomo_rows: list[dict[str, object]] = []
    for omitted in supported_months:
        remaining = {sid: value for sid, value in values.items() if session_by_id[sid].civil_date[:7] != omitted}
        snapshot = support_snapshot(remaining, session_by_id)
        passed = support_pass(snapshot) and snapshot.supported_months >= 3
        lomo_rows.append({"id": omitted, "n": len(remaining), "estimate": mean(remaining.values()) if remaining else None, "supported": passed})
    ordered_ids = sorted(values)
    blocks: list[list[float]] = [[] for _ in range(4)]
    for index, sid in enumerate(ordered_ids):
        blocks[min(3, 4 * index // len(ordered_ids))].append(values[sid])
    block_rows = [{"id": str(index), "n": len(vals), "estimate": mean(vals) if vals else None,
                   "supported": len(vals) >= 33} for index, vals in enumerate(blocks)]
    month_slices = [(sign(float(row["estimate"])), bool(row["supported"])) for row in month_rows]
    regime_slices = [(sign(float(row["estimate"])) if row["estimate"] is not None else 0, bool(row["supported"])) for row in regime_rows]
    sensitivity = [(sign(float(row["estimate"])) if row["estimate"] is not None else 0, bool(row["supported"]))
                   for row in lomo_rows + block_rows]
    status = temporal_status(sign(aggregate), month_slices, regime_slices, sensitivity)
    return {"status": status, "calendar_month": month_rows, "server_offset": regime_rows,
            "leave_one_month_out": lomo_rows, "chronological_block": block_rows}


def formal_values(
    spec: Estimand,
    summaries: Mapping[tuple[str, int], dict[str, object]],
    widths: Mapping[tuple[str, int], Decimal],
    session_ids: Iterable[str],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for sid in session_ids:
        row = summaries[(sid, spec.range_k)]
        if spec.template_id == "WIDTH_DELTA_ADJACENT":
            assert spec.adjacent_to_k is not None
            values[sid] = float(widths[(sid, spec.adjacent_to_k)] - widths[(sid, spec.range_k)])
        elif spec.template_id == "FIRST_OUTSIDE_SIDE_BALANCE":
            value = row["first_outside_side"]
            if value is not None:
                values[sid] = float(value)
        elif spec.template_id == "LOCATION_BALANCE":
            duration = int(row["duration_bars"])
            if duration:
                values[sid] = (int(row["above_duration"]) - int(row["below_duration"])) / duration
        else:
            if int(row["duration_bars"]) >= 2:
                values[sid] = float(row["signed_displacement"])
    return values


def run_discovery(source: Path, partition: Path, census: Path, repo: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError("output directory must be new")
    output.mkdir(parents=True)
    guard = verify_parent_authority(repo, partition)
    discovery, total_rows, safe_rows = load_metadata(partition, census)
    sessions = session_table(discovery)
    for session in sessions:
        guard.admit_session(session.session_id, "DISCOVERY")
    m1, m5, prefix_hash = load_discovery_bars(source, sessions, safe_rows, total_rows)
    session_by_id = {row.session_id: row for row in sessions}

    census_fields = (
        "session_id", "civil_date", "server_offset_minutes", "range_k", "range_start_epoch", "freeze_epoch",
        "knowledge_epoch", "range_high", "range_low", "midpoint", "width", "availability", "duration_bars",
        "duration_seconds", "first_outside_time", "first_outside_side", "outside_duration", "in_zone_duration",
        "above_duration", "below_duration", "return_count", "cross_through_count", "terminal_location",
        "terminal_relative_close", "signed_displacement", "positive_excursion", "negative_excursion", "path_length",
        "directional_efficiency", "return_distance",
    )
    sequence_fields = ("session_id", "range_k", "bar_open_epoch", "bar_close_epoch", "close", "relative_close", "location", "event", "outside_run")
    scale_fields = ("session_id", "from_k", "to_k", "width_delta", "classification_survival", "state_transition", "availability")
    span_fields = ("session_id", "from_k", "to_k", "terminal_location")
    census_out = TsvWriter(output / "discovery_census.tsv", census_fields)
    sequence_out = TsvWriter(output / "interaction_sequence.tsv", sequence_fields)
    scale_out = TsvWriter(output / "scale_relations.tsv", scale_fields)
    span_out = TsvWriter(output / "contiguous_persistence.tsv", span_fields)
    summaries: dict[tuple[str, int], dict[str, object]] = {}
    widths: dict[tuple[str, int], Decimal] = {}
    for session in sessions:
        highs: list[Decimal] = []
        lows: list[Decimal] = []
        terminals: dict[int, int] = {}
        for k, source_bar in enumerate(m1[session.session_id], start=1):
            highs.append(source_bar.high)
            lows.append(source_bar.low)
            high, low = max(highs), min(lows)
            midpoint, width = (high + low) / 2, high - low
            freeze = session.start_epoch + k * 60
            path = interaction_path(m5[session.session_id], high, low, freeze, session.area_end_epoch)
            summary = describe_path(path)
            if summary["availability"] != "ELIGIBLE":
                raise ValueError("qualified path unexpectedly unavailable")
            summaries[(session.session_id, k)] = summary
            widths[(session.session_id, k)] = width
            terminals[k] = int(summary["terminal_location"])
            last_close = Decimal(str(path[-1].close))
            relative = None if width == 0 else (last_close - midpoint) / (width / 2)
            census_out.write({
                "session_id": session.session_id, "civil_date": session.civil_date,
                "server_offset_minutes": session.offset_minutes, "range_k": k,
                "range_start_epoch": session.start_epoch, "freeze_epoch": freeze, "knowledge_epoch": freeze,
                "range_high": high, "range_low": low, "midpoint": midpoint, "width": width,
                "availability": "ELIGIBLE" if width > 0 else "ELIGIBLE_DEGENERATE_RELATIVE_GEOMETRY",
                "terminal_relative_close": relative, **summary,
            })
            for bar in path:
                close = Decimal(str(bar.close))
                sequence_out.write({
                    "session_id": session.session_id, "range_k": k, "bar_open_epoch": bar.epoch,
                    "bar_close_epoch": bar.epoch + 300, "close": close,
                    "relative_close": None if width == 0 else (close - midpoint) / (width / 2),
                    "location": bar.location, "event": bar.event, "outside_run": bar.outside_run,
                })
        for row in adjacent_relations(session.session_id, terminals):
            k = int(row["from_k"])
            scale_out.write({**row, "width_delta": widths[(session.session_id, k + 1)] - widths[(session.session_id, k)]})
        for start, end, location in contiguous_terminal_spans(terminals):
            span_out.write({"session_id": session.session_id, "from_k": start, "to_k": end, "terminal_location": location})
    for writer in (census_out, sequence_out, scale_out, span_out):
        writer.close()

    formal_specs = estimands()
    computed: list[dict[str, object]] = []
    p_values: dict[str, float] = {}
    robustness: dict[str, object] = {}
    values_cache: dict[str, dict[str, float]] = {}
    for spec in formal_specs:
        values = formal_values(spec, summaries, widths, session_by_id)
        values_cache[spec.estimand_id] = values
        bootstrap = bootstrap_summary(values)
        snapshot = support_snapshot(values, session_by_id)
        temporal = temporal_receipt(values, session_by_id, float(bootstrap["point_estimate"]))
        p_values[spec.estimand_id] = float(bootstrap["raw_p"])
        robustness[spec.estimand_id] = temporal
        computed.append({"spec": spec, "bootstrap": bootstrap, "support": snapshot, "temporal": temporal})
    holm = holm_bonferroni(p_values)

    formal_fields = ("estimand_id", "template_id", "range_k", "adjacent_to_k", "representation", "eligible_sessions",
                     "point_estimate", "lower_95", "upper_95", "raw_p", "holm_pass", "temporal_status", "terminal_class", "reason")
    candidate_fields = ("candidate_id", "estimand_id", "template_id", "range_k", "adjacent_to_k", "representation",
                        "eligible_sessions", "point_estimate", "lower_95", "upper_95", "raw_p", "temporal_status", "candidate_class")
    rejection_fields = ("estimand_id", "template_id", "range_k", "adjacent_to_k", "eligible_sessions", "raw_p", "holm_pass", "temporal_status", "terminal_class", "reason")
    formal_out = TsvWriter(output / "formal_estimand_ledger.tsv", formal_fields)
    candidate_out = TsvWriter(output / "candidate_registry.tsv", candidate_fields)
    rejection_out = TsvWriter(output / "candidate_rejection_ledger.tsv", rejection_fields)
    confirmation_rows: list[dict[str, object]] = []
    terminal_counts = Counter()
    for item in computed:
        spec: Estimand = item["spec"]  # type: ignore[assignment]
        bootstrap = item["bootstrap"]
        snapshot: SupportSnapshot = item["support"]  # type: ignore[assignment]
        temporal = item["temporal"]
        raw_p = float(bootstrap["raw_p"])
        estimate = float(bootstrap["point_estimate"])
        if not support_pass(snapshot):
            terminal_class, reason = "INSUFFICIENT_SUPPORT", "INSUFFICIENT_ELIGIBLE_SUPPORT"
        elif temporal["status"] == "TEMPORAL_SUPPORT_INSUFFICIENT":
            terminal_class, reason = "INSUFFICIENT_SUPPORT", "INSUFFICIENT_TEMPORAL_SUPPORT"
        elif raw_p > 0.05:
            terminal_class, reason = "DESCRIPTIVE_ONLY", "FAILS_UNADJUSTED_EVIDENCE"
        elif not holm[spec.estimand_id]:
            terminal_class, reason = "DESCRIPTIVE_ONLY", "FAILS_FAMILYWISE_CORRECTION"
        elif temporal["status"] == "TEMPORALLY_UNSTABLE":
            terminal_class, reason = "TEMPORALLY_UNSTABLE_STRUCTURE", "TEMPORALLY_UNSTABLE"
        elif spec.template_id == "WIDTH_DELTA_ADJACENT":
            terminal_class, reason = "SCALE_DEPENDENT_STRUCTURE", None
        else:
            terminal_class, reason = "RECURRING_STRUCTURE", None
        terminal_counts[terminal_class] += 1
        common = {
            "estimand_id": spec.estimand_id, "template_id": spec.template_id, "range_k": spec.range_k,
            "adjacent_to_k": spec.adjacent_to_k, "representation": spec.representation,
            "eligible_sessions": bootstrap["eligible_sessions"], "point_estimate": estimate,
            "lower_95": bootstrap["lower_95"], "upper_95": bootstrap["upper_95"], "raw_p": raw_p,
            "holm_pass": holm[spec.estimand_id], "temporal_status": temporal["status"],
            "terminal_class": terminal_class, "reason": reason,
        }
        formal_out.write(common)
        if reason is None:
            candidate_id = f"OBSOPEN03_CAND_{candidate_out.rows + 1:03d}"
            candidate_out.write({**common, "candidate_id": candidate_id, "candidate_class": terminal_class})
            confirmation_rows.append(emit_confirmation_estimand(
                candidate_id, spec.estimand_id, spec.template_id, spec.representation,
                spec.session_value_definition, spec.eligibility_definition, 0.0, estimate,
                spec.range_k, spec.adjacent_to_k,
            ))
        else:
            rejection_out.write(common)
    for writer in (formal_out, candidate_out, rejection_out):
        writer.close()

    (output / "robustness_receipt.json").write_bytes(canonical_json({
        "schema": "OBS_OPEN_03_TEMPORAL_ROBUSTNESS_V1", "estimands": robustness,
    }))
    with (output / "confirmation_estimand_registry.jsonl").open("wb") as handle:
        for row in confirmation_rows:
            handle.write(canonical_json(row))
    minimum_p = 2 / 2001
    first_holm = 0.05 / 119
    (output / "multiplicity_receipt.json").write_bytes(canonical_json({
        "schema": "OBS_OPEN_03_MULTIPLICITY_RECEIPT_V1", "formal_tests": 119,
        "procedure": "HOLM_BONFERRONI", "alpha": 0.05, "bootstrap_resamples": 2000,
        "plus_one_two_sided_minimum_raw_p": minimum_p, "first_holm_threshold": first_holm,
        "minimum_raw_p_exceeds_first_holm_threshold": minimum_p > first_holm,
        "holm_pass_count": sum(holm.values()), "terminal_class_counts": dict(sorted(terminal_counts.items())),
    }))
    (output / "confirmation_firewall_receipt.json").write_bytes(canonical_json({
        "schema": "OBS_OPEN_03_CONFIRMATION_FIREWALL_V1", **guard.state(),
        "confirmation_rows_read": 0, "confirmation_paths_opened": 0, "next_source_row_requested": False,
        "status": "PASS_FROZEN_UNOPENED",
    }))
    TsvWriter(output / "future_question_ledger.tsv", ("question_id", "description", "status")).close()

    artifact_names = (
        "discovery_census.tsv", "interaction_sequence.tsv", "scale_relations.tsv", "contiguous_persistence.tsv",
        "formal_estimand_ledger.tsv", "candidate_registry.tsv", "candidate_rejection_ledger.tsv",
        "confirmation_estimand_registry.jsonl", "robustness_receipt.json", "multiplicity_receipt.json",
        "confirmation_firewall_receipt.json", "future_question_ledger.tsv",
    )
    manifest_path = output / "discovery_content_manifest.tsv"
    manifest_out = TsvWriter(manifest_path, ("path", "size_bytes", "sha256"))
    for name in artifact_names:
        path = output / name
        manifest_out.write({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest_out.close()
    manifest_hash = sha256_file(manifest_path)
    root_payload = {
        "schema": "OBS_OPEN_03_DISCOVERY_ROOT_V1", "study_id": "OBS-OPEN-01", "gate": "OBS-OPEN-03",
        "universe_root_sha256": UNIVERSE_ROOT, "protocol_root_sha256": PROTOCOL_ROOT,
        "r1_root_sha256": R1_ROOT, "r2_root_sha256": R2_ROOT, "source_discovery_prefix_sha256": prefix_hash,
        "executor_sha256": sha256_file(Path(__file__).resolve()),
        "measurement_module_sha256": sha256_file(Path(__file__).with_name("obs_open_02_measurement.py")),
        "familywise_module_sha256": sha256_file(Path(__file__).with_name("obs_open_02r1_familywise_rules.py")),
        "r2_semantics_module_sha256": sha256_file(Path(__file__).with_name("obs_open_02r2_semantics.py")),
        "partition_manifest_sha256": sha256_file(partition),
        "bootstrap_resamples": 2000, "bootstrap_seed": 20260814,
        "discovery_sessions": len(sessions), "range_rows": census_out.rows, "interaction_rows": sequence_out.rows,
        "scale_relation_rows": scale_out.rows, "contiguous_span_rows": span_out.rows,
        "formal_estimands": formal_out.rows, "candidate_rows": candidate_out.rows,
        "rejection_rows": rejection_out.rows, "confirmation_estimands_frozen": len(confirmation_rows),
        "confirmation_rows_read": 0, "confirmation_status": "FROZEN_UNOPENED",
        "content_manifest_sha256": manifest_hash, "economic_authority": False, "trading_authority": False,
    }
    root_hash = hashlib.sha256(canonical_json(root_payload)).hexdigest()
    root_payload["discovery_root_sha256"] = root_hash
    (output / "discovery_root_receipt.json").write_bytes(canonical_json(root_payload))
    return root_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--partition", required=True, type=Path)
    parser.add_argument("--census", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = run_discovery(args.source, args.partition, args.census, args.repo, args.output)
    print(receipt["discovery_root_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
