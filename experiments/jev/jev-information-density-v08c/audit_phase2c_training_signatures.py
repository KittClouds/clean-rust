"""Audit v0.5 model-input/loss signature distances without model inference."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import phase2c_training_signatures as sig  # noqa: E402


DEFAULT_DATA = Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08")
DEFAULT_SELECTION = Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12")
DEFAULT_PHASE2B = Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\equivalent-substitution-v01")
DEFAULT_OUT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_freeze_receipt(path: Path, contract_path: Path) -> str:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("status") != "SEALED_BEFORE_SIGNATURE_AUDIT":
        raise ValueError("Phase 2C freeze receipt is not sealed")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("Phase 2C freeze receipt contract hash mismatch")
    for relative, expected in receipt.get("repository_sources", {}).items():
        actual = sha256_file(ROOT / relative)
        if actual != expected:
            raise ValueError(f"frozen repository source changed after seal: {relative}")
    for name, record in receipt.get("external_inputs", {}).items():
        actual = sha256_file(Path(record["path"]))
        if actual != record["sha256"]:
            raise ValueError(f"frozen external input changed after seal: {name}")
    return sha256_file(path)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pinned standard-library source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_manifest(path: Path, expected_count: int = 100_000) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = str(row["group_id"])
            if group_id in result:
                raise ValueError(f"duplicate ID in {path}:{line_number}")
            result[group_id] = str(row.get("episode_id", ""))
    if len(result) != expected_count:
        raise ValueError(f"{path} contains {len(result)} IDs, expected {expected_count}")
    return result


def overlap_digests(row: dict[str, Any]) -> tuple[str, str, str]:
    values: dict[str, list[str]] = {"model_input": [], "gold_target": [], "structural": []}
    for key in row["overlap_keys"]:
        for kind in values:
            prefix = f"{kind}:"
            if key.startswith(prefix):
                values[kind].append(key[len(prefix):])
    if any(len(items) != 1 for items in values.values()):
        raise ValueError(f"group {row.get('group_id')} has malformed overlap keys")
    return values["model_input"][0], values["gold_target"][0], values["structural"][0]


def create_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute(
        """CREATE TABLE training_groups (
            group_id TEXT PRIMARY KEY,
            episode_id TEXT NOT NULL,
            root_id TEXT NOT NULL,
            split_family_bundle_id TEXT NOT NULL,
            selector_model_input_sha256 TEXT NOT NULL,
            selector_gold_target_sha256 TEXT NOT NULL,
            selector_structural_sha256 TEXT NOT NULL,
            state_input_sha256 TEXT NOT NULL,
            candidate_ordered_sha256 TEXT NOT NULL,
            candidate_set_sha256 TEXT NOT NULL,
            target_ordered_sha256 TEXT NOT NULL,
            supervised_signature_sha256 TEXT NOT NULL,
            ordered_signature_sha256 TEXT NOT NULL,
            invariant_key_sha256 TEXT NOT NULL,
            perturbation_class TEXT,
            adapter_kind TEXT NOT NULL,
            view TEXT NOT NULL,
            open_world INTEGER NOT NULL,
            probability_source TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            posterior_entropy_nats REAL NOT NULL,
            base_strata_json TEXT NOT NULL,
            family_ids_json TEXT NOT NULL,
            coverage_features_json TEXT NOT NULL,
            held_out INTEGER NOT NULL,
            entropy_quintile INTEGER,
            joint_cell_json TEXT,
            atom_id TEXT
        )"""
    )
    connection.execute("CREATE INDEX ix_groups_episode ON training_groups(episode_id)")
    connection.execute("CREATE INDEX ix_groups_atom ON training_groups(atom_id)")
    return connection


def entropy_quintile_thresholds(values: list[float]) -> list[float]:
    values.sort()
    return [values[min(len(values) - 1, math.floor(len(values) * q / 5))] for q in range(1, 5)]


def candidate_record(
    group: dict[str, Any], metadata: dict[str, Any], split_module: Any
) -> tuple[Any, ...]:
    hashes = sig.base_signatures(group)
    selector_input, selector_gold, selector_structural = overlap_digests(metadata)
    invariant_key_hash = hashlib.sha256(group["invariant_key"].encode("utf-8")).hexdigest()
    families = metadata["family_ids"]
    strata = metadata["strata"]
    if not isinstance(strata, dict):
        raise ValueError(f"invalid strata on {group['group_id']}")
    base_strata = [strata[key] for key in split_module.STRATUM_FIELDS[:3]]
    if len(base_strata) != 3:
        raise ValueError("expected three pre-quintile strata")
    entropy = float(metadata["posterior_entropy_nats"])
    if not math.isfinite(entropy) or entropy < 0:
        raise ValueError(f"invalid posterior entropy on {group['group_id']}")
    return (
        group["group_id"],
        group["episode_id"],
        str(metadata["root_id"]),
        str(metadata["split_family_bundle_id"]),
        selector_input,
        selector_gold,
        selector_structural,
        hashes["state_input_sha256"],
        hashes["candidate_ordered_sha256"],
        hashes["candidate_set_sha256"],
        hashes["target_ordered_sha256"],
        hashes["supervised_signature_sha256"],
        hashes["ordered_signature_sha256"],
        invariant_key_hash,
        group["perturbation_class"],
        group["kind"],
        group["view"],
        int(group["open_world"]),
        group["probability_source"],
        len(group["candidate_surfaces"]),
        entropy,
        sig.canonical_json(base_strata),
        sig.canonical_json(families),
        sig.canonical_json(metadata["coverage_features"]),
        int(split_module.is_held_out(str(metadata["split_family_bundle_id"]))),
    )


INSERT_SQL = """INSERT INTO training_groups (
    group_id, episode_id, root_id, split_family_bundle_id,
    selector_model_input_sha256, selector_gold_target_sha256, selector_structural_sha256,
    state_input_sha256, candidate_ordered_sha256, candidate_set_sha256, target_ordered_sha256,
    supervised_signature_sha256, ordered_signature_sha256, invariant_key_sha256,
    perturbation_class, adapter_kind, view, open_world, probability_source, candidate_count,
    posterior_entropy_nats, base_strata_json, family_ids_json, coverage_features_json, held_out
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def progress_event(stream: Any, stage: str, count: int, start_time: float) -> None:
    event = {
        "stage": stage,
        "processed": count,
        "elapsed_seconds": round(time.perf_counter() - start_time, 3),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    stream.write(json.dumps(event, separators=(",", ":")) + "\n")
    stream.flush()
    print(f"{stage}: {count:,} processed; {event['elapsed_seconds']:.1f}s", flush=True)


def build_index(
    data_dir: Path,
    output_dir: Path,
    selection_dir: Path,
    phase2b_dir: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    generator_audit = load_module(
        "phase2c_generator_audit",
        ROOT / "experiments" / "jev-information-density-v08" / "audit_generator_outputs.py",
    )
    split_module = load_module(
        "phase2c_split_source",
        ROOT / "experiments" / "jev-information-density-v08" / "select_banks.py",
    )
    expected_hashes = contract["inputs"]
    input_paths = {
        "group_records_sha256": data_dir / "group-records.jsonl",
        "canonical_episodes_sha256": data_dir / "new-universe-canonical.jsonl",
        "r100_manifest_sha256": selection_dir / "new-tight-r100-group-ids.jsonl",
        "c100_manifest_sha256": selection_dir / "new-tight-c100-group-ids.jsonl",
        "eval_manifest_sha256": selection_dir / "new-tight-eval-group-ids.jsonl",
        "input_target_consistency_sha256": data_dir / "input-target-consistency.json",
        "phase2b_cm100_atom_provisional_sha256": phase2b_dir / "cm100-provisional-ids.jsonl",
        "phase2b_rm100_atom_provisional_sha256": phase2b_dir / "rm100-provisional-ids.jsonl",
        "phase2b_atom_validation_sha256": phase2b_dir / "candidate-validation.json",
    }
    actual_hashes = {key: sha256_file(path) for key, path in input_paths.items()}
    for key, actual in actual_hashes.items():
        if actual != expected_hashes[key]:
            raise ValueError(f"frozen source mismatch for {key}")
    consistency = json.loads(input_paths["input_target_consistency_sha256"].read_text(encoding="utf-8"))
    if (
        consistency.get("status") != "PASS"
        or consistency.get("input_target_consistency", {}).get("conflicting_inputs") != 0
    ):
        raise ValueError("pinned input-target consistency receipt is not a zero-conflict PASS")

    parent_phase2b = phase2b_dir.parent
    lineage_paths = {
        "parent_phase2b_freeze_sha256": parent_phase2b / "phase2b-freeze-receipt.json",
        "atom_stage_freeze_sha256": parent_phase2b / "atom-stage-freeze-receipt.json",
        "atom_stage_validation_sha256": phase2b_dir / "candidate-validation.json",
        "phase2b_construction_sha256": phase2b_dir / "construction-report.json",
        "phase2b_objective_contract_sha256": HERE / "v08c-phase2b-contract.json",
        "phase2b_atom_contract_sha256": HERE / "v08c-phase2b-atom-stage-contract.json",
    }
    actual_lineage_hashes = {key: sha256_file(path) for key, path in lineage_paths.items()}
    for key, actual in actual_lineage_hashes.items():
        if actual != contract["lineage"][key]:
            raise ValueError(f"frozen Phase 2B lineage mismatch for {key}")

    bank_paths = {
        "R100": input_paths["r100_manifest_sha256"],
        "C100": input_paths["c100_manifest_sha256"],
        "CM100_atom": input_paths["phase2b_cm100_atom_provisional_sha256"],
        "RM100_atom": input_paths["phase2b_rm100_atom_provisional_sha256"],
    }
    bank_ids = {name: read_manifest(path) for name, path in bank_paths.items()}
    eval_ids = read_manifest(input_paths["eval_manifest_sha256"], expected_count=83_328)
    if any(set(rows) & set(eval_ids) for rows in bank_ids.values()):
        raise ValueError("a training bank overlaps NewTight-Eval")

    index_path = output_dir / "eligible-training-signatures.jsonl"
    db_path = output_dir / "training-signatures.sqlite"
    progress_path = output_dir / "progress.jsonl"
    connection = create_db(db_path)
    entropy_values: list[float] = []
    metadata_count = 0
    derived_count = 0
    eligible_count = 0
    held_count = 0
    start_time = time.perf_counter()

    with (
        (data_dir / "group-records.jsonl").open("r", encoding="utf-8") as metadata_stream,
        (data_dir / "new-universe-canonical.jsonl").open("r", encoding="utf-8") as episode_stream,
        index_path.open("x", encoding="utf-8", newline="\n") as index_stream,
        progress_path.open("x", encoding="utf-8", newline="\n") as progress_stream,
    ):
        metadata_iter = iter(metadata_stream)
        pending_metadata: dict[str, Any] | None = None

        def next_metadata() -> dict[str, Any] | None:
            for line in metadata_iter:
                if line.strip():
                    return json.loads(line)
            return None

        pending_metadata = next_metadata()
        batch: list[tuple[Any, ...]] = []
        for episode_line, episode_text in enumerate(episode_stream, 1):
            if not episode_text.strip():
                continue
            episode = json.loads(episode_text)
            episode_id = str(episode["identity"]["episode_id"])
            block: list[dict[str, Any]] = []
            while pending_metadata is not None and pending_metadata["episode_id"] == episode_id:
                block.append(pending_metadata)
                pending_metadata = next_metadata()
            if not block:
                raise ValueError(f"metadata has no block for canonical episode {episode_id}")
            if any(row["episode_id"] != episode_id or row["valid"] is not True for row in block):
                raise ValueError(f"malformed metadata block for {episode_id}")

            # Independent cross-language check: canonical episode -> generator group IDs/digests.
            generated = list(generator_audit.groups_for_episode(episode))
            generated_by_id = {group_id: (input_hash, structural_hash) for group_id, input_hash, structural_hash in generated}
            if len(generated_by_id) != len(generated):
                raise ValueError(f"duplicate generator group IDs for {episode_id}")
            block_by_id = {str(row["group_id"]): row for row in block}
            if set(generated_by_id) != set(block_by_id):
                raise ValueError(f"canonical/raw generator group IDs differ for {episode_id}")
            for group_id, (input_hash, structural_hash) in generated_by_id.items():
                observed_input, _observed_gold, observed_structural = overlap_digests(block_by_id[group_id])
                if (input_hash, structural_hash) != (observed_input, observed_structural):
                    raise ValueError(f"canonical/raw generator digest mismatch for {group_id}")

            projected = sig.group_records(episode)
            projected_by_id = {group["group_id"]: group for group in projected}
            if len(projected_by_id) != len(projected):
                raise ValueError(f"duplicate v0.5 adapter group IDs for {episode_id}")
            closed_ids = {
                group_id
                for group_id, group in projected_by_id.items()
                if not group["open_world"] and group["kind"] in {"choice", "independent"}
            }
            if closed_ids != set(block_by_id):
                raise ValueError(f"closed v0.5 adapter groups differ from metadata for {episode_id}")
            if any(
                group["authority"] != "synthetic_control"
                for group in projected_by_id.values()
                if not group["open_world"]
            ):
                raise ValueError("non-synthetic authority encountered in the frozen S100 source universe")

            metadata_count += len(block)
            for group_id, group in projected_by_id.items():
                if group_id not in block_by_id or group["open_world"]:
                    continue
                metadata = block_by_id[group_id]
                held = split_module.is_held_out(str(metadata["split_family_bundle_id"]))
                if held:
                    held_count += 1
                    continue
                eligible_count += 1
                row = candidate_record(group, metadata, split_module)
                if row[24] != 0:
                    raise AssertionError("eligible split calculation drifted during record creation")
                entropy_values.append(row[20])
                batch.append(row)
                sigs = sig.base_signatures(group)
                index_stream.write(
                    json.dumps(
                        {
                            "group_id": row[0],
                            "episode_id": row[1],
                            "root_id": row[2],
                            "split_family_bundle_id": row[3],
                            "selector_model_input_sha256": row[4],
                            "selector_gold_target_sha256": row[5],
                            "selector_structural_sha256": row[6],
                            "state_input_sha256": row[7],
                            "candidate_ordered_sha256": row[8],
                            "candidate_set_sha256": row[9],
                            "target_ordered_sha256": row[10],
                            "supervised_signature_sha256": row[11],
                            "ordered_signature_sha256": row[12],
                            "invariant_key_sha256": row[13],
                            "perturbation_class": row[14],
                            "adapter_kind": row[15],
                            "view": row[16],
                            "open_world": bool(row[17]),
                            "probability_source": row[18],
                            "candidate_count": row[19],
                            "posterior_entropy_nats": row[20],
                            "base_strata": json.loads(row[21]),
                            "family_ids": json.loads(row[22]),
                            "coverage_features": json.loads(row[23]),
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                derived_count += 1
                if len(batch) >= 10_000:
                    connection.executemany(INSERT_SQL, batch)
                    connection.commit()
                    batch.clear()
            if episode_line % 5_000 == 0:
                progress_event(progress_stream, "canonical_projection", episode_line, start_time)

        if pending_metadata is not None:
            raise ValueError(f"unmatched trailing metadata group {pending_metadata['group_id']}")
        if batch:
            connection.executemany(INSERT_SQL, batch)
            connection.commit()
        if metadata_count != 500_000:
            raise ValueError(f"metadata group count {metadata_count} != 500000")
        if eligible_count != 416_672 or derived_count != eligible_count:
            raise ValueError(
                f"eligible projection count mismatch: {eligible_count=} {derived_count=}"
            )

    thresholds = entropy_quintile_thresholds(entropy_values)
    connection.execute("BEGIN")
    cursor = connection.execute(
        "SELECT group_id, posterior_entropy_nats, base_strata_json, selector_model_input_sha256, "
        "root_id, split_family_bundle_id, family_ids_json, coverage_features_json FROM training_groups "
        "ORDER BY group_id"
    )
    update_rows: list[tuple[int, str, str, str, str]] = []
    for group_id, entropy, strata_json, input_id, root_id, bundle, families_json, features_json in cursor:
        strata = json.loads(strata_json)
        quintile = bisect.bisect_right(thresholds, float(entropy)) + 1
        entropy_band = (
            "very_low" if entropy < 0.20 else
            "low" if entropy < 0.55 else
            "medium" if entropy < 0.95 else
            "high" if entropy < 1.30 else "very_high"
        )
        joint_cell = [
            strata[0], str(bundle), strata[1], strata[2], f"q{quintile}", entropy_band
        ]
        families = json.loads(families_json)
        features = json.loads(features_json)
        topology = sorted(
            str(value)
            for value in features.get("structural_coverage", [])
            if str(value).startswith("topology:")
        )
        intervention = str(families["intervention_family"])
        atom_id = sig.digest([input_id, str(root_id), joint_cell, topology, intervention])
        update_rows.append(
            (quintile, sig.canonical_json(joint_cell), atom_id, group_id, sig.canonical_json([strata[0], strata[1], strata[2], f"q{quintile}"]))
        )
        if len(update_rows) >= 10_000:
            connection.executemany(
                "UPDATE training_groups SET entropy_quintile=?, joint_cell_json=?, atom_id=?, base_strata_json=? WHERE group_id=?",
                [(q, cell, atom, new_strata, gid) for q, cell, atom, gid, new_strata in update_rows],
            )
            update_rows.clear()
    if update_rows:
        connection.executemany(
            "UPDATE training_groups SET entropy_quintile=?, joint_cell_json=?, atom_id=?, base_strata_json=? WHERE group_id=?",
            [(q, cell, atom, new_strata, gid) for q, cell, atom, gid, new_strata in update_rows],
        )
    connection.commit()
    connection.execute("CREATE INDEX ix_groups_cell ON training_groups(joint_cell_json)")
    connection.execute("CREATE INDEX ix_groups_signature ON training_groups(supervised_signature_sha256)")
    connection.commit()

    bank_summaries: dict[str, Any] = {}
    for bank_name, manifest in bank_ids.items():
        missing = [group_id for group_id in manifest if connection.execute(
            "SELECT 1 FROM training_groups WHERE group_id=?", (group_id,)
        ).fetchone() is None]
        if missing:
            raise ValueError(f"{bank_name} contains non-eligible IDs; first={missing[0]}")
        bank_summaries[bank_name] = bank_summary(connection, manifest)
    for bank_name, manifest in bank_ids.items():
        mismatches = [
            group_id for group_id, episode_id in manifest.items()
            if connection.execute(
                "SELECT episode_id FROM training_groups WHERE group_id=?", (group_id,)
            ).fetchone()[0] != episode_id
        ]
        if mismatches:
            raise ValueError(f"{bank_name} episode IDs mismatch; first={mismatches[0]}")

    comparisons = {
        "R100_vs_C100": compare_banks(connection, bank_ids["R100"], bank_ids["C100"]),
        "R100_vs_CM100_atom": compare_banks(connection, bank_ids["R100"], bank_ids["CM100_atom"]),
        "C100_vs_RM100_atom": compare_banks(connection, bank_ids["C100"], bank_ids["RM100_atom"]),
    }
    connection.close()
    return {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-training-signature-audit",
        "status": "PASS_METADATA_SIGNATURES_RECONSTRUCTED",
        "source_hashes": {**actual_hashes, **actual_lineage_hashes},
        "source_row_counts": {
            "raw_metadata_groups": metadata_count,
            "eligible_closed_v05_training_groups": eligible_count,
            "held_out_closed_v05_groups": held_count,
            "canonical_episodes": episode_line,
        },
        "training_eligibility": "v0.5 S100 synthetic-control rule: authority synthetic_control, train split, closed-world, adapter kind choice or independent; ordinal is projected to choice-kind softmax; open-world rows are excluded",
        "entropy_quintile_thresholds_nats": thresholds,
        "banks": bank_summaries,
        "comparisons": comparisons,
        "external_artifacts": {
            "signature_index": str(index_path),
            "signature_index_sha256": sha256_file(index_path),
            "sqlite_index": str(db_path),
            "sqlite_index_sha256": sha256_file(db_path),
        },
        "model_contact": False,
        "tokenizer_or_feature_equivalence_checked": False,
        "phoenix_access": False,
    }


def bank_rows(connection: sqlite3.Connection, ids: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_id in sorted(ids):
        record = connection.execute(
            "SELECT group_id, state_input_sha256, candidate_ordered_sha256, "
            "candidate_set_sha256, target_ordered_sha256, supervised_signature_sha256, "
            "ordered_signature_sha256, invariant_key_sha256, perturbation_class, adapter_kind, "
            "view, open_world, probability_source, episode_id, root_id, atom_id, "
            "candidate_count, joint_cell_json, selector_model_input_sha256, posterior_entropy_nats, "
            "family_ids_json, coverage_features_json FROM training_groups WHERE group_id=?",
            (group_id,),
        ).fetchone()
        if record is None:
            raise ValueError(f"bank ID absent from signature database: {group_id}")
        keys = (
            "group_id", "state_input_sha256", "candidate_ordered_sha256",
            "candidate_set_sha256", "target_ordered_sha256", "supervised_signature_sha256",
            "ordered_signature_sha256", "invariant_key_sha256", "perturbation_class",
            "kind", "view", "open_world", "probability_source", "episode_id", "root_id",
            "atom_id", "candidate_count", "joint_cell_json", "selector_model_input_sha256", "posterior_entropy_nats",
            "family_ids_json", "coverage_features_json",
        )
        row = dict(zip(keys, record))
        row["invariant_key"] = row.pop("invariant_key_sha256")
        row["open_world"] = bool(row["open_world"])
        rows.append(row)
    return rows


def bank_summary(connection: sqlite3.Connection, ids: dict[str, str]) -> dict[str, Any]:
    rows = bank_rows(connection, ids)
    final, pair_hashes = sig.attach_invariance_context(rows)
    root_counts = Counter(row["root_id"] for row in rows)
    state_inputs = {row["state_input_sha256"] for row in rows}
    candidate_sets = {row["candidate_set_sha256"] for row in rows}
    state_occurrences = Counter(row["state_input_sha256"] for row in rows)
    candidate_occurrences = Counter(row["candidate_set_sha256"] for row in rows)
    return {
        "group_count": len(rows),
        "unique_root_count": len(root_counts),
        "unique_state_query_input_count": len(state_inputs),
        "unique_candidate_surface_set_count": len(candidate_sets),
        "mean_group_occurrences_per_state_query_input": len(rows) / max(1, len(state_inputs)),
        "state_input_occurrence_histogram": dict(sorted(Counter(map(str, state_occurrences.values())).items())),
        "root_occurrence_histogram": dict(sorted(Counter(map(str, root_counts.values())).items())),
        "candidate_set_occurrence_histogram": dict(sorted(Counter(map(str, candidate_occurrences.values())).items())),
        "adapter_kind_counts": dict(sorted(Counter(row["kind"] for row in rows).items())),
        "view_counts": dict(sorted(Counter(row["view"] for row in rows).items())),
        "probability_source_counts": dict(sorted(Counter(row["probability_source"] for row in rows).items())),
        "candidate_cardinality_counts": dict(sorted(Counter(str(len_candidate(row)) for row in rows).items())),
        "atom_count": len({row["atom_id"] for row in rows}),
        "selected_invariance_pair_count": len(pair_hashes),
        "selected_invariance_pair_hashes": pair_hashes,
        "training_signature_multiset_sha256": sig.digest(sorted(final.values())),
        "supervised_signature_multiset_sha256": sig.digest(sorted(row["supervised_signature_sha256"] for row in rows)),
    }


def len_candidate(row: dict[str, Any]) -> int:
    # The hashed index stores surfaces, not raw candidate text.
    return int(row.get("candidate_count", 0))


def counter_distance(left: Iterable[str], right: Iterable[str]) -> float:
    return sig.multiset_distance(left, right)


def compare_banks(
    connection: sqlite3.Connection,
    left_manifest: dict[str, str],
    right_manifest: dict[str, str],
) -> dict[str, Any]:
    left_ids, right_ids = set(left_manifest), set(right_manifest)
    left_rows = bank_rows(connection, left_manifest)
    right_rows = bank_rows(connection, right_manifest)
    left_final, left_pairs = sig.attach_invariance_context(left_rows)
    right_final, right_pairs = sig.attach_invariance_context(right_rows)
    left_inputs = {row["state_input_sha256"] for row in left_rows}
    right_inputs = {row["state_input_sha256"] for row in right_rows}
    left_candidates = {row["candidate_set_sha256"] for row in left_rows}
    right_candidates = {row["candidate_set_sha256"] for row in right_rows}
    left_roots = {row["root_id"] for row in left_rows}
    right_roots = {row["root_id"] for row in right_rows}
    pair_counts_left = Counter(left_pairs)
    pair_counts_right = Counter(right_pairs)
    supervised_distance = counter_distance(
        (row["supervised_signature_sha256"] for row in left_rows),
        (row["supervised_signature_sha256"] for row in right_rows),
    )
    training_distance = counter_distance(left_final.values(), right_final.values())
    return {
        "row_identity": {
            "left_count": len(left_ids),
            "right_count": len(right_ids),
            "overlap_count": len(left_ids & right_ids),
            "symmetric_difference_count": len(left_ids ^ right_ids),
            "group_id_jaccard": len(left_ids & right_ids) / max(1, len(left_ids | right_ids)),
        },
        "model_visible_text_signature": {
            "D_supervised": supervised_distance,
            "D_train": training_distance,
            "supervised_multiset_distance": supervised_distance,
            "training_multiset_distance_with_selected_invariance_context": training_distance,
            "strict_ordered_supervised_multiset_distance": counter_distance(
                (row["ordered_signature_sha256"] for row in left_rows),
                (row["ordered_signature_sha256"] for row in right_rows),
            ),
            "selector_model_input_multiset_distance": counter_distance(
                (row["selector_model_input_sha256"] for row in left_rows),
                (row["selector_model_input_sha256"] for row in right_rows),
            ),
        },
        "input_and_schema_turnover": {
            "unique_state_query_inputs_left": len(left_inputs),
            "unique_state_query_inputs_right": len(right_inputs),
            "state_query_input_intersection": len(left_inputs & right_inputs),
            "state_query_input_union": len(left_inputs | right_inputs),
            "state_query_input_jaccard": len(left_inputs & right_inputs) / max(1, len(left_inputs | right_inputs)),
            "state_query_inputs_introduced": len(right_inputs - left_inputs),
            "state_query_inputs_removed": len(left_inputs - right_inputs),
            "unique_candidate_surface_sets_left": len(left_candidates),
            "unique_candidate_surface_sets_right": len(right_candidates),
            "candidate_surface_set_intersection": len(left_candidates & right_candidates),
            "candidate_surface_set_union": len(left_candidates | right_candidates),
            "candidate_surface_set_jaccard": len(left_candidates & right_candidates) / max(1, len(left_candidates | right_candidates)),
        },
        "root_turnover": {
            "unique_roots_left": len(left_roots),
            "unique_roots_right": len(right_roots),
            "root_intersection": len(left_roots & right_roots),
            "root_union": len(left_roots | right_roots),
        },
        "invariance_regularizer": {
            "selected_pair_count_left": len(left_pairs),
            "selected_pair_count_right": len(right_pairs),
            "selected_pair_multiset_distance": counter_distance(left_pairs, right_pairs),
            "selected_pair_hashes_left": left_pairs,
            "selected_pair_hashes_right": right_pairs,
        },
        "training_signatures_are_text_level_not_feature_level": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--selection-dir", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--phase2b-dir", type=Path, default=DEFAULT_PHASE2B)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    contract_path = HERE / "v08c-phase2c-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if args.outdir.exists():
        existing = {path.name for path in args.outdir.iterdir()}
        allowed = {"phase2c-freeze-receipt.json"}
        if existing - allowed or "phase2c-freeze-receipt.json" not in existing:
            raise FileExistsError(f"refusing to reuse non-fresh run directory: {args.outdir}")
        freeze_hash = verify_freeze_receipt(args.outdir / "phase2c-freeze-receipt.json", contract_path)
    else:
        raise FileNotFoundError("Phase 2C must be sealed before the signature audit starts")
    args.outdir.mkdir(parents=True, exist_ok=True)
    report = build_index(args.data_dir, args.outdir, args.selection_dir, args.phase2b_dir, contract)
    report["contract_sha256"] = sha256_file(contract_path)
    report["freeze_receipt_sha256"] = freeze_hash
    report_path = args.outdir / "training-equivalence-audit.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path), "banks": report["banks"], "comparisons": report["comparisons"]}, indent=2))


if __name__ == "__main__":
    main()
