#!/usr/bin/env python3
"""Diagnose a compositional action adapter from frozen clause identity outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

KINDS = ["different", "exactly_one_role", "fixed_role", "forbidden_role", "implies_not_role", "same"]
KIND_TO_ID = {value: index for index, value in enumerate(KINDS)}
EXPECTED_SUPPORT_SHA256 = "b05e99f83cec97342582dbacec0a3c7ba0bf634130f301dd909a886bcbb66e46"
EXPECTED_ADAPTER_MANIFEST_SHA256 = "4bac71dc6673fdab6dcfefea8407dc84af8694f01c1e5d029f9b858e5920e02d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def validate_inputs(args: argparse.Namespace) -> dict[str, Any]:
    adapter_manifest_path = Path(args.adapter_manifest)
    if sha256(adapter_manifest_path) != EXPECTED_ADAPTER_MANIFEST_SHA256:
        raise ValueError("semantic adapter manifest digest differs from frozen v01")
    adapter_manifest = json.loads(adapter_manifest_path.read_text(encoding="utf-8"))
    if adapter_manifest["manifest"] != "R1-SEMANTIC-ACTION-ADAPTER-v01":
        raise ValueError("unexpected semantic adapter manifest")
    support_path = Path(args.support_manifest)
    support_sha = sha256(support_path)
    if support_sha != EXPECTED_SUPPORT_SHA256:
        raise ValueError("support manifest digest differs from frozen v02")
    support = json.loads(support_path.read_text(encoding="utf-8"))
    public_path = Path(args.public_tasks)
    if sha256(public_path) != support["source"]["sha256"]:
        raise ValueError("public task input differs from frozen support roster")
    extraction = Path(args.extraction)
    extraction_receipt = json.loads((extraction / "receipt.json").read_text(encoding="utf-8"))
    if extraction_receipt["input"]["sha256"] != support["source"]["sha256"]:
        raise ValueError("extraction receipt has a different public input")
    if extraction_receipt["input"]["support_manifest"]["sha256"] != support_sha:
        raise ValueError("extraction receipt has a different support manifest")
    for entry in extraction_receipt["output_files"]:
        path = extraction / entry["path"]
        if path.stat().st_size != int(entry["bytes"]) or sha256(path) != entry["sha256"]:
            raise ValueError(f"extraction artifact failed receipt check: {entry['path']}")
    labels_dir = Path(args.labels)
    summary = json.loads((labels_dir / "support-summary.json").read_text(encoding="utf-8"))
    if summary["support_manifest_sha256"] != support_sha:
        raise ValueError("offline label summary has a different support manifest")
    if summary["public_input_sha256"] != support["source"]["sha256"]:
        raise ValueError("offline label summary has a different public input")
    if summary["clause_label_rows"] != 872 or summary["action_label_rows"] != 55008:
        raise ValueError("offline label row counts differ from the frozen support")
    for filename, digest_key in (("private-clause-labels.jsonl", "clause_labels_sha256"),
                                 ("private-action-labels.jsonl", "action_labels_sha256")):
        if sha256(labels_dir / filename) != summary[digest_key]:
            raise ValueError(f"offline label checksum mismatch: {filename}")
    report_dir = Path(args.sensor_probe)
    run_receipt = json.loads((report_dir / "run-receipt.json").read_text(encoding="utf-8"))
    report = json.loads((report_dir / "qualification-report.json").read_text(encoding="utf-8"))
    if run_receipt["status"] != "R1_SENSOR_PROBES_COMPLETE" or report["manifest"] != "FAS-R1-SENSOR-PROBE-FIT-v02":
        raise ValueError("sensor probe run is not the expected completed v02 run")
    if run_receipt["support_manifest_sha256"] != support_sha:
        raise ValueError("sensor probe run has a different support manifest")
    model_path = report_dir / "identity.pt"
    return {"support": support, "support_sha256": support_sha,
            "adapter_manifest": adapter_manifest,
            "adapter_manifest_sha256": EXPECTED_ADAPTER_MANIFEST_SHA256,
            "extraction_receipt": extraction_receipt, "label_summary": summary,
            "sensor_run_receipt": run_receipt, "sensor_report": report,
            "identity_model_path": model_path, "identity_model_sha256": sha256(model_path)}


def satisfied(kind: str, entities: list[int], roles: list[int], assignment: list[int]) -> float:
    if kind in ("same", "different"):
        if len(entities) != 2:
            return 0.0
        equal = assignment[entities[0]] == assignment[entities[1]]
        return float(equal if kind == "same" else not equal)
    if kind in ("fixed_role", "forbidden_role"):
        if len(entities) != 1 or len(roles) != 1:
            return 0.0
        equal = assignment[entities[0]] == roles[0]
        return float(equal if kind == "fixed_role" else not equal)
    if kind == "exactly_one_role":
        if not entities or len(roles) != 1:
            return 0.0
        count = sum(assignment[entity] == roles[0] for entity in entities)
        return float(count == 1)
    if kind == "implies_not_role":
        if len(entities) != 2 or len(roles) != 2:
            return 0.0
        # Public incidence preserves the mentioned sets but not the two argument pairings.
        pairings = (((entities[0], roles[0]), (entities[1], roles[1])),
                    ((entities[0], roles[1]), (entities[1], roles[0])))
        values = []
        for (if_entity, if_role), (then_entity, then_role) in pairings:
            values.append(float(assignment[if_entity] != if_role or assignment[then_entity] != then_role))
        return sum(values) / len(values)
    raise ValueError(f"unknown clause kind {kind}")


def sign_class(value: float) -> int:
    return 1 if value > 1.0e-9 else (-1 if value < -1.0e-9 else 0)


def report_metrics(target: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    confusion = np.zeros((3, 3), dtype=np.int64)
    order = [-1, 0, 1]
    for truth, pred in zip(target, prediction):
        confusion[order.index(int(truth)), order.index(int(pred))] += 1
    f1s = {}
    for i, cls in enumerate(order):
        tp = int(confusion[i, i])
        fp = int(confusion[:, i].sum() - tp)
        fn = int(confusion[i, :].sum() - tp)
        den = 2 * tp + fp + fn
        f1s[str(cls)] = 2 * tp / den if den else 0.0
    return {"macro_f1": float(np.mean(list(f1s.values()))), "per_class_f1": f1s,
            "accuracy": float(np.mean(target == prediction)), "confusion_rows_truth_cols_pred": confusion.tolist()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-manifest", required=True)
    parser.add_argument("--support-manifest", required=True)
    parser.add_argument("--extraction", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--public-tasks", required=True)
    parser.add_argument("--sensor-probe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    verified = validate_inputs(args)
    h = np.load(Path(args.extraction) / "constraint_H.float32.npy", mmap_mode="r")
    tasks = read_jsonl(Path(args.public_tasks))
    rows = read_jsonl(Path(args.extraction) / "rows.jsonl")
    clauses = read_jsonl(Path(args.labels) / "private-clause-labels.jsonl")
    actions = read_jsonl(Path(args.labels) / "private-action-labels.jsonl")
    mapping = {(int(row["task_index"]), int(row["clause_index"])): row for row in clauses}
    device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    device = torch.device("cpu" if device_name == "auto" else device_name)
    model_blob = torch.load(verified["identity_model_path"], map_location="cpu", weights_only=False)
    model = nn.Linear(h.shape[1], len(KINDS)).to(device)
    model.load_state_dict(model_blob["state_dict"])
    mean = np.asarray(model_blob["mean"], dtype=np.float32)
    std = np.asarray(model_blob["std"], dtype=np.float32)
    all_h = np.asarray(h, dtype=np.float32)
    probs = np.zeros((len(clauses), len(KINDS)), dtype=np.float32)
    clause_feature_rows = np.asarray([int(row["constraint_row"]) for row in clauses], dtype=np.int64)
    if not np.array_equal(clause_feature_rows, np.arange(len(clauses), dtype=np.int64)):
        raise ValueError("private clause labels are not in extraction row order")
    model.eval()
    with torch.no_grad():
        chunk_size = 512
        for start_i in range(0, len(clauses), chunk_size):
            row_ids = clause_feature_rows[start_i : start_i + chunk_size]
            batch = np.asarray(all_h[row_ids], dtype=np.float32)
            batch = (batch - mean) / std
            logits = model(torch.as_tensor(batch, device=device))
            probs[start_i : start_i + len(batch)] = torch.softmax(logits, dim=1).cpu().numpy()
    probs_by_key = {(int(row["task_index"]), int(row["clause_index"])): probs[i] for i, row in enumerate(clauses)}
    true_kind_by_key = {(int(row["task_index"]), int(row["clause_index"])): row["clause_kind"] for row in clauses}
    features_pred: list[float] = []
    features_oracle: list[float] = []
    targets = np.empty(len(actions), dtype=np.int8)
    splits = np.empty(len(actions), dtype="U16")
    implication_affected = np.zeros(len(actions), dtype=np.int8)
    for i, action in enumerate(actions):
        ti = int(action["task_index"])
        task = tasks[ti]
        before = [int(role) for role in action["assignment"]]
        edit = action["edit"]
        entity, new_role = int(edit["entity"]), int(edit["to_role"])
        if before[entity] != int(edit["from_role"]):
            raise ValueError(f"action {i} from_role disagrees with parent assignment")
        after = before.copy()
        after[entity] = new_role
        score_pred = 0.0
        score_oracle = 0.0
        for clause_index, mentioned_entities in enumerate(task["entity_mentions"]):
            if entity not in mentioned_entities:
                continue
            key = (ti, clause_index)
            mentioned_roles = [int(r) for r in task["role_mentions"][clause_index]]
            distribution = probs_by_key[key]
            for kind_index, kind in enumerate(KINDS):
                delta = (satisfied(kind, mentioned_entities, mentioned_roles, after)
                         - satisfied(kind, mentioned_entities, mentioned_roles, before))
                score_pred += float(distribution[kind_index]) * delta
            true_kind = true_kind_by_key[key]
            score_oracle += (satisfied(true_kind, mentioned_entities, mentioned_roles, after)
                             - satisfied(true_kind, mentioned_entities, mentioned_roles, before))
            if true_kind == "implies_not_role":
                implication_affected[i] = 1
        features_pred.append(score_pred)
        features_oracle.append(score_oracle)
        targets[i] = int(action["sign_delta"])
        splits[i] = action["split"]
    pred_score = np.asarray(features_pred, dtype=np.float64)
    oracle_score = np.asarray(features_oracle, dtype=np.float64)
    pred = np.asarray([sign_class(value) for value in pred_score], dtype=np.int8)
    oracle = np.asarray([sign_class(value) for value in oracle_score], dtype=np.int8)
    metrics: dict[str, Any] = {}
    for split in ("train", "validation", "qualification"):
        mask = splits == split
        metrics[split] = {
            "identity_probabilities_plus_public_incidence": report_metrics(targets[mask], pred[mask]),
            "private_kind_oracle_plus_public_incidence": report_metrics(targets[mask], oracle[mask]),
            "examples": int(mask.sum()),
        }
    report = {
        "adapter": "R1-SEMANTIC-ACTION-ADAPTER-v01",
        "status": "COMPLETED_ENGINEERING_DIAGNOSTIC",
        "prediction": "sum per-affected-clause expected satisfaction delta under identity-head class probabilities; sign selects action class",
        "runtime_inputs": ["frozen clause H_j", "public per-clause entity and role incidence", "complete assignment", "candidate edit"],
        "offline_only": ["private clause kinds are used only for the labeled oracle diagnostic", "private action delta labels are used only for scoring"],
        "implication_handling": "public incidence omits argument pairing; evaluate both entity-role pairings and average, which is used in both predicted and private-kind oracle paths",
        "metrics": metrics,
        "implication_affected_actions": int(implication_affected.sum()),
        "qualification_interpretation": "adaptive engineering retest after prior qualification exposure; not independent confirmation",
        "elapsed_seconds": time.monotonic() - start,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "status": "R1_ACTION_ADAPTER_COMPLETE",
        "adapter_source_sha256": sha256(Path(__file__)),
        "adapter_manifest_sha256": verified["adapter_manifest_sha256"],
        "support_manifest_sha256": verified["support_sha256"],
        "extraction_receipt_sha256": sha256(Path(args.extraction) / "receipt.json"),
        "identity_probe_receipt_sha256": sha256(Path(args.sensor_probe) / "run-receipt.json"),
        "identity_probe_model_sha256": verified["identity_model_sha256"],
        "clause_labels_sha256": verified["label_summary"]["clause_labels_sha256"],
        "action_labels_sha256": verified["label_summary"]["action_labels_sha256"],
        "report_sha256": sha256(output / "report.json"),
        "device": str(device),
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output_arg = None
        for index, arg in enumerate(sys.argv[:-1]):
            if arg == "--output":
                output_arg = sys.argv[index + 1]
                break
        if output_arg is not None and Path(output_arg).exists():
            failure = {"status": "R1_ACTION_ADAPTER_FAILED", "error_type": type(error).__name__,
                       "error": str(error), "adapter_source_sha256": sha256(Path(__file__))}
            (Path(output_arg) / "failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        raise
