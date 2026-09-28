"""Narrow stdio MCP façade. Clients communicate exclusively through HTTP."""
from __future__ import annotations

import json
import sys
from urllib.parse import quote

from .client import KammiClient

# Tool names bind fixed endpoints; callers cannot supply Cypher or arbitrary URLs.
TOOLS = {
    "custody_get_run": ("GET", "/v1/runs/{run_id}/history/summary"),
    "custody_get_attempt": ("GET", "/v1/attempts/{attempt_id}?actor_id={actor_id}"),
    "custody_get_lineage": ("GET", "/v1/seals/{root}/lineage"),
    "custody_verify": ("GET", "/v1/seals/{root}/lineage"),
    "custody_contact_status": ("GET", "/v1/runs/{run_id}/history/summary"),
    "custody_create_run": ("POST", "/v1/runs"),
    "custody_register_artifact": ("POST", "/v1/artifacts/base64"),
    "policy_check": ("POST", "/v1/policy/check"),
    "authorization_request": ("POST", "/v1/authorize"),
    "exposure_request": ("POST", "/v1/panels/{panel_id}/open"),
    "exposure_report": ("GET", "/v1/panels/{panel_id}/exposure"),
    "lease_acquire": ("POST", "/v1/leases/acquire"),
    "lease_renew": ("POST", "/v1/leases/{lease_id}/renew"),
    "lease_release": ("POST", "/v1/leases/{lease_id}/release"),
    "lease_status": ("GET", "/v1/resources/{resource_id}/lease"),
    "adapter_resolve": ("POST", "/v1/adapters/{adapter_id}/apply"),
    "remote_create_bundle": ("POST", "/v1/remote/bundles"),
    "remote_accept_return": ("POST", "/v1/remote/bundles/{bundle_id}/return"),
    "memory_search": ("POST", "/v1/memory/search"),
    "memory_record": ("POST", "/v1/memory"),
    "memory_supersede": ("POST", "/v1/memory/supersede"),
    "memory_get": ("GET", "/v1/memory/{memory_id}?actor_id={actor_id}"),
    "memory_trace": ("GET", "/v1/memory/{memory_id}/trace?actor_id={actor_id}"),
    "memory_neighbors": ("GET", "/v1/memory/{memory_id}/neighbors?actor_id={actor_id}"),
}


def tool_schema(name: str) -> dict:
    method, path = TOOLS[name]
    from string import Formatter

    fields = [field for _, field, _, _ in Formatter().parse(path) if field]
    properties = {field: {"type": "string"} for field in fields}
    if method == "POST":
        properties["body"] = {"type": "object", "description": "Versioned HTTP request object; server validates scope."}
        fields.append("body")
    return {"name": name, "description": f"Kammi {name}; server custody and policy semantics apply.",
            "inputSchema": {"type": "object", "properties": properties,
                            "required": fields, "additionalProperties": False}}


class MCP:
    def __init__(self, client: KammiClient):
        self.client = client
        self.initialized = False

    def dispatch(self, message: dict) -> dict | None:
        identity = message.get("id")
        if message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": identity,
                    "error": {"code": -32600, "message": "Invalid Request"}}
        method = message.get("method")
        if identity is None:
            return None
        try:
            if method == "initialize":
                self.initialized = True
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "kammi-ledger", "version": "0.3.0"}}
            elif method == "ping":
                result = {}
            elif not self.initialized:
                raise ValueError("initialize first")
            elif method == "tools/list":
                result = {"tools": [tool_schema(name) for name in TOOLS]}
            elif method == "tools/call":
                params = message["params"]
                name, args = params["name"], params.get("arguments", {})
                if name not in TOOLS:
                    raise ValueError("unknown narrow tool")
                schema = tool_schema(name)["inputSchema"]
                if set(args) != set(schema["required"]):
                    raise ValueError("tool arguments do not match schema")
                verb, path = TOOLS[name]
                path = path.format(**{key: quote(value, safe="") for key, value in args.items() if key != "body"})
                try:
                    value = (self.client.open_panel(args["panel_id"], args["body"])
                             if name == "exposure_request" else self.client.call(verb, path, args.get("body")))
                    result = {"content": [{"type": "text", "text": json.dumps(value)}],
                              "structuredContent": value, "isError": False}
                except RuntimeError as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": identity,
                        "error": {"code": -32601, "message": "Method not found"}}
            return {"jsonrpc": "2.0", "id": identity, "result": result}
        except (ValueError, KeyError, TypeError) as exc:
            return {"jsonrpc": "2.0", "id": identity,
                    "error": {"code": -32602, "message": str(exc)}}


def main():
    server = MCP(KammiClient.from_environment())
    while line := sys.stdin.buffer.readline(1024 * 1024 + 1):
        if len(line) > 1024 * 1024:
            raise SystemExit("MCP frame too large")
        try:
            reply = server.dispatch(json.loads(line))
        except (json.JSONDecodeError, AttributeError):
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            print(json.dumps(reply, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
