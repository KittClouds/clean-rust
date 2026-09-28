"""Event-derived exclusive resource leases with monotonic fencing tokens."""

from __future__ import annotations

from datetime import datetime, timezone

from .authority import utc
from .graph import SAFE

RESOURCE_KINDS = frozenset({
    "GPU", "CPU_POOL", "HOST", "REMOTE_WORKER", "DATASET_LOCK",
    "PANEL_LOCK", "FILESYSTEM_EXCLUSIVE",
})


def resource_payload(resource_id: str, kind: str, host: str,
                     constraints: dict) -> dict:
    for value in (resource_id, host):
        if not isinstance(value, str) or not SAFE.fullmatch(value):
            raise ValueError("invalid resource ID or host")
    if kind not in RESOURCE_KINDS:
        raise ValueError("unsupported resource kind")
    if not isinstance(constraints, dict) or any(
        not isinstance(key, str) or not SAFE.fullmatch(key)
        or not isinstance(value, str) or len(value) > 160
        for key, value in constraints.items()
    ):
        raise ValueError("invalid resource constraints")
    return {
        "resource_id": resource_id, "kind": kind,
        "host": host, "constraints": constraints,
    }


class LeaseState:
    def __init__(self) -> None:
        self.resources: dict[str, dict] = {}
        self.leases: dict[str, dict] = {}
        self.active: dict[str, str] = {}
        self.fencing: dict[str, int] = {}
        self.by_request: dict[str, tuple[str, dict]] = {}

    def apply(self, kind: str, payload: dict) -> None:
        if kind == "ResourceRegistered":
            rid = payload["resource_id"]
            if rid in self.resources and self.resources[rid] != payload:
                raise ValueError("resource identity collision")
            self.resources[rid] = payload
        elif kind == "LeaseGranted":
            rid = payload["resource_id"]
            token = payload["fencing_token"]
            if token != self.fencing.get(rid, 0) + 1:
                raise ValueError("non-monotonic lease fencing token")
            self.fencing[rid] = token
            self.leases[payload["lease_id"]] = payload
            self.active[rid] = payload["lease_id"]
            self.by_request[payload["request_id"]] = (kind, payload)
        elif kind == "LeaseDenied":
            self.by_request[payload["request_id"]] = (kind, payload)
        elif kind == "LeaseRenewed":
            self.leases[payload["lease_id"]] = {
                **self.leases[payload["lease_id"]],
                "expires_utc": payload["expires_utc"],
            }
        elif kind in ("LeaseExpired", "LeaseReleased"):
            rid = payload["resource_id"]
            if self.active.get(rid) == payload["lease_id"]:
                del self.active[rid]

    def valid(self, lease_id: str, resource_id: str, fencing_token: int,
              actor_id: str, run_id: str, at: datetime | None = None) -> bool:
        lease = self.leases.get(lease_id)
        if lease is None:
            return False
        return (
            self.active.get(resource_id) == lease_id
            and lease["resource_id"] == resource_id
            and lease["fencing_token"] == fencing_token
            and self.fencing.get(resource_id) == fencing_token
            and lease["actor_id"] == actor_id
            and lease["run_id"] == run_id
            and utc(lease["expires_utc"]) > (at or datetime.now(timezone.utc))
        )

    def report(self, resource_id: str, at: datetime | None = None) -> dict:
        if resource_id not in self.resources:
            raise ValueError("unknown resource")
        lease_id = self.active.get(resource_id)
        lease = self.leases.get(lease_id) if lease_id else None
        valid = bool(lease and utc(lease["expires_utc"]) > (at or datetime.now(timezone.utc)))
        return {
            "resource": self.resources[resource_id],
            "fencing_counter": self.fencing.get(resource_id, 0),
            "active_lease": lease if valid else None,
        }
