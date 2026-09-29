//! Custody operations (`core.py`, `file_intake.py`, `release.py:accept_library`).

use std::path::Path;

use kammi_jcs::{canonical, typed_id, Domain, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get, get_str};
use crate::ledger::Ledger;
use crate::rules::{builtin, implementation_hash, summarize, validate_policy};
use crate::safe::{is_id, is_safe, require_id};
use crate::state::{validated_fact, ACTIONS, ACTOR_KINDS, RESOURCE_KINDS};
use crate::time::parse_utc;

pub const MAX_LOCAL_IMPORT_BYTES: u64 = 8 * 1024 * 1024 * 1024;

/// Pre-v4 acceptance gates. This remains the profile until the first v4 activation event.
pub const GATES: [&str; 32] = [
    "artifact_tamper",
    "journal_tamper",
    "db_deletion_rebuild",
    "crash_recovery",
    "windows_durability_characterization",
    "backup_restore",
    "single_writer_fencing",
    "actor_authorization",
    "policy_engine",
    "exposure_enforcement",
    "resource_leases",
    "stale_fencing_rejection",
    "adapter_registry",
    "failure_history_queries",
    "contact_evidence_scope",
    "remote_execution",
    "remote_tamper_replay",
    "memory_plane",
    "fts_retrieval",
    "vector_retrieval",
    "graph_retrieval",
    "memory_custody_trace",
    "mcp_interface",
    "python_sdk",
    "rust_sdk",
    "e4_legacy_reconstruction",
    "cleanroom_replay",
    "phoenix_vault",
    "v1_import_parity",
    "shadow_zero_diff",
    "projector_isolation",
    "export_v1_rollback",
];

/// Post-v4 profile retires the Python export rollback proof and adds the four one-way
/// activation proofs. The old acceptance remains historical; the next acceptance after the
/// activation event must use this profile.
pub const GATES_V4: [&str; 35] = [
    "artifact_tamper",
    "journal_tamper",
    "db_deletion_rebuild",
    "crash_recovery",
    "windows_durability_characterization",
    "backup_restore",
    "single_writer_fencing",
    "actor_authorization",
    "policy_engine",
    "exposure_enforcement",
    "resource_leases",
    "stale_fencing_rejection",
    "adapter_registry",
    "failure_history_queries",
    "contact_evidence_scope",
    "remote_execution",
    "remote_tamper_replay",
    "memory_plane",
    "fts_retrieval",
    "vector_retrieval",
    "graph_retrieval",
    "memory_custody_trace",
    "mcp_interface",
    "python_sdk",
    "rust_sdk",
    "e4_legacy_reconstruction",
    "cleanroom_replay",
    "phoenix_vault",
    "v1_import_parity",
    "shadow_zero_diff",
    "projector_isolation",
    "rust_independent_verifier",
    "v4_replay_identity",
    "resume_gate",
    "activation_rehearsal",
];

pub fn acceptance_gates(vocabulary_v4: bool) -> &'static [&'static str] {
    if vocabulary_v4 {
        &GATES_V4
    } else {
        &GATES
    }
}

impl Ledger {
    fn artifact_payload(
        &self,
        id: &str,
        size: u64,
        kind: &str,
        media_type: &str,
        schema_id: &str,
        location: &str,
    ) -> Value {
        crate::obj! {
            "artifact_id" => id,
            "byte_count" => size,
            "kind" => kind,
            "media_type" => media_type,
            "schema_id" => schema_id,
            "source_location" => location,
        }
    }

    /// `register_bytes`.
    pub fn register_bytes(
        &mut self,
        data: &[u8],
        kind: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        let (id, size) = self.put_bytes(data)?;
        let payload = self.artifact_payload(
            &id,
            size,
            kind,
            "application/octet-stream",
            "raw-v1",
            "api-upload",
        );
        let event = self.emit("ArtifactRegistered", payload, actor, request_id, None)?;
        Ok((id, event))
    }

    /// `register_file`.
    pub fn register_file(
        &mut self,
        source: &Path,
        kind: &str,
        media_type: &str,
        schema_id: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        let (id, size) = self.put_file(source)?;
        let location = std::fs::canonicalize(source).map_err(crate::error::io_error(source))?;
        let payload = self.artifact_payload(
            &id,
            size,
            kind,
            media_type,
            schema_id,
            &python_path(&location),
        );
        let event = self.emit("ArtifactRegistered", payload, actor, request_id, None)?;
        Ok((id, event))
    }

    /// `file_intake.import_local_artifact`: returns (artifact_id, event_id, byte_count).
    pub fn import_local_artifact(&mut self, body: &Value) -> Result<(String, String, u64)> {
        let expected = require_id(get_str(body, "expected_sha256")?)?.to_string();
        let expected_bytes = get(body, "expected_bytes")?;
        let expected_bytes = match expected_bytes.as_u64() {
            Some(n) if n <= MAX_LOCAL_IMPORT_BYTES => n,
            _ => return value_error("invalid local artifact size"),
        };
        for key in ["kind", "actor", "request_id"] {
            if !get(body, key)?.as_str().is_some_and(is_safe) {
                return value_error("invalid local artifact identity fields");
            }
        }
        let source = Path::new(get_str(body, "path")?);
        let meta = std::fs::symlink_metadata(source).ok();
        if !source.is_absolute() || !meta.as_ref().is_some_and(|m| m.is_file()) {
            return value_error("local artifact must be an absolute ordinary file");
        }
        if meta.unwrap().len() != expected_bytes {
            return value_error("local artifact size differs from declared identity");
        }
        let resolved = std::fs::canonicalize(source).map_err(crate::error::io_error(source))?;
        let (id, size) = self.put_file(&resolved)?;
        if id != expected || size != expected_bytes {
            return value_error("local artifact bytes differ from declared identity");
        }
        let payload = self.artifact_payload(
            &id,
            size,
            get_str(body, "kind")?,
            "application/octet-stream",
            "raw-v1",
            &python_path(&resolved),
        );
        let event = self.emit(
            "ArtifactRegistered",
            payload,
            get_str(body, "actor")?,
            get_str(body, "request_id")?,
            None,
        )?;
        Ok((id, event, size))
    }

    pub fn create_run(
        &mut self,
        run_id: &str,
        lab: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(run_id) || !is_safe(lab) {
            return value_error("invalid run or lab ID");
        }
        if self.state.runs.contains_key(run_id) && !self.has_request(request_id)? {
            return value_error("run already exists");
        }
        self.emit(
            "RunCreated",
            crate::obj! {"run_id" => run_id, "lab" => lab},
            actor,
            request_id,
            None,
        )
    }

    pub fn register_actor(
        &mut self,
        actor_id: &str,
        kind: &str,
        lab: &str,
        credential_sha256: &str,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(actor_id) || !is_safe(lab) {
            return value_error("invalid actor/lab ID");
        }
        if !ACTOR_KINDS.contains(&kind) {
            return value_error("unknown actor kind");
        }
        if credential_sha256.len() != 64
            || !credential_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return value_error("invalid credential digest");
        }
        if self.state.authority.actors.contains_key(actor_id) && !self.has_request(request_id)? {
            return value_error("actor already registered");
        }
        let payload = crate::obj! {"actor_id" => actor_id, "kind" => kind, "lab" => lab, "credential_sha256" => credential_sha256};
        self.emit("ActorRegistered", payload, "ledger-admin", request_id, None)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn issue_grant(
        &mut self,
        grant_id: &str,
        actor_id: &str,
        action: &str,
        run_id: &str,
        stage_id: &str,
        policy_hash: &str,
        expires_utc: &str,
        request_id: &str,
    ) -> Result<String> {
        for value in [grant_id, actor_id, run_id, stage_id] {
            if !is_safe(value) {
                return value_error("invalid grant scope");
            }
        }
        if !ACTIONS.contains(&action) {
            return value_error("unknown grant action");
        }
        require_id(policy_hash)?;
        if parse_utc(expires_utc)? <= self.now() {
            return value_error("grant must expire in the future");
        }
        let Some(actor_lab) = self.state.authority.actor_lab(actor_id).map(str::to_string) else {
            return value_error("grant actor is unregistered");
        };
        if let Some(run_lab) = self.state.run_lab(run_id) {
            if run_lab != actor_lab {
                return value_error("grant actor belongs to another lab");
            }
        }
        if self.state.authority.grants.contains_key(grant_id) && !self.has_request(request_id)? {
            return value_error("grant already exists");
        }
        let payload = crate::obj! {
            "grant_id" => grant_id, "actor_id" => actor_id, "action" => action,
            "run_id" => run_id, "stage_id" => stage_id,
            "policy_hash" => policy_hash, "expires_utc" => expires_utc,
        };
        self.emit("GrantIssued", payload, "ledger-admin", request_id, None)
    }

    pub fn register_panel(
        &mut self,
        panel_id: &str,
        artifact_id: &str,
        lab: &str,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(panel_id) || !is_safe(lab) {
            return value_error("invalid panel ID or lab");
        }
        require_id(artifact_id)?;
        if !self.state.artifacts.contains_key(artifact_id) {
            return value_error("panel bytes must be registered first");
        }
        if self.state.exposure.panels.contains_key(panel_id) && !self.has_request(request_id)? {
            return value_error("panel already registered");
        }
        let payload =
            crate::obj! {"panel_id" => panel_id, "artifact_id" => artifact_id, "lab" => lab};
        self.emit("PanelRegistered", payload, "ledger-admin", request_id, None)
    }

    pub fn register_resource(
        &mut self,
        resource_id: &str,
        kind: &str,
        host: &str,
        constraints: &Value,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(resource_id) || !is_safe(host) {
            return value_error("invalid resource ID or host");
        }
        if !RESOURCE_KINDS.contains(&kind) {
            return value_error("unsupported resource kind");
        }
        let valid = constraints.as_object().is_some_and(|map| {
            map.iter()
                .all(|(k, v)| is_safe(k) && v.as_str().is_some_and(|s| s.chars().count() <= 160))
        });
        if !valid {
            return value_error("invalid resource constraints");
        }
        if self.state.leases.resources.contains_key(resource_id) && !self.has_request(request_id)? {
            return value_error("resource already registered");
        }
        let payload = crate::obj! {"resource_id" => resource_id, "kind" => kind, "host" => host, "constraints" => constraints.clone()};
        self.emit(
            "ResourceRegistered",
            payload,
            "ledger-admin",
            request_id,
            None,
        )
    }

    pub fn register_adapter(
        &mut self,
        adapter_id: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        let Some(item) = builtin(adapter_id) else {
            return value_error("unknown built-in adapter");
        };
        let (source_id, _) = self.register_bytes(
            item.source,
            "adapter-implementation",
            "ledger-admin",
            &format!("{request_id}:source"),
        )?;
        let expected = implementation_hash(&item);
        if source_id != expected {
            return value_error("adapter source hash mismatch");
        }
        let payload = crate::obj! {
            "adapter_id" => adapter_id,
            "source_schema" => item.source_schema,
            "target_schema" => item.target_schema,
            "implementation_hash" => expected,
            "implementation_artifact" => source_id.clone(),
            "version" => item.version,
        };
        let event = self.emit(
            "AdapterRegistered",
            payload,
            "ledger-admin",
            &format!("{request_id}:registered"),
            None,
        )?;
        Ok((source_id, event))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn apply_adapter(
        &mut self,
        adapter_id: &str,
        source_artifact: &str,
        actor_id: &str,
        actor_token: &str,
        run_id: &str,
        stage_id: &str,
        authorization_id: &str,
        purpose: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        if !is_safe(purpose) {
            return value_error("invalid adapter purpose");
        }
        let Some(registered) = self.state.adapters.registered.get(adapter_id).cloned() else {
            return value_error("adapter or source artifact is unregistered");
        };
        if !self.state.artifacts.contains_key(source_artifact) {
            return value_error("adapter or source artifact is unregistered");
        }
        let now = self.now();
        let policy_hash = self
            .state
            .policy
            .current_policy_hash(stage_id)
            .map(str::to_string);
        let allowed = self
            .state
            .authority
            .verify_credential(actor_id, actor_token)
            && self.state.authority.actor_lab(actor_id) == self.state.run_lab(run_id)
            && match &policy_hash {
                Some(hash) => self
                    .state
                    .authority
                    .matching_grant(actor_id, "apply_adapter", run_id, stage_id, hash, now)?
                    .is_some(),
                None => false,
            }
            && self.authorization_valid(authorization_id, actor_id, run_id, stage_id)?;
        if !allowed {
            return value_error("adapter application lacks scoped authorization");
        }
        let item = builtin(adapter_id).ok_or_else(|| LedgerError::Key(adapter_id.to_string()))?;
        if registered["implementation_hash"].as_str() != Some(implementation_hash(&item).as_str()) {
            return value_error("adapter implementation drift");
        }
        let converted = (item.function)(&self.object_bytes(source_artifact)?)?;
        let (derived, _) = self.register_bytes(
            &converted,
            "adapter-derived-view",
            actor_id,
            &format!("{request_id}:derived"),
        )?;
        let payload = crate::obj! {
            "adapter_id" => adapter_id,
            "source_artifact_id" => source_artifact,
            "derived_view_id" => derived.clone(),
            "implementation_hash" => registered["implementation_hash"].clone(),
            "source_schema" => registered["source_schema"].clone(),
            "target_schema" => registered["target_schema"].clone(),
            "purpose" => purpose,
            "run_id" => run_id, "stage_id" => stage_id,
            "authorization_id" => authorization_id,
        };
        let event = self.emit(
            "AdapterApplied",
            payload,
            actor_id,
            &format!("{request_id}:applied"),
            None,
        )?;
        Ok((derived, event))
    }

    pub fn register_policy(
        &mut self,
        policy: &Value,
        request_id: &str,
    ) -> Result<(String, String)> {
        validate_policy(policy)?;
        let (artifact_id, _) = self.register_bytes(
            &canonical(policy)?,
            "stage-policy",
            "ledger-admin",
            &format!("{request_id}:artifact"),
        )?;
        let payload = crate::obj! {
            "stage_id" => policy["stage_id"].clone(), "version" => policy["version"].clone(),
            "policy_hash" => artifact_id.clone(), "artifact_id" => artifact_id.clone(),
        };
        let event = self.emit(
            "PolicyRegistered",
            payload,
            "ledger-admin",
            &format!("{request_id}:policy"),
            None,
        )?;
        Ok((artifact_id, event))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn bind_spec(
        &mut self,
        run_id: &str,
        stage_id: &str,
        spec_kind: &str,
        artifact_id: &str,
        seal_root: &str,
        actor_id: &str,
        request_id: &str,
    ) -> Result<String> {
        if !matches!(spec_kind, "SCIENTIFIC" | "EXECUTION") {
            return value_error("unsupported spec kind");
        }
        if !is_safe(stage_id) || !self.state.runs.contains_key(run_id) {
            return value_error("unknown run or invalid stage");
        }
        if !self.state.artifacts.contains_key(artifact_id)
            || !self
                .verify_seal(seal_root)?
                .iter()
                .any(|m| m == artifact_id)
        {
            return value_error("spec is not in verified seal");
        }
        let payload = crate::obj! {
            "run_id" => run_id, "stage_id" => stage_id, "spec_kind" => spec_kind,
            "artifact_id" => artifact_id, "seal_root" => seal_root, "status" => "SEALED",
        };
        self.emit("SpecBound", payload, actor_id, request_id, None)
    }

    pub fn record_seal_verification(
        &mut self,
        run_id: &str,
        stage_id: &str,
        root: &str,
        actor_id: &str,
        request_id: &str,
    ) -> Result<String> {
        if !self.state.runs.contains_key(run_id) || !is_safe(stage_id) {
            return value_error("unknown run or invalid stage");
        }
        let closure = self.verify_seal(root)?;
        let payload = crate::obj! {"run_id" => run_id, "stage_id" => stage_id, "root" => root, "closure_count" => closure.len()};
        self.emit("SealVerified", payload, actor_id, request_id, None)
    }

    pub fn record_contact(
        &mut self,
        run_id: &str,
        stage_id: &str,
        contact_class: &str,
        target: &str,
        actor_id: &str,
        request_id: &str,
    ) -> Result<String> {
        const ALLOWED: [&str; 8] = [
            "POPULATION_GENERATED",
            "TOKENIZER",
            "MODEL",
            "CUDA",
            "TRUTH_LABEL",
            "EVAL_PANEL",
            "SCORING",
            "HUMAN_INSPECTION",
        ];
        if !ALLOWED.contains(&contact_class) || !self.state.runs.contains_key(run_id) {
            return value_error("invalid contact class or run");
        }
        if !is_safe(stage_id) || !is_safe(target) {
            return value_error("invalid contact scope");
        }
        let payload = crate::obj! {"run_id" => run_id, "stage_id" => stage_id, "contact_class" => contact_class, "target" => target};
        self.emit("ContactRecorded", payload, actor_id, request_id, None)
    }

    pub fn record_fact(
        &mut self,
        fact: &Value,
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        let payload = validated_fact(fact, &self.state.artifacts, &self.state.runs)?;
        let fact_id = payload["fact_id"].as_str().unwrap().to_string();
        if self.state.facts.contains_key(&fact_id) && !self.has_request(request_id)? {
            return value_error("fact already recorded");
        }
        let event = self.emit("FactRecorded", payload, actor, request_id, None)?;
        Ok((fact_id, event))
    }

    /// Facts of a run ordered like the Python projection query (`kind, subject, id`), shaped
    /// like `graph.history`.
    pub fn history(&self, run_id: &str) -> Result<Vec<Value>> {
        if !self.state.runs.contains_key(run_id) {
            return value_error("unknown run");
        }
        let mut facts: Vec<&Value> = self
            .state
            .facts_by_run
            .get(run_id)
            .map(|ids| ids.iter().map(|id| &self.state.facts[id]).collect())
            .unwrap_or_default();
        let key = |f: &Value, k: &str| f.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        facts.sort_by_key(|a| (key(a, "kind"), key(a, "subject"), key(a, "fact_id")));
        Ok(facts
            .into_iter()
            .map(|f| {
                crate::obj! {
                    "fact_id" => f["fact_id"].clone(), "kind" => f["kind"].clone(),
                    "subject" => f["subject"].clone(), "object" => f["object"].clone(),
                    "value" => f["value"].clone(), "evidence_artifact" => f["evidence_artifact"].clone(),
                    "scope" => f["scope"].clone(),
                }
            })
            .collect())
    }

    pub fn history_summary(&self, run_id: &str) -> Result<Value> {
        summarize(&self.history(run_id)?)
    }

    pub fn create_seal(
        &mut self,
        members: &[String],
        parents: &[String],
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        for member in members {
            if !self.state.artifacts.contains_key(member) || !self.cas_verify(member) {
                return value_error(format!("unregistered or corrupt member: {member}"));
            }
        }
        for parent in parents {
            if !self.state.seal_artifacts.contains_key(parent) {
                return value_error(format!("unknown parent seal: {parent}"));
            }
            self.verify_seal(parent)?;
        }
        let (seal, root) = make_seal(members, parents)?;
        let (seal_artifact, _) = self.put_bytes(&canonical(&seal)?)?;
        if let Some(existing) = self.state.seal_artifacts.get(&root) {
            if !self.has_request(request_id)? {
                if existing != &seal_artifact {
                    return value_error("seal identity collision");
                }
                return value_error("seal already exists; use its existing root");
            }
        }
        let payload = crate::obj! {
            "root" => root.clone(), "seal_artifact" => seal_artifact,
            "direct_members" => seal["direct_members"].clone(), "parents" => seal["parents"].clone(),
        };
        let event = self.emit("SealCreated", payload, actor, request_id, None)?;
        Ok((root, event))
    }

    /// `seals.verify_lineage`: the sorted transitive data members of a seal.
    pub fn verify_seal(&self, root: &str) -> Result<Vec<String>> {
        let mut closure = std::collections::BTreeSet::new();
        let mut visited = std::collections::HashSet::new();
        let mut visiting = std::collections::HashSet::new();
        let mut stack = vec![(root.to_string(), false)];
        while let Some((current, closing)) = stack.pop() {
            if closing {
                visiting.remove(&current);
                visited.insert(current);
                continue;
            }
            require_id(&current)?;
            if visiting.contains(&current) {
                return value_error("seal ancestry cycle");
            }
            if visited.contains(&current) {
                continue;
            }
            visiting.insert(current.clone());
            let Some(artifact) = self.state.seal_artifacts.get(&current) else {
                return value_error(format!("unknown seal: {current}"));
            };
            let payload = self.object_json(artifact)?;
            if payload.get("schema").and_then(Value::as_str) != Some("KAMMI_SEAL_V1") {
                return value_error("unsupported seal schema");
            }
            let members = crate::json::string_list(&payload, "direct_members")?;
            let parents = crate::json::string_list(&payload, "parents")?;
            let (expected, calculated) = make_seal(&members, &parents)?;
            if expected != payload || calculated != current {
                return value_error("seal root mismatch");
            }
            for member in &members {
                if !closure.contains(member) && !self.cas_verify(member) {
                    return value_error(format!("missing or corrupt artifact: {member}"));
                }
                closure.insert(member.clone());
            }
            stack.push((current, true));
            for parent in parents.iter().rev() {
                stack.push((parent.clone(), false));
            }
        }
        Ok(closure.into_iter().collect())
    }

    /// `release.accept_library` against this build's identities.
    pub fn accept_library(
        &mut self,
        acceptance: &Value,
        request_id: &str,
    ) -> Result<(String, String)> {
        let required_gates = acceptance_gates(self.vocabulary_v4_active());
        let gates = acceptance.get("gates").and_then(Value::as_object);
        let gate_names: std::collections::BTreeSet<&str> = gates
            .map(|g| g.keys().map(String::as_str).collect())
            .unwrap_or_default();
        let expected: std::collections::BTreeSet<&str> = required_gates.iter().copied().collect();
        if acceptance.get("schema").and_then(Value::as_str) != Some("LibraryAcceptanceV2")
            || gate_names != expected
        {
            return value_error("acceptance gate schema mismatch");
        }
        if gates.unwrap().values().any(|v| v.as_str() != Some("PASS")) {
            return value_error("all acceptance gates must pass");
        }
        let flight = self.flight.clone();
        if get_str(acceptance, "architecture_hash")? != flight.architecture
            || get_str(acceptance, "source_root")? != flight.source_root
            || get_str(acceptance, "runtime_identity")? != flight.runtime_identity
        {
            return value_error("acceptance does not bind current architecture/source/runtime");
        }
        for field in ["acceptance_suite_root", "independent_verification_root"] {
            let id = get_str(acceptance, field)?;
            if !self.state.artifacts.contains_key(id) || !self.cas_verify(id) {
                return value_error("acceptance evidence is not registered and verified");
            }
        }
        let suite = self.object_json(get_str(acceptance, "acceptance_suite_root")?)?;
        let audit = self.object_json(get_str(acceptance, "independent_verification_root")?)?;
        for (report, schema) in [
            (&suite, "KAMMI_ENDSTATE_ACCEPTANCE_V1"),
            (&audit, "KAMMI_ENDSTATE_INDEPENDENT_AUDIT_V1"),
        ] {
            if report.get("schema").and_then(Value::as_str) != Some(schema)
                || report.get("status").and_then(Value::as_str) != Some("PASS")
                || report.get("source_root").and_then(Value::as_str)
                    != Some(flight.source_root.as_str())
                || report.get("runtime_identity").and_then(Value::as_str)
                    != Some(flight.runtime_identity.as_str())
            {
                return value_error("acceptance evidence schema/status/identity mismatch");
            }
        }
        if audit.get("acceptance_suite_root") != acceptance.get("acceptance_suite_root") {
            return value_error("independent audit does not bind acceptance suite");
        }
        let suite_gates = suite.get("gates").and_then(Value::as_object);
        let suite_names: std::collections::BTreeSet<&str> = suite_gates
            .map(|g| g.keys().map(String::as_str).collect())
            .unwrap_or_default();
        if suite_names != expected {
            return value_error("suite does not demonstrate every gate");
        }
        for (gate, proof) in suite_gates.unwrap() {
            let evidence = proof.get("evidence").and_then(Value::as_array);
            if proof.get("status").and_then(Value::as_str) != Some("PASS")
                || evidence.is_none_or(|e| e.is_empty())
            {
                return value_error(format!("gate lacks passing evidence: {gate}"));
            }
            for identity in evidence.unwrap() {
                let id = identity.as_str().unwrap_or("");
                if !self.state.artifacts.contains_key(id) || !self.cas_verify(id) {
                    return value_error(format!("gate evidence is unavailable: {gate}"));
                }
            }
        }
        let (artifact, _) = self.register_bytes(
            &canonical(acceptance)?,
            "library-acceptance",
            "library-auditor",
            &format!("{request_id}:artifact"),
        )?;
        let payload = crate::obj! {"acceptance_artifact" => artifact.clone(), "source_root" => flight.source_root, "runtime_identity" => flight.runtime_identity};
        let event = self.emit(
            "LibraryAccepted",
            payload,
            "library-auditor",
            &format!("{request_id}:accepted"),
            None,
        )?;
        Ok((artifact, event))
    }

    /// Checks a caller-supplied object is a registered artifact (helper for routes).
    pub fn is_registered_artifact(&self, id: &str) -> bool {
        is_id(id) && self.state.artifacts.contains_key(id)
    }
}

#[cfg(test)]
mod acceptance_gate_tests {
    use super::{acceptance_gates, GATES, GATES_V4};
    use std::collections::BTreeSet;

    #[test]
    fn activation_switches_to_the_post_v4_gate_profile() {
        let pre_v4 = acceptance_gates(false);
        let post_v4 = acceptance_gates(true);
        assert_eq!(pre_v4.len(), 32);
        assert_eq!(post_v4.len(), 35);
        assert!(pre_v4.contains(&"export_v1_rollback"));
        assert!(!post_v4.contains(&"export_v1_rollback"));
        for gate in [
            "rust_independent_verifier",
            "v4_replay_identity",
            "resume_gate",
            "activation_rehearsal",
        ] {
            assert!(post_v4.contains(&gate));
        }
        assert_eq!(GATES.len(), 32);
        assert_eq!(GATES_V4.len(), 35);
        assert_eq!(post_v4.iter().copied().collect::<BTreeSet<_>>().len(), 35);
    }
}

/// `seals.make_seal`: sorted members/parents, duplicates refused, root over the payload.
pub fn make_seal(members: &[String], parents: &[String]) -> Result<(Value, String)> {
    for identity in members.iter().chain(parents) {
        require_id(identity)?;
    }
    let unique = |items: &[String]| {
        items.iter().collect::<std::collections::HashSet<_>>().len() == items.len()
    };
    if !unique(members) || !unique(parents) {
        return value_error("duplicate seal member or parent");
    }
    let mut members = members.to_vec();
    let mut parents = parents.to_vec();
    members.sort();
    parents.sort();
    let payload = crate::obj! {"schema" => "KAMMI_SEAL_V1", "direct_members" => members, "parents" => parents};
    let root = typed_id(Domain::Seal, &payload)?.to_string();
    Ok((payload, root))
}

/// Python `str(Path.resolve())` on Windows: no `\\?\` verbatim prefix.
pub fn python_path(path: &Path) -> String {
    let text = path.to_string_lossy().into_owned();
    match text.strip_prefix(r"\\?\UNC\") {
        Some(rest) => format!(r"\\{rest}"),
        None => text
            .strip_prefix(r"\\?\")
            .map(str::to_string)
            .unwrap_or(text),
    }
}
