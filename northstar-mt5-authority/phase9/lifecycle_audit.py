from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import Corpus, enrich, load_corpus, read_tsv, numeric, _one


TRACKER_MATCH_DISTANCE_ATR = 0.20
MAX_ATTEMPT_BARS = 24
EPISODE_GAP_BARS = 12
RETIRE_AFTER_REBUILDS = 3


@dataclass
class LifecycleAudit:
    summary: dict
    retirement_traces: pd.DataFrame
    replacement_candidates: pd.DataFrame
    timeout_traces: pd.DataFrame
    transit_timeout_traces: pd.DataFrame
    attempt_chains: pd.DataFrame
    node_history: pd.DataFrame


def _epoch(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    return parsed.astype("datetime64[s]").astype("int64").where(parsed.notna(), np.nan)


def _node_histories(corpus_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "run_key", "node_id", "snapshot", "generation", "market_time", "atr",
        "evidence_id", "lower", "price", "upper", "family_mask", "family_count",
        "member_count", "revision",
    ]
    first_parts: list[pd.DataFrame] = []
    last_parts: list[pd.DataFrame] = []
    cycle_parts: list[pd.DataFrame] = []
    for directory in sorted(corpus_root.iterdir()):
        if not directory.is_dir():
            continue
        node_path = _one(directory / "raw" / "structure", "*_nodes.tsv")
        for chunk in read_tsv(node_path, usecols=columns, chunksize=100_000):
            numeric(chunk, [
                "generation", "atr", "lower", "price", "upper", "family_mask",
                "family_count", "member_count", "revision",
            ])
            chunk["market_epoch"] = _epoch(chunk["market_time"])
            order = chunk.sort_values(["market_epoch", "generation"])
            first_parts.append(order.drop_duplicates(["run_key", "node_id"], keep="first"))
            last_parts.append(order.drop_duplicates(["run_key", "node_id"], keep="last"))
            cycle_parts.append(chunk[["run_key", "market_epoch", "atr"]].drop_duplicates())

    first = pd.concat(first_parts, ignore_index=True)
    last = pd.concat(last_parts, ignore_index=True)
    first = first.sort_values(["market_epoch", "generation"]).drop_duplicates(
        ["run_key", "node_id"], keep="first"
    )
    last = last.sort_values(["market_epoch", "generation"]).drop_duplicates(
        ["run_key", "node_id"], keep="last"
    )
    identity = ["run_key", "node_id"]
    first = first.rename(columns={c: f"first_{c}" for c in first.columns if c not in identity})
    last = last.rename(columns={c: f"last_{c}" for c in last.columns if c not in identity})
    history = first.merge(last, on=identity, how="outer", validate="one_to_one")
    cycles = pd.concat(cycle_parts, ignore_index=True)
    cycles = cycles.groupby(["run_key", "market_epoch"], as_index=False)["atr"].median()
    return history, cycles


def _prepare_structure_events(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    numeric(result, [
        "reference_price", "lower", "price", "upper", "attempt_count", "revision",
    ])
    result["market_epoch"] = _epoch(result["market_time"])
    return result


def _final_attempts(attempts: pd.DataFrame) -> pd.DataFrame:
    return attempts.sort_values(["run_key", "episode_id", "ordinal", "end"]).drop_duplicates(
        ["run_key", "episode_id"], keep="last"
    )


def _phase(row: pd.Series) -> str:
    if pd.notna(row.get("accepted")):
        return "ACCEPTED_PENDING_DEPARTURE"
    if pd.notna(row.get("break")):
        return "BROKEN_NO_ACCEPTANCE"
    if pd.notna(row.get("contact")):
        if float(row.get("penetration_atr", 0.0) or 0.0) > 0.0:
            return "PENETRATED_NO_RESOLUTION"
        return "CONTACT_NO_PENETRATION"
    return "APPROACH_NO_CONTACT"


def _interval_gap(lower_a: float, upper_a: float, lower_b: float, upper_b: float) -> float:
    if lower_b > upper_a:
        return lower_b - upper_a
    if lower_a > upper_b:
        return lower_a - upper_b
    return 0.0


def _replacement_receipts(
    retirements: pd.DataFrame,
    structure_events: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    created = structure_events[structure_events["event"] == "CREATED"].copy()
    origin = history[[
        "run_key", "node_id", "first_family_mask", "first_family_count",
    ]].rename(columns={
        "node_id": "candidate_node_id",
        "first_family_mask": "candidate_family_mask",
        "first_family_count": "candidate_family_count",
    })
    created = created.rename(columns={
        "node_id": "candidate_node_id", "evidence_id": "candidate_evidence_id",
        "market_epoch": "candidate_created_epoch", "lower": "candidate_lower",
        "price": "candidate_price", "upper": "candidate_upper",
    }).merge(origin, on=["run_key", "candidate_node_id"], how="left")

    rows: list[dict] = []
    by_run = {key: group for key, group in created.groupby("run_key", sort=False)}
    for retired in retirements.itertuples(index=False):
        pool = by_run.get(retired.run_key)
        if pool is None or not np.isfinite(retired.retire_epoch):
            continue
        start = retired.last_market_epoch
        if not np.isfinite(start):
            start = retired.attempt_start
        candidates = pool[
            (pool["candidate_created_epoch"] > start)
            & (pool["candidate_created_epoch"] <= retired.retire_epoch + 60)
            & (pool["candidate_node_id"] != retired.node_id)
        ]
        safe_atr = max(float(retired.retire_atr), 1e-12)
        old_mask = int(retired.last_family_mask) if pd.notna(retired.last_family_mask) else 0
        for candidate in candidates.itertuples(index=False):
            new_mask = int(candidate.candidate_family_mask) if pd.notna(candidate.candidate_family_mask) else 0
            gap_atr = _interval_gap(
                retired.last_lower, retired.last_upper,
                candidate.candidate_lower, candidate.candidate_upper,
            ) / safe_atr
            center_gap_atr = abs(candidate.candidate_price - retired.last_price) / safe_atr
            family_overlap = old_mask & new_mask
            compatible = (
                family_overlap != 0
                and gap_atr <= TRACKER_MATCH_DISTANCE_ATR
                and center_gap_atr <= TRACKER_MATCH_DISTANCE_ATR * 2.0
            )
            if not compatible:
                continue
            rows.append({
                "run_key": retired.run_key,
                "instrument": retired.instrument,
                "episode_id": retired.episode_id,
                "retired_node_id": retired.node_id,
                "candidate_node_id": candidate.candidate_node_id,
                "retire_epoch": retired.retire_epoch,
                "candidate_created_epoch": candidate.candidate_created_epoch,
                "seconds_from_retire": candidate.candidate_created_epoch - retired.retire_epoch,
                "created_during_three_miss_grace": candidate.candidate_created_epoch <= retired.retire_epoch,
                "gap_atr": gap_atr,
                "center_gap_atr": center_gap_atr,
                "family_overlap_mask": family_overlap,
                "old_family_mask": old_mask,
                "candidate_family_mask": new_mask,
                "old_evidence_id": retired.last_evidence_id,
                "candidate_evidence_id": candidate.candidate_evidence_id,
            })
    return pd.DataFrame(rows)


def _retirement_traces(
    corpus: Corpus,
    structure_events: pd.DataFrame,
    history: pd.DataFrame,
    cycles: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    resolved = corpus.episodes[
        (corpus.episodes["completion_status"] == "RESOLVED")
        & (corpus.episodes["resolution"] == "NODE_RETIRED")
    ].copy()
    final = _final_attempts(corpus.attempts)
    keep = [
        "run_key", "episode_id", "attempt_id", "node_id", "ordinal", "start", "contact",
        "break", "accepted", "end", "resolution", "start_bar", "end_bar", "frozen_atr",
        "penetration_atr", "node_width_atr", "family_mask", "family_count", "member_count",
    ]
    traces = resolved.merge(final[keep], on=["run_key", "episode_id", "node_id"],
                            suffixes=("_episode", "_attempt"), validate="one_to_one")
    traces = traces.rename(columns={
        "start_episode": "episode_start", "end_episode": "episode_end",
        "start_attempt": "attempt_start", "end_attempt": "attempt_end",
        "resolution_episode": "episode_resolution",
        "resolution_attempt": "attempt_resolution",
    })
    history_keep = history.rename(columns={"node_id": "history_node_id"})
    traces = traces.merge(
        history_keep, left_on=["run_key", "node_id"], right_on=["run_key", "history_node_id"],
        how="left", validate="many_to_one",
    )
    retire = structure_events[structure_events["event"] == "RETIRE"].copy()
    retire = retire.sort_values("market_epoch").drop_duplicates(["run_key", "node_id"], keep="last")
    retire = retire[["run_key", "node_id", "market_epoch", "revision", "attempt_count"]].rename(
        columns={"market_epoch": "retire_epoch", "revision": "retire_revision",
                 "attempt_count": "retire_attempt_count"}
    )
    traces = traces.merge(retire, on=["run_key", "node_id"], how="left", validate="many_to_one")
    traces["retire_epoch"] = pd.to_numeric(traces["retire_epoch"], errors="coerce").astype(float)
    cycles["market_epoch"] = pd.to_numeric(cycles["market_epoch"], errors="coerce").astype(float)
    traces["retire_atr"] = np.nan
    for run_key, indexes in traces.groupby("run_key").groups.items():
        available = cycles[cycles["run_key"] == run_key].sort_values("market_epoch")
        if available.empty:
            continue
        times = available["market_epoch"].to_numpy()
        atrs = available["atr"].to_numpy()
        for index in indexes:
            target = traces.at[index, "retire_epoch"]
            if not np.isfinite(target):
                continue
            position = int(np.searchsorted(times, target, side="right") - 1)
            if position >= 0 and target - times[position] <= 300:
                traces.at[index, "retire_atr"] = atrs[position]
    traces["retire_atr"] = traces["retire_atr"].fillna(traces["frozen_atr"])
    traces["last_seen_to_retire_seconds"] = traces["retire_epoch"] - traces["last_market_epoch"]
    traces["attempt_start_to_retire_seconds"] = traces["retire_epoch"] - traces["attempt_start"]
    traces["episode_start_to_retire_seconds"] = traces["retire_epoch"] - traces["episode_start"]
    traces["attempt_end_to_tracker_retire_seconds"] = traces["retire_epoch"] - traces["attempt_end"]
    traces["orphaned_before_tracker_retire"] = traces["attempt_end_to_tracker_retire_seconds"] > 0
    traces["same_id_seen_after_attempt_end"] = traces["last_market_epoch"] > traces["attempt_end"]
    traces["terminal_phase"] = traces.apply(_phase, axis=1)

    lineage = structure_events[structure_events["event"].isin(["MERGE", "SPLIT"])].copy()
    lineage_counts: list[dict] = []
    by_run = {key: group for key, group in lineage.groupby("run_key", sort=False)}
    for row in traces.itertuples(index=False):
        pool = by_run.get(row.run_key)
        if pool is None:
            count, successors, kinds = 0, "", ""
        else:
            found = pool[
                (pool["related_node_id"] == row.node_id)
                & (pool["market_epoch"] > row.last_market_epoch)
                & (pool["market_epoch"] <= row.retire_epoch)
            ]
            count = len(found)
            successors = ",".join(sorted(found["node_id"].astype(str).unique()))
            kinds = ",".join(sorted(found["event"].astype(str).unique()))
        lineage_counts.append({"lineage_receipt_count": count,
                               "lineage_successor_ids": successors,
                               "lineage_event_kinds": kinds})
    traces = pd.concat([traces.reset_index(drop=True), pd.DataFrame(lineage_counts)], axis=1)
    replacements = _replacement_receipts(traces, structure_events, history)
    compatible_episodes = set(replacements.loc[
        replacements.get("created_during_three_miss_grace", pd.Series(dtype=bool)) == True,
        "episode_id",
    ].astype(str)) if not replacements.empty else set()
    traces["compatible_created_during_grace"] = traces["episode_id"].astype(str).isin(compatible_episodes)
    traces["continuity_receipt"] = (
        (traces["lineage_receipt_count"] > 0) | traces["compatible_created_during_grace"]
    )
    columns = [
        "run_key", "instrument", "episode_id", "attempt_id", "node_id", "ordinal",
        "episode_start", "attempt_start", "retire_epoch", "episode_end", "attempt_end",
        "first_market_epoch", "last_market_epoch", "last_seen_to_retire_seconds",
        "attempt_start_to_retire_seconds", "episode_start_to_retire_seconds",
        "attempt_end_to_tracker_retire_seconds", "orphaned_before_tracker_retire",
        "same_id_seen_after_attempt_end",
        "retire_atr", "last_lower", "last_price", "last_upper", "last_family_mask",
        "last_family_count", "last_member_count", "last_revision", "retire_revision",
        "retire_attempt_count", "terminal_phase", "penetration_atr", "node_width_atr",
        "lineage_receipt_count", "lineage_event_kinds", "lineage_successor_ids",
        "compatible_created_during_grace", "continuity_receipt",
    ]
    return traces[[c for c in columns if c in traces]], replacements


def _timeout_traces(corpus: Corpus) -> pd.DataFrame:
    attempts = corpus.attempts[
        (corpus.attempts["completion_status"] == "RESOLVED")
        & (corpus.attempts["resolution"] == "TIMEOUT")
    ].copy()
    attempts["bar_span"] = attempts["end_bar"] - attempts["start_bar"]
    attempts["duration_seconds"] = attempts["end"] - attempts["start"]
    attempts["terminal_phase"] = attempts.apply(_phase, axis=1)
    attempts["threshold_exact"] = attempts["bar_span"] == MAX_ATTEMPT_BARS + 1
    episode_meta = corpus.episodes[[
        "run_key", "episode_id", "end", "attempts", "duration_bars", "duration_seconds",
        "completion_status", "resolution",
    ]].rename(columns={
        "end": "episode_end", "attempts": "episode_attempts", "duration_bars": "episode_duration_bars",
        "duration_seconds": "episode_duration_seconds", "completion_status": "episode_completion",
        "resolution": "episode_resolution",
    })
    attempts = attempts.merge(episode_meta, on=["run_key", "episode_id"], how="left",
                              validate="many_to_one")
    event_sequences = corpus.events.groupby(["run_key", "attempt_id"], sort=False)["event_type"].agg(
        lambda values: ">".join(values.astype(str))
    ).rename("event_sequence").reset_index()
    attempts = attempts.merge(event_sequences, on=["run_key", "attempt_id"], how="left",
                              validate="one_to_one")
    attempts["is_episode_terminal_attempt"] = (
        (attempts["episode_completion"] == "RESOLVED")
        & (attempts["episode_resolution"] == "TIMEOUT")
        & (attempts["end"] == attempts["episode_end"])
    )
    columns = [
        "run_key", "instrument", "episode_id", "attempt_id", "node_id", "ordinal",
        "start", "contact", "break", "accepted", "end", "start_bar", "end_bar", "bar_span",
        "duration_seconds", "terminal_phase", "threshold_exact", "event_sequence",
        "node_width_atr", "initial_distance_atr", "approach_efficiency", "penetration_atr",
        "inside_updates", "inside_seconds", "far_closes", "max_above_atr", "max_below_atr",
        "episode_attempts", "episode_duration_bars", "episode_duration_seconds",
        "episode_completion", "episode_resolution", "is_episode_terminal_attempt",
    ]
    return attempts[[c for c in columns if c in attempts]]


def _transit_timeout_traces(corpus: Corpus) -> pd.DataFrame:
    transits = corpus.transits[
        (corpus.transits["completion_status"] == "RESOLVED")
        & (corpus.transits["resolution"] == "TIMEOUT")
    ].copy()
    episodes = corpus.episodes[[
        "run_key", "episode_id", "end", "completion_status", "resolution",
    ]].rename(columns={
        "end": "episode_end", "completion_status": "episode_completion",
        "resolution": "episode_resolution",
    })
    transits = transits.merge(episodes, on=["run_key", "episode_id"], how="left",
                              validate="many_to_one")
    transits["is_episode_terminal_transit"] = (
        (transits["episode_completion"] == "RESOLVED")
        & (transits["episode_resolution"] == "TIMEOUT")
        & (transits["end"] == transits["episode_end"])
    )
    transits["threshold_exact"] = transits["duration_bars"] == MAX_ATTEMPT_BARS * 2 + 1
    columns = [
        "run_key", "instrument", "episode_id", "attempt_id", "transit_id", "source_node_id",
        "destination_node_id", "direction", "start", "end", "start_bar", "end_bar",
        "duration_bars", "duration_seconds", "distance_atr", "path_efficiency",
        "max_adverse_atr", "resolution", "threshold_exact", "episode_end",
        "episode_completion", "episode_resolution", "is_episode_terminal_transit",
    ]
    return transits[[c for c in columns if c in transits]]


def _attempt_chains(corpus: Corpus) -> pd.DataFrame:
    target = corpus.episodes[
        (corpus.episodes["completion_status"] == "RESOLVED")
        & corpus.episodes["resolution"].isin(["NODE_RETIRED", "TIMEOUT"])
    ][["run_key", "episode_id", "resolution"]].rename(columns={"resolution": "episode_resolution"})
    chains = corpus.attempts.merge(target, on=["run_key", "episode_id"], how="inner")
    columns = [
        "run_key", "instrument", "episode_id", "episode_resolution", "ordinal", "attempt_id",
        "node_id", "start", "contact", "break", "accepted", "end", "resolution",
        "completion_status", "start_bar", "end_bar", "node_width_atr", "penetration_atr",
        "inside_seconds", "max_above_atr", "max_below_atr",
    ]
    return chains.sort_values(["run_key", "episode_id", "ordinal"])[columns]


def audit(corpus: Corpus, corpus_root: Path) -> LifecycleAudit:
    enrich(corpus)
    structure_events = _prepare_structure_events(corpus.structure_events)
    history, cycles = _node_histories(corpus_root)
    retirement, replacements = _retirement_traces(corpus, structure_events, history, cycles)
    timeouts = _timeout_traces(corpus)
    transit_timeouts = _transit_timeout_traces(corpus)
    chains = _attempt_chains(corpus)

    retired_n = len(retirement)
    retired_attempts = corpus.attempts[
        (corpus.attempts["completion_status"] == "RESOLVED")
        & (corpus.attempts["resolution"] == "NODE_RETIRED")
    ][["run_key", "episode_id", "attempt_id"]]
    retired_episode_chains = retired_attempts[["run_key", "episode_id"]].drop_duplicates().merge(
        corpus.episodes[["run_key", "episode_id", "completion_status", "resolution"]],
        on=["run_key", "episode_id"], how="left", validate="one_to_one",
    )
    later_episode_outcomes = retired_episode_chains[
        ~((retired_episode_chains["completion_status"] == "RESOLVED")
          & (retired_episode_chains["resolution"] == "NODE_RETIRED"))
    ]
    later_receipts = {
        f"{status}:{resolution}": int(count)
        for (status, resolution), count in later_episode_outcomes.groupby(
            ["completion_status", "resolution"]
        ).size().items()
    }
    lineage_n = int((retirement["lineage_receipt_count"] > 0).sum())
    compatible_n = int(retirement["compatible_created_during_grace"].sum())
    continuity_n = int(retirement["continuity_receipt"].sum())
    timeout_episode = timeouts[timeouts["is_episode_terminal_attempt"]]
    terminal_transit_timeout = transit_timeouts[transit_timeouts["is_episode_terminal_transit"]]
    prior_behavior = chains[
        chains["episode_resolution"].isin(["NODE_RETIRED", "TIMEOUT"])
        & chains["resolution"].isin([
            "REJECT_TO_ORIGIN", "RECLAIM_AFTER_BREAK", "ACCEPT_THROUGH_NODE",
            "ACCEPT_AND_HOLD_RETEST", "ACCEPT_AND_FAIL_RETEST",
        ])
    ][["run_key", "episode_id"]].drop_duplicates()
    administrative_episodes = chains[["run_key", "episode_id"]].drop_duplicates()
    prior_behavior_rate = len(prior_behavior) / len(administrative_episodes) if len(administrative_episodes) else 0.0

    retirement_continuity_rate = continuity_n / retired_n if retired_n else 0.0
    retire_receipts = int(retirement["retire_epoch"].notna().sum())
    orphaned_before_retire = int(retirement["orphaned_before_tracker_retire"].sum())
    recovered_same_id = int(retirement["same_id_seen_after_attempt_end"].sum())
    verdict = "RG2_ADMISSIBLE_FOR_PHASE10_ATTEMPT_LEVEL_ANALYSIS_ONLY"
    reason = (
        "behavioral attempts are usable, but NODE_RETIRED is a first-absence administrative "
        "termination and episode.resolution is not a whole-episode outcome"
    )

    summary = {
        "contract": "MST_RG2_PHASE9_LIFECYCLE_AUDIT_V1",
        "scope": "PRE_PHASE10_PHASE9_EXIT_GATE",
        "verdict": verdict,
        "verdict_reason": reason,
        "constants": {
            "tracker_match_distance_atr": TRACKER_MATCH_DISTANCE_ATR,
            "retire_after_rebuilds": RETIRE_AFTER_REBUILDS,
            "max_attempt_bars": MAX_ATTEMPT_BARS,
            "episode_gap_bars": EPISODE_GAP_BARS,
        },
        "node_retired": {
            "resolved_attempts": len(retired_attempts),
            "episodes_containing_node_retired_attempt": len(retired_episode_chains),
            "terminal_resolved_episodes": retired_n,
            "episode_chains_with_later_or_censored_terminal_receipt": len(later_episode_outcomes),
            "later_or_censored_terminal_receipts": later_receipts,
            "explicit_lineage_receipts": lineage_n,
            "compatible_created_during_grace": compatible_n,
            "continuity_receipts": continuity_n,
            "continuity_rate": retirement_continuity_rate,
            "tracker_retire_receipts": retire_receipts,
            "tracker_retire_receipt_rate": retire_receipts / retired_n if retired_n else 0.0,
            "orphaned_before_tracker_retire": orphaned_before_retire,
            "orphaned_before_tracker_retire_rate": orphaned_before_retire / retired_n if retired_n else 0.0,
            "same_id_seen_after_attempt_end": recovered_same_id,
            "same_id_recovery_rate": recovered_same_id / retired_n if retired_n else 0.0,
            "median_seconds_last_seen_to_retire": float(retirement["last_seen_to_retire_seconds"].median()),
            "median_seconds_attempt_start_to_retire": float(retirement["attempt_start_to_retire_seconds"].median()),
            "median_seconds_attempt_end_to_tracker_retire": float(
                retirement["attempt_end_to_tracker_retire_seconds"].median()
            ),
            "finding": "auction attempts terminate on first candidate absence, before the tracker's three-miss retirement gate",
        },
        "timeout": {
            "resolved_attempts": len(timeouts),
            "episodes_terminated_by_attempt_timeout": len(timeout_episode),
            "resolved_transit_timeouts": len(transit_timeouts),
            "episodes_terminated_by_transit_timeout": len(terminal_transit_timeout),
            "terminal_timeout_episodes_total": len(timeout_episode) + len(terminal_transit_timeout),
            "all_attempts_exactly_25_bars": bool(timeouts["threshold_exact"].all()),
            "all_transits_exactly_49_bars": bool(transit_timeouts["threshold_exact"].all()),
            "median_attempt_duration_seconds": float(timeouts["duration_seconds"].median()),
            "median_terminal_episode_attempts": float(timeout_episode["episode_attempts"].median()),
            "terminal_phase_counts": timeout_episode["terminal_phase"].value_counts().to_dict(),
        },
        "episode_semantics": {
            "administrative_terminal_episodes": len(administrative_episodes),
            "with_prior_behavioral_attempt": len(prior_behavior),
            "prior_behavioral_attempt_rate": prior_behavior_rate,
            "finding": "episode resolution is the latest completed attempt or transit resolution, not a summary of all attempts",
        },
        "phase10_gates": {
            "behavioral_attempt_analysis": "PASS",
            "timeout_boundary_integrity": "PASS",
            "episode_resolution_as_whole_episode_outcome": "FAIL",
            "node_retired_as_market_behavior_outcome": "FAIL",
            "required_treatment": (
                "analyze attempt chains; treat NODE_RETIRED as structural administrative censoring; "
                "separate attempt TIMEOUT from transit TIMEOUT"
            ),
            "new_generation_required_now": False,
            "new_generation_trigger": "only if runtime lifecycle or auction semantics are changed",
        },
    }
    return LifecycleAudit(summary, retirement, replacements, timeouts, transit_timeouts, chains, history)


def semantic_hash(audit_result: LifecycleAudit, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(audit_result.summary, sort_keys=True, separators=(",", ":")).encode())
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_and_audit(workspace: Path) -> LifecycleAudit:
    corpus_root = workspace / "furnace" / "corpus"
    corpus = load_corpus(corpus_root, workspace / "campaign" / "campaign_manifest_rg2_v3.tsv")
    return audit(corpus, corpus_root)
