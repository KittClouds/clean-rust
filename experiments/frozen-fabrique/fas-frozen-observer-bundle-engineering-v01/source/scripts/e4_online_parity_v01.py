#!/usr/bin/env python3
"""E4-0 stage runner entrypoint; heavyweight runtime imports remain lazy."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e4_runner_common_v01 import CONTRACT_STAGES, E4RunnerError
from e4_runner_artifacts_v01 import load_authorization
from e4_runner_modes_v01 import authorized_tokenizer_panel, run_online_mode

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4-0 exact parity and fresh feature extraction runner")
    parser.add_argument("--mode", choices=tuple(CONTRACT_STAGES), required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        authorization = load_authorization(args.authorization.resolve(strict=True))
        if args.mode == "materialize-parity-panel":
            receipt = authorized_tokenizer_panel(authorization)
        else:
            receipt = run_online_mode(authorization, args.mode)
    except Exception as error:
        print(f"E4-0 {args.mode} stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": receipt["status"], "mode": args.mode}, ensure_ascii=True, sort_keys=True))
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
