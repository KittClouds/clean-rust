"""Run Q10-RH1-Q1 real-learner canonical visitation-order qualification."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF5_ROOT = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
CQ_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-cq1-v1/scripts"
sys.path.insert(0, str(CQ_ROOT))
sys.path.insert(0, str(PF5_ROOT / "scripts"))
import common_runtime as CQ  # noqa: E402
import run_q10_pf5 as PF5  # noqa: E402


OUT_ROOT = ROOT / "qualification"


def tie_hash(mapping: dict[int, int]) -> str:
    return hashlib.sha256(b"rh1-tie-v1\0" + CQ.canonical_bytes(mapping)).hexdigest().upper()


def verify_contract() -> dict[str, str]:
    contract = CQ.load_json(ROOT / "CONTRACT.json")
    preexecution = CQ.load_json(ROOT / "PREEXECUTION.json")
    CQ.require(preexecution["plan_sha256"] == CQ.digest(ROOT / "PLAN.md"), "Q1 plan hash drift")
    CQ.require(preexecution["contract_sha256"] == CQ.digest(ROOT / "CONTRACT.json"), "Q1 contract hash drift")
    bindings: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        CQ.require(path.is_file(), f"missing Q1 parent: {binding['label']}")
        actual = CQ.digest(path)
        CQ.require(actual == binding["sha256"].upper(), f"Q1 parent drift: {binding['label']}")
        bindings[binding["label"]] = actual
    return bindings


def commit_actual(state: Any, mapping: dict[int, int]) -> dict[str, Any]:
    weight_bits = list(state.baseline_weight_bits)
    for coordinate, choice in CQ.canonical_state(mapping):
        raw = PF5.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        CQ.require(raw is not None, f"Q1 illegal prefix: {state.key} {coordinate} {choice}")
        weight_bits[coordinate] = raw
    committed_bits = tuple(weight_bits)
    weights = tuple(PF5.from_bits(raw) for raw in committed_bits)
    readout_bits = PF5.readout_bits(state.rows, weights)
    geometry = PF5.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {
        "weight_bits": committed_bits,
        "readout_bits": readout_bits,
        "geometry": geometry,
    }


def choose_mapping(state: Any, coordinates: list[int]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for position, coordinate in enumerate(coordinates):
        legal = [
            choice for choice in PF5.CHOICES
            if choice != 0 and PF5.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice) is not None
        ]
        CQ.require(legal, f"Q1 fixture coordinate has no nonzero legal prefix: {state.key} {coordinate}")
        mapping[coordinate] = legal[position % len(legal)]
    return mapping


def run() -> dict[str, Any]:
    bindings = verify_contract()
    groups = [group for group in CQ.load_groups() if group["coordinates_total"] >= 32]
    groups.sort(key=lambda group: tuple(group["identity"]))
    selected = groups[:8]
    CQ.require(len(selected) == 8, "Q1 sample cardinality drift")
    lineage = PF5.load_lineage(PF5_ROOT)
    states = PF5.load_endpoint_states(lineage, selected_keys={(g["endpoint"], g["set_index"]) for g in selected})
    state_by_key = {state.key: state for state in states}
    records: list[dict[str, Any]] = []
    for group in selected:
        state = state_by_key[(group["endpoint"], group["set_index"])]
        coordinates = group["coordinates"][:3]
        mapping = choose_mapping(state, coordinates)
        order_a = coordinates[:]
        order_b = list(reversed(coordinates))
        mapping_a = {coordinate: mapping[coordinate] for coordinate in order_a}
        mapping_b = {coordinate: mapping[coordinate] for coordinate in order_b}
        result_a = commit_actual(state, mapping_a)
        result_b = commit_actual(state, mapping_b)
        checks = {
            "canonical_state_equal": CQ.canonical_state(mapping_a) == CQ.canonical_state(mapping_b),
            "canonical_bytes_equal": CQ.canonical_bytes(mapping_a) == CQ.canonical_bytes(mapping_b),
            "state_identity_equal": CQ.state_identity(mapping_a) == CQ.state_identity(mapping_b),
            "tie_hash_equal": tie_hash(mapping_a) == tie_hash(mapping_b),
            "committed_weight_bytes_equal": result_a["weight_bits"] == result_b["weight_bits"],
            "sequential_f32_readout_equal": result_a["readout_bits"] == result_b["readout_bits"],
            "geometry_metrics_equal": result_a["geometry"] == result_b["geometry"],
        }
        CQ.require(all(checks.values()), f"Q1 real canonical invariant failed: {group['identity']}")
        records.append({
            "identity": group["identity"],
            "coordinates": coordinates,
            "mapping": sorted(mapping.items()),
            "order_a": order_a,
            "order_b": order_b,
            "checks": checks,
            "state_identity": CQ.state_identity(mapping_a),
            "tie_hash": tie_hash(mapping_a),
        })
    summary = {
        "protocol": "Q10-PF6-RH1-Q1",
        "status": "Q1_REAL_LEARNER_CANONICAL_EQUIVALENCE_COMPLETE",
        "parent_bindings_verified": bindings,
        "groups_tested": len(records),
        "all_checks_passed": all(all(record["checks"].values()) for record in records),
        "records": records,
        "scope": {
            "measured_factorial_started": False,
            "scientific_seed_bundles": 0,
            "behavioral_probe": False,
            "dh08b_authorized": False,
        },
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (OUT_ROOT / "RESULT.md").write_text(
        "\n".join([
            "# Q10-RH1-Q1 result",
            "",
            "Real-learner canonical visitation-order equivalence qualification.",
            "",
            f"Status: `{summary['status']}`.",
            f"Groups tested: {len(records)}.",
            "All canonical identity, tie hash, committed f32 weight bytes, sequential-f32 readout, and geometry checks passed.",
            "No RH1 factorial, scientific seed, behavioral, or DH08B work ran.",
        ]) + "\n",
        encoding="utf-8",
    )
    status = {
        "protocol": "Q10-PF6-RH1-Q1",
        "status": summary["status"],
        "summary_sha256": CQ.digest(OUT_ROOT / "SUMMARY.json"),
        "groups_tested": len(records),
        "all_checks_passed": summary["all_checks_passed"],
        "measured_factorial_started": False,
        "scientific_seed_bundles": 0,
        "behavioral_probe": False,
        "dh08b_authorized": False,
    }
    (OUT_ROOT / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
