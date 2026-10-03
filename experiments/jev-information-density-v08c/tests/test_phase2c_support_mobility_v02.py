from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import audit_phase2c_support_mobility_v02 as corrected


class InputDigestDomainTests(unittest.TestCase):
    def test_distinct_input_digest_domains_are_not_compared(self) -> None:
        profile = {"group_count": 100_000, "unique_roots": 25_700, "unique_inputs": 22_900}
        audit = {"banks": {"R100": {
            "group_count": 100_000,
            "unique_root_count": 25_700,
            "unique_state_query_input_count": 8_593,
        }}}
        corrected.profile_matches_audit("R100", profile, audit)

    def test_shared_profile_fields_are_still_checked(self) -> None:
        profile = {"group_count": 99_999, "unique_roots": 25_700, "unique_inputs": 22_900}
        audit = {"banks": {"R100": {
            "group_count": 100_000,
            "unique_root_count": 25_700,
            "unique_state_query_input_count": 8_593,
        }}}
        with self.assertRaises(ValueError):
            corrected.profile_matches_audit("R100", profile, audit)


if __name__ == "__main__":
    unittest.main()
