from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
E1_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
E1_SEAL_PATH = E1_ROOT / "e1-seal-v01.json"
E1_SUPPORT_PATH = E1_ROOT / "receipts" / "support-receipt-v01.json"
E1_ROWS_PATH = E1_ROOT / "panel" / "row-manifest-v01.jsonl"
E1_SPLIT_PATH = E1_ROOT / "panel" / "split-manifest-v01.jsonl"
FEATURE_CACHE_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\V1_FINAL_POSITION.f32le")
E3_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02")
E3_SEAL_PATH = E3_ROOT / "e3-v02-seal.json"
E3_BUNDLE_PATH = E3_ROOT / "frozen-capability-fabric-v02.json"
CONTRACT_PATH = PROJECT / "contracts" / "e3-score-v01.json"
AUTHORIZATION_PATH = PROJECT / "audits" / "e3-score-authorization-v01.json"
OUTPUT_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-score-v01")
SCORE_SEAL_PATH = PROJECT / "seals" / "e3-score-v01-seal.json"
AUDIT_PATH = PROJECT / "audits" / "e3-score-v01-independent-audit.json"
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
EXPECTED_E3_ROOT = "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1"
ROWS = 106_496
DIM = 2_048
TEST_ROWS = 21_292
VARIANTS = ("A", "C", "E", "P")
ENDPOINTS = (
    "context_identity",
    "entity_identity",
    "relation",
    "observed_state",
    "exact_target_in_domain",
    "exact_target_context_novel",
    "exact_target_entity_novel",
    "exact_target_both_novel",
)
TASKS = {
    "context_identity": ("context_term_id", 32, "all"),
    "entity_identity": ("entity_term_id", 32, "all"),
    "relation": ("relation_id", 2, "train_side"),
    "observed_state": ("state_id", 3, "train_side"),
    "exact_target": ("exact_target", 3, "all"),
}
TARGET_STRATA = {
    "exact_target_in_domain": "IN_DOMAIN",
    "exact_target_context_novel": "CONTEXT_NOVEL",
    "exact_target_entity_novel": "ENTITY_NOVEL",
    "exact_target_both_novel": "BOTH_NOVEL",
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def artifact_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def path_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def target_stratum(context_id: int, entity_id: int) -> str:
    return {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(context_id >= 16, entity_id >= 16)]


def load_truth_rows() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    manifest = read_jsonl(E1_ROWS_PATH)
    split = read_jsonl(E1_SPLIT_PATH)
    split_by_quartet = {entry["quartet_id"]: entry["split"] for entry in split}
    if len(manifest) != ROWS or [row["row_index"] for row in manifest] != list(range(ROWS)):
        raise RuntimeError("E1 row manifest identity/order failed independent replay")
    test_manifest = []
    by_quartet: dict[str, list[dict[str, Any]]] = {}
    for row in manifest:
        if row.get("quartet_split") != split_by_quartet.get(row.get("quartet_id")):
            raise RuntimeError("E1 row/split manifest disagreement in independent replay")
        if row["quartet_split"] == "TEST":
            test_manifest.append(row)
            by_quartet.setdefault(row["quartet_id"], []).append(row)
    if len(test_manifest) != TEST_ROWS:
        raise RuntimeError("E1 TEST row count mismatch in independent replay")
    scored = read_jsonl(OUTPUT_ROOT / "scored-test-rows-v01.jsonl")
    if len(scored) != TEST_ROWS:
        raise RuntimeError("scored-row artifact count mismatch")
    rows: list[dict[str, Any]] = []
    truth_grouped: dict[str, list[dict[str, Any]]] = {}
    for expected, observed in zip(test_manifest, scored, strict=True):
        for field in ("row_index", "row_id", "quartet_id", "variant_id"):
            if observed.get(field) != expected.get(field):
                raise RuntimeError(f"scored-row {field} differs from E1 row manifest")
        if observed["variant_id"] not in VARIANTS:
            raise RuntimeError("scored-row variant is outside the frozen quartet")
        truth = observed.get("truth")
        if not isinstance(truth, dict):
            raise RuntimeError("scored-row truth payload is malformed")
        for field, class_count in (("context_term_id", 32), ("entity_term_id", 32), ("relation_id", 2), ("state_id", 3), ("exact_target", 3)):
            value = truth.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < class_count:
                raise RuntimeError(f"scored-row truth class is invalid: {field}")
        stratum = target_stratum(truth["context_term_id"], truth["entity_term_id"])
        if observed.get("target_stratum") != stratum:
            raise RuntimeError("scored-row novelty slice is inconsistent with its frozen term IDs")
        reconstructed = {**expected, "truth": truth, "target_stratum": stratum, "prediction": observed.get("prediction")}
        rows.append(reconstructed)
        truth_grouped.setdefault(expected["quartet_id"], []).append(reconstructed)
    for quartet, quartet_rows in by_quartet.items():
        if tuple(row["variant_id"] for row in quartet_rows) != VARIANTS:
            raise RuntimeError(f"incomplete or reordered E1 quartet: {quartet}")
    return rows, truth_grouped


def recompute_predictions(rows: list[dict[str, Any]], batch_rows: int) -> dict[str, np.ndarray]:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    cache = np.memmap(FEATURE_CACHE_PATH, dtype="<f4", mode="r", shape=(ROWS, DIM))
    predictions: dict[str, np.ndarray] = {}
    for task, (label_field, class_count, scope) in TASKS.items():
        selected = np.asarray([
            index for index, row in enumerate(rows)
            if scope == "all" or (row["truth"]["context_term_id"] < 16 and row["truth"]["entity_term_id"] < 16)
        ], dtype=np.int64)
        if task == "exact_target":
            selected = np.arange(len(rows), dtype=np.int64)
        mean = torch.from_numpy(np.fromfile(E3_ROOT / f"{task}.mean.f32le", dtype="<f4").copy())
        scale = torch.from_numpy(np.fromfile(E3_ROOT / f"{task}.scale.f32le", dtype="<f4").copy())
        weights = torch.from_numpy(np.fromfile(E3_ROOT / f"{task}.weight.f32le", dtype="<f4").reshape(class_count, DIM).copy())
        bias = torch.from_numpy(np.fromfile(E3_ROOT / f"{task}.bias.f32le", dtype="<f4").copy())
        if mean.numel() != DIM or scale.numel() != DIM or weights.shape != (class_count, DIM) or bias.numel() != class_count:
            raise RuntimeError(f"E3 observer tensor dimensions failed for {task}")
        output = np.full(len(rows), -1, dtype=np.int64)
        for start in range(0, len(selected), batch_rows):
            indices = selected[start : start + batch_rows]
            feature_rows = np.asarray([rows[int(index)]["row_index"] for index in indices], dtype=np.int64)
            raw = np.array(cache[feature_rows], dtype=np.float32, order="C", copy=True)
            if not np.isfinite(raw).all():
                raise RuntimeError(f"non-finite feature row encountered for {task}")
            x = torch.from_numpy(raw)
            x.sub_(mean).div_(scale)
            logits = F.linear(x, weights, bias)
            output[indices] = torch.argmax(logits, dim=1).numpy()
        predictions[task] = output
        for row_index, row in enumerate(rows):
            recorded = row["prediction"].get(task)
            expected = int(output[row_index]) if int(output[row_index]) >= 0 else None
            if recorded != expected:
                raise RuntimeError(f"prediction replay mismatch for {task} at row {row_index}")
    del cache
    return predictions


def metric(truth: np.ndarray, prediction: np.ndarray, class_count: int) -> dict[str, Any]:
    matrix = np.zeros((class_count, class_count), dtype=np.int64)
    for actual, predicted in zip(truth, prediction, strict=True):
        matrix[int(actual), int(predicted)] += 1
    support = matrix.sum(axis=1)
    if np.any(support == 0):
        raise RuntimeError("independent metric replay found an unsupported truth class")
    recall = np.diag(matrix) / support
    return {
        "rows": int(len(truth)),
        "accuracy": float(np.trace(matrix) / len(truth)),
        "balanced_accuracy": float(recall.mean()),
        "class_ids": list(range(class_count)),
        "class_support": support.tolist(),
        "per_class_recall": recall.tolist(),
        "confusion_matrix": matrix.tolist(),
    }


def endpoint_quartet_stratum(task: str, quartet: str, grouped: dict[str, list[dict[str, Any]]]) -> int:
    baseline = next(row for row in grouped[quartet] if row["variant_id"] == "A")
    key = {
        "context_identity": "context_term_id",
        "entity_identity": "entity_term_id",
        "relation": "relation_id",
        "observed_state": "state_id",
        "exact_target": "exact_target",
    }[task]
    return int(baseline["truth"][key])


def bootstrap_replay(
    truth: np.ndarray,
    predicted: np.ndarray,
    quartet_ids: list[str],
    quartet_strata: list[int],
    classes: int,
    count: int,
    rng: np.random.Generator,
) -> tuple[float, np.ndarray, dict[str, int]]:
    members: dict[str, list[int]] = {}
    stratum_of: dict[str, int] = {}
    for index in range(len(truth)):
        quartet = quartet_ids[index]
        stratum = int(quartet_strata[index])
        if quartet in stratum_of and stratum_of[quartet] != stratum:
            raise RuntimeError("independent bootstrap replay found a mixed quartet stratum")
        stratum_of[quartet] = stratum
        members.setdefault(quartet, []).append(index)
    ordered = list(members)
    supports = np.zeros((len(ordered), classes), dtype=np.int64)
    correct = np.zeros_like(supports)
    for q_index, quartet in enumerate(ordered):
        ix = members[quartet]
        for index in ix:
            actual = int(truth[index])
            supports[q_index, actual] += 1
            correct[q_index, actual] += int(predicted[index] == actual)
    strata_to_q: dict[int, list[int]] = {}
    for q_index, quartet in enumerate(ordered):
        strata_to_q.setdefault(stratum_of[quartet], []).append(q_index)
    if sorted(strata_to_q) != list(range(classes)):
        raise RuntimeError("independent bootstrap replay lacks a class stratum")
    boot_support = np.zeros((count, classes), dtype=np.int64)
    boot_correct = np.zeros_like(boot_support)
    for class_id in range(classes):
        eligible = np.asarray(strata_to_q[class_id], dtype=np.int64)
        n = len(eligible)
        for start in range(0, count, 64):
            end = min(start + 64, count)
            draw = rng.integers(0, n, size=(end - start, n), dtype=np.int32)
            sampled = eligible[draw]
            boot_support[start:end] += supports[sampled].sum(axis=1)
            boot_correct[start:end] += correct[sampled].sum(axis=1)
    scores = (boot_correct / boot_support).mean(axis=1)
    return float(np.quantile(scores, 0.05, method="linear")), scores, {str(k): len(v) for k, v in sorted(strata_to_q.items())}


def replay_metrics(rows: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]], predictions: dict[str, np.ndarray], e0: dict[str, Any]) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if tuple(e0["performance_gates"]["individual_endpoints"]) != ENDPOINTS:
        raise RuntimeError("independent endpoint order does not match frozen E0")
    floor_match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)?)", e0["performance_gates"]["gate"])
    if floor_match is None:
        raise RuntimeError("independent audit could not parse the frozen performance floor")
    floor = float(floor_match.group(1))
    minimum = int(e0["performance_gates"]["minimum_test_rows_per_class"])
    generator = np.random.Generator(np.random.PCG64(int(e0["bootstrap"]["seed"])))
    replicates = int(e0["bootstrap"]["replicates"])
    metrics: dict[str, Any] = {}
    bootstrap: dict[str, np.ndarray] = {}
    for endpoint in ENDPOINTS:
        if endpoint.startswith("exact_target_"):
            task = "exact_target"
            class_count = 3
            label = "exact_target"
            selected = [i for i, row in enumerate(rows) if row["target_stratum"] == TARGET_STRATA[endpoint]]
        else:
            task = endpoint
            label, class_count, scope = TASKS[task]
            selected = [
                i for i, row in enumerate(rows)
                if scope == "all" or (row["truth"]["context_term_id"] < 16 and row["truth"]["entity_term_id"] < 16)
            ]
        ids = np.asarray(selected, dtype=np.int64)
        actual = np.asarray([rows[int(i)]["truth"][label] for i in ids], dtype=np.int64)
        predicted = predictions[task][ids]
        summary = metric(actual, predicted, class_count)
        if min(summary["class_support"]) < minimum:
            raise RuntimeError(f"independent replay support gate failed for {endpoint}")
        quartet_ids = [rows[int(i)]["quartet_id"] for i in ids]
        quartet_strata = [endpoint_quartet_stratum(task, qid, grouped) for qid in quartet_ids]
        lower, values, counts = bootstrap_replay(actual, predicted, quartet_ids, quartet_strata, class_count, replicates, generator)
        metrics[endpoint] = {
            **summary,
            "bootstrap_replicates": replicates,
            "bootstrap_seed": int(e0["bootstrap"]["seed"]),
            "bootstrap_rng": "NumPy PCG64; one generator consumed in frozen endpoint order",
            "bootstrap_resampling_unit": "whole quartet; class-stratified among eligible TEST quartets",
            "bootstrap_lower_bound_percentile": 5,
            "bootstrap_quantile_method": "linear",
            "balanced_accuracy_lower_95": lower,
            "minimum_rows_per_class": minimum,
            "support_gate_pass": True,
            "performance_floor": floor,
            "gate_pass": lower >= floor,
            "bootstrap_eligible_quartets_by_stratum": counts,
        }
        bootstrap[endpoint] = values
    return metrics, bootstrap


def disposition(metrics: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    passed = [name for name in ENDPOINTS if metrics[name]["gate_pass"]]
    failed = [name for name in ENDPOINTS if not metrics[name]["gate_pass"]]
    if len(passed) == len(ENDPOINTS):
        state = "ALL_EIGHT_GATES_PASS_BUNDLE_QUALIFIED_FOR_ROUTING_DESIGN"
    elif passed:
        state = "PARTIAL_CAPABILITY_FABRIC_ONLY_PASSED_ENDPOINTS_QUALIFIED"
    else:
        state = "NO_PERFORMANCE_GATES_PASS_CHEAP_FITTING_DID_NOT_YIELD_QUALIFIED_ENDPOINTS"
    return state, passed, failed


def build_score_seal() -> tuple[dict[str, Any], str]:
    if SCORE_SEAL_PATH.exists():
        raise RuntimeError("E3 score seal already exists; refusing to replace it")
    files: list[tuple[str, Path]] = [
        ("contract/e3-score-v01.json", CONTRACT_PATH),
        ("authorization/e3-score-authorization-v01.json", AUTHORIZATION_PATH),
        ("source/score_e3_v01.py", PROJECT / "source" / "scripts" / "score_e3_v01.py"),
        ("source/test_e3_score_v01.py", PROJECT / "source" / "tests" / "test_e3_score_v01.py"),
        ("source/build_e3_score_contract_v01.py", PROJECT / "source" / "scripts" / "build_e3_score_contract_v01.py"),
        ("source/audit_e3_score_v01.py", PROJECT / "source" / "scripts" / "audit_e3_score_v01.py"),
    ]
    files.extend((f"output/{path.name}", path) for path in sorted(OUTPUT_ROOT.iterdir()) if path.is_file())
    entries = []
    for artifact_id, path in files:
        digest, size = sha256_file(path)
        entries.append({"artifact_id": artifact_id, "path": str(path.resolve()), "bytes": size, "sha256": digest})
    root = artifact_root(entries)
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_V01_SEAL",
        "status": "E3_SCORE_V01_SEALED_AFTER_INDEPENDENT_REPLAY",
        "root_sha256": root,
        "entry_count": len(entries),
        "entries": entries,
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e1_root_sha256": EXPECTED_E1_ROOT,
        "e2_v07_root_sha256": EXPECTED_E2_ROOT,
        "e3_v02_root_sha256": EXPECTED_E3_ROOT,
        "raw_e1_evaluation_labels_included": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    SCORE_SEAL_PATH.write_text(json.dumps(seal, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return seal, root


def main() -> int:
    if AUDIT_PATH.exists() or SCORE_SEAL_PATH.exists():
        raise RuntimeError("independent audit or score seal already exists; refusing to overwrite")
    contract = read_json(CONTRACT_PATH)
    authorization = read_json(AUTHORIZATION_PATH)
    e1_seal = read_json(E1_SEAL_PATH)
    e3_seal = read_json(E3_SEAL_PATH)
    e1_support = read_json(E1_SUPPORT_PATH)
    if e1_seal.get("root_sha256") != EXPECTED_E1_ROOT or path_root(e1_seal["entries"]) != EXPECTED_E1_ROOT:
        raise RuntimeError("independent audit E1 root verification failed")
    if artifact_root(e3_seal["entries"]) != EXPECTED_E3_ROOT or e3_seal.get("root_sha256") != EXPECTED_E3_ROOT:
        raise RuntimeError("independent audit E3 root verification failed")
    for entry in e3_seal["entries"]:
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"E3 artifact changed before independent replay: {entry['artifact_id']}")
    if contract.get("e0_root_sha256") != EXPECTED_E0_ROOT or contract.get("e1_root_sha256") != EXPECTED_E1_ROOT or contract.get("e3_v02_root_sha256") != EXPECTED_E3_ROOT:
        raise RuntimeError("score contract roots are inconsistent")
    contract_hash, _ = sha256_file(CONTRACT_PATH)
    if authorization.get("contract_sha256") != contract_hash or authorization.get("e3_scoring_authorized") is not True:
        raise RuntimeError("scoring authorization does not bind the frozen score contract")
    for key, entry in contract["input_files"].items():
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"score contract input mismatch during independent audit: {key}")
    for name, entry in contract["source_files"].items():
        path = REPO_ROOT / entry["path"]
        digest, size = sha256_file(path)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"score source changed before independent audit: {name}")

    run_receipt = read_json(OUTPUT_ROOT / "e3-score-run-receipt-v01.json")
    preflight = read_json(OUTPUT_ROOT / "prelabel-preflight-v01.json")
    scored_metrics = read_json(OUTPUT_ROOT / "metrics-and-gates-v01.json")
    if run_receipt.get("status") != "E3_V02_HELDOUT_SCORING_COMPLETE_PENDING_INDEPENDENT_REPLAY":
        raise RuntimeError("scoring execution receipt is not complete")
    if preflight.get("evaluation_label_file_opened") is not False or preflight.get("evaluation_label_content_hashed") is not False:
        raise RuntimeError("prelabel receipt reports premature held-out label access")
    eval_entry = next(entry for entry in e1_seal["entries"] if entry["path"] == "labels/eval-labels-v01.jsonl")
    if run_receipt.get("evaluation_label_file_open_count") != 1 or run_receipt.get("e1_evaluation_labels_sha256_expected") != eval_entry["sha256"] or run_receipt.get("e1_evaluation_labels_sha256_observed_in_single_stream") != eval_entry["sha256"] or run_receipt.get("e1_evaluation_labels_bytes_observed_in_single_stream") != eval_entry["bytes"]:
        raise RuntimeError("single-stream evaluation label identity receipt does not match sealed E1")
    if run_receipt.get("refit_performed") is not False or run_receipt.get("scaler_changes_performed") is not False or run_receipt.get("representation_search_performed") is not False or run_receipt.get("hyperparameter_rescue_performed") is not False or run_receipt.get("shared_heads_used") is not False or run_receipt.get("E4_integration_opened") is not False:
        raise RuntimeError("scoring execution exceeded its authorized scope")

    rows, grouped = load_truth_rows()
    support: dict[str, list[int]] = {}
    for task, (label, classes, scope) in TASKS.items():
        subset = [row for row in rows if scope == "all" or (row["truth"]["context_term_id"] < 16 and row["truth"]["entity_term_id"] < 16)]
        if task == "exact_target":
            for endpoint, stratum in TARGET_STRATA.items():
                values = [row["truth"][label] for row in subset if row["target_stratum"] == stratum]
                support[endpoint.upper()] = np.bincount(values, minlength=classes).tolist()
        else:
            key = "RELATION_IDENTITY" if task == "relation" else "OBSERVED_STATE" if task == "observed_state" else task.upper()
            support[key] = np.bincount([row["truth"][label] for row in subset], minlength=classes).tolist()
    if support != e1_support["test_class_support"] or support != run_receipt.get("e1_test_support"):
        raise RuntimeError("scored-row truth support does not match the sealed E1 support receipt")
    predictions = recompute_predictions(rows, int(contract["inference"]["batch_rows"]))
    e0 = read_json(PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json")
    replayed, bootstrap = replay_metrics(rows, grouped, predictions, e0)
    disposition_text, passed, failed = disposition(replayed)
    if replayed != scored_metrics.get("endpoints"):
        raise RuntimeError("independent per-endpoint metric replay differs from scoring output")
    if scored_metrics.get("terminal_disposition") != disposition_text or scored_metrics.get("passed_endpoints") != passed or scored_metrics.get("failed_endpoints") != failed:
        raise RuntimeError("independent terminal disposition replay differs from scoring output")
    if run_receipt.get("terminal_disposition") != disposition_text or run_receipt.get("passed_endpoints") != passed or run_receipt.get("failed_endpoints") != failed:
        raise RuntimeError("independent terminal disposition differs from scoring receipt")
    with np.load(OUTPUT_ROOT / "whole-quartet-bootstrap-v01.npz", allow_pickle=False) as stored:
        if set(stored.files) != set(ENDPOINTS):
            raise RuntimeError("stored bootstrap artifact has wrong endpoint set")
        for endpoint in ENDPOINTS:
            if not np.array_equal(stored[endpoint], bootstrap[endpoint]):
                raise RuntimeError(f"independent bootstrap replay differs for {endpoint}")

    seal, seal_root = build_score_seal()
    audit = {
        "audit_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_V01_INDEPENDENT_AUDIT",
        "status": "E3_SCORE_V01_INDEPENDENT_REPLAY_PASS_SCORING_DISPOSITION_SEALED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e1_root_sha256": EXPECTED_E1_ROOT,
        "e2_v07_root_sha256": EXPECTED_E2_ROOT,
        "e3_v02_root_sha256": EXPECTED_E3_ROOT,
        "score_seal_root_sha256": seal_root,
        "score_seal_entry_count": seal["entry_count"],
        "all_eight_endpoint_metrics_replayed": True,
        "all_10000_bootstrap_replicates_replayed_per_endpoint": True,
        "prediction_replay_passed": True,
        "row_identity_replay_passed": True,
        "support_replay_passed": True,
        "evaluation_label_single_stream_receipt_passed": True,
        "raw_evaluation_label_file_opened_by_auditor": False,
        "terminal_disposition": disposition_text,
        "passed_endpoints": passed,
        "failed_endpoints": failed,
        "E4_integration_authorized": False,
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
