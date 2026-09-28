"""Pure v0.8P descriptive event-time and A/F-partition analysis helpers.

This module deliberately has no prediction, panel, checkpoint, or model loader.
Callers provide in-memory per-neighborhood arrays.  The sealed analysis contract
does not fully specify the Q95 quantile estimator, family/PCG64 draw order, or
whether bootstrap index plans are shared across series.  Those gaps are exposed
by :func:`contract_ambiguities`; this module never chooses them implicitly.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


CONTRACT_PATH = Path(__file__).with_name("phase-b-p-analysis-contract-v01.json")
CONTINUOUS_COORDINATES = (
    "new_probability_delta",
    "anchor_old_map",
    "sham_l1",
    "matched_l1",
)
BINARY_APPEARANCE_COORDINATES = ("fact_new_map", "strict_transition")
FOUR_CELL_NAMES = (
    "A_AND_F",
    "A_AND_NOT_F",
    "NOT_A_AND_F",
    "NOT_A_AND_NOT_F",
)


class ContractDefinitionError(ValueError):
    """The supplied contract does not encode the v0.8P event-time rules."""


class ContractAmbiguityError(RuntimeError):
    """An operation needs a bootstrap convention absent from the sealed contract."""


class AnalysisInputError(ValueError):
    """Synthetic or caller-provided analysis arrays violate their declared shape."""


@dataclass(frozen=True)
class EventTimeSpec:
    baseline_step: int
    epoch3_steps: tuple[int, ...]
    all_steps: tuple[int, ...]
    persistence_steps: int
    bootstrap_replicates: int
    bootstrap_seed: int
    confidence: float
    family_count: int
    neighborhoods_per_family: int
    censor_step: int
    fact_probability_direction: str
    anchor_loss_direction: str
    locality_directions: tuple[str, str]
    transition_cells: tuple[tuple[str, bool, bool], ...]


def load_analysis_contract(path: str | Path = CONTRACT_PATH) -> dict[str, Any]:
    """Read only the sealed analysis-contract JSON; no data artifacts are read."""
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ContractDefinitionError("analysis contract root must be a JSON object")
    return contract


def contract_ambiguities(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Return bootstrap choices not bound by the supplied frozen contract.

    These are intentionally not assigned defaults.  They affect exact
    reproducibility and should be resolved by a separately authorized contract
    addendum before real-panel event-time analysis.
    """
    bootstrap = contract.get("descriptive_event_time_rules", {}).get("bootstrap", {})
    gaps: list[str] = []
    if not any(key in bootstrap for key in ("quantile_method", "quantile_estimator")):
        gaps.append("bootstrap Q95 quantile estimator/interpolation method is unspecified")
    if not any(key in bootstrap for key in ("family_order", "stratum_order", "family_draw_order")):
        gaps.append("family-stratum traversal and PCG64 draw order are unspecified")
    if not any(key in bootstrap for key in ("resample_scope", "resampling_scope", "series_resampling_policy")):
        gaps.append("whether bootstrap index plans are shared across seed/arm/coordinate series is unspecified")
    return tuple(gaps)


def require_unambiguous_bootstrap_contract(contract: Mapping[str, Any]) -> None:
    """Fail closed when the sealed contract leaves bootstrap execution choices open."""
    gaps = contract_ambiguities(contract)
    if gaps:
        details = "\n - ".join(gaps)
        raise ContractAmbiguityError(
            "sealed v0.8P contract is insufficient for contract-compliant bootstrap execution:\n - "
            + details
        )


def event_time_spec(contract: Mapping[str, Any]) -> EventTimeSpec:
    """Validate and parse the frozen v0.8P event-time definitions."""
    try:
        design = contract["evaluation_design"]
        rules = contract["descriptive_event_time_rules"]
        bootstrap = rules["bootstrap"]
        transitions = contract["transition_decomposition"]["events"]
        raw_epoch3 = design["epoch_3_steps"]
    except (KeyError, TypeError) as exc:
        raise ContractDefinitionError(f"missing event-time contract field: {exc}") from exc

    if not isinstance(raw_epoch3, list) or len(raw_epoch3) != 2:
        raise ContractDefinitionError("epoch_3_steps must be the frozen inclusive [first,last] pair")
    first_step, last_step = (int(raw_epoch3[0]), int(raw_epoch3[1]))
    epoch3_steps = tuple(range(first_step, last_step + 1))
    baseline_match = re.search(r"global_step\s*=\s*(\d+)", str(rules.get("reference_point", "")))
    if baseline_match is None:
        raise ContractDefinitionError("cannot parse the frozen step-80 reference point")
    baseline_step = int(baseline_match.group(1))

    persistence_match = re.search(r"(\d+)-consecutive-step", str(rules.get("persistence", "")))
    if persistence_match is None:
        raise ContractDefinitionError("cannot parse the consecutive-step persistence rule")
    persistence_steps = int(persistence_match.group(1))

    replicate_count = int(bootstrap.get("replicates", -1))
    rng_text = str(bootstrap.get("rng", ""))
    rng_match = re.search(r"PCG64\((\d+)\)", rng_text)
    derivation = str(bootstrap.get("seed_derivation", ""))
    derivation_match = re.search(r"UTF-8\('([^']+)'\)", derivation)
    if rng_match is None or derivation_match is None:
        raise ContractDefinitionError("PCG64 seed or its frozen SHA-256 derivation is not parseable")
    bootstrap_seed = int(rng_match.group(1))
    derived_seed = int.from_bytes(
        hashlib.sha256(derivation_match.group(1).encode("utf-8")).digest()[:4],
        byteorder="little",
        signed=False,
    )
    if bootstrap_seed != derived_seed:
        raise ContractDefinitionError(
            f"PCG64 seed mismatch: declared={bootstrap_seed}, derived={derived_seed}"
        )

    confidence_match = re.search(r"one-sided\s+(\d+(?:\.\d+)?)%", str(bootstrap.get("simultaneity", "")))
    if confidence_match is None:
        raise ContractDefinitionError("cannot parse the one-sided simultaneous confidence level")
    confidence = float(confidence_match.group(1)) / 100.0

    stratification = str(bootstrap.get("stratification", ""))
    family_n_match = re.search(r"resample\s+(\d+)\s+neighborhoods", stratification)
    family_count_match = re.search(r"four\s+families", stratification, flags=re.IGNORECASE)
    if family_n_match is None or family_count_match is None:
        raise ContractDefinitionError("cannot parse frozen family-stratified resample allocation")

    censor_text = str(rules.get("censoring", ""))
    censor_match = re.search(r"global_step=(\d+)", censor_text)
    if censor_match is None:
        raise ContractDefinitionError("cannot parse the frozen censoring step")
    censor_step = int(censor_match.group(1))

    if (baseline_step, first_step, last_step, len(epoch3_steps)) != (80, 81, 120, 40):
        raise ContractDefinitionError("v0.8P timing requires baseline step 80 and exactly steps 81..120")
    if replicate_count != 10_000 or persistence_steps != 3 or confidence != 0.95:
        raise ContractDefinitionError("replicate, persistence, or confidence rule differs from sealed v0.8P")
    if censor_step != 120:
        raise ContractDefinitionError("v0.8P event-time censoring must be global step 120")

    event_by_name = {str(event.get("cell")): event for event in transitions}
    if tuple(event_by_name) != FOUR_CELL_NAMES:
        raise ContractDefinitionError("four-cell transition identities/order differ from sealed v0.8P")
    cells: list[tuple[str, bool, bool]] = []
    for name in FOUR_CELL_NAMES:
        event = event_by_name[name]
        cells.append((name, bool(event["anchor_old_map"]), bool(event["fact_new_map"])))
    if tuple(cells) != (
        ("A_AND_F", True, True),
        ("A_AND_NOT_F", True, False),
        ("NOT_A_AND_F", False, True),
        ("NOT_A_AND_NOT_F", False, False),
    ):
        raise ContractDefinitionError("four-cell conditions are not a complete frozen A/F partition")

    direction_text = {
        "fact_probability_movement_rise": str(rules.get("fact_probability_movement_rise", "")),
        "anchor_loss": str(rules.get("anchor_loss", "")),
        "sham_locality_change": str(rules.get("sham_locality_change", "")),
        "matched_locality_change": str(rules.get("matched_locality_change", "")),
    }
    if "lower simultaneous band" not in direction_text["fact_probability_movement_rise"]:
        raise ContractDefinitionError("fact probability onset must use the lower simultaneous band")
    if "upper simultaneous band" not in direction_text["anchor_loss"]:
        raise ContractDefinitionError("anchor-loss onset must use the upper simultaneous band")
    if any("decrease" not in direction_text[name] or "increase" not in direction_text[name]
           for name in ("sham_locality_change", "matched_locality_change")):
        raise ContractDefinitionError("both directions of each locality change must remain reportable")

    return EventTimeSpec(
        baseline_step=baseline_step,
        epoch3_steps=epoch3_steps,
        all_steps=(baseline_step, *epoch3_steps),
        persistence_steps=persistence_steps,
        bootstrap_replicates=replicate_count,
        bootstrap_seed=bootstrap_seed,
        confidence=confidence,
        family_count=4,
        neighborhoods_per_family=int(family_n_match.group(1)),
        censor_step=censor_step,
        fact_probability_direction="positive",
        anchor_loss_direction="negative",
        locality_directions=("negative", "positive"),
        transition_cells=tuple(cells),
    )


def validate_panel_family_allocation(
    family_ids: Sequence[str], contract: Mapping[str, Any]
) -> dict[str, int]:
    """Validate the contract's 4 × 500 panel allocation without reading a panel."""
    spec = event_time_spec(contract)
    labels = np.asarray(family_ids, dtype=object)
    if labels.ndim != 1 or labels.size != spec.family_count * spec.neighborhoods_per_family:
        raise AnalysisInputError("family vector does not have the contracted 2,000-neighborhood length")
    if any(not isinstance(label, str) or not label for label in labels.tolist()):
        raise AnalysisInputError("family IDs must be non-empty strings")
    unique = sorted(set(labels.tolist()))
    if len(unique) != spec.family_count:
        raise AnalysisInputError(f"expected {spec.family_count} distinct families, found {len(unique)}")
    counts = {family: int(np.count_nonzero(labels == family)) for family in unique}
    if any(count != spec.neighborhoods_per_family for count in counts.values()):
        raise AnalysisInputError("each contracted family must contain exactly 500 neighborhoods")
    return counts


def generate_family_stratified_resamples(
    family_ids: Sequence[str],
    contract: Mapping[str, Any],
    *,
    family_order: Sequence[str],
    draw_order: str,
) -> np.ndarray:
    """Generate one explicit PCG64 stratified index plan.

    ``family_order`` and ``draw_order`` are required because their exact order is
    not frozen in the current contract.  ``draw_order`` currently supports only
    ``"family_major"`` (one vectorized draw per family, in the supplied order).
    The returned plan is suitable for reuse across metrics only if the caller
    explicitly chooses to reuse it; this helper does not make that choice.
    """
    spec = event_time_spec(contract)
    labels = np.asarray(family_ids, dtype=object)
    if labels.ndim != 1 or labels.size == 0:
        raise AnalysisInputError("family_ids must be a non-empty vector")
    observed_order = tuple(str(value) for value in family_order)
    if len(observed_order) != spec.family_count or len(set(observed_order)) != spec.family_count:
        raise AnalysisInputError("family_order must explicitly name four unique strata")
    actual = set(labels.tolist())
    if set(observed_order) != actual:
        raise AnalysisInputError("family_order must exactly match the supplied family IDs")
    if draw_order != "family_major":
        raise AnalysisInputError("draw_order must be explicit and equal to 'family_major'")

    rng = np.random.Generator(np.random.PCG64(spec.bootstrap_seed))
    samples = np.empty((spec.bootstrap_replicates, labels.size), dtype=np.int32)
    offset = 0
    for family in observed_order:
        members = np.flatnonzero(labels == family).astype(np.int32, copy=False)
        if members.size == 0:
            raise AnalysisInputError(f"empty family stratum: {family}")
        local_draws = rng.integers(
            0, members.size,
            size=(spec.bootstrap_replicates, members.size),
            dtype=np.int32,
        )
        end = offset + members.size
        samples[:, offset:end] = members[local_draws]
        offset = end
    validate_stratified_resamples(samples, labels, family_order=observed_order, expected_replicates=spec.bootstrap_replicates)
    return samples


def validate_stratified_resamples(
    resample_indices: np.ndarray,
    family_ids: Sequence[str],
    *,
    family_order: Sequence[str],
    expected_replicates: int | None = None,
) -> None:
    """Check that every resample preserves each family's observed sample count."""
    labels = np.asarray(family_ids, dtype=object)
    indices = np.asarray(resample_indices)
    if labels.ndim != 1 or indices.ndim != 2 or indices.shape[1] != labels.size:
        raise AnalysisInputError("resample indices must have shape (replicates, neighborhoods)")
    if not np.issubdtype(indices.dtype, np.integer):
        raise AnalysisInputError("resample indices must use an integer dtype")
    if expected_replicates is not None and indices.shape[0] != expected_replicates:
        raise AnalysisInputError(f"expected {expected_replicates} bootstrap replicates")
    if indices.size == 0 or int(indices.min()) < 0 or int(indices.max()) >= labels.size:
        raise AnalysisInputError("resample index is outside the neighborhood range")
    order = tuple(str(value) for value in family_order)
    if len(order) != 4 or set(order) != set(labels.tolist()):
        raise AnalysisInputError("family_order does not exactly cover the four strata")
    sampled_families = labels[indices]
    for family in order:
        expected_count = int(np.count_nonzero(labels == family))
        observed_counts = np.count_nonzero(sampled_families == family, axis=1)
        if not np.all(observed_counts == expected_count):
            raise AnalysisInputError(f"bootstrap resample changed family allocation for {family}")


def _finite_matrix(values: np.ndarray, *, name: str, rows: int | None = None) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise AnalysisInputError(f"{name} must be a non-empty (steps, neighborhoods) matrix")
    if rows is not None and matrix.shape[0] != rows:
        raise AnalysisInputError(f"{name} must contain exactly {rows} step rows")
    if not np.isfinite(matrix).all():
        raise AnalysisInputError(f"{name} contains NaN or infinite values")
    return matrix


def simultaneous_max_deviation_band(
    neighborhood_values: np.ndarray,
    family_ids: Sequence[str],
    resample_indices: np.ndarray,
    contract: Mapping[str, Any],
    *,
    family_order: Sequence[str],
    quantile_method: str,
) -> dict[str, Any]:
    """Compute the frozen 40-step one-sided max-deviation band from explicit draws.

    Rows in ``neighborhood_values`` are step 80 followed by steps 81..120.
    The function takes the quantile method and resample plan explicitly; neither
    is silently inferred from the currently sealed contract.
    """
    spec = event_time_spec(contract)
    matrix = _finite_matrix(neighborhood_values, name="neighborhood_values", rows=len(spec.all_steps))
    labels = np.asarray(family_ids, dtype=object)
    if labels.shape != (matrix.shape[1],):
        raise AnalysisInputError("family_ids length must equal the neighborhood dimension")
    indices = np.asarray(resample_indices)
    validate_stratified_resamples(
        indices, labels, family_order=family_order,
        expected_replicates=spec.bootstrap_replicates,
    )
    if not isinstance(quantile_method, str) or not quantile_method:
        raise AnalysisInputError("quantile_method must be an explicit NumPy quantile method name")

    centered = matrix[1:, :] - matrix[0:1, :]
    estimate = centered.mean(axis=1, dtype=np.float64)
    bootstrap_means = np.empty((spec.bootstrap_replicates, len(spec.epoch3_steps)), dtype=np.float64)
    # Bound temporary memory while preserving the supplied resample matrix.
    batch_size = 32
    for first in range(0, spec.bootstrap_replicates, batch_size):
        last = min(first + batch_size, spec.bootstrap_replicates)
        sampled = centered[:, indices[first:last]]
        bootstrap_means[first:last, :] = sampled.mean(axis=2, dtype=np.float64).T
    errors = bootstrap_means - estimate[None, :]
    lower_extrema = np.max(-errors, axis=1)
    upper_extrema = np.max(errors, axis=1)
    try:
        lower_offset = float(np.quantile(lower_extrema, spec.confidence, method=quantile_method))
        upper_offset = float(np.quantile(upper_extrema, spec.confidence, method=quantile_method))
    except (TypeError, ValueError) as exc:
        raise AnalysisInputError(f"unsupported explicit NumPy quantile method: {quantile_method}") from exc

    lower = estimate - lower_offset
    upper = estimate + upper_offset
    return {
        "baseline_step": spec.baseline_step,
        "steps": list(spec.epoch3_steps),
        "estimate_change": estimate.tolist(),
        "lower": lower.tolist(),
        "upper": upper.tolist(),
        "lower_max_deviation_q": lower_offset,
        "upper_max_deviation_q": upper_offset,
        "confidence": spec.confidence,
        "bootstrap_replicates": spec.bootstrap_replicates,
        "bootstrap_seed": spec.bootstrap_seed,
        "quantile_method_explicit_input": quantile_method,
        "family_order_explicit_input": list(family_order),
        "contract_ambiguities": list(contract_ambiguities(contract)),
    }


def _event_record(
    condition: np.ndarray,
    steps: Sequence[int],
    persistence: int,
    censor_step: int,
) -> dict[str, Any]:
    flags = np.asarray(condition, dtype=np.bool_)
    step_values = tuple(int(step) for step in steps)
    if flags.ndim != 1 or flags.size != len(step_values):
        raise AnalysisInputError("event condition length must match its optimizer-step sequence")
    for first in range(0, max(0, flags.size - persistence + 1)):
        if bool(np.all(flags[first:first + persistence])):
            onset = step_values[first]
            return {
                "status": "OBSERVED",
                "onset_step": onset,
                "confirmed_at_step": step_values[first + persistence - 1],
                "persistence_steps": persistence,
            }
    return {
        "status": f"NOT_OBSERVED_BY_STEP_{censor_step}",
        "onset_step": None,
        "confirmed_at_step": None,
        "persistence_steps": persistence,
        "censor_step": censor_step,
    }


def continuous_onsets_from_band(
    coordinate: str,
    band: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply contract-defined signed 3-step onset rules to an explicit band."""
    spec = event_time_spec(contract)
    if coordinate not in CONTINUOUS_COORDINATES:
        raise AnalysisInputError(f"unsupported continuous onset coordinate: {coordinate}")
    if int(band.get("baseline_step", -1)) != spec.baseline_step:
        raise AnalysisInputError("band baseline differs from the sealed step-80 reference")
    steps = tuple(int(step) for step in band.get("steps", ()))
    if steps != spec.epoch3_steps:
        raise AnalysisInputError("band must cover every optimizer step 81..120 in order")
    lower = np.asarray(band.get("lower"), dtype=np.float64)
    upper = np.asarray(band.get("upper"), dtype=np.float64)
    if lower.shape != (len(spec.epoch3_steps),) or upper.shape != lower.shape:
        raise AnalysisInputError("band lower/upper arrays must each have 40 entries")
    if not np.isfinite(lower).all() or not np.isfinite(upper).all() or np.any(lower > upper):
        raise AnalysisInputError("band bounds are non-finite or inverted")

    def signed(direction: str) -> dict[str, Any]:
        condition = lower > 0.0 if direction == "positive" else upper < 0.0
        return _event_record(condition, steps, spec.persistence_steps, spec.censor_step)

    if coordinate == "new_probability_delta":
        return {"positive_rise": signed("positive")}
    if coordinate == "anchor_old_map":
        return {"anchor_loss": signed("negative")}
    return {
        "decrease": signed("negative"),
        "increase": signed("positive"),
    }


def _binary_matrix(values: np.ndarray, *, name: str, expected_rows: int) -> np.ndarray:
    raw = np.asarray(values)
    if raw.ndim != 2 or raw.shape[0] != expected_rows or raw.shape[1] == 0:
        raise AnalysisInputError(f"{name} must have shape ({expected_rows}, neighborhoods)")
    if raw.dtype == np.bool_:
        return raw.astype(np.bool_, copy=False)
    try:
        numeric = raw.astype(np.float64)
    except (TypeError, ValueError) as exc:
        raise AnalysisInputError(f"{name} must contain only Boolean/0/1 values") from exc
    if not np.isfinite(numeric).all() or not np.isin(numeric, (0.0, 1.0)).all():
        raise AnalysisInputError(f"{name} must contain only finite Boolean/0/1 values")
    return numeric.astype(np.bool_)


def _appearance_for_group(
    matrix: np.ndarray,
    steps: Sequence[int],
    persistence: int,
    censor_step: int,
) -> dict[str, Any]:
    counts = matrix.sum(axis=1, dtype=np.int64)
    first_any: dict[str, Any] = {
        "status": f"NOT_OBSERVED_BY_STEP_{censor_step}",
        "step": None,
        "count": 0,
        "censor_step": censor_step,
    }
    nonzero = np.flatnonzero(counts > 0)
    if nonzero.size:
        first = int(nonzero[0])
        first_any = {
            "status": "PRESENT_AT_BASELINE" if first == 0 else "OBSERVED",
            "step": int(steps[first]),
            "count": int(counts[first]),
        }

    persistent: dict[str, Any] = {
        "status": f"NOT_OBSERVED_BY_STEP_{censor_step}",
        "onset_step": None,
        "confirmed_at_step": None,
        "counts_during_run": [],
        "persistence_steps": persistence,
        "censor_step": censor_step,
    }
    active = counts > 0
    for first in range(0, max(0, active.size - persistence + 1)):
        if bool(np.all(active[first:first + persistence])):
            persistent = {
                "status": "PRESENT_AT_BASELINE" if first == 0 else "OBSERVED",
                "onset_step": int(steps[first]),
                "confirmed_at_step": int(steps[first + persistence - 1]),
                "counts_during_run": [int(value) for value in counts[first:first + persistence]],
                "persistence_steps": persistence,
            }
            break
    return {
        "first_nonzero": first_any,
        "first_three_consecutive_nonzero": persistent,
        "counts_by_step": [
            {"step": int(step), "count": int(count), "rate": float(count / matrix.shape[1])}
            for step, count in zip(steps, counts, strict=True)
        ],
    }


def binary_appearance_events(
    coordinate: str,
    neighborhood_values: np.ndarray,
    family_ids: Sequence[str],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Report any/persistent fact-new-MAP or strict-transition appearance and counts."""
    spec = event_time_spec(contract)
    if coordinate not in BINARY_APPEARANCE_COORDINATES:
        raise AnalysisInputError(f"unsupported binary appearance coordinate: {coordinate}")
    matrix = _binary_matrix(neighborhood_values, name=coordinate, expected_rows=len(spec.all_steps))
    labels = np.asarray(family_ids, dtype=object)
    if labels.shape != (matrix.shape[1],):
        raise AnalysisInputError("family_ids length must equal the neighborhood dimension")
    families = tuple(sorted(set(labels.tolist())))
    if len(families) != spec.family_count:
        raise AnalysisInputError("binary appearance analysis requires the four contracted families")

    overall = _appearance_for_group(matrix, spec.all_steps, spec.persistence_steps, spec.censor_step)
    by_family = {
        family: _appearance_for_group(
            matrix[:, labels == family], spec.all_steps, spec.persistence_steps, spec.censor_step
        )
        for family in families
    }
    return {
        "coordinate": coordinate,
        "overall": overall,
        "by_family": by_family,
        "contract_ambiguities": list(contract_ambiguities(contract)),
    }


def continuous_coordinate_analysis(
    coordinate: str,
    neighborhood_values: np.ndarray,
    family_ids: Sequence[str],
    resample_indices: np.ndarray,
    contract: Mapping[str, Any],
    *,
    family_order: Sequence[str],
    quantile_method: str,
) -> dict[str, Any]:
    """Compute one coordinate's simultaneous band and frozen onset descriptor."""
    if coordinate not in CONTINUOUS_COORDINATES:
        raise AnalysisInputError(f"unsupported continuous coordinate: {coordinate}")
    band = simultaneous_max_deviation_band(
        neighborhood_values,
        family_ids,
        resample_indices,
        contract,
        family_order=family_order,
        quantile_method=quantile_method,
    )
    return {
        "coordinate": coordinate,
        "band": band,
        "onsets": continuous_onsets_from_band(coordinate, band, contract),
        "contract_ambiguities": list(contract_ambiguities(contract)),
    }


def _binary_vector(values: np.ndarray, *, name: str) -> np.ndarray:
    matrix = _binary_matrix(np.asarray(values).reshape(1, -1), name=name, expected_rows=1)
    return matrix[0]


def _cell_summary(mask: np.ndarray, family_ids: np.ndarray, cells: Sequence[tuple[str, bool, bool]]) -> dict[str, Any]:
    n = int(mask.size)
    overall: dict[str, dict[str, float | int]] = {}
    by_family: dict[str, dict[str, dict[str, float | int]]] = {}
    for name, _, _ in cells:
        count = int(np.count_nonzero(mask == name))
        overall[name] = {"count": count, "proportion": float(count / n)}
    for family in sorted(set(family_ids.tolist())):
        family_mask = family_ids == family
        family_n = int(np.count_nonzero(family_mask))
        by_family[str(family)] = {}
        for name, _, _ in cells:
            count = int(np.count_nonzero(mask[family_mask] == name))
            by_family[str(family)][name] = {"count": count, "proportion": float(count / family_n)}
    return {"n": n, "overall": overall, "by_family": by_family}


def four_cell_partition(
    anchor_old_map: np.ndarray,
    fact_new_map: np.ndarray,
    family_ids: Sequence[str],
    contract: Mapping[str, Any],
    *,
    steps: Sequence[int],
    strict_transition: np.ndarray | None = None,
) -> dict[str, Any]:
    """Partition each snapshot into the frozen exhaustive/disjoint A/F cells."""
    spec = event_time_spec(contract)
    old = np.asarray(anchor_old_map)
    new = np.asarray(fact_new_map)
    if old.ndim == 1:
        old = old.reshape(1, -1)
    if new.ndim == 1:
        new = new.reshape(1, -1)
    old = _binary_matrix(old, name="anchor_old_map", expected_rows=old.shape[0] if old.ndim == 2 else -1)
    new = _binary_matrix(new, name="fact_new_map", expected_rows=new.shape[0] if new.ndim == 2 else -1)
    if old.shape != new.shape:
        raise AnalysisInputError("anchor_old_map and fact_new_map must have identical shapes")
    labels = np.asarray(family_ids, dtype=object)
    if labels.shape != (old.shape[1],):
        raise AnalysisInputError("family_ids length must equal the neighborhood dimension")
    if len(set(labels.tolist())) != spec.family_count:
        raise AnalysisInputError("four-cell partition requires exactly four family strata")
    step_values = tuple(int(step) for step in steps)
    if len(step_values) != old.shape[0]:
        raise AnalysisInputError("steps length must equal the snapshot dimension")
    if len(step_values) == len(spec.all_steps) and step_values != spec.all_steps:
        raise AnalysisInputError("trajectory partition steps must be exactly 80..120")
    if len(step_values) not in (1, len(spec.all_steps)):
        raise AnalysisInputError("partition must contain one synthetic snapshot or the full 80..120 path")

    strict: np.ndarray | None = None
    if strict_transition is not None:
        strict_raw = np.asarray(strict_transition)
        if strict_raw.ndim == 1:
            strict_raw = strict_raw.reshape(1, -1)
        strict = _binary_matrix(strict_raw, name="strict_transition", expected_rows=old.shape[0])
        if strict.shape != old.shape or not np.array_equal(strict, old & new):
            raise AnalysisInputError("strict_transition must equal anchor_old_map AND fact_new_map")

    result_steps: list[dict[str, Any]] = []
    for index, step in enumerate(step_values):
        a = old[index]
        f = new[index]
        masks = (
            (a & f),
            (a & ~f),
            (~a & f),
            (~a & ~f),
        )
        cell_ids = np.empty(labels.size, dtype=object)
        for (name, _, _), mask in zip(spec.transition_cells, masks, strict=True):
            cell_ids[mask] = name
        summary = _cell_summary(cell_ids, labels, spec.transition_cells)
        result_steps.append({"global_step": step, **summary})

    result = {"cell_order": [cell[0] for cell in spec.transition_cells], "steps": result_steps}
    validate_four_cell_partition(result)
    return result


def validate_four_cell_partition(partition: Mapping[str, Any]) -> bool:
    """Validate counts/rates exhaustively overall and within every family."""
    try:
        steps = partition["steps"]
        cell_order = tuple(partition["cell_order"])
    except (KeyError, TypeError) as exc:
        raise AnalysisInputError("partition must contain cell_order and steps") from exc
    if cell_order != FOUR_CELL_NAMES or not isinstance(steps, list) or not steps:
        raise AnalysisInputError("partition has an unexpected four-cell ordering or no snapshots")
    for snapshot in steps:
        n = int(snapshot["n"])
        overall = snapshot["overall"]
        if set(overall) != set(cell_order):
            raise AnalysisInputError("overall partition omits or adds a transition cell")
        total = 0
        for name in cell_order:
            count = int(overall[name]["count"])
            proportion = float(overall[name]["proportion"])
            if count < 0 or not np.isfinite(proportion) or not 0.0 <= proportion <= 1.0:
                raise AnalysisInputError(f"invalid overall cell count/rate for {name}")
            if not np.isclose(proportion, count / n, rtol=0.0, atol=1e-15):
                raise AnalysisInputError(f"overall proportion/count mismatch for {name}")
            total += count
        if n <= 0 or total != n:
            raise AnalysisInputError("four overall A/F cell counts must sum exactly to n")

        by_family = snapshot["by_family"]
        if len(by_family) != 4:
            raise AnalysisInputError("four-cell partition must retain exactly four families")
        family_total = 0
        for family, family_cells in by_family.items():
            if set(family_cells) != set(cell_order):
                raise AnalysisInputError(f"family {family} omits or adds a transition cell")
            family_n = sum(int(family_cells[name]["count"]) for name in cell_order)
            if family_n <= 0:
                raise AnalysisInputError(f"family {family} has no neighborhoods")
            family_total += family_n
            for name in cell_order:
                count = int(family_cells[name]["count"])
                proportion = float(family_cells[name]["proportion"])
                if count < 0 or not np.isfinite(proportion) or not 0.0 <= proportion <= 1.0:
                    raise AnalysisInputError(f"invalid family cell count/rate for {family}/{name}")
                if not np.isclose(proportion, count / family_n, rtol=0.0, atol=1e-15):
                    raise AnalysisInputError(f"family proportion/count mismatch for {family}/{name}")
        if family_total != n:
            raise AnalysisInputError("family four-cell totals do not sum to the overall n")
        strict = overall["A_AND_F"]["proportion"]
        if not np.isclose(float(strict), int(overall["A_AND_F"]["count"]) / n, rtol=0.0, atol=1e-15):
            raise AnalysisInputError("strict transition must equal the A_AND_F cell")
    return True

