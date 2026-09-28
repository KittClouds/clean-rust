use phoenix_store_native_core::StoreError;
use phoenix_types::{
    NativeDecisionRewardObservationOperation, NativeDecisionRewardObservationReceipt,
};

use super::native_decision_persistence::{
    decode_location, DecodedRecord, NativeDecisionReceiptIndex, RecordLocation,
};

pub(super) fn validate_reward_observation_lineage(
    mapped: &[u8],
    index: &NativeDecisionReceiptIndex,
    receipt: &NativeDecisionRewardObservationReceipt,
) -> Result<(), StoreError> {
    let locations = index
        .reward_observations_by_decision_receipt
        .get(receipt.decision_receipt_id.as_str())
        .map(Vec::as_slice)
        .unwrap_or_default();
    let mut prior = locations
        .iter()
        .copied()
        .map(|location| decode_reward_observation(mapped, location))
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .filter(|observation| {
            observation.candidate_action_identity == receipt.candidate_action_identity
                && observation.dimension == receipt.dimension
        })
        .collect::<Vec<_>>();
    prior.sort_unstable_by_key(|observation| observation.observed_at);
    match prior.last() {
        None if receipt.operation != NativeDecisionRewardObservationOperation::Observe => Err(
            StoreError::Query("first native reward observation must observe".to_owned()),
        ),
        None => Ok(()),
        Some(latest)
            if receipt.operation == NativeDecisionRewardObservationOperation::Observe
                || receipt.predecessor_observation_receipt_id.as_ref()
                    != Some(&latest.receipt_id)
                || receipt.observed_at <= latest.observed_at =>
        {
            Err(StoreError::Query(
                "native reward observation must extend the latest immutable receipt".to_owned(),
            ))
        }
        Some(_) => Ok(()),
    }
}

pub(super) fn decode_reward_observation(
    mapped: &[u8],
    location: RecordLocation,
) -> Result<NativeDecisionRewardObservationReceipt, StoreError> {
    match decode_location(mapped, location)? {
        DecodedRecord::RewardObservation(value) => Ok(*value),
        DecodedRecord::Decision(_)
        | DecodedRecord::Outcome(_)
        | DecodedRecord::RewardEvidence(_) => Err(StoreError::Snapshot(
            "native reward observation record kind mismatch".to_owned(),
        )),
    }
}

pub(super) fn decode_reward_observation_payload(
    payload: &[u8],
) -> Result<NativeDecisionRewardObservationReceipt, StoreError> {
    let value: NativeDecisionRewardObservationReceipt =
        rmp_serde::from_slice(payload).map_err(|error| {
            StoreError::Snapshot(format!("native reward observation decode: {error}"))
        })?;
    value
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(value)
}
