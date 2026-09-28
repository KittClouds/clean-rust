use serde::{Deserialize, Serialize};

use crate::observer::{OBSERVER_INPUT_SCHEMA, OBSERVER_OUTPUT_SCHEMA, OBSERVER_SCHEMA_VERSION};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObserverBundleManifest {
    pub bundle_schema_version: u16,
    pub bundle_id: String,
    pub observer_interface_version: u16,
    pub implementation_id: String,
    pub input_schema: String,
    pub output_schema: String,
    pub backbone_name: String,
    pub backbone_revision: String,
    pub backbone_sha256: String,
    pub runtime_name: String,
    pub runtime_revision: String,
    pub runtime_sha256: String,
    pub representation_surface_id: String,
    pub representation_surface_sha256: String,
    pub normalization_contract: String,
    pub typed_head_id: String,
    pub typed_head_kind: String,
    pub typed_head_schema_sha256: String,
    pub temperature_milli: u16,
    pub top_p_milli: u16,
    pub maximum_output_tokens: u16,
    pub seed: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BundleError {
    WrongVersion,
    EmptyField,
    WrongSchema,
    InvalidHash,
    InvalidDecodingContract,
}

impl ObserverBundleManifest {
    pub fn validate(&self) -> Result<(), BundleError> {
        if self.bundle_schema_version != 1
            || self.observer_interface_version != OBSERVER_SCHEMA_VERSION
        {
            return Err(BundleError::WrongVersion);
        }
        if self.input_schema != OBSERVER_INPUT_SCHEMA
            || self.output_schema != OBSERVER_OUTPUT_SCHEMA
        {
            return Err(BundleError::WrongSchema);
        }
        let required = [
            &self.bundle_id,
            &self.implementation_id,
            &self.backbone_name,
            &self.backbone_revision,
            &self.runtime_name,
            &self.runtime_revision,
            &self.representation_surface_id,
            &self.normalization_contract,
            &self.typed_head_id,
            &self.typed_head_kind,
        ];
        if required.iter().any(|field| field.trim().is_empty()) {
            return Err(BundleError::EmptyField);
        }
        let hashes = [
            &self.backbone_sha256,
            &self.runtime_sha256,
            &self.representation_surface_sha256,
            &self.typed_head_schema_sha256,
        ];
        if hashes.iter().any(|hash| !is_sha256_hex(hash)) {
            return Err(BundleError::InvalidHash);
        }
        if self.temperature_milli > 1000
            || self.top_p_milli == 0
            || self.top_p_milli > 1000
            || self.maximum_output_tokens == 0
        {
            return Err(BundleError::InvalidDecodingContract);
        }
        Ok(())
    }

    pub fn canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }

    pub fn manifest_hash(&self) -> Result<[u8; 32], serde_json::Error> {
        Ok(*blake3::hash(&self.canonical_json()?).as_bytes())
    }
}

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manifest() -> ObserverBundleManifest {
        ObserverBundleManifest {
            bundle_schema_version: 1,
            bundle_id: "test-bundle-v1".to_owned(),
            observer_interface_version: OBSERVER_SCHEMA_VERSION,
            implementation_id: "test-observer".to_owned(),
            input_schema: OBSERVER_INPUT_SCHEMA.to_owned(),
            output_schema: OBSERVER_OUTPUT_SCHEMA.to_owned(),
            backbone_name: "frozen-backbone".to_owned(),
            backbone_revision: "rev-1".to_owned(),
            backbone_sha256: "a".repeat(64),
            runtime_name: "runtime".to_owned(),
            runtime_revision: "rev-2".to_owned(),
            runtime_sha256: "b".repeat(64),
            representation_surface_id: "chat-frame-v1".to_owned(),
            representation_surface_sha256: "c".repeat(64),
            normalization_contract: "line-endings-lf-v1".to_owned(),
            typed_head_id: "json-schema-head-v1".to_owned(),
            typed_head_kind: "constrained-json-generation".to_owned(),
            typed_head_schema_sha256: "d".repeat(64),
            temperature_milli: 0,
            top_p_milli: 1000,
            maximum_output_tokens: 128,
            seed: 0,
        }
    }

    #[test]
    fn bundle_lock_hash_is_stable_and_schema_bound() {
        let first = manifest();
        assert_eq!(first.validate(), Ok(()));
        assert_eq!(
            first.manifest_hash().unwrap(),
            first.manifest_hash().unwrap()
        );
        let mut changed = first;
        changed.typed_head_id.push_str("-changed");
        assert_ne!(
            changed.manifest_hash().unwrap(),
            manifest().manifest_hash().unwrap()
        );
    }

    #[test]
    fn bundle_rejects_missing_artifact_identity() {
        let mut value = manifest();
        value.backbone_sha256 = "unknown".to_owned();
        assert_eq!(value.validate(), Err(BundleError::InvalidHash));
    }
}
