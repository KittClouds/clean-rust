"""Versioned prose-only correction to the already sealed v04 Phase 5 report."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v04")
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v05")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(name):
    return json.loads((PARENT / name).read_text(encoding="utf-8"))


def write_json(path, value):
    # This derived v05 package is resumable until its seal is created.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    permitted_existing = {
        "INPUT-INVENTORY.json", "PHASE5-COMPARISON.json", "FINALIZATION-RECEIPT.json",
        "REPLAY-1.json", "PHASE5-SEAL.json", "INDEPENDENT-REPLAY.json", "FINAL-REPORT.md",
    }
    unexpected = {path.name for path in OUT.iterdir()} - permitted_existing
    if unexpected:
        raise FileExistsError(f"Unexpected correction output already exists: {sorted(unexpected)}")
    parent_seal = read("PHASE5-SEAL.json")
    parent_replay = read("INDEPENDENT-REPLAY.json")
    if parent_replay["status"] != "PASS" or parent_replay["protected_files_opened"] != 0:
        raise ValueError("Parent v04 was not independently replayed")

    inherited = (
        "INPUT-INVENTORY.json", "PHASE5-COMPARISON.json", "FINALIZATION-RECEIPT.json",
        "REPLAY-1.json", "PHASE5-SEAL.json", "INDEPENDENT-REPLAY.json",
    )
    for name in inherited:
        shutil.copy2(PARENT / name, OUT / name)

    comparison = read("PHASE5-COMPARISON.json")
    training = comparison["training_contract"]["training"]
    bridge_s = float(training["BRIDGE"]["training_seconds"])
    a_s = float(training["A_DETERMINISTIC"]["training_seconds"])
    b_s = float(training["B_STOCHASTIC"]["training_seconds"])
    report = (PARENT / "FINAL-REPORT.md").read_text(encoding="utf-8")
    old_line = next((line for line in report.splitlines() if line.startswith("A trained for ")), None)
    if old_line is None or "2.9s" not in old_line or "3.4s" not in old_line:
        raise ValueError("Expected v04 inference/training wording mismatch not found")
    b_op = comparison["results"]["B_stochastic"]["report"]["operational"]
    a_report = comparison["results"]["A_deterministic"]["report"]
    a_latency = a_report["latency"]
    b_latency = b_op["latency"]
    corrected = (
        f"Training time was {bridge_s:.1f}s for the bridge, {a_s:.1f}s for A, and {b_s:.1f}s for B. "
        f"A used {training['A_DETERMINISTIC']['peak_cuda_bytes'] / 1024**2:.1f} MiB peak CUDA memory and "
        f"{training['A_DETERMINISTIC']['trainable_parameters']:,} trainable parameters. B used "
        f"{training['B_STOCHASTIC']['peak_cuda_bytes'] / 1024**2:.1f} MiB and "
        f"{training['B_STOCHASTIC']['trainable_parameters']:,} parameters, including 4,288 scale parameters. "
        f"At batch size {a_latency['batch_rows']}, A inference was {a_latency['T4_seconds'] * 1000:.2f} ms for T4 "
        f"({[round(x * 1000, 2) for x in a_latency['per_step_seconds']]} ms per recurrent step); B was "
        f"{b_latency['T4_seconds'] * 1000:.2f} ms ({[round(x * 1000, 2) for x in b_latency['per_step_seconds']]} ms per step). "
        f"B's measured per-step scale RMS was " + ", ".join(f"{x:.4f}" for x in b_op["scale_RMS"]) + "."
    )
    report = report.replace(old_line, corrected)
    report = report.replace(
        "DEV action support is 333 eligible roots (666 rows). MOVE has 249 roots and is the only action type above the 200-root reliability floor. The two other B trajectories are reported separately in `PHASE5-COMPARISON.json`; they are not averaged or selected.",
        "DEV action support is 333 eligible roots (666 rows). MOVE has 249 roots and is the only action type above the 200-root reliability floor. The two other B trajectories are reported separately in `PHASE5-COMPARISON.json`; they are not averaged or selected. All three B terminal point estimates are below A, while paired bootstrap intervals include zero: this pilot shows no repeatable stochastic benefit, and does not establish a reliable harmful effect.",
    )
    with (OUT / "FINAL-REPORT.md").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(report)

    comparison["status"] = "PHASE5_RUN_COMPLETE_FINALIZED_AND_REPLAYED"
    comparison["version_correction"] = {
        "version": "v05",
        "parent_seal_sha256": parent_seal["seal_sha256"],
        "change_scope": "presentation and finalization status only; no training, prediction, labels, or metric values changed",
        "training_seconds_source": "frozen BRIDGE/A/B model receipts",
        "parent_metric_replay": "PASS; 22 DEV depth reports; 74 frozen bridge tensors",
    }
    write_json(OUT / "PHASE5-COMPARISON.json", comparison)

    correction = {
        "status": "PROSE_CORRECTION_ONLY",
        "parent_version": "v04",
        "parent_seal_sha256": parent_seal["seal_sha256"],
        "parent_post_seal_replay_sha256": sha256(PARENT / "INDEPENDENT-REPLAY.json"),
        "parent_run_inventory_sha256": read("FINALIZATION-RECEIPT.json")["source_run_inventory_sha256"],
        "correction": "v04 Markdown displayed evaluation-time seconds (2.9s/3.4s) as training time; v05 now reports model-receipt training times and separately reports batch inference latency.",
        "correct_training_seconds": {"BRIDGE": bridge_s, "A_DETERMINISTIC": a_s, "B_STOCHASTIC": b_s},
        "metrics_changed": False,
        "training_or_inference_repeated": False,
        "protected_truth_opened": False,
        "artifacts_derived_from_v04": {name: sha256(OUT / name) for name in inherited},
        "files_byte_identical_to_v04": {name: sha256(OUT / name) for name in inherited if name != "PHASE5-COMPARISON.json"},
    }
    write_json(OUT / "VERSION-CORRECTION.json", correction)
    print(json.dumps({"status": correction["status"], "training_seconds": correction["correct_training_seconds"],
                      "parent_seal_sha256": correction["parent_seal_sha256"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
