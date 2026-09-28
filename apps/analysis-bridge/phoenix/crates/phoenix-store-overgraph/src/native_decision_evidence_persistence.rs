use phoenix_store_native_core::{NativeDecisionReceiptAppend, StoreError};
use phoenix_types::NativeDecisionRewardEvidenceReceipt;

use super::native_decision_persistence::{
    append_encoded, decode_location, encode_record, existing_record, required_map, DecodedRecord,
    RecordKind,
};
use super::PhoenixOvergraphStore;

impl PhoenixOvergraphStore {
    pub(super) fn append_reward_evidence(
        &self,
        receipt: &NativeDecisionRewardEvidenceReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        if let Some(existing) = existing_record(self, &index, &receipt.receipt_id)? {
            return match existing {
                DecodedRecord::RewardEvidence(value) if value.as_ref() == receipt => {
                    Ok(NativeDecisionReceiptAppend::AlreadyPresent {
                        receipt_id: receipt.receipt_id.to_string(),
                    })
                }
                _ => Err(StoreError::Query(
                    "native reward evidence identity collision".to_owned(),
                )),
            };
        }
        if !index
            .by_receipt_id
            .get(receipt.decision_receipt_id.as_str())
            .is_some_and(|location| location.kind == RecordKind::Decision)
        {
            return Err(StoreError::Query(
                "native reward evidence decision receipt missing".to_owned(),
            ));
        }
        let encoded = encode_record(RecordKind::RewardEvidence, receipt)?;
        append_encoded(self, &mut index, &encoded)?;
        Ok(NativeDecisionReceiptAppend::Appended {
            byte_len: encoded.len(),
        })
    }

    pub(super) fn load_reward_evidence(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionRewardEvidenceReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(location) = index
            .by_receipt_id
            .get(receipt_id)
            .copied()
            .filter(|location| location.kind == RecordKind::RewardEvidence)
        else {
            return Ok(None);
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        decode_reward_evidence(&mapped, location).map(Some)
    }

    pub(super) fn load_reward_evidence_for_decision(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionRewardEvidenceReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(locations) = index
            .reward_evidence_by_decision_receipt
            .get(decision_receipt_id)
        else {
            return Ok(Vec::new());
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        locations
            .iter()
            .copied()
            .map(|location| decode_reward_evidence(&mapped, location))
            .collect()
    }
}

fn decode_reward_evidence(
    mapped: &[u8],
    location: super::native_decision_persistence::RecordLocation,
) -> Result<NativeDecisionRewardEvidenceReceipt, StoreError> {
    match decode_location(mapped, location)? {
        DecodedRecord::RewardEvidence(value) => Ok(*value),
        _ => Err(StoreError::Snapshot(
            "native reward evidence record kind mismatch".to_owned(),
        )),
    }
}

pub(super) fn decode_reward_evidence_payload(
    payload: &[u8],
) -> Result<NativeDecisionRewardEvidenceReceipt, StoreError> {
    let value: NativeDecisionRewardEvidenceReceipt = rmp_serde::from_slice(payload)
        .map_err(|error| StoreError::Snapshot(format!("native reward evidence decode: {error}")))?;
    value
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(value)
}
