from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_QUARTETS = 26_624
EXPECTED_ROWS_PER_QUARTET = 4


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Append-only correction for sealed E1 v04 split-count receipt fields")
    parser.add_argument("--run-root", type=Path, default=Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "audits" / "e1-receipt-correction-v04-v01.json",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite correction receipt: {args.output}")
    run_root = args.run_root.resolve(strict=True)
    seal = json.loads((run_root / "e1-seal-v01.json").read_text(encoding="utf-8"))
    if seal.get("root_sha256") != EXPECTED_E1_ROOT or seal.get("status") != "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED":
        raise SystemExit("the supplied run is not the audited E1 v04 seal")
    for entry in seal["entries"]:
        digest, size = sha256_file(run_root / entry["path"])
        if (digest, size) != (entry["sha256"], entry["bytes"]):
            raise SystemExit(f"sealed E1 file changed: {entry['path']}")
    if tree_root(seal["entries"]) != seal["root_sha256"]:
        raise SystemExit("E1 root verification failed")

    all_quartets: Counter[int] = Counter()
    test_quartets: Counter[int] = Counter()
    fit_quartets: Counter[int] = Counter()
    split_path = run_root / "panel/split-manifest-v01.jsonl"
    with split_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            stratum = int(row["exact_target_stratum"])
            all_quartets[stratum] += 1
            (test_quartets if row["split"] == "TEST" else fit_quartets)[stratum] += 1
    if sum(all_quartets.values()) != EXPECTED_QUARTETS:
        raise SystemExit("split manifest quartet count differs from the E0 contract")
    if any(test_quartets[k] != all_quartets[k] // 5 for k in range(3)):
        raise SystemExit("split manifest does not satisfy the frozen floor-20-percent test rule")

    fit_label_rows = sum(1 for _ in (run_root / "labels/fit-labels-v01.jsonl").open("r", encoding="utf-8"))
    test_label_rows = sum(1 for _ in (run_root / "labels/eval-labels-v01.jsonl").open("r", encoding="utf-8"))
    corrected_fit_quartets = sum(fit_quartets.values())
    corrected_test_quartets = sum(test_quartets.values())
    if fit_label_rows != corrected_fit_quartets * EXPECTED_ROWS_PER_QUARTET:
        raise SystemExit("fit-label row count does not match whole-quartet split")
    if test_label_rows != corrected_test_quartets * EXPECTED_ROWS_PER_QUARTET:
        raise SystemExit("test-label row count does not match whole-quartet split")

    receipt_paths = {
        "support_receipt": run_root / "receipts/support-receipt-v01.json",
        "panel_build_core": run_root / "receipts/panel-build-core-v01.json",
        "panel_build_receipt": run_root / "receipts/panel-build-receipt-v01.json",
    }
    old = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in receipt_paths.items()}
    expected_old = [8876, 8874, 8874]
    if any(item.get("test_quartets_by_exact_target_class") != expected_old for item in old.values()):
        raise SystemExit("unexpected sealed receipt values; refusing to issue this correction")
    if old["panel_build_core"].get("fit_quartets") != 0 or old["panel_build_receipt"].get("fit_quartets") != 0:
        raise SystemExit("unexpected sealed fit-quartet count; refusing to issue this correction")

    corrected = {
        "all_quartets_by_exact_target_class": [all_quartets[i] for i in range(3)],
        "test_quartets_by_exact_target_class": [test_quartets[i] for i in range(3)],
        "fit_quartets_by_exact_target_class": [fit_quartets[i] for i in range(3)],
        "test_quartets_total": corrected_test_quartets,
        "fit_quartets_total": corrected_fit_quartets,
        "test_label_rows": test_label_rows,
        "fit_label_rows": fit_label_rows,
    }
    receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_V04_SPLIT_COUNT_ERRATUM_V01",
        "status": "PASS_METADATA_CORRECTION_ONLY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "e1_root_sha256": seal["root_sha256"],
        "sealed_e1_files_modified": False,
        "model_loaded": False,
        "tokenizer_loaded": False,
        "feature_extraction_performed": False,
        "observer_fitting_performed": False,
        "cause": "The builder counted all quartets per exact_target stratum, then labeled that vector as test-only counts; it also derived fit_quartets from the all-quartet total and emitted zero.",
        "sealed_receipt_values_preserved": {
            "support_receipt_test_quartets_by_exact_target_class": old["support_receipt"]["test_quartets_by_exact_target_class"],
            "panel_build_core_fit_quartets": old["panel_build_core"]["fit_quartets"],
            "panel_build_core_test_quartets_by_exact_target_class": old["panel_build_core"]["test_quartets_by_exact_target_class"],
            "panel_build_receipt_fit_quartets": old["panel_build_receipt"]["fit_quartets"],
            "panel_build_receipt_test_quartets_by_exact_target_class": old["panel_build_receipt"]["test_quartets_by_exact_target_class"],
        },
        "corrected_values_from_sealed_split_manifest_and_label_files": corrected,
        "panel_data_split_support_and_e1_root_unchanged": True,
        "use_corrected_values_for_quartet_split_counts": True,
        "correction_script_sha256": sha256_file(Path(__file__).resolve())[0],
        "this_receipt_is_outside_the_e1_sealed_tree": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
