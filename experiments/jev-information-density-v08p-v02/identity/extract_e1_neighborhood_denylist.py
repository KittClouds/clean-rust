#!/usr/bin/env python3
"""One-purpose extractor: emit hashes of sealed E1 neighborhood IDs only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path.name}")
    return value


def canonical_identity_hash(identity: str, domain: bytes) -> str:
    return hashlib.sha256(domain + identity.encode("utf-8", errors="strict")).hexdigest()


def _skip_space(raw: bytes, pos: int) -> int:
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    return pos


def _read_json_string(raw: bytes, pos: int) -> tuple[str, int]:
    if pos >= len(raw) or raw[pos] != ord('"'):
        raise RuntimeError("expected JSON string")
    start = pos
    pos += 1
    escaped = False
    while pos < len(raw):
        byte = raw[pos]
        pos += 1
        if escaped:
            escaped = False
        elif byte == ord("\\"):
            escaped = True
        elif byte == ord('"'):
            value = json.loads(raw[start:pos].decode("utf-8", errors="strict"))
            if not isinstance(value, str):
                raise RuntimeError("JSON string decoder returned a non-string")
            return value, pos
    raise RuntimeError("unterminated JSON string")


def _skip_json_value(raw: bytes, pos: int) -> int:
    pos = _skip_space(raw, pos)
    if pos >= len(raw):
        raise RuntimeError("missing JSON value")
    if raw[pos] == ord('"'):
        _, end = _read_json_string(raw, pos)
        return end
    if raw[pos] in (ord("{"), ord("[")):
        closers = [ord("}") if raw[pos] == ord("{") else ord("]")]
        pos += 1
        in_string = False
        escaped = False
        while pos < len(raw) and closers:
            byte = raw[pos]
            pos += 1
            if in_string:
                if escaped:
                    escaped = False
                elif byte == ord("\\"):
                    escaped = True
                elif byte == ord('"'):
                    in_string = False
                continue
            if byte == ord('"'):
                in_string = True
            elif byte == ord("{"):
                closers.append(ord("}"))
            elif byte == ord("["):
                closers.append(ord("]"))
            elif byte in (ord("}"), ord("]")):
                if not closers or byte != closers[-1]:
                    raise RuntimeError("mismatched JSON container while skipping value")
                closers.pop()
        if closers or in_string:
            raise RuntimeError("unterminated JSON container while skipping value")
        return pos
    start = pos
    while pos < len(raw) and raw[pos] not in b",}] \t\r\n":
        pos += 1
    if pos == start:
        raise RuntimeError("invalid JSON scalar while skipping value")
    return pos


def extract_neighborhood_id_only(raw: bytes) -> str:
    """Read one top-level string value; skip all other JSON values as bytes."""
    pos = _skip_space(raw, 0)
    if pos >= len(raw) or raw[pos] != ord("{"):
        raise RuntimeError("manifest record is not a JSON object")
    pos += 1
    found: list[str] = []
    while True:
        pos = _skip_space(raw, pos)
        if pos >= len(raw):
            raise RuntimeError("unterminated manifest object")
        if raw[pos] == ord("}"):
            pos += 1
            break
        key, pos = _read_json_string(raw, pos)
        pos = _skip_space(raw, pos)
        if pos >= len(raw) or raw[pos] != ord(":"):
            raise RuntimeError("invalid JSON object separator")
        pos = _skip_space(raw, pos + 1)
        if key == "neighborhood_id":
            value, pos = _read_json_string(raw, pos)
            found.append(value)
        else:
            pos = _skip_json_value(raw, pos)
        pos = _skip_space(raw, pos)
        if pos < len(raw) and raw[pos] == ord(","):
            pos += 1
            continue
        if pos < len(raw) and raw[pos] == ord("}"):
            pos += 1
            break
        raise RuntimeError("invalid JSON object delimiter")
    if _skip_space(raw, pos) != len(raw):
        raise RuntimeError("trailing bytes after manifest object")
    if len(found) != 1:
        raise RuntimeError("manifest row must contain exactly one neighborhood_id")
    return found[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seal-manifest", type=Path, required=True)
    parser.add_argument("--firewall-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = load_json(args.contract)
    if contract.get("identity") != "v0.8P-v02-e1-identity-denylist-v01":
        raise RuntimeError("unexpected extraction contract identity")
    if sha256_file(Path(__file__)) != contract["extractor"]["sha256"]:
        raise RuntimeError("extractor source hash differs from frozen contract")

    expected = contract["source"]
    source_hash = sha256_file(args.manifest)
    seal_hash = sha256_file(args.seal_manifest)
    firewall_hash = sha256_file(args.firewall_lock)
    if source_hash != expected["panel_manifest_sha256"]:
        raise RuntimeError("authoritative panel manifest hash mismatch")
    if seal_hash != expected["seal_manifest_sha256"]:
        raise RuntimeError("panel seal-manifest hash mismatch")
    if firewall_hash != expected["firewall_lock_sha256"]:
        raise RuntimeError("panel firewall-lock hash mismatch")

    seal = load_json(args.seal_manifest)
    firewall = load_json(args.firewall_lock)
    if seal.get("identity") != expected["panel_identity"]:
        raise RuntimeError("panel seal identity mismatch")
    if seal.get("status") != expected["seal_status"]:
        raise RuntimeError("panel seal status mismatch")
    if seal.get("contract_sha256") != expected["panel_contract_sha256"]:
        raise RuntimeError("panel contract hash mismatch")
    if seal.get("firewall_sha256") != firewall_hash:
        raise RuntimeError("seal manifest does not bind the firewall lock")
    if not seal.get("panel_locked") or seal.get("phase_b_authorized"):
        raise RuntimeError("source seal is not locked/pre-authorization")
    if firewall.get("identity") != expected["panel_identity"]:
        raise RuntimeError("firewall identity mismatch")
    if firewall.get("panel_manifest_sha256") != source_hash:
        raise RuntimeError("firewall does not bind the source manifest")
    if firewall.get("body_access_granted") is not False:
        raise RuntimeError("source panel body is not locked")
    if firewall.get("training_process_may_read_panel") is not False:
        raise RuntimeError("source training firewall is not locked")
    if firewall.get("evaluation_process_may_read_panel") is not False:
        raise RuntimeError("source evaluation firewall is not locked")

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RuntimeError("denylist output directory is not empty; refusing overwrite")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    domain = contract["identity_hash"]["domain_prefix"].encode("utf-8")
    seen: set[str] = set()
    hashed: set[str] = set()
    with args.manifest.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            # Other fields are traversed only as opaque bytes and are never decoded.
            identity = extract_neighborhood_id_only(raw_line)
            if not isinstance(identity, str) or not identity:
                raise RuntimeError(f"manifest row {line_number} lacks neighborhood_id")
            if identity in seen:
                raise RuntimeError("duplicate canonical neighborhood identity")
            seen.add(identity)
            hashed.add(canonical_identity_hash(identity, domain))

    expected_count = int(contract["source"]["expected_neighborhood_count"])
    if len(seen) != expected_count or len(hashed) != expected_count:
        raise RuntimeError("source neighborhood count/uniqueness mismatch")
    sorted_hashes = sorted(hashed)

    output_path = args.output_dir / contract["output"]["hashes_filename"]
    payload = "".join(json.dumps({"identity_sha256": value}, separators=(",", ":")) + "\n" for value in sorted_hashes)
    output_path.write_text(payload, encoding="utf-8", newline="\n")
    output_hash = sha256_file(output_path)
    contract_hash = sha256_file(args.contract)
    extractor_hash = sha256_file(Path(__file__))
    seal_receipt = {
        "protocol": "jev-information-density/v0.8p-v02-e1-identity-denylist-seal-v01",
        "identity": contract["identity"],
        "status": "SEALED_HASHED_IDENTITY_DENYLIST",
        "source": {
            "panel_identity": expected["panel_identity"],
            "panel_manifest_sha256": source_hash,
            "seal_manifest_sha256": seal_hash,
            "firewall_lock_sha256": firewall_hash,
            "extraction_contract_sha256": contract_hash,
            "extractor_source_sha256": extractor_hash
        },
        "identity_field": "neighborhood_id",
        "raw_identity_values_written": False,
        "identity_hash_algorithm": contract["identity_hash"]["algorithm"],
        "identity_hash_domain_prefix": contract["identity_hash"]["domain_prefix"],
        "count": len(sorted_hashes),
        "sorted_hashes_sha256": output_hash,
        "output_file": output_path.name,
        "candidate_join_read": False,
        "candidate_features_read": False,
        "targets_read_or_emitted": False,
        "predictions_metrics_geometry_or_heads_read": False,
        "collision_check_performed": False
    }
    receipt_path = args.output_dir / contract["output"]["seal_filename"]
    receipt_path.write_text(json.dumps(seal_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": seal_receipt["status"], "count": len(sorted_hashes), "hashes_sha256": output_hash, "seal_path": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
