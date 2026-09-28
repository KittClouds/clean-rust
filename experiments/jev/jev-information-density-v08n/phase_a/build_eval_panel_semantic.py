"""Build the feature-blind held-out v0.8N matched-neutral panel scope."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/eval-panel-v01-contract.json"
ROLES = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]
EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def target(row: dict[str, Any]) -> list[float]:
    return [float(item["probability"]) for item in row["gold_targets"][0]["value"]["probabilities"]]


def max_abs(left: list[float], right: list[float]) -> float:
    return max(abs(a - b) for a, b in zip(left, right))


def map_index(values: list[float]) -> int:
    return max(range(len(values)), key=lambda index: (values[index], -index))


def surface_text(row: dict[str, Any]) -> str:
    return row["renderings"][0]["text"]


def changed_character_count(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def semantic_equal(anchor: dict[str, Any], sibling: dict[str, Any]) -> bool:
    if anchor["sampled_world"] != sibling["sampled_world"]:
        return False
    if anchor["template"] != sibling["template"]:
        return False
    if anchor["queries"] != sibling["queries"]:
        return False
    anchor_state = anchor["evidence_state"]
    sibling_state = sibling["evidence_state"]
    if anchor_state["visible_fact_ids"] != sibling_state["visible_fact_ids"]:
        return False
    if anchor_state["missing_fact_ids"] != sibling_state["missing_fact_ids"]:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    certificates_path = args.source_run / "eval-contrast-certificates.jsonl"
    episodes_path = args.source_run / "eval-exact-world-episodes.jsonl"
    certificates = read_jsonl(certificates_path)
    episodes = read_jsonl(episodes_path)
    if len(certificates) != 2_000 or len(episodes) != 22_000:
        raise RuntimeError("held-out source capacity drift")
    by_id = {row["episode_id"]: row for row in episodes}
    if len(by_id) != len(episodes):
        raise RuntimeError("duplicate held-out episode id")

    neighborhoods: list[dict[str, Any]] = []
    scope: list[dict[str, Any]] = []
    families: set[str] = set()
    for certificate in certificates:
        if certificate.get("partition") != "eval":
            raise RuntimeError(f"non-held-out certificate: {certificate['anchor_id']}")
        if certificate.get("neutral_candidate_count") != 8:
            raise RuntimeError("neutral candidate count drift")
        if not certificate["nuisance_axes"]["independent"] or not certificate["nuisance_axes"]["pairwise_distinct"]:
            raise RuntimeError("nuisance-axis independence certificate failure")
        if certificate["nuisance_axes"]["sham"] in certificate["nuisance_axes"]["neutral"]:
            raise RuntimeError("sham axis overlaps neutral axis")
        anchor_id = certificate["anchor_id"]
        episode_ids = certificate["episode_ids"]
        ids = [episode_ids["anchor"], episode_ids["fact_flip"], episode_ids["sham"], *episode_ids["neutrals"]]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"duplicate episode in neighborhood: {anchor_id}")
        rows = [by_id.get(episode_id) for episode_id in ids]
        if any(row is None for row in rows):
            raise RuntimeError(f"missing held-out episode: {anchor_id}")
        rows = [row for row in rows if row is not None]
        anchor, fact, sham, *neutrals = rows
        if len(neutrals) != 8 or any(not semantic_equal(anchor, sibling) for sibling in [fact, sham, *neutrals]):
            raise RuntimeError(f"schema/world mismatch: {anchor_id}")
        anchor_target = target(anchor)
        sham_target = target(sham)
        neutral_targets = [target(row) for row in neutrals]
        if max_abs(anchor_target, sham_target) > EPS or any(max_abs(anchor_target, value) > EPS for value in neutral_targets):
            raise RuntimeError(f"exact invariance failure: {anchor_id}")
        fact_target = target(fact)
        if map_index(anchor_target) == map_index(fact_target):
            raise RuntimeError(f"fact MAP winner did not change: {anchor_id}")
        all_texts = [surface_text(row) for row in rows]
        if len({len(text) for text in all_texts}) != 1:
            raise RuntimeError(f"surface length drift: {anchor_id}")
        if changed_character_count(all_texts[0], all_texts[2]) != 1 or any(changed_character_count(all_texts[0], text) != 1 for text in all_texts[3:]):
            raise RuntimeError(f"surface edit magnitude drift: {anchor_id}")
        if not certificate["edit_magnitude"]["sham_neutral_magnitude_equal"]:
            raise RuntimeError(f"certificate edit gate failure: {anchor_id}")
        family = certificate["world_family_id"]
        families.add(family)
        neighborhoods.append({
            "anchor_id": anchor_id,
            "family_id": family,
            "schema_family_id": certificate["schema_family_id"],
            "template_id": anchor["template"]["template_id"],
            "certificate_hash": certificate["certificate_hash"],
            "episode_ids": episode_ids,
            "sham_axis": certificate["sham_axis"],
            "neutral_axes": certificate["neutral_axes"],
            "target_hash": hashlib.sha256(json.dumps(anchor_target, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "target": anchor_target,
        })
        for role, row in zip(ROLES, rows):
            text = surface_text(row)
            scope.append({
                "index": len(scope),
                "neighborhood_id": anchor_id,
                "family_id": family,
                "template_id": anchor["template"]["template_id"],
                "role": role,
                "episode_id": row["episode_id"],
                "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
                "target": target(row),
                "partition": "eval",
            })

    if len(neighborhoods) != 2_000 or len(families) != 4 or len(scope) != 22_000:
        raise RuntimeError("held-out panel count/family drift")
    if len({row["anchor_id"] for row in neighborhoods}) != 2_000:
        raise RuntimeError("duplicate held-out neighborhood")

    args.output.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.output / "heldout-neighborhoods.jsonl", neighborhoods)
    write_jsonl(args.output / "heldout-feature-scope.jsonl", scope)
    receipt = {
        "status": "V08N_HELDOUT_PANEL_SEMANTIC_SCOPE_PASS",
        "identity": "v0.8N-eval-panel-v01",
        "contract_sha256": sha256_file(CONTRACT),
        "source_run": str(args.source_run),
        "source_certificates_sha256": sha256_file(certificates_path),
        "source_episodes_sha256": sha256_file(episodes_path),
        "certificate_count": len(certificates),
        "neighborhood_count": len(neighborhoods),
        "episode_count": len(scope),
        "family_count": len(families),
        "families": sorted(families),
        "feature_selection_used": False,
        "evaluation_outcomes_used": False,
        "head_contact": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "phoenix_access": False,
        "outputs": {
            "neighborhoods": {"path": str(args.output / "heldout-neighborhoods.jsonl"), "sha256": sha256_file(args.output / "heldout-neighborhoods.jsonl")},
            "feature_scope": {"path": str(args.output / "heldout-feature-scope.jsonl"), "sha256": sha256_file(args.output / "heldout-feature-scope.jsonl")},
        },
    }
    write_json(args.output / "semantic-scope-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
