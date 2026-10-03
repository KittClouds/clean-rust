from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .constants import ENDPOINT_ORDER, ENDPOINT_SPECS, GATES, TASKS, VARIANTS
from .integrity import AuditError, Seal, read_json, read_jsonl_stream, sha256_file, verify_e4_stage_seal, verify_legacy_head_seal


SCORE_ENTRY_IDS = frozenset({
    "E4_SCORING_PREDICTIONS_V01",
    "E4_SCORING_SCORED_ROWS_V01",
    "E4_SCORING_METRICS_V01",
    "E4_SCORING_BOOTSTRAP_V01",
    "E4_SCORING_LABEL_OPEN_RECEIPT_V01",
    "E4_SCORING_TERMINAL_RECEIPT_V01",
})


def load_heads(e3_seal_path: Path, expected_e3_root: str) -> dict[str, dict[str, np.ndarray]]:
    paths = verify_legacy_head_seal(e3_seal_path, expected_e3_root)
    heads: dict[str, dict[str, np.ndarray]] = {}
    for task, (_field, classes, _scope) in TASKS.items():
        mean = np.fromfile(paths[f"e3_v02_{task}_mean"], dtype="<f4")
        scale = np.fromfile(paths[f"e3_v02_{task}_scale"], dtype="<f4")
        weight = np.fromfile(paths[f"e3_v02_{task}_weight"], dtype="<f4")
        bias = np.fromfile(paths[f"e3_v02_{task}_bias"], dtype="<f4")
        if mean.size != GATES.feature_dimension or scale.size != GATES.feature_dimension:
            raise AuditError(f"frozen E3 scaler dimensions mismatch for {task}")
        if weight.size != classes * GATES.feature_dimension or bias.size != classes:
            raise AuditError(f"frozen E3 readout dimensions mismatch for {task}")
        weight = weight.reshape(classes, GATES.feature_dimension)
        if not all(np.isfinite(item).all() for item in (mean, scale, weight, bias)) or np.any(scale == 0):
            raise AuditError(f"frozen E3 readout contains nonfinite values or a zero scale: {task}")
        heads[task] = {"mean": mean, "scale": scale, "weight": weight, "bias": bias, "classes": np.asarray([classes], dtype=np.int64)}
    return heads


def _cpu_torch_predict(x: np.ndarray, head: Mapping[str, np.ndarray]) -> np.ndarray:
    """Run frozen CPU linear arithmetic independently; CUDA is never initialized."""
    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as exc:
        raise AuditError("CPU torch is required to replay the frozen FP32 observer arithmetic") from exc
    if torch.cuda.is_initialized():
        raise AuditError("independent E4 audit refuses a process with initialized CUDA")
    try:
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    mean = torch.from_numpy(np.asarray(head["mean"], dtype=np.float32).copy())
    scale = torch.from_numpy(np.asarray(head["scale"], dtype=np.float32).copy())
    weights = torch.from_numpy(np.asarray(head["weight"], dtype=np.float32, order="C").copy())
    bias = torch.from_numpy(np.asarray(head["bias"], dtype=np.float32).copy())
    out = np.empty(len(x), dtype=np.int64)
    for start in range(0, len(x), 2_048):
        block = np.array(x[start : start + 2_048], dtype=np.float32, order="C", copy=True)
        if not np.isfinite(block).all():
            raise AuditError("feature input to frozen observer is non-finite")
        tensor = torch.from_numpy(block)
        tensor.sub_(mean).div_(scale)
        logits = functional.linear(tensor, weights, bias)
        out[start : start + len(block)] = torch.argmax(logits, dim=1).numpy()
    return out


def recompute_primary_predictions(
    cache: np.ndarray,
    primary_manifest: Sequence[Mapping[str, Any]],
    heads: Mapping[str, Mapping[str, np.ndarray]],
) -> list[dict[str, int]]:
    if set(heads) != set(TASKS):
        raise AuditError("E3 head artifact set does not contain exactly five observers")
    predictions: list[dict[str, int]] = [dict() for _ in primary_manifest]
    row_indices = np.asarray([row["row_index"] for row in primary_manifest], dtype=np.int64)
    if cache.ndim != 2 or cache.shape[1] != GATES.feature_dimension:
        raise AuditError("feature cache has the wrong matrix shape")
    for task in TASKS:
        all_for_task = np.full(len(primary_manifest), -1, dtype=np.int64)
        selected_positions = np.arange(len(primary_manifest), dtype=np.int64)
        for start in range(0, len(selected_positions), 2_048):
            positions = selected_positions[start : start + 2_048]
            raw = np.asarray(cache[row_indices[positions]], dtype=np.float32, order="C")
            all_for_task[positions] = _cpu_torch_predict(raw, heads[task])
        for position, prediction in enumerate(all_for_task):
            predictions[position][task] = int(prediction) if prediction >= 0 else -1
    return predictions


def _class(value: Any, label: str, classes: int) -> int:
    if type(value) is not int or not 0 <= value < classes:
        raise AuditError(f"{label} is not an integer in 0..{classes - 1}")
    return value


def _validate_label(label: Mapping[str, Any]) -> None:
    ranges = {
        "context_term_id": 32,
        "entity_term_id": 32,
        "relation_id": 2,
        "state_id": 3,
        "exact_target": 3,
        "target_candidate_identity": 3,
    }
    for key, classes in ranges.items():
        _class(label.get(key), key, classes)
    expected_train = label["context_term_id"] < 16 and label["entity_term_id"] < 16
    if label.get("both_terms_train_side") is not expected_train:
        raise AuditError("scored primary label has invalid task eligibility")
    expected_stratum = {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(label["context_term_id"] >= 16, label["entity_term_id"] >= 16)]
    if label.get("score_strata") != expected_stratum:
        raise AuditError("scored primary lexical stratum does not match frozen term-ID rule")
    order = label.get("candidate_identity_order")
    if not isinstance(order, list) or len(order) != 3 or sorted(order) != [0, 1, 2]:
        raise AuditError("scored primary candidate ordering is malformed")
    if order[label["exact_target"]] != label["target_candidate_identity"] or label["state_id"] != label["target_candidate_identity"]:
        raise AuditError("scored primary exact-target position differs from semantic target identity")


def _validate_primary_order(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    row_ids: set[str] = set()
    for row in rows:
        if row.get("surface_id") != "PRIMARY_SEEN" or row.get("truth_partition") != "PRIMARY_TERMINAL":
            raise AuditError("scored primary rows contain a heldout/escrow item")
        if row.get("row_id") in row_ids:
            raise AuditError("scored primary rows contain a duplicate row ID")
        row_ids.add(str(row["row_id"]))
        if not isinstance(row.get("labels"), dict):
            raise AuditError("scored primary row lacks its sealed label payload")
        _validate_label(row["labels"])
        if set(row.get("head_predictions", {})) != set(TASKS):
            raise AuditError("scored primary row does not contain exactly five predictions")
        for task, (_label, classes, _scope) in TASKS.items():
            pred = row["head_predictions"].get(task)
            if type(pred) is not int or not 0 <= pred < classes:
                raise AuditError(f"scored primary prediction outside class range: {task}")
        groups.setdefault(str(row.get("quartet_id")), []).append(row)
    if not groups:
        raise AuditError("scored primary population is empty")
    for qid, group in groups.items():
        if tuple(row.get("variant_id") for row in group) != VARIANTS:
            raise AuditError(f"scored primary quartet is incomplete or misordered: {qid}")
        labels = [row["labels"] for row in group]
        for key in ("relation_id", "state_id", "exact_target", "target_candidate_identity", "candidate_identity_order"):
            if any(label.get(key) != labels[0].get(key) for label in labels[1:]):
                raise AuditError(f"scored primary quartet changed semantic factor {key}: {qid}")
    return groups


def _metric(actual: np.ndarray, predicted: np.ndarray, classes: int) -> dict[str, Any]:
    if len(actual) != len(predicted):
        raise AuditError("metric truth/prediction lengths differ")
    confusion = np.zeros((classes, classes), dtype=np.int64)
    np.add.at(confusion, (actual, predicted), 1)
    support = confusion.sum(axis=1)
    recall: list[float | None] = []
    for class_id in range(classes):
        recall.append(float(confusion[class_id, class_id] / support[class_id]) if support[class_id] else None)
    ba = float(np.mean([value for value in recall if value is not None])) if np.all(support > 0) else None
    return {
        "rows": int(len(actual)),
        "accuracy": float(np.trace(confusion) / len(actual)) if len(actual) else None,
        "balanced_accuracy": ba,
        "class_ids": list(range(classes)),
        "class_support": support.tolist(),
        "per_class_recall": recall,
        "confusion_matrix": confusion.tolist(),
    }


def _endpoint_data(
    endpoint: str, rows: Sequence[Mapping[str, Any]], groups: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[np.ndarray, np.ndarray, list[str], list[int], int]:
    label_field, classes, task, target_stratum = ENDPOINT_SPECS[endpoint]
    selected: list[Mapping[str, Any]] = []
    for row in rows:
        labels = row["labels"]
        if target_stratum is not None and labels.get("score_strata") != target_stratum:
            continue
        if task in ("relation", "observed_state") and labels.get("both_terms_train_side") is not True:
            continue
        selected.append(row)
    actual = np.empty(len(selected), dtype=np.int64)
    predicted = np.empty(len(selected), dtype=np.int64)
    quartets: list[str] = []
    strata: list[int] = []
    for index, row in enumerate(selected):
        label = row["labels"]
        actual[index] = _class(label.get(label_field), label_field, classes)
        predicted[index] = _class(row["head_predictions"].get(task), f"{task} prediction", classes)
        qid = str(row["quartet_id"])
        baseline = groups[qid][0]
        strata.append(_class(baseline["labels"].get(label_field), f"A-variant {label_field}", classes))
        quartets.append(qid)
    return actual, predicted, quartets, strata, classes


def _independent_bootstrap(
    actual: np.ndarray,
    predicted: np.ndarray,
    quartet_ids: Sequence[str],
    quartet_strata: Sequence[int],
    classes: int,
    rng: np.random.Generator,
    *,
    replicates: int,
    chunk: int,
    alpha: float,
) -> tuple[float, np.ndarray, dict[str, int]]:
    """Stratified whole-quartet resampling, reconstructed from row-level sufficient statistics."""
    q_to_rows: dict[str, list[int]] = {}
    q_to_class: dict[str, int] = {}
    for row_idx, (qid, raw_class) in enumerate(zip(quartet_ids, quartet_strata, strict=True)):
        stratum = _class(raw_class, "A-variant bootstrap class", classes)
        if qid in q_to_class and q_to_class[qid] != stratum:
            raise AuditError("bootstrap class stratum changes within a quartet")
        q_to_class.setdefault(qid, stratum)
        q_to_rows.setdefault(qid, []).append(row_idx)
    q_ids = list(q_to_rows)
    q_index = {qid: index for index, qid in enumerate(q_ids)}
    support_by_q = np.zeros((len(q_ids), classes), dtype=np.int64)
    hits_by_q = np.zeros_like(support_by_q)
    for qid, row_indices in q_to_rows.items():
        qrow = q_index[qid]
        for index in row_indices:
            cls = int(actual[index])
            support_by_q[qrow, cls] += 1
            if predicted[index] == cls:
                hits_by_q[qrow, cls] += 1
    strata_to_q: list[list[int]] = [[] for _ in range(classes)]
    for i, qid in enumerate(q_ids):
        strata_to_q[q_to_class[qid]].append(i)
    if any(not values for values in strata_to_q):
        raise AuditError("bootstrap lacks at least one A-variant class stratum")
    support_draws = np.zeros((replicates, classes), dtype=np.int64)
    hit_draws = np.zeros_like(support_draws)
    eligible_counts: dict[str, int] = {}
    for stratum, eligible_list in enumerate(strata_to_q):
        eligible = np.asarray(eligible_list, dtype=np.int64)
        eligible_counts[str(stratum)] = int(eligible.size)
        n = int(eligible.size)
        for begin in range(0, replicates, chunk):
            end = min(begin + chunk, replicates)
            draws = rng.integers(0, n, size=(end - begin, n), dtype=np.int32)
            chosen = eligible[draws]
            support_draws[begin:end] += support_by_q[chosen].sum(axis=1)
            hit_draws[begin:end] += hits_by_q[chosen].sum(axis=1)
    if np.any(support_draws == 0):
        raise AuditError("a whole-quartet bootstrap sample has zero support for a scored class")
    samples = (hit_draws / support_draws).mean(axis=1).astype(np.float64)
    return float(np.quantile(samples, alpha, method="linear")), samples, eligible_counts


def reconstruct_qualification(
    rows: Sequence[Mapping[str, Any]],
    *,
    replicates: int = GATES.bootstrap_replicates,
    seed: int = GATES.bootstrap_seed,
    chunk: int = GATES.bootstrap_chunk,
    alpha: float = GATES.alpha,
    minimum_rows_per_class: int = GATES.support_minimum,
    performance_floor: float = GATES.performance_floor,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Build endpoints and all-eight disposition independently from scorer metrics."""
    if not rows:
        raise AuditError("cannot replay an empty scored-primary population")
    groups = _validate_primary_order(rows)
    rng = np.random.Generator(np.random.PCG64(seed))
    results: dict[str, Any] = {}
    bootstrap_arrays: dict[str, np.ndarray] = {}
    for endpoint in ENDPOINT_ORDER:
        actual, predicted, qids, strata, classes = _endpoint_data(endpoint, rows, groups)
        point = _metric(actual, predicted, classes)
        support_ok = min(point["class_support"], default=0) >= minimum_rows_per_class
        array_key = f"endpoint_{len(results):02d}__bootstrap_balanced_accuracy"
        if not support_ok:
            bootstrap_arrays[array_key] = np.empty(0, dtype=np.float64)
            results[endpoint] = {
                **point,
                "status": "FAIL_SUPPORT",
                "support_gate_pass": False,
                "gate_pass": False,
                "bootstrap_replicates": 0,
                "bootstrap_lower_bound": None,
                "bootstrap_eligible_quartets_by_A_stratum": {},
            }
            continue
        lower, samples, eligible = _independent_bootstrap(
            actual,
            predicted,
            qids,
            strata,
            classes,
            rng,
            replicates=replicates,
            chunk=chunk,
            alpha=alpha,
        )
        gate_pass = lower >= performance_floor
        bootstrap_arrays[array_key] = samples
        results[endpoint] = {
            **point,
            "status": "SCORED",
            "support_gate_pass": True,
            "gate_pass": gate_pass,
            "bootstrap_replicates": replicates,
            "bootstrap_lower_bound": lower,
            "bootstrap_eligible_quartets_by_A_stratum": eligible,
        }
    passed = [name for name in ENDPOINT_ORDER if results[name]["gate_pass"]]
    failed = [name for name in ENDPOINT_ORDER if not results[name]["gate_pass"]]
    metrics = {
        "schema": "fas-e4-0-fresh-qualification-v01",
        "endpoint_order": list(ENDPOINT_ORDER),
        "bootstrap": {
            "replicates": replicates,
            "seed": seed,
            "rng": "NumPy PCG64; one generator consumed in frozen endpoint order",
            "resampling_unit": "whole quartet; class-stratified by task-specific variant-A label",
            "chunk_replicates": chunk,
            "quantile_method": "NumPy linear",
            "lower_tail_alpha_per_endpoint": alpha,
        },
        "support_gate": {"minimum_rows_per_class": minimum_rows_per_class},
        "performance_floor": performance_floor,
        "endpoints": results,
        "passed_endpoints": passed,
        "failed_endpoints": failed,
        "bundle_qualified": not failed,
        "terminal_disposition": "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION" if not failed else "FAIL_FRESH_QUALIFICATION",
    }
    return metrics, bootstrap_arrays


def _compare_endpoint_metric(expected: Mapping[str, Any], actual: Mapping[str, Any], name: str) -> None:
    for field in ("rows", "accuracy", "balanced_accuracy", "class_ids", "class_support", "per_class_recall", "confusion_matrix", "status", "support_gate_pass", "gate_pass", "bootstrap_lower_bound"):
        left, right = expected.get(field), actual.get(field)
        if isinstance(left, float) or isinstance(right, float):
            if left is None or right is None or abs(float(left) - float(right)) > 1e-12:
                raise AuditError(f"scorer/auditor endpoint mismatch {name}.{field}: {left!r} != {right!r}")
        elif left != right:
            raise AuditError(f"scorer/auditor endpoint mismatch {name}.{field}: {left!r} != {right!r}")


def compare_scored_artifacts(
    replay_metrics: Mapping[str, Any],
    replay_arrays: Mapping[str, np.ndarray],
    scorer_metrics_path: Path,
    scorer_bootstrap_path: Path,
) -> None:
    scored = read_json(scorer_metrics_path)
    if tuple(scored.get("endpoint_order", ())) != ENDPOINT_ORDER:
        raise AuditError("scorer metrics endpoint order differs from the frozen contract")
    for name in ("passed_endpoints", "failed_endpoints", "bundle_qualified", "terminal_disposition"):
        if scored.get(name) != replay_metrics.get(name):
            raise AuditError(f"scorer/auditor disposition disagreement: {name}")
    frozen_bootstrap = replay_metrics["bootstrap"]
    if scored.get("bootstrap", {}).get("replicates") != frozen_bootstrap["replicates"] or scored.get("bootstrap", {}).get("seed") != frozen_bootstrap["seed"] or scored.get("bootstrap", {}).get("lower_tail_alpha_per_endpoint") != frozen_bootstrap["lower_tail_alpha_per_endpoint"]:
        raise AuditError("scorer metrics settings differ from the frozen E4-0 bootstrap contract")
    if scored.get("support_gate", {}).get("minimum_rows_per_class") != replay_metrics["support_gate"]["minimum_rows_per_class"] or scored.get("performance_floor") != replay_metrics["performance_floor"]:
        raise AuditError("scorer metrics support/performance gate differs from the frozen contract")
    for name in ENDPOINT_ORDER:
        _compare_endpoint_metric(scored.get("endpoints", {}).get(name, {}), replay_metrics["endpoints"][name], name)
    try:
        archive = np.load(scorer_bootstrap_path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise AuditError(f"cannot load sealed bootstrap arrays: {exc}") from exc
    expected_keys = [f"endpoint_{i:02d}__bootstrap_balanced_accuracy" for i in range(len(ENDPOINT_ORDER))]
    if list(archive.files) != expected_keys:
        raise AuditError("bootstrap NPZ arrays/order differ from the frozen endpoint order")
    for key in expected_keys:
        recorded = archive[key]
        actual = replay_arrays[key]
        if recorded.dtype != np.dtype("float64") or recorded.ndim != 1:
            raise AuditError(f"bootstrap array dtype/shape mismatch: {key}")
        if not np.array_equal(recorded, actual):
            raise AuditError(f"scorer/auditor bootstrap output disagreement: {key}")


def _compare_primary_manifest(scored_rows: Sequence[Mapping[str, Any]], row_manifest_path: Path) -> list[dict[str, Any]]:
    primary = [
        row for row in read_jsonl_stream(row_manifest_path)
        if row.get("surface_id") == "PRIMARY_SEEN" and row.get("truth_partition") == "PRIMARY_TERMINAL"
    ]
    if len(primary) != len(scored_rows):
        raise AuditError("scored primary rows do not match the number of primary population manifest entries")
    for position, (expected, observed) in enumerate(zip(primary, scored_rows, strict=True)):
        for field in ("row_index", "row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"):
            if observed.get(field) != expected.get(field):
                raise AuditError(f"scored primary identity mismatch at {position}: {field}")
    return primary


def audit_scoring_stage(
    *,
    score_seal_path: Path,
    run_root: Path,
    contract_sha256: str,
    contract_root_sha256: str,
    expected_predecessors: Mapping[str, str],
    feature_cache_path: Path,
    population_manifest_path: Path,
    e3_seal_path: Path,
    expected_e3_root: str,
    expected_rows: int = GATES.total_rows,
) -> dict[str, Any]:
    """Replay from sealed scored rows, cache and E3 readout bytes; original truth files are never inputs."""
    seal = verify_e4_stage_seal(
        score_seal_path,
        root=run_root,
        expected_stage="FRESH_SCORING",
        current_contract_sha256=contract_sha256,
        current_contract_root_sha256=contract_root_sha256,
        expected_predecessors=expected_predecessors,
        allowed_entry_ids=SCORE_ENTRY_IDS,
    )
    scored_rows = list(read_jsonl_stream(seal.entries["E4_SCORING_SCORED_ROWS_V01"].path))
    prediction_rows = list(read_jsonl_stream(seal.entries["E4_SCORING_PREDICTIONS_V01"].path))
    if len(scored_rows) != GATES.primary_rows or len(scored_rows) != len(prediction_rows):
        raise AuditError("scoring artifacts have the wrong primary row count")
    primary_manifest = _compare_primary_manifest(scored_rows, population_manifest_path)
    for index, (scored, prediction) in enumerate(zip(scored_rows, prediction_rows, strict=True)):
        for field in ("row_index", "row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"):
            if prediction.get(field) != scored.get(field):
                raise AuditError(f"prediction/scored-row identity mismatch at {index}: {field}")
        if prediction.get("head_predictions") != scored.get("head_predictions"):
            raise AuditError(f"prediction/scored-row heads disagree at primary row {index}")
    heads = load_heads(e3_seal_path, expected_e3_root)
    feature_cache = np.memmap(feature_cache_path, dtype="<f4", mode="r", shape=(expected_rows, GATES.feature_dimension), order="C")
    for start in range(0, expected_rows, 2_048):
        if not np.isfinite(feature_cache[start : start + 2_048]).all():
            raise AuditError("scored population feature cache contains nonfinite values")
    recomputed = recompute_primary_predictions(feature_cache, primary_manifest, heads)
    for index, (observed, predicted) in enumerate(zip(scored_rows, recomputed, strict=True)):
        for task in TASKS:
            expected_value = predicted[task]
            actual_value = observed["head_predictions"].get(task)
            if expected_value != actual_value:
                raise AuditError(f"frozen-head prediction replay mismatch at row {index}/{task}")
    metrics, arrays = reconstruct_qualification(scored_rows)
    compare_scored_artifacts(
        metrics,
        arrays,
        seal.entries["E4_SCORING_METRICS_V01"].path,
        seal.entries["E4_SCORING_BOOTSTRAP_V01"].path,
    )
    label_open = read_json(seal.entries["E4_SCORING_LABEL_OPEN_RECEIPT_V01"].path)
    terminal = read_json(seal.entries["E4_SCORING_TERMINAL_RECEIPT_V01"].path)
    if label_open.get("escrow_label_file_open_count") != 0 or label_open.get("status") != "PRIMARY_TERMINAL_LABELS_OPENED_ONCE":
        raise AuditError("score label-open receipt reports an escrow access or invalid one-open status")
    if terminal.get("primary_label_file_open_count") != 1 or terminal.get("heldout_template_rows_inferred") != 0:
        raise AuditError("score terminal receipt crossed the frozen truth boundary")
    if terminal.get("terminal_disposition") != metrics["terminal_disposition"]:
        raise AuditError("score terminal receipt disagrees with independent all-eight replay")
    return {
        "status": "PASS_INDEPENDENT_REPLAY",
        "score_root_sha256": seal.root_sha256,
        "terminal_disposition": metrics["terminal_disposition"],
        "bundle_qualified": metrics["bundle_qualified"],
        "passed_endpoints": metrics["passed_endpoints"],
        "failed_endpoints": metrics["failed_endpoints"],
        "endpoint_order": list(ENDPOINT_ORDER),
        "predictions_recomputed_from_cache_and_E3_head_bytes": True,
        "bootstrap_replicates_reconstructed": GATES.bootstrap_replicates,
        "original_primary_label_file_opened": False,
        "template_or_joint_escrow_opened": False,
        "all_checks_passed": True,
    }
