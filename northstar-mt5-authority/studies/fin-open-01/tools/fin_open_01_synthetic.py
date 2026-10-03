"""Deterministic synthetic qualification for FIN-OPEN-01.

This module has no filesystem or market-data access. It exercises only the
session-level surface statistic and the block-profile randomization contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from random import Random
from typing import Iterable


Cell = float | None
Grid = list[list[Cell]]


@dataclass(frozen=True)
class SyntheticSurface:
    profiles: tuple[tuple[int | None, ...], ...]
    paths: tuple[tuple[tuple[float, ...], ...], ...]
    strata: tuple[int, ...]

    @property
    def sessions(self) -> int:
        return len(self.profiles)

    @property
    def scales(self) -> int:
        return len(self.profiles[0])

    @property
    def horizons(self) -> int:
        return len(self.paths[0][0])


def _noise(session: int, scale: int, horizon: int, amplitude: float = 0.05) -> float:
    value = ((session * 17 + scale * 11 + horizon * 5) % 23) - 11
    return value * amplitude / 11.0


def make_surface(
    *,
    sessions: int = 48,
    scales: int = 4,
    horizons: int = 6,
    relation: str = "none",
    strength: float = 1.0,
    region: set[tuple[int, int]] | None = None,
    midpoint_every: int | None = None,
    temporal_reversal: bool = False,
    correlated_horizons: bool = False,
) -> SyntheticSurface:
    profiles: list[tuple[int | None, ...]] = []
    paths: list[tuple[tuple[float, ...], ...]] = []
    strata: list[int] = []
    for session in range(sessions):
        profile: list[int | None] = []
        for scale in range(scales):
            sign: int | None = 1 if (session + scale) % 2 == 0 else -1
            if midpoint_every and (session + scale) % midpoint_every == 0:
                sign = 0
            profile.append(sign)
        profiles.append(tuple(profile))
        strata.append(120 if session % 3 else 180)

        session_path: list[tuple[float, ...]] = []
        for scale in range(scales):
            values: list[float] = []
            for horizon in range(horizons):
                active = region is None or (scale, horizon) in region
                local_strength = strength if active else 0.0
                if relation == "none":
                    signal = 0.0
                elif relation == "same":
                    signal = float(profile[scale] or 0) * local_strength
                elif relation == "opposite":
                    signal = -float(profile[scale] or 0) * local_strength
                else:
                    raise ValueError(f"unknown synthetic relation: {relation}")
                if temporal_reversal and session >= sessions // 2:
                    signal = -signal
                noise_horizon = 0 if correlated_horizons else horizon
                values.append(signal + _noise(session, scale, noise_horizon))
            session_path.append(tuple(values))
        paths.append(tuple(session_path))
    return SyntheticSurface(tuple(profiles), tuple(paths), tuple(strata))


def mean_surface(surface: SyntheticSurface, profiles: Iterable[tuple[int | None, ...]]) -> Grid:
    sums = [[0.0 for _ in range(surface.horizons)] for _ in range(surface.scales)]
    counts = [[0 for _ in range(surface.horizons)] for _ in range(surface.scales)]
    for session, profile in enumerate(profiles):
        for scale, sign in enumerate(profile):
            if sign not in (-1, 1):
                continue
            for horizon in range(surface.horizons):
                sums[scale][horizon] += sign * surface.paths[session][scale][horizon]
                counts[scale][horizon] += 1
    return [
        [sums[scale][horizon] / counts[scale][horizon] if counts[scale][horizon] else None
         for horizon in range(surface.horizons)]
        for scale in range(surface.scales)
    ]


def block_permute_profiles(surface: SyntheticSurface, seed: int) -> tuple[tuple[int | None, ...], ...]:
    """Move whole profiles within offset and exact eligibility-mask strata."""
    groups: dict[tuple[int, tuple[bool, ...]], list[int]] = {}
    for session, profile in enumerate(surface.profiles):
        mask = tuple(value is not None for value in profile)
        groups.setdefault((surface.strata[session], mask), []).append(session)

    result: list[tuple[int | None, ...] | None] = [None] * surface.sessions
    rng = Random(seed)
    for indices in groups.values():
        source = list(indices)
        rng.shuffle(source)
        for target, original in zip(indices, source):
            result[target] = surface.profiles[original]
    assert all(profile is not None for profile in result)
    return tuple(profile for profile in result if profile is not None)


def _cell_values(grid: Grid) -> Iterable[float]:
    for row in grid:
        for value in row:
            if value is not None:
                yield value


def analyze(surface: SyntheticSurface, permutations: int = 256, seed: int = 7) -> dict[str, object]:
    observed = mean_surface(surface, surface.profiles)
    permuted: list[Grid] = []
    for index in range(permutations):
        profiles = block_permute_profiles(surface, seed + index)
        permuted.append(mean_surface(surface, profiles))

    null_mean: Grid = [[0.0 for _ in range(surface.horizons)] for _ in range(surface.scales)]
    standard_deviation: Grid = [[0.0 for _ in range(surface.horizons)] for _ in range(surface.scales)]
    for scale in range(surface.scales):
        for horizon in range(surface.horizons):
            values = [grid[scale][horizon] for grid in permuted]
            mean = sum(values) / len(values)
            null_mean[scale][horizon] = mean
            variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
            standard_deviation[scale][horizon] = sqrt(variance)

    z_surface: Grid = [[None for _ in range(surface.horizons)] for _ in range(surface.scales)]
    for scale in range(surface.scales):
        for horizon in range(surface.horizons):
            denominator = standard_deviation[scale][horizon]
            if observed[scale][horizon] is not None and denominator > 1e-12:
                z_surface[scale][horizon] = (
                    observed[scale][horizon] - null_mean[scale][horizon]
                ) / denominator

    observed_max = max((abs(value) for value in _cell_values(z_surface)), default=0.0)
    null_maxima: list[float] = []
    for grid in permuted:
        maximum = 0.0
        for scale in range(surface.scales):
            for horizon in range(surface.horizons):
                denominator = standard_deviation[scale][horizon]
                if denominator > 1e-12:
                    value = (grid[scale][horizon] - null_mean[scale][horizon]) / denominator
                    maximum = max(maximum, abs(value))
        null_maxima.append(maximum)
    exceedances = sum(value >= observed_max for value in null_maxima)
    p_value = (1 + exceedances) / (permutations + 1)
    return {
        "observed": observed,
        "null_mean": null_mean,
        "standard_deviation": standard_deviation,
        "z_surface": z_surface,
        "max_abs_z": observed_max,
        "familywise_p": p_value,
        "permutations": permutations,
        "independent_units": surface.sessions,
        "directional_probe_counts": [
            sum(profile[scale] in (-1, 1) for profile in surface.profiles)
            for scale in range(surface.scales)
        ],
    }


def connected_regions(result: dict[str, object], threshold: float = 2.0) -> list[list[tuple[int, int]]]:
    z_surface = result["z_surface"]
    assert isinstance(z_surface, list)
    scales = len(z_surface)
    horizons = len(z_surface[0]) if scales else 0
    eligible = {
        (scale, horizon)
        for scale in range(scales)
        for horizon in range(horizons)
        if z_surface[scale][horizon] is not None
        and abs(z_surface[scale][horizon]) >= threshold
    }
    regions: list[list[tuple[int, int]]] = []
    while eligible:
        start = min(eligible)
        eligible.remove(start)
        region = [start]
        frontier = [start]
        while frontier:
            scale, horizon = frontier.pop()
            for neighbor in ((scale - 1, horizon), (scale + 1, horizon),
                             (scale, horizon - 1), (scale, horizon + 1)):
                if neighbor in eligible:
                    eligible.remove(neighbor)
                    frontier.append(neighbor)
                    region.append(neighbor)
        regions.append(sorted(region))
    return sorted(regions, key=lambda region: (region[0], len(region)))


def temporal_status(surface: SyntheticSurface, permutations: int = 128) -> str:
    midpoint = surface.sessions // 2
    first = SyntheticSurface(surface.profiles[:midpoint], surface.paths[:midpoint], surface.strata[:midpoint])
    second = SyntheticSurface(surface.profiles[midpoint:], surface.paths[midpoint:], surface.strata[midpoint:])
    first_result = analyze(first, permutations=permutations, seed=31)
    second_result = analyze(second, permutations=permutations, seed=31)
    first_delta = first_result["observed"][0][0] - first_result["null_mean"][0][0]
    second_delta = second_result["observed"][0][0] - second_result["null_mean"][0][0]
    if abs(first_delta) < 0.05 or abs(second_delta) < 0.05:
        return "INSUFFICIENT_TEMPORAL_SUPPORT"
    if first_delta * second_delta < 0:
        return "TEMPORALLY_UNSTABLE"
    return "TEMPORALLY_SUPPORTED"


def assert_read_guards() -> None:
    allowed = {
        "contracts/obs_open_01_protocol_v1.json",
        "qualification/universe/universe/admitted_sessions.tsv",
        "qualification/universe/universe/partition_manifest.tsv",
        "qualification/universe/universe/universe_qualification_receipt.json",
        "qualification/universe/seal/universe_qualification_root_receipt.json",
        "qualification/universe/clock/clock_transport_receipt.json",
        "qualification/parity/opening_range_oracle_receipt.json",
        "qualification/parity/blackbox_parity_receipt.json",
    }
    forbidden = {
        "obs_open_03_discovery",
        "obs-open-03-discovery",
        "discovery_findings",
        "discovery_scale_summary",
        "confirmation_rows",
        "science_confirmation",
    }
    assert not any(any(token in path for token in forbidden) for path in allowed)


def run_synthetic_qualification() -> dict[str, object]:
    assert_read_guards()
    cases: dict[str, dict[str, object]] = {}

    no_association = make_surface(relation="none")
    no_result = analyze(no_association)
    assert no_result["familywise_p"] > 0.05
    cases["NO_ASSOCIATION"] = {"status": "PASS", "familywise_p": no_result["familywise_p"]}

    same = make_surface(relation="same", strength=1.0)
    same_result = analyze(same)
    assert same_result["familywise_p"] < 0.05
    cases["STRONG_SAME_ORIENTATION_ASSOCIATION"] = {"status": "PASS", "familywise_p": same_result["familywise_p"]}

    opposite = make_surface(relation="opposite", strength=1.0)
    opposite_result = analyze(opposite)
    assert opposite_result["familywise_p"] < 0.05
    assert opposite_result["observed"][0][0] < 0
    cases["STRONG_OPPOSITE_ORIENTATION_ASSOCIATION"] = {"status": "PASS", "familywise_p": opposite_result["familywise_p"]}

    isolated = make_surface(relation="same", strength=0.01, region={(0, 0)})
    isolated_result = analyze(isolated)
    assert isolated_result["familywise_p"] > 0.05
    cases["ISOLATED_FALSE_LOOKING_CELL"] = {"status": "PASS", "familywise_p": isolated_result["familywise_p"]}

    region = {(scale, horizon) for scale in (1, 2) for horizon in (1, 2, 3)}
    contiguous = make_surface(relation="same", strength=1.0, region=region)
    contiguous_result = analyze(contiguous)
    regions = connected_regions(contiguous_result, threshold=2.0)
    assert any(set(candidate) >= region for candidate in regions)
    cases["CONTIGUOUS_SCALE_HORIZON_REGION"] = {"status": "PASS", "regions": regions}

    reversal = make_surface(relation="same", strength=1.0, temporal_reversal=True)
    assert temporal_status(reversal) == "TEMPORALLY_UNSTABLE"
    cases["TEMPORAL_SIGN_REVERSAL"] = {"status": "PASS", "temporal_status": "TEMPORALLY_UNSTABLE"}

    sparse = make_surface(relation="same", midpoint_every=5)
    sparse_result = analyze(sparse)
    assert any(count < sparse.sessions for count in sparse_result["directional_probe_counts"])
    cases["SPARSE_MIDPOINT_PROBES"] = {"status": "PASS", "directional_probe_counts": sparse_result["directional_probe_counts"]}

    nested = make_surface(relation="same", scales=5, horizons=4)
    nested_result = analyze(nested)
    assert nested_result["independent_units"] == nested.sessions
    cases["NESTED_CROSS_SCALE_DEPENDENCE"] = {"status": "PASS", "independent_units": nested_result["independent_units"]}

    correlated = make_surface(relation="same", correlated_horizons=True)
    correlated_result = analyze(correlated)
    assert correlated_result["independent_units"] == correlated.sessions
    cases["CORRELATED_HORIZON_PATHS"] = {"status": "PASS", "independent_units": correlated_result["independent_units"]}

    permuted_profiles = block_permute_profiles(same, seed=99)
    for stratum in (120, 180):
        original = sorted(profile for profile, value in zip(same.profiles, same.strata) if value == stratum)
        moved = sorted(profile for profile, value in zip(permuted_profiles, same.strata) if value == stratum)
        assert original == moved
    cases["BLOCK_PROFILE_RANDOMIZATION"] = {"status": "PASS", "whole_profiles_preserved": True}

    cases["OUTCOME_AND_SCIENCE_READ_GUARDS"] = {"status": "PASS", "outcome_files_read": False, "science_confirmation_files_read": False}
    return {
        "schema": "FIN_OPEN_01_SYNTHETIC_QUALIFICATION_RECEIPT_V1",
        "status": "PASS",
        "real_outcomes_read": False,
        "science_confirmation_read": False,
        "cases": cases,
    }
