"""Verify the completed, sealed causal Phase 4A output without opening protected data."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from p4_contract import OUTPUT, P2_SEED, P3_REFERENCE, sha_file, verify_inherited, verify_spec


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    spec = json.loads((OUTPUT / "PHASE4A-SPEC.json").read_text())
    receipt = json.loads((OUTPUT / "PHASE4A-RECEIPT.json").read_text())
    arm = receipt["arm"]
    seal = json.loads((OUTPUT / "FINAL-SEAL.json").read_text())
    require(receipt["status"] == "CAUSAL_PHASE4A_COMPLETE", "Completion receipt status invalid")
    require(seal["status"] == "PHASE4A_OUTPUTS_SEALED", "Final seal status invalid")
    require(seal["receipt_sha256"] == sha_file(OUTPUT / "PHASE4A-RECEIPT.json"), "Receipt hash mismatch")
    for name, digest in seal["bindings"].items():
        path = OUTPUT / name
        require(path.is_file() and sha_file(path) == digest, "Final seal binding mismatch: " + name)
    for name, digest in receipt["files"].items():
        path = OUTPUT / name
        require(path.is_file() and sha_file(path) == digest, "Receipt file binding mismatch: " + name)
    verify_spec(spec)
    verify_inherited()
    require(sha_file(P2_SEED) == spec["primary_seed"]["artifact_sha256"], "P2 seed changed")
    require(sha_file(P3_REFERENCE) == spec["preserved_reference"]["artifact_sha256"], "P3 reference changed")
    require(spec["candidate_convention"]["m_max"] == 28, "Candidate contract changed")
    require(spec["preflight"]["candidate_audit"]["maximum"] == 28, "Candidate audit maximum mismatch")
    require(spec["preflight"]["candidate_audit"]["truncated_candidates"] == 0,
            "Candidate truncation detected")
    require(receipt["protected_TEST_truth_opened"] is False, "Protected TEST was opened")
    require(receipt["BANK_v2_used"] is False, "BANK-v2 was used")
    require(receipt["depths_scored"] == [0, 1, 2, 3, 4], "Depth ladder incomplete")
    require(arm["epochs"] == 20 and arm["full_TRAIN_passes"] == 20, "Training budget incomplete")
    batch = spec["training"]["batch_size"]
    expected_steps = 20 * math.ceil(20000 / batch)
    require(arm["optimizer_steps"] == expected_steps, "Optimizer step count mismatch")
    require(arm["frozen_backbone_optimizer_steps"] == 0 and arm["frozen_seed_graft_optimizer_steps"] == 0,
            "Frozen parameters were optimized")
    require(arm["checkpoint_replay"] and receipt["depth_curve"]["P2_R0_bitwise_seed_state_replay"],
            "P2 seed replay failed")
    curve = receipt["depth_curve"]
    require(set(curve["depths"]) == {"0", "1", "2", "3", "4"}, "Depth curve incomplete")
    require(curve["P2_R0_metric_replay"], "P2 metric replay failed")
    for depth in map(str, range(5)):
        report_path = OUTPUT / "R4-CAUSAL" / f"DEV-METRICS-depth-{depth}.json"
        report = json.loads(report_path.read_text())
        require(report["depth"] == int(depth), "Depth report identity mismatch")
        require("endpoint" in report and "global" in report and "candidate" in report,
                "Depth report missing state/action metrics")
        for scope in ("global", "candidate"):
            require(bool(report[scope]), "Target metrics missing for " + scope)
        if depth in ("0", "4"):
            require(report["pair_correctness"] is not None, "Renderer correctness decomposition missing")
            for key in ("global", "candidate", "action"):
                require(key in report["pair_correctness"], "Renderer pair scope missing: " + key)
    history = json.loads((OUTPUT / "R4-CAUSAL" / "training-history.json").read_text())
    require(len(history) == 20 and [r["epoch"] for r in history] == list(range(1, 21)),
            "Training history incomplete")
    require((OUTPUT / "R4-CAUSAL" / "best-recurrent.pt").is_file(), "Best recurrent checkpoint missing")
    require(sha_file(OUTPUT / "R4-CAUSAL" / "best-recurrent.pt") == arm["best_recurrent_artifact_sha256"],
            "Best recurrent checkpoint hash mismatch")
    require((OUTPUT / "PHASE4A-HANDOFF.md").is_file(), "Human-readable handoff missing")
    print(json.dumps({"status": "PHASE4A_VERIFIED", "output": str(OUTPUT),
        "arm": arm["arm"], "epochs": arm["epochs"], "optimizer_steps": arm["optimizer_steps"],
        "trainable_recurrent_parameters": arm["trainable_recurrent_parameters"],
        "handoff": receipt["interpretation"], "protected_TEST_truth_opened": False,
        "BANK_v2_used": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "VERIFY_FAILED", "error": str(exc)}), file=sys.stderr)
        raise
