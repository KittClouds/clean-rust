"""Write the amended fail-closed qualification terminal receipt."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs/qualification-v2"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ref(path: Path) -> dict[str, object]:
    return {"path": str(path.relative_to(STUDY)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha(path)}


def main() -> None:
    current = RUN / "QUALIFICATION-TERMINAL-RECEIPT.json"
    historical = RUN / "QUALIFICATION-TERMINAL-RECEIPT-v0.1.json"
    if current.is_file() and not historical.exists():
        shutil.copy2(current, historical)
    required = [
        RUN / "QUALIFICATION-COLLECTION-RECEIPT.json",
        RUN / "F4-RECONSTRUCTION-RECEIPT.json",
        RUN / "QUALIFICATION-SUMMARY.json",
        RUN / "QUALIFICATION-ESTIMATOR-RECEIPT.json",
        RUN / "f4-features-v1/F4-FEATURE-COLLECTION-RECEIPT.json",
        STUDY / "EXECUTION-CONTRACT-v0.2-F4-ENCODER-AMENDMENT.json",
        STUDY / "F4-ENCODER-SPEC-v1.json",
        STUDY / "F4-ENCODER-SPEC-v1.sha256",
        STUDY / "F4-ENCODER-QUALIFICATION-RECEIPT.json",
        STUDY / "artifacts/preimplementation/F4-ENCODER-CONTRACT-FREEZE-RECEIPT.json",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing amended receipt input: {path}")
    collection = json.loads((RUN / "QUALIFICATION-COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    replay = json.loads((RUN / "F4-RECONSTRUCTION-RECEIPT.json").read_text(encoding="utf-8"))
    summary = json.loads((RUN / "QUALIFICATION-SUMMARY.json").read_text(encoding="utf-8"))
    f4_features = json.loads((RUN / "f4-features-v1/F4-FEATURE-COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    f4_cal = json.loads((STUDY / "F4-ENCODER-QUALIFICATION-RECEIPT.json").read_text(encoding="utf-8"))
    amendment = json.loads((STUDY / "EXECUTION-CONTRACT-v0.2-F4-ENCODER-AMENDMENT.json").read_text(encoding="utf-8"))
    receipt = {
        "schema": "FLY-REACH-03-qualification-terminal-receipt-v2",
        "study_id": "FLY-REACH-03",
        "run_id": "qualification-v2",
        "status": "QUALIFICATION_STOP_F4_ENCODER_CAPACITY",
        "disposition": "The exact F4 reconstruction invariant passed, but the frozen learned F4 calibration encoder failed its predeclared estimator-capacity gate. No measured scientific interpretation is opened.",
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
            "gate_4_f4_replay": replay["status"],
            "gate_4_constant_baseline": {"omega_hat": 0.0, "balanced_error": 0.5},
            "gate_4_f0_f3b_calibration": "COMPLETE_QUALIFICATION_ONLY",
            "gate_4_f4_encoder_contract": "PASS",
            "gate_4_f4_encoder_calibration": f4_cal["status"],
        },
        "collection": {
            "cells": collection["cells"],
            "trials": collection["trials"],
            "rows": collection["rows"],
            "expected_rows": collection["expected_rows"],
            "f4_checkpoint_digests": replay["checkpoint_digests_checked"],
            "f4_feature_rows": f4_features["rows"],
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
        "f4_encoder_calibration": {
            "status": f4_cal["status"],
            "rows": f4_cal["rows"],
            "feature_width": f4_cal["feature_width"],
            "pooled_balanced_error": f4_cal["pooled_heldout"]["balanced_error"],
            "pooled_omega_hat": f4_cal["pooled_heldout"]["omega_hat"],
            "fold_omega_hat": [row["omega_hat"] for row in f4_cal["qualification_folds"]],
            "gate": f4_cal["gate"],
            "exact_f4_reconstruction": f4_cal["exact_f4_reconstruction"],
            "post_gate_tuning": False,
            "final_encoder_weights_created": False,
        },
        "next_required_action": "Any further work requires a new explicitly authorized encoder-capacity amendment or a new estimator design; do not tune this frozen identity and do not create the measured namespace.",
        "nonpromotable_history": "qualification-v1 omitted terminal F4 checkpoint 8192 and remains preserved separately; earlier estimator attempt remains nonpromotable",
        "artifacts": {path.name: ref(path) for path in required},
        "amendment": {
            "schema": amendment["schema"],
            "sha256": sha(STUDY / "EXECUTION-CONTRACT-v0.2-F4-ENCODER-AMENDMENT.json"),
            "spec_sha256": amendment["feature_spec"]["sha256"],
        },
    }
    current.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "measured_namespace_created": False, "pooled_omega_hat": receipt["f4_encoder_calibration"]["pooled_omega_hat"]}, sort_keys=True))


if __name__ == "__main__":
    main()
