"""Write the fail-closed F4-CAPACITY-01 diagnostic receipt."""
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


def main() -> None:
    contract = STUDY / "F4-CAPACITY-01-CONTRACT.json"
    probe = STUDY / "F4-CAPACITY-01-RECEIPT.json"
    support = STUDY / "F4-CAPACITY-01-CLASS-SUPPORT-AUDIT.json"
    for path in (contract, probe, support):
        if not path.is_file():
            raise SystemExit(f"missing diagnostic artifact: {path}")
    p = json.loads(probe.read_text(encoding="utf-8"))
    s = json.loads(support.read_text(encoding="utf-8"))
    receipt = {
        "schema": "FLY-REACH-03-F4-CAPACITY-01-terminal-receipt-v1",
        "identity": "F4-CAPACITY-01",
        "status": "DIAGNOSTIC_COMPLETE_TEMPORAL_SUPPORT_LIMIT_CROSS_BLOCK_ORIENTATION",
        "parent_status_preserved": "QUALIFICATION_STOP_F4_ENCODER_CAPACITY",
        "contract_sha256": sha(contract),
        "probe_receipt_sha256": sha(probe),
        "class_support_audit_sha256": sha(support),
        "findings": {
            "memorization": p["memorization"],
            "within_block_temporal": p["within_block_temporal"],
            "cross_block_signed_margin": p["cross_block_signed_margin"],
            "temporal_support": s["support"],
        },
        "interpretation": [
            "The frozen 80D encoder plus frozen MLP can memorize the deterministic 256-row subset.",
            "The temporal holdouts are degenerate for three blocks and cannot support a two-class balanced generalization claim.",
            "Cross-block held-out margins change sign and magnitude by block, consistent with task-conditioned orientation or symmetry instability.",
            "No conclusion is drawn about raw F4 information sufficiency from this identity.",
        ],
        "representation_ladder": {
            "status": "DEFERRED",
            "reason": "repair the predeclared within-block support design before changing the representation; no outcome-driven expansion was authored",
        },
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
        "biological_promotion": False,
        "prediction_flip_rescue": False,
        "estimator_tuning": False,
    }
    path = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "measured_namespace_created": False}, sort_keys=True))


if __name__ == "__main__":
    main()
