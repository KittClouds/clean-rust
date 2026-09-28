"""Independent structural audit for a completed Q10-PF6-S1 run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def walk_forbidden(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(str(key).lower() not in forbidden, f"forbidden field {location}.{key}")
            walk_forbidden(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            walk_forbidden(nested, forbidden, f"{location}[{index}]")


def audit(execution_dir: Path) -> dict[str, Any]:
    execution = json.loads((execution_dir / "execution.json").read_text(encoding="utf-8"))
    sample = json.loads((ROOT / "qualification/sample.json").read_text(encoding="utf-8"))
    preexecution = json.loads((ROOT / "qualification/PREEXECUTION.json").read_text(encoding="utf-8"))
    require(execution["protocol"] == "Q10-PF6-S1", "execution protocol drift")
    require(execution["measured_sample"] is True, "execution is not the measured sample")
    require(execution["groups_processed"] == 84, "execution group count drift")
    expected = {tuple(item["identity"]) for item in sample["selected_groups"]}
    observed = {tuple(item["identity"]) for item in execution["results"]}
    require(observed == expected, "execution identities do not match sealed sample")
    require(execution["preexecution_sha256"] == digest(ROOT / "qualification/PREEXECUTION.json"), "preexecution hash drift")
    require(execution["sample_sha256"] == digest(ROOT / "qualification/sample.json"), "sample hash drift")
    require(execution["pf6_helper_sha256"] == preexecution["parent_hashes"]["pf6_runner_sha256"], "helper hash drift")
    counts: dict[str, int] = {}
    forbidden = {
        "accuracy", "reward", "actions", "old_map_margin", "reversed_map_margin",
        "behavior", "behavioral_inference", "scientific_seed_id", "repair_applied",
        "repair_applied_to_canonical_model", "dh08b_authorized",
    }
    for result in execution["results"]:
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1
        require(len(result["trajectory"]) == 17, f"trajectory length drift: {result['identity']}")
        require([point["round"] for point in result["trajectory"]] == list(range(17)), "round trajectory drift")
        for point in result["trajectory"]:
            require("best_search_state" in point, "missing per-round best search state")
            require("best_final_gate_valid_state" in point, "missing per-round best valid state")
        require(result["final_audit"], "missing independent final audit")
        require(result["pf6_helper_sha256"] == execution["pf6_helper_sha256"], "group helper hash drift")
        walk_forbidden(result, forbidden, f"group.{result['identity']}")
    require(counts == execution["status_counts"], "aggregate status count drift")
    receipt = {"status": "Q10_PF6_S1_STRUCTURAL_AUDIT_COMPLETE", "groups": 84, "status_counts": counts}
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-dir", type=Path, default=ROOT / "qualification/execution")
    args = parser.parse_args()
    print(json.dumps(audit(args.execution_dir.resolve()), indent=2))
