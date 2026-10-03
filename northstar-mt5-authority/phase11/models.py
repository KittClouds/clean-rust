from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from contracts import CATEGORICAL_FEATURES, MODEL_GATE, NUMERIC_FEATURES


def sigmoid(values: np.ndarray) -> np.ndarray:
    result = np.empty_like(values, dtype=float)
    positive = values >= 0
    result[positive] = 1 / (1 + np.exp(-values[positive]))
    exp = np.exp(values[~positive])
    result[~positive] = exp / (1 + exp)
    return result


def log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    p = np.clip(probabilities, 1e-12, 1 - 1e-12)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positives = int(labels.sum())
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return math.nan
    order = np.argsort(-scores, kind="stable")
    y, s = labels[order], scores[order]
    boundaries = np.r_[np.flatnonzero(np.diff(s)), len(s) - 1]
    tp = np.r_[0, np.cumsum(y)[boundaries]] / positives
    fp = np.r_[0, np.cumsum(1 - y)[boundaries]] / negatives
    return float(np.trapezoid(tp, fp))


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    positives = int(labels.sum())
    if positives == 0:
        return math.nan
    order = np.argsort(-scores, kind="stable")
    y = labels[order]
    precision = np.cumsum(y) / np.arange(1, len(y) + 1)
    return float((precision * y).sum() / positives)


def calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    if len(labels) == 0:
        return math.nan
    order = np.argsort(probabilities)
    error = 0.0
    for indexes in np.array_split(order, min(bins, len(order))):
        if len(indexes):
            error += len(indexes) / len(labels) * abs(float(labels[indexes].mean() - probabilities[indexes].mean()))
    return error


def metric_row(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    return {
        "rows": len(labels), "positives": int(labels.sum()), "negatives": int(len(labels) - labels.sum()),
        "prevalence": float(labels.mean()), "log_loss": log_loss(labels, probabilities),
        "brier": float(np.mean((labels - probabilities) ** 2)), "auc": auc(labels, probabilities),
        "average_precision": average_precision(labels, probabilities),
        "ece_10": calibration_error(labels, probabilities),
    }


@dataclass
class Preprocessor:
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    missing_indicators: set[str]
    levels: dict[str, tuple[str, ...]]
    names: tuple[str, ...]

    @classmethod
    def fit(cls, frame: pd.DataFrame, minimum_category_count: int = 10) -> "Preprocessor":
        numeric = []
        medians, means, scales = {}, {}, {}
        missing_indicators: set[str] = set()
        names = []
        for column in NUMERIC_FEATURES:
            if column not in frame:
                continue
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.notna().mean() < 1 - MODEL_GATE.maximum_missing_feature_share:
                continue
            median = float(values.median()) if values.notna().any() else 0.0
            filled = values.fillna(median).to_numpy(dtype=float)
            mean, scale = float(filled.mean()), float(filled.std())
            if not np.isfinite(scale) or scale < 1e-12:
                continue
            numeric.append(column)
            medians[column], means[column], scales[column] = median, mean, scale
            names.append(column)
            if values.isna().any():
                missing_indicators.add(column)
                names.append(f"{column}__MISSING")
        levels = {}
        categorical = []
        for column in CATEGORICAL_FEATURES:
            if column not in frame:
                continue
            values = frame[column].fillna("<MISSING>").astype(str)
            counts = values.value_counts()
            kept = sorted(counts[counts >= minimum_category_count].index)
            if len(kept) < 2:
                continue
            categorical.append(column)
            encoded_levels = tuple(kept[1:] + (["<OTHER>"] if int(counts[counts < minimum_category_count].sum()) else []))
            levels[column] = encoded_levels
            names.extend(f"{column}=={value}" for value in encoded_levels)
        return cls(
            tuple(numeric), tuple(categorical), medians, means, scales,
            missing_indicators, levels, tuple(names),
        )

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        columns = []
        for name in self.numeric:
            raw = pd.to_numeric(frame[name], errors="coerce")
            columns.append(((raw.fillna(self.medians[name]).to_numpy(float) - self.means[name]) / self.scales[name]))
            if name in self.missing_indicators:
                columns.append(raw.isna().to_numpy(float))
        for name in self.categorical:
            raw = frame[name].fillna("<MISSING>").astype(str)
            known = {level for level in self.levels[name] if level != "<OTHER>"}
            for level in self.levels[name]:
                if level == "<OTHER>":
                    columns.append((~raw.isin(known)).to_numpy(float))
                else:
                    columns.append(raw.eq(level).to_numpy(float))
        return np.column_stack(columns) if columns else np.empty((len(frame), 0), dtype=float)


@dataclass
class RidgeLogit:
    penalty: float = 1.0
    maximum_iterations: int = 60
    coefficients: np.ndarray | None = None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "RidgeLogit":
        x = np.column_stack([np.ones(len(features)), features])
        prevalence = np.clip(labels.mean(), 1e-6, 1 - 1e-6)
        beta = np.zeros(x.shape[1])
        beta[0] = math.log(prevalence / (1 - prevalence))
        ridge = np.eye(x.shape[1]) * self.penalty
        ridge[0, 0] = 0
        for _ in range(self.maximum_iterations):
            probabilities = sigmoid(x @ beta)
            weights = np.clip(probabilities * (1 - probabilities), 1e-8, None)
            gradient = x.T @ (probabilities - labels) / len(labels) + ridge @ beta
            hessian = (x.T * weights) @ x / len(labels) + ridge
            try:
                step = np.linalg.solve(hessian, gradient)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(hessian, gradient, rcond=None)[0]
            beta -= step
            if np.max(np.abs(step)) < 1e-8:
                break
        self.coefficients = beta
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        if self.coefficients is None:
            raise RuntimeError("model is not fit")
        return sigmoid(self.coefficients[0] + features @ self.coefficients[1:])


@dataclass
class BoostedStumps:
    iterations: int = 40
    learning_rate: float = 0.05
    leaf_penalty: float = 1.0
    base_score: float = 0.0
    stumps: list[tuple[int, float, float, float]] | None = None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "BoostedStumps":
        prevalence = np.clip(labels.mean(), 1e-6, 1 - 1e-6)
        self.base_score = math.log(prevalence / (1 - prevalence))
        score = np.full(len(labels), self.base_score)
        self.stumps = []
        thresholds = [
            np.unique(np.quantile(features[:, column], np.linspace(.1, .9, 9)))
            for column in range(features.shape[1])
        ]
        for _ in range(self.iterations):
            p = sigmoid(score)
            gradient = labels - p
            hessian = np.clip(p * (1 - p), 1e-8, None)
            best = None
            total_gain = gradient.sum() ** 2 / (hessian.sum() + self.leaf_penalty)
            for column, candidates in enumerate(thresholds):
                values = features[:, column]
                for threshold in candidates:
                    left = values <= threshold
                    if left.sum() < 10 or (~left).sum() < 10:
                        continue
                    gl, hl = gradient[left].sum(), hessian[left].sum()
                    gr, hr = gradient[~left].sum(), hessian[~left].sum()
                    gain = gl * gl / (hl + self.leaf_penalty) + gr * gr / (hr + self.leaf_penalty) - total_gain
                    if best is None or gain > best[0]:
                        best = (gain, column, float(threshold), gl / (hl + self.leaf_penalty), gr / (hr + self.leaf_penalty))
            if best is None or best[0] <= 1e-10:
                break
            _, column, threshold, left_value, right_value = best
            left_value, right_value = np.clip([left_value, right_value], -3, 3)
            self.stumps.append((column, threshold, float(left_value), float(right_value)))
            score += self.learning_rate * np.where(features[:, column] <= threshold, left_value, right_value)
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        score = np.full(len(features), self.base_score)
        for column, threshold, left, right in self.stumps or []:
            score += self.learning_rate * np.where(features[:, column] <= threshold, left, right)
        return sigmoid(score)


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def grouped_folds(frame: pd.DataFrame, folds: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    sizes = frame.groupby("run_key").size().sort_values(ascending=False)
    assignments: list[list[str]] = [[] for _ in range(min(folds, len(sizes)))]
    loads = [0] * len(assignments)
    for group, size in sorted(sizes.items(), key=lambda item: (-item[1], _stable_key(str(item[0])))):
        destination = min(range(len(loads)), key=lambda index: (loads[index], index))
        assignments[destination].append(str(group))
        loads[destination] += int(size)
    values = frame["run_key"].astype(str)
    return [
        (np.flatnonzero(~values.isin(groups)), np.flatnonzero(values.isin(groups)))
        for groups in assignments if groups
    ]


def forward_folds(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    groups = frame.groupby("run_key")["start"].min().sort_values().index.astype(str).tolist()
    if len(groups) < 8:
        return []
    initial = max(5, int(math.ceil(len(groups) * .4)))
    block = max(2, int(math.ceil(len(groups) * .2)))
    values = frame["run_key"].astype(str)
    result = []
    for cut in range(initial, len(groups), block):
        test_groups = groups[cut:min(len(groups), cut + block)]
        if not test_groups:
            continue
        train_groups = groups[:cut]
        result.append((np.flatnonzero(values.isin(train_groups)), np.flatnonzero(values.isin(test_groups))))
    return result


def instrument_folds(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    values = frame["canonical_instrument"].astype(str)
    return [
        (np.flatnonzero(values.ne(instrument)), np.flatnonzero(values.eq(instrument)))
        for instrument in sorted(values.unique())
    ]


def select_penalty(frame: pd.DataFrame, candidates: Sequence[float] = (.001, .01, .1, 1.0, 10.0)) -> float:
    folds = grouped_folds(frame, min(4, frame["run_key"].nunique()))
    best = (math.inf, 1.0)
    for penalty in candidates:
        losses = []
        for train, test in folds:
            train_frame, test_frame = frame.iloc[train], frame.iloc[test]
            if train_frame["target_label"].nunique() < 2 or test_frame.empty:
                continue
            prep = Preprocessor.fit(train_frame)
            model = RidgeLogit(penalty).fit(prep.transform(train_frame), train_frame["target_label"].to_numpy(float))
            losses.append(log_loss(test_frame["target_label"].to_numpy(float), model.predict(prep.transform(test_frame))))
        score = float(np.mean(losses)) if losses else math.inf
        if score < best[0]:
            best = score, penalty
    return float(best[1])


def _cv_predictions(frame: pd.DataFrame, split_type: str) -> tuple[pd.DataFrame, list[dict]]:
    if split_type == "GROUPED_RUN":
        folds = grouped_folds(frame)
    elif split_type == "FORWARD_TIME":
        folds = forward_folds(frame)
    else:
        folds = instrument_folds(frame)
    pieces, fold_rows = [], []
    for fold, (train, test) in enumerate(folds):
        train_frame, test_frame = frame.iloc[train], frame.iloc[test]
        if train_frame["target_label"].nunique() < 2 or test_frame["target_label"].nunique() < 2:
            continue
        penalty = select_penalty(train_frame)
        prep = Preprocessor.fit(train_frame)
        x_train, x_test = prep.transform(train_frame), prep.transform(test_frame)
        labels = train_frame["target_label"].to_numpy(float)
        model = RidgeLogit(penalty).fit(x_train, labels)
        prediction = model.predict(x_test)
        null = np.full(len(test_frame), labels.mean())
        part = test_frame[["run_key", "episode_id", "attempt_id", "target_label"]].copy()
        part["probability"] = prediction
        part["null_probability"] = null
        part["fold"] = fold
        part["split_type"] = split_type
        pieces.append(part)
        fold_rows.append({
            "split_type": split_type, "fold": fold, "penalty": penalty,
            "train_rows": len(train_frame), "test_rows": len(test_frame),
            "train_runs": train_frame["run_key"].nunique(), "test_runs": test_frame["run_key"].nunique(),
            "features": x_train.shape[1],
        })
    return (pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(), fold_rows)


def _block_delta_interval(predictions: pd.DataFrame, repetitions: int = 1000) -> tuple[float, float]:
    grouped = []
    for _, part in predictions.groupby("run_key"):
        y = part["target_label"].to_numpy(float)
        model = np.clip(part["probability"].to_numpy(float), 1e-12, 1 - 1e-12)
        null = np.clip(part["null_probability"].to_numpy(float), 1e-12, 1 - 1e-12)
        model_sum = float(-(y * np.log(model) + (1 - y) * np.log(1 - model)).sum())
        null_sum = float(-(y * np.log(null) + (1 - y) * np.log(1 - null)).sum())
        grouped.append((len(part), null_sum - model_sum))
    values = np.asarray(grouped, dtype=float)
    if len(values) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(117011)
    estimates = []
    for _ in range(repetitions):
        sample = values[rng.integers(0, len(values), len(values))]
        estimates.append(sample[:, 1].sum() / sample[:, 0].sum())
    return float(np.quantile(estimates, .025)), float(np.quantile(estimates, .975))


def evaluate_logistic(
    frame: pd.DataFrame, target: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prediction_parts, fold_rows = [], []
    for split_type in ("GROUPED_RUN", "FORWARD_TIME", "INSTRUMENT_TRANSFER"):
        predictions, folds = _cv_predictions(frame, split_type)
        if not predictions.empty:
            prediction_parts.append(predictions)
            fold_rows.extend(folds)
    predictions = pd.concat(prediction_parts, ignore_index=True)
    rows = []
    for split_type, part in predictions.groupby("split_type"):
        y = part["target_label"].to_numpy(float)
        for model_name, column in (("NULL_PREVALENCE", "null_probability"), ("RIDGE_LOGISTIC", "probability")):
            row = {"target": target, "split_type": split_type, "model": model_name, **metric_row(y, part[column].to_numpy(float))}
            rows.append(row)
        low, high = _block_delta_interval(part)
        rows[-1]["run_block_delta_logloss_low"] = low
        rows[-1]["run_block_delta_logloss_high"] = high
    penalty = select_penalty(frame)
    prep = Preprocessor.fit(frame)
    model = RidgeLogit(penalty).fit(prep.transform(frame), frame["target_label"].to_numpy(float))
    coefficients = pd.DataFrame({
        "target": target, "feature": ("INTERCEPT", *prep.names),
        "coefficient": model.coefficients, "absolute_coefficient": np.abs(model.coefficients),
        "full_fit_penalty": penalty,
    }).sort_values("absolute_coefficient", ascending=False)
    folds = pd.DataFrame(fold_rows)
    if not folds.empty:
        folds.insert(0, "target", target)
    return pd.DataFrame(rows), predictions, folds, coefficients


def evaluate_stumps(frame: pd.DataFrame, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, pieces = [], []
    for split_type, folds in (
        ("GROUPED_RUN", grouped_folds(frame)),
        ("FORWARD_TIME", forward_folds(frame)),
        ("INSTRUMENT_TRANSFER", instrument_folds(frame)),
    ):
        for fold, (train, test) in enumerate(folds):
            train_frame, test_frame = frame.iloc[train], frame.iloc[test]
            if train_frame["target_label"].nunique() < 2 or test_frame["target_label"].nunique() < 2:
                continue
            prep = Preprocessor.fit(train_frame)
            model = BoostedStumps().fit(
                prep.transform(train_frame), train_frame["target_label"].to_numpy(float)
            )
            probability = model.predict(prep.transform(test_frame))
            part = test_frame[["run_key", "episode_id", "attempt_id", "target_label"]].copy()
            part["probability"] = probability
            part["fold"] = fold
            part["split_type"] = split_type
            pieces.append(part)
        selected = [part for part in pieces if part["split_type"].iloc[0] == split_type]
        if selected:
            joined = pd.concat(selected, ignore_index=True)
            rows.append({"target": target, "split_type": split_type, "model": "BOOSTED_STUMPS", **metric_row(
                joined["target_label"].to_numpy(float), joined["probability"].to_numpy(float)
            )})
    return pd.DataFrame(rows), pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def baseline_gate(metrics: pd.DataFrame, frame: pd.DataFrame) -> dict:
    lookup = metrics.set_index(["split_type", "model"])["log_loss"].to_dict()
    grouped_improvement = lookup.get(("GROUPED_RUN", "NULL_PREVALENCE"), math.nan) - lookup.get(
        ("GROUPED_RUN", "RIDGE_LOGISTIC"), math.nan
    )
    forward_improvement = lookup.get(("FORWARD_TIME", "NULL_PREVALENCE"), math.nan) - lookup.get(
        ("FORWARD_TIME", "RIDGE_LOGISTIC"), math.nan
    )
    transfer_improvement = lookup.get(("INSTRUMENT_TRANSFER", "NULL_PREVALENCE"), math.nan) - lookup.get(
        ("INSTRUMENT_TRANSFER", "RIDGE_LOGISTIC"), math.nan
    )
    positives = int(frame["target_label"].sum())
    negatives = len(frame) - positives
    gates = {
        "minimum_analyzable": len(frame) >= MODEL_GATE.minimum_analyzable,
        "minimum_positive": positives >= MODEL_GATE.minimum_positive,
        "minimum_negative": negatives >= MODEL_GATE.minimum_negative,
        "minimum_runs": frame["run_key"].nunique() >= MODEL_GATE.minimum_runs,
        "grouped_logloss_beats_null": bool(grouped_improvement > MODEL_GATE.minimum_group_logloss_improvement),
        "forward_logloss_beats_null": bool(forward_improvement > MODEL_GATE.minimum_forward_logloss_improvement),
        "instrument_transfer_logloss_beats_null": bool(
            transfer_improvement > MODEL_GATE.minimum_instrument_transfer_logloss_improvement
        ),
    }
    return {
        "status": "PASS_NONLINEAR_CHALLENGER" if all(gates.values()) else "HOLD_BASELINE_ONLY",
        "analyzable": len(frame), "positive": positives, "negative": negatives,
        "runs": frame["run_key"].nunique(), "grouped_logloss_improvement": grouped_improvement,
        "forward_logloss_improvement": forward_improvement, "gates": gates,
        "instrument_transfer_logloss_improvement": transfer_improvement,
    }
