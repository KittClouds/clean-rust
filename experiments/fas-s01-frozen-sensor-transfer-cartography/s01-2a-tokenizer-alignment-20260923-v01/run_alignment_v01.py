from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi
from transformers import AutoTokenizer, __version__ as transformers_version
import tokenizers


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
EXPECTED_PROTOCOL_ROOT = "67644d4a99b9c84f312caac591e00e2a12903cea0433832868aa35dce2b5d6f9"
EXPECTED_CORPUS_SHA256 = "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1"
EXPECTED_TREE_ROOT = "f6065b8163799239e0d7b1200b5dda4aad169772ead14b999130a473ff9d9049"
EXPECTED_QUARTETS = 26_624
EXPECTED_EVENTS = 106_496
REPEAT_SAMPLE_SIZE = 256
REPEAT_SAMPLE_DOMAIN = b"FAS-S01-2A-REPEAT-SAMPLE-V01\x00"

SEALED_ROOT = Path(
    r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed"
)
OUTPUT_ROOT = Path(
    r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v01"
)
TOKENIZER_ROOT = OUTPUT_ROOT / "tokenizer"
CORPUS_PATH = SEALED_ROOT / "corpus" / "counterfactual-quartets-v01.jsonl"
RESULT_SEAL_PATH = SEALED_ROOT / "seals" / "result-tree-seal-v01.json"
DISPOSITION_PATH = SEALED_ROOT / "phase-disposition-v01.json"
PROTOCOL_SEAL_PATH = SEALED_ROOT / "seals" / "protocol-seal-v01.json"

SPAN_TYPES = ("context", "entity", "relation")
VARIANT_IDS = ("A", "C", "E", "P")
VIEWS = (
    "V0_MEAN_FULL",
    "V1_FINAL_POSITION",
    "V2_FIRST_POSITION",
    "V3_CONTEXT_SPAN_MEAN",
    "V4_ENTITY_SPAN_MEAN",
    "V5_RELATION_SPAN_MEAN",
    "V6_FIXED_SPAN_CONCAT",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_sealed_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = json.loads(
        (SEALED_ROOT / "corpus" / "corpus-manifest-v01.json").read_text(encoding="utf-8")
    )
    validation = json.loads(
        (SEALED_ROOT / "validation-report-v01.json").read_text(encoding="utf-8")
    )
    disposition = json.loads(DISPOSITION_PATH.read_text(encoding="utf-8"))
    tree_seal = json.loads(RESULT_SEAL_PATH.read_text(encoding="utf-8"))
    protocol_seal = json.loads(PROTOCOL_SEAL_PATH.read_text(encoding="utf-8"))

    if sha256_file(CORPUS_PATH) != EXPECTED_CORPUS_SHA256:
        raise RuntimeError("sealed corpus byte hash differs from authorized identity")
    if manifest.get("corpus_sha256") != EXPECTED_CORPUS_SHA256:
        raise RuntimeError("corpus manifest hash differs from authorized identity")
    if manifest.get("rendered_input_count") != EXPECTED_EVENTS:
        raise RuntimeError("corpus manifest event count differs from authorized identity")
    if validation.get("counts", {}).get("rendered_inputs") != EXPECTED_EVENTS:
        raise RuntimeError("validation event count differs from authorized identity")
    if disposition.get("protocol_bundle_root_sha256") != EXPECTED_PROTOCOL_ROOT:
        raise RuntimeError("sealed disposition protocol root differs from authorization")
    if protocol_seal.get("root_sha256") != EXPECTED_PROTOCOL_ROOT:
        raise RuntimeError("protocol seal root differs from authorization")
    if tree_seal.get("root_sha256") != EXPECTED_TREE_ROOT:
        raise RuntimeError("construction tree seal root differs from authorization")

    lines: list[str] = []
    for entry in sorted(tree_seal["entries"], key=lambda item: item["path"]):
        path = SEALED_ROOT / entry["path"]
        data = path.read_bytes()
        actual_hash = sha256_bytes(data)
        if len(data) != entry["bytes"] or actual_hash != entry["sha256"]:
            raise RuntimeError(f"sealed tree entry changed: {entry['path']}")
        lines.append(f"{entry['path']}\t{len(data)}\t{actual_hash}\n")
    actual_root = sha256_bytes("".join(lines).encode("utf-8"))
    if actual_root != EXPECTED_TREE_ROOT:
        raise RuntimeError("recomputed construction tree root differs from authorization")

    return manifest, validation, disposition


def verify_tokenizer_identity() -> tuple[Any, dict[str, Any]]:
    info = HfApi().model_info(MODEL_ID, revision=MODEL_REVISION, files_metadata=True)
    if info.sha != MODEL_REVISION:
        raise RuntimeError(
            f"Hub resolved a different tokenizer revision: {info.sha!r}"
        )
    allowed = {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"}
    available = {item.rfilename for item in info.siblings}
    missing = allowed - available
    if missing:
        raise RuntimeError(f"pinned repository lacks required tokenizer files: {sorted(missing)}")

    files: dict[str, dict[str, Any]] = {}
    for filename in sorted(allowed):
        path = TOKENIZER_ROOT / filename
        if not path.is_file():
            raise RuntimeError(f"authorized tokenizer payload is missing: {filename}")
        files[filename] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}

    forbidden_suffixes = (".safetensors", ".bin", ".pt", ".pth", ".onnx")
    unexpected = [
        str(path.relative_to(TOKENIZER_ROOT))
        for path in TOKENIZER_ROOT.rglob("*")
        if path.is_file()
        and path.name != ".gitattributes"
        and path.suffix.lower() in forbidden_suffixes
    ]
    if unexpected:
        raise RuntimeError(f"model/weight payload found in tokenizer staging: {unexpected}")

    tokenizer = AutoTokenizer.from_pretrained(
        TOKENIZER_ROOT,
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise RuntimeError("loaded tokenizer is not a fast tokenizer")

    return tokenizer, {
        "model_id": MODEL_ID,
        "requested_revision": MODEL_REVISION,
        "resolved_commit": info.sha,
        "tokenizer_class": type(tokenizer).__name__,
        "is_fast": bool(tokenizer.is_fast),
        "vocab_size": int(tokenizer.vocab_size),
        "bos_token_id": tokenizer.bos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
        "special_token_ids": sorted(int(value) for value in tokenizer.all_special_ids),
        "files": files,
        "model_weight_files_downloaded": 0,
        "transformers_version": transformers_version,
        "tokenizers_version": tokenizers.__version__,
    }


def make_repeat_sample() -> tuple[list[str], dict[str, Any]]:
    ranking: list[tuple[bytes, str]] = []
    quartet_count = 0
    event_count = 0
    with CORPUS_PATH.open("r", encoding="utf-8", newline="") as source:
        for line in source:
            if not line.endswith("\n"):
                raise RuntimeError("corpus record lacks required LF terminator")
            quartet = json.loads(line)
            quartet_count += 1
            for variant in quartet.get("variants", []):
                event_id = variant["event_id"]
                event_count += 1
                rank = hashlib.sha256(
                    REPEAT_SAMPLE_DOMAIN
                    + EXPECTED_CORPUS_SHA256.encode("ascii")
                    + b"\x00"
                    + event_id.encode("utf-8")
                ).digest()
                ranking.append((rank, event_id))
    if quartet_count != EXPECTED_QUARTETS or event_count != EXPECTED_EVENTS:
        raise RuntimeError(
            f"repeat-sample prepass counts differ: quartets={quartet_count} events={event_count}"
        )
    selected = sorted(ranking)[:REPEAT_SAMPLE_SIZE]
    event_ids = [event_id for _, event_id in selected]
    if len(set(event_ids)) != REPEAT_SAMPLE_SIZE:
        raise RuntimeError("repeat sample contains duplicate event IDs")
    record = {
        "sample_id": "FASS01_S01_2A_DETERMINISTIC_REPEAT_SAMPLE_V01",
        "selection_rule": "lowest SHA-256 rank of domain || corpus_sha256 || NUL || event_id",
        "domain_hex": REPEAT_SAMPLE_DOMAIN.hex(),
        "corpus_sha256": EXPECTED_CORPUS_SHA256,
        "selected_event_count": len(event_ids),
        "selected_event_ids": event_ids,
        "sample_sha256": sha256_bytes(canonical_json_bytes(event_ids)),
        "selection_completed_before_tokenizer_alignment": True,
    }
    return event_ids, record


def align_one_span(
    text: str,
    span: dict[str, Any],
    expected_surface: str,
    offsets: list[tuple[int, int]],
    special_mask: list[int],
) -> dict[str, Any]:
    start = int(span["start"])
    end = int(span["end"])
    reasons: list[str] = []
    if start < 0 or end <= start or end > len(text):
        reasons.append("INVALID_SOURCE_SPAN")
        surface = ""
    else:
        surface = text[start:end]
        if surface != expected_surface:
            reasons.append("ANNOTATION_SURFACE_MISMATCH")

    selected: list[int] = []
    crossings: list[dict[str, Any]] = []
    coverage = [0] * max(0, end - start)
    for position, (token_start, token_end) in enumerate(offsets):
        if special_mask[position] or (token_start == 0 and token_end == 0):
            continue
        if token_start < end and start < token_end:
            selected.append(position)
            if token_start < start or token_end > end:
                crossings.append(
                    {
                        "token_position": position,
                        "token_offset": [token_start, token_end],
                    }
                )
            for character in range(max(start, token_start), min(end, token_end)):
                coverage[character - start] += 1

    if not selected:
        reasons.append("NO_SELECTED_NONSPECIAL_TOKENS")
    if crossings:
        reasons.append("TOKEN_CROSSES_SPAN_BOUNDARY")
    uncovered = sum(value == 0 for value in coverage)
    multiply_covered = sum(value > 1 for value in coverage)
    if uncovered or multiply_covered:
        reasons.append("GAP_OR_OVERLAP_IN_SOURCE_COVERAGE")

    return {
        "occurrence": int(span.get("occurrence", -1)),
        "source_span": [start, end],
        "source_surface": surface,
        "expected_surface": expected_surface,
        "source_surface_matches_annotation": surface == expected_surface,
        "selected_token_positions": selected,
        "selected_token_offsets": [list(offsets[position]) for position in selected],
        "boundary_crossings": crossings,
        "source_character_coverage_min": min(coverage) if coverage else None,
        "source_character_coverage_max": max(coverage) if coverage else None,
        "uncovered_source_characters": uncovered,
        "multiply_covered_source_characters": multiply_covered,
        "rejection_reasons": sorted(set(reasons)),
        "aligned": not reasons,
    }


def encode_one(tokenizer: Any, text: str) -> dict[str, Any]:
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
        padding=False,
        return_offsets_mapping=True,
        return_special_tokens_mask=True,
    )
    ids = [int(value) for value in encoded["input_ids"]]
    offsets = [(int(pair[0]), int(pair[1])) for pair in encoded["offset_mapping"]]
    special_mask = [int(value) for value in encoded["special_tokens_mask"]]
    if not ids or len(ids) != len(offsets) or len(ids) != len(special_mask):
        raise RuntimeError("token IDs, offsets, and special-token mask have inconsistent shapes")
    if any(start < 0 or end < 0 or start > end or end > len(text) for start, end in offsets):
        raise RuntimeError("tokenizer returned an out-of-range offset")
    return {"token_ids": ids, "offsets": offsets, "special_mask": special_mask}


def align_variant(tokenizer: Any, quartet: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    text = variant["input_text"]
    raw = text.encode("utf-8")
    input_hash = sha256_bytes(raw)
    expected_input_hash = variant.get("input_sha256")
    reasons: list[str] = []
    if not text.isascii():
        reasons.append("NON_ASCII_INPUT_VIOLATES_FROZEN_OFFSET_UNIT")
    if input_hash != expected_input_hash:
        reasons.append("INPUT_SHA256_MISMATCH")

    tokenized = encode_one(tokenizer, text)
    ids = tokenized["token_ids"]
    offsets = tokenized["offsets"]
    special_mask = tokenized["special_mask"]
    span_maps: dict[str, Any] = {}
    view_positions: dict[str, list[int]] = {}
    expected_surfaces = {
        "context": variant["context_term"],
        "entity": variant["entity_term"],
        "relation": variant.get("relation_surface", quartet["relation_surface"]),
    }

    for span_type in SPAN_TYPES:
        occurrences = [
            align_one_span(text, span, expected_surfaces[span_type], offsets, special_mask)
            for span in variant["character_spans"][span_type]
        ]
        positions = sorted(
            {
                position
                for occurrence in occurrences
                for position in occurrence["selected_token_positions"]
            }
        )
        span_maps[span_type] = {
            "occurrences": occurrences,
            "deduplicated_token_positions": positions,
            "aligned": bool(occurrences) and all(item["aligned"] for item in occurrences),
        }
        view_positions[span_type] = positions
        for occurrence in occurrences:
            for reason in occurrence["rejection_reasons"]:
                reasons.append(f"{span_type}:{reason}")

    if not ids:
        reasons.append("EMPTY_TOKEN_SEQUENCE")
        first_position = None
        final_position = None
    else:
        first_position = 0
        final_position = len(ids) - 1

    ids_bytes = b"".join(struct.pack("<I", token_id) for token_id in ids)
    offset_pairs = [list(pair) for pair in offsets]
    return {
        "quartet_id": quartet["quartet_id"],
        "event_id": variant["event_id"],
        "variant_id": variant["variant_id"],
        "track_id": quartet["track_id"],
        "observation_template_id": int(variant["observation_template_id"]),
        "query_template_id": int(variant["query_template_id"]),
        "input_sha256": input_hash,
        "input_sha256_matches_sealed_annotation": input_hash == expected_input_hash,
        "token_ids": ids,
        "token_ids_sha256_le_u32": sha256_bytes(ids_bytes),
        "offset_mapping": offset_pairs,
        "offset_mapping_sha256_canonical_json": sha256_bytes(canonical_json_bytes(offset_pairs)),
        "special_tokens_mask": special_mask,
        "sequence_length": len(ids),
        "model_visible_position_count": len(ids),
        "first_model_visible_position": first_position,
        "first_model_visible_token_id": ids[first_position] if first_position is not None else None,
        "final_model_visible_position": final_position,
        "final_model_visible_token_id": ids[final_position] if final_position is not None else None,
        "span_mappings": span_maps,
        "view_span_token_positions": {
            "V3_CONTEXT_SPAN_MEAN": view_positions["context"],
            "V4_ENTITY_SPAN_MEAN": view_positions["entity"],
            "V5_RELATION_SPAN_MEAN": view_positions["relation"],
            "V6_FIXED_SPAN_CONCAT": {
                "context": view_positions["context"],
                "entity": view_positions["entity"],
                "relation": view_positions["relation"],
            },
        },
        "row_alignment_status": "ALIGNED" if not reasons else "REJECTED",
        "rejection_reasons": sorted(set(reasons)),
    }


def factorial_key(quartet: dict[str, Any]) -> str:
    return "|".join(
        (
            quartet["context_term_split"],
            quartet["entity_term_split"],
            quartet["world_family"],
            str(quartet["relation_id"]),
            str(quartet["state_id"]),
            str(quartet["observation_template_id"]),
            str(quartet["query_template_id"]),
            "FACTORIAL_BALANCED",
        )
    )


def binding_context_key(quartet: dict[str, Any]) -> str:
    return "|".join(
        (
            "BINDING_CONTEXT",
            quartet["context_term_split"],
            str(quartet["context_pair_id"]),
            quartet["entity_term_split"],
        )
    )


def binding_entity_key(quartet: dict[str, Any]) -> str:
    return "|".join(
        (
            "BINDING_ENTITY",
            quartet["entity_term_split"],
            str(quartet["entity_pair_id"]),
            quartet["context_term_split"],
        )
    )


def support_summary(
    totals: dict[str, Counter[str]], retained: dict[str, Counter[str]]
) -> dict[str, Any]:
    expected_cell_counts = {
        "FACTORIAL_BALANCED": (1536, 16),
        "BINDING_CONTEXT": (64, 16),
        "BINDING_ENTITY": (64, 16),
    }
    result: dict[str, Any] = {}
    for track, (expected_cells, expected_per_cell) in expected_cell_counts.items():
        total_map = totals[track]
        retained_map = retained[track]
        supports = [retained_map.get(key, 0) for key in total_map]
        result[track] = {
            "observed_cell_count": len(total_map),
            "expected_cell_count": expected_cells,
            "total_quartets_before_alignment_rejections": sum(total_map.values()),
            "retained_quartets_after_alignment_rejections": sum(retained_map.values()),
            "expected_quartets_per_cell": expected_per_cell,
            "minimum_retained_per_cell": min(supports, default=0),
            "maximum_retained_per_cell": max(supports, default=0),
            "cells_below_minimum": sum(value < expected_per_cell for value in supports),
            "cells_not_at_exact_expected_support": sum(value != expected_per_cell for value in supports),
            "support_gate_pass": (
                len(total_map) == expected_cells
                and len(supports) == expected_cells
                and all(value == expected_per_cell for value in supports)
                and all(value == expected_per_cell for value in total_map.values())
            ),
        }
    return result


def seal_output_tree() -> dict[str, Any]:
    seal_path = OUTPUT_ROOT / "seals" / "alignment-tree-seal-v01.json"
    entries: list[dict[str, Any]] = []
    for path in OUTPUT_ROOT.rglob("*"):
        if not path.is_file() or path == seal_path:
            continue
        relative = path.relative_to(OUTPUT_ROOT).as_posix()
        data = path.read_bytes()
        entries.append({"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)})
    entries.sort(key=lambda item: item["path"])
    lines = [f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n" for item in entries]
    root_hash = sha256_bytes("".join(lines).encode("utf-8"))
    seal = {
        "seal_id": "FASS01_S01_2A_TOKENIZER_ALIGNMENT_TREE_V01",
        "phase_id": "S01-2A-TOKENIZER-ALIGNMENT-V01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; seal file excluded",
        "entries": entries,
        "root_sha256": root_hash,
        "corpus_root_sha256": EXPECTED_CORPUS_SHA256,
        "protocol_bundle_root_sha256": EXPECTED_PROTOCOL_ROOT,
        "construction_tree_root_sha256": EXPECTED_TREE_ROOT,
        "model_loaded": False,
        "tokenizer_loaded": True,
        "feature_extraction_performed": False,
    }
    write_json(seal_path, seal)
    return seal


def main() -> int:
    if (OUTPUT_ROOT / "alignment-report-v01.json").exists() or (
        OUTPUT_ROOT / "alignment-tree-seal-v01.json"
    ).exists():
        raise RuntimeError("refusing to overwrite an existing S01-2A result")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "source").mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "seals").mkdir(parents=True, exist_ok=True)
    source_copy = OUTPUT_ROOT / "source" / "run_alignment_v01.py"
    this_file = Path(__file__).resolve()
    if this_file != source_copy.resolve():
        source_copy.write_bytes(this_file.read_bytes())

    manifest, validation, prior_disposition = verify_sealed_inputs()
    if not TOKENIZER_ROOT.is_dir():
        raise RuntimeError("tokenizer payload directory is missing")
    tokenizer, tokenizer_receipt = verify_tokenizer_identity()
    write_json(OUTPUT_ROOT / "tokenizer-identity-v01.json", tokenizer_receipt)

    sample_ids, sample_manifest = make_repeat_sample()
    selected = set(sample_ids)
    write_json(OUTPUT_ROOT / "repeat-sample-v01.json", sample_manifest)

    row_count = 0
    quartet_count = 0
    aligned_rows = 0
    rejected_rows = 0
    deterministic_repeats = 0
    deterministic_repeat_mismatches = 0
    repeated_alignment_rejections = 0
    span_totals: Counter[str] = Counter()
    span_aligned: Counter[str] = Counter()
    span_failure_reasons: Counter[str] = Counter()
    span_template_totals: Counter[str] = Counter()
    span_template_aligned: Counter[str] = Counter()
    span_template_failures: Counter[str] = Counter()
    row_rejections_by_reason: Counter[str] = Counter()
    row_rejections_by_template: Counter[str] = Counter()
    row_rejections_by_variant: Counter[str] = Counter()
    total_cells: dict[str, Counter[str]] = defaultdict(Counter)
    retained_cells: dict[str, Counter[str]] = defaultdict(Counter)
    sequence_lengths: Counter[int] = Counter()
    total_token_ids = 0
    max_sequence_length = 0

    records_path = OUTPUT_ROOT / "alignment-records-v01.jsonl"
    with CORPUS_PATH.open("r", encoding="utf-8", newline="") as source, records_path.open(
        "w", encoding="utf-8", newline="\n", buffering=1 << 20
    ) as records:
        for quartet in source:
            if not quartet.endswith("\n"):
                raise RuntimeError("corpus record lacks required LF terminator")
            q = json.loads(quartet)
            variants = q.get("variants", [])
            if len(variants) != 4 or tuple(item.get("variant_id") for item in variants) != VARIANT_IDS:
                raise RuntimeError("quartet variant inventory/order differs from frozen contract")
            quartet_count += 1
            quartet_aligned = True
            for variant in variants:
                row_count += 1
                event_id = variant["event_id"]
                result = align_variant(tokenizer, q, variant)
                ids = result["token_ids"]
                length = result["sequence_length"]
                total_token_ids += length
                max_sequence_length = max(max_sequence_length, length)
                sequence_lengths[length] += 1

                obs_template = int(variant["observation_template_id"])
                query_template = int(variant["query_template_id"])
                for span_type in SPAN_TYPES:
                    occurrences = result["span_mappings"][span_type]["occurrences"]
                    for occurrence in occurrences:
                        span_totals[span_type] += 1
                        template_key = (
                            f"span={span_type}|obs={obs_template}|query={query_template}|"
                            f"variant={variant['variant_id']}"
                        )
                        span_template_totals[template_key] += 1
                        if occurrence["aligned"]:
                            span_aligned[span_type] += 1
                            span_template_aligned[template_key] += 1
                        else:
                            for reason in occurrence["rejection_reasons"]:
                                span_failure_reasons[f"{span_type}:{reason}"] += 1
                                span_template_failures[f"{template_key}|reason={reason}"] += 1

                rejected = result["row_alignment_status"] == "REJECTED"
                if rejected:
                    rejected_rows += 1
                    quartet_aligned = False
                    template_key = (
                        f"obs={obs_template}|query={query_template}|variant={variant['variant_id']}"
                    )
                    row_rejections_by_template[template_key] += 1
                    row_rejections_by_variant[variant["variant_id"]] += 1
                    for reason in result["rejection_reasons"]:
                        row_rejections_by_reason[reason] += 1
                else:
                    aligned_rows += 1

                repeat_result = None
                if event_id in selected:
                    deterministic_repeats += 1
                    second = align_variant(tokenizer, q, variant)
                    equal = (
                        result["token_ids"] == second["token_ids"]
                        and result["offset_mapping"] == second["offset_mapping"]
                        and result["special_tokens_mask"] == second["special_tokens_mask"]
                        and result["span_mappings"] == second["span_mappings"]
                        and result["sequence_length"] == second["sequence_length"]
                    )
                    if not equal:
                        deterministic_repeat_mismatches += 1
                    if second["row_alignment_status"] == "REJECTED":
                        repeated_alignment_rejections += 1
                    repeat_result = {
                        "repeated": True,
                        "exact_token_and_alignment_match": equal,
                        "repeat_row_alignment_status": second["row_alignment_status"],
                    }
                result["deterministic_repeat"] = repeat_result
                records.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")

                if row_count % 10_000 == 0:
                    print(
                        f"alignment_progress rows={row_count} rejected={rejected_rows} "
                        f"repeats={deterministic_repeats}/{REPEAT_SAMPLE_SIZE}",
                        file=sys.stderr,
                        flush=True,
                    )

            track = q["track_id"]
            if track == "FACTORIAL_BALANCED":
                cell = factorial_key(q)
            elif track == "BINDING_CONTEXT":
                cell = binding_context_key(q)
            elif track == "BINDING_ENTITY":
                cell = binding_entity_key(q)
            else:
                raise RuntimeError(f"unknown geometry support track: {track}")
            total_cells[track][cell] += 1
            if quartet_aligned:
                retained_cells[track][cell] += 1

    if quartet_count != EXPECTED_QUARTETS or row_count != EXPECTED_EVENTS:
        raise RuntimeError(
            f"exhaustive pass counts differ: quartets={quartet_count} rows={row_count}"
        )
    if deterministic_repeats != REPEAT_SAMPLE_SIZE:
        raise RuntimeError(
            f"repeat sample coverage differs: {deterministic_repeats}/{REPEAT_SAMPLE_SIZE}"
        )

    support = support_summary(total_cells, retained_cells)
    token_identity_ok = tokenizer_receipt["resolved_commit"] == MODEL_REVISION and tokenizer.is_fast
    all_rows_aligned = aligned_rows == EXPECTED_EVENTS and rejected_rows == 0
    repeat_ok = deterministic_repeat_mismatches == 0
    support_ok = all(item["support_gate_pass"] for item in support.values())
    alignment_ready = token_identity_ok and all_rows_aligned and repeat_ok and support_ok
    failure_codes: list[str] = []
    if not token_identity_ok:
        failure_codes.append("PINNED_TOKENIZER_IDENTITY_MISMATCH")
    if not all_rows_aligned:
        failure_codes.append("REQUIRED_SPAN_ALIGNMENT_REJECTIONS")
    if not repeat_ok:
        failure_codes.append("DETERMINISTIC_REPEAT_MISMATCH")
    if not support_ok:
        failure_codes.append("PROSPECTIVE_GEOMETRY_SUPPORT_BELOW_CONTRACT")

    by_span_type = {
        span_type: {
            "occurrences": span_totals[span_type],
            "aligned_occurrences": span_aligned[span_type],
            "rejected_occurrences": span_totals[span_type] - span_aligned[span_type],
        }
        for span_type in SPAN_TYPES
    }
    report = {
        "report_id": "FASS01_S01_2A_TOKENIZER_ALIGNMENT_REPORT_V01",
        "phase_id": "S01-2A-TOKENIZER-ALIGNMENT-V01",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "authorization_binding": {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "corpus_sha256": EXPECTED_CORPUS_SHA256,
            "protocol_bundle_root_sha256": EXPECTED_PROTOCOL_ROOT,
            "construction_tree_root_sha256": EXPECTED_TREE_ROOT,
        },
        "tokenizer": tokenizer_receipt,
        "frozen_alignment_rule": "Select every nonspecial token whose offset overlaps a recorded source span; reject if any selected token crosses the span boundary, if any source character has coverage other than exactly one, or if no token is selected. No alternative alignment or string repair is applied.",
        "counts": {
            "quartets_expected": EXPECTED_QUARTETS,
            "quartets_seen": quartet_count,
            "rendered_inputs_expected": EXPECTED_EVENTS,
            "rendered_inputs_tokenized": row_count,
            "rows_aligned": aligned_rows,
            "rows_rejected": rejected_rows,
            "token_ids_total": total_token_ids,
            "sequence_length_min": min(sequence_lengths, default=0),
            "sequence_length_max": max_sequence_length,
            "sequence_length_histogram": {str(key): value for key, value in sorted(sequence_lengths.items())},
            "deterministic_repeat_sample_expected": REPEAT_SAMPLE_SIZE,
            "deterministic_repeat_sample_completed": deterministic_repeats,
            "deterministic_repeat_mismatches": deterministic_repeat_mismatches,
            "repeat_sample_rows_rejected_under_alignment_rule": repeated_alignment_rejections,
        },
        "span_alignment": {
            "required_span_types": list(SPAN_TYPES),
            "by_span_type": by_span_type,
            "rejection_occurrences_by_span_and_reason": dict(sorted(span_failure_reasons.items())),
            "by_template_and_variant": {
                key: {
                    "occurrences": count,
                    "aligned_occurrences": span_template_aligned[key],
                    "rejected_occurrences": count - span_template_aligned[key],
                }
                for key, count in sorted(span_template_totals.items())
            },
            "rejection_occurrences_by_template_and_reason": dict(sorted(span_template_failures.items())),
        },
        "row_rejections": {
            "rows_by_reason": dict(sorted(row_rejections_by_reason.items())),
            "rows_by_observation_query_template_and_variant": dict(sorted(row_rejections_by_template.items())),
            "rows_by_variant": dict(sorted(row_rejections_by_variant.items())),
            "every input remains in alignment-records-v01.jsonl": row_count == EXPECTED_EVENTS,
        },
        "prospective_support_after_rejections": {
            "quartet_rule": "A quartet is retained only if all four variants pass every required span; row rejection occurs before any model forward pass.",
            "retained_quartets": sum(sum(counter.values()) for counter in retained_cells.values()),
            "rejected_quartets": quartet_count - sum(sum(counter.values()) for counter in retained_cells.values()),
            "by_geometry_track": support,
            "by_representation_view": {
                view: {
                    "retained_quartets": sum(sum(counter.values()) for counter in retained_cells.values()),
                    "minimum_support_per_declared_cell": min(
                        (item["minimum_retained_per_cell"] for item in support.values()), default=0
                    ),
                    "support_gate_pass": support_ok,
                    "reason": "frozen contract rejects a row before forward pass when any required span fails; all seven views are therefore unavailable for rejected rows",
                }
                for view in VIEWS
            },
        },
        "disposition": {
            "status": "TOKENIZER_ALIGNMENT_QUALIFIED" if alignment_ready else "FAIL_CLOSED",
            "S01_2_CORPUS_READY": True,
            "S01_2_TOKEN_ALIGNMENT_READY": alignment_ready,
            "S01_2_EXTRACTION_CONTRACT_FROZEN": bool(
                prior_disposition.get("S01_2_EXTRACTION_READY")
            ),
            "S01_2_EXTRACTION_READY": alignment_ready,
            "S01_2_MODEL_CONTACT_AUTHORIZED": False,
            "S01_3_AUTHORIZED": False,
            "model_loaded": False,
            "tokenizer_loaded": True,
            "features_created": False,
            "feature_extraction_performed": False,
            "geometry_analysis_performed": False,
            "failure_codes": failure_codes,
        },
    }
    write_json(OUTPUT_ROOT / "alignment-report-v01.json", report)
    disposition = {
        "disposition_id": "FASS01_S01_2A_TOKENIZER_ALIGNMENT_DISPOSITION_V01",
        "status": report["disposition"]["status"],
        "report_sha256": sha256_file(OUTPUT_ROOT / "alignment-report-v01.json"),
        "corpus_sha256": EXPECTED_CORPUS_SHA256,
        "protocol_bundle_root_sha256": EXPECTED_PROTOCOL_ROOT,
        "construction_tree_root_sha256": EXPECTED_TREE_ROOT,
        "S01_2_CORPUS_READY": True,
        "S01_2_TOKEN_ALIGNMENT_READY": alignment_ready,
        "S01_2_EXTRACTION_READY": alignment_ready,
        "S01_2_MODEL_CONTACT_AUTHORIZED": False,
        "S01_3_AUTHORIZED": False,
        "model_loaded": False,
        "tokenizer_loaded": True,
        "feature_extraction_performed": False,
        "geometry_analysis_performed": False,
        "failure_codes": failure_codes,
        "next_boundary": "stop after sealing tokenizer alignment; separate authorization required for any model contact",
    }
    write_json(OUTPUT_ROOT / "alignment-disposition-v01.json", disposition)

    seal = seal_output_tree()
    print(
        json.dumps(
            {
                "status": disposition["status"],
                "rows": row_count,
                "aligned": aligned_rows,
                "rejected": rejected_rows,
                "repeat_mismatches": deterministic_repeat_mismatches,
                "alignment_ready": alignment_ready,
                "output_root_sha256": seal["root_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if alignment_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
