"""Fail-closed DH-07 seal guard.

DH-07 failed constructor-first qualification before a measured protocol was
sealed. This entry point intentionally cannot launch or seal a scientific run.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    receipt = {
        "protocol": "DH-07",
        "status": "BLOCKED_PRESEAL_QUALIFICATION",
        "sealed": False,
        "measured_execution_allowed": False,
        "reason": (
            "The frozen strict null failed constructor-first real qualification: "
            "one context violated the true delivered acquisition-axis gate and "
            "the other exhausted 64 deterministic feasibility attempts."
        ),
        "evidence": "../qualification/constructor-first-real-seed9000.json",
    }
    print(json.dumps(receipt, indent=2))
    print("Refusing to seal or execute DH-07.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
