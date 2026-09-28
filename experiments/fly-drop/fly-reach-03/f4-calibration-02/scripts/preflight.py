from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent
STUDY = HERE.parents[1]
REPO = STUDY.parents[1]
RUNS = STUDY / "runs"
LINEAGE_ROOT = REPO / "experiments" / "fly-reach-02-v0.1b"
CONTRACT_SHA = "2c3f46214cbe9ec1271a2b9a72a2fac130d648f05f23f1e43685c1436c153a90"
sys.path.insert(0, str(STUDY / "f4-symmetry-03" / "scripts"))
from common import canonical_json, read_json, require, runtime_description, sha_bytes, sha_file, write_json  # noqa: E402


def _repo_path(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def _source_paths(run: Path) -> list[Path]:
    paths = [
        BRANCH / "F4-CALIBRATION-02-CONTRACT-v0.1.md",
        BRANCH / "F4-CALIBRATION-02-CONTRACT-v0.1.json",
        BRANCH / "F4-CALIBRATION-02-PRETASK-FREEZE-RECEIPT.json",
        BRANCH / "F4-CALIBRATION-02-PRETASK-FREEZE-RECEIPT.sha256",
        BRANCH / "scripts/prepare_tasks.py", BRANCH / "scripts/preflight.py",
        BRANCH / "scripts/prepare_d.py", BRANCH / "scripts/fit_d.py",
        BRANCH / "scripts/integrity.py", BRANCH / "scripts/analysis.py",
        BRANCH / "scripts/terminal.py",
        BRANCH / "executor/Cargo.toml", BRANCH / "executor/Cargo.lock",
        BRANCH / "executor/src/main.rs", BRANCH / "executor/src/native_collect.rs",
        STUDY / "f4-symmetry-03/F4-SYMMETRY-03-CONTRACT-v0.1.md",
        STUDY / "runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/TERMINAL-RECEIPT.json",
        STUDY / "f4-symmetry-03/scripts/common.py",
        STUDY / "f4-symmetry-03/scripts/prepare_fit.py",
        STUDY / "f4-symmetry-03/scripts/fit.py",
        STUDY / "scripts/f4_symmetry_01_model.py",
        STUDY / "runs/qualification-v2/QUALIFICATION-TERMINAL-RECEIPT.json",
        STUDY / "manifests/QUALIFICATION-MANIFEST.json",
        STUDY / "executor/Cargo.toml", STUDY / "executor/Cargo.lock",
        STUDY / "executor/src/graph.rs", STUDY / "executor/src/collector.rs",
        STUDY / "executor/src/reach_sim.rs", STUDY / "executor/src/rng.rs",
        STUDY / "executor/src/task.rs",
        run / "task-bank/TASK-BANK-MANIFEST.json",
        run / "task-bank/TASK-BANK-RECEIPT.json", run / "task-bank/training.json",
        run / "bin/f4-calibration-02-executor.exe",
    ]
    paths.extend([LINEAGE_ROOT / "inputs/anatomy" / f"nodes-{side}.tsv" for side in ("L", "R")])
    for side in ("L", "R"):
        paths.append(LINEAGE_ROOT / "inputs/anatomy" / f"edges-{side}.tsv")
        for graph in range(1, 9):
            paths.append(LINEAGE_ROOT / "inputs/null-graphs" / f"g{graph:03d}" / f"edges-{side}.tsv")
    return paths


def preflight(run: Path, binary: Path) -> None:
    contract_path = BRANCH / "F4-CALIBRATION-02-CONTRACT-v0.1.md"
    machine_path = BRANCH / "F4-CALIBRATION-02-CONTRACT-v0.1.json"
    require(sha_file(contract_path) == CONTRACT_SHA, "F4-CALIBRATION-02 contract hash mismatch")
    machine = read_json(machine_path)
    require(machine["contract_markdown_sha256"] == CONTRACT_SHA, "machine contract mismatch")
    freeze = read_json(BRANCH / "F4-CALIBRATION-02-PRETASK-FREEZE-RECEIPT.json")
    require(freeze["status"] == "CONTRACT_FROZEN_PRETASK", "pre-task contract freeze receipt invalid")
    require(freeze["contract_markdown_sha256"] == CONTRACT_SHA and
            freeze["contract_json_sha256"] == sha_file(machine_path), "pre-task freeze receipt contract hashes differ")
    prior = machine["parent_evidence"]
    require(sha_file(STUDY / "runs/qualification-v2/QUALIFICATION-TERMINAL-RECEIPT.json") ==
            prior["qualification_v2_terminal_receipt_sha256"], "parent qualification receipt hash mismatch")
    require(sha_file(STUDY / "runs/F4-SYMMETRY-03-QREP1-IMPLFIX1/TERMINAL-RECEIPT.json") ==
            prior["symmetry03_terminal_receipt_sha256"], "SYMMETRY-03 parent receipt hash mismatch")
    for source in machine["frozen_d_sources"].values():
        path = REPO / source["path"]
        require(sha_file(path) == source["sha256"], f"frozen D source drift: {path}")
    old_gate = read_json(STUDY / "runs/qualification-v2/QUALIFICATION-TERMINAL-RECEIPT.json")
    require(old_gate["f4_encoder_calibration"]["gate"] == {
        "per_fold_omega_hat_min": 0.7,
        "pooled_balanced_error_max": 0.1,
        "pooled_omega_hat_min": 0.8,
        "fold_failure_disposition": "ESTIMATOR_CAPACITY_STOP",
    }, "historical F4 calibration thresholds changed")
    require(run.exists() and {p.name for p in run.iterdir()} == {"task-bank"}, "run directory is not a fresh task-bank-only identity")
    task_manifest = read_json(run / "task-bank/TASK-BANK-MANIFEST.json")
    task_receipt = read_json(run / "task-bank/TASK-BANK-RECEIPT.json")
    ids = [int(x) for x in machine["task_bank"]["block_ids"]]
    require(task_manifest["accepted_block_ids"] == ids and task_manifest["structural_pattern_selection"] is False,
            "task bank differs from frozen ordinary task design")
    require(task_receipt["status"] == "PASS" and task_receipt["outcome_selection"] is False,
            "task bank receipt failed")
    require(task_manifest["training_sha256"] == sha_file(run / "task-bank/training.json"), "training task-bank hash mismatch")
    require(not any(run.glob("collection-staging/*")), "collection already exists before seal")
    (run / "bin").mkdir()
    (run / "collection-staging").mkdir()
    target_binary = run / "bin/f4-calibration-02-executor.exe"
    shutil.copy2(binary, target_binary)

    entries = []
    paths = _source_paths(run)
    for path in paths:
        require(path.is_file(), f"missing sealed source/input: {path}")
        entries.append({"path": _repo_path(path), "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    entries.sort(key=lambda row: row["path"].encode("utf-8"))
    require(len({row["path"] for row in entries}) == len(entries), "duplicate source paths")
    source_obj = {"schema": "F4-CALIBRATION-02-source-input-manifest-v1", "entries": entries}
    source_file_sha = write_json(run / "SOURCE-INPUT-MANIFEST.json", source_obj)
    source_canonical_sha = sha_bytes(canonical_json(source_obj))
    runtime = runtime_description()
    script_names = ("prepare_tasks.py", "preflight.py", "prepare_d.py", "fit_d.py", "integrity.py", "analysis.py", "terminal.py")
    script_hashes = {name: sha_file(BRANCH / "scripts" / name) for name in script_names}
    execution = {
        "schema": "F4-CALIBRATION-02-execution-manifest-v1",
        "run_id": machine["run_id"], "qualification_only": True,
        "contract_sha256": CONTRACT_SHA, "machine_contract_sha256": sha_file(machine_path),
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "block_ids": ids, "fit_ids": [f"D-H{block}" for block in ids],
        "expected_fit_count": 12, "expected_native_stream_count": 216,
        "task_manifest_sha256": sha_file(run / "task-bank/TASK-BANK-MANIFEST.json"),
        "task_training_sha256": sha_file(run / "task-bank/training.json"),
        "executor_path": "bin/f4-calibration-02-executor.exe",
        "executor_sha256": sha_file(target_binary),
        "runtime": runtime, "script_hashes": script_hashes,
        "truth_firewall": "lock all heldout predictions, pass integrity, then open heldout truth",
        "per_block_gate": {"minimum_evaluable": 10, "total": 12, "omega_hat_min": 0.70},
        "pooled_gate": {"epsilon_balanced_max": 0.10, "omega_hat_min": 0.80},
        "measured_reach03_authorized": False,
    }
    execution_file_sha = write_json(run / "EXECUTION-MANIFEST.json", execution)
    execution_canonical_sha = sha_bytes(canonical_json(execution))
    seal = {
        "schema": "F4-CALIBRATION-02-preexecution-seal-v1", "status": "PASS",
        "run_id": machine["run_id"], "contract_sha256": CONTRACT_SHA,
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "execution_manifest_file_sha256": execution_file_sha,
        "execution_manifest_canonical_sha256": execution_canonical_sha,
        "expected_fit_count": 12, "expected_native_stream_count": 216,
        "block_ids": ids, "heldout_truth_opened": False,
        "qualification_only": True, "measured_reach03_authorized": False,
        "biological_promotion": False,
    }
    write_json(run / "PREEXECUTION-SEAL.json", seal)
    write_json(run / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", {
        "schema": "F4-CALIBRATION-02-implementation-preflight-v1", "status": "PASS",
        "contract_sha256": CONTRACT_SHA, "source_entry_count": len(entries),
        "source_manifest_canonical_sha256": source_canonical_sha,
        "execution_manifest_file_sha256": execution_file_sha,
        "preexecution_seal_sha256": sha_file(run / "PREEXECUTION-SEAL.json"),
        "task_bank_passed": True, "native_collection_started": False,
        "heldout_truth_opened": False, "measured_reach03_authorized": False,
    })
    print(json.dumps({"status": "PREEXECUTION_SEALED", "run": str(run), "source_entries": len(entries),
                      "fits": 12, "native_streams": 216}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    preflight(args.run.resolve(), args.binary.resolve())
