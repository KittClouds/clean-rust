//! Phase 1 workspace verbs: one spec table drives the CLI parser, the MCP tools and the
//! provider-neutral function definitions (`kammi verbs --functions`), so every transport means
//! the same thing (amendment v4 section 3).
//!
//! Arguments are a JSON object. `workspace` and `expected_head` come from the CLI session file
//! when omitted there; over MCP and functions they are explicit, and every write answers with
//! the new `head` to pass to the next call.

use serde_json::{json, Map, Value};

use crate::client::{quote, Client, ClientError};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Text,
    Texts,
    Bool,
}

#[derive(Clone, Copy, Debug)]
pub struct Arg {
    pub name: &'static str,
    pub kind: Kind,
    pub required: bool,
    /// Position on the CLI command line (`None`: a `--flag`).
    pub position: Option<usize>,
    pub about: &'static str,
}

const fn arg(
    name: &'static str,
    kind: Kind,
    required: bool,
    position: Option<usize>,
    about: &'static str,
) -> Arg {
    Arg {
        name,
        kind,
        required,
        position,
        about,
    }
}

pub struct VerbSpec {
    pub verb: &'static str,
    /// The workspace event it writes (`None` for reads and `open`).
    pub event: Option<&'static str>,
    pub about: &'static str,
    pub args: &'static [Arg],
}

use Kind::*;
const WS: Arg = arg(
    "workspace",
    Text,
    true,
    None,
    "Workspace ID (the CLI session supplies it)",
);
const HEAD: Arg = arg(
    "expected_head",
    Text,
    true,
    None,
    "HEAD you last read; a stale HEAD is refused with the current one",
);
const REFS: Arg = arg(
    "refs",
    Texts,
    false,
    None,
    "References: artifact:, event:, seal:, memory:, run:, workspace:",
);
const WS_SCOPE: Arg = arg(
    "workspace",
    Text,
    false,
    None,
    "Workspace whose memory scope to use when scope is omitted (the CLI session supplies it)",
);
const SCOPE: Arg = arg(
    "scope",
    Text,
    false,
    None,
    "Memory scope: your lab, or workspace:<id> (default: the workspace)",
);

pub const SPECS: [VerbSpec; 20] = [
    VerbSpec { verb: "create", event: Some("WorkspaceCreated"), about: "Create a workspace (Library admin only; Chief Kammi)", args: &[
        arg("workspace", Text, true, Some(0), "New workspace ID"), arg("title", Text, true, None, "Title"),
        arg("lab", Text, true, None, "Owning lab"), arg("owners", Texts, true, None, "Owner actors (registered)"),
    ]},
    VerbSpec { verb: "open", event: Some("WorkspaceAgentAttached"), about: "Attach this agent to a workspace and read its work packet", args: &[
        arg("workspace", Text, true, Some(0), "Workspace ID"),
        arg("tool", Text, false, None, "The client tool (default kammi-cli)"),
    ]},
    VerbSpec { verb: "work", event: None, about: "Read the work packet: objective, scope, do-not-do list, next step, handoffs, questions, recent events", args: &[WS] },
    VerbSpec { verb: "objective", event: Some("WorkspaceObjectiveSet"), about: "Set the objective (owners only)", args: &[WS, HEAD, arg("objective", Text, true, Some(0), "The objective"), REFS] },
    VerbSpec { verb: "scope", event: Some("WorkspaceScopeSet"), about: "Set the authorised scope and the do-not-do list (owners only)", args: &[WS, HEAD,
        arg("authorized", Texts, true, None, "What is authorised"), arg("forbidden", Texts, true, None, "What must not be done"), REFS] },
    VerbSpec { verb: "next", event: Some("WorkspaceNextStepSet"), about: "Set the single next step", args: &[WS, HEAD, arg("next_step", Text, true, Some(0), "The next step"), REFS] },
    VerbSpec { verb: "note", event: Some("WorkspaceNoteRecorded"), about: "Record a note", args: &[WS, HEAD, arg("text", Text, true, Some(0), "The note"), REFS, arg("note_id", Text, false, None, "Identifier (generated when omitted)")] },
    VerbSpec { verb: "decide", event: Some("WorkspaceDecisionRecorded"), about: "Record a decision", args: &[WS, HEAD,
        arg("text", Text, true, Some(0), "The decision"), arg("rationale", Text, true, None, "Why"), REFS,
        arg("supersedes", Text, false, None, "Decision ID this replaces"), arg("decision_id", Text, false, None, "Identifier (generated when omitted)")] },
    VerbSpec { verb: "ask", event: Some("WorkspaceQuestionOpened"), about: "Open a question", args: &[WS, HEAD, arg("text", Text, true, Some(0), "The question"), REFS, arg("question_id", Text, false, None, "Identifier (generated when omitted)")] },
    VerbSpec { verb: "resolve", event: Some("WorkspaceQuestionResolved"), about: "Resolve a question", args: &[WS, HEAD,
        arg("question_id", Text, true, Some(0), "The question"), arg("resolution", Text, true, Some(1), "The answer"), REFS] },
    VerbSpec { verb: "pin", event: Some("WorkspacePinned"), about: "Pin a reference", args: &[WS, HEAD, arg("ref", Text, true, Some(0), "The reference"), arg("note", Text, false, None, "Why it matters")] },
    VerbSpec { verb: "unpin", event: Some("WorkspaceUnpinned"), about: "Unpin a reference", args: &[WS, HEAD, arg("ref", Text, true, Some(0), "The reference")] },
    VerbSpec { verb: "handoff", event: Some("WorkspaceHandoffSent"), about: "Hand work to another registered actor", args: &[WS, HEAD,
        arg("to", Text, true, None, "Recipient actor"), arg("summary", Text, true, None, "What is handed over"),
        arg("next_step", Text, true, None, "What the recipient should do"), REFS, arg("handoff_id", Text, false, None, "Identifier (generated when omitted)")] },
    VerbSpec { verb: "receive", event: Some("WorkspaceHandoffReceived"), about: "Acknowledge a handoff", args: &[WS, HEAD, arg("handoff_id", Text, true, Some(0), "The handoff")] },
    VerbSpec { verb: "close", event: Some("WorkspaceAgentDetached"), about: "Detach this session; with end=true close the workspace (owners only)", args: &[WS, HEAD,
        arg("outcome", Text, true, None, "What was achieved"), arg("session_id", Text, false, None, "Session to detach (the CLI session supplies it)"),
        arg("end", Bool, false, None, "Close the whole workspace"), arg("summary", Text, false, None, "Closing summary (with end)")] },
    VerbSpec { verb: "remember", event: Some("MemoryRecordedV2"), about: "Record a memory with its time: when it was said, when it happened, when it holds", args: &[
        arg("text", Text, true, Some(0), "What to remember"), WS_SCOPE, SCOPE,
        arg("kind", Text, false, None, "OBSERVED, DERIVED, INTERPRETIVE (default), HYPOTHESIS, PREFERENCE, PROCEDURE, DECISION, FAILURE_MODE, RESULT_SUMMARY"),
        arg("custody_refs", Texts, false, None, "Custody evidence (artifact or event sha256 IDs); required for OBSERVED and DERIVED"),
        arg("tags", Texts, false, None, "Tags"),
        arg("asserted_at", Text, false, None, "When the statement was made (RFC 3339 UTC)"),
        arg("source_time", Text, false, None, "Timestamp carried by the source"),
        arg("occurred_from", Text, false, None, "Start of the event described (with occurred_to)"),
        arg("occurred_to", Text, false, None, "End of the event described (with occurred_from)"),
        arg("valid_from", Text, false, None, "Start of when the statement holds"),
        arg("valid_to", Text, false, None, "End of when it holds (default open)"),
        arg("precision", Text, false, None, "unknown, instant, minute, hour, day, month, year, interval, relative, ordinal"),
        arg("original_text", Text, false, None, "The source's own wording of the time"),
    ]},
    VerbSpec { verb: "recall", event: None, about: "Cited retrieval over memory (writes a receipt to the receipt stream)", args: &[
        arg("query", Text, true, Some(0), "What to look for"), WS_SCOPE, SCOPE,
        arg("mode", Text, false, None, "hybrid (default), fts, vector, graph"), arg("limit", Text, false, None, "Results, 1-100 (default 10)"),
    ]},
    VerbSpec { verb: "trace", event: None, about: "Evidence trace of a memory: its custody references, verified", args: &[arg("memory_id", Text, true, Some(0), "The memory")] },
    VerbSpec { verb: "find", event: None, about: "Custody lookup: workspaces and runs by name, artifacts and seals by identity prefix, an event by ID", args: &[arg("query", Text, true, Some(0), "At least 3 characters")] },
    VerbSpec { verb: "log", event: None, about: "Workspace events after an event ID (the full record behind the packet)", args: &[WS, arg("after", Text, false, None, "Event ID to start after")] },
];

pub fn spec(verb: &str) -> Option<&'static VerbSpec> {
    SPECS.iter().find(|s| s.verb == verb)
}

/// JSON Schema of a verb's arguments; the MCP input schema and the function parameters.
pub fn parameters(spec: &VerbSpec) -> Value {
    let mut properties = Map::new();
    for a in spec.args {
        let schema = match a.kind {
            Text => json!({"type": "string", "description": a.about}),
            Texts => json!({"type": "array", "items": {"type": "string"}, "description": a.about}),
            Bool => json!({"type": "boolean", "description": a.about}),
        };
        properties.insert(a.name.into(), schema);
    }
    let required: Vec<&str> = spec
        .args
        .iter()
        .filter(|a| a.required)
        .map(|a| a.name)
        .collect();
    json!({"type": "object", "properties": properties, "required": required, "additionalProperties": false})
}

/// Provider-neutral function definitions: `{name, description, parameters}` per verb.
/// OpenAI-compatible servers (llama.cpp, OpenRouter) take them as `tools[].function`; MCP
/// carries the same objects as tools.
pub fn functions() -> Vec<Value> {
    SPECS.iter().map(|s| json!({"name": format!("kammi_{}", s.verb), "description": s.about, "parameters": parameters(s)})).collect()
}

#[derive(Debug)]
pub enum VerbError {
    Usage(String),
    Client(ClientError),
}

impl From<ClientError> for VerbError {
    fn from(e: ClientError) -> Self {
        VerbError::Client(e)
    }
}

fn text<'a>(args: &'a Map<String, Value>, name: &str) -> Option<&'a str> {
    args.get(name).and_then(Value::as_str)
}

fn fresh_id(prefix: &str, request_id: &str) -> String {
    format!("{prefix}-{}", &request_id.replace('-', "")[..10])
}

/// Executes a verb. `actor` is the calling agent (`KAMMI_ACTOR`); with the admin credential it
/// may be absent.
pub fn execute(
    client: &Client,
    actor: Option<&str>,
    verb: &str,
    args: &Map<String, Value>,
) -> Result<Value, VerbError> {
    let spec =
        spec(verb).ok_or_else(|| VerbError::Usage(format!("unknown workspace verb {verb}")))?;
    for a in spec.args {
        match args.get(a.name) {
            None if a.required => {
                return Err(VerbError::Usage(format!("{verb}: {} is required", a.name)))
            }
            None => {}
            Some(v) => {
                let ok = match a.kind {
                    Text => v.is_string(),
                    Texts => v.as_array().is_some_and(|x| x.iter().all(Value::is_string)),
                    Bool => v.is_boolean(),
                };
                if !ok {
                    return Err(VerbError::Usage(format!(
                        "{verb}: {} has the wrong type",
                        a.name
                    )));
                }
            }
        }
    }
    if let Some(extra) = args
        .keys()
        .find(|k| !spec.args.iter().any(|a| a.name == k.as_str()))
    {
        return Err(VerbError::Usage(format!(
            "{verb}: unknown argument {extra}"
        )));
    }
    let ws = text(args, "workspace").unwrap_or_default().to_string();
    let who = actor
        .map(|a| format!("?actor_id={}", quote(a, "")))
        .unwrap_or_default();
    let base = format!("/v2/workspaces/{}", quote(&ws, ""));
    if verb == "create" {
        let mut body = json!({"workspace_id": args["workspace"], "title": args["title"], "lab": args["lab"], "owners": args["owners"], "request_id": crate::request_id()});
        if let Some(a) = actor {
            body["actor"] = a.into();
        }
        return Ok(client.v2("POST", "/v2/workspaces", Some(&body))?);
    }
    let memory_scope = || -> Result<String, VerbError> {
        match (text(args, "scope"), text(args, "workspace")) {
            (Some(scope), _) => Ok(scope.to_string()),
            (None, Some(ws)) => Ok(format!("workspace:{ws}")),
            (None, None) => Err(VerbError::Usage(format!(
                "{verb}: give scope, or a workspace (kammi open sets one)"
            ))),
        }
    };
    match verb {
        "remember" => {
            let mut time = Map::new();
            for key in ["asserted_at", "source_time", "precision", "original_text"] {
                if let Some(v) = args.get(key) {
                    time.insert(key.into(), v.clone());
                }
            }
            match (args.get("occurred_from"), args.get("occurred_to")) {
                (Some(from), Some(to)) => {
                    time.insert("occurred".into(), json!({"from": from, "to": to}));
                }
                (None, None) => {}
                _ => {
                    return Err(VerbError::Usage(
                        "remember: occurred_from and occurred_to go together".into(),
                    ))
                }
            }
            if args.contains_key("valid_from") || args.contains_key("valid_to") {
                time.insert("valid".into(), json!({"from": args.get("valid_from").cloned().unwrap_or_else(|| json!("unknown")), "to": args.get("valid_to").cloned().unwrap_or_else(|| json!("open"))}));
            }
            let mut body = json!({"kind": text(args, "kind").unwrap_or("INTERPRETIVE"), "scope": memory_scope()?, "text": args["text"],
                "custody_refs": args.get("custody_refs").cloned().unwrap_or_else(|| json!([])), "tags": args.get("tags").cloned().unwrap_or_else(|| json!([])),
                "time": time, "request_id": crate::request_id()});
            if let Some(a) = actor {
                body["actor_id"] = a.into();
            }
            return Ok(client.v2("POST", "/v2/memory", Some(&body))?);
        }
        "recall" => {
            let limit = match text(args, "limit") {
                Some(l) => l
                    .parse::<i64>()
                    .map_err(|_| VerbError::Usage("recall: limit must be a number".into()))?,
                None => 10,
            };
            let mut body = json!({"query": args["query"], "scope": memory_scope()?, "mode": text(args, "mode").unwrap_or("hybrid"), "limit": limit, "request_id": crate::request_id()});
            if let Some(a) = actor {
                body["actor_id"] = a.into();
            }
            return Ok(client.v2("POST", "/v2/recall", Some(&body))?);
        }
        "trace" => {
            return Ok(client.v2(
                "GET",
                &format!(
                    "/v2/memory/{}/trace{who}",
                    quote(text(args, "memory_id").unwrap_or_default(), ":")
                ),
                None,
            )?)
        }
        "find" => {
            let sep = if who.is_empty() { "?" } else { "&" };
            return Ok(client.v2(
                "GET",
                &format!(
                    "/v2/find{who}{sep}q={}",
                    quote(text(args, "query").unwrap_or_default(), "")
                ),
                None,
            )?);
        }
        "work" => return Ok(client.v2("GET", &format!("{base}/work{who}"), None)?),
        "log" => {
            let sep = if who.is_empty() { "?" } else { "&" };
            let after = text(args, "after")
                .map(|a| format!("{sep}after={}", quote(a, ":")))
                .unwrap_or_default();
            return Ok(client.v2("GET", &format!("{base}/history{who}{after}"), None)?);
        }
        _ => {}
    }
    let request_id = crate::request_id();
    let mut payload = Map::new();
    let mut kind = spec.event.expect("writes name their event").to_string();
    let head = if verb == "open" {
        client.v2("GET", &format!("{base}/work{who}"), None)?["workspace"]["head"]
            .as_str()
            .unwrap_or_default()
            .to_string()
    } else {
        text(args, "expected_head").unwrap_or_default().to_string()
    };
    payload.insert("expected_head".into(), head.into());
    let copy = |payload: &mut Map<String, Value>, names: &[&str]| {
        for name in names {
            if let Some(v) = args.get(*name) {
                payload.insert((*name).into(), v.clone());
            }
        }
    };
    let refs = || args.get("refs").cloned().unwrap_or_else(|| json!([]));
    match verb {
        "open" => {
            let agent = actor.ok_or_else(|| {
                VerbError::Usage("open: set KAMMI_ACTOR to this agent's actor ID".into())
            })?;
            payload.insert("session_id".into(), fresh_id("s", &request_id).into());
            payload.insert("agent".into(), agent.into());
            payload.insert(
                "tool".into(),
                text(args, "tool").unwrap_or("kammi-cli").into(),
            );
        }
        "objective" | "next" | "scope" | "note" | "decide" | "ask" | "resolve" | "handoff" => {
            copy(
                &mut payload,
                &[
                    "objective",
                    "next_step",
                    "authorized",
                    "forbidden",
                    "text",
                    "rationale",
                    "supersedes",
                    "question_id",
                    "resolution",
                    "to",
                    "summary",
                ],
            );
            payload.insert("refs".into(), refs());
            for (v, field, prefix) in [
                ("note", "note_id", "n"),
                ("decide", "decision_id", "d"),
                ("ask", "question_id", "q"),
                ("handoff", "handoff_id", "h"),
            ] {
                if verb == v {
                    let id = text(args, field)
                        .map(str::to_string)
                        .unwrap_or_else(|| fresh_id(prefix, &request_id));
                    payload.insert(field.into(), id.into());
                }
            }
        }
        "pin" | "unpin" | "receive" => copy(&mut payload, &["ref", "note", "handoff_id"]),
        "close" => {
            if args.get("end").and_then(Value::as_bool) == Some(true) {
                kind = "WorkspaceClosed".into();
                payload.insert("outcome".into(), args["outcome"].clone());
                payload.insert(
                    "summary".into(),
                    args.get("summary")
                        .cloned()
                        .unwrap_or_else(|| args["outcome"].clone()),
                );
            } else {
                let session = text(args, "session_id").ok_or_else(|| {
                    VerbError::Usage("close: session_id is required (kammi open sets it)".into())
                })?;
                payload.insert("session_id".into(), session.into());
                payload.insert("outcome".into(), args["outcome"].clone());
            }
        }
        _ => unreachable!("every spec verb is handled"),
    }
    let mut body = json!({"type": kind, "payload": payload, "request_id": request_id});
    if let Some(a) = actor {
        body["actor_id"] = a.into();
    }
    let mut receipt = client.v2("POST", &format!("{base}/commands"), Some(&body))?;
    if verb == "open" {
        receipt["session_id"] = body["payload"]["session_id"].clone();
        receipt["packet"] = client.v2("GET", &format!("{base}/work{who}"), None)?;
    }
    Ok(receipt)
}
