from __future__ import annotations

import json

from .contracts import BANK
from .supervision import observable_row


def read_inputs(split: str, limit: int) -> list[dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("Only TRAIN/DEV construction is available; TEST truth stays closed")
    rows = []
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as src:
        for line in src:
            if line.strip():
                rows.append(observable_row(json.loads(line)))
            if len(rows) >= limit:
                break
    if len(rows) != limit or len({r["world_id"] for r in rows}) != limit:
        raise ValueError("input count/unique row identity mismatch")
    return rows


def read_worlds(split: str, wanted: set[str]) -> dict[str, dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("TEST truth construction is prohibited")
    found = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as src:
        for line in src:
            world = json.loads(line)
            if world["world_id"] in wanted:
                found[world["world_id"]] = world
            if len(found) == len(wanted):
                break
    if set(found) != wanted:
        raise ValueError("missing canonical worlds")
    return found


if __name__ == "__main__":
    from .construct import main
    main()
