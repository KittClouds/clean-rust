from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "build_r3_v03_exclusion_sets_v02.py"
SPEC = importlib.util.spec_from_file_location("r3_exclusions_v02", SOURCE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class TargetFreeSelectionTests(unittest.TestCase):
    def test_nested_target_is_skipped_and_identity_strings_are_selected(self) -> None:
        raw = (
            b'{"target":[{"secret":"DO_NOT_PARSE"}],'
            b'"world_id":"w","root_id":"r","episode_id":"e",'
            b'"full_rendered_input_hash":"f","selector_input_hash":"s"}'
        )
        selected = module.selected_string_fields(raw, set(module.FIELDS))
        self.assertEqual(set(selected), set(module.FIELDS))
        self.assertNotIn("target", selected)
        self.assertNotIn("DO_NOT_PARSE", repr(selected))

    def test_duplicate_identity_key_fails_closed(self) -> None:
        raw = b'{"world_id":"w","world_id":"x"}'
        with self.assertRaisesRegex(ValueError, "duplicate field"):
            module.selected_string_fields(raw, {"world_id"})

    def test_missing_required_field_fails_closed(self) -> None:
        raw = b'{"world_id":"w"}'
        with self.assertRaisesRegex(ValueError, "required fields missing"):
            module.selected_string_fields(raw, set(module.FIELDS))


if __name__ == "__main__":
    unittest.main()
