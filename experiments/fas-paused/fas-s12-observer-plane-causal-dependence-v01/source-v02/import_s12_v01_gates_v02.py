from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from s12_math import canonical_json, entry, sha256_file, tree_root


OLD = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
RUN = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_local_tree(base: Path, seal_path: Path) -> dict[str, Any]:
    seal = read_json(seal_path)
    actual = [entry(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    if actual != sorted(seal["entries"], key=lambda item: item["path"]) or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError(f"S12 v01 source gate seal mismatch: {seal_path}")
    return seal


def copy_verified(source: Path, destination: Path, expected_sha256: str) -> dict[str, Any]:
    digest, size = sha256_file(source)
    if digest != expected_sha256:
        raise RuntimeError(f"S12 v01 source gate hash mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        found, found_size = sha256_file(destination)
        if (found, found_size) != (digest, size):
            raise RuntimeError(f"S12 v02 reuse destination already has different bytes: {destination}")
    else:
        shutil.copyfile(source, destination)
    copied, copied_size = sha256_file(destination)
    if (copied, copied_size) != (digest, size):
        raise RuntimeError(f"S12 v02 copied gate bytes do not match: {destination}")
    return {"source": str(source), "path": destination.name, "bytes": size, "sha256": digest}


def seal_dir(base: Path, seal_name: str, seal_id: str) -> dict[str, Any]:
    entries = [entry(path, base) for path in base.iterdir() if path.is_file() and path.name != seal_name]
    entries.sort(key=lambda item: item["path"])
    seal = {"seal_id": seal_id, "entries": entries, "root_sha256": tree_root(entries)}
    (base / seal_name).write_bytes(canonical_json(seal) + b"\n")
    verify_local_tree(base, base / seal_name)
    return seal


def main() -> int:
    old_base = OLD / "base-parity-v01"
    old_base_seal = verify_local_tree(old_base, old_base / "base-parity-seal-v01.json")
    old_base_receipt_path = old_base / "base-parity-receipt-v01.json"
    old_base_receipt = read_json(old_base_receipt_path)
    if old_base_receipt.get("complete") is not True or old_base_receipt.get("rows") != 21_272 or old_base_receipt.get("byte_identical") is not True:
        raise RuntimeError("S12 v01 all-row base/suffix parity gate is incomplete")
    if old_base_receipt.get("suffix_layer_parity_cells") != 21_272 * 3:
        raise RuntimeError("S12 v01 base/suffix parity did not cover all rows and sites")
    base_dst = RUN / "base-parity-v02"
    if (base_dst / "base-parity-seal-v02.json").exists():
        base_new_seal = verify_local_tree(base_dst, base_dst / "base-parity-seal-v02.json")
    else:
        base_row_source = old_base / "base-parity-rows-v01.jsonl"
        base_row_hash = sha256_file(base_row_source)[0]
        copied_base_rows = copy_verified(base_row_source, base_dst / "base-parity-rows-v02.jsonl", base_row_hash)
        receipt = {
            "receipt_id": "FAS_S12_BASE_AND_SUFFIX_PARITY_V02_REUSED_SEALED_V01",
            "complete": True,
            "rows": 21_272,
            "terminal_matrix_parity_rows": 21_272,
            "suffix_layer_parity_cells": 21_272 * 3,
            "byte_identical": True,
            "row_manifest": {"path": copied_base_rows["path"], "sha256": copied_base_rows["sha256"], "bytes": copied_base_rows["bytes"]},
            "reused_from": {"source_run": str(OLD), "source_root_sha256": old_base_seal["root_sha256"], "source_receipt_sha256": sha256_file(old_base_receipt_path)[0]},
            "reuse_rule": "base inputs/model/suffix implementation were identical; v01 passed every row before the separate branch-check failure; v02 did not repeat or alter feature extraction",
        }
        (base_dst / "base-parity-receipt-v02.json").write_bytes(canonical_json(receipt) + b"\n")
        base_new_seal = seal_dir(base_dst, "base-parity-seal-v02.json", "FAS_S12_BASE_PARITY_SEAL_V02_REUSED_V01")

    old_baseline = OLD / "baseline-v01"
    old_baseline_seal = verify_local_tree(old_baseline, old_baseline / "baseline-seal-v01.json")
    old_baseline_receipt_path = old_baseline / "baseline-replay-receipt-v01.json"
    old_baseline_receipt = read_json(old_baseline_receipt_path)
    if old_baseline_receipt.get("complete") is not True or old_baseline_receipt.get("rows") != 21_272:
        raise RuntimeError("S12 v01 baseline replay gate is incomplete")
    baseline_dst = RUN / "baseline-v02"
    if (baseline_dst / "baseline-seal-v02.json").exists():
        baseline_new_seal = verify_local_tree(baseline_dst, baseline_dst / "baseline-seal-v02.json")
    else:
        copied = []
        names = (
            ("baseline-probe-logits-v01.f32le", "baseline-probe-logits-v02.f32le"),
            ("baseline-probe-probabilities-v01.f32le", "baseline-probe-probabilities-v02.f32le"),
            ("baseline-predictions-v01.i64le", "baseline-predictions-v02.i64le"),
        )
        for source_name, dest_name in names:
            source = old_baseline / source_name
            old_entry = next(item for item in old_baseline_seal["entries"] if item["path"] == source_name)
            copied.append(copy_verified(source, baseline_dst / dest_name, old_entry["sha256"]))
        outputs = []
        for item, (_, dest_name) in zip(copied, names, strict=True):
            old_output = next(record for record in old_baseline_receipt["outputs"] if record["path"] == names[len(outputs)][0])
            outputs.append({"path": dest_name, "shape": old_output["shape"], "dtype": old_output["dtype"], "sha256": item["sha256"], "bytes": item["bytes"]})
        receipt = {
            "receipt_id": "FAS_S12_BASELINE_PROBE_REPLAY_V02_REUSED_SEALED_V01",
            "complete": True,
            "rows": 21_272,
            "class_order": [0, 1, 2],
            "parents": old_baseline_receipt["parents"],
            "probabilities_derived_from": old_baseline_receipt["probabilities_derived_from"],
            "outputs": outputs,
            "reused_from": {"source_run": str(OLD), "source_root_sha256": old_baseline_seal["root_sha256"], "source_receipt_sha256": sha256_file(old_baseline_receipt_path)[0]},
            "reuse_rule": "copied byte-identical sealed baseline probe replay; no new model forward or label access",
        }
        (baseline_dst / "baseline-replay-receipt-v02.json").write_bytes(canonical_json(receipt) + b"\n")
        baseline_new_seal = seal_dir(baseline_dst, "baseline-seal-v02.json", "FAS_S12_BASELINE_SEAL_V02_REUSED_V01")
    report = {
        "receipt_id": "FAS_S12_V01_GATE_REUSE_RECEIPT_V02",
        "complete": True,
        "source_attempt_preserved": str(OLD),
        "base_parity": {"source_root_sha256": old_base_seal["root_sha256"], "reused_root_sha256": base_new_seal["root_sha256"]},
        "baseline_replay": {"source_root_sha256": old_baseline_seal["root_sha256"], "reused_root_sha256": baseline_new_seal["root_sha256"]},
        "data_arrays_byte_identical": True,
        "intervention_outputs_reused": False,
    }
    receipt_path = RUN / "reused-v01-gates-receipt-v02.json"
    receipt_path.write_bytes(canonical_json(report) + b"\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
