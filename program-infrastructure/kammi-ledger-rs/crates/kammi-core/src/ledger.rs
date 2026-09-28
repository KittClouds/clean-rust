//! The single-writer Library: replay, the commit path, object access, status, flight gate.

use std::sync::Arc;

use ed25519_dalek::SigningKey;
use kammi_jcs::{canonical, raw_id, strict_json, Sha256Id, Value};
use kammi_store::{NewEvent, Store, StoreError};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get_str, object_id};
use crate::memory::{Embedder, Memory};
use crate::safe::is_safe;
use crate::state::State;
use crate::time::{Clock, Timestamp};

/// The identities a Library acceptance must bind for this build to open the flight gate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlightIdentity {
    pub architecture: String,
    pub source_root: String,
    pub runtime_identity: String,
}

pub struct LedgerOptions {
    pub clock: Arc<dyn Clock>,
    /// Raw 32-byte Ed25519 seed (`KAMMI_SIGNING_KEY_FILE`).
    pub signing_key: Option<[u8; 32]>,
    /// Enables the memory plane (Python: `KAMMI_EMBEDDING_CACHE`).
    pub embedder: Option<Arc<dyn Embedder>>,
    pub flight: FlightIdentity,
    /// Diagnostic writer metadata reported by `/v1/status`.
    pub writer: Value,
}

/// A committed event read back: envelope, payload and identity.
pub struct Prior {
    pub event: Value,
    pub payload: Value,
    pub event_id: String,
}

pub struct Ledger {
    pub store: Store,
    pub state: State,
    pub memory: Option<Memory>,
    pub(crate) clock: Arc<dyn Clock>,
    pub(crate) signing: Option<SigningKey>,
    pub(crate) flight: FlightIdentity,
    pub(crate) writer: Value,
}

/// A precondition re-checked under the writer lock just before an append.
pub type Guard<'a> = &'a dyn Fn(&Ledger) -> Result<bool>;

impl Ledger {
    /// Replays both journals into memory. Replay reads no clock and repeats every check the
    /// Python daemon performs while indexing.
    pub fn open(store: Store, options: LedgerOptions) -> Result<Ledger> {
        let mut ledger = Ledger {
            store,
            state: State::default(),
            memory: None,
            clock: options.clock,
            signing: options
                .signing_key
                .map(|seed| SigningKey::from_bytes(&seed)),
            flight: options.flight,
            writer: options.writer,
        };
        for seq in 1..=ledger.store.main.seq() {
            let stored = ledger.store.main.read(seq)?;
            let event = strict_json(&stored.event)?;
            let payload = strict_json(&stored.payload)?;
            let kind = get_str(&event, "type")?.to_string();
            let event_id = stored.event_id.to_string();
            let store = &ledger.store;
            let object_len = |id: &str| -> Option<u64> { object_len(store, id) };
            ledger
                .state
                .apply(&kind, &payload, &event_id, &object_len)
                .map_err(|e| {
                    LedgerError::Value(format!(
                        "replay of event {seq} ({kind}) failed: {}",
                        e.detail()
                    ))
                })?;
        }
        if let Some(embedder) = options.embedder {
            let memory = Memory::replay(&ledger, embedder)?;
            ledger.memory = Some(memory);
        }
        Ok(ledger)
    }

    pub fn now(&self) -> Timestamp {
        self.clock.now()
    }

    pub fn flight_identity(&self) -> &FlightIdentity {
        &self.flight
    }

    /// The committed main-journal event that used `request_id`.
    pub fn prior(&self, request_id: &str) -> Result<Option<Prior>> {
        match self.store.main.by_request(request_id)? {
            Some(stored) => Ok(Some(Prior {
                event: strict_json(&stored.event)?,
                payload: strict_json(&stored.payload)?,
                event_id: stored.event_id.to_string(),
            })),
            None => Ok(None),
        }
    }

    pub fn has_request(&self, request_id: &str) -> Result<bool> {
        Ok(self.store.main.by_request(request_id)?.is_some())
    }

    /// `Ledger._emit`: the only way anything is committed to the main journal.
    pub fn emit(
        &mut self,
        kind: &str,
        payload: Value,
        actor: &str,
        request_id: &str,
        guard: Option<Guard<'_>>,
    ) -> Result<String> {
        if !is_safe(actor) || !is_safe(request_id) {
            return value_error("actor/request ID uses unsupported characters");
        }
        let payload_bytes = canonical(&payload)?;
        let payload_artifact = raw_id(&payload_bytes).to_string();
        if let Some(prior) = self.prior(request_id)? {
            if prior.event["type"].as_str() != Some(kind)
                || prior.event["payload_artifact"].as_str() != Some(payload_artifact.as_str())
            {
                return value_error("request ID reused with different payload");
            }
            return Ok(prior.event_id);
        }
        let event = crate::obj! {
            "schema" => "KAMMI_EVENT_V1",
            "seq" => self.store.main.seq() + 1,
            "prev" => self.store.main.head().to_string(),
            "type" => kind,
            "payload_artifact" => payload_artifact,
            "actor" => actor,
            "request_id" => request_id,
            "utc" => self.now().event_utc(),
        };
        if let Some(guard) = guard {
            if !guard(self)? {
                return value_error("live commit prerequisite expired");
            }
        }
        let event_bytes = canonical(&event)?;
        let ids = self.store.main.append_batch(&[NewEvent {
            event: &event_bytes,
            payload: &payload_bytes,
        }])?;
        let event_id = ids[0].to_string();
        let store = &self.store;
        let object_len = |id: &str| -> Option<u64> { object_len(store, id) };
        self.state.apply(kind, &payload, &event_id, &object_len)?;
        Ok(event_id)
    }

    // ------------------------------------------------------------ CAS access

    /// `cas.get`: verified bytes of any stored object or journal payload.
    pub fn object_bytes(&self, id: &str) -> Result<Vec<u8>> {
        let parsed = Sha256Id::parse(id)
            .map_err(|_| LedgerError::Value("expected lowercase sha256: digest".into()))?;
        match self.store.get_object(&parsed) {
            Ok(Some(bytes)) => Ok(bytes),
            Ok(None) | Err(StoreError::ObjectCorrupt(_)) => {
                value_error(format!("missing or corrupt CAS object: {id}"))
            }
            Err(e) => Err(e.into()),
        }
    }

    pub fn object_json(&self, id: &str) -> Result<Value> {
        Ok(strict_json(&self.object_bytes(id)?)?)
    }

    /// `cas.verify`: true when the object exists and its bytes hash to its identity.
    pub fn cas_verify(&self, id: &str) -> bool {
        let Ok(parsed) = Sha256Id::parse(id) else {
            return false;
        };
        if self.store.objects.contains(&parsed) {
            return self.store.objects.verify(&parsed).unwrap_or(false);
        }
        matches!(self.store.get_object(&parsed), Ok(Some(_)))
    }

    pub fn object_size(&self, id: &str) -> Option<u64> {
        object_len(&self.store, id)
    }

    /// `cas.put_bytes`.
    pub fn put_bytes(&mut self, bytes: &[u8]) -> Result<(String, u64)> {
        let id = self.store.objects.put(bytes)?;
        Ok((id.to_string(), bytes.len() as u64))
    }

    /// `cas.put_file`: streams a file of any size.
    pub fn put_file(&mut self, path: &std::path::Path) -> Result<(String, u64)> {
        let mut file = std::fs::File::open(path).map_err(crate::error::io_error(path))?;
        let size = file.metadata().map_err(crate::error::io_error(path))?.len();
        let id = self.store.objects.put_stream(&mut file, None)?;
        Ok((id.to_string(), size))
    }

    /// `valid_custody_ref`: a verified registered artifact, or a committed main-journal event.
    pub fn valid_custody_ref(&self, identity: &str) -> bool {
        if self.state.artifacts.contains_key(identity) {
            return self.cas_verify(identity);
        }
        Sha256Id::parse(identity).is_ok_and(|id| self.store.main.seq_of_event(&id).is_some())
    }

    // ------------------------------------------------------------ status and flight

    pub fn flight_state(&self) -> Value {
        let Some(acceptance_id) = self.state.library_acceptance.clone() else {
            return crate::obj! {"state" => "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity" => Value::Null};
        };
        let acceptance = match self.object_json(&acceptance_id) {
            Ok(value) => value,
            Err(_) => {
                return crate::obj! {"state" => "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity" => acceptance_id,
                "reason" => "acceptance_verification_failed"}
            }
        };
        let matches = acceptance.get("source_root").and_then(Value::as_str)
            == Some(self.flight.source_root.as_str())
            && acceptance.get("runtime_identity").and_then(Value::as_str)
                == Some(self.flight.runtime_identity.as_str());
        if !matches {
            return crate::obj! {"state" => "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity" => acceptance_id,
            "reason" => "source_or_runtime_identity_changed"};
        }
        crate::obj! {"state" => "OPEN", "acceptance_identity" => acceptance_id}
    }

    pub fn flight_open(&self) -> bool {
        self.flight_state()["state"] == "OPEN"
    }

    pub fn status(&self) -> Result<Value> {
        let now = self.now();
        let mut active = Vec::new();
        for rid in self.state.leases.resources.keys() {
            if !self.state.leases.report(rid, now)?["active_lease"].is_null() {
                active.push(Value::from(rid.as_str()));
            }
        }
        let head = self.store.main.head().to_string();
        let seq = self.store.main.seq();
        let memory = match &self.memory {
            Some(memory) => crate::obj! {
                "enabled" => true,
                "records" => memory.records.len(),
                "fts_rebuilds" => 0,
                "fts_pending_records" => 0,
                "journal_head" => self.store.memory.head().to_string(),
            },
            None => {
                crate::obj! {"enabled" => false, "records" => 0, "fts_rebuilds" => 0, "fts_pending_records" => 0, "journal_head" => Value::Null}
            }
        };
        Ok(crate::obj! {
            "journal_events" => seq,
            "journal_head" => head.clone(),
            // The native core is the projection; it is applied synchronously with each commit.
            "projection_seq" => seq,
            "projection_head" => head,
            "counts" => crate::obj! {
                "artifacts" => self.state.artifacts.len(),
                "events" => seq,
                "seals" => self.state.seal_count,
                "runs" => self.state.runs.len(),
                "custodyfacts" => self.state.facts.len(),
            },
            "flight_gate" => self.flight_state()["state"].clone(),
            "acceptance_identity" => self.state.library_acceptance.clone().map_or(Value::Null, Value::from),
            "projection_lag" => 0,
            "writer" => self.writer.clone(),
            "active_lease_resources" => active,
            "authorization_denials" => self.state.policy.denied_decisions,
            "panel_exposures" => self.state.policy.exposures.len(),
            "remote_bundles" => self.state.remote.bundles.len(),
            "remote_verified_returns" => self.state.remote.returns.len(),
            "memory" => memory,
        })
    }

    /// Canonical identity helper exposed for callers building acceptance records.
    pub fn identity_of(value: &Value) -> Result<String> {
        object_id(value)
    }
}

fn object_len(store: &Store, id: &str) -> Option<u64> {
    let parsed = Sha256Id::parse(id).ok()?;
    if let Ok(Some(len)) = store.objects.len(&parsed) {
        return Some(len);
    }
    for journal in [&store.main, &store.memory] {
        if journal.contains_payload(&parsed) {
            return journal
                .payload(&parsed)
                .ok()
                .flatten()
                .map(|p| p.len() as u64);
        }
    }
    None
}
