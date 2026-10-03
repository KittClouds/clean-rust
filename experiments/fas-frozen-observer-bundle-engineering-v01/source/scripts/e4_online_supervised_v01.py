#!/usr/bin/env python3
"""E4-0 scientific runner for launch by the qualified Ledger local worker.

The service worker, not this process, consumes live authority and lease fields.
This command accepts only a static artifact/path binding and never issues or
validates local authority. Invoke it only as the command in a bound
KAMMI_LOCAL_EXECUTION_V1 spec.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e4_runner_common_v05 import CONTRACT_STAGES, E4RunnerError
from e4_runner_modes_v06 import run_online_mode
from e4_supervised_execution_adapter_v01 import load_binding


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4-0 Ledger-supervised parity or feature extraction")
    parser.add_argument("--mode", choices=tuple(CONTRACT_STAGES), required=True)
    parser.add_argument("--binding", type=Path, required=True,
                        help="static Fabrique artifact/path map; contains no stage authority")
    args = parser.parse_args(argv)
    try:
        binding, binding_sha256 = load_binding(args.binding, args.mode)
        binding["_execution_binding_sha256"] = binding_sha256
        receipt = run_online_mode(binding, args.mode)
    except Exception as error:
        print(f"E4-0 supervised {args.mode} stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": receipt["status"],
        "mode": args.mode,
        "execution_adapter_id": binding["adapter_id"],
        "execution_binding_sha256": binding_sha256,
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
