"""Phase 1 wrapper: import the immutable Phase 0 implementation, never modify it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
SOURCE = Path(__file__).resolve().parent
PHASE0 = SOURCE.parent / "ff-s15-semantic-graft-phase0-02"
sys.path.insert(0, str(PHASE0))

from graft.contracts import (NVME, canon_hash, default_config, sha_file,
                             supervision_abi, write_json)
from graft.construct import verify_parent
from graft.train import verify_phase0_lock

OUTPUT = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase1-causal-20261001")
PHASE0_LOCK_SHA = "4e1cc3e3d807bb001a71ab6c50131dd9c7e76f95395dc8cfa710464bedb15279"
SUBSTRATE = "causal_base"


def specification():
    return {
        "schema": "frozen-fabrique.semantic-graft-phase1-causal/v1",
        "substrate": SUBSTRATE,
        "phase0_lock_sha256": PHASE0_LOCK_SHA,
        "candidate_convention": {
            "m_cap": 28, "amendment_authority": "User accepted recommended cap 28",
            "identities": "unchanged complete Phase 0 observable action enumeration",
            "ordering": "unchanged canonical ordering; never permuted as augmentation",
            "padding": "PAD ordinal zero; mask false; no loss or metric contribution",
            "truncation": False,
        },
        "TRAIN_rows": 20000, "DEV_rows": 2000,
        "seed": 20261001, "device": "cuda:0", "arithmetic": "FP32",
        "attention_kernel": "deterministic SDPA math; frozen architecture unchanged",
        "training": {
            "optimizer": "AdamW", "lr": .001, "minimum_lr": .0001,
            "schedule": "cosine over maximum epochs", "weight_decay": .0001,
            "batch_size": 128, "max_epochs": 20, "gradient_clip": 1.0,
            "early_stopping_patience": 6, "checkpoint_each_epoch": True,
            "selection": "lowest exact aggregate DEV five-term loss; earlier epoch wins ties",
            "renderer_pairs_per_batch": 8,
            "backbone_frozen": True,
        },
        "architecture": "Exact Phase 0 causal_late model, without redefinition",
        "surface": "Phase 0 final_plus_mean; no new extraction",
        "loss_semantics": default_config()["loss"],
        "scoring": {
            "source": "Phase 0 measurements and masks; add macro-F1, class support, trivial priors",
            "threshold": .5, "count": "Phase 0 raw MAE and max(0,floor(raw+.5)) exact count",
            "checkpoint_metric": "S + .1 E + .25 A + 1 CF + .1 R, exact population denominators",
            "CF": "inactive; no canonical candidate-support pairs",
            "diagnostics": ["supervised semantic separability", "within-world candidate variance",
                            "existing meaning-preserving renderer pairs"],
        },
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "no_accuracy_exit_threshold": True, "no_cross_fabric_alignment": True,
    }


def verify_frozen():
    path = NVME / "PHASE0-LOCK.json"
    if sha_file(path) != PHASE0_LOCK_SHA:
        raise ValueError("Phase 0 lock identity changed")
    lock = verify_phase0_lock(path)
    verify_parent()
    return lock


def pad_candidates(batch, cap=28):
    import torch
    count = batch["A"].shape[1]
    if count > cap:
        raise ValueError("candidate capacity exceeded; no truncation")
    if count == cap:
        return batch
    for key in ("A", "candidate_mask", "candidate_y", "candidate_available"):
        value = batch[key]
        shape = list(value.shape)
        shape[1] = cap
        padded = torch.zeros(shape, dtype=value.dtype, device=value.device)
        padded[:, :count] = value
        batch[key] = padded
    return batch


def freeze_spec():
    lock = verify_frozen()
    destination = OUTPUT / "PHASE1-SPEC.json"
    if destination.exists():
        raise ValueError("Phase 1 spec already exists; preserve existing attempt")
    spec = specification()
    spec["architecture_sha256"] = lock["package_files"]["graft\\model.py"]
    spec["supervision_abi_sha256"] = canon_hash(supervision_abi())
    spec["source_files"] = {str(p.relative_to(SOURCE)): sha_file(p)
                            for p in sorted(SOURCE.glob("*.py"))}
    write_json(destination, spec)
    return spec


def verify_spec(spec):
    verify_frozen()
    for name, digest in spec["source_files"].items():
        if sha_file(SOURCE / name) != digest:
            raise ValueError("Phase 1 source changed after freeze: " + name)
