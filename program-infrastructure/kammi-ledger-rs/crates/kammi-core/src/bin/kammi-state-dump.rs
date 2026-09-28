//! Dumps the Rust Ledger's derived views in the same shape as `tools/v1_state_oracle.py`.
//! `kammi-state-dump <v2 store>`

use std::sync::Arc;

use kammi_core::{FlightIdentity, HashingEmbedder, Ledger, LedgerOptions, SystemClock};
use kammi_jcs::{canonical, Map, Value};
use kammi_store::{Store, StoreOptions};

fn map_of(items: impl Iterator<Item = (String, Value)>) -> Value {
    Value::Object(items.collect::<Map<String, Value>>())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::args()
        .nth(1)
        .ok_or("usage: kammi-state-dump <v2 store>")?;
    let store = Store::open(std::path::Path::new(&root), StoreOptions::default())?;
    let options = LedgerOptions {
        clock: Arc::new(SystemClock),
        signing_key: None,
        embedder: Some(Arc::new(HashingEmbedder::new(384))),
        flight: FlightIdentity {
            architecture: String::new(),
            source_root: String::new(),
            runtime_identity: String::new(),
        },
        writer: Value::Null,
    };
    let ledger = Ledger::open(store, options)?;
    let state = &ledger.state;
    let status = ledger.status()?;
    let pick = |value: &Value, keys: &[&str]| {
        map_of(keys.iter().map(|k| (k.to_string(), value[*k].clone())))
    };
    let mut runs = Map::new();
    for (run, lab) in &state.runs {
        runs.insert(
            run.clone(),
            kammi_core::obj! {
                "lab" => lab.clone(),
                "history" => ledger.history(run)?,
                "summary" => ledger.history_summary(run)?,
            },
        );
    }
    let mut seals = Map::new();
    for root_id in state.seal_artifacts.keys() {
        seals.insert(root_id.clone(), Value::from(ledger.verify_seal(root_id)?));
    }
    let mut panels = Map::new();
    for panel in state.exposure.panels.keys() {
        panels.insert(panel.clone(), state.exposure.report(panel)?);
    }
    let mut vaults = Map::new();
    for vault in state.vaults.vaults.keys() {
        vaults.insert(vault.clone(), state.vaults.view(vault)?);
    }
    let mut out = kammi_core::obj! {
        "status" => pick(&status, &["journal_events", "journal_head", "counts", "acceptance_identity", "active_lease_resources",
            "authorization_denials", "panel_exposures", "remote_bundles", "remote_verified_returns"]),
        "memory_status" => pick(&status["memory"], &["records", "journal_head"]),
        "runs" => Value::Object(runs),
        "artifacts" => map_of(state.artifacts.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "seals" => Value::Object(seals),
        "facts" => map_of(state.facts.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "actors" => map_of(state.authority.actors.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "grants" => map_of(state.authority.grants.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "policies" => map_of(state.policy.policies.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "specs" => map_of(state.policy.specs.iter().map(|((r, s, k), v)| (format!("{r}|{s}|{k}"), v.clone()))),
        "verified_seals" => {
            let mut v: Vec<String> = state.policy.verified_seals.iter().map(|(r, s, x)| format!("{r}|{s}|{x}")).collect();
            v.sort();
            Value::from(v)
        },
        "contacts" => state.policy.contacts.clone(),
        "authorizations" => map_of(state.policy.authorizations.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "panels" => Value::Object(panels),
        "resources" => map_of(state.leases.resources.iter().map(|(r, v)| (r.clone(), kammi_core::obj! {
            "resource" => v.clone(), "fencing_counter" => *state.leases.fencing.get(r).unwrap_or(&0)}))),
        "leases" => map_of(state.leases.leases.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "active_leases" => map_of(state.leases.active.iter().map(|(k, v)| (k.clone(), Value::from(v.as_str())))),
        "adapters" => map_of(state.adapters.registered.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "worker_keys" => map_of(state.remote.worker_keys.iter().map(|(k, v)| (k.clone(), Value::from(v.as_str())))),
        "bundles" => map_of(state.remote.bundles.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "returns" => map_of(state.remote.returns.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "attempts" => map_of(state.lifecycle.attempts.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "heads" => map_of(state.lifecycle.heads.iter().map(|((r, s), v)| (format!("{r}|{s}"), v.clone()))),
        "vaults" => Value::Object(vaults),
        "library_acceptance" => state.library_acceptance.clone().map_or(Value::Null, Value::from),
    };
    if let Some(memory) = &ledger.memory {
        let mut memories = Map::new();
        let mut traces = Map::new();
        for id in memory.records.keys() {
            memories.insert(id.clone(), ledger.memory_get(id)?);
            traces.insert(id.clone(), ledger.memory_trace(id)?);
        }
        out["memories"] = Value::Object(memories);
        out["memory_traces"] = Value::Object(traces);
    }
    println!("{}", String::from_utf8(canonical(&out)?)?);
    Ok(())
}
