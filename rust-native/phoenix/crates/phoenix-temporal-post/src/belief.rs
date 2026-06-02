use std::collections::BTreeMap;

use phoenix_semantic_v2::{
    BeliefStateAtom, BeliefStateCard, TemporalTruthStatus, TemporalWorldlineId,
};
use phoenix_time::TimeKernel;
use rustc_hash::FxHashMap;

pub fn build_belief_state_cards(
    atoms: &[BeliefStateAtom],
    created_at: i64,
) -> Vec<BeliefStateCard> {
    let mut groups = FxHashMap::<BeliefGroupKey, Vec<&BeliefStateAtom>>::default();
    for atom in atoms {
        groups
            .entry(BeliefGroupKey::from(atom))
            .or_default()
            .push(atom);
    }

    let mut ordered = groups.into_iter().collect::<Vec<_>>();
    ordered.sort_by(|left, right| left.0.cmp(&right.0));
    ordered
        .into_iter()
        .filter_map(|(key, atoms)| belief_card(key, atoms, created_at))
        .collect()
}

fn belief_card(
    key: BeliefGroupKey,
    atoms: Vec<&BeliefStateAtom>,
    created_at: i64,
) -> Option<BeliefStateCard> {
    let strongest = atoms
        .iter()
        .max_by(|left, right| belief_rank(left).cmp(&belief_rank(right)))?;
    let conflict_ids = conflict_ids(&key, &atoms);
    let temporal = TimeKernel::merge_windows(
        atoms.iter().map(|atom| atom.temporal.clone()),
        Some(created_at),
    );

    Some(BeliefStateCard {
        card_id: format!("bcard:{}", key.stable_id()),
        document_id: strongest.document_id.clone(),
        event_id: strongest.event_id.clone(),
        canonical_event_id: strongest.canonical_event_id.clone(),
        observer_entity_id: strongest.observer_entity_id.clone(),
        axis_id: strongest.axis_id.clone(),
        worldline_id: strongest.worldline_id.clone(),
        strongest_kind: strongest.kind,
        strongest_truth_status: strongest.truth_status,
        confidence_millis: strongest.confidence_millis,
        temporal,
        source_belief_ids: sorted_unique(atoms.iter().map(|atom| atom.belief_id.clone())),
        open_conflict_ids: conflict_ids,
        evidence_refs: sorted_unique(atoms.iter().flat_map(|atom| atom.evidence_refs.clone())),
    })
}

fn belief_rank(atom: &BeliefStateAtom) -> (u8, u32, &str) {
    (
        atom.truth_status.rank(),
        atom.confidence_millis,
        atom.belief_id.as_str(),
    )
}

fn conflict_ids(key: &BeliefGroupKey, atoms: &[&BeliefStateAtom]) -> Vec<String> {
    let mut positive = false;
    let mut negative = false;
    for atom in atoms {
        match atom.truth_status {
            TemporalTruthStatus::Observed
            | TemporalTruthStatus::Asserted
            | TemporalTruthStatus::Inferred => positive = true,
            TemporalTruthStatus::Negated | TemporalTruthStatus::Contradicted => negative = true,
            _ => {}
        }
    }
    if positive && negative {
        vec![format!("belief-conflict:{}", key.stable_id())]
    } else {
        Vec::new()
    }
}

fn sorted_unique<I>(values: I) -> Vec<String>
where
    I: Iterator<Item = String>,
{
    let mut rows = values.collect::<Vec<_>>();
    rows.sort();
    rows.dedup();
    rows
}

#[derive(Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
struct BeliefGroupKey {
    document_id: String,
    observer_id: String,
    event_id: String,
    axis_id: String,
    worldline_id: String,
}

impl BeliefGroupKey {
    fn from(atom: &BeliefStateAtom) -> Self {
        Self {
            document_id: atom.document_id.clone(),
            observer_id: atom
                .observer_entity_id
                .as_ref()
                .map(|id| id.0.clone())
                .unwrap_or_else(|| "observer:narrator".to_owned()),
            event_id: atom
                .canonical_event_id
                .as_ref()
                .map(|id| id.0.clone())
                .or_else(|| atom.event_id.clone())
                .unwrap_or_else(|| "event:unknown".to_owned()),
            axis_id: atom.axis_id.0.clone(),
            worldline_id: atom.worldline_id.0.clone(),
        }
    }

    fn stable_id(&self) -> String {
        format!(
            "{}:{}:{}:{}:{}",
            self.document_id, self.observer_id, self.event_id, self.axis_id, self.worldline_id
        )
    }
}

pub fn truth_status_counts(atoms: &[BeliefStateAtom]) -> BTreeMap<String, usize> {
    let mut rows = BTreeMap::<String, usize>::new();
    for atom in atoms {
        *rows
            .entry(atom.truth_status.as_key().to_owned())
            .or_default() += 1;
    }
    rows
}

pub fn default_worldline() -> TemporalWorldlineId {
    TemporalWorldlineId("worldline:main".to_owned())
}

#[cfg(test)]
mod tests {
    use phoenix_semantic_v2::{BeliefSourceKind, BeliefStateKind, TemporalAxisId};
    use phoenix_types::BiTemporalWindow;

    use super::*;

    #[test]
    fn observed_belief_beats_reported_belief_for_same_event() {
        let atoms = vec![
            atom("b1", TemporalTruthStatus::Reported, 700),
            atom("b2", TemporalTruthStatus::Observed, 620),
        ];

        let cards = build_belief_state_cards(&atoms, 100);

        assert_eq!(cards.len(), 1);
        assert_eq!(
            cards[0].strongest_truth_status,
            TemporalTruthStatus::Observed
        );
        assert!(cards[0].open_conflict_ids.is_empty());
    }

    #[test]
    fn asserted_and_negated_beliefs_create_conflict() {
        let atoms = vec![
            atom("b1", TemporalTruthStatus::Asserted, 800),
            atom("b2", TemporalTruthStatus::Negated, 760),
        ];

        let cards = build_belief_state_cards(&atoms, 100);

        assert_eq!(cards.len(), 1);
        assert_eq!(cards[0].open_conflict_ids.len(), 1);
    }

    fn atom(id: &str, truth_status: TemporalTruthStatus, confidence: u32) -> BeliefStateAtom {
        BeliefStateAtom {
            belief_id: id.to_owned(),
            document_id: "doc".to_owned(),
            proposition_id: Some("prop".to_owned()),
            event_id: Some("event".to_owned()),
            axis_id: TemporalAxisId("axis:world".to_owned()),
            worldline_id: default_worldline(),
            kind: BeliefStateKind::Believes,
            truth_status,
            source_kind: BeliefSourceKind::Narration,
            confidence_millis: confidence,
            temporal: BiTemporalWindow {
                valid_from: Some(10),
                valid_to: Some(10),
                recorded_from: Some(100),
                recorded_to: None,
            },
            ..BeliefStateAtom::default()
        }
    }
}
