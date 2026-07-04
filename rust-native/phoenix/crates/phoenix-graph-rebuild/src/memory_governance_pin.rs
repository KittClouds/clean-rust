use crate::types::GraphMemoryState;

pub const MEMORY_GOVERNANCE_PIN_USER_OVERRIDE_PREFIX: &str = "user_override:";
pub const MEMORY_GOVERNANCE_PIN_PROTECTION_RATIONALE: &str = "audit:user_pinned";
pub const MEMORY_GOVERNANCE_PIN_SOURCE_RATIONALE: &str = "audit:pin_source:user_override";

pub fn memory_state_is_user_override_pin(state: &GraphMemoryState) -> bool {
    memory_state_declares_pin(state) && memory_state_has_user_override_source(state)
}

pub fn memory_state_declares_pin(state: &GraphMemoryState) -> bool {
    let key = state.key.to_ascii_lowercase();
    let value = state.value.to_ascii_lowercase();
    matches!(key.as_str(), "user_pinned" | "pinned" | "memory_pin")
        && matches!(value.as_str(), "true" | "yes" | "pinned")
}

pub fn memory_state_has_user_override_source(state: &GraphMemoryState) -> bool {
    state.evidence_ids.iter().any(|id| {
        id.as_str()
            .starts_with(MEMORY_GOVERNANCE_PIN_USER_OVERRIDE_PREFIX)
    })
}
