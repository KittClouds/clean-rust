from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lifecycle_audit import load_and_audit, semantic_hash


def _pct(value: float) -> str:
    return f"{value * 100.0:.1f}%"


def _write_report(result, path: Path) -> None:
    s = result.summary
    retired = s["node_retired"]
    timeout = s["timeout"]
    episode = s["episode_semantics"]
    phases = "\n".join(
        f"- {name}: {count}" for name, count in sorted(timeout["terminal_phase_counts"].items())
    )
    text = f"""# RG2 lifecycle semantics audit

Scope: **Phase 9 exit gate, before Phase 10**

Verdict: **{s['verdict']}**

Reason: {s['verdict_reason']}.

## Authoritative code semantics

- A stable node retires after three unmatched structural rebuilds.
- An active attempt becomes `NODE_RETIRED` as soon as its exact stable node ID is absent from the current candidate array, before the tracker retirement gate.
- An attempt becomes `TIMEOUT` only when closed-bar span is greater than 24; RG2 receipts should therefore close at 25 bars.
- An episode closes after the 12-bar gap and retains the resolution of its last completed attempt.

## NODE_RETIRED trace

- Resolved `NODE_RETIRED` attempts: {retired['resolved_attempts']}
- Episode chains containing one: {retired['episodes_containing_node_retired_attempt']}
- Episodes whose terminal receipt is `NODE_RETIRED`: {retired['terminal_resolved_episodes']}
- Chains later closed by another outcome or censor: {retired['episode_chains_with_later_or_censored_terminal_receipt']}
- Explicit merge/split lineage during the three-miss grace: {retired['explicit_lineage_receipts']}
- Tracker-compatible node created during the grace: {retired['compatible_created_during_grace']}
- Either continuity receipt: {retired['continuity_receipts']} ({_pct(retired['continuity_rate'])})
- Tracker retirement receipt eventually present: {retired['tracker_retire_receipts']} ({_pct(retired['tracker_retire_receipt_rate'])})
- Attempt ended before tracker retirement: {retired['orphaned_before_tracker_retire']} ({_pct(retired['orphaned_before_tracker_retire_rate'])})
- Same stable ID reappeared after attempt termination: {retired['same_id_seen_after_attempt_end']} ({_pct(retired['same_id_recovery_rate'])})
- Median last-seen to retirement: {retired['median_seconds_last_seen_to_retire']:.0f} seconds
- Median attempt-start to retirement: {retired['median_seconds_attempt_start_to_retire']:.0f} seconds
- Median attempt-end to tracker-retirement receipt: {retired['median_seconds_attempt_end_to_tracker_retire']:.0f} seconds

The compatible-node test reproduces the tracker geometry and family-mask gates. Its ATR is recovered from the retirement rebuild snapshot; it is an audit reconstruction, while merge/split rows are authoritative lineage receipts.

## TIMEOUT trace

- Resolved timeout attempts: {timeout['resolved_attempts']}
- Episodes terminated by attempt timeout: {timeout['episodes_terminated_by_attempt_timeout']}
- Episodes terminated by transit timeout: {timeout['episodes_terminated_by_transit_timeout']}
- Every timeout attempt ended at exactly 25 bars: {timeout['all_attempts_exactly_25_bars']}
- Every timeout transit ended at exactly 49 bars: {timeout['all_transits_exactly_49_bars']}
- Median timeout-attempt duration: {timeout['median_attempt_duration_seconds']:.0f} seconds
- Median attempts in terminal timeout episodes: {timeout['median_terminal_episode_attempts']:.0f}

Terminal phases:

{phases}

## Episode-label finding

- Episodes ending in `NODE_RETIRED` or `TIMEOUT`: {episode['administrative_terminal_episodes']}
- Those containing an earlier behavioral attempt: {episode['with_prior_behavioral_attempt']} ({_pct(episode['prior_behavioral_attempt_rate'])})

`episode.resolution` is therefore a terminal attempt-or-transit label. It must not be interpreted as a summary of the complete attempt chain.

## Phase 10 gate

RG2 can enter Phase 10 for attempt-level behavioral analysis. `NODE_RETIRED` must be treated as structural administrative censoring, attempt and transit timeouts must stay separate, and episode resolution cannot serve as a whole-episode target. Changing runtime semantics would start a new research generation; this audit does not require that change before descriptive work begins.
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-Phase-10 RG2 lifecycle audit")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "phase9" / "output" / "lifecycle_audit").resolve()
    output.mkdir(parents=True, exist_ok=True)

    result = load_and_audit(workspace)
    exports = {
        "node_retirement_traces.csv": result.retirement_traces,
        "replacement_candidates.csv": result.replacement_candidates,
        "timeout_traces.csv": result.timeout_traces,
        "transit_timeout_traces.csv": result.transit_timeout_traces,
        "episode_attempt_chains.csv": result.attempt_chains,
        "node_history.csv": result.node_history,
    }
    paths: list[Path] = []
    for name, frame in exports.items():
        path = output / name
        frame.to_csv(path, index=False, na_rep="\\N")
        paths.append(path)
    report_path = output / "lifecycle_audit.md"
    _write_report(result, report_path)
    paths.append(report_path)
    result.summary["semantic_result_sha256"] = semantic_hash(result, paths)
    summary_path = output / "lifecycle_audit.json"
    summary_path.write_text(json.dumps(result.summary, indent=2), encoding="utf-8")
    paths.append(summary_path)

    code_hash = hashlib.sha256()
    for source in (Path(__file__), Path(__file__).with_name("lifecycle_audit.py")):
        code_hash.update(source.read_bytes())
    manifest = {
        "contract": "MST_RG2_PHASE9_LIFECYCLE_AUDIT_MANIFEST_V1",
        "semantic_result_sha256": result.summary["semantic_result_sha256"],
        "analysis_code_sha256": code_hash.hexdigest(),
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    }
    (output / "audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"verdict={result.summary['verdict']}")
    print(f"retired_continuity={result.summary['node_retired']['continuity_rate']:.6f}")
    print(f"timeout_exact_25={result.summary['timeout']['all_attempts_exactly_25_bars']}")
    print(f"semantic_hash={result.summary['semantic_result_sha256']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
