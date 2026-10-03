"""Seal the complete 144-fit manifest and initial tensor surface before training."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRANCH = TOOLS.parent
STUDY = BRANCH.parent
RUN = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-CONTINUATION-v0.1"
OUTPUT = RUN / "FIT-SURFACE-SEAL-v0.1.json"
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
BLOCKS = tuple(range(309000, 309012))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("fit surface seal already exists")
    manifest_path = RUN / "FIT-MANIFEST.csv"
    rows = list(csv.DictReader(manifest_path.open("r", encoding="utf-8", newline="")))
    expected_ids = [f"{arm}-H{block}-I{rep}" for block in BLOCKS for rep in range(3) for arm in ARMS]
    if len(rows) != 144 or [row["fit_id"] for row in rows] != expected_ids:
        raise RuntimeError("fit manifest identity/order mismatch")
    if {arm: sum(row["arm"] == arm for row in rows) for arm in ARMS} != {arm: 36 for arm in ARMS}:
        raise RuntimeError("fit arm counts mismatch")
    if any(row["train_rows"] == "0" or row["train_positive_count"] == "0" or row["train_negative_count"] == "0" for row in rows):
        raise RuntimeError("degenerate training partition in sealed fit manifest")
    for name in ("fit-receipts", "predictions", "final-tensors", "training-traces", "checkpoint-tensors", "heldout-state"):
        if (RUN / name).exists():
            raise RuntimeError(f"fit outputs already exist before surface seal: {name}")
    initializer_paths = []
    for row in rows:
        path = RUN / row["initial_tensor_path"]
        if not path.is_file() or sha_file(path) != row["initial_tensor_file_sha256"]:
            raise RuntimeError(f"initial tensor mismatch: {row['fit_id']}")
        initializer_paths.append({"fit_id": row["fit_id"], "path": row["initial_tensor_path"], "bytes": path.stat().st_size, "sha256": sha_file(path)})
    hashes = {field: {} for field in ("base_stream_sha256", "normalized_tuple_stream_sha256", "paired_source_input_sha256")}
    for fold in range(12):
        fold_rows = [row for row in rows if int(row["fold_index"]) == fold]
        if len(fold_rows) != 12:
            raise RuntimeError(f"fold {fold} does not have 12 arm/replicate rows")
        for field in hashes:
            unique = {row[field] for row in fold_rows}
            if len(unique) != 1:
                raise RuntimeError(f"shared input mismatch at fold {fold}: {field}")
            hashes[field][str(fold)] = next(iter(unique))
    receipt = {
        "schema": "F4-PRESENTATION-03-fit-surface-seal-v0.1",
        "status": "PASS_BEFORE_FIT_1",
        "identity": RUN.name,
        "fit_manifest_sha256": sha_file(manifest_path),
        "fit_manifest_row_hashes_sha256": sha_file(RUN / "FIT-MANIFEST-ROW-HASHES.json"),
        "fit_count": len(rows),
        "arm_counts": {arm: sum(row["arm"] == arm for row in rows) for arm in ARMS},
        "initial_tensor_count": len(initializer_paths),
        "initial_tensors": initializer_paths,
        "shared_input_hashes_by_fold": hashes,
        "training_support_receipt_sha256": sha_file(RUN / "TRAINING-SUPPORT-RECEIPT.json"),
        "fit_prefit_receipt_sha256": sha_file(RUN / "FIT-PREFIT-RECEIPT.json"),
        "execution_prefit_source_freeze_sha256": sha_file(RUN / "EXECUTION-PREFIT-SOURCE-FREEZE-v0.1.json"),
        "no_fit_outputs_existed_at_seal": True,
        "seal_source_sha256": sha_file(Path(__file__).resolve()),
        "truth_access_context_sha256": sha_file(RUN / "TRUTH-ACCESS-CONTEXT-RECEIPT-v0.1.json"),
    }
    write_new(OUTPUT, receipt)
    print(json.dumps({"status": receipt["status"], "fit_count": len(rows), "initial_tensor_count": len(initializer_paths)}, sort_keys=True))


if __name__ == "__main__":
    main()
