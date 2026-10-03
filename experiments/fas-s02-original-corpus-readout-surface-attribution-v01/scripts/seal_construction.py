#!/usr/bin/env python3
"""Verify allowlisted S02 parent artifacts and seal the construction packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEAL = ROOT / "seals" / "construction-seal-v01.json"
ALLOWLIST = (
    "README.md",
    "S02-PROTOCOL.md",
    "contracts/parent-binding-v01.json",
    "contracts/two-view-attribution-contract-v01.json",
    "scripts/seal_construction.py",
    "seals/construction-disposition-v01.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_root(rows: list[dict]) -> str:
    ordered = sorted(rows, key=lambda row: row["path"].encode("utf-8"))
    body = "".join(f'{row["path"]} {row["sha256"]}\n' for row in ordered)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify_parent_files(binding: dict) -> list[dict]:
    fas = binding["fas00"]
    checks = [
        (fas["closure"]["path"], fas["closure"]["record_sha256"]),
        (fas["closure"]["seal_path"], fas["closure"]["seal_file_sha256"]),
        (fas["phase1_v03"]["seal_path"], fas["phase1_v03"]["seal_file_sha256"]),
        (fas["phase1_v03"]["event_corpus_path"], fas["phase1_v03"]["event_corpus_sha256"]),
        (fas["phase2a"]["tensor_path"], fas["phase2a"]["tensor_sha256"]),
        (fas["phase2a"]["feature_rows_path"], fas["phase2a"]["feature_rows_sha256"]),
        (fas["phase2a"]["feature_manifest_path"], fas["phase2a"]["feature_manifest_sha256"]),
        (fas["phase2a"]["cache_seal_path"], fas["phase2a"]["cache_seal_file_sha256"]),
        (fas["phase3"]["contract_path"], fas["phase3"]["contract_sha256"]),
        (fas["phase3"]["result_seal_path"], fas["phase3"]["result_seal_file_sha256"]),
        (fas["phase3"]["report_path"], fas["phase3"]["report_sha256"]),
        (fas["phase3"]["heldout_transfer_probe_state_path"], fas["phase3"]["heldout_transfer_probe_state_sha256"]),
        (fas["phase3"]["heldout_transfer_scores_path"], fas["phase3"]["heldout_transfer_scores_sha256"]),
        (fas["phase3"]["probe_core_source_path"], fas["phase3"]["probe_core_source_sha256"]),
        (fas["phase3"]["phase3_source_path"], fas["phase3"]["phase3_source_sha256"]),
        (fas["phase3"]["scipy_wheel_path"], fas["phase3"]["scipy_wheel_sha256"]),
        (binding["fas_s01_lineage_only"]["s01_3_result_seal_path"], binding["fas_s01_lineage_only"]["s01_3_result_seal_file_sha256"]),
        (binding["fas_s01_lineage_only"]["s01_3_metrics_path"], binding["fas_s01_lineage_only"]["s01_3_metrics_sha256"]),
    ]
    checked: list[dict] = []
    for raw_path, expected in checks:
        path = Path(raw_path)
        if not path.is_file():
            raise RuntimeError(f"Missing bound parent artifact: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Parent hash mismatch for {path}: {actual} != {expected}")
        checked.append({"path": raw_path, "sha256": actual})

    closure = read_json(Path(fas["closure"]["path"]))
    if (closure["terminal_disposition"] != "SENSOR_FAIL_NO_SIGNAL" or
            closure["phase3_result_root_sha256"] != fas["phase3"]["result_root_sha256"]):
        raise RuntimeError("FAS-00 closure does not match the bound terminal result")
    report = read_json(Path(fas["phase3"]["report_path"]))
    transfer = report["probe_results"]["HELDOUT_TERM_EXACT_TARGET"]
    for slice_name, expected in (
        ("test_context_term_3", fas["phase3"]["heldout_context_term_3"]),
        ("test_entity_term_7", fas["phase3"]["heldout_entity_term_7"]),
    ):
        actual = transfer["evaluations"][slice_name]["overall"]
        if (actual["balanced_accuracy"] != expected["balanced_accuracy"] or
                actual["accuracy"] != expected["accuracy"] or
                actual["support"] != expected["support"]):
            raise RuntimeError(f"Bound historical metrics mismatch for {slice_name}")
    return checked


def local_rows() -> list[dict]:
    rows = []
    for relative in ALLOWLIST:
        path = ROOT / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"Missing S02 construction file: {path}")
        rows.append({"path": relative, "sha256": sha256_file(path)})
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file() and path != SEAL}
    if actual != set(ALLOWLIST):
        raise RuntimeError(f"S02 packet inventory differs from allowlist: {sorted(actual ^ set(ALLOWLIST))}")
    return sorted(rows, key=lambda row: row["path"].encode("utf-8"))


def seal() -> None:
    if SEAL.exists():
        raise RuntimeError(f"Refusing to overwrite existing construction seal: {SEAL}")
    binding = read_json(ROOT / "contracts" / "parent-binding-v01.json")
    checked = verify_parent_files(binding)
    rows = local_rows()
    disposition = read_json(ROOT / "seals" / "construction-disposition-v01.json")
    if (disposition["S02_PACKET_READY"] is not True or
            disposition["S02_FINAL_POSITION_EXTRACTION_AUTHORIZED"] is not False or
            disposition["S02_READOUT_ANALYSIS_AUTHORIZED"] is not False or
            disposition["S02_MODEL_CONTACT_PERFORMED"] is not False):
        raise RuntimeError("Construction disposition crosses an authorization boundary")
    result = {
        "seal_id": "FAS_S02_CONSTRUCTION_V01",
        "experiment_id": "fas-s02-original-corpus-readout-surface-attribution-v01",
        "root_sha256": canonical_root(rows),
        "canonicalization": "SHA-256 of UTF-8 '<relative_posix_path> <file_sha256>\\n' rows sorted by UTF-8 path bytes.",
        "files": rows,
        "verified_parent_files": checked,
        "model_contact_performed": False,
        "feature_extraction_performed": False,
        "probe_training_performed": False,
    }
    SEAL.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"S02_CONSTRUCTION_SEALED root_sha256={result['root_sha256']} files={len(rows)} parents_verified={len(checked)}")


def verify() -> None:
    seal_data = read_json(SEAL)
    rows = local_rows()
    if rows != seal_data["files"] or canonical_root(rows) != seal_data["root_sha256"]:
        raise RuntimeError("S02 construction packet hash tree mismatch")
    binding = read_json(ROOT / "contracts" / "parent-binding-v01.json")
    checked = verify_parent_files(binding)
    if checked != seal_data["verified_parent_files"]:
        raise RuntimeError("Verified parent artifact inventory changed")
    print(f"S02_CONSTRUCTION_VERIFIED root_sha256={seal_data['root_sha256']} files={len(rows)} parents_verified={len(checked)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    seal() if args.seal else verify()


if __name__ == "__main__":
    main()
