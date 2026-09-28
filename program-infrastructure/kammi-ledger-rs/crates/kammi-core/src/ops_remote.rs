//! Signed remote bundles, worker returns (`remote_ops.py`) and attempt lifecycle
//! (`lifecycle.py`).

use std::collections::{BTreeMap, BTreeSet, HashSet};

use kammi_jcs::{canonical, raw_id, strict_json, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get, get_str};
use crate::ledger::Ledger;
use crate::rules::{from_hex, hex, key_id, sign, validate_bundle, validated_signed_json};
use crate::safe::is_safe;

impl Ledger {
    pub fn remote_input_allowed(
        &self,
        artifact_id: &str,
        actor_id: &str,
        run_id: &str,
        stage_id: &str,
    ) -> bool {
        let protected = self
            .state
            .exposure
            .panels
            .values()
            .any(|p| p.get("artifact_id").and_then(Value::as_str) == Some(artifact_id));
        !protected
            || self.state.exposure.opened.iter().any(|e| {
                let f = |k: &str| e.get(k).and_then(Value::as_str);
                f("artifact_id") == Some(artifact_id)
                    && f("actor_id") == Some(actor_id)
                    && f("run_id") == Some(run_id)
                    && f("stage_id") == Some(stage_id)
            })
    }

    fn bundle_lease_valid(&self, bundle: &Value, actor_id: &str) -> Result<bool> {
        if bundle["lease_id"].is_null() {
            return Ok(true);
        }
        self.state.leases.valid(
            get_str(bundle, "lease_id")?,
            get_str(bundle, "lease_resource_id")?,
            bundle["fencing_token"].as_i64().unwrap_or(i64::MIN),
            actor_id,
            get_str(bundle, "run_id")?,
            self.now(),
        )
    }

    pub fn remote_worker_started(
        &mut self,
        bundle_id: &str,
        worker_actor_id: &str,
        worker_token: &str,
        request_id: &str,
    ) -> Result<String> {
        let Some(record) = self.state.remote.bundles.get(bundle_id).cloned() else {
            return value_error("unknown bundle or invalid worker credential");
        };
        if !self
            .state
            .authority
            .verify_credential(worker_actor_id, worker_token)
        {
            return value_error("unknown bundle or invalid worker credential");
        }
        let bundle = self.object_json(bundle_id)?;
        let producer = get_str(&record, "actor_id")?.to_string();
        if get_str(&bundle, "worker_actor_id")? != worker_actor_id
            || !self.authorization_valid(
                get_str(&bundle, "authorization_id")?,
                &producer,
                get_str(&bundle, "run_id")?,
                get_str(&bundle, "stage_id")?,
            )?
        {
            return value_error("worker start lacks current authorization");
        }
        if !self.bundle_lease_valid(&bundle, &producer)? {
            return value_error("worker start lease is stale");
        }
        let payload = crate::obj! {"bundle_artifact_id" => bundle_id, "worker_actor_id" => worker_actor_id, "run_id" => bundle["run_id"].clone()};
        self.emit(
            "RemoteWorkerStarted",
            payload,
            worker_actor_id,
            request_id,
            None,
        )
    }

    pub fn register_worker_key(
        &mut self,
        worker_actor_id: &str,
        public_key_hex: &str,
        request_id: &str,
    ) -> Result<String> {
        let is_worker = self
            .state
            .authority
            .actors
            .get(worker_actor_id)
            .and_then(|a| a.get("kind"))
            .and_then(Value::as_str)
            == Some("remote_worker");
        if !is_worker {
            return value_error("worker actor must be registered as remote_worker");
        }
        let public = from_hex(public_key_hex)
            .map_err(|_| LedgerError::Value("invalid worker public key".into()))?;
        let payload = crate::obj! {"worker_actor_id" => worker_actor_id, "public_key_hex" => public_key_hex, "key_id" => key_id(&public)?};
        self.emit(
            "WorkerKeyRegistered",
            payload,
            "ledger-admin",
            request_id,
            None,
        )
    }

    pub fn create_remote_bundle(
        &mut self,
        bundle: &Value,
        actor_id: &str,
        actor_token: &str,
        request_id: &str,
    ) -> Result<(String, Value)> {
        validate_bundle(bundle)?;
        let Some(signing) = self.signing.clone() else {
            return value_error("daemon signing key not configured");
        };
        let run_id = get_str(bundle, "run_id")?;
        let stage_id = get_str(bundle, "stage_id")?;
        let lab = get_str(bundle, "lab")?;
        let now = self.now();
        let current_policy = self
            .state
            .policy
            .current_policy_hash(stage_id)
            .map(str::to_string);
        let allowed = self.state.runs.get(run_id).map(String::as_str) == Some(lab)
            && self
                .state
                .authority
                .verify_credential(actor_id, actor_token)
            && self.state.authority.actor_lab(actor_id) == Some(lab)
            && match &current_policy {
                Some(hash) => self
                    .state
                    .authority
                    .matching_grant(actor_id, "execute_bundle", run_id, stage_id, hash, now)?
                    .is_some(),
                None => false,
            }
            && self.authorization_valid(
                get_str(bundle, "authorization_id")?,
                actor_id,
                run_id,
                stage_id,
            )?;
        if !allowed {
            return value_error("remote bundle lacks scoped authorization");
        }
        let worker = get_str(bundle, "worker_actor_id")?;
        if !self.state.remote.worker_keys.contains_key(worker) {
            return value_error("remote worker key is not registered");
        }
        if self.state.authority.actor_lab(worker) != Some(lab) {
            return value_error("remote worker belongs to another lab");
        }
        for (name, kind) in [
            ("scientific_spec", "SCIENTIFIC"),
            ("execution_spec", "EXECUTION"),
        ] {
            let bound = self.state.policy.specs.get(&(
                run_id.to_string(),
                stage_id.to_string(),
                kind.to_string(),
            ));
            if bound.and_then(|b| b.get("artifact_id")) != Some(&bundle[name]) {
                return value_error("remote bundle spec identity mismatch");
            }
        }
        let mut closure = HashSet::new();
        for root in crate::json::string_list(bundle, "input_roots")? {
            closure.extend(self.verify_seal(&root)?);
        }
        let inputs = crate::json::string_list(bundle, "input_artifacts")?;
        if !inputs.iter().all(|i| closure.contains(i)) {
            return value_error("remote input is outside sealed roots");
        }
        if inputs
            .iter()
            .any(|i| !self.remote_input_allowed(i, actor_id, run_id, stage_id))
        {
            return value_error("protected remote input requires guarded exposure first");
        }
        if !self
            .state
            .artifacts
            .contains_key(get_str(bundle, "environment_lock")?)
        {
            return value_error("remote environment lock unregistered");
        }
        if !bundle["lease_id"].is_null() {
            if !self.bundle_lease_valid(bundle, actor_id)? {
                return value_error("remote bundle lease is stale");
            }
            let lease = &self.state.leases.leases[get_str(bundle, "lease_id")?];
            if lease.get("stage_id").and_then(Value::as_str) != Some(stage_id) {
                return value_error("remote bundle lease stage mismatch");
            }
        }
        let raw = canonical(bundle)?;
        let (bundle_id, _) = self.register_bytes(
            &raw,
            "remote-run-bundle",
            actor_id,
            &format!("{request_id}:bundle"),
        )?;
        let public = signing.verifying_key().to_bytes();
        let payload = crate::obj! {
            "bundle_artifact_id" => bundle_id, "run_id" => run_id,
            "stage_id" => stage_id, "actor_id" => actor_id,
            "signature_hex" => sign(&signing, &raw),
            "issuer_public_hex" => hex(&public), "issuer_key_id" => key_id(&public)?,
        };
        let event = self.emit(
            "RemoteBundleCreated",
            payload.clone(),
            actor_id,
            &format!("{request_id}:created"),
            None,
        )?;
        Ok((event, payload))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn accept_remote_return(
        &mut self,
        bundle_id: &str,
        receipt_raw: &[u8],
        receipt_signature: &str,
        worker_actor_id: &str,
        worker_token: &str,
        outputs: &BTreeMap<String, Vec<u8>>,
        stdout: &[u8],
        stderr: &[u8],
        request_id: &str,
    ) -> Result<(String, Value)> {
        let bundle_record = self.state.remote.bundles.get(bundle_id).cloned();
        let public_hex = self.state.remote.worker_keys.get(worker_actor_id).cloned();
        let (Some(bundle_record), Some(public_hex)) = (bundle_record, public_hex) else {
            return value_error("unknown bundle or worker key");
        };
        if !self
            .state
            .authority
            .verify_credential(worker_actor_id, worker_token)
        {
            return value_error("worker credential mismatch");
        }
        let receipt =
            validated_signed_json(receipt_raw, receipt_signature, &from_hex(&public_hex)?)?;
        let bundle = strict_json(&self.object_bytes(bundle_id)?)?;
        validate_bundle(&bundle)?;
        if receipt.get("schema").and_then(Value::as_str) != Some("KAMMI_REMOTE_RETURN_V1")
            || receipt.get("bundle_artifact_id").and_then(Value::as_str) != Some(bundle_id)
            || receipt.get("run_id") != bundle.get("run_id")
        {
            return value_error("remote receipt bundle identity mismatch");
        }
        if Some(worker_actor_id) != bundle["worker_actor_id"].as_str() {
            return value_error("wrong worker returned bundle");
        }
        if receipt.get("exit_code").and_then(Value::as_i64) != Some(0)
            || receipt.get("exit_code").and_then(Value::as_bool).is_some()
        {
            return value_error("remote worker exited unsuccessfully");
        }
        let Some(environment) = receipt.get("worker_environment").and_then(Value::as_object) else {
            return value_error("remote environment commit mismatch");
        };
        if environment.get("git_commit") != bundle.get("git_commit") {
            return value_error("remote environment commit mismatch");
        }
        if environment.get("dirty_tree") != Some(&Value::Bool(false)) {
            return value_error("remote return reports dirty tree");
        }
        for category in ["runtime_requirements", "gpu_requirements"] {
            for (key, value) in bundle[category].as_object().unwrap() {
                if environment.get(key) != Some(value) {
                    return value_error("remote environment mismatch");
                }
            }
        }
        let expected: BTreeSet<String> = crate::json::string_list(&bundle, "expected_outputs")?
            .into_iter()
            .collect();
        let declared: BTreeSet<String> = receipt
            .get("outputs")
            .and_then(Value::as_object)
            .map(|m| m.keys().cloned().collect())
            .unwrap_or_default();
        let given: BTreeSet<String> = outputs.keys().cloned().collect();
        if given != expected || declared != given {
            return value_error("remote output declaration mismatch");
        }
        for (name, data) in outputs {
            if receipt["outputs"][name].as_str() != Some(raw_id(data).to_string().as_str()) {
                return value_error("remote output hash mismatch");
            }
        }
        if receipt.get("stdout_artifact_id").and_then(Value::as_str)
            != Some(raw_id(stdout).to_string().as_str())
            || receipt.get("stderr_artifact_id").and_then(Value::as_str)
                != Some(raw_id(stderr).to_string().as_str())
        {
            return value_error("remote stream hash mismatch");
        }
        if let Some(existing) = self.state.remote.returns.get(bundle_id).cloned() {
            if existing.get("receipt_artifact_id").and_then(Value::as_str)
                != Some(raw_id(receipt_raw).to_string().as_str())
            {
                return value_error("remote bundle already has a different return");
            }
            return Ok((self.state.remote.return_events[bundle_id].clone(), existing));
        }
        let producer = get_str(&bundle_record, "actor_id")?.to_string();
        let (authorization_id, run_id, stage_id) = (
            get_str(&bundle, "authorization_id")?.to_string(),
            get_str(&bundle, "run_id")?.to_string(),
            get_str(&bundle, "stage_id")?.to_string(),
        );
        if !self.authorization_valid(&authorization_id, &producer, &run_id, &stage_id)? {
            return value_error("remote return authorization is stale");
        }
        if !self.bundle_lease_valid(&bundle, &producer)? {
            return value_error("remote return lease is stale");
        }
        let (receipt_id, _) = self.register_bytes(
            receipt_raw,
            "remote-return-receipt",
            worker_actor_id,
            &format!("{request_id}:receipt"),
        )?;
        let returned = crate::obj! {
            "bundle_artifact_id" => bundle_id, "receipt_artifact_id" => receipt_id.clone(),
            "worker_actor_id" => worker_actor_id, "signature_hex" => receipt_signature,
        };
        self.emit(
            "RemoteWorkerReturned",
            returned,
            worker_actor_id,
            &format!("{request_id}:returned"),
            None,
        )?;
        for (name, data) in outputs {
            self.register_bytes(
                data,
                "remote-output",
                worker_actor_id,
                &format!("{request_id}:output:{name}"),
            )?;
        }
        self.register_bytes(
            stdout,
            "remote-stdout",
            worker_actor_id,
            &format!("{request_id}:stdout"),
        )?;
        self.register_bytes(
            stderr,
            "remote-stderr",
            worker_actor_id,
            &format!("{request_id}:stderr"),
        )?;
        let payload = crate::obj! {
            "bundle_artifact_id" => bundle_id,
            "receipt_artifact_id" => receipt_id,
            "worker_actor_id" => worker_actor_id,
            "outputs" => receipt["outputs"].clone(),
            "stdout_artifact_id" => receipt["stdout_artifact_id"].clone(),
            "stderr_artifact_id" => receipt["stderr_artifact_id"].clone(),
            "status" => "VERIFIED_NOT_HEAD_PROMOTED",
        };
        // Uploading and storing outputs may outlast the lease: recheck at acceptance.
        if !self.authorization_valid(&authorization_id, &producer, &run_id, &stage_id)? {
            return value_error("remote return authorization expired during upload");
        }
        if !self.bundle_lease_valid(&bundle, &producer)? {
            return value_error("remote return lease expired during upload");
        }
        let guard_bundle = bundle.clone();
        let guard = move |ledger: &Ledger| -> Result<bool> {
            Ok(
                ledger.authorization_valid(&authorization_id, &producer, &run_id, &stage_id)?
                    && ledger.bundle_lease_valid(&guard_bundle, &producer)?,
            )
        };
        let event = self.emit(
            "RemoteReceiptVerified",
            payload.clone(),
            "ledgerd",
            &format!("{request_id}:verified"),
            Some(&guard),
        )?;
        Ok((event, payload))
    }

    // -------------------------------------------------------------- lifecycle.py

    pub fn start_attempt(
        &mut self,
        attempt_id: &str,
        run_id: &str,
        stage_id: &str,
        actor_id: &str,
        authorization_id: &str,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(attempt_id)
            || !self.authorization_valid(authorization_id, actor_id, run_id, stage_id)?
        {
            return value_error("attempt lacks current scoped authorization");
        }
        let payload = crate::obj! {
            "attempt_id" => attempt_id, "run_id" => run_id, "stage_id" => stage_id,
            "actor_id" => actor_id, "authorization_id" => authorization_id,
        };
        self.emit("AttemptStarted", payload, actor_id, request_id, None)
    }

    pub fn finish_attempt(
        &mut self,
        attempt_id: &str,
        actor_id: &str,
        outcome: &str,
        evidence_artifact: &str,
        reason: &str,
        request_id: &str,
    ) -> Result<String> {
        if !matches!(outcome, "STOPPED" | "COMPLETE")
            || reason.is_empty()
            || reason.chars().count() > 4096
        {
            return value_error("invalid attempt outcome");
        }
        let attempt = self.state.lifecycle.attempts.get(attempt_id).cloned();
        let Some(attempt) = attempt.filter(|a| {
            a.get("actor_id").and_then(Value::as_str) == Some(actor_id)
                && self.state.artifacts.contains_key(evidence_artifact)
        }) else {
            return value_error("attempt/evidence/actor mismatch");
        };
        if let Some(prior) = self.prior(request_id)? {
            let p = &prior.payload;
            if p.get("attempt_id").and_then(Value::as_str) != Some(attempt_id)
                || p.get("evidence_artifact").and_then(Value::as_str) != Some(evidence_artifact)
                || p.get("reason").and_then(Value::as_str) != Some(reason)
            {
                return value_error("attempt request ID reused");
            }
            return Ok(prior.event_id);
        }
        if attempt.get("state").and_then(Value::as_str) != Some("RUNNING") {
            return value_error("attempt already terminal");
        }
        let payload = crate::obj! {
            "attempt_id" => attempt_id, "run_id" => attempt["run_id"].clone(),
            "stage_id" => attempt["stage_id"].clone(), "actor_id" => actor_id,
            "evidence_artifact" => evidence_artifact, "reason" => reason,
        };
        let kind = if outcome == "STOPPED" {
            "AttemptStopped"
        } else {
            "AttemptCompleted"
        };
        self.emit(kind, payload, actor_id, request_id, None)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn declare_result(
        &mut self,
        run_id: &str,
        stage_id: &str,
        actor_id: &str,
        authorization_id: &str,
        seal_root: &str,
        predecessor: Option<&str>,
        request_id: &str,
    ) -> Result<String> {
        if !self.authorization_valid(authorization_id, actor_id, run_id, stage_id)? {
            return value_error("result lacks current authorization");
        }
        self.verify_seal(seal_root)?;
        let expected = self
            .state
            .lifecycle
            .heads
            .get(&(run_id.to_string(), stage_id.to_string()))
            .and_then(|h| h.get("seal_root"))
            .and_then(Value::as_str)
            .map(str::to_string);
        if !self.has_request(request_id)? && predecessor.map(str::to_string) != expected {
            return value_error("result predecessor is not current head");
        }
        let payload = crate::obj! {
            "run_id" => run_id, "stage_id" => stage_id, "actor_id" => actor_id,
            "authorization_id" => authorization_id, "seal_root" => seal_root,
            "predecessor" => predecessor.map_or(Value::Null, Value::from),
        };
        self.emit("ResultDeclared", payload, actor_id, request_id, None)
    }

    /// A bundle and its envelope for a qualified worker (`qualified_worker`).
    pub fn bundle_for_worker(&self, bundle_id: &str) -> Result<Option<(Value, Vec<u8>)>> {
        let Some(envelope) = self.state.remote.bundles.get(bundle_id).cloned() else {
            return Ok(None);
        };
        let raw = self.object_bytes(bundle_id)?;
        let _ = get(&envelope, "actor_id")?;
        Ok(Some((envelope, raw)))
    }
}
