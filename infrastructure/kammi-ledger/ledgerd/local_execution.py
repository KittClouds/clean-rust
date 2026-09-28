"""Ledger-authorized local process boundary and bounded file import."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from .identity import require_id, strict_json


SPEC_FIELDS = frozenset({
    "schema", "run_id", "stage_id", "actor_id", "command", "cwd",
    "output_root", "expected_outputs", "max_output_bytes", "timeout_seconds",
    "poll_seconds", "source_files",
})
MAX_LOCAL_OUTPUT = 8 * 1024 * 1024 * 1024


def checked_spec(ledger, run_id: str, stage_id: str, actor_id: str) -> dict:
    binding = ledger.policy.specs.get((run_id, stage_id, "EXECUTION"))
    if binding is None:
        raise ValueError("local execution spec is not bound")
    spec = strict_json(ledger.cas.get(binding["artifact_id"]))
    if set(spec) != SPEC_FIELDS or spec["schema"] != "KAMMI_LOCAL_EXECUTION_V1":
        raise ValueError("local execution spec does not match v1")
    if any(spec[key] != value for key, value in (
        ("run_id", run_id), ("stage_id", stage_id), ("actor_id", actor_id),
    )):
        raise ValueError("local execution spec scope differs from authorization")
    if not isinstance(spec["command"], list) or not spec["command"] or any(
        not isinstance(item, str) or not item for item in spec["command"]
    ):
        raise ValueError("local command must be a nonempty argv list")
    if not isinstance(spec["expected_outputs"], list) or not spec["expected_outputs"]:
        raise ValueError("local output inventory must be nonempty")
    if len(spec["expected_outputs"]) != len(set(spec["expected_outputs"])):
        raise ValueError("duplicate local output names")
    for name in spec["expected_outputs"]:
        valid_relative(name)
    if not isinstance(spec["source_files"], list) or not spec["source_files"]:
        raise ValueError("local source inventory must be nonempty")
    if not isinstance(spec["max_output_bytes"], int) or isinstance(spec["max_output_bytes"], bool) or not 0 < spec["max_output_bytes"] <= MAX_LOCAL_OUTPUT:
        raise ValueError("invalid local output cap")
    if not isinstance(spec["timeout_seconds"], int) or not 0 < spec["timeout_seconds"] <= 86400:
        raise ValueError("invalid local timeout")
    if not isinstance(spec["poll_seconds"], int) or not 1 <= spec["poll_seconds"] <= 10:
        raise ValueError("invalid local polling interval")
    for key in ("cwd", "output_root"):
        if not isinstance(spec[key], str) or not Path(spec[key]).is_absolute():
            raise ValueError("local path must be absolute")
    if not Path(spec["cwd"]).is_dir():
        raise ValueError("local working directory is unavailable")
    for source in spec["source_files"]:
        if set(source) != {"path", "sha256", "bytes"} or not Path(source["path"]).is_absolute():
            raise ValueError("invalid local source identity")
        if not isinstance(source["bytes"], int) or source["bytes"] < 0:
            raise ValueError("invalid local source size")
        require_id(source["sha256"])
    return spec


def valid_relative(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("invalid local output name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts) or str(path) != name:
        raise ValueError("local output name escapes its root")
    return path


def verify_source_files(spec: dict) -> None:
    for entry in spec["source_files"]:
        path = Path(entry["path"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != entry["bytes"]:
            raise ValueError("local source missing or changed")
        with path.open("rb") as stream:
            actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != entry["sha256"]:
            raise ValueError("local source hash changed")


def live_local(ledger, body: dict, *, launch: bool = False) -> dict:
    """Call under ledger.lock. Every returned capability is current and scoped."""
    actor, run, stage = (body[key] for key in ("actor_id", "run_id", "stage_id"))
    resource, lease, fence = (body[key] for key in ("resource_id", "lease_id", "fencing_token"))
    if ledger.flight_state()["state"] != "OPEN":
        raise ValueError("Library acceptance is not current")
    if not ledger.authorization_valid(body["authorization_id"], actor, run, stage):
        raise ValueError("stage authorization is stale")
    policy = ledger.policy.current_policy_hash(stage)
    if not policy or ledger.authority.matching_grant(actor, "execute_local", run, stage, policy) is None:
        raise ValueError("execute_local grant missing or stale")
    record = ledger.leases.leases.get(lease)
    registered = ledger.leases.resources.get(resource)
    if record is None or registered is None or record["stage_id"] != stage:
        raise ValueError("local lease does not belong to stage")
    if registered["kind"] not in {"GPU", "CPU_POOL"} or not ledger.leases.valid(
        lease, resource, fence, actor, run
    ):
        raise ValueError("local lease fence is stale")
    spec = checked_spec(ledger, run, stage, actor)
    if launch:
        verify_source_files(spec)
    return spec


def import_local_output(ledger, body: dict) -> tuple[str, str]:
    name = body["relative_path"]
    valid_relative(name)
    expected = require_id(body["expected_sha256"])
    request_id = body["request_id"]
    with ledger.lock:
        spec = live_local(ledger, body)
        if name not in spec["expected_outputs"]:
            raise ValueError("output is not declared by execution spec")
        prior = ledger.journal.by_request.get(request_id)
        if prior is not None:
            event, identity = prior
            receipt = strict_json(ledger.cas.get(event["payload_artifact"]))
            if event["type"] != "ArtifactRegistered" or receipt["artifact_id"] != expected:
                raise ValueError("output import request ID reused")
            return expected, identity
        output_root = Path(spec["output_root"]).resolve(strict=True)
        path = output_root.joinpath(*PurePosixPath(name).parts)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(output_root) or path.is_symlink() or not resolved.is_file():
            raise ValueError("output path is not an ordinary file inside bound root")
        if resolved.stat().st_size > spec["max_output_bytes"]:
            raise ValueError("local output exceeds bound cap")
    # Large copy and hash happen outside the custody lock. A stale capability
    # leaves at most an orphan CAS object and can never commit an artifact event.
    identity, byte_count = ledger.cas.put_file(resolved)
    if identity != expected:
        raise ValueError("local output bytes differ from declared identity")
    with ledger.lock:
        current = live_local(ledger, body)
        if current != spec or resolved != path.resolve(strict=True):
            raise ValueError("local output binding changed during import")
        payload = {"artifact_id": identity, "byte_count": byte_count,
                   "kind": body["kind"], "media_type": "application/octet-stream",
                   "schema_id": "raw-v1", "source_location": str(resolved)}
        event = ledger._emit("ArtifactRegistered", payload, body["actor_id"], request_id,
                             guard=lambda: ledger.authorization_valid(
                                 body["authorization_id"], body["actor_id"],
                                 body["run_id"], body["stage_id"]) and ledger.leases.valid(
                                 body["lease_id"], body["resource_id"], body["fencing_token"],
                                 body["actor_id"], body["run_id"]))
        return identity, event
