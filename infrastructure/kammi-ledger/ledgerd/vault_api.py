"""Owner-scoped Phoenix vault extension; no direct Ladybug or custody writes."""
from __future__ import annotations

import base64
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import Header, HTTPException, Request
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .identity import strict_json
from .vault_archive import MAX_PACKAGE_BYTES, pack, unpack
from .vault import MAX_STREAM_ASSET_BYTES, MAX_STREAM_SOURCE_BYTES


def install_vault_routes(app, ledger, authenticate_actor, *, acceptance_mode=False):
    def writer(actor_id: str, authorization: str | None) -> None:
        authenticate_actor(authorization, actor_id)
        if not acceptance_mode and ledger.flight_state()["state"] != "OPEN":
            raise HTTPException(status_code=423, detail="Library source acceptance pending")

    def decode(content: str) -> bytes:
        try:
            return base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid base64 vault bytes") from exc

    @app.post("/v1/vaults")
    async def create(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            event_id = ledger.vault_create(body["vault_id"], body["actor_id"], body["request_id"])
            return {"vault_id": body["vault_id"], "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/vaults/source")
    async def source(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            receipt, event_id = ledger.vault_commit_source(
                body["vault_id"], body["source_id"], body["base_revision"],
                decode(body["content_base64"]), body["actor_id"], body["request_id"])
            return {"source": receipt, "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/vaults/source-stream")
    async def source_stream(request: Request, authorization: str | None = Header(default=None),
                            x_actor_id: str | None = Header(default=None),
                            x_vault_id: str | None = Header(default=None),
                            x_source_id: str | None = Header(default=None),
                            x_base_revision: str | None = Header(default=None),
                            x_request_id: str | None = Header(default=None)):
        if not all((x_actor_id, x_vault_id, x_source_id, x_base_revision is not None,
                    x_request_id)):
            raise HTTPException(400, "vault source stream headers required")
        writer(x_actor_id, authorization)
        try:
            base_revision = int(x_base_revision)
            with ledger.lock:
                ledger._vault(x_vault_id, x_actor_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        fd, temp_name = tempfile.mkstemp(prefix="vault-source-", dir=ledger.cas.staging)
        temp = Path(temp_name)
        count = 0
        try:
            with os.fdopen(fd, "wb") as output:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_STREAM_SOURCE_BYTES:
                        raise HTTPException(413, "vault source exceeds stream limit")
                    output.write(chunk)
                output.flush()
                await run_in_threadpool(os.fsync, output.fileno())
            try:
                receipt, event_id = await run_in_threadpool(
                    ledger.vault_commit_source_file, x_vault_id, x_source_id,
                    base_revision, temp, x_actor_id, x_request_id)
                return {"source": receipt, "event_id": event_id}
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
        finally:
            temp.unlink(missing_ok=True)

    @app.post("/v1/vaults/asset")
    async def asset(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            artifact_id, event_id = ledger.vault_stage_asset(
                body["vault_id"], decode(body["content_base64"]), body["kind"],
                body["actor_id"], body["request_id"])
            return {"artifact_id": artifact_id, "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/vaults/asset-stream")
    async def asset_stream(request: Request, authorization: str | None = Header(default=None),
                           x_actor_id: str | None = Header(default=None),
                           x_vault_id: str | None = Header(default=None),
                           x_kind: str | None = Header(default=None),
                           x_request_id: str | None = Header(default=None)):
        if not all((x_actor_id, x_vault_id, x_kind, x_request_id)):
            raise HTTPException(400, "vault stream headers required")
        writer(x_actor_id, authorization)
        try:
            with ledger.lock:
                ledger._vault(x_vault_id, x_actor_id)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
        fd, temp_name = tempfile.mkstemp(prefix="vault-upload-", dir=ledger.cas.staging)
        temp = Path(temp_name)
        count = 0
        try:
            with os.fdopen(fd, "wb") as output:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_STREAM_ASSET_BYTES:
                        raise HTTPException(413, "vault asset exceeds stream limit")
                    output.write(chunk)
                output.flush()
                await run_in_threadpool(os.fsync, output.fileno())
            try:
                artifact_id, event_id = await run_in_threadpool(
                    ledger.vault_stage_file, x_vault_id, temp, x_kind,
                    x_actor_id, x_request_id)
                return {"artifact_id": artifact_id, "event_id": event_id,
                        "byte_count": count}
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
        finally:
            temp.unlink(missing_ok=True)

    @app.get("/v1/vaults/{vault_id}/package")
    async def export_package(vault_id: str, actor_id: str, background_tasks: BackgroundTasks,
                             authorization: str | None = Header(default=None)):
        authenticate_actor(authorization, actor_id)
        work = Path(tempfile.mkdtemp(prefix="vault-package-"))
        try:
            root = await run_in_threadpool(ledger.vault_export, vault_id, actor_id, work / "vault")
            archive = work / "vault.zip"
            await run_in_threadpool(pack, work / "vault", archive)
            background_tasks.add_task(shutil.rmtree, work)
            return FileResponse(archive, media_type="application/zip",
                headers={"X-Vault-Package-Root": root})
        except (KeyError, ValueError, TypeError):
            shutil.rmtree(work)
            raise HTTPException(404, "vault unavailable")

    @app.post("/v1/vaults/package")
    async def import_package(request: Request, authorization: str | None = Header(default=None),
                             x_actor_id: str | None = Header(default=None),
                             x_package_root: str | None = Header(default=None)):
        if not x_actor_id or not x_package_root:
            raise HTTPException(400, "vault import headers required")
        writer(x_actor_id, authorization)
        work = Path(tempfile.mkdtemp(prefix="vault-import-", dir=ledger.cas.staging))
        try:
            archive = work / "vault.zip"
            count = 0
            with archive.open("xb") as output:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_PACKAGE_BYTES:
                        raise HTTPException(413, "vault archive exceeds limit")
                    output.write(chunk)
                output.flush()
                await run_in_threadpool(os.fsync, output.fileno())
            await run_in_threadpool(unpack, archive, work / "vault")
            view = await run_in_threadpool(ledger.vault_import, work / "vault", x_actor_id,
                                           x_package_root)
            return {"vault": view, "package_root": x_package_root}
        except (KeyError, ValueError, TypeError, zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            shutil.rmtree(work)

    @app.post("/v1/vaults/generation")
    async def generation(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            receipt, event_id = ledger.vault_select_generation(
                body["vault_id"], body["source_epoch"], body["generation_id"],
                body["manifest_artifact_id"], body["asset_ids"],
                body["actor_id"], body["request_id"])
            return {"generation": receipt, "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/vaults/reader")
    async def reader(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            receipt, event_id = ledger.vault_set_reader(
                body["vault_id"], body["source_id"], body["revision"],
                body["offset"], body["actor_id"], body["request_id"])
            return {"reader": receipt, "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/vaults/product-primary")
    async def product_primary(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            writer(body["actor_id"], authorization)
            receipt, event_id = ledger.vault_select_product_primary(
                body["vault_id"], body["source_epoch"],
                body["receipt_artifact_id"], body["actor_id"], body["request_id"])
            return {"product_authority": receipt, "event_id": event_id}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/v1/vaults/{vault_id}")
    async def view(vault_id: str, actor_id: str, authorization: str | None = Header(default=None)):
        try:
            authenticate_actor(authorization, actor_id)
            return ledger.vault_view(vault_id, actor_id)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/v1/vaults/{vault_id}/sources/{source_id}")
    async def get_source(vault_id: str, source_id: str, actor_id: str,
                         authorization: str | None = Header(default=None)):
        try:
            authenticate_actor(authorization, actor_id)
            receipt, content = ledger.vault_source(vault_id, source_id, actor_id)
            return {"source": receipt, "content_base64": base64.b64encode(content).decode("ascii")}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/v1/vaults/{vault_id}/sources/{source_id}/bytes")
    async def get_source_bytes(vault_id: str, source_id: str, actor_id: str,
                               authorization: str | None = Header(default=None)):
        try:
            authenticate_actor(authorization, actor_id)
            receipt, path = await run_in_threadpool(ledger.vault_source_path,
                                                     vault_id, source_id, actor_id)
            return FileResponse(path, media_type="application/octet-stream",
                headers={"X-Artifact-Id": receipt["artifact_id"],
                         "X-Source-Revision": str(receipt["revision"])})
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/v1/vaults/{vault_id}/assets/{artifact_id}")
    async def get_asset(vault_id: str, artifact_id: str, actor_id: str,
                        authorization: str | None = Header(default=None)):
        try:
            authenticate_actor(authorization, actor_id)
            path, size = await run_in_threadpool(ledger.vault_asset, vault_id, artifact_id, actor_id)
            return FileResponse(path, media_type="application/octet-stream",
                                headers={"X-Artifact-Id": artifact_id, "Content-Length": str(size)})
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(404, str(exc)) from exc
