from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
AUDITS = ROOT / "audits"
PREDECESSOR = PLANS / "E4-0-CONTRACT-DRAFT-v04.json"
SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v11.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v03.md"
TEST_RECEIPT = AUDITS / "e4-0-support-plan-v11-source-tests.json"
PLANNER_DIR = ROOT / "source" / "e4-support-plan-v11"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v05.json"
EXPECTED_V04_SHA256 = "e70572102c04bc315bd3564e3f33cd4fd5e2a70097c10f66f864f512f9ddd4ca"
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


def main() -> int:
    predecessor_hash, _ = sha256(PREDECESSOR)
    support_hash, support_bytes = sha256(SUPPORT)
    test_hash, test_bytes = sha256(TEST_RECEIPT)
    if predecessor_hash != EXPECTED_V04_SHA256:
        raise RuntimeError("v04 predecessor hash mismatch")
    if support_hash != EXPECTED_SUPPORT_SHA256 or test_hash != EXPECTED_TEST_RECEIPT_SHA256:
        raise RuntimeError("v11 source or plan receipt differs from reviewed identity")
    plan = load(SUPPORT)
    tests = load(TEST_RECEIPT)
    if tests["status"] != "PASS_MODEL_FREE_SOURCE_AND_PLAN_VALIDATION":
        raise RuntimeError("support planner source validation did not pass")
    if tests["checks"]["cargo_test_release"].get("failed") != 0:
        raise RuntimeError("support planner unit tests report failures")
    if any(tests[field] for field in (
        "population_rows_written", "tokenizer_contacted", "model_contacted", "cuda_initialized", "labels_opened"
    )):
        raise RuntimeError("support validation receipt crosses a prohibited phase boundary")
    if any(plan[field] for field in (
        "population_rows_written", "tokenizer_contacted", "model_contacted", "labels_opened"
    )):
        raise RuntimeError("symbolic support plan crosses a prohibited phase boundary")

    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    source_path = PLANNER_DIR / "src" / "main.rs"
    manifest_path = PLANNER_DIR / "Cargo.toml"
    lock_path = PLANNER_DIR / "Cargo.lock"
    source_hash, source_bytes = sha256(source_path)
    manifest_hash, manifest_bytes = sha256(manifest_path)
    lock_hash, lock_bytes = sha256(lock_path)
    if plan["planner_source_sha256"] != source_hash or tests["source"]["sha256"] != source_hash:
        raise RuntimeError("v11 source SHA-256 differs from plan/test receipts")
    if tests["support_plan"]["sha256"] != support_hash:
        raise RuntimeError("source-validation receipt references a different support plan")

    draft = copy.deepcopy(load(PREDECESSOR))
    draft["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05"
    draft["draft_revision"] = 5
    draft["supersedes"] = {
        "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V04",
        "sha256": predecessor_hash,
        "reason": "Bind the lint-clean v11 support planner, its model-free replay, and updated implementation map; scientific and resource gates are unchanged.",
    }
    design_inputs = draft["design_inputs"]
    design_inputs["symbolic_support_plan_path"] = str(SUPPORT.relative_to(ROOT)).replace("\\", "/")
    design_inputs["symbolic_support_plan_sha256"] = support_hash
    design_inputs["symbolic_support_plan_bytes"] = support_bytes
    for old_version in ("v01", "v02"):
        for suffix in ("path", "sha256", "bytes"):
            design_inputs.pop(f"implementation_source_map_{old_version}_{suffix}", None)
    design_inputs["implementation_source_map_v03_path"] = str(SOURCE_MAP.relative_to(ROOT)).replace("\\", "/")
    design_inputs["implementation_source_map_v03_sha256"] = source_map_hash
    design_inputs["implementation_source_map_v03_bytes"] = source_map_bytes
    design_inputs["support_plan_v11_validation_receipt_path"] = str(TEST_RECEIPT.relative_to(ROOT)).replace("\\", "/")
    design_inputs["support_plan_v11_validation_receipt_sha256"] = test_hash
    design_inputs["support_plan_v11_validation_receipt_bytes"] = test_bytes

    binding = draft["population"]["support"]["symbolic_plan"]
    binding.update({
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
        "source_validation_receipt_sha256": test_hash,
        "model_free": True,
        "population_rows_written": False,
    })
    planner = draft["implementation_sources_not_yet_bound"]["e4_support_planner"]
    planner.update({
        "path": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": source_hash,
        "bytes": source_bytes,
        "cargo_manifest_sha256": manifest_hash,
        "cargo_manifest_bytes": manifest_bytes,
        "cargo_lock_sha256": lock_hash,
        "cargo_lock_bytes": lock_bytes,
        "source_test_receipt_path": str(TEST_RECEIPT.relative_to(ROOT)).replace("\\", "/"),
        "source_test_receipt_sha256": test_hash,
        "source_test_receipt_bytes": test_bytes,
        "role": "Model-free support and paired-surface planner; verifies E1 quartet IDs, row IDs, and exact rendered inputs. Not the population writer or scoring implementation.",
    })
    draft["identity_collision_correction"].update({
        "current_support_plan": "E4-0-SYMBOLIC-SUPPORT-PLAN-v11",
        "current_support_sha256": support_hash,
        "v11_semantics_match_v10": tests["checks"]["v11_semantics_equal_v10_after_excluding_receipt_and_source_identity"],
        "v11_source_validation_receipt_sha256": test_hash,
    })

    builder_hash, builder_bytes = sha256(Path(__file__).resolve())
    draft["draft_builder"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "sha256": builder_hash,
        "bytes": builder_bytes,
        "role": "Builds an unsealed v05 draft by rebinding the corrected v11 support plan and source validation; no execution authority is conferred.",
    }
    OUTPUT.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": draft["status"], "contract_id": draft["contract_id"],
        "output": str(OUTPUT), "predecessor_sha256": predecessor_hash,
        "support_plan_sha256": support_hash, "planner_source_sha256": source_hash,
        "test_receipt_sha256": test_hash, "source_map_sha256": source_map_hash,
        "authorizations_open": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
