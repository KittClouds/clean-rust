"""Operating-system-backed single writer ownership for one ledger root."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class WriterBusy(RuntimeError):
    pass


class StoreOwner:
    def __init__(self, root: Path) -> None:
        locks = root / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        self.path = locks / "writer.lock"
        self.file = self.path.open("a+b", buffering=0)
        self.held = False
        try:
            self.file.seek(0)
            if self.file.read(1) != b"\0":
                self.file.seek(0)
                self.file.write(b"\0")
                os.fsync(self.file.fileno())
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.held = True
        except OSError as exc:
            self.file.close()
            raise WriterBusy(f"writable ledger store already owned: {root}") from exc
        self.metadata = {
            "pid": os.getpid(),
            "acquired_utc": datetime.now(timezone.utc).isoformat(),
            "root": str(root.resolve()),
        }
        # This file is diagnostic only. The OS-held byte lock is authority.
        diagnostic = locks / "owner.json"
        temp = locks / f"owner-{os.getpid()}.tmp"
        temp.write_text(json.dumps(self.metadata, sort_keys=True), encoding="utf-8")
        os.replace(temp, diagnostic)

    def close(self) -> None:
        if not self.held:
            return
        self.held = False
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()

    def __del__(self) -> None:
        if getattr(self, "held", False):
            self.close()
