from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
PREDECESSOR = PLANS / "E4-0-CONTRACT-DRAFT-v03.json"
SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v10.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v02.md"
PLANNER_DIR = ROOT / "source" / "e4-support-plan-v10"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v04.json"
EXPECTED_V03_SHA256 = "3c55e5778d3dd104c60a57286563d67d6a3906d2e2f7d217de39f409229e5bb4"
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


def main() -> int:
    predecessor_hash, _ = sha256(PREDECESSOR)
    support_hash, support_bytes = sha256(SUPPORT)
    if predecessor_hash != EXPECTED_V03_SHA256:
        raise RuntimeError("v03 predecessor differs from the reviewed draft")
    if support_hash != EXPECTED_SUPPORT_SHA256:
        raise RuntimeError("v10 support receipt differs from the verified model-free plan")
    plan = load(SUPPORT)
    if plan["status"] != "MODEL_FREE_PAIRED_SURFACE_COLLISION_AWARE_SYMBOLIC_PLAN_ONLY":
        raise RuntimeError("support receipt is not a symbolic model-free plan")
    if not all(plan.get(field) is True for field in (
        "e1_quartet_ids_checked", "e1_row_ids_checked", "e4_paired_quartet_and_row_ids_checked"
    )):
        raise RuntimeError("v10 does not attest all required identity-collision checks")
    if any(plan[field] for field in (
        "population_rows_written", "tokenizer_contacted", "model_contacted", "labels_opened"
    )):
        raise RuntimeError("v10 support planning crossed an execution boundary")

    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    planner_hash, planner_bytes = sha256(PLANNER_DIR / "src" / "main.rs")
    manifest_hash, manifest_bytes = sha256(PLANNER_DIR / "Cargo.toml")
    lock_hash, lock_bytes = sha256(PLANNER_DIR / "Cargo.lock")
    if plan["planner_source_sha256"] != planner_hash:
        raise RuntimeError("support receipt planner source hash does not match v10 source")

    draft = copy.deepcopy(load(PREDECESSOR))
    draft["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V04"
    draft["draft_revision"] = 4
    draft["supersedes"] = {
        "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V03",
        "sha256": predecessor_hash,
        "reason": "Bind support planner v10 and its E1 quartet/row collision checks, plus the corrected source map; scientific gates remain unchanged.",
    }
    design_inputs = draft["design_inputs"]
    design_inputs["symbolic_support_plan_path"] = str(SUPPORT.relative_to(ROOT)).replace("\\", "/")
    design_inputs["symbolic_support_plan_sha256"] = support_hash
    design_inputs["symbolic_support_plan_bytes"] = support_bytes
    design_inputs.pop("implementation_source_map_v01_path", None)
    design_inputs.pop("implementation_source_map_v01_sha256", None)
    design_inputs.pop("implementation_source_map_v01_bytes", None)
    design_inputs["implementation_source_map_v02_path"] = str(SOURCE_MAP.relative_to(ROOT)).replace("\\", "/")
    design_inputs["implementation_source_map_v02_sha256"] = source_map_hash
    design_inputs["implementation_source_map_v02_bytes"] = source_map_bytes

    plan_binding = draft["population"]["support"]["symbolic_plan"]
    plan_binding.update({
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
    })
    planner = draft["implementation_sources_not_yet_bound"]["e4_support_planner"]
    planner.update({
        "path": str((PLANNER_DIR / "src" / "main.rs").relative_to(ROOT)).replace("\\", "/"),
        "sha256": planner_hash,
        "bytes": planner_bytes,
        "cargo_manifest_sha256": manifest_hash,
        "cargo_manifest_bytes": manifest_bytes,
        "cargo_lock_sha256": lock_hash,
        "cargo_lock_bytes": lock_bytes,
        "role": "Model-free support and paired-surface planner; verifies E1 quartet IDs, row IDs, and exact rendered inputs. It is not the population writer or scoring implementation.",
    })
    draft["identity_collision_correction"] = {
        "predecessor_support_plan": "E4-0-SYMBOLIC-SUPPORT-PLAN-v09",
        "predecessor_issue": "The v09 planner enforced exact rendered-input hash disjointness but did not compare E1 quartet IDs or row IDs.",
        "corrected_support_plan": "E4-0-SYMBOLIC-SUPPORT-PLAN-v10",
        "corrected_support_sha256": support_hash,
        "checked_keys": ["quartet_id", "row_id", "rendered_input_sha256"],
        "selected_prefix_and_support_unchanged": True,
        "population_rows_written": False,
        "labels_opened": False,
    }

    builder_hash, builder_bytes = sha256(Path(__file__).resolve())
    draft["draft_builder"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "sha256": builder_hash,
        "bytes": builder_bytes,
        "role": "Builds unsealed v04 by rebinding the verified v10 support plan and corrected implementation map; no execution authority is conferred.",
    }
    OUTPUT.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": draft["status"], "contract_id": draft["contract_id"],
        "output": str(OUTPUT), "predecessor_sha256": predecessor_hash,
        "support_plan_sha256": support_hash, "source_map_sha256": source_map_hash,
        "selected_prefix": plan["selected_whole_quartet_prefix"],
        "all_three_collision_keys_checked": True, "authorizations_open": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
