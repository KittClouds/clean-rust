"""Fail-closed partition guard for the future OBS-OPEN-03 executor."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class ConfirmationAccessError(PermissionError):
    """Raised whenever a protocol consumer attempts to open confirmation data."""


@dataclass(frozen=True)
class PartitionGuard:
    discovery_session_ids: frozenset[str]
    confirmation_session_ids: frozenset[str]
    confirmation_status: str

    @classmethod
    def from_manifest(cls, manifest: Path) -> "PartitionGuard":
        discovery: set[str] = set()
        confirmation: set[str] = set()
        with manifest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                session_id = row["session_id"]
                if row["partition"] == "DISCOVERY":
                    discovery.add(session_id)
                elif row["partition"] == "CONFIRMATION":
                    confirmation.add(session_id)
        return cls(frozenset(discovery), frozenset(confirmation), "FROZEN_UNOPENED")

    def admit_session(self, session_id: str, declared_partition: str) -> None:
        if declared_partition != "DISCOVERY":
            raise ConfirmationAccessError("only DISCOVERY is admissible in OBS-OPEN-02")
        if session_id not in self.discovery_session_ids:
            if session_id in self.confirmation_session_ids:
                raise ConfirmationAccessError("confirmation session is FROZEN_UNOPENED")
            raise KeyError(f"unknown session: {session_id}")

    def guard_path(self, path: Path) -> None:
        normalized = str(path).replace("\\", "/").lower()
        if "confirmation" in normalized or "holdout" in normalized:
            raise ConfirmationAccessError("confirmation path is FROZEN_UNOPENED")

    def state(self) -> dict[str, object]:
        return {
            "allowed_partition": "DISCOVERY",
            "blocked_partition": "CONFIRMATION",
            "blocked_status": self.confirmation_status,
            "discovery_sessions": len(self.discovery_session_ids),
            "confirmation_sessions": len(self.confirmation_session_ids),
        }
