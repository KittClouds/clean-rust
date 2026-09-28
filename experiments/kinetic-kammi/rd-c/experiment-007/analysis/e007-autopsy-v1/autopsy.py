"""Exploratory, cross-world autopsy for sealed E007 run e007-1790316330677261600.

Reads the sealed run only. All outcome-conditioned estimates are post-hoc and
must not be promoted to runtime or confirmatory evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


RUN_ID = "e007-1790316330677261600"
PROJECT = Path(r"C:\rd-c\experiment-007")
RUN = PROJECT / "artifacts" / "runs" / RUN_ID
OUT = PROJECT / "analysis" / "e007-autopsy-v1"
BUDGETS = (16, 32, 64)
FEATURE_NAMES = (
    "bias",
    "observer_disagreement",
    "warning",
    "age",
    "confidence_gap",
    "revision_gap",
    "audit_selected",
    "stale_visible",
)
KNN_K = (32, 64, 128, 256)
RIDGE_ALPHA = (0.001, 0.01, 0.1, 1.0)
UNRESOLVED = {"unknown", "failed"}
NO_ACTION = 65535


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_features(frame: pd.DataFrame) -> np.ndarray:
    age = np.minimum(frame["source_age"].to_numpy(dtype=np.float64), 3.0) / 2.0
    confidence_gap = 1.0 - np.minimum(
        frame["confidence_milli"].to_numpy(dtype=np.float64), 1000.0
    ) / 1000.0
    revision_gap = np.minimum(
        frame["revision_gap"].to_numpy(dtype=np.float64), 3.0
    ) / 3.0
    warning = frame["warning"].to_numpy(dtype=bool)
    stale_visible = (frame["source_age"].to_numpy() > 0) | warning
    return np.column_stack(
        (
            np.ones(len(frame)),
            frame["active"].to_numpy() != frame["shadow"].to_numpy(),
            warning,
            age,
            confidence_gap,
            revision_gap,
            frame["audit_selected"].to_numpy(dtype=bool),
            stale_visible,
        )
    ).astype(np.float64)


def classify_query(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Mirror the frozen typed inspection contract and return kind/action."""
    transport = frame["transport"].to_numpy(dtype=np.int64)
    candidate = frame["candidate"].to_numpy(dtype=np.int64)
    competing = frame["competing_candidate"].to_numpy(dtype=np.int64)
    confidence_column = (
        "confidence_milli_source"
        if "confidence_milli_source" in frame.columns
        else "confidence_milli"
    )
    confidence = frame[confidence_column].to_numpy(dtype=np.int64)
    signature = frame["signature_valid"].to_numpy(dtype=bool)
    active = frame["active"].to_numpy(dtype=np.int64)

    failed = np.isin(transport, (1, 2))
    unknown = (transport == 3) | (
        (transport == 0)
        & (
            ~signature
            | (confidence < 800)
            | (candidate == NO_ACTION)
            | (competing != NO_ACTION)
        )
    )
    confirmed = (transport == 0) & ~unknown & ~failed & (candidate == active)
    contradicted = (transport == 0) & ~unknown & ~failed & (candidate != active)
    kind = np.full(len(frame), "failed", dtype=object)
    kind[unknown] = "unknown"
    kind[confirmed] = "confirmed"
    kind[contradicted] = "contradicted"
    action = np.full(len(frame), -1, dtype=np.int64)
    action[confirmed] = active[confirmed]
    action[contradicted] = candidate[contradicted]
    return kind, action


def load_cohort(cohort: str) -> pd.DataFrame:
    public = pd.read_csv(RUN / f"inputs/{cohort}/public.csv")
    labels = pd.read_csv(RUN / f"inputs/{cohort}/labels.csv")
    sources = pd.read_csv(RUN / f"inputs/{cohort}/source-state.csv")
    data = public.merge(labels, on=["world_id", "episode_id"], validate="one_to_one")
    data = data.merge(
        sources, on=["world_id", "episode_id"], validate="one_to_one", suffixes=("", "_source")
    )
    if data[["correct_action", "transport"]].isna().any().any():
        raise ValueError(f"{cohort} source and label coverage is incomplete")
    kinds, proposed = classify_query(data)
    baseline_right = data["active"].to_numpy() == data["correct_action"].to_numpy()
    queried_right = (proposed >= 0) & (proposed == data["correct_action"].to_numpy())
    data["inspection_kind"] = kinds
    data["baseline_right"] = baseline_right
    data["realized_delta"] = queried_right.astype(np.int8) - baseline_right.astype(np.int8)
    data["new_domain_id"] = data["domain_id"].to_numpy() >= 1000
    data["cohort"] = cohort
    return data


def load_episode_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    development = load_cohort("development")
    heldout = load_cohort("heldout")
    if len(development) != 2048 or len(heldout) != 6144:
        raise ValueError("development or held-out source and label coverage is incomplete")
    trace = pd.read_csv(RUN / "run-trace.csv")
    world_strata = trace[["world_id", "stratum"]].drop_duplicates()
    if world_strata["world_id"].duplicated().any():
        raise ValueError("world-to-stratum mapping is not unique")
    heldout = heldout.merge(world_strata, on="world_id", validate="many_to_one")

    models = pd.read_csv(RUN / "inputs/development/frozen-models.csv")
    rows = models[(models["model"] == "feature_router")]
    weights_by_name = dict(zip(rows["feature_or_domain"], rows["weight"].astype(float)))
    if set(weights_by_name) != set(FEATURE_NAMES):
        raise ValueError("frozen feature weights do not match the E007 schema")
    weights = np.asarray([weights_by_name[name] for name in FEATURE_NAMES], dtype=np.float64)
    for cohort_data in (development, heldout):
        x = make_features(cohort_data)
        cohort_data["predicted_delta"] = x @ weights
        cohort_data["query_score"] = cohort_data["predicted_delta"] / np.maximum(
            cohort_data["query_cost_units"].to_numpy(dtype=np.float64), 1.0
        )
    return development, heldout, weights_by_name


def verify_selected_traces(data: pd.DataFrame) -> pd.DataFrame:
    trace = pd.read_csv(RUN / "run-trace.csv")
    selected = trace[(trace["lane"] == "feature_router") & (trace["budget"] == 64)].copy()
    if len(selected) != 16 * 384:
        raise ValueError("feature_router/64 trace has an unexpected row count")
    selected = selected.merge(
        data[["world_id", "episode_id", "realized_delta", "inspection_kind", "baseline_right"]].rename(
            columns={"inspection_kind": "source_kind"}
        ),
        on=["world_id", "episode_id"],
        validate="one_to_one",
    )
    queried = selected["inspection_kind"].ne("none")
    expected_kind = selected["source_kind"]
    if not np.array_equal(
        selected.loc[queried, "inspection_kind"].to_numpy(),
        expected_kind.loc[queried].to_numpy(),
    ):
        raise ValueError("typed inspection outcome differs from the sealed task trace")
    delta_from_trace = (
        selected["completed"].astype(int).to_numpy()
        - selected["baseline_right"].astype(int).to_numpy()
    )
    if not np.array_equal(delta_from_trace[queried], selected.loc[queried, "realized_delta"]):
        raise ValueError("derived counterfactual completion delta differs from trace")
    selected["queried"] = queried.to_numpy()
    selected["u_baseline_right"] = (
        queried & selected["source_kind"].eq("unknown") & selected["baseline_right"]
    )
    selected["u_baseline_wrong"] = (
        queried & selected["source_kind"].eq("unknown") & ~selected["baseline_right"]
    )
    selected["f_baseline_right"] = (
        queried & selected["source_kind"].eq("failed") & selected["baseline_right"]
    )
    selected["f_baseline_wrong"] = (
        queried & selected["source_kind"].eq("failed") & ~selected["baseline_right"]
    )
    selected["unresolved_baseline_right"] = (
        selected["u_baseline_right"] | selected["f_baseline_right"]
    )
    selected["unresolved_baseline_wrong"] = (
        selected["u_baseline_wrong"] | selected["f_baseline_wrong"]
    )
    return selected


def reconcile(selected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for (world_id, stratum), group in selected.groupby(["world_id", "stratum"]):
        calls = group[group["queried"]]
        wrong_to_right = int(calls["wrong_to_right"].sum())
        right_to_wrong = int(calls["right_to_wrong"].sum())
        unresolved_right = int(calls["unresolved_baseline_right"].sum())
        unresolved_wrong = int(calls["unresolved_baseline_wrong"].sum())
        gain = int(group["completed"].sum() - group["baseline_right"].sum())
        decomposed = wrong_to_right - right_to_wrong - unresolved_right
        row: dict[str, object] = {
            "world_id": int(world_id),
            "stratum": stratum,
            "calls": int(calls.shape[0]),
            "unknown_baseline_right": int(calls["u_baseline_right"].sum()),
            "unknown_baseline_wrong": int(calls["u_baseline_wrong"].sum()),
            "failed_baseline_right": int(calls["f_baseline_right"].sum()),
            "failed_baseline_wrong": int(calls["f_baseline_wrong"].sum()),
            "wrong_to_right": wrong_to_right,
            "right_to_wrong": right_to_wrong,
            "unresolved_baseline_right": unresolved_right,
            "avoided_wrong_commits": int(calls["avoided_wrong_commit"].sum()),
            "completion_gain": gain,
            "reconciled_gain": decomposed,
            "residual": gain - decomposed,
        }
        rows.append(row)
    by_world = pd.DataFrame(rows).sort_values("world_id")
    if (by_world["residual"] != 0).any() or not np.array_equal(
        by_world["calls"].to_numpy(), np.full(16, 64)
    ):
        raise ValueError("per-world E007 completion reconciliation failed")
    if not np.array_equal(
        by_world["avoided_wrong_commits"].to_numpy(),
        (by_world["unknown_baseline_wrong"] + by_world["failed_baseline_wrong"]).to_numpy(),
    ):
        raise ValueError("avoided wrong commits do not match unresolved baseline-wrong cases")
    by_stratum = (
        by_world.groupby("stratum", as_index=False)
        .sum(numeric_only=True)
        .drop(columns=["world_id"], errors="ignore")
        .sort_values("stratum")
    )
    by_stratum["residual"] = by_stratum["completion_gain"] - by_stratum[
        "reconciled_gain"
    ]
    overall = pd.DataFrame(
        [
            {
                key: value
                for key, value in by_world.select_dtypes(include="number")
                .drop(columns=["world_id"], errors="ignore")
                .sum()
                .items()
            }
        ]
    )
    overall.insert(0, "stratum", "overall")
    if int(overall.loc[0, "residual"]) != 0:
        raise ValueError("overall E007 completion reconciliation failed")
    return by_world, pd.concat([overall, by_stratum], ignore_index=True)


def score_calibration(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    development_scores = data.loc[
        data["cohort"].eq("development"), "query_score"
    ].to_numpy(dtype=np.float64)
    # Fixed development-derived cut points make the two cohorts comparable.
    cut_points = np.unique(np.quantile(development_scores, np.linspace(0.1, 0.9, 9)))
    data["score_bin"] = np.searchsorted(
        cut_points, data["query_score"].to_numpy(dtype=np.float64), side="right"
    ) + 1
    heldout_rows = data["cohort"].eq("heldout").to_numpy()
    slices: dict[str, np.ndarray] = {
        "all_heldout": heldout_rows,
        "reliability_shift": heldout_rows & data["stratum"].eq("reliability_shift").to_numpy(),
        "stale_sources_stratum": heldout_rows & data["stratum"].eq("stale_sources").to_numpy(),
        "unseen_domain_ids": heldout_rows & data["new_domain_id"].to_numpy(dtype=bool),
        "familiar_domain_ids": heldout_rows & ~data["new_domain_id"].to_numpy(dtype=bool),
        "source_stale": heldout_rows & data["source_is_stale"].to_numpy(dtype=bool),
        "source_fresh": heldout_rows & ~data["source_is_stale"].to_numpy(dtype=bool),
    }
    rows: list[dict[str, object]] = []
    for slice_name, mask in slices.items():
        subset = data.loc[mask]
        for score_bin, group in subset.groupby("score_bin", sort=True):
            values = group["realized_delta"].to_numpy(dtype=np.float64)
            world_means = group.groupby("world_id")["realized_delta"].mean().to_numpy(dtype=np.float64)
            rows.append(
                {
                    "slice": slice_name,
                    "score_bin": int(score_bin),
                    "cohort": "heldout",
                    "bin_basis": "development_score_quantiles",
                    "episodes": len(group),
                    "mean_predicted_delta": group["predicted_delta"].mean(),
                    "mean_query_score": group["query_score"].mean(),
                    "mean_realized_delta": values.mean(),
                    "realized_delta_se": world_means.std(ddof=1) / math.sqrt(len(world_means))
                    if len(world_means) > 1
                    else 0.0,
                    "world_clusters": len(world_means),
                    "mean_query_cost_units": group["query_cost_units"].mean(),
                    "unknown_rate": group["inspection_kind"].eq("unknown").mean(),
                    "failed_rate": group["inspection_kind"].eq("failed").mean(),
                    "source_stale_rate": group["source_is_stale"].mean(),
                }
            )
    for cohort, subset in data.groupby("cohort", sort=True):
        for score_bin, group in subset.groupby("score_bin", sort=True):
            values = group["realized_delta"].to_numpy(dtype=np.float64)
            world_means = group.groupby("world_id")["realized_delta"].mean().to_numpy(dtype=np.float64)
            rows.append(
                {
                    "slice": "development_vs_heldout",
                    "score_bin": int(score_bin),
                    "cohort": cohort,
                    "bin_basis": "development_score_quantiles",
                    "episodes": len(group),
                    "mean_predicted_delta": group["predicted_delta"].mean(),
                    "mean_query_score": group["query_score"].mean(),
                    "mean_realized_delta": values.mean(),
                    "realized_delta_se": world_means.std(ddof=1) / math.sqrt(len(world_means))
                    if len(world_means) > 1
                    else 0.0,
                    "world_clusters": len(world_means),
                    "mean_query_cost_units": group["query_cost_units"].mean(),
                    "unknown_rate": group["inspection_kind"].eq("unknown").mean(),
                    "failed_rate": group["inspection_kind"].eq("failed").mean(),
                    "source_stale_rate": group["source_is_stale"].mean(),
                }
            )
    bins = pd.DataFrame(rows)
    data.to_csv(OUT / "episode-value-diagnostics.csv", index=False)
    bins.to_csv(OUT / "score-calibration.csv", index=False, float_format="%.8f")
    cohort_comparison = bins[bins["slice"] == "development_vs_heldout"].copy()
    return bins, cohort_comparison


def scale_features(x_train: np.ndarray, x_other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-9] = 1.0
    return (x_train - mean) / scale, (x_other - mean) / scale


def predict_candidates(
    x_train: np.ndarray, y_train: np.ndarray, x_other: np.ndarray
) -> dict[str, np.ndarray]:
    train_z, other_z = scale_features(x_train, x_other)
    design = np.column_stack((np.ones(len(train_z)), train_z))
    other_design = np.column_stack((np.ones(len(other_z)), other_z))
    gram = design.T @ design / len(design)
    rhs = design.T @ y_train / len(design)
    predictions: dict[str, np.ndarray] = {}
    for alpha in RIDGE_ALPHA:
        regularizer = np.diag(np.r_[0.0, np.full(train_z.shape[1], alpha)])
        predictions[f"ridge_{alpha:g}"] = other_design @ np.linalg.solve(
            gram + regularizer, rhs
        )

    max_k = min(max(KNN_K), len(train_z))
    train_sq = np.einsum("ij,ij->i", train_z, train_z)
    other_sq = np.einsum("ij,ij->i", other_z, other_z)
    distances = np.maximum(
        other_sq[:, None] + train_sq[None, :] - 2.0 * (other_z @ train_z.T), 0.0
    )
    nearest_partial = np.argpartition(distances, max_k - 1, axis=1)[:, :max_k]
    nearest_dist = np.take_along_axis(distances, nearest_partial, axis=1)
    nearest_order = np.argsort(nearest_dist, axis=1)
    nearest = np.take_along_axis(nearest_partial, nearest_order, axis=1)
    neighbor_values = y_train[nearest]
    cumulative = np.cumsum(neighbor_values, axis=1)
    for k in KNN_K:
        actual_k = min(k, len(train_z))
        predictions[f"knn_{k}"] = cumulative[:, actual_k - 1] / actual_k
    return predictions


def world_gain(
    indices: np.ndarray,
    prediction: np.ndarray,
    data: pd.DataFrame,
    budget: int,
) -> tuple[int, int]:
    score = prediction[indices] / np.maximum(
        data.iloc[indices]["query_cost_units"].to_numpy(dtype=np.float64), 1.0
    )
    ids = data.iloc[indices]["episode_id"].to_numpy(dtype=np.int64)
    order = np.lexsort((ids, -score))
    picked = indices[order[:budget]]
    return int(data.iloc[picked]["realized_delta"].sum()), int(
        data.iloc[picked]["query_cost_units"].sum()
    )


def grouped_inner_folds(train_worlds: list[int], strata_by_world: dict[int, str]) -> list[set[int]]:
    folds = [set(), set(), set()]
    for stratum in sorted(set(strata_by_world[w] for w in train_worlds)):
        worlds = sorted(w for w in train_worlds if strata_by_world[w] == stratum)
        for index, world in enumerate(worlds):
            folds[index % len(folds)].add(world)
    return folds


def fit_crossworld_feature_ranker(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Nested leave-one-world-out selection among ridge and KNN feature rankers."""
    x = make_features(data)[:, 1:]
    y = data["realized_delta"].to_numpy(dtype=np.float64)
    worlds = sorted(data["world_id"].unique().tolist())
    strata_by_world = dict(zip(data["world_id"], data["stratum"]))
    crossfit = np.full(len(data), np.nan, dtype=np.float64)
    fold_rows: list[dict[str, object]] = []
    candidate_names = [f"ridge_{alpha:g}" for alpha in RIDGE_ALPHA] + [
        f"knn_{k}" for k in KNN_K
    ]

    for outer_world in worlds:
        outer_test = np.flatnonzero(data["world_id"].to_numpy() == outer_world)
        training_worlds = [world for world in worlds if world != outer_world]
        outer_train = np.flatnonzero(data["world_id"].to_numpy() != outer_world)
        utilities = {name: [] for name in candidate_names}

        for validation_worlds in grouped_inner_folds(training_worlds, strata_by_world):
            train_mask = ~data["world_id"].isin(validation_worlds | {outer_world}).to_numpy()
            validation_mask = data["world_id"].isin(validation_worlds).to_numpy()
            inner_train = np.flatnonzero(train_mask)
            inner_validation = np.flatnonzero(validation_mask)
            predictions = predict_candidates(x[inner_train], y[inner_train], x[inner_validation])
            for candidate, predicted in predictions.items():
                candidate_world_scores: list[int] = []
                global_prediction = np.full(len(data), np.nan, dtype=np.float64)
                global_prediction[inner_validation] = predicted
                for world in sorted(validation_worlds):
                    world_positions = np.flatnonzero(data["world_id"].to_numpy() == world)
                    gains = [
                        world_gain(world_positions, global_prediction, data, budget)[0]
                        for budget in BUDGETS
                    ]
                    candidate_world_scores.append(sum(gains))
                utilities[candidate].append(float(np.mean(candidate_world_scores)))

        mean_utility = {
            candidate: float(np.mean(values)) for candidate, values in utilities.items()
        }
        chosen = max(candidate_names, key=lambda candidate: mean_utility[candidate])
        fitted = predict_candidates(x[outer_train], y[outer_train], x[outer_test])[chosen]
        crossfit[outer_test] = fitted
        fold_rows.append(
            {
                "heldout_world": int(outer_world),
                "stratum": strata_by_world[outer_world],
                "selected_model": chosen,
                "inner_mean_gain_sum_across_budgets": mean_utility[chosen],
            }
        )

    if np.isnan(crossfit).any():
        raise ValueError("cross-world feature predictions are incomplete")
    result = data[["world_id", "stratum", "episode_id", "domain_id", "query_cost_units", "realized_delta"]].copy()
    result["predicted_delta"] = crossfit
    result["new_domain_id"] = result["domain_id"] >= 1000
    folds = pd.DataFrame(fold_rows).sort_values("heldout_world")
    folds.to_csv(OUT / "feature-ranker-folds.csv", index=False, float_format="%.8f")
    result.to_csv(OUT / "crossworld-feature-predictions.csv", index=False, float_format="%.8f")
    return result, folds


def policy_table(
    data: pd.DataFrame,
    crossworld: pd.DataFrame,
    folds: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    plans = pd.read_csv(RUN / "planning/frozen-router-plans.csv")
    oracle_plans = pd.read_csv(RUN / "planning/evaluation-oracle-plans.csv")
    all_plans = pd.concat((plans, oracle_plans), ignore_index=True)
    delta = data.set_index(["world_id", "episode_id"])["realized_delta"]
    cost = data.set_index(["world_id", "episode_id"])["query_cost_units"]
    world_rows: list[dict[str, object]] = []

    for _, plan in all_plans.groupby(["world_id", "lane", "budget"], sort=False):
        first = plan.iloc[0]
        world, lane, budget = int(first.world_id), first.lane, int(first.budget)
        ids = plan["episode_id"].astype(int).to_list()
        gain = sum(int(delta.loc[(world, episode_id)]) for episode_id in ids)
        paid_cost = sum(int(cost.loc[(world, episode_id)]) for episode_id in ids)
        world_rows.append(
            {
                "policy": lane,
                "world_id": world,
                "stratum": data.loc[data["world_id"] == world, "stratum"].iloc[0],
                "budget": budget,
                "calls": len(ids),
                "realized_gain": gain,
                "paid_cost_units": paid_cost,
            }
        )

    feature_x = make_features(data)
    dev_models = pd.read_csv(RUN / "inputs/development/frozen-models.csv")
    feature_rows = dev_models[dev_models["model"] == "feature_router"]
    weights_by_name = dict(zip(feature_rows["feature_or_domain"], feature_rows["weight"].astype(float)))
    frozen_prediction = feature_x @ np.asarray([weights_by_name[name] for name in FEATURE_NAMES])

    cross_prediction = crossworld["predicted_delta"].to_numpy(dtype=np.float64)
    for world in sorted(data["world_id"].unique()):
        indices = np.flatnonzero(data["world_id"].to_numpy() == world)
        for budget in BUDGETS:
            world_rows.append(
                {
                    "policy": "no_inspection_floor",
                    "world_id": int(world),
                    "stratum": data.loc[data["world_id"] == world, "stratum"].iloc[0],
                    "budget": budget,
                    "calls": 0,
                    "realized_gain": 0,
                    "paid_cost_units": 0,
                }
            )
        for budget in BUDGETS:
            gain, paid_cost = world_gain(indices, cross_prediction, data, budget)
            world_rows.append(
                {
                    "policy": "crossworld_feature_only",
                    "world_id": int(world),
                    "stratum": data.loc[data["world_id"] == world, "stratum"].iloc[0],
                    "budget": budget,
                    "calls": budget,
                    "realized_gain": gain,
                    "paid_cost_units": paid_cost,
                }
            )
    for policy, predictions in [
        ("frozen_feature_positive_stop", frozen_prediction),
        ("crossworld_feature_positive_stop", cross_prediction),
    ]:
        for world in sorted(data["world_id"].unique()):
            indices = np.flatnonzero(data["world_id"].to_numpy() == world)
            positive = indices[predictions[indices] > 0.0]
            score = predictions[positive] / data.iloc[positive]["query_cost_units"].to_numpy()
            order = np.lexsort(
                (data.iloc[positive]["episode_id"].to_numpy(dtype=np.int64), -score)
            )
            picked = positive[order[:64]]
            world_rows.append(
                {
                    "policy": policy,
                    "world_id": int(world),
                    "stratum": data.loc[data["world_id"] == world, "stratum"].iloc[0],
                    "budget": "positive_only_max64",
                    "calls": len(picked),
                    "realized_gain": int(data.iloc[picked]["realized_delta"].sum()),
                    "paid_cost_units": int(data.iloc[picked]["query_cost_units"].sum()),
                }
            )

    world_table = pd.DataFrame(world_rows)
    world_table.to_csv(OUT / "world-policy-results.csv", index=False)
    fixed = world_table[world_table["budget"].isin(BUDGETS)].copy()
    summary_rows: list[dict[str, object]] = []
    for (policy, budget), group in fixed.groupby(["policy", "budget"]):
        oracle_values = fixed[(fixed["policy"] == "evaluation_oracle") & (fixed["budget"] == budget)][
            "realized_gain"
        ]
        mean_oracle = float(oracle_values.mean()) if len(oracle_values) else 0.0
        values = group["realized_gain"].to_numpy(dtype=np.float64)
        summary_rows.append(
            {
                "policy": policy,
                "budget": int(budget),
                "calls_total": int(group["calls"].sum()),
                "mean_calls_per_world": group["calls"].mean(),
                "total_realized_gain": int(group["realized_gain"].sum()),
                "mean_gain_per_world": values.mean(),
                "se_gain_per_world": values.std(ddof=1) / math.sqrt(len(values)),
                "mean_paid_cost_per_world": group["paid_cost_units"].mean(),
                "oracle_mean_gain_per_world": mean_oracle,
                "mean_gain_capture": values.mean() / mean_oracle if mean_oracle > 0 else np.nan,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values(["budget", "policy"])
    summary.to_csv(OUT / "feature-only-ceiling.csv", index=False, float_format="%.8f")

    stopping = world_table[world_table["budget"] == "positive_only_max64"].copy()
    stopping = (
        stopping.groupby("policy", as_index=False)
        .agg(
            mean_calls_per_world=("calls", "mean"),
            zero_call_worlds=("calls", lambda values: int((values == 0).sum())),
            mean_realized_gain_per_world=("realized_gain", "mean"),
            total_realized_gain=("realized_gain", "sum"),
            mean_cost_units_per_world=("paid_cost_units", "mean"),
        )
    )
    stopping.to_csv(OUT / "positive-value-stop-diagnostic.csv", index=False, float_format="%.8f")
    return world_table, summary, stopping


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def interpolate_color(value: float, low: float, high: float) -> tuple[int, int, int]:
    fraction = 0.0 if high <= low else min(1.0, max(0.0, (value - low) / (high - low)))
    start = np.asarray((48, 114, 164), dtype=np.float64)
    end = np.asarray((225, 122, 47), dtype=np.float64)
    rgb = start * (1.0 - fraction) + end * fraction
    return tuple(int(channel) for channel in rgb)


def calibration_plot(bins: pd.DataFrame, output: Path) -> None:
    panel_w, panel_h = 470, 360
    image = Image.new("RGB", (panel_w * 4 + 100, panel_h * 2 + 120), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font = load_font(28, True)
    panel_font = load_font(18, True)
    axis_font = load_font(14)
    draw.text((28, 18), "Frozen E007 router: predicted value, realized value, and price", fill=(25, 35, 45), font=title_font)
    draw.text((30, 58), "X=predicted Δ; Y=realized Δ; color=mean query price. Bins use development quantiles; final panel circles=development, squares=held-out.", fill=(75, 85, 95), font=axis_font)

    panels = [
        ("all_heldout", "All held-out episodes"),
        ("reliability_shift", "Reliability-shift stratum"),
        ("stale_sources_stratum", "Stale-sources stratum"),
        ("unseen_domain_ids", "Unseen domain IDs"),
        ("familiar_domain_ids", "Familiar domain IDs"),
        ("source_stale", "Actual source is stale"),
        ("source_fresh", "Actual source is fresh"),
        ("development_vs_heldout", "Development vs held-out"),
    ]
    costs = bins["mean_query_cost_units"].to_numpy(dtype=np.float64)
    cost_low, cost_high = float(np.nanmin(costs)), float(np.nanmax(costs))
    pred_min = float(bins["mean_predicted_delta"].min())
    pred_max = float(bins["mean_predicted_delta"].max())
    x_low = min(-0.02, pred_min - 0.03)
    x_high = max(0.02, pred_max + 0.03)
    y_low, y_high = -1.0, 1.0

    for panel_index, (slice_name, label) in enumerate(panels):
        row, column = divmod(panel_index, 4)
        left = 24 + column * panel_w
        top = 96 + row * panel_h
        plot_left, plot_top = left + 72, top + 42
        plot_right, plot_bottom = left + panel_w - 24, top + panel_h - 58
        draw.text((left + 12, top + 8), label, fill=(30, 40, 50), font=panel_font)
        for tick in range(5):
            x_value = x_low + (x_high - x_low) * tick / 4
            x = plot_left + (plot_right - plot_left) * tick / 4
            draw.line((x, plot_top, x, plot_bottom), fill=(225, 229, 233), width=1)
            draw.text((x - 24, plot_bottom + 8), f"{x_value:.2f}", fill=(70, 80, 90), font=axis_font)
            y_value = y_low + (y_high - y_low) * tick / 4
            y = plot_bottom - (plot_bottom - plot_top) * tick / 4
            draw.line((plot_left, y, plot_right, y), fill=(225, 229, 233), width=1)
            draw.text((left + 22, y - 8), f"{y_value:.1f}", fill=(70, 80, 90), font=axis_font)
        draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline=(95, 105, 115), width=1)
        diagonal_points = []
        for value in np.linspace(max(x_low, y_low), min(x_high, y_high), 30):
            px = plot_left + (value - x_low) / (x_high - x_low) * (plot_right - plot_left)
            py = plot_bottom - (value - y_low) / (y_high - y_low) * (plot_bottom - plot_top)
            diagonal_points.append((int(px), int(py)))
        if len(diagonal_points) > 1:
            draw.line(diagonal_points, fill=(125, 130, 135), width=2)
        panel = bins[bins["slice"].eq(slice_name)]
        for _, point in panel.iterrows():
            px = plot_left + (point.mean_predicted_delta - x_low) / (x_high - x_low) * (plot_right - plot_left)
            py = plot_bottom - (point.mean_realized_delta - y_low) / (y_high - y_low) * (plot_bottom - plot_top)
            se = 1.96 * float(point.realized_delta_se)
            y_top = plot_bottom - (min(y_high, point.mean_realized_delta + se) - y_low) / (y_high - y_low) * (plot_bottom - plot_top)
            y_bot = plot_bottom - (max(y_low, point.mean_realized_delta - se) - y_low) / (y_high - y_low) * (plot_bottom - plot_top)
            color = interpolate_color(float(point.mean_query_cost_units), cost_low, cost_high)
            draw.line((px, y_top, px, y_bot), fill=color, width=2)
            draw.line((px - 4, y_top, px + 4, y_top), fill=color, width=2)
            draw.line((px - 4, y_bot, px + 4, y_bot), fill=color, width=2)
            radius = 4 + min(4, int(math.log2(max(1, point.episodes)) / 2))
            if slice_name == "development_vs_heldout" and point.cohort == "heldout":
                draw.rectangle((px - radius, py - radius, px + radius, py + radius), fill=color, outline=(35, 45, 55), width=1)
            else:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color, outline=(35, 45, 55), width=1)
        draw.text((plot_left + 55, plot_bottom + 31), "Predicted Δ", fill=(45, 55, 65), font=axis_font)

    # Compact price color scale shared by every calibration facet.
    legend_y = image.height - 34
    legend_x = image.width - 360
    draw.text((legend_x - 115, legend_y - 2), "Mean query price", fill=(45, 55, 65), font=axis_font)
    for step in range(160):
        color = interpolate_color(cost_low + (cost_high - cost_low) * step / 159, cost_low, cost_high)
        draw.line((legend_x + step, legend_y, legend_x + step, legend_y + 14), fill=color, width=1)
    draw.text((legend_x, legend_y + 16), f"{cost_low:.1f}", fill=(45, 55, 65), font=axis_font)
    draw.text((legend_x + 132, legend_y + 16), f"{cost_high:.1f} cost units", fill=(45, 55, 65), font=axis_font)
    image.save(output, optimize=True)


def unresolved_plot(by_world: pd.DataFrame, output: Path) -> None:
    width, height = 1680, 850
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, panel_font, axis_font = load_font(28, True), load_font(18, True), load_font(15)
    draw.text((30, 20), "Unresolved inspection outcomes at 64 calls/world", fill=(25, 35, 45), font=title_font)
    draw.text((32, 60), "Stacked by source status and whether the active action was already correct.", fill=(75, 85, 95), font=axis_font)
    categories = [
        ("unknown_baseline_right", "Unknown · baseline right", (70, 130, 180)),
        ("failed_baseline_right", "Failed · baseline right", (55, 160, 145)),
        ("unknown_baseline_wrong", "Unknown · baseline wrong", (225, 145, 70)),
        ("failed_baseline_wrong", "Failed · baseline wrong", (195, 90, 70)),
    ]
    strata = ["familiar_ids", "new_ids", "reliability_shift", "stale_sources"]
    panel_w, panel_h = 790, 340
    maximum = max(
        int(by_world.loc[by_world["stratum"].eq(stratum), [column for column, _, _ in categories]].sum(axis=1).max())
        for stratum in strata
    )
    y_max = max(20, int(math.ceil(maximum / 5) * 5))
    for index, stratum in enumerate(strata):
        row, column = divmod(index, 2)
        left, top = 32 + column * 820, 105 + row * 350
        plot_left, plot_top = left + 72, top + 38
        plot_right, plot_bottom = left + panel_w - 20, top + panel_h - 52
        draw.text((left + 2, top + 6), stratum.replace("_", " "), fill=(30, 40, 50), font=panel_font)
        for tick in range(5):
            y_val = y_max * tick / 4
            y = plot_bottom - (plot_bottom - plot_top) * tick / 4
            draw.line((plot_left, y, plot_right, y), fill=(225, 229, 233), width=1)
            draw.text((left + 22, y - 8), f"{y_val:.0f}", fill=(70, 80, 90), font=axis_font)
        group = by_world[by_world["stratum"].eq(stratum)].sort_values("world_id")
        gap = (plot_right - plot_left) / max(1, len(group))
        bar_w = min(68, gap * 0.55)
        for world_index, (_, item) in enumerate(group.iterrows()):
            x_center = plot_left + gap * (world_index + 0.5)
            bottom = plot_bottom
            total = 0
            for column_name, _, color in categories:
                value = int(item[column_name])
                total += value
                bar_h = (plot_bottom - plot_top) * value / y_max
                draw.rectangle((x_center - bar_w / 2, bottom - bar_h, x_center + bar_w / 2, bottom), fill=color)
                bottom -= bar_h
            draw.text((x_center - 20, plot_bottom + 8), str(int(item.world_id)), fill=(60, 70, 80), font=axis_font)
            draw.text((x_center - 16, max(plot_top, bottom - 22)), str(total), fill=(35, 45, 55), font=axis_font)
        draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline=(95, 105, 115), width=1)

    legend_x, legend_y = 62, height - 38
    for column_name, label, color in categories:
        draw.rectangle((legend_x, legend_y, legend_x + 18, legend_y + 18), fill=color)
        draw.text((legend_x + 25, legend_y - 1), label, fill=(45, 55, 65), font=axis_font)
        legend_x += 390
    image.save(output, optimize=True)


def ceiling_plot(summary: pd.DataFrame, output: Path) -> None:
    width, height = 1450, 900
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, axis_font, legend_font = load_font(30, True), load_font(17), load_font(17)
    draw.text((36, 24), "Cross-world feature-only ranking versus the E007 oracle", fill=(25, 35, 45), font=title_font)
    draw.text((38, 68), "Y: mean net completions gained per world. Outer leave-one-world-out predictions; exploratory, not a runtime result.", fill=(75, 85, 95), font=axis_font)
    plot_left, plot_top, plot_right, plot_bottom = 130, 145, 1330, 735
    x_values = np.asarray([0, 16, 32, 64], dtype=np.float64)
    y_values = summary["mean_gain_per_world"].to_numpy(dtype=np.float64)
    err = 1.96 * summary["se_gain_per_world"].to_numpy(dtype=np.float64)
    low = min(-25.0, float(np.nanmin(y_values - err)) - 3.0)
    high = max(55.0, float(np.nanmax(y_values + err)) + 3.0)
    low = math.floor(low / 10) * 10
    high = math.ceil(high / 10) * 10

    def px(x: float) -> float:
        return plot_left + x / 64.0 * (plot_right - plot_left)

    def py(y: float) -> float:
        return plot_bottom - (y - low) / (high - low) * (plot_bottom - plot_top)

    for tick in range(6):
        y = low + (high - low) * tick / 5
        yy = py(y)
        draw.line((plot_left, yy, plot_right, yy), fill=(225, 229, 233), width=1)
        draw.text((82, yy - 10), f"{y:.0f}", fill=(65, 75, 85), font=axis_font)
    for x in x_values:
        xx = px(x)
        draw.line((xx, plot_top, xx, plot_bottom), fill=(235, 238, 241), width=1)
        draw.text((xx - 12, plot_bottom + 12), f"{int(x)}", fill=(65, 75, 85), font=axis_font)
    zero_y = py(0.0)
    draw.line((plot_left, zero_y, plot_right, zero_y), fill=(120, 125, 130), width=2)
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline=(95, 105, 115), width=1)
    draw.text((plot_left + 360, plot_bottom + 55), "Maximum paid queries per world", fill=(45, 55, 65), font=axis_font)

    colors = {
        "feature_router": (65, 105, 160),
        "matched_random": (120, 130, 140),
        "crossworld_feature_only": (45, 150, 125),
        "evaluation_oracle": (210, 115, 55),
        "no_inspection_floor": (50, 55, 60),
    }
    labels = {
        "feature_router": "Frozen E007 feature router",
        "matched_random": "Matched random",
        "crossworld_feature_only": "Cross-world feature-only estimate",
        "evaluation_oracle": "Full-information oracle",
        "no_inspection_floor": "No-inspection floor",
    }
    zero_x, zero_y_value = px(0), py(0)
    for policy in labels:
        subset = summary[summary["policy"].eq(policy)].sort_values("budget")
        points = [(zero_x, zero_y_value)]
        if not subset.empty:
            for _, item in subset.iterrows():
                budget = int(item.budget)
                mean = float(item.mean_gain_per_world)
                se = 1.96 * float(item.se_gain_per_world)
                xx, yy = px(budget), py(mean)
                cap_top, cap_bottom = py(min(high, mean + se)), py(max(low, mean - se))
                draw.line((xx, cap_top, xx, cap_bottom), fill=colors[policy], width=2)
                draw.line((xx - 5, cap_top, xx + 5, cap_top), fill=colors[policy], width=2)
                draw.line((xx - 5, cap_bottom, xx + 5, cap_bottom), fill=colors[policy], width=2)
                points.append((xx, yy))
            draw.line(points, fill=colors[policy], width=3)
            for xx, yy in points:
                draw.ellipse((xx - 6, yy - 6, xx + 6, yy + 6), fill=colors[policy], outline=(35, 45, 55), width=1)

    legend_positions = {
        "feature_router": (65, 835),
        "matched_random": (470, 835),
        "crossworld_feature_only": (795, 835),
        "evaluation_oracle": (405, 870),
        "no_inspection_floor": (790, 870),
    }
    for policy, (legend_x, legend_y) in legend_positions.items():
        draw.line((legend_x, legend_y + 10, legend_x + 30, legend_y + 10), fill=colors[policy], width=4)
        draw.ellipse((legend_x + 11, legend_y + 4, legend_x + 23, legend_y + 16), fill=colors[policy])
        draw.text((legend_x + 38, legend_y), labels[policy], fill=(45, 55, 65), font=legend_font)
    image.save(output, optimize=True)


def build_report(
    data: pd.DataFrame,
    by_world: pd.DataFrame,
    reconciled_summary: pd.DataFrame,
    calibration: pd.DataFrame,
    ceiling: pd.DataFrame,
    folds: pd.DataFrame,
    stopping: pd.DataFrame,
) -> str:
    overall = reconciled_summary[reconciled_summary["stratum"].eq("overall")].iloc[0]
    unknown_base_right = int(overall.unknown_baseline_right)
    unknown_base_wrong = int(overall.unknown_baseline_wrong)
    failed_base_right = int(overall.failed_baseline_right)
    failed_base_wrong = int(overall.failed_baseline_wrong)
    negative_prediction_counts = data.groupby("cohort")["predicted_delta"].apply(
        lambda values: int((values < 0).sum())
    )
    feature_64 = ceiling[(ceiling["policy"] == "feature_router") & (ceiling["budget"] == 64)].iloc[0]
    random_64 = ceiling[(ceiling["policy"] == "matched_random") & (ceiling["budget"] == 64)].iloc[0]
    feature_mean_query_cost = (
        float(feature_64.mean_paid_cost_per_world) * 16 / int(feature_64.calls_total)
    )
    random_mean_query_cost = (
        float(random_64.mean_paid_cost_per_world) * 16 / int(random_64.calls_total)
    )
    feature_total_cost = int(round(float(feature_64.mean_paid_cost_per_world) * 16))
    random_total_cost = int(round(float(random_64.mean_paid_cost_per_world) * 16))
    score_cols = [
        "cohort",
        "score_bin",
        "episodes",
        "mean_predicted_delta",
        "mean_realized_delta",
        "mean_query_cost_units",
        "unknown_rate",
        "failed_rate",
    ]
    lines = [
        "# E007 post-hoc autopsy v1",
        "",
        f"Source run: `{RUN_ID}`. This analysis reads the sealed E007 run and writes only under `analysis/e007-autopsy-v1/`.",
        "",
        "**Status: exploratory and outcome-conditioned.** Held-out labels and source replies are used below for reconciliation, calibration, and cross-world diagnostics. None of these estimates are runtime evidence or a promotion result.",
        "",
        "## 64-call completion reconciliation",
        "",
        f"The full held-out feature-router lane reconciles exactly: `{int(overall.wrong_to_right)} - {int(overall.right_to_wrong)} - {int(overall.unresolved_baseline_right)} = {int(overall.completion_gain)}` net completions. Residual is zero in every world and stratum.",
        "",
        f"Unresolved outcomes split into **Unknown**: {unknown_base_right} baseline-right and {unknown_base_wrong} baseline-wrong; **Failed**: {failed_base_right} baseline-right and {failed_base_wrong} baseline-wrong. Thus {unknown_base_right + failed_base_right} previously correct tasks were stranded, while {unknown_base_wrong + failed_base_wrong} unresolved cases avoided a wrong commit. Those avoided commits are safety outcomes and contribute zero completions relative to the zero-query floor.",
        "",
        "### By stratum",
        "",
        "| Stratum | W→R | R→W | U right | U wrong | F right | F wrong | Avoided wrong commits | Net gain | Residual |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in reconciled_summary[reconciled_summary["stratum"].ne("overall")].iterrows():
        lines.append(
            f"| {row.stratum} | {int(row.wrong_to_right)} | {int(row.right_to_wrong)} | {int(row.unknown_baseline_right)} | {int(row.unknown_baseline_wrong)} | {int(row.failed_baseline_right)} | {int(row.failed_baseline_wrong)} | {int(row.avoided_wrong_commits)} | {int(row.completion_gain)} | {int(row.residual)} |"
        )
    lines.extend(
        [
            "",
            "`world-reconciliation.csv` gives the same decomposition for all 16 worlds. `unresolved-breakdown.png` shows the four Unknown/Failed × baseline-right/wrong components per world.",
            "",
            "## Frozen predicted value, realized value, and query price",
            "",
            "The frozen E007 development model predicts completion delta from the original eight features. Its selection score is predicted delta divided by query cost. Score-bin cut points are derived from development score quantiles and reused for held-out worlds, so the cohort rows are directly comparable. Held-out slices use hidden status only for post-hoc grouping. Unknown and Failed rates describe the stored reply if queried, including episodes the router did not select. Whiskers use standard errors across worlds, not individual episodes.",
            "",
            "| Cohort | Development score bin | Episodes | Mean predicted Δ | Mean realized Δ | Mean query cost | Unknown rate | Failed rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, row in calibration[score_cols].iterrows():
        lines.append(
            f"| {row.cohort} | {int(row.score_bin)} | {int(row.episodes)} | {row.mean_predicted_delta:.4f} | {row.mean_realized_delta:.4f} | {row.mean_query_cost_units:.2f} | {row.unknown_rate:.3f} | {row.failed_rate:.3f} |"
        )
    lines.extend(
        [
            "",
            "![Frozen router calibration by score bin, reliability, stale-source status, unseen IDs, and price](value-calibration-price.png)",
            "",
            "See `score-calibration.csv` for held-out bins split by reliability-shift and stale-source strata, actual stale/fresh source status, and unseen/familiar domain IDs. `episode-value-diagnostics.csv` contains the post-hoc per-episode prediction, price, typed result, and realized completion delta for development and held-out rows.",
            "",
            f"The frozen scorer predicted negative net completion delta for {int(negative_prediction_counts.get('development', 0))}/2,048 development episodes and {int(negative_prediction_counts.get('heldout', 0))}/6,144 held-out episodes. At the exact 64-call cap, the feature router bought {int(feature_64.calls_total)} inspections for {feature_total_cost} cost units total ({feature_mean_query_cost:.2f}/query), versus {int(random_64.calls_total)} matched-random calls for {random_total_cost} units ({random_mean_query_cost:.2f}/query). Since the router ranks `predicted_delta / price` in descending order, dividing a negative estimate by a larger price moves its score toward zero and can rank a more expensive query above a cheaper one. This score ordering explains the elevated spend; the exact-call budget made it impossible to stop at zero.",
            "",
            "For the next policy specification, treat each query budget as a maximum. A router needs a calibrated net-value-after-price-and-unresolved-risk estimate and must permit zero calls when that estimate is negative. This autopsy does not alter the sealed runtime.",
            "",
            "## Cross-world feature-only ranking estimate",
            "",
            "For each held-out world, an outer leave-one-world-out fold holds all 384 of its outcomes out. The other 15 worlds supply exploratory training data. Three inner world-group folds select among standardized ridge regressors and uniform K-nearest-neighbor regressors; each candidate ranks by predicted completion delta divided by public query price. The best candidate on inner-world mean completion gain is refit on the other 15 worlds and scored on the untouched outer world.",
            "",
            "This estimates transfer available to the eight public features under the tested model families. It is not a mathematical feature-information ceiling: other estimators could do better, and the development-world training boundary is intentionally relaxed for this post-hoc diagnostic only.",
            "",
            "| Max queries/world | No-inspection floor | Frozen E007 feature | Matched random | Cross-world feature-only | Full-information oracle |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for budget in BUDGETS:
        values: dict[str, float] = {}
        for policy in ("no_inspection_floor", "feature_router", "matched_random", "crossworld_feature_only", "evaluation_oracle"):
            row = ceiling[(ceiling["policy"] == policy) & (ceiling["budget"] == budget)]
            values[policy] = float(row.iloc[0].mean_gain_per_world) if not row.empty else float("nan")
        lines.append(
            f"| {budget} | {values['no_inspection_floor']:.2f} | {values['feature_router']:.2f} | {values['matched_random']:.2f} | {values['crossworld_feature_only']:.2f} | {values['evaluation_oracle']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"The inner folds selected {folds['selected_model'].value_counts().to_dict()} across 16 outer worlds. The cross-world ranker uses held-out labels from other worlds, so its results are an exploratory estimate of feature signal, not an independent replication. Within the tested ridge/KNN families, feature-only ranking stays below the zero-call floor at all three exact budgets while the full-information oracle is positive. This evidence argues against another ridge-weight tweak. Other estimators may extract more value from these features.",
            "",
            "![World-held-out feature-only ranking compared with the frozen router and full-information oracle](feature-only-ceiling.png)",
            "",
            "## Zero-call stopping diagnostic",
            "",
            "As a diagnostic of removing forced spending, each frozen or cross-world estimate selects only episodes with predicted completion delta above zero, ranked by prediction/query-cost, capped at 64 per world. The frozen scorer makes zero calls; the cross-world fit makes only three calls across all 16 worlds and loses two completions. No completion-to-cost exchange rate is specified here, so this tests the sign gate and cost ordering only; it does not claim net economic optimality.",
            "",
            "| Diagnostic policy | Mean calls/world | Worlds with zero calls | Mean realized gain/world | Total gain | Mean cost units/world |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for _, row in stopping.iterrows():
        lines.append(
            f"| {row.policy} | {row.mean_calls_per_world:.2f} | {int(row.zero_call_worlds)} | {row.mean_realized_gain_per_world:.2f} | {int(row.total_realized_gain)} | {row.mean_cost_units_per_world:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "E007’s deterministic authority and paid-query recovery result remains intact. The inspection policy regressed completion because harmful contradictions and unresolved results outweighed corrections. This autopsy does not specify a second evidence path or a new lifecycle. That design question remains open until the breakdown above identifies recoverable unresolved cases.",
            "",
            "The bank has 16 held-out worlds with 384 episodes each. Outcome-conditioned feature fitting uses 15 held-out worlds to predict the remaining world and rotates across all worlds. Results describe these generators and feature semantics only.",
            "",
        ]
    )
    return "\n".join(lines)


def write_analysis_manifest() -> None:
    input_paths = [
        RUN / "manifest.json",
        RUN / "inputs/development/public.csv",
        RUN / "inputs/development/labels.csv",
        RUN / "inputs/development/source-state.csv",
        RUN / "inputs/heldout/public.csv",
        RUN / "inputs/heldout/labels.csv",
        RUN / "inputs/heldout/source-state.csv",
        RUN / "inputs/development/frozen-models.csv",
        RUN / "run-trace.csv",
        RUN / "planning/frozen-router-plans.csv",
        RUN / "planning/evaluation-oracle-plans.csv",
    ]
    implementation_sources = [
        PROJECT / "src/domain.rs",
        PROJECT / "src/evaluation.rs",
        PROJECT / "src/model.rs",
        PROJECT / "src/routing.rs",
        PROJECT / "src/runtime.rs",
        Path(r"C:\rd-c\rdc-runtime-contracts-v1\src\inspection.rs"),
    ]
    outputs = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "analysis-manifest.json")
    value = {
        "analysis": "RDC-C-E007-AUTOPSY-v1",
        "source_run_id": RUN_ID,
        "source_run_read_only": True,
        "status": "exploratory_outcome_conditioned_not_runtime_evidence",
        "analysis_script_sha256": sha256(Path(__file__)),
        "inputs_sha256": {str(path.relative_to(RUN)).replace("\\", "/"): sha256(path) for path in input_paths},
        "implementation_sources_sha256": {str(path): sha256(path) for path in implementation_sources},
        "outputs_sha256": {path.name: sha256(path) for path in outputs},
    }
    (OUT / "analysis-manifest.json").write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    development, heldout, weights = load_episode_data()
    selected = verify_selected_traces(heldout)
    by_world, reconciliation = reconcile(selected)
    by_world.to_csv(OUT / "world-reconciliation.csv", index=False)
    reconciliation.to_csv(OUT / "stratum-reconciliation.csv", index=False)
    calibration_data = pd.concat([development, heldout], ignore_index=True, sort=False)
    bins, cohort_comparison = score_calibration(calibration_data)
    crossworld, folds = fit_crossworld_feature_ranker(heldout)
    world_policies, ceiling, stopping = policy_table(heldout, crossworld, folds)
    ceiling_plot(ceiling, OUT / "feature-only-ceiling.png")
    calibration_plot(bins, OUT / "value-calibration-price.png")
    unresolved_plot(by_world, OUT / "unresolved-breakdown.png")
    report = build_report(calibration_data, by_world, reconciliation, cohort_comparison, ceiling, folds, stopping)
    (OUT / "autopsy-report.md").write_text(report, encoding="utf-8")
    write_analysis_manifest()
    print(f"Autopsy complete: {RUN_ID}; {len(heldout)} held-out episodes; {len(folds)} outer folds.")
    print(f"Feature weights: {weights}")
    print(f"Report: {OUT / 'autopsy-report.md'}")


if __name__ == "__main__":
    main()
