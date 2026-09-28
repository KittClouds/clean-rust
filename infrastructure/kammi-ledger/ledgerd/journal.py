"""Durable hash-chained event frames with recoverable incomplete tails."""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from typing import Iterator

from .identity import canonical, strict_json, typed_id
from .faults import hit
from .vocabulary import validate_event

MAX_EVENT_BYTES = 16 * 1024 * 1024
ZERO_EVENT = "sha256:" + "0" * 64


def _write_all(output, view):
    while view:
        written = output.write(view)
        if not written:
            raise OSError("journal write made no progress")
        view = view[written:]


class EventJournal:
    def __init__(self, root: Path) -> None:
        self.root = root / "journal"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.log"
        self.path.touch(exist_ok=True)
        self.events = self._scan(repair_tail=True)
        self.identities = {identity for _, identity in self.events}
        self.by_request = {event["request_id"]: (event, event_id) for event, event_id in self.events}

    def _quarantine_tail(self, source, offset: int) -> None:
        source.seek(offset)
        tail = source.read()
        recovery = self.root / "recovery"
        recovery.mkdir(exist_ok=True)
        tag = hashlib.sha256(tail).hexdigest()
        path = recovery / f"{offset}-{tag}.partial"
        if not path.exists():
            with path.open("xb") as output:
                output.write(tail)
                output.flush()
                os.fsync(output.fileno())
        source.truncate(offset)
        source.flush()
        os.fsync(source.fileno())

    def _scan(self, repair_tail: bool) -> list[tuple[dict, str]]:
        events: list[tuple[dict, str]] = []
        requests = set()
        mode = "r+b" if repair_tail else "rb"
        with self.path.open(mode) as source:
            while True:
                offset = source.tell()
                header = source.read(4)
                if not header:
                    break
                if len(header) < 4:
                    if not repair_tail:
                        raise ValueError("incomplete journal header")
                    self._quarantine_tail(source, offset)
                    break
                (length,) = struct.unpack(">I", header)
                if not 0 < length <= MAX_EVENT_BYTES:
                    raise ValueError("invalid journal frame length")
                raw = source.read(length)
                checksum = source.read(32)
                if len(raw) < length or len(checksum) < 32:
                    if not repair_tail:
                        raise ValueError("incomplete journal frame")
                    self._quarantine_tail(source, offset)
                    break
                if hashlib.sha256(raw).digest() != checksum:
                    raise ValueError(f"journal checksum mismatch at {offset}")
                event = strict_json(raw)
                validate_event(event)
                if event["request_id"] in requests:
                    raise ValueError("duplicate journal request ID")
                requests.add(event["request_id"])
                if canonical(event) != raw:
                    raise ValueError(f"noncanonical journal event at {offset}")
                prev = events[-1][1] if events else ZERO_EVENT
                if event.get("seq") != len(events) + 1 or event.get("prev") != prev:
                    raise ValueError(f"broken journal chain at {offset}")
                events.append((event, typed_id("event", event)))
        return events

    @property
    def head(self) -> str:
        return self.events[-1][1] if self.events else ZERO_EVENT

    def append(self, event: dict) -> str:
        validate_event(event)
        request_id = event.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id required")
        if request_id in self.by_request:
            old, old_id = self.by_request[request_id]
            if old["type"] != event["type"] or old["payload_artifact"] != event["payload_artifact"]:
                raise ValueError("request_id reused with different operation")
            return old_id
        if event.get("seq") != len(self.events) + 1 or event.get("prev") != self.head:
            raise ValueError("event sequence/head mismatch")
        raw = canonical(event)
        if len(raw) > MAX_EVENT_BYTES:
            raise ValueError("event too large")
        frame = struct.pack(">I", len(raw)) + raw + hashlib.sha256(raw).digest()
        with self.path.open("ab", buffering=0) as output:
            view = memoryview(frame)
            split = len(frame) // 2
            _write_all(output, view[:split])
            hit("journal.mid_frame")
            _write_all(output, view[split:])
            hit("journal.before_fsync")
            os.fsync(output.fileno())
            hit("journal.after_fsync")
        event_id = typed_id("event", event)
        self.events.append((event, event_id))
        self.identities.add(event_id)
        self.by_request[request_id] = (event, event_id)
        return event_id

    def __iter__(self) -> Iterator[tuple[dict, str]]:
        return iter(self.events)

