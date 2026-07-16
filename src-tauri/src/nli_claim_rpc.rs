use std::env;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_rel_post::{
    api, NliClaimAdjudication, NliClaimAdjudicationOptions, NliClaimInput, NliModel,
    NliModelMetadata,
};
use serde::{Deserialize, Serialize};

pub const NATIVE_NLI_CLAIM_REQUEST_SCHEMA_VERSION: &str = "phoenix-native-nli-claim-request/v1";
pub const NATIVE_NLI_CLAIM_RESPONSE_SCHEMA_VERSION: &str = "phoenix-native-nli-claim-response/v1";

const NLI_MODEL_ROOT_ENV: &str = "PHOENIX_NLI_MODEL_ROOT";

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeNliClaimAdjudicationRequest {
    #[serde(default = "default_request_schema_version")]
    schema_version: String,
    #[serde(default)]
    model_root: Option<String>,
    #[serde(default)]
    claims: Vec<NliClaimInput>,
    #[serde(default)]
    options: NativeNliClaimAdjudicationOptionsWire,
}

#[derive(Debug, Clone, Copy, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeNliClaimAdjudicationOptionsWire {
    #[serde(default)]
    max_pairs_per_batch: Option<usize>,
    #[serde(default)]
    support_threshold_millis: Option<u32>,
    #[serde(default)]
    contradiction_threshold_millis: Option<u32>,
    #[serde(default)]
    decision_margin_millis: Option<u32>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeNliClaimAdjudicationResponse {
    schema_version: &'static str,
    request_schema_version: String,
    model_root: Option<String>,
    input_count: usize,
    result_count: usize,
    load_elapsed_millis: u64,
    adjudication_elapsed_millis: u64,
    model_metadata: Option<NliModelMetadata>,
    adjudications: Vec<NliClaimAdjudication>,
    receipts: Vec<String>,
}

pub fn adjudicate_claims_json(request_json: &str) -> Result<String, String> {
    let request = parse_request(request_json)?;
    if request.claims.is_empty() {
        let response = NativeNliClaimAdjudicationResponse {
            schema_version: NATIVE_NLI_CLAIM_RESPONSE_SCHEMA_VERSION,
            request_schema_version: request.schema_version,
            model_root: request.model_root,
            input_count: 0,
            result_count: 0,
            load_elapsed_millis: 0,
            adjudication_elapsed_millis: 0,
            model_metadata: None,
            adjudications: Vec::new(),
            receipts: vec!["native-nli:skipped-empty-claims".to_owned()],
        };
        return serialize_response(&response);
    }

    let model_root = resolve_model_root(request.model_root.as_deref())?;
    let model_root_wire = model_root.display().to_string();
    let load_started = Instant::now();
    let model = NliModel::load(&model_root)
        .map_err(|error| format!("failed to load native NLI model: {error}"))?;
    let load_elapsed_millis = elapsed_millis(load_started);
    let model_metadata = model.metadata().clone();
    let input_count = request.claims.len();
    let options = request.options.into_options();
    let adjudication_started = Instant::now();
    let adjudications = api::adjudicate_claims(&request.claims, &model, options)
        .map_err(|error| format!("native NLI claim adjudication failed: {error}"))?;
    let adjudication_elapsed_millis = elapsed_millis(adjudication_started);
    let result_count = adjudications.len();

    let response = NativeNliClaimAdjudicationResponse {
        schema_version: NATIVE_NLI_CLAIM_RESPONSE_SCHEMA_VERSION,
        request_schema_version: request.schema_version,
        model_root: Some(model_root_wire),
        input_count,
        result_count,
        load_elapsed_millis,
        adjudication_elapsed_millis,
        model_metadata: Some(model_metadata),
        adjudications,
        receipts: vec![format!(
            "native-nli:claims={input_count};results={result_count};loadMs={load_elapsed_millis};adjudicateMs={adjudication_elapsed_millis}"
        )],
    };
    serialize_response(&response)
}

fn parse_request(request_json: &str) -> Result<NativeNliClaimAdjudicationRequest, String> {
    serde_json::from_str::<NativeNliClaimAdjudicationRequest>(request_json)
        .map_err(|error| format!("invalid native NLI claim adjudication request: {error}"))
}

fn serialize_response(response: &NativeNliClaimAdjudicationResponse) -> Result<String, String> {
    serde_json::to_string(response)
        .map_err(|error| format!("failed to serialize native NLI response: {error}"))
}

fn resolve_model_root(explicit: Option<&str>) -> Result<PathBuf, String> {
    if let Some(path) = explicit.and_then(non_empty_path) {
        return ensure_model_root(path);
    }
    match env::var(NLI_MODEL_ROOT_ENV) {
        Ok(value) => non_empty_path(&value)
            .map(ensure_model_root)
            .unwrap_or_else(|| Err(missing_model_root_error())),
        Err(_) => Err(missing_model_root_error()),
    }
}

fn non_empty_path(value: &str) -> Option<PathBuf> {
    let trimmed = value.trim();
    (!trimmed.is_empty()).then(|| PathBuf::from(trimmed))
}

fn ensure_model_root(path: PathBuf) -> Result<PathBuf, String> {
    if path.exists() {
        Ok(path)
    } else {
        Err(format!(
            "native NLI model root does not exist: {}",
            path.display()
        ))
    }
}

fn missing_model_root_error() -> String {
    format!("native NLI model root is required; pass modelRoot or set {NLI_MODEL_ROOT_ENV}")
}

fn elapsed_millis(started: Instant) -> u64 {
    started.elapsed().as_millis().try_into().unwrap_or(u64::MAX)
}

fn default_request_schema_version() -> String {
    NATIVE_NLI_CLAIM_REQUEST_SCHEMA_VERSION.to_owned()
}

impl NativeNliClaimAdjudicationOptionsWire {
    fn into_options(self) -> NliClaimAdjudicationOptions {
        let mut options = NliClaimAdjudicationOptions::default();
        if let Some(value) = self.max_pairs_per_batch {
            options.max_pairs_per_batch = value;
        }
        if let Some(value) = self.support_threshold_millis {
            options.support_threshold_millis = value;
        }
        if let Some(value) = self.contradiction_threshold_millis {
            options.contradiction_threshold_millis = value;
        }
        if let Some(value) = self.decision_margin_millis {
            options.decision_margin_millis = value;
        }
        options
    }
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::*;

    #[test]
    fn empty_request_returns_v1_response_without_loading_model() {
        let json = adjudicate_claims_json(r#"{"claims":[]}"#).expect("empty response");
        let value: Value = serde_json::from_str(&json).expect("response json");

        assert_eq!(
            value["schemaVersion"],
            NATIVE_NLI_CLAIM_RESPONSE_SCHEMA_VERSION
        );
        assert_eq!(
            value["requestSchemaVersion"],
            NATIVE_NLI_CLAIM_REQUEST_SCHEMA_VERSION
        );
        assert_eq!(value["inputCount"], 0);
        assert_eq!(value["resultCount"], 0);
        assert!(value["modelMetadata"].is_null());
    }

    #[test]
    fn request_accepts_legacy_claim_and_partial_options() {
        let request = parse_request(
            r#"{
                "claims": [{
                    "claimId": "claim-1",
                    "evidenceId": "ev-1",
                    "premise": "Mara found the ledger in the bell tower.",
                    "hypothesis": "Mara found the ledger.",
                    "purpose": "canonFact"
                }],
                "options": {
                    "maxPairsPerBatch": 8,
                    "supportThresholdMillis": 640
                }
            }"#,
        )
        .expect("request");
        let options = request.options.into_options();

        assert_eq!(
            request.schema_version,
            NATIVE_NLI_CLAIM_REQUEST_SCHEMA_VERSION
        );
        assert_eq!(
            request.claims[0].schema_version,
            "phoenix-nli-claim-input/v1"
        );
        assert_eq!(request.claims[0].purpose as u8, 1);
        assert_eq!(options.max_pairs_per_batch, 8);
        assert_eq!(options.support_threshold_millis, 640);
        assert_eq!(
            options.contradiction_threshold_millis,
            NliClaimAdjudicationOptions::default().contradiction_threshold_millis
        );
    }
}
