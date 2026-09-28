"""Receipt-shape checks for Q10-PI1; numerical replay is external."""
import json
import sys
from pathlib import Path


def review(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["protocol"] == "Q10-PI1"
    assert len(value["events"]) == 8
    assert len(value["failures"]) == 0
    for event in value["events"]:
        assert event["pair_count"] == 96
        assert event["shared_pair_count"] == 64
        assert event["disjoint_pair_count"] == 32
        assert all(len(pair["candidates"]) == 100 for pair in event["pairs"])
    print(f"Q10-PI map receipt shape passed: {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: review_q10_pi.py PAIR_MAP.json")
    review(Path(sys.argv[1]))
