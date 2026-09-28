from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F


DIMENSION = 2_048
CHUNK_ROWS = 2_048
MINIMUM_ROWS_PER_CLASS = 200
PERFORMANCE_FLOOR = 0.90
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 2_026_092_604
BOOTSTRAP_CHUNK_REPLICATES = 64
BOOTSTRAP_ALPHA = 0.00625
ENDPOINT_ORDER = (
    "context_identity",
    "entity_identity",
    "relation",
    "observed_state",
    "exact_target_in_domain",
    "exact_target_context_novel",
    "exact_target_entity_novel",
    "exact_target_both_novel",
)
QUARTET_VARIANTS = ("A", "C", "E", "P")
PRIMARY_SURFACE = "PRIMARY_SEEN"
PRIMARY_TRUTH_PARTITION = "PRIMARY_TERMINAL"
TEMPLATE_TRUTH_PARTITION = "TEMPLATE_ESCROW"
_TORCH_CPU_CONFIGURED = False

TASKS: dict[str, tuple[str, int, str]] = {
    "context_identity": ("context_term_id", 32, "all"),
    "entity_identity": ("entity_term_id", 32, "all"),
    "relation": ("relation_id", 2, "both_terms_train_side"),
    "observed_state": ("state_id", 3, "both_terms_train_side"),
    "exact_target": ("exact_target", 3, "all"),
}
TARGET_ENDPOINTS = {
    "IN_DOMAIN": "exact_target_in_domain",
    "CONTEXT_NOVEL": "exact_target_context_novel",
    "ENTITY_NOVEL": "exact_target_entity_novel",
    "BOTH_NOVEL": "exact_target_both_novel",
}
AUTH_SCHEMA = "FAS_E4_0_STAGE_AUTH_V01"
AUTH_FIELDS = {
    "schema", "authorization_id", "status", "stage", "contract_sha256",
    "contract_seal_manifest_sha256", "contract_seal_root_sha256",
    "exact_predecessor_roots", "output_root", "scope", "authorized_by",
    "issued_utc_unix_seconds", "valid_from_utc_unix_seconds", "valid_until_utc_unix_seconds",
}
SCORING_AUTH_SCOPE = {
    "population_generation": False,
    "tokenizer_contact": False,
    "model_contact": False,
    "feature_extraction": False,
    "evaluation_label_opening": True,
    "scoring": True,
    "fitting": False,
    "e4_a": False,
    "heldout_template_label_opening": False,
    "joint_template_label_opening": False,
}
SCORING_PREDECESSOR_ROOT_KEYS = (
    "e0_v10_root_sha256",
    "e1_v04_root_sha256",
    "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256",
    "e4_population_root_sha256",
    "e4_population_audit_root_sha256",
    "e4_parity_panel_root_sha256",
    "e4_parity_receipt_root_sha256",
    "e4_feature_cache_root_sha256",
)


@dataclass(frozen=True)
class LinearHead:
    task: str
    class_count: int
    mean: np.ndarray
    scale: np.ndarray
    weight: np.ndarray
    bias: np.ndarray


@dataclass(frozen=True)
class EndpointData:
    labels: np.ndarray
    predictions: np.ndarray
    quartet_ids: tuple[str, ...]
    quartet_strata: tuple[int, ...]
    class_count: int


@dataclass(frozen=True)
class ScoringAuthIdentity:
    contract_sha256: str
    contract_seal_manifest_sha256: str
    contract_seal_root_sha256: str
    exact_predecessor_roots: Mapping[str, str]
    output_root: str


class OneShotPrimaryLabelReader:
    """Single-open primary label reader that checks stage auth before opening bytes."""

    def __init__(
        self,
        label_path: Path,
        *,
        expected_sha256: str,
        expected_bytes: int,
        expected_rows: int,
    ) -> None:
        self.label_path = label_path
        self.expected_sha256 = expected_sha256
        self.expected_bytes = expected_bytes
        self.expected_rows = expected_rows
        self.attempted = False
        self.last_attempt_receipt: dict[str, Any] = {
            "label_file_open_count": 0,
            "semantic_label_open_count": 0,
            "label_bytes_read": 0,
            "label_rows_parsed": 0,
            "label_partial_sha256": None,
        }

    def read_once(
        self,
        authorization: Mapping[str, Any],
        expected_identity: ScoringAuthIdentity,
        *,
        now_unix_seconds: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.attempted:
            raise RuntimeError("primary terminal label stream is one-shot; second open refused")
        validate_scoring_authorization(
            authorization,
            expected_identity,
            now_unix_seconds=now_unix_seconds,
        )
        self.attempted = True
        self.last_attempt_receipt["label_file_open_count"] = 1
        self.last_attempt_receipt["semantic_label_open_count"] = 1
        digest = hashlib.sha256()
        bytes_read = 0
        rows: list[dict[str, Any]] = []
        with self.label_path.open("rb", buffering=0) as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                digest.update(raw_line)
                bytes_read += len(raw_line)
                self.last_attempt_receipt.update({
                    "label_bytes_read": bytes_read,
                    "label_rows_parsed": len(rows),
                    "label_partial_sha256": digest.hexdigest(),
                })
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError(f"invalid primary terminal JSONL at line {line_number}") from error
                if not isinstance(record, dict):
                    raise RuntimeError(f"primary terminal row is not an object at line {line_number}")
                rows.append(record)
                self.last_attempt_receipt["label_rows_parsed"] = len(rows)
        observed_sha256 = digest.hexdigest()
        if bytes_read != self.expected_bytes or observed_sha256 != self.expected_sha256:
            raise RuntimeError("single-open primary terminal labels differ from the sealed population identity")
        if len(rows) != self.expected_rows:
            raise RuntimeError("primary terminal label row count differs from the sealed row manifest")
        self.last_attempt_receipt["label_partial_sha256"] = observed_sha256
        receipt = {
            "label_file_open_count": 1,
            "semantic_label_open_count": 1,
            "label_rows": len(rows),
            "label_bytes": bytes_read,
            "label_sha256": observed_sha256,
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
        }
        return rows, receipt


def validate_scoring_authorization(
    authorization: Mapping[str, Any],
    expected: ScoringAuthIdentity,
    *,
    now_unix_seconds: int | None = None,
) -> None:
    """Fail closed on any scoring-auth scope, identity, or validity mismatch."""
    if set(authorization) != AUTH_FIELDS:
        raise RuntimeError("E4 stage authorization fields differ from the frozen schema")
    if authorization.get("schema") != AUTH_SCHEMA:
        raise RuntimeError("unsupported E4 stage authorization schema")
    if authorization.get("status") != "AUTHORIZED" or authorization.get("stage") != "FRESH_SCORING":
        raise RuntimeError("E4 fresh scoring authorization is absent or names another stage")
    if not isinstance(authorization.get("authorization_id"), str) or not authorization["authorization_id"]:
        raise RuntimeError("E4 scoring authorization lacks an identity")
    if authorization.get("authorized_by") != "ACTIVE_USER_REQUEST":
        raise RuntimeError("E4 scoring authorization lacks the required user authority")
    if authorization.get("contract_sha256") != expected.contract_sha256:
        raise RuntimeError("E4 scoring authorization contract hash mismatch")
    if authorization.get("contract_seal_manifest_sha256") != expected.contract_seal_manifest_sha256:
        raise RuntimeError("E4 scoring authorization seal-manifest hash mismatch")
    if authorization.get("contract_seal_root_sha256") != expected.contract_seal_root_sha256:
        raise RuntimeError("E4 scoring authorization contract root mismatch")
    actual_roots = authorization.get("exact_predecessor_roots")
    if not isinstance(actual_roots, Mapping) or set(actual_roots) != set(SCORING_PREDECESSOR_ROOT_KEYS):
        raise RuntimeError("E4 scoring authorization predecessor-root set is incomplete or broader")
    if dict(actual_roots) != dict(expected.exact_predecessor_roots):
        raise RuntimeError("E4 scoring authorization predecessor roots mismatch")
    if set(expected.exact_predecessor_roots) != set(SCORING_PREDECESSOR_ROOT_KEYS):
        raise RuntimeError("expected E4 scoring predecessor roots are incomplete")
    if authorization.get("output_root") != expected.output_root:
        raise RuntimeError("E4 scoring authorization output root mismatch")
    scope = authorization.get("scope")
    if not isinstance(scope, Mapping) or dict(scope) != SCORING_AUTH_SCOPE:
        raise RuntimeError("E4 scoring authorization scope is broader or narrower than the frozen stage")
    issued = authorization.get("issued_utc_unix_seconds")
    valid_from = authorization.get("valid_from_utc_unix_seconds")
    valid_until = authorization.get("valid_until_utc_unix_seconds")
    for name, value in (("issued", issued), ("valid_from", valid_from), ("valid_until", valid_until)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError(f"E4 scoring authorization {name} time is malformed")
    now = int(datetime.now(timezone.utc).timestamp()) if now_unix_seconds is None else now_unix_seconds
    if isinstance(now, bool) or not isinstance(now, int):
        raise RuntimeError("E4 scoring clock value is malformed")
    if issued > valid_from or valid_from >= valid_until or valid_from > now or now > valid_until:
        raise RuntimeError("E4 scoring authorization is outside its frozen UTC validity interval")


def _integer(value: Any, field: str, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise RuntimeError(f"{field} must be an integer class ID")
    result = int(value)
    if not lower <= result < upper:
        raise RuntimeError(f"{field} is outside its frozen class range")
    return result


def target_stratum(context_id: int, entity_id: int) -> str:
    return {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(context_id >= 16, entity_id >= 16)]


def validate_primary_manifest(manifest: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate the complete row map and return only the primary rows."""
    if not manifest:
        raise RuntimeError("E4 row manifest is empty")
    primary: list[dict[str, Any]] = []
    row_ids: set[str] = set()
    quartets: dict[str, list[str]] = {}
    for expected_index, raw in enumerate(manifest):
        row = dict(raw)
        if row.get("row_index") != expected_index:
            raise RuntimeError("E4 row manifest indices are not contiguous and ordered")
        for field in ("row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise RuntimeError(f"E4 row manifest lacks a valid {field}")
        if row["row_id"] in row_ids:
            raise RuntimeError(f"duplicate E4 row identity: {row['row_id']}")
        row_ids.add(row["row_id"])
        surface, partition = row["surface_id"], row["truth_partition"]
        if (surface, partition) == (PRIMARY_SURFACE, PRIMARY_TRUTH_PARTITION):
            primary.append(row)
            quartets.setdefault(row["quartet_id"], []).append(row["variant_id"])
        elif (surface, partition) == ("HELDOUT_TEMPLATE", TEMPLATE_TRUTH_PARTITION):
            continue
        else:
            raise RuntimeError(f"unrecognized E4 truth custody pair: {surface}/{partition}")
    if not primary:
        raise RuntimeError("E4 manifest has no primary terminal rows")
    for quartet, variants in quartets.items():
        if tuple(variants) != QUARTET_VARIANTS:
            raise RuntimeError(f"primary quartet is incomplete or misordered: {quartet}")
    return primary


def load_frozen_heads(e3_root: Path) -> dict[str, LinearHead]:
    """Load the five existing E3 heads read-only; this function never fits."""
    heads: dict[str, LinearHead] = {}
    for task, (_field, class_count, _scope) in TASKS.items():
        mean = np.fromfile(e3_root / f"{task}.mean.f32le", dtype="<f4")
        scale = np.fromfile(e3_root / f"{task}.scale.f32le", dtype="<f4")
        weight = np.fromfile(e3_root / f"{task}.weight.f32le", dtype="<f4")
        bias = np.fromfile(e3_root / f"{task}.bias.f32le", dtype="<f4")
        if mean.size != DIMENSION or scale.size != DIMENSION:
            raise RuntimeError(f"frozen {task} scaler has the wrong dimension")
        if weight.size != class_count * DIMENSION or bias.size != class_count:
            raise RuntimeError(f"frozen {task} head has the wrong shape")
        weight = weight.reshape(class_count, DIMENSION)
        if not all(np.isfinite(values).all() for values in (mean, scale, weight, bias)):
            raise RuntimeError(f"frozen {task} observer contains a non-finite value")
        if np.any(scale == 0):
            raise RuntimeError(f"frozen {task} observer has a zero scaler entry")
        heads[task] = LinearHead(task, class_count, mean, scale, weight, bias)
    return heads


def predict_primary_rows(
    feature_cache: np.ndarray,
    manifest: Sequence[Mapping[str, Any]],
    heads: Mapping[str, LinearHead],
    batch_rows: int = CHUNK_ROWS,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    """Infer only over PRIMARY_TERMINAL rows, preserving manifest order."""
    if torch.cuda.is_initialized():
        raise RuntimeError("fresh E4 scoring requires CPU inference; CUDA was already initialized")
    if set(heads) != set(TASKS):
        raise RuntimeError("exactly the five frozen E3 heads are required")
    if isinstance(batch_rows, bool) or not isinstance(batch_rows, int) or batch_rows < 1:
        raise RuntimeError("invalid CPU inference batch size")
    primary = validate_primary_manifest(manifest)
    if feature_cache.ndim != 2 or feature_cache.shape != (len(manifest), DIMENSION):
        raise RuntimeError("E4 feature cache shape differs from the full row manifest")
    if np.dtype(feature_cache.dtype) != np.dtype("<f4"):
        raise RuntimeError("E4 feature cache dtype is not little-endian float32")
    selected = np.asarray([row["row_index"] for row in primary], dtype=np.int64)
    global _TORCH_CPU_CONFIGURED
    if not _TORCH_CPU_CONFIGURED:
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        _TORCH_CPU_CONFIGURED = True
    predictions: dict[str, np.ndarray] = {}
    for task, head in heads.items():
        if head.task != task or head.class_count != TASKS[task][1]:
            raise RuntimeError(f"frozen head identity mismatch for {task}")
        mean = torch.from_numpy(np.asarray(head.mean, dtype=np.float32).copy())
        scale = torch.from_numpy(np.asarray(head.scale, dtype=np.float32).copy())
        weight = torch.from_numpy(np.asarray(head.weight, dtype=np.float32, order="C").copy())
        bias = torch.from_numpy(np.asarray(head.bias, dtype=np.float32).copy())
        task_predictions = np.empty(len(primary), dtype=np.int64)
        for start in range(0, len(selected), batch_rows):
            stop = min(start + batch_rows, len(selected))
            block = np.array(feature_cache[selected[start:stop]], dtype=np.float32, order="C", copy=True)
            if not np.isfinite(block).all():
                raise RuntimeError(f"non-finite primary feature values for {task}")
            tensor = torch.from_numpy(block)
            tensor.sub_(mean).div_(scale)
            if not bool(torch.isfinite(tensor).all()):
                raise RuntimeError(f"non-finite standardized primary features for {task}")
            logits = F.linear(tensor, weight, bias)
            task_predictions[start:stop] = torch.argmax(logits, dim=1).numpy()
        predictions[task] = task_predictions
    return primary, predictions


def join_primary_labels(
    primary_manifest: Sequence[Mapping[str, Any]],
    label_rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, np.ndarray],
) -> list[dict[str, Any]]:
    """Join a separately opened primary label stream to predictions by ordered identity."""
    if len(primary_manifest) != len(label_rows):
        raise RuntimeError("primary terminal label count differs from primary row manifest")
    if set(predictions) != set(TASKS):
        raise RuntimeError("prediction set does not contain exactly the five frozen heads")
    if any(len(values) != len(primary_manifest) for values in predictions.values()):
        raise RuntimeError("prediction rows do not align with the primary row manifest")
    joined: list[dict[str, Any]] = []
    ranges = (
        ("context_term_id", 32), ("entity_term_id", 32), ("relation_id", 2),
        ("state_id", 3), ("exact_target", 3),
    )
    for i, (manifest_row, raw_label) in enumerate(zip(primary_manifest, label_rows, strict=True)):
        if (
            manifest_row.get("surface_id") != PRIMARY_SURFACE
            or manifest_row.get("truth_partition") != PRIMARY_TRUTH_PARTITION
        ):
            raise RuntimeError("label join input contains non-primary or escrowed rows")
        label = dict(raw_label)
        for key in ("row_id", "quartet_id", "variant_id"):
            if label.get(key) != manifest_row.get(key):
                raise RuntimeError(f"primary label identity mismatch at ordered row {i}: {key}")
        for field, class_count in ranges:
            label[field] = _integer(label.get(field), field, 0, class_count)
        both_seen = label["context_term_id"] < 16 and label["entity_term_id"] < 16
        if label.get("both_terms_train_side") is not both_seen:
            raise RuntimeError("both_terms_train_side disagrees with the frozen E3 term-ID rule")
        if label.get("score_strata") != target_stratum(label["context_term_id"], label["entity_term_id"]):
            raise RuntimeError("primary lexical stratum disagrees with the frozen term-ID rule")
        target_identity = _integer(
            label.get("target_candidate_identity"), "target_candidate_identity", 0, 3
        )
        if target_identity != label["state_id"]:
            raise RuntimeError("target candidate identity disagrees with observed state identity")
        candidate_order = label.get("candidate_identity_order")
        if not isinstance(candidate_order, list) or len(candidate_order) != 3:
            raise RuntimeError("candidate identity order is not a permutation of the three frozen states")
        candidate_order = [
            _integer(value, "candidate_identity_order", 0, 3)
            for value in candidate_order
        ]
        if sorted(candidate_order) != [0, 1, 2]:
            raise RuntimeError("candidate identity order is not a permutation of the three frozen states")
        if candidate_order[label["exact_target"]] != target_identity:
            raise RuntimeError("exact-target candidate position points to a different target identity")
        joined.append({
            **dict(manifest_row),
            "labels": label,
            "predictions": {task: int(predictions[task][i]) for task in TASKS},
        })
    return joined


def metric_summary(y_true: np.ndarray, y_pred: np.ndarray, class_count: int) -> dict[str, Any]:
    if y_true.ndim != 1 or y_pred.ndim != 1 or len(y_true) == 0 or len(y_true) != len(y_pred):
        raise RuntimeError("metric input is empty or has mismatched prediction rows")
    if np.any(y_true < 0) or np.any(y_true >= class_count) or np.any(y_pred < 0) or np.any(y_pred >= class_count):
        raise RuntimeError("metric input contains an out-of-range class ID")
    confusion = np.bincount(y_true * class_count + y_pred, minlength=class_count * class_count).reshape(class_count, class_count)
    support = confusion.sum(axis=1)
    recall = np.divide(np.diag(confusion), support, out=np.full(class_count, np.nan), where=support > 0)
    balanced_accuracy = float(recall.mean()) if np.all(support > 0) else None
    return {
        "rows": int(len(y_true)),
        "accuracy": float(np.trace(confusion) / len(y_true)),
        "balanced_accuracy": balanced_accuracy,
        "class_ids": list(range(class_count)),
        "class_support": support.astype(np.int64).tolist(),
        "per_class_recall": [float(value) if np.isfinite(value) else None for value in recall],
        "confusion_matrix": confusion.astype(np.int64).tolist(),
    }


def whole_quartet_bootstrap_lower_bound(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    quartet_ids: Sequence[str],
    quartet_strata: Sequence[int],
    class_count: int,
    rng: np.random.Generator,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    chunk_replicates: int = BOOTSTRAP_CHUNK_REPLICATES,
    alpha: float = BOOTSTRAP_ALPHA,
) -> tuple[float, np.ndarray, dict[str, int]]:
    if len(y_true) != len(y_pred) or len(y_true) != len(quartet_ids) or len(y_true) != len(quartet_strata):
        raise RuntimeError("bootstrap inputs have mismatched lengths")
    if replicates < 1 or chunk_replicates < 1 or not 0.0 < alpha < 1.0:
        raise RuntimeError("invalid bootstrap parameters")
    q_rows: dict[str, list[int]] = {}
    q_stratum: dict[str, int] = {}
    for index, (quartet, raw_stratum) in enumerate(zip(quartet_ids, quartet_strata, strict=True)):
        if not isinstance(quartet, str) or not quartet:
            raise RuntimeError("bootstrap quartet identity is invalid")
        stratum = _integer(raw_stratum, "A-variant bootstrap stratum", 0, class_count)
        if quartet not in q_rows:
            q_rows[quartet] = []
            q_stratum[quartet] = stratum
        elif q_stratum[quartet] != stratum:
            raise RuntimeError(f"bootstrap class stratum varies within quartet {quartet}")
        q_rows[quartet].append(index)

    ordered_quartets = list(q_rows)
    support_by_quartet = np.zeros((len(ordered_quartets), class_count), dtype=np.int64)
    correct_by_quartet = np.zeros_like(support_by_quartet)
    for q_index, quartet in enumerate(ordered_quartets):
        rows = np.asarray(q_rows[quartet], dtype=np.int64)
        truth = y_true[rows]
        support_by_quartet[q_index] = np.bincount(truth, minlength=class_count)
        correct_by_quartet[q_index] = np.bincount(truth[y_pred[rows] == truth], minlength=class_count)

    strata_to_quartets: dict[int, list[int]] = {}
    for q_index, quartet in enumerate(ordered_quartets):
        strata_to_quartets.setdefault(q_stratum[quartet], []).append(q_index)
    if set(strata_to_quartets) != set(range(class_count)):
        raise RuntimeError("bootstrap lacks one or more frozen A-variant class strata")

    boot_support = np.zeros((replicates, class_count), dtype=np.int64)
    boot_correct = np.zeros_like(boot_support)
    for stratum in range(class_count):
        q_indices = np.asarray(strata_to_quartets[stratum], dtype=np.int64)
        q_count = len(q_indices)
        for start in range(0, replicates, chunk_replicates):
            stop = min(start + chunk_replicates, replicates)
            draws = rng.integers(0, q_count, size=(stop - start, q_count), dtype=np.int32)
            sampled = q_indices[draws]
            boot_support[start:stop] += support_by_quartet[sampled].sum(axis=1)
            boot_correct[start:stop] += correct_by_quartet[sampled].sum(axis=1)
    if np.any(boot_support == 0):
        raise RuntimeError("bootstrap replicate omitted a scored truth class")
    bootstrap_scores = (boot_correct / boot_support).mean(axis=1)
    lower = float(np.quantile(bootstrap_scores, alpha, method="linear"))
    return lower, bootstrap_scores.astype(np.float64), {str(k): len(v) for k, v in sorted(strata_to_quartets.items())}


def endpoint_inputs(rows: Sequence[Mapping[str, Any]]) -> dict[str, EndpointData]:
    """Build the eight fixed E3-compatible endpoints from primary terminal rows."""
    if not rows:
        raise RuntimeError("no primary scored rows")
    by_quartet: dict[str, list[Mapping[str, Any]]] = {}
    row_ids: set[str] = set()
    for row in rows:
        if row.get("surface_id") != PRIMARY_SURFACE or row.get("truth_partition") != PRIMARY_TRUTH_PARTITION:
            raise RuntimeError("scorer received heldout-template or non-primary truth")
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id in row_ids:
            raise RuntimeError("scorer rows contain a missing or duplicate row ID")
        row_ids.add(row_id)
        quartet = row.get("quartet_id")
        if not isinstance(quartet, str) or not quartet:
            raise RuntimeError("scorer row lacks a valid quartet ID")
        if set(row.get("predictions", {})) != set(TASKS):
            raise RuntimeError("scorer row lacks exactly five frozen head predictions")
        by_quartet.setdefault(quartet, []).append(row)
    for quartet, quartet_rows in by_quartet.items():
        if tuple(row.get("variant_id") for row in quartet_rows) != QUARTET_VARIANTS:
            raise RuntimeError(f"primary quartet is incomplete or misordered: {quartet}")

    specs: dict[str, tuple[str, int, str | None]] = {
        "context_identity": ("context_term_id", 32, None),
        "entity_identity": ("entity_term_id", 32, None),
        "relation": ("relation_id", 2, None),
        "observed_state": ("state_id", 3, None),
        "exact_target_in_domain": ("exact_target", 3, "IN_DOMAIN"),
        "exact_target_context_novel": ("exact_target", 3, "CONTEXT_NOVEL"),
        "exact_target_entity_novel": ("exact_target", 3, "ENTITY_NOVEL"),
        "exact_target_both_novel": ("exact_target", 3, "BOTH_NOVEL"),
    }
    result: dict[str, EndpointData] = {}
    for endpoint, (label_field, class_count, target_filter) in specs.items():
        task = "exact_target" if endpoint.startswith("exact_target_") else endpoint
        selected: list[Mapping[str, Any]] = []
        for row in rows:
            labels = row["labels"]
            if target_filter is not None and labels.get("score_strata") != target_filter:
                continue
            if task in ("relation", "observed_state") and labels.get("both_terms_train_side") is not True:
                continue
            selected.append(row)
        y_true: list[int] = []
        y_pred: list[int] = []
        quartet_ids: list[str] = []
        quartet_strata: list[int] = []
        for row in selected:
            labels = row["labels"]
            y_true.append(_integer(labels.get(label_field), label_field, 0, class_count))
            y_pred.append(_integer(row["predictions"].get(task), f"{task} prediction", 0, class_count))
            quartet = row["quartet_id"]
            baseline = next(item for item in by_quartet[quartet] if item["variant_id"] == "A")
            quartet_strata.append(_integer(baseline["labels"].get(label_field), f"A-variant {label_field}", 0, class_count))
            quartet_ids.append(quartet)
        result[endpoint] = EndpointData(
            np.asarray(y_true, dtype=np.int64), np.asarray(y_pred, dtype=np.int64),
            tuple(quartet_ids), tuple(quartet_strata), class_count,
        )
    if tuple(result) != ENDPOINT_ORDER:
        raise RuntimeError("endpoint construction order differs from E4-0 contract")
    return result


def _score_endpoint_set(
    endpoint_data: Mapping[str, EndpointData],
    *,
    replicates: int,
    seed: int,
    chunk_replicates: int,
    alpha: float,
    minimum_rows_per_class: int,
    performance_floor: float,
) -> dict[str, Any]:
    if tuple(endpoint_data) != ENDPOINT_ORDER:
        raise RuntimeError("scorer endpoint order differs from the frozen E4-0 contract")
    rng = np.random.Generator(np.random.PCG64(seed))
    results: dict[str, Any] = {}
    for endpoint in ENDPOINT_ORDER:
        data = endpoint_data[endpoint]
        if len(data.labels):
            point = metric_summary(data.labels, data.predictions, data.class_count)
        else:
            point = {
                "rows": 0, "accuracy": None, "balanced_accuracy": None,
                "class_ids": list(range(data.class_count)), "class_support": [0] * data.class_count,
                "per_class_recall": [None] * data.class_count,
                "confusion_matrix": [[0] * data.class_count for _ in range(data.class_count)],
            }
        support_ok = min(point["class_support"], default=0) >= minimum_rows_per_class
        if not support_ok:
            results[endpoint] = {
                **point, "status": "FAIL_SUPPORT", "bootstrap_replicates": 0,
                "bootstrap_seed": seed, "bootstrap_lower_bound_alpha": alpha,
                "bootstrap_lower_bound": None, "minimum_rows_per_class": minimum_rows_per_class,
                "support_gate_pass": False, "performance_floor": performance_floor,
                "gate_pass": False, "bootstrap_eligible_quartets_by_A_stratum": {},
            }
            continue
        lower, values, quartet_counts = whole_quartet_bootstrap_lower_bound(
            data.labels, data.predictions, data.quartet_ids, data.quartet_strata,
            data.class_count, rng, replicates=replicates,
            chunk_replicates=chunk_replicates, alpha=alpha,
        )
        results[endpoint] = {
            **point, "status": "SCORED", "bootstrap_replicates": replicates,
            "bootstrap_seed": seed,
            "bootstrap_rng": "NumPy PCG64; one generator consumed in frozen endpoint order",
            "bootstrap_resampling_unit": "whole quartet; stratified by task-specific A-variant truth label",
            "bootstrap_lower_bound_alpha": alpha, "bootstrap_quantile_method": "linear",
            "bootstrap_lower_bound": lower, "minimum_rows_per_class": minimum_rows_per_class,
            "support_gate_pass": True, "performance_floor": performance_floor,
            "gate_pass": lower >= performance_floor,
            "bootstrap_eligible_quartets_by_A_stratum": quartet_counts,
            "bootstrap_scores": values.tolist(),
        }
    passed = [endpoint for endpoint in ENDPOINT_ORDER if results[endpoint]["gate_pass"]]
    failed = [endpoint for endpoint in ENDPOINT_ORDER if not results[endpoint]["gate_pass"]]
    bundle_pass = len(passed) == len(ENDPOINT_ORDER)
    return {
        "schema": "fas-e4-0-fresh-qualification-v01",
        "endpoint_order": list(ENDPOINT_ORDER),
        "bootstrap": {
            "replicates": replicates, "seed": seed,
            "rng": "NumPy PCG64; one generator consumed in frozen endpoint order",
            "resampling_unit": "whole quartet, stratified by task-specific A-variant label",
            "chunk_replicates": chunk_replicates,
            "quantile_method": "NumPy linear", "lower_tail_alpha_per_endpoint": alpha,
            "support_failure_behavior": "record FAIL_SUPPORT; omit that endpoint bootstrap and consume no RNG draws for it",
        },
        "support_gate": {"minimum_rows_per_class": minimum_rows_per_class},
        "performance_floor": performance_floor,
        "endpoints": results, "passed_endpoints": passed, "failed_endpoints": failed,
        "bundle_qualified": bundle_pass,
        "terminal_disposition": (
            "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION"
            if bundle_pass else "FAIL_FRESH_QUALIFICATION"
        ),
    }


def score_primary_population(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run exactly the eight frozen E4-0 gates; no tuning arguments are exposed."""
    return _score_endpoint_set(
        endpoint_inputs(rows),
        replicates=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
        chunk_replicates=BOOTSTRAP_CHUNK_REPLICATES,
        alpha=BOOTSTRAP_ALPHA,
        minimum_rows_per_class=MINIMUM_ROWS_PER_CLASS,
        performance_floor=PERFORMANCE_FLOOR,
    )


def run_authorized_primary_scoring(
    *,
    feature_cache: np.ndarray,
    manifest: Sequence[Mapping[str, Any]],
    heads: Mapping[str, LinearHead],
    label_reader: OneShotPrimaryLabelReader,
    authorization: Mapping[str, Any],
    expected_auth_identity: ScoringAuthIdentity,
    now_unix_seconds: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Authorize, infer on primary rows, open primary truth once, and score.

    The manifest/cache and frozen E3 heads must already have passed their
    independent seal checks before this entry point is called.
    """
    validate_scoring_authorization(
        authorization,
        expected_auth_identity,
        now_unix_seconds=now_unix_seconds,
    )
    primary_manifest, predictions = predict_primary_rows(feature_cache, manifest, heads)
    if label_reader.expected_rows != len(primary_manifest):
        raise RuntimeError("sealed primary label row count differs from selected primary manifest")
    label_rows, label_receipt = label_reader.read_once(
        authorization,
        expected_auth_identity,
        now_unix_seconds=now_unix_seconds,
    )
    joined = join_primary_labels(primary_manifest, label_rows, predictions)
    metrics = score_primary_population(joined)
    return metrics, label_receipt, {
        "primary_row_count": len(primary_manifest),
        "primary_predictions_only": True,
        "heldout_template_predictions": False,
        "joint_template_predictions": False,
        "refit_performed": False,
        "scoring_authorization_validated_before_label_open": True,
    }
