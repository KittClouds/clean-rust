"""Synthetic endpoint fixtures for OBS-OPEN-SRC-01.

These fixtures test only the recovered Breakout boundary contract. They are not
market observations and cannot enter any discovery or confirmation corpus.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    minute: int
    high: float
    low: float
    close: float


def inclusive_range(bars: list[Bar], begin: int, end: int) -> tuple[float, float]:
    selected = [bar for bar in bars if begin <= bar.minute <= end]
    return max(bar.high for bar in selected), min(bar.low for bar in selected)


def half_open_range(bars: list[Bar], begin: int, end: int) -> tuple[float, float]:
    selected = [bar for bar in bars if begin <= bar.minute < end]
    return max(bar.high for bar in selected), min(bar.low for bar in selected)


def test_end_candle_new_high_is_included() -> None:
    bars = [
        Bar(570, 100.0, 98.0, 99.0),
        Bar(574, 101.0, 97.0, 99.0),
        # The endpoint candle makes the new high late in its candle.
        Bar(575, 110.0, 96.0, 100.0),
    ]
    assert inclusive_range(bars, 570, 575) == (110.0, 96.0)
    assert half_open_range(bars, 570, 575) == (101.0, 97.0)


def test_end_candle_new_low_is_included() -> None:
    bars = [
        Bar(570, 100.0, 98.0, 99.0),
        Bar(574, 101.0, 97.0, 99.0),
        # The endpoint candle makes the new low late in its candle.
        Bar(575, 102.0, 90.0, 100.0),
    ]
    assert inclusive_range(bars, 570, 575) == (102.0, 90.0)
    assert half_open_range(bars, 570, 575) == (101.0, 97.0)


def test_endpoint_is_shared_by_period_and_area() -> None:
    bars = [Bar(570, 100.0, 98.0, 99.0), Bar(575, 110.0, 90.0, 100.0)]
    period = inclusive_range(bars, 570, 575)
    area = inclusive_range(bars, 575, 575)
    assert period == (110.0, 90.0)
    assert area == (110.0, 90.0)
