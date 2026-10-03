#!/usr/bin/env python3
"""Build and validate the deterministic OBS-OPEN-01 qualification seal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


EXPECTED = {
    "instrument/candidate-v1_02/OpeningRangeGrammar_v1_02_FullState.mq5":
        "d2c1f0614ba27289a87172dc9fa79f3b018cace73ebd5829afaf100aed406034",
    "instrument/candidate-v1_02/OpeningRangeGrammar_v1_02_FullState.ex5":
        "5505e033d487037a9cc5863788b067123fbf5bc3e48d4c40ddfa0fbe721ac290",
    "qualification/clock/OBS_OPEN_ClockProbe_v1.mq5":
        "f84609aef63cedab7c486e653adda9485936b2e551d2c6239fa381765dc7dcde",
    "qualification/clock/OBS_OPEN_ClockProbe_v1.ex5":
        "267f513ec3c7f3966aef7d8acbd614a95040af76c450d162b0656e6ab7aa46c9",
    "qualification/clock/OBS_OPEN_01_clock_probe_live.tsv":
        "f8186f3948521a4653c84ebc0979a50fb6a0085b5edf3aa8b191af1c97dc941e",
    "qualification/parity/OBS_OPEN_ParityCollector_v1.mq5":
        "c972ac4483da1e02d3fbf99795f636f8a84afd1b0da41a7bccb802ca1f4d6493",
    "qualification/parity/OBS_OPEN_ParityCollector_v1.ex5":
        "c55254edf27e613ba4a7ff277b8517b1924a3119d85cd6b752f44afb389ee1d3",
    "qualification/parity/blackbox_parity_receipt.json":
        "c725a2023a1fdbf35a79446c1173bc15893e6edf9337b0cbfd03abe9c9bb1be7",
}

EXCLUDED_PARTS = {"seal", "rebuild-a", "rebuild-b", "__pycache__"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def admitted_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def parse_clock(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 2:
                raise ValueError(f"clock row must have two fields: {row!r}")
            if row[0] in rows:
                raise ValueError(f"duplicate clock key: {row[0]}")
            rows[row[0]] = row[1]
    return rows


def validate(root: Path) -> None:
    for rel, expected in EXPECTED.items():
        actual = sha256_file(root / rel)
        if actual != expected:
            raise ValueError(f"hash mismatch for {rel}: {actual} != {expected}")

    protocol = json.loads((root / "contracts/obs_open_01_protocol_v1.json").read_text("utf-8"))
    if protocol["substantive_results_status"] != "UNOPENED":
        raise ValueError("substantive results boundary is not UNOPENED")
    if protocol["economic_authority"] or protocol["trading_authority"]:
        raise ValueError("forbidden authority enabled")

    clock = parse_clock(root / "qualification/clock/OBS_OPEN_01_clock_probe_live.tsv")
    required_clock = {
        "receipt_schema": "OBS_OPEN_CLOCK_PROBE_V1",
        "probe_scope": "CURRENT_LIVE_INSTANT_ONLY",
        "historical_offset_authority": "NOT_ESTABLISHED",
        "source_symbol": "US30",
        "source_minus_gmt_seconds": "10800",
        "terminal_connected": "true",
        "mql_tester": "false",
    }
    for key, expected in required_clock.items():
        if clock.get(key) != expected:
            raise ValueError(f"clock contract mismatch {key}: {clock.get(key)!r} != {expected!r}")

    matrix = (root / "qualification/qualification_matrix.tsv").read_text("utf-8")
    if "Q14\tSubstantive results opened\tFROZEN_UNOPENED" not in matrix:
        raise ValueError("qualification matrix lost FROZEN_UNOPENED boundary")
    if "Q07\tHistorical session clock mapping authority\tPASS_BOUNDED_SESSION" not in matrix:
        raise ValueError("bounded historical clock qualification is missing")
    if "Q10\tR01-R30 construction golden suite\tPASS_BOUNDED_SESSION" not in matrix:
        raise ValueError("bounded R01-R30 black-box parity is missing")
    if "Q11\tInteraction grammar golden suite\tPASS_BOUNDED_SESSION" not in matrix:
        raise ValueError("bounded grammar black-box parity is missing")
    if "Q12\tBounded replay determinism\tPASS_BOUNDED_SESSION_BYTE_IDENTICAL" not in matrix:
        raise ValueError("bounded replay determinism is missing")

    parity = json.loads((root / "qualification/clock-parity/clock_parity_receipt.json").read_text("utf-8"))
    if parity["outcome"] != "PASS_BOUNDED_SESSION" or parity["best"]["offset_minutes"] != 180:
        raise ValueError("bounded clock-parity receipt does not pass at UTC+03:00")
    if parity["scope"] != "ADMITTED_SESSION_ONLY":
        raise ValueError("bounded clock-parity scope was broadened")
    if parity["winter_transport"] != "NOT_EVALUABLE_SOURCE_COVERAGE":
        raise ValueError("winter transport was promoted without source coverage")
    if parity["dst_transition_transport"] != "NOT_EVALUABLE_SOURCE_COVERAGE":
        raise ValueError("DST transition transport was promoted without source coverage")

    blackbox = json.loads(
        (root / "qualification/parity/blackbox_parity_receipt.json").read_text("utf-8")
    )
    if blackbox["outcome"] != "PASS" or blackbox["mismatch_cells"] != 0:
        raise ValueError("frozen-observer black-box parity does not pass")
    if blackbox["replay_determinism"] != "PASS_BYTE_IDENTICAL":
        raise ValueError("black-box replay is not byte-identical")
    if blackbox["substantive_results_status"] != "FROZEN_UNOPENED":
        raise ValueError("black-box receipt opened substantive results")


def build(root: Path, output: Path) -> None:
    validate(root)
    rows = ["relative_path\tbytes\tsha256"]
    for path in admitted_files(root):
        rel = path.relative_to(root).as_posix()
        rows.append(f"{rel}\t{path.stat().st_size}\t{sha256_file(path)}")
    manifest = ("\n".join(rows) + "\n").encode("utf-8")
    logical_root = sha256_bytes(manifest)

    receipt = {
        "receipt_schema": "OBS_OPEN_01_QUALIFICATION_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "qualification_logical_root_sha256": logical_root,
        "manifest_sha256": sha256_bytes(manifest),
        "manifest_rows": len(rows) - 1,
        "historical_clock_authority": "PASS_BOUNDED_SESSION_ONLY",
        "winter_clock_transport": "NOT_EVALUABLE_SOURCE_COVERAGE",
        "dst_transition_transport": "NOT_EVALUABLE_SOURCE_COVERAGE",
        "frozen_observer_parity": "PASS_BOUNDED_SESSION_ONLY",
        "replay_determinism": "PASS_BOUNDED_SESSION_BYTE_IDENTICAL",
        "session_universe_and_confirmation_blocks": "NOT_EVALUABLE_SOURCE_COVERAGE",
        "substantive_results_status": "FROZEN_UNOPENED",
        "economic_authority": False,
        "trading_authority": False,
    }
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    build_receipt = {
        "receipt_schema": "OBS_OPEN_01_QUALIFICATION_BUILD_V1",
        "builder": "tools/build_qualification_seal.py",
        "builder_sha256": sha256_file(root / "tools/build_qualification_seal.py"),
        "validation": "PASS",
        "manifest_sha256": logical_root,
        "emitted_files": [
            "qualification_content_manifest.tsv",
            "qualification_root_receipt.json",
            "qualification_build_receipt.json"
        ],
        "determinism_requirement": "TWO_INDEPENDENT_OUTPUT_DIRECTORIES_BYTE_IDENTICAL"
    }
    build_receipt_bytes = (
        json.dumps(build_receipt, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    output.mkdir(parents=True, exist_ok=True)
    (output / "qualification_content_manifest.tsv").write_bytes(manifest)
    (output / "qualification_root_receipt.json").write_bytes(receipt_bytes)
    (output / "qualification_build_receipt.json").write_bytes(build_receipt_bytes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
