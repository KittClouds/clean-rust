"""Independent validator for the sealed v0.8N Road-B fallback branch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt_path = args.branch / "road-b-branch-receipt.json"
    selected_path = args.branch / "selected-matched-neutral.jsonl"
    failures: list[str] = []
    if not receipt_path.exists():
        failures.append("missing_branch_receipt")
    if not selected_path.exists():
        failures.append("missing_selected_control")
    if failures:
        seal = {"status": "V08N_ROAD_B_INDEPENDENT_SEAL_FAIL", "failures": failures}
        write_json(args.output, seal)
        print(json.dumps(seal, indent=2))
        return 1

    receipt = read_json(receipt_path)
    selected_count = sum(1 for line in selected_path.read_text(encoding="utf-8").splitlines() if line.strip())
    gates = receipt.get("gates", {})
    arms = receipt.get("arms", {})
    checks = {
        "status_pass": receipt.get("status") == "V08N_ROAD_B_MATCHED_CONTROL_PASS",
        "selected_count": selected_count == 5_000 and receipt.get("selected_count") == 5_000,
        "selected_hash": receipt.get("selected_control_manifest", {}).get("sha256") == sha256_file(selected_path),
        "mean_gate": gates.get("mean_relative_radius_error") is True,
        "p95_gate": gates.get("p95_absolute_radius_error") is True,
        "family_gate": gates.get("every_family_mean_relative_radius_error") is True,
        "only_radius_rule": receipt.get("selection_rule") == "absolute sham-radius mismatch only; deterministic SHA256 tie-break",
        "no_direction": receipt.get("direction_or_cosine_used") is False,
        "no_road_a": receipt.get("road_a_used") is False,
        "no_history": receipt.get("historical_outcomes_used") is False,
        "no_eval_data": receipt.get("evaluation_data_used") is False,
        "no_training": receipt.get("model_head_training") is False,
        "no_eval_inference": receipt.get("evaluation_inference") is False,
        "no_protected": receipt.get("protected_evaluation_bodies_opened") is False,
        "no_phoenix": receipt.get("phoenix_access") is False,
        "three_arms": set(arms) == {"B-DUP", "B-MATCHED", "B-SHAM"},
    }
    arm_payloads: dict[str, Any] = {}
    for arm, metadata in arms.items():
        path = Path(metadata["path"])
        checks[f"{arm}_exists"] = path.exists()
        if path.exists():
            checks[f"{arm}_hash"] = metadata.get("sha256") == sha256_file(path)
            arm_payloads[arm] = read_json(path)
            checks[f"{arm}_aux_count"] = len(arm_payloads[arm].get("auxiliary_events", [])) == 5_000
            checks[f"{arm}_primary_count"] = len(arm_payloads[arm].get("primary_events", [])) == 10_000
    if len(arm_payloads) == 3:
        primary_sets = {json.dumps(payload["primary_events"], sort_keys=True, separators=(",", ":")) for payload in arm_payloads.values()}
        common_sets = {json.dumps({key: value for key, value in payload.items() if key not in {"arm", "auxiliary_events"}}, sort_keys=True, separators=(",", ":")) for payload in arm_payloads.values()}
        checks["primary_bank_equal"] = len(primary_sets) == 1
        checks["common_contract_equal"] = len(common_sets) == 1
        checks["arm_roles_distinct"] = {payload["auxiliary_events"][0]["auxiliary_source_role"] for payload in arm_payloads.values()} == {"anchor_duplicate", "matched_neutral", "certified_sham"}
    else:
        checks["primary_bank_equal"] = False
        checks["common_contract_equal"] = False
        checks["arm_roles_distinct"] = False
    failures.extend(name for name, passed in checks.items() if not passed)
    seal = {
        "status": "V08N_ROAD_B_INDEPENDENT_SEAL_PASS" if not failures else "V08N_ROAD_B_INDEPENDENT_SEAL_FAIL",
        "branch_receipt_sha256": sha256_file(receipt_path),
        "selected_control_sha256": sha256_file(selected_path),
        "checks": checks,
        "failures": failures,
        "training_only": True,
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "independent_local_fallback_seal": True,
        "luna_review": {"status": "LUNA_NO_ARTIFACT", "interpretation": "No Luna artifact was materialized; this local independent seal is authoritative."},
    }
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite Road-B independent seal: {args.output}")
    write_json(args.output, seal)
    print(json.dumps(seal, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
