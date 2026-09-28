//! Leases, guarded exposure, stage authorization and live gate checks
//! (`core.py`, `gate_ops.py`, `surface_api.py:/v1/policy/check`).

use kammi_jcs::{raw_id, Value};

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get, get_str, merged, without};
use crate::ledger::Ledger;
use crate::rules::{evaluate, failed_reasons};
use crate::safe::is_safe;
use crate::state::PURPOSES;
use crate::time::parse_utc;

/// Outcome of a panel open: bytes only when opened.
pub struct PanelOpen {
    pub data: Option<Vec<u8>>,
    pub event_id: String,
    pub receipt: Value,
}

impl Ledger {
    fn active_policy(&self, stage_id: &str) -> Result<Option<Value>> {
        match self.state.policy.policies.get(stage_id) {
            Some(registration) => Ok(Some(
                self.object_json(get_str(registration, "artifact_id")?)?,
            )),
            None => Ok(None),
        }
    }

    /// `GateOperations.authorization_valid`: re-validates an issued authorization at the
    /// moment it is consumed.
    pub fn authorization_valid(
        &self,
        identity: &str,
        actor_id: &str,
        run_id: &str,
        stage_id: &str,
    ) -> Result<bool> {
        let now = self.now();
        if !self
            .state
            .policy
            .authorization_valid(identity, actor_id, run_id, stage_id, now)?
        {
            return Ok(false);
        }
        if self.state.authority.actor_lab(actor_id) != self.state.run_lab(run_id) {
            return Ok(false);
        }
        let Some(policy) = self.active_policy(stage_id)? else {
            return Ok(false);
        };
        if policy["forbids"]
            .get("eval_panel_opened")
            .and_then(Value::as_bool)
            == Some(true)
        {
            let exposures = &self.state.policy.exposures;
            let run = |e: &&Value| e.get("run_id").and_then(Value::as_str) == Some(run_id);
            let matching = exposures
                .iter()
                .filter(run)
                .filter(|e| e.get("authorization_id").and_then(Value::as_str) == Some(identity))
                .count();
            let unrelated = exposures
                .iter()
                .filter(run)
                .filter(|e| e.get("authorization_id").and_then(Value::as_str) != Some(identity))
                .count();
            // Consume exactly the first panel opening authorized by this stage.
            if unrelated > 0 || matching > 1 {
                return Ok(false);
            }
        }
        let gpu = self
            .state
            .leases
            .gpu_lease_valid(stage_id, actor_id, run_id, now)?;
        let evaluation = evaluate(
            &policy,
            &self.state.policy,
            &self.state.authority,
            run_id,
            actor_id,
            stage_id,
            gpu,
            Some(identity),
            now,
        )?;
        Ok(evaluation.decision == "AUTHORIZED")
    }

    #[allow(clippy::too_many_arguments)]
    pub fn acquire_lease(
        &mut self,
        resource_id: &str,
        run_id: &str,
        stage_id: &str,
        actor_id: &str,
        actor_token: &str,
        purpose: &str,
        ttl_seconds: &Value,
        request_id: &str,
    ) -> Result<(String, Value)> {
        let ttl = match ttl_seconds.as_i64() {
            Some(t) if (1..=3600).contains(&t) => t,
            _ => return value_error("lease TTL must be 1..3600 seconds"),
        };
        if !is_safe(stage_id) || !is_safe(purpose) {
            return value_error("invalid lease stage or purpose");
        }
        let Some(resource) = self.state.leases.resources.get(resource_id).cloned() else {
            return value_error("unknown resource or run");
        };
        if !self.state.runs.contains_key(run_id) {
            return value_error("unknown resource or run");
        }
        if !self
            .state
            .authority
            .verify_credential(actor_id, actor_token)
        {
            return value_error("actor credential mismatch");
        }
        if let Some((kind, receipt)) = self.state.leases.by_request.get(request_id).cloned() {
            for (key, value) in [
                ("resource_id", resource_id),
                ("run_id", run_id),
                ("stage_id", stage_id),
                ("actor_id", actor_id),
                ("purpose", purpose),
            ] {
                if receipt.get(key).and_then(Value::as_str) != Some(value) {
                    return value_error("lease request ID reused with changed scope");
                }
            }
            if receipt.get("requested_ttl_seconds").and_then(Value::as_i64) != Some(ttl) {
                return value_error("lease request ID reused with changed TTL");
            }
            let suffix = if kind == "LeaseGranted" {
                ":granted"
            } else {
                ":denied"
            };
            let prior = self
                .prior(&format!("{request_id}{suffix}"))?
                .ok_or_else(|| LedgerError::Key(format!("{request_id}{suffix}")))?;
            return Ok((prior.event_id, receipt));
        }
        let now = self.now();
        let base = crate::obj! {
            "request_id" => request_id, "resource_id" => resource_id,
            "run_id" => run_id, "stage_id" => stage_id,
            "actor_id" => actor_id, "purpose" => purpose,
            "requested_ttl_seconds" => ttl,
        };
        let reason = if self.has_request(&format!("{request_id}:requested"))? {
            "incomplete_prior_lease_request"
        } else {
            self.emit(
                "LeaseRequested",
                base.clone(),
                actor_id,
                &format!("{request_id}:requested"),
                None,
            )?;
            if let Some(old_id) = self.state.leases.active.get(resource_id).cloned() {
                let old = self.state.leases.leases[&old_id].clone();
                if old
                    .get("expires_utc")
                    .and_then(Value::as_str)
                    .is_some_and(|e| !e.is_empty())
                    && parse_utc(get_str(&old, "expires_utc")?)? <= now
                {
                    let expired = crate::obj! {"lease_id" => old_id.clone(), "resource_id" => resource_id, "fencing_token" => old["fencing_token"].clone()};
                    self.emit(
                        "LeaseExpired",
                        expired,
                        "ledgerd",
                        &format!("{request_id}:expire-old"),
                        None,
                    )?;
                }
            }
            let policy_hash = self
                .state
                .policy
                .current_policy_hash(stage_id)
                .map(str::to_string);
            let credential = self
                .state
                .authority
                .verify_credential(actor_id, actor_token);
            let grant = match &policy_hash {
                Some(hash) => self.state.authority.matching_grant(
                    actor_id,
                    "acquire_lease",
                    run_id,
                    stage_id,
                    hash,
                    now,
                )?,
                None => None,
            };
            let qualified = credential
                && self.state.authority.actors.contains_key(actor_id)
                && self.state.authority.actor_lab(actor_id) == self.state.run_lab(run_id)
                && grant.is_some();
            if !qualified {
                "unauthorized"
            } else if self.state.leases.active.contains_key(resource_id) {
                "occupied"
            } else {
                "granted"
            }
        };
        if reason != "granted" {
            let receipt = merged(
                &base,
                crate::obj! {"decision" => "DENIED", "reason" => reason},
            );
            let event = self.emit(
                "LeaseDenied",
                receipt.clone(),
                actor_id,
                &format!("{request_id}:denied"),
                None,
            )?;
            return Ok((event, receipt));
        }
        let token = self
            .state
            .leases
            .fencing
            .get(resource_id)
            .copied()
            .unwrap_or(0)
            + 1;
        let lease_id = format!(
            "lease-{}",
            &raw_id(format!("{resource_id}\0{request_id}").as_bytes()).to_string()[7..]
        );
        let receipt = merged(
            &base,
            crate::obj! {
                "decision" => "GRANTED", "lease_id" => lease_id, "fencing_token" => token,
                "issued_utc" => now.isoformat(),
                "expires_utc" => now.plus_seconds(ttl).isoformat(),
                "runtime_constraints" => resource["constraints"].clone(),
            },
        );
        let event = self.emit(
            "LeaseGranted",
            receipt.clone(),
            actor_id,
            &format!("{request_id}:granted"),
            None,
        )?;
        Ok((event, receipt))
    }

    fn lease_record(&self, lease_id: &str, actor_id: &str, actor_token: &str) -> Result<Value> {
        match self.state.leases.leases.get(lease_id) {
            Some(lease)
                if self
                    .state
                    .authority
                    .verify_credential(actor_id, actor_token) =>
            {
                Ok(lease.clone())
            }
            _ => value_error("unknown lease or invalid actor credential"),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn renew_lease(
        &mut self,
        lease_id: &str,
        fencing_token: &Value,
        actor_id: &str,
        actor_token: &str,
        ttl_seconds: &Value,
        request_id: &str,
    ) -> Result<String> {
        let ttl = match ttl_seconds.as_i64() {
            Some(t) if (1..=3600).contains(&t) => t,
            _ => return value_error("lease TTL must be 1..3600 seconds"),
        };
        let lease = self.lease_record(lease_id, actor_id, actor_token)?;
        if let Some(prior) = self.prior(request_id)? {
            let r = &prior.payload;
            if prior.event["type"] != "LeaseRenewed"
                || r.get("lease_id").and_then(Value::as_str) != Some(lease_id)
                || r.get("fencing_token") != Some(fencing_token)
                || r.get("actor_id").and_then(Value::as_str) != Some(actor_id)
                || r.get("requested_ttl_seconds").and_then(Value::as_i64) != Some(ttl)
            {
                return value_error("lease renewal request ID reused");
            }
            return Ok(prior.event_id);
        }
        let now = self.now();
        let token = fencing_token.as_i64().unwrap_or(i64::MIN);
        if !self.state.leases.valid(
            lease_id,
            get_str(&lease, "resource_id")?,
            token,
            actor_id,
            get_str(&lease, "run_id")?,
            now,
        )? {
            return value_error("stale or expired lease");
        }
        let payload = crate::obj! {
            "lease_id" => lease_id, "resource_id" => lease["resource_id"].clone(),
            "fencing_token" => fencing_token.clone(), "actor_id" => actor_id,
            "expires_utc" => now.plus_seconds(ttl).isoformat(),
            "requested_ttl_seconds" => ttl,
        };
        self.emit("LeaseRenewed", payload, actor_id, request_id, None)
    }

    pub fn release_lease(
        &mut self,
        lease_id: &str,
        fencing_token: &Value,
        actor_id: &str,
        actor_token: &str,
        request_id: &str,
    ) -> Result<String> {
        let lease = self.lease_record(lease_id, actor_id, actor_token)?;
        if let Some(prior) = self.prior(request_id)? {
            let r = &prior.payload;
            if prior.event["type"] != "LeaseReleased"
                || r.get("lease_id").and_then(Value::as_str) != Some(lease_id)
                || r.get("fencing_token") != Some(fencing_token)
                || r.get("actor_id").and_then(Value::as_str) != Some(actor_id)
            {
                return value_error("lease release request ID reused");
            }
            return Ok(prior.event_id);
        }
        let token = fencing_token.as_i64().unwrap_or(i64::MIN);
        if !self.state.leases.valid(
            lease_id,
            get_str(&lease, "resource_id")?,
            token,
            actor_id,
            get_str(&lease, "run_id")?,
            self.now(),
        )? {
            return value_error("stale or expired lease");
        }
        let payload = crate::obj! {
            "lease_id" => lease_id, "resource_id" => lease["resource_id"].clone(),
            "fencing_token" => fencing_token.clone(), "actor_id" => actor_id,
        };
        self.emit("LeaseReleased", payload, actor_id, request_id, None)
    }

    pub fn lease_validate(
        &self,
        lease_id: &str,
        resource_id: &str,
        fencing_token: &Value,
        actor_id: &str,
        run_id: &str,
    ) -> Result<bool> {
        let token = fencing_token
            .as_i64()
            .ok_or_else(|| LedgerError::Type("fencing_token must be an integer".into()))?;
        self.state
            .leases
            .valid(lease_id, resource_id, token, actor_id, run_id, self.now())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn open_panel(
        &mut self,
        panel_id: &str,
        purpose: &str,
        run_id: &str,
        stage_id: &str,
        actor_id: &str,
        actor_token: &str,
        authorization_id: &str,
        request_id: &str,
    ) -> Result<PanelOpen> {
        if !PURPOSES.contains(&purpose) || !is_safe(stage_id) {
            return value_error("invalid purpose or stage");
        }
        let Some(panel) = self.state.exposure.panels.get(panel_id).cloned() else {
            return value_error("unknown panel or run");
        };
        if !self.state.runs.contains_key(run_id) {
            return value_error("unknown panel or run");
        }
        if !self
            .state
            .authority
            .verify_credential(actor_id, actor_token)
        {
            return value_error("actor credential mismatch");
        }
        let panel_artifact = get_str(&panel, "artifact_id")?.to_string();
        if let Some((kind, receipt)) = self.state.exposure.by_request.get(request_id).cloned() {
            let final_key = format!(
                "{request_id}{}",
                if kind == "ExposureOpened" {
                    ":opened"
                } else {
                    ":denied"
                }
            );
            let event_id = self
                .prior(&final_key)?
                .ok_or_else(|| LedgerError::Key(final_key.clone()))?
                .event_id;
            for (key, value) in [
                ("panel_id", panel_id),
                ("purpose", purpose),
                ("run_id", run_id),
                ("stage_id", stage_id),
                ("actor_id", actor_id),
                ("authorization_id", authorization_id),
            ] {
                if receipt.get(key).and_then(Value::as_str) != Some(value) {
                    return value_error("exposure request ID reused with different scope");
                }
            }
            if kind == "ExposureOpened"
                && !self.authorization_valid(authorization_id, actor_id, run_id, stage_id)?
            {
                return value_error("exposure retry authorization is stale");
            }
            let data = if kind == "ExposureOpened" {
                Some(self.object_bytes(&panel_artifact)?)
            } else {
                None
            };
            if kind == "ExposureOpened" && !self.has_request(&format!("{request_id}:closed"))? {
                let base = without(&receipt, &["decision", "reason", "count"]);
                let closed = merged(&base, crate::obj! {"opened_event" => event_id.clone()});
                self.emit(
                    "ExposureClosed",
                    closed,
                    actor_id,
                    &format!("{request_id}:closed"),
                    None,
                )?;
            }
            return Ok(PanelOpen {
                data,
                event_id,
                receipt,
            });
        }
        let base = crate::obj! {
            "request_id" => request_id, "panel_id" => panel_id,
            "artifact_id" => panel_artifact.clone(), "purpose" => purpose,
            "run_id" => run_id, "lab" => panel["lab"].clone(),
            "stage_id" => stage_id, "actor_id" => actor_id,
            "authorization_id" => authorization_id,
            "decision_context" => "guarded_panel_gateway",
        };
        let reason = if self.has_request(&format!("{request_id}:requested"))? {
            "incomplete_prior_exposure_request"
        } else {
            self.emit(
                "ExposureRequested",
                base.clone(),
                actor_id,
                &format!("{request_id}:requested"),
                None,
            )?;
            let now = self.now();
            let current_policy = self
                .state
                .policy
                .current_policy_hash(stage_id)
                .map(str::to_string);
            let one_panel_limit = match self.active_policy(stage_id)? {
                Some(policy) => policy["forbids"]
                    .get("eval_panel_opened")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                None => false,
            };
            let prior_run_open = self
                .state
                .exposure
                .opened
                .iter()
                .any(|e| e.get("run_id").and_then(Value::as_str) == Some(run_id));
            let credential = self
                .state
                .authority
                .verify_credential(actor_id, actor_token);
            let grant = match &current_policy {
                Some(hash) => self.state.authority.matching_grant(
                    actor_id,
                    "open_panel",
                    run_id,
                    stage_id,
                    hash,
                    now,
                )?,
                None => None,
            };
            let panel_lab = panel.get("lab").and_then(Value::as_str);
            let qualified = credential
                && self.state.authority.actors.contains_key(actor_id)
                && self.state.authority.actor_lab(actor_id) == panel_lab
                && panel_lab == self.state.run_lab(run_id)
                && grant.is_some()
                && self.authorization_valid(authorization_id, actor_id, run_id, stage_id)?
                && !(one_panel_limit && prior_run_open);
            if qualified {
                "authorized"
            } else if one_panel_limit && prior_run_open {
                "eval_panel_already_opened"
            } else {
                "panel_access_not_authorized"
            }
        };
        let opened = reason == "authorized";
        let receipt = merged(
            &base,
            crate::obj! {"decision" => if opened { "OPENED" } else { "DENIED" }, "reason" => reason, "count" => i64::from(opened)},
        );
        if !opened {
            let event_id = self.emit(
                "ExposureDenied",
                receipt.clone(),
                actor_id,
                &format!("{request_id}:denied"),
                None,
            )?;
            return Ok(PanelOpen {
                data: None,
                event_id,
                receipt,
            });
        }
        // The event is durably committed before the panel bytes are read or returned.
        let event_id = self.emit(
            "ExposureOpened",
            receipt.clone(),
            actor_id,
            &format!("{request_id}:opened"),
            None,
        )?;
        let data = self.object_bytes(&panel_artifact)?;
        let closed = merged(&base, crate::obj! {"opened_event" => event_id.clone()});
        self.emit(
            "ExposureClosed",
            closed,
            actor_id,
            &format!("{request_id}:closed"),
            None,
        )?;
        Ok(PanelOpen {
            data: Some(data),
            event_id,
            receipt,
        })
    }

    pub fn authorize_stage(
        &mut self,
        run_id: &str,
        stage_id: &str,
        actor_id: &str,
        expires_utc: &str,
        request_id: &str,
    ) -> Result<(String, Value)> {
        if !self.state.runs.contains_key(run_id) {
            return value_error("unknown run");
        }
        if !is_safe(stage_id) {
            return value_error("invalid stage");
        }
        let expires = parse_utc(expires_utc)?;
        if expires <= self.now() {
            return value_error("authorization expiry must be in the future");
        }
        let final_request = format!("{request_id}:final");
        if let Some(prior) = self.prior(&final_request)? {
            let r = &prior.payload;
            for (key, value) in [
                ("actor_id", actor_id),
                ("run_id", run_id),
                ("stage_id", stage_id),
                ("expires_utc", expires_utc),
            ] {
                if r.get(key).and_then(Value::as_str) != Some(value) {
                    return value_error("authorization request ID reused with changed scope");
                }
            }
            return Ok((prior.event_id, prior.payload));
        }
        let Some(current) = self.state.policy.policies.get(stage_id).cloned() else {
            return value_error("no registered stage policy");
        };
        let policy = self.object_json(get_str(&current, "artifact_id")?)?;
        let now = self.now();
        let gpu_lease_valid = self
            .state
            .leases
            .gpu_lease_valid(stage_id, actor_id, run_id, now)?;
        let evidence_head = self.store.main.head().to_string();
        let version = get_str(&policy, "version")?.to_string();
        let (decision, checks, grant) = if self.has_request(&format!("{request_id}:evaluated"))? {
            (
                "DENIED",
                vec![crate::obj! {"predicate" => "incomplete_prior_evaluation", "pass" => false}],
                None,
            )
        } else {
            let evaluation = evaluate(
                &policy,
                &self.state.policy,
                &self.state.authority,
                run_id,
                actor_id,
                stage_id,
                gpu_lease_valid,
                None,
                now,
            )?;
            let mut decision = evaluation.decision;
            let mut checks = evaluation.checks;
            let lab_matches = self.state.authority.actor_lab(actor_id).is_some()
                && self.state.authority.actor_lab(actor_id) == self.state.run_lab(run_id);
            checks.push(crate::obj! {"predicate" => "actor_lab_owns_run", "pass" => lab_matches});
            if !lab_matches {
                decision = "DENIED";
            }
            if let Some(grant) = &evaluation.grant {
                let grant_expiry =
                    parse_utc(get_str(&self.state.authority.grants[grant], "expires_utc")?)?;
                if expires > grant_expiry {
                    decision = "DENIED";
                    checks.push(crate::obj! {"predicate" => "authorization_expiry_within_grant", "pass" => false});
                }
            }
            let evaluated = crate::obj! {
                "request_id" => request_id, "actor_id" => actor_id,
                "run_id" => run_id, "stage_id" => stage_id,
                "policy_id" => format!("{stage_id}:{version}"),
                "policy_version" => version.clone(),
                "policy_hash" => current["policy_hash"].clone(),
                "evidence_head" => evidence_head.clone(),
                "prerequisites" => checks.clone(),
                "decision" => decision,
                "reasons" => failed_reasons(&checks),
                "evaluated_utc" => self.now().isoformat(),
            };
            self.emit(
                "PolicyEvaluated",
                evaluated,
                actor_id,
                &format!("{request_id}:evaluated"),
                None,
            )?;
            (decision, checks, evaluation.grant)
        };
        let receipt = crate::obj! {
            "request_id" => request_id, "actor_id" => actor_id,
            "run_id" => run_id, "stage_id" => stage_id,
            "policy_id" => format!("{stage_id}:{version}"),
            "policy_version" => version,
            "policy_hash" => current["policy_hash"].clone(),
            "evidence_head" => evidence_head,
            "prerequisites" => checks.clone(),
            "decision" => decision,
            "reasons" => failed_reasons(&checks),
            "grant_id" => grant.map_or(Value::Null, Value::from),
            "spec_bindings" => self.state.policy.binding_snapshot(run_id, stage_id),
            "expires_utc" => expires_utc,
            "decided_utc" => self.now().isoformat(),
        };
        let kind = if decision == "AUTHORIZED" {
            "AuthorizationIssued"
        } else {
            "AuthorizationDenied"
        };
        let event = self.emit(kind, receipt.clone(), actor_id, &final_request, None)?;
        Ok((event, receipt))
    }

    /// `/v1/policy/check`: a recorded evaluation that confers no authority.
    pub fn policy_check(
        &mut self,
        actor_id: &str,
        run_id: &str,
        stage_id: &str,
        request_id: &str,
    ) -> Result<(String, Value)> {
        if let Some(prior) = self.prior(request_id)? {
            let r = &prior.payload;
            if prior.event["type"] != "PolicyEvaluated"
                || [
                    ("actor_id", actor_id),
                    ("run_id", run_id),
                    ("stage_id", stage_id),
                ]
                .iter()
                .any(|(k, v)| r.get(*k).and_then(Value::as_str) != Some(*v))
            {
                return value_error("policy request ID reused");
            }
            return Ok((prior.event_id, prior.payload));
        }
        let current = self
            .state
            .policy
            .policies
            .get(stage_id)
            .cloned()
            .ok_or_else(|| LedgerError::Key(stage_id.to_string()))?;
        let policy = self.object_json(get_str(&current, "artifact_id")?)?;
        let now = self.now();
        let live_gpu = self
            .state
            .leases
            .gpu_lease_valid(stage_id, actor_id, run_id, now)?;
        let evaluation = evaluate(
            &policy,
            &self.state.policy,
            &self.state.authority,
            run_id,
            actor_id,
            stage_id,
            live_gpu,
            None,
            now,
        )?;
        let version = get(&policy, "version")?.clone();
        let receipt = crate::obj! {
            "request_id" => request_id, "actor_id" => actor_id, "run_id" => run_id,
            "stage_id" => stage_id, "policy_id" => format!("{stage_id}:{}", version.as_str().unwrap_or("")),
            "policy_hash" => current["policy_hash"].clone(), "policy_version" => version,
            "evidence_head" => self.store.main.head().to_string(), "decision" => evaluation.decision,
            "prerequisites" => evaluation.checks.clone(), "reasons" => failed_reasons(&evaluation.checks),
            "authority_conferred" => false, "grant_id" => evaluation.grant.map_or(Value::Null, Value::from),
        };
        let event = self.emit(
            "PolicyEvaluated",
            receipt.clone(),
            actor_id,
            request_id,
            None,
        )?;
        Ok((event, receipt))
    }
}
