"""Independent replay of Q-R1 radius-only matching and semantic-ID joins."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
DEFAULT_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-radius-verification-v01.json")
ROLE_ORDER = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def tie_hash(anchor_id: str, role: str) -> str:
    return sha256_bytes(f"{anchor_id}|{role}".encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    if args.receipt.exists():
        raise RuntimeError("refusing to overwrite the independent Q-R1 radius verification receipt")
    features = RUN_ROOT / "features"
    panel = RUN_ROOT / "panel"
    matching = RUN_ROOT / "matching"
    panel_seal = read_json(RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json")
    panel_entries = {row["path"]: row for row in panel_seal["entries"]}
    scope_entry = panel_entries["panel/panel-feature-scope.jsonl"]
    if sha256_file(panel / "panel-feature-scope.jsonl") != scope_entry["sha256"]:
        raise RuntimeError("Q-R1 radius replay scope differs from construction seal")
    feature_seal = read_json(RUN_ROOT / "seals/q-r1-feature-cache-seal-v01.json")
    feature_payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(feature_seal["entries"], key=lambda row: row["path"]))
    if hashlib.sha256(feature_payload.encode("utf-8")).hexdigest() != feature_seal.get("root_sha256"):
        raise RuntimeError("Q-R1 radius replay feature seal root mismatch")
    for entry in feature_seal["entries"]:
        path = RUN_ROOT / entry["path"]
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 radius replay feature seal mismatch: {entry['path']}")
    tensor_blob = torch.load(features / "r1-state-features.pt", map_location="cpu", weights_only=True)
    matrix = tensor_blob["features"].to(dtype=torch.float64)
    scope = read_jsonl(panel / "panel-feature-scope.jsonl")
    selected = read_jsonl(matching / "matched-neutral-selection.jsonl")
    report = read_json(matching / "radius-gate-report.json")
    match_receipt = read_json(matching / "r1-matching-and-join-receipt.json")
    if tuple(matrix.shape) != (22_000, 2_048) or len(scope) != 22_000 or len(selected) != 2_000:
        raise RuntimeError("Q-R1 radius replay input cardinality/dimension mismatch")
    if tensor_blob.get("scope_sha256") != sha256_file(panel / "panel-feature-scope.jsonl"):
        raise RuntimeError("Q-R1 radius replay tensor/scope binding mismatch")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scope:
        groups[row["neighborhood_id"]].append(row)
    if len(groups) != 2_000:
        raise RuntimeError("Q-R1 radius replay neighborhood count mismatch")
    selection_by_id = {row["neighborhood_id"]: row for row in selected}
    if len(selection_by_id) != len(selected) or set(selection_by_id) != set(groups):
        raise RuntimeError("Q-R1 selected neutral set does not cover exact panel neighborhoods")

    abs_errors: list[float] = []
    rel_errors: list[float] = []
    by_family: dict[str, list[float]] = defaultdict(list)
    for anchor_id, rows in groups.items():
        if len(rows) != 11:
            raise RuntimeError(f"Q-R1 radius replay neighborhood role count mismatch: {anchor_id}")
        rows.sort(key=lambda row: int(row["index"]))
        if [row["role"] for row in rows] != ROLE_ORDER:
            raise RuntimeError(f"Q-R1 radius replay role order mismatch: {anchor_id}")
        values = matrix[[int(row["index"]) for row in rows]]
        sham_radius = float(torch.linalg.vector_norm(values[2] - values[0]))
        neutral_radii = torch.linalg.vector_norm(values[3:] - values[0], dim=1).tolist()
        options = [(abs(radius - sham_radius), tie_hash(anchor_id, f"neutral_{i}"), i, radius) for i, radius in enumerate(neutral_radii, start=1)]
        error, _, neutral_index, neutral_radius = min(options, key=lambda item: (item[0], item[1]))
        row = selection_by_id[anchor_id]
        expected_rel = error / max(sham_radius, torch.finfo(torch.float64).tiny)
        if row["matched_neutral_role"] != f"neutral_{neutral_index}" or row["anchor_episode_id"] != rows[0]["episode_id"] or row["sham_episode_id"] != rows[2]["episode_id"] or row["matched_neutral_episode_id"] != rows[2 + neutral_index]["episode_id"]:
            raise RuntimeError(f"Q-R1 radius selected identity mismatch: {anchor_id}")
        if row["sham_radius"] != sham_radius or row["matched_neutral_radius"] != neutral_radius or row["absolute_radius_error"] != error or row["relative_radius_error"] != expected_rel:
            raise RuntimeError(f"Q-R1 radius numerical replay mismatch: {anchor_id}")
        abs_errors.append(error)
        rel_errors.append(expected_rel)
        by_family[rows[0]["family_slug"]].append(expected_rel)

    mean_relative = sum(rel_errors) / len(rel_errors)
    p95_absolute = float(torch.quantile(torch.tensor(abs_errors, dtype=torch.float64), torch.tensor(0.95, dtype=torch.float64)))
    family_mean = {family: sum(values) / len(values) for family, values in sorted(by_family.items())}
    gates = report["gates"]
    decisions = {
        "mean_relative_pass": mean_relative <= float(gates["mean_relative_error_max"]),
        "p95_absolute_pass": p95_absolute <= float(gates["p95_absolute_error_max"]),
        "family_pass": len(family_mean) == 4 and all(value <= float(gates["per_family_mean_relative_error_max"]) for value in family_mean.values()),
    }
    decisions["all_pass"] = all(decisions.values())
    if report.get("status") != "PASS" or not decisions["all_pass"]:
        raise RuntimeError("Q-R1 independent radius replay failed the sealed gate")
    for key, value in (("mean_relative_radius_error", mean_relative), ("p95_absolute_radius_error", p95_absolute)):
        if report["results"].get(key) != value:
            raise RuntimeError(f"Q-R1 radius summary differs for {key}")
    if report["results"].get("family_mean_relative_radius_error") != family_mean:
        raise RuntimeError("Q-R1 per-family radius summaries differ")

    candidate_texts = read_jsonl(panel / "fresh-candidate-text-manifest.jsonl")
    candidate_manifest = read_jsonl(features / "r1-candidate-feature-manifest.jsonl")
    joins = read_jsonl(matching / "whole-panel-candidate-join.jsonl")
    if len(candidate_texts) != 16 or len(candidate_manifest) != 16 or len(joins) != 8_000:
        raise RuntimeError("Q-R1 target-free candidate join cardinality mismatch")
    feature_by_key = {(row["schema_family_id"], row["candidate_semantic_id"]): row for row in candidate_manifest}
    expected_join_pairs = set()
    for neighborhood_id, rows in groups.items():
        schema = f"jev-v08n-schema:{rows[0]['family_slug']}"
        expected_join_pairs.update((neighborhood_id, row["candidate_semantic_id"]) for row in candidate_texts if row["schema_family_id"] == schema)
    observed_join_keys = {(row["neighborhood_id"], row["candidate_semantic_id"]) for row in joins}
    if len(observed_join_keys) != 8_000 or observed_join_keys != expected_join_pairs:
        raise RuntimeError("Q-R1 candidate join differs from exact family-by-candidate cross product")
    for row in joins:
        feature = feature_by_key.get((row["schema_family_id"], row["candidate_semantic_id"]))
        text = next((item for item in candidate_texts if item["schema_family_id"] == row["schema_family_id"] and item["candidate_semantic_id"] == row["candidate_semantic_id"]), None)
        if feature is None or text is None or row["feature_sha256"] != feature["feature_sha256"] or int(row["feature_index_storage_only"]) != int(feature["index"]) or row["candidate_text_sha256"] != text["text_sha256"] or int(row["candidate_order"]) != int(text["candidate_order"]):
            raise RuntimeError("Q-R1 candidate join points at the wrong feature row")
    if match_receipt.get("status") != "Q_R1_MATCHING_AND_JOIN_PASS" or match_receipt.get("selection_rows") != 2_000 or match_receipt.get("join_rows") != 8_000:
        raise RuntimeError("Q-R1 matching receipt summary mismatch")

    result = {
        "status": "Q_R1_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS",
        "matching_script_sha256": sha256_file(Path(__file__).resolve().parent / "match_q_r1_panel_radius_v01.py"),
        "matching_receipt_sha256": sha256_file(matching / "r1-matching-and-join-receipt.json"),
        "radius_gate_report_sha256": sha256_file(matching / "radius-gate-report.json"),
        "matched_neutral_rows": len(selected),
        "candidate_join_rows": len(joins),
        "mean_relative_radius_error": mean_relative,
        "p95_absolute_radius_error": p95_absolute,
        "family_mean_relative_radius_error": family_mean,
        "decisions": decisions,
        "outcomes_or_targets_read": False,
        "training": False,
        "inference": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
