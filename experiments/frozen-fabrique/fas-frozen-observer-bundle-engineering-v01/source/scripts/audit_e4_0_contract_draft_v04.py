from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
CONTRACT = PLANS / "E4-0-CONTRACT-DRAFT-v04.json"
PREDECESSOR = PLANS / "E4-0-CONTRACT-DRAFT-v03.json"
SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v10.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v02.md"
PLANNER_DIR = ROOT / "source" / "e4-support-plan-v10"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v04-independent-audit.json"
REPO = ROOT.parents[1]
EXPECTED_PREDECESSOR_SHA256 = "3c55e5778d3dd104c60a57286563d67d6a3906d2e2f7d217de39f409229e5bb4"
EXPECTED_SUPPORT_SHA256 = "808e6c167f877a9cbb926c4c989bc06dc74136d94fb9f3c02693ab99c72e3dfb"


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


def fail(message: str) -> None:
    raise RuntimeError(message)


def resolve(value: str) -> Path:
    path = Path(value)
    local = ROOT / path
    if local.is_file():
        return local
    external = REPO / path
    if external.is_file():
        return external
    fail(f"bound path is absent: {value}")


def normalize_population(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["support"]["symbolic_plan"] = "<rebound-support-plan>"
    return result


def main() -> int:
    contract = load(CONTRACT)
    predecessor = load(PREDECESSOR)
    plan = load(SUPPORT)
    errors: list[str] = []
    predecessor_hash, _ = sha256(PREDECESSOR)
    support_hash, support_bytes = sha256(SUPPORT)
    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    if predecessor_hash != EXPECTED_PREDECESSOR_SHA256:
        errors.append("v03 predecessor hash mismatch")
    if support_hash != EXPECTED_SUPPORT_SHA256:
        errors.append("v10 support plan hash mismatch")
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V04":
        errors.append("wrong contract identity")
    if contract.get("status") != "DRAFT_NOT_SEALED_NOT_AUTHORIZED_SOURCE_HASHES_PENDING":
        errors.append("draft status was changed")
    if contract.get("supersedes", {}).get("sha256") != predecessor_hash:
        errors.append("supersession does not bind v03")

    design_inputs = contract.get("design_inputs", {})
    expected_inputs = {
        "symbolic_support_plan": (SUPPORT, support_hash, support_bytes),
        "implementation_source_map_v02": (SOURCE_MAP, source_map_hash, source_map_bytes),
    }
    for name, (path, digest, size) in expected_inputs.items():
        if design_inputs.get(f"{name}_path") != str(path.relative_to(ROOT)).replace("\\", "/"):
            errors.append(f"{name} path mismatch")
        if design_inputs.get(f"{name}_sha256") != digest:
            errors.append(f"{name} SHA-256 mismatch")
        if design_inputs.get(f"{name}_bytes") != size:
            errors.append(f"{name} byte count mismatch")
    for name in ("e4_0_design_v03", "template_manifest", "template_text_audit", "template_structural_audit"):
        path = resolve(design_inputs[f"{name}_path"])
        if sha256(path)[0] != design_inputs[f"{name}_sha256"]:
            errors.append(f"design input hash mismatch: {name}")

    immutable_keys = (
        "predecessors", "representation_abi", "parity", "fresh_qualification", "truth_access",
        "resources", "phase_gates", "stop_rule", "E4_A_dependency", "authorization", "execution_identity",
    )
    for key in immutable_keys:
        if contract.get(key) != predecessor.get(key):
            errors.append(f"v04 altered frozen predecessor section: {key}")
    if normalize_population(contract["population"]) != normalize_population(predecessor["population"]):
        errors.append("v04 changed population semantics outside the support receipt binding")

    support_binding = contract["population"]["support"]["symbolic_plan"]
    expected_support_fields = {
        "path": str(SUPPORT.relative_to(ROOT)).replace("\\", "/"),
        "sha256": support_hash,
        "status": plan["status"],
        "selected_whole_quartet_prefix": plan["selected_whole_quartet_prefix"],
        "previous_prefix_minimum_class_count": plan["minimum_class_count_at_previous_prefix"],
        "previous_prefix_meets_target": plan["immediately_previous_whole_quartet_prefix_meets_target"],
        "primary_rows": plan["rows_in_primary_seen_and_lexical_population"],
        "heldout_template_rows": plan["rows_in_heldout_template_population"],
        "joint_lexical_rows_subset": plan["heldout_template_joint_lexical_rows_subset"],
        "per_class_counts": plan["minimum_support_by_endpoint_and_stratum"],
        "e1_unique_quartet_ids": plan["e1_unique_quartet_ids"],
        "e1_unique_row_ids": plan["e1_unique_row_ids"],
        "e1_unique_rendered_input_hashes": plan["e1_unique_rendered_input_hashes"],
        "all_three_collision_keys_checked": True,
        "model_free": True,
        "population_rows_written": False,
    }
    for key, expected in expected_support_fields.items():
        if support_binding.get(key) != expected:
            errors.append(f"support-plan binding mismatch: {key}")
    if min(
        count
        for endpoint in plan["minimum_support_by_endpoint_and_stratum"].values()
        for count in (sum(endpoint, []) if endpoint and isinstance(endpoint[0], list) else endpoint)
    ) < 250:
        errors.append("selected prefix misses at least 250 examples in a required class")
    if plan["minimum_class_count_at_previous_prefix"] >= 250:
        errors.append("previous prefix does not establish minimum-prefix selection")
    if plan["selected_whole_quartet_prefix"] != 18_667:
        errors.append("selected prefix changed unexpectedly")
    if any(plan[key] for key in ("population_rows_written", "tokenizer_contacted", "model_contacted", "labels_opened")):
        errors.append("symbolic planner indicates execution or truth access")
    for key in ("e1_quartet_ids_checked", "e1_row_ids_checked", "e4_paired_quartet_and_row_ids_checked"):
        if plan.get(key) is not True:
            errors.append(f"planner omitted required collision key check: {key}")

    row_count = int(plan["unique_feature_rows_all_materialized_strata"])
    expected_resources = {
        "feature_rows": row_count,
        "feature_cache_bytes": row_count * 8_192,
        "feature_cache_atomic_staging_bytes": row_count * 8_192,
        "row_level_artifact_max_bytes": row_count * (1_024 + 1_024 + 512),
    }
    expected_resources["projected_peak_bytes_before_free_space_reserve"] = (
        2 * expected_resources["feature_cache_bytes"]
        + expected_resources["row_level_artifact_max_bytes"]
        + 2 * 512 * 1024 * 1024
    )
    for key, expected in expected_resources.items():
        if contract["resources"].get(key) != expected:
            errors.append(f"resource arithmetic changed or is invalid: {key}")
    if contract["resources"].get("total_gpu_memory_claimed") is not False:
        errors.append("GPU claim scope changed")

    planner = contract["implementation_sources_not_yet_bound"]["e4_support_planner"]
    source_path = PLANNER_DIR / "src" / "main.rs"
    manifest_path = PLANNER_DIR / "Cargo.toml"
    lock_path = PLANNER_DIR / "Cargo.lock"
    if planner.get("sha256") != sha256(source_path)[0] or planner.get("bytes") != source_path.stat().st_size:
        errors.append("planner source identity mismatch")
    if planner.get("cargo_manifest_sha256") != sha256(manifest_path)[0]:
        errors.append("planner Cargo.toml identity mismatch")
    if planner.get("cargo_lock_sha256") != sha256(lock_path)[0]:
        errors.append("planner Cargo.lock identity mismatch")

    pending_names = ("e4_population_generator", "e4_online_feature_and_parity_runner", "e4_fresh_scorer", "e4_independent_auditor")
    pending = contract["implementation_sources_not_yet_bound"]
    if any(pending.get(name) is not None for name in pending_names):
        errors.append("a runtime source is unexpectedly claimed as bound")
    if errors:
        fail("; ".join(errors))

    auditor_hash, auditor_bytes = sha256(Path(__file__).resolve())
    result = {
        "receipt_id": "FAS_E4_0_CONTRACT_DRAFT_V04_INDEPENDENT_AUDIT",
        "status": "DRAFT_AUDIT_PASS_WITH_IMPLEMENTATION_SOURCE_BLOCKERS",
        "contract_path": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": sha256(CONTRACT)[0],
        "predecessor_contract_sha256": predecessor_hash,
        "support_plan_sha256": support_hash,
        "support_plan_source_sha256": sha256(source_path)[0],
        "implementation_source_map_sha256": source_map_hash,
        "implementation_source_map_bytes": source_map_bytes,
        "selected_quartets": plan["selected_whole_quartet_prefix"],
        "minimum_selected_class_support": min(
            count for endpoint in plan["minimum_support_by_endpoint_and_stratum"].values()
            for count in (sum(endpoint, []) if endpoint and isinstance(endpoint[0], list) else endpoint)
        ),
        "previous_prefix_minimum_support": plan["minimum_class_count_at_previous_prefix"],
        "unique_feature_rows": row_count,
        "projected_peak_bytes_before_free_space_reserve": expected_resources["projected_peak_bytes_before_free_space_reserve"],
        "execution_sources_pending": list(pending_names),
        "auditor_source_path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "auditor_source_sha256": auditor_hash,
        "auditor_source_bytes": auditor_bytes,
        "authorizations_open": False,
        "population_rows_written": False,
        "tokenizer_contacted": False,
        "model_contacted": False,
        "labels_opened": False,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
