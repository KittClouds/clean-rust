"""Rehash the immutable fit surface before rerunning the repaired auditor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
ENG1 = STUDY / "runs" / "F4-PRESENTATION-03-ENG1"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    manifest_path = HERE / "LOCKED-FIT-OUTPUT-TREE-MANIFEST-v0.1.2.json"
    amendment_path = HERE / "INTEGRITY-REPAIR-AMENDMENT-v0.1.2.json"
    stop_path = HERE / "INTEGRITY-STOP-RECEIPT-v0.1.1.json"
    output = HERE / "PRE-INTEGRITY-LOCKED-OUTPUT-REHASH-RECEIPT-v0.1.2.json"
    if output.exists() or (RUN / "INTEGRITY-RECEIPT.json").exists():
        raise RuntimeError("pre-audit output or integrity receipt already exists")
    amendment = read_json(amendment_path)
    manifest = read_json(manifest_path)
    stop = read_json(stop_path)
    verified = 0
    for entry in manifest["files"]:
        path = RUN / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"locked fit output drift: {entry['path']}")
        verified += 1
    canonical = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    tree_sha = sha_bytes(canonical)
    lock_sha = sha_file(RUN / "PREDICTION-LOCK.json")
    fit_manifest_sha = sha_file(RUN / "FIT-MANIFEST.csv")
    task_sha = sha_file(ENG1 / "task-bank" / "TASK-BANK-MANIFEST.json")
    predictor_sha = sha_file(ENG1 / "native-collection" / "RAW-PREDICTORS.bin")
    truth_sha = sha_file(ENG1 / "native-collection" / "RAW-SCORING-TRUTH.bin")
    if (
        verified != manifest["file_count"]
        or tree_sha != manifest["tree_sha256"]
        or lock_sha != amendment["prediction_lock_sha256"]
        or fit_manifest_sha != amendment["fit_manifest_sha256"]
        or task_sha != stop["task_bank_manifest_sha256"]
        or predictor_sha != stop["raw_predictor_sha256"]
        or truth_sha != stop["raw_truth_file_sha256"]
    ):
        raise RuntimeError("pre-audit immutable input/hash binding mismatch")
    receipt = {
        "schema": "F4-PRESENTATION-03-pre-integrity-locked-output-rehash-v1",
        "status": "PASS",
        "repair_amendment_sha256": sha_file(amendment_path),
        "locked_tree_manifest_sha256": sha_file(manifest_path),
        "locked_tree_sha256": tree_sha,
        "locked_output_file_count": verified,
        "prediction_lock_sha256": lock_sha,
        "fit_manifest_sha256": fit_manifest_sha,
        "task_bank_manifest_sha256": task_sha,
        "raw_predictor_sha256": predictor_sha,
        "raw_truth_file_sha256": truth_sha,
        "integrity_receipt_previously_absent": True,
        "analysis_artifacts_previously_absent": all(not (RUN / name).exists() for name in ("ANALYSIS.json", "RESULTS.md", "TERMINAL-RECEIPT.json")),
        "comparative_scoring_values_read_by_rehash": False,
        "rehash_source_sha256": sha_file(Path(__file__).resolve()),
    }
    raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with output.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    print(json.dumps({"status": "PASS", "locked_output_file_count": verified, "locked_tree_sha256": tree_sha, "prediction_lock_sha256": lock_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
