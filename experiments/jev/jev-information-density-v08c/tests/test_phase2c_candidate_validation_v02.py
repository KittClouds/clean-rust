from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import validate_phase2c_candidate_v02 as validation


class EvalMembershipTests(unittest.TestCase):
    def test_eval_manifest_mapping_is_converted_to_membership_set(self) -> None:
        self.assertEqual(
            validation.eval_id_membership({"group-a": "episode-a", "group-b": "episode-b"}),
            {"group-a", "group-b"},
        )


if __name__ == "__main__":
    unittest.main()
