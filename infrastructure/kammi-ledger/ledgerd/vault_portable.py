"""Portable Phoenix vault package: verified bytes plus semantic event replay."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .identity import canonical, raw_id, require_id, strict_json
from .vault import VaultState
from .graph import SAFE

VAULT_EVENTS = frozenset({"VaultCreated", "VaultSourceCommitted",
                          "VaultGenerationSelected", "VaultReaderPositionSet",
                          "VaultProductPrimarySelected"})


def _object_path(root: Path, identity: str) -> Path:
    digest = require_id(identity)[7:]
    return root / "objects" / "sha256" / digest[:2] / digest[2:]


class VaultPortable:
    def vault_export(self, vault_id: str, actor: str, destination: Path) -> str:
        destination = destination.resolve()
        if destination.exists() or destination == self.root or self.root in destination.parents:
            raise ValueError("vault export destination must be new and outside Library")
        with self.lock:
            self._vault(vault_id, actor)
            events = []
            source_ids, asset_ids = set(), set()
            for event, event_id in self.journal:
                if event["type"] not in VAULT_EVENTS:
                    continue
                payload = strict_json(self.cas.get(event["payload_artifact"]))
                if payload["vault_id"] != vault_id:
                    continue
                events.append({"origin_event_id": event_id, "kind": event["type"],
                               "payload": payload})
                if event["type"] == "VaultSourceCommitted":
                    source_ids.add(payload["artifact_id"])
                elif event["type"] == "VaultGenerationSelected":
                    asset_ids.add(payload["manifest_artifact_id"])
                    asset_ids.update(payload["asset_ids"])
                elif event["type"] == "VaultProductPrimarySelected":
                    asset_ids.add(payload["receipt_artifact_id"])
            objects = []
            for identity in sorted(source_ids | asset_ids):
                if not self.cas.verify(identity):
                    raise ValueError("vault export references corrupt CAS object")
                artifact = self.artifacts.get(identity)
                if identity in asset_ids and (artifact is None or
                    not artifact["kind"].startswith(f"phoenix-vault:{vault_id}:")):
                    raise ValueError("vault export asset scope mismatch")
                objects.append({"artifact_id": identity,
                                "byte_count": self.cas.path_for(identity).stat().st_size,
                                "kind": artifact["kind"] if identity in asset_ids else "source"})
            manifest = {"schema": "PHOENIX_VAULT_PACKAGE_V1", "vault_id": vault_id,
                        "owner_actor": actor, "origin_head": self.journal.head,
                        "events": events, "objects": objects}
            raw = canonical(manifest)
            staged = Path(tempfile.mkdtemp(prefix="vault-export-", dir=destination.parent))
            try:
                for entry in objects:
                    target = _object_path(staged, entry["artifact_id"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with self.cas.path_for(entry["artifact_id"]).open("rb") as src, target.open("xb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                (staged / "VAULT.json").write_bytes(raw)
                os.replace(staged, destination)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
            return raw_id(raw)

    def vault_import(self, package: Path, actor: str, expected_root: str) -> dict:
        package = package.resolve()
        raw = (package / "VAULT.json").read_bytes()
        if raw_id(raw) != require_id(expected_root):
            raise ValueError("vault package root mismatch")
        manifest = strict_json(raw)
        if canonical(manifest) != raw or manifest.get("schema") != "PHOENIX_VAULT_PACKAGE_V1":
            raise ValueError("noncanonical or unknown vault package")
        vault_id = manifest["vault_id"]
        if actor != manifest["owner_actor"] or not manifest["events"]:
            raise ValueError("vault package owner or event history mismatch")
        if self.authority.actors.get(actor, {}).get("kind") != "service":
            raise ValueError("vault import requires a registered service actor")
        assets = {}
        object_ids = set()
        for entry in manifest["objects"]:
            identity = require_id(entry["artifact_id"])
            if identity in object_ids:
                raise ValueError("duplicate vault object")
            object_ids.add(identity)
            path = _object_path(package, identity)
            if not path.resolve().is_relative_to(package) or path.is_symlink() or not path.is_file():
                raise ValueError("unsafe or missing vault object")
            with path.open("rb") as stream:
                actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            if path.stat().st_size != entry["byte_count"] or actual != identity:
                raise ValueError("vault object integrity mismatch")
            kind = entry["kind"]
            if kind != "source":
                prefix = f"phoenix-vault:{vault_id}:"
                if not isinstance(kind, str) or not kind.startswith(prefix) or not SAFE.fullmatch(kind[len(prefix):]):
                    raise ValueError("vault object scope mismatch")
                assets[identity] = kind[len(prefix):]
        dry = VaultState()
        referenced = set()
        for index, item in enumerate(manifest["events"]):
            kind, payload = item["kind"], item["payload"]
            require_id(item["origin_event_id"])
            if kind not in VAULT_EVENTS or payload["vault_id"] != vault_id:
                raise ValueError("foreign vault event")
            if index == 0 and (kind != "VaultCreated" or payload["owner_actor"] != actor):
                raise ValueError("vault history must begin with its owner")
            if index > 0 and kind == "VaultCreated":
                raise ValueError("duplicate vault creation")
            dry.apply(kind, payload)
            if kind == "VaultSourceCommitted":
                referenced.add(payload["artifact_id"])
            elif kind == "VaultGenerationSelected":
                referenced.add(payload["manifest_artifact_id"])
                referenced.update(payload["asset_ids"])
                expected = {"schema": "PHOENIX_VAULT_GENERATION_V1", "vault_id": vault_id,
                            "source_epoch": payload["source_epoch"],
                            "generation_id": payload["generation_id"],
                            "asset_ids": sorted(set(payload["asset_ids"]))}
                if strict_json(_object_path(package, payload["manifest_artifact_id"]).read_bytes()) != expected:
                    raise ValueError("vault generation manifest mismatch")
            elif kind == "VaultProductPrimarySelected":
                referenced.add(payload["receipt_artifact_id"])
                if assets.get(payload["receipt_artifact_id"]) != "cutover-receipt":
                    raise ValueError("vault cutover receipt kind mismatch")
        if referenced != object_ids or len(dry.vaults) != 1:
            raise ValueError("vault package object inventory mismatch")
        for item in manifest["events"]:
            if item["kind"] == "VaultSourceCommitted" and item["payload"]["artifact_id"] in assets:
                raise ValueError("vault source and generation asset overlap")
        with self.lock:
            root = raw_id(raw)
            create_request = f"vault-import:{root}:create"
            if (vault_id in self.vaults.vaults and
                create_request not in self.journal.by_request):
                raise ValueError("vault already exists on destination")
            self.vault_create(vault_id, actor, create_request)
            for index, (identity, kind) in enumerate(sorted(assets.items())):
                imported, _ = self.vault_stage_file(vault_id, _object_path(package, identity),
                                                    kind, actor, f"vault-import:{root}:asset:{index}")
                if imported != identity:
                    raise ValueError("vault imported asset identity mismatch")
            for index, item in enumerate(manifest["events"][1:]):
                kind, payload = item["kind"], item["payload"]
                request = f"vault-import:{root}:event:{index}"
                if kind == "VaultSourceCommitted":
                    imported, _ = self.vault_commit_source(vault_id, payload["source_id"],
                        payload["base_revision"],
                        _object_path(package, payload["artifact_id"]).read_bytes(), actor, request)
                    if imported != payload:
                        raise ValueError("vault imported source lineage mismatch")
                elif kind == "VaultGenerationSelected":
                    imported, _ = self.vault_select_generation(vault_id, payload["source_epoch"],
                        payload["generation_id"], payload["manifest_artifact_id"],
                        payload["asset_ids"], actor, request)
                    if imported != payload:
                        raise ValueError("vault imported generation mismatch")
                elif kind == "VaultReaderPositionSet":
                    imported, _ = self.vault_set_reader(vault_id, payload["source_id"],
                        payload["revision"], payload["offset"], actor, request)
                    if imported != payload:
                        raise ValueError("vault imported reader mismatch")
                elif kind == "VaultProductPrimarySelected":
                    imported, _ = self.vault_select_product_primary(vault_id,
                        payload["source_epoch"], payload["receipt_artifact_id"], actor, request)
                    if imported != payload:
                        raise ValueError("vault imported product authority mismatch")
            return self.vault_view(vault_id, actor)
