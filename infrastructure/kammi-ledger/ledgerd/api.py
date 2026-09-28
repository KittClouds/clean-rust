"""Narrow, local one-writer HTTP façade for custody construction."""

from __future__ import annotations

import hmac
import base64
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

from .core import Ledger, ProjectionLagError
from .identity import strict_json

MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def create_app(ledger: Ledger, token: str, *, acceptance_mode: bool = False) -> FastAPI:
    if not token:
        raise ValueError("KAMMI_TOKEN must be set")
    app = FastAPI(title="Kammi Ledger custody", version="1.0.0")

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        # Bound decoded remote uploads and memory inputs as well as raw artifacts.
        # Consuming the cached body here avoids unbounded endpoint allocations.
        from fastapi.responses import JSONResponse

        if request.method == "POST" and request.url.path in {
            "/v1/vaults/asset-stream", "/v1/vaults/source-stream",
            "/v1/vaults/package"
        }:
            return await call_next(request)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD_BYTES:
                return JSONResponse(status_code=413, content={"error": "body_too_large"})
        request._body = bytes(body)
        if request.method == "POST" and request.url.path != "/v1/artifacts":
            from .wire import validate_request
            try:
                # The closed-flight endpoint permits an empty status-style
                # request; it still cannot issue any authorization.
                if body or request.url.path != "/v1/authorize":
                    validate_request(request.url.path, strict_json(bytes(body)))
            except (ValueError, TypeError) as exc:
                return JSONResponse(status_code=400, content={"detail": str(exc)})
        return await call_next(request)

    def authenticate(authorization: str | None) -> None:
        expected = "Bearer " + token
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    def authenticate_actor(authorization: str | None, actor_id: str) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="actor credential required")
        actor_token = authorization[7:]
        if not ledger.authority.verify_credential(actor_id, actor_token):
            raise HTTPException(status_code=401, detail="actor credential mismatch")
        return actor_token

    def require_scope(authorization: str | None, actor_id: str,
                      action: str, run_id: str, stage_id: str) -> str:
        actor_token = authenticate_actor(authorization, actor_id)
        actor = ledger.authority.actors[actor_id]
        if actor["lab"] != ledger.run_labs.get(run_id):
            raise HTTPException(status_code=403, detail="actor lab does not own run")
        policy_hash = ledger.policy.current_policy_hash(stage_id)
        if policy_hash is None or ledger.authority.matching_grant(
            actor_id, action, run_id, stage_id, policy_hash
        ) is None:
            raise HTTPException(status_code=403, detail="scoped grant missing or stale")
        return actor_token

    @app.exception_handler(ProjectionLagError)
    async def projection_lag(_request: Request, exc: ProjectionLagError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"error": "projection_lag", "committed_event_id": exc.event_id},
        )

    @app.get("/v1/status")
    async def status(authorization: str | None = Header(default=None)):
        authenticate(authorization)
        return ledger.status()

    @app.post("/v1/authorize")
    async def authorize(request: Request, authorization: str | None = Header(default=None)):
        body = strict_json(await request.body()) if await request.body() else {}
        if authorization == "Bearer " + token:
            authenticate(authorization)
        else:
            authenticate_actor(authorization, body.get("actor_id", ""))
        state = ledger.flight_state()
        if state["state"] != "OPEN":
            raise HTTPException(423, {"decision": "DENIED", "flight_state": state,
                                     "reason": "current immutable LibraryAcceptanceV1 required"})
        try:
            require_scope(authorization, body["actor_id"], "authorize_stage", body["run_id"], body["stage_id"])
            identity, receipt = ledger.authorize_stage(body["run_id"], body["stage_id"], body["actor_id"],
                                                       body["expires_utc"], body["request_id"])
            return {"event_id": identity, "receipt": receipt, "library_acceptance": state["acceptance_identity"]}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/artifacts")
    async def artifact(
        request: Request,
        x_kind: str = Header(),
        x_actor: str = Header(),
        x_request_id: str = Header(),
        authorization: str | None = Header(default=None),
    ):
        authenticate(authorization)
        length = request.headers.get("content-length")
        if length is not None:
            try:
                declared_size = int(length)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid content length") from exc
            if declared_size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="upload too large")
        body = await request.body()
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload too large")
        try:
            artifact_id, event_id = ledger.register_bytes(
                body, kind=x_kind, actor=x_actor, request_id=x_request_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"artifact_id": artifact_id, "event_id": event_id}

    @app.post("/v1/artifacts/import-local")
    async def import_local_artifact(request: Request,
                                    authorization: str | None = Header(default=None)):
        authenticate(authorization)
        from starlette.concurrency import run_in_threadpool
        from .file_intake import import_local_artifact as import_file

        try:
            artifact_id, event_id, byte_count = await run_in_threadpool(
                import_file, ledger, strict_json(await request.body())
            )
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"artifact_id": artifact_id, "event_id": event_id,
                "byte_count": byte_count}

    @app.post("/v1/runs")
    async def create_run(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.create_run(
                body["run_id"], body["lab"], body["actor"], body["request_id"]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/facts")
    async def record_fact(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            fact_id, event_id = ledger.record_fact(body["fact"], body["actor"], body["request_id"])
            return {"fact_id": fact_id, "event_id": event_id}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/actors")
    async def register_actor(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.register_actor(
                body["actor_id"], body["kind"], body["lab"],
                body["credential_sha256"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/grants")
    async def issue_grant(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.issue_grant(
                body["grant_id"], body["actor_id"], body["action"],
                body["run_id"], body["stage_id"], body["policy_hash"],
                body["expires_utc"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/policies")
    async def register_policy(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            policy_hash, event_id = ledger.register_policy(body["policy"], body["request_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"policy_hash": policy_hash, "event_id": event_id}

    @app.post("/v1/panels")
    async def register_panel(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.register_panel(
                body["panel_id"], body["artifact_id"], body["lab"], body["request_id"]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/resources")
    async def register_resource(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.register_resource(
                body["resource_id"], body["kind"], body["host"],
                body["constraints"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/adapters")
    async def register_adapter(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            implementation_hash, event_id = ledger.register_adapter(
                body["adapter_id"], body["request_id"]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"implementation_hash": implementation_hash, "event_id": event_id}

    @app.post("/v1/adapters/{adapter_id}/apply")
    async def apply_adapter(adapter_id: str, request: Request,
                            authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            derived, event_id = ledger.apply_adapter(
                adapter_id, body["source_artifact_id"], body["actor_id"],
                actor_token, body["run_id"], body["stage_id"],
                body["authorization_id"], body["purpose"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"derived_view_id": derived, "event_id": event_id}

    @app.post("/v1/remote/worker-keys")
    async def register_worker_key(request: Request,
                                  authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            event_id = ledger.register_worker_key(
                body["worker_actor_id"], body["public_key_hex"], body["request_id"]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/remote/bundles")
    async def create_bundle(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            event_id, envelope = ledger.create_remote_bundle(
                body["bundle"], body["actor_id"], actor_token,
                body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id, "envelope": envelope}

    def qualified_worker(bundle_id: str, authorization: str | None,
                         worker_actor_id: str) -> dict:
        authenticate_actor(authorization, worker_actor_id)
        record = ledger.remote.bundles.get(bundle_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown bundle")
        bundle = strict_json(ledger.cas.get(bundle_id))
        if bundle["worker_actor_id"] != worker_actor_id:
            raise HTTPException(status_code=403, detail="bundle assigned to another worker")
        return bundle

    @app.get("/v1/remote/bundles/{bundle_id}")
    async def get_bundle(bundle_id: str, worker_actor_id: str,
                         authorization: str | None = Header(default=None)):
        qualified_worker(bundle_id, authorization, worker_actor_id)
        envelope = ledger.remote.bundles[bundle_id]
        return {"bundle_base64": base64.b64encode(ledger.cas.get(bundle_id)).decode(),
                "envelope": envelope}

    @app.get("/v1/remote/bundles/{bundle_id}/inputs/{artifact_id}")
    async def get_bundle_input(bundle_id: str, artifact_id: str,
                               worker_actor_id: str,
                               authorization: str | None = Header(default=None)):
        bundle = qualified_worker(bundle_id, authorization, worker_actor_id)
        if artifact_id not in bundle["input_artifacts"]:
            raise HTTPException(status_code=403, detail="input not declared in bundle")
        producer = ledger.remote.bundles[bundle_id]["actor_id"]
        with ledger.lock:
            if not ledger.authorization_valid(bundle["authorization_id"], producer, bundle["run_id"], bundle["stage_id"]):
                raise HTTPException(403, "bundle authorization is no longer current")
            if not ledger.remote_input_allowed(artifact_id, producer, bundle["run_id"], bundle["stage_id"]):
                raise HTTPException(403, "protected bundle input lacks guarded exposure")
            data = ledger.cas.get(artifact_id)
        return Response(content=data,
                        media_type="application/octet-stream")

    @app.post("/v1/remote/bundles/{bundle_id}/return")
    async def accept_remote_return(bundle_id: str, request: Request,
                                   authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            worker_id = body["worker_actor_id"]
            worker_token = authenticate_actor(authorization, worker_id)
            qualified_worker(bundle_id, authorization, worker_id)

            def decode(encoded: str) -> bytes:
                return base64.b64decode(encoded, validate=True)

            outputs = {name: decode(data) for name, data in body["outputs_base64"].items()}
            event_id, receipt = ledger.accept_remote_return(
                bundle_id, decode(body["receipt_base64"]), body["receipt_signature"],
                worker_id, worker_token, outputs, decode(body["stdout_base64"]),
                decode(body["stderr_base64"]), body["request_id"],
            )
        except (ValueError, KeyError, TypeError, base64.binascii.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id, "receipt": receipt}

    @app.post("/v1/remote/bundles/{bundle_id}/start")
    async def start_remote(bundle_id: str, request: Request,
                           authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            token = authenticate_actor(authorization, body["worker_actor_id"])
            event = ledger.remote_worker_started(bundle_id, body["worker_actor_id"], token, body["request_id"])
            return {"event_id": event}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/leases/acquire")
    async def acquire_lease(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            event_id, receipt = ledger.acquire_lease(
                body["resource_id"], body["run_id"], body["stage_id"],
                body["actor_id"], actor_token, body["purpose"],
                body["ttl_seconds"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id, "receipt": receipt}

    @app.post("/v1/leases/{lease_id}/renew")
    async def renew_lease(lease_id: str, request: Request,
                          authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            event_id = ledger.renew_lease(
                lease_id, body["fencing_token"], body["actor_id"],
                actor_token, body["ttl_seconds"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/leases/{lease_id}/release")
    async def release_lease(lease_id: str, request: Request,
                            authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            event_id = ledger.release_lease(
                lease_id, body["fencing_token"], body["actor_id"],
                actor_token, body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/leases/{lease_id}/validate")
    async def validate_lease(lease_id: str, request: Request,
                             authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            valid = ledger.leases.valid(
                lease_id, body["resource_id"], body["fencing_token"],
                body["actor_id"], body["run_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"valid": valid, "lease_id": lease_id}

    @app.get("/v1/resources/{resource_id}/lease")
    async def lease_status(resource_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            return ledger.leases.report(resource_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/specs/bind")
    async def bind_spec(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            require_scope(authorization, body["actor_id"], "bind_spec",
                          body["run_id"], body["stage_id"])
            event_id = ledger.bind_spec(
                body["run_id"], body["stage_id"], body["spec_kind"],
                body["artifact_id"], body["seal_root"], body["actor_id"],
                body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/seals/{root}/verify-for-run")
    async def verify_for_run(root: str, request: Request,
                             authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            require_scope(authorization, body["actor_id"], "bind_spec",
                          body["run_id"], body["stage_id"])
            event_id = ledger.record_seal_verification(
                body["run_id"], body["stage_id"], root,
                body["actor_id"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id}

    @app.post("/v1/panels/{panel_id}/open")
    async def open_panel(panel_id: str, request: Request,
                         authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            actor_token = authenticate_actor(authorization, body["actor_id"])
            data, event_id, receipt = ledger.open_panel(
                panel_id, body["purpose"], body["run_id"], body["stage_id"],
                body["actor_id"], actor_token, body["authorization_id"],
                body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if data is None:
            raise HTTPException(status_code=403, detail={"event_id": event_id, "receipt": receipt})
        return Response(content=data, media_type="application/octet-stream",
                        headers={"X-Exposure-Event": event_id})

    @app.get("/v1/panels/{panel_id}/exposure")
    async def exposure_report(panel_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            return ledger.exposure.report(panel_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/acceptance/stages/authorize")
    async def acceptance_authorize(request: Request,
                                   authorization: str | None = Header(default=None)):
        if not acceptance_mode:
            raise HTTPException(status_code=423, detail="acceptance fixture mode disabled")
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            if not body["run_id"].startswith("acceptance."):
                raise ValueError("acceptance authorization requires isolated fixture run")
            event_id, receipt = ledger.authorize_stage(
                body["run_id"], body["stage_id"], body["actor_id"],
                body["expires_utc"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event_id": event_id, "receipt": receipt}

    @app.post("/v1/seals")
    async def create_seal(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            body = strict_json(await request.body())
            root, event_id = ledger.create_seal(
                body["direct_members"], body["parents"],
                body["actor"], body["request_id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"root": root, "event_id": event_id}

    @app.get("/v1/runs/{run_id}/history")
    async def history(run_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            return {"run_id": run_id, "facts": ledger.history(run_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}/history/summary")
    async def history_summary(run_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            return {"run_id": run_id, **ledger.history_summary(run_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/seals/{root}/lineage")
    async def lineage(root: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            members = ledger.verify_seal(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"root": root, "closure": members, "entry_count": len(members)}

    from .memory_api import install_memory_routes
    from .vault_api import install_vault_routes
    from .lifecycle_api import install_lifecycle_routes
    from .surface_api import install_surface_routes
    from .local_api import install_local_routes

    install_memory_routes(app, ledger, authenticate_actor)
    install_vault_routes(app, ledger, authenticate_actor, acceptance_mode=acceptance_mode)
    install_lifecycle_routes(app, ledger, authenticate_actor)
    install_surface_routes(app, ledger, authenticate, require_scope)
    install_local_routes(app, ledger, authenticate_actor)
    return app


def main() -> None:
    import uvicorn

    root = os.environ.get("KAMMI_ROOT")
    token = os.environ.get("KAMMI_TOKEN")
    if not token and os.environ.get("KAMMI_TOKEN_FILE"):
        token = Path(os.environ["KAMMI_TOKEN_FILE"]).read_text().strip()
    if not root or not token:
        raise SystemExit("KAMMI_ROOT and KAMMI_TOKEN are required")
    key_file = os.environ.get("KAMMI_SIGNING_KEY_FILE")
    signing_key = Path(key_file).read_bytes() if key_file else None
    embedding_cache = os.environ.get("KAMMI_EMBEDDING_CACHE")
    ledger = Ledger(Path(root), signing_key=signing_key,
                    embedding_cache=Path(embedding_cache) if embedding_cache else None)
    try:
        uvicorn.run(create_app(ledger, token, acceptance_mode=os.environ.get("KAMMI_ACCEPTANCE_MODE") == "1"), host="127.0.0.1",
                    port=int(os.environ.get("KAMMI_PORT", "8765")), workers=1)
    finally:
        ledger.close()


if __name__ == "__main__":
    main()

