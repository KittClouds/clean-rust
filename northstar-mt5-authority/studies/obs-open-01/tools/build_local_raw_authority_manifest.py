#!/usr/bin/env python3
"""Inventory D-only OBS-OPEN-01 qualification authority without moving it online."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--local-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def artifact(root: Path, relative: str, kind: str) -> dict[str, object]:
    path = root / relative
    return {
        "logical_path": relative.replace("\\", "/"),
        "kind": kind,
        "availability": "PRESENT" if path.exists() else "MISSING",
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": sha256(path) if path.exists() else "",
    }


def main() -> int:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    root = args.local_root.resolve()
    rows = [
        artifact(root, "raw/OBS_OPEN_01_source_bars.tsv", "BROKER_BAR_AUTHORITY"),
        artifact(root, "source-hcc/US30_2024.hcc", "MT5_HCC_CONTAINER"),
        artifact(root, "source-hcc/US30_2025.hcc", "MT5_HCC_CONTAINER"),
        artifact(root, "clock/broker-anchors-v1/broker_clock_anchors.tsv", "DERIVED_CLOCK_ANCHORS"),
        artifact(root, "clock/broker-anchors-v1/broker_clock_anchors_receipt.json", "DERIVATION_RECEIPT"),
    ]
    for day in contract["clock"]["required_anchor_dates"]:
        base = f"clock/dukascopy-{day}"
        rows.extend([
            artifact(root, f"{base}/dukascopy_hour_manifest.tsv", "EXTERNAL_RAW_HOUR_MANIFEST"),
            artifact(root, f"{base}/dukascopy_utc_minutes.tsv", "EXTERNAL_CLOCK_WITNESS"),
            artifact(root, f"{base}/dukascopy_fixture_receipt.json", "EXTERNAL_SOURCE_RECEIPT"),
            artifact(root, f"clock/alignment-{day}/clock_offset_scan.tsv", "CLOCK_DERIVATION_LEDGER"),
            artifact(root, f"clock/alignment-{day}/clock_parity_receipt.json", "CLOCK_DERIVATION_RECEIPT"),
        ])
        manifest = root / base / "dukascopy_hour_manifest.tsv"
        if manifest.exists():
            with manifest.open(newline="", encoding="utf-8") as handle:
                for hour in csv.DictReader(handle, delimiter="\t"):
                    raw_relative = f"{base}/{hour['relative_path']}"
                    raw_path = root / raw_relative
                    status = hour["status"]
                    if status == "OK" and raw_path.exists():
                        actual = sha256(raw_path)
                        if actual != hour["compressed_sha256"]:
                            raise ValueError(f"external raw hash mismatch: {raw_relative}")
                    if status == "OK_EMPTY" and (not raw_path.exists() or raw_path.stat().st_size != 0):
                        raise ValueError(f"external empty-hour contract mismatch: {raw_relative}")
                    rows.append(artifact(root, raw_relative, f"EXTERNAL_RAW_BI5_{status}"))

    expected_bar_hash = contract["source"]["bar_authority_sha256"]
    if rows[0]["sha256"] != expected_bar_hash:
        raise ValueError("local bar authority does not match the frozen contract")
    missing_required = [row["logical_path"] for row in rows if row["availability"] != "PRESENT" and not str(row["kind"]).endswith("_ERROR")]
    if missing_required:
        raise ValueError(f"required local authority missing: {missing_required[:5]}")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "local_raw_authority_manifest.json"
    manifest_value = {
        "schema": "OBS_OPEN_LOCAL_RAW_AUTHORITY_MANIFEST_V1",
        "storage_class": "D_DRIVE_LOCAL_ONLY",
        "online_publication": False,
        "artifacts": rows,
    }
    manifest_path.write_bytes(canonical_json(manifest_value))
    receipt = {
        "schema": "OBS_OPEN_LOCAL_RAW_VERIFICATION_RECEIPT_V1",
        "outcome": "PASS",
        "artifacts_declared": len(rows),
        "artifacts_present": sum(row["availability"] == "PRESENT" for row in rows),
        "manifest_sha256": sha256(manifest_path),
        "contract_sha256": sha256(args.contract),
        "large_artifacts_committed_to_git": False,
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "local_raw_verification_receipt.json").write_bytes(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
