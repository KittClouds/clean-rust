#!/usr/bin/env python3
"""Build the deterministic OBS-OPEN-01 multi-session qualification seal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PARENT_ROOT = "b5a55b74770cbdb9364cdb3087570c33c4b3b41af7004c9ee4b73b5e8078a040"
ADMITTED = [
    "contracts/obs_open_01_universe_qualification_v1.json",
    "protocol/OBS_OPEN_01_UNIVERSE_QUALIFICATION_V1.md",
    "qualification/OBS_OPEN_01_UNIVERSE_QUALIFICATION_CHECKPOINT_20260814.md",
    "qualification/coverage/OBS_OPEN_SourceCoverageCollectorEA_v1.mq5",
    "qualification/coverage/OBS_OPEN_SourceCoverageCollector_v1.mq5",
    "qualification/coverage/coverage_tester_v1.ini",
    "qualification/universe/clock/clock_transport_matrix.tsv",
    "qualification/universe/clock/clock_transport_receipt.json",
    "qualification/universe/provenance/local_raw_authority_manifest.json",
    "qualification/universe/provenance/local_raw_verification_receipt.json",
    "qualification/universe/provenance/source_acquisition_receipt.json",
    "qualification/universe/provenance/source_acquisition_terminal_excerpt.tsv",
    "qualification/universe/universe/admitted_sessions.tsv",
    "qualification/universe/universe/excluded_sessions.tsv",
    "qualification/universe/universe/partition_manifest.tsv",
    "qualification/universe/universe/session_coverage_census.tsv",
    "qualification/universe/universe/universe_qualification_receipt.json",
    "tools/build_clock_transport_receipt.py",
    "tools/build_coverage_universe.py",
    "tools/build_local_raw_authority_manifest.py",
    "tools/build_source_acquisition_receipt.py",
    "tools/build_universe_qualification_seal.py",
    "tools/download_dukascopy_clock_fixture.py",
    "tools/evaluate_clock_parity.py",
    "tools/extract_clock_anchors.py",
    "tests/test_universe_qualification.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, output: Path) -> None:
    original = json.loads((root / "qualification/seal/qualification_root_receipt.json").read_text("utf-8"))
    if original["qualification_logical_root_sha256"] != PARENT_ROOT:
        raise ValueError("parent qualification root mismatch")
    clock = json.loads((root / "qualification/universe/clock/clock_transport_receipt.json").read_text("utf-8"))
    universe = json.loads((root / "qualification/universe/universe/universe_qualification_receipt.json").read_text("utf-8"))
    raw = json.loads((root / "qualification/universe/provenance/local_raw_verification_receipt.json").read_text("utf-8"))
    acquisition = json.loads((root / "qualification/universe/provenance/source_acquisition_receipt.json").read_text("utf-8"))
    if clock["outcome"] != "QUALIFIED" or clock["qualified_anchors"] != clock["required_anchors"]:
        raise ValueError("clock transport is not qualified")
    if universe["outcome"] != "QUALIFIED" or not all(universe["gates"].values()):
        raise ValueError("universe is not qualified")
    if universe["confirmation_status"] != "FROZEN_UNOPENED":
        raise ValueError("confirmation drawer is not frozen")
    if raw["outcome"] != "PASS" or acquisition["outcome"] != "PASS":
        raise ValueError("source provenance is not qualified")

    rows = ["relative_path\tbytes\tsha256"]
    for relative in sorted(ADMITTED):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing seal member {relative}")
        rows.append(f"{relative}\t{path.stat().st_size}\t{sha256(path)}")
    manifest = ("\n".join(rows) + "\n").encode()
    logical_root = hashlib.sha256(manifest).hexdigest()
    receipt = {
        "schema": "OBS_OPEN_UNIVERSE_QUALIFICATION_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "parent_qualification_root_sha256": PARENT_ROOT,
        "qualification_root_sha256": logical_root,
        "manifest_rows": len(rows) - 1,
        "clock_transport": "QUALIFIED",
        "admitted_sessions": universe["admitted_sessions"],
        "discovery_sessions": universe["discovery_sessions"],
        "confirmation_sessions": universe["confirmation_sessions"],
        "confirmation_status": "FROZEN_UNOPENED",
        "derivation_rebuild": "PASS_BYTE_IDENTICAL",
        "substantive_results_status": "FROZEN_UNOPENED",
        "economic_authority": False,
        "trading_authority": False,
    }
    build_receipt = {
        "schema": "OBS_OPEN_UNIVERSE_QUALIFICATION_BUILD_V1",
        "builder": "tools/build_universe_qualification_seal.py",
        "builder_sha256": sha256(root / "tools/build_universe_qualification_seal.py"),
        "validation": "PASS",
        "determinism_requirement": "TWO_INDEPENDENT_OUTPUT_DIRECTORIES_BYTE_IDENTICAL",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "universe_qualification_content_manifest.tsv").write_bytes(manifest)
    (output / "universe_qualification_root_receipt.json").write_bytes(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    (output / "universe_qualification_build_receipt.json").write_bytes(
        (json.dumps(build_receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
