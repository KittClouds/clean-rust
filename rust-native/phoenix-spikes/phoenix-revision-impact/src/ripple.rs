use std::cmp::Ordering;
use std::collections::BTreeMap;

use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;
use phoenix_types::{ConstraintKind, DependencyClass, ImpactClassification};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;
use thiserror::Error;

use crate::{
    evaluate_requirement, ConstraintAtom, ConstraintGraph, CounterfactualGraphView,
    GraphGeneration, RequirementEvaluation, RevisionRequirementRecord, RevisionRequirementSidecar,
};

#[path = "ripple_scc.rs"]
mod scc;
use scc::condense_scc;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RippleConfig {
    pub max_representative_paths: usize,
    pub max_path_length: usize,
    pub max_signals_per_component: usize,
    pub max_visited_states: usize,
    pub max_traversed_edges: usize,
    pub min_soft_score_millis: u16,
}

impl Default for RippleConfig {
    fn default() -> Self {
        Self {
            max_representative_paths: 3,
            max_path_length: 32,
            max_signals_per_component: 64,
            max_visited_states: 100_000,
            max_traversed_edges: 500_000,
            min_soft_score_millis: 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ImpactPath {
    pub source_id: CompactString,
    pub origin_evidence_id: CompactString,
    pub node_ids: Vec<CompactString>,
    pub constraint_ids: Vec<CompactString>,
    pub evidence_ids: Vec<CompactString>,
    pub classification: ImpactClassification,
    pub score_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RippleImpact {
    pub dependent_id: CompactString,
    pub classification: ImpactClassification,
    pub score_millis: u16,
    pub violated_constraints: Vec<CompactString>,
    pub support_loss_constraints: Vec<CompactString>,
    pub causal_paths: Vec<ImpactPath>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RippleTruncation {
    pub visited_state_limit_hit: bool,
    pub traversed_edge_limit_hit: bool,
    pub path_length_drops: usize,
    pub component_signal_drops: usize,
    pub representative_path_drops: usize,
}

impl RippleTruncation {
    pub const fn truncated(&self) -> bool {
        self.visited_state_limit_hit
            || self.traversed_edge_limit_hit
            || self.path_length_drops > 0
            || self.component_signal_drops > 0
            || self.representative_path_drops > 0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RippleRunReceipt {
    pub generation: GraphGeneration,
    pub seed_source_ids: Vec<CompactString>,
    pub unmatched_seed_ids: Vec<CompactString>,
    pub strongly_connected_components: usize,
    pub condensed_edges: usize,
    pub visited_states: usize,
    pub traversed_edges: usize,
    pub truncation: RippleTruncation,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CausalRippleResult {
    pub impacts: Vec<RippleImpact>,
    pub receipt: RippleRunReceipt,
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum RippleError {
    #[error("generation mismatch: overlay={overlay}, constraints={constraints}, requirements={requirements}")]
    GenerationMismatch {
        overlay: u64,
        constraints: u64,
        requirements: u64,
    },
    #[error("invalid ripple configuration")]
    InvalidConfig,
    #[error("duplicate requirement validator {0}")]
    DuplicateRequirement(CompactString),
    #[error("hard constraint {0} has no validator")]
    MissingHardValidator(CompactString),
    #[error("graph index exceeds u32 capacity")]
    IndexOverflow,
}

pub fn causal_ripple_search(
    overlay: &CounterfactualGraphView<'_>,
    graph: &ConstraintGraph,
    requirements: &RevisionRequirementSidecar,
    config: RippleConfig,
) -> Result<CausalRippleResult, RippleError> {
    validate_inputs(overlay, graph, requirements, config)?;
    let validators = requirement_index(requirements)?;
    let scc = condense_scc(graph)?;
    let mut path_arena = PathArena::with_capacity(graph.atoms().len());
    let mut component_signals = std::iter::repeat_with(SignalBuffer::new)
        .take(scc.component_count)
        .collect::<Vec<_>>();
    let seed_source_ids = changed_source_ids(overlay);
    let mut unmatched_seed_ids = Vec::new();
    for source_id in &seed_source_ids {
        if let Some(node) = graph.node_index(source_id) {
            let path_index = path_arena.push_root(node)?;
            component_signals[scc.component_of[node as usize]]
                .push(NodeSignal::root(node, source_id, path_index));
        } else {
            unmatched_seed_ids.push(source_id.clone());
        }
    }

    let mut accumulators = BTreeMap::<u32, ImpactAccumulator>::new();
    let mut visited_states = 0;
    let mut traversed_edges = 0;
    let mut truncation = RippleTruncation::default();
    let mut halted = false;

    for &component in &scc.topological_order {
        if halted {
            break;
        }
        canonicalize_signals(
            &mut component_signals[component],
            config.max_signals_per_component,
            &mut truncation,
        );
        let initial = std::mem::take(&mut component_signals[component]);
        for signal in initial {
            if halted {
                break;
            }
            let mut queue = SignalQueue::new();
            queue.push(signal);
            let mut best = BestStates::new();
            while !queue.is_empty() {
                let signal = queue.remove(0);
                if !record_best(&mut best, &signal) {
                    continue;
                }
                if visited_states >= config.max_visited_states {
                    truncation.visited_state_limit_hit = true;
                    halted = true;
                    break;
                }
                visited_states += 1;
                let (atom_start, outgoing) = graph.outgoing_with_start(signal.node);
                for (offset, atom) in outgoing.iter().enumerate() {
                    if traversed_edges >= config.max_traversed_edges {
                        truncation.traversed_edge_limit_hit = true;
                        halted = true;
                        break;
                    }
                    traversed_edges += 1;
                    let atom_index = atom_start
                        .checked_add(u32::try_from(offset).map_err(|_| RippleError::IndexOverflow)?)
                        .ok_or(RippleError::IndexOverflow)?;
                    let Some(next) = transition(
                        overlay,
                        (atom, atom_index),
                        &signal,
                        &validators,
                        config,
                        &mut truncation,
                        &mut path_arena,
                    )?
                    else {
                        continue;
                    };
                    accumulators
                        .entry(atom.dependent)
                        .or_default()
                        .record(atom, &next);
                    let target_component = scc.component_of[atom.dependent as usize];
                    if target_component == component {
                        queue.push(next);
                    } else {
                        component_signals[target_component].push(next);
                    }
                }
            }
        }
    }

    let strongly_connected_components = scc.component_count;
    let condensed_edges = scc.condensed_edges;
    drop(component_signals);
    drop(scc);
    let impacts = finalize_impacts(
        graph,
        &path_arena,
        accumulators,
        config.max_representative_paths,
        &mut truncation,
    );
    Ok(CausalRippleResult {
        impacts,
        receipt: RippleRunReceipt {
            generation: graph.generation(),
            seed_source_ids,
            unmatched_seed_ids,
            strongly_connected_components,
            condensed_edges,
            visited_states,
            traversed_edges,
            truncation,
        },
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SignalMode {
    Root,
    HardBroken,
    SoftLoss,
}

impl SignalMode {
    const fn rank(self) -> u8 {
        match self {
            Self::Root => 0,
            Self::SoftLoss => 1,
            Self::HardBroken => 2,
        }
    }

    const fn classification(self) -> ImpactClassification {
        match self {
            Self::HardBroken => ImpactClassification::Broken,
            Self::Root | Self::SoftLoss => ImpactClassification::Suspicious,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct NodeSignal {
    node: u32,
    mode: SignalMode,
    score_millis: u16,
    origin_evidence_id: CompactString,
    path_index: u32,
    depth: usize,
}

type SignalBuffer = SmallVec<[NodeSignal; 1]>;
type SignalQueue = SmallVec<[NodeSignal; 4]>;

impl NodeSignal {
    fn root(node: u32, source_id: &str, path_index: u32) -> Self {
        Self {
            node,
            mode: SignalMode::Root,
            score_millis: 1000,
            origin_evidence_id: format_compact!("seed:{source_id}"),
            path_index,
            depth: 0,
        }
    }
}

struct PathNode {
    parent: u32,
    node: u32,
    atom_index: u32,
}

const NO_PATH_INDEX: u32 = u32::MAX;

struct PathArena {
    rows: Vec<PathNode>,
}

impl PathArena {
    fn with_capacity(edge_count: usize) -> Self {
        Self {
            rows: Vec::with_capacity(edge_count.saturating_add(1)),
        }
    }

    fn push_root(&mut self, node: u32) -> Result<u32, RippleError> {
        self.push(PathNode {
            parent: NO_PATH_INDEX,
            node,
            atom_index: NO_PATH_INDEX,
        })
    }

    fn extend(&mut self, parent: u32, node: u32, atom_index: u32) -> Result<u32, RippleError> {
        self.push(PathNode {
            parent,
            node,
            atom_index,
        })
    }

    fn push(&mut self, row: PathNode) -> Result<u32, RippleError> {
        let index = u32::try_from(self.rows.len()).map_err(|_| RippleError::IndexOverflow)?;
        if index == NO_PATH_INDEX {
            return Err(RippleError::IndexOverflow);
        }
        self.rows.push(row);
        Ok(index)
    }

    fn materialize(
        &self,
        graph: &ConstraintGraph,
        path_index: u32,
        origin_evidence_id: CompactString,
        classification: ImpactClassification,
        score_millis: u16,
    ) -> ImpactPath {
        let mut chain = SmallVec::<[&PathNode; 16]>::new();
        let mut cursor = path_index;
        loop {
            let row = &self.rows[cursor as usize];
            chain.push(row);
            if row.parent == NO_PATH_INDEX {
                break;
            }
            cursor = row.parent;
        }
        chain.reverse();

        let mut node_ids = Vec::with_capacity(chain.len());
        let mut constraint_ids = Vec::with_capacity(chain.len().saturating_sub(1));
        let mut evidence_ids = Vec::with_capacity(1);
        for row in chain {
            node_ids.push(graph.nodes()[row.node as usize].id.clone());
            if row.atom_index != NO_PATH_INDEX {
                let atom = &graph.atoms()[row.atom_index as usize];
                constraint_ids.push(atom.constraint_id.clone());
                for evidence in &atom.evidence {
                    if let Err(index) = evidence_ids.binary_search(&evidence.evidence_id) {
                        evidence_ids.insert(index, evidence.evidence_id.clone());
                    }
                }
            }
        }
        ImpactPath {
            source_id: node_ids[0].clone(),
            origin_evidence_id,
            node_ids,
            constraint_ids,
            evidence_ids,
            classification,
            score_millis,
        }
    }
}

fn transition(
    overlay: &CounterfactualGraphView<'_>,
    atom_entry: (&ConstraintAtom, u32),
    signal: &NodeSignal,
    validators: &HashMap<&str, &RevisionRequirementRecord>,
    config: RippleConfig,
    truncation: &mut RippleTruncation,
    path_arena: &mut PathArena,
) -> Result<Option<NodeSignal>, RippleError> {
    let (atom, atom_index) = atom_entry;
    if signal.depth >= config.max_path_length {
        truncation.path_length_drops += 1;
        return Ok(None);
    }
    let (mode, score_millis) = if atom.strength == DependencyClass::HardRequirement {
        let requirement = validators
            .get(atom.constraint_id.as_str())
            .ok_or_else(|| RippleError::MissingHardValidator(atom.constraint_id.clone()))?;
        if evaluate_requirement(overlay, requirement) != RequirementEvaluation::Violated {
            return Ok(None);
        }
        (SignalMode::HardBroken, 1000)
    } else {
        let score = u32::from(signal.score_millis) * u32::from(edge_weight(atom.kind)) / 1000;
        let score = score as u16;
        if score < config.min_soft_score_millis {
            return Ok(None);
        }
        (SignalMode::SoftLoss, score)
    };
    let origin_evidence_id = if signal.depth == 0 {
        atom.evidence
            .iter()
            .map(|row| &row.evidence_id)
            .min()
            .cloned()
            .unwrap_or_else(|| signal.origin_evidence_id.clone())
    } else {
        signal.origin_evidence_id.clone()
    };
    let path_index = path_arena.extend(signal.path_index, atom.dependent, atom_index)?;
    Ok(Some(NodeSignal {
        node: atom.dependent,
        mode,
        score_millis,
        origin_evidence_id,
        path_index,
        depth: signal.depth + 1,
    }))
}

#[derive(Default)]
struct ImpactAccumulator {
    contributions: SmallVec<[Contribution; 1]>,
    violated_constraints: SmallVec<[CompactString; 1]>,
    support_loss_constraints: SmallVec<[CompactString; 1]>,
}

impl ImpactAccumulator {
    fn record(&mut self, atom: &ConstraintAtom, signal: &NodeSignal) {
        match signal.mode {
            SignalMode::HardBroken => {
                insert_sorted_unique(&mut self.violated_constraints, &atom.constraint_id);
            }
            SignalMode::Root | SignalMode::SoftLoss => {
                insert_sorted_unique(&mut self.support_loss_constraints, &atom.constraint_id);
            }
        }
        let contribution = Contribution {
            origin_evidence_id: signal.origin_evidence_id.clone(),
            classification: signal.mode.classification(),
            score_millis: signal.score_millis,
            path_index: signal.path_index,
        };
        if let Some(existing) = self
            .contributions
            .iter_mut()
            .find(|existing| existing.origin_evidence_id == signal.origin_evidence_id)
        {
            if contribution_better(&contribution, existing) {
                *existing = contribution;
            }
        } else {
            self.contributions.push(contribution);
        }
    }
}

#[derive(Clone)]
struct Contribution {
    origin_evidence_id: CompactString,
    classification: ImpactClassification,
    score_millis: u16,
    path_index: u32,
}

fn finalize_impacts(
    graph: &ConstraintGraph,
    path_arena: &PathArena,
    accumulators: BTreeMap<u32, ImpactAccumulator>,
    max_paths: usize,
    truncation: &mut RippleTruncation,
) -> Vec<RippleImpact> {
    let mut impacts = Vec::with_capacity(accumulators.len());
    for (node, mut accumulator) in accumulators {
        accumulator
            .contributions
            .sort_unstable_by(|left, right| left.origin_evidence_id.cmp(&right.origin_evidence_id));
        let broken = accumulator
            .contributions
            .iter()
            .any(|row| row.classification == ImpactClassification::Broken);
        let classification = if broken {
            ImpactClassification::Broken
        } else {
            ImpactClassification::Suspicious
        };
        let score_millis = if broken {
            1000
        } else {
            combine_independent_scores(accumulator.contributions.iter().map(|row| row.score_millis))
        };
        let mut paths = accumulator
            .contributions
            .into_iter()
            .map(|row| {
                path_arena.materialize(
                    graph,
                    row.path_index,
                    row.origin_evidence_id,
                    row.classification,
                    row.score_millis,
                )
            })
            .collect::<Vec<_>>();
        paths.sort_unstable_by(path_order);
        if paths.len() > max_paths {
            truncation.representative_path_drops += paths.len() - max_paths;
            paths.truncate(max_paths);
        }
        impacts.push(RippleImpact {
            dependent_id: graph.nodes()[node as usize].id.clone(),
            classification,
            score_millis,
            violated_constraints: accumulator.violated_constraints.into_vec(),
            support_loss_constraints: accumulator.support_loss_constraints.into_vec(),
            causal_paths: paths,
        });
    }
    impacts.sort_unstable_by(|left, right| {
        impact_rank(left.classification)
            .cmp(&impact_rank(right.classification))
            .then_with(|| right.score_millis.cmp(&left.score_millis))
            .then_with(|| left.dependent_id.cmp(&right.dependent_id))
    });
    impacts
}

fn validate_inputs(
    overlay: &CounterfactualGraphView<'_>,
    graph: &ConstraintGraph,
    requirements: &RevisionRequirementSidecar,
    config: RippleConfig,
) -> Result<(), RippleError> {
    if overlay.base_generation != graph.generation()
        || overlay.base_generation != requirements.generation
    {
        return Err(RippleError::GenerationMismatch {
            overlay: overlay.base_generation.0,
            constraints: graph.generation().0,
            requirements: requirements.generation.0,
        });
    }
    if config.max_representative_paths == 0
        || config.max_path_length == 0
        || config.max_signals_per_component == 0
        || config.max_visited_states == 0
        || config.max_traversed_edges == 0
        || config.min_soft_score_millis > 1000
    {
        return Err(RippleError::InvalidConfig);
    }
    Ok(())
}

fn requirement_index(
    requirements: &RevisionRequirementSidecar,
) -> Result<HashMap<&str, &RevisionRequirementRecord>, RippleError> {
    let mut out = HashMap::with_capacity(requirements.requirements.len());
    for requirement in &requirements.requirements {
        if out
            .insert(requirement.constraint_id.as_str(), requirement)
            .is_some()
        {
            return Err(RippleError::DuplicateRequirement(
                requirement.constraint_id.clone(),
            ));
        }
    }
    Ok(out)
}

fn changed_source_ids(overlay: &CounterfactualGraphView<'_>) -> Vec<CompactString> {
    let mut ids = overlay
        .receipt
        .changed_fact_ids
        .iter()
        .map(|fact_id| fact_id.0.clone())
        .chain(overlay.receipt.changed_state_refs.iter().map(|state_ref| {
            format_compact!(
                "state:{}:{}",
                state_ref.subject_id.0,
                state_ref.state_kind.0
            )
        }))
        .collect::<Vec<_>>();
    ids.sort_unstable();
    ids.dedup();
    ids
}

fn canonicalize_signals(
    signals: &mut SignalBuffer,
    limit: usize,
    truncation: &mut RippleTruncation,
) {
    signals.sort_unstable_by(signal_order);
    signals.dedup_by(|left, right| {
        left.node == right.node
            && left.mode == right.mode
            && left.origin_evidence_id == right.origin_evidence_id
    });
    if signals.len() > limit {
        truncation.component_signal_drops += signals.len() - limit;
        signals.truncate(limit);
    }
}

struct BestState {
    node: u32,
    origin_evidence_id: CompactString,
    rank_and_score: (u8, u16),
}

type BestStates = SmallVec<[BestState; 4]>;

fn record_best(best: &mut BestStates, signal: &NodeSignal) -> bool {
    let candidate = (signal.mode.rank(), signal.score_millis);
    if let Some(existing) = best.iter_mut().find(|existing| {
        existing.node == signal.node && existing.origin_evidence_id == signal.origin_evidence_id
    }) {
        if existing.rank_and_score >= candidate {
            false
        } else {
            existing.rank_and_score = candidate;
            true
        }
    } else {
        best.push(BestState {
            node: signal.node,
            origin_evidence_id: signal.origin_evidence_id.clone(),
            rank_and_score: candidate,
        });
        true
    }
}

fn insert_sorted_unique(rows: &mut SmallVec<[CompactString; 1]>, value: &CompactString) {
    if let Err(index) = rows.binary_search(value) {
        rows.insert(index, value.clone());
    }
}

fn contribution_better(left: &Contribution, right: &Contribution) -> bool {
    impact_rank(left.classification) < impact_rank(right.classification)
        || (left.classification == right.classification
            && (left.score_millis > right.score_millis
                || (left.score_millis == right.score_millis && left.path_index < right.path_index)))
}

fn signal_order(left: &NodeSignal, right: &NodeSignal) -> Ordering {
    left.node
        .cmp(&right.node)
        .then_with(|| left.origin_evidence_id.cmp(&right.origin_evidence_id))
        .then_with(|| right.mode.rank().cmp(&left.mode.rank()))
        .then_with(|| right.score_millis.cmp(&left.score_millis))
        .then_with(|| left.path_index.cmp(&right.path_index))
}

fn path_order(left: &ImpactPath, right: &ImpactPath) -> Ordering {
    impact_rank(left.classification)
        .cmp(&impact_rank(right.classification))
        .then_with(|| right.score_millis.cmp(&left.score_millis))
        .then_with(|| left.constraint_ids.cmp(&right.constraint_ids))
        .then_with(|| left.node_ids.cmp(&right.node_ids))
}

const fn impact_rank(classification: ImpactClassification) -> u8 {
    match classification {
        ImpactClassification::Broken => 0,
        ImpactClassification::Suspicious => 1,
        ImpactClassification::Unknown => 2,
    }
}

const fn edge_weight(kind: ConstraintKind) -> u16 {
    match kind {
        ConstraintKind::RequiresKnowledge
        | ConstraintKind::RequiresWitness
        | ConstraintKind::RequiresAlive
        | ConstraintKind::RequiresPossession
        | ConstraintKind::RequiresReachability
        | ConstraintKind::RequiresState
        | ConstraintKind::RequiresTemporalOrder
        | ConstraintKind::MutuallyExclusiveStates => 1000,
        ConstraintKind::CausalSupport => 950,
        ConstraintKind::Motivation => 800,
        ConstraintKind::Foreshadowing => 600,
        ConstraintKind::Mention => 150,
        ConstraintKind::ThematicEcho => 50,
    }
}

fn combine_independent_scores(scores: impl IntoIterator<Item = u16>) -> u16 {
    let mut remaining = 1000_u32;
    for score in scores {
        remaining = remaining * (1000 - u32::from(score)) / 1000;
    }
    (1000 - remaining) as u16
}

#[cfg(test)]
#[path = "ripple_tests.rs"]
mod tests;
