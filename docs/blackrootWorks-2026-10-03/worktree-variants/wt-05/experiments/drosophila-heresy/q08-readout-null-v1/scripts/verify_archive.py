"""Verify a Q08 failed-qualification evidence archive without rerunning a learner."""

import hashlib
import json
import pathlib
import sys

if sys.flags.optimize or len(sys.argv) != 2:
    raise RuntimeError("usage: verify_archive.py ARCHIVE_DIRECTORY (without Python -O)")
out = pathlib.Path(sys.argv[1]).resolve()
archive = json.loads((out / "archive.json").read_text())
snapshot = out / "snapshot"
actual = {str(path.relative_to(snapshot)) for path in snapshot.rglob("*") if path.is_file()}
if actual != set(archive["fingerprints"]):
    raise RuntimeError("snapshot membership mismatch")
for name, expected in archive["fingerprints"].items():
    with (snapshot / name).open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
            raise RuntimeError(f"snapshot hash mismatch: {name}")
if archive["scientific_seed_bundles_used"] != 0 or archive["full_qualification_executed"]:
    raise RuntimeError("qualification scope mismatch")
print(json.dumps({"status": "VERIFIED", "files": len(actual),
                  "evidence_kind": archive["kind"], "scientific_sample_size_increased": False}, indent=2))
