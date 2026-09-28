"""Event-derived actor credentials and exact-scope grants."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from .graph import SAFE
from .identity import require_id

ACTOR_KINDS = frozenset({"human", "agent", "service", "remote_worker", "auditor"})
ACTIONS = frozenset({
    "create_run", "register_artifact", "create_seal", "bind_spec",
    "authorize_stage", "open_panel", "acquire_lease", "execute_bundle",
    "execute_local",
    "record_memory", "register_adapter", "apply_adapter",
})


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


class AuthorityState:
    def __init__(self) -> None:
        self.actors: dict[str, dict] = {}
        self.grants: dict[str, dict] = {}

    def apply(self, kind: str, payload: dict) -> None:
        if kind == "ActorRegistered":
            actor_id = payload["actor_id"]
            if actor_id in self.actors and self.actors[actor_id] != payload:
                raise ValueError("actor identity collision")
            self.actors[actor_id] = payload
        elif kind == "GrantIssued":
            grant_id = payload["grant_id"]
            if grant_id in self.grants and self.grants[grant_id] != payload:
                raise ValueError("grant identity collision")
            self.grants[grant_id] = payload

    def verify_credential(self, actor_id: str, token: str) -> bool:
        actor = self.actors.get(actor_id)
        if actor is None:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, actor["credential_sha256"])

    def matching_grant(
        self, actor_id: str, action: str, run_id: str, stage_id: str,
        policy_hash: str, at: datetime | None = None,
    ) -> str | None:
        now = at or datetime.now(timezone.utc)
        for grant_id, grant in self.grants.items():
            if (
                grant["actor_id"] == actor_id
                and grant["action"] == action
                and grant["run_id"] == run_id
                and grant["stage_id"] == stage_id
                and grant["policy_hash"] == policy_hash
                and utc(grant["expires_utc"]) > now
            ):
                return grant_id
        return None


def actor_payload(actor_id: str, kind: str, lab: str, credential_sha256: str) -> dict:
    if not all(isinstance(value, str) and SAFE.fullmatch(value) for value in (actor_id, lab)):
        raise ValueError("invalid actor/lab ID")
    if kind not in ACTOR_KINDS:
        raise ValueError("unknown actor kind")
    if len(credential_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in credential_sha256):
        raise ValueError("invalid credential digest")
    return {
        "actor_id": actor_id, "kind": kind, "lab": lab,
        "credential_sha256": credential_sha256,
    }


def grant_payload(
    grant_id: str, actor_id: str, action: str, run_id: str,
    stage_id: str, policy_hash: str, expires_utc: str,
) -> dict:
    for value in (grant_id, actor_id, run_id, stage_id):
        if not isinstance(value, str) or not SAFE.fullmatch(value):
            raise ValueError("invalid grant scope")
    if action not in ACTIONS:
        raise ValueError("unknown grant action")
    require_id(policy_hash)
    if utc(expires_utc) <= datetime.now(timezone.utc):
        raise ValueError("grant must expire in the future")
    return {
        "grant_id": grant_id, "actor_id": actor_id, "action": action,
        "run_id": run_id, "stage_id": stage_id,
        "policy_hash": policy_hash, "expires_utc": expires_utc,
    }
