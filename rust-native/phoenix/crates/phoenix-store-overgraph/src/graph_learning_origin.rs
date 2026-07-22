use compact_str::CompactString;
use phoenix_graph_kernel::{DiscoveryPathProposalOrigin, GraphProposalBatchReceipt};
use phoenix_store_native_core::StoreError;

const DISCOVERY_ORIGIN_PREFIX: &str = "phoenix-discovery-origin/v1:";

// The fixed v1 mmap header already owns one optional string slot. Discovery
// receipts cannot carry a model, so a tagged origin envelope preserves the
// existing record layout and remains exactly decodable across cold restarts.

pub(super) fn encode_model_slot(receipt: &GraphProposalBatchReceipt) -> Result<String, StoreError> {
    match (&receipt.model_id, &receipt.discovery_origin) {
        (Some(model_id), None) => Ok(model_id.to_string()),
        (None, Some(origin)) => serde_json::to_string(origin)
            .map(|json| format!("{DISCOVERY_ORIGIN_PREFIX}{json}"))
            .map_err(|error| StoreError::Schema(format!("encode discovery origin: {error}"))),
        (None, None) => Ok(String::new()),
        (Some(_), Some(_)) => Err(StoreError::Schema(
            "proposal receipt cannot store both a model and discovery origin".to_owned(),
        )),
    }
}

pub(super) fn decode_model_slot(
    value: &str,
) -> Result<(Option<CompactString>, Option<DiscoveryPathProposalOrigin>), StoreError> {
    let Some(json) = value.strip_prefix(DISCOVERY_ORIGIN_PREFIX) else {
        return Ok(((!value.is_empty()).then(|| CompactString::new(value)), None));
    };
    let origin = serde_json::from_str(json)
        .map_err(|error| StoreError::Snapshot(format!("decode discovery origin: {error}")))?;
    Ok((None, Some(origin)))
}
