"""Write the fail-closed qualification terminal receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ref(path: Path) -> dict[str, object]:
    return {"path": str(path.relative_to(STUDY)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha(path)}


def main() -> None:
    run = STUDY / "runs/qualification-v2"
    required = {
        "collection": run / "QUALIFICATION-COLLECTION-RECEIPT.json",
        "f4": run / "F4-RECONSTRUCTION-RECEIPT.json",
        "summary": run / "QUALIFICATION-SUMMARY.json",
        "estimators": run / "QUALIFICATION-ESTIMATOR-RECEIPT.json",
        "prep": STUDY / "artifacts/preimplementation/QUALIFICATION-PREPARATION-RECEIPT.json",
        "v1_nonpromotable": STUDY / "artifacts/qualification-v1/QUALIFICATION-V1-NONPROMOTABLE-RECEIPT.json",
        "qualification_contract": STUDY / "manifests/QUALIFICATION-CONTRACT-v0.1.json",
    }
    for path in required.values():
        if not path.is_file():
            raise SystemExit(f"missing receipt: {path}")
    collection = json.loads(required["collection"].read_text(encoding="utf-8"))
    f4 = json.loads(required["f4"].read_text(encoding="utf-8"))
    summary = json.loads(required["summary"].read_text(encoding="utf-8"))
    estimator = json.loads(required["estimators"].read_text(encoding="utf-8"))
    receipt = {
        "schema": "FLY-REACH-03-qualification-terminal-receipt-v1",
        "study_id": "FLY-REACH-03",
        "run_id": "qualification-v2",
        "status": "QUALIFICATION_STOP_F4_ENCODER_REQUIRED",
        "measured_execution_authorized": False,
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
        "biological_promotion": False,
        "phase_gates": {
            "gate_0_authority": "PASS_HISTORICAL_PRECREATION_AUDIT",
            "gate_1_contract_roundtrip": "PASS",
            "gate_2_collector_fixture": "PASS",
            "gate_3_f4_reconstruction_fixture": "PASS",
            "gate_4_qualification_collection": "PASS",
            "gate_4_f4_replay": f4["status"],
            "gate_4_constant_baseline": {"omega_hat": 0.0, "balanced_error": 0.5},
            "gate_4_f0_f3b_calibration": "COMPLETE",
            "gate_4_learned_f4_calibration": "NOT_RUN",
        },
        "collection": {
            "cells": collection["cells"],
            "trials": collection["trials"],
            "rows": collection["rows"],
            "expected_rows": collection["expected_rows"],
            "f4_checkpoint_digests": f4["checkpoint_digests_checked"],
        },
        "qualification_population": {
            "rows": summary["rows"],
            "nonzero_target_rows": summary["nonzero_target_rows"],
            "positive_rows": summary["positive_rows"],
            "negative_rows": summary["negative_rows"],
            "zero_target_rows": summary["zero_target_rows"],
            "primary_support_rows": summary["primary_support_rows"],
            "same_rows_all_filtrations": summary["same_rows_all_filtrations"],
            "ipw_finite_positive": summary["inclusion_probability"]["all_finite_positive"],
        },
        "estimator_calibration": {
            "status": estimator["status"],
            "rows_used": estimator["rows_used"],
            "levels": list(estimator["f0_f3b_results"]),
            "cumulative_filtrations": True,
            "f4_exact_reconstruction": estimator["f4_exact_reconstruction"],
            "f4_learned_calibration": estimator["f4_learned_calibration"],
        },
        "nonpromotable_history": "qualification-v1 omitted terminal F4 checkpoint 8192 and is preserved separately",
        "required_next_amendment": "freeze a deterministic learned F4 encoder, add its schema and feature-generation hash, rerun qualification calibration, then reassess measured sealing",
        "artifacts": {name: ref(path) for name, path in required.items()},
    }
    path = run / "QUALIFICATION-TERMINAL-RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "measured_namespace_created": False, "rows": receipt["collection"]["rows"]}, sort_keys=True))


if __name__ == "__main__":
    main()
