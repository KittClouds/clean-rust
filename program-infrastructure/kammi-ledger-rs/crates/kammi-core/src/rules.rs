//! Pure rule modules: policy (`policy.py`), history (`history.py`), remote bundle validation
//! and signatures (`remote.py`), and the adapter builtin (`adapters.py`).

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use kammi_jcs::{canonical, raw_id, strict_json, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get, get_str};
use crate::safe::{is_safe, require_id};
use crate::state::{Authority, Policy};
use crate::time::Timestamp;

// ---------------------------------------------------------------- policy.py

const REQUIRES: [(&str, &str); 5] = [
    ("scientific_spec", "SEALED"),
    ("execution_spec", "SEALED"),
    ("predecessor_seal", "VERIFIED"),
    ("actor", "AUTHORIZED"),
    ("resource.gpu", "LEASED"),
];
const FORBIDS: [&str; 2] = ["truth_label_contact", "eval_panel_opened"];

pub fn validate_policy(policy: &Value) -> Result<()> {
    let map = policy
        .as_object()
        .ok_or_else(|| LedgerError::Type("policy must be an object".into()))?;
    const FIELDS: [&str; 5] = ["forbids", "requires", "schema", "stage_id", "version"];
    if map.len() != FIELDS.len() || !FIELDS.iter().all(|k| map.contains_key(*k)) {
        return value_error("policy fields do not match schema");
    }
    if map["schema"].as_str() != Some("KAMMI_POLICY_V1") {
        return value_error("unsupported policy schema");
    }
    for key in ["stage_id", "version"] {
        if !map[key].as_str().is_some_and(is_safe) {
            return value_error(format!("invalid policy {key}"));
        }
    }
    let (Some(requires), Some(forbids)) = (map["requires"].as_object(), map["forbids"].as_object())
    else {
        return value_error("policy predicates must be objects");
    };
    for (key, value) in requires {
        if !REQUIRES
            .iter()
            .any(|(k, v)| k == key && value.as_str() == Some(v))
        {
            return value_error("unsupported required predicate");
        }
    }
    for (key, value) in forbids {
        if !FORBIDS.contains(&key.as_str()) || value != &Value::Bool(true) {
            return value_error("unsupported forbidden predicate");
        }
    }
    Ok(())
}

/// Result of `policy.evaluate`: decision, ordered checks, matching grant.
pub struct Evaluation {
    pub decision: &'static str,
    pub checks: Vec<Value>,
    pub grant: Option<String>,
}

fn check(predicate: &str, pass: bool) -> Value {
    crate::obj! {"predicate" => predicate, "pass" => pass}
}

/// `policy.evaluate` with the live inputs passed in.
#[allow(clippy::too_many_arguments)]
pub fn evaluate(
    policy: &Value,
    state: &Policy,
    authority: &Authority,
    run_id: &str,
    actor_id: &str,
    stage_id: &str,
    lease_valid: bool,
    authorized_panel_exposure_id: Option<&str>,
    now: Timestamp,
) -> Result<Evaluation> {
    validate_policy(policy)?;
    let Some(policy_hash) = state.current_policy_hash(stage_id) else {
        return Ok(Evaluation {
            decision: "DENIED",
            checks: vec![check("policy_registered", false)],
            grant: None,
        });
    };
    require_id(policy_hash)?;
    let grant = authority.matching_grant(
        actor_id,
        "authorize_stage",
        run_id,
        stage_id,
        policy_hash,
        now,
    )?;
    let mut checks = vec![check("scoped_actor_grant", grant.is_some())];
    let mut requires: Vec<&String> = policy["requires"].as_object().unwrap().keys().collect();
    requires.sort();
    for predicate in requires {
        let passed = match predicate.as_str() {
            "scientific_spec" => state.specs.contains_key(&(
                run_id.to_string(),
                stage_id.to_string(),
                "SCIENTIFIC".to_string(),
            )),
            "execution_spec" => state.specs.contains_key(&(
                run_id.to_string(),
                stage_id.to_string(),
                "EXECUTION".to_string(),
            )),
            "predecessor_seal" => state
                .verified_seals
                .iter()
                .any(|(r, s, _)| r == run_id && s == stage_id),
            "actor" => grant.is_some(),
            "resource.gpu" => lease_valid,
            _ => return value_error("unsupported predicate"),
        };
        checks.push(check(predicate, passed));
    }
    let mut forbids: Vec<&String> = policy["forbids"].as_object().unwrap().keys().collect();
    forbids.sort();
    for predicate in forbids {
        let present = match predicate.as_str() {
            "truth_label_contact" => state.contacts.iter().any(|c| {
                c.get("run_id").and_then(Value::as_str) == Some(run_id)
                    && c.get("contact_class").and_then(Value::as_str) == Some("TRUTH_LABEL")
            }),
            "eval_panel_opened" => state.exposures.iter().any(|e| {
                e.get("run_id").and_then(Value::as_str) == Some(run_id)
                    && e.get("authorization_id").and_then(Value::as_str)
                        != authorized_panel_exposure_id
            }),
            _ => return value_error("unsupported predicate"),
        };
        checks.push(check(predicate, !present));
    }
    let all = checks.iter().all(|c| c["pass"] == Value::Bool(true));
    Ok(Evaluation {
        decision: if all { "AUTHORIZED" } else { "DENIED" },
        checks,
        grant,
    })
}

pub fn failed_reasons(checks: &[Value]) -> Vec<Value> {
    checks
        .iter()
        .filter(|c| c["pass"] != Value::Bool(true))
        .map(|c| c["predicate"].clone())
        .collect()
}

// ---------------------------------------------------------------- history.py

/// `history.summarize` over facts ordered by (kind, subject, fact_id).
pub fn summarize(facts: &[Value]) -> Result<Value> {
    let of_kind = |kind: &str| -> Vec<Value> {
        facts
            .iter()
            .filter(|f| f.get("kind").and_then(Value::as_str) == Some(kind))
            .cloned()
            .collect()
    };
    let heads = of_kind("HEAD");
    let attempts = of_kind("ATTEMPT");
    let supersessions = of_kind("SUPERSESSION");
    let contacts = of_kind("CONTACT");
    let accesses = of_kind("EVIDENCE_ACCESS");
    // Python builds {subject: object}; later facts overwrite earlier ones for a subject.
    let mut edges: indexmap::IndexMap<String, String> = indexmap::IndexMap::new();
    for fact in &supersessions {
        edges.insert(
            get_str(fact, "subject")?.to_string(),
            get_str(fact, "object")?.to_string(),
        );
    }
    let mut chains = Vec::new();
    for head in &heads {
        let mut chain = vec![get_str(head, "object")?.to_string()];
        let mut seen: std::collections::HashSet<String> = chain.iter().cloned().collect();
        while let Some(predecessor) = edges.get(chain.last().unwrap()) {
            if seen.contains(predecessor) {
                return value_error("supersession cycle");
            }
            seen.insert(predecessor.clone());
            chain.push(predecessor.clone());
        }
        chains.push(Value::from(chain));
    }
    let positive = contacts
        .iter()
        .any(|c| c.get("value").and_then(Value::as_str) == Some("YES"));
    let (stopped, other): (Vec<Value>, Vec<Value>) = attempts
        .into_iter()
        .partition(|a| a.get("value").and_then(Value::as_str) == Some("STOP"));
    Ok(crate::obj! {
        "heads" => heads,
        "stopped_attempts" => stopped,
        "other_attempts" => other,
        "supersessions" => supersessions,
        "head_predecessor_chains" => chains,
        "contact_assertions" => contacts,
        "contact_global_state" => if positive { "YES_IN_CITED_SCOPE" } else { "UNKNOWN_GLOBALLY" },
        "evidence_access_assertions" => accesses,
        "authorization_conferred" => false,
    })
}

// ---------------------------------------------------------------- remote.py

pub fn key_id(public: &[u8]) -> Result<String> {
    if public.len() != 32 {
        return value_error("Ed25519 public key must be 32 bytes");
    }
    Ok(raw_id(public).to_string())
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Python `bytes.fromhex`: accepts upper/lower case, rejects odd length and non-hex.
pub fn from_hex(text: &str) -> Result<Vec<u8>> {
    let clean: String = text.chars().filter(|c| !c.is_whitespace()).collect();
    if !clean.len().is_multiple_of(2) {
        return value_error("non-hexadecimal number found in fromhex() arg");
    }
    (0..clean.len())
        .step_by(2)
        .map(|i| {
            u8::from_str_radix(&clean[i..i + 2], 16).map_err(|_| {
                LedgerError::Value("non-hexadecimal number found in fromhex() arg".into())
            })
        })
        .collect()
}

pub fn sign(key: &SigningKey, raw: &[u8]) -> String {
    hex(&key.sign(raw).to_bytes())
}

pub fn verify_signature(public: &[u8], raw: &[u8], signature_hex: &str) -> bool {
    let Ok(public) = <[u8; 32]>::try_from(public) else {
        return false;
    };
    let Ok(key) = VerifyingKey::from_bytes(&public) else {
        return false;
    };
    let Ok(signature) = from_hex(signature_hex) else {
        return false;
    };
    let Ok(signature) = <[u8; 64]>::try_from(signature.as_slice()) else {
        return false;
    };
    key.verify(raw, &Signature::from_bytes(&signature)).is_ok()
}

pub fn validated_signed_json(raw: &[u8], signature_hex: &str, public: &[u8]) -> Result<Value> {
    if !verify_signature(public, raw, signature_hex) {
        return value_error("remote signature invalid");
    }
    let parsed = strict_json(raw)?;
    if canonical(&parsed)? != raw {
        return value_error("signed JSON is not canonical");
    }
    Ok(parsed)
}

fn is_int(value: &Value) -> bool {
    value.as_i64().is_some() || value.as_u64().is_some()
}

/// `remote.validate_bundle`.
pub fn validate_bundle(bundle: &Value) -> Result<()> {
    const REQUIRED: [&str; 21] = [
        "authorization_id",
        "command",
        "dirty_tree_policy",
        "environment_lock",
        "execution_spec",
        "expected_outputs",
        "fencing_token",
        "git_commit",
        "gpu_requirements",
        "input_artifacts",
        "input_roots",
        "lab",
        "lease_id",
        "lease_resource_id",
        "run_id",
        "runtime_requirements",
        "schema",
        "scientific_spec",
        "seeds",
        "stage_id",
        "worker_actor_id",
    ];
    let map = bundle
        .as_object()
        .ok_or_else(|| LedgerError::Type("bundle must be an object".into()))?;
    if map.len() != REQUIRED.len()
        || !REQUIRED.iter().all(|k| map.contains_key(*k))
        || map["schema"].as_str() != Some("KAMMI_REMOTE_BUNDLE_V1")
    {
        return value_error("remote bundle schema mismatch");
    }
    for key in ["run_id", "lab", "stage_id", "worker_actor_id"] {
        if !map[key].as_str().is_some_and(is_safe) {
            return value_error(format!("invalid {key}"));
        }
    }
    for key in [
        "scientific_spec",
        "execution_spec",
        "environment_lock",
        "authorization_id",
    ] {
        require_id(map[key].as_str().unwrap_or(""))?;
    }
    for key in ["input_roots", "input_artifacts"] {
        let Some(items) = map[key].as_array() else {
            return value_error(format!("invalid {key}"));
        };
        let unique: std::collections::HashSet<String> =
            items.iter().map(Value::to_string).collect();
        if unique.len() != items.len() {
            return value_error(format!("invalid {key}"));
        }
        for item in items {
            require_id(item.as_str().unwrap_or(""))?;
        }
    }
    if map["dirty_tree_policy"].as_str() != Some("CLEAN_REQUIRED") {
        return value_error("remote dirty-tree policy must require clean state");
    }
    let commit = map["git_commit"].as_str().unwrap_or("");
    if commit.len() != 40
        || !commit
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return value_error("expected full lowercase Git commit");
    }
    if !map["seeds"]
        .as_array()
        .is_some_and(|seeds| seeds.iter().all(|s| s.as_u64().is_some()))
    {
        return value_error("invalid seed list");
    }
    if !map["command"].as_array().is_some_and(|c| {
        !c.is_empty() && c.iter().all(|a| a.as_str().is_some_and(|s| !s.is_empty()))
    }) {
        return value_error("invalid exact command");
    }
    let outputs_ok = map["expected_outputs"].as_array().is_some_and(|outputs| {
        let unique: std::collections::HashSet<String> =
            outputs.iter().map(Value::to_string).collect();
        unique.len() == outputs.len() && outputs.iter().all(|o| o.as_str().is_some_and(is_safe))
    });
    if !outputs_ok {
        return value_error("invalid declared outputs");
    }
    if !map["runtime_requirements"].is_object() || !map["gpu_requirements"].is_object() {
        return value_error("runtime/GPU requirements must be objects");
    }
    if !map["lease_id"].is_null() {
        if !map["lease_id"].as_str().is_some_and(is_safe) {
            return value_error("invalid lease ID");
        }
        if !map["lease_resource_id"].as_str().is_some_and(is_safe) || !is_int(&map["fencing_token"])
        {
            return value_error("invalid lease fence");
        }
    } else if !map["lease_resource_id"].is_null() || !map["fencing_token"].is_null() {
        return value_error("lease fields must be all present or all null");
    }
    Ok(())
}

// ---------------------------------------------------------------- adapters.py

/// Exact `inspect.getsource(evaluation_cells_rename_v1)` bytes: its SHA-256 is the adapter's
/// registered implementation hash.
pub const EVAL_CELLS_RENAME_V1_SOURCE: &[u8] =
    include_bytes!("../assets/eval_cells_rename_v1.py.txt");

pub struct Builtin {
    pub source_schema: &'static str,
    pub target_schema: &'static str,
    pub version: &'static str,
    pub source: &'static [u8],
    pub function: fn(&[u8]) -> Result<Vec<u8>>,
}

pub fn builtin(adapter_id: &str) -> Option<Builtin> {
    match adapter_id {
        "EVAL_CELLS_RENAME_V1" => Some(Builtin {
            source_schema: "evaluation-v1",
            target_schema: "evaluation-v2",
            version: "v1",
            source: EVAL_CELLS_RENAME_V1_SOURCE,
            function: evaluation_cells_rename_v1,
        }),
        _ => None,
    }
}

pub fn implementation_hash(builtin: &Builtin) -> String {
    raw_id(builtin.source).to_string()
}

fn evaluation_cells_rename_v1(raw: &[u8]) -> Result<Vec<u8>> {
    let value = strict_json(raw)?;
    let Some(map) = value.as_object() else {
        return value_error("adapter source schema mismatch");
    };
    if map.get("schema").and_then(Value::as_str) != Some("evaluation-v1") {
        return value_error("adapter source schema mismatch");
    }
    if !map.contains_key("evaluation_checkpoint_cells") || map.contains_key("evaluation_cells") {
        return value_error("adapter source field is missing or ambiguous");
    }
    let mut result = map.clone();
    let cells = result.remove("evaluation_checkpoint_cells").unwrap();
    result.insert("evaluation_cells".into(), cells);
    result.insert("schema".into(), Value::from("evaluation-v2"));
    Ok(canonical(&Value::Object(result))?)
}

/// Reads a required nested object field (Python `payload[key]`).
pub fn field<'a>(value: &'a Value, key: &str) -> Result<&'a Value> {
    get(value, key)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adapter_source_hash_matches_python_registration() {
        let builtin = builtin("EVAL_CELLS_RENAME_V1").unwrap();
        assert_eq!(
            implementation_hash(&builtin),
            "sha256:fcbdec060aad1a2b2a4cff4e0cde04fb9e80c7ac6dea3983c75ac30021556f25"
        );
        let converted =
            (builtin.function)(br#"{"schema":"evaluation-v1","evaluation_checkpoint_cells":[1]}"#)
                .unwrap();
        assert_eq!(
            converted,
            br#"{"evaluation_cells":[1],"schema":"evaluation-v2"}"#
        );
    }

    #[test]
    fn ed25519_signatures_are_deterministic_and_verify() {
        let key = SigningKey::from_bytes(&[7u8; 32]);
        let signature = sign(&key, b"bundle");
        assert_eq!(signature, sign(&key, b"bundle"));
        assert!(verify_signature(
            key.verifying_key().as_bytes(),
            b"bundle",
            &signature
        ));
        assert!(!verify_signature(
            key.verifying_key().as_bytes(),
            b"bundlE",
            &signature
        ));
    }
}
