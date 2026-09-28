from fastapi import Header, HTTPException, Request
from .identity import strict_json


def install_lifecycle_routes(app, ledger, authenticate_actor):
    @app.post("/v1/attempts/start")
    async def start(request: Request, authorization: str | None = Header(default=None)):
        try:
            b = strict_json(await request.body())
            authenticate_actor(authorization, b["actor_id"])
            identity = ledger.start_attempt(b["attempt_id"], b["run_id"], b["stage_id"],
                                            b["actor_id"], b["authorization_id"], b["request_id"])
            return {"event_id": identity}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/attempts/finish")
    async def finish(request: Request, authorization: str | None = Header(default=None)):
        try:
            b = strict_json(await request.body())
            authenticate_actor(authorization, b["actor_id"])
            identity = ledger.finish_attempt(b["attempt_id"], b["actor_id"], b["outcome"],
                                             b["evidence_artifact"], b["reason"], b["request_id"])
            return {"event_id": identity}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/v1/attempts/{attempt_id}")
    async def get(attempt_id: str, actor_id: str, authorization: str | None = Header(default=None)):
        authenticate_actor(authorization, actor_id)
        attempt = ledger.lifecycle.attempts.get(attempt_id)
        if attempt is None:
            raise HTTPException(404, "unknown attempt")
        if ledger.authority.actors[actor_id]["lab"] != ledger.run_labs[attempt["run_id"]]:
            raise HTTPException(403, "attempt belongs to another lab")
        return attempt

    @app.post("/v1/results/declare")
    async def result(request: Request, authorization: str | None = Header(default=None)):
        try:
            b = strict_json(await request.body())
            authenticate_actor(authorization, b["actor_id"])
            identity = ledger.declare_result(b["run_id"], b["stage_id"], b["actor_id"],
                                             b["authorization_id"], b["seal_root"],
                                             b.get("predecessor"), b["request_id"])
            return {"event_id": identity}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
