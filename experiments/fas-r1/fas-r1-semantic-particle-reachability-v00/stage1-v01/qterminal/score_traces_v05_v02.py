#!/usr/bin/env python3
"""Score closed Stage1 traces with the frozen V05 V02 selector, label-free."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from model_clausewise_v02 import ClausewiseQTerminal


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, record: dict[str, Any], name: str) -> None:
    if not path.is_file() or path.stat().st_size != int(record.get("bytes", -1)):
        raise ValueError(f"missing or wrong-sized {name}: {path}")
    if sha256_file(path) != str(record.get("sha256", "")).lower():
        raise ValueError(f"{name} hash differs from receipt")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"expected JSON object at {path}:{index}")
                rows.append(row)
    return rows


def assignment_key(value: Any, task_id: str) -> bytes:
    if not isinstance(value, list) or len(value) != 20 or any(type(role) is not int or not 0 <= role < 3 for role in value):
        raise ValueError(f"trace assignment is malformed for {task_id}")
    return bytes(value)


def probability(logit: float, temperature: float) -> float:
    z = max(-80.0, min(80.0, logit / temperature))
    return 1.0 / (1.0 + math.exp(-z))


def sidecar_filename(index: int, trace_id: str) -> str:
    """Return a short, deterministic name safe under Windows path limits."""
    if index < 0:
        raise ValueError("sidecar index must be nonnegative")
    trace_digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:12]
    return f"s{index:04d}-{trace_digest}.selector.json"


def load_inputs(args):
    fit_receipt = read_json(args.fit_receipt)
    if fit_receipt.get("schema") != "R1_QTERMINAL_V05_FIT_RECEIPT_V02" or fit_receipt.get("status") != "QTERMINAL_V05_FITTED_VALIDATION_FROZEN":
        raise ValueError("V256 fit receipt is not a frozen V02 selector")
    if fit_receipt.get("test_labels_read") is not False or fit_receipt.get("qualification_labels_read") is not False:
        raise ValueError("V256 fit receipt violates the train/validation-only boundary")
    checkpoint_path = args.checkpoint
    verify_file(checkpoint_path, fit_receipt["checkpoint"], "V256 selector checkpoint")
    source_pins = fit_receipt.get("source_pins", {})
    if source_pins.get("trainer_source_sha256") != sha256_file(Path(__file__).with_name("train_qterminal_v05_v02.py")):
        raise ValueError("V02 trainer source differs from the frozen fit receipt")
    if source_pins.get("model_source_sha256") != sha256_file(Path(__file__).with_name("model_clausewise_v02.py")):
        raise ValueError("V02 model source differs from the frozen fit receipt")

    view = read_json(args.view_receipt)
    features = read_json(args.features_receipt)
    extraction = read_json(args.extraction / "receipt.json")
    if features.get("schema") != "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01" or features.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE":
        raise ValueError("V246 feature receipt is not complete")
    if extraction.get("schema") != "R1_STAGE1_SENSOR_EXTRACTION_V01" or extraction.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE":
        raise ValueError("V228 extraction receipt is not complete")
    if features.get("model_revision") != extraction.get("model", {}).get("revision"):
        raise ValueError("V228 and V246 frozen LFM revisions differ")
    if fit_receipt.get("source_pins", {}).get("v246_features_receipt_sha256") != sha256_file(args.features_receipt):
        raise ValueError("V256 fit is not bound to the supplied V246 receipt")

    public_path = args.public_tasks
    support_path = args.support_manifest
    if sha256_file(public_path) != extraction.get("input", {}).get("sha256"):
        raise ValueError("V228 extraction public-task input hash mismatch")
    if str(support_path) != str(extraction.get("input", {}).get("support_manifest", {}).get("path")):
        raise ValueError("support manifest path differs from V228 extraction receipt")
    support = read_json(support_path)
    if sha256_file(support_path) != extraction["input"]["support_manifest"]["sha256"]:
        raise ValueError("V228 support-manifest hash mismatch")
    split_by_id = {str(row["task_id"]): str(row["split"]) for row in support.get("family_roster", [])}
    if len(split_by_id) != 96:
        raise ValueError("V227 support manifest does not provide the frozen 96-task roster")
    tasks = read_jsonl(public_path)
    task_by_id = {str(row["id"]): row for row in tasks}
    if len(task_by_id) != 96:
        raise ValueError("V227 public task file does not contain 96 unique tasks")

    extraction_files = extraction.get("output_files")
    if not isinstance(extraction_files, list):
        raise ValueError("V228 receipt omits its output file pins")
    extraction_pins = {Path(str(row.get("path", ""))).name: row for row in extraction_files}
    for name in ("constraint_H.float32.npy", "global_h.float32.npy", "rows.jsonl"):
        if name not in extraction_pins:
            raise ValueError(f"V228 receipt omits {name}")
        verify_file(args.extraction / name, extraction_pins[name], f"V228 {name}")
    for name in ("constraint_H_trainval.float32.npy", "global_h_trainval.float32.npy", "rows_trainval.jsonl"):
        verify_file(args.trainval_features / name, features["outputs"][name], f"V246 {name}")
    if features.get("view_receipt_sha256") != sha256_file(args.view_receipt):
        raise ValueError("V246 features are not bound to the supplied V241 receipt")
    if view.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE":
        raise ValueError("V241 train/validation view is not complete")

    return fit_receipt, extraction, features, task_by_id, split_by_id


def load_semantic_features(args, task_by_id, split_by_id):
    public_h = np.load(args.extraction / "constraint_H.float32.npy", mmap_mode="r", allow_pickle=False)
    public_global = np.load(args.extraction / "global_h.float32.npy", mmap_mode="r", allow_pickle=False)
    public_rows = read_jsonl(args.extraction / "rows.jsonl")
    train_h = np.load(args.trainval_features / "constraint_H_trainval.float32.npy", mmap_mode="r", allow_pickle=False)
    train_global = np.load(args.trainval_features / "global_h_trainval.float32.npy", mmap_mode="r", allow_pickle=False)
    train_rows = read_jsonl(args.trainval_features / "rows_trainval.jsonl")
    public_index: dict[str, dict[str, Any]] = {}
    for row in public_rows:
        task_id = str(row["task_id"])
        entry = public_index.setdefault(task_id, {"constraints": {}, "global": None})
        if row["kind"] == "global":
            if entry["global"] is not None:
                raise ValueError(f"duplicate V228 global row for {task_id}")
            entry["global"] = int(row["row"])
        elif row["kind"] == "constraint":
            clause_index = int(row["clause_index"])
            if clause_index in entry["constraints"]:
                raise ValueError(f"duplicate V228 constraint row for {task_id}")
            entry["constraints"][clause_index] = int(row["row"])
        else:
            raise ValueError("unknown V228 feature row kind")
    train_index: dict[tuple[str, str, int | None], str] = {}
    for row in train_rows:
        key = (str(row["task_id"]), str(row["kind"]), int(row["clause_index"]) if row["kind"] == "constraint" else None)
        train_index[key] = str(row["output_float32_sha256"])
    public_hashes = {(str(row["task_id"]), str(row["kind"]), int(row["clause_index"]) if row["kind"] == "constraint" else None): str(row["output_float32_sha256"]) for row in public_rows}
    for key, expected_hash in train_index.items():
        if public_hashes.get(key) != expected_hash:
            raise ValueError(f"V228 frozen feature differs from the V246 train/validation copy: {key}")

    result = {}
    for task_id, task in task_by_id.items():
        if task_id not in public_index:
            raise ValueError(f"V228 is missing task {task_id}")
        mapped = public_index[task_id]
        clauses = task["clauses"]
        if mapped["global"] is None or set(mapped["constraints"]) != set(range(len(clauses))):
            raise ValueError(f"V228 rows do not cover public task {task_id}")
        n, k = int(task["n"]), int(task["k"])
        entity = np.zeros((len(clauses), 20), dtype=np.bool_)
        role = np.zeros((len(clauses), 6), dtype=np.bool_)
        for index, mentions in enumerate(task["entity_mentions"]):
            entity[index, np.asarray(mentions, dtype=np.int64)] = True
        for index, mentions in enumerate(task["role_mentions"]):
            if mentions:
                role[index, np.asarray(mentions, dtype=np.int64)] = True
        result[task_id] = {
            "H": np.asarray(public_h[[mapped["constraints"][i] for i in range(len(clauses))]], dtype=np.float32),
            "h_global": np.asarray(public_global[mapped["global"]], dtype=np.float32),
            "constraint_mask": np.ones(len(clauses), dtype=np.bool_),
            "entity_incidence": entity,
            "role_incidence": role,
            "entity_mask": np.arange(20) < n,
            "role_mask": np.arange(6) < k,
            "n": n,
            "k": k,
            "split": split_by_id.get(task_id, "missing"),
        }
    return result


def collect_traces(trace_dirs: list[Path], task_by_id, split_by_id):
    records = []
    unique: dict[str, set[bytes]] = {}
    trace_ids: set[str] = set()
    for directory in trace_dirs:
        paths = sorted(directory.glob("*.trace.jsonl"))
        if not paths:
            raise ValueError(f"no trace files in {directory}")
        for path in paths:
            header = None
            footer = None
            events = []
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    payload = row.get("payload")
                    if row.get("record") == "header":
                        if header is not None:
                            raise ValueError(f"duplicate header in {path}")
                        header = payload
                    elif row.get("record") == "event":
                        if int(payload.get("event_index", -1)) != len(events):
                            raise ValueError(f"noncontiguous event index in {path}:{line_number}")
                        events.append(payload)
                    elif row.get("record") == "footer":
                        if footer is not None:
                            raise ValueError(f"duplicate footer in {path}")
                        footer = payload
                    else:
                        raise ValueError(f"unknown trace record in {path}:{line_number}")
            if header is None or footer is None or int(footer["ledger"]["expansions"]) != len(events):
                raise ValueError(f"trace is incomplete: {path}")
            task_id = str(header["task_id"])
            if task_id not in task_by_id or split_by_id.get(task_id) != "qualification":
                raise ValueError(f"trace task {task_id} is not in the public qualification roster")
            trace_id = str(header["trace_id"])
            if trace_id in trace_ids:
                raise ValueError(f"duplicate trace id {trace_id}")
            trace_ids.add(trace_id)
            initial_keys = [assignment_key(row["assignment"], task_id) for row in header["initial_particles"]]
            event_keys = [assignment_key(row["assignment_after"], task_id) for row in events]
            unique.setdefault(task_id, set()).update(initial_keys)
            unique[task_id].update(event_keys)
            records.append({"path": path, "run_tag": directory.name, "task_id": task_id, "trace_id": trace_id, "initial_keys": initial_keys, "event_keys": event_keys, "event_count": len(events)})
    return records, unique


def score_unique_assignments(model, features, assignments_by_task, temperature, device, batch_size):
    scores: dict[str, dict[bytes, tuple[float, float]]] = {}
    total_gpu_ns = 0
    total_wall_ns = 0
    total_batches = 0
    torch.cuda.reset_peak_memory_stats(device) if device.type == "cuda" else None
    for task_id in sorted(assignments_by_task):
        feature = features[task_id]
        keys = sorted(assignments_by_task[task_id])
        H_base = {
            "constraint_embeddings": torch.as_tensor(feature["H"], device=device).unsqueeze(0),
            "constraint_mask": torch.as_tensor(feature["constraint_mask"], device=device).unsqueeze(0),
            "entity_incidence": torch.as_tensor(feature["entity_incidence"], device=device).unsqueeze(0),
            "role_incidence": torch.as_tensor(feature["role_incidence"], device=device).unsqueeze(0),
            "entity_mask": torch.as_tensor(feature["entity_mask"], device=device).unsqueeze(0),
            "role_mask": torch.as_tensor(feature["role_mask"], device=device).unsqueeze(0),
        }
        global_base = torch.as_tensor(feature["h_global"].copy(), device=device).unsqueeze(0)
        task_scores = {}
        for start in range(0, len(keys), batch_size):
            batch_keys = keys[start : start + batch_size]
            raw = np.zeros((len(batch_keys), 20), dtype=np.uint8)
            for index, key in enumerate(batch_keys):
                raw[index] = np.frombuffer(key, dtype=np.uint8)
            one_hot = np.zeros((len(batch_keys), 20, 6), dtype=np.float32)
            one_hot[np.arange(len(batch_keys))[:, None], np.arange(20)[None, :], raw] = 1.0
            a = torch.as_tensor(one_hot, device=device)
            H = {name: tensor.expand(len(batch_keys), *tensor.shape[1:]) for name, tensor in H_base.items()}
            h_global = global_base.expand(len(batch_keys), -1)
            if device.type == "cuda":
                torch.cuda.synchronize(device)
                gpu_start = torch.cuda.Event(enable_timing=True)
                gpu_end = torch.cuda.Event(enable_timing=True)
                gpu_start.record()
            wall_start = time.perf_counter_ns()
            with torch.inference_mode():
                logits = model(H, h_global, a).float()
            if device.type == "cuda":
                gpu_end.record()
                torch.cuda.synchronize(device)
                total_gpu_ns += int(gpu_start.elapsed_time(gpu_end) * 1_000_000)
            total_wall_ns += time.perf_counter_ns() - wall_start
            values = logits.detach().cpu().numpy().astype(np.float64)
            for key, logit in zip(batch_keys, values, strict=True):
                task_scores[key] = (float(logit), probability(float(logit), temperature))
            total_batches += 1
        scores[task_id] = task_scores
    peak_memory = torch.cuda.max_memory_allocated(device) if device.type == "cuda" else None
    return scores, {"gpu_active_ns": total_gpu_ns, "wall_active_ns": total_wall_ns, "forward_batches": total_batches, "unique_assignments": sum(map(len, assignments_by_task.values())), "peak_gpu_memory_bytes": peak_memory}


def write_sidecars(args, fit_receipt, extraction, features_receipt, records, scores, score_stats):
    args.output.mkdir(parents=True)
    sidecars = []
    for index, record in enumerate(records):
        task_scores = scores[record["task_id"]]
        initial = [task_scores[key] for key in record["initial_keys"]]
        events = [task_scores[key] for key in record["event_keys"]]
        sidecar = {
            "schema": "R1_QTERMINAL_V05_V02_TRACE_SCORES_V01",
            "trace_id": record["trace_id"],
            "task_id": record["task_id"],
            "scoring_semantics": "raw clausewise-conjunction log-odds rank assignments; calibrated probability uses V256 validation temperature",
            "ranking_scores_initial": [value[0] for value in initial],
            "probabilities_initial": [value[1] for value in initial],
            "ranking_scores_events": [value[0] for value in events],
            "probabilities_events": [value[1] for value in events],
        }
        trace_hash = sha256_file(record["path"])
        filename = sidecar_filename(index, record["trace_id"])
        target = args.output / filename
        temp = target.with_suffix(target.suffix + ".tmp")
        encoded = json.dumps(sidecar, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        with temp.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            import os

            os.fsync(stream.fileno())
        temp.replace(target)
        sidecars.append({
            "trace_file": str(record["path"]),
            "trace_sha256": trace_hash,
            "selector_file": filename,
            "selector_sha256": hashlib.sha256(encoded).hexdigest(),
            "trace_id": record["trace_id"],
            "task_id": record["task_id"],
            "event_count": record["event_count"],
            "assignment_scores": len(record["initial_keys"]) + len(record["event_keys"]),
        })
    manifest = {
        "schema": "R1_QTERMINAL_V05_V02_TRACE_SCORING_RECEIPT_V01",
        "status": "TRACE_SELECTOR_SCORES_COMPLETE",
        "selector_id": "qterminal-v05-v02-clausewise",
        "selector_fit_receipt_sha256": sha256_file(args.fit_receipt),
        "selector_checkpoint_sha256": fit_receipt["checkpoint"]["sha256"],
        "scorer_source_path": str(Path(__file__).resolve()),
        "scorer_source_sha256": sha256_file(Path(__file__)),
        "v228_extraction_receipt_sha256": sha256_file(args.extraction / "receipt.json"),
        "v246_feature_receipt_sha256": sha256_file(args.features_receipt),
        "v227_public_task_sha256": sha256_file(args.public_tasks),
        "v227_support_manifest_sha256": sha256_file(args.support_manifest),
        "model_revision": extraction["model"]["revision"],
        "trace_count": len(records),
        "unique_assignments_scored": score_stats["unique_assignments"],
        "scoring_forward_batches": score_stats["forward_batches"],
        "scoring_gpu_active_ns": score_stats["gpu_active_ns"],
        "scoring_wall_active_ns": score_stats["wall_active_ns"],
        "peak_gpu_memory_bytes": score_stats["peak_gpu_memory_bytes"],
        "inference_reads_private_tasks": False,
        "inference_reads_validator_labels": False,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "sidecars": sidecars,
    }
    path = args.output / "trace-scoring-receipt-v05-v02.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--view-receipt", type=Path, required=True)
    parser.add_argument("--features-receipt", type=Path, required=True)
    parser.add_argument("--trainval-features", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--public-tasks", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
    parser.add_argument("--trace-dirs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    if args.batch_size < 1 or args.output.exists():
        raise SystemExit("batch size must be positive and output directory must be new")
    fit_receipt, extraction, features_receipt, task_by_id, split_by_id = load_inputs(args)
    semantic_features = load_semantic_features(args, task_by_id, split_by_id)
    records, assignments = collect_traces(args.trace_dirs, task_by_id, split_by_id)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if checkpoint.get("schema") != "R1_QTERMINAL_CHECKPOINT_V05_V02":
        raise ValueError("selector checkpoint schema mismatch")
    config = checkpoint["model_config"]
    model = ClausewiseQTerminal(hidden_dim=int(config["hidden_dim"]), hidden_size=int(config["hidden_size"]), max_roles=int(config["max_roles"]))
    model.load_state_dict(checkpoint["state_dict"])
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else "cpu" if args.device == "auto" else args.device)
    model.to(device).eval()
    scores, score_stats = score_unique_assignments(model, semantic_features, assignments, float(checkpoint["temperature"]), device, args.batch_size)
    manifest = write_sidecars(args, fit_receipt, extraction, features_receipt, records, scores, score_stats)
    print(f"{manifest['status']}: traces={manifest['trace_count']} unique_assignments={manifest['unique_assignments_scored']} wall_ms={manifest['scoring_wall_active_ns']/1e6:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
