from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from .research_interface import (
        HoldoutAccessError, INTERFACE_VERSION, QuerySpec, ResearchCorpus, verify_corpus,
    )
except ImportError:  # Direct script execution.
    from research_interface import (
        HoldoutAccessError, INTERFACE_VERSION, QuerySpec, ResearchCorpus, verify_corpus,
    )


TARGETS = (
    "reclaim_given_break",
    "initial_acceptance_given_initial_contact",
    "rejection_given_initial_contact",
    "retest_hold_given_retest_contact",
    "transit_given_episode_acceptance",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def artifacts(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "interface_seal.json"
    }


def build(workspace: Path, output: Path) -> int:
    allowed_root = (workspace / "phase10_5").resolve()
    try:
        output.relative_to(allowed_root)
    except ValueError as exc:
        raise RuntimeError("Phase 10.5 build output must remain under phase10_5") from exc
    if output == allowed_root:
        raise RuntimeError("refusing to replace the Phase 10.5 source directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    before, _ = verify_corpus(workspace)
    corpus = ResearchCorpus(workspace)

    partition = corpus.partition_manifest()
    partition.to_csv(output / "partition_manifest.tsv", sep="\t", index=False, na_rep="\\N")
    (output / "type_contract.json").write_text(
        json.dumps(corpus.type_contract(), indent=2), encoding="utf-8"
    )
    lifecycle = {
        "contract": "MST_RG2_ANALYTICAL_LIFECYCLE_SEMANTICS_V1",
        "behavioral_attempt_outcomes": sorted({
            value for value in corpus.attempt_view()["behavioral_attempt_outcome"].dropna().astype(str)
        }),
        "NODE_RETIRED": "structural_administrative_censoring",
        "attempt_TIMEOUT": "attempt_timeout_boundary_censored_for_behavioral_targets",
        "transit_TIMEOUT": "transit_timeout_boundary_censored_for_transit_targets",
        "RIGHT_CENSORED": "retained_and_excluded_from_observable_denominator",
        "episode_resolution": "terminal_receipt_not_whole_episode_outcome",
        "required_episode_unit": "attempt_chain_or_event_timeline",
    }
    (output / "lifecycle_semantics.json").write_text(json.dumps(lifecycle, indent=2), encoding="utf-8")

    result_root = output / "example_queries"
    summaries = []
    for target in TARGETS:
        result = corpus.estimate(QuerySpec.create(target, group_by=("canonical_instrument",)))
        data_path, receipt_path = result.write(result_root, workspace)
        summaries.append({
            "target": target,
            "eligible_count": int(result.table["eligible_count"].sum()),
            "observed_count": int(result.table["observed_count"].sum()),
            "censored_count": int(result.table["censored_count"].sum()),
            "result": data_path.name,
            "receipt": receipt_path.name,
        })
    (output / "target_registry.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")

    attempts = corpus.attempt_view()
    chains = corpus.attempt_chain_view()
    timeline = corpus.episode_timeline_view()
    transits = corpus.transit_view()
    context = corpus.node_context_view()
    holdout_denied = False
    try:
        corpus.attempt_view("FUTURE_HOLDOUT")
    except HoldoutAccessError:
        holdout_denied = True
    after, _ = verify_corpus(workspace)
    gates = {
        "sealed_corpus_verified_before_and_after": before["canonical_corpus_sha256"] == after["canonical_corpus_sha256"] == corpus.corpus_hash,
        "canonical_attempt_view_one_row_per_attempt": len(attempts) == attempts[["run_key", "attempt_id"]].drop_duplicates().shape[0],
        "attempt_chain_preserves_attempt_cardinality": len(chains) == len(attempts),
        "event_timeline_preserves_event_cardinality": len(timeline) == 38957,
        "transit_view_preserves_transit_cardinality": len(transits) == 628,
        "context_expansion_is_explicit": len(context) > len(attempts),
        "node_retired_never_behavioral": not attempts.loc[
            attempts["resolution"].eq("NODE_RETIRED"), "behavioral_attempt_outcome"
        ].notna().any(),
        "attempt_timeout_never_behavioral": not attempts.loc[
            attempts["resolution"].eq("TIMEOUT"), "behavioral_attempt_outcome"
        ].notna().any(),
        "holdout_access_fails_closed": holdout_denied,
        "all_canonical_targets_have_eligible_observations": all(row["eligible_count"] > 0 for row in summaries),
        "replay_partition_available": len(corpus.attempt_view("RG2_REPLAY_QC")) > 0,
    }
    exit_gate = {
        "contract": "MST_RG2_PHASE10_5_EXIT_GATE_V1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "interface_version": INTERFACE_VERSION,
        "corpus_sha256": corpus.corpus_hash,
        "analysis_code_sha256": corpus.interface_code_hash,
        "counts": {
            "runs": int(partition["run_key"].notna().sum()),
            "attempts": len(attempts), "events": len(timeline), "transits": len(transits),
            "contributor_context_rows": len(context),
            "reserved_holdout_windows": int(partition["partition"].eq("FUTURE_HOLDOUT").sum()),
        },
        "gates": gates,
    }
    (output / "phase10_5_exit_gate.json").write_text(json.dumps(exit_gate, indent=2), encoding="utf-8")
    seal = {
        "contract": "MST_RG2_RESEARCH_INTERFACE_SEAL_V1",
        "status": exit_gate["status"],
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_sha256": corpus.corpus_hash,
        "interface_version": INTERFACE_VERSION,
        "analysis_code_sha256": corpus.interface_code_hash,
        "artifacts": artifacts(output),
    }
    (output / "interface_seal.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    print(f"status={exit_gate['status']} attempts={len(attempts)} corpus={corpus.corpus_hash}")
    return 0 if exit_gate["status"] == "PASS" else 2


def verify(workspace: Path, output: Path) -> int:
    seal_path = output / "interface_seal.json"
    if not seal_path.is_file():
        print("status=FAIL failures=missing_interface_seal")
        return 2
    seal = json.loads(seal_path.read_text(encoding="utf-8-sig"))
    failures = [
        name for name, expected in seal.get("artifacts", {}).items()
        if not (output / name).is_file() or sha256(output / name) != expected
    ]
    try:
        corpus_seal, _ = verify_corpus(workspace)
        if corpus_seal["canonical_corpus_sha256"] != seal.get("corpus_sha256"):
            failures.append("corpus_sha256")
    except Exception as exc:  # verification reports the failure rather than masking it
        failures.append(f"corpus:{type(exc).__name__}")
    status = "PASS" if not failures and seal.get("status") == "PASS" else "FAIL"
    print(f"status={status} failures={','.join(failures)}")
    return 0 if status == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="RG2 Phase 10.5 research interface lock")
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "phase10_5" / "output").resolve()
    return build(workspace, output) if args.command == "build" else verify(workspace, output)


if __name__ == "__main__":
    raise SystemExit(main())
