"""Frozen Q-R1 response-matrix, boundary-geometry, and landmark analysis."""

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
Q = ROOT / "experiments/jev-information-density-v08q"
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
OUTPUT = RUN / "evaluation-v01"
PACKET = R1 / "seals/q-r1-packet-seal-and-authorization-v01.json"
ANALYSIS_CONTRACT = R1 / "contracts/q-r1-analysis-contract-v01.json"
TRAIN_CONTRACT = R1 / "contracts/q-r1-run-contract-v01.json"
SEEDS = (77720160, 4245719435, 3815947415, 3112928194, 4241626823, 534474641,
         3124582801, 4247677041, 811956520, 3972258, 950790373, 949206414)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
STEPS = (40, 80, 100, 120)
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
CONTRACT_SHA = "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b"
TRAIN_SHA = "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317"
PACKET_ROOT_SHA = "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0"
PANEL_ROOT_SHA = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
METRIC_SHA = "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"
GATE_SHA = "4ba7a48438a35f00154e5eefcc76906122080944ff32575a4a26a5b1d29f91b3"
BOOTSTRAP_SEED = 3344893480
BASE_METRICS = (
    "correct_direction", "new_probability_delta", "exact_new_probability_delta", "delta_mae",
    "new_rank_gain", "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy",
    "strict_transition", "anchor_old_map", "fact_new_map", "sham_l1", "sham_map_flip",
    "sham_gold_probability_movement", "sham_new_probability_movement", "sham_margin_movement",
    "sham_exact_gold_l1", "matched_l1", "matched_map_flip", "matched_gold_probability_movement",
    "matched_new_probability_movement", "matched_margin_movement", "matched_exact_gold_l1",
)
GEOMETRY_METRICS = (
    "anchor_old_new_margin", "fact_old_new_margin", "fact_conditioned_pairwise_margin_movement",
    "old_candidate_probability_movement", "anchor_old_winner_gap", "fact_new_winner_gap",
)
NUMERIC_METRICS = BASE_METRICS + GEOMETRY_METRICS
STATE80 = (
    "anchor_old_new_margin", "fact_old_new_margin", "fact_new_winner_gap", "anchor_old_winner_gap",
    "new_probability_delta", "sham_l1", "matched_l1",
)
STEP120_OUTCOMES = (
    "fact_new_map", "strict_transition", "anchor_old_map", "new_probability_delta",
    "fact_conditioned_pairwise_margin_movement", "fact_new_winner_gap", "anchor_old_winner_gap",
    "sham_l1", "matched_l1",
)
PAIR_BOOTSTRAP = (
    "new_probability_delta", "correct_direction", "fact_new_map", "strict_transition", "anchor_old_map",
    "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip",
    "fact_conditioned_pairwise_margin_movement", "fact_new_winner_gap", "anchor_old_winner_gap",
)
LOCALITY_BOOTSTRAP = ("sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    with temp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def expected_cells() -> list[tuple[int, str, int]]:
    cells: list[tuple[int, str, int]] = []
    for seed in SEEDS:
        cells.append((seed, "COMMON_INIT", 0))
        for step in STEPS:
            cells.extend((seed, arm, step) for arm in ARMS)
    return cells


def actual_argmax(probabilities: list[float], candidate_ids: list[str]) -> int:
    # Match the frozen metric's winner rule: probability first, then lexical ID.
    return max(range(len(probabilities)), key=lambda index: (probabilities[index], candidate_ids[index]))


def strongest_other(probabilities: list[float], target_index: int, candidate_ids: list[str]) -> str:
    eligible = [index for index in range(len(probabilities)) if index != target_index]
    index = max(eligible, key=lambda item: (probabilities[item], -item))
    return candidate_ids[index]


def enrich_metrics(views: dict[str, dict[str, Any]], frozen_metric: Any) -> tuple[dict[str, float], dict[str, str]]:
    base = frozen_metric.neighborhood_metrics(views)
    anchor, fact = views["anchor"], views["fact_flip"]
    ids = [str(value) for value in anchor["candidate_semantic_ids"]]
    need(len(ids) == 4 and all([str(value) for value in row["candidate_semantic_ids"]] == ids for row in views.values()),
         "candidate order changed within neighborhood views")
    old_id, new_id = str(anchor["old_candidate_id"]), str(anchor["new_candidate_id"])
    index = {candidate_id: position for position, candidate_id in enumerate(ids)}
    need(old_id in index and new_id in index and old_id != new_id, "invalid old/new candidate identity")
    pa = [float(value) for value in anchor["prediction"]]
    pf = [float(value) for value in fact["prediction"]]
    old_i, new_i = index[old_id], index[new_id]
    anchor_margin = pa[new_i] - pa[old_i]
    fact_margin = pf[new_i] - pf[old_i]
    anchor_competitor = strongest_other(pa, old_i, ids)
    fact_competitor = strongest_other(pf, new_i, ids)
    numeric = {key: float(base[key]) for key in BASE_METRICS}
    numeric.update({
        "anchor_old_new_margin": anchor_margin,
        "fact_old_new_margin": fact_margin,
        "fact_conditioned_pairwise_margin_movement": fact_margin - anchor_margin,
        "old_candidate_probability_movement": pf[old_i] - pa[old_i],
        "anchor_old_winner_gap": pa[old_i] - max(pa[j] for j in range(4) if j != old_i),
        "fact_new_winner_gap": pf[new_i] - max(pf[j] for j in range(4) if j != new_i),
    })
    categorical = {
        "anchor_old_winner_gap_strongest_competitor_id": anchor_competitor,
        "fact_new_winner_gap_strongest_competitor_id": fact_competitor,
        "anchor_frozen_argmax_candidate_id": ids[actual_argmax(pa, ids)],
        "fact_frozen_argmax_candidate_id": ids[actual_argmax(pf, ids)],
        "old_candidate_id": old_id,
        "new_candidate_id": new_id,
    }
    return numeric, categorical


def read_cell(stream: Any, cell: tuple[int, str, int], frozen_metric: Any,
              metrics_dest: Any) -> tuple[list[str], list[str], np.ndarray]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    family_by_id: dict[str, str] = {}
    seed, arm, step = cell
    for _ in range(8_000):
        line = stream.readline()
        need(bool(line), f"prediction table ended inside cell {cell}")
        row = json.loads(line)
        need((int(row["seed"]), str(row["arm"]), int(row["global_step"])) == cell,
             f"prediction cell order mismatch at {cell}")
        neighborhood_id, view = str(row["neighborhood_id"]), str(row["view"])
        need(view in {"anchor", "fact_flip", "sham", "matched_neutral"} and view not in grouped[neighborhood_id],
             f"invalid or duplicate view {neighborhood_id}/{view}")
        prediction = [float(value) for value in row["prediction"]]
        gold = [float(value) for value in row["gold"]]
        need(len(prediction) == len(gold) == 4 and all(np.isfinite(prediction)) and all(np.isfinite(gold))
             and abs(sum(prediction) - 1.0) <= 1e-6 and abs(sum(gold) - 1.0) <= 1e-12,
             f"probability/target row invalid {neighborhood_id}/{view}")
        grouped[neighborhood_id][view] = row
        family_by_id[neighborhood_id] = str(row["family_id"]).split(":")[-1]
    need(len(grouped) == 2_000 and all(set(views) == {"anchor", "fact_flip", "sham", "matched_neutral"}
                                       for views in grouped.values()), f"incomplete four-view panel cell {cell}")
    ids = sorted(grouped)
    families = [family_by_id[neighborhood_id] for neighborhood_id in ids]
    need(set(families) == set(FAMILIES), f"family set mismatch in {cell}")
    values = np.empty((2_000, len(NUMERIC_METRICS)), dtype=np.float64)
    for index, neighborhood_id in enumerate(ids):
        view_rows = grouped[neighborhood_id]
        numeric, categorical = enrich_metrics(view_rows, frozen_metric)
        need(str(view_rows["anchor"]["family_id"]).split(":")[-1] == families[index],
             f"family identity mismatch {neighborhood_id}")
        values[index, :] = [numeric[key] for key in NUMERIC_METRICS]
        output_row = {"seed": seed, "arm": arm, "step": step, "neighborhood_id": neighborhood_id,
                      "family": families[index], **numeric, **categorical}
        metrics_dest.write(json.dumps(output_row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return ids, families, values


def make_shared_plan(ids: list[str], families: list[str], rng_seed: int) -> tuple[np.ndarray, list[str], np.ndarray, str]:
    positions = {family: [] for family in FAMILIES}
    for index, (neighborhood_id, family) in enumerate(zip(ids, families, strict=True)):
        need(family in positions, f"unexpected family {family}")
        positions[family].append((neighborhood_id, index))
    ordered_positions: list[int] = []
    ordered_ids: list[str] = []
    for family in FAMILIES:
        block = sorted(positions[family])
        need(len(block) == 500, f"family support mismatch for {family}")
        ordered_ids.extend(neighborhood_id for neighborhood_id, _ in block)
        ordered_positions.extend(index for _, index in block)
    ordered = np.asarray(ordered_positions, dtype=np.int32)
    rng = np.random.Generator(np.random.PCG64(rng_seed))
    plan = np.empty((10_000, 2_000), dtype=np.int32)
    offset = 0
    for family in FAMILIES:
        members = np.arange(offset, offset + 500, dtype=np.int32)
        local = rng.integers(0, 500, size=(10_000, 500), dtype=np.int32)
        plan[:, offset:offset + 500] = members[local]
        offset += 500
    digest = hashlib.sha256(np.asarray(plan, dtype="<i4").tobytes(order="C")).hexdigest()
    return plan, ordered_ids, ordered, digest


def paired_bootstrap(values: np.ndarray, plan: np.ndarray) -> dict[str, Any]:
    samples = values[plan].mean(axis=1)
    interval = [float(value) for value in np.quantile(samples, [0.025, 0.975], method="linear")]
    return {"mean": float(values.mean()), "ci95": interval,
            "paired_interval_excludes_zero": interval[0] > 0.0 or interval[1] < 0.0,
            "annotation_only": True, "replicates": 10_000}


def summarize_cell(values: np.ndarray, ids: list[str], families: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"n": len(ids), "overall": {}, "by_family": {}, "four_cell_A_F": {}}
    for j, key in enumerate(NUMERIC_METRICS):
        result["overall"][key] = float(values[:, j].mean())
    for family in FAMILIES:
        rows = np.asarray([i for i, value in enumerate(families) if value == family], dtype=np.int32)
        need(len(rows) == 500, f"family metric row count mismatch: {family}")
        result["by_family"][family] = {key: float(values[rows, j].mean()) for j, key in enumerate(NUMERIC_METRICS)}
    a = values[:, NUMERIC_METRICS.index("anchor_old_map")] >= 0.5
    f = values[:, NUMERIC_METRICS.index("fact_new_map")] >= 0.5
    names = {(True, True): "A_old_AND_F_new", (True, False): "A_old_AND_NOT_F_new",
             (False, True): "NOT_A_old_AND_F_new", (False, False): "NOT_A_old_AND_NOT_F_new"}
    for pair, label in names.items():
        mask = (a == pair[0]) & (f == pair[1])
        result["four_cell_A_F"][label] = {"count": int(mask.sum()), "rate": float(mask.mean())}
    return result


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def spearman_rank(left: np.ndarray, right: np.ndarray) -> float | None:
    left_rank, right_rank = average_ranks(left), average_ranks(right)
    if np.ptp(left_rank) == 0.0 or np.ptp(right_rank) == 0.0:
        return None
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def finite_mean(values: np.ndarray, positions: list[int]) -> float | None:
    if not positions:
        return None
    result = float(values[np.asarray(positions, dtype=np.int32)].mean())
    return result if np.isfinite(result) else None


def landmark_analysis(cell_arrays: dict[tuple[int, str, int], np.ndarray], ids: list[str],
                      families: list[str]) -> dict[str, Any]:
    metric_index = {key: index for index, key in enumerate(NUMERIC_METRICS)}
    family_positions = {family: [i for i, item in enumerate(families) if item == family] for family in FAMILIES}
    output: dict[str, Any] = {"purpose": "descriptive step-80 landmark after treatment exposure; not causal mediation",
                              "continuous_strata": {}, "binary_cross_tabs": {}, "spearman_rank_associations": {}}
    binary_states = {"A_old": "anchor_old_map", "F_new": "fact_new_map"}
    for seed in SEEDS:
        for arm in ARMS:
            state = cell_arrays[(seed, arm, 80)]
            final = cell_arrays[(seed, arm, 120)]
            for family in FAMILIES:
                positions = family_positions[family]
                need(len(positions) == 500, f"step-80 family support mismatch {family}")
                prefix = f"{seed}/{arm}/{family}"
                for variable in STATE80:
                    column = state[:, metric_index[variable]]
                    ordered = sorted(positions, key=lambda pos: (float(column[pos]), ids[pos]))
                    quartiles = []
                    for q in range(4):
                        chunk = ordered[q * 125:(q + 1) * 125]
                        quartiles.append({
                            "quartile": q + 1, "n": len(chunk),
                            "step80_min": float(column[chunk[0]]), "step80_max": float(column[chunk[-1]]),
                            "step120_outcomes": {outcome: finite_mean(final[:, metric_index[outcome]], chunk)
                                                 for outcome in STEP120_OUTCOMES},
                        })
                    output["continuous_strata"][f"{prefix}/{variable}"] = quartiles
                for state_name, metric_name in binary_states.items():
                    column = state[:, metric_index[metric_name]] >= 0.5
                    table = {}
                    for value in (False, True):
                        selected = [pos for pos in positions if bool(column[pos]) is value]
                        table[str(value).lower()] = {"n": len(selected), "step120_outcomes": {
                            outcome: finite_mean(final[:, metric_index[outcome]], selected)
                            for outcome in STEP120_OUTCOMES}}
                    output["binary_cross_tabs"][f"{prefix}/{state_name}"] = table
                a_col = state[:, metric_index["anchor_old_map"]] >= 0.5
                f_col = state[:, metric_index["fact_new_map"]] >= 0.5
                joint = {}
                for a_value, f_value, label in ((True, True, "A_old_AND_F_new"),
                                                (True, False, "A_old_AND_NOT_F_new"),
                                                (False, True, "NOT_A_old_AND_F_new"),
                                                (False, False, "NOT_A_old_AND_NOT_F_new")):
                    selected = [pos for pos in positions if bool(a_col[pos]) is a_value and bool(f_col[pos]) is f_value]
                    joint[label] = {"n": len(selected), "step120_outcomes": {
                        outcome: finite_mean(final[:, metric_index[outcome]], selected)
                        for outcome in STEP120_OUTCOMES}}
                output["binary_cross_tabs"][f"{prefix}/A_F_joint"] = joint
                associations = {}
                for variable in STATE80:
                    left = state[positions, metric_index[variable]]
                    for outcome in STEP120_OUTCOMES:
                        right = final[positions, metric_index[outcome]]
                        associations[f"{variable}__vs__{outcome}"] = spearman_rank(left, right)
                output["spearman_rank_associations"][prefix] = associations
    return output


def main() -> int:
    stage = "analysis_preflight"
    try:
        instrument_verifier = load_module(R1 / "source/verify_q_r1_instrument_package_v01.py",
                                          "q_r1_instrument_verifier_analysis")
        instrument_receipt = instrument_verifier.verify()
        need(sha(ANALYSIS_CONTRACT) == CONTRACT_SHA and sha(TRAIN_CONTRACT) == TRAIN_SHA,
             "R1 analysis/run contract hash mismatch")
        packet = read_json(PACKET)
        need(packet.get("contract_bundle_root_sha256") == PACKET_ROOT_SHA
             and packet.get("status") == "SEALED_AUTHORIZED_PENDING_EXECUTION", "R1 packet binding mismatch")
        for row in packet["contracts"]:
            source = R1 / row["path"]
            need(source.is_file() and sha(source) == row["sha256"], f"R1 contract changed: {row['path']}")
        inference = read_json(OUTPUT / "inference-receipt-v01.json")
        tree = read_json(OUTPUT / "raw-prediction-hash-tree-v01.json")
        prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
        need(inference.get("status") == "Q_R1_ALL_204_CELLS_INFERRED_AND_SEALED"
             and inference.get("prediction_sha256") == sha(prediction_path)
             and tree.get("raw_predictions", {}).get("sha256") == sha(prediction_path)
             and tree.get("prediction_rows") == 1_632_000 and tree.get("cell_count") == 204,
             "R1 complete raw-prediction seal invalid")
        need(tree.get("panel_open_count") == 1 and tree.get("predictions_before_analysis") is True
             and tree.get("panel_root_sha256") == PANEL_ROOT_SHA,
             "R1 prediction matrix panel/analysis ordering mismatch")
        metric_path = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
        gate_path = Q / "source/q_analysis_rules_v02.py"
        need(sha(metric_path) == METRIC_SHA and sha(gate_path) == GATE_SHA,
             "frozen Q metrics or seed-gate implementation changed")
        frozen_metric = load_module(metric_path, "q_r1_frozen_neighborhood_metrics")
        gate_rules = load_module(gate_path, "q_r1_unchanged_q_seed_rules")
        metric_file = OUTPUT / "neighborhood-metrics-v01.jsonl"
        arrays: dict[tuple[int, str, int], np.ndarray] = {}
        canonical_ids: list[str] | None = None
        canonical_families: list[str] | None = None
        cells_meta = []
        stage = "stream_metrics_and_shared_plan"
        with prediction_path.open("r", encoding="utf-8") as source, metric_file.open("x", encoding="utf-8", newline="\n") as destination:
            for cell in expected_cells():
                ids, families, values = read_cell(source, cell, frozen_metric, destination)
                if canonical_ids is None:
                    canonical_ids, canonical_families = ids, families
                else:
                    need(ids == canonical_ids and families == canonical_families,
                         f"R1 paired panel identity/order mismatch in {cell}")
                arrays[cell] = values
                cells_meta.append({"seed": cell[0], "arm": cell[1], "step": cell[2], "neighborhoods": len(ids)})
            need(not source.readline(), "extra raw prediction rows after R1 matrix")
            destination.flush()
            os.fsync(destination.fileno())
        need(canonical_ids is not None and canonical_families is not None and len(arrays) == 204,
             "R1 streamed metric cell matrix incomplete")
        summaries = {f"{seed}/{arm}/{step}": summarize_cell(arrays[(seed, arm, step)], canonical_ids, canonical_families)
                     for seed, arm, step in expected_cells()}
        plan, ordered_ids, order_positions, plan_hash = make_shared_plan(canonical_ids, canonical_families, BOOTSTRAP_SEED)
        plan_path = OUTPUT / "shared-bootstrap-resample-plan-v01.npy"
        with plan_path.open("xb") as stream:
            np.save(stream, plan, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        saved_plan = np.load(plan_path, mmap_mode="r", allow_pickle=False)
        need(saved_plan.shape == (10_000, 2_000) and saved_plan.dtype == np.int32
             and hashlib.sha256(np.asarray(saved_plan, dtype="<i4").tobytes(order="C")).hexdigest() == plan_hash,
             "R1 shared bootstrap plan persistence mismatch")
        plan = np.asarray(saved_plan, dtype=np.int32)
        contrast_results: dict[str, Any] = {}
        for seed in SEEDS:
            contrasts = (("B-SHAM-LOW", "B-SHAM", PAIR_BOOTSTRAP),
                         ("B-SHAM-LOW", "B-DUP", LOCALITY_BOOTSTRAP))
            for left_arm, right_arm, metric_names in contrasts:
                left = arrays[(seed, left_arm, 120)]
                right = arrays[(seed, right_arm, 120)]
                for name in metric_names:
                    column = NUMERIC_METRICS.index(name)
                    difference = (left[order_positions, column] - right[order_positions, column]).astype(np.float64)
                    contrast_results[f"{seed}/{left_arm}_minus_{right_arm}/{name}"] = paired_bootstrap(difference, plan)
        labels_by_seed: dict[str, Any] = {}
        for seed in SEEDS:
            def mean(arm: str, name: str) -> float:
                return summaries[f"{seed}/{arm}/120"]["overall"][name]
            low_family = summaries[f"{seed}/B-SHAM-LOW/120"]["by_family"]
            sham_family = summaries[f"{seed}/B-SHAM/120"]["by_family"]
            gate_input = {
                "delta_p_new_low_minus_sham": mean("B-SHAM-LOW", "new_probability_delta") - mean("B-SHAM", "new_probability_delta"),
                "sham_low_correct_direction": mean("B-SHAM-LOW", "correct_direction"),
                "sham_correct_direction": mean("B-SHAM", "correct_direction"),
                "a_old_low_minus_sham": mean("B-SHAM-LOW", "anchor_old_map") - mean("B-SHAM", "anchor_old_map"),
                "family_a_old_low_minus_sham": {family: low_family[family]["anchor_old_map"] - sham_family[family]["anchor_old_map"] for family in FAMILIES},
                "dup_sham_l1": mean("B-DUP", "sham_l1"), "dup_matched_neutral_l1": mean("B-DUP", "matched_l1"),
                "sham_low_sham_l1": mean("B-SHAM-LOW", "sham_l1"), "sham_low_matched_neutral_l1": mean("B-SHAM-LOW", "matched_l1"),
                "dup_sham_map_flip_rate": mean("B-DUP", "sham_map_flip"),
                "dup_matched_neutral_map_flip_rate": mean("B-DUP", "matched_map_flip"),
                "sham_low_sham_map_flip_rate": mean("B-SHAM-LOW", "sham_map_flip"),
                "sham_low_matched_neutral_map_flip_rate": mean("B-SHAM-LOW", "matched_map_flip"),
                "f_new_low_minus_sham": mean("B-SHAM-LOW", "fact_new_map") - mean("B-SHAM", "fact_new_map"),
                "strict_low_minus_sham": mean("B-SHAM-LOW", "strict_transition") - mean("B-SHAM", "strict_transition"),
            }
            labels_by_seed[str(seed)] = {"inputs": gate_input, "labels": gate_rules.seed_gate_record(gate_input)}
        cohort_counts = {name: sum(bool(record["labels"][key]) for record in labels_by_seed.values())
                         for name, key in (("tunable_gain_locality_operating_point", "q_operating_point_seed_pass"),
                                            ("stiff_coupling_pattern", "q_stiff_coupling_seed"),
                                            ("meaningful_map_response", "q_map_response_seed_pass"))}
        cohort = {"seed_count": 12, "observed_counts_out_of_12": cohort_counts,
                  "two_thirds_threshold_count": 8,
                  "labels": {name: count >= 8 for name, count in cohort_counts.items()},
                  "interpretation": "descriptive recurrence among 12 observed paired trajectories; not a population law"}
        stage = "step80_landmark_analysis"
        landmark = landmark_analysis(arrays, canonical_ids, canonical_families)
        initialization = {str(seed): summaries[f"{seed}/COMMON_INIT/0"] for seed in SEEDS}
        result = {
            "status": "Q_R1_FIXED_DOSE_RESPONSE_PHENOTYPE_ANALYSIS_COMPLETE",
            "identity": "JEV-V08Q-R1-RESPONSE-PHENOTYPE-REPLICATION",
            "instrument_package": instrument_receipt,
            "packet_bundle_root_sha256": PACKET_ROOT_SHA,
            "analysis_contract_sha256": CONTRACT_SHA, "run_contract_sha256": TRAIN_SHA,
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "prediction_sha256": sha(prediction_path), "prediction_rows": 1_632_000,
            "cell_count": 204, "neighborhood_metric_rows": 408_000, "cells": cells_meta,
            "numeric_metric_names": list(NUMERIC_METRICS), "response_summaries": summaries,
            "step120_paired_bootstrap_contrasts": contrast_results,
            "shared_bootstrap": {"seed": BOOTSTRAP_SEED, "plan_sha256": plan_hash,
                                 "plan_file_sha256": sha(plan_path), "shape": [10_000, 2_000],
                                 "dtype": "int32", "family_order": list(FAMILIES), "draw_order": "family-major",
                                 "rng": "NumPy PCG64", "quantile_method": "linear",
                                 "interval": "paired neighborhood 95% interval conditional on seed and fixed R1 panel",
                                 "paired_interval_excludes_zero_is_annotation_only": True},
            "same_seed_step120_q_labels": labels_by_seed, "cohort_q_labels": cohort,
            "step80_landmark": landmark, "shared_initialization_descriptive_context": initialization,
            "step120_primary": True, "checkpoint_selection": False,
            "optimizer_seed_population_inference": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        result_path = OUTPUT / "q-r1-analysis-v01.json"
        write_json(result_path, result)
        report_path = OUTPUT / "q-r1-results-v01.md"
        lines = [
            "# JEV v0.8Q-R1: Fixed-Dose Response-Phenotype Replication", "",
            "Fresh-world replication under the same four families and fixed generator/template semantics; this is not novel-family or novel-template generalization.", "",
            f"Panel root: `{PANEL_ROOT_SHA}`  ",
            f"Raw prediction SHA-256: `{sha(prediction_path)}`  ",
            "Cells/rows: **204 / 1,632,000**. The 12 shared initialization states are reported separately from the 192 trained checkpoints.", "",
            "## Step 120: all observed paired trajectories", "",
            "| Seed | Arm | Δp new | Direction | F_new | Strict | A_old | Sham L1 | Matched L1 | Sham flips | Matched flips | Anchor gap | Fact gap |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for seed in SEEDS:
            for arm in ARMS:
                metrics = summaries[f"{seed}/{arm}/120"]["overall"]
                lines.append(f"| {seed} | {arm} | {metrics['new_probability_delta']:.6f} | {metrics['correct_direction']:.4f} | {metrics['fact_new_map']:.4f} | {metrics['strict_transition']:.4f} | {metrics['anchor_old_map']:.4f} | {metrics['sham_l1']:.5f} | {metrics['matched_l1']:.5f} | {metrics['sham_map_flip']:.4f} | {metrics['matched_map_flip']:.4f} | {metrics['anchor_old_winner_gap']:.5f} | {metrics['fact_new_winner_gap']:.5f} |")
        lines += ["", "## Registered Q same-seed predicates", "",
                  "| Seed | Gain | Direction | Locality vs DUP | Preservation | Operating point | Stiff coupling | MAP response | Δp LOW−SHAM | ΔF_new | ΔStrict |", "|---:|---|---|---|---|---|---|---|---:|---:|---:|"]
        for seed in SEEDS:
            record = labels_by_seed[str(seed)]
            label = record["labels"]
            values = record["inputs"]
            lines.append(f"| {seed} | {label['gain_pass']} | {label['direction_pass']} | {label['material_locality_advantage_over_dup_pass']} | {label['preservation_pass']} | {label['q_operating_point_seed_pass']} | {label['q_stiff_coupling_seed']} | {label['q_map_response_seed_pass']} | {values['delta_p_new_low_minus_sham']:.6f} | {values['f_new_low_minus_sham']:.4f} | {values['strict_low_minus_sham']:.4f} |")
        lines += ["", f"Cohort rule: unchanged same-seed labels; two-thirds threshold is **8/12**. Observed counts: `{json.dumps(cohort_counts, sort_keys=True)}`. These are recurrence counts among the 12 observed trajectories, not a seed-population estimate.", "",
                  "## Family-conditioned preservation and crossing", "",
                  "Values below are step-120 rates for SHAM versus SHAM-LOW. The complete arm × seed × checkpoint × family scorecard is in the sealed JSON output.", "",
                  "| Seed | Family | SHAM F_new | LOW F_new | SHAM A_old | LOW A_old | LOW fact gap |", "|---:|---|---:|---:|---:|---:|---:|"]
        for seed in SEEDS:
            for family in FAMILIES:
                sham = summaries[f"{seed}/B-SHAM/120"]["by_family"][family]
                low = summaries[f"{seed}/B-SHAM-LOW/120"]["by_family"][family]
                lines.append(f"| {seed} | {family} | {sham['fact_new_map']:.4f} | {low['fact_new_map']:.4f} | {sham['anchor_old_map']:.4f} | {low['anchor_old_map']:.4f} | {low['fact_new_winner_gap']:.5f} |")
        lines += ["", "## Interpretation limits", "",
                  "Q-R1 repeats the fixed 0.5 auxiliary intervention on fresh neighborhood/world draws under the same four families and fixed templates. Step-80 measures are a post-exposure landmark, not a pre-treatment state; their association with step-120 outcomes is descriptive and not causal mediation. Bootstrap intervals condition on each seed and this fixed panel. No composite score, checkpoint selection, or universal seed-population claim is made.", ""]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        with report_path.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        outputs = (metric_file, plan_path, result_path, report_path)
        entries = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in outputs]
        root = hashlib.sha256("".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                                       for row in sorted(entries, key=lambda item: item["path"])).encode()).hexdigest()
        analysis_seal = {
            "status": "Q_R1_ANALYSIS_OUTPUTS_SEALED", "analysis_root_sha256": root,
            "output_count": len(entries), "outputs": entries,
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "inference_receipt_sha256": sha(OUTPUT / "inference-receipt-v01.json"),
            "analysis_contract_sha256": CONTRACT_SHA, "metric_implementation_sha256": METRIC_SHA,
            "seed_gate_implementation_sha256": GATE_SHA,
            "analysis_implementation_sha256": sha(Path(__file__).resolve()),
            "instrument_package_seal_sha256": instrument_receipt["seal_sha256"],
            "panel_open_count": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(OUTPUT / "q-r1-analysis-seal-v01.json", analysis_seal)
        print(json.dumps({"status": analysis_seal["status"], "analysis_root_sha256": root,
                          "analysis_seal_sha256": sha(OUTPUT / "q-r1-analysis-seal-v01.json"),
                          "cohort_q_labels": cohort}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        failure = OUTPUT / "analysis-failure-receipt-v01.json"
        if OUTPUT.exists() and not failure.exists():
            write_json(failure, {"status": "Q_R1_ANALYSIS_FAILED_CLOSED_PARTIAL_OUTPUTS_PRESERVED",
                                 "stage": stage, "exception_type": type(exc).__name__,
                                 "exception": str(exc), "automatic_retry": False,
                                 "failed_at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
