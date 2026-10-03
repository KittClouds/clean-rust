"""Versioned objective-only wrapper; prior constructions remain byte-for-byte frozen."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
P2_SOURCE = SOURCE.parent / "ff-s15-semantic-graft-phase2-causal-01"
sys.path.insert(0, str(P2_SOURCE))
import p2_contract as p2
from p2_contract import (NVME, PHASE1_OUTPUT, SUBSTRATE, default_config, pad_candidates,
                         state_hash, sha_file, write_json, supervision_abi, canon_hash)
sys.path.insert(0, str(SOURCE))

OUTPUT = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase3-causal-20261001")
P2_OUTPUT = p2.OUTPUT
P2_RECEIPT_SHA = "dc0657b5cdb80e6ca4c8afd8f3a493ac6fd7691d1b59ff624dd6a1bd120a1356"
ARM = "P3-BALANCED"
GLOBAL_GROUPS = {"SRC-GOAL": [1], "SRC-MISSING": [2, 5], "SRC-CONTRADICTION": [3]}
CANDIDATE_GROUPS = {"SRC-LEGAL": [0], "SRC-LEGAL-GOAL": [1]}


def verify_prior():
    p2.verify_spec(json.loads((P2_OUTPUT / "PHASE2-SPEC.json").read_text()))
    if sha_file(P2_OUTPUT / "PHASE2-RECEIPT.json") != P2_RECEIPT_SHA:
        raise ValueError("Phase 2 receipt changed")
    receipt = json.loads((P2_OUTPUT / "PHASE2-RECEIPT.json").read_text())
    for name, digest in receipt["files"].items():
        if sha_file(P2_OUTPUT / name) != digest:
            raise ValueError("Phase 2 bound file changed: " + name)
    seal = json.loads((P2_OUTPUT / "FINAL-SEAL.json").read_text())
    for name, digest in seal["bindings"].items():
        if sha_file(P2_OUTPUT / name) != digest:
            raise ValueError("Phase 2 seal changed: " + name)
    return receipt, json.loads((P2_OUTPUT / "PHASE2-SPEC.json").read_text())


def freeze(registry, candidate_audit):
    if (OUTPUT / "PHASE3-SPEC.json").exists():
        raise ValueError("Phase 3 identity already frozen")
    receipt, prior = verify_prior()
    tests = json.loads((OUTPUT / "HARNESS-TESTS.json").read_text())
    if tests["status"] != "PASS" or tests["skipped"]:
        raise ValueError("Phase 3 harness must pass including CUDA")
    training = dict(prior["training"])
    training.update(selection="minimum .5 J_S + .5 J_E; earlier epoch wins exact ties",
                    early_stopping_patience=None, budget="20 full TRAIN passes; one arm only")
    spec = {
        "schema": "frozen-fabrique.semantic-graft-phase3-causal/v1", "arm": ARM,
        "question": "Unique-source balanced supervision under unchanged causal construction",
        "substrate": SUBSTRATE, "representation_id": prior["representation_id"],
        "phase2_receipt_sha256": P2_RECEIPT_SHA,
        "phase2_spec_sha256": sha_file(P2_OUTPUT / "PHASE2-SPEC.json"),
        "architecture_sha256": prior["architecture_sha256"], "surface": prior["surface"],
        "latent_dimensions": {"s": 64, "e": 64}, "trainable_parameters": 460662,
        "initial_state_sha256": prior["initial_state_sha256"],
        "initialization_artifact_sha256": prior["initialization_artifact_sha256"],
        "reference_sigma_sha256": prior["reference_sigma_sha256"],
        "supervision_abi_sha256": canon_hash(supervision_abi()),
        "seed": prior["seed"], "training": training, "arithmetic": prior["arithmetic"],
        "TRAIN_rows": 20000, "DEV_rows": 2000, "candidate_convention": prior["candidate_convention"],
        "global_source_groups": GLOBAL_GROUPS, "candidate_source_groups": CANDIDATE_GROUPS,
        "TRAIN_prevalence": registry["TRAIN_prevalence"],
        "objective": {
            "binary": "-.5*(y/pi*log(p)+(1-y)/(1-pi)*log(1-p)); TRAIN pi only",
            "source_reduction": "mean supervised entries per head, mean heads per source, mean sources per family",
            "missing_source": "mean(balanced presence BCE, unchanged masked SmoothL1 count); one source unit",
            "coefficients": {"S": 1., "E": 1., "A": .5, "CF": .5, "pair": .25, "var": .05},
            "pair_and_variance": "unchanged P2-CONSIST executable functions and population",
            "CF": "dormant", "raw_latent_R": "retired"},
        "selection": {
            "rule": ".5 mean unique global binary source BCE + .5 mean unique candidate source BCE",
            "weight_prevalence": "frozen TRAIN prevalence, never DEV prevalence",
            "count_proxy": "no extra vote; missing-presence binary head is the source representative",
            "excluded": ["action", "renderer", "variance", "count proxy extra vote"],
            "threshold": .5},
        "pair_contract": prior["pair_contract"], "variance_contract": prior["variance_contract"],
        "target_source_registry_sha256": sha_file(OUTPUT / "TARGET-SOURCE-REGISTRY.json"),
        "candidate_audit_sha256": sha_file(OUTPUT / "CANDIDATE-AUDIT.json"),
        "harness_tests_sha256": sha_file(OUTPUT / "HARNESS-TESTS.json"),
        "source_files": {p.name: sha_file(p) for p in sorted(SOURCE.iterdir())
                         if p.is_file() and p.suffix in (".py", ".md")},
        "prior_comparator": "frozen P2-CONSIST selected epoch 13; inference only",
        "unresolved_targets": registry["identity_audit"]["unresolved_targets"],
        "no_protected_TEST_or_BANK_v2": True, "no_new_architecture_or_supervision": True,
    }
    write_json(OUTPUT / "PHASE3-SPEC.json", spec)
    return spec


def verify_spec(spec):
    verify_prior()
    registry = json.loads((OUTPUT / "TARGET-SOURCE-REGISTRY.json").read_text())
    for name, digest in registry["canonical_code_hashes"].items():
        if sha_file(Path(name)) != digest:
            raise ValueError("Canonical source changed: " + name)
    for name, digest in spec["source_files"].items():
        if sha_file(SOURCE / name) != digest:
            raise ValueError("Frozen Phase 3 source changed: " + name)
    for filename, field in (("TARGET-SOURCE-REGISTRY.json", "target_source_registry_sha256"),
                            ("CANDIDATE-AUDIT.json", "candidate_audit_sha256"),
                            ("HARNESS-TESTS.json", "harness_tests_sha256")):
        if sha_file(OUTPUT / filename) != spec[field]:
            raise ValueError("Frozen preflight changed: " + filename)
