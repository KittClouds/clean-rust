"""Shared language-neutral wire schemas; authority remains in server operations."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REQUESTS = {
    "/v1/runs": ("run_id lab actor request_id", ""),
    "/v1/actors": ("actor_id kind lab credential_sha256 request_id", ""),
    "/v1/grants": ("grant_id actor_id action run_id stage_id policy_hash expires_utc request_id", ""),
    "/v1/policies": ("policy:object request_id", ""),
    "/v1/panels": ("panel_id artifact_id lab request_id", ""),
    "/v1/resources": ("resource_id kind host constraints:object request_id", ""),
    "/v1/adapters": ("adapter_id request_id", ""),
    "/v1/artifacts/base64": ("bytes_base64 kind actor request_id", ""),
    "/v1/artifacts/import-local": ("path expected_sha256 expected_bytes:integer kind actor request_id", ""),
    "/v1/facts": ("fact:object actor request_id", ""),
    "/v1/specs/bind": ("run_id stage_id spec_kind artifact_id seal_root actor_id request_id", ""),
    "/v1/seals": ("direct_members:array parents:array actor request_id", ""),
    "/v1/seals/{root}/verify-for-run": ("run_id stage_id actor_id request_id", ""),
    "/v1/policy/check": ("actor_id run_id stage_id request_id", ""),
    "/v1/authorize": ("actor_id run_id stage_id expires_utc request_id", ""),
    "/v1/acceptance/stages/authorize": ("actor_id run_id stage_id expires_utc request_id", ""),
    "/v1/panels/{panel_id}/open": ("purpose actor_id run_id stage_id authorization_id request_id", ""),
    "/v1/leases/acquire": ("resource_id run_id stage_id actor_id purpose ttl_seconds:integer request_id", ""),
    "/v1/leases/{lease_id}/renew": ("actor_id fencing_token:integer ttl_seconds:integer request_id", ""),
    "/v1/leases/{lease_id}/release": ("actor_id fencing_token:integer request_id", ""),
    "/v1/leases/{lease_id}/validate": ("actor_id resource_id fencing_token:integer run_id", ""),
    "/v1/local/resolve": ("actor_id run_id stage_id authorization_id lease_id resource_id fencing_token:integer", ""),
    "/v1/local/validate": ("actor_id run_id stage_id authorization_id lease_id resource_id fencing_token:integer", ""),
    "/v1/local/import-output": ("actor_id run_id stage_id authorization_id lease_id resource_id fencing_token:integer relative_path expected_sha256 kind request_id", ""),
    "/v1/local/finish": ("actor_id attempt_id result:object request_id", ""),
    "/v1/local/contact": ("actor_id run_id stage_id authorization_id lease_id resource_id fencing_token:integer attempt_id request_id", ""),
    "/v1/adapters/{adapter_id}/apply": ("source_artifact_id actor_id run_id stage_id authorization_id purpose request_id", ""),
    "/v1/remote/worker-keys": ("worker_actor_id public_key_hex request_id", ""),
    "/v1/remote/bundles": ("bundle:object actor_id request_id", ""),
    "/v1/remote/bundles/{bundle_id}/start": ("worker_actor_id request_id", ""),
    "/v1/remote/bundles/{bundle_id}/return": ("worker_actor_id receipt_base64 receipt_signature outputs_base64:object stdout_base64 stderr_base64 request_id", ""),
    "/v1/attempts/start": ("attempt_id actor_id run_id stage_id authorization_id request_id", ""),
    "/v1/attempts/finish": ("attempt_id actor_id outcome evidence_artifact reason request_id", ""),
    "/v1/results/declare": ("run_id stage_id actor_id authorization_id seal_root request_id", "predecessor:nullable_string"),
    "/v1/memory": ("kind scope text actor_id request_id", "custody_refs:array tags:array confidence:nullable_number"),
    "/v1/memory/search": ("query scope actor_id request_id", "mode limit:integer grounded_only:boolean exclude_kinds:array include_superseded:boolean seed_memory:nullable_string"),
    "/v1/memory/supersede": ("old_id new_id actor_id request_id", ""),
    "/v1/vaults": ("vault_id actor_id request_id", ""),
    "/v1/vaults/source": ("vault_id source_id base_revision:integer content_base64 actor_id request_id", ""),
    "/v1/vaults/asset": ("vault_id kind content_base64 actor_id request_id", ""),
    "/v1/vaults/generation": ("vault_id source_epoch:integer generation_id:integer manifest_artifact_id asset_ids:array actor_id request_id", ""),
    "/v1/vaults/reader": ("vault_id source_id revision:integer offset:integer actor_id request_id", ""),
    "/v1/vaults/product-primary": ("vault_id source_epoch:integer receipt_artifact_id actor_id request_id", ""),
}


def schema(required, optional):
    props, needed = {}, []
    for words, is_required in ((required, True), (optional, False)):
        for word in words.split():
            name, _, typ = word.partition(":")
            typ = typ or "string"
            if typ.startswith("nullable_"):
                definition = {"type": [typ[9:], "null"]}
            else:
                definition = {"type": typ}
            if typ == "array":
                definition["items"] = {"type": "string"}
            props[name] = definition
            if is_required:
                needed.append(name)
    return {"type": "object", "properties": props, "required": needed, "additionalProperties": False}


def main():
    definitions = {path: schema(*fields) for path, fields in REQUESTS.items()}
    definitions["ArtifactResponse"] = schema("artifact_id event_id", "")
    definitions["EventResponse"] = schema("event_id", "")
    definitions["AuthorizationResponse"] = schema("event_id receipt:object", "")
    definitions["MemoryRecordResponse"] = schema("memory_id event_id", "")
    definitions["MemorySearchResponse"] = schema("authority mode results:array", "")
    definitions["MemorySearchResponse"]["properties"]["results"]["items"] = {"type": "object"}
    definitions["ExposureResponse"] = schema("bytes_base64 exposure_event", "")
    definitions["ErrorResponse"] = {"type": "object", "properties": {"detail": {}}, "required": ["detail"]}
    output = HERE / "schemas"
    output.mkdir(exist_ok=True)
    (output / "wire-v1.json").write_text(json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema",
                                                    "$id": "urn:kammi:wire:v1", "$defs": definitions}, indent=2) + "\n")
    from ledgerd.mcp import TOOLS, tool_schema
    (output / "mcp-tools-v1.json").write_text(json.dumps({"tools": [tool_schema(name) for name in TOOLS]}, indent=2) + "\n")
    import tempfile
    from ledgerd.core import Ledger
    from ledgerd.api import create_app
    with tempfile.TemporaryDirectory(prefix="kammi-schema-") as directory:
        ledger = Ledger(Path(directory))
        try:
            openapi = create_app(ledger, "schema-export-only").openapi()
            for path, definition in definitions.items():
                if path.startswith("/v1/") and path in openapi["paths"]:
                    operation = openapi["paths"][path].get("post")
                    if operation is not None:
                        operation["requestBody"] = {"required": True, "content": {
                            "application/json": {"schema": definition}}}
            (output / "openapi-v1.json").write_text(json.dumps(openapi, indent=2) + "\n")
        finally:
            ledger.close()


if __name__ == "__main__":
    main()
