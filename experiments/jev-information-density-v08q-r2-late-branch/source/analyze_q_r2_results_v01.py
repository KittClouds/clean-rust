"""Frozen paired-effect and state-moderation analysis for JEV v0.8Q-R2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
OUTPUT = RUN / "evaluation-v01"
CONTRACT = EXP / "contracts/q-r2-analysis-contract-v01.json"
PACKET = EXP / "seals/q-r2-phase-packet-seal-v01.json"
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
BRANCHES = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
CONTRACT_SHA = "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64"
RUN_SHA = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
PACKET_SHA = "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209"
PACKET_ROOT_SHA = "6b3b826fd3c861e1aa9114371f9db68c704fb9c5ad85e5c8c60a93afba527275"
METRIC_SHA = "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70"
BOOTSTRAP_SEED = 3569726509
MODERATOR_SEED = 4165424982
BASE_METRICS = (
    "strict_transition", "anchor_old_map", "fact_new_map", "correct_direction",
    "new_probability_delta", "exact_new_probability_delta", "delta_mae", "new_rank_gain",
    "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy", "sham_l1", "sham_map_flip",
    "sham_gold_probability_movement", "sham_new_probability_movement", "sham_margin_movement",
    "sham_exact_gold_l1", "matched_l1", "matched_map_flip", "matched_gold_probability_movement",
    "matched_new_probability_movement", "matched_margin_movement", "matched_exact_gold_l1",
)
GEOMETRY_METRICS = (
    "anchor_old_new_margin", "fact_old_new_margin", "fact_conditioned_pairwise_margin_movement",
    "old_candidate_probability_movement", "anchor_old_winner_gap", "fact_new_winner_gap",
)
METRICS = BASE_METRICS + GEOMETRY_METRICS
MODERATORS = (
    ("fact_new_winner_gap", "new_probability_delta"),
    ("anchor_old_winner_gap", "anchor_old_map"),
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
    with temp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot load bound analysis helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cells() -> list[tuple[int, str, int]]:
    result: list[tuple[int, str, int]] = []
    for seed in SEEDS:
        result.append((seed, "COMMON_SHAM_1X", 80))
        for branch in BRANCHES:
            result.extend((seed, branch, step) for step in (100, 120))
    return result


def actual_winner(probabilities: list[float], candidate_ids: list[str], frozen_metric: Any) -> str:
    return str(frozen_metric.winner({key: float(value) for key, value in zip(candidate_ids, probabilities, strict=True)}))


def strongest_other(probabilities: list[float], candidate_ids: list[str], target_id: str,
                    frozen_metric: Any) -> str:
    return actual_winner([value for value, key in zip(probabilities, candidate_ids, strict=True) if key != target_id],
                         [key for key in candidate_ids if key != target_id], frozen_metric)


def enriched(views: dict[str, dict[str, Any]], frozen_metric: Any) -> tuple[dict[str, float], dict[str, str]]:
    base = frozen_metric.neighborhood_metrics(views)
    anchor, fact = views["anchor"], views["fact_flip"]
    ids = [str(value) for value in anchor["candidate_semantic_ids"]]
    need(len(ids) == 4 and len(set(ids)) == 4, "candidate identity/order invalid")
    need(all([str(value) for value in row["candidate_semantic_ids"]] == ids for row in views.values()),
         "candidate semantic order changed between views")
    old_id, new_id = str(anchor["old_candidate_id"]), str(anchor["new_candidate_id"])
    need(old_id in ids and new_id in ids and old_id != new_id, "old/new candidate IDs invalid")
    index = {value: position for position, value in enumerate(ids)}
    pa = [float(value) for value in anchor["prediction"]]
    pf = [float(value) for value in fact["prediction"]]
    old_i, new_i = index[old_id], index[new_id]
    anchor_winner = actual_winner(pa, ids, frozen_metric)
    fact_winner = actual_winner(pf, ids, frozen_metric)
    numeric = {key: float(base[key]) for key in BASE_METRICS}
    numeric.update({
        "anchor_old_new_margin": pa[new_i] - pa[old_i],
        "fact_old_new_margin": pf[new_i] - pf[old_i],
        "fact_conditioned_pairwise_margin_movement": (pf[new_i] - pf[old_i]) - (pa[new_i] - pa[old_i]),
        "old_candidate_probability_movement": pf[old_i] - pa[old_i],
        "anchor_old_winner_gap": pa[old_i] - max(pa[j] for j in range(4) if j != old_i),
        "fact_new_winner_gap": pf[new_i] - max(pf[j] for j in range(4) if j != new_i),
    })
    categories = {
        "anchor_frozen_argmax_candidate_id": anchor_winner,
        "fact_frozen_argmax_candidate_id": fact_winner,
        "anchor_old_winner_gap_strongest_competitor_id": strongest_other(pa, ids, old_id, frozen_metric),
        "fact_new_winner_gap_strongest_competitor_id": strongest_other(pf, ids, new_id, frozen_metric),
        "old_candidate_id": old_id, "new_candidate_id": new_id,
    }
    return numeric, categories


def read_cell(stream: Any, cell: tuple[int, str, int], frozen_metric: Any,
              destination: Any) -> tuple[list[str], list[str], np.ndarray, list[dict[str, Any]]]:
    seed, branch, step = cell
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for _ in range(8_000):
        raw = stream.readline()
        need(bool(raw), f"raw prediction stream ended within {cell}")
        row = json.loads(raw)
        need((int(row["seed"]), str(row["arm"]), int(row["global_step"])) == cell,
             f"raw prediction cell order mismatch: expected {cell}")
        nid, view = str(row["neighborhood_id"]), str(row["view"])
        need(view in VIEWS and view not in grouped[nid], f"duplicate/unknown neighborhood view {nid}/{view}")
        prediction, gold = [float(x) for x in row["prediction"]], [float(x) for x in row["gold"]]
        need(len(prediction) == len(gold) == 4 and np.isfinite(prediction).all() and np.isfinite(gold).all()
             and abs(sum(prediction) - 1.0) <= 1e-6 and abs(sum(gold) - 1.0) <= 1e-12,
             f"invalid probability or exact target: {nid}/{view}")
        grouped[nid][view] = row
    need(len(grouped) == 2_000 and all(set(value) == set(VIEWS) for value in grouped.values()),
         f"incomplete four-view cell: {cell}")
    ids = sorted(grouped)
    family_by_id = {nid: str(grouped[nid]["anchor"]["family_id"]).split(":")[-1] for nid in ids}
    families = [family_by_id[nid] for nid in ids]
    need(set(families) == set(FAMILIES) and all(families.count(family) == 500 for family in FAMILIES),
         f"family allocation mismatch in cell {cell}")
    values = np.empty((2_000, len(METRICS)), dtype=np.float64)
    rows_out: list[dict[str, Any]] = []
    for index, nid in enumerate(ids):
        views = grouped[nid]
        family = family_by_id[nid]
        need(all(str(views[v]["family_id"]).split(":")[-1] == family for v in VIEWS),
             f"family differs across views: {nid}")
        numeric, categories = enriched(views, frozen_metric)
        values[index] = [numeric[name] for name in METRICS]
        record = {"seed": seed, "branch": branch, "step": step, "neighborhood_id": nid, "family": family,
                  **numeric, **categories}
        rows_out.append(record)
        destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return ids, families, values, rows_out


def summary(values: np.ndarray, families: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"n": int(len(values)), "overall": {}, "by_family": {}, "four_cell_A_F": {}}
    for column, name in enumerate(METRICS):
        result["overall"][name] = float(values[:, column].mean())
    family_array = np.asarray(families)
    for family in FAMILIES:
        rows = np.flatnonzero(family_array == family)
        need(len(rows) == 500, f"summary family count mismatch: {family}")
        result["by_family"][family] = {name: float(values[rows, col].mean()) for col, name in enumerate(METRICS)}
    a = values[:, METRICS.index("anchor_old_map")] >= 0.5
    f = values[:, METRICS.index("fact_new_map")] >= 0.5
    for av, fv, name in ((True, True, "A_old_AND_F_new"), (True, False, "A_old_AND_NOT_F_new"),
                         (False, True, "NOT_A_old_AND_F_new"), (False, False, "NOT_A_old_AND_NOT_F_new")):
        selected = (a == av) & (f == fv)
        result["four_cell_A_F"][name] = {"count": int(selected.sum()), "rate": float(selected.mean())}
    return result


def neighborhood_plan(ids: list[str], families: list[str], seed: int) -> tuple[np.ndarray, str]:
    positions = {family: np.flatnonzero(np.asarray(families) == family) for family in FAMILIES}
    need(all(len(positions[family]) == 500 for family in FAMILIES), "bootstrap family support mismatch")
    rng = np.random.Generator(np.random.PCG64(seed))
    plan = np.empty((10_000, 2_000), dtype=np.int32)
    for family in FAMILIES:
        members = positions[family].astype(np.int32, copy=False)
        draws = rng.integers(0, len(members), size=(10_000, len(members)), dtype=np.int32)
        plan[:, members] = members[draws]
    digest = hashlib.sha256(np.asarray(plan, dtype="<i4").tobytes(order="C")).hexdigest()
    return plan, digest


def boot_summary(values: np.ndarray, plan: np.ndarray, positions: np.ndarray | None = None) -> dict[str, Any]:
    sampled = values[plan] if positions is None else values[plan[:, positions]]
    means = sampled.mean(axis=1)
    ci = [float(x) for x in np.quantile(means, [0.025, 0.975], method="linear")]
    return {"mean": float(values.mean() if positions is None else values[positions].mean()), "ci95": ci,
            "paired_interval_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
            "annotation_only": True, "replicates": 10_000}


def ols_slope(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) != len(y) or len(x) < 2 or float(np.ptp(x)) == 0.0:
        return None
    xc = x - x.mean()
    return float(np.dot(xc, y - y.mean()) / np.dot(xc, xc))


def moderator_analysis(arrays: dict[tuple[int, str, int], np.ndarray],
                       ids: list[str], families: list[str], output_dir: Path) -> dict[str, Any]:
    index = {name: i for i, name in enumerate(METRICS)}
    fam = np.asarray(families)
    seed_rows: dict[str, Any] = {}
    all_values: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for family in FAMILIES:
        positions = np.flatnonzero(fam == family)
        for moderator, outcome in MODERATORS:
            xs, ys = [], []
            for seed in SEEDS:
                x = arrays[(seed, "COMMON_SHAM_1X", 80)][positions, index[moderator]].mean()
                one = arrays[(seed, "LATE_SHAM_1X", 120)][positions, index[outcome]]
                half = arrays[(seed, "LATE_SHAM_HALF", 120)][positions, index[outcome]]
                y = (half - one).mean()
                xs.append(float(x)); ys.append(float(y))
            all_values[(family, moderator)] = (np.asarray(xs), np.asarray(ys))
            slope = ols_slope(np.asarray(xs), np.asarray(ys))
            seed_rows[f"{family}/{moderator}->{outcome}"] = {
                "observational_unit": "seed; one family-mean pair per seed",
                "moderator": moderator, "paired_outcome": outcome,
                "seed_points": [{"seed": seed, "step80_moderator_mean": x, "step120_half_minus_1x_mean": y}
                                for seed, x, y in zip(SEEDS, xs, ys, strict=True)],
                "ols_slope_per_0.1_moderator": None if slope is None else slope * 0.1,
            }
    boot_seed = np.random.Generator(np.random.PCG64(MODERATOR_SEED))
    seed_plan = boot_seed.integers(0, len(SEEDS), size=(10_000, len(SEEDS)), dtype=np.int32)
    seed_plan_hash = hashlib.sha256(np.asarray(seed_plan, dtype="<i4").tobytes(order="C")).hexdigest()
    seed_plan_path = output_dir / "shared-moderator-seed-resample-plan-v01.npy"
    with seed_plan_path.open("xb") as stream:
        np.save(stream, seed_plan, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    for key, (x, y) in all_values.items():
        slopes = np.full(10_000, np.nan, dtype=np.float64)
        for rep, chosen in enumerate(seed_plan):
            value = ols_slope(x[chosen], y[chosen])
            if value is not None:
                slopes[rep] = value * 0.1
        valid = np.isfinite(slopes)
        rec = seed_rows[f"{key[0]}/{key[1]}->{MODERATORS[0][1] if key[1] == MODERATORS[0][0] else MODERATORS[1][1]}"]
        valid_count = int(valid.sum())
        rec["paired_seed_cluster_bootstrap"] = {
            "seed": MODERATOR_SEED, "shared_plan_sha256": seed_plan_hash, "valid_replicates": valid_count,
            "invalid_replicates": int((~valid).sum()),
            "ci95": ([float(v) for v in np.quantile(slopes[valid], [0.025, 0.975], method="linear")]
                     if valid_count >= 9_500 else None),
            "status": "ESTIMABLE" if valid_count >= 9_500 else "CI_NOT_ESTIMABLE",
            "p_value_or_threshold": False,
        }
    return {"purpose": "secondary descriptive seed-level effect modification; not causal mediation or a controller",
            "seed_count": 24, "family_order": list(FAMILIES), "relationships": seed_rows,
            "shared_seed_resample_plan": {"shape": [10_000, 24], "dtype": "int32",
                "seed": MODERATOR_SEED, "sha256": seed_plan_hash, "file_sha256": sha(seed_plan_path),
                "path": seed_plan_path.name, "shared_across_families_and_relationships": True}}


def self_test() -> None:
    assert cells()[0] == (SEEDS[0], "COMMON_SHAM_1X", 80)
    assert cells()[1:5] == [(SEEDS[0], "LATE_SHAM_1X", 100), (SEEDS[0], "LATE_SHAM_1X", 120),
                            (SEEDS[0], "LATE_SHAM_HALF", 100), (SEEDS[0], "LATE_SHAM_HALF", 120)]
    sample = np.arange(2_000, dtype=np.float64)
    fake = np.tile(np.repeat(np.asarray(FAMILIES), 500), 1).tolist()
    plan, digest = neighborhood_plan([str(i) for i in range(2_000)], fake, BOOTSTRAP_SEED)
    assert plan.shape == (10_000, 2_000) and len(digest) == 64
    assert np.array_equal(plan, neighborhood_plan([str(i) for i in range(2_000)], fake, BOOTSTRAP_SEED)[0])
    assert np.isfinite(boot_summary(sample, plan)["mean"])
    assert ols_slope(np.asarray([1., 2., 3.]), np.asarray([2., 4., 6.])) == 2.0
    print("Q-R2 analysis synthetic self-test PASS")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    stage = "analysis_preflight"
    try:
        verifier_module = load_module(EXP / "source/verify_q_r2_instrument_package_v01.py",
                                      "q_r2_instrument_verifier_analysis")
        instrument = verifier_module.verify()
        need(sha(CONTRACT) == CONTRACT_SHA and sha(PACKET) == PACKET_SHA, "Q-R2 contract identity mismatch")
        packet = read_json(PACKET)
        need(packet.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
             and packet.get("contract_bundle_root_sha256") == PACKET_ROOT_SHA, "Q-R2 phase packet identity mismatch")
        train_seal = read_json(RUN / "training-v01/training-seal-manifest.json")
        pred_tree = read_json(OUTPUT / "raw-prediction-hash-tree-v01.json")
        inference = read_json(OUTPUT / "inference-receipt-v01.json")
        predictions = OUTPUT / "raw-predictions-v01.jsonl"
        need(train_seal.get("status") == "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED"
             and inference.get("status") == "Q_R2_ALL_120_CELLS_INFERRED_AND_SEALED"
             and pred_tree.get("status") == "Q_R2_ALL_120_CELLS_AND_960000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS"
             and inference.get("prediction_sha256") == sha(predictions)
             and pred_tree.get("raw_predictions", {}).get("sha256") == sha(predictions)
             and pred_tree.get("prediction_rows") == 960_000 and pred_tree.get("cell_count") == 120
             and pred_tree.get("panel_open_count") == 1 and pred_tree.get("predictions_before_analysis") is True,
             "Q-R2 prediction/training seal invalid")
        metric_path = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
        need(sha(metric_path) == METRIC_SHA, "frozen neighborhood metric implementation changed")
        frozen_metric = load_module(metric_path, "q_r2_frozen_neighborhood_metric")
        metric_path_out = OUTPUT / "neighborhood-metrics-v01.jsonl"
        arrays: dict[tuple[int, str, int], np.ndarray] = {}
        canonical_ids: list[str] | None = None
        canonical_families: list[str] | None = None
        cells_meta = []
        stage = "stream_metrics_from_sealed_predictions"
        with predictions.open("r", encoding="utf-8") as source, metric_path_out.open("x", encoding="utf-8", newline="\n") as destination:
            for cell in cells():
                ids, families, values, _ = read_cell(source, cell, frozen_metric, destination)
                if canonical_ids is None:
                    canonical_ids, canonical_families = ids, families
                else:
                    need(ids == canonical_ids and families == canonical_families,
                         f"paired panel identity/order differs in {cell}")
                arrays[cell] = values
                cells_meta.append({"seed": cell[0], "branch": cell[1], "step": cell[2], "neighborhoods": len(ids)})
            need(not source.readline(), "extra rows after Q-R2 complete prediction matrix")
            destination.flush()
            os.fsync(destination.fileno())
        need(canonical_ids is not None and canonical_families is not None and len(arrays) == 120,
             "Q-R2 analysis cell matrix incomplete")
        cell_summaries = {f"{seed}/{branch}/{step}": summary(arrays[(seed, branch, step)], canonical_families)
                          for seed, branch, step in cells()}

        stage = "paired_primary_neighborhood_bootstrap"
        plan, plan_hash = neighborhood_plan(canonical_ids, canonical_families, BOOTSTRAP_SEED)
        plan_path = OUTPUT / "shared-neighborhood-bootstrap-plan-v01.npy"
        with plan_path.open("xb") as stream:
            np.save(stream, plan, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        saved = np.load(plan_path, mmap_mode="r", allow_pickle=False)
        need(saved.shape == (10_000, 2_000) and saved.dtype == np.int32
             and hashlib.sha256(np.asarray(saved, dtype="<i4").tobytes(order="C")).hexdigest() == plan_hash,
             "Q-R2 shared neighborhood bootstrap plan persistence mismatch")
        plan = np.asarray(saved, dtype=np.int32)
        family_positions = {family: np.flatnonzero(np.asarray(canonical_families) == family) for family in FAMILIES}
        contrasts: dict[str, Any] = {}
        cohort_differences: dict[str, list[float]] = defaultdict(list)
        for metric in METRICS:
            col = METRICS.index(metric)
            for seed in SEEDS:
                for step in (100, 120):
                    half = arrays[(seed, "LATE_SHAM_HALF", step)][:, col]
                    one = arrays[(seed, "LATE_SHAM_1X", step)][:, col]
                    diff = half - one
                    key = f"{seed}/step{step}/{metric}"
                    if step == 120:
                        contrasts[key] = {"overall": boot_summary(diff, plan), "by_family": {}}
                        cohort_differences[metric].append(float(diff.mean()))
                    else:
                        contrasts[key] = {"overall_mean": float(diff.mean()), "by_family": {}}
                    for family in FAMILIES:
                        pos = family_positions[family]
                        if step == 120:
                            contrasts[key]["by_family"][family] = boot_summary(diff, plan, pos)
                        else:
                            contrasts[key]["by_family"][family] = {"mean": float(diff[pos].mean()), "n": 500}
        cohort_summary = {}
        for metric, values in cohort_differences.items():
            vector = np.asarray(values, dtype=np.float64)
            cohort_summary[metric] = {"mean_of_24_seed_effects": float(vector.mean()),
                "median_of_24_seed_effects": float(np.median(vector)),
                "positive_seed_count": int((vector > 0).sum()), "negative_seed_count": int((vector < 0).sum()),
                "zero_seed_count": int((vector == 0).sum()), "range": [float(vector.min()), float(vector.max())],
                "interpretation": "descriptive across these 24 paired seeds; not a population estimate"}

        stage = "preregistered_seed_level_moderator_analysis"
        moderators = moderator_analysis(arrays, canonical_ids, canonical_families, OUTPUT)
        result = {
            "status": "Q_R2_PAIRED_LATE_BRANCH_ANALYSIS_COMPLETE",
            "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
            "estimand": "within-seed step120 HALF minus 1X after an identical SHAM-1.0 prefix to step80",
            "instrument_package": instrument,
            "contract_sha256": CONTRACT_SHA, "run_contract_sha256": RUN_SHA,
            "packet_sha256": PACKET_SHA, "packet_bundle_root_sha256": PACKET_ROOT_SHA,
            "training_seal_sha256": sha(RUN / "training-v01/training-seal-manifest.json"),
            "panel_input_seal_sha256": sha(RUN / "panel-v01/seals/q-r2-panel-input-terminal-seal-v01.json"),
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "predictions_sha256": sha(predictions), "prediction_rows": 960_000, "cell_count": 120,
            "metric_implementation_sha256": METRIC_SHA,
            "metric_names": list(METRICS), "cells": cells_meta,
            "cell_response_summaries": cell_summaries,
            "step120_primary_paired_effects": contrasts,
            "step100_descriptive_paired_effects": {key: value for key, value in contrasts.items() if "/step100/" in key},
            "observed_seed_effect_summary": cohort_summary,
            "shared_neighborhood_bootstrap": {"seed": BOOTSTRAP_SEED, "plan_sha256": plan_hash,
                "plan_file_sha256": sha(plan_path), "shape": [10_000, 2_000], "dtype": "int32",
                "family_order": list(FAMILIES), "draw_order": "family-major fixed order",
                "quantile_method": "linear", "shared_across_branches_checkpoints_coordinates_within_seed": True,
                "interpretation": "intervals condition on each seed and this fixed panel; they do not quantify seed-to-seed variation"},
            "step80_state_moderation": moderators,
            "step80_role": "shared pre-branch baseline; not a treatment arm",
            "step120_primary": True, "step100_descriptive": True,
            "no_composite_score": True, "no_checkpoint_selection": True,
            "seed_population_inference": False, "policy_or_controller_fitting": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        result_path = OUTPUT / "q-r2-analysis-v01.json"
        write_json(result_path, result)
        report_path = OUTPUT / "q-r2-results-v01.md"
        lines = [
            "# JEV v0.8Q-R2: Paired Late-SHAM Weight Branch", "",
            "Primary estimand: within-seed step-120 HALF minus 1X after the same SHAM-1.0 history through step 80.", "",
            f"Panel input root: `{read_json(RUN / 'panel-v01/seals/q-r2-panel-input-terminal-seal-v01.json')['root_sha256']}`  ",
            f"Prediction SHA-256: `{sha(predictions)}`  ",
            "Evaluation matrix: **120 cells / 960,000 prediction rows**. Step 80 is shared; step 100 is descriptive; step 120 is primary.", "",
            "## Step-120 paired effects by seed", "",
            "Positive means the half-weight continuation is larger for that metric. These are 24 separate paired trajectories, not a seed-population law.", "",
            "| Seed | Δ new-probability | Δ direction | Δ F_new | Δ strict | Δ A_old | Δ sham L1 | Δ matched L1 | Δ fact gap | Δ anchor gap |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for seed in SEEDS:
            cell = {name: contrasts[f"{seed}/step120/{name}"]["overall"]["mean"] for name in METRICS}
            lines.append(f"| {seed} | {cell['new_probability_delta']:+.6f} | {cell['correct_direction']:+.4f} | {cell['fact_new_map']:+.4f} | {cell['strict_transition']:+.4f} | {cell['anchor_old_map']:+.4f} | {cell['sham_l1']:+.5f} | {cell['matched_l1']:+.5f} | {cell['fact_new_winner_gap']:+.5f} | {cell['anchor_old_winner_gap']:+.5f} |")
        lines += ["", "## Secondary step-80 moderator relationships", "",
                  "Each slope uses 24 seed-level family means; the paired seed is the observational unit. Intervals are descriptive cluster-bootstrap annotations, not controller validation.", "",
                  "| Family / relationship | Slope per 0.1 gap | 95% paired-seed bootstrap interval | Status |", "|---|---:|---:|---|"]
        for key, record in moderators["relationships"].items():
            interval = record["paired_seed_cluster_bootstrap"]["ci95"]
            interval_text = "not estimable" if interval is None else f"[{interval[0]:+.6f}, {interval[1]:+.6f}]"
            slope = record["ols_slope_per_0.1_moderator"]
            slope_text = "not estimable" if slope is None else f"{slope:+.6f}"
            lines.append(f"| {key} | {slope_text} | {interval_text} | {record['paired_seed_cluster_bootstrap']['status']} |")
        lines += ["", "## Interpretation boundary", "",
                  "This estimates a late-only multiplier effect conditional on the common SHAM-1.0 step-80 history, on fresh worlds from the same four families and fixed templates. It is not a full-course half-weight effect, evidence that step 80 is universally special, novel-family/template generalization, a mechanism claim, or a validated control policy.", ""]
        report_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        with report_path.open("r+b") as stream:
            stream.flush(); os.fsync(stream.fileno())

        moderator_plan_path = OUTPUT / "shared-moderator-seed-resample-plan-v01.npy"
        output_files = (metric_path_out, plan_path, moderator_plan_path, result_path, report_path)
        entries = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in output_files]
        payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda row: row["path"]))
        output_root = hashlib.sha256(payload.encode()).hexdigest()
        analysis_seal = {"status": "Q_R2_ANALYSIS_OUTPUTS_SEALED", "analysis_root_sha256": output_root,
            "outputs": entries, "output_count": len(entries),
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "inference_receipt_sha256": sha(OUTPUT / "inference-receipt-v01.json"),
            "analysis_contract_sha256": CONTRACT_SHA, "metric_implementation_sha256": METRIC_SHA,
            "analysis_implementation_sha256": sha(Path(__file__).resolve()),
            "instrument_package_seal_sha256": instrument["seal_sha256"], "panel_open_count": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat()}
        seal_path = OUTPUT / "q-r2-analysis-seal-v01.json"
        write_json(seal_path, analysis_seal)
        print(json.dumps({"status": analysis_seal["status"], "analysis_root_sha256": output_root,
                          "analysis_seal_sha256": sha(seal_path), "observed_seed_count": len(SEEDS)}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        failure = OUTPUT / "analysis-failure-receipt-v01.json"
        if OUTPUT.exists() and not failure.exists():
            write_json(failure, {"status": "Q_R2_ANALYSIS_FAILED_CLOSED_PARTIAL_OUTPUTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "automatic_retry": False, "failed_at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
