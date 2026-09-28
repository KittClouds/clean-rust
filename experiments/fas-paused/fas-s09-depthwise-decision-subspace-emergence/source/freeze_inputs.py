from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from s09_common import (
    PROJECT_ROOT,
    RUN_ROOT,
    S01_2_ROOT,
    S01_3_ROOT,
    S08_ROOT,
    entry_for,
    read_json,
    sha256_file,
    token_ids_sha256,
    tree_root,
    verify_tree,
    write_json,
)


PARENT_SPECS = {
    "S01_2_CONSTRUCTION": (Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed"), "seals/result-tree-seal-v01.json", "f6065b8163799239e0d7b1200b5dda4aad169772ead14b999130a473ff9d9049"),
    "S01_2_EXTRACTION_RESULT": (S01_2_ROOT, "seals/result-tree-seal-v01.json", "1fc3aeb432ecdbef21a35aea8fed5b0d59671681eb8eb8032533c9ce751a4384"),
    "S01_2_FEATURE_CACHE": (S01_2_ROOT, "seals/feature-cache-seal-v01.json", "4964f35fb87a45a9447cd0f5f028668027ca3ad3a8f0d0c3f9eb7b9cbe7ccaaa"),
    "S01_3_LINEAR_ACCESSIBILITY": (S01_3_ROOT, "seals/result-tree-seal-v01.json", "2581b50d75382c197793ea46400bf2b8a27508df22b2ff5bdbe82eb20a5238b7"),
    "S08_S01_ANALYSIS": (S08_ROOT / "s01-analysis", "s01-analysis-seal-v02.json", "96be631597a6eddac8624d6dd744927577eb90921f7d07dda509ab4260bbd1fc"),
}


def copy_verified(src: Path, dest: Path, expected_hash: str | None = None) -> dict[str, Any]:
    digest, size = sha256_file(src)
    if expected_hash is not None and digest != expected_hash:
        raise RuntimeError(f"input file hash mismatch: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    copied_hash, copied_size = sha256_file(dest)
    if copied_hash != digest or copied_size != size:
        raise RuntimeError(f"copied input differs from verified source: {src}")
    return {"source": str(src), "path": dest.relative_to(RUN_ROOT).as_posix(), "bytes": size, "sha256": digest}


def project_snapshot() -> list[dict[str, Any]]:
    snapshot = RUN_ROOT / "inputs" / "project-snapshot"
    if snapshot.exists():
        raise RuntimeError("project snapshot already exists; refusing overwrite")
    shutil.copytree(PROJECT_ROOT, snapshot, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    entries = [entry_for(path, RUN_ROOT) for path in snapshot.rglob("*") if path.is_file()]
    return sorted(entries, key=lambda item: item["path"])


def make_token_only_manifest(source: Path, destination: Path, expected_hash: str) -> dict[str, Any]:
    digest, size = sha256_file(source)
    if digest != expected_hash:
        raise RuntimeError("sealed S01 feature-row manifest changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    event_seen: set[str] = set()
    output_hash = hashlib.sha256()
    count = 0
    with source.open("r", encoding="utf-8") as src, destination.open("xb", buffering=8 * 1024 * 1024) as dst:
        for line in src:
            row = json.loads(line)
            tokens = row["token_ids"]
            if not tokens or len(tokens) != int(row["sequence_length"]) or len(tokens) > 2048:
                raise RuntimeError(f"sealed token row length invalid at index {count}")
            if token_ids_sha256(tokens) != row["token_ids_sha256"]:
                raise RuntimeError(f"sealed token identity invalid at index {count}")
            event_id = row["event_id"]
            if event_id in event_seen or int(row["row_index"]) != count:
                raise RuntimeError(f"sealed token row identity/order invalid at index {count}")
            event_seen.add(event_id)
            record = {
                "row_index": count,
                "event_id": event_id,
                "input_sha256": row["input_sha256"],
                "token_ids": tokens,
                "token_ids_sha256": row["token_ids_sha256"],
                "sequence_length": int(row["sequence_length"]),
            }
            serialized = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
            dst.write(serialized)
            output_hash.update(serialized)
            count += 1
    if count != 106496:
        raise RuntimeError(f"sealed token manifest row count differs: {count}")
    return {
        "source_sha256": digest,
        "source_bytes": size,
        "rows": count,
        "unique_event_ids": len(event_seen),
        "token_only_manifest_sha256": output_hash.hexdigest(),
        "token_only_manifest_bytes": destination.stat().st_size,
        "token_hash_rule": "SHA-256 over little-endian uint32 token IDs",
        "model_input_fields": ["token_ids", "sequence_length"],
        "excluded_fields": ["input_text", "labels", "latent world state", "templates", "split metadata"],
    }


def main() -> int:
    if not RUN_ROOT.is_dir():
        raise RuntimeError("run root is missing; protocol seal must be completed first")
    (RUN_ROOT / "inputs").mkdir(parents=True, exist_ok=True)
    contract = read_json(PROJECT_ROOT / "contracts" / "s09-contract-v01.json")
    binding = read_json(PROJECT_ROOT / "contracts" / "parent-binding-v01.json")
    protocol_seal_path = PROJECT_ROOT / "seals" / "protocol-seal-v01.json"
    protocol_seal = read_json(protocol_seal_path)
    protocol_actual = [entry_for(PROJECT_ROOT.joinpath(*item["path"].split("/")), PROJECT_ROOT) for item in protocol_seal["entries"]]
    protocol_actual.sort(key=lambda item: item["path"])
    if protocol_actual != protocol_seal["entries"] or tree_root(protocol_actual) != protocol_seal["root_sha256"]:
        raise RuntimeError("frozen S09 project protocol failed its seal")
    if (RUN_ROOT / "seals" / "preflight-seal-v01.json").exists():
        raise RuntimeError("preflight seal already exists; refusing overwrite")
    if shutil.disk_usage(RUN_ROOT).free < int(contract["runtime"]["minimum_free_disk_bytes"]):
        raise RuntimeError("D: free space is below the sealed pre-extraction floor")

    verified: dict[str, Any] = {}
    for name, (base, relative_seal, expected_root) in PARENT_SPECS.items():
        verified[name] = verify_tree(base, base / relative_seal, expected_root)
    rows_source = S01_2_ROOT / "feature-cache-v01" / "feature-rows-v01.jsonl"
    rows_dest = RUN_ROOT / "inputs" / "token-only-feature-rows-v01.jsonl"
    token_manifest = make_token_only_manifest(rows_source, rows_dest, binding["specific_inputs"]["S01_2_feature_rows_sha256"])

    copied: list[dict[str, Any]] = []
    copy_specs = [
        (S01_3_ROOT / "metadata" / "event-metadata-v01.npz", "inputs/S01-3/event-metadata-v01.npz", binding["specific_inputs"]["S01_3_metadata_sha256"]),
        (S01_3_ROOT / "metadata" / "test-events-v01.jsonl", "inputs/S01-3/test-events-v01.jsonl", None),
        (S01_3_ROOT / "metrics-v01.json", "inputs/S01-3/metrics-v01.json", None),
        (S01_3_ROOT / "run-execution-receipt-v01.json", "inputs/S01-3/run-execution-receipt-v01.json", None),
        (S01_3_ROOT / "contracts" / "linear-accessibility-contract-v01.json", "inputs/S01-3/linear-accessibility-contract-v01.json", None),
        (S01_2_ROOT / "feature-extraction-receipt-v01.json", "inputs/S01-2/feature-extraction-receipt-v01.json", None),
        (S01_2_ROOT / "model-asset-manifest-v01.json", "inputs/S01-2/model-asset-manifest-v01.json", None),
        (S01_2_ROOT / "seals" / "feature-cache-seal-v01.json", "inputs/S01-2/feature-cache-seal-v01.json", None),
        (S01_2_ROOT / "seals" / "result-tree-seal-v01.json", "inputs/S01-2/result-tree-seal-v01.json", None),
        (S01_3_ROOT / "seals" / "result-tree-seal-v01.json", "inputs/S01-3/result-tree-seal-v01.json", None),
        (S08_ROOT / "s01-analysis" / "s01-native-decision-geometry-v02.npz", "inputs/S08/s01-native-decision-geometry-v02.npz", binding["specific_inputs"]["S08_native_geometry_sha256"]),
        (S08_ROOT / "s01-analysis" / "s01-native-subspaces-v02.json", "inputs/S08/s01-native-subspaces-v02.json", None),
        (S08_ROOT / "s01-analysis" / "s01-analysis-seal-v02.json", "inputs/S08/s01-analysis-seal-v02.json", None),
        (S01_3_ROOT / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz", "inputs/S01-3/terminal-reference/M-probe-state.npz", None),
        (S01_3_ROOT / "predictions" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probabilities.npy", "inputs/S01-3/terminal-reference/M-probabilities.npy", None),
        (S01_3_ROOT / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-metadata-v01.json", "inputs/S01-3/terminal-reference/M-probe-metadata.json", None),
        (S01_3_ROOT / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz", "inputs/S01-3/terminal-reference/F-probe-state.npz", None),
        (S01_3_ROOT / "predictions" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probabilities.npy", "inputs/S01-3/terminal-reference/F-probabilities.npy", None),
        (S01_3_ROOT / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-metadata-v01.json", "inputs/S01-3/terminal-reference/F-probe-metadata.json", None),
    ]
    for source, relative, expected in copy_specs:
        copied.append(copy_verified(source, RUN_ROOT / relative, expected))

    source_specs = [
        (PROJECT_ROOT / "source" / "linear_core.py", "inputs/reference-source/linear_core.py"),
        (PROJECT_ROOT / "source" / "s01_common_reference.py", "inputs/reference-source/s01_common_reference.py"),
    ]
    for source, relative in source_specs:
        copied.append(copy_verified(source, RUN_ROOT / relative))
    project_entries = project_snapshot()
    receipt = {
        "receipt_id": "FAS_S09_PARENT_VERIFICATION_RECEIPT_V01",
        "verified_parent_roots": {name: item["root_sha256"] for name, item in verified.items()},
        "parent_entry_counts": {name: item["entry_count"] for name, item in verified.items()},
        "copied_input_files": copied,
        "token_manifest": token_manifest,
        "project_snapshot_entries": project_entries,
        "project_protocol_root_sha256": protocol_seal["root_sha256"],
        "model_loaded": False,
        "features_extracted": False,
        "probes_fitted": False,
        "fas00_artifacts_read": False,
        "fas00_access": False,
    }
    receipt_path = RUN_ROOT / "parent-verification-receipt-v01.json"
    write_json(receipt_path, receipt)
    entries = [entry_for(path, RUN_ROOT) for path in (RUN_ROOT / "inputs").rglob("*") if path.is_file()]
    entries.append(entry_for(receipt_path, RUN_ROOT))
    entries.sort(key=lambda item: item["path"])
    preflight = {
        "seal_id": "FAS_S09_PREFLIGHT_SEAL_V01",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "parents_verified": True,
        "model_loaded": False,
        "features_extracted": False,
        "probes_fitted": False,
        "fas00_artifacts_read": False,
    }
    seal_path = RUN_ROOT / "seals" / "preflight-seal-v01.json"
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(seal_path, preflight)
    print(f"preflight_root_sha256={preflight['root_sha256']} parent_roots={len(verified)} token_rows={token_manifest['rows']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
