"""Compare actual routed novel requests at fixed coverage; never publish a graph.

The first run in each process is warmup. Preserve all entity/mention/candidate
outputs exactly before considering a thread-count change for the live bundle.
"""
import json
from pathlib import Path
import statistics
import subprocess
import sys

bridge, descriptor, document, destination = map(Path, sys.argv[1:])
destination.mkdir(parents=True, exist_ok=True)
bundle = json.loads(descriptor.read_text())
rows = []
for index, threads in enumerate((8, 4, 2, 1, 4, 8)):
    root = destination / f"{index:02d}-threads-{threads}"
    root.mkdir(exist_ok=False)
    candidate = dict(bundle, threads=threads)
    (root / "gliner25.json").write_text(json.dumps(candidate, indent=2))
    with (root / "stderr.log").open("wb") as stderr:
        result = subprocess.run(
            [str(bridge), "probe-ner", str(root), str(document), "3"],
            stdout=subprocess.PIPE, stderr=stderr, timeout=240,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    (root / "stdout.jsonl").write_bytes(result.stdout)
    result.check_returncode()
    runs = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(runs) == 3
    row = dict(threads=threads, runs=runs,
               median_warm_micros=statistics.median(r["dynamic_ner_micros"] for r in runs[1:]))
    rows.append(row)
    print(json.dumps({k: v for k, v in row.items() if k != "runs"}), flush=True)
    (destination / "results.json").write_text(json.dumps(rows, indent=2))
hashes = {run["output_hash"] for row in rows for run in row["runs"]}
print(json.dumps(dict(exact_output_parity=len(hashes) == 1, output_hashes=sorted(hashes))), flush=True)
if len(hashes) != 1:
    raise SystemExit("Thread sweep changed outputs; do not promote on speed alone")
