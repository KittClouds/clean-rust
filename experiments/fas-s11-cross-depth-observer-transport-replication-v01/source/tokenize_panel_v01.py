from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path

from s11_exec_common_v01 import EVENTS, MANIFEST, RUN, canonical_json, jsonl_rows, read_json, sha256_file, verify_ancestry, verify_code_binding, write_json


EXPECTED_ROWS = 21_272
TOKENIZER_DIR = RUN / "inputs" / "tokenizer-snapshot"
OUT = RUN / "tokenization-v01"
TMP = RUN / "tokenization-v01.tmp"


def token_sha(token_ids: list[int]) -> str:
    return hashlib.sha256(struct.pack(f"<{len(token_ids)}I", *token_ids)).hexdigest()


def encode(tokenizer, text: str) -> list[int]:
    encoded = tokenizer(text, add_special_tokens=True, padding=False, truncation=False, return_attention_mask=False)
    ids = [int(value) for value in encoded["input_ids"]]
    if not ids or any(value < 0 or value >= 2**32 for value in ids):
        raise RuntimeError("empty or out-of-range token IDs")
    if len(ids) > tokenizer.model_max_length:
        raise RuntimeError("S11 input exceeds the tokenizer model maximum; no truncation is permitted")
    return ids


def main() -> int:
    started = time.perf_counter()
    manifest = read_json(MANIFEST)
    verify_ancestry(manifest)
    code_binding = verify_code_binding(manifest)
    if OUT.exists() or TMP.exists():
        raise RuntimeError("tokenization output already exists; preserve it and use a versioned attempt")
    event_digest, event_bytes = sha256_file(EVENTS)
    expected_event_digest = manifest["authoritative_s11_ancestry"]["panel_events_sha256"]
    if event_digest != expected_event_digest:
        raise RuntimeError(f"selected event file hash mismatch: {event_digest}")
    tokenizer_manifest_path = RUN / "inputs" / "tokenizer-assets-manifest-v01.json"
    tokenizer_identity_path = RUN / "inputs" / "tokenizer-identity-v01.json"
    tokenizer_manifest = read_json(tokenizer_manifest_path)
    tokenizer_identity_hash = sha256_file(tokenizer_identity_path)[0]
    if tokenizer_identity_hash != manifest["preflight"]["tokenizer"]["identity_sha256"]:
        raise RuntimeError("pinned tokenizer identity file changed after preflight")
    if sha256_file(tokenizer_manifest_path)[0] != manifest["preflight"]["tokenizer"]["manifest_sha256"]:
        raise RuntimeError("pinned tokenizer asset manifest changed after preflight")
    for asset in manifest["preflight"]["tokenizer"]["files"]:
        digest, size = sha256_file(TOKENIZER_DIR / asset["name"])
        if digest != asset["sha256"] or size != asset["bytes"]:
            raise RuntimeError(f"pinned tokenizer asset changed: {asset['name']}")
    if tokenizer_manifest.get("resolved_commit") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise RuntimeError("tokenizer manifest revision differs from the pinned model")

    rows: list[dict[str, object]] = []
    row_hasher = hashlib.sha256()
    with EVENTS.open("r", encoding="utf-8") as stream:
        for row_index, line in enumerate(stream):
            event = json.loads(line)
            # Deliberately project only input identity and rendered text; latent fields and labels are ignored.
            event_id = event["event_id"]
            input_text = event["input_text"]
            input_hash = event["input_sha256"]
            actual_input_hash = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
            if input_hash != actual_input_hash:
                raise RuntimeError(f"rendered input hash mismatch at row {row_index}")
            projected = {"row_index": row_index, "event_id": event_id, "input_sha256": input_hash, "input_text": input_text}
            payload = canonical_json(projected) + b"\n"
            row_hasher.update(payload)
            rows.append(projected)
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"expected {EXPECTED_ROWS} rows, found {len(rows)}")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(TOKENIZER_DIR), local_files_only=True, trust_remote_code=False, use_fast=True
    )
    if not tokenizer.is_fast or tokenizer.vocab_size != 64_400:
        raise RuntimeError("pinned tokenizer implementation or vocabulary size differs")
    if (tokenizer.bos_token_id, tokenizer.eos_token_id, tokenizer.pad_token_id) != (1, 7, 0):
        raise RuntimeError("pinned tokenizer special token IDs differ")

    encoded_rows: list[dict[str, object]] = []
    first_pass_ids: list[list[int]] = []
    token_sha_stream = hashlib.sha256()
    length_sha_stream = hashlib.sha256()
    for row in rows:
        ids = encode(tokenizer, str(row["input_text"]))
        digest = token_sha(ids)
        encoded = {
            "row_index": row["row_index"],
            "event_id": row["event_id"],
            "input_sha256": row["input_sha256"],
            "sequence_length": len(ids),
            "token_ids_sha256": digest,
            "token_ids": ids,
        }
        encoded_rows.append(encoded)
        first_pass_ids.append(ids)
        token_sha_stream.update(bytes.fromhex(digest))
        length_sha_stream.update(struct.pack("<I", len(ids)))

    repeat_digest = hashlib.sha256()
    for index, row in enumerate(rows):
        repeat_ids = encode(tokenizer, str(row["input_text"]))
        if repeat_ids != first_pass_ids[index]:
            raise RuntimeError(f"deterministic repeat tokenization mismatch at row {index}")
        repeat_digest.update(bytes.fromhex(token_sha(repeat_ids)))

    TMP.mkdir(parents=True)
    input_path = TMP / "token-inputs-v01.jsonl"
    token_path = TMP / "token-rows-v01.jsonl"
    input_hash = hashlib.sha256()
    input_size = 0
    with input_path.open("wb") as stream:
        for row in rows:
            payload = canonical_json(row) + b"\n"
            stream.write(payload)
            input_hash.update(payload)
            input_size += len(payload)
    token_hash = hashlib.sha256()
    token_size = 0
    with token_path.open("wb") as stream:
        for row in encoded_rows:
            payload = canonical_json(row) + b"\n"
            stream.write(payload)
            token_hash.update(payload)
            token_size += len(payload)
    receipt = {
        "receipt_id": "FAS_S11_TOKENIZATION_RECEIPT_V01",
        "complete": True,
        "rows": len(rows),
        "source_event_file_sha256": event_digest,
        "source_event_file_bytes": event_bytes,
        "input_projection_sha256": input_hash.hexdigest(),
        "input_projection_bytes": input_size,
        "input_projection_rows_sha256": row_hasher.hexdigest(),
        "token_rows_sha256": token_hash.hexdigest(),
        "token_rows_bytes": token_size,
        "token_id_digest_stream_sha256": token_sha_stream.hexdigest(),
        "token_repeat_digest_stream_sha256": repeat_digest.hexdigest(),
        "sequence_length_stream_sha256": length_sha_stream.hexdigest(),
        "sequence_length_min": min(int(row["sequence_length"]) for row in encoded_rows),
        "sequence_length_max": max(int(row["sequence_length"]) for row in encoded_rows),
        "tokenizer": {
            "repo_id": "LiquidAI/LFM2.5-1.2B-Base",
            "revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
            "is_fast": bool(tokenizer.is_fast),
            "vocab_size": tokenizer.vocab_size,
            "bos_token_id": tokenizer.bos_token_id,
            "eos_token_id": tokenizer.eos_token_id,
            "pad_token_id": tokenizer.pad_token_id,
            "identity_file_sha256": tokenizer_identity_hash,
            "add_special_tokens": True,
            "padding": False,
            "truncation": False,
            "local_files_only": True,
        },
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "frozen_contract_sha256": manifest["frozen_contract_sha256"],
        "panel_tree_root_sha256": manifest["authoritative_s11_ancestry"]["panel_tree_root_sha256"],
        "deterministic_repeat": {"all_rows_retokenized": True, "byte_identity": repeat_digest.hexdigest() == token_sha_stream.hexdigest()},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "model_loaded": False,
        "hidden_state_extraction": False,
        "labels_or_latent_fields_used": False,
    }
    if not receipt["deterministic_repeat"]["byte_identity"]:
        raise RuntimeError("repeat token identity stream differs")
    from s11_exec_common_v01 import entry, tree_root

    entries = [entry(path, TMP) for path in (input_path, token_path)]
    receipt["tree_root_sha256"] = tree_root(entries)
    write_json(TMP / "tokenization-receipt-v01.json", receipt)
    entries = [entry(path, TMP) for path in TMP.rglob("*") if path.is_file() and path.name != "tokenization-seal-v01.json"]
    write_json(TMP / "tokenization-seal-v01.json", {"seal_id": "FAS_S11_TOKENIZATION_SEAL_V01", "entries": entries, "root_sha256": tree_root(entries)})
    TMP.replace(OUT)
    print(f"S11 tokenization sealed: {len(rows)} rows, root={tree_root(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
