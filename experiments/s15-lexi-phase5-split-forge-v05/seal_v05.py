"""Seal the prose-only v05 correction against the v04 verified run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v05")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    correction = read("VERSION-CORRECTION.json")
    parent = read("PHASE5-SEAL.json")
    parent_replay = read("INDEPENDENT-REPLAY.json")
    comparison = read("PHASE5-COMPARISON.json")
    if parent["seal_sha256"] != correction["parent_seal_sha256"]:
        raise ValueError("v05 does not bind to v04 parent seal")
    if parent_replay["status"] != "PASS" or correction["metrics_changed"]:
        raise ValueError("Parent replay or no-metrics-change contract failed")
    payload = {
        "status": "SEALED_AWAITING_POST_CORRECTION_REPLAY",
        "version": "LEXI_PHASE5_REPORT_CORRECTION_v05",
        "parent_v04_seal_sha256": parent["seal_sha256"],
        "run_disposition": comparison["disposition"],
        "scope": "report-time correction only; v04 training, predictions, and metric replay inherited unchanged",
        "sealed_outputs": {
            name: sha(OUT / name) for name in (
                "INPUT-INVENTORY.json", "PHASE5-COMPARISON.json", "FINAL-REPORT.md",
                "FINALIZATION-RECEIPT.json", "REPLAY-1.json", "PHASE5-SEAL.json",
                "INDEPENDENT-REPLAY.json", "VERSION-CORRECTION.json",
            )
        },
        "correction_sources": {
            name: sha(HERE / name) for name in ("correct_report_v05.py", "seal_v05.py", "replay_v05.py")
        },
        "protected_evaluation_opened": False,
    }
    payload["seal_sha256"] = canonical_hash(payload)
    with (OUT / "V05-CORRECTION-SEAL.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
