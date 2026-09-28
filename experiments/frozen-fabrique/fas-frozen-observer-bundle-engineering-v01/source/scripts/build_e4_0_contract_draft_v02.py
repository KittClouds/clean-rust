from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
SOURCE = ROOT / "source" / "e4-support-plan-v09"
INPUT_DRAFT = PLANS / "E4-0-CONTRACT-DRAFT-v01.json"
SUPPORT_PLAN = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v09.json"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v02.json"


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    draft = read_json(INPUT_DRAFT)
    plan = read_json(SUPPORT_PLAN)
    plan_hash, plan_bytes = sha256(SUPPORT_PLAN)
    plan_source = SOURCE / "src" / "main.rs"
    source_hash, source_bytes = sha256(plan_source)
    cargo_hash, cargo_bytes = sha256(SOURCE / "Cargo.toml")
    lock_hash, lock_bytes = sha256(SOURCE / "Cargo.lock")

    if draft["authorization"]["population_generation_authorized"]:
        raise RuntimeError("contract input unexpectedly authorizes population generation")
    if any(
        plan[key]
        for key in ("population_rows_written", "tokenizer_contacted", "model_contacted", "labels_opened")
    ):
        raise RuntimeError("support plan is not a model-free, rows-not-written planning receipt")
    if plan["planner_source_sha256"] != source_hash:
        raise RuntimeError("support plan source hash does not match the v09 planner")
    if not plan["immediately_previous_whole_quartet_prefix_meets_target"] is False:
        raise RuntimeError("support plan does not prove its selected prefix is minimal")
    if plan["minimum_class_count_at_previous_prefix"] >= plan["construction_target_rows_per_class"]:
        raise RuntimeError("support plan predecessor unexpectedly meets the target")
    if plan["selected_whole_quartet_prefix"] != 18_667:
        raise RuntimeError("support plan prefix differs from the reviewed expected schedule")

    draft["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V02"
    draft["status"] = "DRAFT_NOT_SEALED_NOT_AUTHORIZED_SOURCE_HASHES_PENDING"
    draft["draft_revision"] = 2
    draft["design_inputs"]["symbolic_support_plan_path"] = str(SUPPORT_PLAN.relative_to(ROOT)).replace("\\", "/")
    draft["design_inputs"]["symbolic_support_plan_sha256"] = plan_hash
    draft["design_inputs"]["symbolic_support_plan_bytes"] = plan_bytes

    population = draft["population"]
    population["identity_serialization"] = {
        "text_encoding": "UTF-8",
        "unicode_normalization_for_rendered_inputs": "None; the exact byte sequence supplied to the tokenizer is hashed.",
        "template_exclusion_normalization": "Unicode NFKC, Unicode case-fold, trim, collapse internal Unicode whitespace runs to one ASCII space.",
        "namespace_ascii": "FAS-E4-0-POP-V01",
        "seed_u64": 2026092605,
        "seed_integer_encoding": "Unsigned 64-bit little-endian.",
        "schedule_ordinal_encoding": "Unsigned 64-bit little-endian, zero-based in the exact E1 v04 factorial loop order.",
        "quartet_id_preimage": "UTF8(ASCII FAS-E4-0-QUARTET-ID-v01) || 0x00 || ASCII namespace || 0x00 || u64le(seed) || u64le(shared_candidate_counter) || u64le(schedule_ordinal) || bytes(track_code, context_split, entity_split, family_id, relation_id, state_id, context_pair_id, entity_pair_id).",
        "track_codes": {"FACTORIAL_BALANCED": 0, "BINDING_CONTEXT": 1, "BINDING_ENTITY": 2},
        "quartet_id_digest": "SHA-256; lowercase 64-character hexadecimal encoding.",
        "row_id": "lowercase quartet digest hex || ASCII ':' || two lowercase hex digits for surface code (00 seen, 01 held-out) || ASCII ':' || two lowercase hex digits for variant code (00 A, 01 C, 02 E, 03 P).",
        "rendered_input_sha256": "SHA-256 of exact UTF-8 input_text bytes only; no JSON encoding or line terminator.",
        "candidate_choice_domain_bytes": "ASCII domain tag including its trailing 0x00, followed by ASCII namespace, 0x00, u64le(seed), and u64le(schedule_ordinal). Primary and held-out surfaces use distinct frozen domain tags.",
        "choice_permutation": "Read digest bytes 0..3 and 4..7 as u32 little-endian; start = first_u32 mod 384; step = second_u32 mod 384, incremented modulo 384 until gcd(step, 384)=1. For shared candidate counter k in 0..383, choice=(start+k*step) mod 384.",
        "choice_index_fields": "query_id=floor(choice/48); observation_id=floor((choice mod 48)/6); candidate_order_id=choice mod 6. A/C/E use observation_id; P uses (observation_id+4) mod 8.",
        "shared_collision_counter": "One counter per semantic quartet, shared by the primary and held-out render surfaces. At each counter test all eight row input hashes. Accept the whole semantic quartet only if all eight are pairwise distinct and absent from E1 and prior E4 rows. Fail closed after all 384 counters.",
        "collision_retry_changes_rendering": True,
        "row_order": "Surface order primary then held-out; within each surface A, C, E, P.",
    }
    population["collision"] = {
        "keys": ["semantic_quartet_id", "surface-specific-row_id", "exact-rendered-input-sha256"],
        "compare_against": ["all E1 rows", "all earlier accepted E4 rows across both surfaces"],
        "action": "Reject the entire paired-surface quartet and increment the shared candidate counter; the counter changes both surface render choices. Never change semantic labels or keep a subset of rows.",
        "exhaustion": "If no collision-free pair exists among all 384 paired choices, preserve and stop before completing the population.",
    }
    population["strata_materialization"] = {
        "primary_seen_and_lexical": "One four-row rendering per semantic quartet using E1's eight observation and eight query templates.",
        "heldout_template": "One second four-row rendering per same semantic quartet using the frozen E4 template manifest.",
        "joint_template_plus_lexical": "A truth stratum over held-out-template rows whose context or entity term is novel; it adds no duplicate row or feature vector.",
        "template_and_joint_labels": "Stored in escrow; no support, predictions, or score output from these truth partitions before FF-BUNDLE-TEMPLATE-01 freezes its contract.",
    }
    population["support"]["symbolic_plan"] = {
        "path": str(SUPPORT_PLAN.relative_to(ROOT)).replace("\\", "/"),
        "sha256": plan_hash,
        "status": plan["status"],
        "selected_whole_quartet_prefix": plan["selected_whole_quartet_prefix"],
        "previous_prefix_minimum_class_count": plan["minimum_class_count_at_previous_prefix"],
        "previous_prefix_meets_target": plan["immediately_previous_whole_quartet_prefix_meets_target"],
        "primary_rows": plan["rows_in_primary_seen_and_lexical_population"],
        "heldout_template_rows": plan["rows_in_heldout_template_population"],
        "joint_lexical_rows_subset": plan["heldout_template_joint_lexical_rows_subset"],
        "per_class_counts": plan["minimum_support_by_endpoint_and_stratum"],
        "model_free": True,
        "population_rows_written": False,
    }

    row_count = int(plan["unique_feature_rows_all_materialized_strata"])
    feature_bytes = row_count * 8192
    input_cap = row_count * 1024
    label_cap = row_count * 1024
    row_manifest_cap = row_count * 512
    row_files_cap = input_cap + label_cap + row_manifest_cap
    persistent_other_cap = 512 * 1024 * 1024
    peak_temp_cap = 512 * 1024 * 1024
    projected_peak = 2 * feature_bytes + row_files_cap + persistent_other_cap + peak_temp_cap
    resources = draft["resources"]
    resources.update(
        {
            "feature_rows": row_count,
            "feature_cache_bytes": feature_bytes,
            "feature_cache_atomic_staging_bytes": feature_bytes,
            "feature_cache_final_plus_staging_bytes": 2 * feature_bytes,
            "panel_input_jsonl_max_bytes": input_cap,
            "label_jsonl_max_bytes": label_cap,
            "row_manifest_jsonl_max_bytes": row_manifest_cap,
            "row_level_artifact_max_bytes": row_files_cap,
            "other_persistent_artifact_max_bytes": persistent_other_cap,
            "temporary_artifact_max_bytes": peak_temp_cap,
            "projected_peak_bytes_before_free_space_reserve": projected_peak,
            "free_space_reserve": "ceil(0.10 * live D: total bytes); contract preflight records volume size and requires free_before >= projected_peak_bytes_before_free_space_reserve + reserve_bytes.",
            "row_size_caps_enforced_by_generator": {
                "panel_input_jsonl_line_including_lf": 1024,
                "label_jsonl_line_including_lf": 1024,
                "row_manifest_jsonl_line_including_lf": 512,
            },
            "resource_scope": "Conservative output-size ceiling, not a claim about actual eventual file sizes. Actual per-file byte counts and process RAM/GPU receipts remain required.",
            "resource_preflight_model_contact": False,
            "model_and_tokenizer_assets": "Existing pinned read-only assets; not duplicated into the E4 output tree.",
        }
    )
    draft["implementation_sources_not_yet_bound"] = {
        "e4_population_generator": None,
        "e4_online_feature_and_parity_runner": None,
        "e4_fresh_scorer": None,
        "e4_independent_auditor": None,
        "e4_support_planner": {
            "path": str((SOURCE / "src" / "main.rs").relative_to(ROOT)).replace("\\", "/"),
            "sha256": source_hash,
            "bytes": source_bytes,
            "cargo_manifest_sha256": cargo_hash,
            "cargo_manifest_bytes": cargo_bytes,
            "cargo_lock_sha256": lock_hash,
            "cargo_lock_bytes": lock_bytes,
            "role": "Model-free support and paired-input-collision schedule planner only; not the population writer or scoring implementation.",
        },
    }
    draft["draft_blockers_before_freeze"] = [
        "Implement and bind the population writer; it must reproduce the v09 paired-surface schedule, IDs, exact input hashes, and support plan without semantic drift.",
        "Implement and bind the online feature/parity runner against the sealed E2 ABI and the exact 256-quartet parity selector.",
        "Implement and bind the CPU fresh scorer and a separate auditor that independently reconstructs support, BA, bootstrap bounds, and disposition.",
        "Run source-level regression tests and an independent contract audit; seal only after all source and input identities match.",
    ]
    draft["phase_gates"] = [
        "Contract and all implementation source identities reviewed and sealed; no execution authority is conferred by the draft.",
        "Model-free population generation under the bound generator, support/resource receipts, population seal, and independent audit.",
        "Only after population audit and separate authorization: tokenizer-only parity selection; seal its concrete 256-quartet panel before model weights load.",
        "After a separate model-contact authorization: online/cache parity and fresh feature extraction; held-out-template truth remains escrowed.",
        "After parity receipts are sealed and a separate scoring authorization: one primary label opening and simultaneous scoring.",
        "Independent replay and terminal disposition; E4-A remains a separate later decision.",
    ]
    draft["execution_identity"]["population_generation_authorized"] = False
    draft["execution_identity"]["tokenizer_contact_authorized"] = False
    draft["execution_identity"]["feature_extraction_authorized"] = False
    draft["execution_identity"]["model_contact_authorized"] = False
    draft["execution_identity"]["label_opening_authorized"] = False
    draft["execution_identity"]["scoring_authorized"] = False
    draft["execution_identity"]["E4_A_authorized"] = False
    builder_hash, builder_bytes = sha256(Path(__file__).resolve())
    draft["draft_builder"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "sha256": builder_hash,
        "bytes": builder_bytes,
        "role": "Builds the unsealed machine-readable E4-0 draft from the bound design and symbolic support plan; it confers no execution authority.",
    }

    OUTPUT.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": draft["status"], "output": str(OUTPUT), "support_plan_sha256": plan_hash,
                      "planner_source_sha256": source_hash, "projected_peak_bytes": projected_peak}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
