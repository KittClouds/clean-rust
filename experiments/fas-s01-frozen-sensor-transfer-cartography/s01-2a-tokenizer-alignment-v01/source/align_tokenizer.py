from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=False).encode("utf-8")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def verify_preflight(root: Path) -> tuple[dict[str, Any], str]:
    seal_path = root / "seals" / "preflight-seal-v01.json"
    if not seal_path.is_file():
        raise RuntimeError("preflight seal is missing")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    entries = seal["entries"]
    canonical = bytearray()
    observed_paths: set[str] = set()
    for entry in entries:
        relative = entry["path"]
        observed_paths.add(relative)
        path = root.joinpath(*relative.split("/"))
        actual_sha, actual_bytes = sha256_file(path)
        if actual_sha != entry["sha256"] or actual_bytes != entry["bytes"]:
            raise RuntimeError(f"preflight file hash mismatch: {relative}")
        canonical.extend(f"{relative}\t{actual_bytes}\t{actual_sha}\n".encode("utf-8"))
    actual_root = hashlib.sha256(canonical).hexdigest()
    if actual_root != seal["root_sha256"]:
        raise RuntimeError("preflight bundle root does not reproduce")
    contract = json.loads((root / "inputs" / "tokenizer-alignment-execution-contract-v01.json").read_text(encoding="utf-8"))
    expected_parent = {
        "S01_2_corpus_sha256": "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1",
        "S01_2_protocol_bundle_root_sha256": "67644d4a99b9c84f312caac591e00e2a12903cea0433832868aa35dce2b5d6f9",
        "S01_2_result_tree_root_sha256": "f6065b8163799239e0d7b1200b5dda4aad169772ead14b999130a473ff9d9049",
        "S01_2_world_contract_sha256": "d886932c92068432b8f670c3a43c1ef604485ebf626c2babae8179b506847c87",
        "S01_2_feature_extraction_contract_sha256": "08ddd42795d71d9b598da5015d5541316c6cf1f2c0761ce3c0890229cda4d5b0",
        "S01_2_geometry_contract_sha256": "4f6df89b02d0b991e09ab5d8f2658627c48799a10b1dd0557795c433d61099ab",
    }
    if contract.get("project_id") != "fas-s01-frozen-sensor-transfer-cartography" or contract.get("phase_id") != "S01-2A-v01":
        raise RuntimeError("execution contract identity differs from the frozen S01-2A packet")
    if contract.get("parent_identity") != expected_parent:
        raise RuntimeError("execution contract parent roots differ from the authorized S01-2A packet")
    if contract.get("tokenizer", {}).get("repo_id") != "LiquidAI/LFM2.5-1.2B-Base" or contract.get("tokenizer", {}).get("revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise RuntimeError("execution contract tokenizer identity differs from the authorized revision")
    if contract.get("tokenization", {}).get("row_count") != 106496 or contract.get("determinism", {}).get("sample_size") != 256:
        raise RuntimeError("execution contract row count or deterministic sample differs from the sealed packet")
    if contract.get("tokenizer", {}).get("allowed_snapshot_files") != ["config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"]:
        raise RuntimeError("tokenizer snapshot allowlist differs from the frozen packet")
    frozen_options = {
        "add_special_tokens": True,
        "padding": False,
        "truncation": False,
        "return_offsets_mapping": True,
        "return_special_tokens_mask": True,
    }
    if contract.get("tokenization", {}).get("per_input_options") != frozen_options:
        raise RuntimeError("tokenizer invocation options differ from the frozen packet")
    frozen_support = {
        "factorial": {"cells": 1536, "required_per_cell": 16},
        "binding_context": {"cells": 64, "required_per_cell": 16},
        "binding_entity": {"cells": 64, "required_per_cell": 16},
    }
    if contract.get("support_gates") != {
        **frozen_support,
        "support_unit": "complete A/C/E/P quartet; a quartet is complete only if all four inputs pass context, entity, and relation alignment",
        "on_shortage": "FAIL_CLOSED; report every under-supported cell and do not merge cells or lower support",
    }:
        raise RuntimeError("support gates differ from the frozen packet")
    if contract.get("span_alignment", {}).get("types") != ["context", "entity", "relation"]:
        raise RuntimeError("execution contract span types differ from the frozen seven-view contract")
    expected = {
        "inputs/tokenizer-alignment-execution-contract-v01.json",
        "inputs/parent-construction-binding-v01.json",
        "README.md",
        "source/align_tokenizer.py",
        "source/seal_result.py",
        "source/seal_preflight.py",
    }
    if observed_paths != expected:
        raise RuntimeError("preflight artifact set differs from the declared set")
    return contract, actual_root


def verify_parent_artifacts(contract: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    parent = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed")
    parent_seal_path = parent / "seals" / "result-tree-seal-v01.json"
    parent_seal = json.loads(parent_seal_path.read_text(encoding="utf-8"))
    expected_parent = contract["parent_identity"]
    if parent_seal["root_sha256"] != expected_parent["S01_2_result_tree_root_sha256"]:
        raise RuntimeError("parent result tree root differs from the authorization packet")
    if parent_seal["corpus_root_sha256"] != expected_parent["S01_2_corpus_sha256"]:
        raise RuntimeError("parent result tree corpus root differs from the authorization packet")
    if parent_seal["protocol_bundle_root_sha256"] != expected_parent["S01_2_protocol_bundle_root_sha256"]:
        raise RuntimeError("parent protocol root differs from the authorization packet")

    corpus_path = parent / "corpus" / "counterfactual-quartets-v01.jsonl"
    declared_entries = parent_seal["entries"]
    declared_paths = [entry["path"] for entry in declared_entries]
    actual_paths = sorted(
        path.relative_to(parent).as_posix()
        for path in parent.rglob("*")
        if path.is_file() and path != parent_seal_path
    )
    if actual_paths != declared_paths:
        raise RuntimeError("parent result-tree file set differs from its seal")
    canonical = bytearray()
    actual_hashes: dict[str, tuple[str, int]] = {}
    for entry in declared_entries:
        relative = entry["path"]
        path = parent.joinpath(*relative.split("/"))
        actual_sha, actual_bytes = sha256_file(path)
        if actual_sha != entry["sha256"] or actual_bytes != entry["bytes"]:
            raise RuntimeError(f"parent result-tree entry mismatch: {relative}")
        actual_hashes[relative] = (actual_sha, actual_bytes)
        canonical.extend(f"{relative}\t{actual_bytes}\t{actual_sha}\n".encode("utf-8"))
    if hashlib.sha256(canonical).hexdigest() != expected_parent["S01_2_result_tree_root_sha256"]:
        raise RuntimeError("parent result-tree root does not reproduce")
    actual_corpus_sha, actual_corpus_bytes = actual_hashes["corpus/counterfactual-quartets-v01.jsonl"]
    if actual_corpus_sha != expected_parent["S01_2_corpus_sha256"]:
        raise RuntimeError("sealed corpus bytes differ from the authorization packet")
    manifest = json.loads((parent / "corpus" / "corpus-manifest-v01.json").read_text(encoding="utf-8"))
    if manifest["corpus_sha256"] != actual_corpus_sha or manifest["corpus_bytes"] != actual_corpus_bytes:
        raise RuntimeError("corpus manifest does not bind the current corpus bytes")
    if manifest["rendered_input_count"] != contract["tokenization"]["row_count"]:
        raise RuntimeError("corpus manifest row count differs from the alignment contract")
    feature_contract_sha, _ = actual_hashes["inputs/contracts/feature-extraction-contract-v01.json"]
    if feature_contract_sha != expected_parent["S01_2_feature_extraction_contract_sha256"]:
        raise RuntimeError("feature-extraction contract hash mismatch")
    return corpus_path, manifest


def token_ids_hash(token_ids: list[int]) -> str:
    digest = hashlib.sha256()
    for token_id in token_ids:
        if token_id < 0 or token_id > 0xFFFFFFFF:
            raise ValueError(f"token ID outside u32 range: {token_id}")
        digest.update(struct.pack("<I", token_id))
    return digest.hexdigest()


def align_one_span(
    span: dict[str, int],
    offsets: list[list[int]],
    special_mask: list[int],
    input_length: int,
) -> tuple[list[int], str | None]:
    start, end = int(span["start"]), int(span["end"])
    if start < 0 or end <= start or end > input_length:
        return [], "character_span_out_of_bounds_or_empty"

    selected: list[tuple[int, int, int]] = []
    for position, ((offset_start, offset_end), is_special) in enumerate(zip(offsets, special_mask, strict=True)):
        if is_special:
            continue
        if offset_start < 0 or offset_end < offset_start or offset_end > input_length:
            if offset_start < end and offset_end > start:
                return [], "invalid_token_offset_overlaps_required_span"
            continue
        if offset_start < end and offset_end > start:
            if offset_start < start or offset_end > end:
                return [], "token_offset_crosses_span_boundary"
            if offset_start == offset_end:
                return [], "empty_token_offset_overlaps_required_span"
            selected.append((position, offset_start, offset_end))

    if not selected:
        return [], "required_span_has_no_nonspecial_tokens"
    selected.sort(key=lambda item: (item[1], item[2], item[0]))
    cursor = start
    for _, token_start, token_end in selected:
        if token_start < cursor:
            return [], "required_span_token_offsets_overlap"
        if token_start > cursor:
            return [], "required_span_has_uncovered_characters"
        cursor = token_end
    if cursor != end:
        return [], "required_span_has_uncovered_characters"
    return [position for position, _, _ in selected], None


def encode_record(
    tokenizer: Any,
    quartet: dict[str, Any],
    variant: dict[str, Any],
    contract: dict[str, Any],
    asset_manifest_sha: str,
) -> dict[str, Any]:
    input_text = variant["input_text"]
    if not input_text.isascii():
        raise ValueError("input_text is not ASCII under the frozen character-offset rule")
    input_sha = hashlib.sha256(input_text.encode("ascii")).hexdigest()
    if input_sha != variant["input_sha256"]:
        raise ValueError("serialized input bytes do not match the sealed input SHA-256")

    encoded = tokenizer(
        input_text,
        add_special_tokens=True,
        padding=False,
        truncation=False,
        return_offsets_mapping=True,
        return_special_tokens_mask=True,
    )
    token_ids = [int(token_id) for token_id in encoded["input_ids"]]
    offsets = [[int(pair[0]), int(pair[1])] for pair in encoded["offset_mapping"]]
    special_mask = [int(value) for value in encoded["special_tokens_mask"]]
    if not token_ids or len(token_ids) != len(offsets) or len(token_ids) != len(special_mask):
        raise ValueError("token IDs, offsets, and special-token mask have incompatible lengths")
    if any(value not in (0, 1) for value in special_mask):
        raise ValueError("special-token mask is not binary")

    span_details: dict[str, list[dict[str, Any]]] = {}
    span_unions: dict[str, list[int]] = {}
    rejection_reasons: list[dict[str, Any]] = []
    for span_type in contract["span_alignment"]["types"]:
        spans = variant["character_spans"].get(span_type, [])
        details: list[dict[str, Any]] = []
        positions_union: set[int] = set()
        if not spans:
            rejection_reasons.append({"span_type": span_type, "occurrence": None, "reason": "required_span_type_has_no_occurrences"})
        for span in spans:
            positions, failure = align_one_span(span, offsets, special_mask, len(input_text))
            details.append({
                "occurrence": int(span["occurrence"]),
                "character_span": [int(span["start"]), int(span["end"])],
                "token_positions": positions,
                "status": "PASS" if failure is None else "REJECT",
                "failure_reason": failure,
            })
            if failure is None:
                positions_union.update(positions)
            else:
                rejection_reasons.append({"span_type": span_type, "occurrence": int(span["occurrence"]), "reason": failure})
        span_details[span_type] = details
        span_unions[span_type] = sorted(positions_union)

    sequence_length = len(token_ids)
    row = {
        "quartet_id": quartet["quartet_id"],
        "event_id": variant["event_id"],
        "variant_id": variant["variant_id"],
        "input_sha256": input_sha,
        "model_id": contract["tokenizer"]["repo_id"],
        "model_revision": contract["tokenizer"]["revision"],
        "tokenizer_asset_manifest_sha256": asset_manifest_sha,
        "feature_contract_sha256": contract["parent_identity"]["S01_2_feature_extraction_contract_sha256"],
        "token_ids": token_ids,
        "token_ids_sha256": token_ids_hash(token_ids),
        "offset_mapping": offsets,
        "special_tokens_mask": special_mask,
        "sequence_length": sequence_length,
        "first_model_visible_position": 0,
        "first_token_id": token_ids[0],
        "final_model_visible_position": sequence_length - 1,
        "final_token_id": token_ids[-1],
        "span_mappings": span_details,
        "deduplicated_span_positions": span_unions,
        "alignment_status": "REJECT" if rejection_reasons else "PASS",
        "rejection_reasons": rejection_reasons,
    }
    return row


def support_key(quartet: dict[str, Any]) -> tuple[str, ...]:
    track = quartet["track_id"]
    context_split = quartet["context_term_split"]
    entity_split = quartet["entity_term_split"]
    if track == "FACTORIAL_BALANCED":
        return (
            track,
            context_split,
            entity_split,
            str(quartet["world_family_id"]),
            str(quartet["relation_id"]),
            str(quartet["state_id"]),
            str(quartet["observation_template_id"]),
            str(quartet["query_template_id"]),
        )
    if track == "BINDING_CONTEXT":
        return (track, context_split, str(quartet["context_pair_id"]), entity_split)
    if track == "BINDING_ENTITY":
        return (track, entity_split, str(quartet["entity_pair_id"]), context_split)
    raise ValueError(f"unknown corpus track: {track}")


def support_summary(expected: Counter[tuple[str, ...]], complete: Counter[tuple[str, ...]]) -> dict[str, Any]:
    details = []
    for key in sorted(expected):
        details.append({"cell": list(key), "expected": expected[key], "complete_quartets": complete[key]})
    under = [item for item in details if item["complete_quartets"] != item["expected"] or item["complete_quartets"] < 16]
    factorial_cells = sum(1 for key in expected if key[0] == "FACTORIAL_BALANCED")
    binding_context_cells = sum(1 for key in expected if key[0] == "BINDING_CONTEXT")
    binding_entity_cells = sum(1 for key in expected if key[0] == "BINDING_ENTITY")
    structure_valid = (
        factorial_cells == 1536
        and binding_context_cells == 64
        and binding_entity_cells == 64
        and all(value == 16 for value in expected.values())
    )
    return {
        "factorial_cells": factorial_cells,
        "binding_context_cells": binding_context_cells,
        "binding_entity_cells": binding_entity_cells,
        "minimum_observed_support": min(complete.get(key, 0) for key in expected) if expected else 0,
        "under_supported_cells": under,
        "frozen_cell_structure_valid": structure_valid,
        "all_cells_at_frozen_support": structure_valid and not under,
        "cell_support": details,
    }


def run(run_root: Path) -> int:
    run_root = run_root.resolve()
    contract, preflight_root = verify_preflight(run_root)
    corpus_path, parent_manifest = verify_parent_artifacts(contract)

    tokenizer_contract = contract["tokenizer"]
    repo_id = tokenizer_contract["repo_id"]
    revision = tokenizer_contract["revision"]
    hf_home = run_root / "tokenizer-cache" / "hf-home"
    cache_dir = run_root / "tokenizer-cache" / "hub"
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(cache_dir)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    import huggingface_hub
    import tokenizers
    import transformers
    from huggingface_hub import HfApi, snapshot_download
    from transformers import AutoTokenizer

    api = HfApi(token=False)
    repo_info = api.model_info(repo_id, revision=revision, files_metadata=False, token=False)
    if repo_info.sha != tokenizer_contract["expected_resolved_commit"]:
        raise RuntimeError(f"tokenizer repository resolved to unexpected commit {repo_info.sha}")
    repository_files = sorted(sibling.rfilename for sibling in repo_info.siblings)
    allowed_files = set(tokenizer_contract["allowed_snapshot_files"])
    if not allowed_files.issubset(repository_files):
        raise RuntimeError("pinned tokenizer revision lacks one or more required tokenizer files")

    snapshot_path = Path(snapshot_download(
        repo_id=repo_id,
        revision=revision,
        cache_dir=str(cache_dir),
        allow_patterns=sorted(allowed_files),
        token=False,
    )).resolve()
    if snapshot_path.name != revision:
        raise RuntimeError("downloaded tokenizer snapshot directory does not match the pinned revision")
    snapshot_files = sorted(path.name for path in snapshot_path.iterdir() if path.is_file())
    if snapshot_files != sorted(allowed_files):
        raise RuntimeError(f"tokenizer snapshot file set differs from the allowlist: {snapshot_files}")
    forbidden_found = [
        str(path.relative_to(run_root))
        for path in (run_root / "tokenizer-cache").rglob("*")
        if path.is_file() and any(fnmatch.fnmatchcase(path.name.lower(), pattern.lower()) for pattern in tokenizer_contract["forbidden_artifact_patterns"])
    ]
    if forbidden_found:
        raise RuntimeError(f"forbidden model artifact found in tokenizer cache: {forbidden_found}")

    asset_entries = []
    for filename in sorted(allowed_files):
        asset_sha, asset_bytes = sha256_file(snapshot_path / filename)
        asset_entries.append({"path": filename, "bytes": asset_bytes, "sha256": asset_sha})

    tokenizer = AutoTokenizer.from_pretrained(
        str(snapshot_path),
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise RuntimeError("pinned tokenizer did not instantiate as a fast tokenizer")

    assets_manifest = {
        "manifest_id": "FASS01_S01_2A_TOKENIZER_ASSETS_V01",
        "repo_id": repo_id,
        "requested_revision": revision,
        "resolved_commit": repo_info.sha,
        "repository_file_inventory": repository_files,
        "loaded_snapshot_files": asset_entries,
        "transformers_version": transformers.__version__,
        "tokenizers_version": tokenizers.__version__,
        "huggingface_hub_version": huggingface_hub.__version__,
        "tokenizer_class": f"{type(tokenizer).__module__}.{type(tokenizer).__name__}",
        "tokenizer_is_fast": bool(tokenizer.is_fast),
        "vocabulary_size": int(tokenizer.vocab_size),
        "added_vocabulary_size": int(len(tokenizer)),
        "special_tokens_map": {
            key: [str(item) for item in value] if isinstance(value, list) else (None if value is None else str(value))
            for key, value in tokenizer.special_tokens_map.items()
        },
        "special_token_ids": {
            "bos": tokenizer.bos_token_id,
            "eos": tokenizer.eos_token_id,
            "pad": tokenizer.pad_token_id,
            "unk": tokenizer.unk_token_id,
        },
        "tokenizer_cache_is_fas_specific": True,
        "model_weights_downloaded_or_loaded": False,
    }
    write_json_new(run_root / "tokenizer-assets-manifest-v01.json", assets_manifest)
    asset_manifest_sha, _ = sha256_file(run_root / "tokenizer-assets-manifest-v01.json")

    output_path = run_root / "alignment-records-v01.jsonl"
    if output_path.exists():
        raise RuntimeError("alignment output already exists; refusing overwrite")
    output_digest = hashlib.sha256()
    event_ids: set[str] = set()
    row_count = 0
    token_count = 0
    sequence_lengths: Counter[int] = Counter()
    span_counts: dict[str, Counter[str]] = {
        span_type: Counter() for span_type in contract["span_alignment"]["types"]
    }
    rejection_counts: Counter[str] = Counter()
    rejected_event_ids: list[str] = []
    expected_support: Counter[tuple[str, ...]] = Counter()
    complete_support: Counter[tuple[str, ...]] = Counter()
    repeat_expected: list[tuple[str, dict[str, Any], dict[str, Any], bytes]] = []
    quartet_count = 0
    timer_start = time.perf_counter()

    with corpus_path.open("r", encoding="utf-8") as corpus, output_path.open("xb") as output:
        for line_number, line in enumerate(corpus, start=1):
            quartet = json.loads(line)
            quartet_count += 1
            cell = support_key(quartet)
            expected_support[cell] += 1
            quartet_complete = True
            if len(quartet["variants"]) != 4:
                raise RuntimeError(f"quartet {quartet['quartet_id']} has non-four row cardinality")
            for variant in quartet["variants"]:
                event_id = variant["event_id"]
                if event_id in event_ids:
                    raise RuntimeError(f"duplicate event id at corpus line {line_number}: {event_id}")
                event_ids.add(event_id)
                try:
                    record = encode_record(tokenizer, quartet, variant, contract, asset_manifest_sha)
                except Exception as error:  # Preserve row accounting for tokenizer/offset failures.
                    record = {
                        "quartet_id": quartet["quartet_id"],
                        "event_id": event_id,
                        "variant_id": variant["variant_id"],
                        "input_sha256": variant.get("input_sha256"),
                        "model_id": repo_id,
                        "model_revision": revision,
                        "tokenizer_asset_manifest_sha256": asset_manifest_sha,
                        "feature_contract_sha256": contract["parent_identity"]["S01_2_feature_extraction_contract_sha256"],
                        "token_ids": None,
                        "token_ids_sha256": None,
                        "offset_mapping": None,
                        "special_tokens_mask": None,
                        "sequence_length": None,
                        "first_model_visible_position": None,
                        "first_token_id": None,
                        "final_model_visible_position": None,
                        "final_token_id": None,
                        "span_mappings": {},
                        "deduplicated_span_positions": {},
                        "alignment_status": "REJECT",
                        "rejection_reasons": [{"span_type": None, "occurrence": None, "reason": f"tokenizer_or_identity_error:{type(error).__name__}:{error}"}],
                    }
                serialized = canonical_json_bytes(record)
                output.write(serialized)
                output.write(b"\n")
                output_digest.update(serialized)
                output_digest.update(b"\n")
                row_count += 1
                if record["alignment_status"] != "PASS":
                    quartet_complete = False
                    rejected_event_ids.append(event_id)
                    for reason in record["rejection_reasons"]:
                        label = f"{reason.get('span_type')}:{reason['reason']}"
                        rejection_counts[label] += 1
                if record["sequence_length"] is not None:
                    token_count += record["sequence_length"]
                    sequence_lengths[record["sequence_length"]] += 1
                for span_type, details in record["span_mappings"].items():
                    span_counts[span_type]["occurrences"] += len(details)
                    span_counts[span_type]["passed_occurrences"] += sum(item["status"] == "PASS" for item in details)
                    span_counts[span_type]["failed_occurrences"] += sum(item["status"] != "PASS" for item in details)
                if len(repeat_expected) < contract["determinism"]["sample_size"]:
                    repeat_expected.append((event_id, quartet, variant, serialized))
            if quartet_complete:
                complete_support[cell] += 1
        output.flush()
        os.fsync(output.fileno())

    if row_count != contract["tokenization"]["row_count"] or quartet_count != parent_manifest["quartet_count"]:
        raise RuntimeError(f"exhaustive input count mismatch: rows={row_count}, quartets={quartet_count}")

    repeat_mismatches: list[str] = []
    for event_id, quartet, variant, expected_bytes in repeat_expected:
        try:
            repeated = encode_record(tokenizer, quartet, variant, contract, asset_manifest_sha)
            repeated_bytes = canonical_json_bytes(repeated)
        except Exception as error:
            repeated_bytes = canonical_json_bytes({"event_id": event_id, "repeat_error": f"{type(error).__name__}:{error}"})
        if repeated_bytes != expected_bytes:
            repeat_mismatches.append(event_id)

    support = support_summary(expected_support, complete_support)
    output_sha = output_digest.hexdigest()
    output_bytes = output_path.stat().st_size
    no_rejections = not rejected_event_ids
    repeat_pass = len(repeat_expected) == contract["determinism"]["sample_size"] and not repeat_mismatches
    identity_pass = repo_info.sha == revision and tokenizer.is_fast and not forbidden_found
    support_pass = support["all_cells_at_frozen_support"]
    all_pass = identity_pass and no_rejections and repeat_pass and support_pass and row_count == 106496
    status = "TOKENIZER_ALIGNMENT_PASS" if all_pass else "TOKENIZER_ALIGNMENT_FAIL_CLOSED"
    elapsed = time.perf_counter() - timer_start

    summary = {
        "report_id": "FASS01_S01_2A_TOKENIZER_ALIGNMENT_REPORT_V01",
        "status": status,
        "preflight_root_sha256": preflight_root,
        "corpus_sha256": contract["parent_identity"]["S01_2_corpus_sha256"],
        "protocol_bundle_root_sha256": contract["parent_identity"]["S01_2_protocol_bundle_root_sha256"],
        "construction_tree_root_sha256": contract["parent_identity"]["S01_2_result_tree_root_sha256"],
        "feature_contract_sha256": contract["parent_identity"]["S01_2_feature_extraction_contract_sha256"],
        "tokenizer_asset_manifest_sha256": asset_manifest_sha,
        "tokenizer_repo_id": repo_id,
        "tokenizer_requested_revision": revision,
        "tokenizer_resolved_commit": repo_info.sha,
        "tokenizer_class": assets_manifest["tokenizer_class"],
        "tokenizer_is_fast": bool(tokenizer.is_fast),
        "model_instantiated": False,
        "model_weights_downloaded_or_loaded": False,
        "feature_extraction_performed": False,
        "quartets_seen": quartet_count,
        "rendered_inputs_seen": row_count,
        "alignment_records_sha256": output_sha,
        "alignment_records_bytes": output_bytes,
        "total_token_positions": token_count,
        "sequence_length_min": min(sequence_lengths) if sequence_lengths else None,
        "sequence_length_max": max(sequence_lengths) if sequence_lengths else None,
        "sequence_length_histogram": {str(key): value for key, value in sorted(sequence_lengths.items())},
        "span_occurrence_counts": {name: dict(counts) for name, counts in span_counts.items()},
        "rejected_input_count": len(rejected_event_ids),
        "rejected_event_ids": rejected_event_ids,
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "repeat_sample_size": len(repeat_expected),
        "repeat_sample_selection": contract["determinism"]["sample_selection"],
        "repeat_check_pass": repeat_pass,
        "repeat_mismatch_event_ids": repeat_mismatches,
        "support_audit": support,
        "gates": {
            "PINNED_TOKENIZER_IDENTITY": "PASS" if identity_pass else "FAIL",
            "ALL_INPUTS_TOKENIZED": "PASS" if row_count == 106496 else "FAIL",
            "REQUIRED_SPANS_UNAMBIGUOUS": "PASS" if no_rejections else "FAIL",
            "DETERMINISTIC_REPEAT": "PASS" if repeat_pass else "FAIL",
            "POST_REJECTION_SUPPORT": "PASS" if support_pass else "FAIL",
            "LFM_WEIGHTS_NOT_LOADED": "PASS",
            "NO_FEATURES_OR_PROBES": "PASS",
        },
        "elapsed_seconds_local_diagnostic": round(elapsed, 3),
        "complete": True,
    }
    write_json_new(run_root / "tokenizer-alignment-report-v01.json", summary)
    disposition = {
        "disposition_id": "FASS01_S01_2A_ALIGNMENT_DISPOSITION_V01",
        "project_id": contract["project_id"],
        "phase_id": contract["phase_id"],
        "tokenizer_alignment_status": status,
        "S01_2_CORPUS_READY": True,
        "S01_2_TOKEN_ALIGNMENT_READY": bool(all_pass),
        "S01_2_EXTRACTION_READY": True,
        "S01_2_EXTRACTION_READY_MEANING": "frozen extraction contract is ready; this disposition separately reports whether required tokenizer spans passed",
        "S01_2_MODEL_CONTACT_AUTHORIZED": False,
        "S01_3_AUTHORIZED": False,
        "LFM_LOADED": False,
        "TOKENIZER_LOADED": True,
        "FEATURES_CREATED": False,
        "PROBES_TRAINED": False,
        "GEOMETRY_ANALYSIS_PERFORMED": False,
        "rejected_input_count": len(rejected_event_ids),
        "post_rejection_support_pass": support_pass,
        "next_boundary": "stop after sealing tokenizer alignment for review",
    }
    write_json_new(run_root / "phase-disposition-v01.json", disposition)
    print(json.dumps({"status": status, "rows": row_count, "rejected": len(rejected_event_ids), "alignment_sha256": output_sha}, separators=(",", ":")))
    return 0 if all_pass else 2


def preflight_only(run_root: Path) -> int:
    run_root = run_root.resolve()
    contract, preflight_root = verify_preflight(run_root)
    corpus_path, manifest = verify_parent_artifacts(contract)
    print(json.dumps({
        "preflight": "PASS",
        "preflight_root_sha256": preflight_root,
        "corpus_sha256": manifest["corpus_sha256"],
        "corpus_path": str(corpus_path),
        "rows": manifest["rendered_input_count"],
        "tokenizer_loaded": False,
        "model_loaded": False,
    }, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tokenizer-only S01-2A span alignment qualification")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        return preflight_only(args.run_root)
    return run(args.run_root)


if __name__ == "__main__":
    sys.exit(main())
