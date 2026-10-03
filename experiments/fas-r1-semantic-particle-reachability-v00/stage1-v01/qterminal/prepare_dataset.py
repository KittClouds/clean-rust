"""Prepare family-split Q_terminal rows from offline features and labels."""

from __future__ import annotations

import argparse
from pathlib import Path

from qterminal import ContractError, prepare_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True, help="validator-labeled candidate JSONL")
    parser.add_argument("--features", type=Path, required=True, help="R1_FEATURE_V1 directory of .npy arrays")
    parser.add_argument("--output", type=Path, required=True, help="new directory for prepared selector data")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("manifest-v02.json"),
        help="frozen Q_terminal mixture manifest",
    )
    args = parser.parse_args()
    try:
        receipt = prepare_dataset(args.candidates, args.features, args.output, args.manifest)
    except (ContractError, OSError) as error:
        parser.error(str(error))
    print(
        "prepared rows: "
        + ", ".join(f"{split}={count}" for split, count in receipt["split_counts"].items())
    )
    print("No model was loaded or fitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
