//! Vocabulary activation and workspace commands (amendment v4), plus the work packet.
//!
//! Authorization is decided here, at command time: the Library admin (master token) may do
//! anything; owners may do anything in their workspace; an actor a handoff was sent to may take
//! part (attach, note, decide, ask, resolve, pin, hand off, receive), but only owners set the
//! objective or scope and close the workspace. The work packet is rendered from state and
//! journal envelopes only, so replay reproduces it byte for byte.

use kammi_jcs::{Sha256Id, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::get_str;
use crate::ledger::Ledger;
use crate::workspace::{Line, Workspace};

const OWNER_ONLY: [&str; 3] = [
    "WorkspaceObjectiveSet",
    "WorkspaceScopeSet",
    "WorkspaceClosed",
];
/// Text packet budget in bytes (about 2,000 tokens).
pub const PACKET_BUDGET: usize = 8192;

/// Who issues a command: the admin credential, or an authenticated actor.
#[derive(Clone, Copy, Debug)]
pub enum Principal<'a> {
    Admin(&'a str),
    Actor(&'a str),
}

impl Principal<'_> {
    pub fn actor(&self) -> &str {
        match self {
            Principal::Admin(a) | Principal::Actor(a) => a,
        }
    }
    fn admin(&self) -> bool {
        matches!(self, Principal::Admin(_))
    }
}

fn short(event: &str) -> &str {
    event
        .strip_prefix("sha256:")
        .map_or(event, |hex| &hex[..hex.len().min(12)])
}

fn clip(text: &str, limit: usize) -> String {
    let flat: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= limit {
        flat
    } else {
        format!("{}...", flat.chars().take(limit - 3).collect::<String>())
    }
}

fn line_json(line: &Line) -> Value {
    crate::obj! {"text" => line.text.clone(), "refs" => line.refs.clone(), "event" => line.event.clone()}
}

impl Ledger {
    pub fn vocabulary_v4_active(&self) -> bool {
        self.state.vocabulary_v4.is_some()
    }

    /// `LibraryVocabularyActivated`: the one-way switch. Admin only; refused before the
    /// rollback-window floor, and unless the closure decision and a passing verification of
    /// this store at its current head are registered.
    pub fn activate_vocabulary(
        &mut self,
        payload: Value,
        actor: &str,
        request_id: &str,
    ) -> Result<String> {
        if let Some(prior) = self.prior(request_id)? {
            if prior.event["type"] == kammi_contract::activation::EVENT {
                return Ok(prior.event_id);
            }
        }
        kammi_contract::activation::validate(&payload).map_err(LedgerError::Value)?;
        let floor = crate::time::parse_utc(kammi_contract::activation::NOT_BEFORE)?;
        if self.now() < floor {
            return value_error(format!(
                "the rollback window cannot close before {}",
                kammi_contract::activation::NOT_BEFORE
            ));
        }
        if self.vocabulary_v4_active() {
            return value_error("vocabulary v4 is already active");
        }
        for field in kammi_contract::activation::ARTIFACT_FIELDS {
            let id = get_str(&payload, field)?;
            if !self.state.artifacts.contains_key(id) || !self.cas_verify(id) {
                return value_error(format!(
                    "activation {field} must be a registered, verified artifact"
                ));
            }
        }
        let decision = self.object_json(get_str(&payload, "closure_decision")?)?;
        if decision.get("schema").and_then(Value::as_str)
            != Some(kammi_contract::activation::CLOSURE_SCHEMA)
            || decision.get("decision").and_then(Value::as_str) != Some("CLOSE")
        {
            return value_error(format!(
                "closure_decision must be a {} document deciding CLOSE",
                kammi_contract::activation::CLOSURE_SCHEMA
            ));
        }
        // The verification covers every event before its own registration, and that
        // registration must be the latest event, so nothing enters unverified.
        let verification_id = get_str(&payload, "verification")?.to_string();
        let verification = self.object_json(&verification_id)?;
        let last = self.store.main.read(self.store.main.seq())?;
        let (last_event, last_payload) = (
            kammi_jcs::strict_json(&last.event)?,
            kammi_jcs::strict_json(&last.payload)?,
        );
        let registers_verification = last_event["type"] == "ArtifactRegistered"
            && last_payload["artifact_id"].as_str() == Some(verification_id.as_str());
        if verification.get("status").and_then(Value::as_str) != Some("PASS")
            || !registers_verification
            || verification.get("journal_head").and_then(Value::as_str)
                != last_event["prev"].as_str()
        {
            return value_error("verification must PASS at the head just before its registration, and that registration must be the latest event");
        }
        self.emit(
            kammi_contract::activation::EVENT,
            payload,
            actor,
            request_id,
            None,
        )
    }

    fn check_refs(&self, payload: &Value) -> Result<()> {
        let mut refs: Vec<&str> = payload
            .get("refs")
            .and_then(Value::as_array)
            .map(|r| r.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        if let Some(single) = payload.get("ref").and_then(Value::as_str) {
            refs.push(single);
        }
        for reference in refs {
            let (kind, id) = reference.split_once(':').unwrap_or_default();
            let known = match kind {
                "artifact" => self.state.artifacts.contains_key(id) && self.cas_verify(id),
                "event" => {
                    Sha256Id::parse(id).is_ok_and(|e| self.store.main.seq_of_event(&e).is_some())
                }
                "memory" => self
                    .memory
                    .as_ref()
                    .is_some_and(|m| m.records.contains_key(id)),
                "seal" => self.state.seal_artifacts.contains_key(id),
                "run" => self.state.runs.contains_key(id),
                "workspace" => self.state.workspaces.map.contains_key(id),
                _ => false,
            };
            if !known {
                return value_error(format!("unknown reference {reference}"));
            }
        }
        Ok(())
    }

    fn workspace(&self, id: &str) -> Result<&Workspace> {
        self.state
            .workspaces
            .map
            .get(id)
            .ok_or_else(|| LedgerError::Key(id.to_string()))
    }

    pub fn workspace_readable(&self, id: &str, who: Principal<'_>) -> Result<()> {
        let ws = self.workspace(id)?;
        if who.admin() || ws.participant(who.actor()) {
            Ok(())
        } else {
            value_error("actor is not a participant of this workspace")
        }
    }

    /// One workspace event. Returns `{event_id, workspace_id, head}`; a stale `expected_head`
    /// is a [`LedgerError::Conflict`] carrying the current HEAD.
    pub fn workspace_command(
        &mut self,
        kind: &str,
        payload: Value,
        who: Principal<'_>,
        request_id: &str,
    ) -> Result<Value> {
        if !self.vocabulary_v4_active() {
            return value_error("vocabulary v4 is not active on this Library");
        }
        let workspace_id = get_str(&payload, "workspace_id")?.to_string();
        if let Some(prior) = self.prior(request_id)? {
            // A retry of a committed command answers with its original receipt.
            let event_id = self.emit(kind, payload, who.actor(), request_id, None)?;
            debug_assert_eq!(event_id, prior.event_id);
            let head = self.workspace(&workspace_id)?.head().to_string();
            return Ok(
                crate::obj! {"event_id" => event_id, "workspace_id" => workspace_id, "head" => head, "replayed" => true},
            );
        }
        kammi_contract::workspace::validate(kind, &payload).map_err(LedgerError::Value)?;
        let actor = who.actor();
        if kind == "WorkspaceCreated" {
            if !who.admin() {
                return value_error("only the Library admin creates workspaces");
            }
            for owner in payload["owners"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
            {
                if !self.state.authority.actors.contains_key(owner) {
                    return value_error(format!("owner {owner} is not a registered actor"));
                }
            }
        } else {
            let ws = self.workspace(&workspace_id)?;
            let allowed = who.admin()
                || ws.owner(actor)
                || (ws.participant(actor) && !OWNER_ONLY.contains(&kind));
            if !allowed {
                return value_error("actor may not write this workspace");
            }
            if kind == "WorkspaceAgentAttached"
                && !who.admin()
                && payload["agent"].as_str() != Some(actor)
            {
                return value_error("an agent attaches only itself");
            }
            if kind == "WorkspaceHandoffSent"
                && !self
                    .state
                    .authority
                    .actors
                    .contains_key(get_str(&payload, "to")?)
            {
                return value_error("handoff recipient is not a registered actor");
            }
            let head = ws.head().to_string();
            if payload["expected_head"].as_str() != Some(head.as_str()) {
                return Err(LedgerError::Conflict(crate::obj! {
                    "error" => "conflict", "workspace_id" => workspace_id, "head" => head,
                    "expected_head" => payload["expected_head"].clone(),
                }));
            }
        }
        self.check_refs(&payload)?;
        // Replay's own checks, run on a copy before the append: an event that replay would
        // refuse must never reach the journal.
        let mut trial = crate::workspace::Workspaces {
            map: self.state.workspaces.map.clone(),
        };
        let (artifacts, seals, runs) = (
            &self.state.artifacts,
            &self.state.seal_artifacts,
            &self.state.runs,
        );
        let known = |reference: &str| match reference.split_once(':') {
            Some(("artifact", id)) => artifacts.contains_key(id),
            Some(("seal", id)) => seals.contains_key(id),
            Some(("run", id)) => runs.contains_key(id),
            _ => false,
        };
        trial.apply(kind, &payload, "sha256:trial", &known)?;
        let event_id = self.emit(kind, payload, actor, request_id, None)?;
        Ok(
            crate::obj! {"event_id" => event_id.clone(), "workspace_id" => workspace_id, "head" => event_id},
        )
    }

    fn envelope(&self, event_id: &str) -> Result<(u64, Value, Value)> {
        let id =
            Sha256Id::parse(event_id).map_err(|_| LedgerError::Value("bad event id".into()))?;
        let seq = self
            .store
            .main
            .seq_of_event(&id)
            .ok_or_else(|| LedgerError::Key(event_id.to_string()))?;
        let stored = self.store.main.read(seq)?;
        Ok((
            seq,
            kammi_jcs::strict_json(&stored.event)?,
            kammi_jcs::strict_json(&stored.payload)?,
        ))
    }

    /// The workspace's full projected state.
    pub fn workspace_view(&self, id: &str) -> Result<Value> {
        let ws = self.workspace(id)?;
        Ok(crate::obj! {
            "workspace_id" => ws.id.clone(), "title" => ws.title.clone(), "lab" => ws.lab.clone(),
            "owners" => ws.owners.clone(), "head" => ws.head().to_string(), "events" => ws.events.len(),
            "objective" => ws.objective.as_ref().map_or(Value::Null, line_json),
            "scope" => ws.scope.as_ref().map_or(Value::Null, |s| crate::obj! {"authorized" => s.authorized.clone(), "forbidden" => s.forbidden.clone(), "refs" => s.refs.clone(), "event" => s.event.clone()}),
            "next_step" => ws.next_step.as_ref().map_or(Value::Null, line_json),
            "notes" => ws.notes.iter().map(|(k, l)| crate::obj! {"note_id" => k.clone(), "text" => l.text.clone(), "refs" => l.refs.clone(), "event" => l.event.clone()}).collect::<Vec<_>>(),
            "decisions" => ws.decisions.iter().map(|(k, d)| crate::obj! {"decision_id" => k.clone(), "text" => d.line.text.clone(), "rationale" => d.rationale.clone(), "refs" => d.line.refs.clone(), "event" => d.line.event.clone(), "supersedes" => d.supersedes.clone().map_or(Value::Null, Value::from), "superseded_by" => d.superseded_by.clone().map_or(Value::Null, Value::from)}).collect::<Vec<_>>(),
            "questions" => ws.questions.iter().map(|(k, q)| crate::obj! {"question_id" => k.clone(), "text" => q.line.text.clone(), "refs" => q.line.refs.clone(), "event" => q.line.event.clone(), "resolution" => q.resolution.as_ref().map_or(Value::Null, line_json)}).collect::<Vec<_>>(),
            "pinned" => ws.pinned.iter().map(|(r, l)| crate::obj! {"ref" => r.clone(), "note" => l.text.clone(), "event" => l.event.clone()}).collect::<Vec<_>>(),
            "handoffs" => ws.handoffs.iter().map(|(k, h)| crate::obj! {"handoff_id" => k.clone(), "to" => h.to.clone(), "summary" => h.summary.clone(), "next_step" => h.next_step.clone(), "refs" => h.refs.clone(), "event" => h.event.clone(), "received" => h.received.clone().map_or(Value::Null, Value::from)}).collect::<Vec<_>>(),
            "sessions" => ws.sessions.iter().map(|(k, s)| crate::obj! {"session_id" => k.clone(), "agent" => s.agent.clone(), "tool" => s.tool.clone(), "event" => s.event.clone(), "detached" => s.detached.as_ref().map_or(Value::Null, |(o, e)| crate::obj! {"outcome" => o.clone(), "event" => e.clone()})}).collect::<Vec<_>>(),
            "closed" => ws.closed.as_ref().map_or(Value::Null, |c| crate::obj! {"outcome" => c.outcome.clone(), "summary" => c.summary.clone(), "event" => c.event.clone()}),
        })
    }

    fn summary(kind: &str, payload: &Value) -> String {
        let s = |key: &str| payload.get(key).and_then(Value::as_str).unwrap_or_default();
        match kind {
            "WorkspaceCreated" => format!("created: {}", clip(s("title"), 80)),
            "WorkspaceObjectiveSet" => format!("objective: {}", clip(s("objective"), 100)),
            "WorkspaceScopeSet" => format!(
                "scope: {} authorised, {} forbidden",
                payload["authorized"].as_array().map_or(0, Vec::len),
                payload["forbidden"].as_array().map_or(0, Vec::len)
            ),
            "WorkspaceNextStepSet" => format!("next step: {}", clip(s("next_step"), 100)),
            "WorkspaceNoteRecorded" => format!("note {}: {}", s("note_id"), clip(s("text"), 100)),
            "WorkspaceDecisionRecorded" => {
                format!("decision {}: {}", s("decision_id"), clip(s("text"), 100))
            }
            "WorkspaceQuestionOpened" => {
                format!("question {}: {}", s("question_id"), clip(s("text"), 100))
            }
            "WorkspaceQuestionResolved" => format!(
                "resolved {}: {}",
                s("question_id"),
                clip(s("resolution"), 100)
            ),
            "WorkspacePinned" => format!("pinned {}", s("ref")),
            "WorkspaceUnpinned" => format!("unpinned {}", s("ref")),
            "WorkspaceHandoffSent" => format!(
                "handoff {} to {}: {}",
                s("handoff_id"),
                s("to"),
                clip(s("summary"), 80)
            ),
            "WorkspaceHandoffReceived" => format!("received handoff {}", s("handoff_id")),
            "WorkspaceAgentAttached" => format!(
                "attached {} ({}) as session {}",
                s("agent"),
                s("tool"),
                s("session_id")
            ),
            "WorkspaceAgentDetached" => format!(
                "detached session {}: {}",
                s("session_id"),
                clip(s("outcome"), 80)
            ),
            "WorkspaceClosed" => format!("closed: {}", clip(s("outcome"), 80)),
            other => other.to_string(),
        }
    }

    /// Events of a workspace after `after` (an event ID of that workspace), oldest first.
    pub fn workspace_history(&self, id: &str, after: Option<&str>, limit: usize) -> Result<Value> {
        let ws = self.workspace(id)?;
        let start = match after {
            Some(event) => ws
                .events
                .iter()
                .position(|e| e == event)
                .map(|i| i + 1)
                .ok_or_else(|| {
                    LedgerError::Value("after is not an event of this workspace".into())
                })?,
            None => 0,
        };
        let mut out = Vec::new();
        for event_id in ws.events.iter().skip(start).take(limit) {
            let (seq, event, payload) = self.envelope(event_id)?;
            out.push(crate::obj! {
                "event" => event_id.clone(), "seq" => seq, "utc" => event["utc"].clone(), "actor" => event["actor"].clone(),
                "type" => event["type"].clone(), "summary" => Self::summary(event["type"].as_str().unwrap_or_default(), &payload),
                "payload" => payload,
            });
        }
        Ok(crate::obj! {"workspace_id" => id, "head" => ws.head().to_string(), "events" => out})
    }

    /// The work packet: everything a fresh agent needs to resume, each line citing its event.
    /// Plain ASCII in its own wording, so any console or model reads it the same.
    pub fn work_packet(&self, id: &str) -> Result<Value> {
        let ws = self.workspace(id)?;
        let view = self.workspace_view(id)?;
        let current_decisions: Vec<(&String, &crate::workspace::Decision)> = ws
            .decisions
            .iter()
            .filter(|(_, d)| d.superseded_by.is_none())
            .collect();
        let pending: Vec<(&String, &crate::workspace::Handoff)> = ws
            .handoffs
            .iter()
            .filter(|(_, h)| h.received.is_none())
            .collect();
        let open: Vec<(&String, &crate::workspace::Question)> = ws
            .questions
            .iter()
            .filter(|(_, q)| q.resolution.is_none())
            .collect();
        let attached: Vec<(&String, &crate::workspace::Session)> = ws
            .sessions
            .iter()
            .filter(|(_, s)| s.detached.is_none())
            .collect();
        let history = self.workspace_history(id, None, usize::MAX)?;
        let events = history["events"].as_array().cloned().unwrap_or_default();
        let senders: std::collections::HashMap<String, String> = events
            .iter()
            .filter(|e| e["type"] == "WorkspaceHandoffSent")
            .map(|e| {
                (
                    e["event"].as_str().unwrap_or_default().to_string(),
                    e["actor"].as_str().unwrap_or_default().to_string(),
                )
            })
            .collect();
        let cite = |event: &str| format!("[e:{}]", short(event));
        let refs = |refs: &[String]| {
            if refs.is_empty() {
                String::new()
            } else {
                format!(" (refs: {})", refs.join(", "))
            }
        };

        let mut head_lines = vec![
            format!("WORKSPACE {} - {} (lab {}; owners {}) {}", ws.id, clip(&ws.title, 80), ws.lab, ws.owners.join(", "), cite(&ws.events[0])),
            format!("HEAD {} after {} events. Citations [e:...] are event ID prefixes; full IDs are in --json.", ws.head(), ws.events.len()),
        ];
        if let Some(c) = &ws.closed {
            head_lines.push(format!(
                "CLOSED: {} - {} {}",
                c.outcome,
                clip(&c.summary, 200),
                cite(&c.event)
            ));
        }
        let mut fixed = head_lines;
        match &ws.objective {
            Some(o) => fixed.push(format!(
                "OBJECTIVE {}{} {}",
                o.text,
                refs(&o.refs),
                cite(&o.event)
            )),
            None => fixed.push("OBJECTIVE (not set)".into()),
        }
        if let Some(s) = &ws.scope {
            fixed.push(format!("AUTHORISED {}", cite(&s.event)));
            fixed.extend(
                s.authorized
                    .iter()
                    .map(|a| format!("  - {a} {}", cite(&s.event))),
            );
            fixed.push(format!("DO NOT {}", cite(&s.event)));
            fixed.extend(
                s.forbidden
                    .iter()
                    .map(|f| format!("  - {f} {}", cite(&s.event))),
            );
            if !s.refs.is_empty() {
                fixed.push(format!(
                    "  scope rests on: {} {}",
                    s.refs.join(", "),
                    cite(&s.event)
                ));
            }
        } else {
            fixed.push("AUTHORISED / DO NOT (scope not set)".into());
        }
        match &ws.next_step {
            Some(n) => fixed.push(format!(
                "NEXT STEP {}{} {}",
                n.text,
                refs(&n.refs),
                cite(&n.event)
            )),
            None => fixed.push("NEXT STEP (not set)".into()),
        }
        if !pending.is_empty() {
            fixed.push("PENDING HANDOFFS".into());
            for (hid, h) in &pending {
                let from = senders.get(&h.event).map(String::as_str).unwrap_or("?");
                fixed.push(format!(
                    "  - {hid}: {from} -> {}: {}; next: {}{} {}",
                    h.to,
                    h.summary,
                    h.next_step,
                    refs(&h.refs),
                    cite(&h.event)
                ));
            }
        }
        if !open.is_empty() {
            fixed.push("OPEN QUESTIONS".into());
            fixed.extend(open.iter().map(|(qid, q)| {
                format!(
                    "  - {qid}: {}{} {}",
                    q.line.text,
                    refs(&q.line.refs),
                    cite(&q.line.event)
                )
            }));
        }
        if !attached.is_empty() {
            fixed.push("ATTACHED".into());
            fixed.extend(
                attached.iter().map(|(sid, s)| {
                    format!("  - {sid}: {} ({}) {}", s.agent, s.tool, cite(&s.event))
                }),
            );
        }
        // Trimmable sections, newest kept first when the budget bites.
        let decisions: Vec<String> = current_decisions
            .iter()
            .map(|(did, d)| {
                format!(
                    "  - {did}: {} (why: {}){} {}",
                    d.line.text,
                    clip(&d.rationale, 160),
                    refs(&d.line.refs),
                    cite(&d.line.event)
                )
            })
            .collect();
        let pinned: Vec<String> = ws
            .pinned
            .iter()
            .map(|(r, l)| {
                format!(
                    "  - {r}{} {}",
                    if l.text.is_empty() {
                        String::new()
                    } else {
                        format!(": {}", l.text)
                    },
                    cite(&l.event)
                )
            })
            .collect();
        let notes: Vec<String> = ws
            .notes
            .iter()
            .map(|(nid, n)| {
                format!(
                    "  - {nid}: {}{} {}",
                    clip(&n.text, 240),
                    refs(&n.refs),
                    cite(&n.event)
                )
            })
            .collect();
        let recent: Vec<String> = events
            .iter()
            .map(|e| {
                format!(
                    "  - {} {} {} {}",
                    e["utc"].as_str().unwrap_or_default(),
                    e["actor"].as_str().unwrap_or_default(),
                    e["summary"].as_str().unwrap_or_default(),
                    cite(e["event"].as_str().unwrap_or_default())
                )
            })
            .collect();

        let render = |keep_recent: usize, keep_notes: usize| -> String {
            let mut lines = fixed.clone();
            let mut section = |title: &str, items: &[String], keep: usize| {
                if keep > 0 && !items.is_empty() {
                    lines.push(title.to_string());
                    let skip = items.len().saturating_sub(keep);
                    if skip > 0 {
                        lines.push(format!("  ... {skip} older omitted (kammi log)"));
                    }
                    lines.extend(items.iter().skip(skip).cloned());
                }
            };
            section("DECISIONS", &decisions, 10);
            section("PINNED", &pinned, pinned.len());
            section("NOTES", &notes, keep_notes);
            section("RECENT", &recent, keep_recent);
            lines.join("\n") + "\n"
        };
        // Defaults: the 12 newest events and 5 newest notes; the budget may cut further.
        let (mut keep_recent, mut keep_notes) = (recent.len().min(12), notes.len().min(5));
        let mut text = render(keep_recent, keep_notes);
        while text.len() > PACKET_BUDGET && (keep_recent > 0 || keep_notes > 0) {
            if keep_recent > 0 {
                keep_recent -= 1;
            } else {
                keep_notes -= 1;
            }
            text = render(keep_recent, keep_notes);
        }
        Ok(crate::obj! {
            "schema" => "KAMMI_WORK_PACKET_V1",
            "workspace" => view,
            "recent" => events.iter().rev().take(keep_recent).rev().map(|e| crate::obj! {"event" => e["event"].clone(), "utc" => e["utc"].clone(), "actor" => e["actor"].clone(), "type" => e["type"].clone(), "summary" => e["summary"].clone()}).collect::<Vec<_>>(),
            "within_budget" => text.len() <= PACKET_BUDGET,
            "text" => text,
        })
    }

    /// Workspaces the principal may read, in creation order.
    pub fn workspace_list(&self, who: Principal<'_>) -> Value {
        let items: Vec<Value> = self.state.workspaces.map.values()
            .filter(|ws| who.admin() || ws.participant(who.actor()))
            .map(|ws| crate::obj! {"workspace_id" => ws.id.clone(), "title" => ws.title.clone(), "lab" => ws.lab.clone(), "head" => ws.head().to_string(), "closed" => ws.closed.is_some()})
            .collect();
        crate::obj! {"vocabulary_v4" => self.vocabulary_v4_active(), "workspaces" => items}
    }
}
