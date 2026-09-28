"""Independent replay of the Q-R1 exact-world target join; no model contact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
RECEIPT_OUT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-target-join-verification-v01.json")
HELPER = ROOT / "experiments/jev-information-density-v08p-r2/runner/r2_panel_target_join.py"
HELPER_SHA256 = "e7673ba4bdf0bbac924ffe863dfb7cd2f1aa60ac2dfe8d7e0919fda1e9b350eb"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main() -> int:
    if RECEIPT_OUT.exists():
        raise RuntimeError("refusing to overwrite the Q-R1 target-join verification receipt")
    if sha256_file(HELPER) != HELPER_SHA256:
        raise RuntimeError("hash-bound exact-world target helper changed")
    panel = RUN_ROOT / "panel"
    panel_seal = read_json(RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json")
    panel_entries = {row["path"]: row for row in panel_seal["entries"]}
    for name in (
        "panel-feature-scope.jsonl",
        "panel-exact-world-episodes.jsonl",
        "panel-canonical-episodes.jsonl",
        "fresh-candidate-text-manifest.jsonl",
    ):
        rel = f"panel/{name}"
        entry = panel_entries.get(rel)
        path = panel / name
        if entry is None or path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 target replay source is not bound by panel seal: {name}")

    scope = read_jsonl(panel / "panel-feature-scope.jsonl")
    exact = read_jsonl(panel / "panel-exact-world-episodes.jsonl")
    canonical = read_jsonl(panel / "panel-canonical-episodes.jsonl")
    candidates = read_jsonl(panel / "fresh-candidate-text-manifest.jsonl")
    schema_orders: dict[str, list[str]] = {}
    for row in candidates:
        slug = row["schema_family_id"].split(":")[-1]
        schema_orders.setdefault(slug, []).append(row["candidate_semantic_id"])
    schema_orders = {
        slug: [row["candidate_semantic_id"] for row in sorted(
            (item for item in candidates if item["schema_family_id"].split(":")[-1] == slug),
            key=lambda item: int(item["candidate_order"]),
        )]
        for slug in schema_orders
    }
    if len(schema_orders) != 4 or any(len(ids) != 4 or len(set(ids)) != 4 for ids in schema_orders.values()):
        raise RuntimeError("Q-R1 authoritative schema candidate order is incomplete")

    spec = importlib.util.spec_from_file_location("jev_q_r1_exact_target_helper", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the bound exact-world target helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    replay = helper.attach_exact_world_targets(scope, exact, canonical, schema_orders)
    if replay.get("status") != "EXACT_WORLD_TARGET_JOIN_PASS" or replay.get("scope_rows") != 22_000 or replay.get("neighborhoods") != 2_000 or replay.get("fact_map_flip_count") != 2_000:
        raise RuntimeError("Q-R1 independent target-join replay failed its structural counts")

    target_path = RUN_ROOT / "target-joins/r1-exact-world-targets.jsonl"
    target_receipt_path = RUN_ROOT / "target-joins/q-exact-world-target-join-receipt.json"
    receipt = read_json(target_receipt_path)
    observed = read_jsonl(target_path)
    expected = [
        {"index": row["index"], "episode_id": row["episode_id"], "neighborhood_id": row["neighborhood_id"], "family_slug": row["family_slug"], "role": row["role"], "target": row["target"]}
        for row in scope
    ]
    if len(observed) != 22_000 or observed != expected:
        raise RuntimeError("Q-R1 sealed target rows differ from independent exact-world replay")
    if receipt.get("status") != "Q_R1_EXACT_WORLD_TARGET_JOIN_PASS" or receipt.get("target_rows") != 22_000 or receipt.get("target_rows_sha256") != sha256_file(target_path):
        raise RuntimeError("Q-R1 target join receipt does not bind the verified rows")
    if receipt.get("helper_sha256") != HELPER_SHA256 or receipt.get("join_summary") != replay:
        raise RuntimeError("Q-R1 target join provenance/replay summary mismatch")

    result = {
        "status": "Q_R1_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS",
        "target_rows": len(observed),
        "neighborhoods": replay["neighborhoods"],
        "fact_map_flip_count": replay["fact_map_flip_count"],
        "target_rows_sha256": sha256_file(target_path),
        "target_join_receipt_sha256": sha256_file(target_receipt_path),
        "helper_sha256": HELPER_SHA256,
        "head_loaded": False,
        "training": False,
        "inference": False,
    }
    RECEIPT_OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
