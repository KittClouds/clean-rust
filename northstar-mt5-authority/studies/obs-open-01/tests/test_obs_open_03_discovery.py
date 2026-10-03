from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from obs_open_03_discovery import (  # noqa: E402
    EVENT_CROSS_ABOVE_TO_BELOW,
    EVENT_FAILED_ABOVE,
    EVENT_FIRST_ABOVE,
    EVENT_FIRST_BELOW,
    EVENT_IN_ZONE,
    EVENT_PERSIST_ABOVE,
    EVENT_RETURN_ABOVE,
    SourceBar,
    estimands,
    interaction_path,
)


def bar(epoch: int, close: str) -> SourceBar:
    value = Decimal(close)
    return SourceBar(epoch, value, value, value, value)


class ObsOpen03DiscoveryTests(unittest.TestCase):
    def test_formal_family_expands_exactly_119(self) -> None:
        rows = estimands()
        self.assertEqual(119, len(rows))
        self.assertEqual(119, len({row.estimand_id for row in rows}))
        self.assertEqual("WIDTH_DELTA_ADJACENT_K01_TO_K02", rows[0].estimand_id)
        self.assertEqual("SIGNED_PATH_DISPLACEMENT_K30", rows[-1].estimand_id)

    def test_interaction_path_matches_frozen_event_grammar(self) -> None:
        start = 1_000_000
        source = [
            bar(start, "100"),
            bar(start + 300, "111"),
            bar(start + 600, "112"),
            bar(start + 900, "105"),
            bar(start + 1200, "89"),
        ]
        path = interaction_path(source, Decimal("110"), Decimal("90"), start, start + 1500)
        self.assertEqual(
            [EVENT_IN_ZONE, EVENT_FIRST_ABOVE, EVENT_PERSIST_ABOVE, EVENT_RETURN_ABOVE, EVENT_FIRST_BELOW],
            [row.event for row in path],
        )
        self.assertEqual([0, 1, 2, 0, 1], [row.outside_run for row in path])

    def test_cross_through_is_not_return(self) -> None:
        start = 2_000_000
        source = [bar(start, "111"), bar(start + 300, "89")]
        path = interaction_path(source, Decimal("110"), Decimal("90"), start, start + 600)
        self.assertEqual([EVENT_FIRST_ABOVE, EVENT_CROSS_ABOVE_TO_BELOW], [row.event for row in path])

    def test_one_bar_outside_failure_is_strict(self) -> None:
        start = 2_500_000
        source = [bar(start, "111"), bar(start + 300, "100")]
        path = interaction_path(source, Decimal("110"), Decimal("90"), start, start + 600)
        self.assertEqual([EVENT_FIRST_ABOVE, EVENT_FAILED_ABOVE], [row.event for row in path])

    def test_freeze_and_area_boundaries_are_causal(self) -> None:
        start = 3_000_000
        source = [bar(start, "100"), bar(start + 300, "101"), bar(start + 600, "102")]
        path = interaction_path(source, Decimal("110"), Decimal("90"), start + 1, start + 600)
        self.assertEqual([start + 300], [row.epoch for row in path])

    def test_frozen_multiplicity_floor_cannot_pass_first_holm_step(self) -> None:
        minimum_raw_p = 2 / 2001
        first_holm_threshold = 0.05 / 119
        self.assertGreater(minimum_raw_p, first_holm_threshold)


if __name__ == "__main__":
    unittest.main()
