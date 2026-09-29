"""C2a: the complementarity census on CAL. Writes results/c2a-census.json. No policy is trained or scored.

  python run_c2a.py
"""
from __future__ import annotations

import json
import sys

from c2 import census
from c2.common import RESULTS, TAG, load_cal, sha256_file

GO_THRESHOLD = 0.25  # the preregistered rule in C2A-PLAN.md: proceed iff oracle headroom on CAL at alpha 0.05 is at least 25%


def main() -> int:
    cal = load_cal()
    tags = ["a20", "a10", "a05", "a02", "a01"]
    report = {"schema": "c2a-census/v1", "rows": int(len(cal["truth_decision"])), "primary_tag": TAG, "go_threshold": GO_THRESHOLD, "tags": {t: census.census(cal, t) for t in tags}}
    headroom = report["tags"][TAG]["group"]["oracle_headroom"]
    report["exploratory_post_hoc"] = {
        "note": "not in C2A-PLAN.md; added after the planned census was read",
        "harmful_anatomy": {t: census.harmful_anatomy(cal, t) for t in ("a05", "a10")},
        "single_surface_frontier": census.single_surface_frontier(cal, (0.05, 0.06, 0.07, 0.08, 0.09, 0.10)),
    }
    report["decision"] = {"oracle_headroom_at_primary": headroom, "proceed_to_c2b": headroom is not None and headroom >= GO_THRESHOLD}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "c2a-census.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    print(f"wrote {path.name} sha256={sha256_file(path)[:16]}")
    print(json.dumps(report["decision"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
