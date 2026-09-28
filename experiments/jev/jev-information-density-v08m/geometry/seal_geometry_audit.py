"""Independent local seal for the read-only v0.8M geometry diagnostic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


OUT = Path(r"D:\codex-runs\jev-information-density-v08m\geometry-v01")
REPORT = OUT / "geometry-audit.json"
RECEIPT = OUT / "geometry-audit-receipt.json"
PER_ANCHOR = OUT / "per-anchor-geometry.jsonl"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    report = read_json(REPORT)
    receipt = read_json(RECEIPT)
    lines = [line for line in PER_ANCHOR.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(report["status"] == "GEOMETRY_AUDIT_COMPLETE_READ_ONLY_NO_HEAD_NO_EVALUATION", "report status drift")
    require(receipt["promotable"] is False, "diagnostic was marked promotable")
    require(receipt["model_head_training"] is False, "head-training boundary drift")
    require(receipt["evaluation_inference"] is False, "evaluation boundary drift")
    require(receipt["protected_evaluation_bodies_opened"] is False, "protected-eval boundary drift")
    require(receipt["phoenix_access"] is False, "Phoenix boundary drift")
    require(len(lines) == 5000, f"per-anchor count drift: {len(lines)}")
    require(receipt["report_sha256"] == sha256_file(REPORT), "report hash mismatch")
    require(receipt["per_anchor_sha256"] == sha256_file(PER_ANCHOR), "per-anchor hash mismatch")
    for path_text, expected in report["source_hashes"].items():
        path = Path(path_text)
        require(path.exists(), f"source missing: {path}")
        require(sha256_file(path) == expected, f"source drift: {path}")
    seal = {
        "status": "LOCAL_INDEPENDENT_SEAL_PASS_DIAGNOSTIC_ONLY",
        "protocol": report["protocol"],
        "identity": report["identity"],
        "report_sha256": sha256_file(REPORT),
        "receipt_sha256": sha256_file(RECEIPT),
        "per_anchor_sha256": sha256_file(PER_ANCHOR),
        "anchor_count": len(lines),
        "source_hashes_verified": len(report["source_hashes"]),
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
        "promotable": False,
        "interpretation": "read-only geometry diagnostic; no causal or training authorization",
    }
    path = OUT / "geometry-audit-local-seal.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(json.dumps(seal, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
