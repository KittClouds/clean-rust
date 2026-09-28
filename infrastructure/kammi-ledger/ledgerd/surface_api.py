"""Additional narrow wire operations for SDK/MCP clients."""
import base64
from fastapi import Header, HTTPException, Request
from .identity import strict_json
from .policy import evaluate


def install_surface_routes(app, ledger, authenticate, require_scope):
    @app.post("/v1/artifacts/base64")
    async def register(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try:
            b = strict_json(await request.body())
            identity, event = ledger.register_bytes(base64.b64decode(b["bytes_base64"], validate=True),
                                                    kind=b["kind"], actor=b["actor"], request_id=b["request_id"])
            return {"artifact_id": identity, "event_id": event}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/policy/check")
    async def check(request: Request, authorization: str | None = Header(default=None)):
        try:
            b = strict_json(await request.body())
            require_scope(authorization, b["actor_id"], "authorize_stage", b["run_id"], b["stage_id"])
            with ledger.lock:
                if b["request_id"] in ledger.journal.by_request:
                    e, identity = ledger.journal.by_request[b["request_id"]]
                    receipt = strict_json(ledger.cas.get(e["payload_artifact"]))
                    if e["type"] != "PolicyEvaluated" or any(receipt[k] != b[k] for k in ("actor_id", "run_id", "stage_id")):
                        raise ValueError("policy request ID reused")
                    return {"event_id": identity, "receipt": receipt}
                current = ledger.policy.policies[b["stage_id"]]
                p = strict_json(ledger.cas.get(current["artifact_id"]))
                live_gpu = any(ledger.leases.resources[r]["kind"] == "GPU"
                               and ledger.leases.leases[i]["stage_id"] == b["stage_id"]
                               and ledger.leases.valid(i, r, ledger.leases.leases[i]["fencing_token"], b["actor_id"], b["run_id"])
                               for r, i in ledger.leases.active.items())
                decision, predicates, grant = evaluate(p, ledger.policy, ledger.authority,
                                                       b["run_id"], b["actor_id"], b["stage_id"], live_gpu)
                receipt = {"request_id": b["request_id"], "actor_id": b["actor_id"], "run_id": b["run_id"],
                           "stage_id": b["stage_id"], "policy_id": b["stage_id"] + ":" + p["version"],
                           "policy_hash": current["policy_hash"], "policy_version": p["version"],
                           "evidence_head": ledger.journal.head, "decision": decision,
                           "prerequisites": predicates, "reasons": [c["predicate"] for c in predicates if not c["pass"]],
                           "authority_conferred": False, "grant_id": grant}
                event = ledger._emit("PolicyEvaluated", receipt, b["actor_id"], b["request_id"])
                return {"event_id": event, "receipt": receipt}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
