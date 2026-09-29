//! `kammi-ledgerd accept`: issues the Rust Library's `LibraryAcceptanceV2`.
//!
//! ```text
//! kammi-ledgerd accept --store <v2 store> --evidence-map <map.json> [--request-id <id>]
//! ```
//!
//! The map names, per acceptance gate, the report files that prove it, plus the independent
//! verification of this very store (the unmodified Python `independent_verify` over its
//! `export-v1`):
//!
//! ```json
//! {"gates": {"artifact_tamper": ["reports/workspace-tests.txt"], ...},
//!  "independent_verification": "reports/independent-verify.json"}
//! ```
//!
//! Run by the same binary that will serve, with the daemon stopped, so the acceptance binds
//! exactly the source root and runtime identity the daemon computes. Every evidence file is
//! checked (a JSON report must say `PASS`; a test log must show `test result: ok` and no
//! failures), registered as an artifact, and cited; the core then applies its own
//! `accept_library` checks (all 32 gates, evidence registered and verified, identities bound).

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use kammi_core::ops_custody::GATES;
use kammi_core::{Clock, FlightIdentity, Ledger, LedgerOptions, SystemClock};
use kammi_jcs::{raw_id, Value};
use kammi_store::{Store, StoreOptions};

type Error = Box<dyn std::error::Error + Send + Sync>;

fn flag(args: &[String], name: &str) -> Option<String> {
    args.windows(2).find(|w| w[0] == name).map(|w| w[1].clone())
}

/// Refuses evidence that does not itself show a pass.
fn check_evidence(path: &Path, bytes: &[u8]) -> Result<(), Error> {
    if let Ok(value) = serde_json::from_slice::<Value>(bytes) {
        return match value.get("status").and_then(Value::as_str) {
            Some("PASS") => Ok(()),
            Some(other) => Err(format!("{}: status {other}, not PASS", path.display()).into()),
            None => Err(format!("{}: JSON evidence without a status", path.display()).into()),
        };
    }
    let text = String::from_utf8_lossy(bytes);
    if text.contains("test result: ok") && !text.contains("FAILED") && !text.contains("panicked") {
        Ok(())
    } else {
        Err(format!("{}: test log does not show a clean pass", path.display()).into())
    }
}

pub fn run(args: &[String], flight: FlightIdentity) -> Result<(), Error> {
    let store_root = PathBuf::from(flag(args, "--store").ok_or("--store required")?);
    let map_path = PathBuf::from(flag(args, "--evidence-map").ok_or("--evidence-map required")?);
    let base = map_path.parent().unwrap_or(Path::new(".")).to_path_buf();
    let map: Value = serde_json::from_slice(&std::fs::read(&map_path)?)?;
    let stamp = SystemClock.now().isoformat();
    let prefix = flag(args, "--request-id").unwrap_or_else(|| {
        format!(
            "rust-acceptance-{}",
            &raw_id(stamp.as_bytes()).to_string()[7..19]
        )
    });

    let store = Store::open(&store_root, StoreOptions::default())?;
    let options = LedgerOptions {
        clock: Arc::new(SystemClock),
        signing_key: None,
        embedder: None,
        flight: flight.clone(),
        writer: kammi_core::obj! {"pid" => std::process::id(), "implementation" => "kammi-ledgerd accept"},
    };
    let mut ledger = Ledger::open(store, options)?;
    let head_before = ledger.store.main.head().to_string();

    // The independent verification must cover this store at its current head.
    let audit_path = base.join(
        map["independent_verification"]
            .as_str()
            .ok_or("independent_verification missing")?,
    );
    let audit_bytes = std::fs::read(&audit_path)?;
    let audit_result: Value = serde_json::from_slice(&audit_bytes)?;
    if audit_result["journal_head"].as_str() != Some(head_before.as_str()) {
        return Err(format!(
            "independent verification covers head {} but the store is at {head_before}",
            audit_result["journal_head"]
        )
        .into());
    }
    if audit_result.get("status").and_then(Value::as_str) != Some("PASS") {
        return Err("independent verification did not pass".into());
    }

    // Register every evidence file once.
    let gates = map["gates"].as_object().ok_or("gates missing")?;
    let wanted: BTreeSet<&str> = GATES.iter().copied().collect();
    let named: BTreeSet<&str> = gates.keys().map(String::as_str).collect();
    if named != wanted {
        return Err(format!(
            "evidence map must name exactly the {} gates; missing {:?}, extra {:?}",
            GATES.len(),
            wanted.difference(&named).collect::<Vec<_>>(),
            named.difference(&wanted).collect::<Vec<_>>()
        )
        .into());
    }
    let mut registered: BTreeMap<String, String> = BTreeMap::new();
    for files in gates.values() {
        for file in files.as_array().ok_or("gate evidence must be a list")? {
            let name = file.as_str().ok_or("evidence path must be a string")?;
            if registered.contains_key(name) {
                continue;
            }
            let path = base.join(name);
            let bytes = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            check_evidence(&path, &bytes)?;
            let digest = raw_id(name.as_bytes()).to_string();
            let (id, _) = ledger.register_bytes(
                &bytes,
                "library-qualification-evidence",
                "library-auditor",
                &format!("{prefix}:evidence-{}", &digest[7..23]),
            )?;
            registered.insert(name.to_string(), id);
        }
    }
    let mut suite_gates = kammi_jcs::Map::new();
    for (gate, files) in gates {
        let evidence: Vec<Value> = files
            .as_array()
            .unwrap()
            .iter()
            .map(|f| Value::from(registered[f.as_str().unwrap()].clone()))
            .collect();
        suite_gates.insert(
            gate.clone(),
            kammi_core::obj! {"status" => "PASS", "evidence" => evidence},
        );
    }
    let suite = kammi_core::obj! {
        "schema" => "KAMMI_ENDSTATE_ACCEPTANCE_V1", "status" => "PASS", "implementation" => "kammi-ledger-rs",
        "architecture_hash" => flight.architecture.clone(), "source_root" => flight.source_root.clone(),
        "runtime_identity" => flight.runtime_identity.clone(), "journal_head" => head_before.clone(),
        "gates" => Value::Object(suite_gates), "issued_at" => stamp.clone(),
    };
    let (suite_id, _) = ledger.register_bytes(
        &kammi_jcs::canonical(&suite)?,
        "library-qualification-suite",
        "library-auditor",
        &format!("{prefix}:suite"),
    )?;
    let audit = kammi_core::obj! {
        "schema" => "KAMMI_ENDSTATE_INDEPENDENT_AUDIT_V1", "status" => "PASS",
        "source_root" => flight.source_root.clone(), "runtime_identity" => flight.runtime_identity.clone(),
        "acceptance_suite_root" => suite_id.clone(),
        "independent_verifier" => "kammi-ledger/scripts/independent_verify.py (unmodified Python) over export-v1 of this store",
        "verified_head" => head_before.clone(), "result" => audit_result,
    };
    let (audit_id, _) = ledger.register_bytes(
        &kammi_jcs::canonical(&audit)?,
        "library-independent-audit",
        "library-auditor",
        &format!("{prefix}:audit"),
    )?;

    // Evidence seal, chained to the previous acceptance's evidence when it has one.
    let prior = ledger.state.library_acceptance.clone();
    let mut parents = Vec::new();
    if let Some(prior_id) = &prior {
        if let Ok(previous) = ledger.object_json(prior_id) {
            if let Some(root) = previous.get("evidence_merkle_root").and_then(Value::as_str) {
                parents.push(root.to_string());
            }
        }
    }
    let mut members: Vec<String> = registered.values().cloned().collect();
    members.push(suite_id.clone());
    members.push(audit_id.clone());
    members.sort();
    members.dedup();
    let (evidence_root, _) = ledger.create_seal(
        &members,
        &parents,
        "library-auditor",
        &format!("{prefix}:evidence-seal"),
    )?;

    let acceptance = kammi_core::obj! {
        "schema" => "LibraryAcceptanceV2", "architecture_hash" => flight.architecture.clone(),
        "source_root" => flight.source_root.clone(), "runtime_identity" => flight.runtime_identity.clone(),
        "acceptance_suite_root" => suite_id.clone(), "independent_verification_root" => audit_id.clone(),
        "evidence_merkle_root" => evidence_root.clone(),
        "gates" => Value::Object(GATES.iter().map(|g| (g.to_string(), Value::from("PASS"))).collect()),
        "issued_at" => stamp, "predecessor_acceptance" => prior.clone().map_or(Value::Null, Value::from),
        "scope" => "Infrastructure acceptance of the Rust Library only; scientific protocols retain their own authorization.",
    };
    let (acceptance_id, event) = ledger.accept_library(&acceptance, &prefix)?;
    let flight_state = ledger.flight_state();
    println!(
        "{}",
        kammi_core::obj! {
            "status" => if flight_state["state"] == "OPEN" { "PASS" } else { "FAIL" },
            "acceptance_identity" => acceptance_id, "event_id" => event, "flight_state" => flight_state,
            "evidence_files" => registered.len(), "acceptance_suite_root" => suite_id, "independent_verification_root" => audit_id,
            "evidence_merkle_root" => evidence_root, "predecessor_acceptance" => prior.map_or(Value::Null, Value::from),
            "source_root" => flight.source_root, "runtime_identity" => flight.runtime_identity,
        }
    );
    Ok(())
}
