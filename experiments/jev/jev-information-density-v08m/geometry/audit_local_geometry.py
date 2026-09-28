"""Read-only v0.8M preflight geometry audit.

This audit consumes only sealed, training-only v0.8L Phase-A artifacts.  It
does not construct a bank, train a head, open evaluation bodies, or create a
promotable parent for v0.8L.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

import torch


ROOT = Path(__file__).resolve().parents[3]
L_ROOT = Path(r"D:\codex-runs\jev-information-density-v08l\phase-a-v01-clean")
I_ROOT = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized")
TRIPLETS = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean\inputs\triplets.jsonl")
SHAMS = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01\inputs\sham-views.jsonl")
F100 = I_ROOT / "F100-groups.jsonl"
STATE_INPUTS = I_ROOT / "state-inputs.jsonl"
OUT = Path(r"D:\codex-runs\jev-information-density-v08m\geometry-v01")
FEATURES = L_ROOT / "feature-cache" / "state-features.pt"
SCOPE = L_ROOT / "feature-cache" / "state-scope.jsonl"
POOL = L_ROOT / "candidate-pool.jsonl"
MATCHING = L_ROOT / "novel-matching.jsonl"
L_RECEIPT = L_ROOT / "phase-a-final-receipt.json"

PROTOCOL = "jev-information-density/v0.8m-preflight-geometry-v01"
IDENTITY = "v0.8m-preflight-geometry-v01"
CHUNK = 128


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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def gold_key(row: dict[str, Any]) -> tuple[float, ...]:
    return tuple(round(float(value), 12) for value in row["gold"])


def entropy(row: dict[str, Any]) -> float:
    values = [float(value) for value in row["gold"] if float(value) > 0.0]
    return -sum(value * math.log(value) for value in values)


def quantiles(values: Iterable[float]) -> dict[str, float | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "min": None, "p10": None, "median": None, "p90": None, "max": None}

    def q(fraction: float) -> float:
        index = int(fraction * (len(ordered) - 1))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p10": q(0.10),
        "median": q(0.50),
        "p90": q(0.90),
        "max": ordered[-1],
    }


def distance_rows(features: torch.Tensor, anchor_indices: list[int]) -> list[torch.Tensor]:
    """Return one L2 distance vector per anchor using bounded matrix chunks."""
    norms = (features * features).sum(dim=1)
    result: list[torch.Tensor] = []
    state_t = features.transpose(0, 1).contiguous()
    for start in range(0, len(anchor_indices), CHUNK):
        indices = anchor_indices[start : start + CHUNK]
        anchors = features[indices]
        distances_sq = norms[None, :] + norms[indices, None] - 2.0 * (anchors @ state_t)
        result.extend(torch.sqrt(distances_sq.clamp_min_(0.0)))
    return result


def summary(values: list[float]) -> dict[str, Any]:
    stats = quantiles(values)
    if values:
        stats["mean"] = mean(values)
        stats["std"] = float(torch.tensor(values, dtype=torch.float64).std(unbiased=False).item())
    else:
        stats["mean"] = None
        stats["std"] = None
    return stats


def hard_key(row: dict[str, Any]) -> tuple[Any, ...]:
    fields = (
        "world_or_topology_family",
        "ontology_family",
        "schema_composition_family",
        "candidate_set_construction_family",
        "definition_template_family",
    )
    families = tuple((field, row.get("family_ids", {}).get(field)) for field in fields)
    return (
        row.get("kind"),
        row.get("view"),
        int(row.get("candidate_cardinality", -1)),
        tuple(row.get("candidate_semantic_ids", [])),
        tuple(row.get("candidate_indices", {}).get("name_definition", [])),
        families,
        row.get("probability_source"),
        gold_key(row),
    )


def main() -> int:
    receipt = read_json(L_RECEIPT)
    require(receipt["status"] == "PHASE_A_SEALED_NOT_PROMOTABLE", "unexpected L seal status")
    require(receipt["a1_feature_materialization"] == "PASS_TRAINING_ONLY", "L A1 is not training-only")
    require(receipt["model_head_training"] is False, "head-training boundary drift")
    require(receipt["evaluation_inference"] is False, "evaluation boundary drift")
    require(receipt["protected_evaluation_bodies_opened"] is False, "protected-eval boundary drift")
    require(receipt["phoenix_access"] is False, "Phoenix boundary drift")

    scope_rows = read_jsonl(SCOPE)
    scope_indices = [int(row["source_state_idx"]) for row in scope_rows]
    require([int(row["index"]) for row in scope_rows] == list(range(len(scope_rows))), "scope index drift")
    payload = torch.load(FEATURES, map_location="cpu", weights_only=True)
    features = payload["features"].to(torch.float32).contiguous()
    require(features.shape == (len(scope_rows), 2048), "feature shape drift")
    source_to_local = {source: index for index, source in enumerate(scope_indices)}

    primary = read_jsonl(F100)
    sham_rows = read_jsonl(SHAMS)
    states = read_jsonl(STATE_INPUTS)
    triplets = read_jsonl(TRIPLETS)
    pool = read_jsonl(POOL)
    matching = read_jsonl(MATCHING)
    require(len(primary) == 100_000, "F100 count drift")
    require(len(triplets) == 5_000 and len(matching) == 5_000, "triplet/matching count drift")
    require(len(pool) > 0, "candidate pool is empty")

    primary_by_id = {row["group_id"]: row for row in primary}
    matching_by_triplet = {row["triplet_id"]: row for row in matching}
    feature_meta: dict[int, dict[str, Any]] = {}
    for row in primary + sham_rows:
        state_idx = int(row["state_idx"])
        if state_idx not in source_to_local:
            continue
        feature_meta.setdefault(state_idx, row)
    require(len(feature_meta) > 0, "no feature-scoped training metadata")

    anchors: list[dict[str, Any]] = []
    for triplet in triplets:
        anchor = primary_by_id[triplet["anchor_group_id"]]
        match = matching_by_triplet[triplet["triplet_id"]]
        anchor_state = int(anchor["state_idx"])
        sham_state = int(match["sham_state_idx"])
        require(anchor_state in source_to_local and sham_state in source_to_local, "triplet state outside feature scope")
        anchors.append({
            "triplet_id": triplet["triplet_id"],
            "anchor": anchor,
            "anchor_state": anchor_state,
            "sham_state": sham_state,
            "anchor_local": source_to_local[anchor_state],
            "sham_local": source_to_local[sham_state],
            "sham_radius": float(match["anchor_radius"]),
            "family": anchor.get("family_ids", {}).get("world_or_topology_family"),
            "ontology": anchor.get("family_ids", {}).get("ontology_family"),
            "schema": anchor.get("family_ids", {}).get("schema_composition_family"),
            "entropy": entropy(anchor),
            "hard_key": hard_key(anchor),
        })

    entropy_values = sorted(item["entropy"] for item in anchors)

    def entropy_bin(value: float) -> str:
        rank = sum(1 for other in entropy_values if other < value)
        return f"q{min(4, int(5 * rank / max(1, len(entropy_values)) )) + 1}"

    for item in anchors:
        item["entropy_bin"] = entropy_bin(item["entropy"])

    anchor_distances = distance_rows(features, [item["anchor_local"] for item in anchors])
    state_local_to_source = {local: source for source, local in source_to_local.items()}
    scope_meta = [feature_meta.get(state_local_to_source[index]) for index in range(len(scope_rows))]
    require(all(meta is not None for meta in scope_meta), "missing metadata for feature scope")

    pool_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool:
        pool_by_anchor[row["anchor_group_id"]].append(row)

    exact_target_radii: list[float] = []
    exact_target_errors: list[float] = []
    same_family_nearest: list[float] = []
    same_ontology_nearest: list[float] = []
    same_schema_nearest: list[float] = []
    all_state_nearest: list[float] = []
    sham_radii: list[float] = []
    per_anchor: list[dict[str, Any]] = []

    for item, distances in zip(anchors, anchor_distances):
        anchor_row = item["anchor"]
        anchor_local = item["anchor_local"]
        sham_radius = item["sham_radius"]
        sham_radii.append(sham_radius)
        same_family = []
        same_ontology = []
        same_schema = []
        all_states = []
        for local, meta in enumerate(scope_meta):
            if local in (anchor_local, item["sham_local"]) or meta is None:
                continue
            distance = float(distances[local].item())
            all_states.append(distance)
            families = meta.get("family_ids", {})
            if families.get("world_or_topology_family") == item["family"]:
                same_family.append(distance)
            if families.get("ontology_family") == item["ontology"]:
                same_ontology.append(distance)
            if families.get("schema_composition_family") == item["schema"]:
                same_schema.append(distance)
        candidates = pool_by_anchor[anchor_row["group_id"]]
        candidate_radii = []
        candidate_errors = []
        for candidate in candidates:
            local = source_to_local[int(candidate["candidate_state_idx"])]
            radius = float(distances[local].item())
            candidate_radii.append(radius)
            candidate_errors.append(abs(radius - sham_radius))
        require(candidate_radii, f"no exact-target candidates for {item['triplet_id']}")
        exact_target_radii.extend(candidate_radii)
        exact_target_errors.extend(candidate_errors)
        same_family_nearest.append(min(same_family) if same_family else float("nan"))
        same_ontology_nearest.append(min(same_ontology) if same_ontology else float("nan"))
        same_schema_nearest.append(min(same_schema) if same_schema else float("nan"))
        all_state_nearest.append(min(all_states) if all_states else float("nan"))
        per_anchor.append({
            "triplet_id": item["triplet_id"],
            "anchor_state_idx": item["anchor_state"],
            "sham_state_idx": item["sham_state"],
            "family": item["family"],
            "entropy_bin": item["entropy_bin"],
            "entropy_nats": item["entropy"],
            "sham_radius": sham_radius,
            "exact_target_candidate_count": len(candidates),
            "exact_target_candidate_radius": summary(candidate_radii),
            "exact_target_radius_error": summary(candidate_errors),
            "nearest_same_world_family_radius": min(same_family) if same_family else None,
            "nearest_same_ontology_family_radius": min(same_ontology) if same_ontology else None,
            "nearest_same_schema_radius": min(same_schema) if same_schema else None,
            "nearest_scope_state_radius": min(all_states) if all_states else None,
        })

    def finite(values: list[float]) -> list[float]:
        return [value for value in values if math.isfinite(value)]

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_entropy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_anchor:
        by_family[str(row["family"])].append(row)
        by_entropy[str(row["entropy_bin"])].append(row)

    def grouped_report(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, rows in sorted(groups.items()):
            output[key] = {
                "anchor_count": len(rows),
                "sham_radius": summary([float(row["sham_radius"]) for row in rows]),
                "exact_target_radius_error": summary([float(row["exact_target_radius_error"]["mean"]) for row in rows]),
                "nearest_same_world_family_radius": summary(finite([float(row["nearest_same_world_family_radius"]) for row in rows if row["nearest_same_world_family_radius"] is not None])),
                "nearest_same_ontology_family_radius": summary(finite([float(row["nearest_same_ontology_family_radius"]) for row in rows if row["nearest_same_ontology_family_radius"] is not None])),
                "nearest_same_schema_radius": summary(finite([float(row["nearest_same_schema_radius"]) for row in rows if row["nearest_same_schema_radius"] is not None])),
                "nearest_scope_state_radius": summary(finite([float(row["nearest_scope_state_radius"]) for row in rows if row["nearest_scope_state_radius"] is not None])),
            }
        return output

    sources = [L_RECEIPT, FEATURES, SCOPE, POOL, MATCHING, F100, SHAMS, STATE_INPUTS, TRIPLETS]
    report = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "GEOMETRY_AUDIT_COMPLETE_READ_ONLY_NO_HEAD_NO_EVALUATION",
        "scientific_role": "diagnostic only; not a v0.8L repair and not a v0.8M Phase-A parent",
        "source_scope": "sealed v0.8L A1 training-only LFM features and training-side metadata",
        "source_hashes": {str(path): sha256_file(path) for path in sources},
        "feature_cache": {
            "states": len(scope_rows),
            "dimensions": list(features.shape),
            "model_head_training": False,
            "evaluation_inference": False,
            "protected_evaluation_bodies_opened": False,
            "phoenix_access": False,
        },
        "anchors": len(anchors),
        "sham_radius": summary(sham_radii),
        "exact_target_candidate_radius": summary(exact_target_radii),
        "exact_target_radius_error": summary(exact_target_errors),
        "nearest_same_world_family_radius": summary(finite(same_family_nearest)),
        "nearest_same_ontology_family_radius": summary(finite(same_ontology_nearest)),
        "nearest_same_schema_radius": summary(finite(same_schema_nearest)),
        "nearest_scope_state_radius": summary(finite(all_state_nearest)),
        "support_checks": {
            "exact_target_candidates": len(exact_target_radii),
            "exact_target_candidate_min_per_anchor": min(row["exact_target_candidate_count"] for row in per_anchor),
            "exact_target_candidate_max_per_anchor": max(row["exact_target_candidate_count"] for row in per_anchor),
            "radius_error_mean_threshold": 0.05,
            "radius_error_p95_threshold": 0.15,
            "unconstrained_lower_bound_mean_from_sealed_L": read_json(L_ROOT / "matching-summary.json")["unconstrained_nearest_lower_bound"]["mean"],
            "unconstrained_lower_bound_p95_from_sealed_L": read_json(L_ROOT / "matching-summary.json")["unconstrained_nearest_lower_bound"]["p95"],
        },
        "by_family": grouped_report(by_family),
        "by_entropy_quintile": grouped_report(by_entropy),
        "interpretation": {
            "sham_locality": "descriptive only",
            "generic_same_target_support": "available exact-target candidate geometry is measured but not a causal control",
            "local_neutral_direction": "not constructed; requires a fresh generator-side semantic identity",
            "phase_b_authorized": False,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "geometry-audit.json", report)
    write_jsonl(OUT / "per-anchor-geometry.jsonl", per_anchor)
    receipt = {
        "status": report["status"],
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "report_sha256": sha256_file(OUT / "geometry-audit.json"),
        "per_anchor_sha256": sha256_file(OUT / "per-anchor-geometry.jsonl"),
        "source_hashes": report["source_hashes"],
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
        "promotable": False,
    }
    write_json(OUT / "geometry-audit-receipt.json", receipt)
    print(json.dumps({
        "status": report["status"],
        "anchors": len(anchors),
        "sham_radius_mean": report["sham_radius"]["mean"],
        "exact_target_radius_error_mean": report["exact_target_radius_error"]["mean"],
        "nearest_scope_state_radius_mean": report["nearest_scope_state_radius"]["mean"],
        "out": str(OUT),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
