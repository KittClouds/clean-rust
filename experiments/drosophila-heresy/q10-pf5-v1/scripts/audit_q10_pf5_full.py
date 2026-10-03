"""Audit and conservatively reclassify a completed PF5 full receipt.

This post-run audit does not replay candidates or alter the source receipt. It
only corrects the classification of exact-enumeration groups whose geometry
guard pruning was mistakenly treated as bounded-search exhaustion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def walk_forbidden(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in forbidden:
                raise RuntimeError(f"forbidden field at {location}.{key}")
            walk_forbidden(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            walk_forbidden(nested, forbidden, f"{location}[{index}]")


def audit(source_dir: Path, output_dir: Path) -> None:
    execution_path = source_dir / "execution.json"
    results_path = source_dir / "results.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if execution.get("run_scope") != "full_streaming" or execution.get("completeness", {}).get("complete") is not True:
        raise RuntimeError("source receipt is not a complete streamed PF5 run")
    if len(results.get("endpoint_coverage", [])) != 28:
        raise RuntimeError("source receipt does not contain 28 endpoint coverage records")
    endpoint_results = results.get("endpoint_results", [])
    if len(endpoint_results) != len(results.get("group_inventory", [])):
        raise RuntimeError("source receipt group cardinality mismatch")

    changed = 0
    for record in endpoint_results:
        if (
            record.get("status") == "INCONCLUSIVE_BOUNDED_SEARCH"
            and record.get("coverage_state") == "complete"
            and record.get("replay_plan", {}).get("mode") == "EXACT_ENUMERATION"
            and not record.get("exact_target")
            and not record.get("improved_over_baseline")
        ):
            record["status"] = "BLOCKED_WITHIN_DECLARED_DOMAIN"
            record["classification_audit"] = {
                "previous_status": "INCONCLUSIVE_BOUNDED_SEARCH",
                "reason": "complete exact enumeration; intermediate geometry pruning is not bounded-search exhaustion",
            }
            changed += 1

    forbidden = {
        "accuracy",
        "reward",
        "actions",
        "old_map_margin",
        "reversed_map_margin",
        "behavior",
        "behavioral_inference",
        "scientific_seed_id",
        "repair_applied",
        "repair_applied_to_canonical_model",
        "dh08b_authorized",
    }
    audit_execution = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_RECEIPT_AUDIT_COMPLETE",
        "audit_scope": "classification_only__no_replay",
        "source_execution_sha256": digest(execution_path),
        "source_results_sha256": digest(results_path),
        "source_run_scope": execution["run_scope"],
        "primary_endpoints": len(results["endpoint_coverage"]),
        "groups": len(endpoint_results),
        "reclassified_exact_guard_pruned_groups": changed,
        "status_counts": dict(sorted(Counter(item["status"] for item in endpoint_results).items())),
        "canonical_state_updated": False,
        "behavioral_probe": False,
        "scientific_bundle_count": 0,
        "future_protocol_opened": False,
    }
    audited_results = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_RECEIPT_AUDIT_COMPLETE",
        "source_execution_sha256": audit_execution["source_execution_sha256"],
        "source_results_sha256": audit_execution["source_results_sha256"],
        "endpoint_results": endpoint_results,
        "endpoint_coverage": results["endpoint_coverage"],
        "group_inventory": results["group_inventory"],
    }
    walk_forbidden(audit_execution, forbidden, "execution")
    walk_forbidden(audited_results, forbidden, "results")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "execution.json").write_text(json.dumps(audit_execution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "results.json").write_text(json.dumps(audited_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "Q10-PF5 full receipt audit passed: "
        f"groups={len(endpoint_results)} reclassified={changed} output={output_dir}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    audit(args.source_dir.resolve(), args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
