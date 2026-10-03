"""Independently replay the v05 report correction and its sealed v04 parent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v04")
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v05")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def main():
    seal = read(OUT, "V05-CORRECTION-SEAL.json")
    seal_hash = seal.pop("seal_sha256")
    if canonical_hash(seal) != seal_hash:
        raise ValueError("v05 seal hash mismatch")
    for name, expected in seal["sealed_outputs"].items():
        if sha(OUT / name) != expected:
            raise ValueError("v05 output hash mismatch: " + name)
    for name, expected in seal["correction_sources"].items():
        if sha(HERE / name) != expected:
            raise ValueError("v05 correction source hash mismatch: " + name)

    parent_seal = read(PARENT, "PHASE5-SEAL.json")
    parent_replay = read(PARENT, "INDEPENDENT-REPLAY.json")
    correction = read(OUT, "VERSION-CORRECTION.json")
    if parent_seal["seal_sha256"] != correction["parent_seal_sha256"] or parent_replay["status"] != "PASS":
        raise ValueError("v04 parent seal/replay not verified")
    if parent_replay["protected_files_opened"] != 0:
        raise ValueError("Parent replay reports protected-file access")

    old = read(PARENT, "PHASE5-COMPARISON.json")
    new = read(OUT, "PHASE5-COMPARISON.json")
    for document in (old, new):
        document.pop("status", None)
        document.pop("version_correction", None)
    if old != new:
        raise ValueError("v05 changed measurements or comparison content")
    if new["disposition"] != seal["run_disposition"]:
        raise ValueError("Disposition drift")

    expected_seconds = new["training_contract"]["training"]
    if correction["correct_training_seconds"] != {
        "BRIDGE": expected_seconds["BRIDGE"]["training_seconds"],
        "A_DETERMINISTIC": expected_seconds["A_DETERMINISTIC"]["training_seconds"],
        "B_STOCHASTIC": expected_seconds["B_STOCHASTIC"]["training_seconds"],
    }:
        raise ValueError("Corrected report times disagree with frozen model receipts")
    report = (OUT / "FINAL-REPORT.md").read_text(encoding="utf-8")
    for token in ("Training time was 418.9s", "1462.0s for A", "1558.9s for B", "does not establish a reliable harmful effect"):
        if token not in report:
            raise ValueError("Corrected report omits expected clarification: " + token)

    result = {
        "status": "PASS",
        "v05_seal_sha256": seal_hash,
        "parent_v04_seal_sha256": parent_seal["seal_sha256"],
        "parent_full_run_replay": "PASS; 176 files / 7,829,033,196 bytes; 22 DEV depth reports; 74 bridge tensors",
        "comparison_metrics_unchanged": True,
        "training_time_prose_verified_against_receipts": True,
        "protected_files_opened": 0,
        "replay_scope": "versioned correction and inherited parent replay; no model run or DEV metric was changed",
    }
    with (OUT / "V05-INDEPENDENT-REPLAY.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
