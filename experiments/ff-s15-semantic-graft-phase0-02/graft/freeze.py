"""Bind the executable Phase0 package, canonical sources, data and checks."""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

from .contracts import (BANK_CODE, EXPERIMENT, NVME, PARENT_LOCK_SHA256, SUBSTRATES, canon_hash,
                        default_config, sha_file, supervision_abi, write_json)
from .construct import verify_parent
from .dataset import PackedBank, assert_disjoint


def main():
    path = NVME / "PHASE0-LOCK.json"
    if path.exists():
        raise FileExistsError("Phase0 lock is already sealed; do not overwrite")
    config = default_config()
    abi = supervision_abi()
    verify_parent()
    check_path = NVME / "checks" / "verification.json"
    checks = json.loads(check_path.read_text())
    if checks["status"] != "PHASE0_CHECKS_PASS" or checks["config_sha256"] != canon_hash(config):
        raise ValueError("verification contract mismatch")
    for relative, digest in checks["source_files"].items():
        if sha_file(EXPERIMENT / relative) != digest:
            raise ValueError(f"source changed since checks: {relative}")
    write_json(EXPERIMENT / "config.json", config)
    write_json(EXPERIMENT / "supervision-abi.json", abi)
    write_json(EXPERIMENT / "state-abi.json", {
        "schema": "frozen-fabrique.semantic-candidate-state/v2",
        "semantic_slot": {"name": "s", "shape": ["B", 64], "dtype": "float32", "scope": "task/world state"},
        "candidate_slots": {"name": "e", "shape": ["B", "M", 64], "dtype": "float32", "scope": "candidate-conditioned partially supervised epistemic state"},
        "latent_dimensions_have_named_semantics": False, "cross_fabric_coordinate_alignment": False,
        "decoders": {"global": abi["global"], "candidate": abi["candidate"], "action": abi["action_endpoint"]},
        "forward_inputs": "frozen H, observable A, availability/padding masks; encoder additionally uses already extracted masked entity-local vectors",
        "runtime_provenance": "MODEL_ESTIMATE only with trained artifact; unavailable targets never emitted as false",
    })
    populations = {}
    data = {}
    summaries = {}
    for split in ("TRAIN", "DEV"):
        folder = NVME / "data" / split
        populations[split] = PackedBank(folder, SUBSTRATES[0], config)
        manifest = populations[split].manifest
        extension = populations[split].extension
        if manifest["rows"] != config["train_rows" if split == "TRAIN" else "dev_rows"]:
            raise ValueError("frozen row budget mismatch")
        for source, digest in manifest["source_code_hashes"].items():
            if sha_file(BANK_CODE / source) != digest:
                raise ValueError("canonical supervision source changed")
        for substrate in SUBSTRATES:
            H = np.load(populations[split].folder / f"H_{substrate}.npy", mmap_mode="r", allow_pickle=False)
            if H.shape != (manifest["rows"], config["input_dim"]):
                raise ValueError("registered H shape mismatch")
            for start in range(0, len(H), 256):
                if not np.isfinite(H[start:start+256]).all():
                    raise ValueError("nonfinite frozen representation")
            if split == "DEV" and extension["representation_ids"][substrate] != populations["TRAIN"].extension["representation_ids"][substrate]:
                raise ValueError("representation contract differs across partitions")
        data[split] = {"path": str(folder / "manifest.json"), "sha256": sha_file(folder / "manifest.json")}
        arrays = populations[split].arrays
        summaries[split] = {
            "rows": manifest["rows"], "canonical_world_groups": manifest["canonical_world_groups"],
            "candidates": manifest["candidates"],
            "renderers": dict(sorted(Counter(r["renderer"] for r in populations[split].rows).items())),
            "global_positive_or_count_sums": arrays["global_y"].sum(0).tolist(),
            "candidate_positive_sums": arrays["candidate_y"].sum(0).tolist(),
            "supervision_masks": manifest["supervision_masks"],
            "renderer_pairs": extension["renderer_pairs"],
            "action_eligible_rows": extension["action_eligible_rows"],
            "contrast_support_pairs": extension["contrast_support_pairs"],
            "encoder_local": extension["encoder_local"],
        }
    assert_disjoint(populations["TRAIN"], populations["DEV"])
    package_paths = [p for p in EXPERIMENT.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json")]
    lock = {
        "schema": "frozen-fabrique.semantic-graft-phase0-lock/v2",
        "parent_lock_sha256": PARENT_LOCK_SHA256,
        "status": "PHASE0_READY_TO_BEGIN_TRAINING", "package": str(EXPERIMENT),
        "package_files": {str(p.relative_to(EXPERIMENT)): sha_file(p) for p in sorted(package_paths)},
        "config_sha256": canon_hash(config), "supervision_abi_sha256": canon_hash(abi),
        "data": data, "population_summary": summaries,
        "verification": {"path": str(check_path), "sha256": sha_file(check_path)},
        "unit_tests": checks["unit_tests"], "graft_parameters": checks["smoke"]["graft_parameters"],
        "graft_parameters_by_fabric": {s: record["graft_parameters"] for s, record in checks["fabric_smokes"].items()},
        "representation_ids": populations["TRAIN"].extension["representation_ids"],
        "loss_semantics": config["loss"], "hidden_coordinate_alignment": False,
        "exit_gate": {"SUBSTRATE_IDENTITY_FROZEN": True, "SURFACE_IDENTITY_FROZEN": True,
                      "STATE_ABI_FROZEN": True, "TARGET_PROVENANCE_COMPLETE": True,
                      "PAIR_CONSTRUCTION_REPLAYABLE": all(p.extension["renderer_replay_verified"] for p in populations.values()),
                      "TRAINING_OBJECTIVE_IMPLEMENTED": True, "UNTRAINED_FORWARD_TESTS_PASS": checks["status"] == "PHASE0_CHECKS_PASS",
                      "NO_PROTECTED_TRUTH_CONTACT": not any(p.extension["protected_truth_contact"] for p in populations.values()),
                      "PHASE1_CONFIG_READY": True},
        "output_root": str(NVME), "new_outputs_on_NVMe_C": True,
        "BANK_training_steps": 0, "backbone_training_steps": 0,
        "synthetic_fixture_smoke_steps": checks["smoke"]["synthetic_optimizer_steps"],
        "TEST_truth_opened": False, "VCS_reopened": False, "System1_5_changed": False,
        "scope": "Executable partially supervised semantic/candidate-epistemic interface; no learned capability or policy qualification claim",
    }
    write_json(path, lock)
    print(json.dumps({"status": lock["status"], "lock": str(path), "sha256": sha_file(path),
                      "population_summary": summaries, "graft_parameters": lock["graft_parameters"]}, indent=2))


if __name__ == "__main__":
    main()
