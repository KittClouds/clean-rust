#!/usr/bin/env python3
"""Independently verify the S11 panel-construction v02 tree seal."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SEAL_REL = Path("seals/panel-tree-seal-v02.json")
RECEIPT_REL = Path("verification/independent-verification-v02.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def enumerate_rows(root: Path) -> list[dict[str, object]]:
    rows = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError(f"symlink forbidden in sealed tree: {path}")
        rel = path.relative_to(root)
        if rel == SEAL_REL or rel.parts[0] == "verification":
            continue
        rows.append({"path": rel.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return sorted(rows, key=lambda row: str(row["path"]))


def root_hash(rows: list[dict[str, object]]) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n".encode("utf-8"))
    return h.hexdigest()


def read_json(root: Path, rel: str) -> dict:
    with (root / rel).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_panel_tree_v02.py PANEL_ROOT")
    root = Path(sys.argv[1]).resolve()
    seal_path = root / SEAL_REL
    seal = read_json(root, SEAL_REL.as_posix())
    observed = enumerate_rows(root)
    observed_root = root_hash(observed)
    if observed != seal.get("entries"):
        raise SystemExit("sealed tree entries differ from disk")
    if observed_root != seal.get("tree_root_sha256"):
        raise SystemExit("tree root mismatch")

    report = read_json(root, "reports/panel-validation-report-v02.json")
    auth = read_json(root, "authorization-v02.json")
    construction = read_json(root, "receipts/construction-receipt-v02.json")
    parents = read_json(root, "preflight/parent-verification-v02.json")
    gates = report.get("gates", {})
    checks = {
        "validation_status": report.get("status") == "S11_PANEL_CONSTRUCTION_VALID",
        "all_validation_gates_pass": bool(gates) and all(value == "PASS" for value in gates.values()),
        "candidate_count": report.get("candidate_quartets") == 26624,
        "selected_quartets": report.get("selected_quartets") == 5318,
        "selected_rows": report.get("selected_event_rows") == 21272,
        "class_quotas": report.get("exact_target_class_counts") == {"0": 1733, "1": 1815, "2": 1770},
        "zero_selected_input_collisions": report.get("freshness", {}).get("selected_panel_duplicate_input_hashes") == 0,
        "construction_only": report.get("construction_only") is True,
        "auth_panel_only": auth.get("panel_construction_authorized") is True,
        "auth_model_off": auth.get("model_loaded") is False,
        "auth_tokenizer_off": auth.get("tokenizer_loaded") is False,
        "features_off": auth.get("feature_extraction_performed") is False,
        "observer_replay_off": auth.get("observer_replay_performed") is False,
        "probe_fitting_off": auth.get("probe_fitting_performed") is False,
        "construction_model_off": construction.get("model_loaded") is False,
        "construction_tokenizer_off": construction.get("tokenizer_loaded") is False,
        "construction_features_off": construction.get("feature_extraction_performed") is False,
        "parents_pass": parents.get("status") == "PASS" and all(x.get("root_verified") is True for x in parents.get("checks", [])),
    }
    if not all(checks.values()):
        failed = [key for key, value in checks.items() if not value]
        raise SystemExit(f"panel semantic verification failed: {failed}")

    receipt = {
        "receipt_id": "FAS_S11_PANEL_TREE_INDEPENDENT_VERIFICATION_V02",
        "status": "S11_PANEL_SEAL_VERIFY_PASS",
        "tree_root_sha256": observed_root,
        "seal_file_sha256": sha256(seal_path),
        "verified_file_count": len(observed),
        "checks": checks,
        "tokenizer_loaded": False,
        "model_loaded": False,
        "feature_extraction_performed": False,
        "observer_replay_performed": False,
    }
    receipt_path = root / RECEIPT_REL
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"S11_PANEL_SEAL_VERIFY_PASS files={len(observed)} root={observed_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
