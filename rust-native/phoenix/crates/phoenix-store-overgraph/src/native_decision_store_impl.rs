use phoenix_store_native_core::{
    NativeDecisionReceiptAppend, PhoenixNativeDecisionStore, StoreError,
};
use phoenix_types::{
    NativeDecisionOutcomeReceipt, NativeDecisionReceipt, NativeDecisionRewardEvidenceReceipt,
    NativeDecisionRewardObservationReceipt,
};

use super::PhoenixOvergraphStore;

impl PhoenixNativeDecisionStore for PhoenixOvergraphStore {
    fn append_native_decision_receipt(
        &self,
        receipt: &NativeDecisionReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        self.append_decision(receipt)
    }

    fn append_native_decision_outcome_receipt(
        &self,
        receipt: &NativeDecisionOutcomeReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        self.append_outcome(receipt)
    }

    fn load_native_decision_receipt(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionReceipt>, StoreError> {
        self.load_decision(receipt_id)
    }

    fn load_native_decision_receipt_by_decision_id(
        &self,
        decision_id: &str,
    ) -> Result<Option<NativeDecisionReceipt>, StoreError> {
        self.load_decision_by_decision_id(decision_id)
    }

    fn load_native_decision_receipts(&self) -> Result<Vec<NativeDecisionReceipt>, StoreError> {
        self.load_decisions()
    }

    fn load_native_decision_outcome_receipt(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionOutcomeReceipt>, StoreError> {
        self.load_outcome(receipt_id)
    }

    fn load_native_decision_outcome_receipts(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionOutcomeReceipt>, StoreError> {
        self.load_outcomes(decision_receipt_id)
    }

    fn append_native_decision_reward_evidence(
        &self,
        receipt: &NativeDecisionRewardEvidenceReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        self.append_reward_evidence(receipt)
    }

    fn load_native_decision_reward_evidence(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionRewardEvidenceReceipt>, StoreError> {
        self.load_reward_evidence(receipt_id)
    }

    fn load_native_decision_reward_evidence_for_decision(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionRewardEvidenceReceipt>, StoreError> {
        self.load_reward_evidence_for_decision(decision_receipt_id)
    }

    fn append_native_decision_reward_observation(
        &self,
        receipt: &NativeDecisionRewardObservationReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        self.append_reward_observation(receipt)
    }

    fn load_native_decision_reward_observation(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionRewardObservationReceipt>, StoreError> {
        self.load_reward_observation(receipt_id)
    }

    fn load_native_decision_reward_observations(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionRewardObservationReceipt>, StoreError> {
        self.load_reward_observations(decision_receipt_id)
    }
}
