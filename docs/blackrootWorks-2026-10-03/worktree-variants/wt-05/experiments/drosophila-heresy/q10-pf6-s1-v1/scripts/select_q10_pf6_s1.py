"""Deterministic, pre-replay sampler for Q10-PF6-S1."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF5 = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
PF6 = REPO / "experiments/drosophila-heresy/q10-pf6-v1"
AUDIT = PF5 / "qualification/full-run-v3-audit"
SLICE_ID = ("seed9731-L-tau16.json", 0, 6)
sys.path.insert(0, str(PF6 / "scripts"))
import run_q10_pf6 as PF6_RUNNER  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def identity(item: dict[str, Any]) -> tuple[str, int, int]:
    return (str(item["source_event"]), int(item["set_index"]), int(item["group_index"]))


def stable_hash(key: tuple[str, int, int]) -> str:
    encoded = f"{key[0]}|{key[1]}|{key[2]}".encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * quantile + 0.9999999999)) - 1))
    return ordered[index]


def baseline_metadata(item: dict[str, Any], state: Any) -> dict[str, Any]:
    residuals = [
        PF6_RUNNER.PF5.from_bits(state.baseline_readout_bits[row])
        - PF6_RUNNER.PF5.from_bits(state.target_readout_bits[row])
        for row in item["rows"]
    ]
    mismatched = sum(
        state.baseline_readout_bits[row] != state.target_readout_bits[row]
        for row in item["rows"]
    )
    classes = [str(value) for value in item.get("threshold_classes", [])]
    threshold_fraction = (
        sum(value == "threshold_gated" for value in classes) / len(classes)
        if classes else None
    )
    # PF5 stores bridge totals globally, not per group. Do not reconstruct a
    # per-group bridge value by replaying; missing local metadata stays zero.
    return {
        "coordinate_count": len(item["coordinates"]),
        "mismatched_row_count": int(mismatched),
        "residual_mass": float(sum(value * value for value in residuals)),
        "bridge_count": 0,
        "bridge_count_source": "not_present_in_sealed_pf5_group_receipt",
        "threshold_gated_fraction": threshold_fraction,
        "row_count": len(item["rows"]),
    }


def tie_key(record: dict[str, Any]) -> tuple[Any, ...]:
    metadata = record["baseline"]
    return (
        -float(metadata["residual_mass"]),
        -int(metadata["mismatched_row_count"]),
        -int(metadata["bridge_count"]),
        str(record["stable_group_hash"]),
    )


def choose_endpoint(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = [int(record["baseline"]["coordinate_count"]) for record in records]
    targets = (
        ("low_coordinate_quartile", nearest_rank(counts, 0.25)),
        ("median_coordinate_count", nearest_rank(counts, 0.50)),
        ("high_coordinate_quartile", nearest_rank(counts, 0.75)),
    )
    chosen: list[dict[str, Any]] = []
    used: set[tuple[str, int, int]] = set()
    for stratum, target in targets:
        candidates = [record for record in records if tuple(record["identity"]) not in used]
        candidates.sort(
            key=lambda record: (
                abs(int(record["baseline"]["coordinate_count"]) - target),
                *tie_key(record),
            )
        )
        if not candidates:
            raise RuntimeError("endpoint has fewer than three eligible groups")
        selected = dict(candidates[0])
        selected["stratum"] = stratum
        selected["target_coordinate_count"] = target
        chosen.append(selected)
        used.add(tuple(selected["identity"]))
    return chosen


def build_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    results_path = AUDIT / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    lineage = PF6_RUNNER.PF5.load_lineage(PF6_RUNNER.PF5_ROOT)
    states = PF6_RUNNER.PF5.load_endpoint_states(lineage)
    state_by_key = {state.key: state for state in states}
    all_items = list(results["endpoint_results"])
    eligible = [
        item for item in all_items
        if item.get("status") == "OVERSIZE_UNTESTED" and identity(item) != SLICE_ID
    ]
    if len(all_items) != 1596 or len(eligible) != 1456:
        raise RuntimeError(f"S1 eligible population drift: all={len(all_items)} pool={len(eligible)}")
    records: list[dict[str, Any]] = []
    for item in eligible:
        key = identity(item)
        state = state_by_key[(key[0], key[1])]
        records.append({
            "identity": list(key),
            "stable_group_hash": stable_hash(key),
            "endpoint": [key[0], key[1]],
            "baseline": baseline_metadata(item, state),
        })
    by_endpoint: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        by_endpoint.setdefault(tuple(record["endpoint"]), []).append(record)
    selected: list[dict[str, Any]] = []
    for endpoint in sorted(by_endpoint):
        endpoint_selected = choose_endpoint(by_endpoint[endpoint])
        if len(endpoint_selected) != 3:
            raise RuntimeError(f"S1 endpoint selection drift: {endpoint}")
        selected.extend(endpoint_selected)
    if len(selected) != 84 or len({tuple(record["identity"]) for record in selected}) != 84:
        raise RuntimeError("S1 selected identity cardinality drift")
    if {tuple(record["endpoint"]) for record in selected} != set(by_endpoint):
        raise RuntimeError("S1 endpoint coverage drift")
    sample = {
        "protocol": "Q10-PF6-S1",
        "status": "SAMPLE_SELECTED_NO_REPLAY",
        "population": {
            "pf5_audited_groups": len(all_items),
            "pf5_oversize_groups": 1457,
            "excluded_pf6_slice": [list(SLICE_ID)],
            "eligible_selection_pool": len(records),
            "selected_groups": len(selected),
        },
        "eligible_groups": sorted(records, key=lambda record: tuple(record["identity"])),
        "selected_groups": sorted(selected, key=lambda record: tuple(record["identity"])),
    }
    parent = {
        "pf5_audit_results_sha256": digest(results_path),
        "pf5_audit_execution_sha256": digest(AUDIT / "execution.json"),
        "pf6_plan_sha256": digest(PF6 / "PLAN.md"),
        "pf6_contract_sha256": digest(PF6 / "CONTRACT.json"),
        "pf6_runner_sha256": digest(PF6 / "scripts/run_q10_pf6.py"),
        "pf6_runtime_helper_sha256": digest(PF5 / "scripts/run_q10_pf5.py"),
    }
    return sample, parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "qualification")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sample, parent = build_manifest()
    sample_path = output / "sample.json"
    sample_path.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
    preexecution = {
        "protocol": "Q10-PF6-S1",
        "status": "PREEXECUTION_SEALED_NO_REPLAY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_hashes": parent,
        "s1_plan_sha256": digest(ROOT / "PLAN.md"),
        "s1_contract_sha256": digest(ROOT / "CONTRACT.json"),
        "sampler_sha256": digest(Path(__file__).resolve()),
        "sample_sha256": digest(sample_path),
        "eligible_group_identities": [record["identity"] for record in sample["eligible_groups"]],
        "selected_group_identities": [record["identity"] for record in sample["selected_groups"]],
        "configuration": {
            "exploit_width": 24,
            "explore_width": 8,
            "beam_width": 32,
            "maximum_rounds": 16,
            "max_nodes_per_group": 32768,
            "candidate_replay": "exact_learner_order_sequential_binary32",
            "stable_hash": "sha256(source_event|set_index|group_index)",
        },
        "source_manifest": {
            "pf5_audit_results": str(AUDIT / "results.json"),
            "pf6_runner": str(PF6 / "scripts/run_q10_pf6.py"),
        },
        "scientific_bundle_count": 0,
        "behavioral_probe": False,
        "canonical_state_updated": False,
        "dh08b_authorized": False,
    }
    (output / "PREEXECUTION.json").write_text(json.dumps(preexecution, indent=2) + "\n", encoding="utf-8")
    print(f"Q10-PF6-S1 sample sealed: pool={len(sample['eligible_groups'])} selected={len(sample['selected_groups'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
