"""Open and score Stage B truth after repaired integrity has passed."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import repair_common as common

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent


def load_source(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen source {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manifest = common.require_repair_manifest()
    common.verify_immutable_inputs(manifest)
    integrity_repair_path = common.RUN / "EMPTY-BLOCK-REPAIR-INTEGRITY-RECEIPT.json"
    integrity_repair = common.read_json(integrity_repair_path)
    if integrity_repair.get("status") != "PASS":
        raise RuntimeError("repaired pre-truth integrity receipt is not PASS")
    sys.path.insert(0, str(BRANCH))
    import binding_stage_b_data as data

    loader = load_source("f4_binding_stage_b_empty_loader_analysis", HERE / "binding_stage_b_empty_block_loader.py")
    data.load_predictors = lambda path, expected_blocks=data.BLOCK_IDS: loader.load_predictors_allow_empty(data, path, expected_blocks)
    analyzer = load_source("f4_binding_stage_b_analyzer_frozen", BRANCH / "analyze_stage_b.py")
    analyzer.main()
    repair_receipt = {
        "schema": "F4-BINDING-01-stage-b-empty-block-analysis-repair-receipt-v0.1",
        "identity": common.REPAIR_ID,
        "status": "ANALYSIS_COMPLETE",
        "repair_manifest_sha256": common.sha_file(common.MANIFEST_PATH),
        "integrity_repair_receipt_sha256": common.sha_file(integrity_repair_path),
        "prediction_lock_sha256": common.sha_file(common.RUN / "PREDICTION-LOCK.json"),
        "truth_sha256": common.sha_file(common.RUN / "native-collection" / "RAW-SCORING-TRUTH.bin"),
        "analysis_sha256": common.sha_file(common.RUN / "ANALYSIS.json"),
        "terminal_receipt_sha256": common.sha_file(common.RUN / "STAGE-B-TERMINAL-RECEIPT.json"),
        "scientific_disposition": common.read_json(common.RUN / "ANALYSIS.json")["scientific_disposition"],
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    common.write_new_json(common.RUN / "EMPTY-BLOCK-REPAIR-ANALYSIS-RECEIPT.json", repair_receipt)


if __name__ == "__main__":
    main()
