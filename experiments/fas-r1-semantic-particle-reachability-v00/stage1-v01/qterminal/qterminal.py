"""Q_terminal data contracts and deterministic training-mixture construction.

This module never invokes a language model. Validator labels are accepted only
as offline candidate metadata and are never included in the model input map.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SPLITS = ("train", "validation", "test")
SOURCES = ("random_complete", "policy_visited")
LABEL_SOURCE = "independent_typed_validator_v1"
FEATURE_ARRAYS = (
    "feature_ids",
    "task_ids",
    "family_ids",
    "n_by_feature",
    "k_by_feature",
    "h_constraints",
    "constraint_mask",
    "h_global",
    "entity_incidence",
    "role_incidence",
)
SAMPLE_ARRAYS = (
    "assignment_feature_index",
    "assignments",
    "labels",
    "splits",
    "source_kinds",
    "family_ids",
    "feature_ids",
    "sample_ids",
)


class ContractError(ValueError):
    """An input does not satisfy the frozen Q_terminal v1 contract."""


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "R1_QTERMINAL_TRAINING_MIXTURE_V02":
        raise ContractError("unexpected mixture-manifest schema")
    return manifest


def family_split(family_id: str, manifest: dict[str, Any]) -> str:
    """Assign a family deterministically before any rendering or sampling."""
    if not family_id:
        raise ContractError("family_id must be a nonempty opaque string")
    spec = manifest["family_split"]
    payload = f"{spec['salt']}\0{family_id}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 10_000
    for split, bounds in spec["ranges"].items():
        if int(bounds[0]) <= bucket <= int(bounds[1]):
            return split
    raise ContractError(f"manifest split ranges do not cover bucket {bucket}")


def _stable_order_key(seed: int, *parts: str) -> bytes:
    payload = "\0".join((str(seed), *parts)).encode("utf-8")
    return hashlib.sha256(payload).digest()


def read_candidate_records(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    required = set(manifest["candidate_records"]["required_fields"])
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ContractError(f"candidate JSONL line {line_number}: {error}") from error
            missing = required - row.keys()
            if missing:
                raise ContractError(
                    f"candidate line {line_number} missing fields: {sorted(missing)}"
                )
            if row["schema"] != manifest["candidate_records"]["schema"]:
                raise ContractError(f"candidate line {line_number} has an unexpected schema")
            source_fields = (
                manifest["candidate_records"]["policy_fields"]["required_for_policy_visited"]
                if row.get("source_kind") == "policy_visited"
                else manifest["candidate_records"]["random_fields"]["required_for_random_complete"]
            )
            allowed = required | set(source_fields)
            extra = row.keys() - allowed
            if extra:
                raise ContractError(
                    f"candidate line {line_number} has undeclared fields: {sorted(extra)}"
                )
            sample_id = row["sample_id"]
            if not isinstance(sample_id, str) or not sample_id:
                raise ContractError(f"candidate line {line_number} has invalid sample_id")
            if sample_id in seen_ids:
                raise ContractError(f"duplicate sample_id {sample_id!r}")
            seen_ids.add(sample_id)
            if row["source_kind"] not in SOURCES:
                raise ContractError(f"unsupported source_kind on line {line_number}")
            if row["label_source"] != LABEL_SOURCE or type(row["posthoc_valid"]) is not bool:
                raise ContractError(
                    f"candidate line {line_number} lacks an exact offline validator label"
                )
            for name in ("feature_id", "task_id", "family_id"):
                if not isinstance(row[name], str) or not row[name]:
                    raise ContractError(f"candidate line {line_number} has invalid {name}")
            if not isinstance(row["assignment"], list) or not row["assignment"]:
                raise ContractError(f"candidate line {line_number} has invalid assignment")
            if row["source_kind"] == "policy_visited":
                policy_required = set(
                    manifest["candidate_records"]["policy_fields"]["required_for_policy_visited"]
                )
                if not policy_required.issubset(row):
                    raise ContractError(
                        f"policy candidate {sample_id!r} lacks required trace provenance"
                    )
                if row.get("policy_training_split") != "train":
                    raise ContractError(
                        f"policy candidate {sample_id!r} came from a non-training policy"
                    )
                if family_split(row["family_id"], manifest) != "train":
                    raise ContractError(
                        f"policy trace label {sample_id!r} is not from a training family"
                    )
                if row["policy_checkpoint_id"] != manifest["policy_trace_source"]["policy_checkpoint_id"]:
                    raise ContractError(
                        f"policy candidate {sample_id!r} uses an unfrozen visitation policy"
                    )
                if (
                    not isinstance(row["policy_trace_id"], str)
                    or not row["policy_trace_id"]
                    or type(row["trace_event_index"]) is not int
                    or row["trace_event_index"] < -1
                ):
                    raise ContractError(f"policy candidate {sample_id!r} has invalid trace coordinates")
            else:
                random_required = set(
                    manifest["candidate_records"]["random_fields"]["required_for_random_complete"]
                )
                if not random_required.issubset(row):
                    raise ContractError(
                        f"random candidate {sample_id!r} lacks sampler provenance"
                    )
                if (
                    row["random_sampler_id"]
                    != manifest["candidate_records"]["random_fields"]["random_sampler_id"]
                    or type(row["random_replicate_index"]) is not int
                    or row["random_replicate_index"] < 0
                ):
                    raise ContractError(f"random candidate {sample_id!r} has invalid sampler provenance")
            records.append(row)
    if not records:
        raise ContractError("candidate file is empty")
    return records


def load_feature_bank(
    directory: Path,
    *,
    hidden_dim: int = 2048,
    max_constraints: int = 512,
    max_entities: int = 20,
    max_roles: int = 6,
) -> dict[str, np.ndarray]:
    """Load the supplied Stage 1 extraction and adapt its flattened rows."""
    arrays, _ = load_feature_bundle(
        directory,
        hidden_dim=hidden_dim,
        max_constraints=max_constraints,
        max_entities=max_entities,
        max_roles=max_roles,
    )
    return arrays


def load_feature_bundle(
    directory: Path,
    *,
    hidden_dim: int = 2048,
    max_constraints: int = 512,
    max_entities: int = 20,
    max_roles: int = 6,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Verify and adapt `R1_STAGE1_SENSOR_EXTRACTION_V01` without model calls."""
    receipt_path = directory / "receipt.json"
    if not receipt_path.is_file():
        raise ContractError(f"expected the frozen sensor-extraction receipt at {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "R1_STAGE1_SENSOR_EXTRACTION_V01" or receipt.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE":
        raise ContractError("sensor extraction receipt is absent, incomplete, or uses another schema")
    if receipt.get("training_performed") or receipt.get("selector_training_performed"):
        raise ContractError("input receipt reports that selector training was already performed")

    output_paths: dict[str, Path] = {}
    output_hashes: dict[str, str] = {}
    for item in receipt.get("output_files", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.name != item["path"]:
            raise ContractError("sensor extraction receipt contains a nonlocal output path")
        path = directory / relative
        if not path.is_file() or path.stat().st_size != int(item["bytes"]):
            raise ContractError(f"sensor extraction output is missing or has wrong size: {item['path']}")
        actual = sha256_file(path)
        expected = str(item["sha256"]).lower()
        if actual != expected:
            raise ContractError(f"sensor extraction output hash mismatch: {item['path']}")
        output_paths[item["path"]] = path
        output_hashes[item["path"]] = actual
    required_outputs = {"constraint_H.float32.npy", "global_h.float32.npy", "rows.jsonl"}
    if set(output_paths) != required_outputs:
        raise ContractError(f"sensor extraction outputs differ from v1 schema: {sorted(output_paths)}")

    public_path = Path(receipt["input"]["path"])
    if not public_path.is_file() or sha256_file(public_path) != str(receipt["input"]["sha256"]).lower():
        raise ContractError("sensor extraction's public task input is missing or hash-mismatched")
    public_tasks = []
    with public_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                public_tasks.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ContractError(f"public task JSONL line {line_number}: {error}") from error
    expected_task_count = int(receipt["input"]["public_task_count"])
    if len(public_tasks) != expected_task_count or not public_tasks:
        raise ContractError("public task count does not match the sensor extraction receipt")
    if len({task["id"] for task in public_tasks}) != len(public_tasks):
        raise ContractError("public task IDs are not unique")

    h_constraints_raw = np.load(output_paths["constraint_H.float32.npy"], mmap_mode="r", allow_pickle=False)
    h_global_raw = np.load(output_paths["global_h.float32.npy"], mmap_mode="r", allow_pickle=False)
    if h_constraints_raw.dtype != np.float32 or h_constraints_raw.ndim != 2 or h_constraints_raw.shape[1] != hidden_dim:
        raise ContractError("constraint_H.float32.npy must be float32[R,2048]")
    if h_global_raw.dtype != np.float32 or h_global_raw.shape != (len(public_tasks), hidden_dim):
        raise ContractError("global_h.float32.npy must be float32[T,2048]")
    if h_constraints_raw.shape[0] != int(receipt["input"]["constraint_count"]):
        raise ContractError("constraint representation row count does not match receipt")

    row_path = output_paths["rows.jsonl"]
    global_rows: dict[int, dict[str, Any]] = {}
    constraint_rows: dict[int, dict[str, Any]] = {}
    constraint_row_lookup: dict[tuple[int, int], int] = {}
    sensor_splits: dict[int, str] = {}
    with row_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ContractError(f"sensor rows JSONL line {line_number}: {error}") from error
            task_index = int(row["task_index"])
            if task_index < 0 or task_index >= len(public_tasks):
                raise ContractError(f"sensor row {line_number} has an invalid task_index")
            task = public_tasks[task_index]
            if row["task_id"] != task["id"] or row["family_id"] != task["family_id"]:
                raise ContractError(f"sensor row {line_number} does not match public-task order")
            prior_split = sensor_splits.setdefault(task_index, row["split"])
            if prior_split != row["split"]:
                raise ContractError(f"sensor split changes inside task {task['id']}")
            row_index = int(row["row"])
            if row["kind"] == "global":
                if row_index in global_rows or row_index != task_index:
                    raise ContractError("global output row index is duplicated or misaligned")
                global_rows[row_index] = row
                text = task["global_text"]
                expected_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if expected_text_hash != row["input_text_sha256"]:
                    raise ContractError("global embedding row does not match its public input text")
                raw_vector_hash = hashlib.sha256(
                    np.asarray(h_global_raw[row_index], dtype="<f4").tobytes()
                ).hexdigest()
                if raw_vector_hash != row["output_float32_sha256"]:
                    raise ContractError("global embedding row does not match its recorded vector hash")
            elif row["kind"] == "constraint":
                clause_index = int(row["clause_index"])
                if row_index in constraint_rows:
                    raise ContractError("constraint output row index is duplicated")
                if clause_index < 0 or clause_index >= len(task["clauses"]):
                    raise ContractError("constraint row clause_index is outside its public task")
                constraint_rows[row_index] = row
                key = (task_index, clause_index)
                if key in constraint_row_lookup:
                    raise ContractError("duplicate encoded clause for a public task")
                constraint_row_lookup[key] = row_index
                text = task["clauses"][clause_index]
                expected_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if expected_text_hash != row["input_text_sha256"]:
                    raise ContractError("constraint embedding row does not match its public clause")
                raw_vector_hash = hashlib.sha256(
                    np.asarray(h_constraints_raw[row_index], dtype="<f4").tobytes()
                ).hexdigest()
                if raw_vector_hash != row["output_float32_sha256"]:
                    raise ContractError("constraint embedding row does not match its recorded vector hash")
            else:
                raise ContractError(f"sensor row {line_number} has unknown kind {row['kind']!r}")
    if set(global_rows) != set(range(len(public_tasks))):
        raise ContractError("global rows do not cover each public task exactly once")
    if set(constraint_rows) != set(range(h_constraints_raw.shape[0])):
        raise ContractError("constraint rows do not cover each encoded clause exactly once")

    max_n = max(int(task["n"]) for task in public_tasks)
    max_k = max(int(task["k"]) for task in public_tasks)
    # Keep one explicit masked slot for worlds with an empty constraint set.
    max_m = max(1, max(len(task["clauses"]) for task in public_tasks))
    if max_n > max_entities or max_k > max_roles or max_m > max_constraints:
        raise ContractError("extracted public tasks exceed the frozen Q_terminal feature support")
    h_constraints = np.zeros((len(public_tasks), max_m, hidden_dim), dtype=np.float32)
    constraint_mask = np.zeros((len(public_tasks), max_m), dtype=np.bool_)
    entity_incidence = np.zeros((len(public_tasks), max_m, max_entities), dtype=np.bool_)
    role_incidence = np.zeros((len(public_tasks), max_m, max_roles), dtype=np.bool_)
    h_global = np.asarray(h_global_raw, dtype=np.float32)
    n_by_feature = np.empty(len(public_tasks), dtype=np.uint16)
    k_by_feature = np.empty(len(public_tasks), dtype=np.uint8)
    for task_index, task in enumerate(public_tasks):
        global_row = global_rows[task_index]
        if int(global_row["task_index"]) != task_index:
            raise ContractError("global task index is misaligned")
        clauses = task["clauses"]
        entity_mentions = task["entity_mentions"]
        role_mentions = task["role_mentions"]
        if not (len(clauses) == len(entity_mentions) == len(role_mentions)):
            raise ContractError(f"public incidence does not align with clauses for {task['id']}")
        n_value = int(task["n"])
        k_value = int(task["k"])
        if n_value > max_entities or k_value > max_roles:
            raise ContractError("public task shape exceeds the fixed feature support")
        n_by_feature[task_index] = n_value
        k_by_feature[task_index] = k_value
        for clause_index in range(len(clauses)):
            encoded_row = constraint_row_lookup.get((task_index, clause_index))
            if encoded_row is None:
                raise ContractError(f"expected one extracted vector for {task['id']} clause {clause_index}")
            h_constraints[task_index, clause_index] = h_constraints_raw[encoded_row]
            constraint_mask[task_index, clause_index] = True
            for entity in entity_mentions[clause_index]:
                entity = int(entity)
                if entity < 0 or entity >= n_value:
                    raise ContractError("public entity incidence is outside the task entity range")
                entity_incidence[task_index, clause_index, entity] = True
            for role in role_mentions[clause_index]:
                role = int(role)
                if role < 0 or role >= k_value:
                    raise ContractError("public role incidence is outside the task role range")
                role_incidence[task_index, clause_index, role] = True

    observed_sensor_splits: dict[str, int] = {}
    family_sensor_splits: dict[str, str] = {}
    for task_index, task in enumerate(public_tasks):
        split = sensor_splits[task_index]
        observed_sensor_splits[split] = observed_sensor_splits.get(split, 0) + 1
        previous = family_sensor_splits.setdefault(task["family_id"], split)
        if previous != split:
            raise ContractError("sensor extraction split is inconsistent within a family")
    expected_sensor_splits = receipt["input"]["support_manifest"]["split_counts"]
    if observed_sensor_splits != expected_sensor_splits:
        raise ContractError("sensor extraction split counts differ from its support manifest")

    feature_ids = np.asarray([task["id"] for task in public_tasks], dtype="U128")
    task_ids = feature_ids.copy()
    family_ids = np.asarray([task["family_id"] for task in public_tasks], dtype="U128")
    arrays = {
        "feature_ids": feature_ids,
        "task_ids": task_ids,
        "family_ids": family_ids,
        "n_by_feature": n_by_feature,
        "k_by_feature": k_by_feature,
        "h_constraints": h_constraints,
        "constraint_mask": constraint_mask,
        "h_global": h_global,
        "entity_incidence": entity_incidence,
        "role_incidence": role_incidence,
    }
    validate_feature_bank(
        arrays,
        hidden_dim=hidden_dim,
        max_constraints=max_constraints,
        max_entities=max_entities,
        max_roles=max_roles,
    )
    support_path = Path(receipt["input"]["support_manifest"]["path"])
    model_manifest_path = Path(receipt["model"]["model_contact_manifest"]["path"])
    for path, expected, label in (
        (support_path, receipt["input"]["support_manifest"]["sha256"], "sensor support manifest"),
        (model_manifest_path, receipt["model"]["model_contact_manifest"]["sha256"], "model contact manifest"),
    ):
        if not path.is_file() or sha256_file(path) != str(expected).lower():
            raise ContractError(f"{label} is missing or hash-mismatched")
    provenance = {
        "schema": receipt["schema"],
        "extraction_directory": str(directory.resolve()),
        "extraction_receipt_sha256": sha256_file(receipt_path),
        "constraint_H_sha256": output_hashes["constraint_H.float32.npy"],
        "global_h_sha256": output_hashes["global_h.float32.npy"],
        "rows_jsonl_sha256": output_hashes["rows.jsonl"],
        "public_tasks_path": str(public_path.resolve()),
        "public_tasks_sha256": str(receipt["input"]["sha256"]).lower(),
        "sensor_support_manifest_path": str(support_path.resolve()),
        "sensor_support_manifest_sha256": str(receipt["input"]["support_manifest"]["sha256"]).lower(),
        "model_contact_manifest_path": str(model_manifest_path.resolve()),
        "model_contact_manifest_sha256": str(receipt["model"]["model_contact_manifest"]["sha256"]).lower(),
        "model_repo_id": receipt["model"]["repo_id"],
        "model_revision": receipt["model"]["revision"],
        "hidden_size": hidden_dim,
        "input_text_sha256": receipt["extraction"]["verification"]["input_text_sha256"],
        "repeat_feature_sha256": receipt["extraction"]["verification"]["repeat_1_output_float32_sha256"],
        "task_count": len(public_tasks),
        "constraint_count": int(h_constraints_raw.shape[0]),
        "sensor_split_counts": receipt["input"]["support_manifest"]["split_counts"],
    }
    return arrays, provenance


def validate_feature_bank(
    arrays: dict[str, np.ndarray],
    *,
    hidden_dim: int = 2048,
    max_constraints: int = 512,
    max_entities: int = 20,
    max_roles: int = 6,
) -> None:
    missing = set(FEATURE_ARRAYS) - arrays.keys()
    extra = arrays.keys() - set(FEATURE_ARRAYS)
    if missing or extra:
        raise ContractError(f"feature keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    feature_ids = arrays["feature_ids"]
    if feature_ids.ndim != 1 or feature_ids.dtype.kind not in "US":
        raise ContractError("feature_ids must be a one-dimensional non-object string array")
    count = len(feature_ids)
    if count == 0 or len(set(feature_ids.tolist())) != count:
        raise ContractError("feature_ids must be nonempty and unique")
    for name in ("task_ids", "family_ids"):
        values = arrays[name]
        if values.shape != (count,) or values.dtype.kind not in "US":
            raise ContractError(f"{name} must be a string vector aligned with feature_ids")
        if any(not value for value in values.tolist()):
            raise ContractError(f"{name} contains an empty ID")
    n_values = arrays["n_by_feature"]
    k_values = arrays["k_by_feature"]
    if n_values.shape != (count,) or n_values.dtype.kind not in "iu":
        raise ContractError("n_by_feature must be an integer vector aligned with feature_ids")
    if k_values.shape != (count,) or k_values.dtype.kind not in "iu":
        raise ContractError("k_by_feature must be an integer vector aligned with feature_ids")
    if np.any(n_values < 1) or np.any(n_values > max_entities):
        raise ContractError("entity count is outside the frozen support; do not truncate")
    if np.any(k_values < 1) or np.any(k_values > max_roles):
        raise ContractError("role count is outside the frozen support; do not truncate")

    h = arrays["h_constraints"]
    global_h = arrays["h_global"]
    mask = arrays["constraint_mask"]
    entity_inc = arrays["entity_incidence"]
    role_inc = arrays["role_incidence"]
    if h.ndim != 3 or h.shape[0] != count or h.shape[1] > max_constraints or h.shape[2] != hidden_dim:
        raise ContractError("h_constraints must have shape [T,M,D] within the frozen support")
    if h.dtype != np.float32:
        raise ContractError("h_constraints must contain float32 values")
    if global_h.shape != (count, hidden_dim) or global_h.dtype != np.float32:
        raise ContractError("h_global must have shape [T,D] and dtype float32")
    for begin in range(0, count, 8):
        end = min(count, begin + 8)
        if not np.isfinite(global_h[begin:end]).all():
            raise ContractError("h_global contains non-finite values")
    if mask.shape != h.shape[:2] or mask.dtype != np.bool_:
        raise ContractError("constraint_mask must be bool[T,M]")
    if entity_inc.shape != (*h.shape[:2], max_entities) or entity_inc.dtype != np.bool_:
        raise ContractError("entity_incidence must be bool[T,M,max_entities]")
    if role_inc.shape != (*h.shape[:2], max_roles) or role_inc.dtype != np.bool_:
        raise ContractError("role_incidence must be bool[T,M,max_roles]")
    for begin in range(0, count, 8):
        end = min(count, begin + 8)
        mask_chunk = mask[begin:end]
        h_chunk = h[begin:end]
        entity_chunk = entity_inc[begin:end]
        role_chunk = role_inc[begin:end]
        if not np.isfinite(h_chunk).all():
            raise ContractError("h_constraints contains non-finite values")
        if np.any((~mask_chunk[:, :-1]) & mask_chunk[:, 1:]):
            raise ContractError("constraint rows must be left-packed before padding")
        if np.any(h_chunk[~mask_chunk] != 0):
            raise ContractError("padded constraint embeddings must be exactly zero")
        if np.any(entity_chunk[~mask_chunk]) or np.any(role_chunk[~mask_chunk]):
            raise ContractError("incidence masks must be false on padded constraints")
        for offset, (n_value, k_value) in enumerate(
            zip(n_values[begin:end], k_values[begin:end], strict=True)
        ):
            if np.any(entity_chunk[offset, :, int(n_value) :]):
                raise ContractError("entity incidence is true beyond a task's public entity count")
            if np.any(role_chunk[offset, :, int(k_value) :]):
                raise ContractError("role incidence is true beyond a task's public role count")


def select_balanced_mixture(
    records: Iterable[dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic, family-disjoint, exactly balanced sample rows."""
    feature_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in records:
        pair = (row["feature_id"], row["source_kind"])
        assignment_key = ",".join(str(value) for value in row["assignment"])
        dedupe_key = (pair[0], pair[1], assignment_key)
        if dedupe_key not in feature_rows:
            feature_rows[dedupe_key] = row
        else:
            current = feature_rows[dedupe_key]
            current_visit = int(current.get("trace_event_index", 2**63 - 1))
            next_visit = int(row.get("trace_event_index", 2**63 - 1))
            if (next_visit, row["sample_id"]) < (current_visit, current["sample_id"]):
                feature_rows[dedupe_key] = row

    by_split_cell_family: dict[tuple[str, str, int, str], list[dict[str, Any]]] = {}
    for row in feature_rows.values():
        split = family_split(row["family_id"], manifest)
        label = int(row["posthoc_valid"])
        key = (split, row["source_kind"], label, row["family_id"])
        by_split_cell_family.setdefault(key, []).append(row)

    cap = int(manifest["mixture"]["per_family_per_cell_cap"])
    seed = int(manifest["mixture"]["sampling_seed"])
    max_cell = int(manifest["mixture"]["maximum_rows_per_cell_per_split"])
    output: dict[str, list[dict[str, Any]]] = {}
    for split in SPLITS:
        eligible_sources = SOURCES if split == "train" else ("random_complete",)
        cells: dict[tuple[str, int], list[dict[str, Any]]] = {
            (source, label): [] for source in eligible_sources for label in (0, 1)
        }
        for (row_split, source, label, family), family_rows in by_split_cell_family.items():
            if row_split != split:
                continue
            ordered = sorted(
                family_rows,
                key=lambda row: _stable_order_key(
                    seed, split, source, str(label), family, row["sample_id"]
                ),
            )
            cells[(source, label)].extend(ordered[:cap])
        sizes = {cell: len(rows) for cell, rows in cells.items()}
        target = min(min(sizes.values()), max_cell)
        if target == 0:
            raise ContractError(
                f"{split} split cannot form its frozen balanced mixture; cell sizes={sizes}"
            )
        selected: list[dict[str, Any]] = []
        for (source, label), rows in cells.items():
            ordered = sorted(
                rows,
                key=lambda row: _stable_order_key(
                    seed, split, source, str(label), row["family_id"], row["sample_id"]
                ),
            )
            selected.extend(ordered[:target])
        selected.sort(
            key=lambda row: (
                SOURCES.index(row["source_kind"]),
                int(row["posthoc_valid"]),
                _stable_order_key(seed, split, row["family_id"], row["sample_id"]),
            )
        )
        output[split] = [dict(row, split=split) for row in selected]
    return output


def prepare_dataset(
    candidate_path: Path,
    feature_dir: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate and materialize the frozen mixture without fitting a model."""
    if output_dir.exists():
        raise ContractError(f"output directory already exists: {output_dir}")
    manifest = load_manifest(manifest_path)
    features, feature_source = load_feature_bundle(
        feature_dir,
        hidden_dim=int(manifest["feature_input"]["h_global"].split(",")[-1].split("]")[0]),
        max_constraints=int(manifest["feature_input"]["max_constraints"]),
        max_entities=int(manifest["feature_input"]["max_entities"]),
        max_roles=int(manifest["feature_input"]["max_roles"]),
    )
    feature_lookup = {value: index for index, value in enumerate(features["feature_ids"].tolist())}
    feature_meta: dict[str, tuple[str, str, int, int]] = {}
    for index, feature_id in enumerate(features["feature_ids"].tolist()):
        feature_meta[feature_id] = (
            str(features["task_ids"][index]),
            str(features["family_ids"][index]),
            int(features["n_by_feature"][index]),
            int(features["k_by_feature"][index]),
        )

    records = read_candidate_records(candidate_path, manifest)
    for row in records:
        if row["feature_id"] not in feature_lookup:
            raise ContractError(f"candidate references missing feature {row['feature_id']!r}")
        task_id, family_id, n_value, k_value = feature_meta[row["feature_id"]]
        if (row["task_id"], row["family_id"]) != (task_id, family_id):
            raise ContractError(f"candidate/feature identity mismatch for {row['sample_id']!r}")
        assignment = row["assignment"]
        if len(assignment) != n_value:
            raise ContractError(f"candidate {row['sample_id']!r} is not a complete assignment")
        if any(type(role) is not int or role < 0 or role >= k_value for role in assignment):
            raise ContractError(f"candidate {row['sample_id']!r} has an invalid role ID")

    selected = select_balanced_mixture(records, manifest)
    output_dir.mkdir(parents=True)
    max_entities = int(manifest["feature_input"]["max_entities"])
    sample_count = sum(len(rows) for rows in selected.values())
    assignments = np.full((sample_count, max_entities), 255, dtype=np.uint8)
    feature_indices = np.empty(sample_count, dtype=np.uint32)
    labels = np.empty(sample_count, dtype=np.uint8)
    split_values = np.empty(sample_count, dtype="U10")
    source_values = np.empty(sample_count, dtype="U20")
    family_width = max(len(row["family_id"]) for rows in selected.values() for row in rows)
    feature_width = max(len(row["feature_id"]) for rows in selected.values() for row in rows)
    sample_width = max(len(row["sample_id"]) for rows in selected.values() for row in rows)
    family_values = np.empty(sample_count, dtype=f"U{family_width}")
    feature_values = np.empty(sample_count, dtype=f"U{feature_width}")
    sample_values = np.empty(sample_count, dtype=f"U{sample_width}")
    selected_path = output_dir / "selected-candidates.jsonl"
    counts: dict[str, dict[str, int]] = {}
    index = 0
    with selected_path.open("w", encoding="utf-8", newline="\n") as stream:
        for split in SPLITS:
            rows = selected[split]
            counts[split] = {
                f"{source}:valid={label}": 0
                for source in (SOURCES if split == "train" else ("random_complete",))
                for label in (0, 1)
            }
            for row in rows:
                assignment = np.asarray(row["assignment"], dtype=np.uint8)
                assignments[index, : len(assignment)] = assignment
                feature_indices[index] = feature_lookup[row["feature_id"]]
                labels[index] = int(row["posthoc_valid"])
                split_values[index] = split
                source_values[index] = row["source_kind"]
                family_values[index] = row["family_id"]
                feature_values[index] = row["feature_id"]
                sample_values[index] = row["sample_id"]
                counts[split][f"{row['source_kind']}:valid={int(row['posthoc_valid'])}"] += 1
                safe_row = {
                    "schema": "R1_QTERMINAL_SELECTED_CANDIDATE_V01",
                    "sample_id": row["sample_id"],
                    "feature_id": row["feature_id"],
                    "task_id": row["task_id"],
                    "family_id": row["family_id"],
                    "split": split,
                    "source_kind": row["source_kind"],
                    "assignment": row["assignment"],
                    "posthoc_valid": row["posthoc_valid"],
                    "label_source": row["label_source"],
                }
                if row["source_kind"] == "policy_visited":
                    safe_row.update(
                        policy_checkpoint_id=row["policy_checkpoint_id"],
                        policy_training_split=row["policy_training_split"],
                        policy_trace_id=row["policy_trace_id"],
                        trace_event_index=row["trace_event_index"],
                    )
                else:
                    safe_row.update(
                        random_sampler_id=row["random_sampler_id"],
                        random_replicate_index=row["random_replicate_index"],
                    )
                stream.write(json.dumps(safe_row, sort_keys=True, separators=(",", ":")) + "\n")
                index += 1

    arrays = {
        "assignment_feature_index": feature_indices,
        "assignments": assignments,
        "labels": labels,
        "splits": split_values,
        "source_kinds": source_values,
        "family_ids": family_values,
        "feature_ids": feature_values,
        "sample_ids": sample_values,
    }
    for name, value in arrays.items():
        np.save(output_dir / f"{name}.npy", value, allow_pickle=False)

    manifest_hash = sha256_file(manifest_path)
    candidate_hash = sha256_file(candidate_path)
    sample_hashes = {
        name: sha256_file(output_dir / f"{name}.npy") for name in SAMPLE_ARRAYS
    }
    prepared = {
        "schema": "R1_QTERMINAL_PREPARED_DATASET_V01",
        "mixture_manifest_sha256": manifest_hash,
        "candidate_jsonl_sha256": candidate_hash,
        "selected_candidates_sha256": sha256_file(selected_path),
        "sample_array_sha256": sample_hashes,
        "feature_source": feature_source,
        "feature_directory": str(feature_dir.resolve()),
        "row_count": sample_count,
        "split_counts": {split: len(selected[split]) for split in SPLITS},
        "cell_counts": counts,
        "cell_weights": {
            "train": {cell: 0.25 for cell in counts["train"]},
            "validation": {cell: 0.5 for cell in counts["validation"]},
            "test": {cell: 0.5 for cell in counts["test"]},
        },
        "families_disjoint_across_splits": True,
        "policy_visited_candidates_from_training_families_only": True,
        "validator_labels_are_offline_supervision_only": True,
        "model_contact_or_training_performed": False,
    }
    (output_dir / "dataset-manifest.json").write_text(
        json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return prepared


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_sample_arrays(dataset_dir: Path) -> dict[str, np.ndarray]:
    arrays = {
        name: np.load(dataset_dir / f"{name}.npy", mmap_mode="r", allow_pickle=False)
        for name in SAMPLE_ARRAYS
    }
    lengths = {len(values) for values in arrays.values()}
    if len(lengths) != 1:
        raise ContractError("prepared sample arrays have inconsistent row counts")
    if arrays["assignments"].ndim != 2 or arrays["assignments"].dtype != np.uint8:
        raise ContractError("assignments must be a uint8 matrix with sentinel padding")
    if arrays["labels"].dtype != np.uint8 or np.any(arrays["labels"] > 1):
        raise ContractError("labels must be binary uint8 offline validator targets")
    if not set(arrays["splits"].tolist()).issubset(SPLITS):
        raise ContractError("prepared dataset contains an unknown split")
    return arrays


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
