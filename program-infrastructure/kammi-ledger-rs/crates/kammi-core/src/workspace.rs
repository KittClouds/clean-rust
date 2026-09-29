//! Workspace state (amendment v4 section 2): the projection of the workspace events.
//!
//! Replay repeats every check the command path makes that the journal alone can decide: the
//! payload shape, the per-workspace HEAD chain, identifier uniqueness and life cycle. Who may
//! write is decided at command time (`ops_workspace`), like every other Library authorization.

use indexmap::IndexMap;
use kammi_jcs::Value;

use crate::error::{value_error, Result};
use crate::json::get_str;

/// One line of workspace state and the event that established it.
#[derive(Clone, Debug, PartialEq)]
pub struct Line {
    pub text: String,
    pub refs: Vec<String>,
    pub event: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Scope {
    pub authorized: Vec<String>,
    pub forbidden: Vec<String>,
    pub refs: Vec<String>,
    pub event: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Decision {
    pub line: Line,
    pub rationale: String,
    pub supersedes: Option<String>,
    pub superseded_by: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Question {
    pub line: Line,
    pub resolution: Option<Line>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Handoff {
    pub to: String,
    pub summary: String,
    pub next_step: String,
    pub refs: Vec<String>,
    pub event: String,
    pub received: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Session {
    pub agent: String,
    pub tool: String,
    pub event: String,
    pub detached: Option<(String, String)>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Workspace {
    pub id: String,
    pub title: String,
    pub lab: String,
    pub owners: Vec<String>,
    /// Every event of this workspace in journal order; the last one is HEAD.
    pub events: Vec<String>,
    pub objective: Option<Line>,
    pub scope: Option<Scope>,
    pub next_step: Option<Line>,
    pub notes: IndexMap<String, Line>,
    pub decisions: IndexMap<String, Decision>,
    pub questions: IndexMap<String, Question>,
    pub pinned: IndexMap<String, Line>,
    pub handoffs: IndexMap<String, Handoff>,
    pub sessions: IndexMap<String, Session>,
    pub closed: Option<Closed>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Closed {
    pub outcome: String,
    pub summary: String,
    pub event: String,
}

impl Workspace {
    pub fn head(&self) -> &str {
        self.events.last().map(String::as_str).unwrap_or("genesis")
    }

    /// Owners, plus every actor a handoff in this workspace was sent to (handoffs delegate).
    pub fn participant(&self, actor: &str) -> bool {
        self.owners.iter().any(|o| o == actor) || self.handoffs.values().any(|h| h.to == actor)
    }

    pub fn owner(&self, actor: &str) -> bool {
        self.owners.iter().any(|o| o == actor)
    }
}

#[derive(Default)]
pub struct Workspaces {
    pub map: IndexMap<String, Workspace>,
}

fn strings(payload: &Value, key: &str) -> Vec<String> {
    payload
        .get(key)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn text(payload: &Value, key: &str) -> Result<String> {
    Ok(get_str(payload, key)?.to_string())
}

fn line(payload: &Value, key: &str, event: &str) -> Result<Line> {
    Ok(Line {
        text: text(payload, key)?,
        refs: strings(payload, "refs"),
        event: event.to_string(),
    })
}

impl Workspaces {
    /// Applies one committed workspace event. `known_ref` answers whether a reference the
    /// main state can see exists (artifacts, seals, runs); event and memory references are
    /// checked at command time only.
    pub fn apply(
        &mut self,
        kind: &str,
        payload: &Value,
        event_id: &str,
        known_ref: &dyn Fn(&str) -> bool,
    ) -> Result<()> {
        kammi_contract::workspace::validate(kind, payload)
            .map_err(crate::error::LedgerError::Value)?;
        for reference in strings(payload, "refs").iter().chain(
            payload
                .get("ref")
                .and_then(Value::as_str)
                .map(str::to_string)
                .iter(),
        ) {
            let (ref_kind, identity) = reference.split_once(':').unwrap_or_default();
            let known = match ref_kind {
                "workspace" => self.map.contains_key(identity),
                "artifact" | "seal" | "run" => known_ref(reference),
                _ => true,
            };
            if !known {
                return value_error(format!("unknown reference {reference}"));
            }
        }
        let id = get_str(payload, "workspace_id")?.to_string();
        let expected = get_str(payload, "expected_head")?;
        if kind == "WorkspaceCreated" {
            if self.map.contains_key(&id) {
                return value_error("workspace already exists");
            }
            self.map.insert(
                id.clone(),
                Workspace {
                    id,
                    title: text(payload, "title")?,
                    lab: text(payload, "lab")?,
                    owners: strings(payload, "owners"),
                    events: vec![event_id.to_string()],
                    objective: None,
                    scope: None,
                    next_step: None,
                    notes: IndexMap::new(),
                    decisions: IndexMap::new(),
                    questions: IndexMap::new(),
                    pinned: IndexMap::new(),
                    handoffs: IndexMap::new(),
                    sessions: IndexMap::new(),
                    closed: None,
                },
            );
            return Ok(());
        }
        let Some(ws) = self.map.get_mut(&id) else {
            return value_error("unknown workspace");
        };
        if ws.closed.is_some() {
            return value_error("workspace is closed");
        }
        if ws.head() != expected {
            return value_error("workspace HEAD moved");
        }
        let event = event_id.to_string();
        match kind {
            "WorkspaceObjectiveSet" => ws.objective = Some(line(payload, "objective", &event)?),
            "WorkspaceNextStepSet" => ws.next_step = Some(line(payload, "next_step", &event)?),
            "WorkspaceScopeSet" => {
                ws.scope = Some(Scope {
                    authorized: strings(payload, "authorized"),
                    forbidden: strings(payload, "forbidden"),
                    refs: strings(payload, "refs"),
                    event: event.clone(),
                })
            }
            "WorkspaceNoteRecorded" => {
                let note_id = text(payload, "note_id")?;
                if ws.notes.contains_key(&note_id) {
                    return value_error("note ID already used");
                }
                ws.notes.insert(note_id, line(payload, "text", &event)?);
            }
            "WorkspaceDecisionRecorded" => {
                let decision_id = text(payload, "decision_id")?;
                if ws.decisions.contains_key(&decision_id) {
                    return value_error("decision ID already used");
                }
                let supersedes = payload
                    .get("supersedes")
                    .and_then(Value::as_str)
                    .map(str::to_string);
                if let Some(old) = &supersedes {
                    match ws.decisions.get_mut(old) {
                        Some(previous) if previous.superseded_by.is_none() => {
                            previous.superseded_by = Some(decision_id.clone())
                        }
                        Some(_) => return value_error("decision already superseded"),
                        None => return value_error("superseded decision does not exist"),
                    }
                }
                ws.decisions.insert(
                    decision_id,
                    Decision {
                        line: line(payload, "text", &event)?,
                        rationale: text(payload, "rationale")?,
                        supersedes,
                        superseded_by: None,
                    },
                );
            }
            "WorkspaceQuestionOpened" => {
                let question_id = text(payload, "question_id")?;
                if ws.questions.contains_key(&question_id) {
                    return value_error("question ID already used");
                }
                ws.questions.insert(
                    question_id,
                    Question {
                        line: line(payload, "text", &event)?,
                        resolution: None,
                    },
                );
            }
            "WorkspaceQuestionResolved" => {
                let question_id = text(payload, "question_id")?;
                match ws.questions.get_mut(&question_id) {
                    Some(q) if q.resolution.is_none() => {
                        q.resolution = Some(line(payload, "resolution", &event)?)
                    }
                    Some(_) => return value_error("question already resolved"),
                    None => return value_error("unknown question"),
                }
            }
            "WorkspacePinned" => {
                let reference = text(payload, "ref")?;
                if ws.pinned.contains_key(&reference) {
                    return value_error("reference already pinned");
                }
                let note = payload
                    .get("note")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string();
                ws.pinned.insert(
                    reference,
                    Line {
                        text: note,
                        refs: Vec::new(),
                        event: event.clone(),
                    },
                );
            }
            "WorkspaceUnpinned" => {
                if ws.pinned.shift_remove(get_str(payload, "ref")?).is_none() {
                    return value_error("reference is not pinned");
                }
            }
            "WorkspaceHandoffSent" => {
                let handoff_id = text(payload, "handoff_id")?;
                if ws.handoffs.contains_key(&handoff_id) {
                    return value_error("handoff ID already used");
                }
                ws.handoffs.insert(
                    handoff_id,
                    Handoff {
                        to: text(payload, "to")?,
                        summary: text(payload, "summary")?,
                        next_step: text(payload, "next_step")?,
                        refs: strings(payload, "refs"),
                        event: event.clone(),
                        received: None,
                    },
                );
            }
            "WorkspaceHandoffReceived" => {
                match ws.handoffs.get_mut(get_str(payload, "handoff_id")?) {
                    Some(h) if h.received.is_none() => h.received = Some(event.clone()),
                    Some(_) => return value_error("handoff already received"),
                    None => return value_error("unknown handoff"),
                }
            }
            "WorkspaceAgentAttached" => {
                let session_id = text(payload, "session_id")?;
                if ws.sessions.contains_key(&session_id) {
                    return value_error("session ID already used");
                }
                ws.sessions.insert(
                    session_id,
                    Session {
                        agent: text(payload, "agent")?,
                        tool: text(payload, "tool")?,
                        event: event.clone(),
                        detached: None,
                    },
                );
            }
            "WorkspaceAgentDetached" => {
                match ws.sessions.get_mut(get_str(payload, "session_id")?) {
                    Some(s) if s.detached.is_none() => {
                        s.detached = Some((text(payload, "outcome")?, event.clone()))
                    }
                    Some(_) => return value_error("session already detached"),
                    None => return value_error("unknown session"),
                }
            }
            "WorkspaceClosed" => {
                ws.closed = Some(Closed {
                    outcome: text(payload, "outcome")?,
                    summary: text(payload, "summary")?,
                    event: event.clone(),
                })
            }
            _ => return value_error(format!("{kind} is not a workspace event")),
        }
        ws.events.push(event);
        Ok(())
    }
}
