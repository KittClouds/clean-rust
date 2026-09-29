"""Score sealed BANK-v1 predictions after every representation arm is fixed."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from common import (ALL_HEADS, CATEGORICAL_HEADS, INPUT_SPECS,
                    MULTILABEL_HEADS, encode_targets, input_paths, read_jsonl,
                    sha256, write_json)

def verify_prediction_seal(output: Path):
    seal_path = output / "all-surfaces-prediction-seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("truth_join_performed") is not False:
        raise RuntimeError("predictions were not sealed before truth join")
    if set(seal["surface_order"]) != set(x["surface"] for x in seal["arms"]):
        raise RuntimeError("incomplete surface roster")
    predictions = {}
    receipts = {}
    for arm in seal["arms"]:
        surface = arm["surface"]
        sp = output / "predictions" / f"{surface}-seal.json"
        receipt = json.loads(sp.read_text(encoding="utf-8"))
        pred_path = output / "predictions" / f"{surface}.jsonl"
        if sha256(pred_path) != receipt["sha256"] or receipt["truth_join_performed"] is not False:
            raise RuntimeError(f"prediction seal mismatch: {surface}")
        if sha256(sp) != arm["prediction_seal_sha256"]:
            raise RuntimeError(f"prediction receipt mismatch: {surface}")
        if arm.get("prediction_sha256") != receipt["sha256"]:
            raise RuntimeError(f"aggregate prediction hash mismatch: {surface}")
        rows = list(read_jsonl(pred_path))
        if len(rows) != receipt["rows"]:
            raise RuntimeError(f"prediction count mismatch: {surface}")
        ids = [r["row_id"] for r in rows]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"duplicate prediction identities: {surface}")
        predictions[surface] = {r["row_id"]: r for r in rows}
        receipts[surface] = receipt
    return seal, predictions, receipts

def categorical_metrics(rows, targets, task: str):
    classes = CATEGORICAL_HEADS[task]
    truth, pred = [], []
    for row, target in zip(rows, targets):
        if task not in target:
            continue
        truth.append(int(target[task]))
        pred.append(classes.index(row[task]))
    if not truth:
        return {"rows": 0, "accuracy": None, "class_support": [0] * len(classes),
                "class_recall": [None] * len(classes), "macro_f1": None}
    y = np.asarray(truth, dtype=np.int64)
    p = np.asarray(pred, dtype=np.int64)
    cm = np.zeros((len(classes), len(classes)), dtype=np.int64)
    np.add.at(cm, (y, p), 1)
    support = cm.sum(axis=1)
    tp = np.diag(cm)
    precision = tp / np.maximum(cm.sum(axis=0), 1)
    recall = tp / np.maximum(support, 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    present = support > 0
    return {
        "rows": len(y), "accuracy": float(np.mean(y == p)),
        "balanced_accuracy_present_classes": float(np.mean(recall[present])),
        "macro_f1_present_classes": float(np.mean(f1[present])),
        "class_names": list(classes), "class_support": support.tolist(),
        "class_correct": tp.tolist(), "class_recall": [float(x) if s else None
                                                         for x, s in zip(recall, support)],
        "confusion_matrix_rows_true_cols_pred": cm.tolist(),
    }

def multilabel_metrics(rows, targets, task: str):
    classes = MULTILABEL_HEADS[task]
    truth_sets, pred_sets = [], []
    for row, target in zip(rows, targets):
        if task not in target:
            continue
        truth_sets.append(set(classes[i] for i in target[task]))
        pred_sets.append(set(row[task]))
    if not truth_sets:
        return {"rows": 0, "micro_f1": None, "macro_f1_present_classes": None,
                "exact_set_match": None, "class_names": list(classes), "class_support": [0] * len(classes)}
    tp = np.zeros(len(classes), dtype=np.int64)
    fp = np.zeros(len(classes), dtype=np.int64)
    fn = np.zeros(len(classes), dtype=np.int64)
    for actual, guess in zip(truth_sets, pred_sets):
        for i, cls in enumerate(classes):
            if cls in actual and cls in guess: tp[i] += 1
            elif cls not in actual and cls in guess: fp[i] += 1
            elif cls in actual and cls not in guess: fn[i] += 1
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / np.maximum(tp + fn, 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    present = (tp + fn) > 0
    micro_f1 = 2 * int(tp.sum()) / max(2 * int(tp.sum()) + int(fp.sum()) + int(fn.sum()), 1)
    return {
        "rows": len(truth_sets), "micro_f1": float(micro_f1),
        "macro_f1_present_classes": float(np.mean(f1[present])),
        "exact_set_match": float(np.mean([a == b for a, b in zip(truth_sets, pred_sets)])),
        "class_names": list(classes), "class_support": (tp + fn).tolist(),
        "class_tp": tp.tolist(), "class_fp": fp.tolist(), "class_fn": fn.tolist(),
        "class_precision": [float(x) if (a + b) else None
                            for x, a, b in zip(precision, tp, fp)],
        "class_recall": [float(x) if s else None for x, s in zip(recall, tp + fn)],
    }

def target_bundle_metrics(rows, targets):
    route_total = route_ok = full_total = full_ok = 0
    for row, target in zip(rows, targets):
        if "decision" in target:
            route_total += 1
            expected_decision = CATEGORICAL_HEADS["decision"][int(target["decision"])]
            ok = row["decision"] == expected_decision
            if expected_decision == "ABSTAIN" and "abstain_reason" in target:
                reason = CATEGORICAL_HEADS["abstain_reason"][int(target["abstain_reason"])]
                ok = ok and row["abstain_reason"] == reason
            if expected_decision in ("ACT", "ASK") and "action_type" in target:
                action = CATEGORICAL_HEADS["action_type"][int(target["action_type"])]
                ok = ok and row["action_type"] == action
            route_ok += int(ok)

        available = [h for h in ALL_HEADS if h in target]
        if available:
            full_total += 1
            exact = True
            for name in available:
                if name in CATEGORICAL_HEADS:
                    exact &= row[name] == CATEGORICAL_HEADS[name][int(target[name])]
                else:
                    expected = {MULTILABEL_HEADS[name][i] for i in target[name]}
                    exact &= set(row[name]) == expected
            full_ok += int(exact)
    return {
        "decision_route_exact": {"rows": route_total, "accuracy": route_ok / route_total if route_total else None},
        "all_available_BANK_heads_exact": {"rows": full_total, "accuracy": full_ok / full_total if full_total else None},
    }

def metric_pack(rows, targets):
    out = {"heads": {}, "bundles": target_bundle_metrics(rows, targets)}
    for task in ALL_HEADS:
        out["heads"][task] = (categorical_metrics(rows, targets, task)
                              if task in CATEGORICAL_HEADS
                              else multilabel_metrics(rows, targets, task))
    return out

def load_partition_rows(bank_root: Path, split: str, protected: bool):
    if split == "DEV":
        path = bank_root / "inputs" / "DEV.jsonl"
        return list(read_jsonl(path)), sha256(path)
    input_path = bank_root / "public" / "test-inputs" / f"{split}.jsonl"
    truth_path = bank_root / "protected" / "test-truth" / f"{split}.jsonl"
    inputs = list(read_jsonl(input_path))
    truth = list(read_jsonl(truth_path))
    if len(inputs) != len(truth):
        raise RuntimeError(f"{split} input/truth row counts differ")
    joined = []
    for i, (inp, label) in enumerate(zip(inputs, truth)):
        if inp["world_id"] != label["world_id"] or inp["world_hash"] != label["world_hash"]:
            raise RuntimeError(f"{split} label identity mismatch at row {i}")
        joined.append({**inp, "labels": label.get("labels") or {}})
    return joined, sha256(truth_path)

def read_rowmap(path: Path):
    return list(read_jsonl(path))

def bank_metamorphic_receipt(bank_root: Path):
    gate_path = bank_root / "manifests" / "seal-gates.json"
    if not gate_path.is_file():
        return {"available": False}
    data = json.loads(gate_path.read_text(encoding="utf-8"))
    return {"available": True, "path": str(gate_path.resolve()), "sha256": sha256(gate_path),
            "receipt": data}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    bank_root, output = args.bank_root, args.output
    seal, predictions, pred_receipts = verify_prediction_seal(output)
    source_lock = json.loads((output / "source-lock.json").read_text(encoding="utf-8"))
    if source_lock["release"] != "BANK-v1":
        raise RuntimeError("scoring non-BANK-v1 data")
    rowmap = read_rowmap(output / "rowmap.jsonl")
    if len(rowmap) != source_lock["row_count"]:
        raise RuntimeError("rowmap length mismatch")
    by_id = {r["row_id"]: r for r in rowmap}
    for surface, pred_map in predictions.items():
        expected = {r["row_id"] for r in rowmap if r["split"] in ("DEV",) or r["split"].startswith("TEST-")}
        if set(pred_map) != expected:
            raise RuntimeError(f"{surface} prediction population mismatch")

    # Prediction seals are verified above before any protected TEST truth is opened.
    partition_data = {}
    truth_hashes = {}
    for split in ("DEV", "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE",
                  "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT"):
        rows, label_hash = load_partition_rows(bank_root, split, protected=split.startswith("TEST-"))
        truth_hashes[split] = label_hash
        row_targets = [encode_targets(row) for row in rows]
        if any(row["world_id"] not in by_id or by_id[row["world_id"]]["split"] != split for row in rows):
            raise RuntimeError(f"{split} scoring rows do not match sealed rowmap")
        partition_data[split] = (rows, row_targets)

    arms = {}
    row_index = {surface: {r["row_id"]: r for r in pred.values()} for surface, pred in predictions.items()}
    for surface in seal["surface_order"]:
        per_split = {}
        for split, (truth_rows, targets) in partition_data.items():
            scored = [row_index[surface][row["world_id"]] for row in truth_rows]
            per_split[split] = {
                "all_labeled_input_rows": metric_pack(scored, targets),
                "primary_world_rows": metric_pack(
                    [p for p, row in zip(scored, truth_rows) if not row.get("paired_world")],
                    [t for t, row in zip(targets, truth_rows) if not row.get("paired_world")]),
            }
        all_test = []
        all_test_targets = []
        all_test_truth_rows = []
        for split in INPUT_SPECS_TEST:
            truth_rows, targets = partition_data[split]
            for row, target in zip(truth_rows, targets):
                if not row.get("paired_world"):
                    all_test.append(row_index[surface][row["world_id"]])
                    all_test_targets.append(target)
                    all_test_truth_rows.append(row)
        heldout = {}
        for family in ("S7", "S8", "S9"):
            selected = [(p, t) for p, t, row in zip(all_test, all_test_targets, all_test_truth_rows)
                        if row.get("surface_family") == family]
            heldout[family] = metric_pack([p for p, _ in selected], [t for _, t in selected])
        heldout["S7_S8_S9_pooled"] = metric_pack(
            [p for p, t, row in zip(all_test, all_test_targets, all_test_truth_rows)
             if row.get("surface_family") in ("S7", "S8", "S9")],
            [t for p, t, row in zip(all_test, all_test_targets, all_test_truth_rows)
             if row.get("surface_family") in ("S7", "S8", "S9")])
        arms[surface] = {"per_split": per_split, "heldout_renderer_surfaces": heldout,
                         "test_canonical_worlds": metric_pack(all_test, all_test_targets)}

        # Model-facing truth-preserving rendered-pair checks on test worlds.
        pair_rows = []
        lookup = row_index[surface]
        for row in rowmap:
            if not row["split"].startswith("TEST-") or not row.get("paired_world"):
                continue
            base_id = str(row["paired_world"])
            base_pred = lookup.get(base_id)
            variant_pred = lookup.get(row["row_id"])
            if base_pred is None or variant_pred is None:
                continue
            pair_rows.append((base_pred, variant_pred))
        total_pairs = len(pair_rows)
        decision_same = sum(a["decision"] == b["decision"] for a, b in pair_rows)
        structured_same = 0
        for a, b in pair_rows:
            structured_same += int(all(a[h] == b[h] for h in ALL_HEADS))
        arms[surface]["renderer_pair_metamorphic"] = {
            "pairs": total_pairs,
            "decision_invariance": decision_same / total_pairs if total_pairs else None,
            "all_typed_heads_invariance": structured_same / total_pairs if total_pairs else None,
            "interpretation": "same latent world, alternative BANK renderer; consistency diagnostic, not correctness",
        }

    # Difficulty thresholds are derived only from TRAIN metadata, never from test labels.
    train_meta = [r for r in rowmap if r["split"] == "TRAIN" and not r.get("paired_world")]
    feature_names = sorted({k for r in train_meta for k in r["difficulty"]})
    cuts = {}
    for feature in feature_names:
        values = np.asarray([r["difficulty"].get(feature, 0) for r in train_meta], dtype=np.float64)
        cuts[feature] = [float(np.quantile(values, 1 / 3)), float(np.quantile(values, 2 / 3))]
    difficulty = {}
    for surface in seal["surface_order"]:
        pmap = row_index[surface]
        per_feature = {}
        for feature, (q1, q2) in cuts.items():
            bins = {"LOW": [], "MID": [], "HIGH": []}
            for split in INPUT_SPECS_TEST:
                for row, target in zip(*partition_data[split]):
                    if row.get("paired_world"):
                        continue
                    value = row["difficulty"].get(feature, 0)
                    group = "LOW" if value <= q1 else ("MID" if value <= q2 else "HIGH")
                    bins[group].append((pmap[row["world_id"]], target))
            per_feature[feature] = {}
            for name, pairs in bins.items():
                per_feature[feature][name] = {
                    "rows": len(pairs),
                    "decision": categorical_metrics([p for p, t in pairs], [t for p, t in pairs], "decision"),
                    "route_bundle": target_bundle_metrics([p for p, t in pairs], [t for p, t in pairs]),
                }
        difficulty[surface] = per_feature

    report = {
        "schema": "phoenix.bank-v1-230m-surface-extremes-score/v1",
        "surface_sweep": seal["surface_sweep"],
        "claim": "engineering capability allocation map for frozen 230M linear readouts on synthetic BANK-v1; not lexical-transport qualification",
        "prediction_seal_sha256": sha256(output / "all-surfaces-prediction-seal.json"),
        "truth_hashes_opened_after_prediction_seal": truth_hashes,
        "surface_order": seal["surface_order"],
        "arms": arms,
        "difficulty_tercile_cutpoints_from_train_metadata_only": cuts,
        "difficulty_metrics": difficulty,
        "bank_metamorphic_g20": bank_metamorphic_receipt(bank_root),
        "test_truth_join_performed_after_all_surface_predictions_sealed": True,
    }
    report_path = output / "surface-score.json"
    write_json(report_path, report)
    print(json.dumps({"phase": "score_complete", "surfaces": len(arms),
                      "test_splits": len(INPUT_SPECS_TEST),
                      "score_path": str(report_path.resolve()), "score_sha256": sha256(report_path)}),
          flush=True)

INPUT_SPECS_TEST = tuple(split for split, _ in INPUT_SPECS if split.startswith("TEST-"))

if __name__ == "__main__":
    main()
