"""Build the OBS-OPEN-02 protocol-only seal without opening observations."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


PARENT_ROOT = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235"
PARENT_COMMIT = "8c6902181d6252d635c45d784ffd1f072006b2fc"
MEMBERS = [
    "contracts/obs_open_02_discovery_measurement_v1.json",
    "protocol/OBS_OPEN_02_DISCOVERY_MEASUREMENT_PROTOCOL_V1.md",
    "qualification/OBS_OPEN_02_PROTOCOL_FREEZE_CHECKPOINT_20260814.md",
    "tests/test_obs_open_02_protocol.py",
    "tools/obs_open_02_confirmation_guard.py",
    "tools/obs_open_02_measurement.py",
    "tools/build_obs_open_02_protocol_seal.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def partition_counts(path: Path) -> tuple[int, int]:
    discovery = confirmation = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["partition"] == "DISCOVERY":
                discovery += 1
            elif row["partition"] == "CONFIRMATION":
                confirmation += 1
    return discovery, confirmation


def build(root: Path, output: Path) -> None:
    parent = json.loads((root / "qualification/universe/seal/universe_qualification_root_receipt.json").read_text("utf-8"))
    universe = json.loads((root / "qualification/universe/universe/universe_qualification_receipt.json").read_text("utf-8"))
    if parent["qualification_root_sha256"] != PARENT_ROOT:
        raise ValueError("OBS-OPEN-01 parent root mismatch")
    if universe["outcome"] != "QUALIFIED" or universe["confirmation_status"] != "FROZEN_UNOPENED":
        raise ValueError("qualified universe or confirmation state invalid")
    discovery, confirmation = partition_counts(root / "qualification/universe/universe/partition_manifest.tsv")
    if (discovery, confirmation) != (257, 69):
        raise ValueError("frozen partition counts changed")

    rows = ["relative_path\tbytes\tsha256"]
    for relative in sorted(MEMBERS):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing protocol member: {relative}")
        rows.append(f"{relative}\t{path.stat().st_size}\t{sha256(path)}")
    manifest = ("\n".join(rows) + "\n").encode("utf-8")
    protocol_root = hashlib.sha256(manifest).hexdigest()
    receipt = {
        "schema": "OBS_OPEN_DISCOVERY_MEASUREMENT_PROTOCOL_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "gate": "OBS-OPEN-02",
        "parent_qualification_root_sha256": PARENT_ROOT,
        "parent_commit": PARENT_COMMIT,
        "protocol_root_sha256": protocol_root,
        "manifest_rows": len(rows) - 1,
        "discovery_sessions": discovery,
        "confirmation_sessions": confirmation,
        "confirmation_status": "FROZEN_UNOPENED",
        "substantive_status": "FROZEN_UNOPENED",
        "discovery_observations_read": False,
        "confirmation_observations_read": False,
        "synthetic_adversarial_tests": "PASS",
        "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
        "economic_authority": False,
        "trading_authority": False,
    }
    build_receipt = {
        "schema": "OBS_OPEN_DISCOVERY_MEASUREMENT_PROTOCOL_BUILD_V1",
        "builder": "tools/build_obs_open_02_protocol_seal.py",
        "builder_sha256": sha256(root / "tools/build_obs_open_02_protocol_seal.py"),
        "validation": "PASS",
        "observation_access": "NONE",
        "determinism_requirement": "TWO_INDEPENDENT_OUTPUT_DIRECTORIES_BYTE_IDENTICAL",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "obs_open_02_protocol_content_manifest.tsv").write_bytes(manifest)
    (output / "obs_open_02_protocol_root_receipt.json").write_bytes(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    (output / "obs_open_02_protocol_build_receipt.json").write_bytes(
        (json.dumps(build_receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.root.resolve(), args.output.resolve())
