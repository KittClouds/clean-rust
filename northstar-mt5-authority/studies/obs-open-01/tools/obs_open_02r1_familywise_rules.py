"""OBS-OPEN-02R1 frozen familywise decision semantics.

The module is data-independent: it contains no market-data loader. Tests use
synthetic session values only; OBS-OPEN-03 may supply real values later.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence


ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260814

FORMAL_TEMPLATES = {
    "WIDTH_DELTA_ADJACENT": range(1, 30),
    "FIRST_OUTSIDE_SIDE_BALANCE": range(1, 31),
    "LOCATION_BALANCE": range(1, 31),
    "SIGNED_PATH_DISPLACEMENT": range(1, 31),
}


def expand_estimand_ids() -> tuple[str, ...]:
    ids: list[str] = []
    for template, domain in FORMAL_TEMPLATES.items():
        for k in domain:
            if template == "WIDTH_DELTA_ADJACENT":
                ids.append(f"{template}_K{k:02d}_TO_K{k + 1:02d}")
            else:
                ids.append(f"{template}_K{k:02d}")
    return tuple(ids)


@dataclass(frozen=True)
class SupportSnapshot:
    eligible_sessions: int
    supported_months: int
    minimum_month_sessions: int
    supported_offset_regimes: int
    minimum_regime_sessions: int
    conditional_cell_sessions: int | None = None


def support_pass(snapshot: SupportSnapshot, conditional: bool = False) -> bool:
    if snapshot.eligible_sessions < 129:
        return False
    if snapshot.supported_months < 4 or snapshot.minimum_month_sessions < 10:
        return False
    if snapshot.supported_offset_regimes < 2 or snapshot.minimum_regime_sessions < 20:
        return False
    return not conditional or (
        snapshot.conditional_cell_sessions is not None
        and snapshot.conditional_cell_sessions >= 30
    )


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires values")
    index = int(q * (len(sorted_values) - 1))
    return float(sorted_values[index])


def bootstrap_summary(values_by_session: Mapping[str, float]) -> dict[str, float | int]:
    ordered = tuple(sorted(values_by_session.items()))
    if not ordered:
        raise ValueError("bootstrap requires eligible sessions")
    values = tuple(value for _, value in ordered)
    point = float(mean(values))
    rng = random.Random(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [values[rng.randrange(len(values))] for _ in values]
        draws.append(float(mean(sample)))
    draws.sort()
    lower = _quantile(draws, 0.025)
    upper = _quantile(draws, 0.975)
    lower_tail = sum(draw <= 0.0 for draw in draws)
    upper_tail = sum(draw >= 0.0 for draw in draws)
    raw_p = 2.0 * min(
        (lower_tail + 1) / (BOOTSTRAP_RESAMPLES + 1),
        (upper_tail + 1) / (BOOTSTRAP_RESAMPLES + 1),
    )
    return {
        "point_estimate": point,
        "lower_95": lower,
        "upper_95": upper,
        "raw_p": min(1.0, raw_p),
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "eligible_sessions": len(values),
    }


def holm_bonferroni(p_values: Mapping[str, float], alpha: float = ALPHA) -> dict[str, bool]:
    if not p_values:
        return {}
    ordered = sorted((float(p), key) for key, p in p_values.items())
    decisions: dict[str, bool] = {key: False for _, key in ordered}
    still_rejecting = True
    total = len(ordered)
    for rank, (p_value, key) in enumerate(ordered):
        threshold = alpha / (total - rank)
        accepted = still_rejecting and p_value <= threshold
        decisions[key] = accepted
        if not accepted:
            still_rejecting = False
    return decisions


def temporal_status(
    aggregate_sign: int,
    month_slices: Sequence[tuple[int, bool]],
    regime_slices: Sequence[tuple[int, bool]],
    sensitivity_slices: Sequence[tuple[int, bool]] = (),
) -> str:
    """Classify predeclared time views without treating them as new tests.

    Month and server-offset slices establish support strata. Leave-one-month-out
    and chronological-block slices are sensitivity views; they still must be
    supported and sign-consistent before a candidate is called stable.
    """
    slices = tuple(month_slices) + tuple(regime_slices) + tuple(sensitivity_slices)
    if not slices or not all(supported for _, supported in slices):
        return "TEMPORAL_SUPPORT_INSUFFICIENT"
    signs = [sign for sign, _ in slices if sign != 0]
    if len(signs) != len(slices):
        return "TEMPORAL_SUPPORT_INSUFFICIENT"
    if aggregate_sign == 0:
        return "TEMPORAL_SUPPORT_INSUFFICIENT"
    opposite = sum(sign != aggregate_sign for sign in signs)
    if opposite >= 2:
        return "TEMPORALLY_UNSTABLE"
    if all(sign == aggregate_sign for sign in signs):
        return "TEMPORALLY_SUPPORTED"
    return "TEMPORAL_SUPPORT_INSUFFICIENT"


def classify_formal_candidate(
    template: str,
    estimate: float,
    raw_p: float,
    familywise_pass: bool,
    support: SupportSnapshot,
    temporal: str,
) -> tuple[str, str | None]:
    if template not in FORMAL_TEMPLATES:
        return "NOT_EVALUABLE", "NOT_EVALUABLE"
    if not support_pass(support):
        return "INSUFFICIENT_SUPPORT", "INSUFFICIENT_ELIGIBLE_SUPPORT"
    if raw_p > ALPHA:
        return "DESCRIPTIVE_ONLY", "FAILS_UNADJUSTED_EVIDENCE"
    if not familywise_pass:
        return "DESCRIPTIVE_ONLY", "FAILS_FAMILYWISE_CORRECTION"
    if temporal == "TEMPORAL_SUPPORT_INSUFFICIENT":
        return "INSUFFICIENT_SUPPORT", "INSUFFICIENT_TEMPORAL_SUPPORT"
    if temporal == "TEMPORALLY_UNSTABLE":
        return "TEMPORALLY_UNSTABLE_STRUCTURE", "TEMPORALLY_UNSTABLE"
    if estimate == 0.0:
        return "DESCRIPTIVE_ONLY", "NEAR_NULL_NOT_EVALUABLE"
    if template == "WIDTH_DELTA_ADJACENT":
        return "SCALE_DEPENDENT_STRUCTURE", None
    return "RECURRING_STRUCTURE", None
