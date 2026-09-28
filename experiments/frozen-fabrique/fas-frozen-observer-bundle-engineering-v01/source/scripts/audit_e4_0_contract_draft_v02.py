from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
CONTRACT = PLANS / "E4-0-CONTRACT-DRAFT-v02.json"
SUPPORT_PLAN = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v09.json"
REPO = ROOT.parents[1]


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_bound_path(value: str) -> Path:
    path = Path(value)
    local_candidate = ROOT / path
    if local_candidate.is_file():
        return local_candidate
    repo_candidate = REPO / path
    if repo_candidate.is_file():
        return repo_candidate
    fail(f"bound input is missing: {value}")


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    contract = load(CONTRACT)
    plan = load(SUPPORT_PLAN)
    errors: list[str] = []

    bound_inputs = contract["design_inputs"]
    for name in (
        "e4_0_design_v03",
        "template_manifest",
        "template_text_audit",
        "template_structural_audit",
        "symbolic_support_plan",
    ):
        path = resolve_bound_path(bound_inputs[f"{name}_path"])
        observed_hash, observed_bytes = sha256(path)
        if observed_hash != bound_inputs[f"{name}_sha256"]:
            errors.append(f"{name}: SHA-256 mismatch")
        if name == "symbolic_support_plan" and observed_bytes != bound_inputs[f"{name}_bytes"]:
            errors.append(f"{name}: byte count mismatch")

    if contract["status"] != "DRAFT_NOT_SEALED_NOT_AUTHORIZED_SOURCE_HASHES_PENDING":
        errors.append("contract status is not the frozen draft status")
    if contract["contract_id"] != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V02":
        errors.append("wrong contract identity")
    for section in (contract["authorization"], contract["execution_identity"]):
        for key, value in section.items():
            if key.endswith("authorized") and value is not False:
                errors.append(f"authorization unexpectedly true: {key}")

    support = plan["minimum_support_by_endpoint_and_stratum"]
    all_counts = (
        support["context_identity"]
        + support["entity_identity"]
        + support["relation"]
        + support["observed_state"]
        + [count for classes in support["exact_target_by_stratum"] for count in classes]
    )
    if min(all_counts) < 250:
        errors.append("selected support prefix misses a 250/class endpoint gate")
    if plan["immediately_previous_whole_quartet_prefix_meets_target"] is not False:
        errors.append("immediately previous prefix unexpectedly meets target")
    if plan["minimum_class_count_at_previous_prefix"] >= 250:
        errors.append("previous prefix minimum does not prove minimality")
    if plan["population_rows_written"] or plan["model_contacted"] or plan["tokenizer_contacted"] or plan["labels_opened"]:
        errors.append("support planning receipt crosses a prohibited phase boundary")

    rows = int(plan["unique_feature_rows_all_materialized_strata"])
    feature_bytes = rows * 8_192
    row_caps = rows * (1_024 + 1_024 + 512)
    expected_peak = 2 * feature_bytes + row_caps + 2 * (512 * 1024 * 1024)
    resources = contract["resources"]
    arithmetic = {
        "feature_rows": rows,
        "feature_cache_bytes": feature_bytes,
        "feature_cache_atomic_staging_bytes": feature_bytes,
        "row_level_artifact_max_bytes": row_caps,
        "projected_peak_bytes_before_free_space_reserve": expected_peak,
    }
    for key, expected in arithmetic.items():
        if resources.get(key) != expected:
            errors.append(f"resource arithmetic mismatch: {key}")
    if expected_peak != 3_902_763_008:
        errors.append("resource projection differs from the reviewed byte arithmetic")

    source_ids = contract["implementation_sources_not_yet_bound"]
    required = (
        "e4_population_generator",
        "e4_online_feature_and_parity_runner",
        "e4_fresh_scorer",
        "e4_independent_auditor",
    )
    missing_sources = [key for key in required if source_ids.get(key) is not None]
    if missing_sources:
        errors.append("execution sources were filled without an independent review: " + ",".join(missing_sources))

    if errors:
        fail("; ".join(errors))
    result = {
        "receipt_id": "FAS_E4_0_CONTRACT_DRAFT_V02_INDEPENDENT_AUDIT",
        "status": "DRAFT_AUDIT_PASS_WITH_EXECUTION_SOURCE_BLOCKERS",
        "contract_path": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": sha256(CONTRACT)[0],
        "support_plan_sha256": sha256(SUPPORT_PLAN)[0],
        "auditor_source_path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "auditor_source_sha256": sha256(Path(__file__).resolve())[0],
        "auditor_source_bytes": sha256(Path(__file__).resolve())[1],
        "selected_whole_quartet_prefix": plan["selected_whole_quartet_prefix"],
        "minimum_selected_class_support": min(all_counts),
        "previous_prefix_minimum_support": plan["minimum_class_count_at_previous_prefix"],
        "resource_arithmetic": arithmetic,
        "execution_sources_pending": list(required),
        "authorizations_open": False,
        "population_rows_written": False,
        "tokenizer_contacted": False,
        "model_contacted": False,
        "labels_opened": False,
    }
    output = PLANS / "E4-0-CONTRACT-DRAFT-v02-independent-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
