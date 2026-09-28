use serde::{Deserialize, Serialize};

use crate::observer::{
    OBSERVER_INPUT_SCHEMA, OBSERVER_OUTPUT_SCHEMA, OBSERVER_OUTPUT_SCHEMA_V2,
    OBSERVER_SCHEMA_VERSION,
};

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chat_template_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chat_template_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_mode: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub system_prompt_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output_schema_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub minimum_applicability_milli: Option<u16>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub maximum_abstention_milli: Option<u16>,
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
        if !matches!(self.bundle_schema_version, 1 | 2)
            || self.observer_interface_version != OBSERVER_SCHEMA_VERSION
        {
            return Err(BundleError::WrongVersion);
        }
        if self.input_schema != OBSERVER_INPUT_SCHEMA
            || (self.output_schema != OBSERVER_OUTPUT_SCHEMA
                && self.output_schema != OBSERVER_OUTPUT_SCHEMA_V2)
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
        if self.bundle_schema_version == 2 {
            let Some(chat_template_id) = &self.chat_template_id else {
                return Err(BundleError::EmptyField);
            };
            let Some(reasoning_mode) = &self.reasoning_mode else {
                return Err(BundleError::EmptyField);
            };
            if chat_template_id.trim().is_empty()
                || !matches!(reasoning_mode.as_str(), "auto" | "off" | "on")
            {
                return Err(BundleError::EmptyField);
            }
            let hashes = [
                &self.chat_template_sha256,
                &self.system_prompt_sha256,
                &self.output_schema_sha256,
            ];
            if hashes
                .into_iter()
                .any(|hash| hash.as_deref().is_none_or(|value| !is_sha256_hex(value)))
            {
                return Err(BundleError::InvalidHash);
            }
            if self
                .minimum_applicability_milli
                .is_none_or(|value| value > 1000)
                || self.maximum_abstention_milli.is_none_or(|value| value > 1000)
            {
                return Err(BundleError::InvalidDecodingContract);
            }
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
            chat_template_id: None,
            chat_template_sha256: None,
            reasoning_mode: None,
            system_prompt_sha256: None,
            output_schema_sha256: None,
            minimum_applicability_milli: None,
            maximum_abstention_milli: None,
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

    #[test]
    fn version_two_bundle_hashes_the_observer_runtime_contract() {
        let mut value = manifest();
        value.bundle_schema_version = 2;
        value.chat_template_id = Some("model-embedded-jinja-v1".to_owned());
        value.chat_template_sha256 = Some("e".repeat(64));
        value.reasoning_mode = Some("off".to_owned());
        value.system_prompt_sha256 = Some("f".repeat(64));
        value.output_schema_sha256 = Some("1".repeat(64));
        value.minimum_applicability_milli = Some(700);
        value.maximum_abstention_milli = Some(600);
        assert_eq!(value.validate(), Ok(()));

        let original_hash = value.manifest_hash().unwrap();
        value.reasoning_mode = Some("auto".to_owned());
        assert_ne!(value.manifest_hash().unwrap(), original_hash);
        value.reasoning_mode = Some("off".to_owned());
        value.normalization_contract = "percent-0-100-to-milli-x10-v1".to_owned();
        assert_ne!(value.manifest_hash().unwrap(), original_hash);
    }

    #[test]
    fn version_two_bundle_accepts_percent_output_schema() {
        let mut value = manifest();
        value.bundle_schema_version = 2;
        value.output_schema = OBSERVER_OUTPUT_SCHEMA_V2.to_owned();
        value.chat_template_id = Some("model-embedded-jinja-v1".to_owned());
        value.chat_template_sha256 = Some("e".repeat(64));
        value.reasoning_mode = Some("off".to_owned());
        value.system_prompt_sha256 = Some("f".repeat(64));
        value.output_schema_sha256 = Some("1".repeat(64));
        value.minimum_applicability_milli = Some(700);
        value.maximum_abstention_milli = Some(600);
        assert_eq!(value.validate(), Ok(()));
    }

    #[test]
    fn version_two_bundle_requires_all_behavioral_hash_inputs() {
        let mut value = manifest();
        value.bundle_schema_version = 2;
        assert_eq!(value.validate(), Err(BundleError::EmptyField));
    }
}
