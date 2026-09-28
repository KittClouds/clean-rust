from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from s07_common import (
    ANALYSIS_CONTRACT, FAS00_FEATURES, FAS00_HIDDEN, FAS00_ROWS, FAS00_ROOT,
    FAS00_PHASE2, FAS00_PHASE3, PARENT_BINDING, PROJECT, RUN, S01_CACHE,
    S01_HIDDEN, S01_META, S01_ROOT, S01_2_ROOT, S01_3_ROOT, S01_ROWS,
    S02_CACHE, S02_FEATURES, S02_HIDDEN, S02_ROWS, S02_RESULT, S04_ROOT,
    S05_ROOT, S06_ROOT, FailClosed, read_json, root_simple, sha256_file,
    verify_direct_inputs, verify_parent_manifest, verify_protocol, write_json,
)


def _parents(binding: dict) -> dict[str, str]:
    expected = binding["parents"]
    specifications = [
        ("s01_phase2_result_root", S01_2_ROOT / "seals" / "result-tree-seal-v01.json", S01_2_ROOT, "tab_bytes"),
        ("s01_feature_cache_root", S01_2_ROOT / "seals" / "feature-cache-seal-v01.json", S01_2_ROOT, "tab_bytes"),
        ("s01_phase3_result_root", S01_3_ROOT / "seals" / "result-tree-seal-v01.json", S01_3_ROOT, "tab_bytes"),
        ("s04_result_root", S04_ROOT / "result-tree-seal-v01.json", S04_ROOT, "simple"),
        ("s05_result_root", S05_ROOT / "result-tree-seal-v01.json", S05_ROOT, "simple"),
        ("s06_result_root", S06_ROOT / "result-tree-seal-v01.json", S06_ROOT, "simple"),
        ("fas00_phase2a_cache_root", FAS00_PHASE2 / "phase2a-v01-cache-seal.json", FAS00_PHASE2, "simple"),
        ("fas00_phase3_result_root", FAS00_PHASE3 / "phase3-result-seal-v01.json", FAS00_PHASE3, "simple"),
        ("s02_final_cache_root", S02_CACHE / "feature-cache-seal-v01.json", S02_CACHE, "simple"),
        ("s02_result_root", S02_RESULT / "seals" / "result-tree-seal-v01.json", S02_RESULT, "simple"),
    ]
    observed = {}
    for key, path, _base, style in specifications:
        root = expected[key]
        seal = verify_parent_manifest(path, root, style=style)
        observed[key] = {"root_sha256": seal["root_sha256"], "seal_path": str(path)}
    # Parent dispositions are intentionally non-promoting.
    for path in (S04_ROOT / "result-tree-seal-v01.json", S05_ROOT / "result-tree-seal-v01.json", S06_ROOT / "result-tree-seal-v01.json"):
        seal = read_json(path)
        for flag in ("FAS00_SENSOR_PASS", "FAS00_PHASE4_AUTHORIZED", "adaptive_mechanisms", "SAE_analysis", "SAE_ANALYSIS_AUTHORIZED"):
            if seal.get(flag) is True:
                raise FailClosed(f"Unexpected promoting parent disposition {flag}: {path}")
    return observed


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    return str(value)


def _validate_s01_rows() -> dict[str, int]:
    with np.load(S01_META, allow_pickle=False) as archive:
        required = {"row_index", "event_id", "quartet_id", "split_bucket", "variant"}
        if not required.issubset(archive.files):
            raise FailClosed("S01 event metadata is missing split identity fields")
        row_index = archive["row_index"]
        event_ids = archive["event_id"]
        quartet_ids = archive["quartet_id"]
        buckets = archive["split_bucket"]
        variants = archive["variant"]
    n = len(row_index)
    if n != S01_ROWS or not np.array_equal(row_index, np.arange(n, dtype=row_index.dtype)):
        raise FailClosed("S01 metadata row identity/count mismatch")
    if any(len(array) != n for array in (event_ids, quartet_ids, buckets, variants)):
        raise FailClosed("S01 metadata columns have inconsistent lengths")
    if set(map(int, np.unique(buckets))) != {0, 1, 2, 3, 4}:
        raise FailClosed("S01 split bucket inventory differs from frozen contract")

    group_rows: dict[str, list[int]] = defaultdict(list)
    group_buckets: dict[str, set[int]] = defaultdict(set)
    group_variants: dict[str, set[int]] = defaultdict(set)
    for i in range(n):
        qid = _decode(quartet_ids[i])
        bucket = int(buckets[i])
        group_rows[qid].append(i)
        group_buckets[qid].add(bucket)
        group_variants[qid].add(int(variants[i]))
    if len(group_rows) != 26_624:
        raise FailClosed(f"Unexpected S01 quartet count: {len(group_rows)}")
    for qid, rows in group_rows.items():
        if len(rows) != 4 or len(group_buckets[qid]) != 1 or group_variants[qid] != {0, 1, 2, 3}:
            raise FailClosed(f"S01 quartet split/variant integrity failure: {qid}")
        expected = int.from_bytes(hashlib.sha256(f"FASS01-S01-3-GROUPSPLIT-V01|{qid}".encode()).digest()[:4], "big") % 5
        if next(iter(group_buckets[qid])) != expected:
            raise FailClosed(f"S01 stored split bucket fails independent reconstruction: {qid}")
    counts = Counter(map(int, buckets))
    if counts != Counter({0: 21_272, 1: counts[1], 2: counts[2], 3: counts[3], 4: counts[4]}):
        raise FailClosed("S01 bucket-0 test support differs from sealed split")
    if sum(counts[b] for b in (1, 2, 3, 4)) != 85_224:
        raise FailClosed("S01 training-side row support differs from contract")

    # Independently bind the full-row feature identity manifest to metadata order.
    manifest = S01_CACHE / "feature-rows-v01.jsonl"
    with manifest.open("r", encoding="utf-8") as stream:
        for i, line in enumerate(stream):
            if i >= n:
                raise FailClosed("S01 feature-row manifest contains excess rows")
            row = json.loads(line)
            if int(row.get("row_index", -1)) != i or row.get("event_id") != _decode(event_ids[i]):
                raise FailClosed(f"S01 feature row identity mismatch at row {i}")
        if i + 1 != n:
            raise FailClosed("S01 feature-row manifest row count mismatch")
    train = np.flatnonzero(np.isin(buckets, np.asarray([1, 2, 3, 4], dtype=buckets.dtype))).astype(np.uint32)
    np.save(RUN / "train-row-indices-v01.npy", train, allow_pickle=False)
    return {f"bucket_{key}": int(value) for key, value in sorted(counts.items())} | {"train_rows": int(len(train)), "test_rows": int(counts[0]), "quartets": int(len(group_rows))}


def main() -> None:
    protocol = verify_protocol()
    binding = read_json(PARENT_BINDING)
    analysis = read_json(ANALYSIS_CONTRACT)
    if analysis.get("status") != "FROZEN_PRE_FIT" or analysis["faithfulness_gate"]["balanced_accuracy_max_degradation"] != 0.03:
        raise FailClosed("S07 analysis contract is not the frozen prospective version")
    parent_roots = _parents(binding)
    direct_inputs = verify_direct_inputs(binding)
    bucket_counts = _validate_s01_rows()
    # Exact cache dimensions and byte contracts; arrays are memory-mapped later.
    expected_bytes = {
        "s01_mean_features": S01_ROWS * S01_HIDDEN * 4,
        "s01_final_features": S01_ROWS * S01_HIDDEN * 4,
        "fas00_mean_features": FAS00_ROWS * FAS00_HIDDEN * 4,
        "s02_final_features": S02_ROWS * S02_HIDDEN * 4,
    }
    for key, expected in expected_bytes.items():
        if direct_inputs[key]["bytes"] != expected:
            raise FailClosed(f"Feature-cache shape/byte mismatch: {key}")
    row_indices = np.load(RUN / "train-row-indices-v01.npy", allow_pickle=False)
    if len(row_indices) != 85_224 or row_indices.dtype != np.uint32 or int(row_indices[-1]) >= S01_ROWS:
        raise FailClosed("Materialized S07 training row index set failed validation")
    receipt = {
        "receipt_id": "FAS_S07_PREFLIGHT_RECEIPT_V01",
        "status": "PASS",
        "protocol_root_sha256": protocol["root_sha256"],
        "parent_roots": {key: value["root_sha256"] for key, value in parent_roots.items()},
        "direct_input_identities": direct_inputs,
        "s01_split_reconstruction": bucket_counts,
        "train_rows": len(row_indices),
        "train_vector_rows_per_surface": len(row_indices),
        "train_pooled_vector_count": 2 * len(row_indices),
        "heldout_s01_rows_opened": False,
        "fas00_features_opened": False,
        "labels_opened": False,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "parent_artifacts_modified": False,
    }
    receipt_path = RUN / "preflight-receipt-v01.json"
    write_json(receipt_path, receipt)
    indices_path = RUN / "train-row-indices-v01.npy"
    entries = [
        {"path": "preflight-receipt-v01.json", "bytes": receipt_path.stat().st_size, "sha256": sha256_file(receipt_path)},
        {"path": "train-row-indices-v01.npy", "bytes": indices_path.stat().st_size, "sha256": sha256_file(indices_path)},
    ]
    seal = {"seal_id": "FAS_S07_PREFLIGHT_SEAL_V01", "status": "SEALED", "entries": entries, "root_sha256": root_simple(entries)}
    write_json(RUN / "preflight-seal-v01.json", seal)
    print(f"S07_PREFLIGHT_PASS train_rows={len(row_indices)} heldout_rows=21272 pooled={2*len(row_indices)}")


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_PREFLIGHT_FAIL_CLOSED {exc}")
        raise SystemExit(2)
