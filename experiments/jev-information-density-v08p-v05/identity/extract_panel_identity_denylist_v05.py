#!/usr/bin/env python3
"""Hash canonical E1 neighborhood IDs via the sealed firewall-lock binding.

The only E1 inputs are the exact firewall lock and the exact panel manifest.
Run twice with ``python -I -S`` in separate processes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any

E1_ROOT = os.path.normcase(r"D:\codex-runs\jev-information-density-v08n")
OUTPUT_ROOT = r"D:\codex-runs\jev-information-density-v08p-v05\identity"
ALLOWLIST_ID = "v0.8P-v05-direct-panel-identity-source-allowlist-v01"
EXPECTED_COUNT = 2000
OUTPUTS = {
    "clean-process-1": os.path.join(OUTPUT_ROOT, "run-1"),
    "clean-process-2": os.path.join(OUTPUT_ROOT, "run-2"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def path_hash(path: str) -> str:
    return sha256_bytes(normalized_path(path).encode("utf-8"))


def _protected(path: Any) -> str | None:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    try:
        value = normalized_path(os.fsdecode(os.fspath(path)))
    except (TypeError, ValueError, OSError):
        return None
    if value == E1_ROOT or value.startswith(E1_ROOT + os.sep):
        return value
    return None


def install_guard(authorized: set[str]) -> dict[str, Any]:
    state: dict[str, Any] = {"open_attempts": [], "blocked": [], "successful_opens": []}

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            value = _protected(args[0])
            if value is None:
                return
            if value not in authorized:
                state["blocked"].append({"event": event, "path_hash": sha256_bytes(value.encode("utf-8"))})
                raise PermissionError("E1 open is outside the exact v05 allowlist")
            state["open_attempts"].append(value)
            return
        if event in {"os.listdir", "os.scandir", "glob.glob", "glob.glob/2"} and args:
            value = _protected(args[0])
            if value is not None:
                state["blocked"].append({"event": event, "path_hash": sha256_bytes(value.encode("utf-8"))})
                raise PermissionError("E1 discovery/enumeration is forbidden")

    sys.addaudithook(audit)
    return state


def _skip_ws(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1
    return pos


def _string_end(data: bytes, pos: int) -> int:
    if pos >= len(data) or data[pos] != ord('"'):
        raise ValueError("expected JSON string")
    pos += 1
    while pos < len(data):
        if data[pos] == ord('\\'):
            pos += 2
            continue
        if data[pos] == ord('"'):
            return pos + 1
        pos += 1
    raise ValueError("unterminated JSON string")


def _decode_string(data: bytes, pos: int) -> tuple[str, int]:
    end = _string_end(data, pos)
    value = json.loads(data[pos:end].decode("utf-8"))
    if not isinstance(value, str):
        raise ValueError("expected JSON string token")
    return value, end


def _skip_value(data: bytes, pos: int) -> int:
    """Lexically skip one value without decoding or materializing it."""
    pos = _skip_ws(data, pos)
    if pos >= len(data):
        raise ValueError("missing JSON value")
    if data[pos] == ord('"'):
        return _string_end(data, pos)
    closes: list[int] = []
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
            closes.append(ord('}'))
        elif byte == ord('['):
            closes.append(ord(']'))
        elif byte in (ord('}'), ord(']')):
            if closes:
                if closes.pop() != byte:
                    raise ValueError("mismatched JSON container")
                if not closes:
                    return pos + 1
            elif byte == ord('}'):
                return pos
            else:
                raise ValueError("unexpected JSON array end")
        elif byte == ord(',') and not closes:
            return pos
        pos += 1
    if closes or in_string:
        raise ValueError("unterminated JSON value")
    return pos


def extract_top_level_string(data: bytes, field: str) -> str:
    """Extract one top-level string field; all other values remain opaque."""
    pos = _skip_ws(data, 0)
    if pos >= len(data) or data[pos] != ord('{'):
        raise ValueError("JSON record is not an object")
    pos += 1
    found: str | None = None
    while True:
        pos = _skip_ws(data, pos)
        if pos >= len(data):
            raise ValueError("unterminated JSON object")
        if data[pos] == ord('}'):
            pos += 1
            break
        key, pos = _decode_string(data, pos)
        pos = _skip_ws(data, pos)
        if pos >= len(data) or data[pos] != ord(':'):
            raise ValueError("JSON member lacks colon")
        pos = _skip_ws(data, pos + 1)
        if key == field:
            if found is not None:
                raise ValueError(f"duplicate {field} field")
            found, pos = _decode_string(data, pos)
        else:
            pos = _skip_value(data, pos)
        pos = _skip_ws(data, pos)
        if pos < len(data) and data[pos] == ord(','):
            pos += 1
            continue
        if pos < len(data) and data[pos] == ord('}'):
            pos += 1
            break
        raise ValueError("invalid JSON member boundary")
    if _skip_ws(data, pos) != len(data):
        raise ValueError("trailing bytes after JSON object")
    if found is None:
        raise ValueError(f"missing top-level {field}")
    return found


def canonical_identity(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("neighborhood_id is empty or has surrounding whitespace")
    if not unicodedata.is_normalized("NFC", value):
        raise ValueError("neighborhood_id is not already NFC canonical")
    return value


def extract_identity_hashes(manifest: bytes) -> list[str]:
    hashes: list[str] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    rows = manifest.splitlines()
    if len(rows) != EXPECTED_COUNT:
        raise ValueError(f"expected exactly {EXPECTED_COUNT} JSONL rows, found {len(rows)}")
    for row_number, row in enumerate(rows, start=1):
        if not row.strip():
            raise ValueError(f"blank manifest row at line {row_number}")
        identity = canonical_identity(extract_top_level_string(row, "neighborhood_id"))
        if identity in seen_ids:
            raise ValueError("duplicate canonical neighborhood_id")
        digest = sha256_bytes(identity.encode("utf-8"))
        if digest in seen_hashes:
            raise ValueError("duplicate neighborhood identity digest")
        seen_ids.add(identity)
        seen_hashes.add(digest)
        hashes.append(digest)
    if len(hashes) != EXPECTED_COUNT:
        raise ValueError("identity count mismatch")
    return sorted(hashes)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_one_exact(path: str, purpose: str) -> tuple[bytes, dict[str, Any]]:
    with open(path, "rb") as stream:
        data = stream.read()
    return data, {"path_hash": path_hash(path), "bytes_read": len(data), "purpose": purpose}


def write_receipt(out_dir: Path, receipt: dict[str, Any]) -> None:
    path = out_dir / "source-access-receipt.json"
    if path.exists():
        raise FileExistsError("source-access receipt already exists")
    path.write_bytes(json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8") + b"\n")


def run(args: argparse.Namespace) -> int:
    expected_output = OUTPUTS.get(args.run_label)
    if expected_output is None or normalized_path(args.output_dir) != normalized_path(expected_output):
        raise ValueError("run label/output directory is not one of the frozen v05 destinations")
    out_dir = Path(expected_output)
    if not out_dir.is_dir():
        raise FileNotFoundError("frozen v05 output directory must exist before source access")
    denylist_path = out_dir / "canonical-e1-neighborhood-hash-denylist.json"
    receipt_path = out_dir / "source-access-receipt.json"
    if denylist_path.exists() or receipt_path.exists():
        raise FileExistsError("frozen v05 output path is not empty")

    allow_path = Path(args.allowlist).resolve(strict=True)
    allow_bytes = allow_path.read_bytes()
    allow_hash = sha256_bytes(allow_bytes)
    if allow_hash != args.allowlist_sha256:
        raise ValueError("v05 allowlist hash mismatch")
    allow = json.loads(allow_bytes)
    if allow.get("identity") != ALLOWLIST_ID or allow.get("status") != "FROZEN_BEFORE_EXTRACTION":
        raise ValueError("unexpected v05 source allowlist identity/state")

    extractor_hash = sha256_bytes(Path(__file__).resolve(strict=True).read_bytes())
    if extractor_hash != allow["extractor"]["sha256"]:
        raise ValueError("extractor hash mismatch")

    authority_receipts: list[dict[str, str]] = []
    authority_bytes: dict[str, bytes] = {}
    for item in allow["authority_artifacts"]:
        raw = Path(item["path"]).read_bytes()
        actual = sha256_bytes(raw)
        if actual != item["sha256"]:
            raise ValueError("local v04 authority artifact hash mismatch")
        authority_bytes[item["path"]] = raw
        authority_receipts.append({"path": item["path"], "sha256": actual})
    trace = json.loads(authority_bytes[allow["authority_artifacts"][0]["path"]])
    stage_a_seal = json.loads(authority_bytes[allow["authority_artifacts"][1]["path"]])
    if stage_a_seal["artifacts"]["authority_trace"]["sha256"] != allow["v04_authority_trace_sha256"]:
        raise ValueError("v04 Stage-A seal does not bind the authorized trace hash")
    expected_manifest = allow["authorized_sources"][1]
    trace_authority = trace["authority_artifacts"]
    matching = [item for item in trace_authority if item.get("bound_object", "").replace("\\", "/").lower() == expected_manifest["path"].replace("\\", "/").lower()]
    if len(matching) != 1 or matching[0].get("bound_value", "").lower() != expected_manifest["expected_sha256"]:
        raise ValueError("v04 Stage-A trace does not uniquely bind the exact manifest path/hash")

    sources = allow["authorized_sources"]
    if len(sources) != 2:
        raise ValueError("v05 allowlist must contain exactly two E1 objects")
    allowed_paths: set[str] = set()
    for item in sources:
        p = normalized_path(item["path"])
        if path_hash(item["path"]) != item["canonical_path_sha256"]:
            raise ValueError("v05 canonical path hash mismatch")
        if p in allowed_paths:
            raise ValueError("duplicate E1 allowlist path")
        allowed_paths.add(p)
    if sources[0]["permitted_fields"] != ["panel_manifest_sha256"] or sources[1]["permitted_fields"] != ["neighborhood_id"]:
        raise ValueError("unexpected v05 semantic field allowlist")

    guard = install_guard(allowed_paths)
    source_records: list[dict[str, Any]] = []
    denylist: dict[str, Any] | None = None
    failure: str | None = None
    try:
        lock_bytes, lock_meta = read_one_exact(sources[0]["path"], sources[0]["purpose"])
        guard["successful_opens"].append(normalized_path(sources[0]["path"]))
        lock_hash = sha256_bytes(lock_bytes)
        lock_meta.update({"expected_sha256": sources[0]["expected_sha256"], "observed_sha256": lock_hash, "match": lock_hash == sources[0]["expected_sha256"]})
        source_records.append(lock_meta)
        if lock_hash != sources[0]["expected_sha256"]:
            raise ValueError("firewall-lock SHA-256 mismatch")

        bound_hash = extract_top_level_string(lock_bytes, "panel_manifest_sha256")
        if bound_hash.lower() != sources[1]["expected_sha256"]:
            raise ValueError("firewall lock binding differs from exact manifest allowlist hash")

        manifest_bytes, manifest_meta = read_one_exact(sources[1]["path"], sources[1]["purpose"])
        guard["successful_opens"].append(normalized_path(sources[1]["path"]))
        manifest_hash = sha256_bytes(manifest_bytes)
        manifest_meta.update({"expected_sha256": sources[1]["expected_sha256"], "observed_sha256": manifest_hash, "match": manifest_hash == sources[1]["expected_sha256"]})
        source_records.append(manifest_meta)
        if manifest_hash != sources[1]["expected_sha256"]:
            raise ValueError("panel manifest SHA-256 mismatch")

        identity_hashes = extract_identity_hashes(manifest_bytes)
        expected_set = set(allowed_paths)
        if guard["blocked"] or len(guard["open_attempts"]) != 2 or set(guard["open_attempts"]) != expected_set:
            raise PermissionError("E1 open-attempt set differs from exact allowlist")
        if len(guard["successful_opens"]) != 2 or set(guard["successful_opens"]) != expected_set:
            raise PermissionError("successful E1 open set differs from exact allowlist")

        denylist = {
            "schema": "canonical-neighborhood-id-sha256-set-v01",
            "count": len(identity_hashes),
            "identity_sha256": identity_hashes,
            "authority": {
                "v04_stage_a_trace_sha256": allow["v04_authority_trace_sha256"],
                "firewall_lock_sha256": lock_hash,
                "firewall_lock_pointer": "/panel_manifest_sha256",
                "panel_manifest_sha256": manifest_hash,
            },
            "extractor_sha256": extractor_hash,
        }
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"

    receipt = {
        "protocol": "jev-information-density/v0.8p-v05-source-access-receipt-v01",
        "run_label": args.run_label,
        "status": "PASS" if failure is None else "FAIL_CLOSED",
        "allowlist_sha256": allow_hash,
        "extractor_sha256": extractor_hash,
        "local_authority_artifacts": authority_receipts,
        "authorized_e1_path_hashes": sorted(item["canonical_path_sha256"] for item in sources),
        "successful_input_opens": sorted(source_records, key=lambda item: item["path_hash"]),
        "open_attempt_path_hashes": sorted(path_hash(p) for p in guard["open_attempts"]),
        "blocked_access_events": guard["blocked"],
        "observed_successful_open_set_equals_authorized_set": len(guard["successful_opens"]) == len(allowed_paths) and set(guard["successful_opens"]) == allowed_paths,
        "exactly_one_successful_open_per_source": len(guard["successful_opens"]) == len(allowed_paths) and set(guard["successful_opens"]) == allowed_paths,
        "semantic_fields_accessed": {"firewall_lock": ["panel_manifest_sha256"], "panel_manifest": ["neighborhood_id"]},
        "raw_neighborhood_ids_written": False,
        "identity_count": 0 if denylist is None else denylist["count"],
        "failure": failure,
    }
    write_receipt(out_dir, receipt)
    if failure is not None:
        return 2
    denylist_path.write_bytes(canonical_json_bytes(denylist))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--allowlist-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-label", required=True)
    args = parser.parse_args()
    try:
        code = run(args)
    except Exception as exc:
        # Pre-source failures are not source-access passes; no E1 file is opened.
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
