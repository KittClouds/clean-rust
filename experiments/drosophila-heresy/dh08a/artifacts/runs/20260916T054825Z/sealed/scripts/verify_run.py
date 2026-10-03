"""Self-contained DH-08A archive hash and manifest verifier."""

import hashlib
import json
import pathlib
import sys

if sys.flags.optimize != 0:
    raise RuntimeError("DH-08A verification forbids optimized Python")


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


require(len(sys.argv) == 2, "usage: verify_run.py RUN_DIRECTORY")
run = pathlib.Path(sys.argv[1]).resolve()
seal = json.loads((run / "seal.json").read_text())
completion = json.loads((run / "completion.json").read_text())
require(digest(run / "seal.json") == completion["seal_sha256"], "seal hash mismatch")
global_marker = run.parent / "DH08A_MEASURED_SEEDS_OPENED.json"
require(digest(global_marker) == completion["global_open_marker_sha256"],
        "repository-wide measured-seed marker mismatch")

sealed = run / "sealed"
actual_frozen = {str(path.relative_to(sealed)) for path in sealed.rglob("*") if path.is_file()}
require(actual_frozen == set(seal["fingerprints"]), "sealed manifest membership mismatch")
for name, expected in seal["fingerprints"].items():
    require(digest(sealed / name) == expected, f"sealed hash mismatch: {name}")

actual_outputs = {
    str(path.relative_to(run)) for path in run.rglob("*")
    if path.is_file() and sealed not in path.parents
    and path.name not in {"seal.json", "completion.json"}
}
require(actual_outputs == set(completion["output_hashes"]), "output manifest membership mismatch")
for name, expected in completion["output_hashes"].items():
    require(digest(run / name) == expected, f"output hash mismatch: {name}")

require(completion["frozen_inputs_reverified"] is True, "completion lacks frozen-input receipt")
require(completion["parent_dh07r_reverified"] is True, "completion lacks parent receipt")
require(completion["q07_reverified"] is True, "completion lacks Q07 receipt")
print(json.dumps({
    "status": "VERIFIED",
    "run": str(run),
    "sealed_files": len(actual_frozen),
    "output_files": len(actual_outputs),
    "scientific_sample_size_increased": False,
}, indent=2))
