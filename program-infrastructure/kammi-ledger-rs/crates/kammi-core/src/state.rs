//! Replayed custody state. `State::apply` is the Rust counterpart of `Ledger._index` plus
//! every `*State.apply` in the Python daemon: same effects, same replay refusals. It never
//! reads a clock.

use hashbrown::{HashMap, HashSet};
use indexmap::IndexMap;
use kammi_jcs::{raw_id, typed_id, Domain, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get, get_int, get_str, merged, without};
use crate::safe::{is_safe, require_id};
use crate::time::{parse_utc, Timestamp};

pub const ACTOR_KINDS: [&str; 5] = ["human", "agent", "service", "remote_worker", "auditor"];
pub const ACTIONS: [&str; 12] = [
    "create_run",
    "register_artifact",
    "create_seal",
    "bind_spec",
    "authorize_stage",
    "open_panel",
    "acquire_lease",
    "execute_bundle",
    "execute_local",
    "record_memory",
    "register_adapter",
    "apply_adapter",
];

#[derive(Default)]
pub struct Authority {
    pub actors: IndexMap<String, Value>,
    pub grants: IndexMap<String, Value>,
}

impl Authority {
    /// `sha256(token).hexdigest() == credential_sha256`, compared in constant time.
    pub fn verify_credential(&self, actor_id: &str, token: &str) -> bool {
        let Some(actor) = self.actors.get(actor_id) else {
            return false;
        };
        let expected = actor
            .get("credential_sha256")
            .and_then(Value::as_str)
            .unwrap_or("");
        let digest = raw_id(token.as_bytes()).to_string();
        constant_time_eq(&digest.as_bytes()[7..], expected.as_bytes())
    }

    pub fn actor_lab(&self, actor_id: &str) -> Option<&str> {
        self.actors
            .get(actor_id)
            .and_then(|a| a.get("lab"))
            .and_then(Value::as_str)
    }

    /// First grant (in issue order) matching the exact scope and still unexpired.
    pub fn matching_grant(
        &self,
        actor_id: &str,
        action: &str,
        run_id: &str,
        stage_id: &str,
        policy_hash: &str,
        now: Timestamp,
    ) -> Result<Option<String>> {
        for (grant_id, grant) in &self.grants {
            let field = |k: &str| grant.get(k).and_then(Value::as_str);
            if field("actor_id") == Some(actor_id)
                && field("action") == Some(action)
                && field("run_id") == Some(run_id)
                && field("stage_id") == Some(stage_id)
                && field("policy_hash") == Some(policy_hash)
                && parse_utc(field("expires_utc").unwrap_or(""))? > now
            {
                return Ok(Some(grant_id.clone()));
            }
        }
        Ok(None)
    }
}

pub fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[derive(Default)]
pub struct Policy {
    /// stage_id -> latest PolicyRegistered payload.
    pub policies: HashMap<String, Value>,
    /// (run, stage, kind) -> latest SpecBound payload, in first-bound order.
    pub specs: IndexMap<(String, String, String), Value>,
    pub verified_seals: HashSet<(String, String, String)>,
    pub contacts: Vec<Value>,
    pub exposures: Vec<Value>,
    /// AuthorizationIssued event_id -> receipt.
    pub authorizations: HashMap<String, Value>,
    /// Count of PolicyEvaluated/AuthorizationDenied payloads whose decision is DENIED.
    pub denied_decisions: usize,
}

impl Policy {
    pub fn current_policy_hash(&self, stage_id: &str) -> Option<&str> {
        self.policies
            .get(stage_id)
            .and_then(|p| p.get("policy_hash"))
            .and_then(Value::as_str)
    }

    /// `{kind: artifact_id}` for every spec bound to (run, stage).
    pub fn binding_snapshot(&self, run_id: &str, stage_id: &str) -> Value {
        let mut map = kammi_jcs::Map::new();
        for ((run, stage, kind), bound) in &self.specs {
            if run == run_id && stage == stage_id {
                map.insert(
                    kind.clone(),
                    bound.get("artifact_id").cloned().unwrap_or(Value::Null),
                );
            }
        }
        Value::Object(map)
    }

    /// `PolicyState.authorization_valid`.
    pub fn authorization_valid(
        &self,
        identity: &str,
        actor_id: &str,
        run_id: &str,
        stage_id: &str,
        now: Timestamp,
    ) -> Result<bool> {
        let Some(issued) = self.authorizations.get(identity) else {
            return Ok(false);
        };
        let field = |k: &str| issued.get(k).and_then(Value::as_str);
        let bindings = issued
            .get("spec_bindings")
            .cloned()
            .unwrap_or_else(|| Value::Object(Default::default()));
        Ok(field("actor_id") == Some(actor_id)
            && field("run_id") == Some(run_id)
            && field("stage_id") == Some(stage_id)
            && field("policy_hash") == self.current_policy_hash(stage_id)
            && bindings == self.binding_snapshot(run_id, stage_id)
            && parse_utc(field("expires_utc").unwrap_or(""))? > now)
    }
}

#[derive(Default)]
pub struct Exposure {
    pub panels: IndexMap<String, Value>,
    pub opened: Vec<Value>,
    pub denied: Vec<Value>,
    pub by_request: HashMap<String, (String, Value)>,
}

pub const PURPOSES: [&str; 6] = [
    "generation",
    "fit",
    "selection",
    "thresholding",
    "diagnostic",
    "terminal",
];

impl Exposure {
    pub fn report(&self, panel_id: &str) -> Result<Value> {
        if !self.panels.contains_key(panel_id) {
            return value_error("unknown panel");
        }
        let selected: Vec<Value> = self
            .opened
            .iter()
            .filter(|e| e.get("panel_id").and_then(Value::as_str) == Some(panel_id))
            .cloned()
            .collect();
        let mut vector = kammi_jcs::Map::new();
        for purpose in PURPOSES {
            let count = selected
                .iter()
                .filter(|e| e.get("purpose").and_then(Value::as_str) == Some(purpose))
                .count();
            vector.insert(purpose.to_string(), Value::from(count));
        }
        let denials: Vec<Value> = self
            .denied
            .iter()
            .filter(|e| e.get("panel_id").and_then(Value::as_str) == Some(panel_id))
            .cloned()
            .collect();
        Ok(crate::obj! {
            "panel_id" => panel_id,
            "exposure_vector" => Value::Object(vector),
            "count" => selected.len(),
            "openings" => selected,
            "denials" => denials,
        })
    }
}

pub const RESOURCE_KINDS: [&str; 7] = [
    "GPU",
    "CPU_POOL",
    "HOST",
    "REMOTE_WORKER",
    "DATASET_LOCK",
    "PANEL_LOCK",
    "FILESYSTEM_EXCLUSIVE",
];

#[derive(Default)]
pub struct Leases {
    pub resources: IndexMap<String, Value>,
    pub leases: HashMap<String, Value>,
    pub active: IndexMap<String, String>,
    pub fencing: HashMap<String, i64>,
    pub by_request: HashMap<String, (String, Value)>,
}

impl Leases {
    pub fn valid(
        &self,
        lease_id: &str,
        resource_id: &str,
        fencing_token: i64,
        actor_id: &str,
        run_id: &str,
        now: Timestamp,
    ) -> Result<bool> {
        let Some(lease) = self.leases.get(lease_id) else {
            return Ok(false);
        };
        let field = |k: &str| lease.get(k).and_then(Value::as_str);
        Ok(
            self.active.get(resource_id).map(String::as_str) == Some(lease_id)
                && field("resource_id") == Some(resource_id)
                && lease.get("fencing_token").and_then(Value::as_i64) == Some(fencing_token)
                && self.fencing.get(resource_id) == Some(&fencing_token)
                && field("actor_id") == Some(actor_id)
                && field("run_id") == Some(run_id)
                && parse_utc(field("expires_utc").unwrap_or(""))? > now,
        )
    }

    pub fn report(&self, resource_id: &str, now: Timestamp) -> Result<Value> {
        let Some(resource) = self.resources.get(resource_id) else {
            return value_error("unknown resource");
        };
        let lease = self
            .active
            .get(resource_id)
            .and_then(|id| self.leases.get(id));
        let active = match lease {
            Some(lease)
                if parse_utc(
                    lease
                        .get("expires_utc")
                        .and_then(Value::as_str)
                        .unwrap_or(""),
                )? > now =>
            {
                lease.clone()
            }
            _ => Value::Null,
        };
        Ok(crate::obj! {
            "resource" => resource.clone(),
            "fencing_counter" => *self.fencing.get(resource_id).unwrap_or(&0),
            "active_lease" => active,
        })
    }

    /// Any valid GPU lease for (stage, actor, run): `resource.gpu` predicate input.
    pub fn gpu_lease_valid(
        &self,
        stage_id: &str,
        actor_id: &str,
        run_id: &str,
        now: Timestamp,
    ) -> Result<bool> {
        for (rid, lease_id) in &self.active {
            let kind = self
                .resources
                .get(rid)
                .and_then(|r| r.get("kind"))
                .and_then(Value::as_str);
            let lease = &self.leases[lease_id];
            if kind == Some("GPU")
                && lease.get("stage_id").and_then(Value::as_str) == Some(stage_id)
                && self.valid(
                    lease_id,
                    rid,
                    lease
                        .get("fencing_token")
                        .and_then(Value::as_i64)
                        .unwrap_or(-1),
                    actor_id,
                    run_id,
                    now,
                )?
            {
                return Ok(true);
            }
        }
        Ok(false)
    }
}

#[derive(Default)]
pub struct Adapters {
    pub registered: HashMap<String, Value>,
    pub applications: usize,
}

#[derive(Default)]
pub struct Remote {
    pub worker_keys: HashMap<String, String>,
    pub bundles: HashMap<String, Value>,
    pub returns: HashMap<String, Value>,
    pub return_events: HashMap<String, String>,
}

#[derive(Default)]
pub struct Lifecycle {
    pub attempts: HashMap<String, Value>,
    pub heads: HashMap<(String, String), Value>,
}

#[derive(Default, Clone, Debug)]
pub struct VaultRecord {
    pub owner: String,
    pub epoch: i64,
    pub sources: IndexMap<String, Value>,
    pub revisions: HashMap<(String, i64), Value>,
    pub generation: Option<Value>,
    pub reader: Option<Value>,
    pub authority: Option<Value>,
}

#[derive(Default)]
pub struct Vaults {
    pub vaults: IndexMap<String, VaultRecord>,
}

pub const VAULT_EVENTS: [&str; 5] = [
    "VaultCreated",
    "VaultSourceCommitted",
    "VaultGenerationSelected",
    "VaultReaderPositionSet",
    "VaultProductPrimarySelected",
];

impl Vaults {
    /// `VaultState.apply`.
    pub fn apply(&mut self, kind: &str, payload: &Value) -> Result<()> {
        match kind {
            "VaultCreated" => {
                let vault_id = get_str(payload, "vault_id")?;
                let owner = get_str(payload, "owner_actor")?;
                if let Some(existing) = self.vaults.get(vault_id) {
                    if existing.owner != owner {
                        return value_error("vault owner collision");
                    }
                    return Ok(());
                }
                self.vaults.insert(
                    vault_id.to_string(),
                    VaultRecord {
                        owner: owner.to_string(),
                        ..Default::default()
                    },
                );
            }
            "VaultSourceCommitted" => {
                let vault = self.vault_mut(payload)?;
                let source_id = get_str(payload, "source_id")?.to_string();
                let prior_revision = vault
                    .sources
                    .get(&source_id)
                    .and_then(|s| s.get("revision"))
                    .and_then(Value::as_i64)
                    .unwrap_or(0);
                let base = get_int(payload, "base_revision")?;
                if base != prior_revision {
                    return value_error("vault source revision discontinuity");
                }
                let revision = get_int(payload, "revision")?;
                let epoch = get_int(payload, "epoch")?;
                if revision != base + 1 || epoch != vault.epoch + 1 {
                    return value_error("vault source epoch discontinuity");
                }
                let source = crate::obj! {
                    "revision" => revision,
                    "artifact_id" => get(payload, "artifact_id")?.clone(),
                    "byte_count" => get(payload, "byte_count")?.clone(),
                    "epoch" => epoch,
                };
                vault.sources.insert(source_id.clone(), source.clone());
                vault.revisions.insert((source_id, revision), source);
                vault.epoch = epoch;
            }
            "VaultGenerationSelected" => {
                let vault = self.vault_mut(payload)?;
                if get_int(payload, "source_epoch")? != vault.epoch {
                    return value_error("vault generation selected from stale sources");
                }
                let generation_id = get_int(payload, "generation_id")?;
                if let Some(current) = &vault.generation {
                    if generation_id
                        <= current
                            .get("generation_id")
                            .and_then(Value::as_i64)
                            .unwrap_or(0)
                    {
                        return value_error("vault generation must increase");
                    }
                }
                vault.generation = Some(crate::obj! {
                    "generation_id" => generation_id,
                    "source_epoch" => get(payload, "source_epoch")?.clone(),
                    "manifest_artifact_id" => get(payload, "manifest_artifact_id")?.clone(),
                    "asset_ids" => get(payload, "asset_ids")?.clone(),
                });
            }
            "VaultReaderPositionSet" => {
                let vault = self.vault_mut(payload)?;
                let key = (
                    get_str(payload, "source_id")?.to_string(),
                    get_int(payload, "revision")?,
                );
                let offset = get_int(payload, "offset")?;
                match vault.revisions.get(&key) {
                    Some(source)
                        if offset
                            <= source
                                .get("byte_count")
                                .and_then(Value::as_i64)
                                .unwrap_or(-1) => {}
                    _ => return value_error("reader locator references unavailable revision"),
                }
                vault.reader = Some(crate::obj! {
                    "source_id" => key.0.clone(),
                    "revision" => key.1,
                    "offset" => offset,
                });
            }
            "VaultProductPrimarySelected" => {
                let vault = self.vault_mut(payload)?;
                let epoch = get_int(payload, "source_epoch")?;
                if vault.authority.is_some() || epoch != vault.epoch {
                    return value_error("vault product authority transition is stale or repeated");
                }
                vault.authority = Some(crate::obj! {
                    "mode" => "LIBRARY_PRIMARY",
                    "source_epoch" => epoch,
                    "receipt_artifact_id" => get(payload, "receipt_artifact_id")?.clone(),
                });
            }
            _ => {}
        }
        Ok(())
    }

    fn vault_mut(&mut self, payload: &Value) -> Result<&mut VaultRecord> {
        let vault_id = get_str(payload, "vault_id")?;
        self.vaults
            .get_mut(vault_id)
            .ok_or_else(|| LedgerError::Key(vault_id.to_string()))
    }

    pub fn view(&self, vault_id: &str) -> Result<Value> {
        let vault = self
            .vaults
            .get(vault_id)
            .ok_or_else(|| LedgerError::Key(vault_id.to_string()))?;
        let current = vault
            .generation
            .as_ref()
            .is_some_and(|g| g.get("source_epoch").and_then(Value::as_i64) == Some(vault.epoch));
        let sources: kammi_jcs::Map<String, Value> = vault
            .sources
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        Ok(crate::obj! {
            "vault_id" => vault_id,
            "owner_actor" => vault.owner.clone(),
            "source_epoch" => vault.epoch,
            "sources" => Value::Object(sources),
            "active_generation" => vault.generation.clone().unwrap_or(Value::Null),
            "generation_current" => current,
            "reader" => vault.reader.clone().unwrap_or(Value::Null),
            "product_authority" => vault.authority.clone().unwrap_or_else(|| crate::obj! {"mode" => "LEGACY_MIRROR"}),
        })
    }
}

pub const FACT_KINDS: [&str; 5] = [
    "ATTEMPT",
    "SUPERSESSION",
    "CONTACT",
    "EVIDENCE_ACCESS",
    "HEAD",
];

fn fact_values(kind: &str) -> &'static [&'static str] {
    match kind {
        "ATTEMPT" => &["PASS", "STOP", "UNKNOWN"],
        "SUPERSESSION" => &["DECLARED"],
        "CONTACT" | "EVIDENCE_ACCESS" => &["YES", "NO_ATTESTED", "UNKNOWN"],
        "HEAD" => &["SEALED", "SUPERSEDED", "UNKNOWN"],
        _ => &[],
    }
}

/// `facts.validated_fact`: returns the fact plus its `fact_id`.
pub fn validated_fact(
    fact: &Value,
    artifacts: &HashMap<String, Value>,
    runs: &IndexMap<String, String>,
) -> Result<Value> {
    let map = fact
        .as_object()
        .ok_or_else(|| LedgerError::Type("fact must be an object".into()))?;
    const REQUIRED: [&str; 7] = [
        "evidence_artifact",
        "kind",
        "object",
        "run_id",
        "scope",
        "subject",
        "value",
    ];
    if map.len() != REQUIRED.len() || !REQUIRED.iter().all(|k| map.contains_key(*k)) {
        return value_error("custody fact fields must match the central vocabulary");
    }
    let kind = map["kind"].as_str().unwrap_or("");
    let value = map["value"].as_str().unwrap_or("\u{0}");
    if !FACT_KINDS.contains(&kind) || !fact_values(kind).contains(&value) {
        return value_error("unsupported custody fact kind/value");
    }
    if !map["run_id"].as_str().is_some_and(|r| runs.contains_key(r)) {
        return value_error("unknown run");
    }
    for field in ["run_id", "subject", "object", "scope"] {
        if !map[field].as_str().is_some_and(is_safe) {
            return value_error(format!("invalid {field}"));
        }
    }
    let evidence = map["evidence_artifact"]
        .as_str()
        .ok_or_else(|| LedgerError::Value("expected lowercase sha256: digest".into()))?;
    require_id(evidence)?;
    if !artifacts.contains_key(evidence) {
        return value_error("fact evidence must be a registered artifact");
    }
    let fact_id = typed_id(Domain::Fact, fact)?.to_string();
    Ok(merged(fact, crate::obj! {"fact_id" => fact_id}))
}

/// Everything the daemon knows after replaying the main journal.
#[derive(Default)]
pub struct State {
    pub artifacts: HashMap<String, Value>,
    pub seal_artifacts: HashMap<String, String>,
    /// run_id -> lab, in creation order.
    pub runs: IndexMap<String, String>,
    pub facts: HashMap<String, Value>,
    pub facts_by_run: HashMap<String, Vec<String>>,
    pub seal_count: usize,
    pub authority: Authority,
    pub policy: Policy,
    pub exposure: Exposure,
    pub leases: Leases,
    pub adapters: Adapters,
    pub remote: Remote,
    pub lifecycle: Lifecycle,
    pub vaults: Vaults,
    pub library_acceptance: Option<String>,
}

impl State {
    /// Applies one committed main-journal event. `object_len` resolves a CAS identity to its
    /// size (None when absent), for the replay checks the Python daemon performs.
    pub fn apply(
        &mut self,
        kind: &str,
        payload: &Value,
        event_id: &str,
        object_len: &dyn Fn(&str) -> Option<u64>,
    ) -> Result<()> {
        // AuthorityState
        match kind {
            "ActorRegistered" => {
                let actor_id = get_str(payload, "actor_id")?.to_string();
                if self
                    .authority
                    .actors
                    .get(&actor_id)
                    .is_some_and(|a| a != payload)
                {
                    return value_error("actor identity collision");
                }
                self.authority.actors.insert(actor_id, payload.clone());
            }
            "GrantIssued" => {
                let grant_id = get_str(payload, "grant_id")?.to_string();
                if self
                    .authority
                    .grants
                    .get(&grant_id)
                    .is_some_and(|g| g != payload)
                {
                    return value_error("grant identity collision");
                }
                self.authority.grants.insert(grant_id, payload.clone());
            }
            _ => {}
        }
        // PolicyState
        match kind {
            "PolicyRegistered" => {
                self.policy
                    .policies
                    .insert(get_str(payload, "stage_id")?.to_string(), payload.clone());
            }
            "SpecBound" => {
                let key = (
                    get_str(payload, "run_id")?.to_string(),
                    get_str(payload, "stage_id")?.to_string(),
                    get_str(payload, "spec_kind")?.to_string(),
                );
                self.policy.specs.insert(key, payload.clone());
            }
            "SealVerified" => {
                self.policy.verified_seals.insert((
                    get_str(payload, "run_id")?.to_string(),
                    get_str(payload, "stage_id")?.to_string(),
                    get_str(payload, "root")?.to_string(),
                ));
            }
            "ContactRecorded" => self.policy.contacts.push(payload.clone()),
            "ExposureOpened" => self.policy.exposures.push(payload.clone()),
            "PolicyEvaluated" | "AuthorizationDenied" => {
                if payload.get("decision").and_then(Value::as_str) == Some("DENIED") {
                    self.policy.denied_decisions += 1;
                }
            }
            "AuthorizationIssued" => {
                self.policy
                    .authorizations
                    .insert(event_id.to_string(), payload.clone());
            }
            _ => {}
        }
        // ExposureState
        match kind {
            "PanelRegistered" => {
                let panel_id = get_str(payload, "panel_id")?.to_string();
                if self
                    .exposure
                    .panels
                    .get(&panel_id)
                    .is_some_and(|p| p != payload)
                {
                    return value_error("panel identity collision");
                }
                self.exposure.panels.insert(panel_id, payload.clone());
            }
            "ExposureOpened" | "ExposureDenied" => {
                if kind == "ExposureOpened" {
                    self.exposure.opened.push(payload.clone());
                } else {
                    self.exposure.denied.push(payload.clone());
                }
                self.exposure.by_request.insert(
                    get_str(payload, "request_id")?.to_string(),
                    (kind.to_string(), payload.clone()),
                );
            }
            _ => {}
        }
        // LeaseState
        match kind {
            "ResourceRegistered" => {
                let rid = get_str(payload, "resource_id")?.to_string();
                if self
                    .leases
                    .resources
                    .get(&rid)
                    .is_some_and(|r| r != payload)
                {
                    return value_error("resource identity collision");
                }
                self.leases.resources.insert(rid, payload.clone());
            }
            "LeaseGranted" => {
                let rid = get_str(payload, "resource_id")?.to_string();
                let token = get_int(payload, "fencing_token")?;
                if token != self.leases.fencing.get(&rid).copied().unwrap_or(0) + 1 {
                    return value_error("non-monotonic lease fencing token");
                }
                self.leases.fencing.insert(rid.clone(), token);
                let lease_id = get_str(payload, "lease_id")?.to_string();
                self.leases.leases.insert(lease_id.clone(), payload.clone());
                self.leases.active.insert(rid, lease_id);
                self.leases.by_request.insert(
                    get_str(payload, "request_id")?.to_string(),
                    (kind.to_string(), payload.clone()),
                );
            }
            "LeaseDenied" => {
                self.leases.by_request.insert(
                    get_str(payload, "request_id")?.to_string(),
                    (kind.to_string(), payload.clone()),
                );
            }
            "LeaseRenewed" => {
                let lease_id = get_str(payload, "lease_id")?;
                let lease = self
                    .leases
                    .leases
                    .get_mut(lease_id)
                    .ok_or_else(|| LedgerError::Key(lease_id.to_string()))?;
                *lease = merged(
                    lease,
                    crate::obj! {"expires_utc" => get(payload, "expires_utc")?.clone()},
                );
            }
            "LeaseExpired" | "LeaseReleased" => {
                let rid = get_str(payload, "resource_id")?;
                if self.leases.active.get(rid).map(String::as_str)
                    == Some(get_str(payload, "lease_id")?)
                {
                    self.leases.active.shift_remove(rid);
                }
            }
            _ => {}
        }
        // AdapterState
        match kind {
            "AdapterRegistered" => {
                let name = get_str(payload, "adapter_id")?.to_string();
                if self
                    .adapters
                    .registered
                    .get(&name)
                    .is_some_and(|a| a != payload)
                {
                    return value_error("adapter identity collision");
                }
                self.adapters.registered.insert(name, payload.clone());
            }
            "AdapterApplied" => self.adapters.applications += 1,
            _ => {}
        }
        // RemoteState
        match kind {
            "WorkerKeyRegistered" => {
                self.remote.worker_keys.insert(
                    get_str(payload, "worker_actor_id")?.to_string(),
                    get_str(payload, "public_key_hex")?.to_string(),
                );
            }
            "RemoteBundleCreated" => {
                self.remote.bundles.insert(
                    get_str(payload, "bundle_artifact_id")?.to_string(),
                    payload.clone(),
                );
            }
            "RemoteReceiptVerified" => {
                let bundle_id = get_str(payload, "bundle_artifact_id")?.to_string();
                if self
                    .remote
                    .returns
                    .get(&bundle_id)
                    .is_some_and(|r| r != payload)
                {
                    return value_error("remote bundle has conflicting verified returns");
                }
                self.remote
                    .returns
                    .insert(bundle_id.clone(), payload.clone());
                self.remote
                    .return_events
                    .insert(bundle_id, event_id.to_string());
            }
            _ => {}
        }
        // LifecycleState
        match kind {
            "AttemptStarted" => {
                let attempt_id = get_str(payload, "attempt_id")?.to_string();
                if self.lifecycle.attempts.contains_key(&attempt_id) {
                    return value_error("duplicate attempt identity");
                }
                let record = merged(
                    payload,
                    crate::obj! {"state" => "RUNNING", "events" => vec![event_id.to_string()]},
                );
                self.lifecycle.attempts.insert(attempt_id, record);
            }
            "AttemptStopped" | "AttemptCompleted" => {
                let attempt_id = get_str(payload, "attempt_id")?;
                let attempt = self
                    .lifecycle
                    .attempts
                    .get_mut(attempt_id)
                    .ok_or_else(|| LedgerError::Key(attempt_id.to_string()))?;
                if attempt.get("state").and_then(Value::as_str) != Some("RUNNING") {
                    return value_error("attempt already terminal");
                }
                let mut events: Vec<Value> = attempt
                    .get("events")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                events.push(Value::from(event_id));
                let state = if kind == "AttemptStopped" {
                    "STOPPED"
                } else {
                    "COMPLETE"
                };
                let mut updated = merged(attempt, payload.clone());
                updated = merged(
                    &updated,
                    crate::obj! {"state" => state, "events" => Value::Array(events)},
                );
                *attempt = updated;
            }
            "ResultDeclared" => {
                let key = (
                    get_str(payload, "run_id")?.to_string(),
                    get_str(payload, "stage_id")?.to_string(),
                );
                self.lifecycle
                    .heads
                    .insert(key, merged(payload, crate::obj! {"event_id" => event_id}));
            }
            _ => {}
        }
        // Vault replay checks (Ledger._index), then VaultState.
        match kind {
            "VaultSourceCommitted" => {
                let id = get_str(payload, "artifact_id")?;
                match object_len(id) {
                    None => return value_error("vault source bytes unavailable during replay"),
                    Some(len)
                        if Some(len as i64)
                            != payload.get("byte_count").and_then(Value::as_i64) =>
                    {
                        return value_error("vault source byte count changed")
                    }
                    _ => {}
                }
            }
            "VaultGenerationSelected" => {
                let mut ids = vec![get_str(payload, "manifest_artifact_id")?.to_string()];
                ids.extend(crate::json::string_list(payload, "asset_ids")?);
                if ids.iter().any(|id| object_len(id).is_none()) {
                    return value_error("vault generation bytes unavailable during replay");
                }
            }
            "VaultProductPrimarySelected"
                if object_len(get_str(payload, "receipt_artifact_id")?).is_none() =>
            {
                return value_error("vault cutover receipt unavailable during replay");
            }
            _ => {}
        }
        self.vaults.apply(kind, payload)?;
        // Custody core (Ledger._index)
        match kind {
            "LibraryAccepted" => {
                self.library_acceptance =
                    Some(get_str(payload, "acceptance_artifact")?.to_string());
            }
            "ArtifactRegistered" => {
                let artifact_id = require_id(get_str(payload, "artifact_id")?)?.to_string();
                if let Some(previous) = self.artifacts.get(&artifact_id) {
                    if previous.get("byte_count") != payload.get("byte_count") {
                        return value_error("artifact byte count collision");
                    }
                }
                self.artifacts.insert(artifact_id, payload.clone());
            }
            "SealCreated" => {
                let root = require_id(get_str(payload, "root")?)?.to_string();
                let seal_artifact = require_id(get_str(payload, "seal_artifact")?)?.to_string();
                match self.seal_artifacts.get(&root) {
                    Some(previous) if previous != &seal_artifact => {
                        return value_error("seal root collision")
                    }
                    Some(_) => {}
                    None => {
                        self.seal_count += 1;
                        self.seal_artifacts.insert(root, seal_artifact);
                    }
                }
            }
            "RunCreated" => {
                self.runs.insert(
                    get_str(payload, "run_id")?.to_string(),
                    get_str(payload, "lab")?.to_string(),
                );
            }
            "FactRecorded" => {
                let fact_id = require_id(get_str(payload, "fact_id")?)?.to_string();
                let fact = without(payload, &["fact_id"]);
                if validated_fact(&fact, &self.artifacts, &self.runs)? != *payload {
                    return value_error("invalid custody fact in journal");
                }
                if let Some(previous) = self.facts.get(&fact_id) {
                    if previous != payload {
                        return value_error("fact identity collision");
                    }
                    return Ok(());
                }
                self.facts_by_run
                    .entry(get_str(payload, "run_id")?.to_string())
                    .or_default()
                    .push(fact_id.clone());
                self.facts.insert(fact_id, payload.clone());
            }
            _ => {}
        }
        Ok(())
    }

    pub fn run_lab(&self, run_id: &str) -> Option<&str> {
        self.runs.get(run_id).map(String::as_str)
    }
}
