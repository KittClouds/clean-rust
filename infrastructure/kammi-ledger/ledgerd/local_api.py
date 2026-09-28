"""Narrow HTTP boundary for supervised local execution and large outputs."""
from __future__ import annotations

from fastapi import Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .identity import canonical, strict_json
from .local_execution import checked_spec, import_local_output, live_local


def install_local_routes(app, ledger, authenticate_actor):
    @app.post("/v1/local/resolve")
    async def resolve(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            def resolve_checked():
                with ledger.lock:
                    spec = live_local(ledger, body, launch=True)
                    return {"valid": True, "execution_spec": spec,
                            "library_acceptance": ledger.library_acceptance}
            return await run_in_threadpool(resolve_checked)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.post("/v1/local/validate")
    async def validate(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            def validate_checked():
                with ledger.lock:
                    live_local(ledger, body)
                    return {"valid": True}
            return await run_in_threadpool(validate_checked)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.post("/v1/local/import-output")
    async def import_output(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            artifact_id, event_id = await run_in_threadpool(import_local_output, ledger, body)
            return {"artifact_id": artifact_id, "event_id": event_id}
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.post("/v1/local/contact")
    async def contact(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            with ledger.lock:
                live_local(ledger, body)
                attempt = ledger.lifecycle.attempts.get(body["attempt_id"])
                if attempt is None or attempt["state"] != "RUNNING" or any(
                    attempt[key] != body[key] for key in ("actor_id", "run_id", "stage_id")
                ):
                    raise ValueError("contact attempt is not current")
                event = ledger.record_contact(body["run_id"], body["stage_id"],
                                              "MODEL", body["attempt_id"],
                                              body["actor_id"], body["request_id"])
                return {"event_id": event, "meaning": "model process launched; contact conservatively possible"}
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc

    @app.post("/v1/local/finish")
    async def finish(request: Request, authorization: str | None = Header(default=None)):
        try:
            body = strict_json(await request.body())
            authenticate_actor(authorization, body["actor_id"])
            receipt = body["result"]
            if not isinstance(receipt, dict) or receipt.get("attempt_id") != body["attempt_id"]:
                raise ValueError("local result does not name the attempt")
            if receipt.get("status") not in {"OUTPUTS_REGISTERED", "STOPPED"}:
                raise ValueError("unsupported local result status")
            outcome = "COMPLETE" if receipt["status"] == "OUTPUTS_REGISTERED" else "STOPPED"
            with ledger.lock:
                attempt = ledger.lifecycle.attempts.get(body["attempt_id"])
                if attempt is None or attempt["actor_id"] != body["actor_id"]:
                    raise ValueError("unknown local attempt or actor")
                if outcome == "COMPLETE":
                    spec = checked_spec(ledger, attempt["run_id"], attempt["stage_id"], body["actor_id"])
                    if set(receipt.get("outputs", {})) != set(spec["expected_outputs"]):
                        raise ValueError("local result omits declared outputs")
                    for item in receipt["outputs"].values():
                        if item.get("artifact_id") not in ledger.artifacts or not ledger.cas.verify(item["artifact_id"]):
                            raise ValueError("local output is not registered and verified")
                identity, _ = ledger.register_bytes(canonical(receipt), kind="local-execution-receipt",
                                                    actor=body["actor_id"], request_id=body["request_id"] + ":receipt")
                event = ledger.finish_attempt(body["attempt_id"], body["actor_id"], outcome,
                                              identity, receipt.get("stop_reason", "outputs_registered"),
                                              body["request_id"] + ":finish")
                return {"receipt_artifact_id": identity, "event_id": event, "outcome": outcome}
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
