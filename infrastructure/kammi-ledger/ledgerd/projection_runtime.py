"""Pinned native backend and bounded memory for disposable projections."""
import gc
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def open_database(root: Path, filename: str):
    import ladybug as lb

    def quarantine(detail: str):
        gc.collect()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        quarantine_dir = root / "projection-recovery" / (filename + "-" + stamp)
        quarantine_dir.mkdir(parents=True)
        files = []
        for path in sorted(root.glob(filename + "*")):
            if path.is_symlink() or not path.is_file():
                raise ValueError("projection recovery encountered unsupported path")
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            target = quarantine_dir / path.name
            path.replace(target)
            files.append({"file": path.name, "sha256": digest, "bytes": target.stat().st_size})
        receipt = {"schema": "KAMMI_PROJECTION_RECOVERY_V1", "authority": "DIAGNOSTIC_ONLY",
                   "reason": detail, "files": files, "recovery": "replay_from_CAS_and_journal"}
        (quarantine_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    # A native crash during Ladybug WAL recovery cannot be caught by Python.
    # Probe in a disposable process before the authority process opens the DB.
    # The store owner lock has already been acquired by Ledger at this point.
    wal = root / (filename + ".wal")
    if wal.is_file() and wal.stat().st_size and os.environ.get("KAMMI_NATIVE_PROBE") != "1":
        code = ("import ladybug as lb,sys; d=lb.Database(sys.argv[1],backend='capi',"
                "buffer_pool_size=256*1024*1024,max_num_threads=2); d.close()")
        try:
            probe = subprocess.run([sys.executable, "-c", code, str(root / filename)],
                                   capture_output=True, timeout=60,
                                   env={**os.environ, "KAMMI_NATIVE_PROBE": "1"})
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("native projection preflight timed out") from exc
        if probe.returncode in {-1073740791, 3221226505, -1073741819, 3221225477}:
            quarantine(f"native Ladybug WAL probe crashed: {probe.returncode}")
        elif probe.returncode:
            detail = probe.stderr.decode(errors="replace")[-2000:]
            if any(term in detail.lower() for term in
                   ("corrupted wal", "invalid wal record", "checksum mismatch",
                    "wal file is corrupted", "checksum verification failed")):
                quarantine("native Ladybug WAL probe rejected projection: " + detail[-500:])
            else:
                raise RuntimeError("native projection preflight failed: " + detail[-1000:])

    def create():
        return lb.Database(str(root / filename), backend="capi",
                           buffer_pool_size=256 * 1024 * 1024, max_num_threads=2)
    try:
        return create()
    except RuntimeError as exc:
        if not any(term in str(exc).lower() for term in ("corrupted wal", "invalid wal record", "checksum mismatch",
                                                        "wal file is corrupted", "checksum verification failed")):
            raise
        detail = str(exc)
    # Preserve corrupted derived bytes; never alter CAS or either journal.
    quarantine(detail)
    return create()
