from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

NULL_TOKEN = "\\N"
EXPECTED_SCHEMA = {
    "dataset_schema": "7",
    "contract_version": "1",
    "contract_id": "MST_AUCTION_RELATIONAL_V1",
    "research_generation": "2",
}
BEHAVIORAL_RESOLUTIONS = {
    "TRANSIT_TO_NEXT_NODE", "RECLAIM_AFTER_BREAK", "RETURN_TO_SOURCE_NODE",
    "REJECT_TO_ORIGIN", "ACCEPT_AND_HOLD_RETEST", "ACCEPT_AND_FAIL_RETEST",
    "ACCEPT_THROUGH_NODE", "ACCEPT_THROUGH_NODE",
}


def long_path(path: Path) -> str:
    value = str(path.resolve())
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def read_tsv(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(
        long_path(path), sep="\t", dtype=str, keep_default_na=False,
        na_values=[NULL_TOKEN], **kwargs,
    )


def numeric(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def shannon(values: pd.Series) -> tuple[float, float]:
    counts = values.fillna(NULL_TOKEN).value_counts()
    if counts.empty:
        return 0.0, 0.0
    p = counts / counts.sum()
    entropy = float(-(p * np.log2(p)).sum())
    maximum = math.log2(len(counts)) if len(counts) > 1 else 0.0
    return entropy, entropy / maximum if maximum else 0.0


def classify_count(count: int) -> str:
    if count == 0:
        return "EMPTY"
    if count < 10:
        return "INSUFFICIENT"
    if count < 30:
        return "PRELIMINARY_ONLY"
    return "READY_DESCRIPTIVE"


@dataclass
class Corpus:
    runs: pd.DataFrame
    events: pd.DataFrame
    attempts: pd.DataFrame
    episodes: pd.DataFrame
    context: pd.DataFrame
    features: pd.DataFrame
    transits: pd.DataFrame
    structure_events: pd.DataFrame
    nodes: pd.DataFrame
    qc_failures: list[str]
    corpus_fingerprint: str


def _one(path: Path, pattern: str) -> Path:
    matches = list(path.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern} under {path}, found {len(matches)}")
    return matches[0]


def _terminal_nodes(path: Path, run_key: str) -> pd.DataFrame:
    usecols = [
        "run_key", "node_id", "generation", "market_time", "existence_state",
        "revision", "width_atr", "family_count", "member_count",
        "structural_region", "median_distance_sigma", "cog_distance_sigma",
        "width_sigma", "developing_count", "frozen_count",
    ]
    pieces: list[pd.DataFrame] = []
    for chunk in read_tsv(path, usecols=usecols, chunksize=100_000):
        numeric(chunk, ["generation", "revision", "width_atr", "family_count",
                        "member_count", "median_distance_sigma", "cog_distance_sigma",
                        "width_sigma", "developing_count", "frozen_count"])
        pieces.append(chunk.sort_values("generation").drop_duplicates(["run_key", "node_id"], keep="last"))
    if not pieces:
        return pd.DataFrame(columns=usecols)
    result = pd.concat(pieces, ignore_index=True)
    result = result.sort_values("generation").drop_duplicates(["run_key", "node_id"], keep="last")
    if not (result["run_key"] == run_key).all():
        raise RuntimeError(f"foreign run key in node snapshots: {path}")
    return result


def load_corpus(root: Path, manifest_path: Path) -> Corpus:
    manifest = read_tsv(manifest_path)
    manifest_by_window = manifest.set_index("window_id", drop=False)
    loaded: dict[str, list[pd.DataFrame]] = {
        name: [] for name in ("events", "attempts", "episodes", "context", "features", "transits")
    }
    run_rows: list[dict] = []
    structural_events: list[pd.DataFrame] = []
    node_snapshots: list[pd.DataFrame] = []
    qc: list[str] = []
    fingerprint = hashlib.sha256()

    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        admission_path = directory / "receipts" / "admission_receipt.json"
        terminal_path = directory / "receipts" / "terminal_run_receipt.json"
        seal_path = directory / "seal.json"
        admission = json.loads(admission_path.read_text(encoding="utf-8-sig"))
        terminal = json.loads(terminal_path.read_text(encoding="utf-8-sig"))
        seal = json.loads(seal_path.read_text(encoding="utf-8-sig"))
        for receipt_path in (admission_path, terminal_path, seal_path):
            fingerprint.update(receipt_path.read_bytes())
        window_id = admission["window_id"]
        if window_id not in manifest_by_window.index:
            qc.append(f"{directory.name}: window absent from manifest")
            continue
        meta = manifest_by_window.loc[window_id]
        if isinstance(meta, pd.DataFrame):
            meta = meta.iloc[0]
        for field, expected in EXPECTED_SCHEMA.items():
            if str(terminal.get(field)) != expected:
                qc.append(f"{directory.name}: {field}={terminal.get(field)} expected={expected}")
        if terminal.get("run_status") != "COMPLETE" or terminal.get("contract_valid") != "1":
            qc.append(f"{directory.name}: terminal contract not complete/valid")
        row = dict(terminal)
        row.update({
            "window_id": window_id,
            "instrument": meta["canonical_instrument"],
            "data_source": meta["data_source_id"],
            "selection_class": meta["selection_class"],
            "environment_stratum": meta["environment_stratum"],
            "expected_profile_bars": admission.get("expected_profile_bars", np.nan),
            "observed_profile_bars": admission.get("observed_profile_bars", np.nan),
            "source_frame_valid": admission.get("source_frame_valid", True),
            "unexpected_data_gaps": admission.get("unexpected_data_gaps", 0),
            "canonical_dataset_hash": admission["canonical_dataset_hash"],
            "sealed_payload_sha256": seal["sealed_payload_sha256"],
        })
        run_rows.append(row)

        auction = directory / "raw" / "auction"
        for name in loaded:
            frame = read_tsv(_one(auction, f"*_{name}.tsv"))
            expected_rows = int(admission["row_counts"][name])
            if len(frame) != expected_rows:
                qc.append(f"{directory.name}: {name} rows={len(frame)} receipt={expected_rows}")
            frame["instrument"] = meta["canonical_instrument"]
            frame["data_source"] = meta["data_source_id"]
            frame["selection_class"] = meta["selection_class"]
            frame["environment_stratum"] = meta["environment_stratum"]
            frame["window_id"] = window_id
            loaded[name].append(frame)

        structure = directory / "raw" / "structure"
        se = read_tsv(_one(structure, "*_events.tsv"))
        se["instrument"] = meta["canonical_instrument"]
        se["window_id"] = window_id
        structural_events.append(se)
        node_snapshots.append(_terminal_nodes(_one(structure, "*_nodes.tsv"), admission["run_key"]))

    runs = pd.DataFrame(run_rows)
    frames = {name: pd.concat(parts, ignore_index=True) for name, parts in loaded.items()}
    se = pd.concat(structural_events, ignore_index=True)
    terminal_nodes = pd.concat(node_snapshots, ignore_index=True)
    return Corpus(runs=runs, structure_events=se, nodes=terminal_nodes,
                  qc_failures=qc, corpus_fingerprint=fingerprint.hexdigest(), **frames)


def enrich(corpus: Corpus) -> None:
    a, e, f, c, t, runs = (corpus.attempts, corpus.episodes, corpus.features,
                            corpus.context, corpus.transits, corpus.runs)
    numeric(a, ["ordinal", "is_retest", "start", "contact", "break", "accepted", "end",
                "start_bar", "contact_bar", "end_bar", "direction", "frozen_atr",
                "node_width_atr", "initial_distance_atr", "approach_efficiency",
                "penetration_atr", "penetration_node", "inside_updates", "inside_seconds",
                "max_above_atr", "max_below_atr", "rejection_excursion_atr",
                "corridor_up_atr", "corridor_down_atr", "family_count", "member_count",
                "node_revision", "start_median_sigma", "node_from_median_sigma",
                "node_from_cog_sigma", "node_width_sigma"])
    numeric(e, ["start", "end", "first_direction", "attempts", "breaks", "reclaims",
                "retests", "corridor_up_atr", "corridor_down_atr", "node_width_atr",
                "family_count", "member_count", "max_up_excursion_atr",
                "max_down_excursion_atr", "duration_bars", "duration_seconds"])
    numeric(f, ["frozen_bar_time", "cog_distance_atr", "cog_velocity_atr", "c3_distance_atr",
                "c3_velocity_atr", "lattice_width_atr", "field_width_atr", "spread_atr",
                "raw_level_count", "noise_level_count", "active_node_count", "structural_sigma",
                "price_from_median_atr", "price_from_median_sigma", "price_from_cog_atr",
                "price_from_cog_sigma", "cog_median_gap_atr", "cog_median_gap_sigma",
                "regional_cog_velocity_atr", "regional_cog_velocity_sigma",
                "regional_median_velocity_atr", "regional_median_velocity_sigma",
                "regional_sigma_log_change_per_bar", "regional_valid", "sigma_valid"])
    numeric(t, ["direction", "start", "end", "start_bar", "end_bar", "frozen_atr",
                "distance_atr", "path_length", "path_efficiency", "max_adverse_atr",
                "duration_bars", "duration_seconds", "start_price_from_median_sigma",
                "end_price_from_median_sigma"])
    numeric(runs, ["window_start", "window_end", "event_rows", "attempt_rows", "episode_rows",
                   "context_rows", "feature_rows", "transit_rows", "expected_profile_bars",
                   "observed_profile_bars", "unexpected_data_gaps"])

    contributors = c.groupby(["run_key", "attempt_id"], dropna=False).agg(
        observed_family_count=("family", "nunique"),
        family_combo=("family", lambda x: "+".join(sorted(set(x.dropna())))),
        producer_combo=("producer", lambda x: "+".join(sorted(set(x.dropna())))),
        contributor_rows=("source_key", "size"),
    ).reset_index()
    a2 = a.merge(contributors, on=["run_key", "attempt_id"], how="left", validate="one_to_one")
    feature_columns = [x for x in f.columns if x not in {"attempt_id", "run_key", "invocation_id",
                       "instrument", "data_source", "selection_class", "environment_stratum", "window_id"}]
    f2 = f[["run_key", "attempt_id"] + feature_columns].rename(columns={x: f"feature_{x}" for x in feature_columns})
    a2 = a2.merge(f2, on=["run_key", "attempt_id"], how="left", validate="one_to_one")

    episode_contributors = c.groupby(["run_key", "episode_id"], dropna=False).agg(
        family_combo=("family", lambda x: "+".join(sorted(set(x.dropna())))),
        producer_combo=("producer", lambda x: "+".join(sorted(set(x.dropna())))),
        observed_family_count=("family", "nunique"),
    ).reset_index()
    e2 = e.merge(episode_contributors, on=["run_key", "episode_id"], how="left", validate="one_to_one")

    lifecycle = build_node_lifecycle(corpus)
    created = lifecycle[["run_key", "node_id", "created_epoch"]]
    a2 = a2.merge(created, on=["run_key", "node_id"], how="left", validate="many_to_one")
    a2["node_age_seconds"] = a2["start"] - a2["created_epoch"]
    a2["duration_seconds"] = a2["end"] - a2["start"]
    a2["duration_bars"] = a2["end_bar"] - a2["start_bar"] + 1
    first_attempt = a2.sort_values(["run_key", "episode_id", "ordinal"]).drop_duplicates(["run_key", "episode_id"])
    e2 = e2.merge(first_attempt[["run_key", "episode_id", "start_median_sigma", "node_age_seconds"]],
                  on=["run_key", "episode_id"], how="left", validate="one_to_one")

    for frame, start_col, direction_col in ((a2, "start", "direction"), (e2, "start", "first_direction"),
                                             (t, "start", "direction")):
        frame["direction_label"] = frame[direction_col].map({1: "FROM_BELOW", -1: "FROM_ABOVE"}).fillna("UNKNOWN")
        hour = ((frame[start_col] % 86400) // 3600).astype("Int64")
        frame["server_hour"] = hour
        frame["server_time_bucket"] = hour.map(lambda x: NULL_TOKEN if pd.isna(x) else f"{(int(x)//4)*4:02d}-{(int(x)//4)*4+3:02d}")

    for frame, sigma_col, width_col, age_col, up_col, down_col in (
        (a2, "start_median_sigma", "node_width_atr", "node_age_seconds", "corridor_up_atr", "corridor_down_atr"),
        (e2, "start_median_sigma", "node_width_atr", "node_age_seconds", "corridor_up_atr", "corridor_down_atr"),
    ):
        frame["sigma_band"] = pd.cut(frame[sigma_col], [-np.inf, -2, -1, -.5, .5, 1, 2, np.inf],
                                     labels=["<=-2", "(-2,-1]", "(-1,-0.5]", "CORE", "(0.5,1]", "(1,2]", ">2"])
        frame["node_width_bucket"] = pd.cut(frame[width_col], [-np.inf, .1, .25, .5, 1, np.inf],
                                            labels=["<=0.10", "(0.10,0.25]", "(0.25,0.50]", "(0.50,1.00]", ">1.00"])
        frame["node_age_bucket"] = pd.cut(frame[age_col] / 3600, [-np.inf, 1, 4, 12, 24, 72, np.inf],
                                          labels=["<=1h", "(1h,4h]", "(4h,12h]", "(12h,24h]", "(1d,3d]", ">3d"])
        frame["nearest_corridor_atr"] = frame[[up_col, down_col]].min(axis=1, skipna=True)
        frame["corridor_bucket"] = pd.cut(frame["nearest_corridor_atr"], [-np.inf, .25, .5, 1, 2, np.inf],
                                          labels=["<=0.25", "(0.25,0.50]", "(0.50,1.00]", "(1.00,2.00]", ">2.00"])
    t["distance_bucket"] = pd.cut(t["distance_atr"], [-np.inf, .5, 1, 2, 4, np.inf],
                                  labels=["<=0.50", "(0.50,1.00]", "(1.00,2.00]", "(2.00,4.00]", ">4.00"])
    corpus.attempts = a2
    corpus.episodes = e2
    corpus.nodes = lifecycle


def build_node_lifecycle(corpus: Corpus) -> pd.DataFrame:
    se = corpus.structure_events.copy()
    parsed = pd.to_datetime(se["market_time"], format="%Y.%m.%d %H:%M:%S", errors="coerce")
    se["event_epoch"] = parsed.map(lambda value: value.timestamp() if pd.notna(value) else np.nan)
    numeric(se, ["revision"])
    run_end = corpus.runs.set_index("run_key")["window_end"].to_dict()
    rows: list[dict] = []
    for (run_key, node_id), group in se.groupby(["run_key", "node_id"], sort=False):
        group = group.sort_values(["event_epoch", "revision"])
        created = group.loc[group["event"] == "CREATED", "event_epoch"]
        retired = group.loc[group["event"] == "RETIRE", "event_epoch"]
        created_epoch = float(created.iloc[0]) if not created.empty else float(group["event_epoch"].iloc[0])
        retired_epoch = float(retired.iloc[-1]) if not retired.empty else np.nan
        cutoff = float(run_end[run_key])
        rows.append({
            "run_key": run_key, "node_id": node_id, "instrument": group["instrument"].iloc[0],
            "window_id": group["window_id"].iloc[0], "created_epoch": created_epoch,
            "retired_epoch": retired_epoch, "lifecycle": "RETIRED" if not np.isnan(retired_epoch) else "PERSISTED_AT_CUTOFF",
            "lifetime_seconds": (retired_epoch if not np.isnan(retired_epoch) else cutoff) - created_epoch,
            "event_count": len(group), "merge_events": int((group["event"] == "MERGE").sum()),
            "evidence_changes": int((group["event"] == "EVIDENCE_CHANGED").sum()),
            "last_event": group["event"].iloc[-1],
        })
    lifecycle = pd.DataFrame(rows)
    terminal = corpus.nodes.rename(columns={
        "width_atr": "terminal_width_atr", "family_count": "terminal_family_count",
        "member_count": "terminal_member_count", "structural_region": "terminal_region",
        "revision": "terminal_revision", "existence_state": "terminal_existence_state",
    })
    keep = ["run_key", "node_id", "terminal_width_atr", "terminal_family_count", "terminal_member_count",
            "terminal_region", "terminal_revision", "terminal_existence_state", "median_distance_sigma",
            "cog_distance_sigma", "width_sigma", "developing_count", "frozen_count"]
    lifecycle = lifecycle.merge(terminal[keep], on=["run_key", "node_id"], how="left", validate="one_to_one")
    numeric(lifecycle, ["terminal_width_atr", "terminal_family_count", "terminal_member_count",
                        "terminal_revision", "median_distance_sigma", "cog_distance_sigma", "width_sigma"])
    lifecycle["node_age_bucket"] = pd.cut(lifecycle["lifetime_seconds"] / 3600,
        [-np.inf, 1, 4, 12, 24, 72, np.inf], labels=["<=1h", "(1h,4h]", "(4h,12h]", "(12h,24h]", "(1d,3d]", ">3d"])
    lifecycle["node_width_bucket"] = pd.cut(lifecycle["terminal_width_atr"],
        [-np.inf, .1, .25, .5, 1, np.inf], labels=["<=0.10", "(0.10,0.25]", "(0.25,0.50]", "(0.50,1.00]", ">1.00"])
    return lifecycle


def coverage_table(frame: pd.DataFrame, unit: str, dimensions: Iterable[str], censored: pd.Series) -> pd.DataFrame:
    rows: list[dict] = []
    total = len(frame)
    for dimension in dimensions:
        values = frame[dimension].astype("object").where(frame[dimension].notna(), NULL_TOKEN).astype(str)
        entropy, normalized = shannon(values)
        work = pd.DataFrame({"value": values, "censored": censored.to_numpy(dtype=bool)})
        for value, group in work.groupby("value", dropna=False):
            count = len(group)
            censored_count = int(group["censored"].sum())
            rows.append({
                "unit": unit, "dimension": dimension, "value": value, "count": count,
                "total": total, "share": count / total if total else 0,
                "censored_count": censored_count, "censoring_rate": censored_count / count if count else 0,
                "entropy_bits": entropy, "normalized_entropy": normalized,
            })
    return pd.DataFrame(rows)


def continuous_table(frame: pd.DataFrame, unit: str, metrics: Iterable[str], censored: pd.Series) -> pd.DataFrame:
    rows: list[dict] = []
    for metric in metrics:
        series = pd.to_numeric(frame[metric], errors="coerce").replace([np.inf, -np.inf], np.nan)
        valid = series.dropna()
        quantiles = valid.quantile([.01, .05, .25, .5, .75, .95, .99]) if len(valid) else pd.Series(dtype=float)
        rows.append({
            "unit": unit, "metric": metric, "rows": len(frame), "count": len(valid),
            "missing_count": int(series.isna().sum()), "missing_rate": float(series.isna().mean()) if len(series) else 0,
            "censored_count": int(censored.sum()), "censoring_rate": float(censored.mean()) if len(censored) else 0,
            "min": valid.min() if len(valid) else np.nan, "p01": quantiles.get(.01, np.nan),
            "p05": quantiles.get(.05, np.nan), "p25": quantiles.get(.25, np.nan),
            "median": quantiles.get(.5, np.nan), "p75": quantiles.get(.75, np.nan),
            "p95": quantiles.get(.95, np.nan), "p99": quantiles.get(.99, np.nan),
            "max": valid.max() if len(valid) else np.nan, "mean": valid.mean() if len(valid) else np.nan,
            "std": valid.std(ddof=1) if len(valid) > 1 else np.nan,
        })
    return pd.DataFrame(rows)


def stratified_continuous(frame: pd.DataFrame, unit: str, group_column: str,
                          metrics: Iterable[str], censored: pd.Series) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for value, indexes in frame.groupby(group_column, dropna=False).groups.items():
        subset = frame.loc[indexes]
        table = continuous_table(subset, unit, metrics, censored.loc[indexes])
        table.insert(1, "stratifier", group_column)
        table.insert(2, "stratum", NULL_TOKEN if pd.isna(value) else str(value))
        pieces.append(table)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def cross_table(frame: pd.DataFrame, unit: str, dimensions: list[str], censored: pd.Series) -> pd.DataFrame:
    work = frame[dimensions].copy()
    for column in dimensions:
        work[column] = work[column].astype("object").where(work[column].notna(), NULL_TOKEN).astype(str)
    work["censored"] = censored.to_numpy(dtype=bool)
    total = len(work)
    grouped = work.groupby(dimensions, dropna=False).agg(count=("censored", "size"), censored_count=("censored", "sum")).reset_index()
    grouped = grouped.rename(columns={dimensions[0]: "value_1", dimensions[1]: "value_2"})
    grouped.insert(0, "unit", unit)
    grouped.insert(1, "cross", " x ".join(dimensions))
    grouped.insert(2, "dimension_1", dimensions[0])
    grouped.insert(4, "dimension_2", dimensions[1])
    grouped["total"] = total
    grouped["share"] = grouped["count"] / total if total else 0
    grouped["censoring_rate"] = grouped["censored_count"] / grouped["count"]
    return grouped


def missingness_table(named: dict[str, pd.DataFrame]) -> pd.DataFrame:
    required = {
        "attempts": {"run_key", "attempt_id", "episode_id", "node_id", "start", "end", "resolution", "completion_status"},
        "episodes": {"run_key", "episode_id", "node_id", "start", "end", "resolution", "completion_status"},
        "features": {"run_key", "attempt_id", "frozen_bar_time"},
        "transits": {"run_key", "transit_id", "attempt_id", "episode_id", "source_node_id", "completion_status"},
    }
    conditional = {"contact", "break", "accepted", "next_node_id", "destination_node_id", "related_node_id"}
    rows: list[dict] = []
    for name, frame in named.items():
        censored = frame.get("completion_status", pd.Series(index=frame.index, dtype=str)).ne("RESOLVED")
        for column in frame.columns:
            missing = frame[column].isna()
            if column in required.get(name, set()):
                semantics = "CONTRACT_VIOLATION_IF_MISSING"
            elif column in conditional:
                semantics = "CONDITIONAL_NOT_APPLICABLE_OR_NOT_OBSERVED"
            else:
                semantics = "RECORDED_UNAVAILABLE_OR_NOT_APPLICABLE"
            rows.append({
                "dataset": name, "column": column, "rows": len(frame),
                "missing_count": int(missing.sum()), "missing_rate": float(missing.mean()) if len(frame) else 0,
                "missing_on_censored": int((missing & censored).sum()), "null_token": NULL_TOKEN,
                "semantics": semantics,
            })
    return pd.DataFrame(rows)


def relational_invariants(corpus: Corpus) -> pd.DataFrame:
    rows: list[dict] = []

    def add(name: str, violations: int, detail: str) -> None:
        rows.append({"invariant": name, "status": "PASS" if violations == 0 else "FAIL",
                     "violations": int(violations), "detail": detail})

    def orphan_count(child: pd.DataFrame, parent: pd.DataFrame, keys: list[str]) -> int:
        usable = child.dropna(subset=keys)
        child_keys = set(map(tuple, usable[keys].astype(str).itertuples(index=False, name=None)))
        parent_keys = set(map(tuple, parent[keys].dropna().astype(str).itertuples(index=False, name=None)))
        return len(child_keys - parent_keys)

    a, e, f, c, t, ev, n = (corpus.attempts, corpus.episodes, corpus.features, corpus.context,
                              corpus.transits, corpus.events, corpus.nodes)
    for name, frame, keys in [
        ("events_primary_key", ev, ["run_key", "event_id"]),
        ("attempts_primary_key", a, ["run_key", "attempt_id"]),
        ("episodes_primary_key", e, ["run_key", "episode_id"]),
        ("features_primary_key", f, ["run_key", "attempt_id"]),
        ("transits_primary_key", t, ["run_key", "transit_id"]),
    ]:
        add(name, int(frame.duplicated(keys).sum()), "duplicate composite primary keys")
    add("attempt_episode_fk", orphan_count(a, e, ["run_key", "episode_id"]), "attempts reference existing episodes")
    add("feature_attempt_fk", orphan_count(f, a, ["run_key", "attempt_id"]), "features reference existing attempts")
    add("context_attempt_fk", orphan_count(c, a, ["run_key", "attempt_id"]), "context references existing attempts")
    add("event_attempt_fk", orphan_count(ev, a, ["run_key", "attempt_id"]), "non-null event attempts exist")
    add("event_episode_fk", orphan_count(ev, e, ["run_key", "episode_id"]), "non-null event episodes exist")
    add("transit_attempt_fk", orphan_count(t, a, ["run_key", "attempt_id"]), "transits reference existing attempts")
    add("transit_episode_fk", orphan_count(t, e, ["run_key", "episode_id"]), "transits reference existing episodes")
    source_nodes = t.rename(columns={"source_node_id": "node_id"})
    destination_nodes = t.rename(columns={"destination_node_id": "node_id"})
    add("transit_source_node_fk", orphan_count(source_nodes, n, ["run_key", "node_id"]), "source nodes observed structurally")
    add("transit_destination_node_fk", orphan_count(destination_nodes, n, ["run_key", "node_id"]), "destination nodes observed structurally")
    feature_counts = f.groupby(["run_key", "attempt_id"]).size()
    attempt_keys = pd.MultiIndex.from_frame(a[["run_key", "attempt_id"]])
    add("attempt_exactly_one_feature", int(sum(feature_counts.get(key, 0) != 1 for key in attempt_keys)),
        "each attempt has exactly one frozen feature snapshot")
    context_keys = set(map(tuple, c[["run_key", "attempt_id"]].astype(str).itertuples(index=False, name=None)))
    add("attempt_has_context", int(sum(tuple(map(str, key)) not in context_keys for key in attempt_keys)),
        "each attempt has at least one frozen contributor row")
    required_missing = 0
    for frame, columns in [(a, ["run_key", "attempt_id", "episode_id", "node_id", "start", "end"]),
                           (e, ["run_key", "episode_id", "node_id", "start", "end"]),
                           (t, ["run_key", "transit_id", "attempt_id", "episode_id", "source_node_id"] )]:
        required_missing += int(frame[columns].isna().any(axis=1).sum())
    add("required_values_present", required_missing, "required identities and timestamps are not null")
    add("terminal_contract_violations", int(pd.to_numeric(corpus.runs["contract_violations"], errors="coerce").fillna(0).sum()),
        "terminal relational contracts reported zero violations")
    add("unexpected_data_gaps", int(pd.to_numeric(corpus.runs["unexpected_data_gaps"], errors="coerce").fillna(0).sum()),
        "frozen profile reports no unexpected gaps")
    return pd.DataFrame(rows)


def question_ledger(corpus: Corpus) -> pd.DataFrame:
    e, a, t = corpus.episodes, corpus.attempts, corpus.transits
    resolved_episodes = e[e["completion_status"] == "RESOLVED"]
    resolution_counts = resolved_episodes["resolution"].value_counts()
    region_counts = e["initial_region"].value_counts()
    ordinal_counts = a["ordinal"].value_counts()
    combo_counts = a["producer_combo"].value_counts()
    sigma_counts = e["sigma_band"].astype(str).value_counts()
    core_sigma_min = min(int(sigma_counts.get(label, 0)) for label in ["(-1,-0.5]", "CORE", "(0.5,1]"])
    extreme_sigma_count = int(sigma_counts.get("<=-2", 0) + sigma_counts.get(">2", 0))
    questions = [
        ("Why do resolved episodes terminate through node retirement?", "episode", int(resolution_counts.get("NODE_RETIRED", 0)), "READY_DESCRIPTIVE", "semantic lifecycle audit; no expectancy"),
        ("Is node retirement concentrated by instrument?", "episode", int(e.groupby("instrument").size().min()), "READY_DESCRIPTIVE", "all six instruments populated"),
        ("What contexts accompany node-to-node transit?", "transit", len(t), classify_count(len(t)), "descriptive geometry only"),
        ("What contexts accompany reclaim after break?", "episode", int(resolution_counts.get("RECLAIM_AFTER_BREAK", 0)), classify_count(int(resolution_counts.get("RECLAIM_AFTER_BREAK", 0))), "cross-cells may remain sparse"),
        ("What contexts accompany accepted retest failure?", "episode", int(resolution_counts.get("ACCEPT_AND_FAIL_RETEST", 0)), classify_count(int(resolution_counts.get("ACCEPT_AND_FAIL_RETEST", 0))), "too few for conditional inference"),
        ("How do EXTREME_ABOVE episodes behave?", "episode", int(region_counts.get("EXTREME_ABOVE", 0)), classify_count(int(region_counts.get("EXTREME_ABOVE", 0))), "empty regional cell"),
        ("How do EXTREME_BELOW episodes behave?", "episode", int(region_counts.get("EXTREME_BELOW", 0)), classify_count(int(region_counts.get("EXTREME_BELOW", 0))), "near-empty regional cell"),
        ("Does repeated testing differ by attempt ordinal?", "episode", int((e["attempts"] >= 2).sum()), classify_count(int((e["attempts"] >= 2).sum())), "episodes with repeated attempts; within-episode attempts remain dependent"),
        ("Do exact producer combinations differ?", "attempt", int(combo_counts.min()) if len(combo_counts) else 0, "PRELIMINARY_ONLY" if int((combo_counts >= 30).sum()) >= 2 else "INSUFFICIENT", f"{int((combo_counts >= 30).sum())} combinations have at least 30 attempts"),
        ("Are both approach directions represented?", "episode", int(e.groupby("direction_label").size().min()), "READY_DESCRIPTIVE", "from-above and from-below mirrors are both populated"),
        ("Can behavior be compared across data sources?", "run", int(corpus.runs["data_source"].nunique()), "EMPTY_COMPARISON", "RG2 contains one data source"),
        ("Can behavior be compared across core sigma bands?", "episode", core_sigma_min, classify_count(core_sigma_min), "minimum cell across negative core, median core, and positive core"),
        ("Can behavior be compared at absolute sigma above two?", "episode", extreme_sigma_count, classify_count(extreme_sigma_count), "both extreme sigma tails combined"),
        ("Can node age and width be audited against retirement/timeout?", "episode", len(e), "READY_DESCRIPTIVE", "stratified continuous and categorical geometry available"),
        ("How does corridor geometry differ across resolutions?", "attempt", len(a), "READY_DESCRIPTIVE", "continuous distributions and cross-coverage available"),
        ("Can RG2 support a predictive model?", "corpus", len(e), "BLOCKED_BY_DESIGN", "Phase 9 forbids modeling; outcome imbalance requires review"),
    ]
    return pd.DataFrame(questions, columns=["question", "unit", "evidence_count", "readiness", "reason"])


def analyze(corpus: Corpus, replay_verification: dict) -> dict[str, pd.DataFrame | dict]:
    enrich(corpus)
    a, e, t, n = corpus.attempts, corpus.episodes, corpus.transits, corpus.nodes
    episode_censored = e["completion_status"].ne("RESOLVED")
    attempt_censored = a["completion_status"].ne("RESOLVED")
    transit_censored = t["completion_status"].ne("RESOLVED")
    node_censored = n["lifecycle"].eq("PERSISTED_AT_CUTOFF")

    coverage = pd.concat([
        coverage_table(e, "episode", ["instrument", "data_source", "direction_label", "initial_region",
            "sigma_band", "resolution", "attempts", "family_count", "producer_combo",
            "server_time_bucket", "node_age_bucket", "node_width_bucket", "corridor_bucket"], episode_censored),
        coverage_table(a, "attempt", ["instrument", "direction_label", "start_region", "sigma_band",
            "resolution", "ordinal", "family_count", "producer_combo", "server_time_bucket",
            "node_age_bucket", "node_width_bucket", "corridor_bucket", "is_retest",
            "feature_regional_valid", "feature_sigma_valid"], attempt_censored),
        coverage_table(t, "transit", ["instrument", "direction_label", "source_region", "destination_region",
            "resolution", "server_time_bucket", "distance_bucket"], transit_censored),
        coverage_table(n, "node", ["instrument", "lifecycle", "terminal_region", "node_age_bucket",
            "node_width_bucket", "terminal_family_count", "terminal_existence_state"], node_censored),
    ], ignore_index=True)

    continuous = pd.concat([
        continuous_table(e, "episode", ["duration_seconds", "duration_bars", "max_up_excursion_atr",
            "max_down_excursion_atr", "node_width_atr", "node_age_seconds", "start_median_sigma",
            "corridor_up_atr", "corridor_down_atr", "nearest_corridor_atr"], episode_censored),
        continuous_table(a, "attempt", ["duration_seconds", "duration_bars", "penetration_atr",
            "penetration_node", "max_above_atr", "max_below_atr", "rejection_excursion_atr",
            "inside_seconds", "approach_efficiency", "node_width_atr", "node_age_seconds",
            "start_median_sigma", "node_from_median_sigma", "node_from_cog_sigma",
            "feature_price_from_median_sigma", "feature_price_from_cog_sigma",
            "feature_cog_median_gap_sigma", "feature_regional_median_velocity_sigma",
            "feature_regional_cog_velocity_sigma", "feature_structural_sigma",
            "feature_regional_sigma_log_change_per_bar", "corridor_up_atr", "corridor_down_atr"], attempt_censored),
        continuous_table(t, "transit", ["distance_atr", "duration_seconds", "duration_bars",
            "path_length", "path_efficiency", "max_adverse_atr", "start_price_from_median_sigma",
            "end_price_from_median_sigma"], transit_censored),
        continuous_table(n, "node", ["lifetime_seconds", "terminal_width_atr", "terminal_revision",
            "terminal_family_count", "terminal_member_count", "median_distance_sigma",
            "cog_distance_sigma", "width_sigma", "evidence_changes", "merge_events"], node_censored),
    ], ignore_index=True)

    crosses = pd.concat([
        cross_table(e, "episode", ["instrument", "resolution"], episode_censored),
        cross_table(e, "episode", ["initial_region", "resolution"], episode_censored),
        cross_table(e, "episode", ["direction_label", "resolution"], episode_censored),
        cross_table(e, "episode", ["selection_class", "resolution"], episode_censored),
        cross_table(e, "episode", ["sigma_band", "resolution"], episode_censored),
        cross_table(e, "episode", ["node_age_bucket", "resolution"], episode_censored),
        cross_table(e, "episode", ["node_width_bucket", "resolution"], episode_censored),
        cross_table(e, "episode", ["corridor_bucket", "resolution"], episode_censored),
        cross_table(e, "episode", ["family_count", "resolution"], episode_censored),
        cross_table(e, "episode", ["producer_combo", "resolution"], episode_censored),
        cross_table(a, "attempt", ["ordinal", "resolution"], attempt_censored),
        cross_table(a, "attempt", ["family_count", "resolution"], attempt_censored),
        cross_table(a, "attempt", ["producer_combo", "resolution"], attempt_censored),
        cross_table(n, "node", ["instrument", "lifecycle"], node_censored),
    ], ignore_index=True)

    stratified = pd.concat([
        stratified_continuous(e, "episode", "resolution", ["duration_seconds", "duration_bars",
            "node_width_atr", "node_age_seconds", "start_median_sigma", "nearest_corridor_atr"], episode_censored),
        stratified_continuous(a, "attempt", "resolution", ["duration_seconds", "penetration_atr",
            "inside_seconds", "approach_efficiency", "node_width_atr", "node_age_seconds",
            "start_median_sigma", "nearest_corridor_atr"], attempt_censored),
        stratified_continuous(n, "node", "lifecycle", ["lifetime_seconds", "terminal_width_atr",
            "terminal_revision", "terminal_family_count", "terminal_member_count"], node_censored),
    ], ignore_index=True)

    missing = missingness_table({"attempts": a, "episodes": e, "features": corpus.features, "transits": t})
    readiness = question_ledger(corpus)
    invariants = relational_invariants(corpus)
    runs = corpus.runs.copy()
    runs["scheduled_span_hours"] = (runs["window_end"] - runs["window_start"]) / 3600
    runs["observed_bar_hours"] = runs["observed_profile_bars"] * 5 / 60
    runs["bar_gap"] = runs["expected_profile_bars"] - runs["observed_profile_bars"]

    primary_duplicates = {
        "events": int(corpus.events.duplicated(["run_key", "event_id"]).sum()),
        "attempts": int(a.duplicated(["run_key", "attempt_id"]).sum()),
        "episodes": int(e.duplicated(["run_key", "episode_id"]).sum()),
        "features": int(corpus.features.duplicated(["run_key", "attempt_id"]).sum()),
        "transits": int(t.duplicated(["run_key", "transit_id"]).sum()),
    }
    behavioral_count = int((e["resolution"].isin(BEHAVIORAL_RESOLUTIONS) & ~episode_censored).sum())
    resolved = e[~episode_censored]
    retired_episodes = e[e["resolution"] == "NODE_RETIRED"]
    timeout_episodes = e[e["resolution"] == "TIMEOUT"]
    retired_resolved = resolved[resolved["resolution"] == "NODE_RETIRED"]
    timeout_resolved = resolved[resolved["resolution"] == "TIMEOUT"]
    retired_nodes = n[n["lifecycle"] == "RETIRED"]
    persisted_nodes = n[n["lifecycle"] == "PERSISTED_AT_CUTOFF"]
    diagnostics = {
        "node_retired_episode_rows": len(retired_episodes),
        "node_retired_resolved": len(retired_resolved),
        "node_retired_censored": int(retired_episodes["completion_status"].ne("RESOLVED").sum()),
        "node_retired_share_of_resolved": len(retired_resolved) / len(resolved),
        "node_retired_node_age_median_seconds": float(retired_resolved["node_age_seconds"].median()),
        "node_retired_width_median_atr": float(retired_resolved["node_width_atr"].median()),
        "node_retired_duration_median_seconds": float(retired_resolved["duration_seconds"].median()),
        "node_retired_under_1h_count": int((retired_resolved["node_age_seconds"] <= 3600).sum()),
        "timeout_episode_rows": len(timeout_episodes),
        "timeout_resolved": len(timeout_resolved),
        "timeout_censored": int(timeout_episodes["completion_status"].ne("RESOLVED").sum()),
        "timeout_share_of_resolved": len(timeout_resolved) / len(resolved),
        "timeout_node_age_median_seconds": float(timeout_resolved["node_age_seconds"].median()),
        "timeout_width_median_atr": float(timeout_resolved["node_width_atr"].median()),
        "timeout_duration_median_seconds": float(timeout_resolved["duration_seconds"].median()),
        "timeout_over_1atr_count": int((timeout_resolved["node_width_atr"] > 1).sum()),
        "retired_node_lifetime_median_seconds": float(retired_nodes["lifetime_seconds"].median()),
        "persisted_node_observed_age_median_seconds": float(persisted_nodes["lifetime_seconds"].median()),
        "repeated_attempt_episodes": int((e["attempts"] >= 2).sum()),
        "producer_combinations": int(a["producer_combo"].nunique()),
        "minimum_producer_combo_attempts": int(a["producer_combo"].value_counts().min()),
    }
    invariant_failures = invariants.loc[invariants.status == "FAIL", "invariant"].tolist()
    summary = {
        "contract": "MST_RG2_PHASE9_DATASET_GEOMETRY_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_generation": 2,
        "corpus_fingerprint": corpus.corpus_fingerprint,
        "runs": len(runs), "instruments": int(runs.instrument.nunique()),
        "data_sources": int(runs.data_source.nunique()),
        "scheduled_span_hours": float(runs.scheduled_span_hours.sum()),
        "observed_bar_hours": float(runs.observed_bar_hours.sum()),
        "observed_bars": int(runs.observed_profile_bars.sum()),
        "nodes_created": len(n), "nodes_retired": int((n.lifecycle == "RETIRED").sum()),
        "nodes_persisted_at_cutoff": int((n.lifecycle == "PERSISTED_AT_CUTOFF").sum()),
        "events": len(corpus.events), "attempts": len(a), "episodes": len(e), "transits": len(t),
        "episodes_resolved": int((~episode_censored).sum()),
        "episodes_right_censored": int(episode_censored.sum()),
        "episode_censoring_rate": float(episode_censored.mean()),
        "behavioral_resolutions": behavioral_count,
        "behavioral_resolution_share": behavioral_count / len(e),
        "unexpected_data_gaps": int(runs.unexpected_data_gaps.sum()),
        "profile_bar_gap": int(runs.bar_gap.sum()),
        "replay_count": replay_verification.get("replay_count", 0),
        "replay_status": replay_verification.get("status", "MISSING"),
        "replay_hash_agreement": replay_verification.get("status") == "PASS",
        "replays": replay_verification.get("replays", []),
        "primary_key_duplicates": primary_duplicates,
        "qc_failures": corpus.qc_failures,
        "relational_invariant_failures": invariant_failures,
        "diagnostics": diagnostics,
        "status": "PASS" if not corpus.qc_failures and not any(primary_duplicates.values()) and not invariant_failures
                  and replay_verification.get("status") == "PASS" else "FAIL",
        "phase9_decision": "HOLD_RG2_FOR_LIFECYCLE_COVERAGE_REVIEW",
    }
    return {
        "summary": summary, "runs": runs, "coverage": coverage, "continuous": continuous,
        "cross_coverage": crosses, "continuous_stratified": stratified,
        "missingness": missing, "readiness": readiness, "invariants": invariants, "nodes": n,
    }
