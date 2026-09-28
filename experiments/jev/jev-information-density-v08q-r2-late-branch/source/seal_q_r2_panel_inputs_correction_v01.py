"""Outcome-blind correction for the Q-R2 terminal panel-input inventory omission."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
PANEL = RUN / "panel-v01"
SEAL = PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"
CONSTRUCTION = PANEL / "seals/q-r2-panel-construction-seal-v01.json"
FEATURES = PANEL / "seals/q-r2-feature-cache-seal-v01.json"
PANEL_VERIFY = RUN / "panel-v01-independent-verification-v01.json"
TARGET_VERIFY = RUN / "panel-v01-independent-target-join-verification-v01.json"
FAILURE = RUN / "provenance/q-r2-panel-input-sealer-v01-failed-attempt.json"
CORRECTION_RECEIPT = RUN / "provenance/q-r2-panel-input-sealer-correction-v01.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def seal_json(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"refusing to replace correction provenance: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def main() -> int:
    require(not SEAL.exists(), "Q-R2 terminal panel-input seal already exists")
    correction_source_sha = sha(Path(__file__).resolve())
    old_script = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_panel_inputs_v01.py"
    instrument = read_json(RUN / "provenance/q-r2-instrument-package-seal-v01.json")
    old_source_binding = next((row for row in instrument["entries"] if row["path"].endswith("seal_q_r2_panel_inputs_v01.py")), None)
    require(old_source_binding is not None and sha(old_script) == old_source_binding["sha256"],
            "failed-attempt sealer no longer matches the pre-run instrument seal")
    require(sha(RUN / "provenance/q-r2-instrument-package-seal-v01.json") == "0e5b1276ebeeb3e25678cac2de45d17160ba9162ba616936eae8fe776bbb0f9b",
            "Q-R2 instrument package seal identity mismatch")

    failure = {"status": "Q_R2_PANEL_INPUT_SEAL_V01_FAILED_BEFORE_SEAL",
        "stage": "exact_panel_tree_inventory",
        "exception_type": "RuntimeError",
        "exception": "Q-R2 terminal panel tree mismatch: omitted already-sealed files seals/q-r2-feature-cache-seal-v01.json and seals/q-r2-panel-construction-seal-v01.json",
        "traceback": [
            "seal_q_r2_panel_inputs_v01.py:79 in main",
            "require(observed == set(explicit), ...)",
            "observed \ symmetric(explicit) = [seals/q-r2-feature-cache-seal-v01.json, seals/q-r2-panel-construction-seal-v01.json]",
        ],
        "source_sha256": old_source_binding["sha256"],
        "panel_opened": False, "head_loaded": False, "training": False, "inference": False,
        "preserved_at_utc": datetime.now(timezone.utc).isoformat()}
    seal_json(FAILURE, failure)

    construction = read_json(CONSTRUCTION)
    features = read_json(FEATURES)
    matching = PANEL / "matching"
    targets = PANEL / "target-joins"
    panel_verification = read_json(PANEL_VERIFY)
    target_verification = read_json(TARGET_VERIFY)
    radius = read_json(matching / "radius-gate-report.json")
    join_preflight = read_json(matching / "whole-panel-join-preflight.json")
    matching_receipt = read_json(matching / "r2-matching-and-join-receipt.json")
    target_receipt = read_json(targets / "q-exact-world-target-join-receipt.json")

    require(construction.get("status") == "Q_R2_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING",
            "Q-R2 panel construction seal invalid")
    require(features.get("status") == "Q_R2_FEATURE_CACHE_SEALED"
            and features.get("feature_receipt_sha256") == sha(PANEL / "features/r2-feature-extraction-receipt.json"),
            "Q-R2 feature seal invalid")
    require(matching_receipt.get("status") == "Q_R2_MATCHING_AND_JOIN_PASS"
            and radius.get("status") == "PASS"
            and radius.get("results", {}).get("decisions", {}).get("all_pass") is True,
            "Q-R2 frozen radius gate invalid")
    require(join_preflight.get("status") == "PASS" and join_preflight.get("neighborhoods") == 2_000
            and join_preflight.get("resolved_candidate_rows") == 8_000
            and join_preflight.get("missing_duplicate_extra") == 0,
            "Q-R2 exact candidate join invalid")
    require(target_receipt.get("status") == "Q_R2_EXACT_WORLD_TARGET_JOIN_PASS"
            and target_verification.get("status") == "Q_R2_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS"
            and target_verification.get("target_rows") == 22_000
            and target_verification.get("neighborhoods") == 2_000,
            "Q-R2 exact-world target join invalid")
    require(panel_verification.get("status") == "Q_R2_INDEPENDENT_PANEL_VERIFICATION_PASS"
            and panel_verification.get("neighborhoods") == 2_000
            and panel_verification.get("occurrences") == 22_000,
            "Q-R2 panel construction verification invalid")

    explicit: dict[str, dict[str, Any]] = {}
    for row in construction["entries"] + features["entries"]:
        explicit[row["path"]] = row
    # The original terminal sealer omitted these two non-self-referential seal files.
    for path in (CONSTRUCTION, FEATURES):
        rel = path.relative_to(PANEL).as_posix()
        explicit[rel] = {"path": rel, "bytes": path.stat().st_size, "sha256": sha(path)}
    for directory in (matching, targets):
        for path in sorted(item for item in directory.iterdir() if item.is_file()):
            rel = path.relative_to(PANEL).as_posix()
            explicit[rel] = {"path": rel, "bytes": path.stat().st_size, "sha256": sha(path)}
    entries = [explicit[key] for key in sorted(explicit)]
    observed = {path.relative_to(PANEL).as_posix() for path in PANEL.rglob("*") if path.is_file() and path != SEAL}
    require(observed == set(explicit), f"Q-R2 corrected terminal panel file set mismatch: {sorted(observed ^ set(explicit))[:20]}")
    for row in entries:
        path = PANEL / row["path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
                f"Q-R2 corrected terminal entry changed: {row['path']}")
    root_payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    root = hashlib.sha256(root_payload.encode("utf-8")).hexdigest()

    correction = {"status": "Q_R2_PANEL_INPUT_SEAL_CORRECTION_PASS",
        "identity": "Q-R2-TERMINAL-PANEL-INPUT-SEALER-CORRECTION-V01",
        "original_instrument_seal_sha256": sha(RUN / "provenance/q-r2-instrument-package-seal-v01.json"),
        "failed_sealer_source_sha256": sha(old_script), "correction_source_sha256": correction_source_sha,
        "failure_receipt_sha256": sha(FAILURE),
        "correction_scope": "include the two existing construction/feature seal files in the already-contracted terminal panel input inventory; no panel or feature bytes changed",
        "model_contact": True, "head_initialization": False, "training": False,
        "panel_opened_for_behavior": False, "inference": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    seal_json(CORRECTION_RECEIPT, correction)

    panel_seal = {"schema": "jev-v08q-r2-panel-input-terminal-seal-v01",
        "status": "Q_R2_PANEL_INPUTS_SEALED_TRAINING_PENDING",
        "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "entries": entries, "entry_count": len(entries), "root_sha256": root,
        "construction_seal_sha256": sha(CONSTRUCTION), "feature_cache_seal_sha256": sha(FEATURES),
        "matching_receipt_sha256": sha(matching / "r2-matching-and-join-receipt.json"),
        "target_join_receipt_sha256": sha(targets / "q-exact-world-target-join-receipt.json"),
        "panel_verification_status": panel_verification["status"],
        "radius_verification_status": radius["status"], "target_verification_status": target_verification["status"],
        "external_receipts": {str(PANEL_VERIFY): sha(PANEL_VERIFY), str(TARGET_VERIFY): sha(TARGET_VERIFY),
            str(FAILURE): sha(FAILURE), str(CORRECTION_RECEIPT): sha(CORRECTION_RECEIPT)},
        "terminal_sealer_correction": {"identity": correction["identity"], "source_sha256": correction_source_sha,
            "failed_attempt_receipt_sha256": sha(FAILURE), "correction_receipt_sha256": sha(CORRECTION_RECEIPT)},
        "panel_opened": False, "head_initialization": False, "training": False, "inference": False}
    seal_json(SEAL, panel_seal)
    print(json.dumps({"status": panel_seal["status"], "root_sha256": root, "entry_count": len(entries),
        "correction_source_sha256": correction_source_sha, "failed_attempt_sha256": sha(FAILURE),
        "training": False, "inference": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
