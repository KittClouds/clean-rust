"""Bind exact Q world targets after feature extraction and radius qualification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PANEL = RUN_ROOT / "panel"
OUTPUT = RUN_ROOT / "target-joins"
LOCKED_HELPER = ROOT / "experiments/jev-information-density-v08p-r2/runner/r2_panel_target_join.py"
LOCKED_HELPER_SHA256 = "e7673ba4bdf0bbac924ffe863dfb7cd2f1aa60ac2dfe8d7e0919fda1e9b350eb"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError("refusing existing Q target-join output")
    if sha256_file(LOCKED_HELPER) != LOCKED_HELPER_SHA256:
        raise RuntimeError("hash-locked exact target-join helper changed")
    feature_receipt = json.loads((RUN_ROOT / "features/q-feature-extraction-receipt.json").read_text(encoding="utf-8"))
    match_receipt = json.loads((RUN_ROOT / "matching/q-matching-and-join-receipt.json").read_text(encoding="utf-8"))
    radius = json.loads((RUN_ROOT / "matching/radius-gate-report.json").read_text(encoding="utf-8"))
    if feature_receipt.get("status") != "Q_FROZEN_PANEL_FEATURE_EXTRACTION_PASS" or match_receipt.get("status") != "Q_MATCHING_AND_JOIN_PASS" or radius.get("status") != "PASS":
        raise RuntimeError("Q feature or radius-matching prerequisite is not PASS")
    panel_seal = json.loads((RUN_ROOT / "seals/q-panel-construction-seal-v01.json").read_text(encoding="utf-8"))
    seal_entries = {row["path"]: row for row in panel_seal["entries"]}
    for name in ("panel-feature-scope.jsonl", "panel-exact-world-episodes.jsonl", "panel-canonical-episodes.jsonl", "fresh-candidate-text-manifest.jsonl"):
        rel = f"panel/{name}"
        path = PANEL / name
        entry = seal_entries.get(rel)
        if entry is None or entry["bytes"] != path.stat().st_size or entry["sha256"] != sha256_file(path):
            raise RuntimeError(f"Q target join input is not bound by the construction seal: {name}")

    spec = importlib.util.spec_from_file_location("jev_q_locked_exact_target_join", LOCKED_HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load hash-locked exact target-join helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    scope = read_jsonl(PANEL / "panel-feature-scope.jsonl")
    exact = read_jsonl(PANEL / "panel-exact-world-episodes.jsonl")
    canonical = read_jsonl(PANEL / "panel-canonical-episodes.jsonl")
    candidate_rows = read_jsonl(PANEL / "fresh-candidate-text-manifest.jsonl")
    schema_orders: dict[str, list[str]] = {}
    for row in candidate_rows:
        schema_orders.setdefault(row["schema_family_id"], []).append(row["candidate_semantic_id"])
    schema_orders = {schema: [row["candidate_semantic_id"] for row in sorted((item for item in candidate_rows if item["schema_family_id"] == schema), key=lambda item: int(item["candidate_order"]))] for schema in schema_orders}
    result = module.attach_exact_world_targets(scope, exact, canonical, schema_orders)
    if result.get("status") != "EXACT_WORLD_TARGET_JOIN_PASS" or result.get("scope_rows") != 22_000 or result.get("neighborhoods") != 2_000 or result.get("fact_map_flip_count") != 2_000:
        raise RuntimeError("Q exact-world target join counts differ from frozen contract")

    OUTPUT.mkdir(parents=True, exist_ok=False)
    target_rows = [{"index": row["index"], "episode_id": row["episode_id"], "neighborhood_id": row["neighborhood_id"], "family_slug": row["family_slug"], "role": row["role"], "target": row["target"]} for row in scope]
    target_path = OUTPUT / "q-exact-world-targets.jsonl"
    write_jsonl(target_path, target_rows)
    receipt = {
        "status": "Q_EXACT_WORLD_TARGET_JOIN_PASS",
        "helper_sha256": LOCKED_HELPER_SHA256,
        "feature_receipt_sha256": sha256_file(RUN_ROOT / "features/q-feature-extraction-receipt.json"),
        "matching_receipt_sha256": sha256_file(RUN_ROOT / "matching/q-matching-and-join-receipt.json"),
        "scope_sha256": sha256_file(PANEL / "panel-feature-scope.jsonl"),
        "exact_world_sha256": sha256_file(PANEL / "panel-exact-world-episodes.jsonl"),
        "canonical_world_sha256": sha256_file(PANEL / "panel-canonical-episodes.jsonl"),
        "candidate_catalog_sha256": sha256_file(PANEL / "fresh-candidate-text-manifest.jsonl"),
        "target_rows_sha256": sha256_file(target_path),
        "target_rows": len(target_rows),
        "pretraining_evaluation_target_rows": 8_000,
        "join_summary": result,
        "head_loaded": False,
        "training": False,
        "heldout_inference": False,
        "outcome_analysis": False,
    }
    write_json(OUTPUT / "q-exact-world-target-join-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
