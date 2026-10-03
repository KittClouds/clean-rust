"""Seal Phase 2C input and source identities before signature auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_DATA = Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08")
DEFAULT_SELECTION = Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12")
DEFAULT_PHASE2B = Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\equivalent-substitution-v01")
DEFAULT_OUT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01")

REPOSITORY_SOURCES = (
    "docs/jev-information-density-v0.8c-phase2c-cross-atom.md",
    "experiments/jev-information-density-v08c/v08c-phase2c-contract.json",
    "experiments/jev-information-density-v08c/phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/audit_phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_audit.py",
    "experiments/jev-information-density-v08c/tests/test_phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/v08c-phase2b-contract.json",
    "experiments/jev-information-density-v08c/v08c-phase2b-atom-stage-contract.json",
    "experiments/jev-information-density-v08c/build_phase2b_atom_candidates.py",
    "experiments/jev-information-density-v08c/optimize_matched_banks.py",
    "experiments/jev-information-density-v08b/v08b-contract.json",
    "experiments/jev-information-density-v08b/build_factorial_banks.py",
    "experiments/jev-information-density-v08/select_banks.py",
    "experiments/jev-information-density-v08/v08-contract.json",
    "experiments/jev-information-density-v08/audit_generator_outputs.py",
    "experiments/jev-frozen-readout-v01/probe.py",
    "experiments/jev-frozen-scaling-v05/train_v05.py",
    "experiments/jev-frozen-scaling-v05/v05-contract.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_expected(actual: dict[str, str], expected: dict[str, str], label: str) -> None:
    for key, expected_hash in expected.items():
        if actual.get(key) != expected_hash:
            raise ValueError(f"{label} hash mismatch for {key}")


def input_paths(data_dir: Path, selection_dir: Path, phase2b_dir: Path) -> dict[str, Path]:
    return {
        "group_records_sha256": data_dir / "group-records.jsonl",
        "canonical_episodes_sha256": data_dir / "new-universe-canonical.jsonl",
        "r100_manifest_sha256": selection_dir / "new-tight-r100-group-ids.jsonl",
        "c100_manifest_sha256": selection_dir / "new-tight-c100-group-ids.jsonl",
        "eval_manifest_sha256": selection_dir / "new-tight-eval-group-ids.jsonl",
        "input_target_consistency_sha256": data_dir / "input-target-consistency.json",
        "phase2b_cm100_atom_provisional_sha256": phase2b_dir / "cm100-provisional-ids.jsonl",
        "phase2b_rm100_atom_provisional_sha256": phase2b_dir / "rm100-provisional-ids.jsonl",
        "phase2b_atom_validation_sha256": phase2b_dir / "candidate-validation.json",
    }


def lineage_paths(phase2b_dir: Path) -> dict[str, Path]:
    parent = phase2b_dir.parent
    return {
        "parent_phase2b_freeze_sha256": parent / "phase2b-freeze-receipt.json",
        "atom_stage_freeze_sha256": parent / "atom-stage-freeze-receipt.json",
        "atom_stage_validation_sha256": phase2b_dir / "candidate-validation.json",
        "phase2b_construction_sha256": phase2b_dir / "construction-report.json",
        "phase2b_objective_contract_sha256": HERE / "v08c-phase2b-contract.json",
        "phase2b_atom_contract_sha256": HERE / "v08c-phase2b-atom-stage-contract.json",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--selection-dir", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--phase2b-dir", type=Path, default=DEFAULT_PHASE2B)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.outdir.exists() and any(args.outdir.iterdir()):
        raise FileExistsError(f"refusing to freeze over existing output: {args.outdir}")
    contract_path = HERE / "v08c-phase2c-contract.json"
    contract: dict[str, Any] = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_training_signature_audit":
        raise ValueError("Phase 2C contract status is not the pre-audit freeze state")

    sources = {rel: sha256_file(ROOT / rel) for rel in REPOSITORY_SOURCES}
    for relative, expected in contract.get("source_pins", {}).items():
        if sources.get(relative) != expected:
            raise ValueError(f"pinned prior protocol source changed: {relative}")
    external_paths = {**input_paths(args.data_dir, args.selection_dir, args.phase2b_dir), **lineage_paths(args.phase2b_dir)}
    external = {key: sha256_file(path) for key, path in external_paths.items()}
    check_expected(
        {key: external[key] for key in contract["inputs"]},
        contract["inputs"],
        "Phase 2C input",
    )
    check_expected(
        {key: external[key] for key in contract["lineage"] if key in external},
        {key: value for key, value in contract["lineage"].items() if key in external},
        "Phase 2B lineage",
    )

    consistency = json.loads(external_paths["input_target_consistency_sha256"].read_text(encoding="utf-8"))
    if (
        consistency.get("status") != "PASS"
        or consistency.get("input_target_consistency", {}).get("conflicting_inputs") != 0
    ):
        raise ValueError("pinned input-target consistency receipt does not pass with zero conflicts")

    test = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(HERE / "tests"),
            "-p",
            "test_phase2c_training_signatures.py",
            "-v",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if test.returncode != 0:
        raise RuntimeError(f"Phase 2C signature tests failed:\n{test.stdout}\n{test.stderr}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-audit-freeze",
        "status": "SEALED_BEFORE_SIGNATURE_AUDIT",
        "contract_sha256": sha256_file(contract_path),
        "repository_sources": sources,
        "external_inputs": {key: {"path": str(path), "sha256": external[key]} for key, path in external_paths.items()},
        "projection_tests": {
            "status": "PASS",
            "test_count": 7,
            "command": "python -m unittest discover -s experiments/jev-information-density-v08c/tests -p test_phase2c_training_signatures.py -v",
            "stdout_sha256": hashlib.sha256(test.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(test.stderr.encode("utf-8")).hexdigest(),
        },
        "authorization": {
            "metadata_signature_audit": True,
            "support_mobility_census": True,
            "candidate_search": False,
            "model_contact": False,
            "backbone_inference": False,
            "phoenix_access": False,
        },
    }
    output = args.outdir / "phase2c-freeze-receipt.json"
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output), "contract_sha256": receipt["contract_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
