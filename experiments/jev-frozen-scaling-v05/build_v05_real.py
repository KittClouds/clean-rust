"""Normalize bounded real sources into the canonical v1 episode contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


EMOTIONS = (
    "admiration", "amusement", "anger", "annoyance", "approval", "caring",
    "confusion", "curiosity", "desire", "disappointment", "disapproval",
    "disgust", "embarrassment", "excitement", "fear", "gratitude", "grief",
    "joy", "love", "nervousness", "optimism", "pride", "realization",
    "relief", "remorse", "sadness", "surprise", "neutral",
)
REAL_SOURCE_IDS = {"ChaosNLI", "google-research-datasets/go_emotions", "AmazonScience/massive"}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def split_for(value: str) -> str:
    bucket = int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if bucket == 0 else "dev" if bucket == 1 else "train"


def external_partition(value: str) -> bool:
    """Reserve a disjoint half of the source-hash test bucket."""
    return int(hashlib.sha256(("external:" + value).encode("utf-8")).hexdigest()[:8], 16) % 2 == 0


def authority(source: str, row_id: str, split: str, note: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record_id = f"auth-{source.replace('/', '_')}-{row_id}"
    lineage = {
        "source_dataset_id": source,
        "source_revision": {
            "ChaosNLI": "f358e234ea2797d9298f7b0213bf1308b6d7756b",
            "google-research-datasets/go_emotions": "add492243ff905527e67aeb8b80c082af02207c3",
            "AmazonScience/massive": "ff6bd8e4e27c3543e4f8fe2108f32bb95a6f8740",
        }[source],
        "source_split": split,
        "source_row_id": row_id,
        "upstream_dataset_id": None,
        "upstream_row_id": None,
        "adapter_id": "jev_v05_real_bridge",
        "adapter_revision": "0.5.0",
        "transformation_chain": ["source_row", "canonical_v1", note],
    }
    record = {
        "authority_record_id": record_id,
        "authority_class": "externally_annotated",
        "authority_domain": "external_dataset",
        "authority_scope": "source row target",
        "creator_or_system": source,
        "source_identity": source,
        "source_revision_or_snapshot": lineage["source_revision"],
        "annotation_or_generator_protocol": note,
        "created_at": None,
        "available_at": None,
        "license_or_access_basis": "source audit v0.2; external run artifact",
        "parent_authority_ids": [],
        "quality_limitations": ["human annotation distributions are not synthetic world posteriors"],
        "lineage": lineage,
    }
    return {"episode_authority_class": "externally_annotated", "authority_record_ids": [record_id], "phoenix_authority_domain": False}, record


def emotion_episode(example_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    text = str(first["text"])
    counts = {emotion: sum(int(row.get(emotion, 0)) for row in rows) for emotion in EMOTIONS}
    total = len(rows)
    split = split_for(example_id)
    candidates = []
    targets = []
    annotations = []
    for emotion in EMOTIONS:
        candidates.append({
            "candidate_id": emotion,
            "candidate_semantic_id": emotion,
            "kind": "label",
            "name": emotion,
            "description": f"The text expresses {emotion}.",
            "aliases": [],
            "opaque_id": None,
            "parent_candidate_semantic_id": None,
            "order_rank": None,
            "mutually_exclusive_group_id": None,
            "independent_allowed": True,
        })
        targets.append({"candidate_semantic_id": emotion, "probability": counts[emotion] / total})
    for row in rows:
        labels = [emotion for emotion in EMOTIONS if int(row.get(emotion, 0))]
        annotations.append({"annotator_id": f"rater-{row.get('rater_id')}", "labels": labels})
    authority_value, authority_record = authority(
        "google-research-datasets/go_emotions", example_id, split, "raw_rater_rows_to_empirical_label_frequencies"
    )
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "contract": "jev-like-decision-dataset/v1",
        "contract_status": "v1",
        "identity": {
            "episode_id": f"go-emotions-v05-{example_id}",
            "world_family_id": "external:google-research-datasets/go_emotions",
            "world_instance_id": f"google-research-datasets/go_emotions:{example_id}",
            "surface_renderer_id": "source-go-emotions-raw",
            "paraphrase_family_id": "external-source-native",
            "perturbation_family_id": "none",
            "schema_family_id": "schema-emotions-28",
            "task_family_ids": ["independent_applicability", "human_uncertainty"],
            "domain_family_id": "emotion",
            "semantic_fingerprint": content_hash,
        },
        "state": {
            "representation": "prose",
            "observable": {"content": text, "items": [f"ev-{example_id}"]},
            "latent": None,
            "variables": {"observed": [f"ev-{example_id}"], "missing": [], "hidden": []},
            "structured_state": None,
        },
        "evidence_items": [{"evidence_id": f"ev-{example_id}", "kind": "text", "content": text,
                            "source_ref": f"google-research-datasets/go_emotions:{example_id}",
                            "available_at": None, "character_span": [0, len(text)]}],
        "runtime_schema": {
            "schema_id": "schema-emotions-28-v05",
            "schema_family_id": "schema-emotions-28",
            "candidates": candidates,
            "candidate_sets": [{"candidate_set_id": "cs-emotions", "candidate_ids": list(EMOTIONS),
                                "set_role": "independent-labels", "declared_semantics": "independent_applicability",
                                "ordered": False, "parent_candidate_set_id": None}],
            "constraints": [], "presentation_profiles": [],
        },
        "queries": [{"query_id": "q-emotions", "query_semantic_id": "emotion-applicability",
                      "view": "independent_applicability", "instruction": "Which emotions apply to the text?",
                      "candidate_set_id": "cs-emotions", "argument_scope": None, "abstention_policy": None,
                      "exposed_fields": ["name", "description"]}],
        "gold_targets": [{
            "query_id": "q-emotions", "authority_record_id": authority_record["authority_record_id"],
            "score_semantics": "independent_applicability", "candidate_set_id": "cs-emotions",
            "probability_source": {"probability_source": "empirical_annotator_distribution", "sample_count": total,
                                   "annotator_count": total, "raw_label_counts": counts,
                                   "aggregation_method": "normalized_rater_frequencies",
                                   "normalization_scope": "per_label_rater_frequency",
                                   "distribution_interpretation": "human_annotation_frequency"},
            "target": {"target_kind": "independent_applicability", "candidates": targets, "abstain_allowed": False},
            "annotations": annotations,
        }],
        "evidence_links": [], "perturbation": None, "authority": authority_value,
        "authority_records": [authority_record],
        "workload": {"query_count": 1, "candidate_cardinality": len(EMOTIONS), "label_density": sum(bool(v) for v in counts.values()) / len(EMOTIONS)},
        "evaluation_constraints": {"split_regime": f"real_source_hash_{split}", "excluded_from_primary_benchmark": False, "notes": []},
    }


def load_pilot(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.open("r", encoding="utf-8"):
        episode = json.loads(line)
        if episode.get("authority", {}).get("episode_authority_class") != "externally_annotated":
            continue
        lineage = (episode.get("authority_records") or [{}])[0].get("lineage") or {}
        if lineage.get("source_dataset_id") in REAL_SOURCE_IDS:
            rows.append(episode)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--go-emotions-parquet", required=True)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    table = pq.read_table(args.go_emotions_parquet)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in table.to_pylist():
        grouped[str(row["id"])].append(row)
    episodes = [emotion_episode(example_id, rows) for example_id, rows in sorted(grouped.items())]
    episodes.extend(load_pilot(Path(args.pilot)))
    output = Path(args.output)
    splits = {name: [] for name in ("train", "dev", "test", "external")}
    for episode in episodes:
        regime = episode.get("evaluation_constraints", {}).get("split_regime")
        split = regime.rsplit("_", 1)[-1] if regime else split_for(episode["identity"]["world_instance_id"])
        if split == "eval":
            split = "test"
        if split == "test" and external_partition(episode["identity"]["world_instance_id"]):
            split = "external"
        splits[split].append(episode)
    write_jsonl(output / "train.jsonl", splits["train"])
    write_jsonl(output / "dev.jsonl", splits["dev"])
    write_jsonl(output / "test.jsonl", splits["test"])
    write_jsonl(output / "external-eval.jsonl", splits["external"])
    manifest = {
        "contract": "jev-frozen-decision-surface-scaling/v0.5",
        "source_rows": {"go_emotions_raw": int(table.num_rows), "pilot_real_rows": len(episodes) - len(grouped)},
        "episode_count": len(episodes),
        "split_counts": {key: len(value) for key, value in splits.items()},
        "external_partition": "sha256(external:<world_instance_id>) mod 2 over source-hash test bucket",
        "source_policy": "GoEmotions expanded from raw rater rows; ChaosNLI/MASSIVE retained at audited fixture scale because public extraction paths were unavailable in this run",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
