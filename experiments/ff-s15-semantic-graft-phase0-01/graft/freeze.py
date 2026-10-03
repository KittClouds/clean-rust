"""Bind the executable Phase0 package, canonical sources, data and checks."""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

from .contracts import (BANK_CODE, EXPERIMENT, NVME, SUBSTRATES, canon_hash,
                        default_config, sha_file, supervision_abi, write_json)
from .dataset import PackedBank, assert_disjoint


def main():
    path = NVME / "PHASE0-LOCK.json"
    if path.exists():
        raise FileExistsError("Phase0 lock is already sealed; do not overwrite")
    config = default_config()
    abi = supervision_abi()
    check_path = NVME / "checks" / "verification.json"
    checks = json.loads(check_path.read_text())
    if checks["status"] != "PHASE0_CHECKS_PASS" or checks["config_sha256"] != canon_hash(config):
        raise ValueError("verification contract mismatch")
    for relative, digest in checks["source_files"].items():
        if sha_file(EXPERIMENT / relative) != digest:
            raise ValueError(f"source changed since checks: {relative}")
    write_json(EXPERIMENT / "config.json", config)
    write_json(EXPERIMENT / "supervision-abi.json", abi)
    populations = {}
    data = {}
    summaries = {}
    for split in ("TRAIN", "DEV"):
        folder = NVME / "data" / split
        populations[split] = PackedBank(folder, SUBSTRATES[0], config)
        manifest = populations[split].manifest
        if manifest["rows"] != config["train_rows" if split == "TRAIN" else "dev_rows"]:
            raise ValueError("frozen row budget mismatch")
        for source, digest in manifest["source_code_hashes"].items():
            if sha_file(BANK_CODE / source) != digest:
                raise ValueError("canonical supervision source changed")
        for substrate in SUBSTRATES:
            H = np.load(folder / f"H_{substrate}.npy", mmap_mode="r", allow_pickle=False)
            if H.shape != (manifest["rows"], config["input_dim"]):
                raise ValueError("registered H shape mismatch")
            for start in range(0, len(H), 256):
                if not np.isfinite(H[start:start+256]).all():
                    raise ValueError("nonfinite frozen representation")
            if split == "DEV" and manifest["representations"][substrate]["representation_id"] != populations["TRAIN"].manifest["representations"][substrate]["representation_id"]:
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
        }
    assert_disjoint(populations["TRAIN"], populations["DEV"])
    package_paths = [p for p in EXPERIMENT.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json")]
    lock = {
        "schema": "frozen-fabrique.semantic-graft-phase0-lock/v1",
        "status": "PHASE0_READY_TO_BEGIN_TRAINING", "package": str(EXPERIMENT),
        "package_files": {str(p.relative_to(EXPERIMENT)): sha_file(p) for p in sorted(package_paths)},
        "config_sha256": canon_hash(config), "supervision_abi_sha256": canon_hash(abi),
        "data": data, "population_summary": summaries,
        "verification": {"path": str(check_path), "sha256": sha_file(check_path)},
        "unit_tests": checks["unit_tests"], "graft_parameters": checks["smoke"]["graft_parameters"],
        "representation_ids": {s: populations["TRAIN"].manifest["representations"][s]["representation_id"] for s in SUBSTRATES},
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
