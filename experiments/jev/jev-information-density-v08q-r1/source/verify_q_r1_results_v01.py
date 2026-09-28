"""Independent, prediction-only replay and integrity audit for Q-R1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
TRAIN = RUN / "training"
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
OUT = RUN / "evaluation-v01"
SEEDS = (77720160, 4245719435, 3815947415, 3112928194, 4241626823, 534474641,
         3124582801, 4247677041, 811956520, 3972258, 950790373, 949206414)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
STEPS = (40, 80, 100, 120)
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
PACKET_SHA = "80090a8011455395134f5ba8e0ef2a4eef33d4a78ccc795a137b9d7dc0bed7a4"
PACKET_ROOT = "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0"
RUN_SHA = "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317"
ANALYSIS_SHA = "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b"
PANEL_ROOT = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
BOOTSTRAP_SEED = 3344893480
NUMERIC = (
    "correct_direction", "new_probability_delta", "exact_new_probability_delta", "delta_mae",
    "new_rank_gain", "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy",
    "strict_transition", "anchor_old_map", "fact_new_map", "sham_l1", "sham_map_flip",
    "sham_gold_probability_movement", "sham_new_probability_movement", "sham_margin_movement",
    "sham_exact_gold_l1", "matched_l1", "matched_map_flip", "matched_gold_probability_movement",
    "matched_new_probability_movement", "matched_margin_movement", "matched_exact_gold_l1",
    "anchor_old_new_margin", "fact_old_new_margin", "fact_conditioned_pairwise_margin_movement",
    "old_candidate_probability_movement", "anchor_old_winner_gap", "fact_new_winner_gap",
)
PAIR_BOOTSTRAP = (
    "new_probability_delta", "correct_direction", "fact_new_map", "strict_transition", "anchor_old_map",
    "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip",
    "fact_conditioned_pairwise_margin_movement", "fact_new_winner_gap", "anchor_old_winner_gap",
)
LOCALITY_BOOTSTRAP = ("sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip")


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def per_seed_schedule_hashes() -> dict[int, str]:
    collected: dict[int, list[bytes]] = {seed: [] for seed in SEEDS}
    with (RUN / "schedule/fixed-schedule.jsonl").open("rb") as stream:
        for raw in stream:
            if raw.strip():
                seed = int(json.loads(raw)["seed"])
                need(seed in collected, f"unexpected schedule seed: {seed}")
                collected[seed].append(raw)
    return {seed: hashlib.sha256(b"".join(lines)).hexdigest() for seed, lines in collected.items()}


def root_digest(rows: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                   for row in sorted(rows, key=lambda item: item["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def winner(values: dict[str, float]) -> str:
    return max(values, key=lambda key: (values[key], key))


def rank(values: dict[str, float], wanted: str) -> int:
    return sorted(values, key=lambda key: (-values[key], key)).index(wanted) + 1


def close(left: float, right: float, tolerance: float = 2e-11) -> bool:
    return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def verify_instrument_package() -> dict[str, Any]:
    path = R1 / "source/verify_q_r1_instrument_package_v01.py"
    spec = importlib.util.spec_from_file_location("q_r1_instrument_verifier_result", path)
    need(spec is not None and spec.loader is not None, "cannot load pre-run instrument verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify()


def row_metrics(views: dict[str, dict[str, Any]]) -> tuple[dict[str, float], dict[str, str]]:
    anchor, fact = views["anchor"], views["fact_flip"]
    ids = [str(value) for value in anchor["candidate_semantic_ids"]]
    need(len(ids) == 4 and len(set(ids)) == 4, "invalid candidate IDs in prediction replay")
    for row in views.values():
        need([str(value) for value in row["candidate_semantic_ids"]] == ids, "candidate order changed across views")
    old, new = str(anchor["old_candidate_id"]), str(anchor["new_candidate_id"])
    need(old in ids and new in ids and old != new, "old/new candidate binding invalid")
    need(all(str(row["old_candidate_id"]) == old and str(row["new_candidate_id"]) == new
             for row in views.values()), "old/new candidate IDs changed between views")
    p = {view: dict(zip(ids, map(float, views[view]["prediction"]), strict=True)) for view in VIEWS}
    g = {view: dict(zip(ids, map(float, views[view]["gold"]), strict=True)) for view in VIEWS}
    for view in VIEWS:
        need(set(p[view]) == set(g[view]), "prediction/gold candidate sets differ")
        need(abs(sum(p[view].values()) - 1.0) <= 1e-6 and abs(sum(g[view].values()) - 1.0) <= 1e-12,
             "probability or target normalization failure")
    wa, wf = winner(p["anchor"]), winner(p["fact_flip"])
    model_delta = p["fact_flip"][new] - p["anchor"][new]
    exact_delta = g["fact_flip"][new] - g["anchor"][new]
    direction = float(model_delta * exact_delta > 0.0 if abs(exact_delta) > 1e-12 else abs(model_delta) <= 1e-12)
    values: dict[str, float] = {
        "correct_direction": direction,
        "new_probability_delta": model_delta,
        "exact_new_probability_delta": exact_delta,
        "delta_mae": abs(model_delta - exact_delta),
        "new_rank_gain": float(rank(p["anchor"], new) - rank(p["fact_flip"], new)),
        "anchor_nll": -sum(g["anchor"][key] * math.log(max(p["anchor"][key], 1e-30)) for key in ids),
        "anchor_brier": sum((p["anchor"][key] - g["anchor"][key]) ** 2 for key in ids),
        "anchor_gold_map_accuracy": float(wa == winner(g["anchor"])),
        "strict_transition": float(wa == old and wf == new),
        "anchor_old_map": float(wa == old),
        "fact_new_map": float(wf == new),
        "anchor_old_new_margin": p["anchor"][new] - p["anchor"][old],
        "fact_old_new_margin": p["fact_flip"][new] - p["fact_flip"][old],
        "fact_conditioned_pairwise_margin_movement": (p["fact_flip"][new] - p["fact_flip"][old]) - (p["anchor"][new] - p["anchor"][old]),
        "old_candidate_probability_movement": p["fact_flip"][old] - p["anchor"][old],
        "anchor_old_winner_gap": p["anchor"][old] - max(p["anchor"][key] for key in ids if key != old),
        "fact_new_winner_gap": p["fact_flip"][new] - max(p["fact_flip"][key] for key in ids if key != new),
    }
    for view, prefix in (("sham", "sham"), ("matched_neutral", "matched")):
        values[f"{prefix}_l1"] = sum(abs(p["anchor"][key] - p[view][key]) for key in ids)
        values[f"{prefix}_map_flip"] = float(winner(p["anchor"]) != winner(p[view]))
        values[f"{prefix}_gold_probability_movement"] = p[view][old] - p["anchor"][old]
        values[f"{prefix}_new_probability_movement"] = p[view][new] - p["anchor"][new]
        values[f"{prefix}_margin_movement"] = (p[view][new] - p[view][old]) - (p["anchor"][new] - p["anchor"][old])
        values[f"{prefix}_exact_gold_l1"] = sum(abs(g["anchor"][key] - g[view][key]) for key in ids)
    candidate_order = {key: index for index, key in enumerate(ids)}
    categorical = {
        "anchor_old_winner_gap_strongest_competitor_id": min(
            (key for key in ids if key != old), key=lambda key: (-p["anchor"][key], candidate_order[key])),
        "fact_new_winner_gap_strongest_competitor_id": min(
            (key for key in ids if key != new), key=lambda key: (-p["fact_flip"][key], candidate_order[key])),
        "anchor_frozen_argmax_candidate_id": wa,
        "fact_frozen_argmax_candidate_id": wf,
        "old_candidate_id": old,
        "new_candidate_id": new,
    }
    return values, categorical


def check_panel_and_training() -> tuple[dict[str, Any], dict[str, Any]]:
    panel_seal_path = PANEL / "seals/q-r1-panel-input-terminal-seal-v01.json"
    panel_seal = json_file(panel_seal_path)
    need(panel_seal.get("root_sha256") == PANEL_ROOT and root_digest(panel_seal["entries"]) == PANEL_ROOT,
         "panel root receipt invalid")
    for row in panel_seal["entries"]:
        path = PANEL / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"panel artifact mismatch: {row['path']}")
    training_seal_path = TRAIN / "training-seal-manifest.json"
    training_tree_path = TRAIN / "checkpoint-hash-tree.json"
    training_seal, tree = json_file(training_seal_path), json_file(training_tree_path)
    need(training_seal.get("status") == "Q_R1_ALL_48_RUNS_COMPLETE_SEALED_UNEVALUATED"
         and training_seal.get("run_count") == 48 and training_seal.get("trained_checkpoint_count") == 192
         and training_seal.get("initial_template_count") == 12 and training_seal.get("sealed_object_count") == 204,
         "training seal incomplete")
    need(training_seal.get("evaluation_panel_opened") is False and training_seal.get("evaluation_feedback") is False,
         "training seal reports panel contact")
    instrument = verify_instrument_package()
    need(training_seal.get("instrument_manifest_sha256") == instrument["manifest_sha256"]
         and training_seal.get("instrument_entries_root_sha256") == instrument["entries_root_sha256"],
         "training seal does not bind the pre-run instrument package")
    need(training_seal.get("checkpoint_tree_sha256") == sha(training_tree_path)
         and tree.get("entry_count") == len(tree.get("entries", [])) and root_digest(tree["entries"]) == tree.get("entries_root_sha256", root_digest(tree["entries"])),
         "training tree receipt invalid")
    for row in tree["entries"]:
        path = TRAIN / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"training object changed: {row['path']}")
    checkpoint_count = sum(Path(row["path"]).name.startswith("step-") and Path(row["path"]).suffix == ".pt" for row in tree["entries"])
    init_count = sum("initial-templates/seed-" in row["path"] and row["path"].endswith(".pt") for row in tree["entries"])
    need(checkpoint_count == 192 and init_count == 12, "training object inventory differs from frozen matrix")
    preflight_path = TRAIN / "training-preflight-receipt-v01.json"
    preflight = json_file(preflight_path)
    need(training_seal.get("training_preflight_sha256") == sha(preflight_path)
         and preflight.get("status") == "Q_R1_TRAINING_PREFLIGHT_PASS_ZERO_OPTIMIZER_STEPS",
         "training preflight receipt binding/status mismatch")
    seed_schedules = {int(row["seed"]): row for row in preflight.get("per_seed_schedule_receipts", [])}
    need(set(seed_schedules) == set(SEEDS) and len(preflight.get("per_seed_schedule_receipts", [])) == 12,
         "per-seed schedule receipts missing")
    recomputed_schedules = per_seed_schedule_hashes()
    expected_order = []
    for seed_index, seed in enumerate(SEEDS):
        init_path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
        need(init_path.is_file(), f"shared initialization missing: {seed}")
        arm_order = list(ARMS[seed_index % 4:] + ARMS[:seed_index % 4])
        need(seed_schedules[seed].get("rows") == 120
             and seed_schedules[seed].get("schedule_sha256") == recomputed_schedules[seed]
             and seed_schedules[seed].get("execution_arm_order") == arm_order,
             f"per-seed schedule/arm-order receipt mismatch: {seed}")
        for arm in arm_order:
            expected_order.append(f"{seed}/{arm}")
            run_dir = TRAIN / "runs" / f"seed-{seed}" / arm
            config_path, integrity_path = run_dir / "run-config.json", run_dir / "run-integrity.json"
            config, integrity = json_file(config_path), json_file(integrity_path)
            need(config.get("seed") == seed and config.get("arm") == arm
                 and config.get("seed_schedule_sha256") == seed_schedules[seed]["schedule_sha256"]
                 and integrity.get("seed_schedule_sha256") == seed_schedules[seed]["schedule_sha256"]
                 and integrity.get("run_config_sha256") == sha(config_path)
                 and integrity.get("checkpoint_count") == 4 and integrity.get("optimizer_steps") == 120,
                 f"run schedule/integrity mismatch: {seed}/{arm}")
    need(training_seal.get("completed_order") == expected_order,
         "run execution order does not match the prospectively rotated schedule")
    return panel_seal, training_seal


def expected_cells():
    for seed in SEEDS:
        yield seed, "COMMON_INIT", 0
        for step in STEPS:
            for arm in ARMS:
                yield seed, arm, step


def bootstrap_plan(ids: list[str], family_by_id: dict[str, str]) -> tuple[np.ndarray, list[int], str]:
    ordered_ids: list[str] = []
    positions: list[int] = []
    for family in FAMILIES:
        block = sorted(nid for nid in ids if family_by_id[nid] == family)
        need(len(block) == 500, f"bootstrap family support mismatch: {family}")
        ordered_ids.extend(block)
        positions.extend(ids.index(nid) for nid in block)
    plan = np.empty((10_000, 2_000), dtype=np.int32)
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    offset = 0
    for _family in FAMILIES:
        ix = np.arange(offset, offset + 500, dtype=np.int32)
        draws = rng.integers(0, 500, size=(10_000, 500), dtype=np.int32)
        plan[:, offset:offset + 500] = ix[draws]
        offset += 500
    digest = hashlib.sha256(np.asarray(plan, dtype="<i4").tobytes(order="C")).hexdigest()
    return plan, positions, digest


def load_panel_truth() -> dict[str, dict[str, Any]]:
    scope_rows = list(jsonl(PANEL / "panel/panel-feature-scope.jsonl"))
    target_rows = list(jsonl(PANEL / "target-joins/r1-exact-world-targets.jsonl"))
    neighborhoods = list(jsonl(PANEL / "panel/panel-neighborhoods.jsonl"))
    selections = list(jsonl(PANEL / "matching/matched-neutral-selection.jsonl"))
    candidate_rows = list(jsonl(PANEL / "features/r1-candidate-feature-manifest.jsonl"))
    need(len(scope_rows) == len(target_rows) == 22_000 and len(neighborhoods) == len(selections) == 2_000,
         "sealed panel input cardinality invalid")
    targets_by_episode: dict[tuple[str, str], dict[str, Any]] = {}
    for index, target in enumerate(target_rows):
        need(int(target["index"]) == index and index < len(scope_rows), "target row index discontinuity")
        scope = scope_rows[index]
        nid, eid = str(scope["neighborhood_id"]), str(scope["episode_id"])
        need(str(target["neighborhood_id"]) == nid and str(target["episode_id"]) == eid
             and str(target["role"]) == str(scope["role"]), f"exact target identity mismatch at {index}")
        targets_by_episode[(nid, eid)] = {"target": [float(value) for value in target["target"]], "role": str(target["role"])}
    scopes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in scope_rows:
        nid, eid = str(row["neighborhood_id"]), str(row["episode_id"])
        need(eid not in scopes[nid], f"duplicate episode in panel scope: {nid}/{eid}")
        scopes[nid][eid] = row
    selection_by_id = {str(row["neighborhood_id"]): row for row in selections}
    need(len(selection_by_id) == 2_000, "matched-neutral selection identities not unique")
    candidate_orders: dict[str, list[str]] = defaultdict(list)
    for row in sorted(candidate_rows, key=lambda item: (str(item["schema_family_id"]), int(item["candidate_order"]))):
        candidate_orders[str(row["schema_family_id"]).split(":")[-1]].append(str(row["candidate_semantic_id"]))
    need(set(candidate_orders) == set(FAMILIES) and all(len(ids) == 4 for ids in candidate_orders.values()),
         "sealed candidate semantic order invalid")
    result: dict[str, dict[str, Any]] = {}
    for neighborhood in neighborhoods:
        nid = str(neighborhood["neighborhood_id"])
        role_rows = scopes[nid]
        role_episode = {str(row["role"]): str(row["episode_id"]) for row in role_rows.values()}
        selected = selection_by_id[nid]
        matched = str(selected["matched_neutral_episode_id"])
        need(matched in role_rows and role_rows[matched]["role"] == selected["matched_neutral_role"],
             f"selected-neutral identity mismatch: {nid}")
        episodes = {"anchor": role_episode["anchor"], "fact_flip": role_episode["fact_flip"],
                    "sham": role_episode["sham"], "matched_neutral": matched}
        family = str(neighborhood["family_id"])
        slug = str(neighborhood["family_slug"])
        candidates = candidate_orders[slug]
        exact = {view: targets_by_episode[(nid, eid)]["target"] for view, eid in episodes.items()}
        need(max(abs(a - b) for a, b in zip(exact["anchor"], exact["sham"], strict=True)) <= 1e-12
             and max(abs(a - b) for a, b in zip(exact["anchor"], exact["matched_neutral"], strict=True)) <= 1e-12,
             f"exact-world invariant target changed: {nid}")
        old_index = max(range(4), key=lambda i: (exact["anchor"][i], -i))
        new_index = max(range(4), key=lambda i: (exact["fact_flip"][i], -i))
        need(old_index != new_index, f"fact target does not change MAP: {nid}")
        result[nid] = {"family_id": family, "episodes": episodes, "candidate_ids": candidates,
                       "old_candidate_id": candidates[old_index], "new_candidate_id": candidates[new_index],
                       "targets": exact}
    need(len(result) == 2_000 and set(result) == set(selection_by_id), "sealed panel truth join incomplete")
    return result


def replay_cell(seed: int, arm: str, step: int, prediction_stream: Any, metric_stream: Any,
                expected_panel: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, float]], np.ndarray]:
    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for _ in range(8_000):
        row = json.loads(prediction_stream.readline())
        need((row.get("seed"), row.get("arm"), row.get("global_step")) == (seed, arm, step),
             f"raw prediction order error in {seed}/{arm}/{step}")
        nid, view = str(row["neighborhood_id"]), str(row["view"])
        need(nid in expected_panel and view in VIEWS and view not in groups[nid], f"unexpected/duplicate panel row: {nid}/{view}")
        binding = expected_panel[nid]
        need(row.get("family_id") == binding["family_id"] and row.get("episode_id") == binding["episodes"][view]
             and row.get("candidate_semantic_ids") == binding["candidate_ids"]
             and row.get("old_candidate_id") == binding["old_candidate_id"]
             and row.get("new_candidate_id") == binding["new_candidate_id"]
             and row.get("gold") == binding["targets"][view],
             f"prediction input/target identity differs from sealed panel: {nid}/{view}")
        groups[nid][view] = row
    ids = sorted(groups)
    need(len(ids) == 2_000 and all(set(groups[nid]) == set(VIEWS) for nid in ids), "cell is not 2000 complete four-view neighborhoods")
    total = {key: 0.0 for key in NUMERIC}
    family_sums = {family: {key: 0.0 for key in NUMERIC} for family in FAMILIES}
    family_counts = Counter()
    four = Counter()
    matrix = np.empty((2_000, len(NUMERIC)), dtype=np.float64)
    categorical: dict[str, dict[str, float]] = {}
    for index, nid in enumerate(ids):
        values, labels = row_metrics(groups[nid])
        fam = str(groups[nid]["anchor"]["family_id"]).split(":")[-1]
        need(fam in family_sums, f"unexpected family {fam}")
        family_counts[fam] += 1
        for key in NUMERIC:
            value = values[key]
            total[key] += value
            family_sums[fam][key] += value
            matrix[index, NUMERIC.index(key)] = value
        pair = (values["anchor_old_map"] >= 0.5, values["fact_new_map"] >= 0.5)
        four[pair] += 1
        expected_metric = json.loads(metric_stream.readline())
        need((expected_metric.get("seed"), expected_metric.get("arm"), expected_metric.get("step"),
              expected_metric.get("neighborhood_id")) == (seed, arm, step, nid),
             f"analysis row order/identity mismatch: {seed}/{arm}/{step}/{nid}")
        for key in NUMERIC:
            need(key in expected_metric and close(float(expected_metric[key]), values[key]),
                 f"independent per-neighborhood metric replay differs: {seed}/{arm}/{step}/{nid}/{key}")
        for key, value in labels.items():
            need(expected_metric.get(key) == value, f"categorical replay mismatch: {nid}/{key}")
        categorical[nid] = labels
    need(all(family_counts[f] == 500 for f in FAMILIES), "cell family allocation changed")
    overall = {key: value / 2_000 for key, value in total.items()}
    by_family = {family: {key: value / 500 for key, value in sums.items()} for family, sums in family_sums.items()}
    names = {(True, True): "A_old_AND_F_new", (True, False): "A_old_AND_NOT_F_new",
             (False, True): "NOT_A_old_AND_F_new", (False, False): "NOT_A_old_AND_NOT_F_new"}
    four_rows = {name: {"count": int(four[pair]), "rate": four[pair] / 2_000} for pair, name in names.items()}
    return {"n": 2_000, "overall": overall, "by_family": by_family, "four_cell_A_F": four_rows}, categorical, matrix


def verify_seed_gates(summaries: dict[str, Any], results: dict[str, Any]) -> dict[str, int]:
    counts = Counter()
    for seed in SEEDS:
        low = summaries[f"{seed}/B-SHAM-LOW/120"]["overall"]
        sham = summaries[f"{seed}/B-SHAM/120"]["overall"]
        dup = summaries[f"{seed}/B-DUP/120"]["overall"]
        low_fam = summaries[f"{seed}/B-SHAM-LOW/120"]["by_family"]
        sham_fam = summaries[f"{seed}/B-SHAM/120"]["by_family"]
        gain = low["new_probability_delta"] - sham["new_probability_delta"] >= 0.020
        direction = low["correct_direction"] >= 0.99 and low["correct_direction"] >= sham["correct_direction"] - 0.01
        locality = (dup["sham_l1"] > 0 and dup["matched_l1"] > 0
                    and low["sham_l1"] <= .75 * dup["sham_l1"]
                    and low["matched_l1"] <= .75 * dup["matched_l1"]
                    and low["sham_map_flip"] <= dup["sham_map_flip"] + .05
                    and low["matched_map_flip"] <= dup["matched_map_flip"] + .05)
        preserve = (low["anchor_old_map"] - sham["anchor_old_map"] >= -.05
                    and all(low_fam[f]["anchor_old_map"] - sham_fam[f]["anchor_old_map"] >= -.10 for f in FAMILIES))
        stiff = (gain and dup["sham_l1"] > 0 and dup["matched_l1"] > 0
                 and abs(low["sham_l1"] - dup["sham_l1"]) / dup["sham_l1"] <= .10
                 and abs(low["matched_l1"] - dup["matched_l1"]) / dup["matched_l1"] <= .10
                 and abs(low["sham_map_flip"] - dup["sham_map_flip"]) <= .05
                 and abs(low["matched_map_flip"] - dup["matched_map_flip"]) <= .05)
        map_response = (low["fact_new_map"] - sham["fact_new_map"] >= .10
                        and low["strict_transition"] - sham["strict_transition"] >= .10)
        expected = {"gain_pass": gain, "direction_pass": direction,
                    "material_locality_advantage_over_dup_pass": locality,
                    "preservation_pass": preserve, "q_operating_point_seed_pass": gain and direction and locality and preserve,
                    "q_stiff_coupling_seed": stiff, "q_map_response_seed_pass": map_response,
                    "dup_zero_l1_channel_unclassifiable": dup["sham_l1"] == 0 or dup["matched_l1"] == 0}
        recorded = results["same_seed_step120_q_labels"][str(seed)]["labels"]
        need(recorded == expected, f"Q same-seed label replay mismatch for {seed}")
        for key, value in expected.items():
            if value:
                counts[key] += 1
    for key, count in (("tunable_gain_locality_operating_point", counts["q_operating_point_seed_pass"]),
                       ("stiff_coupling_pattern", counts["q_stiff_coupling_seed"]),
                       ("meaningful_map_response", counts["q_map_response_seed_pass"])):
        need(results["cohort_q_labels"]["observed_counts_out_of_12"][key] == count
             and results["cohort_q_labels"]["labels"][key] == (count >= 8), f"cohort count replay mismatch: {key}")
    return dict(counts)


def main() -> int:
    instrument = verify_instrument_package()
    packet_path = R1 / "seals/q-r1-packet-seal-and-authorization-v01.json"
    need(sha(packet_path) == PACKET_SHA, "authorization packet hash mismatch")
    packet = json_file(packet_path)
    need(packet["status"] == "SEALED_AUTHORIZED_PENDING_EXECUTION" and packet["contract_bundle_root_sha256"] == PACKET_ROOT,
         "authorization packet identity mismatch")
    for row in packet["contracts"]:
        path = R1 / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"contract bundle member mismatch: {row['path']}")
    need(sha(R1 / "contracts/q-r1-run-contract-v01.json") == RUN_SHA
         and sha(R1 / "contracts/q-r1-analysis-contract-v01.json") == ANALYSIS_SHA,
         "sealed R1 contract changed")
    panel_seal, training_seal = check_panel_and_training()
    opening = json_file(OUT / "panel-opening-receipt-v01.json")
    inference = json_file(OUT / "inference-receipt-v01.json")
    tree = json_file(OUT / "raw-prediction-hash-tree-v01.json")
    pred_path = OUT / "raw-predictions-v01.jsonl"
    metric_path = OUT / "neighborhood-metrics-v01.jsonl"
    need(opening.get("opening_count") == 1 and opening.get("panel_root_sha256") == PANEL_ROOT
         and opening.get("all_training_artifacts_sealed_before_open") is True
         and opening.get("training_seal_sha256") == sha(TRAIN / "training-seal-manifest.json")
         and opening.get("checkpoint_tree_sha256") == sha(TRAIN / "checkpoint-hash-tree.json"),
         "panel opening receipt invalid")
    need(opening.get("instrument_package_seal_sha256") == instrument["seal_sha256"]
         and opening.get("instrument_package_entries_root_sha256") == instrument["entries_root_sha256"],
         "panel opening does not bind the instrument package")
    need(inference.get("status") == "Q_R1_ALL_204_CELLS_INFERRED_AND_SEALED"
         and inference.get("panel_open_count") == 1 and inference.get("prediction_sha256") == sha(pred_path)
         and tree.get("raw_predictions", {}).get("sha256") == sha(pred_path)
         and tree.get("prediction_rows") == 1_632_000 and tree.get("cell_count") == 204,
         "complete inference receipt/hash tree invalid")
    need(tree.get("panel_open_count") == 1 and tree.get("predictions_before_analysis") is True
         and tree.get("panel_root_sha256") == PANEL_ROOT, "prediction tree firewall/order mismatch")
    panel_inputs = load_panel_truth()
    panel_families = {nid: row["family_id"] for nid, row in panel_inputs.items()}
    need(len(panel_families) == 2_000 and {value.split(":")[-1] for value in panel_families.values()} == set(FAMILIES),
         "sealed fresh panel identity/family set invalid")
    results = json_file(OUT / "q-r1-analysis-v01.json")
    analysis_seal = json_file(OUT / "q-r1-analysis-seal-v01.json")
    need(results.get("status") == "Q_R1_FIXED_DOSE_RESPONSE_PHENOTYPE_ANALYSIS_COMPLETE"
         and results.get("prediction_sha256") == sha(pred_path) and results.get("prediction_hash_tree_sha256") == sha(OUT / "raw-prediction-hash-tree-v01.json"),
         "analysis result is not bound to the sealed prediction matrix")
    need(results.get("instrument_package", {}).get("seal_sha256") == instrument["seal_sha256"]
         and analysis_seal.get("instrument_package_seal_sha256") == instrument["seal_sha256"],
         "analysis outputs do not bind the pre-run instrument package")
    outputs = analysis_seal.get("outputs", [])
    need(analysis_seal.get("status") == "Q_R1_ANALYSIS_OUTPUTS_SEALED"
         and analysis_seal.get("analysis_root_sha256") == root_digest(outputs)
         and analysis_seal.get("panel_open_count") == 1, "analysis output seal invalid")
    for row in outputs:
        path = OUT / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"analysis output hash mismatch: {row['path']}")
    summaries = results["response_summaries"]
    family_by_id = {nid: family.split(":")[-1] for nid, family in panel_families.items()}
    matrices: dict[tuple[int, str, int], np.ndarray] = {}
    replays = 0
    with pred_path.open("r", encoding="utf-8") as predictions, metric_path.open("r", encoding="utf-8") as metrics:
        for cell in expected_cells():
            summary, _categorical, matrix = replay_cell(*cell, predictions, metrics, panel_families)
            matrices[cell] = matrix
            # The independently checked panel set is fixed; replay_cell checks each cell against it.
            actual = summaries[f"{cell[0]}/{cell[1]}/{cell[2]}"]["overall"]
            for key in NUMERIC:
                need(close(float(actual[key]), summary["overall"][key]), f"cell aggregate replay mismatch {cell}/{key}")
            recorded_four = summaries[f"{cell[0]}/{cell[1]}/{cell[2]}"]["four_cell_A_F"]
            for label, row in summary["four_cell_A_F"].items():
                need(recorded_four[label]["count"] == row["count"] and close(float(recorded_four[label]["rate"]), row["rate"]),
                     f"A/F four-cell replay mismatch {cell}/{label}")
            replays += 1
        need(not predictions.readline() and not metrics.readline(), "extra rows after complete prediction/metric matrices")
    # Re-read the analysis metric table once for independent family aggregation and enforce per-cell identity order.
    with metric_path.open("r", encoding="utf-8") as metrics:
        for cell in expected_cells():
            seed, arm, step = cell
            sums = {family: {key: 0.0 for key in NUMERIC} for family in FAMILIES}
            counts = Counter()
            for _ in range(2_000):
                row = json.loads(metrics.readline())
                fam = str(row["family"])
                need(fam in sums, "metric table contains unexpected family")
                counts[fam] += 1
                for key in NUMERIC:
                    sums[fam][key] += float(row[key])
            for family in FAMILIES:
                need(counts[family] == 500, f"family row count invalid {cell}/{family}")
                recorded = summaries[f"{seed}/{arm}/{step}"]["by_family"][family]
                for key in NUMERIC:
                    need(close(float(recorded[key]), sums[family][key] / 500),
                         f"family aggregate replay mismatch {cell}/{family}/{key}")
    gate_counts = verify_seed_gates(summaries, results)
    plan_path = OUT / "shared-bootstrap-resample-plan-v01.npy"
    plan = np.load(plan_path, mmap_mode="r", allow_pickle=False)
    need(plan.shape == (10_000, 2_000) and plan.dtype == np.int32, "shared bootstrap plan schema mismatch")
    bootstrap_data = results["shared_bootstrap"]
    need(sha(plan_path) == bootstrap_data["plan_file_sha256"], "bootstrap plan file hash mismatch")
    with pred_path.open("r", encoding="utf-8") as stream:
        first_cell = [json.loads(stream.readline()) for _ in range(8_000)]
    ids_order = sorted({str(row["neighborhood_id"]) for row in first_cell})
    need(len(ids_order) == 2_000, "first cell identity set invalid for bootstrap replay")
    expected_plan, order_positions, expected_plan_hash = bootstrap_plan(ids_order, family_by_id)
    need(hashlib.sha256(np.asarray(plan, dtype="<i4").tobytes(order="C")).hexdigest() == expected_plan_hash
         and bootstrap_data["plan_sha256"] == expected_plan_hash
         and np.array_equal(plan, expected_plan), "shared stratified bootstrap resample plan replay mismatch")
    bootstrap_results = results["step120_paired_bootstrap_contrasts"]
    contrasts = (("B-SHAM-LOW", "B-SHAM", PAIR_BOOTSTRAP),
                 ("B-SHAM-LOW", "B-DUP", LOCALITY_BOOTSTRAP))
    for seed in SEEDS:
        for left_arm, right_arm, metric_names in contrasts:
            left = matrices[(seed, left_arm, 120)]
            right = matrices[(seed, right_arm, 120)]
            for name in metric_names:
                difference = left[order_positions, NUMERIC.index(name)] - right[order_positions, NUMERIC.index(name)]
                samples = difference[expected_plan].mean(axis=1)
                interval = np.quantile(samples, [0.025, 0.975], method="linear")
                key = f"{seed}/{left_arm}_minus_{right_arm}/{name}"
                recorded = bootstrap_results[key]
                need(close(float(recorded["mean"]), float(difference.mean()))
                     and len(recorded["ci95"]) == 2
                     and close(float(recorded["ci95"][0]), float(interval[0]))
                     and close(float(recorded["ci95"][1]), float(interval[1]))
                     and recorded["paired_interval_excludes_zero"] is bool(interval[0] > 0 or interval[1] < 0),
                     f"paired bootstrap replay mismatch: {key}")
    need(results.get("cell_count") == 204 and results.get("prediction_rows") == 1_632_000
         and results.get("neighborhood_metric_rows") == 408_000 and replays == 204,
         "analysis matrix cardinality mismatch")
    receipt = {
        "status": "Q_R1_INDEPENDENT_RESULT_REPLAY_PASS",
        "packet_sha256": PACKET_SHA, "packet_bundle_root_sha256": PACKET_ROOT,
        "panel_input_root_sha256": PANEL_ROOT, "instrument_package_seal_sha256": instrument["seal_sha256"],
        "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
        "prediction_sha256": sha(pred_path), "analysis_seal_sha256": sha(OUT / "q-r1-analysis-seal-v01.json"),
        "independently_replayed_cells": replays, "independently_replayed_prediction_rows": 1_632_000,
        "independently_replayed_metric_rows": 408_000, "same_seed_label_counts": gate_counts,
        "cohort_threshold": 8, "optimizer_seed_population_inference": False,
        "panel_open_count": 1, "no_inference_performed": True,
    }
    receipt_path = OUT / "independent-result-verification-v01.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
        stream.flush()
    print(json.dumps({**receipt, "receipt_sha256": sha(receipt_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
