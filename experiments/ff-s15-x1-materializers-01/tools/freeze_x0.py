"""Records the hashes of the frozen X0 sources once, after checking them against the commit that holds them."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from x1 import common

COMMIT = "13d87e83a702209ad35f9bfc30f00fdda4551ef3"
repo = ROOT.parents[1]
for f in common.X0_FILES:
    blob = subprocess.run(["git", "show", f"{COMMIT}:experiments/ff-s15-x0-graph-sandbox-01/{f}"], cwd=repo, capture_output=True, check=True).stdout
    import hashlib
    assert hashlib.sha256(blob).hexdigest() == common.sha256_file(common.X0 / f), f"{f} differs from commit {COMMIT[:8]}"
(ROOT / "results" / "x0-frozen.json").write_text(json.dumps({"commit": COMMIT, "files": common.x0_hashes()}, indent=1, sort_keys=True), encoding="ascii", newline="\n")
print("frozen", COMMIT[:8], len(common.X0_FILES), "files")
