"""Bind target-free feature-scope rows to authoritative exact-world targets."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _index_unique(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        episode_id = str(row["episode_id"])
        if episode_id in result:
            raise ValueError(f"duplicate {label} episode_id: {episode_id}")
        result[episode_id] = row
    return result


def index_scope_rows(
    scope_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    """Return both exact episode lookup and role lookup, without conflating them."""
    by_episode: dict[str, dict[str, dict[str, Any]]] = {}
    by_role: dict[str, dict[str, dict[str, Any]]] = {}
    for row in scope_rows:
        neighborhood_id = str(row["neighborhood_id"])
        episode_id = str(row["episode_id"])
        role = str(row["role"])
        episode_bucket = by_episode.setdefault(neighborhood_id, {})
        role_bucket = by_role.setdefault(neighborhood_id, {})
        if episode_id in episode_bucket:
            raise ValueError(f"duplicate episode in neighborhood scope: {neighborhood_id}/{episode_id}")
        if role in role_bucket:
            raise ValueError(f"duplicate role in neighborhood scope: {neighborhood_id}/{role}")
        episode_bucket[episode_id] = row
        role_bucket[role] = row
    return by_episode, by_role


def attach_exact_world_targets(
    scope_rows: list[dict[str, Any]],
    exact_rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
    schema_orders: dict[str, list[str]],
) -> dict[str, Any]:
    """Attach posterior vectors through exact episode IDs and verify their semantics.

    `scope_rows` remains the model-input manifest. Gold targets come only from the
    separately sealed exact-world episode artifact; candidate IDs are checked
    against the canonical schema and the frozen candidate-semantic order.
    """
    scope = _index_unique(scope_rows, "scope")
    exact = _index_unique(exact_rows, "exact-world")
    canonical = _index_unique(canonical_rows, "canonical")
    if not (set(scope) == set(exact) == set(canonical)):
        raise ValueError("scope/exact/canonical episode_id sets are not an exact bijection")

    targets: dict[str, list[float]] = {}
    for episode_id, episode in exact.items():
        canonical_row = canonical[episode_id]
        scope_row = scope[episode_id]
        runtime_schema = canonical_row["runtime_schema"]
        slug = str(scope_row["family_slug"])
        schema_slug = str(runtime_schema["schema_family_id"]).split(":")[-1]
        if schema_slug != slug or slug not in schema_orders:
            raise ValueError(f"episode/schema family mismatch: {episode_id}")

        candidates = runtime_schema["candidates"]
        candidate_ids = [str(row["candidate_id"]) for row in candidates]
        semantic_ids = [str(row["candidate_semantic_id"]) for row in candidates]
        if candidate_ids != [f"candidate-{index}" for index in range(4)]:
            raise ValueError(f"canonical candidate identity/order mismatch: {episode_id}")
        if semantic_ids != schema_orders[slug]:
            raise ValueError(f"canonical/candidate-catalog order mismatch: {episode_id}")

        gold_targets = episode["gold_targets"]
        if len(gold_targets) != 1:
            raise ValueError(f"expected one gold target: {episode_id}")
        value = gold_targets[0]["value"]
        probabilities = value["probabilities"]
        if value.get("semantic_type") != "choice" or len(probabilities) != 4:
            raise ValueError(f"invalid choice posterior shape/type: {episode_id}")
        candidate_ordinals = [int(row["value"]) for row in probabilities]
        if candidate_ordinals != [0, 1, 2, 3]:
            raise ValueError(f"gold target candidate order mismatch: {episode_id}")
        posterior = [float(row["probability"]) for row in probabilities]
        if (not all(math.isfinite(item) and item >= 0.0 for item in posterior)
                or abs(sum(posterior) - 1.0) > 1e-12):
            raise ValueError(f"invalid exact-world posterior: {episode_id}")
        targets[episode_id] = posterior

    for row in scope_rows:
        row["target"] = targets[str(row["episode_id"])]

    by_neighborhood: dict[str, dict[str, list[float]]] = {}
    for row in scope_rows:
        roles = by_neighborhood.setdefault(str(row["neighborhood_id"]), {})
        role = str(row["role"])
        if role in roles:
            raise ValueError(f"duplicate role within neighborhood: {row['neighborhood_id']}/{role}")
        roles[role] = targets[str(row["episode_id"])]
    expected_roles = {"anchor", "fact_flip", "sham", *(f"neutral_{i}" for i in range(1, 9))}
    for neighborhood_id, roles in by_neighborhood.items():
        if set(roles) != expected_roles:
            raise ValueError(f"incomplete target neighborhood: {neighborhood_id}")
        anchor = roles["anchor"]
        old_winner = max(range(4), key=lambda index: (anchor[index], -index))
        fact_winner = max(range(4), key=lambda index: (roles["fact_flip"][index], -index))
        if old_winner == fact_winner:
            raise ValueError(f"fact target does not change MAP: {neighborhood_id}")
        for role, posterior in roles.items():
            if role != "fact_flip" and max(abs(a - b) for a, b in zip(anchor, posterior, strict=True)) > 1e-12:
                raise ValueError(f"invariant target changed: {neighborhood_id}/{role}")

    target_payload = [[episode_id, targets[episode_id]] for episode_id in sorted(targets)]
    target_sha256 = hashlib.sha256(
        json.dumps(target_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "EXACT_WORLD_TARGET_JOIN_PASS",
        "join_key": "episode_id",
        "scope_rows": len(scope_rows),
        "exact_world_rows": len(exact_rows),
        "canonical_rows": len(canonical_rows),
        "unique_episode_ids": len(targets),
        "neighborhoods": len(by_neighborhood),
        "candidate_schema_count": len(schema_orders),
        "invariant_target_role_count": len(scope_rows) - len(by_neighborhood),
        "fact_map_flip_count": len(by_neighborhood),
        "target_vectors_sha256": target_sha256,
    }
