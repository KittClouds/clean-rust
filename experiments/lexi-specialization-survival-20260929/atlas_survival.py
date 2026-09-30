"""Score frozen and refitted Rung-0 heads on a specialized LFM BANK cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

SURFACE_DIR = Path(__file__).resolve().parents[1] / "bank-v1-surface-extremes-20260929"
sys.path.insert(0, str(SURFACE_DIR))
import common  # noqa: E402
import fit_predict  # noqa: E402
import score as bank_score  # noqa: E402
from extract import configure_torch  # noqa: E402

SURFACES = ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean", "first_token")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def link_inputs(target: Path, feature_dir: Path, rowmap: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    (target / "features").mkdir()
    for source in feature_dir.glob("*.npy"):
        os.link(source, target / "features" / source.name)
    os.link(rowmap, target / "rowmap.jsonl")


def predict(args) -> None:
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    extraction_path = args.features / "features" / "extraction-seal.json"
    extraction = read_json(extraction_path)
    if extraction.get("truth_joined") is not False:
        raise RuntimeError("specialized feature extraction is not label-blind")
    if sha256(args.model / "model.safetensors") != extraction["model"]["weights_sha256"]:
        raise RuntimeError("feature cache does not match the supplied specialized model")
    source_lock = read_json(args.features / "source-lock.json")
    if source_lock.get("release") != "BANK-v1":
        raise RuntimeError("feature cache is not bound to BANK-v1")
    rows = int(extraction["rows"])
    hidden = int(extraction["hidden_size"])
    rowmap_path = args.features / "rowmap.jsonl"
    rowmap = list(common.read_jsonl(rowmap_path))
    if len(rowmap) != rows or any(meta["idx"] != index for index, meta in enumerate(rowmap)):
        raise RuntimeError("specialized rowmap does not match feature row count/order")
    split_counts = {split: sum(meta["split"] == split for meta in rowmap)
                    for split in {meta["split"] for meta in rowmap}}
    train_rows, dev_rows = split_counts["TRAIN"], split_counts["DEV"]
    primitives, projection = fit_predict.load_primitives(args.features / "features", rows, hidden)
    train_values, train_masks = fit_predict.load_targets(args.bank_root / "inputs" / "TRAIN.jsonl",
                                                        train_rows)
    view_paths = {}
    for lane in ("old-head", "refit-head"):
        view_paths[lane] = output / lane
        link_inputs(view_paths[lane], args.features / "features", rowmap_path)
    receipt = {"schema": "lexi-specialization-bank-predictions/v1", "truth_joined": False,
               "bank_release": "BANK-v1", "features_seal_sha256": sha256(extraction_path),
               "model_path": str(args.model.resolve()),
               "model_weights_sha256": sha256(args.model / "model.safetensors"),
               "source_lock_sha256": sha256(args.features / "source-lock.json"),
               "rows": rows, "train_rows": train_rows, "dev_rows": dev_rows,
               "surfaces": list(SURFACES), "lanes": {}}
    for surface in SURFACES:
        original = args.r0_artifacts / "models" / f"{surface}.npz"
        old_view = view_paths["old-head"]
        old_record = fit_predict.predict_surface(configure_torch(), surface, original,
            primitives, projection, hidden, rowmap, train_rows, dev_rows, old_view)
        old_record["seal_sha256"] = sha256(old_view / "predictions" / f"{surface}-seal.json")
        receipt["lanes"].setdefault("old-head", {})[surface] = {
            "model_path": str(original.resolve()), "model_sha256": sha256(original),
            "prediction": old_record}
        new_model, refit_record = fit_predict.fit_surface(configure_torch(), surface,
            primitives, projection, hidden, train_rows, train_values, train_masks,
            view_paths["refit-head"])
        new_pred = fit_predict.predict_surface(configure_torch(), surface, new_model,
            primitives, projection, hidden, rowmap, train_rows, dev_rows,
            view_paths["refit-head"])
        new_pred["seal_sha256"] = sha256(view_paths["refit-head"] / "predictions" /
                                         f"{surface}-seal.json")
        receipt["lanes"].setdefault("refit-head", {})[surface] = {
            "model_path": str(new_model.resolve()), "model_sha256": sha256(new_model),
            "fit_receipt_sha256": sha256(view_paths["refit-head"] / "models" / f"{surface}-fit.json"),
            "prediction": new_pred}
        print(json.dumps({"phase": "surface_predictions_sealed", "surface": surface,
                          "old_sha256": old_record["sha256"], "refit_sha256": new_pred["sha256"]}),
              flush=True)
    write_json(output / "prediction-manifest.json", receipt)
    print(json.dumps({"phase": "prediction_complete", "output": str(output),
                      "manifest_sha256": sha256(output / "prediction-manifest.json"),
                      "truth_joined": False}), flush=True)


def score(args) -> None:
    output = args.output.resolve()
    manifest_path = output / "prediction-manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("truth_joined") is not False:
        raise RuntimeError("predictions must be sealed before truth join")
    for lane in ("old-head", "refit-head"):
        for surface, item in manifest["lanes"][lane].items():
            prediction = item["prediction"]
            pred_path = output / lane / "predictions" / f"{surface}.jsonl"
            seal_path = output / lane / "predictions" / f"{surface}-seal.json"
            seal = read_json(seal_path)
            if sha256(pred_path) != prediction["sha256"] or sha256(seal_path) != prediction["seal_sha256"]:
                raise RuntimeError(f"prediction hash mismatch: {lane}/{surface}")
            if seal.get("truth_join_performed") is not False:
                raise RuntimeError(f"prediction lane already contains a truth join: {lane}/{surface}")
    report = {"schema": "lexi-specialization-bank-survival/v1",
              "prediction_manifest_sha256": sha256(manifest_path),
              "truth_join_after_predictions": True, "lanes": {}, "base_atlas": {}}
    baseline = read_json(args.r0_artifacts / "surface-score.json")
    truth_hashes = {}
    split_names = ["DEV", *[name for name, _ in common.INPUT_SPECS if name.startswith("TEST-")]]
    partitions = {}
    for split in split_names:
        rows, truth_hash = bank_score.load_partition_rows(args.bank_root, split,
                                                           protected=split.startswith("TEST-"))
        truth_hashes[split] = truth_hash
        targets = [common.encode_targets(row) for row in rows]
        partitions[split] = (rows, targets)
    for lane in ("old-head", "refit-head"):
        lane_report = {}
        for surface in SURFACES:
            predictions = {row["row_id"]: row for row in common.read_jsonl(
                output / lane / "predictions" / f"{surface}.jsonl")}
            per_split = {}
            all_test_scored, all_test_targets, all_test_rows = [], [], []
            for split, (truth_rows, targets) in partitions.items():
                if any(row["world_id"] not in predictions for row in truth_rows):
                    raise RuntimeError(f"missing {lane}/{surface} predictions for {split}")
                scored = [predictions[row["world_id"]] for row in truth_rows]
                if split.startswith("TEST-"):
                    all_test_scored.extend(scored)
                    all_test_targets.extend(targets)
                    all_test_rows.extend(truth_rows)
                primary_mask = [not row.get("paired_world") for row in truth_rows]
                primary_rows = [row for row, keep in zip(scored, primary_mask) if keep]
                primary_targets = [target for target, keep in zip(targets, primary_mask) if keep]
                per_split[split] = {"all_rows": bank_score.metric_pack(scored, targets),
                                    "primary_worlds": bank_score.metric_pack(primary_rows,
                                                                              primary_targets)}
            primary_mask = [not row.get("paired_world") for row in all_test_rows]
            primary_scored = [row for row, keep in zip(all_test_scored, primary_mask) if keep]
            primary_targets = [target for target, keep in zip(all_test_targets, primary_mask) if keep]
            held_mask = [keep and row.get("surface_family") in {"S7", "S8", "S9"}
                         for row, keep in zip(all_test_rows, primary_mask)]
            held_scored = [row for row, keep in zip(all_test_scored, held_mask) if keep]
            held_targets = [target for target, keep in zip(all_test_targets, held_mask) if keep]
            lane_report[surface] = {
                "per_split": per_split,
                "test_all_rows": bank_score.metric_pack(all_test_scored, all_test_targets),
                "test_primary_worlds": bank_score.metric_pack(primary_scored, primary_targets),
                "test_held_renderers_s7_s8_s9": bank_score.metric_pack(held_scored, held_targets),
            }
        report["lanes"][lane] = lane_report
    for surface in SURFACES:
        report["base_atlas"][surface] = baseline["arms"][surface]["per_split"]
    report["truth_hashes_opened_after_prediction_seal"] = truth_hashes
    write_json(output / "survival-score.json", report)
    lines = ["# Specialized BANK-v1 capability survival", "",
             "Frozen Rung-0 observers are applied unchanged to specialized features; refit observers use BANK TRAIN only.",
             "Rows below are canonical TEST worlds pooled across the frozen test partitions.", "",
             "| Surface | Head set | Route exact | Decision macro-F1 | Abstain-reason macro-F1 | NLI macro-F1 | Held S7/S8/S9 route exact |",
             "|---|---|---:|---:|---:|---:|---:|"]
    def metric_value(pack, *path):
        value = pack
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        return "—" if value is None else f"{value:.4f}"
    for surface in SURFACES:
        baseline_pack = baseline["arms"][surface]["test_canonical_worlds"]
        lines.append("| {} | Base | {} | {} | {} | {} | — |".format(
            surface, metric_value(baseline_pack, "bundles", "decision_route_exact", "accuracy"),
            metric_value(baseline_pack, "heads", "decision", "macro_f1_present_classes"),
            metric_value(baseline_pack, "heads", "abstain_reason", "macro_f1_present_classes"),
            metric_value(baseline_pack, "heads", "nli", "macro_f1_present_classes")))
        for lane, label in (("old-head", "Frozen"), ("refit-head", "Refit")):
            pack = report["lanes"][lane][surface]["test_primary_worlds"]
            held_pack = report["lanes"][lane][surface]["test_held_renderers_s7_s8_s9"]
            lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                surface, label, metric_value(pack, "bundles", "decision_route_exact", "accuracy"),
                metric_value(pack, "heads", "decision", "macro_f1_present_classes"),
                metric_value(pack, "heads", "abstain_reason", "macro_f1_present_classes"),
                metric_value(pack, "heads", "nli", "macro_f1_present_classes"),
                metric_value(held_pack, "bundles", "decision_route_exact", "accuracy")))
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "scoring_complete", "output": str(output),
                      "score_sha256": sha256(output / "survival-score.json"),
                      "surfaces": list(SURFACES)}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--bank-root", type=Path, required=True)
    p.add_argument("--features", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--r0-artifacts", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(run=predict)
    s = sub.add_parser("score")
    s.add_argument("--bank-root", type=Path, required=True)
    s.add_argument("--r0-artifacts", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.set_defaults(run=score)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
