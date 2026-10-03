"""Build fresh Phase-A representation tables from R100-star training rows only.

The v0.8G shared text tables are intentionally never opened. This builder uses
the sealed R100-star group manifest, its training-only materialized group rows,
and the canonical archive only to fully parse episodes whose IDs are referenced
by R100-star. Nonmatching archive records are inspected only through the early
identity. Their remaining bytes are discarded without JSON decoding or output.
Evaluation manifests and group-record metadata are used for identity/hash
firewall checks; evaluation observable text is never parsed or materialized.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import types
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO, Iterable

ROOT = Path(__file__).resolve().parents[2]
V08G_RUN = Path(r"D:\codex-runs\jev-information-density-v08g")
V08G_MATERIALIZED = V08G_RUN / "materialized-inputs"
V08_RUN = Path(r"D:\codex-runs\jev-information-density-v08")
V08_FULL = V08_RUN / "full-universe-500k-v08"
CANONICAL = V08_FULL / "new-universe-canonical.jsonl"
GROUP_RECORDS = V08_FULL / "group-records.jsonl"
SIGNATURE_DB = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")
PROBE_PATH = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"
PROFILES = ("name", "name_definition", "opaque_definition", "opaque_only")
CONTRACT_DEFAULT = ROOT / "experiments" / "jev-information-density-v08i" / "phase-a-v02-clean-contract.json"
ARM_COUNT = 100_000
IDENTITY_EPISODE_RE = re.compile(
    rb'"identity"\s*:\s*\{[^{}]{0,8192}?"episode_id"\s*:\s*("(?:\\.|[^"\\])*")',
    re.DOTALL,
)
OVERLAP_FIELDS = {
    "group": "group",
    "episode": "episode",
    "root": "root",
    "text_exact": "text_exact",
    "schema_surface": "schema_surface",
    "model_input": "model_input",
}
FAMILY_FIELDS = (
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def training_value_digest(value: Any) -> str:
    """Match v0.8C's digest(value), including JSON quoting for strings."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_ids(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid metadata JSONL at {path}:{line_no}") from exc


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return sha256_file(path)


def validate_phase_a_contract(contract: dict[str, Any]) -> None:
    """Validate frozen generator and bank dimensions at their declared paths."""
    if contract.get("run_identity") != "phase-a-v02-clean":
        raise ValueError("wrong Phase-A v02 contract identity")
    generator = contract.get("generator", {})
    bank = contract.get("bank_construction", {})
    if (generator.get("training_pair_capacity") != 12_000
            or generator.get("heldout_pair_capacity") != 2_000):
        raise ValueError("Phase-A v02 pair capacities drifted from the frozen protocol")
    if (bank.get("selected_anchor_dose") != 5_000
            or bank.get("bank_groups_per_arm") != ARM_COUNT
            or bank.get("common_skeleton_groups") != 90_000
            or bank.get("replacement_groups_per_arm") != 10_000):
        raise ValueError("Phase-A v02 bank dose/count drifted from the frozen protocol")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            payload = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            stream.write(payload.decode("utf-8"))
            digest.update(payload)
    return digest.hexdigest()


def load_probe() -> Any:
    """Load only frozen pure-Python grouping helpers, never model dependencies."""
    required = {
        "stable_hash",
        "stable_opaque_id",
        "candidate_surface",
        "candidate_index",
        "query_candidates",
        "query_target",
        "state_query_text",
        "split_name",
        "group_records",
    }
    parsed = ast.parse(PROBE_PATH.read_text(encoding="utf-8"), filename=str(PROBE_PATH))
    definitions = {
        node.name: node
        for node in parsed.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = required - definitions.keys()
    if missing:
        raise RuntimeError(f"frozen group adapter helpers missing: {sorted(missing)}")
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *(definitions[name] for name in sorted(required)),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {"Any": Any, "hashlib": hashlib}
    exec(compile(module, str(PROBE_PATH), "exec"), namespace)
    return types.SimpleNamespace(**{name: namespace[name] for name in required})


def manifest_rows(
    path: Path,
    expected: int | None = None,
    *,
    require_unique: bool = True,
) -> list[dict[str, Any]]:
    rows = list(read_jsonl(path))
    ids = [str(row.get("group_id", "")) for row in rows]
    if any(not value for value in ids) or (
        require_unique and len(ids) != len(set(ids))
    ):
        raise ValueError(f"invalid or duplicate group IDs in {path}")
    if expected is not None and len(rows) != expected:
        raise ValueError(f"{path} has {len(rows)} rows, expected {expected}")
    return rows


def _skip_record_tail(stream: BinaryIO) -> None:
    """Skip a nonselected JSONL record without retaining or decoding its body."""
    while True:
        block = stream.read(1 << 16)
        if not block:
            return
        newline = block.find(b"\n")
        if newline < 0:
            continue
        remainder = len(block) - newline - 1
        if remainder:
            stream.seek(-remainder, 1)
        return


def _read_episode_id_prefix(stream: BinaryIO, line_no: int) -> tuple[bytes, str] | None:
    prefix = bytearray()
    while len(prefix) <= (1 << 14):
        byte = stream.read(1)
        if not byte:
            return None if not prefix else (_raise(f"truncated canonical record at line {line_no}"))
        prefix.extend(byte)
        if byte == b"\n":
            if not prefix.strip():
                return bytes(prefix), ""
            raise ValueError(f"canonical identity is not in early record prefix at line {line_no}")
        match = IDENTITY_EPISODE_RE.search(prefix)
        if match:
            try:
                episode_id = json.loads(match.group(1).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid identity episode_id at canonical line {line_no}") from exc
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError(f"empty identity episode_id at canonical line {line_no}")
            return bytes(prefix), episode_id
    raise ValueError(f"canonical identity prefix exceeded 16 KiB at line {line_no}")


def _raise(message: str) -> Any:
    raise ValueError(message)


def selected_canonical_episodes(
    path: Path, wanted_episode_ids: set[str], protected_episode_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    found: dict[str, dict[str, Any]] = {}
    counts = Counter()
    with path.open("rb", buffering=1 << 20) as stream:
        line_no = 0
        while True:
            prefix_result = _read_episode_id_prefix(stream, line_no + 1)
            if prefix_result is None:
                break
            prefix, episode_id = prefix_result
            if not episode_id:
                line_no += 1
                continue
            line_no += 1
            counts["records_identity_scanned"] += 1
            if episode_id in wanted_episode_ids:
                tail = stream.readline()
                raw = prefix + tail
                try:
                    episode = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid selected canonical record at line {line_no}") from exc
                if episode.get("identity", {}).get("episode_id") != episode_id:
                    raise ValueError(f"selected canonical identity drift at line {line_no}")
                if episode_id in found:
                    raise ValueError(f"duplicate selected canonical episode {episode_id}")
                found[episode_id] = episode
                counts["selected_training_episode_bodies_parsed"] += 1
                counts["protected_eval_episode_bodies_parsed"] += int(episode_id in protected_episode_ids)
            else:
                _skip_record_tail(stream)
                counts["nonselected_record_bodies_json_decoded"] += 0
                counts["protected_eval_identity_prefixes_seen"] += int(episode_id in protected_episode_ids)
    missing = wanted_episode_ids - found.keys()
    if missing:
        raise ValueError(f"canonical source lacks {len(missing)} R100-star training episodes")
    if counts["protected_eval_episode_bodies_parsed"]:
        raise ValueError("protected evaluation episode body was parsed")
    return found, dict(counts)


def source_hash_record(run_manifest: dict[str, Any], target: Path) -> dict[str, Any]:
    resolved = str(target.resolve()).casefold()
    for entry in run_manifest.get("lineage_files_verified", []):
        if str(Path(entry["path"]).resolve()).casefold() == resolved:
            return entry
    raise ValueError(f"frozen run manifest has no hash for {target}")


def db_rows(group_ids: set[str]) -> dict[str, dict[str, Any]]:
    uri = f"file:{SIGNATURE_DB.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    result: dict[str, dict[str, Any]] = {}
    try:
        ordered = sorted(group_ids)
        for start in range(0, len(ordered), 700):
            chunk = ordered[start : start + 700]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                "SELECT group_id, episode_id, root_id, state_input_sha256, "
                "selector_model_input_sha256, candidate_ordered_sha256, "
                "family_ids_json, held_out FROM training_groups WHERE group_id IN ("
                + placeholders + ")",
                chunk,
            )
            for row in rows:
                result[str(row[0])] = {
                    "episode_id": str(row[1]),
                    "root_id": str(row[2]),
                    "state_input_sha256": str(row[3]),
                    "selector_model_input_sha256": str(row[4]),
                    "candidate_ordered_sha256": str(row[5]),
                    "family_ids": json.loads(row[6]),
                    "held_out": bool(row[7]),
                }
    finally:
        connection.close()
    return result


def overlap_values(row: dict[str, Any]) -> dict[str, set[str]]:
    found = {field: set() for field in OVERLAP_FIELDS}
    for item in row.get("overlap_keys", []):
        if not isinstance(item, str) or ":" not in item:
            continue
        prefix, value = item.split(":", 1)
        if prefix in found:
            found[prefix].add(value)
    return found


def audit_protected_metadata(
    group_records_path: Path,
    source_group_ids: set[str],
    protected_group_ids: set[str],
    protected_episode_ids: set[str],
    protected_family_ids: dict[str, set[str]],
    expected_sha256: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    wanted = source_group_ids | protected_group_ids
    found: dict[str, dict[str, Any]] = {}
    source_digest = hashlib.sha256()
    with group_records_path.open("rb") as stream:
        for line_no, raw_line in enumerate(stream, 1):
            source_digest.update(raw_line)
            line = raw_line.decode("utf-8")
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row.get("group_id")
            if group_id not in wanted:
                continue
            if group_id in found:
                raise ValueError(f"duplicate metadata record for {group_id}")
            found[group_id] = row
    actual_sha256 = source_digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("metadata-only group record source hash changed")
    missing_source = source_group_ids - found.keys()
    if missing_source:
        raise ValueError(f"source metadata lacks {len(missing_source)} R100-star groups")
    source_meta = {key: found[key] for key in source_group_ids}
    eval_meta = {key: found[key] for key in (protected_group_ids & found.keys())}

    source_episode_ids = {str(row.get("episode_id", "")) for row in source_meta.values()}
    eval_episode_ids = set(protected_episode_ids)
    source_roots = {str(row.get("root_id", "")) for row in source_meta.values()}
    eval_roots = {str(row.get("root_id", "")) for row in eval_meta.values()}
    source_families = {
        field: {str(row.get("family_ids", {}).get(field, "")) for row in source_meta.values()}
        for field in FAMILY_FIELDS
    }
    eval_families = {field: set(values) for field, values in protected_family_ids.items()}
    for field in FAMILY_FIELDS:
        eval_families.setdefault(
            field,
            {str(row.get("family_ids", {}).get(field, "")) for row in eval_meta.values()},
        )
    source_overlap = {field: set() for field in OVERLAP_FIELDS}
    eval_overlap = {field: set() for field in OVERLAP_FIELDS}
    for row in source_meta.values():
        for field, values in overlap_values(row).items():
            source_overlap[field].update(values)
    for row in eval_meta.values():
        for field, values in overlap_values(row).items():
            eval_overlap[field].update(values)
    overlap_counts = {field: len(source_overlap[field] & eval_overlap[field]) for field in OVERLAP_FIELDS}
    family_overlap_counts = {
        field: len(source_families[field] & eval_families[field])
        for field in FAMILY_FIELDS
    }
    report = {
        "source_group_count": len(source_group_ids),
        "group_metadata_sha256_recomputed": actual_sha256,
        "protected_group_id_count": len(protected_group_ids),
        "protected_group_metadata_found": len(eval_meta),
        "source_group_id_overlap": len(source_group_ids & protected_group_ids),
        "source_episode_id_overlap": len(source_episode_ids & eval_episode_ids),
        "source_root_id_overlap": len(source_roots & eval_roots),
        "source_family_id_overlap_by_field": family_overlap_counts,
        "source_exact_state_text_hash_overlap": overlap_counts["text_exact"],
        "source_schema_surface_hash_overlap": overlap_counts["schema_surface"],
        "source_model_input_hash_overlap": overlap_counts["model_input"],
        "source_group_hash_overlap": overlap_counts["group"],
        "source_episode_hash_overlap": overlap_counts["episode"],
        "available_overlap_key_types": sorted(
            field for field, count in overlap_counts.items() if count == 0
        ),
    }
    return source_meta, report


def index_text(text: str, values: list[str], indexes: dict[str, int]) -> int:
    current = indexes.get(text)
    if current is None:
        current = len(values)
        indexes[text] = current
        values.append(text)
    return current


def build_scoped_rows(
    episode_map: dict[str, dict[str, Any]],
    source_group_rows: list[dict[str, Any]],
    metadata_by_group: dict[str, dict[str, Any]],
    signature_metadata: dict[str, dict[str, Any]],
    probe: Any,
) -> tuple[list[dict[str, Any]], list[str], dict[str, list[str]]]:
    wanted = {str(row["group_id"]) for row in source_group_rows}
    wanted_episode = {str(row["episode_id"]) for row in source_group_rows}
    states: list[str] = []
    state_index: dict[str, int] = {}
    candidates: dict[str, list[str]] = {profile: [] for profile in PROFILES}
    candidate_index: dict[str, dict[str, int]] = {profile: {} for profile in PROFILES}
    output: dict[str, dict[str, Any]] = {}
    source_by_id = {str(row["group_id"]): row for row in source_group_rows}
    for episode_id in sorted(wanted_episode):
        episode = episode_map[episode_id]
        for source_group in probe.group_records([episode]):
            group_id = str(source_group["group_id"])
            if group_id not in wanted:
                continue
            source_row = source_by_id[group_id]
            if str(source_row["episode_id"]) != str(episode_id):
                raise ValueError(f"R100-star episode mismatch for {group_id}")
            signature = signature_metadata[group_id]
            if training_value_digest(source_group["state_text"]) != signature["state_input_sha256"]:
                raise ValueError(f"R100-star state input differs from sealed signature metadata: {group_id}")
            state_idx = index_text(source_group["state_text"], states, state_index)
            semantic_ids = list(source_group["candidate_semantic_ids"])
            candidate_indices: dict[str, list[int]] = {}
            name_definition_surfaces: list[str] = []
            for profile in PROFILES:
                values: list[int] = []
                for position, semantic_id in enumerate(semantic_ids):
                    candidate = source_group["candidate_descriptions"][semantic_id]
                    surface = probe.candidate_surface(candidate, position, profile)
                    if profile == "name_definition":
                        name_definition_surfaces.append(surface)
                    key = f"{semantic_id}|{surface}"
                    index = candidate_index[profile].get(key)
                    if index is None:
                        index = len(candidates[profile])
                        candidate_index[profile][key] = index
                        candidates[profile].append(surface)
                    values.append(index)
                candidate_indices[profile] = values
            surface_digest = hashlib.sha256(canonical_json(name_definition_surfaces).encode("utf-8")).hexdigest()
            if surface_digest != signature["candidate_ordered_sha256"]:
                raise ValueError(f"R100-star candidate surfaces differ from sealed signature metadata: {group_id}")
            meta = metadata_by_group[group_id]
            compact = {
                "group_id": group_id,
                "episode_id": str(source_group["episode_id"]),
                "query_id": source_group["query_id"],
                "kind": source_group["kind"],
                "view": source_group["view"],
                "state_idx": state_idx,
                "candidate_semantic_ids": semantic_ids,
                "candidate_indices": candidate_indices,
                "gold": source_group["gold"],
                "open_world": source_group["open_world"],
                "probability_source": source_group["probability_source"],
                "authority": source_group["authority"],
                "split": "train",
                "invariant_key": source_group["invariant_key"],
                "semantic_fingerprint": source_group["semantic_fingerprint"],
                "perturbation_class": source_group["perturbation_class"],
                "candidate_cardinality": source_group.get("candidate_cardinality", len(semantic_ids)),
                "root_id": meta.get("root_id"),
                "family_ids": meta.get("family_ids", {}),
                "coverage_features": meta.get("coverage_features", {}),
                "strata": meta.get("strata", {}),
            }
            if group_id in output:
                raise ValueError(f"R100-star group was produced multiple times: {group_id}")
            output[group_id] = compact
    if output.keys() != wanted:
        missing = wanted - output.keys()
        extra = output.keys() - wanted
        raise ValueError(f"scoped materialization ID mismatch: missing={len(missing)} extra={len(extra)}")
    return [output[key] for key in sorted(output)], states, candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT_DEFAULT)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f"output directory must be empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    contract = read_json(args.contract)
    contract_hash = sha256_file(args.contract)
    validate_phase_a_contract(contract)

    run_manifest_path = V08G_RUN / "v08g-run-manifest.json"
    materialization_receipt_path = V08G_MATERIALIZED / "materialization-receipt.json"
    authorization_path = V08G_RUN / "preflight" / "model-contact-authorization.json"
    run_manifest = read_json(run_manifest_path)
    materialization_receipt = read_json(materialization_receipt_path)
    authorization = read_json(authorization_path)
    if authorization.get("status") != "PASS":
        raise ValueError("v0.8G source preflight receipt is not PASS")
    if run_manifest.get("status") != "FROZEN_MODEL_CONTACT_AUTHORIZED":
        raise ValueError("v0.8G source run manifest is not the frozen source")
    if materialization_receipt.get("model_loaded") is not False:
        raise ValueError("source materialization receipt crossed a model boundary")

    frozen = run_manifest["frozen_inputs"]
    random_manifest_path = Path(frozen["R100-star"]["path"])
    eval_manifest_path = Path(frozen["NewTight-Eval"]["path"])
    legacy_paths = [Path(value["path"]) for value in frozen["legacy_protected"].values()]
    random_groups_source = V08G_MATERIALIZED / "random-groups.jsonl"
    random_groups_receipt = materialization_receipt["group_files"]["random"]
    if random_groups_receipt.get("group_count") != ARM_COUNT:
        raise ValueError("sealed random source group count is not 100,000")

    for path, expected in (
        (random_manifest_path, frozen["R100-star"]["sha256"]),
        (eval_manifest_path, frozen["NewTight-Eval"]["sha256"]),
        (random_groups_source, random_groups_receipt["sha256"]),
    ):
        if sha256_file(path) != expected:
            raise ValueError(f"sealed source hash mismatch: {path}")
    for entry in frozen["legacy_protected"].values():
        path = Path(entry["path"])
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"protected legacy ID-manifest hash mismatch: {path}")

    random_manifest = manifest_rows(random_manifest_path, ARM_COUNT)
    random_ids = {str(row["group_id"]): str(row["episode_id"]) for row in random_manifest}
    random_group_rows = list(read_jsonl(random_groups_source))
    if len(random_group_rows) != ARM_COUNT:
        raise ValueError("sealed random group file count is not 100,000")
    if {str(row["group_id"]) for row in random_group_rows} != set(random_ids):
        raise ValueError("sealed random group file differs from R100-star ID manifest")
    for row in random_group_rows:
        if str(row.get("episode_id")) != random_ids[str(row["group_id"])]:
            raise ValueError(f"random group episode mapping mismatch: {row['group_id']}")
        if row.get("split") != "train":
            raise ValueError(f"random source row is not marked train: {row['group_id']}")

    eval_rows = manifest_rows(eval_manifest_path, int(frozen["NewTight-Eval"]["group_count"]))
    legacy_rows = [
        row for path in legacy_paths
        for row in manifest_rows(path, require_unique=False)
    ]
    protected_group_ids = {str(row["group_id"]) for row in eval_rows + legacy_rows}
    protected_episode_ids = {
        str(row["episode_id"]) for row in eval_rows if row.get("episode_id")
    }
    protected_family_ids: dict[str, set[str]] = {field: set() for field in FAMILY_FIELDS}
    for row in eval_rows:
        for field, value in (row.get("held_out_family_ids") or {}).items():
            if field in protected_family_ids and value:
                protected_family_ids[field].add(str(value))

    if set(random_ids) & protected_group_ids:
        raise ValueError("R100-star source overlaps a protected group ID")
    if set(random_ids.values()) & protected_episode_ids:
        raise ValueError("R100-star source overlaps a protected episode ID")

    metadata_receipt = source_hash_record(run_manifest, GROUP_RECORDS)
    source_meta, metadata_audit = audit_protected_metadata(
        GROUP_RECORDS,
        set(random_ids),
        protected_group_ids,
        protected_episode_ids,
        protected_family_ids,
        str(metadata_receipt["sha256"]),
    )
    if metadata_audit["source_group_id_overlap"] or metadata_audit["source_episode_id_overlap"]:
        raise ValueError("metadata firewall found protected group/episode overlap")
    if metadata_audit["source_root_id_overlap"]:
        raise ValueError("metadata firewall found protected root overlap")
    if any(metadata_audit["source_family_id_overlap_by_field"].values()):
        raise ValueError("metadata firewall found protected family overlap")
    if any(metadata_audit[key] for key in (
        "source_exact_state_text_hash_overlap",
        "source_schema_surface_hash_overlap",
        "source_model_input_hash_overlap",
    )):
        raise ValueError("metadata firewall found exact protected text/schema/input overlap")

    database_receipt = source_hash_record(run_manifest, SIGNATURE_DB)
    if sha256_file(SIGNATURE_DB) != database_receipt["sha256"]:
        raise ValueError("sealed training signature database hash changed")
    source_db_metadata = db_rows(set(random_ids))
    if len(source_db_metadata) != ARM_COUNT:
        raise ValueError("sealed signature DB lacks R100-star source metadata")
    for row in random_group_rows:
        group_id = str(row["group_id"])
        db = source_db_metadata.get(group_id)
        if db is None or db["held_out"] or db["episode_id"] != random_ids[group_id]:
            raise ValueError(f"R100-star database lineage mismatch: {group_id}")

    canonical_receipt = source_hash_record(run_manifest, CANONICAL)
    if CANONICAL.stat().st_size != int(canonical_receipt.get("bytes", CANONICAL.stat().st_size)):
        raise ValueError("canonical archive size differs from frozen source receipt")
    if GROUP_RECORDS.stat().st_size != int(metadata_receipt.get("bytes", GROUP_RECORDS.stat().st_size)):
        raise ValueError("metadata archive size differs from frozen source receipt")

    wanted_episode_ids = set(random_ids.values())
    episode_map, scan_counts = selected_canonical_episodes(
        CANONICAL, wanted_episode_ids, protected_episode_ids,
    )
    source_content_hashes = {
        hashlib.sha256(
            str(episode.get("state", {}).get("observable", {}).get("content") or "").encode("utf-8")
        ).hexdigest()
        for episode in episode_map.values()
    }
    source_meta_text_hashes = {
        value
        for row in source_meta.values()
        for value in overlap_values(row)["text_exact"]
    }
    if not source_content_hashes.issubset(source_meta_text_hashes):
        raise ValueError("selected canonical state text does not match R100-star metadata fingerprints")
    probe = load_probe()
    scoped_groups, state_texts, candidate_texts = build_scoped_rows(
        episode_map, random_group_rows, source_meta, source_db_metadata, probe,
    )

    source_bank_hash = frozen["R100-star"]["sha256"]
    group_id_digest = digest_ids(random_ids)
    source_file_hashes = {
        "v08g_run_manifest": {"path": str(run_manifest_path), "sha256": sha256_file(run_manifest_path)},
        "r100_star_group_id_manifest": {"path": str(random_manifest_path), "sha256": source_bank_hash},
        "r100_star_materialized_group_rows": {"path": str(random_groups_source), "sha256": random_groups_receipt["sha256"]},
        "newtight_eval_id_manifest": {"path": str(eval_manifest_path), "sha256": frozen["NewTight-Eval"]["sha256"]},
        "group_metadata_source": {"path": str(GROUP_RECORDS), "sha256_from_frozen_manifest": metadata_receipt["sha256"], "bytes": metadata_receipt.get("bytes")},
        "canonical_episode_source": {"path": str(CANONICAL), "sha256_from_frozen_manifest": canonical_receipt["sha256"], "bytes": canonical_receipt.get("bytes")},
    }
    for label, path in (("v08g_materialization_receipt", materialization_receipt_path),
                        ("v08g_model_contact_authorization", authorization_path),
                        ("training_signature_database", SIGNATURE_DB)):
        source_file_hashes[label] = {"path": str(path), "sha256": sha256_file(path)}
    for index, path in enumerate(legacy_paths):
        source_file_hashes[f"legacy_protected_id_manifest_{index}"] = {
            "path": str(path), "sha256": frozen["legacy_protected"][list(frozen["legacy_protected"])[index]]["sha256"]
        }

    output_group_path = args.output / "random-groups.jsonl"
    output_group_hash = write_jsonl(output_group_path, scoped_groups)
    table_receipts: dict[str, dict[str, Any]] = {}
    state_path = args.output / "state-inputs.jsonl"
    state_hash = write_jsonl(
        state_path,
        ({"index": index, "text": text} for index, text in enumerate(state_texts)),
    )
    table_receipts["state_inputs"] = {
        "path": str(state_path), "sha256": state_hash, "count": len(state_texts),
        "source_scope": "training_only", "source_banks": ["R100-star"],
        "source_bank_hash": source_bank_hash, "source_row_count": ARM_COUNT,
        "contains_eval_ids": False, "contains_eval_family_ids": False, "contains_eval_text": False,
    }
    for profile in PROFILES:
        path = args.output / f"candidate-inputs-{profile}.jsonl"
        table_hash = write_jsonl(
            path,
            ({"index": index, "text": text} for index, text in enumerate(candidate_texts[profile])),
        )
        table_receipts[profile] = {
            "path": str(path), "sha256": table_hash, "count": len(candidate_texts[profile]),
            "source_scope": "training_only", "source_banks": ["R100-star"],
            "source_bank_hash": source_bank_hash, "source_row_count": ARM_COUNT,
            "contains_eval_ids": False, "contains_eval_family_ids": False, "contains_eval_text": False,
        }

    state_text_hashes = {training_value_digest(text) for text in state_texts}
    train_state_input_hashes = {row["state_input_sha256"] for row in source_db_metadata.values()}
    if not state_text_hashes.issubset(train_state_input_hashes):
        raise ValueError("scoped model-input state table is not covered by R100-star signature metadata")

    scope_receipt = {
        "protocol": "jev-information-density/v0.8i-phase-a-v02-clean",
        "status": "TRAINING_ONLY_REPRESENTATION_SCOPE_PASS",
        "identity": "phase-a-v02-clean",
        "protocol_contract_path": str(args.contract),
        "protocol_contract_sha256": contract_hash,
        "source_scope": "training_only",
        "source_bank": "R100-star",
        "source_bank_hash": source_bank_hash,
        "source_row_count": ARM_COUNT,
        "source_group_id_digest": group_id_digest,
        "source_file_hashes": source_file_hashes,
        "contains_eval_ids": False,
        "contains_eval_family_ids": False,
        "contains_eval_text": False,
        "source_lineage": {
            "group_id_count": len(random_ids),
            "episode_id_count": len(wanted_episode_ids),
            "state_input_count": len(state_texts),
            "candidate_text_counts": {key: len(value) for key, value in candidate_texts.items()},
            "state_table_text_hashes_all_derive_from_R100_star": True,
            "group_row_order": "ascending group_id",
            "text_tables_built_from": "selected R100-star canonical episodes only",
            "mixed_v08g_representation_tables_opened": False,
        },
        "protected_identity_audit": metadata_audit,
        "canonical_scan": {
            **scan_counts,
            "source_archive_sha256": canonical_receipt["sha256"],
            "source_archive_hash_recomputed": False,
            "nonselected_record_json_decoded": 0,
            "eval_text_materialized": False,
            "eval_text_hash_computed_from_bodies": False,
        },
        "group_file": {
            "path": str(output_group_path), "sha256": output_group_hash,
            "count": len(scoped_groups), "source_scope": "training_only",
            "source_banks": ["R100-star"], "source_bank_hash": source_bank_hash,
        },
        "representation_tables": table_receipts,
        "model_loaded": False,
        "model_inference": False,
        "feature_extraction": False,
        "training": False,
        "evaluation_inference": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
    }
    write_json(args.output / "scope-receipt.json", scope_receipt)
    print(json.dumps({
        "status": scope_receipt["status"],
        "group_count": len(scoped_groups),
        "unique_states": len(state_texts),
        "candidate_counts": scope_receipt["source_lineage"]["candidate_text_counts"],
        "protected_group_metadata_found": metadata_audit["protected_group_metadata_found"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
