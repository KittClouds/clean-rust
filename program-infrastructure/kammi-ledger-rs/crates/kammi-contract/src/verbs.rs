//! The frozen shell ABI (amendment v4 §3). One meaning across the `kammi` CLI, MCP and SDKs.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Verb {
    pub name: &'static str,
    /// The build phase that makes the verb available. 0 = today.
    pub phase: u8,
    /// Writes the Library (needs an idempotency key; workspace writes also an expected HEAD).
    pub writes: bool,
    pub summary: &'static str,
}

const fn verb(name: &'static str, phase: u8, writes: bool, summary: &'static str) -> Verb {
    Verb {
        name,
        phase,
        writes,
        summary,
    }
}

pub const VERBS: [Verb; 26] = [
    verb("status", 0, false, "Library status and flight gate"),
    verb(
        "call",
        0,
        true,
        "Escape hatch: one /v1 request with a JSON body file",
    ),
    verb(
        "artifact",
        0,
        true,
        "Register a file's bytes as an artifact",
    ),
    verb("run", 0, true, "Create a run"),
    verb(
        "seal",
        0,
        true,
        "Create a seal over direct members and parents",
    ),
    verb("lineage", 0, false, "Seal lineage"),
    verb("history", 0, false, "Run history, or its summary"),
    verb(
        "open",
        1,
        true,
        "Attach a session to a workspace and print its work packet",
    ),
    verb(
        "work",
        1,
        false,
        "The work packet; every line cites the event behind it",
    ),
    verb("objective", 1, true, "Set the workspace objective"),
    verb(
        "scope",
        1,
        true,
        "Set the authorised scope and the do-not-do list",
    ),
    verb("next", 1, true, "Set the single next step"),
    verb("note", 1, true, "Record a workspace note"),
    verb("decide", 1, true, "Record a decision"),
    verb("ask", 1, true, "Open a question"),
    verb("resolve", 1, true, "Resolve a question"),
    verb("pin", 1, true, "Pin a reference"),
    verb("unpin", 1, true, "Unpin a reference"),
    verb("handoff", 1, true, "Send a handoff"),
    verb("receive", 1, true, "Acknowledge a handoff"),
    verb(
        "close",
        1,
        true,
        "Detach the session, or close the workspace",
    ),
    verb("remember", 1, true, "Record a memory"),
    verb("recall", 1, true, "Cited retrieval (writes a receipt)"),
    verb("trace", 1, false, "Evidence trace of a memory"),
    verb("find", 1, false, "Custody lookup by name or identity"),
    verb("verbs", 0, false, "List this ABI"),
];

pub fn lookup(name: &str) -> Option<&'static Verb> {
    VERBS.iter().find(|v| v.name == name)
}

/// The MCP tool that carries a verb.
pub fn mcp_tool(verb: &Verb) -> String {
    format!("kammi_{}", verb.name)
}

/// Shell exit codes.
pub mod exit {
    pub const OK: i32 = 0;
    pub const REFUSED: i32 = 1;
    pub const USAGE: i32 = 2;
    pub const CONFLICT: i32 = 3;
    pub const UNREACHABLE: i32 = 4;
}
