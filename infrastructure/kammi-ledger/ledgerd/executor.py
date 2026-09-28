"""Qualified local process launch guarded by a live fencing token."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from .core import Ledger
from .processes import terminate_tree


class StaleLease(RuntimeError):
    pass


def run_fenced(
    ledger: Ledger, *, lease_id: str, resource_id: str,
    fencing_token: int, actor_id: str, run_id: str,
    argv: list[str], cwd: Path, timeout_seconds: float = 60.0,
) -> tuple[int, bytes, bytes]:
    if not argv or any(not isinstance(part, str) or not part for part in argv):
        raise ValueError("argv must contain nonempty string arguments")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with ledger.lock:
            if not ledger.leases.valid(
                lease_id, resource_id, fencing_token, actor_id, run_id
            ):
                raise StaleLease("fencing token is not current at launch")
            process = subprocess.Popen(
                argv, cwd=str(cwd), shell=False, stdout=stdout, stderr=stderr,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout_seconds
        try:
            while process.poll() is None:
                with ledger.lock:
                    valid = ledger.leases.valid(
                        lease_id, resource_id, fencing_token, actor_id, run_id
                    )
                if not valid:
                    raise StaleLease("fencing token expired while process ran")
                if time.monotonic() >= deadline:
                    raise TimeoutError("fenced process timed out")
                time.sleep(0.05)
        except (StaleLease, TimeoutError):
            terminate_tree(process)
            raise
        stdout.seek(0)
        stderr.seek(0)
        return process.returncode, stdout.read(), stderr.read()
