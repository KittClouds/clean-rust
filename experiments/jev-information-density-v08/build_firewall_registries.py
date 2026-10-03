"""Build external overlap registries without reading target or prediction fields."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import audit_generator_outputs as signatures


READ_FIELDS = (
    "identity",
    "state.observable.content",
    "runtime_schema.candidates",
    "runtime_schema.candidate_sets",
    "queries",
    "perturbation",
)


def optional_key(keys: list[str], prefix: str, value: Any) -> None:
    if value is not None and str(value) not in ("", "none", "unknown"):
        keys.append(f"{prefix}:{value}")


def root_id(episode: dict[str, Any], root_overrides: dict[str, str]) -> str:
    identity = episode.get("identity") or {}
    episode_id = str(identity.get("episode_id", ""))
    if episode_id in root_overrides:
        return root_overrides[episode_id]
    for key in ("_v04_family_id", "_v05_family_id", "_v06_family_id"):
        if episode.get(key):
            return str(episode[key])
    return str(identity.get("world_instance_id") or episode_id)


def episode_registry_rows(
    episode: dict[str, Any],
    source_id: str,
    root_overrides: dict[str, str],
    strict_metadata: dict[str, dict[str, Any]],
):
    identity = episode.get("identity") or {}
    episode_id = str(identity.get("episode_id", ""))
    if not episode_id:
        return
    root = root_id(episode, root_overrides)
    observable = str(((episode.get("state") or {}).get("observable") or {}).get("content") or "")
    exact_text_hash = hashlib.sha256(observable.encode("utf-8")).hexdigest()
    normalized_text_hash = hashlib.sha256(signatures.normalize(observable).encode("utf-8")).hexdigest()
    metadata = strict_metadata.get(episode_id, {})
    perturbation = episode.get("perturbation") or {}
    schema = episode.get("runtime_schema") or {}
    candidate_by_id = {item.get("candidate_id"): item for item in schema.get("candidates", [])}
    set_by_id = {item.get("candidate_set_id"): item for item in schema.get("candidate_sets", [])}

    for query in episode.get("queries", []):
        view = str(query.get("view") or "unknown")
        candidate_set = set_by_id.get(query.get("candidate_set_id"), {})
        members = [
            candidate_by_id[identifier]
            for identifier in candidate_set.get("candidate_ids", [])
            if identifier in candidate_by_id
        ]
        if view == "independent_applicability":
            semantic_ids = sorted({str(candidate.get("candidate_semantic_id", "")) for candidate in members})
            group_ids = [f"{episode_id}|{query.get('query_id')}|{semantic_id}" for semantic_id in semantic_ids]
            kind = "independent_applicability"
            cardinality = 1
        else:
            group_ids = [f"{episode_id}|{query.get('query_id')}" ]
            kind = view
            cardinality = len(members)
        for group_id in group_ids:
            keys: list[str] = []
            optional_key(keys, "group", group_id)
            optional_key(keys, "episode", episode_id)
            optional_key(keys, "root", root)
            optional_key(keys, "world_instance", identity.get("world_instance_id"))
            optional_key(keys, "semantic", identity.get("semantic_fingerprint"))
            optional_key(keys, "text", normalized_text_hash)
            optional_key(keys, "text_exact", exact_text_hash)
            optional_key(keys, "schema_surface", signatures.schema_surface_digest(episode, query, kind))
            optional_key(keys, "model_input", signatures.model_input_digest(episode, query, kind))
            optional_key(keys, "structural", signatures.structural_digest(episode, query, cardinality))
            optional_key(keys, "world_family", identity.get("world_family_id"))
            optional_key(keys, "ontology_family", identity.get("schema_family_id") or schema.get("schema_family_id"))
            optional_key(keys, "schema_composition", schema.get("schema_family_id"))
            optional_key(keys, "generator_template", identity.get("world_family_id"))
            optional_key(keys, "definition_template", identity.get("paraphrase_family_id"))
            optional_key(keys, "intervention_family", identity.get("perturbation_family_id"))
            optional_key(keys, "parent", perturbation.get("parent_episode_id"))
            optional_key(keys, "parent", metadata.get("parent_episode_id"))
            optional_key(keys, "semantic", metadata.get("semantic_fingerprint"))
            optional_key(keys, "text_exact", metadata.get("text_sha256"))
            optional_key(keys, "text", metadata.get("normalized_text_sha256"))
            optional_key(keys, "structural", metadata.get("structural_fingerprint"))
            optional_key(keys, "root", metadata.get("root_family_id"))
            yield {
                "source_id": source_id,
                "episode_id": episode_id,
                "group_id": group_id,
                "overlap_keys": sorted(set(keys)),
            }


def load_strict_metadata(path: Path | None) -> tuple[dict[str, str], dict[str, dict[str, Any]], str | None, int]:
    if path is None:
        return {}, {}, None, 0
    root_overrides: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            episode_id = str(row["episode_id"])
            root_overrides[episode_id] = str(row["root_family_id"])
            records[episode_id] = row
            count += 1
    return root_overrides, records, digest.hexdigest(), count


def metadata_registry_row(row: dict[str, Any], source_id: str) -> dict[str, Any]:
    keys: list[str] = []
    optional_key(keys, "episode", row.get("episode_id"))
    optional_key(keys, "root", row.get("parent_family_id") or row.get("root_family_id"))
    optional_key(keys, "root", row.get("root_family_id"))
    optional_key(keys, "parent", row.get("parent_episode_id"))
    optional_key(keys, "semantic", row.get("semantic_fingerprint"))
    optional_key(keys, "structural", row.get("structural_fingerprint"))
    optional_key(keys, "world_family", row.get("world_family_id"))
    optional_key(keys, "ontology_family", row.get("ontology_family_id"))
    optional_key(keys, "schema_composition", row.get("schema_family_id"))
    optional_key(keys, "generator_template", row.get("generator_template_id"))
    optional_key(keys, "definition_template", row.get("paraphrase_family_id"))
    optional_key(keys, "intervention_family", row.get("perturbation_family_id"))
    optional_key(keys, "world_regime", row.get("world_regime"))
    optional_key(keys, "ontology_regime", row.get("ontology_regime"))
    optional_key(keys, "topology_class", row.get("topology_class"))
    optional_key(keys, "operation", row.get("operation"))
    optional_key(keys, "text", row.get("normalized_text_sha256"))
    optional_key(keys, "text_exact", row.get("text_sha256"))
    return {"source_id": source_id, "episode_id": str(row.get("episode_id", "")), "overlap_keys": sorted(set(keys))}


def build(plan_path: Path, output: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    strict_meta_path = Path(plan["strict_novel_root_metadata"])
    if not strict_meta_path.is_file():
        raise FileNotFoundError(f"required StrictNovel93 metadata is absent: {strict_meta_path}")
    missing_sources = [Path(source["path"]) for source in plan["sources"] if not Path(source["path"]).is_file()]
    if missing_sources:
        raise FileNotFoundError(f"required source is absent: {missing_sources[0]}")
    root_overrides, strict_metadata, strict_metadata_sha, strict_metadata_count = load_strict_metadata(strict_meta_path)
    training_path = output / "legacy-training-registry.jsonl"
    protected_path = output / "protected-eval-registry.jsonl"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("refusing to overwrite an existing firewall registry")
    output.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    registry_counts: Counter[str] = Counter()
    training_writer = training_path.open("w", encoding="utf-8", buffering=1 << 20)
    protected_writer = protected_path.open("w", encoding="utf-8", buffering=1 << 20)
    writer_for_role = {
        "prior_training": training_writer,
        "prior_candidate_firewall": training_writer,
        "protected_evaluation": protected_writer,
        "protected_family_registry": protected_writer,
        "protected_metadata": protected_writer,
    }
    try:
        for source in plan["sources"]:
            path = Path(source["path"])
            source_id = str(source["id"])
            role = str(source["role"])
            digest = hashlib.sha256()
            row_count = 0
            group_count = 0
            writer = writer_for_role[role]
            with path.open("rb") as stream:
                for raw in stream:
                    digest.update(raw)
                    if not raw.strip():
                        continue
                    row = json.loads(raw)
                    row_count += 1
                    if source.get("format") == "v04_metadata":
                        record = metadata_registry_row(row, source_id)
                        writer.write(json.dumps(record, separators=(",", ":")) + "\n")
                        registry_counts[role] += 1
                        group_count += 1
                        continue
                    # Deliberately never access gold_targets, labels, predictions, or score files.
                    for record in episode_registry_rows(row, source_id, root_overrides, strict_metadata):
                        writer.write(json.dumps(record, separators=(",", ":")) + "\n")
                        registry_counts[role] += 1
                        group_count += 1
            summaries.append(
                {
                    "source_id": source_id,
                    "role": role,
                    "path": str(path),
                    "sha256": digest.hexdigest(),
                    "row_count": row_count,
                    "registry_group_count": group_count,
                    "gold_targets_accessed": False,
                    "predictions_accessed": False,
                }
            )
    finally:
        training_writer.close()
        protected_writer.close()

    report = {
        "contract": plan["contract"],
        "source_plan_path": str(plan_path),
        "source_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "strict_novel_metadata_path": str(strict_meta_path),
        "strict_novel_metadata_sha256": strict_metadata_sha,
        "strict_novel_metadata_episode_count": strict_metadata_count,
        "sources": summaries,
        "source_count": len(summaries),
        "training_registry_group_count": registry_counts["prior_training"] + registry_counts["prior_candidate_firewall"],
        "protected_registry_group_count": registry_counts["protected_evaluation"] + registry_counts["protected_family_registry"] + registry_counts["protected_metadata"],
        "training_registry_sha256": hashlib.sha256(training_path.read_bytes()).hexdigest(),
        "protected_registry_sha256": hashlib.sha256(protected_path.read_bytes()).hexdigest(),
        "fields_accessed": list(READ_FIELDS),
        "gold_targets_accessed": False,
        "model_predictions_accessed": False,
        "protected_text_exported": False,
        "phoenix_in_scope": False,
        "status": "registry_built_preselection_only",
    }
    report_path = output / "source-audit.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite existing source audit: {report_path}")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.plan, args.out)
    print(json.dumps({
        "source_count": report["source_count"],
        "training_registry_group_count": report["training_registry_group_count"],
        "protected_registry_group_count": report["protected_registry_group_count"],
        "source_plan_sha256": report["source_plan_sha256"],
        "gold_targets_accessed": report["gold_targets_accessed"],
        "status": report["status"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
