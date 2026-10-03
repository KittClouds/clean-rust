"""Verify generated canonical inputs against metadata-only selector records."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    chars = (
        character.lower() if character.isalnum() else " "
        for character in unicodedata.normalize("NFKC", value)
    )
    return " ".join("".join(chars).split())


def schema_surface_text(episode: dict[str, Any], query: dict[str, Any], kind: str) -> str:
    schema = episode["runtime_schema"]
    sets = {item["candidate_set_id"]: item for item in schema["candidate_sets"]}
    candidates = {item["candidate_id"]: item for item in schema["candidates"]}
    candidate_set = sets.get(query.get("candidate_set_id"), {})
    members = sorted(
        (candidates[identifier] for identifier in candidate_set.get("candidate_ids", []) if identifier in candidates),
        key=lambda item: (
            item.get("name") or "",
            item.get("description") or "",
            item.get("order_rank") if kind == "ordinal_score" else None,
        ),
    )
    rows = [f"view:{query['view']}", f"task:{kind}", query.get("instruction") or ""]
    if candidate_set:
        rows.extend(
            [
                candidate_set.get("set_role", ""),
                candidate_set.get("declared_semantics", ""),
                f"ordered:{str(bool(candidate_set.get('ordered', False))).lower()}",
            ]
        )
    for candidate in members:
        rows.extend([candidate.get("name") or "", candidate.get("description") or ""])
        if kind == "ordinal_score":
            rows.append(
                str(candidate.get("order_rank"))
                if candidate.get("order_rank") is not None
                else ""
            )
    return "\n".join(rows)


def model_input_digest(episode: dict[str, Any], query: dict[str, Any], kind: str) -> str:
    schema_surface = schema_surface_text(episode, query, kind)
    surface = f"{episode['state']['observable']['content']}\n{schema_surface}"
    return hashlib.sha256(normalize(surface).encode("utf-8")).hexdigest()


def schema_surface_digest(episode: dict[str, Any], query: dict[str, Any], kind: str) -> str:
    return hashlib.sha256(normalize(schema_surface_text(episode, query, kind)).encode("utf-8")).hexdigest()


def structural_digest(episode: dict[str, Any], query: dict[str, Any], cardinality: int) -> str:
    schema = episode["runtime_schema"]
    candidates = sorted(
        [
            candidate["candidate_semantic_id"],
            candidate["kind"],
            candidate.get("parent_candidate_semantic_id"),
        ]
        for candidate in schema["candidates"]
    )
    by_id = {candidate["candidate_id"]: candidate for candidate in schema["candidates"]}
    sets = []
    for candidate_set in schema["candidate_sets"]:
        members = [
            by_id[identifier]["candidate_semantic_id"]
            for identifier in candidate_set["candidate_ids"]
            if identifier in by_id
        ]
        if not candidate_set["ordered"]:
            members.sort()
        sets.append(
            {
                "role": candidate_set["set_role"],
                "semantics": candidate_set["declared_semantics"],
                "ordered": candidate_set["ordered"],
                "members": members,
            }
        )
    sets.sort(
        key=lambda value: (
            value["role"],
            json.dumps(value, separators=(",", ":")),
        )
    )
    perturbation = episode.get("perturbation") or {}
    raw_operation = perturbation.get("class", "base")
    operation = {
        "surfaceinvariance": "surface_invariance",
        "observationintervention": "observation_intervention",
        "worldintervention": "world_intervention",
    }.get(raw_operation, raw_operation)
    signature = {
        "candidates": candidates,
        "candidate_sets": sets,
        "query_view": query["view"],
        "candidate_cardinality": cardinality,
        "topology_family": episode["identity"].get("world_family_id"),
        "operation": operation,
        "renderer": episode["identity"].get("surface_renderer_id"),
    }
    payload = json.dumps(signature, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def groups_for_episode(episode: dict[str, Any]):
    targets = {item["query_id"]: item.get("target") or {} for item in episode["gold_targets"]}
    for query in episode["queries"]:
        target = targets.get(query["query_id"], {})
        kind = target.get("target_kind")
        view = query.get("view")
        episode_id = episode["identity"]["episode_id"]
        if kind == "independent_applicability" and view == "independent_applicability":
            entries = target.get("candidates") or []
            if len(entries) != 1:
                raise ValueError(f"expected one v0.8 independent candidate: {episode_id}|{query['query_id']}")
            group_id = f"{episode_id}|{query['query_id']}|{entries[0]['candidate_semantic_id']}"
            surface_kind = "independent_applicability"
        elif kind == "choice" and view == "choice":
            if float(target.get("other_probability") or 0.0) > 1e-12:
                continue
            group_id = f"{episode_id}|{query['query_id']}"
            surface_kind = "choice"
        elif kind == "ordinal" and view == "ordinal_score":
            group_id = f"{episode_id}|{query['query_id']}"
            surface_kind = "ordinal_score"
        else:
            continue
        schema = episode["runtime_schema"]
        candidate_sets = {item["candidate_set_id"]: item for item in schema["candidate_sets"]}
        members = candidate_sets.get(query.get("candidate_set_id"), {}).get("candidate_ids", [])
        cardinality = 1 if kind == "independent_applicability" else len(members)
        yield (
            group_id,
            model_input_digest(episode, query, surface_kind),
            structural_digest(episode, query, cardinality),
        )


def read_metadata(path: Path) -> tuple[dict[str, tuple[str, str, str]], Counter[str]]:
    records: dict[str, tuple[str, str, str]] = {}
    inputs: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row["group_id"]
            if group_id in records:
                raise ValueError(f"duplicate group record: {group_id}")
            input_hashes = [key.removeprefix("model_input:") for key in row["overlap_keys"] if key.startswith("model_input:")]
            gold_hashes = [key.removeprefix("gold_target:") for key in row["overlap_keys"] if key.startswith("gold_target:")]
            structural_hashes = [key.removeprefix("structural:") for key in row["overlap_keys"] if key.startswith("structural:")]
            if len(input_hashes) != 1 or len(gold_hashes) != 1 or len(structural_hashes) != 1:
                raise ValueError(f"missing digest key at {path}:{line_number}")
            records[group_id] = (input_hashes[0], gold_hashes[0], structural_hashes[0])
            inputs[input_hashes[0]].add(gold_hashes[0])
            counts["groups"] += 1
    counts["unique_inputs"] = len(inputs)
    counts["duplicate_input_occurrences"] = counts["groups"] - len(inputs)
    counts["conflicting_inputs"] = sum(len(targets) > 1 for targets in inputs.values())
    counts["max_gold_signatures_per_input"] = max((len(targets) for targets in inputs.values()), default=0)
    return records, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite audit output: {args.out}")

    records, consistency = read_metadata(args.group_records)
    mismatch_count = 0
    structural_mismatch_count = 0
    missing_count = 0
    canonical_group_count = 0
    with args.canonical.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            episode = json.loads(line)
            for group_id, digest, structure in groups_for_episode(episode):
                canonical_group_count += 1
                metadata = records.pop(group_id, None)
                if metadata is None:
                    missing_count += 1
                elif metadata[0] != digest:
                    mismatch_count += 1
                if metadata is not None and metadata[2] != structure:
                    structural_mismatch_count += 1
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    report = {
        "contract": "jev-decision-data-information-density/v0.8",
        "canonical_sha256": sha256_file(args.canonical),
        "group_records_sha256": sha256_file(args.group_records),
        "generation_receipt_sha256": sha256_file(args.receipt),
        "generation_receipt": receipt,
        "canonical_group_count": canonical_group_count,
        "metadata_group_count": consistency["groups"],
        "unmatched_metadata_group_count": len(records),
        "missing_metadata_group_count": missing_count,
        "cross_language_model_input_hash_mismatches": mismatch_count,
        "cross_language_structural_hash_mismatches": structural_mismatch_count,
        "input_target_consistency": consistency,
        "model_outputs_or_features_read": False,
        "phoenix_in_scope": False,
        "status": "PASS"
        if not (records or missing_count or mismatch_count or structural_mismatch_count or consistency["conflicting_inputs"])
        else "FAIL",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "canonical_group_count", "metadata_group_count", "unmatched_metadata_group_count",
        "missing_metadata_group_count", "cross_language_model_input_hash_mismatches",
        "cross_language_structural_hash_mismatches",
        "input_target_consistency", "status",
    )}, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
