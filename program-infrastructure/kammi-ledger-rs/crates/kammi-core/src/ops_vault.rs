//! Phoenix vault operations (`vault.py`), portable packages (`vault_portable.py`) and the
//! ZIP64 transport (`vault_archive.py`).

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use kammi_jcs::{canonical, raw_id, strict_json, Sha256Hasher, Sha256Id, Value};

use crate::error::{io_error, value_error, LedgerError, Result};
use crate::json::{get, get_int, get_str};
use crate::ledger::Ledger;
use crate::safe::{is_safe, require_id};
use crate::state::{VaultRecord, Vaults, VAULT_EVENTS};

pub const MAX_SOURCE_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_STREAM_SOURCE_BYTES: u64 = 16 * 1024 * 1024;
pub const MAX_ASSET_BYTES: usize = 10 * 1024 * 1024;
pub const MAX_STREAM_ASSET_BYTES: u64 = 8 * 1024 * 1024 * 1024;
pub const MAX_PACKAGE_BYTES: u64 = 64 * 1024 * 1024 * 1024;
pub const MAX_PACKAGE_FILES: usize = 100_000;

fn object_path(root: &Path, identity: &str) -> Result<PathBuf> {
    let digest = &require_id(identity)?[7..];
    Ok(root
        .join("objects")
        .join("sha256")
        .join(&digest[..2])
        .join(&digest[2..]))
}

impl Ledger {
    pub fn vault(&self, vault_id: &str, actor: &str) -> Result<&VaultRecord> {
        if !is_safe(vault_id) {
            return value_error("invalid vault ID");
        }
        match self.state.vaults.vaults.get(vault_id) {
            Some(vault) if vault.owner == actor => Ok(vault),
            _ => value_error("unknown vault or actor does not own it"),
        }
    }

    pub fn vault_create(
        &mut self,
        vault_id: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<String> {
        if !is_safe(vault_id) {
            return value_error("invalid vault ID");
        }
        let kind = self
            .state
            .authority
            .actors
            .get(actor)
            .and_then(|a| a.get("kind"))
            .and_then(Value::as_str);
        if kind != Some("service") {
            return value_error("vault owner must be a registered service actor");
        }
        if self.state.vaults.vaults.contains_key(vault_id) && !self.has_request(request_id)? {
            return value_error("vault already exists");
        }
        self.emit(
            "VaultCreated",
            crate::obj! {"vault_id" => vault_id, "owner_actor" => actor},
            actor,
            request_id,
            None,
        )
    }

    pub fn vault_commit_source(
        &mut self,
        vault_id: &str,
        source_id: &str,
        base_revision: &Value,
        content: &[u8],
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        if !is_safe(source_id) {
            return value_error("invalid source ID");
        }
        if content.len() > MAX_SOURCE_BYTES {
            return value_error("source exceeds vault limit");
        }
        self.vault(vault_id, actor)?;
        let (id, size) = self.put_bytes(content)?;
        self.vault_commit_source_id(
            vault_id,
            source_id,
            base_revision,
            &id,
            size,
            actor,
            request_id,
        )
    }

    pub fn vault_commit_source_file(
        &mut self,
        vault_id: &str,
        source_id: &str,
        base_revision: &Value,
        source: &Path,
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        if !is_safe(source_id) {
            return value_error("invalid source ID");
        }
        if fs::metadata(source).map_err(io_error(source))?.len() > MAX_STREAM_SOURCE_BYTES {
            return value_error("source exceeds vault stream limit");
        }
        self.vault(vault_id, actor)?;
        let (id, size) = self.put_file(source)?;
        if size > MAX_STREAM_SOURCE_BYTES {
            return value_error("source exceeds vault stream limit");
        }
        self.vault_commit_source_id(
            vault_id,
            source_id,
            base_revision,
            &id,
            size,
            actor,
            request_id,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn vault_commit_source_id(
        &mut self,
        vault_id: &str,
        source_id: &str,
        base_revision: &Value,
        artifact_id: &str,
        size: u64,
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        let vault = self.vault(vault_id, actor)?.clone();
        if let Some(prior) = self.prior(request_id)? {
            let p = &prior.payload;
            if prior.event["type"] != "VaultSourceCommitted"
                || p["vault_id"].as_str() != Some(vault_id)
                || p["source_id"].as_str() != Some(source_id)
                || &p["base_revision"] != base_revision
                || p["artifact_id"].as_str() != Some(artifact_id)
            {
                return value_error("request ID reused for another source commit");
            }
            return Ok((prior.payload, prior.event_id));
        }
        let revision = vault
            .sources
            .get(source_id)
            .and_then(|s| s.get("revision"))
            .and_then(Value::as_i64)
            .unwrap_or(0);
        if base_revision.as_i64() != Some(revision) {
            return value_error("stale source revision");
        }
        let payload = crate::obj! {
            "vault_id" => vault_id, "source_id" => source_id,
            "base_revision" => base_revision.clone(), "revision" => revision + 1,
            "epoch" => vault.epoch + 1, "artifact_id" => artifact_id,
            "byte_count" => size,
        };
        let event = self.emit(
            "VaultSourceCommitted",
            payload.clone(),
            actor,
            request_id,
            None,
        )?;
        Ok((payload, event))
    }

    pub fn vault_stage_asset(
        &mut self,
        vault_id: &str,
        content: &[u8],
        kind: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String)> {
        if content.len() > MAX_ASSET_BYTES || !is_safe(kind) {
            return value_error("invalid vault asset");
        }
        self.vault(vault_id, actor)?;
        self.register_bytes(
            content,
            &format!("phoenix-vault:{vault_id}:{kind}"),
            actor,
            request_id,
        )
    }

    pub fn vault_stage_file(
        &mut self,
        vault_id: &str,
        source: &Path,
        kind: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<(String, String, u64)> {
        if !is_safe(kind) {
            return value_error("invalid vault asset kind");
        }
        self.vault(vault_id, actor)?;
        let (id, size) = self.put_file(source)?;
        if size > MAX_STREAM_ASSET_BYTES {
            return value_error("vault asset exceeds stream limit");
        }
        self.vault(vault_id, actor)?;
        let payload = crate::obj! {
            "artifact_id" => id.clone(), "byte_count" => size,
            "kind" => format!("phoenix-vault:{vault_id}:{kind}"),
            "media_type" => "application/octet-stream", "schema_id" => "raw-v1",
            "source_location" => "vault-stream",
        };
        let event = self.emit("ArtifactRegistered", payload, actor, request_id, None)?;
        Ok((id, event, size))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn vault_select_generation(
        &mut self,
        vault_id: &str,
        source_epoch: &Value,
        generation_id: &Value,
        manifest_artifact_id: &str,
        asset_ids: &Value,
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        let vault = self.vault(vault_id, actor)?.clone();
        if let Some(prior) = self.prior(request_id)? {
            let requested: BTreeSet<String> = asset_ids
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            let expected = crate::obj! {
                "vault_id" => vault_id, "source_epoch" => source_epoch.clone(),
                "generation_id" => generation_id.clone(), "manifest_artifact_id" => manifest_artifact_id,
                "asset_ids" => requested.into_iter().collect::<Vec<_>>(),
            };
            if prior.event["type"] != "VaultGenerationSelected" || prior.payload != expected {
                return value_error("request ID reused for another generation");
            }
            return Ok((prior.payload, prior.event_id));
        }
        if source_epoch.as_i64() != Some(vault.epoch) {
            return value_error("generation source epoch is stale");
        }
        let current = vault
            .generation
            .as_ref()
            .and_then(|g| g.get("generation_id"))
            .and_then(Value::as_i64);
        match generation_id.as_i64() {
            Some(g) if g >= 1 && current.is_none_or(|c| g > c) => {}
            _ => return value_error("generation ID must increase"),
        }
        let items = match asset_ids.as_array() {
            Some(items) if !items.is_empty() && items.len() <= 64 => items,
            _ => return value_error("generation needs bounded asset inventory"),
        };
        let mut ids = BTreeSet::new();
        for item in items {
            ids.insert(require_id(item.as_str().unwrap_or(""))?.to_string());
        }
        let ids: Vec<String> = ids.into_iter().collect();
        require_id(manifest_artifact_id)?;
        for identity in std::iter::once(manifest_artifact_id.to_string()).chain(ids.iter().cloned())
        {
            let Some(artifact) = self.state.artifacts.get(&identity) else {
                return value_error("generation asset is unavailable");
            };
            let kind = artifact
                .get("kind")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            if !self.cas_verify(&identity) {
                return value_error("generation asset is unavailable");
            }
            let scope: Vec<&str> = kind.split(':').take(2).collect();
            if scope != ["phoenix-vault", vault_id] {
                return value_error("generation asset belongs to another scope");
            }
        }
        let manifest = self.object_json(manifest_artifact_id)?;
        let expected = crate::obj! {
            "schema" => "PHOENIX_VAULT_GENERATION_V1", "vault_id" => vault_id,
            "source_epoch" => source_epoch.clone(), "generation_id" => generation_id.clone(),
            "asset_ids" => ids.clone(),
        };
        if manifest != expected {
            return value_error("generation manifest does not bind exact assets and sources");
        }
        let payload = crate::obj! {
            "vault_id" => vault_id, "source_epoch" => source_epoch.clone(),
            "generation_id" => generation_id.clone(),
            "manifest_artifact_id" => manifest_artifact_id, "asset_ids" => ids,
        };
        let event = self.emit(
            "VaultGenerationSelected",
            payload.clone(),
            actor,
            request_id,
            None,
        )?;
        Ok((payload, event))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn vault_set_reader(
        &mut self,
        vault_id: &str,
        source_id: &str,
        revision: &Value,
        offset: &Value,
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        let vault = self.vault(vault_id, actor)?;
        let Some(source) = revision
            .as_i64()
            .and_then(|r| vault.revisions.get(&(source_id.to_string(), r)))
        else {
            return value_error("reader source revision is unavailable");
        };
        let byte_count = source
            .get("byte_count")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        match offset.as_i64() {
            Some(o) if (0..=byte_count).contains(&o) => {}
            _ => return value_error("reader offset is outside source"),
        }
        let payload = crate::obj! {"vault_id" => vault_id, "source_id" => source_id, "revision" => revision.clone(), "offset" => offset.clone()};
        let event = self.emit(
            "VaultReaderPositionSet",
            payload.clone(),
            actor,
            request_id,
            None,
        )?;
        Ok((payload, event))
    }

    pub fn vault_select_product_primary(
        &mut self,
        vault_id: &str,
        source_epoch: &Value,
        receipt_artifact_id: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<(Value, String)> {
        let vault = self.vault(vault_id, actor)?.clone();
        let identity = require_id(receipt_artifact_id)?.to_string();
        let expected_kind = format!("phoenix-vault:{vault_id}:cutover-receipt");
        match self.state.artifacts.get(&identity) {
            Some(a) if a.get("kind").and_then(Value::as_str) == Some(expected_kind.as_str()) => {}
            _ => return value_error("cutover receipt is unavailable or foreign"),
        }
        if !self.cas_verify(&identity) {
            return value_error("cutover receipt is corrupt");
        }
        let record = self.object_json(&identity)?;
        let keys: BTreeSet<&str> = record
            .as_object()
            .map(|m| m.keys().map(String::as_str).collect())
            .unwrap_or_default();
        let expected_keys: BTreeSet<&str> = [
            "schema",
            "vault_id",
            "source_epoch",
            "legacy_snapshot_id",
            "cold_open_root",
        ]
        .into_iter()
        .collect();
        if record.get("schema").and_then(Value::as_str) != Some("PHOENIX_VAULT_CUTOVER_V1")
            || record.get("vault_id").and_then(Value::as_str) != Some(vault_id)
            || record.get("source_epoch") != Some(source_epoch)
            || keys != expected_keys
        {
            return value_error("cutover receipt does not bind vault state");
        }
        require_id(record["legacy_snapshot_id"].as_str().unwrap_or(""))?;
        require_id(record["cold_open_root"].as_str().unwrap_or(""))?;
        let payload = crate::obj! {"vault_id" => vault_id, "source_epoch" => source_epoch.clone(), "receipt_artifact_id" => identity};
        if let Some(prior) = self.prior(request_id)? {
            if prior.event["type"] != "VaultProductPrimarySelected" || prior.payload != payload {
                return value_error("request ID reused for another cutover");
            }
            return Ok((payload, prior.event_id));
        }
        if vault.authority.is_some() || source_epoch.as_i64() != Some(vault.epoch) {
            return value_error("vault cutover is stale or already selected");
        }
        let event = self.emit(
            "VaultProductPrimarySelected",
            payload.clone(),
            actor,
            request_id,
            None,
        )?;
        Ok((payload, event))
    }

    pub fn vault_view(&self, vault_id: &str, actor: &str) -> Result<Value> {
        self.vault(vault_id, actor)?;
        self.state.vaults.view(vault_id)
    }

    /// The current revision record and verified bytes of a source.
    pub fn vault_source(
        &self,
        vault_id: &str,
        source_id: &str,
        actor: &str,
    ) -> Result<(Value, Vec<u8>)> {
        let vault = self.vault(vault_id, actor)?;
        let source = vault
            .sources
            .get(source_id)
            .cloned()
            .ok_or_else(|| LedgerError::Key(source_id.to_string()))?;
        let bytes = self
            .object_bytes(get_str(&source, "artifact_id")?)
            .map_err(|_| LedgerError::Value("vault source is missing or corrupt".into()))?;
        Ok((source, bytes))
    }

    /// A scoped asset: artifact identity, size, verified.
    pub fn vault_asset(
        &self,
        vault_id: &str,
        artifact_id: &str,
        actor: &str,
    ) -> Result<(Sha256Id, u64)> {
        self.vault(vault_id, actor)?;
        let identity = require_id(artifact_id)?;
        let prefix = format!("phoenix-vault:{vault_id}:");
        let Some(artifact) = self.state.artifacts.get(identity) else {
            return value_error("vault asset is unavailable");
        };
        if !artifact
            .get("kind")
            .and_then(Value::as_str)
            .is_some_and(|k| k.starts_with(&prefix))
        {
            return value_error("vault asset is unavailable");
        }
        if !self.cas_verify(identity) {
            return value_error("vault asset is missing or corrupt");
        }
        Ok((
            Sha256Id::parse(identity).unwrap(),
            artifact
                .get("byte_count")
                .and_then(Value::as_u64)
                .unwrap_or(0),
        ))
    }

    // ------------------------------------------------------------ portable packages

    /// `vault_export`: writes the package directory and returns its root identity.
    pub fn vault_export(&self, vault_id: &str, actor: &str, destination: &Path) -> Result<String> {
        if destination.exists() || destination.starts_with(self.store.root()) {
            return value_error("vault export destination must be new and outside Library");
        }
        self.vault(vault_id, actor)?;
        let mut events = Vec::new();
        let (mut source_ids, mut asset_ids) = (BTreeSet::new(), BTreeSet::new());
        for seq in 1..=self.store.main.seq() {
            let stored = self.store.main.read(seq)?;
            let event = strict_json(&stored.event)?;
            let kind = get_str(&event, "type")?;
            if !VAULT_EVENTS.contains(&kind) {
                continue;
            }
            let payload = strict_json(&stored.payload)?;
            if payload["vault_id"].as_str() != Some(vault_id) {
                continue;
            }
            match kind {
                "VaultSourceCommitted" => {
                    source_ids.insert(get_str(&payload, "artifact_id")?.to_string());
                }
                "VaultGenerationSelected" => {
                    asset_ids.insert(get_str(&payload, "manifest_artifact_id")?.to_string());
                    asset_ids.extend(crate::json::string_list(&payload, "asset_ids")?);
                }
                "VaultProductPrimarySelected" => {
                    asset_ids.insert(get_str(&payload, "receipt_artifact_id")?.to_string());
                }
                _ => {}
            }
            events.push(crate::obj! {"origin_event_id" => stored.event_id.to_string(), "kind" => kind, "payload" => payload});
        }
        let mut objects = Vec::new();
        let all: BTreeSet<String> = source_ids.union(&asset_ids).cloned().collect();
        for identity in &all {
            if !self.cas_verify(identity) {
                return value_error("vault export references corrupt CAS object");
            }
            let artifact = self.state.artifacts.get(identity);
            let kind = if asset_ids.contains(identity) {
                let kind = artifact
                    .and_then(|a| a.get("kind"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !kind.starts_with(&format!("phoenix-vault:{vault_id}:")) {
                    return value_error("vault export asset scope mismatch");
                }
                kind.to_string()
            } else {
                "source".to_string()
            };
            objects.push(crate::obj! {"artifact_id" => identity.clone(), "byte_count" => self.object_size(identity).unwrap_or(0), "kind" => kind});
        }
        let manifest = crate::obj! {
            "schema" => "PHOENIX_VAULT_PACKAGE_V1", "vault_id" => vault_id,
            "owner_actor" => actor, "origin_head" => self.store.main.head().to_string(),
            "events" => events, "objects" => objects,
        };
        let raw = canonical(&manifest)?;
        let parent = destination.parent().ok_or_else(|| {
            LedgerError::Value("vault export destination must be new and outside Library".into())
        })?;
        let staged = parent.join(format!(".vault-export-{}", std::process::id()));
        let result = (|| {
            for identity in &all {
                let target = object_path(&staged, identity)?;
                fs::create_dir_all(target.parent().unwrap()).map_err(io_error(&target))?;
                let mut out = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&target)
                    .map_err(io_error(&target))?;
                let id = Sha256Id::parse(identity).unwrap();
                if self.store.objects.contains(&id) {
                    self.store.objects.copy_to(&id, &mut out)?;
                } else {
                    out.write_all(&self.object_bytes(identity)?)
                        .map_err(io_error(&target))?;
                }
                out.sync_all().map_err(io_error(&target))?;
            }
            fs::write(staged.join("VAULT.json"), &raw).map_err(io_error(&staged))?;
            fs::rename(&staged, destination).map_err(io_error(destination))
        })();
        if staged.exists() {
            let _ = fs::remove_dir_all(&staged);
        }
        result?;
        Ok(raw_id(&raw).to_string())
    }

    /// `vault_import`: verifies an unpacked package and replays its semantic events.
    pub fn vault_import(
        &mut self,
        package: &Path,
        actor: &str,
        expected_root: &str,
    ) -> Result<Value> {
        let raw = fs::read(package.join("VAULT.json")).map_err(io_error(package))?;
        if raw_id(&raw).to_string() != require_id(expected_root)? {
            return value_error("vault package root mismatch");
        }
        let manifest = strict_json(&raw)?;
        if canonical(&manifest)? != raw
            || manifest.get("schema").and_then(Value::as_str) != Some("PHOENIX_VAULT_PACKAGE_V1")
        {
            return value_error("noncanonical or unknown vault package");
        }
        let vault_id = get_str(&manifest, "vault_id")?.to_string();
        let events = crate::json::get_array(&manifest, "events")?.clone();
        if get_str(&manifest, "owner_actor")? != actor || events.is_empty() {
            return value_error("vault package owner or event history mismatch");
        }
        if self
            .state
            .authority
            .actors
            .get(actor)
            .and_then(|a| a.get("kind"))
            .and_then(Value::as_str)
            != Some("service")
        {
            return value_error("vault import requires a registered service actor");
        }
        let mut assets: BTreeMap<String, String> = BTreeMap::new();
        let mut object_ids = BTreeSet::new();
        for entry in crate::json::get_array(&manifest, "objects")? {
            let identity = require_id(get_str(entry, "artifact_id")?)?.to_string();
            if !object_ids.insert(identity.clone()) {
                return value_error("duplicate vault object");
            }
            let path = object_path(package, &identity)?;
            let meta = fs::symlink_metadata(&path).ok();
            if !meta.as_ref().is_some_and(|m| m.is_file()) {
                return value_error("unsafe or missing vault object");
            }
            let mut hasher = Sha256Hasher::new();
            let mut file = File::open(&path).map_err(io_error(&path))?;
            let mut buffer = vec![0u8; 1 << 20];
            loop {
                let read = file.read(&mut buffer).map_err(io_error(&path))?;
                if read == 0 {
                    break;
                }
                hasher.update(&buffer[..read]);
            }
            if Some(meta.unwrap().len()) != get(entry, "byte_count")?.as_u64()
                || hasher.finish().to_string() != identity
            {
                return value_error("vault object integrity mismatch");
            }
            let kind = get_str(entry, "kind")?;
            if kind != "source" {
                let prefix = format!("phoenix-vault:{vault_id}:");
                match kind.strip_prefix(&prefix) {
                    Some(rest) if is_safe(rest) => {
                        assets.insert(identity.clone(), rest.to_string());
                    }
                    _ => return value_error("vault object scope mismatch"),
                }
            }
        }
        let mut dry = Vaults::default();
        let mut referenced = BTreeSet::new();
        for (index, item) in events.iter().enumerate() {
            let kind = get_str(item, "kind")?;
            let payload = get(item, "payload")?;
            require_id(get_str(item, "origin_event_id")?)?;
            if !VAULT_EVENTS.contains(&kind)
                || payload.get("vault_id").and_then(Value::as_str) != Some(vault_id.as_str())
            {
                return value_error("foreign vault event");
            }
            if index == 0
                && (kind != "VaultCreated"
                    || payload.get("owner_actor").and_then(Value::as_str) != Some(actor))
            {
                return value_error("vault history must begin with its owner");
            }
            if index > 0 && kind == "VaultCreated" {
                return value_error("duplicate vault creation");
            }
            dry.apply(kind, payload)?;
            match kind {
                "VaultSourceCommitted" => {
                    referenced.insert(get_str(payload, "artifact_id")?.to_string());
                }
                "VaultGenerationSelected" => {
                    referenced.insert(get_str(payload, "manifest_artifact_id")?.to_string());
                    let ids: BTreeSet<String> = crate::json::string_list(payload, "asset_ids")?
                        .into_iter()
                        .collect();
                    referenced.extend(ids.iter().cloned());
                    let expected = crate::obj! {
                        "schema" => "PHOENIX_VAULT_GENERATION_V1", "vault_id" => vault_id.clone(),
                        "source_epoch" => payload["source_epoch"].clone(),
                        "generation_id" => payload["generation_id"].clone(),
                        "asset_ids" => ids.into_iter().collect::<Vec<_>>(),
                    };
                    let path = object_path(package, get_str(payload, "manifest_artifact_id")?)?;
                    if strict_json(&fs::read(&path).map_err(io_error(&path))?)? != expected {
                        return value_error("vault generation manifest mismatch");
                    }
                }
                "VaultProductPrimarySelected" => {
                    let receipt = get_str(payload, "receipt_artifact_id")?.to_string();
                    if assets.get(&receipt).map(String::as_str) != Some("cutover-receipt") {
                        return value_error("vault cutover receipt kind mismatch");
                    }
                    referenced.insert(receipt);
                }
                _ => {}
            }
        }
        if referenced != object_ids || dry.vaults.len() != 1 {
            return value_error("vault package object inventory mismatch");
        }
        for item in &events {
            if item["kind"] == "VaultSourceCommitted"
                && assets.contains_key(item["payload"]["artifact_id"].as_str().unwrap_or(""))
            {
                return value_error("vault source and generation asset overlap");
            }
        }
        let root = raw_id(&raw).to_string();
        let create_request = format!("vault-import:{root}:create");
        if self.state.vaults.vaults.contains_key(&vault_id) && !self.has_request(&create_request)? {
            return value_error("vault already exists on destination");
        }
        self.vault_create(&vault_id, actor, &create_request)?;
        for (index, (identity, kind)) in assets.iter().enumerate() {
            let (imported, _, _) = self.vault_stage_file(
                &vault_id,
                &object_path(package, identity)?,
                kind,
                actor,
                &format!("vault-import:{root}:asset:{index}"),
            )?;
            if &imported != identity {
                return value_error("vault imported asset identity mismatch");
            }
        }
        for (index, item) in events.iter().enumerate().skip(1) {
            let kind = get_str(item, "kind")?;
            let payload = get(item, "payload")?;
            let request = format!("vault-import:{root}:event:{}", index - 1);
            let imported = match kind {
                // Streams the source, lifting Python's 8 MiB JSON limit to the 16 MiB stream limit.
                "VaultSourceCommitted" => {
                    let path = object_path(package, get_str(payload, "artifact_id")?)?;
                    self.vault_commit_source_file(
                        &vault_id,
                        get_str(payload, "source_id")?,
                        get(payload, "base_revision")?,
                        &path,
                        actor,
                        &request,
                    )?
                    .0
                }
                "VaultGenerationSelected" => {
                    self.vault_select_generation(
                        &vault_id,
                        get(payload, "source_epoch")?,
                        get(payload, "generation_id")?,
                        get_str(payload, "manifest_artifact_id")?,
                        get(payload, "asset_ids")?,
                        actor,
                        &request,
                    )?
                    .0
                }
                "VaultReaderPositionSet" => {
                    self.vault_set_reader(
                        &vault_id,
                        get_str(payload, "source_id")?,
                        get(payload, "revision")?,
                        get(payload, "offset")?,
                        actor,
                        &request,
                    )?
                    .0
                }
                "VaultProductPrimarySelected" => {
                    self.vault_select_product_primary(
                        &vault_id,
                        get(payload, "source_epoch")?,
                        get_str(payload, "receipt_artifact_id")?,
                        actor,
                        &request,
                    )?
                    .0
                }
                _ => continue,
            };
            if &imported != payload {
                return value_error(match kind {
                    "VaultSourceCommitted" => "vault imported source lineage mismatch",
                    "VaultGenerationSelected" => "vault imported generation mismatch",
                    "VaultReaderPositionSet" => "vault imported reader mismatch",
                    _ => "vault imported product authority mismatch",
                });
            }
        }
        self.vault_view(&vault_id, actor)
    }
}

/// `vault_archive.pack`: ZIP64, stored (no compression), entries sorted.
pub fn pack(directory: &Path, archive: &Path) -> Result<()> {
    let mut files = Vec::new();
    collect_files(directory, directory, &mut files)?;
    files.sort();
    let out = File::create(archive).map_err(io_error(archive))?;
    let mut zip = zip::ZipWriter::new(out);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Stored)
        .large_file(true);
    for relative in files {
        zip.start_file(relative.clone(), options)
            .map_err(|e| LedgerError::Value(e.to_string()))?;
        let path = directory.join(&relative);
        let mut source = File::open(&path).map_err(io_error(&path))?;
        std::io::copy(&mut source, &mut zip).map_err(io_error(&path))?;
    }
    let file = zip
        .finish()
        .map_err(|e| LedgerError::Value(e.to_string()))?;
    file.sync_all().map_err(io_error(archive))?;
    Ok(())
}

fn collect_files(root: &Path, dir: &Path, out: &mut Vec<String>) -> Result<()> {
    for entry in fs::read_dir(dir).map_err(io_error(dir))? {
        let entry = entry.map_err(io_error(dir))?;
        let kind = entry.file_type().map_err(io_error(dir))?;
        if kind.is_symlink() {
            return value_error("vault package cannot contain symlinks");
        }
        if kind.is_dir() {
            collect_files(root, &entry.path(), out)?;
        } else {
            let relative = entry
                .path()
                .strip_prefix(root)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            out.push(relative);
        }
    }
    Ok(())
}

fn valid_member_name(name: &str) -> bool {
    if name == "VAULT.json" {
        return true;
    }
    let Some(rest) = name.strip_prefix("objects/sha256/") else {
        return false;
    };
    let parts: Vec<&str> = rest.split('/').collect();
    parts.len() == 2
        && parts[0].len() == 2
        && parts[1].len() == 62
        && parts.iter().all(|p| {
            p.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
}

/// `vault_archive.unpack` with the same limits.
pub fn unpack(archive: &Path, destination: &Path) -> Result<()> {
    let file = File::open(archive).map_err(io_error(archive))?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| LedgerError::Value(e.to_string()))?;
    if zip.len() > MAX_PACKAGE_FILES {
        return value_error("vault package has too many objects");
    }
    let mut names = BTreeSet::new();
    let mut total = 0u64;
    for index in 0..zip.len() {
        let mut member = zip
            .by_index(index)
            .map_err(|e| LedgerError::Value(e.to_string()))?;
        let name = member.name().to_string();
        if names.contains(&name) || !valid_member_name(&name) {
            return value_error("vault package contains duplicate or unsafe path");
        }
        names.insert(name.clone());
        if member.is_dir() || member.size() > MAX_PACKAGE_BYTES {
            return value_error("vault package object exceeds limit");
        }
        total += member.size();
        if total > MAX_PACKAGE_BYTES {
            return value_error("vault package exceeds limit");
        }
        let target = destination.join(&name);
        fs::create_dir_all(target.parent().unwrap()).map_err(io_error(&target))?;
        let mut out = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(io_error(&target))?;
        std::io::copy(&mut member, &mut out).map_err(io_error(&target))?;
        out.sync_all().map_err(io_error(&target))?;
    }
    if !names.contains("VAULT.json") {
        return value_error("vault package manifest missing");
    }
    Ok(())
}

/// Revision numbers are Python ints; reject anything else explicitly.
pub fn int_field(value: &Value, key: &str) -> Result<i64> {
    get_int(value, key)
}
