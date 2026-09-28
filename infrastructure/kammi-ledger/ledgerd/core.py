"""Single-writer custody operations over CAS, journal, and graph projection."""

from __future__ import annotations

import threading
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .cas import ContentStore
from .authority import AuthorityState, actor_payload, grant_payload
from .adapters import AdapterState, BUILTINS, implementation_bytes, implementation_hash
from .facts import validated_fact
from .exposure import ExposureState, PURPOSES, panel_payload
from .graph import CustodyGraph, SAFE
from .history import summarize
from .identity import canonical, require_id, strict_json
from .journal import EventJournal
from .leases import LeaseState, resource_payload
from .lifecycle import LifecycleOperations, LifecycleState
from .policy import PolicyState, evaluate, validate_policy
from .remote import RemoteState
from .remote_ops import RemoteOperations
from .release import ReleaseOperations
from .seals import make_seal, verify_lineage
from .writer import StoreOwner
from .gate_ops import GateOperations
from .vault import VaultOperations, VaultState
from .vault_portable import VaultPortable


class ProjectionLagError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"custody event committed; graph projection pending: {event_id}")


class Ledger(RemoteOperations, LifecycleOperations, ReleaseOperations, GateOperations,
             VaultOperations, VaultPortable):
    def __init__(self, root: Path, signing_key: bytes | None = None,
                 embedding_cache: Path | None = None) -> None:
        try:
            self._initialize(root, signing_key, embedding_cache)
        except BaseException:
            self.close()
            raise

    def _initialize(self, root, signing_key, embedding_cache):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.signing_private = (
            Ed25519PrivateKey.from_private_bytes(signing_key) if signing_key else None
        )
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.owner = StoreOwner(self.root)
        self.lock = threading.RLock()
        self.cas = ContentStore(self.root)
        self.journal = EventJournal(self.root)
        self.graph = CustodyGraph(self.root)
        self.artifacts: dict[str, dict] = {}
        self.seal_artifacts: dict[str, str] = {}
        self.runs: set[str] = set()
        self.run_labs: dict[str, str] = {}
        self.facts: dict[str, dict] = {}
        self.authority = AuthorityState()
        self.policy = PolicyState()
        self.exposure = ExposureState()
        self.leases = LeaseState()
        self.adapters = AdapterState()
        self.remote = RemoteState()
        self.lifecycle = LifecycleState()
        self.vaults = VaultState()
        self.library_acceptance = None
        position, head = self.graph.position()
        if position > len(self.journal.events):
            raise ValueError("graph is ahead of authoritative journal")
        expected = self.journal.events[position - 1][1] if position else self.journal.head
        if position and head != expected:
            raise ValueError("graph/journal head disagreement")
        if not position and head != "sha256:" + "0" * 64:
            raise ValueError("graph genesis head mismatch")
        for event, event_id in self.journal:
            payload = strict_json(self.cas.get(event["payload_artifact"]))
            self._index(event, payload, event_id)
            if event["seq"] > position:
                self.graph.apply(event, event_id, payload)
        self.memory = None
        if embedding_cache is not None:
            from .embedding import Embedder
            from .memory import MemoryService

            self.memory = MemoryService(self.root, self.cas, Embedder(embedding_cache),
                                        self.valid_custody_ref, self.graph.db, self.lock)

    def valid_custody_ref(self, identity: str) -> bool:
        if identity in self.artifacts:
            return self.cas.verify(identity)
        return identity in self.journal.identities

    def close(self) -> None:
        memory = getattr(self, "memory", None)
        if memory is not None:
            memory.close()
            self.memory = None
        graph = getattr(self, "graph", None)
        if graph is not None:
            graph.close()
            self.graph = None
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.close()

    def __del__(self) -> None:
        self.close()

    def _index(self, event: dict, payload: dict, event_id: str) -> None:
        kind = event["type"]
        self.authority.apply(kind, payload)
        self.policy.apply(kind, payload, event_id)
        self.exposure.apply(kind, payload)
        self.leases.apply(kind, payload)
        self.adapters.apply(kind, payload, event_id)
        self.remote.apply(kind, payload, event_id)
        self.lifecycle.apply(kind, payload, event_id)
        if kind == "VaultSourceCommitted":
            if not self.cas.verify(payload["artifact_id"]):
                raise ValueError("vault source bytes unavailable during replay")
            if self.cas.path_for(payload["artifact_id"]).stat().st_size != payload["byte_count"]:
                raise ValueError("vault source byte count changed")
        elif kind == "VaultGenerationSelected":
            for artifact_id in [payload["manifest_artifact_id"], *payload["asset_ids"]]:
                if not self.cas.verify(artifact_id):
                    raise ValueError("vault generation bytes unavailable during replay")
        elif kind == "VaultProductPrimarySelected":
            if not self.cas.verify(payload["receipt_artifact_id"]):
                raise ValueError("vault cutover receipt unavailable during replay")
        self.vaults.apply(kind, payload)
        if kind == "LibraryAccepted":
            self.library_acceptance = payload["acceptance_artifact"]
        if kind == "ArtifactRegistered":
            artifact_id = require_id(payload["artifact_id"])
            previous = self.artifacts.get(artifact_id)
            if previous and previous["byte_count"] != payload["byte_count"]:
                raise ValueError("artifact byte count collision")
            self.artifacts[artifact_id] = payload
        elif kind == "SealCreated":
            root = require_id(payload["root"])
            seal_artifact = require_id(payload["seal_artifact"])
            previous = self.seal_artifacts.get(root)
            if previous and previous != seal_artifact:
                raise ValueError("seal root collision")
            self.seal_artifacts[root] = seal_artifact
        elif kind == "RunCreated":
            self.runs.add(payload["run_id"])
            self.run_labs[payload["run_id"]] = payload["lab"]
        elif kind == "FactRecorded":
            fact_id = require_id(payload["fact_id"])
            fact = {key: value for key, value in payload.items() if key != "fact_id"}
            if validated_fact(fact, set(self.artifacts), self.runs) != payload:
                raise ValueError("invalid custody fact in journal")
            previous = self.facts.get(fact_id)
            if previous and previous != payload:
                raise ValueError("fact identity collision")
            self.facts[fact_id] = payload

    def _emit(self, kind: str, payload: dict, actor: str, request_id: str, guard=None) -> str:
        if not SAFE.fullmatch(actor) or not SAFE.fullmatch(request_id):
            raise ValueError("actor/request ID uses unsupported characters")
        payload_artifact, _ = self.cas.put_bytes(canonical(payload))
        if request_id in self.journal.by_request:
            previous, event_id = self.journal.by_request[request_id]
            if previous["type"] != kind or previous["payload_artifact"] != payload_artifact:
                raise ValueError("request ID reused with different payload")
            self.graph.apply(previous, event_id, payload)
            return event_id
        event = {
            "schema": "KAMMI_EVENT_V1",
            "seq": len(self.journal.events) + 1,
            "prev": self.journal.head,
            "type": kind,
            "payload_artifact": payload_artifact,
            "actor": actor,
            "request_id": request_id,
            "utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if guard is not None and not guard():
            raise ValueError("live commit prerequisite expired")
        event_id = self.journal.append(event)
        self._index(event, payload, event_id)
        try:
            self.graph.apply(event, event_id, payload)
        except Exception as exc:
            raise ProjectionLagError(event_id) from exc
        return event_id

    def register_file(
        self,
        source: Path,
        *,
        kind: str,
        media_type: str,
        schema_id: str,
        actor: str,
        request_id: str,
    ) -> tuple[str, str]:
        with self.lock:
            artifact_id, byte_count = self.cas.put_file(source)
            payload = {
                "artifact_id": artifact_id,
                "byte_count": byte_count,
                "kind": kind,
                "media_type": media_type,
                "schema_id": schema_id,
                "source_location": str(source.resolve()),
            }
            return artifact_id, self._emit("ArtifactRegistered", payload, actor, request_id)

    def register_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        actor: str,
        request_id: str,
    ) -> tuple[str, str]:
        with self.lock:
            artifact_id, byte_count = self.cas.put_bytes(data)
            payload = {
                "artifact_id": artifact_id,
                "byte_count": byte_count,
                "kind": kind,
                "media_type": "application/octet-stream",
                "schema_id": "raw-v1",
                "source_location": "api-upload",
            }
            return artifact_id, self._emit("ArtifactRegistered", payload, actor, request_id)

    def create_run(self, run_id: str, lab: str, actor: str, request_id: str) -> str:
        if not SAFE.fullmatch(run_id) or not SAFE.fullmatch(lab):
            raise ValueError("invalid run or lab ID")
        with self.lock:
            if run_id in self.runs and request_id not in self.journal.by_request:
                raise ValueError("run already exists")
            return self._emit(
                "RunCreated", {"run_id": run_id, "lab": lab}, actor, request_id
            )

    def register_actor(
        self, actor_id: str, kind: str, lab: str, credential_sha256: str,
        request_id: str,
    ) -> str:
        payload = actor_payload(actor_id, kind, lab, credential_sha256)
        with self.lock:
            if actor_id in self.authority.actors and request_id not in self.journal.by_request:
                raise ValueError("actor already registered")
            return self._emit("ActorRegistered", payload, "ledger-admin", request_id)

    def register_panel(self, panel_id: str, artifact_id: str, lab: str,
                       request_id: str) -> str:
        payload = panel_payload(panel_id, artifact_id, lab)
        with self.lock:
            if artifact_id not in self.artifacts:
                raise ValueError("panel bytes must be registered first")
            if panel_id in self.exposure.panels and request_id not in self.journal.by_request:
                raise ValueError("panel already registered")
            return self._emit("PanelRegistered", payload, "ledger-admin", request_id)

    def register_resource(self, resource_id: str, kind: str, host: str,
                          constraints: dict, request_id: str) -> str:
        payload = resource_payload(resource_id, kind, host, constraints)
        with self.lock:
            if resource_id in self.leases.resources and request_id not in self.journal.by_request:
                raise ValueError("resource already registered")
            return self._emit("ResourceRegistered", payload, "ledger-admin", request_id)

    def register_adapter(self, adapter_id: str, request_id: str) -> tuple[str, str]:
        item = BUILTINS.get(adapter_id)
        if item is None:
            raise ValueError("unknown built-in adapter")
        with self.lock:
            source_id, _ = self.register_bytes(
                implementation_bytes(adapter_id), kind="adapter-implementation",
                actor="ledger-admin", request_id=request_id + ":source",
            )
            expected = implementation_hash(adapter_id)
            if source_id != expected:
                raise ValueError("adapter source hash mismatch")
            payload = {
                "adapter_id": adapter_id,
                "source_schema": item["source_schema"],
                "target_schema": item["target_schema"],
                "implementation_hash": expected,
                "implementation_artifact": source_id,
                "version": item["version"],
            }
            event_id = self._emit(
                "AdapterRegistered", payload, "ledger-admin", request_id + ":registered"
            )
            return source_id, event_id

    def apply_adapter(
        self, adapter_id: str, source_artifact: str, actor_id: str,
        actor_token: str, run_id: str, stage_id: str,
        authorization_id: str, purpose: str, request_id: str,
    ) -> tuple[str, str]:
        if not SAFE.fullmatch(purpose):
            raise ValueError("invalid adapter purpose")
        with self.lock:
            registered = self.adapters.registered.get(adapter_id)
            if registered is None or source_artifact not in self.artifacts:
                raise ValueError("adapter or source artifact is unregistered")
            policy_hash = self.policy.current_policy_hash(stage_id)
            allowed = (
                self.authority.verify_credential(actor_id, actor_token)
                and self.authority.actors[actor_id]["lab"] == self.run_labs.get(run_id)
                and policy_hash is not None
                and self.authority.matching_grant(
                    actor_id, "apply_adapter", run_id, stage_id, policy_hash
                ) is not None
                and self.authorization_valid(
                    authorization_id, actor_id, run_id, stage_id
                )
            )
            if not allowed:
                raise ValueError("adapter application lacks scoped authorization")
            if registered["implementation_hash"] != implementation_hash(adapter_id):
                raise ValueError("adapter implementation drift")
            converted = BUILTINS[adapter_id]["function"](self.cas.get(source_artifact))
            derived, _ = self.register_bytes(
                converted, kind="adapter-derived-view", actor=actor_id,
                request_id=request_id + ":derived",
            )
            event_id = self._emit("AdapterApplied", {
                "adapter_id": adapter_id,
                "source_artifact_id": source_artifact,
                "derived_view_id": derived,
                "implementation_hash": registered["implementation_hash"],
                "source_schema": registered["source_schema"],
                "target_schema": registered["target_schema"],
                "purpose": purpose,
                "run_id": run_id, "stage_id": stage_id,
                "authorization_id": authorization_id,
            }, actor_id, request_id + ":applied")
            return derived, event_id

    def acquire_lease(
        self, resource_id: str, run_id: str, stage_id: str, actor_id: str,
        actor_token: str, purpose: str, ttl_seconds: int, request_id: str,
        at: datetime | None = None,
    ) -> tuple[str, dict]:
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("lease TTL must be 1..3600 seconds")
        if not SAFE.fullmatch(stage_id) or not SAFE.fullmatch(purpose):
            raise ValueError("invalid lease stage or purpose")
        with self.lock:
            resource = self.leases.resources.get(resource_id)
            if resource is None or run_id not in self.runs:
                raise ValueError("unknown resource or run")
            if not self.authority.verify_credential(actor_id, actor_token):
                raise ValueError("actor credential mismatch")
            prior = self.leases.by_request.get(request_id)
            if prior is not None:
                kind, receipt = prior
                if any(receipt[key] != value for key, value in (
                    ("resource_id", resource_id), ("run_id", run_id),
                    ("stage_id", stage_id), ("actor_id", actor_id),
                    ("purpose", purpose),
                )):
                    raise ValueError("lease request ID reused with changed scope")
                if receipt.get("requested_ttl_seconds") != ttl_seconds:
                    raise ValueError("lease request ID reused with changed TTL")
                suffix = ":granted" if kind == "LeaseGranted" else ":denied"
                return self.journal.by_request[request_id + suffix][1], receipt
            now = at or datetime.now(timezone.utc)
            base = {
                "request_id": request_id, "resource_id": resource_id,
                "run_id": run_id, "stage_id": stage_id,
                "actor_id": actor_id, "purpose": purpose,
                "requested_ttl_seconds": ttl_seconds,
            }
            if request_id + ":requested" in self.journal.by_request:
                reason = "incomplete_prior_lease_request"
            else:
                self._emit("LeaseRequested", base, actor_id, request_id + ":requested")
                old_id = self.leases.active.get(resource_id)
                if old_id and self.leases.leases[old_id]["expires_utc"]:
                    old = self.leases.leases[old_id]
                    from .authority import utc

                    if utc(old["expires_utc"]) <= now:
                        self._emit("LeaseExpired", {
                            "lease_id": old_id, "resource_id": resource_id,
                            "fencing_token": old["fencing_token"],
                        }, "ledgerd", request_id + ":expire-old")
                policy_hash = self.policy.current_policy_hash(stage_id)
                actor = self.authority.actors.get(actor_id)
                credential = self.authority.verify_credential(actor_id, actor_token)
                grant = self.authority.matching_grant(
                    actor_id, "acquire_lease", run_id, stage_id, policy_hash, now
                ) if policy_hash else None
                qualified = (
                    credential and actor is not None
                    and actor["lab"] == self.run_labs[run_id]
                    and grant is not None
                )
                reason = (
                    "unauthorized" if not qualified else
                    "occupied" if resource_id in self.leases.active else
                    "granted"
                )
            if reason != "granted":
                receipt = {**base, "decision": "DENIED", "reason": reason}
                event_id = self._emit(
                    "LeaseDenied", receipt, actor_id, request_id + ":denied"
                )
                return event_id, receipt
            token = self.leases.fencing.get(resource_id, 0) + 1
            lease_id = "lease-" + hashlib.sha256(
                (resource_id + "\0" + request_id).encode("utf-8")
            ).hexdigest()
            receipt = {
                **base, "decision": "GRANTED", "lease_id": lease_id,
                "fencing_token": token,
                "issued_utc": now.isoformat(),
                "expires_utc": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                "runtime_constraints": resource["constraints"],
            }
            event_id = self._emit("LeaseGranted", receipt, actor_id,
                                  request_id + ":granted")
            return event_id, receipt

    def renew_lease(self, lease_id: str, fencing_token: int, actor_id: str,
                    actor_token: str, ttl_seconds: int, request_id: str,
                    at: datetime | None = None) -> str:
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("lease TTL must be 1..3600 seconds")
        with self.lock:
            lease = self.leases.leases.get(lease_id)
            if lease is None or not self.authority.verify_credential(actor_id, actor_token):
                raise ValueError("unknown lease or invalid actor credential")
            if request_id in self.journal.by_request:
                prior, identity = self.journal.by_request[request_id]
                receipt = strict_json(self.cas.get(prior["payload_artifact"]))
                if prior["type"] != "LeaseRenewed" or any(receipt[k] != v for k, v in (
                    ("lease_id", lease_id), ("fencing_token", fencing_token),
                    ("actor_id", actor_id), ("requested_ttl_seconds", ttl_seconds))):
                    raise ValueError("lease renewal request ID reused")
                return identity
            if not self.leases.valid(
                lease_id, lease["resource_id"], fencing_token,
                actor_id, lease["run_id"], at,
            ):
                raise ValueError("stale or expired lease")
            now = at or datetime.now(timezone.utc)
            return self._emit("LeaseRenewed", {
                "lease_id": lease_id, "resource_id": lease["resource_id"],
                "fencing_token": fencing_token, "actor_id": actor_id,
                "expires_utc": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                "requested_ttl_seconds": ttl_seconds,
            }, actor_id, request_id)

    def release_lease(self, lease_id: str, fencing_token: int, actor_id: str,
                      actor_token: str, request_id: str) -> str:
        with self.lock:
            lease = self.leases.leases.get(lease_id)
            if lease is None or not self.authority.verify_credential(actor_id, actor_token):
                raise ValueError("unknown lease or invalid actor credential")
            if request_id in self.journal.by_request:
                prior, identity = self.journal.by_request[request_id]
                receipt = strict_json(self.cas.get(prior["payload_artifact"]))
                if prior["type"] != "LeaseReleased" or any(receipt[k] != v for k, v in (
                    ("lease_id", lease_id), ("fencing_token", fencing_token), ("actor_id", actor_id))):
                    raise ValueError("lease release request ID reused")
                return identity
            if not self.leases.valid(
                lease_id, lease["resource_id"], fencing_token,
                actor_id, lease["run_id"],
            ):
                raise ValueError("stale or expired lease")
            return self._emit("LeaseReleased", {
                "lease_id": lease_id, "resource_id": lease["resource_id"],
                "fencing_token": fencing_token, "actor_id": actor_id,
            }, actor_id, request_id)

    def open_panel(
        self, panel_id: str, purpose: str, run_id: str, stage_id: str,
        actor_id: str, actor_token: str, authorization_id: str,
        request_id: str,
    ) -> tuple[bytes | None, str, dict]:
        if purpose not in PURPOSES or not SAFE.fullmatch(stage_id):
            raise ValueError("invalid purpose or stage")
        with self.lock:
            panel = self.exposure.panels.get(panel_id)
            if panel is None or run_id not in self.runs:
                raise ValueError("unknown panel or run")
            if not self.authority.verify_credential(actor_id, actor_token):
                raise ValueError("actor credential mismatch")
            prior = self.exposure.by_request.get(request_id)
            if prior is not None:
                kind, receipt = prior
                final_key = request_id + (":opened" if kind == "ExposureOpened" else ":denied")
                event_id = self.journal.by_request[final_key][1]
                if any(receipt[key] != value for key, value in (
                    ("panel_id", panel_id), ("purpose", purpose), ("run_id", run_id),
                    ("stage_id", stage_id), ("actor_id", actor_id),
                    ("authorization_id", authorization_id),
                )):
                    raise ValueError("exposure request ID reused with different scope")
                if kind == "ExposureOpened" and not self.authorization_valid(
                    authorization_id, actor_id, run_id, stage_id
                ):
                    raise ValueError("exposure retry authorization is stale")
                data = self.cas.get(panel["artifact_id"]) if kind == "ExposureOpened" else None
                if kind == "ExposureOpened" and request_id + ":closed" not in self.journal.by_request:
                    base = {k: v for k, v in receipt.items() if k not in {"decision", "reason", "count"}}
                    self._emit("ExposureClosed", {**base, "opened_event": event_id},
                               actor_id, request_id + ":closed")
                return data, event_id, receipt
            base = {
                "request_id": request_id, "panel_id": panel_id,
                "artifact_id": panel["artifact_id"], "purpose": purpose,
                "run_id": run_id, "lab": panel["lab"],
                "stage_id": stage_id, "actor_id": actor_id,
                "authorization_id": authorization_id,
                "decision_context": "guarded_panel_gateway",
            }
            if request_id + ":requested" in self.journal.by_request:
                reason = "incomplete_prior_exposure_request"
            else:
                self._emit("ExposureRequested", base, actor_id, request_id + ":requested")
                current_policy = self.policy.current_policy_hash(stage_id)
                actor = self.authority.actors.get(actor_id)
                credential = self.authority.verify_credential(actor_id, actor_token)
                grant = self.authority.matching_grant(
                    actor_id, "open_panel", run_id, stage_id, current_policy
                ) if current_policy else None
                qualified = (
                    credential and actor is not None
                    and actor["lab"] == panel["lab"] == self.run_labs[run_id]
                    and grant is not None
                    and self.authorization_valid(
                        authorization_id, actor_id, run_id, stage_id
                    )
                )
                reason = "authorized" if qualified else "panel_access_not_authorized"
            receipt = {**base, "decision": "OPENED" if reason == "authorized" else "DENIED",
                       "reason": reason, "count": 1 if reason == "authorized" else 0}
            if reason != "authorized":
                event_id = self._emit(
                    "ExposureDenied", receipt, actor_id, request_id + ":denied"
                )
                return None, event_id, receipt
            # The event is durably committed before the panel bytes are read or returned.
            event_id = self._emit(
                "ExposureOpened", receipt, actor_id, request_id + ":opened"
            )
            data = self.cas.get(panel["artifact_id"])
            self._emit("ExposureClosed", {**base, "opened_event": event_id},
                       actor_id, request_id + ":closed")
            return data, event_id, receipt

    def issue_grant(
        self, grant_id: str, actor_id: str, action: str, run_id: str,
        stage_id: str, policy_hash: str, expires_utc: str, request_id: str,
    ) -> str:
        payload = grant_payload(
            grant_id, actor_id, action, run_id, stage_id, policy_hash, expires_utc
        )
        with self.lock:
            if actor_id not in self.authority.actors:
                raise ValueError("grant actor is unregistered")
            if run_id in self.run_labs and self.authority.actors[actor_id]["lab"] != self.run_labs[run_id]:
                raise ValueError("grant actor belongs to another lab")
            if grant_id in self.authority.grants and request_id not in self.journal.by_request:
                raise ValueError("grant already exists")
            return self._emit("GrantIssued", payload, "ledger-admin", request_id)

    def register_policy(self, policy: dict, request_id: str) -> tuple[str, str]:
        validate_policy(policy)
        with self.lock:
            artifact_id, _ = self.register_bytes(
                canonical(policy), kind="stage-policy", actor="ledger-admin",
                request_id=request_id + ":artifact",
            )
            payload = {
                "stage_id": policy["stage_id"], "version": policy["version"],
                "policy_hash": artifact_id, "artifact_id": artifact_id,
            }
            event_id = self._emit(
                "PolicyRegistered", payload, "ledger-admin", request_id + ":policy"
            )
            return artifact_id, event_id

    def bind_spec(
        self, run_id: str, stage_id: str, spec_kind: str, artifact_id: str,
        seal_root: str, actor_id: str, request_id: str,
    ) -> str:
        if spec_kind not in ("SCIENTIFIC", "EXECUTION"):
            raise ValueError("unsupported spec kind")
        if not SAFE.fullmatch(stage_id) or run_id not in self.runs:
            raise ValueError("unknown run or invalid stage")
        with self.lock:
            if artifact_id not in self.artifacts or artifact_id not in self.verify_seal(seal_root):
                raise ValueError("spec is not in verified seal")
            return self._emit("SpecBound", {
                "run_id": run_id, "stage_id": stage_id,
                "spec_kind": spec_kind, "artifact_id": artifact_id,
                "seal_root": seal_root, "status": "SEALED",
            }, actor_id, request_id)

    def record_seal_verification(
        self, run_id: str, stage_id: str, root: str,
        actor_id: str, request_id: str,
    ) -> str:
        if run_id not in self.runs or not SAFE.fullmatch(stage_id):
            raise ValueError("unknown run or invalid stage")
        with self.lock:
            closure = self.verify_seal(root)
            return self._emit("SealVerified", {
                "run_id": run_id, "stage_id": stage_id, "root": root,
                "closure_count": len(closure),
            }, actor_id, request_id)

    def record_contact(
        self, run_id: str, stage_id: str, contact_class: str,
        target: str, actor_id: str, request_id: str,
    ) -> str:
        allowed = {
            "POPULATION_GENERATED", "TOKENIZER", "MODEL", "CUDA",
            "TRUTH_LABEL", "EVAL_PANEL", "SCORING", "HUMAN_INSPECTION",
        }
        if contact_class not in allowed or run_id not in self.runs:
            raise ValueError("invalid contact class or run")
        if not SAFE.fullmatch(stage_id) or not SAFE.fullmatch(target):
            raise ValueError("invalid contact scope")
        with self.lock:
            return self._emit("ContactRecorded", {
                "run_id": run_id, "stage_id": stage_id,
                "contact_class": contact_class, "target": target,
            }, actor_id, request_id)

    def authorize_stage(
        self, run_id: str, stage_id: str, actor_id: str,
        expires_utc: str, request_id: str,
    ) -> tuple[str, dict]:
        from .authority import utc

        if run_id not in self.runs:
            raise ValueError("unknown run")
        if not SAFE.fullmatch(stage_id):
            raise ValueError("invalid stage")
        if utc(expires_utc) <= datetime.now(timezone.utc):
            raise ValueError("authorization expiry must be in the future")
        with self.lock:
            final_request = request_id + ":final"
            if final_request in self.journal.by_request:
                event, identity = self.journal.by_request[final_request]
                receipt = strict_json(self.cas.get(event["payload_artifact"]))
                if any(receipt[k] != v for k, v in (("actor_id", actor_id), ("run_id", run_id),
                                                  ("stage_id", stage_id), ("expires_utc", expires_utc))):
                    raise ValueError("authorization request ID reused with changed scope")
                return identity, receipt
            current = self.policy.policies.get(stage_id)
            if current is None:
                raise ValueError("no registered stage policy")
            policy = strict_json(self.cas.get(current["artifact_id"]))
            gpu_lease_valid = any(
                self.leases.resources[rid]["kind"] == "GPU"
                and self.leases.leases[lease_id]["stage_id"] == stage_id
                and self.leases.valid(
                    lease_id, rid, self.leases.leases[lease_id]["fencing_token"],
                    actor_id, run_id,
                )
                for rid, lease_id in self.leases.active.items()
            )
            evidence_head = self.journal.head
            if request_id + ":evaluated" in self.journal.by_request:
                decision, checks, grant = "DENIED", [
                    {"predicate": "incomplete_prior_evaluation", "pass": False}
                ], None
            else:
                decision, checks, grant = evaluate(
                    policy, self.policy, self.authority, run_id, actor_id,
                    stage_id, gpu_lease_valid,
                )
                lab_matches = self.authority.actors.get(actor_id, {}).get("lab") == self.run_labs[run_id]
                checks.append({"predicate": "actor_lab_owns_run", "pass": lab_matches})
                if not lab_matches:
                    decision = "DENIED"
                if grant is not None and utc(expires_utc) > utc(
                    self.authority.grants[grant]["expires_utc"]
                ):
                    decision = "DENIED"
                    checks.append({"predicate": "authorization_expiry_within_grant", "pass": False})
                evaluated = {
                    "request_id": request_id, "actor_id": actor_id,
                    "run_id": run_id, "stage_id": stage_id,
                    "policy_id": stage_id + ":" + policy["version"],
                    "policy_version": policy["version"],
                    "policy_hash": current["policy_hash"],
                    "evidence_head": evidence_head,
                    "prerequisites": checks,
                    "decision": decision,
                    "reasons": [c["predicate"] for c in checks if not c["pass"]],
                    "evaluated_utc": datetime.now(timezone.utc).isoformat(),
                }
                self._emit("PolicyEvaluated", evaluated, actor_id,
                           request_id + ":evaluated")
            receipt = {
                "request_id": request_id, "actor_id": actor_id,
                "run_id": run_id, "stage_id": stage_id,
                "policy_id": stage_id + ":" + policy["version"],
                "policy_version": policy["version"],
                "policy_hash": current["policy_hash"],
                "evidence_head": evidence_head,
                "prerequisites": checks,
                "decision": decision,
                "reasons": [c["predicate"] for c in checks if not c["pass"]],
                "grant_id": grant,
                "spec_bindings": self.policy.binding_snapshot(run_id, stage_id),
                "expires_utc": expires_utc,
                "decided_utc": datetime.now(timezone.utc).isoformat(),
            }
            event_kind = "AuthorizationIssued" if decision == "AUTHORIZED" else "AuthorizationDenied"
            identity = self._emit(event_kind, receipt, actor_id, final_request)
            return identity, receipt

    def record_fact(self, fact: dict, actor: str, request_id: str) -> tuple[str, str]:
        with self.lock:
            payload = validated_fact(fact, set(self.artifacts), self.runs)
            if payload["fact_id"] in self.facts and request_id not in self.journal.by_request:
                raise ValueError("fact already recorded")
            event_id = self._emit("FactRecorded", payload, actor, request_id)
            return payload["fact_id"], event_id

    def history(self, run_id: str) -> list[dict]:
        with self.lock:
            if run_id not in self.runs:
                raise ValueError("unknown run")
            return self.graph.history(run_id)

    def history_summary(self, run_id: str) -> dict:
        return summarize(self.history(run_id))

    def create_seal(
        self,
        members: list[str],
        parents: list[str],
        actor: str,
        request_id: str,
    ) -> tuple[str, str]:
        with self.lock:
            for member in members:
                if member not in self.artifacts or not self.cas.verify(member):
                    raise ValueError(f"unregistered or corrupt member: {member}")
            for parent in parents:
                if parent not in self.seal_artifacts:
                    raise ValueError(f"unknown parent seal: {parent}")
                self.verify_seal(parent)
            seal, root = make_seal(members, parents)
            seal_artifact, _ = self.cas.put_bytes(canonical(seal))
            if root in self.seal_artifacts and request_id not in self.journal.by_request:
                if self.seal_artifacts[root] != seal_artifact:
                    raise ValueError("seal identity collision")
                raise ValueError("seal already exists; use its existing root")
            payload = {
                "root": root,
                "seal_artifact": seal_artifact,
                "direct_members": seal["direct_members"],
                "parents": seal["parents"],
            }
            event_id = self._emit("SealCreated", payload, actor, request_id)
            return root, event_id

    def verify_seal(self, root: str) -> list[str]:
        with self.lock:
            def load_seal(identity: str) -> bytes:
                artifact_id = self.seal_artifacts.get(identity)
                if artifact_id is None:
                    raise ValueError(f"unknown seal: {identity}")
                return self.cas.get(artifact_id)

            return verify_lineage(root, load_seal, self.cas.verify)

    def status(self) -> dict:
        with self.lock:
            seq, projected_head = self.graph.position()
            return {
                "journal_events": len(self.journal.events),
                "journal_head": self.journal.head,
                "projection_seq": seq,
                "projection_head": projected_head,
                "counts": self.graph.counts(),
                "flight_gate": self.flight_state()["state"],
                "acceptance_identity": self.library_acceptance,
                "projection_lag": len(self.journal.events) - seq,
                "writer": self.owner.metadata,
                "active_lease_resources": [rid for rid in self.leases.resources
                                           if self.leases.report(rid)["active_lease"] is not None],
                "authorization_denials": sum(d.get("decision") == "DENIED" for d in self.policy.decisions),
                "panel_exposures": len(self.policy.exposures),
                "remote_bundles": len(self.remote.bundles),
                "remote_verified_returns": len(self.remote.returns),
                "memory": {"enabled": self.memory is not None,
                           "records": len(self.memory.records) if self.memory else 0,
                           "fts_rebuilds": self.memory.graph.fts_rebuilds if self.memory else 0,
                           "fts_pending_records": len(self.memory.graph.delta_ids) if self.memory else 0,
                           "journal_head": self.memory.journal.head if self.memory else None},
            }


def new_request_id() -> str:
    return str(uuid4())

