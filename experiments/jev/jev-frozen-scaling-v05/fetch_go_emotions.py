"""Read-only Hugging Face Dataset Viewer extraction for raw GoEmotions."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://datasets-server.huggingface.co/rows"
DATASET = "google-research-datasets/go_emotions"
CONFIG = "raw"
SPLIT = "train"
TOTAL = 211_225


def fetch(offset: int, length: int, retries: int = 4) -> tuple[int, list[dict]]:
    query = urlencode(
        {"dataset": DATASET, "config": CONFIG, "split": SPLIT, "offset": offset, "length": length}
    )
    request = Request(f"{API}?{query}", headers={"User-Agent": "jev-v05-research/0.1"})
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return offset, [item["row"] for item in payload.get("rows", [])]
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    total = min(TOTAL, max(100, args.limit))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pages: dict[int, list[dict]] = {}
    offsets = range(0, total, 100)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, offset, min(100, total - offset)) for offset in offsets]
        for future in as_completed(futures):
            offset, rows = future.result()
            pages[offset] = rows
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for offset in sorted(pages):
            for row in pages[offset]:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
                count += 1
    print(json.dumps({"dataset": DATASET, "config": CONFIG, "split": SPLIT, "requested_rows": total, "rows": count}))


if __name__ == "__main__":
    main()
