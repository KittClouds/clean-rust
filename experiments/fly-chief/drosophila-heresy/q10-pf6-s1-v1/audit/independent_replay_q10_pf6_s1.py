"""Replay S1 retained prefixes from committed bytes and compare receipts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF6_ROOT = REPO / "experiments/drosophila-heresy/q10-pf6-v1"
sys.path.insert(0, str(PF6_ROOT / "scripts"))
import run_q10_pf6 as PF6  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def audit(execution_dir: Path) -> dict[str, Any]:
    execution = json.loads((execution_dir / "execution.json").read_text(encoding="utf-8"))
    sample = json.loads((ROOT / "qualification/sample.json").read_text(encoding="utf-8"))
    lineage = PF6.PF5.load_lineage(PF6.PF5_ROOT)
    states = PF6.PF5.load_endpoint_states(lineage)
    state_by_key = {state.key: state for state in states}
    topology = PF6.PF5.augment_missing_prefix_topology(
        PF6.PF5.load_topology(lineage), states, lineage
    )
    groups_by_key: dict[tuple[str, int], dict[int, Any]] = {}
    for state in states:
        groups_by_key[state.key] = {
            group.group_index: group
            for group in PF6.PF5.build_raw_groups(state, topology, lineage)
        }
    expected = {tuple(record["identity"]): record for record in sample["selected_groups"]}
    require(len(execution["results"]) == 84, "measured result count drift")
    checked = 0
    for result in execution["results"]:
        identity = tuple(result["identity"])
        require(identity in expected, f"unexpected identity {identity}")
        event, set_index, group_index = identity
        key = (event, int(set_index))
        state = state_by_key[key]
        group = groups_by_key[key][int(group_index)]
        ranked = PF6.rank_coordinates(state, group)
        ordered = PF6.reorder_group(group, ranked)
        retained = result["best_valid"] or result["best_search"]
        prefix = tuple(int(value) for value in retained["prefix"])
        candidate = PF6.PF5._candidate(state, ordered, prefix)
        require(candidate.readout_bits == PF6.PF5.readout_bits(state.rows, tuple(PF6.PF5.from_bits(raw) for raw in candidate.weight_bits)), f"replay readout mismatch {identity}")
        require(candidate.objective.mismatch_rows == retained["mismatch_count"], f"mismatch receipt drift {identity}")
        require(candidate.objective.total_ulp_distance == retained["total_ulp_distance"], f"ULP receipt drift {identity}")
        require(abs(candidate.objective.residual_l2 - retained["residual_l2"]) <= 1.0e-15, f"L2 receipt drift {identity}")
        require(candidate.objective.maximum_absolute_residual == retained["max_residual"], f"max residual drift {identity}")
        checked += 1
    return {
        "status": "Q10_PF6_S1_INDEPENDENT_REPLAY_AUDIT_COMPLETE",
        "groups_checked": checked,
        "execution_sha256": digest(execution_dir / "execution.json"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-dir", type=Path, default=ROOT / "qualification/execution")
    args = parser.parse_args()
    print(json.dumps(audit(args.execution_dir.resolve()), indent=2))
