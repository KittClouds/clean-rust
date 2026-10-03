from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterator


VARIANTS = ("A", "C", "E", "P")
CHANGED_FACTOR = {"A": "NONE", "C": "CONTEXT", "E": "ENTITY", "P": "OBSERVATION_TEMPLATE"}
SPAN_TYPES = ("context", "entity", "relation")
FEATURE_CONTRACT_SHA = "08ddd42795d71d9b598da5015d5541316c6cf1f2c0761ce3c0890229cda4d5b0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(
        f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8")
        for item in entries
    )


def actual_tree_entries(root: Path, seal_relative: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise RuntimeError(f"symlink in sealed parent tree: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == seal_relative:
            continue
        digest, size = hash_file(path)
        entries.append({"path": relative, "bytes": size, "sha256": digest})
    return entries


def verify_tree(root: Path, seal_relative: str, expected_root: str) -> dict[str, Any]:
    seal_path = root.joinpath(*seal_relative.split("/"))
    if not seal_path.is_file():
        raise RuntimeError(f"missing parent seal: {seal_path}")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"parent seal root mismatch: {root}")
    entries = actual_tree_entries(root, seal_relative)
    if entries != seal.get("entries"):
        raise RuntimeError(f"parent tree entries differ from seal: {root}")
    reproduced = hashlib.sha256(canonical(entries)).hexdigest()
    if reproduced != expected_root:
        raise RuntimeError(f"parent tree hash does not reproduce: {root}")
    return seal


def verify_preflight(root: Path, binding: dict[str, Any]) -> str:
    seal_path = root / "seals" / "preflight-seal-v01.json"
    if not seal_path.is_file():
        raise RuntimeError("S01-2C preflight seal is missing")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    entries = []
    for item in seal["entries"]:
        path = root.joinpath(*item["path"].split("/"))
        digest, size = hash_file(path)
        entries.append({"path": item["path"], "bytes": size, "sha256": digest})
    if entries != seal["entries"] or hashlib.sha256(canonical(entries)).hexdigest() != seal["root_sha256"]:
        raise RuntimeError("S01-2C preflight seal does not reproduce")
    if seal.get("parents") != binding.get("parent_roots"):
        raise RuntimeError("S01-2C preflight parent binding differs")
    return seal["root_sha256"]


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc


def token_ids_sha256(token_ids: list[int]) -> str:
    digest = hashlib.sha256()
    packer = struct.Struct("<I")
    for token_id in token_ids:
        if not isinstance(token_id, int) or token_id < 0 or token_id > 0xFFFFFFFF:
            raise ValueError("token ID is outside the frozen unsigned 32-bit serialization")
        digest.update(packer.pack(token_id))
    return digest.hexdigest()


def spill_category(text: str) -> str:
    if not text:
        return "no_spill"
    whitespace = all(char.isspace() for char in text)
    punctuation = all(unicodedata.category(char).startswith("P") for char in text)
    if whitespace and punctuation:
        return "whitespace + punctuation"
    if whitespace:
        return "whitespace only"
    if punctuation:
        return "punctuation only"
    return "other"


def self_test() -> None:
    assert spill_category("") == "no_spill"
    assert spill_category(" ") == "whitespace only"
    assert spill_category("(") == "punctuation only"
    assert spill_category(")") == "punctuation only"
    assert spill_category("x") == "other"
    assert all(char in (" ", "(") and len(char) <= 1 for char in (" ", "("))
    assert not (len(")") <= 1 and all(char in (" ", "(") for char in ")"))
    coverage = [0] * 3
    for lo, hi in ((0, 2), (2, 3)):
        for index in range(lo, hi):
            coverage[index] += 1
    assert coverage == [1, 1, 1]
    assert [0, 1, 2] == list(range(0, 3))
    assert [0, 2] != list(range(0, 3))


def mapping_failure(mapping: dict[str, Any]) -> str | None:
    reason = mapping.get("failure_reason")
    return reason if reason not in (None, "") else None


def validate_span(
    *,
    text: str,
    char_span: list[int],
    token_ids: list[int],
    offsets: list[list[int]],
    special_mask: list[int],
    source_mapping: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if len(char_span) != 2 or not all(isinstance(value, int) for value in char_span):
        return {"status": "FAIL", "character_span": char_span}, ["malformed_character_span"]
    start, end = char_span
    if start < 0 or end <= start or end > len(text):
        return {"status": "FAIL", "character_span": char_span}, ["character_span_out_of_bounds"]
    if len(token_ids) != len(offsets) or len(token_ids) != len(special_mask):
        return {"status": "FAIL", "character_span": char_span}, ["token_sequence_arrays_have_different_lengths"]

    selected: list[int] = []
    for position, (offset, is_special) in enumerate(zip(offsets, special_mask, strict=True)):
        if not isinstance(offset, list) or len(offset) != 2 or not all(isinstance(v, int) for v in offset):
            errors.append("malformed_token_offset")
            continue
        lo, hi = offset
        if is_special not in (0, 1):
            errors.append("malformed_special_token_mask")
            continue
        if is_special:
            if (lo, hi) != (0, 0):
                errors.append("special_token_offset_anomaly")
            if lo < end and hi > start:
                errors.append("special_token_overlaps_semantic_span")
            continue
        if lo < 0 or hi <= lo or hi > len(text):
            errors.append("malformed_nonspecial_offset")
            continue
        if lo < end and hi > start:
            selected.append(position)

    if errors:
        return {"status": "FAIL", "character_span": [start, end], "token_positions": selected}, sorted(set(errors))
    if not selected:
        return {"status": "FAIL", "character_span": [start, end], "token_positions": []}, ["empty_token_cover"]
    if selected != list(range(selected[0], selected[-1] + 1)):
        errors.append("noncontiguous_token_positions")

    coverage = [0] * (end - start)
    for position in selected:
        lo, hi = offsets[position]
        clipped_lo, clipped_hi = max(lo, start), min(hi, end)
        if clipped_lo >= clipped_hi:
            errors.append("selected_token_does_not_overlap_span")
            continue
        for index in range(clipped_lo - start, clipped_hi - start):
            coverage[index] += 1
    if any(count == 0 for count in coverage):
        errors.append("semantic_character_coverage_gap")
    if any(count > 1 for count in coverage):
        errors.append("semantic_character_coverage_overlap")

    cover_start = min(offsets[position][0] for position in selected)
    cover_end = max(offsets[position][1] for position in selected)
    left_spill = text[cover_start:start] if cover_start <= start else "INVALID_RIGHTWARD_START"
    right_spill = text[end:cover_end] if cover_end >= end else "INVALID_LEFTWARD_END"
    if cover_start > start or cover_end < end:
        errors.append("token_cover_does_not_contain_semantic_span")
    if right_spill:
        errors.append("right_spill_forbidden")
    if len(left_spill) > 1:
        errors.append("left_spill_exceeds_one_character")
    if any(char not in (" ", "(") for char in left_spill):
        errors.append("left_spill_character_not_allowlisted")

    selected_offsets = [offsets[position] for position in selected]
    crossing = []
    for position in selected:
        lo, hi = offsets[position]
        if lo < start or hi > end:
            token_left = text[lo:start] if lo < start else ""
            token_right = text[end:hi] if hi > end else ""
            crossing.append({
                "token_position": position,
                "token_id": token_ids[position],
                "token_offsets": [lo, hi],
                "token_text": text[lo:hi],
                "left_spill_text": token_left,
                "right_spill_text": token_right,
                "left_spill_width": len(token_left),
                "right_spill_width": len(token_right),
                "left_spill_category": spill_category(token_left),
                "right_spill_category": spill_category(token_right),
                "combined_spill_category": spill_category(token_left + token_right),
            })

    if audit.get("character_span") != [start, end]:
        errors.append("audit_character_span_mismatch")
    if audit.get("anomalous_token_positions") != []:
        errors.append("sealed_audit_reports_tokenizer_anomaly")
    cover_audit = audit.get("minimal_cover", {})
    exact_checks = {
        "selected_token_positions": selected,
        "character_span": [cover_start, cover_end],
        "coverage_status": "EXACT_ONCE" if all(count == 1 for count in coverage) else "NOT_EXACT_ONCE",
        "left_spill_text": left_spill,
        "left_spill_width": len(left_spill),
        "right_spill_text": right_spill,
        "right_spill_width": len(right_spill),
        "total_spill_width": len(left_spill) + len(right_spill),
    }
    for field, expected in exact_checks.items():
        if cover_audit.get(field) != expected:
            errors.append(f"S01_2B_minimal_cover_mismatch:{field}")
    if audit.get("crossing_token_count") != len(crossing):
        errors.append("S01_2B_crossing_token_count_mismatch")
    if audit.get("crossing_tokens") != crossing:
        errors.append("S01_2B_crossing_token_details_mismatch")
    if audit.get("source_alignment_status") != source_mapping.get("status"):
        errors.append("S01_2B_source_alignment_status_mismatch")
    audit_reason = audit.get("source_alignment_failure_reason")
    if audit_reason in ("", None):
        audit_reason = None
    if audit_reason != mapping_failure(source_mapping):
        errors.append("S01_2B_source_alignment_reason_mismatch")
    if source_mapping.get("character_span") != [start, end]:
        errors.append("S01_2A_character_span_mismatch")
    if source_mapping.get("occurrence") != audit.get("occurrence_index"):
        errors.append("occurrence_identity_mismatch")
    if source_mapping.get("status") == "PASS" and source_mapping.get("token_positions") != selected:
        errors.append("preexisting_pass_positions_differ_from_minimal_cover")
    if source_mapping.get("status") == "REJECT" and mapping_failure(source_mapping) != "token_offset_crosses_span_boundary":
        errors.append("unexpected_historical_rejection_reason")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "occurrence": source_mapping.get("occurrence"),
        "character_span": [start, end],
        "token_positions": selected,
        "selected_token_offsets": selected_offsets,
        "minimal_cover_character_interval": [cover_start, cover_end],
        "left_spill_text": left_spill,
        "right_spill_text": right_spill,
        "boundary_crossing_positions": [item["token_position"] for item in crossing],
    }
    return result, sorted(set(errors))


def expected_parent_checks(binding: dict[str, Any]) -> dict[str, Any]:
    roots = binding["parent_roots"]
    verified = {}
    for name in ("S01_2", "S01_2A", "S01_2B"):
        item = roots[name]
        root = Path(item["path"])
        seal = verify_tree(root, item["seal_path"], item["result_tree_root_sha256"])
        verified[name] = seal
        print(f"verified_parent={name} root={item['result_tree_root_sha256']}", flush=True)

    phase1, phase2a, phase2b = (verified[name] for name in ("S01_2", "S01_2A", "S01_2B"))
    if phase1.get("corpus_root_sha256") != binding["corpus_sha256"]:
        raise RuntimeError("S01-2 parent seal does not bind the contracted corpus")
    if phase1.get("protocol_bundle_root_sha256") != binding["protocol_bundle_root_sha256"]:
        raise RuntimeError("S01-2 parent protocol root differs")
    if phase2a.get("corpus_sha256") != binding["corpus_sha256"] or phase2a.get("construction_tree_root_sha256") != roots["S01_2"]["result_tree_root_sha256"]:
        raise RuntimeError("S01-2A parent provenance differs")
    if phase2b.get("corpus_sha256") != binding["corpus_sha256"] or phase2b.get("S01_2A_result_tree_root_sha256") != roots["S01_2A"]["result_tree_root_sha256"]:
        raise RuntimeError("S01-2B parent provenance differs")
    return verified


def support_result(counter: Counter[tuple[Any, ...]], expected_cells: int, required: int) -> dict[str, Any]:
    cells = [
        {"key": list(key), "complete_quartets": count}
        for key, count in sorted(counter.items(), key=lambda item: tuple(str(v) for v in item[0]))
    ]
    under = [item for item in cells if item["complete_quartets"] != required]
    return {
        "observed_cells": len(cells),
        "expected_cells": expected_cells,
        "required_per_cell": required,
        "all_cells_exact": len(cells) == expected_cells and not under,
        "under_supported_or_over_supported_cells": under,
        "cell_support": cells,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the sealed S01-2C minimal-cover rule to stored offsets")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    contract_path = root / "inputs" / "minimal-cover-alignment-contract-v01.json"
    binding_path = root / "inputs" / "alignment-input-binding-v01.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if sha256_bytes(contract_path.read_bytes()) != binding["S01_2C_contract_sha256"]:
        raise SystemExit("frozen contract hash differs from binding")
    preflight_root = verify_preflight(root, binding)
    self_test()
    parents = expected_parent_checks(binding)

    corpus_path = Path(binding["inputs"]["corpus"])
    alignment_path = Path(binding["inputs"]["alignment_records"])
    audit_path = Path(binding["inputs"]["boundary_span_audit"])
    corpus_hash, corpus_bytes = hash_file(corpus_path)
    alignment_hash, alignment_bytes = hash_file(alignment_path)
    audit_hash, audit_bytes = hash_file(audit_path)
    expected_hashes = binding["input_sha256"]
    if (corpus_hash, alignment_hash, audit_hash) != (
        expected_hashes["corpus"], expected_hashes["alignment_records"], expected_hashes["boundary_span_audit"]
    ):
        raise RuntimeError("an allowlisted S01-2C input hash differs from its sealed binding")

    phase2a_root = Path(binding["parent_roots"]["S01_2A"]["path"])
    phase2b_root = Path(binding["parent_roots"]["S01_2B"]["path"])
    phase2a_report = json.loads((phase2a_root / "tokenizer-alignment-report-v01.json").read_text(encoding="utf-8"))
    phase2a_disposition = json.loads((phase2a_root / "phase-disposition-v01.json").read_text(encoding="utf-8"))
    phase2b_report = json.loads((phase2b_root / "boundary-audit-report-v02.json").read_text(encoding="utf-8"))
    phase2b_disposition = json.loads((phase2b_root / "phase-disposition-v02.json").read_text(encoding="utf-8"))
    if phase2a_report.get("status") != "TOKENIZER_ALIGNMENT_FAIL_CLOSED" or phase2a_disposition.get("tokenizer_alignment_status") != "TOKENIZER_ALIGNMENT_FAIL_CLOSED":
        raise RuntimeError("historical S01-2A failure disposition was not preserved")
    if phase2a_report.get("repeat_check_pass") is not True:
        raise RuntimeError("sealed S01-2A deterministic repeat check did not pass")
    if phase2a_report.get("tokenizer_resolved_commit") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise RuntimeError("S01-2A tokenizer revision differs from the pinned revision")
    if phase2a_report.get("model_instantiated") is not False or phase2a_report.get("model_weights_downloaded_or_loaded") is not False or phase2a_report.get("feature_extraction_performed") is not False:
        raise RuntimeError("S01-2A report crosses its tokenizer-only boundary")
    if phase2b_report.get("complete") is not True or phase2b_report.get("status") != "BOUNDARY_AUDIT_COMPLETE":
        raise RuntimeError("S01-2B audit is not complete")
    if phase2b_disposition.get("S01_2A_TOKENIZER_ALIGNMENT_FAIL_CLOSED") is not True or phase2b_disposition.get("S01_2_FEATURE_EXTRACTION_ELIGIBLE") is not False:
        raise RuntimeError("S01-2B disposition does not preserve the historical boundary")
    if phase2b_report.get("tokenizer_loaded_during_S01_2B") is not False or phase2b_report.get("LFM_loaded_or_instantiated") is not False or phase2b_report.get("feature_extraction_performed") is not False:
        raise RuntimeError("S01-2B report exceeds its read-only boundary")

    audit_iter = iter(read_jsonl(audit_path))
    align_iter = iter(read_jsonl(alignment_path))
    assignments_partial = root / "alignment-assignments-v01.jsonl.partial"
    assignments_path = root / "alignment-assignments-v01.jsonl"
    if assignments_partial.exists() or assignments_path.exists():
        raise SystemExit("S01-2C assignments already exist; refusing overwrite")

    events_seen = 0
    quartets_seen = 0
    span_occurrences = 0
    span_passes = 0
    span_failures = 0
    span_crossings = 0
    crossing_character_counts: Counter[str] = Counter()
    span_fail_reasons: Counter[str] = Counter()
    row_errors: Counter[str] = Counter()
    first_errors: list[dict[str, Any]] = []
    quartet_counts: Counter[str] = Counter()
    support_factorial: Counter[tuple[Any, ...]] = Counter()
    support_context: Counter[tuple[Any, ...]] = Counter()
    support_entity: Counter[tuple[Any, ...]] = Counter()
    output_digest = hashlib.sha256()
    output_bytes = 0

    def note_error(event_id: str, span_type: str, occurrence: int | None, reason: str) -> None:
        row_errors[reason] += 1
        if len(first_errors) < 200:
            first_errors.append({"event_id": event_id, "span_type": span_type, "occurrence": occurrence, "reason": reason})

    with assignments_partial.open("xb") as output:
        corpus_iter = read_jsonl(corpus_path)
        for q_index, quartet in enumerate(corpus_iter, start=1):
            quartets_seen += 1
            qid = quartet.get("quartet_id")
            variants = quartet.get("variants", [])
            quartet_ok = len(variants) == 4 and [v.get("variant_id") for v in variants] == list(VARIANTS)
            if not quartet_ok:
                note_error(str(qid), "quartet", None, "variant_order_or_count_mismatch")
            invariant_fields = (
                "latent_world_sha256", "target_candidate_identity", "exact_target",
                "candidate_identity_order", "relation_id", "state_id", "relation_surface", "state_surface",
            )
            for field in invariant_fields:
                if len(variants) == 4 and any(variant.get(field) != variants[0].get(field) for variant in variants[1:]):
                    quartet_ok = False
                    note_error(str(qid), "quartet", None, f"counterfactual_invariant_mismatch:{field}")
            prepared_rows = []
            for variant in variants:
                variant_id = variant.get("variant_id")
                event_id = variant.get("event_id")
                alignment = next(align_iter, None)
                if alignment is None:
                    raise RuntimeError("tokenizer alignment JSONL ended before corpus events")
                events_seen += 1
                if variant_id not in VARIANTS or variant.get("changed_factor") != CHANGED_FACTOR.get(variant_id):
                    quartet_ok = False
                    note_error(str(event_id), "quartet", None, "changed_factor_or_variant_identity_mismatch")
                if alignment.get("quartet_id") != qid or alignment.get("event_id") != event_id or alignment.get("variant_id") != variant_id:
                    quartet_ok = False
                    note_error(str(event_id), "event", None, "alignment_event_identity_mismatch")
                if alignment.get("input_sha256") != variant.get("input_sha256"):
                    quartet_ok = False
                    note_error(str(event_id), "event", None, "alignment_input_identity_mismatch")
                try:
                    encoded_text = variant["input_text"].encode("ascii")
                except (KeyError, UnicodeEncodeError):
                    encoded_text = b""
                    quartet_ok = False
                    note_error(str(event_id), "event", None, "input_text_not_exact_ascii")
                if sha256_bytes(encoded_text) != variant.get("input_sha256"):
                    quartet_ok = False
                    note_error(str(event_id), "event", None, "rendered_input_hash_mismatch")

                token_ids = alignment.get("token_ids", [])
                offsets = alignment.get("offset_mapping", [])
                special_mask = alignment.get("special_tokens_mask", [])
                seq_len = alignment.get("sequence_length")
                event_errors: list[dict[str, Any]] = []
                if alignment.get("model_id") != "LiquidAI/LFM2.5-1.2B-Base" or alignment.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "tokenizer_model_identity_mismatch"})
                if alignment.get("feature_contract_sha256") != FEATURE_CONTRACT_SHA or alignment.get("tokenizer_asset_manifest_sha256") != binding["parent_roots"]["S01_2A"]["tokenizer_asset_manifest_sha256"]:
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "tokenizer_or_feature_contract_hash_mismatch"})
                try:
                    reproduced_ids_sha = token_ids_sha256(token_ids)
                except (TypeError, ValueError, struct.error):
                    reproduced_ids_sha = ""
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "invalid_token_ids"})
                if reproduced_ids_sha != alignment.get("token_ids_sha256"):
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "token_ids_sha256_mismatch"})
                if seq_len != len(token_ids) or len(offsets) != len(token_ids) or len(special_mask) != len(token_ids) or seq_len <= 0:
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "sequence_array_length_mismatch"})
                if alignment.get("first_model_visible_position") != 0 or alignment.get("final_model_visible_position") != seq_len - 1:
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "first_or_final_position_mismatch"})
                if token_ids and (alignment.get("first_token_id") != token_ids[0] or alignment.get("final_token_id") != token_ids[-1]):
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "first_or_final_token_identity_mismatch"})
                if alignment.get("alignment_status") not in ("PASS", "REJECT"):
                    event_errors.append({"span_type": "event", "occurrence": None, "reason": "unknown_historical_alignment_status"})

                mapping_by_type = alignment.get("span_mappings", {})
                audit_rows = []
                span_records: dict[str, list[dict[str, Any]]] = {kind: [] for kind in SPAN_TYPES}
                positions_by_type: dict[str, set[int]] = {kind: set() for kind in SPAN_TYPES}
                for span_type in SPAN_TYPES:
                    source_mappings = mapping_by_type.get(span_type, [])
                    spans = variant.get("character_spans", {}).get(span_type, [])
                    if len(source_mappings) != len(spans):
                        event_errors.append({"span_type": span_type, "occurrence": None, "reason": "S01_2A_span_count_mismatch"})
                    for span, source_mapping in zip(spans, source_mappings, strict=False):
                        audit = next(audit_iter, None)
                        span_occurrences += 1
                        if audit is None:
                            raise RuntimeError("S01-2B span audit ended before corpus spans")
                        audit_rows.append(audit)
                        occurrence = span.get("occurrence")
                        if audit.get("event_id") != event_id or audit.get("quartet_id") != qid or audit.get("variant_id") != variant_id or audit.get("span_type") != span_type or audit.get("occurrence_index") != occurrence:
                            event_errors.append({"span_type": span_type, "occurrence": occurrence, "reason": "S01_2B_audit_identity_mismatch"})
                        expected_template = {"observation_template_id": variant.get("observation_template_id"), "query_template_id": variant.get("query_template_id")}
                        if audit.get("template_identity") != expected_template:
                            event_errors.append({"span_type": span_type, "occurrence": occurrence, "reason": "S01_2B_template_identity_mismatch"})
                        term_fields = {
                            "context": (variant.get("context_term_id"), variant.get("context_term"), variant.get("context_term_split")),
                            "entity": (variant.get("entity_term_id"), variant.get("entity_term"), variant.get("entity_term_split")),
                            "relation": (quartet.get("relation_id"), quartet.get("relation_surface"), "RELATION_INVENTORY"),
                        }
                        term_id, term_surface, term_split = term_fields[span_type]
                        if audit.get("term_identity") != {"term_id": term_id, "surface": term_surface, "split": term_split}:
                            event_errors.append({"span_type": span_type, "occurrence": occurrence, "reason": "S01_2B_term_identity_mismatch"})
                        if source_mapping.get("occurrence") != occurrence:
                            event_errors.append({"span_type": span_type, "occurrence": occurrence, "reason": "S01_2A_occurrence_identity_mismatch"})
                        validated, errors = validate_span(
                            text=variant.get("input_text", ""),
                            char_span=[span.get("start"), span.get("end")],
                            token_ids=token_ids,
                            offsets=offsets,
                            special_mask=special_mask,
                            source_mapping=source_mapping,
                            audit=audit,
                        )
                        for reason in errors:
                            event_errors.append({"span_type": span_type, "occurrence": occurrence, "reason": reason})
                        if validated.get("status") == "PASS" and not errors:
                            span_passes += 1
                            span_crossings += len(validated["boundary_crossing_positions"])
                            for char in validated["left_spill_text"]:
                                crossing_character_counts[f"U+{ord(char):04X}"] += 1
                            for char in validated["right_spill_text"]:
                                crossing_character_counts[f"U+{ord(char):04X}"] += 1
                            positions_by_type[span_type].update(validated["token_positions"])
                        else:
                            span_failures += 1
                        span_records[span_type].append(validated)

                for item in event_errors:
                    note_error(str(event_id), item["span_type"], item.get("occurrence"), item["reason"])
                if event_errors:
                    quartet_ok = False
                if variant_id != "A" and len(variants) == 4:
                    pass
                view_positions = {kind: sorted(positions_by_type[kind]) for kind in SPAN_TYPES}
                assignment = {
                    "quartet_id": qid,
                    "event_id": event_id,
                    "variant_id": variant_id,
                    "input_sha256": variant.get("input_sha256"),
                    "token_ids_sha256": alignment.get("token_ids_sha256"),
                    "sequence_length": seq_len,
                    "tokenizer_revision": alignment.get("model_revision"),
                    "feature_contract_sha256": alignment.get("feature_contract_sha256"),
                    "span_records": span_records,
                    "span_positions_by_type": view_positions,
                    "view_assignments": {
                        "V0_MEAN_FULL": {"position_range_half_open": [0, seq_len], "position_count": seq_len},
                        "V1_FINAL_POSITION": {"positions": [seq_len - 1], "position_count": 1},
                        "V2_FIRST_POSITION": {"positions": [0], "position_count": 1},
                        "V3_CONTEXT_SPAN_MEAN": {"positions": view_positions["context"], "position_count": len(view_positions["context"])},
                        "V4_ENTITY_SPAN_MEAN": {"positions": view_positions["entity"], "position_count": len(view_positions["entity"])},
                        "V5_RELATION_SPAN_MEAN": {"positions": view_positions["relation"], "position_count": len(view_positions["relation"])},
                        "V6_FIXED_SPAN_CONCAT": {"ordered_segments": [
                            {"source_view": "V3_CONTEXT_SPAN_MEAN", "positions": view_positions["context"]},
                            {"source_view": "V4_ENTITY_SPAN_MEAN", "positions": view_positions["entity"]},
                            {"source_view": "V5_RELATION_SPAN_MEAN", "positions": view_positions["relation"]},
                        ]},
                    },
                }
                prepared_rows.append((assignment, event_errors))

            if len(variants) != 4:
                quartet_ok = False
            for assignment, event_errors in prepared_rows:
                assignment["quartet_eligible"] = bool(quartet_ok and not event_errors)
                encoded = (json.dumps(assignment, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
                output.write(encoded)
                output_digest.update(encoded)
                output_bytes += len(encoded)
                quartet_counts[str(quartet.get("track_id"))] += 1 if assignment["variant_id"] == "A" and assignment["quartet_eligible"] else 0

            if quartet_ok and len(prepared_rows) == 4:
                track = quartet.get("track_id")
                context_split = quartet.get("context_term_split")
                entity_split = quartet.get("entity_term_split")
                if track == "FACTORIAL_BALANCED":
                    support_factorial[(track, context_split, entity_split, quartet.get("world_family_id"), quartet.get("relation_id"), quartet.get("state_id"), quartet.get("observation_template_id"), quartet.get("query_template_id"))] += 1
                elif track == "BINDING_CONTEXT":
                    support_context[(track, context_split, quartet.get("context_pair_id"), entity_split)] += 1
                elif track == "BINDING_ENTITY":
                    support_entity[(track, entity_split, quartet.get("entity_pair_id"), context_split)] += 1
                else:
                    note_error(str(qid), "quartet", None, "unknown_track_id")
            if quartets_seen % 1024 == 0:
                print(f"processed_quartets={quartets_seen} events={events_seen} spans={span_occurrences}", flush=True)

        if next(align_iter, None) is not None:
            raise RuntimeError("tokenizer alignment JSONL has trailing event rows")
        if next(audit_iter, None) is not None:
            raise RuntimeError("S01-2B audit JSONL has trailing span rows")
        output.flush()
        os.fsync(output.fileno())

    os.replace(assignments_partial, assignments_path)
    factorial = support_result(support_factorial, 1536, 16)
    binding_context = support_result(support_context, 64, 16)
    binding_entity = support_result(support_entity, 64, 16)
    support_pass = (
        quartets_seen == 26624 and events_seen == 106496
        and quartet_counts == Counter({"FACTORIAL_BALANCED": 24576, "BINDING_CONTEXT": 1024, "BINDING_ENTITY": 1024})
        and factorial["all_cells_exact"] and binding_context["all_cells_exact"] and binding_entity["all_cells_exact"]
    )
    spans_pass = span_occurrences == 638976 and span_passes == 638976 and span_failures == 0 and not row_errors
    b_audit_pass = (
        span_occurrences == phase2b_report.get("span_occurrences_reconciled")
        and span_crossings == phase2b_report.get("crossing_token_total")
        and phase2b_report.get("events_reconciled") == 106496
        and phase2b_report.get("quartets_reconciled") == 26624
    )
    overall_pass = support_pass and spans_pass and b_audit_pass
    output_hash, output_size = hash_file(assignments_path)
    report = {
        "report_id": "FASS01_S01_2C_MINIMAL_COVER_ALIGNMENT_REPORT_V01",
        "phase_id": "S01-2C-v01",
        "status": "MINIMAL_COVER_ALIGNMENT_PASS" if overall_pass else "TOKEN_SPAN_QUALIFICATION_FAIL_CLOSED",
        "preflight_root_sha256": preflight_root,
        "S01_2C_contract_sha256": binding["S01_2C_contract_sha256"],
        "parent_roots": {name: item["result_tree_root_sha256"] for name, item in binding["parent_roots"].items()},
        "input_sha256": expected_hashes,
        "input_bytes": {"corpus": corpus_bytes, "alignment_records": alignment_bytes, "boundary_span_audit": audit_bytes},
        "parent_tree_verification": {name: {"root_sha256": seal.get("root_sha256"), "verified": True} for name, seal in parents.items()},
        "source_S01_2A_status_preserved": phase2a_disposition.get("tokenizer_alignment_status"),
        "source_S01_2A_repeat_check_pass": phase2a_report.get("repeat_check_pass"),
        "events_reconciled": events_seen,
        "quartets_reconciled": quartets_seen,
        "span_occurrences_reconciled": span_occurrences,
        "span_passes": span_passes,
        "span_failures": span_failures,
        "minimal_cover_crossing_spans": span_crossings,
        "left_spill_character_counts": dict(sorted(crossing_character_counts.items())),
        "validation_error_counts": dict(sorted(row_errors.items())),
        "first_validation_errors": first_errors,
        "eligible_quartets_by_track": dict(sorted(quartet_counts.items())),
        "support_audit": {
            "factorial_balanced": factorial,
            "binding_context": binding_context,
            "binding_entity": binding_entity,
            "pass": support_pass,
        },
        "boundary_audit_reconciliation": {
            "pass": b_audit_pass,
            "S01_2B_crossing_token_total": phase2b_report.get("crossing_token_total"),
            "S01_2C_reconstructed_crossing_span_total": span_crossings,
            "mismatch_count": 0 if b_audit_pass and not row_errors else len(row_errors),
        },
        "alignment_assignments": {"path": assignments_path.name, "rows": events_seen, "bytes": output_size, "sha256": output_hash},
        "disallowed_work": {
            "tokenizer_loaded_during_S01_2C": False,
            "LFM_loaded_or_instantiated": False,
            "hidden_states_extracted": False,
            "features_created": False,
            "probe_training_performed": False,
            "geometry_analysis_performed": False,
            "S01_3_executed": False,
        },
        "gates": {
            "PARENT_SEALS": "PASS",
            "HISTORICAL_S01_2A_FAILURE_PRESERVED": "PASS",
            "TOKEN_SPAN_RULE": "PASS" if spans_pass else "FAIL",
            "S01_2B_AUDIT_RECONCILIATION": "PASS" if b_audit_pass else "FAIL",
            "QUARTET_SUPPORT": "PASS" if support_pass else "FAIL",
        },
        "complete": True,
    }
    disposition = {
        "disposition_id": "FASS01_S01_2C_MINIMAL_COVER_ALIGNMENT_DISPOSITION_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2C-v01",
        "S01_2A_TOKEN_ALIGNMENT": "TOKENIZER_ALIGNMENT_FAIL_CLOSED",
        "S01_2B_BOUNDARY_AUDIT_COMPLETE": True,
        "S01_2C_MINIMAL_COVER_ALIGNMENT": "PASS" if overall_pass else "FAIL_CLOSED",
        "S01_2_FEATURE_EXTRACTION_ELIGIBLE": bool(overall_pass),
        "S01_2_MODEL_CONTACT_AUTHORIZED": False,
        "S01_3_AUTHORIZED": False,
        "tokenizer_loaded_during_S01_2C": False,
        "LFM_loaded_or_instantiated": False,
        "features_created": False,
        "next_boundary": "stop after sealing S01-2C for review",
    }
    for path, content in (
        (root / "minimal-cover-alignment-report-v01.json", report),
        (root / "phase-disposition-v01.json", disposition),
    ):
        with path.open("xb") as target:
            target.write(json.dumps(content, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
            target.flush()
            os.fsync(target.fileno())
    print(f"S01_2C_MINIMAL_COVER_ALIGNMENT={disposition['S01_2C_MINIMAL_COVER_ALIGNMENT']}")
    print(f"events={events_seen} quartets={quartets_seen} spans={span_occurrences} support_pass={support_pass}")
    print(f"alignment_assignments_sha256={output_hash}")
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
