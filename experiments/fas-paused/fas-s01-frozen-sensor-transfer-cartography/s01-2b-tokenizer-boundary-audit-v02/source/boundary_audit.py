from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PHASE1_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed")
S01_2A_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v02")
EXPECTED = {
    "corpus_sha256": "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1",
    "phase1_tree_sha256": "f6065b8163799239e0d7b1200b5dda4aad169772ead14b999130a473ff9d9049",
    "phase2a_tree_sha256": "aad22fe9487928a016d70c3c91bee8095c2fe8db1a8f4b19df30d9fae4f0a2a0",
    "protocol_root_sha256": "67644d4a99b9c84f312caac591e00e2a12903cea0433832868aa35dce2b5d6f9",
    "alignment_sha256": "c8589ed5325f4bbd6a3965b598044d97c3d74704ef9c6f63d428414c68132f46",
    "report_sha256": "843217f7ce448d3361da048d9a3d5fcc8e4e7aaabb2b94d86de7d077bdbcb61a",
    "disposition_sha256": "81d7fe88b52fc8275fa4f15ef69ac2b78343875e7c9feb06d611daf1e82569be",
    "assets_sha256": "c5e9a5b08ec5658ef2a8760d8230bbe9367bea124451488e164baf0eeca95afc",
    "feature_contract_sha256": "08ddd42795d71d9b598da5015d5541316c6cf1f2c0761ce3c0890229cda4d5b0",
    "tokenizer_commit": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
}
SPAN_TYPES = ("context", "entity", "relation")
NONSEMANTIC_CATEGORIES = {"no_spill", "whitespace only", "punctuation only", "whitespace + punctuation"}


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def canonical_tree(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8") for item in entries)


def verify_tree(root: Path, seal_relative: str, expected_root: str) -> dict[str, dict[str, Any]]:
    seal_path = root / Path(*seal_relative.split("/"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal["root_sha256"] != expected_root:
        raise RuntimeError(f"unexpected result-tree root at {root}")
    declared = seal["entries"]
    declared_paths = [item["path"] for item in declared]
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != seal_path
    )
    if actual_paths != declared_paths:
        raise RuntimeError(f"file set does not reproduce result-tree seal at {root}")
    canonical = bytearray()
    verified: dict[str, dict[str, Any]] = {}
    for item in declared:
        path = root.joinpath(*item["path"].split("/"))
        digest, size = hash_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"result-tree entry mismatch: {item['path']}")
        canonical.extend(f"{item['path']}\t{size}\t{digest}\n".encode("utf-8"))
        verified[item["path"]] = item
    if hashlib.sha256(canonical).hexdigest() != expected_root:
        raise RuntimeError(f"result-tree root does not reproduce at {root}")
    return verified


def verify_preflight(run_root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    seal_path = run_root / "seals" / "preflight-seal-v02.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    canonical = bytearray()
    observed: set[str] = set()
    for item in seal["entries"]:
        relative = item["path"]
        observed.add(relative)
        digest, size = hash_file(run_root.joinpath(*relative.split("/")))
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"preflight input changed: {relative}")
        canonical.extend(f"{relative}\t{size}\t{digest}\n".encode("utf-8"))
    root_hash = hashlib.sha256(canonical).hexdigest()
    if root_hash != seal["root_sha256"]:
        raise RuntimeError("preflight seal does not reproduce")
    expected_paths = {
        "README.md",
        "inputs/boundary-audit-contract-v02.json",
        "inputs/audit-input-binding-v02.json",
        "source/boundary_audit.py",
        "source/seal_preflight.py",
        "source/seal_result.py",
    }
    if observed != expected_paths:
        raise RuntimeError("preflight artifact set differs from the frozen set")
    contract = json.loads((run_root / "inputs" / "boundary-audit-contract-v02.json").read_text(encoding="utf-8"))
    binding = json.loads((run_root / "inputs" / "audit-input-binding-v02.json").read_text(encoding="utf-8"))
    if contract.get("phase_id") != "S01-2B-v02":
        raise RuntimeError("audit contract identity is not S01-2B-v02")
    if contract["parent_identity"]["S01_2A_result_tree_root_sha256"] != EXPECTED["phase2a_tree_sha256"]:
        raise RuntimeError("contract parent S01-2A root mismatch")
    if binding["input_hashes"] != {
        "S01_2_corpus_sha256": EXPECTED["corpus_sha256"],
        "S01_2_result_tree_root_sha256": EXPECTED["phase1_tree_sha256"],
        "S01_2A_result_tree_root_sha256": EXPECTED["phase2a_tree_sha256"],
        "S01_2A_alignment_records_sha256": EXPECTED["alignment_sha256"],
        "S01_2A_report_sha256": EXPECTED["report_sha256"],
        "S01_2A_disposition_sha256": EXPECTED["disposition_sha256"],
        "S01_2A_tokenizer_assets_sha256": EXPECTED["assets_sha256"],
    }:
        raise RuntimeError("input binding does not match sealed S01-2 and S01-2A hashes")
    return contract, binding, root_hash


def verify_inputs(contract: dict[str, Any]) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    s01_entries = verify_tree(PHASE1_ROOT, "seals/result-tree-seal-v01.json", EXPECTED["phase1_tree_sha256"])
    a_entries = verify_tree(S01_2A_ROOT, "seals/result-tree-seal-v01.json", EXPECTED["phase2a_tree_sha256"])
    corpus_path = PHASE1_ROOT / "corpus" / "counterfactual-quartets-v01.jsonl"
    alignment_path = S01_2A_ROOT / "alignment-records-v01.jsonl"
    report_path = S01_2A_ROOT / "tokenizer-alignment-report-v01.json"
    disposition_path = S01_2A_ROOT / "phase-disposition-v01.json"
    assets_path = S01_2A_ROOT / "tokenizer-assets-manifest-v01.json"
    corpus_digest, _ = hash_file(corpus_path)
    if corpus_digest != EXPECTED["corpus_sha256"]:
        raise RuntimeError("sealed corpus hash changed")
    for path, expected_sha in (
        (alignment_path, EXPECTED["alignment_sha256"]),
        (report_path, EXPECTED["report_sha256"]),
        (disposition_path, EXPECTED["disposition_sha256"]),
        (assets_path, EXPECTED["assets_sha256"]),
    ):
        digest, _ = hash_file(path)
        if digest != expected_sha:
            raise RuntimeError(f"sealed S01-2A input hash changed: {path.name}")
    if s01_entries["corpus/counterfactual-quartets-v01.jsonl"]["sha256"] != EXPECTED["corpus_sha256"]:
        raise RuntimeError("S01-2 result seal does not bind the authorized corpus")
    if a_entries["alignment-records-v01.jsonl"]["sha256"] != EXPECTED["alignment_sha256"]:
        raise RuntimeError("S01-2A result seal does not bind the authorized alignment output")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    disposition = json.loads(disposition_path.read_text(encoding="utf-8"))
    assets = json.loads(assets_path.read_text(encoding="utf-8"))
    if report["status"] != "TOKENIZER_ALIGNMENT_FAIL_CLOSED" or disposition["S01_2_TOKEN_ALIGNMENT_READY"] is not False:
        raise RuntimeError("S01-2A failed disposition does not match the contracted input state")
    if report["model_instantiated"] or report["model_weights_downloaded_or_loaded"] or report["feature_extraction_performed"]:
        raise RuntimeError("S01-2A report violates the no-feature boundary")
    if assets["resolved_commit"] != EXPECTED["tokenizer_commit"] or assets["model_weights_downloaded_or_loaded"]:
        raise RuntimeError("S01-2A tokenizer provenance is inconsistent")
    if report["rendered_inputs_seen"] != 106496 or report["quartets_seen"] != 26624:
        raise RuntimeError("S01-2A report does not bind the complete expected corpus")
    if report["alignment_records_sha256"] != EXPECTED["alignment_sha256"]:
        raise RuntimeError("S01-2A report alignment hash mismatch")
    if contract["input_contract"]["expected_span_occurrences"] != 638976:
        raise RuntimeError("audit span count differs from the frozen S01-2B contract")
    return corpus_path, alignment_path, report, disposition


def character_class(character: str) -> str:
    if character.isspace():
        return "whitespace"
    category = unicodedata.category(character)
    if category.startswith("P"):
        return "punctuation"
    if category[0] in ("L", "N", "M"):
        return "semantic"
    return "other"


def spill_category(text: str, anomaly: bool = False) -> str:
    if anomaly:
        return "special-token / offset anomaly"
    if not text:
        return "no_spill"
    classes = {character_class(character) for character in text}
    if "semantic" in classes:
        return "adjacent semantic characters"
    if "other" in classes:
        return "other"
    if classes == {"whitespace", "punctuation"}:
        return "whitespace + punctuation"
    if classes == {"whitespace"}:
        return "whitespace only"
    if classes == {"punctuation"}:
        return "punctuation only"
    return "other"


def cover_status(intervals: list[tuple[int, int, int]], start: int, end: int) -> str:
    if not intervals:
        return "NO_TOKEN"
    cursor = start
    has_gap = False
    has_overlap = False
    for left, right, _ in sorted(intervals, key=lambda item: (item[0], item[1], item[2])):
        if left > cursor:
            has_gap = True
        elif left < cursor:
            has_overlap = True
        cursor = max(cursor, right)
    if cursor < end:
        has_gap = True
    if has_gap and has_overlap:
        return "GAP_AND_OVERLAP"
    if has_gap:
        return "GAP"
    if has_overlap:
        return "OVERLAP"
    return "EXACT_ONCE"


def audit_span(
    *,
    input_text: str,
    offsets: list[list[int]],
    special_mask: list[int],
    span: dict[str, Any],
    source_alignment: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    start, end = int(span["start"]), int(span["end"])
    if start < 0 or end <= start or end > len(input_text):
        raise RuntimeError("sealed source span is out of bounds or empty")

    intersections: list[tuple[int, int, int, int, int]] = []
    selected_positions: list[int] = []
    crossing_tokens: list[dict[str, Any]] = []
    anomaly_positions: list[int] = []
    for position, (pair, special) in enumerate(zip(offsets, special_mask, strict=True)):
        if len(pair) != 2:
            raise RuntimeError("offset row is not a pair")
        token_start, token_end = int(pair[0]), int(pair[1])
        valid = 0 <= token_start <= token_end <= len(input_text)
        if special not in (0, 1):
            anomaly_positions.append(position)
            continue
        if special == 1:
            if valid and token_end > token_start and token_start < end and token_end > start:
                anomaly_positions.append(position)
            continue
        if not valid:
            anomaly_positions.append(position)
            continue
        if token_start == token_end:
            if start <= token_start <= end:
                anomaly_positions.append(position)
            continue
        if token_start < end and token_end > start:
            selected_positions.append(position)
            clipped_start = max(start, token_start)
            clipped_end = min(end, token_end)
            intersections.append((clipped_start, clipped_end, position, token_start, token_end))
            if token_start < start or token_end > end:
                left_text = input_text[token_start:start] if token_start < start else ""
                right_text = input_text[end:token_end] if token_end > end else ""
                both = left_text + right_text
                crossing_tokens.append({
                    "token_position": position,
                    "token_id": metadata["token_ids"][position],
                    "token_offsets": [token_start, token_end],
                    "token_text": input_text[token_start:token_end],
                    "left_spill_text": left_text,
                    "right_spill_text": right_text,
                    "left_spill_width": len(left_text),
                    "right_spill_width": len(right_text),
                    "left_spill_category": spill_category(left_text),
                    "right_spill_category": spill_category(right_text),
                    "combined_spill_category": spill_category(both),
                })

    candidate_anomaly = bool(anomaly_positions)
    coverage = cover_status([(l, r, p) for l, r, p, _, _ in intersections], start, end)
    if candidate_anomaly:
        coverage = "SPECIAL_OR_OFFSET_ANOMALY"
    if intersections:
        cover_start = min(item[3] for item in intersections)
        cover_end = max(item[4] for item in intersections)
        left_cover = input_text[cover_start:start] if cover_start < start else ""
        right_cover = input_text[end:cover_end] if cover_end > end else ""
    else:
        cover_start = None
        cover_end = None
        left_cover = ""
        right_cover = ""
    combined_cover = left_cover + right_cover
    cover_category = spill_category(combined_cover, anomaly=candidate_anomaly)
    exact_coverage = coverage == "EXACT_ONCE"
    nonsemantic_candidate = exact_coverage and cover_category in NONSEMANTIC_CATEGORIES
    whitespace_candidate = exact_coverage and cover_category in {"no_spill", "whitespace only"}

    mapping = next((item for item in source_alignment["span_mappings"].get(metadata["span_type"], [])
                   if int(item["occurrence"]) == int(span["occurrence"])), None)
    if mapping is None:
        raise RuntimeError("S01-2A output lacks a source span occurrence")
    reported_reason = mapping["failure_reason"]
    if (reported_reason == "token_offset_crosses_span_boundary") != bool(crossing_tokens):
        metadata["failure_reconciliation_mismatches"].append({
            "event_id": metadata["event_id"],
            "span_type": metadata["span_type"],
            "occurrence": int(span["occurrence"]),
            "reported_reason": reported_reason,
            "reconstructed_crossing_token_count": len(crossing_tokens),
        })

    position_decile = min(9, (start * 10) // max(1, len(input_text)))
    return {
        "quartet_id": metadata["quartet_id"],
        "event_id": metadata["event_id"],
        "variant_id": metadata["variant_id"],
        "track_id": metadata["track_id"],
        "span_type": metadata["span_type"],
        "occurrence_index": int(span["occurrence"]),
        "template_identity": {
            "observation_template_id": metadata["observation_template_id"],
            "query_template_id": metadata["query_template_id"],
        },
        "term_identity": metadata["term_identity"],
        "character_span": [start, end],
        "input_character_length": len(input_text),
        "position_decile": position_decile,
        "source_alignment_status": mapping["status"],
        "source_alignment_failure_reason": reported_reason,
        "crossing_token_count": len(crossing_tokens),
        "crossing_tokens": crossing_tokens,
        "anomalous_token_positions": anomaly_positions,
        "minimal_cover": {
            "selected_token_positions": selected_positions,
            "character_span": None if cover_start is None else [cover_start, cover_end],
            "left_spill_text": left_cover,
            "right_spill_text": right_cover,
            "left_spill_width": len(left_cover),
            "right_spill_width": len(right_cover),
            "total_spill_width": len(combined_cover),
            "spill_category": cover_category,
            "coverage_status": coverage,
            "diagnostic_nonsemantic_only_candidate": nonsemantic_candidate,
            "diagnostic_whitespace_only_candidate": whitespace_candidate,
        },
    }


def new_aggregate() -> dict[str, Any]:
    return {
        "span_occurrences": 0,
        "spans_with_crossing_tokens": 0,
        "crossing_token_count_histogram": Counter(),
        "cover_spill_category_counts": Counter(),
        "crossing_token_spill_category_counts": Counter(),
        "coverage_status_counts": Counter(),
        "diagnostic_nonsemantic_only_candidate_count": 0,
        "diagnostic_whitespace_only_candidate_count": 0,
        "left_cover_spill_width_histogram": Counter(),
        "right_cover_spill_width_histogram": Counter(),
        "total_cover_spill_width_histogram": Counter(),
        "left_token_spill_width_histogram": Counter(),
        "right_token_spill_width_histogram": Counter(),
    }


def update_aggregate(aggregate: dict[str, Any], item: dict[str, Any]) -> None:
    cover = item["minimal_cover"]
    count = item["crossing_token_count"]
    aggregate["span_occurrences"] += 1
    aggregate["spans_with_crossing_tokens"] += int(count > 0)
    aggregate["crossing_token_count_histogram"][str(count)] += 1
    aggregate["cover_spill_category_counts"][cover["spill_category"]] += 1
    aggregate["coverage_status_counts"][cover["coverage_status"]] += 1
    aggregate["diagnostic_nonsemantic_only_candidate_count"] += int(cover["diagnostic_nonsemantic_only_candidate"])
    aggregate["diagnostic_whitespace_only_candidate_count"] += int(cover["diagnostic_whitespace_only_candidate"])
    aggregate["left_cover_spill_width_histogram"][str(cover["left_spill_width"])] += 1
    aggregate["right_cover_spill_width_histogram"][str(cover["right_spill_width"])] += 1
    aggregate["total_cover_spill_width_histogram"][str(cover["total_spill_width"])] += 1
    for token in item["crossing_tokens"]:
        aggregate["left_token_spill_width_histogram"][str(token["left_spill_width"])] += 1
        aggregate["right_token_spill_width_histogram"][str(token["right_spill_width"])] += 1
        aggregate["crossing_token_spill_category_counts"][token["combined_spill_category"]] += 1


def quantile_from_histogram(histogram: Counter[str], quantile: float) -> int | None:
    total = sum(histogram.values())
    if total == 0:
        return None
    target = math.ceil(quantile * total)
    cumulative = 0
    for value in sorted((int(key) for key in histogram)):
        cumulative += histogram[str(value)]
        if cumulative >= target:
            return value
    raise RuntimeError("histogram quantile rank was not reached")


def freeze_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    frozen: dict[str, Any] = {}
    for key, value in aggregate.items():
        if isinstance(value, Counter):
            frozen[key] = dict(sorted(value.items(), key=lambda pair: int(pair[0]) if str(pair[0]).isdigit() else str(pair[0])))
        else:
            frozen[key] = value
    frozen["total_cover_spill_width_quantiles_nearest_rank"] = {
        "p50": quantile_from_histogram(aggregate["total_cover_spill_width_histogram"], 0.5),
        "p95": quantile_from_histogram(aggregate["total_cover_spill_width_histogram"], 0.95),
    }
    return frozen


def run_self_tests() -> None:
    expected = {
        "": "no_spill",
        " \t": "whitespace only",
        ",.!": "punctuation only",
        " ,": "whitespace + punctuation",
        "K": "adjacent semantic characters",
        "$": "other",
    }
    for value, category in expected.items():
        if spill_category(value) != category:
            raise RuntimeError(f"spill classifier self-test failed for {value!r}")
    if spill_category("A", anomaly=True) != "special-token / offset anomaly":
        raise RuntimeError("anomaly priority self-test failed")
    if cover_status([(1, 3, 0), (3, 5, 1)], 1, 5) != "EXACT_ONCE":
        raise RuntimeError("exact coverage self-test failed")
    if cover_status([(1, 2, 0), (3, 5, 1)], 1, 5) != "GAP":
        raise RuntimeError("gap self-test failed")
    if cover_status([(1, 4, 0), (3, 5, 1)], 1, 5) != "OVERLAP":
        raise RuntimeError("overlap self-test failed")
    if cover_status([(1, 2, 0), (2, 4, 1), (3, 5, 2)], 1, 6) != "GAP_AND_OVERLAP":
        raise RuntimeError("mixed gap/overlap self-test failed")
    if quartet_candidate_flags([(True, True)] * 4) != (True, True):
        raise RuntimeError("all-positive quartet reducer self-test failed")
    if quartet_candidate_flags([(True, True), (False, True), (True, True), (True, True)]) != (False, True):
        raise RuntimeError("nonsemantic quartet reducer self-test failed")
    if quartet_candidate_flags([(True, True), (True, False), (True, True), (True, True)]) != (True, False):
        raise RuntimeError("whitespace quartet reducer self-test failed")


def quartet_candidate_flags(variant_flags: list[tuple[bool, bool]]) -> tuple[bool, bool]:
    if len(variant_flags) != 4:
        raise ValueError("candidate reduction requires exactly four variants")
    return (
        all(nonsemantic for nonsemantic, _ in variant_flags),
        all(whitespace_only for _, whitespace_only in variant_flags),
    )


def run(run_root: Path) -> int:
    run_root = run_root.resolve()
    contract, binding, preflight_root = verify_preflight(run_root)
    corpus_path, alignment_path, source_report, source_disposition = verify_inputs(contract)

    audit_path = run_root / "boundary-span-audit-v02.jsonl"
    digest = hashlib.sha256()
    total_bytes = 0
    total_events = 0
    total_quartets = 0
    total_spans = 0
    original_failed_spans = 0
    original_failed_by_type: Counter[str] = Counter()
    spans_with_crossings = 0
    crossing_token_total = 0
    event_ids: set[str] = set()
    reason_counts: Counter[str] = Counter()
    type_aggs: dict[str, dict[str, Any]] = {span_type: new_aggregate() for span_type in SPAN_TYPES}
    category_aggs: dict[str, dict[str, Any]] = defaultdict(new_aggregate)
    template_aggs: dict[str, dict[str, Any]] = defaultdict(new_aggregate)
    term_aggs: dict[str, dict[str, Any]] = defaultdict(new_aggregate)
    position_aggs: dict[str, dict[str, Any]] = defaultdict(new_aggregate)
    failure_reconciliation_mismatches: list[dict[str, Any]] = []
    quartet_candidate_counts = Counter()
    original_rejected_events = 0
    actual_token_total = 0

    if audit_path.exists():
        raise RuntimeError("audit JSONL already exists; refusing to overwrite")
    with corpus_path.open("r", encoding="utf-8") as corpus, alignment_path.open("r", encoding="utf-8") as aligned, audit_path.open("xb") as output:
        for corpus_line_number, corpus_line in enumerate(corpus, start=1):
            quartet = json.loads(corpus_line)
            total_quartets += 1
            if len(quartet["variants"]) != 4:
                raise RuntimeError(f"quartet cardinality mismatch at corpus line {corpus_line_number}")
            variant_candidate_flags: list[tuple[bool, bool]] = []
            quartet_rows = 0
            for variant in quartet["variants"]:
                source_row = json.loads(next(aligned))
                total_events += 1
                quartet_rows += 1
                event_id = variant["event_id"]
                if event_id in event_ids:
                    raise RuntimeError(f"duplicate source event id: {event_id}")
                event_ids.add(event_id)
                if (source_row["quartet_id"], source_row["event_id"], source_row["variant_id"]) != (quartet["quartet_id"], event_id, variant["variant_id"]):
                    raise RuntimeError(f"S01-2A row identity order mismatch for {event_id}")
                if source_row["input_sha256"] != variant["input_sha256"]:
                    raise RuntimeError(f"input identity mismatch for {event_id}")
                if source_row["model_id"] != "LiquidAI/LFM2.5-1.2B-Base" or source_row["model_revision"] != EXPECTED["tokenizer_commit"]:
                    raise RuntimeError(f"tokenizer row provenance mismatch for {event_id}")
                input_text = variant["input_text"]
                if not input_text.isascii() or hashlib.sha256(input_text.encode("ascii")).hexdigest() != variant["input_sha256"]:
                    raise RuntimeError(f"sealed input text/hash mismatch for {event_id}")
                token_ids = source_row["token_ids"]
                offsets = source_row["offset_mapping"]
                special_mask = source_row["special_tokens_mask"]
                if token_ids is None or offsets is None or special_mask is None:
                    raise RuntimeError(f"sealed S01-2A row lacks tokenization output: {event_id}")
                if len(token_ids) != len(offsets) or len(token_ids) != len(special_mask) or len(token_ids) != source_row["sequence_length"]:
                    raise RuntimeError(f"token, offset, and special-mask lengths differ for {event_id}")
                token_hash = hashlib.sha256()
                for token_id in token_ids:
                    if int(token_id) < 0 or int(token_id) > 0xFFFFFFFF:
                        raise RuntimeError(f"token ID outside u32 at {event_id}")
                    token_hash.update(struct.pack("<I", int(token_id)))
                if token_hash.hexdigest() != source_row["token_ids_sha256"]:
                    raise RuntimeError(f"token ID hash mismatch for {event_id}")
                actual_token_total += len(token_ids)
                original_rejected_events += int(source_row["alignment_status"] == "REJECT")
                variant_nonsemantic = True
                variant_whitespace = True
                for span_type in SPAN_TYPES:
                    term_identity: dict[str, Any]
                    if span_type == "context":
                        term_identity = {"term_id": variant["context_term_id"], "surface": variant["context_term"], "split": variant["context_term_split"]}
                    elif span_type == "entity":
                        term_identity = {"term_id": variant["entity_term_id"], "surface": variant["entity_term"], "split": variant["entity_term_split"]}
                    else:
                        term_identity = {"term_id": quartet["relation_id"], "surface": quartet["relation_surface"], "split": "RELATION_INVENTORY"}
                    spans = variant["character_spans"].get(span_type, [])
                    if not spans:
                        raise RuntimeError(f"required span missing for {event_id}:{span_type}")
                    for span in spans:
                        metadata = {
                            "quartet_id": quartet["quartet_id"],
                            "event_id": event_id,
                            "variant_id": variant["variant_id"],
                            "track_id": quartet["track_id"],
                            "span_type": span_type,
                            "observation_template_id": variant["observation_template_id"],
                            "query_template_id": variant["query_template_id"],
                            "term_identity": term_identity,
                            "token_ids": token_ids,
                            "failure_reconciliation_mismatches": failure_reconciliation_mismatches,
                        }
                        item = audit_span(
                            input_text=input_text,
                            offsets=offsets,
                            special_mask=special_mask,
                            span=span,
                            source_alignment=source_row,
                            metadata=metadata,
                        )
                        total_spans += 1
                        original_failed_spans += int(item["source_alignment_status"] == "REJECT")
                        original_failed_by_type[span_type] += int(item["source_alignment_status"] == "REJECT")
                        count_cross = item["crossing_token_count"]
                        spans_with_crossings += int(count_cross > 0)
                        crossing_token_total += count_cross
                        reason_counts[item["source_alignment_failure_reason"] or "PASS"] += 1
                        cover = item["minimal_cover"]
                        variant_nonsemantic = variant_nonsemantic and cover["diagnostic_nonsemantic_only_candidate"]
                        variant_whitespace = variant_whitespace and cover["diagnostic_whitespace_only_candidate"]

                        serialized = json_bytes(item) + b"\n"
                        output.write(serialized)
                        digest.update(serialized)
                        total_bytes += len(serialized)

                        category_key = f"{span_type}|{cover['spill_category']}"
                        template_key = f"{span_type}|obs={variant['observation_template_id']}|query={variant['query_template_id']}"
                        term_key = f"{span_type}|id={term_identity['term_id']}|surface={term_identity['surface']}|split={term_identity['split']}"
                        position_key = f"{span_type}|decile={item['position_decile']}"
                        update_aggregate(type_aggs[span_type], item)
                        update_aggregate(category_aggs[category_key], item)
                        update_aggregate(template_aggs[template_key], item)
                        update_aggregate(term_aggs[term_key], item)
                        update_aggregate(position_aggs[position_key], item)
                variant_candidate_flags.append((variant_nonsemantic, variant_whitespace))
            if quartet_rows != 4:
                raise RuntimeError(f"quartet {quartet['quartet_id']} did not reconcile to four events")
            all_variants_nonsemantic, all_variants_whitespace = quartet_candidate_flags(variant_candidate_flags)
            quartet_candidate_counts["nonsemantic_only_complete_quartets"] += int(all_variants_nonsemantic)
            quartet_candidate_counts["whitespace_only_complete_quartets"] += int(all_variants_whitespace)
            if not all_variants_nonsemantic:
                quartet_candidate_counts["nonsemantic_only_ineligible_quartets"] += 1
            if not all_variants_whitespace:
                quartet_candidate_counts["whitespace_only_ineligible_quartets"] += 1
        output.flush()
        import os
        os.fsync(output.fileno())
        if aligned.readline() != "":
            raise RuntimeError("S01-2A alignment output has trailing rows after the sealed corpus")

    if total_events != 106496 or total_quartets != 26624 or total_spans != 638976:
        raise RuntimeError(f"audit completeness count mismatch: events={total_events}, quartets={total_quartets}, spans={total_spans}")
    if original_rejected_events != source_report["rejected_input_count"]:
        raise RuntimeError("rejected event count differs from the sealed S01-2A report")
    expected_failure_counts = {"context": 191872, "entity": 200704, "relation": 212992}
    for span_type, expected_failures in expected_failure_counts.items():
        if source_report["span_occurrence_counts"][span_type]["failed_occurrences"] != expected_failures:
            raise RuntimeError(f"sealed S01-2A failure count differs from the binding for {span_type}")
        if original_failed_by_type[span_type] != expected_failures:
            raise RuntimeError(f"reconciled S01-2A failure count differs for {span_type}")
    if len(failure_reconciliation_mismatches) > 0:
        raise RuntimeError(f"reconstructed crossing-token failures disagree with S01-2A in {len(failure_reconciliation_mismatches)} occurrences")

    for group in (type_aggs, category_aggs, template_aggs, term_aggs, position_aggs):
        for key, value in list(group.items()):
            group[key] = freeze_aggregate(value)
    audit_sha = digest.hexdigest()
    audit_report = {
        "report_id": "FASS01_S01_2B_BOUNDARY_AUDIT_REPORT_V02",
        "status": "BOUNDARY_AUDIT_COMPLETE",
        "phase_id": "S01-2B-v02",
        "preflight_root_sha256": preflight_root,
        "corpus_sha256": EXPECTED["corpus_sha256"],
        "S01_2_result_tree_root_sha256": EXPECTED["phase1_tree_sha256"],
        "S01_2A_result_tree_root_sha256": EXPECTED["phase2a_tree_sha256"],
        "S01_2A_alignment_records_sha256": EXPECTED["alignment_sha256"],
        "S01_2A_report_sha256": EXPECTED["report_sha256"],
        "S01_2A_disposition_sha256": EXPECTED["disposition_sha256"],
        "S01_2A_tokenizer_assets_sha256": EXPECTED["assets_sha256"],
        "S01_2A_original_status": source_report["status"],
        "S01_2A_original_disposition_preserved": source_disposition["tokenizer_alignment_status"] == "TOKENIZER_ALIGNMENT_FAIL_CLOSED",
        "tokenizer_loaded_during_S01_2B": False,
        "LFM_loaded_or_instantiated": False,
        "feature_extraction_performed": False,
        "probe_training_performed": False,
        "geometry_analysis_performed": False,
        "quartets_reconciled": total_quartets,
        "events_reconciled": total_events,
        "span_occurrences_reconciled": total_spans,
        "originally_failed_span_occurrences": original_failed_spans,
        "spans_with_boundary_crossings": spans_with_crossings,
        "crossing_token_total": crossing_token_total,
        "source_failure_reason_counts": dict(sorted(reason_counts.items(), key=lambda item: str(item[0]))),
        "failure_reconciliation_mismatches": failure_reconciliation_mismatches,
        "token_positions_reconciled": actual_token_total,
        "audit_jsonl_sha256": audit_sha,
        "audit_jsonl_bytes": total_bytes,
        "aggregates": {
            "by_span_type": type_aggs,
            "by_span_type_and_minimal_cover_category": category_aggs,
            "by_span_type_and_template_pair": template_aggs,
            "by_span_type_and_term_identity": term_aggs,
            "by_span_type_and_string_position_decile": position_aggs,
        },
        "minimal_cover_diagnostics_not_adopted": {
            "diagnostic_nonsemantic_only_complete_quartets": quartet_candidate_counts["nonsemantic_only_complete_quartets"],
            "diagnostic_nonsemantic_only_ineligible_quartets": quartet_candidate_counts["nonsemantic_only_ineligible_quartets"],
            "diagnostic_whitespace_only_complete_quartets": quartet_candidate_counts["whitespace_only_complete_quartets"],
            "diagnostic_whitespace_only_ineligible_quartets": quartet_candidate_counts["whitespace_only_ineligible_quartets"],
            "interpretation": "Read-only counterfactual diagnostics only; no alignment rule or spill allowlist is adopted.",
        },
        "complete": True,
    }
    audit_report["supersedes_unsealed_attempt"] = {
        "phase_id": "S01-2B-v01",
        "preflight_root_sha256": "2d540a0474d3da63e6b70a434c205a1b85d8ae55a7f41b6087c199956bbff217",
        "result_tree_seal_created": False,
        "reason": "implementation defect in spill-category matching and quartet-level flag reduction; source inputs and S01-2A disposition were unchanged",
    }
    write_json(run_root / "boundary-audit-report-v02.json", audit_report)
    disposition = {
        "disposition_id": "FASS01_S01_2B_BOUNDARY_AUDIT_DISPOSITION_V02",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2B-v02",
        "S01_2A_TOKENIZER_ALIGNMENT_FAIL_CLOSED": True,
        "S01_2B_BOUNDARY_AUDIT_COMPLETE": True,
        "S01_2_FEATURE_EXTRACTION_ELIGIBLE": False,
        "S01_2_MODEL_CONTACT_AUTHORIZED": False,
        "S01_3_AUTHORIZED": False,
        "tokenizer_loaded": False,
        "LFM_loaded": False,
        "features_created": False,
        "rule_adopted": False,
        "source_S01_2A_disposition_sha256": EXPECTED["disposition_sha256"],
        "next_boundary": "stop after sealing the read-only tokenizer-boundary audit",
    }
    write_json(run_root / "phase-disposition-v02.json", disposition)
    print(json.dumps({
        "status": audit_report["status"],
        "events": total_events,
        "span_occurrences": total_spans,
        "spans_with_boundary_crossings": spans_with_crossings,
        "crossing_tokens": crossing_token_total,
        "audit_sha256": audit_sha,
        "minimal_cover_diagnostics": audit_report["minimal_cover_diagnostics_not_adopted"],
    }, separators=(",", ":")))
    return 0


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with path.open("xb") as output:
        output.write(payload)
        output.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only S01-2B tokenizer-boundary audit")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_tests()
        print("self_test=PASS")
        return 0
    contract, _, preflight_root = verify_preflight(args.run_root.resolve())
    if args.preflight_only:
        corpus, alignment, _, _ = verify_inputs(contract)
        print(json.dumps({
            "preflight": "PASS",
            "preflight_root_sha256": preflight_root,
            "corpus": str(corpus),
            "alignment": str(alignment),
            "tokenizer_loaded": False,
            "model_loaded": False,
        }, separators=(",", ":")))
        return 0
    return run(args.run_root)


if __name__ == "__main__":
    sys.exit(main())
