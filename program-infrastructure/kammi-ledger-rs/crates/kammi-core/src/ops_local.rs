//! Ledger-authorized local execution (`local_execution.py`, `local_api.py`).

use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use kammi_jcs::{canonical, Sha256Hasher, Value};

use crate::error::{io_error, value_error, LedgerError, Result};
use crate::json::{get, get_str};
use crate::ledger::Ledger;
use crate::ops_custody::python_path;
use crate::safe::require_id;

pub const MAX_LOCAL_OUTPUT: i64 = 8 * 1024 * 1024 * 1024;
const SPEC_FIELDS: [&str; 12] = [
    "actor_id",
    "command",
    "cwd",
    "expected_outputs",
    "max_output_bytes",
    "output_root",
    "poll_seconds",
    "run_id",
    "schema",
    "source_files",
    "stage_id",
    "timeout_seconds",
];

/// `valid_relative`: a POSIX relative path that cannot escape its root.
pub fn valid_relative(name: &str) -> Result<()> {
    if name.is_empty() || name.contains('\\') || name.contains(':') {
        return value_error("invalid local output name");
    }
    let parts: Vec<&str> = name.split('/').collect();
    // PurePosixPath normalization: str(path) != name catches empty parts and trailing slashes.
    if name.starts_with('/')
        || parts
            .iter()
            .any(|p| p.is_empty() || *p == "." || *p == "..")
    {
        return value_error("local output name escapes its root");
    }
    Ok(())
}

fn is_int(value: &Value) -> bool {
    value.as_i64().is_some() && !value.is_boolean()
}

impl Ledger {
    /// `checked_spec`.
    pub fn checked_spec(&self, run_id: &str, stage_id: &str, actor_id: &str) -> Result<Value> {
        let Some(binding) = self.state.policy.specs.get(&(
            run_id.to_string(),
            stage_id.to_string(),
            "EXECUTION".to_string(),
        )) else {
            return value_error("local execution spec is not bound");
        };
        let spec = self.object_json(get_str(binding, "artifact_id")?)?;
        let map = spec
            .as_object()
            .ok_or_else(|| LedgerError::Value("local execution spec does not match v1".into()))?;
        if map.len() != SPEC_FIELDS.len()
            || !SPEC_FIELDS.iter().all(|k| map.contains_key(*k))
            || map["schema"].as_str() != Some("KAMMI_LOCAL_EXECUTION_V1")
        {
            return value_error("local execution spec does not match v1");
        }
        for (key, value) in [
            ("run_id", run_id),
            ("stage_id", stage_id),
            ("actor_id", actor_id),
        ] {
            if map[key].as_str() != Some(value) {
                return value_error("local execution spec scope differs from authorization");
            }
        }
        if !map["command"].as_array().is_some_and(|c| {
            !c.is_empty() && c.iter().all(|a| a.as_str().is_some_and(|s| !s.is_empty()))
        }) {
            return value_error("local command must be a nonempty argv list");
        }
        let outputs = match map["expected_outputs"].as_array() {
            Some(o) if !o.is_empty() => o,
            _ => return value_error("local output inventory must be nonempty"),
        };
        let unique: BTreeSet<String> = outputs.iter().map(Value::to_string).collect();
        if unique.len() != outputs.len() {
            return value_error("duplicate local output names");
        }
        for name in outputs {
            valid_relative(
                name.as_str()
                    .ok_or_else(|| LedgerError::Value("invalid local output name".into()))?,
            )?;
        }
        if map["source_files"].as_array().is_none_or(|s| s.is_empty()) {
            return value_error("local source inventory must be nonempty");
        }
        let max = &map["max_output_bytes"];
        if !is_int(max) || !(1..=MAX_LOCAL_OUTPUT).contains(&max.as_i64().unwrap()) {
            return value_error("invalid local output cap");
        }
        if !is_int(&map["timeout_seconds"])
            || !(1..=86_400).contains(&map["timeout_seconds"].as_i64().unwrap())
        {
            return value_error("invalid local timeout");
        }
        if !is_int(&map["poll_seconds"])
            || !(1..=10).contains(&map["poll_seconds"].as_i64().unwrap())
        {
            return value_error("invalid local polling interval");
        }
        for key in ["cwd", "output_root"] {
            if !map[key]
                .as_str()
                .is_some_and(|p| Path::new(p).is_absolute())
            {
                return value_error("local path must be absolute");
            }
        }
        if !Path::new(map["cwd"].as_str().unwrap()).is_dir() {
            return value_error("local working directory is unavailable");
        }
        for source in map["source_files"].as_array().unwrap() {
            let keys: BTreeSet<&str> = source
                .as_object()
                .map(|m| m.keys().map(String::as_str).collect())
                .unwrap_or_default();
            if keys != ["bytes", "path", "sha256"].into_iter().collect()
                || !source["path"]
                    .as_str()
                    .is_some_and(|p| Path::new(p).is_absolute())
            {
                return value_error("invalid local source identity");
            }
            if source["bytes"].as_u64().is_none() {
                return value_error("invalid local source size");
            }
            require_id(source["sha256"].as_str().unwrap_or(""))?;
        }
        Ok(spec)
    }

    /// `verify_source_files`.
    pub fn verify_source_files(spec: &Value) -> Result<()> {
        for entry in spec["source_files"].as_array().unwrap() {
            let path = Path::new(entry["path"].as_str().unwrap());
            let meta = std::fs::symlink_metadata(path).ok();
            if !meta.as_ref().is_some_and(|m| m.is_file())
                || meta.unwrap().len() != entry["bytes"].as_u64().unwrap()
            {
                return value_error("local source missing or changed");
            }
            if hash_file(path)? != entry["sha256"].as_str().unwrap() {
                return value_error("local source hash changed");
            }
        }
        Ok(())
    }

    /// `live_local`: every returned capability is current and scoped.
    pub fn live_local(&self, body: &Value, launch: bool) -> Result<Value> {
        let (actor, run, stage) = (
            get_str(body, "actor_id")?,
            get_str(body, "run_id")?,
            get_str(body, "stage_id")?,
        );
        let (resource, lease) = (get_str(body, "resource_id")?, get_str(body, "lease_id")?);
        let fence = get(body, "fencing_token")?;
        if !self.flight_open() {
            return value_error("Library acceptance is not current");
        }
        if !self.authorization_valid(get_str(body, "authorization_id")?, actor, run, stage)? {
            return value_error("stage authorization is stale");
        }
        let now = self.now();
        let grant = match self.state.policy.current_policy_hash(stage) {
            Some(policy) => self.state.authority.matching_grant(
                actor,
                "execute_local",
                run,
                stage,
                policy,
                now,
            )?,
            None => None,
        };
        if grant.is_none() {
            return value_error("execute_local grant missing or stale");
        }
        let record = self.state.leases.leases.get(lease);
        let registered = self.state.leases.resources.get(resource);
        let (Some(record), Some(registered)) = (record, registered) else {
            return value_error("local lease does not belong to stage");
        };
        if record.get("stage_id").and_then(Value::as_str) != Some(stage) {
            return value_error("local lease does not belong to stage");
        }
        let kind = registered.get("kind").and_then(Value::as_str);
        if !matches!(kind, Some("GPU" | "CPU_POOL"))
            || !self.state.leases.valid(
                lease,
                resource,
                fence.as_i64().unwrap_or(i64::MIN),
                actor,
                run,
                now,
            )?
        {
            return value_error("local lease fence is stale");
        }
        let spec = self.checked_spec(run, stage, actor)?;
        if launch {
            Self::verify_source_files(&spec)?;
        }
        Ok(spec)
    }

    /// Step one of `import_local_output`, under the writer lock: resolves and bounds the file.
    pub fn prepare_local_output(&self, body: &Value) -> Result<LocalOutputPlan> {
        let name = get_str(body, "relative_path")?;
        valid_relative(name)?;
        let expected = require_id(get_str(body, "expected_sha256")?)?.to_string();
        let request_id = get_str(body, "request_id")?;
        let spec = self.live_local(body, false)?;
        if !spec["expected_outputs"]
            .as_array()
            .unwrap()
            .iter()
            .any(|o| o.as_str() == Some(name))
        {
            return value_error("output is not declared by execution spec");
        }
        if let Some(prior) = self.prior(request_id)? {
            if prior.event["type"] != "ArtifactRegistered"
                || prior.payload["artifact_id"].as_str() != Some(expected.as_str())
            {
                return value_error("output import request ID reused");
            }
            return Ok(LocalOutputPlan::Done {
                artifact_id: expected,
                event_id: prior.event_id,
            });
        }
        let root = std::fs::canonicalize(spec["output_root"].as_str().unwrap())
            .map_err(io_error(spec["output_root"].as_str().unwrap()))?;
        let path = name.split('/').fold(root.clone(), |p, part| p.join(part));
        let resolved = std::fs::canonicalize(&path).map_err(io_error(&path))?;
        let is_link = std::fs::symlink_metadata(&path)
            .map(|m| m.file_type().is_symlink())
            .unwrap_or(true);
        if !resolved.starts_with(&root) || is_link || !resolved.is_file() {
            return value_error("output path is not an ordinary file inside bound root");
        }
        let size = std::fs::metadata(&resolved)
            .map_err(io_error(&resolved))?
            .len();
        if size as i64 > spec["max_output_bytes"].as_i64().unwrap() {
            return value_error("local output exceeds bound cap");
        }
        Ok(LocalOutputPlan::Copy {
            expected,
            spec,
            path,
            resolved,
        })
    }

    /// Step three of `import_local_output`: rechecks the binding and commits with a guard.
    pub fn commit_local_output(
        &mut self,
        body: &Value,
        spec: &Value,
        path: &Path,
        resolved: &Path,
        identity: &str,
        size: u64,
    ) -> Result<String> {
        let current = self.live_local(body, false)?;
        if &current != spec || std::fs::canonicalize(path).map_err(io_error(path))? != resolved {
            return value_error("local output binding changed during import");
        }
        let payload = crate::obj! {
            "artifact_id" => identity, "byte_count" => size,
            "kind" => get_str(body, "kind")?, "media_type" => "application/octet-stream",
            "schema_id" => "raw-v1", "source_location" => python_path(resolved),
        };
        let b = body.clone();
        let guard = move |ledger: &Ledger| -> Result<bool> {
            Ok(ledger.authorization_valid(
                get_str(&b, "authorization_id")?,
                get_str(&b, "actor_id")?,
                get_str(&b, "run_id")?,
                get_str(&b, "stage_id")?,
            )? && ledger.state.leases.valid(
                get_str(&b, "lease_id")?,
                get_str(&b, "resource_id")?,
                b["fencing_token"].as_i64().unwrap_or(i64::MIN),
                get_str(&b, "actor_id")?,
                get_str(&b, "run_id")?,
                ledger.now(),
            )?)
        };
        self.emit(
            "ArtifactRegistered",
            payload,
            get_str(body, "actor_id")?,
            get_str(body, "request_id")?,
            Some(&guard),
        )
    }

    /// `/v1/local/contact`.
    pub fn local_contact(&mut self, body: &Value) -> Result<String> {
        self.live_local(body, false)?;
        let attempt_id = get_str(body, "attempt_id")?;
        let attempt = self.state.lifecycle.attempts.get(attempt_id);
        let current = attempt.is_some_and(|a| {
            a.get("state").and_then(Value::as_str) == Some("RUNNING")
                && ["actor_id", "run_id", "stage_id"]
                    .iter()
                    .all(|k| a.get(*k) == body.get(*k))
        });
        if !current {
            return value_error("contact attempt is not current");
        }
        let (run, stage, actor, request) = (
            get_str(body, "run_id")?.to_string(),
            get_str(body, "stage_id")?.to_string(),
            get_str(body, "actor_id")?.to_string(),
            get_str(body, "request_id")?.to_string(),
        );
        self.record_contact(&run, &stage, "MODEL", attempt_id, &actor, &request)
    }

    /// `/v1/local/finish`: returns (receipt_artifact_id, event_id, outcome).
    pub fn local_finish(&mut self, body: &Value) -> Result<(String, String, &'static str)> {
        let receipt = get(body, "result")?;
        let attempt_id = get_str(body, "attempt_id")?;
        let actor = get_str(body, "actor_id")?;
        if !receipt.is_object()
            || receipt.get("attempt_id").and_then(Value::as_str) != Some(attempt_id)
        {
            return value_error("local result does not name the attempt");
        }
        let outcome = match receipt.get("status").and_then(Value::as_str) {
            Some("OUTPUTS_REGISTERED") => "COMPLETE",
            Some("STOPPED") => "STOPPED",
            _ => return value_error("unsupported local result status"),
        };
        let Some(attempt) = self
            .state
            .lifecycle
            .attempts
            .get(attempt_id)
            .cloned()
            .filter(|a| a.get("actor_id").and_then(Value::as_str) == Some(actor))
        else {
            return value_error("unknown local attempt or actor");
        };
        if outcome == "COMPLETE" {
            let spec = self.checked_spec(
                get_str(&attempt, "run_id")?,
                get_str(&attempt, "stage_id")?,
                actor,
            )?;
            let outputs = receipt
                .get("outputs")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            let named: BTreeSet<String> = outputs.keys().cloned().collect();
            let expected: BTreeSet<String> = spec["expected_outputs"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(|o| o.as_str().map(str::to_string))
                .collect();
            if named != expected {
                return value_error("local result omits declared outputs");
            }
            for item in outputs.values() {
                let id = item
                    .get("artifact_id")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !self.state.artifacts.contains_key(id) || !self.cas_verify(id) {
                    return value_error("local output is not registered and verified");
                }
            }
        }
        let request_id = get_str(body, "request_id")?.to_string();
        let (identity, _) = self.register_bytes(
            &canonical(receipt)?,
            "local-execution-receipt",
            actor,
            &format!("{request_id}:receipt"),
        )?;
        let reason = receipt
            .get("stop_reason")
            .and_then(Value::as_str)
            .unwrap_or("outputs_registered")
            .to_string();
        let actor = actor.to_string();
        let event = self.finish_attempt(
            attempt_id,
            &actor,
            outcome,
            &identity,
            &reason,
            &format!("{request_id}:finish"),
        )?;
        Ok((identity, event, outcome))
    }
}

/// What `prepare_local_output` decided.
pub enum LocalOutputPlan {
    /// The request was already committed.
    Done {
        artifact_id: String,
        event_id: String,
    },
    /// Hash and copy `resolved` outside the lock, then commit.
    Copy {
        expected: String,
        spec: Value,
        path: PathBuf,
        resolved: PathBuf,
    },
}

pub fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).map_err(io_error(path))?;
    let mut hasher = Sha256Hasher::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = file.read(&mut buffer).map_err(io_error(path))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher.finish().to_string())
}
