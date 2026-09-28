use serde_json::Value;

use crate::identity::{SELECTED_PREFIX, SUPPORT_TARGET, sha256_hex};
use crate::schema::PrimarySupport;

pub const SUPPORT_PLAN_SHA256: &str =
    "a15bca5d78867ea32905299fabd21f85cf6846a5a02a0c55dd32337e0396847f";
const SUPPORT_PLAN_BYTES: &str = include_str!("../../../plans/E4-0-SYMBOLIC-SUPPORT-PLAN-v11.json");

impl PrimarySupport {
    pub fn record_row(
        &mut self,
        context_term_id: u8,
        entity_term_id: u8,
        relation_id: u8,
        state_id: u8,
        exact_target: u8,
    ) {
        self.context_identity[context_term_id as usize] += 1;
        self.entity_identity[entity_term_id as usize] += 1;
        let stratum = lexical_stratum_index(context_term_id, entity_term_id);
        self.exact_target_by_stratum[stratum][exact_target as usize] += 1;
        if context_term_id < 16 && entity_term_id < 16 {
            self.relation[relation_id as usize] += 1;
            self.observed_state[state_id as usize] += 1;
        }
    }

    pub fn minimum_class_count(&self) -> u64 {
        self.context_identity
            .iter()
            .chain(self.entity_identity.iter())
            .chain(self.relation.iter())
            .chain(self.observed_state.iter())
            .chain(self.exact_target_by_stratum.iter().flatten())
            .copied()
            .min()
            .unwrap_or(0)
    }

    pub fn meets_target(&self) -> bool {
        self.context_identity
            .iter()
            .all(|count| *count >= SUPPORT_TARGET)
            && self
                .entity_identity
                .iter()
                .all(|count| *count >= SUPPORT_TARGET)
            && self.relation.iter().all(|count| *count >= SUPPORT_TARGET)
            && self
                .observed_state
                .iter()
                .all(|count| *count >= SUPPORT_TARGET)
            && self
                .exact_target_by_stratum
                .iter()
                .all(|classes| classes.iter().all(|count| *count >= SUPPORT_TARGET))
    }
}

pub fn lexical_stratum_index(context_term_id: u8, entity_term_id: u8) -> usize {
    match (context_term_id >= 16, entity_term_id >= 16) {
        (false, false) => 0,
        (true, false) => 1,
        (false, true) => 2,
        (true, true) => 3,
    }
}

pub fn lexical_stratum(context_term_id: u8, entity_term_id: u8) -> &'static str {
    match lexical_stratum_index(context_term_id, entity_term_id) {
        0 => "IN_DOMAIN",
        1 => "CONTEXT_NOVEL",
        2 => "ENTITY_NOVEL",
        3 => "BOTH_NOVEL",
        _ => unreachable!(),
    }
}

#[derive(Clone, Debug)]
pub struct FrozenSupportExpectation {
    pub selected_prefix: usize,
    pub candidate_counter_sum: u64,
    pub maximum_candidate_counter: u64,
    pub previous_minimum: u64,
    pub selected: PrimarySupport,
}

pub fn frozen_support_expectation() -> Result<FrozenSupportExpectation, String> {
    if sha256_hex(SUPPORT_PLAN_BYTES.as_bytes()) != SUPPORT_PLAN_SHA256 {
        return Err("embedded support plan differs from the sealed v11 planning identity".into());
    }
    let root: Value = serde_json::from_str(SUPPORT_PLAN_BYTES)
        .map_err(|error| format!("decode embedded support plan: {error}"))?;
    let selected_prefix = root["selected_whole_quartet_prefix"]
        .as_u64()
        .ok_or("support plan has no selected prefix")? as usize;
    let previous_minimum = root["minimum_class_count_at_previous_prefix"]
        .as_u64()
        .ok_or("support plan has no previous-prefix minimum")?;
    let candidate_counter_sum = root["shared_candidate_counter_sum"]
        .as_u64()
        .ok_or("support plan has no candidate-counter sum")?;
    let maximum_candidate_counter = root["maximum_candidate_counter"]
        .as_u64()
        .ok_or("support plan has no maximum candidate counter")?;
    let selected: PrimarySupport =
        serde_json::from_value(root["minimum_support_by_endpoint_and_stratum"].clone())
            .map_err(|error| format!("decode frozen support counts: {error}"))?;
    if selected_prefix != SELECTED_PREFIX
        || candidate_counter_sum != 7_915
        || maximum_candidate_counter != 8
        || previous_minimum != 248
        || selected.minimum_class_count() != 252
        || !selected.meets_target()
    {
        return Err(
            "support-plan prefix/count invariants differ from the contract-bound values".into(),
        );
    }
    Ok(FrozenSupportExpectation {
        selected_prefix,
        candidate_counter_sum,
        maximum_candidate_counter,
        previous_minimum,
        selected,
    })
}

#[cfg(test)]
mod tests {
    use super::{frozen_support_expectation, lexical_stratum};
    use crate::schema::PrimarySupport;

    #[test]
    fn lexical_partition_matches_frozen_term_id_cut() {
        assert_eq!(lexical_stratum(15, 15), "IN_DOMAIN");
        assert_eq!(lexical_stratum(16, 15), "CONTEXT_NOVEL");
        assert_eq!(lexical_stratum(15, 16), "ENTITY_NOVEL");
        assert_eq!(lexical_stratum(16, 16), "BOTH_NOVEL");
    }

    #[test]
    fn selected_prefix_receipt_is_bound_and_meets_support_without_a_bundle_average() {
        let plan = frozen_support_expectation().unwrap();
        assert_eq!(plan.selected_prefix, 18_667);
        assert_eq!(plan.candidate_counter_sum, 7_915);
        assert_eq!(plan.maximum_candidate_counter, 8);
        assert_eq!(plan.previous_minimum, 248);
        assert_eq!(plan.selected.minimum_class_count(), 252);
        assert!(plan.selected.meets_target());
        let mut support = PrimarySupport::default();
        assert!(!support.meets_target());
        support = plan.selected;
        assert!(support.meets_target());
        support.exact_target_by_stratum[3][2] = 249;
        assert!(!support.meets_target());
    }
}
