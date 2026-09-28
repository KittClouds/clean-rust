"""Pure-Python projection of the frozen v0.5 trainer's decision groups.

This module intentionally imports no ML runtime.  It computes hashes of exact
adapter text/loss inputs for metadata-only audits; it never writes those texts.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections import Counter, defaultdict
from typing import Any, Iterable


CALIBRATION_SOURCES = frozenset(
    {
        "exact_generative_posterior",
        "empirical_annotator_distribution",
        "elicited_subjective_probability",
        "adjudicated_distribution",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def f32_bits(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite target cannot be represented as a training signature")
    return struct.pack("<f", number).hex()


def state_query_text(episode: dict[str, Any], query: dict[str, Any]) -> str:
    content = episode.get("state", {}).get("observable", {}).get("content") or ""
    view = query.get("view", "choice")
    semantic_id = query.get("query_semantic_id", "runtime_query")
    return (
        f"State:\n{content}\n"
        f"Decision view: {view}\n"
        f"Runtime query: {semantic_id}\n"
        "Compare this state with each supplied candidate definition."
    )


def candidate_surface(candidate: dict[str, Any], profile: str = "name_definition") -> str:
    name = candidate.get("name") or candidate["candidate_semantic_id"]
    description = candidate.get("description") or name
    if profile != "name_definition":
        raise ValueError(f"unsupported frozen signature profile: {profile}")
    return f"{name} — {description}"


def query_candidates(episode: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_by_id = {
        item["candidate_id"]: item
        for item in episode["runtime_schema"]["candidates"]
    }
    candidate_sets = {
        item["candidate_set_id"]: item
        for item in episode["runtime_schema"].get("candidate_sets", [])
    }
    candidate_set = candidate_sets.get(query.get("candidate_set_id"), {})
    return [
        candidate_by_id[candidate_id]
        for candidate_id in candidate_set.get("candidate_ids", [])
        if candidate_id in candidate_by_id
    ]


def query_target(episode: dict[str, Any], query_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in episode.get("gold_targets", [])
            if item["query_id"] == query_id
        ),
        None,
    )


def group_records(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Mirror probe.group_records for the supported choice/applicability views."""
    result: list[dict[str, Any]] = []
    perturbation = episode.get("perturbation") or {}
    parent = perturbation.get("parent_episode_id")
    invariant_base = parent or episode["identity"]["episode_id"]

    for query in episode.get("queries", []):
        view = query.get("view")
        if view in {"abstain", "span_type", "relation"}:
            continue
        target = query_target(episode, query.get("query_id", ""))
        if not target:
            continue
        body = target.get("target") or {}
        target_kind = body.get("target_kind")
        candidates = query_candidates(episode, query)
        by_semantic = {item["candidate_semantic_id"]: item for item in candidates}
        query_id = query["query_id"]
        source = target.get("probability_source", {}).get("probability_source", "unknown")
        state_text = state_query_text(episode, query)

        if target_kind in {"choice", "ordinal", "hard_label_only"}:
            distribution = body.get("distribution") or []
            if target_kind == "hard_label_only":
                selected = body.get("selected_candidate_semantic_id")
                gold = {
                    candidate["candidate_semantic_id"]: float(
                        candidate["candidate_semantic_id"] == selected
                    )
                    for candidate in candidates
                }
            elif target_kind == "ordinal":
                gold = {
                    candidate["candidate_semantic_id"]: float(probability)
                    for candidate, probability in zip(candidates, distribution)
                }
            elif distribution:
                gold = {
                    item["candidate_semantic_id"]: float(item["probability"])
                    for item in distribution
                    if item["candidate_semantic_id"] in by_semantic
                }
            else:
                selected = body.get("selected_candidate_semantic_id")
                gold = {
                    candidate["candidate_semantic_id"]: float(
                        candidate["candidate_semantic_id"] == selected
                    )
                    for candidate in candidates
                }

            other_probability = float(body.get("other_probability") or 0.0)
            if not gold or len(gold) != len(candidates):
                continue
            ordered_surfaces = [candidate_surface(item) for item in candidates]
            ordered_gold = [gold[item["candidate_semantic_id"]] for item in candidates]
            result.append(
                {
                    "group_id": f"{episode['identity']['episode_id']}|{query_id}",
                    "episode_id": episode["identity"]["episode_id"],
                    "query_id": query_id,
                    "kind": "choice",
                    "view": view,
                    "state_text": state_text,
                    "candidate_surfaces": ordered_surfaces,
                    "gold": ordered_gold,
                    "open_world": other_probability > 1e-12,
                    "probability_source": source,
                    "authority": episode.get("authority", {}).get("episode_authority_class", "unknown"),
                    "invariant_key": f"{invariant_base}|{query_id}",
                    "perturbation_class": perturbation.get("class"),
                }
            )

        elif target_kind == "independent_applicability":
            for item in body.get("candidates") or []:
                semantic_id = item["candidate_semantic_id"]
                candidate = by_semantic.get(semantic_id)
                if candidate is None:
                    continue
                result.append(
                    {
                        "group_id": f"{episode['identity']['episode_id']}|{query_id}|{semantic_id}",
                        "episode_id": episode["identity"]["episode_id"],
                        "query_id": query_id,
                        "kind": "independent",
                        "view": view,
                        "state_text": state_text,
                        "candidate_surfaces": [candidate_surface(candidate)],
                        "gold": [float(item["probability"])],
                        "open_world": False,
                        "probability_source": source,
                        "authority": episode.get("authority", {}).get("episode_authority_class", "unknown"),
                        "invariant_key": f"{invariant_base}|{query_id}|{semantic_id}",
                        "perturbation_class": perturbation.get("class"),
                    }
                )
    return result


def loss_mode(group: dict[str, Any]) -> str:
    return "soft_binary_cross_entropy" if group["kind"] == "independent" else "soft_cross_entropy"


def _signature_payload(group: dict[str, Any], ordered: bool) -> dict[str, Any]:
    pairs = [
        [surface, f32_bits(target)]
        for surface, target in zip(group["candidate_surfaces"], group["gold"])
    ]
    if not ordered:
        pairs.sort()
    source = group["probability_source"]
    return {
        "adapter": "jev-frozen-readout/v0.5/name_definition",
        "state_query_text": group["state_text"],
        "candidate_surface_float32_target_pairs": pairs,
        "kind": group["kind"],
        "view": group["view"],
        "open_world": bool(group["open_world"]),
        "probability_source": source,
        "semantic_loss": loss_mode(group),
        "semantic_loss_weight_float32": f32_bits(1.0),
        "brier_applies": source in CALIBRATION_SOURCES,
        "brier_weight_float32": f32_bits(0.25),
        "group_weight_float32": f32_bits(1.0),
        "candidate_order_augmentation": "reverse_candidate_and_target_arrays_each_batch",
    }


def base_signatures(group: dict[str, Any]) -> dict[str, str]:
    payload = _signature_payload(group, ordered=False)
    ordered_payload = _signature_payload(group, ordered=True)
    return {
        "state_input_sha256": digest(group["state_text"]),
        "candidate_ordered_sha256": digest(group["candidate_surfaces"]),
        "candidate_set_sha256": digest(sorted(group["candidate_surfaces"])),
        "target_ordered_sha256": digest([f32_bits(value) for value in group["gold"]]),
        "supervised_signature_sha256": digest(payload),
        "ordered_signature_sha256": digest(ordered_payload),
    }


def _pair_endpoint(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_input_sha256": group.get("state_input_sha256") or digest(group["state_text"]),
        "candidate_ordered_sha256": group.get("candidate_ordered_sha256")
        or digest(group["candidate_surfaces"]),
        "kind": group["kind"],
        "view": group["view"],
        "open_world": bool(group["open_world"]),
    }


def selected_invariance_pairs(
    groups: Iterable[dict[str, Any]], max_pairs: int = 16
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Reproduce the frozen v0.5 first-16 directed pair selection."""
    ordered = sorted(groups, key=lambda group: group["group_id"])
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in ordered:
        if not group["open_world"]:
            by_key[group["invariant_key"]].append(group)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for values in by_key.values():
        base = next(
            (item for item in values if item["perturbation_class"] is None),
            None,
        )
        sibling = next(
            (
                item
                for item in values
                if item["perturbation_class"] == "surfaceinvariance"
            ),
            None,
        )
        if base is not None and sibling is not None:
            pairs.append((base, sibling))
    return pairs[:max_pairs]


def attach_invariance_context(
    groups: list[dict[str, Any]], max_pairs: int = 16
) -> tuple[dict[str, str], list[str]]:
    """Return final per-group signatures and selected directed pair hashes."""
    selected = selected_invariance_pairs(groups, max_pairs=max_pairs)
    contexts: dict[str, list[tuple[str, str]]] = defaultdict(list)
    pair_hashes: list[str] = []
    for base, sibling in selected:
        edge_hash = digest(
            {
                "loss": "v0.5_directed_invariance",
                "loss_weight_float32": f32_bits(0.10),
                "left_base": _pair_endpoint(base),
                "right_surfaceinvariance": _pair_endpoint(sibling),
            }
        )
        pair_hashes.append(edge_hash)
        contexts[base["group_id"]].append((edge_hash, "base"))
        contexts[sibling["group_id"]].append((edge_hash, "surfaceinvariance"))

    final: dict[str, str] = {}
    for group in groups:
        base = group.get("supervised_signature_sha256")
        if base is None:
            base = base_signatures(group)["supervised_signature_sha256"]
        role_events = sorted(contexts.get(group["group_id"], []))
        final[group["group_id"]] = digest(
            {"supervised_signature_sha256": base, "invariance_pair_role_events": role_events}
        )
    return final, pair_hashes


def multiset_distance(left: Iterable[str], right: Iterable[str]) -> float:
    left_counts = Counter(left)
    right_counts = Counter(right)
    mass = sum(abs(left_counts[key] - right_counts[key]) for key in left_counts.keys() | right_counts.keys())
    denominator = 2 * max(sum(left_counts.values()), sum(right_counts.values()), 1)
    return mass / denominator
