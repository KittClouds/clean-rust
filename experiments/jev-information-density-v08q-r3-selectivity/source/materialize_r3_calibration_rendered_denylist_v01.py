"""Build an opaque exact-rendered-input denylist from sealed identity artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v01")
Q_PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01")
OUT = RUN / "calibration-exclusions-v01"
EXCLUSIONS_SHA256 = "47155233c933f28f6b122b6350cc7c11e6e77e71c13883f9958c203be8bb0f19"
IDENTITIES_SHA256 = "f05b8e65ef867a361f7cd531f1512f0934e01dae88e8385545467e9ac70914c1"
PANEL_SEAL_SHA256 = "a674c43526f1623f8e201e3ac3b1b92f365ee275a3878b805b81ac6d173c77bf"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def domain_digest(raw_hash: str) -> str:
    payload = f"jev-v08q-exclusion-v01:full_rendered_input_hash:{raw_hash}".encode("ascii")
    return sha_bytes(payload)


def main() -> int:
    require(not OUT.exists(), f"refusing existing denylist namespace: {OUT}")
    exclusions_path = Q_PANEL / "exclusions/five-field-exclusion-sets.json"
    identity_path = Q_PANEL / "panel/panel-occurrence-identities.jsonl"
    seal_path = Q_PANEL / "seals/q-r2-panel-construction-seal-v01.json"
    for path, expected, label in (
        (exclusions_path, EXCLUSIONS_SHA256, "sealed exclusion set"),
        (identity_path, IDENTITIES_SHA256, "Q-R2 identity manifest"),
        (seal_path, PANEL_SEAL_SHA256, "Q-R2 construction seal"),
    ):
        require(path.is_file() and sha_file(path) == expected, f"{label} hash mismatch")

    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    entry = next((row for row in seal["entries"] if row["path"] == "panel/panel-occurrence-identities.jsonl"), None)
    require(entry is not None and entry["sha256"] == IDENTITIES_SHA256, "Q-R2 seal does not bind the identity source")
    exclusions = json.loads(exclusions_path.read_text(encoding="utf-8"))
    values = set(exclusions["training"]["full_rendered_input_hash"])
    values.update(exclusions["prior_panel"]["full_rendered_input_hash"])
    source_rows = 0
    with identity_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row: dict[str, Any] = json.loads(line)
            raw_hash = row.get("full_rendered_input_hash")
            require(isinstance(raw_hash, str) and len(raw_hash) == 64, "malformed rendered-input identity")
            values.add(domain_digest(raw_hash))
            source_rows += 1
    require(source_rows == 22_000, "Q-R2 identity row count mismatch")
    ordered = sorted(values)
    require(all(len(value) == 64 for value in ordered), "denylist contains malformed digest")

    OUT.mkdir(parents=True, exist_ok=False)
    body = {"schema": "r3-full-rendered-input-domain-hash-set-v01", "count": len(ordered), "identity_sha256": ordered}
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
    output_path = OUT / "full-rendered-input-hash-denylist.json"
    output_path.write_text(payload, encoding="utf-8", newline="\n")
    receipt = {
        "status": "R3_CALIBRATION_RENDERED_DENYLIST_SEALED",
        "denylist_sha256": sha_file(output_path),
        "denylist_count": len(ordered),
        "source_rows": {
            "sealed_training_and_prior_identity_digests": len(exclusions["training"]["full_rendered_input_hash"])
            + len(exclusions["prior_panel"]["full_rendered_input_hash"]),
            "Q_R2_identity_rows": source_rows,
        },
        "source_sha256": {
            "Q_R2_five_field_exclusion_set": EXCLUSIONS_SHA256,
            "Q_R2_identity_manifest": IDENTITIES_SHA256,
            "Q_R2_construction_seal": PANEL_SEAL_SHA256,
        },
        "information_emitted": "sorted domain-separated SHA-256 values only; no raw identities or rendered text",
        "no_targets_predictions_metrics_features_or_heads_read": True,
    }
    receipt_path = OUT / "denylist-receipt-v01.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
