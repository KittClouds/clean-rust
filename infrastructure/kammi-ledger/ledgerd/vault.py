"""Phoenix product vault state over the Library's authoritative CAS and journal."""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import SAFE
from .identity import require_id, strict_json

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_STREAM_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 10 * 1024 * 1024
MAX_STREAM_ASSET_BYTES = 8 * 1024 * 1024 * 1024


@dataclass
class VaultRecord:
    owner: str
    epoch: int = 0
    sources: dict[str, dict] = field(default_factory=dict)
    revisions: dict[tuple[str, int], dict] = field(default_factory=dict)
    generation: dict | None = None
    reader: dict | None = None
    authority: dict | None = None


class VaultState:
    def __init__(self) -> None:
        self.vaults: dict[str, VaultRecord] = {}

    def apply(self, kind: str, payload: dict) -> None:
        if kind == "VaultCreated":
            vault_id, owner = payload["vault_id"], payload["owner_actor"]
            if vault_id in self.vaults:
                if self.vaults[vault_id].owner != owner:
                    raise ValueError("vault owner collision")
                return
            self.vaults[vault_id] = VaultRecord(owner=owner)
        elif kind == "VaultSourceCommitted":
            vault = self.vaults[payload["vault_id"]]
            source_id = payload["source_id"]
            prior = vault.sources.get(source_id)
            if payload["base_revision"] != (prior["revision"] if prior else 0):
                raise ValueError("vault source revision discontinuity")
            if payload["revision"] != payload["base_revision"] + 1 or payload["epoch"] != vault.epoch + 1:
                raise ValueError("vault source epoch discontinuity")
            source = {
                "revision": payload["revision"], "artifact_id": payload["artifact_id"],
                "byte_count": payload["byte_count"], "epoch": payload["epoch"],
            }
            vault.sources[source_id] = source
            vault.revisions[source_id, payload["revision"]] = source
            vault.epoch = payload["epoch"]
        elif kind == "VaultGenerationSelected":
            vault = self.vaults[payload["vault_id"]]
            if payload["source_epoch"] != vault.epoch:
                raise ValueError("vault generation selected from stale sources")
            if vault.generation and payload["generation_id"] <= vault.generation["generation_id"]:
                raise ValueError("vault generation must increase")
            vault.generation = {key: payload[key] for key in
                                ("generation_id", "source_epoch", "manifest_artifact_id", "asset_ids")}
        elif kind == "VaultReaderPositionSet":
            vault = self.vaults[payload["vault_id"]]
            source = vault.revisions.get((payload["source_id"], payload["revision"]))
            if source is None or payload["offset"] > source["byte_count"]:
                raise ValueError("reader locator references unavailable revision")
            vault.reader = {key: payload[key] for key in ("source_id", "revision", "offset")}
        elif kind == "VaultProductPrimarySelected":
            vault = self.vaults[payload["vault_id"]]
            if vault.authority is not None or payload["source_epoch"] != vault.epoch:
                raise ValueError("vault product authority transition is stale or repeated")
            vault.authority = {"mode": "LIBRARY_PRIMARY",
                               "source_epoch": payload["source_epoch"],
                               "receipt_artifact_id": payload["receipt_artifact_id"]}

    def view(self, vault_id: str) -> dict:
        vault = self.vaults[vault_id]
        return {"vault_id": vault_id, "owner_actor": vault.owner, "source_epoch": vault.epoch,
                "sources": dict(vault.sources), "active_generation": vault.generation,
                "generation_current": bool(vault.generation and
                                           vault.generation["source_epoch"] == vault.epoch),
                "reader": vault.reader,
                "product_authority": vault.authority or {"mode": "LEGACY_MIRROR"}}


class VaultOperations:
    def _vault(self, vault_id: str, actor: str) -> VaultRecord:
        if not isinstance(vault_id, str) or not SAFE.fullmatch(vault_id):
            raise ValueError("invalid vault ID")
        vault = self.vaults.vaults.get(vault_id)
        if vault is None or vault.owner != actor:
            raise ValueError("unknown vault or actor does not own it")
        return vault

    def vault_create(self, vault_id: str, actor: str, request_id: str) -> str:
        if not isinstance(vault_id, str) or not SAFE.fullmatch(vault_id):
            raise ValueError("invalid vault ID")
        if self.authority.actors.get(actor, {}).get("kind") != "service":
            raise ValueError("vault owner must be a registered service actor")
        with self.lock:
            if vault_id in self.vaults.vaults and request_id not in self.journal.by_request:
                raise ValueError("vault already exists")
            return self._emit("VaultCreated", {"vault_id": vault_id, "owner_actor": actor},
                              actor, request_id)

    def vault_commit_source(self, vault_id: str, source_id: str, base_revision: int,
                            content: bytes, actor: str, request_id: str) -> tuple[dict, str]:
        if not isinstance(source_id, str) or not SAFE.fullmatch(source_id):
            raise ValueError("invalid source ID")
        if not isinstance(content, bytes) or len(content) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds vault limit")
        with self.lock:
            self._vault(vault_id, actor)
            artifact_id, size = self.cas.put_bytes(content)
            return self._vault_commit_source_id(vault_id, source_id, base_revision,
                                                artifact_id, size, actor, request_id)

    def vault_commit_source_file(self, vault_id: str, source_id: str, base_revision: int,
                                 source, actor: str, request_id: str) -> tuple[dict, str]:
        if not isinstance(source_id, str) or not SAFE.fullmatch(source_id):
            raise ValueError("invalid source ID")
        if source.stat().st_size > MAX_STREAM_SOURCE_BYTES:
            raise ValueError("source exceeds vault stream limit")
        with self.lock:
            self._vault(vault_id, actor)
            artifact_id, size = self.cas.put_file(source)
            if size > MAX_STREAM_SOURCE_BYTES:
                raise ValueError("source exceeds vault stream limit")
            return self._vault_commit_source_id(vault_id, source_id, base_revision,
                                                artifact_id, size, actor, request_id)

    def _vault_commit_source_id(self, vault_id: str, source_id: str, base_revision: int,
                                artifact_id: str, size: int, actor: str,
                                request_id: str) -> tuple[dict, str]:
        vault = self._vault(vault_id, actor)
        if request_id in self.journal.by_request:
            event, identity = self.journal.by_request[request_id]
            payload = strict_json(self.cas.get(event["payload_artifact"]))
            if event["type"] != "VaultSourceCommitted" or any((
                payload["vault_id"] != vault_id, payload["source_id"] != source_id,
                payload["base_revision"] != base_revision,
                payload["artifact_id"] != artifact_id)):
                raise ValueError("request ID reused for another source commit")
            return payload, identity
        prior = vault.sources.get(source_id)
        revision = prior["revision"] if prior else 0
        if base_revision != revision:
            raise ValueError("stale source revision")
        payload = {"vault_id": vault_id, "source_id": source_id,
                   "base_revision": base_revision, "revision": revision + 1,
                   "epoch": vault.epoch + 1, "artifact_id": artifact_id,
                   "byte_count": size}
        return payload, self._emit("VaultSourceCommitted", payload, actor, request_id)

    def vault_stage_asset(self, vault_id: str, content: bytes, kind: str,
                          actor: str, request_id: str) -> tuple[str, str]:
        if len(content) > MAX_ASSET_BYTES or not SAFE.fullmatch(kind):
            raise ValueError("invalid vault asset")
        with self.lock:
            self._vault(vault_id, actor)
            return self.register_bytes(content, kind=f"phoenix-vault:{vault_id}:{kind}",
                                       actor=actor, request_id=request_id)

    def vault_stage_file(self, vault_id: str, source, kind: str,
                         actor: str, request_id: str) -> tuple[str, str]:
        if not isinstance(kind, str) or not SAFE.fullmatch(kind):
            raise ValueError("invalid vault asset kind")
        with self.lock:
            self._vault(vault_id, actor)
        artifact_id, byte_count = self.cas.put_file(source)
        if byte_count > MAX_STREAM_ASSET_BYTES:
            raise ValueError("vault asset exceeds stream limit")
        with self.lock:
            self._vault(vault_id, actor)
            payload = {"artifact_id": artifact_id, "byte_count": byte_count,
                       "kind": f"phoenix-vault:{vault_id}:{kind}",
                       "media_type": "application/octet-stream", "schema_id": "raw-v1",
                       "source_location": "vault-stream"}
            return artifact_id, self._emit("ArtifactRegistered", payload, actor, request_id)

    def vault_select_generation(self, vault_id: str, source_epoch: int,
                                generation_id: int, manifest_artifact_id: str,
                                asset_ids: list[str], actor: str, request_id: str) -> tuple[dict, str]:
        with self.lock:
            vault = self._vault(vault_id, actor)
            if request_id in self.journal.by_request:
                event, identity = self.journal.by_request[request_id]
                payload = strict_json(self.cas.get(event["payload_artifact"]))
                if event["type"] != "VaultGenerationSelected" or payload != {
                    "vault_id": vault_id, "source_epoch": source_epoch,
                    "generation_id": generation_id, "manifest_artifact_id": manifest_artifact_id,
                    "asset_ids": sorted(set(asset_ids))}:
                    raise ValueError("request ID reused for another generation")
                return payload, identity
            if not isinstance(source_epoch, int) or source_epoch != vault.epoch:
                raise ValueError("generation source epoch is stale")
            if not isinstance(generation_id, int) or generation_id < 1 or (
                vault.generation and generation_id <= vault.generation["generation_id"]
            ):
                raise ValueError("generation ID must increase")
            if not isinstance(asset_ids, list) or not asset_ids or len(asset_ids) > 64:
                raise ValueError("generation needs bounded asset inventory")
            ids = sorted(set(require_id(identity) for identity in asset_ids))
            manifest_artifact_id = require_id(manifest_artifact_id)
            for identity in [manifest_artifact_id, *ids]:
                if identity not in self.artifacts or not self.cas.verify(identity):
                    raise ValueError("generation asset is unavailable")
                if self.artifacts[identity]["kind"].split(":")[:2] != ["phoenix-vault", vault_id]:
                    raise ValueError("generation asset belongs to another scope")
            manifest = strict_json(self.cas.get(manifest_artifact_id))
            if manifest != {"schema": "PHOENIX_VAULT_GENERATION_V1", "vault_id": vault_id,
                            "source_epoch": source_epoch, "generation_id": generation_id,
                            "asset_ids": ids}:
                raise ValueError("generation manifest does not bind exact assets and sources")
            payload = {"vault_id": vault_id, "source_epoch": source_epoch,
                       "generation_id": generation_id,
                       "manifest_artifact_id": manifest_artifact_id, "asset_ids": ids}
            return payload, self._emit("VaultGenerationSelected", payload, actor, request_id)

    def vault_set_reader(self, vault_id: str, source_id: str, revision: int,
                         offset: int, actor: str, request_id: str) -> tuple[dict, str]:
        with self.lock:
            vault = self._vault(vault_id, actor)
            source = vault.revisions.get((source_id, revision))
            if source is None:
                raise ValueError("reader source revision is unavailable")
            if not isinstance(offset, int) or offset < 0 or offset > source["byte_count"]:
                raise ValueError("reader offset is outside source")
            payload = {"vault_id": vault_id, "source_id": source_id,
                       "revision": revision, "offset": offset}
            return payload, self._emit("VaultReaderPositionSet", payload, actor, request_id)

    def vault_select_product_primary(self, vault_id: str, source_epoch: int,
                                     receipt_artifact_id: str, actor: str,
                                     request_id: str) -> tuple[dict, str]:
        with self.lock:
            vault = self._vault(vault_id, actor)
            identity = require_id(receipt_artifact_id)
            artifact = self.artifacts.get(identity)
            if artifact is None or artifact["kind"] != f"phoenix-vault:{vault_id}:cutover-receipt":
                raise ValueError("cutover receipt is unavailable or foreign")
            if not self.cas.verify(identity):
                raise ValueError("cutover receipt is corrupt")
            record = strict_json(self.cas.get(identity))
            if (record.get("schema") != "PHOENIX_VAULT_CUTOVER_V1" or
                record.get("vault_id") != vault_id or
                record.get("source_epoch") != source_epoch or
                set(record) != {"schema", "vault_id", "source_epoch",
                                "legacy_snapshot_id", "cold_open_root"}):
                raise ValueError("cutover receipt does not bind vault state")
            require_id(record["legacy_snapshot_id"])
            require_id(record["cold_open_root"])
            payload = {"vault_id": vault_id, "source_epoch": source_epoch,
                       "receipt_artifact_id": identity}
            if request_id in self.journal.by_request:
                event, event_id = self.journal.by_request[request_id]
                if event["type"] != "VaultProductPrimarySelected" or strict_json(
                        self.cas.get(event["payload_artifact"])) != payload:
                    raise ValueError("request ID reused for another cutover")
                return payload, event_id
            if vault.authority is not None or source_epoch != vault.epoch:
                raise ValueError("vault cutover is stale or already selected")
            return payload, self._emit("VaultProductPrimarySelected", payload, actor, request_id)

    def vault_view(self, vault_id: str, actor: str) -> dict:
        with self.lock:
            self._vault(vault_id, actor)
            return self.vaults.view(vault_id)

    def vault_source(self, vault_id: str, source_id: str, actor: str) -> tuple[dict, bytes]:
        with self.lock:
            vault = self._vault(vault_id, actor)
            source = vault.sources[source_id]
            return dict(source), self.cas.get(source["artifact_id"])

    def vault_source_path(self, vault_id: str, source_id: str, actor: str):
        with self.lock:
            vault = self._vault(vault_id, actor)
            source = vault.sources[source_id]
            identity = source["artifact_id"]
            if not self.cas.verify(identity):
                raise ValueError("vault source is missing or corrupt")
            return dict(source), self.cas.path_for(identity)

    def vault_asset(self, vault_id: str, artifact_id: str, actor: str):
        with self.lock:
            self._vault(vault_id, actor)
            identity = require_id(artifact_id)
            artifact = self.artifacts.get(identity)
            if artifact is None or not artifact["kind"].startswith(f"phoenix-vault:{vault_id}:"):
                raise ValueError("vault asset is unavailable")
            if not self.cas.verify(identity):
                raise ValueError("vault asset is missing or corrupt")
            return self.cas.path_for(identity), artifact["byte_count"]
