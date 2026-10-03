"""Independent CPU replay for the sealed Phase 5 DEV run."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUN = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v03")
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v04")
sys.path.insert(0, str(Path(r"C:/code land/clean-rust/experiments/s15-lexi-phase5-split-forge-v03")))

from lexi_contract import verify as verify_frozen_inputs
from report import Population, metrics
from comparison_v04 import compare_depths


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def replay_checks():
    verify_frozen_inputs()
    inventory = read(OUT / "INPUT-INVENTORY.json")
    checked = 0
    for row in inventory["files"]:
        path = RUN / row["relative_path"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
            raise ValueError("Source-run inventory mismatch: " + row["relative_path"])
        checked += 1

    summary = read(OUT / "PHASE5-COMPARISON.json")
    if summary["candidate_and_population"]["protected_test_truth_opened"] is not False:
        raise ValueError("Protected truth status is not closed")
    if summary["metric_replay"]["protected_files_opened"] != 0:
        raise ValueError("Protected-file access recorded")
    pop = Population("DEV", device="cpu")
    if len(pop.meta) != 6000 or len({item["root"] for item in pop.meta}) != 3000:
        raise ValueError("DEV population identity/count mismatch")

    reports = [
        ("INIT", read(RUN / "INIT-REPORT.json")),
        ("BRIDGE", read(RUN / "BRIDGE-REPORT.json")),
        ("A_DETERMINISTIC", read(RUN / "A-REPORT.json")),
    ]
    b_report = read(RUN / "B-REPORT.json")
    reports.extend(("B_STOCHASTIC", item) for item in [b_report["operational"], *b_report["diagnostic_seeds"]])
    metric_depths = 0
    for identity, report in reports:
        for depth, expected in report["depths"].items():
            path = RUN / "predictions" / identity / f"{report['seed']}-T{depth}.npz"
            with np.load(path, allow_pickle=False) as archive:
                arrays = [archive[name] for name in ("g", "c", "action", "s", "e_stats")]
                if arrays[0].shape != (6000, 6) or arrays[1].shape != (6000, 171, 7):
                    raise ValueError("Prediction geometry mismatch: " + str(path))
                if arrays[2].shape != (6000,) or arrays[3].shape != (6000, 64):
                    raise ValueError("Prediction shape mismatch: " + str(path))
                if not all(np.isfinite(item).all() for item in (arrays[0], arrays[1], arrays[3], arrays[4])):
                    raise ValueError("Nonfinite prediction: " + str(path))
                observed = metrics(pop, *arrays)
            if observed != expected:
                raise ValueError(f"Metric replay mismatch: {identity} T{depth}")
            metric_depths += 1

    # Recompute frozen bridge tensor identity without loading the backbone.
    import torch
    bridge = torch.load(RUN / "models" / "BRIDGE" / "best.pt", map_location="cpu", weights_only=True)
    bridge_checks = 0
    for arm in ("A_DETERMINISTIC", "B_STOCHASTIC"):
        state = torch.load(RUN / "models" / arm / "best.pt", map_location="cpu", weights_only=True)
        for key, tensor in bridge.items():
            if not torch.equal(tensor, state["seed." + key]):
                raise ValueError(f"Frozen bridge changed: {arm}/{key}")
            bridge_checks += 1

    comparison = compare_depths(pop, read(RUN / "A-REPORT.json"), b_report)
    expected_comparison = summary["results"]["comparison"]
    # Compare stable operational facts independently; finalizer adds semantic intervals.
    for key in ("unit", "eligible_roots", "eligible_rows", "B_terminal_action_differences_by_seed",
                "disposition_before_semantic_preservation", "axis_null_policy"):
        if comparison[key] != expected_comparison[key]:
            raise ValueError("Comparison replay mismatch: " + key)
    return {
        "status": "PASS",
        "inventory_files_verified": checked,
        "inventory_bytes_verified": inventory["total_bytes"],
        "DEV_metric_depths_replayed": metric_depths,
        "bridge_tensors_exactly_replayed": bridge_checks,
        "comparison_core_replayed": True,
        "protected_files_opened": 0,
        "DEV_roots": 3000,
    }


def verify_seal():
    seal = read(OUT / "PHASE5-SEAL.json")
    digest = seal.pop("seal_sha256")
    if canonical_hash(seal) != digest:
        raise ValueError("Seal identity hash mismatch")
    for name, expected in seal["sealed_outputs"].items():
        path = OUT / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("Sealed output changed: " + name)
    return digest


def main():
    verify_seal_mode = "--verify-seal" in sys.argv[1:]
    out_name = "INDEPENDENT-REPLAY.json" if verify_seal_mode else "REPLAY-1.json"
    seal_hash = verify_seal() if verify_seal_mode else None
    result = replay_checks()
    result["mode"] = "independent post-seal replay" if verify_seal_mode else "independent pre-seal replay"
    result["seal_sha256"] = seal_hash
    result["replay_script_sha256"] = sha256(HERE / "replay_v04.py")
    with (OUT / out_name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
