"""Fail-closed preflight for Q10-PF6-S1 sample qualification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF5 = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
PF6 = REPO / "experiments/drosophila-heresy/q10-pf6-v1"
AUDIT = PF5 / "qualification/full-run-v3-audit"
SLICE_ID = ["seed9731-L-tau16.json", 0, 6]


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


def main() -> int:
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == "Q10-PF6-S1", "S1 protocol identity drift")
    require(digest(ROOT / "PLAN.md") == contract["plan_sha256"], "S1 PLAN hash drift")
    parent = contract["parent"]
    require(digest(PF5 / "PLAN.md") == parent["pf5_plan_sha256"], "PF5 PLAN hash drift")
    require(digest(PF5 / "CONTRACT.json") == parent["pf5_contract_sha256"], "PF5 CONTRACT hash drift")
    require(digest(AUDIT / "execution.json") == parent["pf5_audit_execution_sha256"], "PF5 audit execution drift")
    require(digest(AUDIT / "results.json") == parent["pf5_audit_results_sha256"], "PF5 audit results drift")
    require(digest(PF6 / "PLAN.md") == parent["pf6_plan_sha256"], "PF6 PLAN hash drift")
    require(digest(PF6 / "CONTRACT.json") == parent["pf6_contract_sha256"], "PF6 CONTRACT hash drift")
    require(digest(PF6 / "scripts/run_q10_pf6.py") == parent["pf6_runner_sha256"], "PF6 runner hash drift")
    require(digest(PF5 / "scripts/run_q10_pf5.py") == parent["pf6_runtime_helper_sha256"], "PF6 runtime helper drift")

    results = json.loads((AUDIT / "results.json").read_text(encoding="utf-8"))
    require(len(results["endpoint_results"]) == 1596, "PF5 group cardinality drift")
    statuses = {}
    for item in results["endpoint_results"]:
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    require(statuses == {
        "BLOCKED_WITHIN_DECLARED_DOMAIN": 37,
        "OVERSIZE_UNTESTED": 1457,
        "PARTIAL_FEASIBILITY_FOUND": 102,
    }, "PF5 status counts drift")

    sample_path = ROOT / "qualification/sample.json"
    preexecution_path = ROOT / "qualification/PREEXECUTION.json"
    require(sample_path.is_file() and preexecution_path.is_file(), "S1 PREEXECUTION is not sealed")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    preexecution = json.loads(preexecution_path.read_text(encoding="utf-8"))
    eligible = sample["eligible_groups"]
    selected = sample["selected_groups"]
    require(len(eligible) == 1456, "S1 eligible selection pool drift")
    require(len(selected) == 84, "S1 selected cardinality drift")
    identities = [tuple(record["identity"]) for record in selected]
    require(len(set(identities)) == 84, "S1 duplicate selected identity")
    by_endpoint: dict[tuple[str, int], int] = {}
    for record in selected:
        endpoint = tuple(record["endpoint"])
        by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
        require(record["identity"] != SLICE_ID, "S1 PF6 slice contamination")
    require(len(by_endpoint) == 28 and set(by_endpoint.values()) == {3}, "S1 endpoint stratification drift")
    eligible_ids = {tuple(record["identity"]) for record in eligible}
    require(set(identities) <= eligible_ids, "S1 selected group outside eligible pool")
    require(preexecution["sample_sha256"] == digest(sample_path), "S1 sample receipt hash drift")
    require(preexecution["s1_plan_sha256"] == digest(ROOT / "PLAN.md"), "S1 plan receipt drift")
    require(preexecution["s1_contract_sha256"] == digest(ROOT / "CONTRACT.json"), "S1 contract receipt drift")
    require(preexecution["sampler_sha256"] == digest(ROOT / "scripts/select_q10_pf6_s1.py"), "S1 sampler receipt drift")
    require(preexecution["selected_group_identities"] == [list(identity) for identity in identities], "S1 PREEXECUTION selection drift")
    require(preexecution["parent_hashes"]["pf6_runner_sha256"] == parent["pf6_runner_sha256"], "S1 runner receipt drift")
    forbidden = {str(item).lower() for item in contract["forbidden_fields"]}
    walk_forbidden(sample, forbidden, "sample")
    print("Q10-PF6-S1 preflight passed: pool=1456 selected=84 endpoints=28")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
