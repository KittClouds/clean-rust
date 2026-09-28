"""Minimal receipt-shape reviewer for Q10-DA1.

The stronger numerical replay lives in supervision/q10-pi-da/audit_da.py and
is intentionally kept outside the sealed Rust source manifest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def review(path: Path) -> None:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["protocol"] == "Q10-DA1"
    assert receipt["status"] == "DA1_EVENT_COMPLETE"
    assert receipt["candidate_steps"] == [0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16]
    assert len(receipt["sets"]) == 4
    for result in receipt["sets"]:
        assert result["support_disjoint_over_all_rows"]
        assert result["assembled_full_replay_bitwise_equal"]
        assert result["replay_implementation_status"] == "ASSEMBLED_FULL_REPLAY_PARITY_PASS"
        assert len(result["nested_prefix_curve"]) == 6
        assert len(result["selected_coordinates"]) == len(result["coordinates"])
    print(f"Q10-DA receipt shape passed: {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: review_q10_da.py EVENT.json")
    review(Path(sys.argv[1]))
