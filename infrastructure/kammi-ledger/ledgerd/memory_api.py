"""Memory HTTP surface; actor scope is enforced by the service."""
from fastapi import Header, HTTPException, Request

from .identity import strict_json


def install_memory_routes(app, ledger, authenticate_actor) -> None:
    def service():
        if ledger.memory is None:
            raise HTTPException(503, "memory runtime is not configured")
        return ledger.memory

    def actor_scope(actor_id, authorization, scope=None):
        authenticate_actor(authorization, actor_id)
        lab = ledger.authority.actors[actor_id]["lab"]
        if scope is not None and scope != lab:
            raise HTTPException(403, "memory scope does not belong to actor")
        return lab

    @app.post("/v1/memory")
    async def record(request: Request, authorization: str | None = Header(default=None)):
        body = strict_json(await request.body())
        actor_scope(body["actor_id"], authorization, body["scope"])
        try:
            identity, event = service().record(
                kind=body["kind"], scope=body["scope"], text=body["text"],
                actor=body["actor_id"], custody_refs=body.get("custody_refs", []),
                tags=body.get("tags", []), confidence=body.get("confidence"),
                request_id=body["request_id"],
            )
            return {"memory_id": identity, "event_id": event}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/memory/search")
    async def search(request: Request, authorization: str | None = Header(default=None)):
        body = strict_json(await request.body())
        actor_scope(body["actor_id"], authorization, body["scope"])
        try:
            return service().search(
                body["query"], scope=body["scope"], actor=body["actor_id"],
                request_id=body["request_id"], mode=body.get("mode", "hybrid"),
                limit=body.get("limit", 10), grounded_only=body.get("grounded_only", False),
                exclude_kinds=body.get("exclude_kinds", []),
                include_superseded=body.get("include_superseded", False),
                seed_memory=body.get("seed_memory"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/v1/memory/{identity}")
    async def get(identity: str, actor_id: str,
                  authorization: str | None = Header(default=None)):
        record = service().get(identity)
        actor_scope(actor_id, authorization, record["scope"])
        return record

    @app.get("/v1/memory/{identity}/trace")
    async def trace(identity: str, actor_id: str,
                    authorization: str | None = Header(default=None)):
        record = service().get(identity)
        actor_scope(actor_id, authorization, record["scope"])
        return service().trace(identity)

    @app.get("/v1/memory/{identity}/neighbors")
    async def neighbors(identity: str, actor_id: str,
                        authorization: str | None = Header(default=None)):
        record = service().get(identity)
        actor_scope(actor_id, authorization, record["scope"])
        with service().lock:
            return {"results": [service().get(i) for i in service().graph.neighbors(identity)
                                if service().get(i)["scope"] == record["scope"]]}

    @app.post("/v1/memory/supersede")
    async def supersede(request: Request, authorization: str | None = Header(default=None)):
        body = strict_json(await request.body())
        old, new = service().get(body["old_id"]), service().get(body["new_id"])
        actor_scope(body["actor_id"], authorization, old["scope"])
        actor_scope(body["actor_id"], authorization, new["scope"])
        try:
            event = service().supersede(body["old_id"], body["new_id"],
                                       body["actor_id"], body["request_id"])
            return {"event_id": event}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
