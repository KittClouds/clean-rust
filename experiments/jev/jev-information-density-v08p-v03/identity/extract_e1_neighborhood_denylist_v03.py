#!/usr/bin/env python3
"""Extract only hashed canonical neighborhood IDs from an exact allowlist.

This program intentionally has no discovery, directory enumeration, globbing,
or general-purpose input path. Run it twice in separate isolated processes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

PROTECTED_ROOT = os.path.normcase(r"D:\codex-runs\jev-information-density-v08n")
OUTPUT_ROOT = r"D:\codex-runs\jev-information-density-v08p-v03\identity"
ALLOWLIST_ID = "v0.8P-v03-e1-neighborhood-denylist-source-allowlist-v01"
EXPECTED_COUNT = 2000
EXPECTED_OUTPUTS = {
    "clean-process-1": os.path.join(OUTPUT_ROOT, "run-1", "result"),
    "clean-process-2": os.path.join(OUTPUT_ROOT, "run-2", "result"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def protected_path(path: Any) -> str | None:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    try:
        value = os.fsdecode(os.fspath(path))
        resolved = canonical_path(value)
    except (TypeError, ValueError, OSError):
        return None
    if resolved == PROTECTED_ROOT or resolved.startswith(PROTECTED_ROOT + os.sep):
        return resolved
    return None


def install_e1_access_guard(allowed_paths: set[str]) -> dict[str, Any]:
    state: dict[str, Any] = {"open_events": [], "successful_opens": [], "blocked_events": []}

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            resolved = protected_path(args[0])
            if resolved is None:
                return
            if resolved not in allowed_paths:
                state["blocked_events"].append({"event": event, "path": resolved})
                raise PermissionError("E1 source open is not allowlisted")
            state["open_events"].append(resolved)
            return

        if event in {"os.listdir", "os.scandir", "glob.glob", "glob.glob/2"} and args:
            resolved = protected_path(args[0])
            if resolved is not None:
                state["blocked_events"].append({"event": event, "path": resolved})
                raise PermissionError("E1 directory discovery is forbidden")

    sys.addaudithook(audit)
    return state


def _skip_ws(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1
    return pos


def _json_string_end(data: bytes, pos: int) -> int:
    if pos >= len(data) or data[pos] != ord('"'):
        raise ValueError("expected JSON string")
    pos += 1
    while pos < len(data):
        byte = data[pos]
        if byte == ord('\\'):
            pos += 2
            continue
        if byte == ord('"'):
            return pos + 1
        pos += 1
    raise ValueError("unterminated JSON string")


def _decode_json_string(data: bytes, pos: int) -> tuple[str, int]:
    end = _json_string_end(data, pos)
    value = json.loads(data[pos:end].decode("utf-8"))
    if not isinstance(value, str):
        raise ValueError("JSON key/value is not a string")
    return value, end


def _skip_json_value(data: bytes, pos: int) -> int:
    """Skip one JSON value without parsing or materializing its contents."""
    pos = _skip_ws(data, pos)
    if pos >= len(data):
        raise ValueError("missing JSON value")
    if data[pos] == ord('"'):
        return _json_string_end(data, pos)

    stack: list[int] = []
    in_string = False
    escaped = False
    while pos < len(data):
        byte = data[pos]
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord('\\'):
                escaped = True
            elif byte == ord('"'):
                in_string = False
        elif byte == ord('"'):
            in_string = True
        elif byte == ord('{'):
            stack.append(ord('}'))
        elif byte == ord('['):
            stack.append(ord(']'))
        elif byte in (ord('}'), ord(']')):
            if stack:
                if stack.pop() != byte:
                    raise ValueError("mismatched JSON container")
                if not stack:
                    return pos + 1
            elif byte == ord('}'):
                return pos
            else:
                raise ValueError("unexpected JSON array terminator")
        elif byte == ord(',') and not stack:
            return pos
        pos += 1
    if stack or in_string:
        raise ValueError("unterminated JSON value")
    return pos


def extract_top_level_string_field(raw_line: bytes, wanted: str) -> str:
    """Read one named top-level string; skip all other values as opaque bytes."""
    data = raw_line.strip()
    pos = _skip_ws(data, 0)
    if pos >= len(data) or data[pos] != ord('{'):
        raise ValueError("manifest record is not a JSON object")
    pos += 1
    found: str | None = None
    while True:
        pos = _skip_ws(data, pos)
        if pos >= len(data):
            raise ValueError("unterminated manifest object")
        if data[pos] == ord('}'):
            pos += 1
            break
        key, pos = _decode_json_string(data, pos)
        pos = _skip_ws(data, pos)
        if pos >= len(data) or data[pos] != ord(':'):
            raise ValueError("missing JSON member colon")
        pos = _skip_ws(data, pos + 1)
        if key == wanted:
            if found is not None:
                raise ValueError(f"duplicate top-level {wanted} field")
            found, pos = _decode_json_string(data, pos)
        else:
            pos = _skip_json_value(data, pos)
        pos = _skip_ws(data, pos)
        if pos < len(data) and data[pos] == ord(','):
            pos += 1
            continue
        if pos < len(data) and data[pos] == ord('}'):
            pos += 1
            break
        raise ValueError("malformed JSON object member boundary")
    if _skip_ws(data, pos) != len(data):
        raise ValueError("unexpected trailing bytes after manifest object")
    if not found:
        raise ValueError(f"manifest record lacks top-level {wanted}")
    return found


def read_manifest_id_hashes(path: str) -> tuple[str, list[str]]:
    source_hasher = hashlib.sha256()
    identity_values: set[str] = set()
    identity_hashes: list[str] = []
    count = 0
    with open(path, "rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            source_hasher.update(raw_line)
            if not raw_line.strip():
                continue
            identity = extract_top_level_string_field(raw_line, "neighborhood_id")
            if identity in identity_values:
                raise ValueError("duplicate canonical neighborhood_id")
            identity_values.add(identity)
            identity_hashes.append(sha256_bytes(identity.encode("utf-8")))
            count += 1
    if count != EXPECTED_COUNT:
        raise ValueError(f"expected {EXPECTED_COUNT} identities, found {count}")
    return source_hasher.hexdigest(), sorted(identity_hashes)


def read_opaque_source_hash(path: str) -> str:
    source_hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            source_hasher.update(chunk)
    return source_hasher.hexdigest()


def canonical_denylist_bytes(
    identity_hashes: list[str], source_hashes: list[dict[str, str]], extractor_hash: str
) -> bytes:
    payload = {
        "schema": "canonical-neighborhood-id-sha256-set-v01",
        "count": len(identity_hashes),
        "identity_sha256": sorted(identity_hashes),
        "authorized_source_sha256": sorted(
            item["observed_sha256"] for item in source_hashes
        ),
        "extractor_sha256": extractor_hash,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def expected_open_set_matches(observed: list[str], expected: set[str]) -> bool:
    return len(observed) == len(expected) and set(observed) == expected


def run(args: argparse.Namespace) -> None:
    expected_output = EXPECTED_OUTPUTS.get(args.run_label)
    if expected_output is None or canonical_path(args.output_dir) != canonical_path(expected_output):
        raise ValueError("run label/output path is not one of the two frozen clean-process destinations")
    if os.path.exists(expected_output):
        raise FileExistsError("frozen output destination already exists")
    allowlist_path = Path(args.allowlist).resolve(strict=True)
    allowlist_bytes = allowlist_path.read_bytes()
    observed_allowlist_hash = sha256_bytes(allowlist_bytes)
    if observed_allowlist_hash != args.allowlist_sha256:
        raise ValueError("source allowlist hash mismatch")
    allowlist = json.loads(allowlist_bytes)
    if allowlist.get("identity") != ALLOWLIST_ID or allowlist.get("status") != "FROZEN_BEFORE_EXTRACTION":
        raise ValueError("unexpected allowlist identity or state")

    script_path = Path(__file__).resolve(strict=True)
    extractor_hash = sha256_bytes(script_path.read_bytes())
    expected_extractor_hash = allowlist["extractor"]["sha256"]
    if extractor_hash != expected_extractor_hash:
        raise ValueError("extractor source hash differs from frozen allowlist")

    sources = allowlist["authorized_sources"]
    if len(sources) != 3:
        raise ValueError("allowlist must contain exactly three source files")
    source_by_path: dict[str, dict[str, Any]] = {}
    for entry in sources:
        path = entry["path"]
        normalized = canonical_path(path)
        path_hash = sha256_bytes(normalized.encode("utf-8"))
        if path_hash != entry["canonical_path_sha256"]:
            raise ValueError("allowlisted canonical path hash mismatch")
        if normalized in source_by_path:
            raise ValueError("duplicate exact source path")
        source_by_path[normalized] = entry

    if len(sources[0]["permitted_fields"]) != 1 or sources[0]["permitted_fields"] != ["neighborhood_id"]:
        raise ValueError("manifest allowlist must authorize only neighborhood_id")
    if any(entry["permitted_fields"] for entry in sources[1:]):
        raise ValueError("opaque provenance sources must not expose semantic fields")

    access = install_e1_access_guard(set(source_by_path))
    source_receipts: list[dict[str, str]] = []
    identity_hashes: list[str] = []
    for index, entry in enumerate(sources):
        path = entry["path"]
        normalized = canonical_path(path)
        # The panel manifest is streamed; non-identity values are lexically skipped.
        if index == 0:
            observed_hash, identity_hashes = read_manifest_id_hashes(path)
        else:
            observed_hash = read_opaque_source_hash(path)
        if observed_hash != entry["expected_sha256"]:
            raise ValueError(f"authorized source hash mismatch: {entry['canonical_path_sha256']}")
        access["successful_opens"].append(normalized)
        source_receipts.append(
            {
                "path_hash": entry["canonical_path_sha256"],
                "expected_sha256": entry["expected_sha256"],
                "observed_sha256": observed_hash,
                "purpose": entry["purpose"],
            }
        )

    if access["blocked_events"]:
        raise PermissionError("an unexpected E1 access was blocked")
    expected_paths = set(source_by_path)
    if not expected_open_set_matches(access["successful_opens"], expected_paths):
        raise PermissionError("observed successful E1 open set differs from exact allowlist")
    denylist = canonical_denylist_bytes(identity_hashes, source_receipts, extractor_hash)

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=False)
    denylist_path = output_root / "canonical-e1-neighborhood-hash-denylist.json"
    receipt_path = output_root / "source-access-execution-receipt.json"
    denylist_path.write_bytes(denylist)
    receipt = {
        "protocol": "jev-information-density/v0.8p-v03-source-access-receipt-v01",
        "run_label": args.run_label,
        "allowlist_sha256": observed_allowlist_hash,
        "extractor_sha256": extractor_hash,
        "expected_source_path_hashes": sorted(entry["canonical_path_sha256"] for entry in sources),
        "successful_input_opens": sorted(source_receipts, key=lambda item: item["path_hash"]),
        "observed_path_hash_set_equals_authorized_set": True,
        "successful_open_count_per_authorized_path": 1,
        "blocked_or_unexpected_access_count": 0,
        "semantic_fields_accessed": {"manifest": ["neighborhood_id"], "opaque_provenance": []},
        "identity_count": len(identity_hashes),
        "raw_neighborhood_ids_written": False,
        "denylist_sha256": sha256_bytes(denylist),
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--allowlist-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-label", required=True)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
