//! Narrow stdio MCP, behaviour-compatible with `ledgerd/mcp.py`.
//!
//! Tool names bind fixed endpoints; callers cannot supply Cypher or arbitrary URLs. One
//! deliberate difference: when the Library is unreachable, Python's server dies on the
//! uncaught `URLError`; this one answers the call with `isError`.

use serde_json::{json, Map, Value};

use crate::client::{quote, Client, ClientError};

pub const MAX_FRAME: usize = 1024 * 1024;

/// `(tool, method, path template)`, in `mcp.py`'s order.
pub const TOOLS: [(&str, &str, &str); 24] = [
    (
        "custody_get_run",
        "GET",
        "/v1/runs/{run_id}/history/summary",
    ),
    (
        "custody_get_attempt",
        "GET",
        "/v1/attempts/{attempt_id}?actor_id={actor_id}",
    ),
    ("custody_get_lineage", "GET", "/v1/seals/{root}/lineage"),
    ("custody_verify", "GET", "/v1/seals/{root}/lineage"),
    (
        "custody_contact_status",
        "GET",
        "/v1/runs/{run_id}/history/summary",
    ),
    ("custody_create_run", "POST", "/v1/runs"),
    ("custody_register_artifact", "POST", "/v1/artifacts/base64"),
    ("policy_check", "POST", "/v1/policy/check"),
    ("authorization_request", "POST", "/v1/authorize"),
    ("exposure_request", "POST", "/v1/panels/{panel_id}/open"),
    ("exposure_report", "GET", "/v1/panels/{panel_id}/exposure"),
    ("lease_acquire", "POST", "/v1/leases/acquire"),
    ("lease_renew", "POST", "/v1/leases/{lease_id}/renew"),
    ("lease_release", "POST", "/v1/leases/{lease_id}/release"),
    ("lease_status", "GET", "/v1/resources/{resource_id}/lease"),
    ("adapter_resolve", "POST", "/v1/adapters/{adapter_id}/apply"),
    ("remote_create_bundle", "POST", "/v1/remote/bundles"),
    (
        "remote_accept_return",
        "POST",
        "/v1/remote/bundles/{bundle_id}/return",
    ),
    ("memory_search", "POST", "/v1/memory/search"),
    ("memory_record", "POST", "/v1/memory"),
    ("memory_supersede", "POST", "/v1/memory/supersede"),
    (
        "memory_get",
        "GET",
        "/v1/memory/{memory_id}?actor_id={actor_id}",
    ),
    (
        "memory_trace",
        "GET",
        "/v1/memory/{memory_id}/trace?actor_id={actor_id}",
    ),
    (
        "memory_neighbors",
        "GET",
        "/v1/memory/{memory_id}/neighbors?actor_id={actor_id}",
    ),
];

fn tool(name: &str) -> Option<(&'static str, &'static str)> {
    TOOLS
        .iter()
        .find(|(n, _, _)| *n == name)
        .map(|(_, m, p)| (*m, *p))
}

fn path_fields(path: &str) -> Vec<&str> {
    path.split('{')
        .skip(1)
        .filter_map(|part| part.split_once('}').map(|(field, _)| field))
        .collect()
}

/// `mcp.py`'s `tool_schema`; `required` lists the path fields in order, then `body` for POST.
pub fn tool_schema(name: &str) -> Value {
    let (method, path) = tool(name).expect("known tool");
    let mut fields: Vec<String> = path_fields(path).into_iter().map(str::to_string).collect();
    let mut properties = Map::new();
    for field in &fields {
        properties.insert(field.clone(), json!({"type": "string"}));
    }
    if method == "POST" {
        properties.insert("body".into(), json!({"type": "object", "description": "Versioned HTTP request object; server validates scope."}));
        fields.push("body".into());
    }
    json!({"name": name, "description": format!("Kammi {name}; server custody and policy semantics apply."),
           "inputSchema": {"type": "object", "properties": properties, "required": fields, "additionalProperties": false}})
}

pub struct Mcp {
    client: Client,
    initialized: bool,
}

fn invalid_params(identity: &Value, message: impl Into<String>) -> Value {
    json!({"jsonrpc": "2.0", "id": identity, "error": {"code": -32602, "message": message.into()}})
}

impl Mcp {
    pub fn new(client: Client) -> Self {
        Mcp {
            client,
            initialized: false,
        }
    }

    /// One JSON-RPC message in, at most one reply out (notifications get none).
    pub fn dispatch(&mut self, message: &Value) -> Option<Value> {
        let identity = message.get("id").cloned().unwrap_or(Value::Null);
        if message.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
            return Some(
                json!({"jsonrpc": "2.0", "id": identity, "error": {"code": -32600, "message": "Invalid Request"}}),
            );
        }
        if identity.is_null() {
            return None;
        }
        let method = message.get("method").and_then(Value::as_str).unwrap_or("");
        let result = match method {
            "initialize" => {
                self.initialized = true;
                json!({"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                       "serverInfo": {"name": "kammi-ledger", "version": "0.3.0"}})
            }
            "ping" => json!({}),
            _ if !self.initialized => return Some(invalid_params(&identity, "initialize first")),
            "tools/list" => {
                json!({"tools": TOOLS.iter().map(|(n, _, _)| tool_schema(n)).collect::<Vec<_>>()})
            }
            "tools/call" => match self.call(message) {
                Ok(result) => result,
                Err(error) => return Some(invalid_params(&identity, error)),
            },
            _ => {
                return Some(
                    json!({"jsonrpc": "2.0", "id": identity, "error": {"code": -32601, "message": "Method not found"}}),
                )
            }
        };
        Some(json!({"jsonrpc": "2.0", "id": identity, "result": result}))
    }

    fn call(&self, message: &Value) -> Result<Value, String> {
        let params = message.get("params").ok_or("'params'")?;
        let name = params
            .get("name")
            .ok_or("'name'")?
            .as_str()
            .ok_or("unknown narrow tool")?;
        let empty = Map::new();
        let args = match params.get("arguments") {
            None => &empty,
            Some(Value::Object(map)) => map,
            Some(_) => return Err("tool arguments do not match schema".into()),
        };
        let (verb, template) = tool(name).ok_or("unknown narrow tool")?;
        let schema = tool_schema(name);
        let mut required: Vec<&str> = schema["inputSchema"]["required"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .collect();
        let mut given: Vec<&str> = args.keys().map(String::as_str).collect();
        required.sort_unstable();
        given.sort_unstable();
        if required != given {
            return Err("tool arguments do not match schema".into());
        }
        let mut path = template.to_string();
        for field in path_fields(template) {
            let value = args[field]
                .as_str()
                .ok_or("tool arguments do not match schema")?;
            path = path.replacen(&format!("{{{field}}}"), &quote(value, ""), 1);
        }
        let body = args.get("body");
        let outcome = if name == "exposure_request" {
            let panel = args["panel_id"].as_str().unwrap_or_default();
            self.client.open_panel(panel, body.unwrap_or(&Value::Null))
        } else {
            self.client.call(verb, &path, body)
        };
        Ok(match outcome {
            Ok(value) => {
                json!({"content": [{"type": "text", "text": crate::ascii(&python_dumps(&value))}],
                                "structuredContent": value, "isError": false})
            }
            Err(ClientError::Usage(message)) => return Err(message),
            Err(error) => {
                json!({"content": [{"type": "text", "text": error.to_string()}], "isError": true})
            }
        })
    }
}

/// Python's default `json.dumps` separators (`", "`, `": "`), on sorted keys.
fn python_dumps(value: &Value) -> String {
    match value {
        Value::Array(items) => format!(
            "[{}]",
            items
                .iter()
                .map(python_dumps)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(map) => format!(
            "{{{}}}",
            map.iter()
                .map(|(k, v)| format!("{}: {}", Value::String(k.clone()), python_dumps(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        other => other.to_string(),
    }
}

/// Serves stdin to stdout until EOF. A frame over 1 MiB ends the server, as in `mcp.py`.
pub fn serve(mut server: Mcp) -> Result<(), String> {
    use std::io::{BufRead, Write};
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let stdout = std::io::stdout();
    let mut line = Vec::new();
    loop {
        line.clear();
        let read = std::io::Read::take(&mut input, MAX_FRAME as u64 + 1)
            .read_until(b'\n', &mut line)
            .map_err(|e| e.to_string())?;
        if read == 0 {
            return Ok(());
        }
        if line.len() > MAX_FRAME {
            return Err("MCP frame too large".into());
        }
        let reply = match serde_json::from_slice::<Value>(&line) {
            Ok(message) if message.is_object() => server.dispatch(&message),
            _ => Some(
                json!({"jsonrpc": "2.0", "id": null, "error": {"code": -32700, "message": "Parse error"}}),
            ),
        };
        if let Some(reply) = reply {
            let mut out = stdout.lock();
            writeln!(out, "{}", crate::ascii(&reply.to_string())).map_err(|e| e.to_string())?;
            out.flush().map_err(|e| e.to_string())?;
        }
    }
}
