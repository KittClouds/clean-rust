"""Stage controller for the qualification-only F4-SYMMETRY-01 lineage."""
from __future__ import annotations

import argparse
from pathlib import Path

from f4_symmetry_01_common import OUT_REL, REPO, ROOT, write_json
from f4_symmetry_01_prepare import collect_native, prepare, preflight
from f4_symmetry_01_fit import run_fits
from f4_symmetry_01_integrity import analyze, integrity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "collect", "prepare", "fit", "integrity", "analyze"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / OUT_REL)
    parser.add_argument("--predecessor-stop", type=Path)
    parser.add_argument("--lineage", type=Path, default=REPO / "experiments/fly-reach-02-v0.1b")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out
    try:
        if args.phase == "preflight":
            if args.binary is None:
                parser.error("--binary is required for preflight")
            preflight(args.binary, out, args.predecessor_stop)
        elif args.phase == "collect":
            collect_native(out, args.lineage)
        elif args.phase == "prepare":
            prepare(out, args.lineage)
        elif args.phase == "fit":
            run_fits(out)
        elif args.phase == "integrity":
            integrity(out)
        else:
            analyze(out)
    except Exception as error:
        if out.is_dir():
            receipt_name = {
                "preflight": "PREFLIGHT-STOP-RECEIPT.json",
                "collect": "COLLECTION-STOP-RECEIPT.json",
                "prepare": "PREPARATION-STOP-RECEIPT.json",
                "fit": "FIT-STOP-RECEIPT.json",
                "integrity": "INTEGRITY-STOP-RECEIPT.json",
                "analyze": "ANALYSIS-STOP-RECEIPT.json",
            }[args.phase]
            path = out / receipt_name
            if not path.exists():
                try:
                    write_json(path, {
                        "schema": "F4-SYMMETRY-01-stop-receipt-v1",
                        "phase": args.phase,
                        "status": "STOP",
                        "first_mismatch": f"{type(error).__name__}: {error}",
                        "measured_namespace_created": False,
                    })
                except OSError:
                    pass
        raise


if __name__ == "__main__":
    main()
