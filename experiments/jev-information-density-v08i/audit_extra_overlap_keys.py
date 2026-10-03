"""Metadata-only audit of extra fingerprints available in group-record rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


V08G_RUN = Path(r"D:\codex-runs\jev-information-density-v08g")
GROUP_RECORDS = Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08\group-records.jsonl")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def group_ids(path: Path, expected_hash: str | None = None) -> set[str]:
    if expected_hash and sha256_file(path) != expected_hash:
        raise ValueError(f"protected ID manifest hash mismatch: {path}")
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = str(json.loads(line).get("group_id", ""))
            if not value:
                raise ValueError(f"missing group_id: {path}:{line_no}")
            result.add(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    training = args.run / "training-inputs"
    output_dir = args.run / "materialized"
    scope_receipt = read_json(training / "scope-receipt.json")
    v08g_manifest_path = V08G_RUN / "v08g-run-manifest.json"
    v08g_manifest = read_json(v08g_manifest_path)
    frozen = v08g_manifest["frozen_inputs"]

    source_ids = group_ids(training / "random-groups.jsonl")
    eval_entry = frozen["NewTight-Eval"]
    protected_ids = group_ids(Path(eval_entry["path"]), eval_entry["sha256"])
    for entry in frozen["legacy_protected"].values():
        protected_ids |= group_ids(Path(entry["path"]), entry["sha256"])

    source_keys: dict[str, set[str]] = defaultdict(set)
    protected_keys: dict[str, set[str]] = defaultdict(set)
    found_source: set[str] = set()
    found_protected: set[str] = set()
    file_digest = hashlib.sha256()
    with GROUP_RECORDS.open("rb") as stream:
        for raw in stream:
            file_digest.update(raw)
            row = json.loads(raw)
            group_id = str(row.get("group_id", ""))
            if group_id not in source_ids and group_id not in protected_ids:
                continue
            if group_id in source_ids:
                found_source.add(group_id)
            if group_id in protected_ids:
                found_protected.add(group_id)
            for item in row.get("overlap_keys", []):
                if isinstance(item, str) and ":" in item:
                    prefix, value = item.split(":", 1)
                    if group_id in source_ids:
                        source_keys[prefix].add(value)
                    if group_id in protected_ids:
                        protected_keys[prefix].add(value)

    expected_metadata_hash = scope_receipt["source_file_hashes"]["group_metadata_source"][
        "sha256_from_frozen_manifest"
    ]
    if file_digest.hexdigest() != expected_metadata_hash:
        raise ValueError("group metadata source hash differs from frozen v0.8G manifest")
    overlaps = {
        key: len(source_keys[key] & protected_keys[key])
        for key in sorted(source_keys.keys() | protected_keys.keys())
    }
    required_zero = ("semantic", "text_exact", "schema_surface", "model_input")
    status = "PASS" if all(overlaps.get(key, 0) == 0 for key in required_zero) else "OVERLAP_FOUND"
    report = {
        "audit": "extra-protected-fingerprint-overlap-metadata-only",
        "status": status,
        "training_source": "R100-star training-only rows",
        "source_row_count": len(source_ids),
        "protected_group_id_count": len(protected_ids),
        "source_metadata_rows_found": len(found_source),
        "protected_metadata_rows_found": len(found_protected),
        "source_group_metadata_sha256": file_digest.hexdigest(),
        "source_fingerprint_counts": {key: len(value) for key, value in sorted(source_keys.items())},
        "protected_fingerprint_counts": {key: len(value) for key, value in sorted(protected_keys.items())},
        "cross_scope_overlap_counts": overlaps,
        "required_zero_fingerprints": list(required_zero),
        "structural_and_other_overlap_keys_are_diagnostics": True,
        "protected_evaluation_bodies_opened": False,
        "canonical_evaluation_archive_opened": False,
        "model_contact": False,
        "phoenix_access": False,
    }
    output = output_dir / "phase-a-v02-extra-fingerprint-audit.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": status, "overlaps": overlaps, "output": str(output)}, separators=(",", ":")))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
