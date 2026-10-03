"""Objective-only causal Phase 2; immutable Phase 0/1 interfaces are imported."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
SOURCE = Path(__file__).resolve().parent
PHASE1_SOURCE = SOURCE.parent / "ff-s15-semantic-graft-phase1-causal-01"
sys.path.insert(0, str(PHASE1_SOURCE))
from contract import (NVME, PHASE0_LOCK_SHA, SUBSTRATE, default_config, pad_candidates,
                      verify_frozen, sha_file, write_json, supervision_abi, canon_hash)

PHASE1_OUTPUT = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase1-causal-20261001")
OUTPUT = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase2-causal-20261001")
PHASE1_RECEIPT_SHA = "dbad6a8a1b83a83f778f4230c30495133ba78fefddb00845d2d16ce60e943534"
ARMS = ("P2-BASE", "P2-CONSIST")


def verify_prior():
    lock = verify_frozen()
    path = PHASE1_OUTPUT / "PHASE1-RECEIPT.json"
    if sha_file(path) != PHASE1_RECEIPT_SHA:
        raise ValueError("Phase 1 receipt changed")
    receipt = json.loads(path.read_text())
    for name,digest in receipt["files"].items():
        if sha_file(PHASE1_OUTPUT / name) != digest:
            raise ValueError("frozen Phase 1 artifact changed: " + name)
    spec = json.loads((PHASE1_OUTPUT / "PHASE1-SPEC.json").read_text())
    for name,digest in spec["source_files"].items():
        if sha_file(PHASE1_SOURCE / name) != digest:
            raise ValueError("Phase 1 implementation changed: " + name)
    return lock, receipt, spec


def specification(cap, representation_id):
    _lock,_receipt,prior_spec = verify_prior()
    training = dict(prior_spec["training"])
    training.update({"selection": "lowest exact own-arm DEV objective; earlier epoch wins ties",
                     "early_stopping_patience": None,
                     "budget": "20 full TRAIN passes in each arm; identical batches and sampled pairs"})
    return {
        "schema": "frozen-fabrique.semantic-graft-phase2-causal/v1",
        "question": "Prediction-consistent informative state without raw latent invariance reward",
        "substrate": SUBSTRATE, "representation_id": representation_id,
        "phase0_lock_sha256": PHASE0_LOCK_SHA, "phase1_receipt_sha256": PHASE1_RECEIPT_SHA,
        "architecture_sha256": prior_spec["architecture_sha256"],
        "supervision_abi_sha256": canon_hash(supervision_abi()),
        "surface": prior_spec["surface"], "s_dim": 64, "e_dim": 64,
        "seed": prior_spec["seed"], "arithmetic": "FP32; deterministic CUDA SDPA math",
        "TRAIN_rows": 20000, "DEV_rows": 2000,
        "candidate_convention": {"m_cap": cap, "retain_every_canonical_candidate": True,
                                 "ordering": "unchanged Phase 0 action identities and binding ordinals",
                                 "padding": "zero PAD; explicit false mask; no loss or metric",
                                 "Phase1_truncated_candidates": 0},
        "arms": {
            "P2-BASE": {"coefficients": {"S":1.,"E":.1,"A":.25,"CF":1.,"R":.1},
                        "objective": "Frozen Phase 1 five-term objective including raw latent R"},
            "P2-CONSIST": {"coefficients": {"S":1.,"E":1.,"A":.5,"CF":.5,"pair":.25,"var":.05},
                           "objective": "S+E+.5A+.5CF+.25pair+.05var; no raw latent R"}},
        "training": training,
        "pair_contract": {
            "population": "existing Phase 0 TRAIN/DEV renderer pairs only",
            "global": "Bernoulli JS averaged over shared supervised targets per pair",
            "count_distribution": "Current 0/1 count proxy: clip raw predicted count into [0,1] as P(count=1); scoring remains raw SmoothL1/MAE",
            "candidate": "Bernoulli JS: supervised target mean then valid aligned candidate mean",
            "action": "categorical JS over valid exhaustive candidates if full identities align; no need for ACT endpoint label",
            "identity": "canonical action keys + exact binding ordinal tensors + masks",
            "unaligned": "omit E and A consistency for that pair; retain available S",
            "epsilon": 1e-7, "sum": "pair_S + pair_E + pair_A; pair-mean population reduction",
        },
        "variance_contract": {
            "reference": "untrained Phase 0 seed initialization, TRAIN-only normalizer, full TRAIN",
            "statistic": "per-coordinate population standard deviation; correction=0",
            "floor_multiplier": .5, "loss": "mean coordinate squared positive floor shortfall",
            "numerical_variance_floor": 1e-12,
            "DEV_selection": "mean fixed sequential DEV minibatch variance penalties; reference stays TRAIN-only",
            "covariance_penalty": False,
        },
        "scoring": prior_spec["scoring"],
        "external_method_reference": "https://arxiv.org/abs/2105.04906",
        "not_full_VICReg": True, "no_hyperparameter_tuning": True,
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "no_new_surfaces_or_architecture": True, "no_cross_lane_winner": True,
    }


def state_hash(model):
    import hashlib
    h = hashlib.sha256()
    for name,tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous().numpy()
        h.update(name.encode()); h.update(str(array.dtype).encode())
        h.update(str(array.shape).encode()); h.update(array.tobytes())
    return h.hexdigest()


def freeze(spec):
    if (OUTPUT / "PHASE2-SPEC.json").exists():
        raise ValueError("Phase 2 identity already frozen; do not overwrite")
    tests=json.loads((OUTPUT / "HARNESS-TESTS.json").read_text())
    if tests["status"]!="PASS" or tests["skipped"]:
        raise ValueError("Phase 2 harness did not qualify")
    spec["source_files"] = {str(p.relative_to(SOURCE)):sha_file(p)
                            for p in sorted(SOURCE.iterdir()) if p.is_file() and p.suffix in (".py",".md")}
    spec["harness_tests_sha256"] = sha_file(OUTPUT / "HARNESS-TESTS.json")
    spec["candidate_audit_sha256"] = sha_file(OUTPUT / "CANDIDATE-AUDIT.json")
    write_json(OUTPUT / "PHASE2-SPEC.json", spec)


def verify_spec(spec):
    verify_prior()
    for name,digest in spec["source_files"].items():
        if sha_file(SOURCE / name) != digest:
            raise ValueError("Phase 2 source changed: " + name)
