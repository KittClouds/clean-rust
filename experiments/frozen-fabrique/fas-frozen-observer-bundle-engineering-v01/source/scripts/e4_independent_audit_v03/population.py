from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from .constants import GATES, PRIMARY_LABEL_ID, ESCROW_LABEL_ID, EXPECTED_PREDECESSORS, SURFACES, VARIANTS
from .integrity import AuditError, Seal, read_json, read_jsonl_stream, sha256_file, stage_contract_binding, verify_e4_stage_seal


POPULATION_ENTRIES = frozenset({
    "E4_POPULATION_INPUTS_V01",
    "E4_POPULATION_ROW_MANIFEST_V01",
    PRIMARY_LABEL_ID,
    ESCROW_LABEL_ID,
    "E4_POPULATION_GENERATION_RECEIPT_V01",
})
SUPPORT_PLAN_SHA256 = "a15bca5d78867ea32905299fabd21f85cf6846a5a02a0c55dd32337e0396847f"
E1_INPUT_SHA256 = "9f0076daa147bac37aa80d4f9a55f9225289910ceb8acc41998354c5a166917a"
E1_ROW_MANIFEST_SHA256 = "ebfdf0064430ecae7a9ae2edd139f47c0c61291aa6c30c8ccb97daa195f835bc"


def _require(status: bool, detail: str) -> None:
    if not status:
        raise AuditError(detail)


def _file_member(seal: Seal, artifact_id: str):
    try:
        return seal.entries[artifact_id]
    except KeyError as exc:
        raise AuditError(f"population seal is missing {artifact_id}") from exc


def _line_pair(inputs: Path, manifest: Path):
    left = iter(read_jsonl_stream(inputs))
    right = iter(read_jsonl_stream(manifest))
    index = 0
    sentinel = object()
    while True:
        input_row = next(left, sentinel)
        manifest_row = next(right, sentinel)
        if input_row is sentinel and manifest_row is sentinel:
            return
        if input_row is sentinel or manifest_row is sentinel:
            raise AuditError("model-input JSONL and population manifest row counts differ")
        yield index, input_row, manifest_row
        index += 1


def _validate_input_and_row(row_index: int, item: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if set(item) != {"row_id", "quartet_id", "variant_id", "input_text"}:
        raise AuditError("population model input contains extra fields or truth")
    if set(row) != {"row_index", "row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"}:
        raise AuditError("population row manifest contains extra fields or truth-derived strata")
    if type(row.get("row_index")) is not int or row["row_index"] != row_index:
        raise AuditError("population row_index is not contiguous and ordered")
    for name in ("row_id", "quartet_id", "variant_id", "input_text"):
        if not isinstance(item.get(name), str) or not item[name]:
            raise AuditError(f"population input lacks nonempty {name}")
    for name in ("row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"):
        if not isinstance(row.get(name), str) or not row[name]:
            raise AuditError(f"population row manifest lacks nonempty {name}")
    for name in ("row_id", "quartet_id", "variant_id"):
        if item[name] != row[name]:
            raise AuditError(f"population input/manifest identity differs at row {row_index}: {name}")
    return row["row_id"], row["quartet_id"], row["variant_id"], row["surface_id"]


def _load_e1_freshness(e1_inputs: Path, e1_manifest: Path) -> tuple[set[str], set[str], set[str]]:
    input_sha, _ = sha256_file(e1_inputs)
    manifest_sha, _ = sha256_file(e1_manifest)
    _require(input_sha == E1_INPUT_SHA256, "E1 public input file differs from the frozen v11 planner identity")
    _require(manifest_sha == E1_ROW_MANIFEST_SHA256, "E1 row manifest differs from the frozen v11 planner identity")
    qids: set[str] = set()
    row_ids: set[str] = set()
    input_hashes: set[str] = set()
    for index, item, row in _line_pair(e1_inputs, e1_manifest):
        rid, qid, variant, _ = _validate_e1_pair(index, item, row)
        if rid in row_ids:
            raise AuditError("E1 contains duplicate row IDs in the public row manifest")
        if not isinstance(item.get("input_text"), str):
            raise AuditError("E1 public model input has no text")
        row_ids.add(rid)
        qids.add(qid)
        input_hashes.add(hashlib.sha256(item["input_text"].encode("utf-8")).hexdigest())
        if variant not in VARIANTS:
            raise AuditError("E1 public manifest has an unknown variant")
    _require(len(row_ids) == 106_496, "E1 public row count differs from the sealed panel")
    _require(len(qids) == 26_624, "E1 public quartet count differs from the sealed panel")
    _require(len(input_hashes) == 103_206, "E1 rendered-input uniqueness differs from the frozen support planner")
    return qids, row_ids, input_hashes


def _validate_e1_pair(index: int, item: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if type(row.get("row_index")) is not int or row.get("row_index") != index:
        raise AuditError("E1 row manifest indices are not contiguous")
    for key in ("row_id", "quartet_id", "variant_id", "input_text"):
        if not isinstance(item.get(key), str) or not item[key]:
            raise AuditError(f"E1 input row lacks {key}")
    if any(item.get(key) != row.get(key) for key in ("row_id", "quartet_id", "variant_id")):
        raise AuditError("E1 input/manifest row identity mismatch")
    if row.get("quartet_split") not in ("FIT", "TEST"):
        raise AuditError("E1 row manifest contains an unknown split")
    return row["row_id"], row["quartet_id"], row["variant_id"], row["quartet_split"]


def _verify_selected_support(receipt: Mapping[str, Any], support_plan_path: Path) -> dict[str, Any]:
    plan_sha, _ = sha256_file(support_plan_path)
    _require(plan_sha == SUPPORT_PLAN_SHA256, "support plan SHA-256 differs from the frozen v11 plan")
    plan = read_json(support_plan_path)
    expected = plan.get("minimum_support_by_endpoint_and_stratum")
    observed = receipt.get("selected_primary_support")
    _require(isinstance(expected, dict) and isinstance(observed, dict), "primary support receipt/plan malformed")
    _require(observed == expected, "generation receipt primary support differs from frozen symbolic schedule")
    flat_counts: list[int] = []
    for endpoint in ("context_identity", "entity_identity", "relation", "observed_state"):
        values = observed.get(endpoint)
        if not isinstance(values, list) or any(type(value) is not int or value < 0 for value in values):
            raise AuditError(f"primary support table is malformed: {endpoint}")
        flat_counts.extend(values)
    target = observed.get("exact_target_by_stratum")
    if not isinstance(target, list) or len(target) != 4:
        raise AuditError("primary exact-target support table is malformed")
    for values in target:
        if not isinstance(values, list) or len(values) != 3 or any(type(value) is not int or value < 0 for value in values):
            raise AuditError("primary exact-target support cells are malformed")
        flat_counts.extend(values)
    if min(flat_counts, default=0) < GATES.support_construction_target:
        raise AuditError("primary construction support is below 250/class")
    previous = receipt.get("previous_prefix_minimum_class_count")
    if type(previous) is not int or previous != 248:
        raise AuditError("generation receipt does not preserve the immediately previous prefix minimum 248")
    return {
        "construction_minimum_rows_per_class": min(flat_counts),
        "scoring_minimum_rows_per_class": GATES.support_minimum,
        "primary_support_cells": len(flat_counts),
        "heldout_or_joint_support_read": False,
        "method": "compare the declared primary-only support matrix with the hash-pinned deterministic symbolic support plan; never read either terminal-label file",
    }


def audit_population(
    *,
    seal_path: Path,
    run_root: Path,
    contract_sha256: str,
    contract_root_sha256: str,
    expected_predecessors: Mapping[str, str],
    e1_inputs: Path,
    e1_manifest: Path,
    support_plan_path: Path,
    expected_rows: int = GATES.total_rows,
) -> dict[str, Any]:
    """Audit identity, freshness, support receipt, and custody without label-file I/O."""
    _inherited_contract_sha, inherited_contract_root = stage_contract_binding(
        "POPULATION_GENERATION", contract_sha256, contract_root_sha256
    )
    seal = verify_e4_stage_seal(
        seal_path,
        root=run_root,
        expected_stage="POPULATION_GENERATION",
        current_contract_sha256=contract_sha256,
        current_contract_root_sha256=contract_root_sha256,
        expected_predecessors=expected_predecessors,
        deferred_member_ids=frozenset({PRIMARY_LABEL_ID, ESCROW_LABEL_ID}),
        allowed_entry_ids=POPULATION_ENTRIES,
    )
    inputs_member = _file_member(seal, "E4_POPULATION_INPUTS_V01")
    manifest_member = _file_member(seal, "E4_POPULATION_ROW_MANIFEST_V01")
    receipt_member = _file_member(seal, "E4_POPULATION_GENERATION_RECEIPT_V01")
    primary_labels = _file_member(seal, PRIMARY_LABEL_ID)
    escrow_labels = _file_member(seal, ESCROW_LABEL_ID)
    expected_paths = {
        "E4_POPULATION_INPUTS_V01": "population/panel-inputs-v01.jsonl",
        "E4_POPULATION_ROW_MANIFEST_V01": "population/row-manifest-v01.jsonl",
        PRIMARY_LABEL_ID: "labels/primary-terminal-labels-v01.jsonl",
        ESCROW_LABEL_ID: "labels/template-joint-escrow-v01.jsonl",
        "E4_POPULATION_GENERATION_RECEIPT_V01": "receipts/population-generation-receipt-v01.json",
    }
    for artifact_id, path in expected_paths.items():
        if seal.entries[artifact_id].relative_path != path:
            raise AuditError(f"population seal path mismatch: {artifact_id}")

    e1_qids, e1_rows, e1_text_hashes = _load_e1_freshness(e1_inputs, e1_manifest)
    seen_qids: set[str] = set()
    seen_rows: set[str] = set()
    seen_text_hashes: set[str] = set()
    current_group: list[tuple[str, str, str, str]] = []
    count = 0
    quartets = 0
    previous_group_id: str | None = None
    for index, item, row in _line_pair(inputs_member.path, manifest_member.path):
        rid, qid, variant, surface = _validate_input_and_row(index, item, row)
        expected_surface, expected_custody = SURFACES[(index % 8) // 4]
        expected_variant = VARIANTS[index % 4]
        if surface != expected_surface or row["truth_partition"] != expected_custody or variant != expected_variant:
            raise AuditError(f"population row schedule/custody mismatch at row {index}")
        if re.fullmatch(r"[0-9a-f]{64}", qid) is None:
            raise AuditError("population quartet ID is not canonical lowercase SHA-256 hex")
        surface_code = 0 if surface == "PRIMARY_SEEN" else 1
        expected_row_id = f"{qid}:{surface_code:02x}:{index % 4:02x}"
        if rid != expected_row_id:
            raise AuditError(f"population row ID differs from frozen namespace serialization at row {index}")
        if rid in e1_rows or rid in seen_rows:
            raise AuditError("population row-ID collision against E1 or prior E4 row")
        text_hash = hashlib.sha256(item["input_text"].encode("utf-8")).hexdigest()
        if text_hash in e1_text_hashes or text_hash in seen_text_hashes:
            raise AuditError("population rendered-input SHA-256 collision against E1 or prior E4 row")
        group_index = index % 8
        if group_index == 0:
            if qid in e1_qids or qid in seen_qids:
                raise AuditError("population quartet-ID collision against E1 or a prior quartet")
            seen_qids.add(qid)
            previous_group_id = qid
            quartets += 1
        if qid != previous_group_id:
            raise AuditError(f"paired surface rows do not share the scheduled quartet at {index}")
        seen_rows.add(rid)
        seen_text_hashes.add(text_hash)
        current_group.append((rid, qid, variant, surface))
        if group_index == 7:
            if len(current_group) != 8:
                raise AuditError("incomplete schedule quartet")
            current_group.clear()
        count += 1
    if count != expected_rows or quartets * 8 != expected_rows or current_group:
        raise AuditError("population row count/quartet prefix differs from the frozen schedule")

    receipt = read_json(receipt_member.path)
    if receipt.get("status") != "POPULATION_COMPLETE_GATE_PASS" or receipt.get("population_rows_written") is not True:
        raise AuditError("population generation receipt is not complete/pass")
    if receipt.get("contract_seal_root_sha256") != inherited_contract_root:
        raise AuditError("population receipt binds another contract seal")
    if receipt.get("template_truth_opened") is not False or receipt.get("template_joint_support_emitted") is not False:
        raise AuditError("population receipt crossed heldout truth/support boundary")
    if receipt.get("predictions_emitted") is not False or receipt.get("model_contacted") is not False or receipt.get("tokenizer_contacted") is not False or receipt.get("cuda_initialized") is not False:
        raise AuditError("population generation receipt records a forbidden computation")
    if receipt.get("selected_whole_quartet_prefix") != quartets:
        raise AuditError("population receipt prefix differs from ordered manifest")
    if receipt.get("population_namespace") != "FAS-E4-0-POP-V01" or receipt.get("world_render_seed_u64") != 2_026_092_605:
        raise AuditError("population receipt namespace or world/render seed differs from the frozen schedule")
    if receipt.get("e1_root_sha256") != EXPECTED_PREDECESSORS["e1_v04_root_sha256"] or receipt.get("e1_input_sha256") != E1_INPUT_SHA256 or receipt.get("e1_row_manifest_sha256") != E1_ROW_MANIFEST_SHA256:
        raise AuditError("population receipt does not bind the frozen E1 public inputs")
    if receipt.get("row_order") != "schedule ordinal ascending; primary surface then heldout surface; variants A,C,E,P":
        raise AuditError("population receipt row-order declaration differs from the frozen schedule")
    if receipt.get("primary_rows") != quartets * 4 or receipt.get("heldout_template_rows") != quartets * 4 or receipt.get("unique_feature_rows") != count:
        raise AuditError("population receipt row counts differ from ordered manifest")
    support = _verify_selected_support(receipt, support_plan_path)
    skips = receipt.get("collision_skips")
    if not isinstance(skips, list) or len(skips) != 7_915 or receipt.get("shared_candidate_counter_sum") != 7_915 or receipt.get("maximum_candidate_counter") != 8:
        raise AuditError("collision retry receipt differs from the frozen paired-surface schedule")
    allowed_collision_kinds = {"quartet_id", "row_id", "rendered_input_sha256"}
    counters_by_ordinal: dict[int, list[int]] = {}
    for skip in skips:
        if not isinstance(skip, dict) or type(skip.get("schedule_ordinal")) is not int or type(skip.get("candidate_counter")) is not int:
            raise AuditError("collision retry receipt entry is malformed")
        classes = skip.get("collision_classes")
        if not isinstance(classes, list) or not classes or not set(classes).issubset(allowed_collision_kinds):
            raise AuditError("collision retry receipt contains an unknown collision class")
        counters_by_ordinal.setdefault(skip["schedule_ordinal"], []).append(skip["candidate_counter"])
    if any(values != list(range(len(values))) for values in counters_by_ordinal.values()):
        raise AuditError("collision counters do not show contiguous reject-and-retry sequences")
    files = receipt.get("files")
    if not isinstance(files, list):
        raise AuditError("population receipt files list is malformed")
    receipt_file_by_id = {entry.get("artifact_id"): entry for entry in files if isinstance(entry, dict)}
    for artifact_id in ("E4_POPULATION_INPUTS_V01", "E4_POPULATION_ROW_MANIFEST_V01", PRIMARY_LABEL_ID, ESCROW_LABEL_ID):
        entry = receipt_file_by_id.get(artifact_id)
        sealed = seal.entries[artifact_id]
        if not isinstance(entry, dict) or entry.get("path") != sealed.relative_path or entry.get("byte_length") != sealed.bytes or entry.get("sha256") != sealed.sha256:
            raise AuditError(f"population generation receipt differs from seal metadata: {artifact_id}")
    return {
        "status": "PASS_POPULATION_FRESHNESS_SUPPORT",
        "population_root_sha256": seal.root_sha256,
        "rows": count,
        "quartets": quartets,
        "e1_quartets_checked": len(e1_qids),
        "e1_rows_checked": len(e1_rows),
        "e1_rendered_input_hashes_checked": len(e1_text_hashes),
        "population_truth_files_opened": False,
        "primary_support": support,
        "all_checks_passed": True,
    }
