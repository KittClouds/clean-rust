from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
E0_SEAL_PATH = PROJECT / "seals" / "e0-seal-v10.json"
E0_AUDIT_PATH = PROJECT / "audits" / "e0-v10-independent-audit-v01.json"
E0_CONTRACT_PATH = PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json"
E1_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
E1_SEAL_PATH = E1_ROOT / "e1-seal-v01.json"
E1_AUDIT_PATH = PROJECT / "audits" / "e1-independent-audit-v04.json"
E1_SUPPORT_PATH = E1_ROOT / "receipts" / "support-receipt-v01.json"
E1_ROWS_PATH = E1_ROOT / "panel" / "row-manifest-v01.jsonl"
E1_SPLIT_PATH = E1_ROOT / "panel" / "split-manifest-v01.jsonl"
E1_EVAL_LABELS_PATH = E1_ROOT / "labels" / "eval-labels-v01.jsonl"
E2_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07")
FEATURE_CACHE_PATH = E2_ROOT / "V1_FINAL_POSITION.f32le"
E3_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02")
E3_SEAL_PATH = E3_ROOT / "e3-v02-seal.json"
E3_AUDIT_PATH = E3_ROOT / "e3-v02-independent-audit-v01.json"
E3_BUNDLE_PATH = E3_ROOT / "frozen-capability-fabric-v02.json"
CONTRACT_PATH = PROJECT / "contracts" / "e3-score-v01.json"
AUTHORIZATION_PATH = PROJECT / "audits" / "e3-score-authorization-v01.json"
OUTPUT_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-score-v01")
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
EXPECTED_E3_ROOT = "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1"
ROWS = 106_496
DIM = 2_048
TEST_ROWS = 21_292
QUARTET_VARIANTS = ("A", "C", "E", "P")
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
    "context_identity": ("context_term_id", 32, "all_test_rows"),
    "entity_identity": ("entity_term_id", 32, "all_test_rows"),
    "relation": ("relation_id", 2, "both_terms_train_side"),
    "observed_state": ("state_id", 3, "both_terms_train_side"),
    "exact_target": ("exact_target", 3, "all_test_rows"),
}
TARGET_STRATA = {
    "IN_DOMAIN": "exact_target_in_domain",
    "CONTEXT_NOVEL": "exact_target_context_novel",
    "ENTITY_NOVEL": "exact_target_entity_novel",
    "BOTH_NOVEL": "exact_target_both_novel",
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


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def path_tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def artifact_tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def verify_e0_seal() -> dict[str, Any]:
    seal = read_json(E0_SEAL_PATH)
    actual = []
    for entry in seal.get("entries", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe E0 sealed path: {entry['path']}")
        digest, size = sha256_file(REPO_ROOT / relative)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"E0 sealed member mismatch: {entry['path']}")
        actual.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if len(actual) != seal.get("entry_count") or path_tree_root(actual) != EXPECTED_E0_ROOT:
        raise RuntimeError("E0 v10 seal root failed recomputation")
    return seal


def verify_e3_seal() -> dict[str, Any]:
    seal = read_json(E3_SEAL_PATH)
    entries = seal.get("entries", [])
    for entry in entries:
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"E3 sealed member mismatch: {entry.get('artifact_id')}")
    if artifact_tree_root(entries) != EXPECTED_E3_ROOT or seal.get("root_sha256") != EXPECTED_E3_ROOT:
        raise RuntimeError("E3 v02 root failed recomputation")
    return seal


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"invalid JSONL in {path.name} at line {line_no}") from error
    return rows


def parse_performance_floor(gate_text: str) -> float:
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)?)", gate_text)
    if match is None:
        raise RuntimeError("frozen E0 performance gate does not contain a parseable numeric floor")
    return float(match.group(1))


def require_file_identity(contract: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    expected = contract["input_files"][key]
    if str(path.resolve()) != expected["path"]:
        raise RuntimeError(f"scoring input path changed for {key}")
    digest, size = sha256_file(path)
    if digest != expected["sha256"] or size != expected["bytes"]:
        raise RuntimeError(f"scoring input identity changed for {key}")
    return {"path": str(path.resolve()), "sha256": digest, "bytes": size}


def verify_inference_contract(inference: dict[str, Any]) -> int:
    if not isinstance(inference, dict):
        raise RuntimeError("scoring inference contract is missing")
    if inference.get("backend") != "PyTorch CPU float32 linear inference":
        raise RuntimeError("scoring inference backend differs from the frozen CPU execution contract")
    if inference.get("torch_num_threads") != 1 or inference.get("torch_num_interop_threads") != 1 or inference.get("tf32") is not False or inference.get("cuda_contact") is not False:
        raise RuntimeError("scoring inference execution controls differ from the frozen CPU contract")
    batch_rows = inference.get("batch_rows")
    if isinstance(batch_rows, bool) or not isinstance(batch_rows, int) or batch_rows < 1:
        raise RuntimeError("scoring inference batch size is invalid")
    if inference.get("linear_operation") != "torch.nn.functional.linear((features - mean) / scale, weight, bias); argmax over class dimension":
        raise RuntimeError("scoring linear operation differs from the frozen inference contract")
    return batch_rows


def target_stratum(context_id: int, entity_id: int) -> str:
    return {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(context_id >= 16, entity_id >= 16)]


def metric_summary(y_true: np.ndarray, y_pred: np.ndarray, class_count: int) -> dict[str, Any]:
    if len(y_true) == 0 or len(y_true) != len(y_pred):
        raise RuntimeError("metric input is empty or has mismatched prediction rows")
    if np.any(y_true < 0) or np.any(y_true >= class_count) or np.any(y_pred < 0) or np.any(y_pred >= class_count):
        raise RuntimeError("metric input contains an out-of-range class ID")
    confusion = np.bincount(y_true * class_count + y_pred, minlength=class_count * class_count).reshape(class_count, class_count)
    support = confusion.sum(axis=1)
    if np.any(support == 0):
        raise RuntimeError("scored endpoint is missing a declared truth class")
    recall = np.diag(confusion) / support
    return {
        "rows": int(len(y_true)),
        "accuracy": float(np.trace(confusion) / len(y_true)),
        "balanced_accuracy": float(recall.mean()),
        "class_ids": list(range(class_count)),
        "class_support": support.astype(np.int64).tolist(),
        "per_class_recall": recall.astype(np.float64).tolist(),
        "confusion_matrix": confusion.astype(np.int64).tolist(),
    }


def whole_quartet_bootstrap_lower_bound(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    quartet_ids: list[str],
    quartet_strata: list[int],
    class_count: int,
    replicates: int,
    rng: np.random.Generator,
    chunk_replicates: int = 64,
) -> tuple[float, np.ndarray, dict[str, int]]:
    if len(y_true) != len(y_pred) or len(y_true) != len(quartet_ids) or len(y_true) != len(quartet_strata):
        raise RuntimeError("bootstrap inputs have mismatched lengths")
    q_rows: dict[str, list[int]] = {}
    q_stratum: dict[str, int] = {}
    for row_index, (quartet, stratum) in enumerate(zip(quartet_ids, quartet_strata, strict=True)):
        if quartet not in q_rows:
            q_rows[quartet] = []
            q_stratum[quartet] = int(stratum)
        elif q_stratum[quartet] != int(stratum):
            raise RuntimeError(f"bootstrap class stratum varies within quartet {quartet}")
        q_rows[quartet].append(row_index)

    ordered_quartets = list(q_rows)
    support_by_quartet = np.zeros((len(ordered_quartets), class_count), dtype=np.int64)
    correct_by_quartet = np.zeros_like(support_by_quartet)
    for q_index, quartet in enumerate(ordered_quartets):
        rows = np.asarray(q_rows[quartet], dtype=np.int64)
        truth = y_true[rows]
        support_by_quartet[q_index] = np.bincount(truth, minlength=class_count)
        correct_by_quartet[q_index] = np.bincount(truth[y_pred[rows] == truth], minlength=class_count)

    strata_to_q: dict[int, list[int]] = {}
    for q_index, quartet in enumerate(ordered_quartets):
        strata_to_q.setdefault(q_stratum[quartet], []).append(q_index)
    if set(strata_to_q) != set(range(class_count)):
        raise RuntimeError("whole-quartet bootstrap lacks one or more frozen class strata")

    boot_support = np.zeros((replicates, class_count), dtype=np.int64)
    boot_correct = np.zeros_like(boot_support)
    for stratum in range(class_count):
        q_indices = np.asarray(strata_to_q[stratum], dtype=np.int64)
        q_count = len(q_indices)
        if q_count == 0:
            raise RuntimeError(f"empty bootstrap stratum {stratum}")
        for start in range(0, replicates, chunk_replicates):
            stop = min(start + chunk_replicates, replicates)
            draws = rng.integers(0, q_count, size=(stop - start, q_count), dtype=np.int32)
            sampled_q = q_indices[draws]
            boot_support[start:stop] += support_by_quartet[sampled_q].sum(axis=1)
            boot_correct[start:stop] += correct_by_quartet[sampled_q].sum(axis=1)
    if np.any(boot_support == 0):
        raise RuntimeError("bootstrap replicate omitted a scored truth class")
    bootstrap_scores = (boot_correct / boot_support).mean(axis=1)
    lower = float(np.quantile(bootstrap_scores, 0.05, method="linear"))
    return lower, bootstrap_scores.astype(np.float64), {str(k): len(v) for k, v in sorted(strata_to_q.items())}


def preflight() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if OUTPUT_ROOT.exists():
        raise RuntimeError(f"score output root already exists; preserving it: {OUTPUT_ROOT}")
    e0_seal = verify_e0_seal()
    e0_audit = read_json(E0_AUDIT_PATH)
    e1_seal = read_json(E1_SEAL_PATH)
    e1_audit = read_json(E1_AUDIT_PATH)
    if e1_seal.get("root_sha256") != EXPECTED_E1_ROOT or path_tree_root(e1_seal.get("entries", [])) != EXPECTED_E1_ROOT:
        raise RuntimeError("E1 v04 manifest root does not match the frozen population")
    if e1_audit.get("status") != "PASS" or e1_audit.get("e1_root_sha256") != EXPECTED_E1_ROOT:
        raise RuntimeError("E1 v04 independent audit did not pass")
    e3_seal = verify_e3_seal()
    e3_audit = read_json(E3_AUDIT_PATH)
    if e3_audit.get("status") != "E3_V02_FIVE_FITS_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED" or e3_audit.get("e3_root_sha256") != EXPECTED_E3_ROOT or e3_audit.get("all_checks_passed") is not True:
        raise RuntimeError("E3 v02 independent audit did not pass")
    contract = read_json(CONTRACT_PATH)
    authorization = read_json(AUTHORIZATION_PATH)
    contract_hash, _ = sha256_file(CONTRACT_PATH)
    auth_hash, _ = sha256_file(AUTHORIZATION_PATH)
    if contract.get("schema") != "fas-frozen-observer-bundle-e3-score-v01":
        raise RuntimeError("unsupported E3 score contract schema")
    if contract.get("e0_root_sha256") != EXPECTED_E0_ROOT or contract.get("e1_root_sha256") != EXPECTED_E1_ROOT or contract.get("e2_v07_root_sha256") != EXPECTED_E2_ROOT or contract.get("e3_v02_root_sha256") != EXPECTED_E3_ROOT:
        raise RuntimeError("scoring contract does not bind the frozen E0/E1/E2/E3 identities")
    if tuple(contract.get("endpoints", [])) != ENDPOINTS:
        raise RuntimeError("scoring contract endpoint list/order differs from the frozen E0 contract")
    for key, path in contract["source_files"].items():
        source_path = (REPO_ROOT / path["path"]).resolve()
        digest, size = sha256_file(source_path)
        if digest != path["sha256"] or size != path["bytes"]:
            raise RuntimeError(f"scoring source identity changed for {key}")
    verified_inputs = {
        "e0_contract": require_file_identity(contract, "e0_contract", E0_CONTRACT_PATH),
        "e0_seal": require_file_identity(contract, "e0_seal", E0_SEAL_PATH),
        "e0_audit": require_file_identity(contract, "e0_audit", E0_AUDIT_PATH),
        "e1_seal": require_file_identity(contract, "e1_seal", E1_SEAL_PATH),
        "e1_audit": require_file_identity(contract, "e1_audit", E1_AUDIT_PATH),
        "e1_support": require_file_identity(contract, "e1_support", E1_SUPPORT_PATH),
        "e1_rows": require_file_identity(contract, "e1_rows", E1_ROWS_PATH),
        "e1_split": require_file_identity(contract, "e1_split", E1_SPLIT_PATH),
        "e3_seal": require_file_identity(contract, "e3_seal", E3_SEAL_PATH),
        "e3_audit": require_file_identity(contract, "e3_audit", E3_AUDIT_PATH),
        "e3_bundle": require_file_identity(contract, "e3_bundle", E3_BUNDLE_PATH),
        "feature_cache": require_file_identity(contract, "feature_cache", FEATURE_CACHE_PATH),
    }
    for source_name, source_entry in contract["source_files"].items():
        if source_name not in {"scorer", "tests", "contract_builder", "independent_auditor"}:
            raise RuntimeError(f"unknown scoring source identity: {source_name}")
    verify_inference_contract(contract.get("inference"))
    if authorization.get("contract_sha256") != contract_hash or authorization.get("e3_scoring_authorized") is not True:
        raise RuntimeError("E3 scoring authorization is absent or does not bind its contract")
    if authorization.get("e0_root_sha256") != EXPECTED_E0_ROOT or authorization.get("e1_root_sha256") != EXPECTED_E1_ROOT or authorization.get("e3_v02_root_sha256") != EXPECTED_E3_ROOT or authorization.get("refit_authorized") is not False or authorization.get("E4_integration_authorized") is not False or authorization.get("one_evaluation_label_opening") is not True:
        raise RuntimeError("E3 scoring authorization is broader than the sealed scoring-only scope")
    if e0_seal.get("root_sha256") != EXPECTED_E0_ROOT or e0_audit.get("all_checks_passed") is not True:
        raise RuntimeError("E0 v10 freeze or independent audit failed")

    eval_entry = next((row for row in e1_seal["entries"] if row["path"] == "labels/eval-labels-v01.jsonl"), None)
    if eval_entry is None:
        raise RuntimeError("sealed E1 manifest does not bind the evaluation label artifact")
    if str(E1_EVAL_LABELS_PATH.resolve()) != contract["evaluation_labels"]["path"]:
        raise RuntimeError("evaluation label path differs from the frozen scoring contract")
    if eval_entry["sha256"] != contract["evaluation_labels"]["sha256"] or eval_entry["bytes"] != contract["evaluation_labels"]["bytes"]:
        raise RuntimeError("evaluation label identity differs between E1 seal and scoring contract")

    expected_sources = contract.get("runtime", {})
    if expected_sources.get("python_version") != sys.version.split()[0] or expected_sources.get("numpy_version") != np.__version__ or expected_sources.get("torch_version") != torch.__version__:
        raise RuntimeError("Python/NumPy/PyTorch runtime differs from the pre-score freeze")

    output_usage = shutil.disk_usage(OUTPUT_ROOT.parent)
    minimum_free = int(contract["resources"]["minimum_free_disk_bytes"])
    if output_usage.free < minimum_free:
        raise RuntimeError(f"scoring output volume free-space gate failed: {output_usage.free} < {minimum_free}")
    preflight_receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_V01_PREFLIGHT",
        "status": "PRELABEL_PREFLIGHT_PASS_EVALUATION_LABELS_NOT_OPENED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e1_root_sha256": EXPECTED_E1_ROOT,
        "e3_v02_root_sha256": EXPECTED_E3_ROOT,
        "e3_score_contract_sha256": contract_hash,
        "authorization_sha256": auth_hash,
        "e1_evaluation_label_expected_sha256": eval_entry["sha256"],
        "e1_evaluation_label_expected_bytes": eval_entry["bytes"],
        "evaluation_label_file_opened": False,
        "evaluation_label_content_hashed": False,
        "disk_free_bytes_before_scoring": int(output_usage.free),
        "minimum_free_disk_bytes": minimum_free,
        "disk_gate_passed": True,
        "verified_inputs": verified_inputs,
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
        "python_version": sys.version.split()[0],
        "cuda_initialized": False,
        "evaluation_scoring_performed": False,
    }
    return e1_seal, e3_seal, contract, preflight_receipt


def load_evaluation_once(expected_sha256: str, expected_bytes: int, stream_state: dict[str, Any]) -> tuple[list[dict[str, Any]], str, int]:
    digest = hashlib.sha256()
    labels: list[dict[str, Any]] = []
    bytes_read = 0
    # This is the sole direct open/read of the sealed E1 TEST-label file in the scoring execution.
    with E1_EVAL_LABELS_PATH.open("rb", buffering=0) as stream:
        stream_state["opened"] = True
        for line_no, raw_line in enumerate(stream, start=1):
            digest.update(raw_line)
            bytes_read += len(raw_line)
            stream_state["bytes_read"] = bytes_read
            stream_state["rows_parsed"] = len(labels)
            stream_state["partial_sha256"] = digest.copy().hexdigest()
            try:
                labels.append(json.loads(raw_line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError(f"invalid held-out label JSONL at line {line_no}") from error
            stream_state["rows_parsed"] = len(labels)
    actual_sha = digest.hexdigest()
    if bytes_read != expected_bytes or actual_sha != expected_sha256:
        raise RuntimeError("the once-opened evaluation label file differs from the sealed E1 identity")
    return labels, actual_sha, bytes_read


def build_test_rows(e1_seal: dict[str, Any], labels: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    row_manifest = read_jsonl(E1_ROWS_PATH)
    split_manifest = read_jsonl(E1_SPLIT_PATH)
    split_by_quartet: dict[str, str] = {}
    for item in split_manifest:
        qid = item["quartet_id"]
        if qid in split_by_quartet:
            raise RuntimeError(f"duplicate E1 split quartet: {qid}")
        split_by_quartet[qid] = item["split"]
    if len(row_manifest) != ROWS or [row["row_index"] for row in row_manifest] != list(range(ROWS)):
        raise RuntimeError("E1 row manifest is not the frozen complete feature-cache ordering")
    expected_test_rows = []
    rows_by_quartet: dict[str, list[dict[str, Any]]] = {}
    for row in row_manifest:
        if row.get("quartet_split") != split_by_quartet.get(row.get("quartet_id")):
            raise RuntimeError("E1 row manifest and split manifest disagree")
        if row["quartet_split"] == "TEST":
            expected_test_rows.append(row)
            rows_by_quartet.setdefault(row["quartet_id"], []).append(row)
    if len(expected_test_rows) != TEST_ROWS or len(labels) != TEST_ROWS:
        raise RuntimeError("held-out row count differs from the sealed E1 test population")
    joined: list[dict[str, Any]] = []
    for expected, label in zip(expected_test_rows, labels, strict=True):
        if label.get("row_id") != expected["row_id"] or label.get("quartet_id") != expected["quartet_id"] or label.get("variant_id") != expected["variant_id"]:
            raise RuntimeError("held-out label row identity differs from sealed E1 feature order")
        if split_by_quartet[label["quartet_id"]] != "TEST":
            raise RuntimeError("evaluation labels contain a non-TEST quartet")
        context, entity = label.get("context_term_id"), label.get("entity_term_id")
        if isinstance(context, bool) or isinstance(entity, bool) or not isinstance(context, int) or not isinstance(entity, int):
            raise RuntimeError("held-out factor identity label is malformed")
        stratum = target_stratum(context, entity)
        if label.get("score_strata") != stratum:
            raise RuntimeError("held-out target novelty label does not match the frozen term-ID rule")
        if label.get("both_terms_train_side") is not (context < 16 and entity < 16):
            raise RuntimeError("held-out train-side eligibility flag does not match frozen IDs")
        for field, class_count in (("context_term_id", 32), ("entity_term_id", 32), ("relation_id", 2), ("state_id", 3), ("exact_target", 3)):
            value = label.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < class_count:
                raise RuntimeError(f"held-out {field} label is malformed")
        joined.append({**expected, "labels": label, "target_stratum": stratum})
    for quartet, rows in rows_by_quartet.items():
        if tuple(row["variant_id"] for row in rows) != QUARTET_VARIANTS:
            raise RuntimeError(f"TEST quartet is incomplete or misordered: {quartet}")
    return joined, rows_by_quartet


def support_counts(rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    values: dict[str, list[int]] = {}
    for task, (label_field, class_count, _) in TASKS.items():
        selected = [row for row in rows if task not in ("relation", "observed_state") or row["labels"]["both_terms_train_side"]]
        if task == "exact_target":
            for stratum, endpoint in TARGET_STRATA.items():
                endpoint_rows = [row for row in selected if row["target_stratum"] == stratum]
                counts = np.bincount([row["labels"][label_field] for row in endpoint_rows], minlength=class_count)
                values[endpoint.upper()] = counts.astype(np.int64).tolist()
        else:
            key = "RELATION_IDENTITY" if task == "relation" else "OBSERVED_STATE" if task == "observed_state" else task.upper()
            counts = np.bincount([row["labels"][label_field] for row in selected], minlength=class_count)
            values[key] = counts.astype(np.int64).tolist()
    return values


def infer_task(
    task: str,
    rows: list[dict[str, Any]],
    feature_cache: np.memmap,
    batch_rows: int,
) -> tuple[np.ndarray, np.ndarray]:
    label_field, class_count, scope = TASKS[task]
    selected = np.asarray([
        i for i, row in enumerate(rows)
        if scope == "all_test_rows" or row["labels"]["both_terms_train_side"]
    ], dtype=np.int64)
    if task == "exact_target":
        selected = np.arange(len(rows), dtype=np.int64)
    model_root = E3_ROOT
    mean = np.fromfile(model_root / f"{task}.mean.f32le", dtype="<f4")
    scale = np.fromfile(model_root / f"{task}.scale.f32le", dtype="<f4")
    weights = np.fromfile(model_root / f"{task}.weight.f32le", dtype="<f4").reshape(class_count, DIM)
    bias = np.fromfile(model_root / f"{task}.bias.f32le", dtype="<f4")
    if mean.size != DIM or scale.size != DIM or bias.size != class_count or not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.isfinite(weights).all() or not np.isfinite(bias).all():
        raise RuntimeError(f"observer artifact integrity failed during scoring: {task}")
    torch_mean = torch.from_numpy(mean.copy())
    torch_scale = torch.from_numpy(scale.copy())
    torch_weights = torch.from_numpy(weights.copy())
    torch_bias = torch.from_numpy(bias.copy())
    predictions = np.full(len(rows), -1, dtype=np.int64)
    for start in range(0, len(selected), batch_rows):
        positions = selected[start : start + batch_rows]
        feature_indices = np.asarray([rows[int(i)]["row_index"] for i in positions], dtype=np.int64)
        x_array = np.array(feature_cache[feature_indices], dtype=np.float32, order="C", copy=True)
        if not bool(np.isfinite(x_array).all()):
            raise RuntimeError(f"non-finite raw scoring features for {task}")
        x = torch.from_numpy(x_array)
        x.sub_(torch_mean).div_(torch_scale)
        if not bool(torch.isfinite(x).all()):
            raise RuntimeError(f"non-finite standardized scoring features for {task}")
        logits = F.linear(x, torch_weights, torch_bias)
        predictions[positions] = torch.argmax(logits, dim=1).numpy()
    return selected, predictions


def task_stratum_for_quartet(task: str, rows_by_quartet: dict[str, list[dict[str, Any]]], quartet: str) -> int:
    baseline = next((row for row in rows_by_quartet[quartet] if row["variant_id"] == "A"), None)
    if baseline is None:
        raise RuntimeError(f"TEST quartet lacks the baseline A variant: {quartet}")
    labels = baseline["labels"]
    field = {
        "context_identity": "context_term_id",
        "entity_identity": "entity_term_id",
        "relation": "relation_id",
        "observed_state": "state_id",
        "exact_target": "exact_target",
    }[task]
    return int(labels[field])


def score_endpoints(
    rows: list[dict[str, Any]],
    rows_by_quartet: dict[str, list[dict[str, Any]]],
    predictions: dict[str, np.ndarray],
    e0: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    endpoint_spec = e0["performance_gates"]["individual_endpoints"]
    if tuple(endpoint_spec) != ENDPOINTS:
        raise RuntimeError("E0 individual endpoint order differs from the frozen scorer contract")
    replicate_count = int(e0["bootstrap"]["replicates"])
    seed = int(e0["bootstrap"]["seed"])
    generator = np.random.Generator(np.random.PCG64(seed))
    metrics: dict[str, Any] = {}
    bootstrap_values: dict[str, np.ndarray] = {}
    min_rows = int(e0["performance_gates"]["minimum_test_rows_per_class"])
    floor = parse_performance_floor(e0["performance_gates"]["gate"])

    for endpoint in ENDPOINTS:
        if endpoint.startswith("exact_target_"):
            stratum_name = {
                "exact_target_in_domain": "IN_DOMAIN",
                "exact_target_context_novel": "CONTEXT_NOVEL",
                "exact_target_entity_novel": "ENTITY_NOVEL",
                "exact_target_both_novel": "BOTH_NOVEL",
            }[endpoint]
            selected = [i for i, row in enumerate(rows) if row["target_stratum"] == stratum_name]
            task = "exact_target"
            class_count = 3
            label_field = "exact_target"
        else:
            task = endpoint
            label_field, class_count, scope = TASKS[task]
            selected = [i for i, row in enumerate(rows) if scope == "all_test_rows" or row["labels"]["both_terms_train_side"]]
        row_indices = np.asarray(selected, dtype=np.int64)
        y_true = np.asarray([rows[int(i)]["labels"][label_field] for i in row_indices], dtype=np.int64)
        y_pred = predictions[task][row_indices]
        point = metric_summary(y_true, y_pred, class_count)
        if min(point["class_support"]) < min_rows:
            raise RuntimeError(f"minimum support gate failed at {endpoint}")
        quartet_ids = [rows[int(i)]["quartet_id"] for i in row_indices]
        strata = [task_stratum_for_quartet(task, rows_by_quartet, qid) for qid in quartet_ids]
        lower, values, quartet_stratum_counts = whole_quartet_bootstrap_lower_bound(
            y_true, y_pred, quartet_ids, strata, class_count, replicate_count, generator,
        )
        passed = lower >= floor
        metrics[endpoint] = {
            **point,
            "bootstrap_replicates": replicate_count,
            "bootstrap_seed": seed,
            "bootstrap_rng": "NumPy PCG64; one generator consumed in frozen endpoint order",
            "bootstrap_resampling_unit": "whole quartet; class-stratified among eligible TEST quartets",
            "bootstrap_lower_bound_percentile": 5,
            "bootstrap_quantile_method": "linear",
            "balanced_accuracy_lower_95": lower,
            "minimum_rows_per_class": min_rows,
            "support_gate_pass": True,
            "performance_floor": floor,
            "gate_pass": passed,
            "bootstrap_eligible_quartets_by_stratum": quartet_stratum_counts,
        }
        bootstrap_values[endpoint] = values
    return metrics, bootstrap_values


def terminal_disposition(metrics: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    passed = [endpoint for endpoint in ENDPOINTS if metrics[endpoint]["gate_pass"]]
    failed = [endpoint for endpoint in ENDPOINTS if not metrics[endpoint]["gate_pass"]]
    if len(passed) == len(ENDPOINTS):
        disposition = "ALL_EIGHT_GATES_PASS_BUNDLE_QUALIFIED_FOR_ROUTING_DESIGN"
    elif passed:
        disposition = "PARTIAL_CAPABILITY_FABRIC_ONLY_PASSED_ENDPOINTS_QUALIFIED"
    else:
        disposition = "NO_PERFORMANCE_GATES_PASS_CHEAP_FITTING_DID_NOT_YIELD_QUALIFIED_ENDPOINTS"
    return disposition, passed, failed


def main(preflight_only: bool = False) -> int:
    stream_state: dict[str, Any] = {"opened": False, "bytes_read": 0, "rows_parsed": 0, "partial_sha256": None}
    opened_label_hash: str | None = None
    labels_read = 0
    output_created = False
    try:
        e1_seal, e3_seal, contract, preflight_receipt = preflight()
        if preflight_only:
            print(json.dumps({
                "status": preflight_receipt["status"],
                "evaluation_label_file_opened": False,
                "evaluation_label_content_hashed": False,
                "verified_input_count": len(preflight_receipt["verified_inputs"]),
                "disk_free_bytes_before_scoring": preflight_receipt["disk_free_bytes_before_scoring"],
                "e0_root_sha256": EXPECTED_E0_ROOT,
                "e1_root_sha256": EXPECTED_E1_ROOT,
                "e3_v02_root_sha256": EXPECTED_E3_ROOT,
            }, indent=2))
            return 0
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        OUTPUT_ROOT.mkdir(parents=True)
        output_created = True
        (OUTPUT_ROOT / "prelabel-preflight-v01.json").write_bytes(canonical_json(preflight_receipt))
        support = read_json(E1_SUPPORT_PATH)
        row_manifest = read_jsonl(E1_ROWS_PATH)
        split_manifest = read_jsonl(E1_SPLIT_PATH)
        e0 = read_json(E0_CONTRACT_PATH)
        e1_entry = next(row for row in e1_seal["entries"] if row["path"] == "labels/eval-labels-v01.jsonl")

        eval_rows, opened_label_hash, labels_read = load_evaluation_once(e1_entry["sha256"], int(e1_entry["bytes"]), stream_state)
        joined, rows_by_quartet = build_test_rows(e1_seal, eval_rows)
        actual_support = support_counts(joined)
        expected_support = support["test_class_support"]
        if actual_support != expected_support:
            raise RuntimeError("opened E1 test-label support does not match the sealed pre-model support receipt")
        if any(min(values) < int(e0["performance_gates"]["minimum_test_rows_per_class"]) for values in actual_support.values()):
            raise RuntimeError("opened E1 test-label support violates the frozen per-class floor")

        feature_cache = np.memmap(FEATURE_CACHE_PATH, dtype="<f4", mode="r", shape=(ROWS, DIM))
        predictions: dict[str, np.ndarray] = {}
        batch_rows = verify_inference_contract(contract.get("inference"))
        for task in TASKS:
            _, predictions[task] = infer_task(task, joined, feature_cache, batch_rows)
        del feature_cache
        metrics, bootstrap = score_endpoints(joined, rows_by_quartet, predictions, e0)
        disposition, passed, failed = terminal_disposition(metrics)

        scored_rows_path = OUTPUT_ROOT / "scored-test-rows-v01.jsonl"
        with scored_rows_path.open("wb", buffering=0) as stream:
            for i, row in enumerate(joined):
                truth = {field: int(row["labels"][field]) for field in ("context_term_id", "entity_term_id", "relation_id", "state_id", "exact_target")}
                record = {
                    "row_index": int(row["row_index"]),
                    "row_id": row["row_id"],
                    "quartet_id": row["quartet_id"],
                    "variant_id": row["variant_id"],
                    "target_stratum": row["target_stratum"],
                    "truth": truth,
                    "prediction": {
                        task: (int(predictions[task][i]) if int(predictions[task][i]) >= 0 else None)
                        for task in TASKS
                    },
                }
                stream.write((json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8"))

        bootstrap_path = OUTPUT_ROOT / "whole-quartet-bootstrap-v01.npz"
        np.savez_compressed(bootstrap_path, **{endpoint: bootstrap[endpoint] for endpoint in ENDPOINTS})
        metrics_path = OUTPUT_ROOT / "metrics-and-gates-v01.json"
        metrics_doc = {
            "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_METRICS_V01",
            "status": "SCORED_NO_INDEPENDENT_REPLAY_YET",
            "e0_root_sha256": EXPECTED_E0_ROOT,
            "e1_root_sha256": EXPECTED_E1_ROOT,
            "e3_v02_root_sha256": EXPECTED_E3_ROOT,
            "endpoints": metrics,
            "terminal_disposition": disposition,
            "passed_endpoints": passed,
            "failed_endpoints": failed,
            "bundle_qualified": len(passed) == len(ENDPOINTS),
            "qualified_heads": {
                "context_identity": metrics["context_identity"]["gate_pass"],
                "entity_identity": metrics["entity_identity"]["gate_pass"],
                "relation": metrics["relation"]["gate_pass"],
                "observed_state": metrics["observed_state"]["gate_pass"],
                "exact_target": all(metrics[name]["gate_pass"] for name in ENDPOINTS[4:]),
            },
            "evaluation_label_sha256": opened_label_hash,
            "evaluation_label_bytes": labels_read,
            "evaluation_rows": len(joined),
            "test_quartets": len(rows_by_quartet),
            "evaluation_labels_opened_once": True,
            "refit_performed": False,
            "score_tuning_or_rescue_performed": False,
            "E4_integration_opened": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        metrics_path.write_bytes(canonical_json(metrics_doc))
        score_receipt = {
            "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_RUN_V01",
            "status": "E3_V02_HELDOUT_SCORING_COMPLETE_PENDING_INDEPENDENT_REPLAY",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "e0_root_sha256": EXPECTED_E0_ROOT,
            "e1_root_sha256": EXPECTED_E1_ROOT,
            "e3_v02_root_sha256": EXPECTED_E3_ROOT,
            "e3_score_contract_sha256": sha256_file(CONTRACT_PATH)[0],
            "authorization_sha256": sha256_file(AUTHORIZATION_PATH)[0],
            "e1_evaluation_labels_sha256_expected": e1_entry["sha256"],
            "e1_evaluation_labels_sha256_observed_in_single_stream": opened_label_hash,
            "e1_evaluation_labels_bytes_expected": e1_entry["bytes"],
            "e1_evaluation_labels_bytes_observed_in_single_stream": labels_read,
            "evaluation_label_file_open_count": 1,
            "evaluation_label_rows": len(joined),
            "test_quartets": len(rows_by_quartet),
            "support_matches_sealed_e1_receipt": True,
            "e1_test_support": actual_support,
            "predictions_path": str(scored_rows_path.resolve()),
            "metrics_path": str(metrics_path.resolve()),
            "bootstrap_path": str(bootstrap_path.resolve()),
            "terminal_disposition": disposition,
            "passed_endpoints": passed,
            "failed_endpoints": failed,
            "refit_performed": False,
            "scaler_changes_performed": False,
            "representation_search_performed": False,
            "hyperparameter_rescue_performed": False,
            "shared_heads_used": False,
            "evaluation_scoring_performed": True,
            "E4_integration_opened": False,
            "evaluation_truth_labels_in_scored_rows_artifact": True,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        receipt_path = OUTPUT_ROOT / "e3-score-run-receipt-v01.json"
        receipt_path.write_bytes(canonical_json(score_receipt))
        print(json.dumps({
            "status": score_receipt["status"],
            "terminal_disposition": disposition,
            "passed_endpoints": passed,
            "failed_endpoints": failed,
            "label_sha256": opened_label_hash,
            "evaluation_rows": len(joined),
            "scoring_receipt": str(receipt_path),
        }, indent=2))
        return 0
    except Exception as error:
        if output_created:
            failure_path = OUTPUT_ROOT / "e3-score-stop-v01.json"
            if not failure_path.exists():
                failure = {
                    "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_SCORE_STOP_V01",
                    "status": "SCORING_ATTEMPT_STOPPED_AND_PRESERVED",
                    "recorded_utc": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(error).__name__}: {error}",
                    "evaluation_label_file_opened": stream_state["opened"],
                    "evaluation_label_sha256_if_completed": opened_label_hash,
                    "evaluation_label_bytes_read": stream_state["bytes_read"],
                    "evaluation_label_rows_parsed": stream_state["rows_parsed"],
                    "evaluation_label_partial_sha256": stream_state["partial_sha256"],
                    "refit_performed": False,
                    "E4_integration_opened": False,
                }
                failure_path.write_bytes(canonical_json(failure))
        raise


if __name__ == "__main__":
    raise SystemExit(main("--preflight-only" in sys.argv[1:]))
