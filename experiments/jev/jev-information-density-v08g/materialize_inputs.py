"""Materialize exact-ID compiler rows and representation tables; no model use."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
PROBE_PATH = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"
V08_RUN = Path(r"D:\codex-runs\jev-information-density-v08")
CANONICAL = V08_RUN / "full-universe-500k-v08" / "new-universe-canonical.jsonl"
GROUP_RECORDS = V08_RUN / "full-universe-500k-v08" / "group-records.jsonl"
EVAL_MANIFEST = V08_RUN / "selection-v08-c100v12" / "new-tight-eval-group-ids.jsonl"
PROFILES = ("name", "name_definition", "opaque_definition", "opaque_only")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest(path: Path, expected_count: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row.get("group_id")
            if not isinstance(group_id, str) or group_id in result:
                raise ValueError(f"invalid or duplicate group ID at {path}:{line_number}")
            result[group_id] = row
    if len(result) != expected_count:
        raise ValueError(f"{path}: found {len(result)} IDs, expected {expected_count}")
    return result


def load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08g_frozen_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen group adapter: {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expected_input_hash(run_manifest: dict[str, Any], path: Path) -> str:
    resolved = str(path.resolve()).casefold()
    for record in run_manifest.get("lineage_files_verified", []):
        if str(Path(record["path"]).resolve()).casefold() == resolved:
            return str(record["sha256"])
    raise ValueError(f"run manifest does not bind source hash for {path}")


def index_text(text: str, values: list[str], indices: dict[str, int]) -> int:
    index = indices.get(text)
    if index is None:
        index = len(values)
        indices[text] = index
        values.append(text)
    return index


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            payload = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            stream.write(payload.decode("utf-8"))
            digest.update(payload)
    return digest.hexdigest()


def materialize() -> dict[str, Any]:
    run_manifest_path = OUT / "v08g-run-manifest.json"
    auth_path = OUT / "preflight" / "model-contact-authorization.json"
    run_manifest = load_json(run_manifest_path)
    authorization = load_json(auth_path)
    if authorization.get("status") != "PASS" or authorization.get("model_contact_authorized") is not True:
        raise ValueError("model/data preflight authorization is not PASS")
    if sha256_file(run_manifest_path) != authorization.get("manifest_sha256"):
        raise ValueError("frozen v0.8G run manifest hash changed")
    expected_canonical = expected_input_hash(run_manifest, CANONICAL)
    expected_metadata = expected_input_hash(run_manifest, GROUP_RECORDS)
    if sha256_file(CANONICAL) != expected_canonical:
        raise ValueError("canonical episode source changed after preflight")

    frozen = run_manifest["frozen_inputs"]
    random_path = Path(frozen["R100-star"]["path"])
    curated_path = Path(frozen["C100-star"]["path"])
    eval_path = Path(frozen["NewTight-Eval"]["path"])
    random_ids = read_manifest(random_path, 100_000)
    curated_ids = read_manifest(curated_path, 100_000)
    eval_rows = read_manifest(eval_path, 83_328)
    bank_ids = {
        "random": random_ids,
        "curated": curated_ids,
        "new_tight_eval": eval_rows,
    }
    expected_episode_by_id: dict[str, str] = {}
    memberships: dict[str, set[str]] = {}
    for bank_name, rows in bank_ids.items():
        for group_id, row in rows.items():
            episode_id = str(row.get("episode_id", ""))
            if not episode_id:
                raise ValueError(f"missing source episode_id in {bank_name}: {group_id}")
            prior = expected_episode_by_id.setdefault(group_id, episode_id)
            if prior != episode_id:
                raise ValueError(f"cross-bank episode mismatch for {group_id}")
            memberships.setdefault(group_id, set()).add(bank_name)

    # Metadata is read from the frozen metadata-only index, not reconstructed
    # from observable text. The complete file digest is recomputed while read.
    wanted = set(expected_episode_by_id)
    metadata_by_id: dict[str, dict[str, Any]] = {}
    metadata_digest = hashlib.sha256()
    with GROUP_RECORDS.open("rb", buffering=1 << 20) as stream:
        for line_number, raw_line in enumerate(stream, 1):
            metadata_digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed group metadata at line {line_number}") from exc
            group_id = row.get("group_id")
            if group_id in wanted:
                if group_id in metadata_by_id:
                    raise ValueError(f"duplicate selected metadata row for {group_id}")
                metadata_by_id[group_id] = {
                    "root_id": row.get("root_id"),
                    "family_ids": row.get("family_ids", {}),
                    "coverage_features": row.get("coverage_features", {}),
                    "strata": row.get("strata", {}),
                }
    if metadata_digest.hexdigest() != expected_metadata:
        raise ValueError("group metadata file changed during exact-ID materialization")
    missing_metadata = wanted - metadata_by_id.keys()
    if missing_metadata:
        raise ValueError(f"selected IDs missing from group metadata: {len(missing_metadata)}")

    eval_metadata: dict[str, dict[str, Any]] = {}
    with eval_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            eval_metadata[row["group_id"]] = {
                "split_family_bundle_id": row.get("split_family_bundle_id"),
                "held_out_axes": row.get("held_out_axes", []),
                "held_out_family_ids": row.get("held_out_family_ids", {}),
            }

    probe = load_probe()
    state_texts: list[str] = []
    state_index: dict[str, int] = {}
    candidate_texts: dict[str, list[str]] = {profile: [] for profile in PROFILES}
    candidate_index: dict[str, dict[str, int]] = {profile: {} for profile in PROFILES}
    bank_groups: dict[str, list[dict[str, Any]]] = {
        "random": [], "curated": [], "new_tight_eval": [],
    }
    found_occurrences: Counter[str] = Counter()
    canonical_digest = hashlib.sha256()
    canonical_episode_ids_seen: set[str] = set()
    target_episodes = set(expected_episode_by_id.values())
    with CANONICAL.open("rb", buffering=1 << 20) as stream:
        for line_number, raw_line in enumerate(stream, 1):
            canonical_digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                episode = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed canonical episode at line {line_number}") from exc
            episode_id = episode.get("identity", {}).get("episode_id")
            if episode_id not in target_episodes:
                continue
            canonical_episode_ids_seen.add(episode_id)
            source_groups = probe.group_records([episode])
            for source_group in source_groups:
                group_id = source_group["group_id"]
                if group_id not in memberships:
                    continue
                if expected_episode_by_id[group_id] != episode_id:
                    raise ValueError(f"manifest episode mismatch during canonical reload: {group_id}")
                found_occurrences[group_id] += 1
                if found_occurrences[group_id] != 1:
                    raise ValueError(f"selected group ID has multiple canonical records: {group_id}")

                state_idx = index_text(source_group["state_text"], state_texts, state_index)
                semantic_ids = list(source_group["candidate_semantic_ids"])
                candidate_indices_by_profile: dict[str, list[int]] = {}
                for profile in PROFILES:
                    indices: list[int] = []
                    for position, semantic_id in enumerate(semantic_ids):
                        candidate = source_group["candidate_descriptions"][semantic_id]
                        surface = probe.candidate_surface(candidate, position, profile)
                        # This mirrors the v0.7 cache identity exactly.
                        cache_key = f"{semantic_id}|{surface}"
                        index = candidate_index[profile].get(cache_key)
                        if index is None:
                            index = len(candidate_texts[profile])
                            candidate_index[profile][cache_key] = index
                            candidate_texts[profile].append(surface)
                        indices.append(index)
                    candidate_indices_by_profile[profile] = indices

                meta = metadata_by_id[group_id]
                compact = {
                    "group_id": group_id,
                    "episode_id": episode_id,
                    "query_id": source_group["query_id"],
                    "kind": source_group["kind"],
                    "view": source_group["view"],
                    "state_idx": state_idx,
                    "candidate_semantic_ids": semantic_ids,
                    "candidate_indices": candidate_indices_by_profile,
                    "gold": source_group["gold"],
                    "open_world": source_group["open_world"],
                    "probability_source": source_group["probability_source"],
                    "authority": source_group["authority"],
                    "split": "new_tight_eval" if "new_tight_eval" in memberships[group_id] else "train",
                    "invariant_key": source_group["invariant_key"],
                    "semantic_fingerprint": source_group["semantic_fingerprint"],
                    "perturbation_class": source_group["perturbation_class"],
                    "candidate_cardinality": source_group.get("candidate_cardinality", len(semantic_ids)),
                    "root_id": meta["root_id"],
                    "family_ids": meta["family_ids"],
                    "coverage_features": meta["coverage_features"],
                    "strata": meta["strata"],
                }
                for bank_name in memberships[group_id]:
                    bank_groups[bank_name].append(dict(compact))
    if canonical_digest.hexdigest() != expected_canonical:
        raise ValueError("canonical episode file changed during exact-ID materialization")
    missing_groups = wanted - found_occurrences.keys()
    if missing_groups:
        raise ValueError(f"selected IDs missing from canonical episodes: {len(missing_groups)}")

    expected_counts = {"random": 100_000, "curated": 100_000, "new_tight_eval": 83_328}
    for bank_name, expected_count in expected_counts.items():
        if len(bank_groups[bank_name]) != expected_count:
            raise ValueError(f"{bank_name} materialized {len(bank_groups[bank_name])}, expected {expected_count}")
        bank_groups[bank_name].sort(key=lambda row: row["group_id"])

    materialized_dir = OUT / "materialized-inputs"
    materialized_dir.mkdir(exist_ok=False)
    group_receipts = {}
    for bank_name, rows in bank_groups.items():
        path = materialized_dir / f"{bank_name}-groups.jsonl"
        group_receipts[bank_name] = {
            "path": str(path),
            "sha256": write_jsonl(path, rows),
            "group_count": len(rows),
            "unique_group_id_count": len({row["group_id"] for row in rows}),
            "open_world_unsupported_count": sum(bool(row["open_world"]) for row in rows),
            "kind_counts": dict(Counter(row["kind"] for row in rows)),
            "view_counts": dict(Counter(row["view"] for row in rows)),
            "probability_source_counts": dict(Counter(row["probability_source"] for row in rows)),
            "unique_state_text_count": len({row["state_idx"] for row in rows}),
        }
    table_receipts = {}
    state_path = materialized_dir / "state-inputs.jsonl"
    table_receipts["state_inputs"] = {
        "path": str(state_path),
        "sha256": write_jsonl(state_path, [{"index": i, "text": text} for i, text in enumerate(state_texts)]),
        "count": len(state_texts),
    }
    for profile in PROFILES:
        path = materialized_dir / f"candidate-inputs-{profile}.jsonl"
        table_receipts[profile] = {
            "path": str(path),
            "sha256": write_jsonl(
                path,
                [{"index": i, "text": text} for i, text in enumerate(candidate_texts[profile])],
            ),
            "count": len(candidate_texts[profile]),
        }
    report = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "status": "EXACT_ID_INPUTS_MATERIALIZED_NO_MODEL_LOADED",
        "source_hashes_rechecked": {
            "canonical_episodes": expected_canonical,
            "group_records": expected_metadata,
        },
        "episode_ids_seen": len(canonical_episode_ids_seen),
        "manifest_group_occurrences": {name: len(rows) for name, rows in bank_groups.items()},
        "training_occurrence_preservation": {
            "random_manifest_rows": len(random_ids),
            "random_materialized_rows": len(bank_groups["random"]),
            "curated_manifest_rows": len(curated_ids),
            "curated_materialized_rows": len(bank_groups["curated"]),
            "group_occurrences_deduplicated": False,
        },
        "group_files": group_receipts,
        "representation_tables": table_receipts,
        "model_loaded": False,
        "phoenix_access": False,
    }
    report_path = materialized_dir / "materialization-receipt.json"
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = materialize()
    print(json.dumps({
        "status": result["status"],
        "groups": result["manifest_group_occurrences"],
        "state_texts": result["representation_tables"]["state_inputs"]["count"],
        "candidate_texts": {key: value["count"] for key, value in result["representation_tables"].items() if key != "state_inputs"},
        "model_loaded": False,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
