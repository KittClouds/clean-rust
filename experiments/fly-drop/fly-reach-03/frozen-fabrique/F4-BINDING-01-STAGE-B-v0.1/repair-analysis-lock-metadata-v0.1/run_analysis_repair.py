"""Execute the frozen analysis with an in-memory registry metadata join."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import analysis_repair_common as common

HERE = Path(__file__).resolve().parent
BRANCH = common.BRANCH


def load_source(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen/repair source {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manifest = common.require_manifest()
    stop = common.read_json(common.RUN / "ANALYSIS-START-STOP-RECEIPT.json")
    if stop.get("truth_values_opened") is not True or stop.get("comparison_outputs_written") is not False:
        raise RuntimeError("analysis repair provenance precondition mismatch")
    if any((common.RUN / name).exists() for name in (
        "ANALYSIS.json", "RESULTS.md", "STAGE-B-TERMINAL-RECEIPT.json", "ASSIGNMENT-METRICS.csv",
        "MODEL-ASSIGNMENT-METRICS.csv", "BLOCK-METRICS.csv", "MODEL-CELL-METRICS.csv", "STAGE-B-SUPPORT-TABLE.csv",
    )):
        raise RuntimeError("analysis outputs already exist; preserve and stop")

    first_repair = common.EMPTY_BLOCK_REPAIR
    first_manifest = common.read_json(first_repair / "REPAIR-MANIFEST.json")
    detached = (first_repair / "REPAIR-MANIFEST.sha256").read_text(encoding="ascii").strip()
    if common.sha_file(first_repair / "REPAIR-MANIFEST.json") != detached:
        raise RuntimeError("parent empty-block repair manifest changed")
    for entry in first_manifest["repair_sources"]:
        path = common.REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or common.sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"parent empty-block repair source drift: {entry['path']}")

    sys.path.insert(0, str(BRANCH))
    sys.path.insert(0, str(first_repair))
    import binding_stage_b_data as data
    from binding_stage_b_empty_block_loader import load_predictors_allow_empty

    data.load_predictors = lambda path, expected_blocks=data.BLOCK_IDS: load_predictors_allow_empty(data, path, expected_blocks)
    analyzer = load_source("f4_binding_stage_b_analyzer_frozen_after_metadata_repair", BRANCH / "analyze_stage_b.py")
    original_read_json = analyzer.read_json
    lock_path = common.RUN / "PREDICTION-LOCK.json"
    freeze = original_read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    registry_path = common.REPO / Path(freeze["model_registry_path"])
    registry = original_read_json(registry_path)
    registry_rows = registry["models"]

    def read_json_with_frozen_lock_metadata(path: Path):
        value = original_read_json(path)
        if Path(path).resolve() == lock_path.resolve():
            return common.enrich_lock_metadata(value, registry_rows)
        return value

    analyzer.read_json = read_json_with_frozen_lock_metadata
    analyzer.main()

    outputs = [
        common.RUN / "ANALYSIS.json", common.RUN / "RESULTS.md", common.RUN / "STAGE-B-TERMINAL-RECEIPT.json",
        common.RUN / "ASSIGNMENT-METRICS.csv", common.RUN / "MODEL-ASSIGNMENT-METRICS.csv",
        common.RUN / "BLOCK-METRICS.csv", common.RUN / "MODEL-CELL-METRICS.csv", common.RUN / "STAGE-B-SUPPORT-TABLE.csv",
    ]
    receipt = {
        "schema": "F4-BINDING-01-stage-b-analysis-metadata-repair-receipt-v0.1",
        "identity": common.IDENTITY,
        "status": "ANALYSIS_COMPLETE_WITH_PREVIOUS_TRUTH_ACCESS",
        "analysis_repair_manifest_sha256": common.sha_file(common.MANIFEST),
        "analysis_stop_receipt_sha256": common.sha_file(common.RUN / "ANALYSIS-START-STOP-RECEIPT.json"),
        "original_analysis_source_sha256": common.sha_file(BRANCH / "analyze_stage_b.py"),
        "repaired_wrapper_sha256": common.sha_file(Path(__file__).resolve()),
        "truth_values_previously_opened": True,
        "comparative_result_previously_emitted": False,
        "models_refit": False,
        "predictions_regenerated": False,
        "locked_prediction_surface_unchanged": True,
        "metrics_and_disposition_source_unchanged": True,
        "output_hashes": {path.name: common.sha_file(path) for path in outputs},
        "scientific_disposition": common.read_json(common.RUN / "ANALYSIS.json")["scientific_disposition"],
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    common.write_new_json(common.RUN / "ANALYSIS-METADATA-REPAIR-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "scientific_disposition": receipt["scientific_disposition"], "row_count": common.read_json(common.RUN / "ANALYSIS.json")["row_count"], "truth_previously_opened": True}, sort_keys=True))


if __name__ == "__main__":
    main()
