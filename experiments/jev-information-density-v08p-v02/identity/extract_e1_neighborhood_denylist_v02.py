#!/usr/bin/env python3
"""Extract only canonical E1 neighborhood IDs as domain-separated hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("expected JSON object")
    return value


def _ws(raw: bytes, pos: int) -> int:
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    return pos


def _string(raw: bytes, pos: int) -> tuple[str, int]:
    if pos >= len(raw) or raw[pos] != 34:
        raise RuntimeError("expected JSON string")
    start = pos
    pos += 1
    escaped = False
    while pos < len(raw):
        value = raw[pos]
        pos += 1
        if escaped:
            escaped = False
        elif value == 92:
            escaped = True
        elif value == 34:
            decoded = json.loads(raw[start:pos].decode("utf-8", errors="strict"))
            if not isinstance(decoded, str):
                raise RuntimeError("invalid JSON string")
            return decoded, pos
    raise RuntimeError("unterminated JSON string")


def _skip_value(raw: bytes, pos: int) -> int:
    pos = _ws(raw, pos)
    if pos >= len(raw):
        raise RuntimeError("missing JSON value")
    if raw[pos] == 34:
        return _string(raw, pos)[1]
    if raw[pos] in (123, 91):
        stack = [125 if raw[pos] == 123 else 93]
        pos += 1
        quoted = escaped = False
        while pos < len(raw) and stack:
            byte = raw[pos]
            pos += 1
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte == 123:
                stack.append(125)
            elif byte == 91:
                stack.append(93)
            elif byte in (125, 93):
                if not stack or byte != stack[-1]:
                    raise RuntimeError("mismatched JSON container")
                stack.pop()
        if stack or quoted:
            raise RuntimeError("unterminated JSON container")
        return pos
    start = pos
    while pos < len(raw) and raw[pos] not in b",}] \t\r\n":
        pos += 1
    if pos == start:
        raise RuntimeError("invalid JSON scalar")
    return pos


def neighborhood_id_only(raw: bytes) -> str:
    """Decode only the top-level neighborhood_id value; skip other values raw."""
    pos = _ws(raw, 0)
    if pos >= len(raw) or raw[pos] != 123:
        raise RuntimeError("manifest row is not a JSON object")
    pos += 1
    values: list[str] = []
    while True:
        pos = _ws(raw, pos)
        if pos >= len(raw):
            raise RuntimeError("unterminated JSON object")
        if raw[pos] == 125:
            pos += 1
            break
        key, pos = _string(raw, pos)
        pos = _ws(raw, pos)
        if pos >= len(raw) or raw[pos] != 58:
            raise RuntimeError("invalid JSON key/value separator")
        pos = _ws(raw, pos + 1)
        if key == "neighborhood_id":
            identity, pos = _string(raw, pos)
            values.append(identity)
        else:
            pos = _skip_value(raw, pos)
        pos = _ws(raw, pos)
        if pos < len(raw) and raw[pos] == 44:
            pos += 1
            continue
        if pos < len(raw) and raw[pos] == 125:
            pos += 1
            break
        raise RuntimeError("invalid JSON object delimiter")
    if _ws(raw, pos) != len(raw) or len(values) != 1:
        raise RuntimeError("trailing bytes or non-unique neighborhood_id")
    return values[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seal-manifest", type=Path, required=True)
    parser.add_argument("--firewall-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    if contract.get("identity") != "v0.8P-v02-e1-identity-denylist-v02":
        raise RuntimeError("unexpected extraction contract identity")
    if sha256_file(Path(__file__)) != contract["extractor"]["sha256"]:
        raise RuntimeError("extractor hash mismatch")
    source = contract["source"]
    hashes = {
        "panel_manifest_sha256": sha256_file(args.manifest),
        "seal_manifest_sha256": sha256_file(args.seal_manifest),
        "firewall_lock_sha256": sha256_file(args.firewall_lock),
    }
    for key, actual in hashes.items():
        if actual != source[key]:
            raise RuntimeError(f"source hash mismatch: {key}")

    seal = read_json(args.seal_manifest)
    firewall = read_json(args.firewall_lock)
    if seal.get("identity") != source["panel_identity"] or seal.get("status") != source["seal_status"]:
        raise RuntimeError("source seal identity/status mismatch")
    if seal.get("contract_sha256") != source["panel_contract_sha256"]:
        raise RuntimeError("source panel contract mismatch")
    if seal.get("firewall_sha256") != hashes["firewall_lock_sha256"]:
        raise RuntimeError("source seal does not bind firewall lock")
    if not seal.get("panel_locked") or seal.get("phase_b_authorized"):
        raise RuntimeError("source panel seal is not locked/pre-authorization")
    if firewall.get("identity") != source["panel_identity"]:
        raise RuntimeError("source firewall identity mismatch")
    if firewall.get("panel_manifest_sha256") != hashes["panel_manifest_sha256"]:
        raise RuntimeError("firewall does not bind source manifest")
    for key in ("body_access_granted", "training_process_may_read_panel", "evaluation_process_may_read_panel"):
        if firewall.get(key) is not False:
            raise RuntimeError(f"source firewall is not locked: {key}")

    if not args.output_dir.is_dir() or any(args.output_dir.iterdir()):
        raise RuntimeError("output directory must exist and be empty")
    domain = contract["identity_hash"]["domain_prefix"].encode("utf-8")
    seen: set[str] = set()
    hashed: set[str] = set()
    with args.manifest.open("rb") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            identity = neighborhood_id_only(raw)
            if not identity or identity in seen:
                raise RuntimeError(f"empty or duplicate neighborhood identity at row {line_number}")
            seen.add(identity)
            hashed.add(hashlib.sha256(domain + identity.encode("utf-8", errors="strict")).hexdigest())

    expected_count = int(source["expected_neighborhood_count"])
    if len(seen) != expected_count or len(hashed) != expected_count:
        raise RuntimeError("neighborhood count or uniqueness gate failed")
    sorted_hashes = sorted(hashed)
    hash_path = args.output_dir / contract["output"]["hashes_filename"]
    with hash_path.open("x", encoding="utf-8", newline="\n") as stream:
        for value in sorted_hashes:
            stream.write(json.dumps({"identity_sha256": value}, separators=(",", ":")) + "\n")
    receipt = {
        "protocol": "jev-information-density/v0.8p-v02-e1-identity-denylist-seal-v02",
        "identity": contract["identity"],
        "status": "SEALED_HASHED_IDENTITY_DENYLIST",
        "source": {**source, **hashes, "extraction_contract_sha256": sha256_file(args.contract), "extractor_sha256": sha256_file(Path(__file__))},
        "identity_field": "neighborhood_id",
        "raw_identity_values_written": False,
        "hash_algorithm": contract["identity_hash"]["algorithm"],
        "hash_domain_prefix": contract["identity_hash"]["domain_prefix"],
        "count": len(sorted_hashes),
        "sorted_hashes_sha256": sha256_file(hash_path),
        "hashes_filename": hash_path.name,
        "candidate_join_read": False,
        "candidate_features_read": False,
        "targets_read_or_emitted": False,
        "predictions_metrics_geometry_or_heads_read": False,
        "collision_check_performed": False
    }
    seal_path = args.output_dir / contract["output"]["seal_filename"]
    with seal_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "count": receipt["count"], "hashes_sha256": receipt["sorted_hashes_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
