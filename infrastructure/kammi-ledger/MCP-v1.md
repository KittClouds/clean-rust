# Narrow MCP v1

Run python -m ledgerd.mcp with KAMMI_URL and the appropriate KAMMI_TOKEN.
Supported transport: UTF-8 newline-delimited JSON-RPC on stdio, protocol 2025-06-18.
Initialization, ping, tools/list and tools/call are supported. Stdout is protocol only.
Frames are bounded to 1 MiB. API body limits also apply.

Tools bind fixed HTTP endpoints for custody, authorization, exposure, leases, adapters,
remote returns and memory. No arbitrary Cypher, raw DB writes or user-controlled URLs.
The tools/list response publishes machine-readable input schemas. Body request objects
use the shared versioned wire schemas; service scope/validation remains authoritative.
Configure a separate MCP process per credential role; credentials are not tool arguments.
