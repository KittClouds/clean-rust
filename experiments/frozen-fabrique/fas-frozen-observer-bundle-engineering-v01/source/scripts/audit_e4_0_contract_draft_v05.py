from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
AUDITS = ROOT / "audits"
CONTRACT = PLANS / "E4-0-CONTRACT-DRAFT-v05.json"
PREDECESSOR = PLANS / "E4-0-CONTRACT-DRAFT-v04.json"
SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v11.json"
PREVIOUS_SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v10.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v03.md"
TEST_RECEIPT = AUDITS / "e4-0-support-plan-v11-source-tests.json"
PLANNER_DIR = ROOT / "source" / "e4-support-plan-v11"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v05-independent-audit.json"
REPO = ROOT.parents[1]
EXPECTED_PREDECESSOR_SHA256 = "e70572102c04bc315bd3564e3f33cd4fd5e2a70097c10f66f864f512f9ddd4ca"
EXPECTED_SUPPORT_SHA256 = "a15bca5d78867ea32905299fabd21f85cf6846a5a02a0c55dd32337e0396847f"
EXPECTED_TEST_RECEIPT_SHA256 = "833c011ff9a9770756f106f390a275949751b9b71d46dbb4efa92f806a82b0c6"


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


def plan_semantics(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    for key in ("receipt_id", "planner_source_path", "planner_source_sha256"):
        result.pop(key, None)
    return result


def main() -> int:
    contract = load(CONTRACT)
    predecessor = load(PREDECESSOR)
    plan = load(SUPPORT)
    old_plan = load(PREVIOUS_SUPPORT)
    tests = load(TEST_RECEIPT)
    errors: list[str] = []
    predecessor_hash, _ = sha256(PREDECESSOR)
    support_hash, support_bytes = sha256(SUPPORT)
    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    test_hash, test_bytes = sha256(TEST_RECEIPT)

    if predecessor_hash != EXPECTED_PREDECESSOR_SHA256:
        errors.append("v04 predecessor hash mismatch")
    if support_hash != EXPECTED_SUPPORT_SHA256:
        errors.append("v11 support plan hash mismatch")
    if test_hash != EXPECTED_TEST_RECEIPT_SHA256:
        errors.append("v11 source validation receipt hash mismatch")
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05":
        errors.append("wrong v05 contract identity")
    if contract.get("status") != "DRAFT_NOT_SEALED_NOT_AUTHORIZED_SOURCE_HASHES_PENDING":
        errors.append("draft status was changed")
    if contract.get("supersedes", {}).get("sha256") != predecessor_hash:
        errors.append("v05 does not bind v04 as its predecessor")

    design = contract.get("design_inputs", {})
    expected_bound = {
        "symbolic_support_plan": (SUPPORT, support_hash, support_bytes),
        "implementation_source_map_v03": (SOURCE_MAP, source_map_hash, source_map_bytes),
        "support_plan_v11_validation_receipt": (TEST_RECEIPT, test_hash, test_bytes),
    }
    for key, (path, digest, size) in expected_bound.items():
        if design.get(f"{key}_path") != str(path.relative_to(ROOT)).replace("\\", "/"):
            errors.append(f"bound path mismatch: {key}")
        if design.get(f"{key}_sha256") != digest or design.get(f"{key}_bytes") != size:
            errors.append(f"bound identity mismatch: {key}")
    for key in ("e4_0_design_v03", "template_manifest", "template_text_audit", "template_structural_audit"):
        path = resolve(design[f"{key}_path"])
        if sha256(path)[0] != design[f"{key}_sha256"]:
            errors.append(f"frozen design input hash mismatch: {key}")

    immutable_sections = (
        "predecessors", "representation_abi", "parity", "fresh_qualification", "truth_access",
        "resources", "phase_gates", "stop_rule", "E4_A_dependency", "authorization", "execution_identity",
    )
    for key in immutable_sections:
        if contract.get(key) != predecessor.get(key):
            errors.append(f"scientific or execution section changed from v04: {key}")
    if normalize_population(contract["population"]) != normalize_population(predecessor["population"]):
        errors.append("population design changed outside the support receipt binding")

    if plan_semantics(plan) != plan_semantics(old_plan):
        errors.append("v11 changed support-plan semantics from corrected v10")
    if plan["planner_source_sha256"] != sha256(PLANNER_DIR / "src" / "main.rs")[0]:
        errors.append("support plan source hash does not match v11 source bytes")
    if tests["source"]["sha256"] != plan["planner_source_sha256"]:
        errors.append("test receipt and support plan bind different sources")
    if tests["support_plan"]["sha256"] != support_hash:
        errors.append("test receipt binds a different support plan")
    if tests["checks"].get("cargo_fmt_check") != "PASS":
        errors.append("format check did not pass")
    if tests["checks"].get("cargo_test_release", {}).get("passed") != 5 or tests["checks"].get("cargo_test_release", {}).get("failed") != 0:
        errors.append("expected 5 passing unit tests and no failures")
    if tests["checks"].get("cargo_clippy_release_deny_warnings") != "PASS":
        errors.append("strict Clippy did not pass")
    if any(tests[key] for key in ("population_rows_written", "tokenizer_contacted", "model_contacted", "cuda_initialized", "labels_opened")):
        errors.append("source validation receipt reports prohibited execution")

    binding = contract["population"]["support"]["symbolic_plan"]
    if binding.get("sha256") != support_hash or binding.get("path") != str(SUPPORT.relative_to(ROOT)).replace("\\", "/"):
        errors.append("population support binding does not point to v11")
    if binding.get("all_three_collision_keys_checked") is not True:
        errors.append("contract does not bind all three collision keys")
    if binding.get("source_validation_receipt_sha256") != test_hash:
        errors.append("support binding omits the source validation receipt")
    if plan["selected_whole_quartet_prefix"] != 18_667 or plan["minimum_class_count_at_previous_prefix"] != 248:
        errors.append("support selection/minimality differs from reviewed result")
    if plan["population_rows_written"] or plan["tokenizer_contacted"] or plan["model_contacted"] or plan["labels_opened"]:
        errors.append("support plan crossed an execution/truth boundary")

    expected_feature_rows = plan["unique_feature_rows_all_materialized_strata"]
    expected_feature_bytes = expected_feature_rows * 8192
    expected_row_bytes = expected_feature_rows * (1024 + 1024 + 512)
    expected_peak = 2 * expected_feature_bytes + expected_row_bytes + 2 * 512 * 1024 * 1024
    resources = contract["resources"]
    for key, value in {
        "feature_rows": expected_feature_rows,
        "feature_cache_bytes": expected_feature_bytes,
        "feature_cache_atomic_staging_bytes": expected_feature_bytes,
        "row_level_artifact_max_bytes": expected_row_bytes,
        "projected_peak_bytes_before_free_space_reserve": expected_peak,
    }.items():
        if resources.get(key) != value:
            errors.append(f"resource arithmetic mismatch: {key}")
    if resources.get("total_gpu_memory_claimed") is not False:
        errors.append("GPU metric scope was broadened")

    planner = contract["implementation_sources_not_yet_bound"]["e4_support_planner"]
    for key, expected in {
        "path": "source/e4-support-plan-v11/src/main.rs",
        "sha256": plan["planner_source_sha256"],
        "bytes": (PLANNER_DIR / "src" / "main.rs").stat().st_size,
        "cargo_manifest_sha256": sha256(PLANNER_DIR / "Cargo.toml")[0],
        "cargo_lock_sha256": sha256(PLANNER_DIR / "Cargo.lock")[0],
        "source_test_receipt_sha256": test_hash,
    }.items():
        if planner.get(key) != expected:
            errors.append(f"planner source binding mismatch: {key}")
    runtime_sources = (
        "e4_population_generator", "e4_online_feature_and_parity_runner",
        "e4_fresh_scorer", "e4_independent_auditor",
    )
    sources = contract["implementation_sources_not_yet_bound"]
    if any(sources.get(key) is not None for key in runtime_sources):
        errors.append("runtime implementation source was claimed without implementation review")
    if any(value is not False for key, value in contract["execution_identity"].items() if key.endswith("authorized")):
        errors.append("execution authorization is enabled")
    if errors:
        fail("; ".join(errors))

    auditor_hash, auditor_bytes = sha256(Path(__file__).resolve())
    result = {
        "receipt_id": "FAS_E4_0_CONTRACT_DRAFT_V05_INDEPENDENT_AUDIT",
        "status": "DRAFT_AUDIT_PASS_WITH_IMPLEMENTATION_SOURCE_BLOCKERS",
        "contract_path": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": sha256(CONTRACT)[0],
        "predecessor_contract_sha256": predecessor_hash,
        "support_plan_sha256": support_hash,
        "planner_source_sha256": plan["planner_source_sha256"],
        "source_test_receipt_sha256": test_hash,
        "implementation_source_map_sha256": source_map_hash,
        "selected_quartets": plan["selected_whole_quartet_prefix"],
        "selected_minimum_class_support": 252,
        "previous_prefix_minimum_support": 248,
        "unique_feature_rows": expected_feature_rows,
        "projected_peak_bytes_before_free_space_reserve": expected_peak,
        "execution_sources_pending": list(runtime_sources),
        "auditor_source_path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "auditor_source_sha256": auditor_hash,
        "auditor_source_bytes": auditor_bytes,
        "authorizations_open": False,
        "population_rows_written": False,
        "tokenizer_contacted": False,
        "model_contacted": False,
        "cuda_initialized": False,
        "labels_opened": False,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
