"""Bind finalization outputs and the first independent replay into a seal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v04")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    replay = read("REPLAY-1.json")
    if replay.get("status") != "PASS" or replay.get("protected_files_opened") != 0:
        raise ValueError("Independent pre-seal replay did not pass")
    summary = read("PHASE5-COMPARISON.json")
    receipt = read("FINALIZATION-RECEIPT.json")
    if summary["metric_replay"]["DEV_depth_reports_exactly_recomputed"] != replay["DEV_metric_depths_replayed"]:
        raise ValueError("Replay counts disagree")
    outputs = (
        "INPUT-INVENTORY.json", "PHASE5-COMPARISON.json", "FINAL-REPORT.md",
        "FINALIZATION-RECEIPT.json", "REPLAY-1.json",
    )
    sources = (
        "comparison_v04.py", "finalize.py", "replay_v04.py", "seal_v04.py",
        "test_comparison_v04.py",
    )
    payload = {
        "status": "SEALED_AWAITING_POST_SEAL_REPLAY",
        "lane": "LEXI_LFM230M",
        "phase5_spec_sha256": receipt["phase5_spec_sha256"],
        "source_run_inventory_sha256": receipt["source_run_inventory_sha256"],
        "disposition": summary["disposition"],
        "sealed_outputs": {name: sha256(OUT / name) for name in outputs},
        "finalizer_source_hashes": {name: sha256(HERE / name) for name in sources},
        "protected_evaluation_opened": False,
        "evaluation_boundary": "BANK-v3-core DEV only; protected/test-truth unopened",
    }
    payload["seal_sha256"] = canonical_hash(payload)
    with (OUT / "PHASE5-SEAL.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
