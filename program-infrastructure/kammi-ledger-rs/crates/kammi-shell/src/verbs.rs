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

pub const SPECS: [VerbSpec; 15] = [
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
    match verb {
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
