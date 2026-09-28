"""Independent raw-prediction replay and Q-R2 analysis verification."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
EVAL = RUN / "evaluation-v01"
TRAIN = RUN / "training-v01"
PANEL = RUN / "panel-v01"
RECEIPT = EVAL / "independent-replay-verification-v01.json"
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
BRANCHES = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
BASE_METRICS = (
    "strict_transition", "anchor_old_map", "fact_new_map", "correct_direction",
    "new_probability_delta", "exact_new_probability_delta", "delta_mae", "new_rank_gain",
    "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy", "sham_l1", "sham_map_flip",
    "sham_gold_probability_movement", "sham_new_probability_movement", "sham_margin_movement",
    "sham_exact_gold_l1", "matched_l1", "matched_map_flip", "matched_gold_probability_movement",
    "matched_new_probability_movement", "matched_margin_movement", "matched_exact_gold_l1",
)
GEOMETRY_METRICS = ("anchor_old_new_margin", "fact_old_new_margin",
                    "fact_conditioned_pairwise_margin_movement", "old_candidate_probability_movement",
                    "anchor_old_winner_gap", "fact_new_winner_gap")
METRICS = BASE_METRICS + GEOMETRY_METRICS
MODERATORS = (("fact_new_winner_gap", "new_probability_delta"),
              ("anchor_old_winner_gap", "anchor_old_map"))
BOOTSTRAP_SEED = 3569726509
MODERATOR_SEED = 4165424982


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def actual_winner(values: dict[str, float]) -> str:
    return max(values, key=lambda candidate: (values[candidate], candidate))


def rank(values: dict[str, float], candidate: str) -> int:
    return sorted(values, key=lambda item: (-values[item], item)).index(candidate) + 1


def replay_neighborhood(views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    need(set(views) == set(VIEWS), "independent replay found incomplete four-view neighborhood")
    prediction: dict[str, dict[str, float]] = {}
    gold: dict[str, dict[str, float]] = {}
    ids: list[str] | None = None
    for view in VIEWS:
        row = views[view]
        current = [str(value) for value in row["candidate_semantic_ids"]]
        need(len(current) == 4 and len(set(current)) == 4, "candidate identity/order malformed")
        need(ids is None or current == ids, "candidate ordering differs between views")
        ids = current
        p = [float(value) for value in row["prediction"]]
        g = [float(value) for value in row["gold"]]
        need(len(p) == len(g) == 4 and all(math.isfinite(v) for v in p + g), "nonfinite/malformed probability vector")
        need(abs(sum(p) - 1.0) <= 1e-6 and abs(sum(g) - 1.0) <= 1e-12, "probability vector normalization mismatch")
        prediction[view] = dict(zip(current, p, strict=True))
        gold[view] = dict(zip(current, g, strict=True))
    assert ids is not None
    anchor_row = views["anchor"]
    old, new = str(anchor_row["old_candidate_id"]), str(anchor_row["new_candidate_id"])
    need(old in ids and new in ids and old != new, "old/new target identities invalid")
    need(all(str(row["old_candidate_id"]) == old and str(row["new_candidate_id"]) == new for row in views.values()),
         "old/new identity mismatch across views")
    family = str(anchor_row["family_id"]).split(":")[-1]
    need(family in FAMILIES and all(str(row["family_id"]).split(":")[-1] == family for row in views.values()),
         "family identity malformed across views")
    pa, pf = prediction["anchor"], prediction["fact_flip"]
    ga, gf = gold["anchor"], gold["fact_flip"]
    wa, wf = actual_winner(pa), actual_winner(pf)
    d_model, d_exact = pf[new] - pa[new], gf[new] - ga[new]
    values: dict[str, float] = {
        "strict_transition": float(wa == old and wf == new),
        "anchor_old_map": float(wa == old), "fact_new_map": float(wf == new),
        "correct_direction": float(d_model * d_exact > 0.0 if abs(d_exact) > 1e-12 else abs(d_model) <= 1e-12),
        "new_probability_delta": d_model, "exact_new_probability_delta": d_exact,
        "delta_mae": abs(d_model - d_exact), "new_rank_gain": float(rank(pa, new) - rank(pf, new)),
        "anchor_nll": -sum(ga[key] * math.log(max(pa[key], 1e-30)) for key in ids),
        "anchor_brier": sum((pa[key] - ga[key]) ** 2 for key in ids),
        "anchor_gold_map_accuracy": float(wa == actual_winner(ga)),
        "anchor_old_new_margin": pa[new] - pa[old], "fact_old_new_margin": pf[new] - pf[old],
        "fact_conditioned_pairwise_margin_movement": (pf[new] - pf[old]) - (pa[new] - pa[old]),
        "old_candidate_probability_movement": pf[old] - pa[old],
        "anchor_old_winner_gap": pa[old] - max(pa[key] for key in ids if key != old),
        "fact_new_winner_gap": pf[new] - max(pf[key] for key in ids if key != new),
    }
    categories: dict[str, Any] = {
        "anchor_frozen_argmax_candidate_id": wa, "fact_frozen_argmax_candidate_id": wf,
        "anchor_old_winner_gap_strongest_competitor_id": actual_winner({key: pa[key] for key in ids if key != old}),
        "fact_new_winner_gap_strongest_competitor_id": actual_winner({key: pf[key] for key in ids if key != new}),
        "old_candidate_id": old, "new_candidate_id": new,
    }
    for view, prefix in (("sham", "sham"), ("matched_neutral", "matched")):
        pred = prediction[view]
        gv = gold[view]
        values[f"{prefix}_l1"] = sum(abs(pa[key] - pred[key]) for key in ids)
        values[f"{prefix}_map_flip"] = float(actual_winner(pa) != actual_winner(pred))
        values[f"{prefix}_gold_probability_movement"] = pred[old] - pa[old]
        values[f"{prefix}_new_probability_movement"] = pred[new] - pa[new]
        values[f"{prefix}_margin_movement"] = (pred[new] - pred[old]) - (pa[new] - pa[old])
        values[f"{prefix}_exact_gold_l1"] = sum(abs(ga[key] - gv[key]) for key in ids)
    return {"family": family, **values, **categories}


def cells() -> list[tuple[int, str, int]]:
    result = []
    for seed in SEEDS:
        result.append((seed, "COMMON_SHAM_1X", 80))
        for arm in BRANCHES:
            result.extend((seed, arm, step) for step in (100, 120))
    return result


def close(a: Any, b: Any, tol: float = 1e-12) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=tol)
    except (TypeError, ValueError):
        return False


def compare_record(expected: dict[str, Any], observed: dict[str, Any], label: str) -> None:
    need(expected.keys() == observed.keys(), f"metric output fields differ at {label}")
    for key, value in expected.items():
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            need(close(value, observed[key]), f"independent metric replay mismatch {label}/{key}: {value} != {observed[key]}")
        else:
            need(value == observed[key], f"independent metric replay category mismatch {label}/{key}")


def independent_plan(families: list[str]) -> np.ndarray:
    pos = {family: np.flatnonzero(np.asarray(families) == family) for family in FAMILIES}
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    plan = np.empty((10_000, 2_000), dtype=np.int32)
    for family in FAMILIES:
        members = pos[family].astype(np.int32, copy=False)
        plan[:, members] = members[rng.integers(0, len(members), size=(10_000, len(members)), dtype=np.int32)]
    return plan


def verify() -> dict[str, Any]:
    instrument = json.loads((RUN / "provenance/q-r2-instrument-package-seal-v01.json").read_text(encoding="utf-8"))
    need(instrument.get("status") == "Q_R2_INSTRUMENT_PACKAGE_SEALED", "instrument seal absent")
    verifier_spec = __import__("importlib.util", fromlist=["spec_from_file_location"])
    spec = verifier_spec.spec_from_file_location("q_r2_result_instrument_verifier", EXP / "source/verify_q_r2_instrument_package_v01.py")
    need(spec is not None and spec.loader is not None, "instrument verifier cannot load")
    module = verifier_spec.module_from_spec(spec)
    spec.loader.exec_module(module)
    instrument_check = module.verify()
    panel_seal = read_json(PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json")
    train_seal = read_json(TRAIN / "training-seal-manifest.json")
    train_tree = read_json(TRAIN / "checkpoint-hash-tree.json")
    inference = read_json(EVAL / "inference-receipt-v01.json")
    pred_tree = read_json(EVAL / "raw-prediction-hash-tree-v01.json")
    analysis_seal = read_json(EVAL / "q-r2-analysis-seal-v01.json")
    result = read_json(EVAL / "q-r2-analysis-v01.json")
    predictions_path = EVAL / "raw-predictions-v01.jsonl"
    need(panel_seal.get("status") == "Q_R2_PANEL_INPUTS_SEALED_TRAINING_PENDING" and panel_seal.get("panel_opened") is False,
         "R2 panel input seal invalid")
    need(train_seal.get("status") == "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED"
         and train_seal.get("trained_checkpoint_count") == 120 and train_seal.get("evaluation_panel_opened") is False,
         "R2 training seal invalid or evaluation feedback present")
    need(train_tree.get("entry_count") == len(train_tree.get("entries", []))
         and train_seal.get("checkpoint_tree_sha256") == sha(TRAIN / "checkpoint-hash-tree.json"),
         "R2 checkpoint tree binding invalid")
    for row in train_tree["entries"]:
        path = TRAIN / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"R2 training artifact hash mismatch: {row['path']}")
    need(inference.get("status") == "Q_R2_ALL_120_CELLS_INFERRED_AND_SEALED"
         and pred_tree.get("status") == "Q_R2_ALL_120_CELLS_AND_960000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS"
         and inference.get("panel_open_count") == pred_tree.get("panel_open_count") == 1
         and pred_tree.get("prediction_rows") == 960_000 and pred_tree.get("cell_count") == 120
         and predictions_path.is_file() and sha(predictions_path) == pred_tree["raw_predictions"]["sha256"]
         and sha(EVAL / "raw-prediction-hash-tree-v01.json") == inference["prediction_hash_tree_sha256"],
         "R2 complete sealed prediction matrix invalid")
    need(analysis_seal.get("status") == "Q_R2_ANALYSIS_OUTPUTS_SEALED"
         and analysis_seal.get("panel_open_count") == 1
         and analysis_seal.get("prediction_hash_tree_sha256") == sha(EVAL / "raw-prediction-hash-tree-v01.json"),
         "R2 analysis seal binding invalid")
    output_by_name = {row["path"]: row for row in analysis_seal["outputs"]}
    need(len(output_by_name) == len(analysis_seal["outputs"]), "duplicate analysis output entries")
    for name, row in output_by_name.items():
        path = EVAL / name
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"sealed analysis output mismatch: {name}")

    metrics_path = EVAL / "neighborhood-metrics-v01.jsonl"
    metric_stream = metrics_path.open("r", encoding="utf-8")
    pred_stream = predictions_path.open("r", encoding="utf-8")
    replayed: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    canonical_ids: list[str] | None = None
    canonical_families: list[str] | None = None
    prediction_row_count = metric_row_count = 0
    try:
        for cell in cells():
            seed, arm, step = cell
            grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
            for _ in range(8_000):
                raw = pred_stream.readline()
                need(bool(raw), f"prediction EOF inside cell {cell}")
                prediction_row_count += 1
                row = json.loads(raw)
                need((int(row["seed"]), str(row["arm"]), int(row["global_step"])) == cell,
                     f"prediction cell ordering mismatch at {cell}")
                nid, view = str(row["neighborhood_id"]), str(row["view"])
                need(view in VIEWS and view not in grouped[nid], f"duplicate/unexpected view {nid}/{view}")
                grouped[nid][view] = row
            need(len(grouped) == 2_000, f"cell neighborhood cardinality mismatch: {cell}")
            ids = sorted(grouped)
            rows = [replay_neighborhood(grouped[nid]) for nid in ids]
            families = [row["family"] for row in rows]
            need(set(families) == set(FAMILIES) and all(families.count(name) == 500 for name in FAMILIES),
                 f"cell family quota mismatch: {cell}")
            if canonical_ids is None:
                canonical_ids, canonical_families = ids, families
            else:
                need(ids == canonical_ids and families == canonical_families, f"panel identity/order differs: {cell}")
            metric_rows = []
            for nid, expected in zip(ids, rows, strict=True):
                raw = metric_stream.readline()
                need(bool(raw), "metric stream EOF before complete replay")
                metric_row_count += 1
                observed = json.loads(raw)
                need((observed["seed"], observed["branch"], observed["step"], observed["neighborhood_id"])
                     == (seed, arm, step, nid), f"metric row identity mismatch {seed}/{arm}/{step}/{nid}")
                expected_full = {"seed": seed, "branch": arm, "step": step, "neighborhood_id": nid, **expected}
                compare_record(expected_full, observed, f"{seed}/{arm}/{step}/{nid}")
                metric_rows.append(expected)
            replayed[cell] = metric_rows
        need(not pred_stream.readline() and not metric_stream.readline(), "extra prediction or metric rows")
    finally:
        pred_stream.close()
        metric_stream.close()
    need(prediction_row_count == 960_000 and metric_row_count == 240_000,
         "prediction/metric row totals incorrect")
    assert canonical_ids is not None and canonical_families is not None

    saved_plan_path = EVAL / "shared-neighborhood-bootstrap-plan-v01.npy"
    saved_plan = np.load(saved_plan_path, mmap_mode="r", allow_pickle=False)
    generated_plan = independent_plan(canonical_families)
    need(saved_plan.shape == (10_000, 2_000) and saved_plan.dtype == np.int32
         and np.array_equal(saved_plan, generated_plan), "shared neighborhood bootstrap plan replay mismatch")
    plan_hash = hashlib.sha256(np.asarray(generated_plan, dtype="<i4").tobytes(order="C")).hexdigest()
    need(result["shared_neighborhood_bootstrap"]["plan_sha256"] == plan_hash,
         "analysis neighborhood plan identity mismatch")
    family_pos = {family: np.flatnonzero(np.asarray(canonical_families) == family) for family in FAMILIES}
    index = {name: i for i, name in enumerate(METRICS)}
    def matrix(cell: tuple[int, str, int]) -> np.ndarray:
        return np.asarray([[row[name] for name in METRICS] for row in replayed[cell]], dtype=np.float64)
    def boot(values: np.ndarray, positions: np.ndarray | None = None) -> dict[str, Any]:
        sampled = values[generated_plan] if positions is None else values[generated_plan[:, positions]]
        means = sampled.mean(axis=1)
        ci = np.quantile(means, [0.025, 0.975], method="linear")
        point = values.mean() if positions is None else values[positions].mean()
        return {"mean": float(point), "ci95": [float(ci[0]), float(ci[1])],
                "paired_interval_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
                "annotation_only": True, "replicates": 10_000}

    for cell in cells():
        values = matrix(cell)
        key = f"{cell[0]}/{cell[1]}/{cell[2]}"
        summary = result["cell_response_summaries"][key]
        need(summary.get("n") == 2_000, f"cell summary count mismatch: {key}")
        for metric in METRICS:
            need(close(summary["overall"][metric], values[:, index[metric]].mean()), f"overall summary mismatch {key}/{metric}")
            for family in FAMILIES:
                pos = family_pos[family]
                need(close(summary["by_family"][family][metric], values[pos, index[metric]].mean()),
                     f"family summary mismatch {key}/{family}/{metric}")
        a = values[:, index["anchor_old_map"]] >= 0.5
        f = values[:, index["fact_new_map"]] >= 0.5
        four = ((True, True, "A_old_AND_F_new"), (True, False, "A_old_AND_NOT_F_new"),
                (False, True, "NOT_A_old_AND_F_new"), (False, False, "NOT_A_old_AND_NOT_F_new"))
        for av, fv, name in four:
            count = int(((a == av) & (f == fv)).sum())
            need(summary["four_cell_A_F"][name]["count"] == count
                 and close(summary["four_cell_A_F"][name]["rate"], count / 2000),
                 f"A/F cell mismatch {key}/{name}")

    contrasts = result["step120_primary_paired_effects"]
    effects: dict[str, list[float]] = {metric: [] for metric in METRICS}
    for seed in SEEDS:
        one, half = matrix((seed, "LATE_SHAM_1X", 120)), matrix((seed, "LATE_SHAM_HALF", 120))
        for metric in METRICS:
            diff = half[:, index[metric]] - one[:, index[metric]]
            rec = contrasts[f"{seed}/step120/{metric}"]
            compare_record(boot(diff), rec["overall"], f"paired contrast {seed}/{metric}")
            effects[metric].append(float(diff.mean()))
            for family, pos in family_pos.items():
                compare_record(boot(diff, pos), rec["by_family"][family], f"family contrast {seed}/{family}/{metric}")
    for metric, values in effects.items():
        observed = result["observed_seed_effect_summary"][metric]
        need(close(observed["mean_of_24_seed_effects"], np.mean(values))
             and close(observed["median_of_24_seed_effects"], np.median(values))
             and observed["positive_seed_count"] == int(np.sum(np.asarray(values) > 0))
             and observed["negative_seed_count"] == int(np.sum(np.asarray(values) < 0))
             and observed["zero_seed_count"] == int(np.sum(np.asarray(values) == 0))
             and close(observed["range"][0], min(values)) and close(observed["range"][1], max(values)),
             f"cohort descriptive summary mismatch: {metric}")

    moderator_plan = np.random.Generator(np.random.PCG64(MODERATOR_SEED)).integers(
        0, len(SEEDS), size=(10_000, len(SEEDS)), dtype=np.int32)
    moderator_path = EVAL / "shared-moderator-seed-resample-plan-v01.npy"
    saved_moderator_plan = np.load(moderator_path, mmap_mode="r", allow_pickle=False)
    need(saved_moderator_plan.shape == moderator_plan.shape and saved_moderator_plan.dtype == np.int32
         and np.array_equal(saved_moderator_plan, moderator_plan), "moderator shared seed plan mismatch")
    def slope(x: np.ndarray, y: np.ndarray) -> float | None:
        if len(x) < 2 or float(np.ptp(x)) == 0.0:
            return None
        xc = x - x.mean()
        return float(np.dot(xc, y - y.mean()) / np.dot(xc, xc))
    rels = result["step80_state_moderation"]["relationships"]
    fam_arr = np.asarray(canonical_families)
    for family in FAMILIES:
        pos = np.flatnonzero(fam_arr == family)
        for moderator, outcome in MODERATORS:
            xi, yi = [], []
            for seed in SEEDS:
                x = matrix((seed, "COMMON_SHAM_1X", 80))[pos, index[moderator]].mean()
                y = (matrix((seed, "LATE_SHAM_HALF", 120))[pos, index[outcome]]
                     - matrix((seed, "LATE_SHAM_1X", 120))[pos, index[outcome]]).mean()
                xi.append(float(x)); yi.append(float(y))
            x, y = np.asarray(xi), np.asarray(yi)
            key = f"{family}/{moderator}->{outcome}"
            observed = rels[key]
            need(len(observed["seed_points"]) == 24, f"moderator point count mismatch: {key}")
            for i, point in enumerate(observed["seed_points"]):
                need(point["seed"] == SEEDS[i] and close(point["step80_moderator_mean"], x[i])
                     and close(point["step120_half_minus_1x_mean"], y[i]), f"moderator pair mismatch {key}/{i}")
            base_slope = slope(x, y)
            need((base_slope is None and observed["ols_slope_per_0.1_moderator"] is None)
                 or (base_slope is not None and close(observed["ols_slope_per_0.1_moderator"], base_slope * 0.1)),
                 f"moderator slope mismatch: {key}")
            boot_slopes = np.full(10_000, np.nan, dtype=np.float64)
            for replicate, chosen in enumerate(moderator_plan):
                candidate = slope(x[chosen], y[chosen])
                if candidate is not None:
                    boot_slopes[replicate] = candidate * 0.1
            finite = boot_slopes[np.isfinite(boot_slopes)]
            bootrec = observed["paired_seed_cluster_bootstrap"]
            need(bootrec["valid_replicates"] == len(finite), f"moderator bootstrap valid count mismatch: {key}")
            expected_ci = np.quantile(finite, [0.025, 0.975], method="linear").tolist() if len(finite) >= 9_500 else None
            actual_ci = bootrec["ci95"]
            need((expected_ci is None and actual_ci is None)
                 or (expected_ci is not None and actual_ci is not None and all(close(a, b) for a, b in zip(expected_ci, actual_ci, strict=True))),
                 f"moderator bootstrap interval mismatch: {key}")

    need(result.get("status") == "Q_R2_PAIRED_LATE_BRANCH_ANALYSIS_COMPLETE"
         and result.get("seed_population_inference") is False and result.get("policy_or_controller_fitting") is False,
         "Q-R2 analysis scope/status mismatch")
    output = {"status": "Q_R2_INDEPENDENT_RESULT_REPLAY_PASS",
              "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
              "instrument_package_seal_sha256": instrument_check["seal_sha256"],
              "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
              "panel_input_seal_sha256": sha(PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"),
              "prediction_tree_sha256": sha(EVAL / "raw-prediction-hash-tree-v01.json"),
              "raw_predictions_sha256": sha(predictions_path), "analysis_seal_sha256": sha(EVAL / "q-r2-analysis-seal-v01.json"),
              "cells_replayed": 120, "prediction_rows_replayed": prediction_row_count,
              "metric_rows_independently_replayed": metric_row_count, "seed_count": 24,
              "metric_coordinates_recomputed": len(METRICS), "paired_effects_recomputed": 24 * len(METRICS),
              "moderator_relationships_replayed": len(FAMILIES) * len(MODERATORS),
              "independent_metric_formula": True, "shared_resample_plans_replayed": True,
              "created_at_utc": datetime.now(timezone.utc).isoformat()}
    if RECEIPT.exists():
        raise FileExistsError(f"refusing to replace independent replay receipt: {RECEIPT}")
    RECEIPT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({**output, "receipt_sha256": sha(RECEIPT)}, indent=2))
    return output


if __name__ == "__main__":
    verify()
