from __future__ import annotations

import hashlib
import math
from typing import Iterable

import numpy as np
import pandas as pd

from contracts import CONTINUOUS_GEOMETRY, GEOMETRY_DIMENSIONS


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "little")


def prepare_cohort(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    result = frame.copy()
    result["direction_label"] = result["direction"].map({1: "FROM_BELOW", -1: "FROM_ABOVE"}).fillna("UNKNOWN")
    result["attempt_number_bucket"] = result["ordinal"].map(
        lambda value: "UNKNOWN" if pd.isna(value) else str(int(value)) if int(value) <= 3 else "4+"
    )
    result["node_width_bucket"] = pd.cut(
        pd.to_numeric(result["node_width_atr"], errors="coerce"),
        [-np.inf, .1, .25, .5, 1, np.inf],
        labels=["<=0.10", "(0.10,0.25]", "(0.25,0.50]", "(0.50,1.00]", ">1.00"],
    )
    result["node_age_bucket"] = pd.cut(
        pd.to_numeric(result.get("node_age_seconds"), errors="coerce") / 3600,
        [-np.inf, 1, 4, 12, 24, 72, np.inf],
        labels=["<=1h", "(1h,4h]", "(4h,12h]", "(12h,24h]", "(1d,3d]", ">3d"],
    )
    result["sigma_bucket"] = pd.cut(
        pd.to_numeric(result["start_median_sigma"], errors="coerce"),
        [-np.inf, -2, -1, -.5, .5, 1, 2, np.inf],
        labels=["<-2", "[-2,-1)", "[-1,-.5)", "[-.5,.5)", "[.5,1)", "[1,2)", ">=2"],
        right=False,
    )
    up = pd.to_numeric(result["corridor_up_atr"], errors="coerce")
    down = pd.to_numeric(result["corridor_down_atr"], errors="coerce")
    result["nearest_corridor_atr"] = pd.concat([up, down], axis=1).min(axis=1, skipna=True)
    result["corridor_bucket"] = pd.cut(
        result["nearest_corridor_atr"], [-np.inf, .25, .5, 1, 2, np.inf],
        labels=["<=0.25", "(0.25,0.50]", "(0.50,1.00]", "(1.00,2.00]", ">2.00"],
    )
    start = pd.to_numeric(result["start"], errors="coerce")
    hour = ((start % 86400) // 3600).astype("Int64")
    result["server_hour"] = hour
    result["server_time_bucket"] = hour.map(
        lambda value: "UNKNOWN" if pd.isna(value) else f"{(int(value)//4)*4:02d}-{(int(value)//4)*4+3:02d}"
    )
    result["server_hour_sin"] = np.sin(2 * np.pi * pd.to_numeric(hour, errors="coerce") / 24)
    result["server_hour_cos"] = np.cos(2 * np.pi * pd.to_numeric(hour, errors="coerce") / 24)
    if target == "reclaim_given_break":
        landmark = pd.to_numeric(result["break"], errors="coerce")
    elif target == "transit_given_episode_acceptance":
        landmark = pd.to_numeric(result["accepted"], errors="coerce").fillna(
            pd.to_numeric(result["first_acceptance_end"], errors="coerce")
        )
    else:
        landmark = pd.to_numeric(result["contact"], errors="coerce")
    result["eligibility_latency_seconds"] = (landmark - start).clip(lower=0)
    result["target_state"] = np.select(
        [result["target_censored"], result["target_observed"]],
        ["CENSORED", "POSITIVE"], default="NEGATIVE",
    )
    return result


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def cluster_bootstrap_rate(frame: pd.DataFrame, seed: int, repetitions: int = 500) -> tuple[float, float]:
    work = frame[frame["target_analyzable"]].copy()
    if work.empty:
        return math.nan, math.nan
    grouped = work.groupby("run_key")["target_label"].agg(["sum", "count"])
    if len(grouped) < 2:
        value = float(grouped["sum"].sum() / grouped["count"].sum())
        return value, value
    values = grouped[["sum", "count"]].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions)
    for index in range(repetitions):
        sample = values[rng.integers(0, len(values), len(values))]
        draws[index] = sample[:, 0].sum() / sample[:, 1].sum()
    return float(np.quantile(draws, .025)), float(np.quantile(draws, .975))


def rate_rows(frame: pd.DataFrame, target: str, dimensions: Iterable[str] = GEOMETRY_DIMENSIONS) -> pd.DataFrame:
    rows: list[dict] = []
    dimensions = ("OVERALL", *dimensions)
    for dimension in dimensions:
        values = pd.Series("ALL", index=frame.index) if dimension == "OVERALL" else frame[dimension].astype("object")
        values = values.where(values.notna(), "MISSING").astype(str)
        for value, indexes in values.groupby(values).groups.items():
            part = frame.loc[indexes]
            analyzable = part[part["target_analyzable"]]
            positive = int(analyzable["target_label"].sum())
            total = len(analyzable)
            low, high = _wilson(positive, total)
            block_low, block_high = cluster_bootstrap_rate(part, _seed(f"{target}|{dimension}|{value}"))
            rows.append({
                "target": target, "dimension": dimension, "value": value,
                "eligible_count": len(part), "analyzable_count": total,
                "positive_count": positive, "negative_count": total - positive,
                "censored_count": int(part["target_censored"].sum()),
                "rate": positive / total if total else math.nan,
                "wilson_low": low, "wilson_high": high,
                "run_block_bootstrap_low": block_low, "run_block_bootstrap_high": block_high,
                "run_count": part["run_key"].nunique(), "episode_count": part["episode_id"].nunique(),
            })
    return pd.DataFrame(rows)


def continuous_rows(
    frame: pd.DataFrame,
    target: str,
    metrics: Iterable[str] = CONTINUOUS_GEOMETRY,
) -> pd.DataFrame:
    rows = []
    for metric in metrics:
        if metric not in frame:
            continue
        for state, part in frame.groupby("target_state"):
            values = pd.to_numeric(part[metric], errors="coerce").dropna()
            rows.append({
                "target": target, "metric": metric, "target_state": state,
                "rows": len(part), "observed": len(values), "missing": len(part) - len(values),
                "mean": values.mean(), "std": values.std(), "minimum": values.min(),
                "q05": values.quantile(.05), "q25": values.quantile(.25),
                "median": values.quantile(.5), "q75": values.quantile(.75),
                "q95": values.quantile(.95), "maximum": values.max(),
            })
    return pd.DataFrame(rows)


def cumulative_incidence(frame: pd.DataFrame, target: str, maximum_points: int = 80) -> pd.DataFrame:
    work = frame[["target_time_seconds", "target_observed", "target_censored", "target_analyzable"]].copy()
    work["time"] = pd.to_numeric(work["target_time_seconds"], errors="coerce").clip(lower=0)
    work = work.dropna(subset=["time"]).sort_values("time")
    if work.empty:
        return pd.DataFrame()
    survival = 1.0
    cif = 0.0
    rows = []
    for time, at_time in work.groupby("time", sort=True):
        risk = int((work["time"] >= time).sum())
        interest = int(at_time["target_observed"].sum())
        competing = int((at_time["target_analyzable"] & ~at_time["target_observed"]).sum())
        censored = int(at_time["target_censored"].sum())
        if risk:
            cif += survival * interest / risk
            survival *= 1 - (interest + competing) / risk
        rows.append({
            "target": target, "time_seconds": float(time), "risk_set": risk,
            "interest_events": interest, "competing_events": competing,
            "censored": censored, "survival_any_behavior": survival,
            "cumulative_incidence_target": cif,
        })
    result = pd.DataFrame(rows)
    if len(result) > maximum_points:
        indexes = np.unique(np.linspace(0, len(result) - 1, maximum_points).astype(int))
        result = result.iloc[indexes].reset_index(drop=True)
    return result


def _cluster_dependence(frame: pd.DataFrame, cluster: str) -> dict:
    work = frame[frame["target_analyzable"]][[cluster, "target_label"]].dropna()
    groups = work.groupby(cluster)["target_label"]
    sizes = groups.size().astype(float)
    means = groups.mean()
    n, k = len(work), len(sizes)
    if n <= k or k <= 1:
        return {"clusters": k, "rows": n, "mean_cluster_size": sizes.mean(), "icc": math.nan, "effective_n": n}
    grand = float(work["target_label"].mean())
    ms_between = float((sizes * (means - grand) ** 2).sum() / (k - 1))
    joined = work.join(means.rename("cluster_mean"), on=cluster)
    ms_within = float(((joined["target_label"] - joined["cluster_mean"]) ** 2).sum() / (n - k))
    n0 = float((n - (sizes.pow(2).sum() / n)) / (k - 1))
    denominator = ms_between + (n0 - 1) * ms_within
    icc = (ms_between - ms_within) / denominator if denominator > 0 else 0.0
    design = 1 + max(0.0, icc) * (float(sizes.mean()) - 1)
    return {
        "clusters": k, "rows": n, "mean_cluster_size": float(sizes.mean()),
        "median_cluster_size": float(sizes.median()), "maximum_cluster_size": int(sizes.max()),
        "icc": float(icc), "design_effect": design, "effective_n": n / design,
    }


def dependence_rows(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"target": target, "cluster_unit": unit, **_cluster_dependence(frame, unit)}
        for unit in ("run_key", "episode_id")
    ])


def transition_audit(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = events.sort_values(["run_key", "episode_id", "timestamp", "event_sequence"]).copy()
    grouped = order.groupby(["run_key", "episode_id"], dropna=False)
    order["next_event"] = grouped["event_type"].shift(-1)
    transitions = order.dropna(subset=["next_event"])
    counts = transitions.groupby(["event_type", "next_event"], as_index=False).size().rename(columns={"size": "count"})
    counts["source_total"] = counts.groupby("event_type")["count"].transform("sum")
    counts["probability"] = counts["count"] / counts["source_total"]
    run_counts = transitions.groupby(["run_key", "event_type", "next_event"], as_index=False).size()
    stability = []
    for source, part in run_counts.groupby("event_type"):
        destinations = sorted(part["next_event"].unique())
        vectors = []
        for _, run in part.groupby("run_key"):
            values = run.set_index("next_event")["size"].reindex(destinations, fill_value=0).to_numpy(float)
            vectors.append(values / values.sum())
        matrix = np.vstack(vectors)
        pooled = matrix.mean(axis=0)
        jsd = []
        for values in matrix:
            midpoint = (values + pooled) / 2
            left = np.sum(values[values > 0] * np.log2(values[values > 0] / midpoint[values > 0]))
            mask = pooled > 0
            right = np.sum(pooled[mask] * np.log2(pooled[mask] / midpoint[mask]))
            jsd.append((left + right) / 2)
        stability.append({
            "event_type": source, "runs": len(vectors), "destinations": len(destinations),
            "transitions": int(part["size"].sum()), "mean_run_jsd_bits": float(np.mean(jsd)),
            "max_run_jsd_bits": float(np.max(jsd)),
        })
    return counts, pd.DataFrame(stability)
