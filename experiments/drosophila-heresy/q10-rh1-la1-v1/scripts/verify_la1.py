"""Read-only final verification for a complete LA1 qualification."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
import derive_la1 as DERIVE  # noqa: E402
import run_la1 as LA1  # noqa: E402


def verify(execution_path: Path, derived_dir: Path) -> dict[str, object]:
    context, receipts = DERIVE.load_and_validate(execution_path.resolve())
    status_path = derived_dir / "STATUS.json"
    summary_path = derived_dir / "SUMMARY.json"
    result_path = derived_dir / "RESULT.md"
    LA1.require(status_path.is_file(), "missing LA1 STATUS.json")
    LA1.require(summary_path.is_file(), "missing LA1 SUMMARY.json")
    LA1.require(result_path.is_file(), "missing LA1 RESULT.md")
    status = LA1.load_json(status_path)
    summary = LA1.load_json(summary_path)
    LA1.require(status.get("status") == "ENGINEERING_LA1_COMPLETE_NO_SCIENTIFIC_PROMOTION", "LA1 status is not complete")
    LA1.require(status.get("raw_execution_sha256") == LA1.digest(execution_path.resolve()), "LA1 raw execution hash mismatch")
    LA1.require(status.get("derived_summary_sha256") == LA1.digest(summary_path), "LA1 derived summary hash mismatch")
    LA1.require(status.get("derived_result_sha256") == LA1.digest(result_path), "LA1 derived result hash mismatch")
    LA1.require(summary.get("selected_group_count") == len(receipts), "LA1 summary count mismatch")
    LA1.require(summary.get("derived_classification_policy") == DERIVE.CLASSIFICATION_POLICY, "LA1 classification policy drift")
    LA1.require(summary.get("derived_classification_policy_sha256") == LA1.json_digest(DERIVE.CLASSIFICATION_POLICY), "LA1 classification policy hash mismatch")
    counts = summary.get("mechanism_class_counts")
    LA1.require(isinstance(counts, dict), "LA1 classification counts missing")
    LA1.require(set(counts) == set(DERIVE.MECHANISM_CLASSES), "LA1 classification count labels drift")
    LA1.require(sum(counts.values()) == len(receipts), "LA1 classification count total mismatch")
    LA1.require(len(summary.get("groups", [])) == len(receipts), "LA1 summary group cardinality mismatch")
    for group in summary["groups"]:
        classification = group.get("mechanism_classification", {})
        LA1.require(classification.get("mechanism_class") in DERIVE.MECHANISM_CLASSES, f"invalid mechanism class: {group.get('identity')}")
        LA1.require(classification.get("descriptive_only") is True, f"mechanism class not descriptive-only: {group.get('identity')}")
        LA1.require(classification.get("row_interaction", {}).get("sha256") == group.get("row_interaction_sha256"), f"interaction hash not preserved: {group.get('identity')}")
        LA1.require(group.get("morphology", {}).get("descriptive_only") is True, f"morphology scope drift: {group.get('identity')}")
    LA1.require(status.get("classification_policy_sha256") == summary["derived_classification_policy_sha256"], "LA1 status classification policy hash mismatch")
    LA1.require(status.get("mechanism_class_counts") == counts, "LA1 status classification counts mismatch")
    LA1.require(status.get("mechanism_class_descriptive_only") is True, "LA1 mechanism class scope drift")
    LA1.require(summary.get("scope", {}).get("scientific_promotion") is False, "LA1 scientific promotion flag drift")
    LA1.require(summary.get("scope", {}).get("behavioral_probe") is False, "LA1 behavioral probe flag drift")
    result = {
        "status": status["status"],
        "selected_group_count": len(receipts),
        "actual_endpoint_geometry_hard_gate_pass": bool(status["actual_endpoint_geometry_hard_gate_pass"]),
        "counterfactual_geometry_failures_non_blocking": bool(status["counterfactual_geometry_failures_non_blocking"]),
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="verify a complete Q10-RH1-LA1 qualification")
    parser.add_argument("--execution", type=Path, default=ROOT / "qualification" / "execution" / "execution.json")
    parser.add_argument("--derived-dir", type=Path, default=ROOT / "qualification" / "derived")
    args = parser.parse_args()
    try:
        verify(args.execution, args.derived_dir)
    except (LA1.LA1Error, OSError, KeyError, TypeError, ValueError) as error:
        print(f"Q10-RH1-LA1 verification failed closed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
