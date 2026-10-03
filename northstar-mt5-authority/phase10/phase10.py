from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


NULL_TOKEN = "\\N"
TARGETS = [
    ("DE40_20260413_DIRECTIONAL_EXPANSION_UP", "instrument lacks directional coverage; add upward expansion"),
    ("FRA40_20251201_PROLONGED_BALANCE", "lowest episode count; add common balance coverage"),
    ("JPN225_20260713_DIRECTIONAL_EXPANSION_DOWN", "instrument lacks directional coverage; add downward expansion"),
    ("US30_20260413_DIRECTIONAL_EXPANSION_UP", "instrument lacks directional coverage; add upward expansion"),
    ("US500_20260601_DIRECTIONAL_EXPANSION_DOWN", "instrument lacks directional coverage; add downward expansion"),
    ("USTEC_20260105_PROLONGED_BALANCE", "lowest episode count; add common balance coverage"),
]
BEHAVIORAL_ATTEMPT_OUTCOMES = [
    "REJECT_TO_ORIGIN", "RECLAIM_AFTER_BREAK", "ACCEPT_THROUGH_NODE",
    "ACCEPT_AND_HOLD_RETEST", "ACCEPT_AND_FAIL_RETEST",
]
EXPECTED_ATTEMPT_RESOLUTIONS = set(BEHAVIORAL_ATTEMPT_OUTCOMES) | {
    "NODE_RETIRED", "TIMEOUT", "NONE",
}


def read_tsv(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False,
                       na_values=[NULL_TOKEN], **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _one(path: Path, pattern: str) -> Path:
    values = list(path.glob(pattern))
    if len(values) != 1:
        raise RuntimeError(f"expected one {pattern} under {path}, found {len(values)}")
    return values[0]


def admissions(workspace: Path) -> list[dict]:
    rows = []
    for directory in sorted((workspace / "furnace" / "corpus").iterdir()):
        if not directory.is_dir():
            continue
        receipt = json.loads((directory / "receipts" / "admission_receipt.json").read_text(encoding="utf-8-sig"))
        terminal = json.loads((directory / "receipts" / "terminal_run_receipt.json").read_text(encoding="utf-8-sig"))
        seal = json.loads((directory / "seal.json").read_text(encoding="utf-8-sig"))
        rows.append({"directory": directory, "admission": receipt, "terminal": terminal, "seal": seal})
    return rows


def metrics(workspace: Path) -> dict:
    runs = admissions(workspace)
    attempts: list[pd.DataFrame] = []
    episodes: list[pd.DataFrame] = []
    instrument_rows: list[dict] = []
    for run in runs:
        terminal = run["terminal"]
        auction = run["directory"] / "raw" / "auction"
        attempt = read_tsv(_one(auction, "*_attempts.tsv"), usecols=[
            "run_key", "attempt_id", "episode_id", "resolution", "completion_status",
            "start_region", "node_region",
        ])
        episode = read_tsv(_one(auction, "*_episodes.tsv"), usecols=[
            "run_key", "episode_id", "resolution", "completion_status", "initial_region",
        ])
        attempt["instrument"] = terminal["canonical_instrument"]
        episode["instrument"] = terminal["canonical_instrument"]
        attempts.append(attempt)
        episodes.append(episode)
        instrument_rows.append({
            "instrument": terminal["canonical_instrument"],
            "episodes": len(episode), "attempts": len(attempt), "runs": 1,
        })
    attempt_frame = pd.concat(attempts, ignore_index=True)
    episode_frame = pd.concat(episodes, ignore_index=True)
    by_instrument = pd.DataFrame(instrument_rows).groupby("instrument", as_index=False).sum()
    censored = int((episode_frame["completion_status"] == "RIGHT_CENSORED").sum())
    return {
        "runs": len(runs),
        "attempts": len(attempt_frame),
        "episodes": len(episode_frame),
        "episodes_right_censored": censored,
        "episode_censoring_rate": censored / len(episode_frame) if len(episode_frame) else 0.0,
        "by_instrument": by_instrument.set_index("instrument").to_dict(orient="index"),
        "attempt_resolution_counts": attempt_frame["resolution"].value_counts().sort_index().to_dict(),
        "episode_terminal_resolution_counts": episode_frame["resolution"].value_counts().sort_index().to_dict(),
        "episode_initial_region_counts": episode_frame["initial_region"].value_counts().sort_index().to_dict(),
    }


def js_divergence(left: dict[str, int], right: dict[str, int]) -> float:
    keys = sorted(set(left) | set(right))
    p = np.array([left.get(key, 0) for key in keys], dtype=float)
    q = np.array([right.get(key, 0) for key in keys], dtype=float)
    if p.sum() == 0 or q.sum() == 0:
        return math.inf
    p /= p.sum()
    q /= q.sum()
    midpoint = (p + q) / 2.0

    def kl(values: np.ndarray) -> float:
        mask = values > 0
        return float(np.sum(values[mask] * np.log2(values[mask] / midpoint[mask])))

    return (kl(p) + kl(q)) / 2.0


def write_plan(workspace: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = workspace / "campaign" / "campaign_manifest_rg2_v3.tsv"
    manifest = read_tsv(manifest_path)
    admitted_ids = {row["admission"]["window_id"] for row in admissions(workspace)}
    records = []
    for priority, (window_id, reason) in enumerate(TARGETS, start=1):
        found = manifest[manifest["window_id"] == window_id]
        if len(found) != 1:
            raise RuntimeError(f"target window missing or duplicated: {window_id}")
        row = found.iloc[0].to_dict()
        if window_id in admitted_ids:
            status = "ALREADY_ADMITTED"
        else:
            status = "TARGET_FROZEN"
        records.append({
            "priority": priority, "window_id": window_id,
            "canonical_instrument": row["canonical_instrument"],
            "broker_symbol": row["broker_symbol"], "selection_class": row["selection_class"],
            "environment_stratum": row["environment_stratum"], "window_start": row["window_start"],
            "window_end": row["window_end"], "configuration_hash": row["configuration_hash"],
            "research_generation": row["research_generation"], "target_reason": reason,
            "status_at_freeze": status,
        })
    targets = pd.DataFrame(records)
    targets.to_csv(output / "targeted_windows.tsv", sep="\t", index=False)
    baseline_metrics = metrics(workspace)
    baseline = {
        "contract": "MST_RG2_PHASE10_BASELINE_V1",
        "phase": "TARGETED_GAP_COLLECTION_AND_CORPUS_SEAL",
        "research_generation": 2,
        "manifest_sha256": sha256(manifest_path),
        "phase9_semantic_hash": json.loads(
            (workspace / "phase9" / "output" / "phase9_summary.json").read_text()
        )["semantic_result_sha256"],
        "lifecycle_audit_semantic_hash": json.loads(
            (workspace / "phase9" / "output" / "lifecycle_audit" / "lifecycle_audit.json").read_text()
        )["semantic_result_sha256"],
        "target_windows": [item[0] for item in TARGETS],
        "metrics": baseline_metrics,
    }
    (output / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(f"status=PLAN_FROZEN targets={len(records)} baseline_runs={baseline_metrics['runs']}")


def canonical_corpus_hash(run_rows: list[dict], manifest_sha: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"MST_RG2_CANONICAL_CORPUS_V1\0")
    digest.update(manifest_sha.encode())
    for row in sorted(run_rows, key=lambda value: value["terminal"]["run_key"]):
        terminal, seal = row["terminal"], row["seal"]
        fields = [
            terminal["run_key"], terminal["config_hash"], terminal["dataset_schema_version"],
            terminal["data_source_id"], terminal["data_fingerprint"],
            seal["canonical_dataset_hash"], seal["sealed_payload_sha256"],
        ]
        digest.update(("\t".join(map(str, fields)) + "\n").encode())
    return digest.hexdigest()


def _run_table(run_rows: list[dict]) -> pd.DataFrame:
    values = []
    for row in run_rows:
        terminal, admission, seal = row["terminal"], row["admission"], row["seal"]
        values.append({
            "run_key": terminal["run_key"], "invocation_id": terminal["invocation_id"],
            "window_id": admission["window_id"], "instrument": terminal["canonical_instrument"],
            "symbol": terminal["symbol"], "data_source_id": terminal["data_source_id"],
            "data_fingerprint": terminal["data_fingerprint"], "window_start": terminal["window_start"],
            "window_end": terminal["window_end"], "config_hash": terminal["config_hash"],
            "events": terminal["event_rows"], "attempts": terminal["attempt_rows"],
            "episodes": terminal["episode_rows"], "transits": terminal["transit_rows"],
            "canonical_dataset_hash": seal["canonical_dataset_hash"],
            "sealed_payload_sha256": seal["sealed_payload_sha256"], "status": "ADMITTED_SEALED",
        })
    return pd.DataFrame(values).sort_values(["instrument", "window_start", "run_key"])


def _quarantine_table(workspace: Path) -> pd.DataFrame:
    rows = []
    root = workspace / "furnace" / "quarantine"
    for receipt_path in sorted(root.rglob("failure_receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        rows.append({
            "path": str(receipt_path.parent.relative_to(workspace)),
            "window_id": receipt.get("window_id"), "attempt_tag": receipt.get("attempt_tag"),
            "reason": receipt.get("reason"), "status": receipt.get("status"),
            "deletion_performed": receipt.get("deletion_performed"),
        })
    return pd.DataFrame(rows, columns=[
        "path", "window_id", "attempt_tag", "reason", "status", "deletion_performed",
    ])


def _schema_dictionary(run_rows: list[dict]) -> dict:
    auction = run_rows[0]["directory"] / "raw" / "auction"
    datasets = {}
    for name in ("events", "attempts", "episodes", "context", "features", "transits", "runs"):
        path = _one(auction, f"*_{name}.tsv")
        header = path.open("r", encoding="utf-8-sig").readline().rstrip("\r\n").split("\t")
        datasets[name] = {"columns": header, "column_count": len(header)}
    return {
        "contract": "MST_AUCTION_RELATIONAL_V1", "dataset_schema": 7,
        "delimiter": "tab", "null_token": NULL_TOKEN, "timestamp_encoding": "unix_seconds",
        "timestamp_timezone": "MT5_SERVER", "price_precision_rule": "symbol_digits_from_runs",
        "migration_rule": "new_schema_or_semantics_new_stem_no_in_place_mix",
        "datasets": datasets,
    }


def seal(workspace: Path, plan_dir: Path, output: Path) -> int:
    baseline = json.loads((plan_dir / "baseline.json").read_text())
    targets = read_tsv(plan_dir / "targeted_windows.tsv")
    run_rows = admissions(workspace)
    admitted_ids = {row["admission"]["window_id"] for row in run_rows}
    missing_targets = sorted(set(targets["window_id"]) - admitted_ids)
    post = metrics(workspace)
    before = baseline["metrics"]
    divergence = js_divergence(before["attempt_resolution_counts"], post["attempt_resolution_counts"])
    phase9 = json.loads((workspace / "phase9" / "output" / "phase9_summary.json").read_text())
    lifecycle = json.loads(
        (workspace / "phase9" / "output" / "lifecycle_audit" / "lifecycle_audit.json").read_text()
    )
    min_runs = min(value["runs"] for value in post["by_instrument"].values())
    min_episodes = min(value["episodes"] for value in post["by_instrument"].values())
    common_counts = {
        name: int(post["attempt_resolution_counts"].get(name, 0))
        for name in BEHAVIORAL_ATTEMPT_OUTCOMES
    }
    unexpected_codes = sorted(set(post["attempt_resolution_counts"]) - EXPECTED_ATTEMPT_RESOLUTIONS)
    sparse = {
        "attempt_resolutions_below_30": {
            key: value for key, value in post["attempt_resolution_counts"].items() if value < 30
        },
        "episode_regions_below_30": {
            key: value for key, value in post["episode_initial_region_counts"].items() if value < 30
        },
    }
    gates = {
        "all_target_windows_admitted": not missing_targets,
        "minimum_three_runs_per_instrument": min_runs >= 3,
        "minimum_180_episodes_per_instrument": min_episodes >= 180,
        "common_behavioral_attempt_outcomes_at_least_30": min(common_counts.values()) >= 30,
        "episode_censoring_at_most_5_percent": post["episode_censoring_rate"] <= 0.05,
        "no_unexpected_attempt_resolution_codes": not unexpected_codes,
        "marginal_distribution_reproduced_jsd_at_most_0_05_bits": divergence <= 0.05,
        "phase9_qc_pass": phase9["status"] == "PASS",
        "lifecycle_attempt_analysis_pass": lifecycle["phase10_gates"]["behavioral_attempt_analysis"] == "PASS",
        "lifecycle_timeout_integrity_pass": lifecycle["phase10_gates"]["timeout_boundary_integrity"] == "PASS",
    }
    status = "SEALED" if all(gates.values()) else "HOLD_NOT_SEALED"
    candidate = {
        "contract": "MST_RG2_PHASE10_EXIT_GATE_V1", "status": status,
        "research_generation": 2, "baseline_runs": before["runs"], "final_runs": post["runs"],
        "baseline_episodes": before["episodes"], "final_episodes": post["episodes"],
        "added_runs": post["runs"] - before["runs"], "added_episodes": post["episodes"] - before["episodes"],
        "minimum_runs_per_instrument": int(min_runs),
        "minimum_episodes_per_instrument": int(min_episodes),
        "attempt_resolution_js_divergence_bits": divergence,
        "common_behavioral_attempt_counts": common_counts,
        "sparse_cells_honestly_retained": sparse, "missing_targets": missing_targets,
        "unexpected_attempt_resolution_codes": unexpected_codes, "gates": gates,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "phase10_exit_gate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    if status != "SEALED":
        print(f"status={status} failed={','.join(key for key, value in gates.items() if not value)}")
        return 2

    manifest_sha = sha256(workspace / "campaign" / "campaign_manifest_rg2_v3.tsv")
    corpus_hash = canonical_corpus_hash(run_rows, manifest_sha)
    run_table = _run_table(run_rows)
    run_table.to_csv(output / "corpus_manifest.tsv", sep="\t", index=False)
    run_table.to_csv(output / "admitted_runs.tsv", sep="\t", index=False)
    _quarantine_table(workspace).to_csv(output / "quarantined_runs.tsv", sep="\t", index=False)
    run_table[[
        "run_key", "instrument", "data_source_id", "data_fingerprint",
        "canonical_dataset_hash", "sealed_payload_sha256",
    ]].to_csv(output / "source_fingerprints.tsv", sep="\t", index=False)
    terminals = [row["terminal"] for row in run_rows]
    config = {
        "research_generation": 2, "configuration_hashes": sorted({row["config_hash"] for row in terminals}),
        "config_texts": sorted({row["config_text"] for row in terminals}),
        "version_matrix": sorted({
            (row["controller_version"], row["topology_version"], row["auction_grammar_version"],
             row["feature_schema_version"], row["dataset_schema_version"], row["producer_bundle_version"])
            for row in terminals
        }),
    }
    (output / "configuration.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (output / "schema_dictionary.json").write_text(
        json.dumps(_schema_dictionary(run_rows), indent=2), encoding="utf-8"
    )
    shutil.copy2(plan_dir / "targeted_windows.tsv", output / "targeted_gap_collection.tsv")
    shutil.copy2(workspace / "phase9" / "output" / "phase9_report.md", output / "coverage_report.md")
    shutil.copy2(workspace / "phase9" / "output" / "phase9_report.html", output / "coverage_report.html")
    shutil.copy2(
        workspace / "phase9" / "output" / "lifecycle_audit" / "lifecycle_audit.md",
        output / "lifecycle_audit.md",
    )
    seal_payload = {
        "contract": "MST_RG2_IMMUTABLE_CORPUS_SEAL_V1", "status": "SEALED",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(), "research_generation": 2,
        "run_count": len(run_rows), "canonical_corpus_sha256": corpus_hash,
        "campaign_manifest_sha256": manifest_sha,
        "configuration_hash": terminals[0]["config_hash"],
        "dataset_contract": terminals[0]["contract_id"],
        "dataset_schema": terminals[0]["dataset_schema_version"],
        "phase9_semantic_hash": phase9["semantic_result_sha256"],
        "lifecycle_audit_semantic_hash": lifecycle["semantic_result_sha256"],
        "immutability": "raw run directories remain immutable; additions or semantic changes require a new corpus generation",
        "artifacts": {},
    }
    for path in sorted(output.iterdir()):
        if path.name == "corpus_seal.json":
            continue
        seal_payload["artifacts"][path.name] = sha256(path)
    (output / "corpus_seal.json").write_text(json.dumps(seal_payload, indent=2), encoding="utf-8")
    print(f"status=SEALED runs={len(run_rows)} corpus_hash={corpus_hash}")
    return 0


def verify(workspace: Path, output: Path) -> int:
    seal_path = output / "corpus_seal.json"
    value = json.loads(seal_path.read_text())
    failures = []
    for name, expected in value["artifacts"].items():
        path = output / name
        if not path.exists() or sha256(path) != expected:
            failures.append(name)
    actual = canonical_corpus_hash(admissions(workspace), value["campaign_manifest_sha256"])
    if actual != value["canonical_corpus_sha256"]:
        failures.append("canonical_corpus_sha256")
    print(f"status={'PASS' if not failures else 'FAIL'} failures={','.join(failures)}")
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="RG2 Phase 10 targeted collection and seal")
    parser.add_argument("command", choices=["plan", "seal", "verify"])
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    plan_dir = workspace / "phase10" / "plan"
    seal_dir = workspace / "phase10" / "seal"
    if args.command == "plan":
        write_plan(workspace, plan_dir)
        return 0
    if args.command == "seal":
        return seal(workspace, plan_dir, seal_dir)
    return verify(workspace, seal_dir)


if __name__ == "__main__":
    raise SystemExit(main())
