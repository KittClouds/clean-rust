"""Materialize feature-blind P panel manifests from exact-world generator output."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
P_ROOT = ROOT / "experiments/jev-information-density-v08p"
CONTRACT_PATH = P_ROOT / "phase_a/fresh-panel-contract-v01.json"
AUTH_PATH = P_ROOT / "phase_a/phase-a-authorization-receipt-v01.json"
BUNDLE_PATH = P_ROOT / "contracts/contract-bundle-seal-v01.json"
ROLES = ("anchor", "fact_flip", "sham", *(f"neutral_{i}" for i in range(1, 9)))
EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def distribution(row: dict[str, Any]) -> list[float]:
    entries = row["gold_targets"][0]["target"]["distribution"]
    return [float(item["probability"]) for item in entries]


def candidate_ids(row: dict[str, Any]) -> list[str]:
    return [str(item["candidate_semantic_id"]) for item in row["runtime_schema"]["candidates"]]


def argmax(values: list[float]) -> int:
    return max(range(len(values)), key=lambda index: (values[index], -index))


def changed_chars(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def verify_authorization(contract: dict[str, Any], authorization: dict[str, Any], bundle: dict[str, Any]) -> None:
    if authorization.get("authorization") != "AUTHORIZED_BY_USER":
        raise RuntimeError("Phase-A user authorization receipt is absent")
    if authorization["bindings"]["fresh_panel_contract_sha256"] != sha256_file(CONTRACT_PATH):
        raise RuntimeError("fresh-panel contract hash differs from authorization")
    if authorization["bindings"]["contract_bundle_seal_sha256"] != sha256_file(BUNDLE_PATH):
        raise RuntimeError("contract bundle hash differs from authorization")
    if contract["identity"] != "v0.8P-fresh-eval-panel-v01" or bundle["identity"] != authorization["bindings"]["contract_bundle_identity"]:
        raise RuntimeError("P identity binding mismatch")
    if bundle["state"]["training_authorized"] or bundle["state"]["evaluation_authorized"]:
        raise RuntimeError("P training/evaluation must remain unauthorized")


def main(panel_root: Path) -> None:
    contract = read_json(CONTRACT_PATH)
    authorization = read_json(AUTH_PATH)
    bundle = read_json(BUNDLE_PATH)
    verify_authorization(contract, authorization, bundle)
    solver_receipt_path = panel_root / "exact-world-validation.json"
    solver_receipt = read_json(solver_receipt_path)
    if solver_receipt.get("status") != "V08P_EXACT_WORLD_PANEL_VALIDATION_PASS":
        raise RuntimeError("independent exact-world validator has not passed")
    if solver_receipt.get("neighborhood_count") != 2_000 or solver_receipt.get("episode_count") != 22_000:
        raise RuntimeError("exact-world validator count mismatch")

    certificate_path = panel_root / "eval-contrast-certificates.jsonl"
    canonical_path = panel_root / "eval-canonical-episodes.jsonl"
    certificates = read_jsonl(certificate_path)
    episodes = read_jsonl(canonical_path)
    if len(certificates) != 2_000 or len(episodes) != 22_000:
        raise RuntimeError("P generated input count mismatch")
    by_id = {str(row["episode_id"]): row for row in episodes}
    if len(by_id) != len(episodes):
        raise RuntimeError("duplicate P canonical episode identity")

    family_basis = {row["slug"]: row["neighborhoods"] for row in contract["freshness_and_scope"]["family_basis"]}
    family_counts: Counter[str] = Counter()
    neighborhood_manifest: list[dict[str, Any]] = []
    scope: list[dict[str, Any]] = []
    candidates_by_schema: dict[str, list[dict[str, Any]]] = {}
    seen_episode_ids: set[str] = set()
    for cert in certificates:
        if cert.get("partition") != "eval_v08p":
            raise RuntimeError(f"wrong P partition: {cert.get('anchor_id')}")
        if cert.get("neutral_candidate_count") != 8 or not cert["nuisance_axes"]["independent"] or not cert["nuisance_axes"]["pairwise_distinct"]:
            raise RuntimeError(f"neutral-axis certificate failure: {cert.get('anchor_id')}")
        if cert["nuisance_axes"]["sham"] in cert["nuisance_axes"]["neutral"]:
            raise RuntimeError(f"sham axis collides with neutral axis: {cert['anchor_id']}")
        ids_by_role = cert["episode_ids"]
        ids = [ids_by_role["anchor"], ids_by_role["fact_flip"], ids_by_role["sham"], *ids_by_role["neutrals"]]
        if len(ids) != 11 or len(set(ids)) != 11 or any(item in seen_episode_ids for item in ids):
            raise RuntimeError(f"duplicate or malformed episode IDs: {cert['anchor_id']}")
        rows = [by_id.get(str(episode_id)) for episode_id in ids]
        if any(row is None for row in rows):
            raise RuntimeError(f"missing P canonical episode: {cert['anchor_id']}")
        rows = [row for row in rows if row is not None]
        anchor, fact, sham, *neutrals = rows
        if len(neutrals) != 8:
            raise RuntimeError("P neutral count drift")
        schema = str(cert["schema_family_id"])
        family = schema.split(":")[-1]
        if family not in family_basis:
            raise RuntimeError(f"non-held-out family in P panel: {family}")
        family_counts[family] += 1

        anchor_ids = candidate_ids(anchor)
        if len(anchor_ids) != 4 or len(set(anchor_ids)) != 4:
            raise RuntimeError(f"candidate identity/order invalid: {cert['anchor_id']}")
        for row in rows:
            if row["identity"]["schema_family_id"] != schema or candidate_ids(row) != anchor_ids:
                raise RuntimeError(f"schema/candidate order mismatch: {cert['anchor_id']}")
            if row["queries"] != anchor["queries"]:
                raise RuntimeError(f"query semantics changed within neighborhood: {cert['anchor_id']}")
            if row["identity"]["world_instance_id"] != anchor["identity"]["world_instance_id"]:
                raise RuntimeError(f"world identity changed within neighborhood: {cert['anchor_id']}")
        anchor_target = distribution(anchor)
        fact_target = distribution(fact)
        sham_target = distribution(sham)
        neutral_targets = [distribution(row) for row in neutrals]
        if any(len(target) != 4 or abs(sum(target) - 1.0) > EPS for target in [anchor_target, fact_target, sham_target, *neutral_targets]):
            raise RuntimeError(f"target shape/normalization failure: {cert['anchor_id']}")
        if max(abs(a - b) for a, b in zip(anchor_target, sham_target)) > EPS:
            raise RuntimeError(f"sham target changed: {cert['anchor_id']}")
        if any(max(abs(a - b) for a, b in zip(anchor_target, target)) > EPS for target in neutral_targets):
            raise RuntimeError(f"neutral target changed: {cert['anchor_id']}")
        if argmax(anchor_target) == argmax(fact_target):
            raise RuntimeError(f"fact target MAP did not flip: {cert['anchor_id']}")
        surfaces = [str(row["state"]["observable"]["content"]) for row in rows]
        for index, sibling in enumerate(surfaces[1:], start=1):
            if changed_chars(surfaces[0], sibling) != 1:
                raise RuntimeError(f"surface edit is not one character: {cert['anchor_id']}/{ROLES[index]}")
            before_lines, after_lines = surfaces[0].splitlines(), sibling.splitlines()
            if len(before_lines) != len(after_lines) or sum(a != b for a, b in zip(before_lines, after_lines)) != 1:
                raise RuntimeError(f"surface edit spans multiple fields: {cert['anchor_id']}/{ROLES[index]}")

        if schema not in candidates_by_schema:
            entries = []
            for order_index, candidate in enumerate(anchor["runtime_schema"]["candidates"]):
                name = str(candidate["surface"]["name"])
                description = str(candidate["surface"]["description"])
                text = f"{name} — {description}"
                entries.append({
                    "schema_family_id": schema,
                    "candidate_semantic_id": str(candidate["candidate_semantic_id"]),
                    "candidate_order_index": order_index,
                    "name": name,
                    "description": description,
                    "input_text": text,
                    "input_text_sha256": sha256_text(text),
                    "candidate_id": str(candidate["candidate_id"]),
                })
            candidates_by_schema[schema] = entries
        elif [item["candidate_semantic_id"] for item in candidates_by_schema[schema]] != anchor_ids:
            raise RuntimeError(f"schema candidate catalog is not stable: {schema}")

        episode_id_map = dict(zip(ROLES, ids))
        template_id = f"jev_v08n_{family}_p{int(cert['profile_index'])}"
        neighborhood_manifest.append({
            "neighborhood_id": str(cert["anchor_id"]),
            "family_id": family,
            "schema_family_id": schema,
            "template_id": template_id,
            "world_instance_id": str(anchor["identity"]["world_instance_id"]),
            "certificate_hash": str(cert["certificate_hash"]),
            "episode_ids": episode_id_map,
        })
        for role, row, episode_id in zip(ROLES, rows, ids):
            target = distribution(row)
            target_by_id = {str(entry["candidate_semantic_id"]): float(entry["probability"]) for entry in row["gold_targets"][0]["target"]["distribution"]}
            if list(target_by_id) != anchor_ids:
                raise RuntimeError(f"gold target candidate order differs from schema: {episode_id}")
            text = str(row["state"]["observable"]["content"])
            scope.append({
                "index": len(scope),
                "neighborhood_id": str(cert["anchor_id"]),
                "family_id": family,
                "schema_family_id": schema,
                "template_id": template_id,
                "role": role,
                "episode_id": str(episode_id),
                "input_sha256": sha256_text(text),
                "text": text,
                "target": target,
                "target_sha256": sha256_text(json.dumps(target, separators=(",", ":"))),
                "candidate_semantic_ids": anchor_ids,
                "partition": "eval_v08p",
            })
            seen_episode_ids.add(str(episode_id))

    if dict(family_counts) != family_basis:
        raise RuntimeError(f"P family allocation mismatch: {dict(family_counts)}")
    if len(neighborhood_manifest) != 2_000 or len(scope) != 22_000 or len(seen_episode_ids) != 22_000:
        raise RuntimeError("P manifest totals drift")
    candidate_manifest = [row for schema in sorted(candidates_by_schema) for row in candidates_by_schema[schema]]
    if len(candidate_manifest) != 16 or len({row["candidate_semantic_id"] for row in candidate_manifest}) != 16:
        raise RuntimeError("P candidate semantic basis must contain exactly 16 unique entries")

    write_jsonl(panel_root / "heldout-neighborhoods.jsonl", neighborhood_manifest)
    write_jsonl(panel_root / "heldout-feature-scope.jsonl", scope)
    write_jsonl(panel_root / "fresh-candidate-text-manifest.jsonl", candidate_manifest)
    receipt = {
        "status": "V08P_SEMANTIC_PANEL_VALIDATION_PASS",
        "identity": contract["identity"],
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "authorization_receipt_sha256": sha256_file(AUTH_PATH),
        "generator_receipt_sha256": sha256_file(panel_root / "generator-receipt.json"),
        "exact_world_validation_sha256": sha256_file(solver_receipt_path),
        "neighborhood_count": len(neighborhood_manifest),
        "episode_count": len(scope),
        "family_counts": dict(sorted(family_counts.items())),
        "candidate_text_count": len(candidate_manifest),
        "candidate_text_recipe": "exact name-definition surface `name — description` from authoritative frozen FamilySpec candidates",
        "validation": {
            "exact_world_solver_validated": True,
            "same_world_query_schema_and_candidate_order": True,
            "sham_and_neutral_targets_equal_anchor_within_1e-12": True,
            "fact_flip_changes_exact_map_winner": True,
            "single_character_single_field_edits": True,
            "candidate_semantic_ids_unique": True,
        },
        "E1_or_prior_panel_bodies_read": False,
        "head_load": False,
        "head_training": False,
        "evaluation_inference": False,
        "behavioral_metrics": False,
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
    }
    write_json(panel_root / "semantic-validation-receipt.json", receipt)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-root", type=Path, required=True)
    arguments = parser.parse_args()
    main(arguments.panel_root)
