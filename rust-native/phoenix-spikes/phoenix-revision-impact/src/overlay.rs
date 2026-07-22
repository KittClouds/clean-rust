use std::collections::{BTreeMap, BTreeSet};

use compact_str::CompactString;
use phoenix_types::{
    EntityId, FactId, FactValue, GraphTruthDigest, StateKind, StoryInterval, StoryMutation,
    StoryTime,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const COUNTERFACTUAL_OVERLAY_SCHEMA: &str = "phoenix-counterfactual-overlay/v1";

#[derive(
    Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
)]
#[serde(transparent)]
pub struct GraphGeneration(pub u64);

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StateRef {
    pub subject_id: EntityId,
    pub state_kind: StateKind,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionFactRecord {
    pub fact_id: FactId,
    pub value: FactValue,
    pub interval: StoryInterval,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionStateRecord {
    pub state_ref: StateRef,
    pub value: FactValue,
    pub interval: StoryInterval,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionEdgeRecord {
    pub edge_id: CompactString,
    #[serde(default)]
    pub dependency_fact_ids: Vec<FactId>,
    #[serde(default)]
    pub dependency_state_refs: Vec<StateRef>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NamedSidecarDigest {
    pub sidecar_id: CompactString,
    pub digest: GraphTruthDigest,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RevisionGraphSnapshot {
    generation: GraphGeneration,
    facts: Vec<RevisionFactRecord>,
    states: Vec<RevisionStateRecord>,
    edges: Vec<RevisionEdgeRecord>,
    sidecar_digests: Vec<NamedSidecarDigest>,
}

impl RevisionGraphSnapshot {
    pub fn new(
        generation: GraphGeneration,
        mut facts: Vec<RevisionFactRecord>,
        mut states: Vec<RevisionStateRecord>,
        mut edges: Vec<RevisionEdgeRecord>,
        mut sidecar_digests: Vec<NamedSidecarDigest>,
    ) -> Result<Self, CounterfactualOverlayError> {
        facts.sort_unstable_by(|left, right| left.fact_id.cmp(&right.fact_id));
        states.sort_unstable_by(|left, right| left.state_ref.cmp(&right.state_ref));
        edges.sort_unstable_by(|left, right| left.edge_id.cmp(&right.edge_id));
        sidecar_digests.sort_unstable_by(|left, right| left.sidecar_id.cmp(&right.sidecar_id));

        reject_duplicate(facts.iter().map(|fact| fact.fact_id.0.as_str()), "fact")?;
        reject_duplicate(
            states
                .iter()
                .map(|state| state_ref_key(&state.state_ref))
                .map(|key| key.to_string()),
            "state",
        )?;
        reject_duplicate(edges.iter().map(|edge| edge.edge_id.as_str()), "edge")?;
        reject_duplicate(
            sidecar_digests
                .iter()
                .map(|sidecar| sidecar.sidecar_id.as_str()),
            "sidecar",
        )?;

        if let Some(fact) = facts.iter().find(|fact| !fact.interval.is_well_formed()) {
            return Err(CounterfactualOverlayError::InvalidInterval(
                fact.fact_id.0.clone(),
            ));
        }
        if let Some(state) = states.iter().find(|state| !state.interval.is_well_formed()) {
            return Err(CounterfactualOverlayError::InvalidInterval(state_ref_key(
                &state.state_ref,
            )));
        }
        if let Some(sidecar) = sidecar_digests
            .iter()
            .find(|sidecar| sidecar.digest.is_zero())
        {
            return Err(CounterfactualOverlayError::ZeroSidecarDigest(
                sidecar.sidecar_id.clone(),
            ));
        }

        for edge in &mut edges {
            edge.dependency_fact_ids.sort_unstable();
            edge.dependency_fact_ids.dedup();
            edge.dependency_state_refs.sort_unstable();
            edge.dependency_state_refs.dedup();
        }

        Ok(Self {
            generation,
            facts,
            states,
            edges,
            sidecar_digests,
        })
    }

    pub const fn generation(&self) -> GraphGeneration {
        self.generation
    }

    pub fn facts(&self) -> &[RevisionFactRecord] {
        &self.facts
    }

    pub fn states(&self) -> &[RevisionStateRecord] {
        &self.states
    }

    pub fn edges(&self) -> &[RevisionEdgeRecord] {
        &self.edges
    }

    pub fn sidecar_digests(&self) -> &[NamedSidecarDigest] {
        &self.sidecar_digests
    }

    pub fn fact(&self, fact_id: &FactId) -> Option<&RevisionFactRecord> {
        self.facts
            .binary_search_by(|fact| fact.fact_id.cmp(fact_id))
            .ok()
            .map(|index| &self.facts[index])
    }

    pub fn state(&self, state_ref: &StateRef) -> Option<&RevisionStateRecord> {
        self.states
            .binary_search_by(|state| state.state_ref.cmp(state_ref))
            .ok()
            .map(|index| &self.states[index])
    }

    pub fn digest(&self) -> GraphTruthDigest {
        let mut hasher = blake3::Hasher::new();
        hash_bytes(&mut hasher, COUNTERFACTUAL_OVERLAY_SCHEMA.as_bytes());
        hash_u64(&mut hasher, self.generation.0);
        for fact in &self.facts {
            hash_fact(&mut hasher, fact);
        }
        for state in &self.states {
            hash_state(&mut hasher, state);
        }
        for edge in &self.edges {
            hash_string(&mut hasher, &edge.edge_id);
            for fact_id in &edge.dependency_fact_ids {
                hash_string(&mut hasher, &fact_id.0);
            }
            for state_ref in &edge.dependency_state_refs {
                hash_state_ref(&mut hasher, state_ref);
            }
        }
        for sidecar in &self.sidecar_digests {
            hash_string(&mut hasher, &sidecar.sidecar_id);
            hasher.update(&sidecar.digest.0);
        }
        GraphTruthDigest(*hasher.finalize().as_bytes())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    content = "fact",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum FactOverlayEntry {
    Retracted,
    Replaced(RevisionFactRecord),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CounterfactualOverlayReceipt {
    pub schema_version: CompactString,
    pub base_generation: GraphGeneration,
    pub base_digest: GraphTruthDigest,
    pub mutation_digest: GraphTruthDigest,
    pub changed_fact_ids: Vec<FactId>,
    pub changed_state_refs: Vec<StateRef>,
    pub invalidated_edge_ids: Vec<CompactString>,
    pub base_sidecar_digests: Vec<NamedSidecarDigest>,
    pub no_base_writes: bool,
}

#[derive(Debug)]
pub struct CounterfactualGraphView<'a> {
    base: &'a RevisionGraphSnapshot,
    pub base_generation: GraphGeneration,
    pub mutations: Vec<StoryMutation>,
    pub overridden_facts: BTreeMap<FactId, FactOverlayEntry>,
    pub invalidated_edges: BTreeSet<CompactString>,
    pub derived_state: BTreeMap<StateRef, RevisionStateRecord>,
    pub receipt: CounterfactualOverlayReceipt,
}

impl<'a> CounterfactualGraphView<'a> {
    pub fn new(
        base: &'a RevisionGraphSnapshot,
        mutations: Vec<StoryMutation>,
    ) -> Result<Self, CounterfactualOverlayError> {
        let mut ordered = mutations
            .into_iter()
            .map(|mutation| (mutation_target(&mutation), mutation))
            .collect::<Vec<_>>();
        ordered.sort_unstable_by(|left, right| left.0.cmp(&right.0));
        if let Some(pair) = ordered.windows(2).find(|pair| pair[0].0 == pair[1].0) {
            return Err(CounterfactualOverlayError::ConflictingMutation(
                pair[0].0.label(),
            ));
        }

        let mutations = ordered
            .iter()
            .map(|(_, mutation)| mutation.clone())
            .collect::<Vec<_>>();
        let mut overridden_facts = BTreeMap::new();
        let mut derived_state = BTreeMap::new();
        let mut changed_fact_ids = BTreeSet::new();
        let mut changed_state_refs = BTreeSet::new();

        for (_, mutation) in ordered {
            match mutation {
                StoryMutation::RetractFact { fact_id } => {
                    require_fact(base, &fact_id)?;
                    changed_fact_ids.insert(fact_id.clone());
                    overridden_facts.insert(fact_id, FactOverlayEntry::Retracted);
                }
                StoryMutation::SupersedeFact {
                    fact_id,
                    replacement,
                    valid_from,
                } => {
                    let existing = require_fact(base, &fact_id)?;
                    let valid_to_exclusive = existing
                        .interval
                        .valid_to_exclusive
                        .filter(|end| valid_from < *end);
                    changed_fact_ids.insert(fact_id.clone());
                    overridden_facts.insert(
                        fact_id.clone(),
                        FactOverlayEntry::Replaced(RevisionFactRecord {
                            fact_id,
                            value: replacement,
                            interval: StoryInterval {
                                valid_from,
                                valid_to_exclusive,
                            },
                        }),
                    );
                }
                StoryMutation::ShiftValidity {
                    fact_id,
                    new_interval,
                } => {
                    if !new_interval.is_well_formed() {
                        return Err(CounterfactualOverlayError::InvalidInterval(
                            fact_id.0.clone(),
                        ));
                    }
                    let existing = require_fact(base, &fact_id)?;
                    changed_fact_ids.insert(fact_id.clone());
                    overridden_facts.insert(
                        fact_id.clone(),
                        FactOverlayEntry::Replaced(RevisionFactRecord {
                            fact_id,
                            value: existing.value.clone(),
                            interval: new_interval,
                        }),
                    );
                }
                StoryMutation::ChangeState {
                    subject_id,
                    state_kind,
                    replacement,
                    valid_from,
                } => {
                    let state_ref = StateRef {
                        subject_id,
                        state_kind,
                    };
                    changed_state_refs.insert(state_ref.clone());
                    derived_state.insert(
                        state_ref.clone(),
                        RevisionStateRecord {
                            state_ref,
                            value: replacement,
                            interval: StoryInterval {
                                valid_from,
                                valid_to_exclusive: None,
                            },
                        },
                    );
                }
            }
        }

        let invalidated_edges = base
            .edges
            .iter()
            .filter(|edge| {
                edge.dependency_fact_ids
                    .iter()
                    .any(|fact_id| changed_fact_ids.contains(fact_id))
                    || edge
                        .dependency_state_refs
                        .iter()
                        .any(|state_ref| changed_state_refs.contains(state_ref))
            })
            .map(|edge| edge.edge_id.clone())
            .collect::<BTreeSet<_>>();
        let base_digest = base.digest();
        let mutation_digest = digest_mutations(&mutations);
        let receipt = CounterfactualOverlayReceipt {
            schema_version: COUNTERFACTUAL_OVERLAY_SCHEMA.into(),
            base_generation: base.generation,
            base_digest,
            mutation_digest,
            changed_fact_ids: changed_fact_ids.into_iter().collect(),
            changed_state_refs: changed_state_refs.into_iter().collect(),
            invalidated_edge_ids: invalidated_edges.iter().cloned().collect(),
            base_sidecar_digests: base.sidecar_digests.clone(),
            no_base_writes: true,
        };

        Ok(Self {
            base,
            base_generation: base.generation,
            mutations,
            overridden_facts,
            invalidated_edges,
            derived_state,
            receipt,
        })
    }

    pub const fn base(&self) -> &'a RevisionGraphSnapshot {
        self.base
    }

    pub fn effective_fact(&self, fact_id: &FactId) -> Option<&RevisionFactRecord> {
        match self.overridden_facts.get(fact_id) {
            Some(FactOverlayEntry::Retracted) => None,
            Some(FactOverlayEntry::Replaced(fact)) => Some(fact),
            None => self.base.fact(fact_id),
        }
    }

    pub fn effective_state(&self, state_ref: &StateRef) -> Option<&RevisionStateRecord> {
        self.derived_state
            .get(state_ref)
            .or_else(|| self.base.state(state_ref))
    }

    pub fn fact_satisfies(
        &self,
        fact_id: &FactId,
        expected: &FactValue,
        required: StoryInterval,
    ) -> bool {
        match self.overridden_facts.get(fact_id) {
            Some(FactOverlayEntry::Retracted) => false,
            Some(FactOverlayEntry::Replaced(replacement)) => {
                if fact_record_satisfies(replacement, expected, required) {
                    return true;
                }
                let superseded_after_requirement = self.mutations.iter().any(|mutation| {
                    matches!(
                        mutation,
                        StoryMutation::SupersedeFact {
                            fact_id: target,
                            valid_from,
                            ..
                        } if target == fact_id && interval_precedes(required, *valid_from)
                    )
                });
                superseded_after_requirement
                    && self
                        .base
                        .fact(fact_id)
                        .is_some_and(|fact| fact_record_satisfies(fact, expected, required))
            }
            None => self
                .base
                .fact(fact_id)
                .is_some_and(|fact| fact_record_satisfies(fact, expected, required)),
        }
    }

    pub fn state_satisfies(
        &self,
        state_ref: &StateRef,
        expected: &FactValue,
        required: StoryInterval,
    ) -> bool {
        if let Some(state) = self.derived_state.get(state_ref) {
            if state_record_satisfies(state, expected, required) {
                return true;
            }
            if interval_precedes(required, state.interval.valid_from) {
                return self
                    .base
                    .state(state_ref)
                    .is_some_and(|base| state_record_satisfies(base, expected, required));
            }
            return false;
        }
        self.base
            .state(state_ref)
            .is_some_and(|state| state_record_satisfies(state, expected, required))
    }

    pub fn edge_is_invalidated(&self, edge_id: &str) -> bool {
        self.invalidated_edges.contains(edge_id)
    }
}

fn fact_record_satisfies(
    fact: &RevisionFactRecord,
    expected: &FactValue,
    required: StoryInterval,
) -> bool {
    fact.value == *expected && interval_contains(fact.interval, required)
}

fn state_record_satisfies(
    state: &RevisionStateRecord,
    expected: &FactValue,
    required: StoryInterval,
) -> bool {
    state.value == *expected && interval_contains(state.interval, required)
}

fn interval_precedes(required: StoryInterval, boundary: StoryTime) -> bool {
    required
        .valid_to_exclusive
        .is_some_and(|end| end <= boundary)
}

fn interval_contains(outer: StoryInterval, inner: StoryInterval) -> bool {
    outer.valid_from <= inner.valid_from
        && match (outer.valid_to_exclusive, inner.valid_to_exclusive) {
            (None, _) => true,
            (Some(_), None) => false,
            (Some(outer_end), Some(inner_end)) => inner_end <= outer_end,
        }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum MutationTarget {
    Fact(FactId),
    State(StateRef),
}

impl MutationTarget {
    fn label(&self) -> CompactString {
        match self {
            Self::Fact(fact_id) => format!("fact:{}", fact_id.0).into(),
            Self::State(state_ref) => state_ref_key(state_ref),
        }
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum CounterfactualOverlayError {
    #[error("duplicate {kind} record {id}")]
    DuplicateRecord {
        kind: &'static str,
        id: CompactString,
    },
    #[error("missing fact {0}")]
    MissingFact(CompactString),
    #[error("conflicting mutations target {0}")]
    ConflictingMutation(CompactString),
    #[error("invalid interval for {0}")]
    InvalidInterval(CompactString),
    #[error("sidecar {0} has a zero digest")]
    ZeroSidecarDigest(CompactString),
}

fn mutation_target(mutation: &StoryMutation) -> MutationTarget {
    match mutation {
        StoryMutation::RetractFact { fact_id }
        | StoryMutation::SupersedeFact { fact_id, .. }
        | StoryMutation::ShiftValidity { fact_id, .. } => MutationTarget::Fact(fact_id.clone()),
        StoryMutation::ChangeState {
            subject_id,
            state_kind,
            ..
        } => MutationTarget::State(StateRef {
            subject_id: subject_id.clone(),
            state_kind: state_kind.clone(),
        }),
    }
}

fn require_fact<'a>(
    base: &'a RevisionGraphSnapshot,
    fact_id: &FactId,
) -> Result<&'a RevisionFactRecord, CounterfactualOverlayError> {
    base.fact(fact_id)
        .ok_or_else(|| CounterfactualOverlayError::MissingFact(fact_id.0.clone()))
}

fn reject_duplicate<I, S>(values: I, kind: &'static str) -> Result<(), CounterfactualOverlayError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut previous = None::<String>;
    for value in values {
        let value = value.as_ref();
        if previous.as_deref() == Some(value) {
            return Err(CounterfactualOverlayError::DuplicateRecord {
                kind,
                id: value.into(),
            });
        }
        previous = Some(value.to_owned());
    }
    Ok(())
}

fn digest_mutations(mutations: &[StoryMutation]) -> GraphTruthDigest {
    let mut hasher = blake3::Hasher::new();
    hash_bytes(&mut hasher, COUNTERFACTUAL_OVERLAY_SCHEMA.as_bytes());
    for mutation in mutations {
        match mutation {
            StoryMutation::RetractFact { fact_id } => {
                hash_u8(&mut hasher, 0);
                hash_string(&mut hasher, &fact_id.0);
            }
            StoryMutation::SupersedeFact {
                fact_id,
                replacement,
                valid_from,
            } => {
                hash_u8(&mut hasher, 1);
                hash_string(&mut hasher, &fact_id.0);
                hash_fact_value(&mut hasher, replacement);
                hash_i64(&mut hasher, valid_from.0);
            }
            StoryMutation::ShiftValidity {
                fact_id,
                new_interval,
            } => {
                hash_u8(&mut hasher, 2);
                hash_string(&mut hasher, &fact_id.0);
                hash_interval(&mut hasher, *new_interval);
            }
            StoryMutation::ChangeState {
                subject_id,
                state_kind,
                replacement,
                valid_from,
            } => {
                hash_u8(&mut hasher, 3);
                hash_string(&mut hasher, &subject_id.0);
                hash_string(&mut hasher, &state_kind.0);
                hash_fact_value(&mut hasher, replacement);
                hash_i64(&mut hasher, valid_from.0);
            }
        }
    }
    GraphTruthDigest(*hasher.finalize().as_bytes())
}

fn hash_fact(hasher: &mut blake3::Hasher, fact: &RevisionFactRecord) {
    hash_string(hasher, &fact.fact_id.0);
    hash_fact_value(hasher, &fact.value);
    hash_interval(hasher, fact.interval);
}

fn hash_state(hasher: &mut blake3::Hasher, state: &RevisionStateRecord) {
    hash_state_ref(hasher, &state.state_ref);
    hash_fact_value(hasher, &state.value);
    hash_interval(hasher, state.interval);
}

fn hash_state_ref(hasher: &mut blake3::Hasher, state_ref: &StateRef) {
    hash_string(hasher, &state_ref.subject_id.0);
    hash_string(hasher, &state_ref.state_kind.0);
}

fn hash_fact_value(hasher: &mut blake3::Hasher, value: &FactValue) {
    match value {
        FactValue::Boolean(value) => {
            hash_u8(hasher, 0);
            hash_u8(hasher, u8::from(*value));
        }
        FactValue::Integer(value) => {
            hash_u8(hasher, 1);
            hash_i64(hasher, *value);
        }
        FactValue::Text(value) => {
            hash_u8(hasher, 2);
            hash_string(hasher, value);
        }
        FactValue::Entity(value) => {
            hash_u8(hasher, 3);
            hash_string(hasher, &value.0);
        }
        FactValue::DurationMinutes(value) => {
            hash_u8(hasher, 4);
            hash_i64(hasher, *value);
        }
    }
}

fn hash_interval(hasher: &mut blake3::Hasher, interval: StoryInterval) {
    hash_i64(hasher, interval.valid_from.0);
    match interval.valid_to_exclusive {
        Some(end) => {
            hash_u8(hasher, 1);
            hash_i64(hasher, end.0);
        }
        None => hash_u8(hasher, 0),
    }
}

fn hash_string(hasher: &mut blake3::Hasher, value: &str) {
    hash_bytes(hasher, value.as_bytes());
}

fn hash_bytes(hasher: &mut blake3::Hasher, bytes: &[u8]) {
    hasher.update(&(bytes.len() as u64).to_le_bytes());
    hasher.update(bytes);
}

fn hash_u64(hasher: &mut blake3::Hasher, value: u64) {
    hasher.update(&value.to_le_bytes());
}

fn hash_i64(hasher: &mut blake3::Hasher, value: i64) {
    hasher.update(&value.to_le_bytes());
}

fn hash_u8(hasher: &mut blake3::Hasher, value: u8) {
    hasher.update(&[value]);
}

fn state_ref_key(state_ref: &StateRef) -> CompactString {
    format!(
        "state:{}:{}",
        state_ref.subject_id.0, state_ref.state_kind.0
    )
    .into()
}

#[cfg(test)]
#[path = "overlay_tests.rs"]
mod tests;
