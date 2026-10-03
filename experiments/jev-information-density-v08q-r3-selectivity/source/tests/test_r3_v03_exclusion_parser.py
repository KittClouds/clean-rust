from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "build_r3_v03_exclusion_sets_v01.py"
SPEC = importlib.util.spec_from_file_location("r3_exclusion_builder", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TargetFreeIdentityParserTests(unittest.TestCase):
    def test_extracts_only_five_identity_strings_and_skips_target_array(self) -> None:
        raw = (
            b'{"target":[{"text":"braces } ] and quote \\\""},[0.25,0.75]],'
            b'"world_id":"world-1","root_id":"root-1","episode_id":"ep-1",'
            b'"full_rendered_input_hash":"render-1","selector_input_hash":"selector-1"}'
        )
        decoded: list[str] = []
        original = MODULE.json.loads

        def capture(value: bytes | str, *args: object, **kwargs: object) -> object:
            decoded.append(value.decode("utf-8") if isinstance(value, bytes) else value)
            return original(value, *args, **kwargs)

        with patch.object(MODULE.json, "loads", side_effect=capture):
            result = MODULE.target_free_identity_fields(raw)

        self.assertEqual(set(result), set(MODULE.FIELDS))
        self.assertEqual(result["world_id"], "world-1")
        self.assertTrue(all("braces" not in token for token in decoded))
        self.assertIn('"target"', decoded)  # key only; its array value is skipped bytewise

    def test_rejects_missing_identity_field(self) -> None:
        raw = b'{"world_id":"w","root_id":"r","episode_id":"e","full_rendered_input_hash":"h"}'
        with self.assertRaisesRegex(ValueError, "lacks"):
            MODULE.target_free_identity_fields(raw)

    def test_rejects_duplicate_identity_field(self) -> None:
        raw = (
            b'{"world_id":"w","world_id":"w2","root_id":"r","episode_id":"e",'
            b'"full_rendered_input_hash":"h","selector_input_hash":"s"}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            MODULE.target_free_identity_fields(raw)


if __name__ == "__main__":
    unittest.main()
