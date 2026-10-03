from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GUARD = load_tool("obs_open_02_confirmation_guard")
MEASURE = load_tool("obs_open_02_measurement")
ConfirmationAccessError = GUARD.ConfirmationAccessError
PartitionGuard = GUARD.PartitionGuard
Event = MEASURE.Event
RangeRecord = MEASURE.RangeRecord
adjacent_scale_delta = MEASURE.adjacent_scale_delta
contiguous_scale_survival = MEASURE.contiguous_scale_survival
geometry_view = MEASURE.geometry_view
range_relative_price = MEASURE.range_relative_price
sequence_view = MEASURE.sequence_view

PARTITION = ROOT / "qualification/universe/universe/partition_manifest.tsv"


class ObsOpen02ProtocolTests(unittest.TestCase):
    def test_contract_keeps_substantive_and_confirmation_closed(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/obs_open_02_discovery_measurement_v1.json").read_text()
        )
        self.assertEqual("FROZEN_UNOPENED", contract["substantive_status"])
        self.assertEqual("FROZEN_UNOPENED", contract["confirmation_status"])
        self.assertIsNone(contract["range_family"]["privileged_duration"])
        self.assertFalse(contract["confirmation_firewall"]["read_confirmation_observations"])

    def test_nested_geometry_and_degenerate_width(self) -> None:
        record = RangeRecord("SYNTH", 1, "09:31", "09:31", 110.0, 90.0)
        view = geometry_view(record)
        self.assertEqual(20.0, view["width"])
        self.assertEqual(100.0, view["midpoint"])
        self.assertEqual(1.0, range_relative_price(110.0, record))
        degenerate = RangeRecord("SYNTH", 2, "09:32", "09:32", 100.0, 100.0)
        self.assertIsNone(range_relative_price(100.0, degenerate))
        self.assertEqual("NOT_EVALUABLE_GEOMETRY", geometry_view(degenerate)["relative_geometry"])

    def test_sequence_preserves_order_and_typed_availability(self) -> None:
        events = [
            Event("FIRST_OUTSIDE", "09:35", "UP"),
            Event("RETURN_INSIDE", "09:40", None),
        ]
        view = sequence_view(events, "CENSORED")
        self.assertEqual(("FIRST_OUTSIDE", "RETURN_INSIDE"), view["event_types"])
        self.assertEqual("CENSORED", view["availability"])

    def test_scale_relations_require_same_session_and_adjacent_k(self) -> None:
        left = geometry_view(RangeRecord("SYNTH", 3, "09:33", "09:33", 110.0, 90.0))
        right = geometry_view(RangeRecord("SYNTH", 4, "09:34", "09:34", 112.0, 88.0))
        delta = adjacent_scale_delta(left, right)
        self.assertEqual(4, delta["to_k"])
        self.assertEqual(4.0, delta["delta_width"])
        self.assertEqual(((3, 4),), contiguous_scale_survival([
            RangeRecord("SYNTH", 3, "", "", 110.0, 90.0),
            RangeRecord("SYNTH", 4, "", "", 112.0, 88.0),
        ]))
        with self.assertRaises(ValueError):
            adjacent_scale_delta(left, geometry_view(RangeRecord("OTHER", 4, "", "", 1.0, 0.0)))

    def test_firewall_blocks_confirmation_without_opening_observations(self) -> None:
        guard = PartitionGuard.from_manifest(PARTITION)
        self.assertEqual(257, len(guard.discovery_session_ids))
        self.assertEqual(69, len(guard.confirmation_session_ids))
        discovery_id = next(iter(guard.discovery_session_ids))
        confirmation_id = next(iter(guard.confirmation_session_ids))
        guard.admit_session(discovery_id, "DISCOVERY")
        with self.assertRaises(ConfirmationAccessError):
            guard.admit_session(confirmation_id, "CONFIRMATION")
        with self.assertRaises(ConfirmationAccessError):
            guard.guard_path(Path("D:/obs-open-01/confirmation/raw-observations.tsv"))

    def test_protocol_does_not_require_real_observation_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            guard = PartitionGuard.from_manifest(PARTITION)
            guard.guard_path(Path(temp) / "synthetic-discovery-fixture.tsv")


if __name__ == "__main__":
    unittest.main()
