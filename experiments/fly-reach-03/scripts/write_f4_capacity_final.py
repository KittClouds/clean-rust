"""Seal the complete qualification-only F4 capacity anatomy branch."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    current = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT.json"
    first = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT-v1.json"
    if current.is_file() and not first.exists():
        shutil.copy2(current, first)
    paths = {
        "contract": STUDY / "F4-CAPACITY-01-CONTRACT.json",
        "first_probe": STUDY / "F4-CAPACITY-01-RECEIPT.json",
        "class_support": STUDY / "F4-CAPACITY-01-CLASS-SUPPORT-AUDIT.json",
        "margin": STUDY / "F4-CAPACITY-01-REFERENCE-MARGIN-AUDIT.json",
        "action_sign_contract": STUDY / "F4-CAPACITY-01-ACTION-SIGN-CONTRACT.json",
        "action_sign": STUDY / "F4-CAPACITY-01-ACTION-SIGN-RECEIPT.json",
        "post_prob_contract": STUDY / "F4-CAPACITY-01-POST-PROB-CONTRACT.json",
        "post_prob": STUDY / "F4-CAPACITY-01-POST-PROB-RECEIPT.json",
    }
    for path in paths.values():
        if not path.is_file():
            raise SystemExit(f"missing capacity artifact: {path}")
    p = json.loads(paths["first_probe"].read_text(encoding="utf-8"))
    a = json.loads(paths["action_sign"].read_text(encoding="utf-8"))
    b = json.loads(paths["post_prob"].read_text(encoding="utf-8"))
    m = json.loads(paths["margin"].read_text(encoding="utf-8"))
    receipt = {
        "schema": "FLY-REACH-03-F4-CAPACITY-01-terminal-receipt-v2",
        "identity": "F4-CAPACITY-01",
        "status": "DIAGNOSTIC_COMPLETE_REPRESENTATION_PRECISION_PRESSURE",
        "parent_status_preserved": "QUALIFICATION_STOP_F4_ENCODER_CAPACITY",
        "artifacts": {name: {"path": str(path.relative_to(STUDY)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size} for name, path in paths.items()},
        "findings": {
            "memorization_80d": p["memorization"],
            "within_block_temporal": p["within_block_temporal"],
            "temporal_class_support": json.loads(paths["class_support"].read_text(encoding="utf-8"))["support"],
            "cross_block_80d": p["cross_block_signed_margin"],
            "cross_block_81d_action_sign": a["folds"],
            "cross_block_85d_action_sign_post_probability": b["folds"],
            "reference_margin_audit": m,
        },
        "bounded_interpretation": [
            "The frozen 80D encoder and MLP can memorize a balanced 256-row subset.",
            "The temporal holdout is class-degenerate for three blocks, so its apparent perfect Omega values are not valid two-class generalization evidence.",
            "Cross-block signed margins vary in sign and magnitude by held-out block.",
            "Adding action_sign and then cue-specific post probabilities did not restore cross-block extraction under the unchanged estimator.",
            "The target channel is numerically concentrated near EPS: 86.10% of rows are at or below 1e-8 and 65.24% at or below 1e-9.",
            "This is consistent with representation precision pressure in the float32 compact map; it is not a theorem that raw F4 lacks or contains the signal.",
        ],
        "next_step": "If continued, freeze a new high-precision or margin-preserving representation audit before any estimator-capacity increase.",
        "representation_ladder": "NOT_AUTHORED_FROM_OUTCOMES",
        "estimator_tuning": False,
        "prediction_flip_rescue": False,
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
        "biological_promotion": False,
    }
    current.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "measured_namespace_created": False}, sort_keys=True))


if __name__ == "__main__": main()
