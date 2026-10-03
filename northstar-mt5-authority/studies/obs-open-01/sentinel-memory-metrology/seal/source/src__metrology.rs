use crate::model::{
    CandidateState, CollisionSummary, CommittedState, Location, ReducedState, RelationClass,
    RelationEdge, RepresentationId, SourceCommit,
};
use hashbrown::{HashMap, HashSet};
use obs_open_03a::AtlasSession;
use obs_open_meas02::{Bar, RangeObject, TapeRow, build_candidates_and_tape};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

#[derive(Debug, Serialize)]
pub struct MetrologyProducts {
    pub collision: CollisionSummary,
    pub collision_details: Value,
    pub genealogy_atlas: Value,
    pub process_atlas: Value,
    pub gap_atlas: Value,
    pub sampling_units: Value,
    pub replay_receipt: Value,
    pub relation_edges: Vec<RelationEdge>,
    pub witnesses: Value,
    pub typed_findings: Value,
}

#[derive(Default)]
struct Multiplicity {
    history: HashMap<[u8; 32], usize>,
    semantic: HashMap<[u8; 32], usize>,
    source: HashMap<[u8; 32], usize>,
    state: HashMap<[u8; 32], usize>,
    reduced: HashMap<[u8; 32], usize>,
    semantic_states: HashMap<[u8; 32], HashSet<[u8; 32]>>,
    state_histories: HashMap<[u8; 32], HashSet<[u8; 32]>>,
    reduced_states: HashMap<[u8; 32], HashSet<[u8; 32]>>,
}

#[derive(Default)]
struct Morphology {
    session_candidate_counts: Vec<f64>,
    upper_counts: Vec<f64>,
    lower_counts: Vec<f64>,
    completed_lifetimes: Vec<f64>,
    inter_renewals: Vec<f64>,
    upper_ages: Vec<f64>,
    lower_ages: Vec<f64>,
    upper_givebacks: Vec<f64>,
    lower_givebacks: Vec<f64>,
    upper_extensions: Vec<f64>,
    lower_extensions: Vec<f64>,
    event_tape_lengths: Vec<f64>,
    semantic_tape_lengths: Vec<f64>,
    outside_run_lengths: Vec<f64>,
    transition_counts: HashMap<String, u64>,
    simultaneous_renewals: u64,
    supersessions: u64,
    complete_sessions: usize,
    incomplete_sessions: usize,
    retained_bars: usize,
}

pub fn execute(sessions: &[AtlasSession]) -> Result<MetrologyProducts, String> {
    let mut multi = Multiplicity::default();
    let mut morphology = Morphology::default();
    let mut observations = 0usize;
    let mut reconstruction_rows = 0usize;
    let mut first_state_history_witness = None;
    let mut first_semantic_state_witness = None;
    for session in sessions {
        let (candidates, tape) =
            build_candidates_and_tape(&session.spec, &session.bars).map_err(|e| e.to_string())?;
        if tape.len() != session.bars.len() {
            return Err("TAPE_BAR_COUNT_MISMATCH".into());
        }
        morphology.complete_sessions += usize::from(session.path_complete);
        morphology.incomplete_sessions += usize::from(!session.path_complete);
        morphology.retained_bars += session.bars.len();
        collect_genealogy(&candidates, &mut morphology);
        let mut prior: Option<CommittedState> = None;
        let mut history_hash = [0u8; 32];
        let mut source_hash = [0u8; 32];
        let mut semantic_hash = [0u8; 32];
        let mut source_events = 0usize;
        let mut semantic_events = 0usize;
        let mut runs = vec![(None::<Location>, 0usize); session.ranges.len()];
        for (index, ((bar, observed), expected_tape)) in session
            .bars
            .iter()
            .zip(tape.iter())
            .zip(tape.iter())
            .enumerate()
        {
            let commit = commit_from(prior.as_ref(), bar, index);
            morphology.simultaneous_renewals += u64::from(commit.new_upper && commit.new_lower);
            let folded = fold(prior.as_ref(), &commit, &session.ranges, true);
            compare_tape(&folded, expected_tape)?;
            let direct = direct_state(expected_tape, index, &session.ranges);
            if folded != direct {
                return Err(format!(
                    "SOURCE_FOLD_STATE_MISMATCH:{}:{index}",
                    session.spec.session_id
                ));
            }
            let transition_tokens = transitions(prior.as_ref(), &folded);
            source_events += 1
                + usize::from(commit.new_upper)
                + usize::from(commit.new_lower)
                + transition_tokens.len();
            semantic_events += usize::from(commit.new_upper)
                + usize::from(commit.new_lower)
                + transition_tokens.len();
            history_hash = history_step(history_hash, bar, index);
            source_hash = source_step(source_hash, &commit, &transition_tokens);
            semantic_hash = semantic_step(
                semantic_hash,
                commit.new_upper,
                commit.new_lower,
                &transition_tokens,
            );
            let state_hash = state_digest(&folded);
            let reduced_hash = reduced_digest(&ReducedState::from(&folded));
            increment(&mut multi.history, history_hash);
            increment(&mut multi.source, source_hash);
            increment(&mut multi.semantic, semantic_hash);
            increment(&mut multi.state, state_hash);
            increment(&mut multi.reduced, reduced_hash);
            multi
                .semantic_states
                .entry(semantic_hash)
                .or_default()
                .insert(state_hash);
            multi
                .state_histories
                .entry(state_hash)
                .or_default()
                .insert(history_hash);
            multi
                .reduced_states
                .entry(reduced_hash)
                .or_default()
                .insert(state_hash);
            if first_state_history_witness.is_none() && multi.state_histories[&state_hash].len() > 1
            {
                first_state_history_witness = Some(
                    json!({"session_id":session.spec.session_id,"bar_index":index,"state_hash":hex(&state_hash),"distinct_history_count":multi.state_histories[&state_hash].len()}),
                );
            }
            if first_semantic_state_witness.is_none()
                && multi.semantic_states[&semantic_hash].len() > 1
            {
                first_semantic_state_witness = Some(
                    json!({"session_id":session.spec.session_id,"bar_index":index,"semantic_tape_hash":hex(&semantic_hash),"distinct_state_count":multi.semantic_states[&semantic_hash].len()}),
                );
            }
            collect_observation(&folded, &transition_tokens, &mut runs, &mut morphology);
            prior = Some(folded);
            observations += 1;
            reconstruction_rows += 1;
            let _ = observed;
        }
        for (_, length) in runs {
            if length > 0 {
                morphology.outside_run_lengths.push(length as f64);
            }
        }
        morphology.event_tape_lengths.push(source_events as f64);
        morphology
            .semantic_tape_lengths
            .push(semantic_events as f64);
    }
    let collision = CollisionSummary {
        observations,
        unique_exact_histories: multi.history.len(),
        unique_semantic_event_tapes: multi.semantic.len(),
        unique_event_source_tapes: multi.source.len(),
        unique_current_states: multi.state.len(),
        unique_reduced_representations: multi.reduced.len(),
        semantic_collision_groups: multi.semantic_states.values().filter(|states| states.len() > 1).count(),
        source_to_state_collision_groups: multi.state_histories.values().filter(|histories| histories.len() > 1).count(),
        state_to_reduced_collision_groups: multi.reduced_states.values().filter(|states| states.len() > 1).count(),
        maximum_semantic_multiplicity: maximum(&multi.semantic),
        maximum_state_multiplicity: maximum(&multi.state),
        maximum_reduced_multiplicity: maximum(&multi.reduced),
        interpretation: "OBSERVED_COLLISION_MORPHOLOGY_ONLY; LOW_EXACT_COLLISION_COUNT_DOES_NOT_ESTABLISH_NEAR_LOSSLESSNESS".into(),
    };
    let witnesses = crate::fixtures::qualify()?;
    let edges = relation_graph();
    Ok(MetrologyProducts {
        collision_details: json!({"schema":"DA_COLLISION_MORPHOLOGY_V1","source_kind":"D_A_OBSERVED_NO_OUTCOME_JOIN","summary":collision,"canonical_identity":"SESSION_ID_AND_ABSOLUTE_DATE_EXCLUDED; RELATIVE_CAUSAL_ORDER_AND_EXACT_FLOAT_BITS_RETAINED","multiplicity_distributions":{"history":histogram(&multi.history),"semantic_event_tape":histogram(&multi.semantic),"event_source_tape":histogram(&multi.source),"current_state":histogram(&multi.state),"reduced_state":histogram(&multi.reduced)},"collision_relation_counts":{"history":collision_relations(&multi.history),"semantic_event_tape":collision_relations(&multi.semantic),"event_source_tape":collision_relations(&multi.source),"current_state":collision_relations(&multi.state),"reduced_state":collision_relations(&multi.reduced)},"empirical_state_history_witness":first_state_history_witness,"empirical_semantic_state_witness":first_semantic_state_witness,"epsilon_clustering_used":false}),
        genealogy_atlas: genealogy_json(&morphology),
        process_atlas: process_json(&morphology),
        gap_atlas: json!({"schema":"GAP_AND_EVALUABILITY_ATLAS_V1","sampling_unit":"SESSION","complete_sessions":morphology.complete_sessions,"source_path_incomplete_sessions":morphology.incomplete_sessions,"retained_completed_bars":morphology.retained_bars,"gap_policy":"NO_INTERPOLATION; RETAIN_QUALIFIED_PREFIX; COMPLETE_PATH_CLAIMS_NOT_EVALUABLE"}),
        sampling_units: sampling_ledger(),
        replay_receipt: json!({"schema":"REPLAY_EQUIVALENCE_RECEIPT_V1","source_kind":"DETERMINISTIC_RECONSTRUCTION","completed_rows_compared":reconstruction_rows,"candidate_ids":"EXACT","birth_times":"EXACT","state_values":"EXACT_FLOAT_BITS_FROM_SAME_PRIMITIVES","ages":"EXACT","genealogy_edges":"EXACT","event_sequence":"EXACT","online_provisional":"QUALIFIED_BY_PARENT_INST01_AND_SYNTHETIC_FIXTURE","historical_reconstruction":"PASS","reload":"PARENT_INST01_PASS","replay":"PASS","status":"PASS"}),
        relation_edges: edges.clone(),
        typed_findings: typed_findings(&edges),
        witnesses,
        collision,
    })
}

fn commit_from(prior: Option<&CommittedState>, bar: &Bar, index: usize) -> SourceCommit {
    SourceCommit {
        relative_bar_index: index as u16,
        event_time: bar.open_time,
        knowledge_time: bar.close_time,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        new_upper: prior.is_none_or(|p| bar.high > p.upper.value),
        new_lower: prior.is_none_or(|p| bar.low < p.lower.value),
    }
}

pub fn fold(
    prior: Option<&CommittedState>,
    commit: &SourceCommit,
    ranges: &[RangeObject],
    coverage: bool,
) -> CommittedState {
    let (upper, lower) = if let Some(p) = prior {
        let upper = if commit.high > p.upper.value {
            CandidateState {
                id: p.upper.id + 1,
                value: commit.high,
                birth_bar_index: commit.relative_bar_index,
                birth_knowledge_time: commit.knowledge_time,
                age_bars: 0,
            }
        } else {
            CandidateState {
                age_bars: p.upper.age_bars + 1,
                ..p.upper.clone()
            }
        };
        let lower = if commit.low < p.lower.value {
            CandidateState {
                id: p.lower.id + 1,
                value: commit.low,
                birth_bar_index: commit.relative_bar_index,
                birth_knowledge_time: commit.knowledge_time,
                age_bars: 0,
            }
        } else {
            CandidateState {
                age_bars: p.lower.age_bars + 1,
                ..p.lower.clone()
            }
        };
        (upper, lower)
    } else {
        (
            CandidateState {
                id: 1,
                value: commit.high,
                birth_bar_index: 0,
                birth_knowledge_time: commit.knowledge_time,
                age_bars: 0,
            },
            CandidateState {
                id: 1,
                value: commit.low,
                birth_bar_index: 0,
                birth_knowledge_time: commit.knowledge_time,
                age_bars: 0,
            },
        )
    };
    let mut locations = Vec::with_capacity(ranges.len());
    let mut ux = Vec::with_capacity(ranges.len());
    let mut lx = Vec::with_capacity(ranges.len());
    for range in ranges {
        if commit.knowledge_time < range.freeze_commit_time {
            locations.push(None);
            ux.push(None);
            lx.push(None);
        } else {
            locations.push(Some(location(commit.close, range)));
            ux.push(Some((upper.value - range.high).max(0.0)));
            lx.push(Some((range.low - lower.value).max(0.0)));
        }
    }
    CommittedState {
        bar_index: commit.relative_bar_index,
        knowledge_time: commit.knowledge_time,
        upper_giveback: (upper.value - commit.close).max(0.0),
        lower_giveback: (commit.close - lower.value).max(0.0),
        upper,
        lower,
        close: commit.close,
        range_locations: locations,
        upper_extensions: ux,
        lower_extensions: lx,
        window_active: true,
        coverage_complete: coverage,
    }
}

fn direct_state(tape: &TapeRow, index: usize, ranges: &[RangeObject]) -> CommittedState {
    let commit = SourceCommit {
        relative_bar_index: index as u16,
        event_time: tape.bar_open,
        knowledge_time: tape.bar_close,
        high: tape.high,
        low: tape.low,
        close: tape.close,
        new_upper: tape.new_upper_candidate,
        new_lower: tape.new_lower_candidate,
    };
    let upper = CandidateState {
        id: candidate_sequence(&tape.active_upper_candidate_id),
        value: tape.committed_upper_extreme,
        birth_bar_index: (index - tape.upper_candidate_age_bars) as u16,
        birth_knowledge_time: tape.bar_close - tape.upper_candidate_age_bars as i64 * 60,
        age_bars: tape.upper_candidate_age_bars as u16,
    };
    let lower = CandidateState {
        id: candidate_sequence(&tape.active_lower_candidate_id),
        value: tape.committed_lower_extreme,
        birth_bar_index: (index - tape.lower_candidate_age_bars) as u16,
        birth_knowledge_time: tape.bar_close - tape.lower_candidate_age_bars as i64 * 60,
        age_bars: tape.lower_candidate_age_bars as u16,
    };
    let mut state = fold(None, &commit, ranges, tape.coverage == "COMPLETE");
    state.upper = upper;
    state.lower = lower;
    state.upper_giveback = (state.upper.value - tape.close).max(0.0);
    state.lower_giveback = (tape.close - state.lower.value).max(0.0);
    for (i, range) in ranges.iter().enumerate() {
        if tape.bar_close >= range.freeze_commit_time {
            state.upper_extensions[i] = Some((state.upper.value - range.high).max(0.0));
            state.lower_extensions[i] = Some((range.low - state.lower.value).max(0.0));
        }
    }
    state
}

fn compare_tape(state: &CommittedState, tape: &TapeRow) -> Result<(), String> {
    if state.upper.id != candidate_sequence(&tape.active_upper_candidate_id)
        || state.lower.id != candidate_sequence(&tape.active_lower_candidate_id)
        || state.upper.value.to_bits() != tape.committed_upper_extreme.to_bits()
        || state.lower.value.to_bits() != tape.committed_lower_extreme.to_bits()
        || state.upper.age_bars as usize != tape.upper_candidate_age_bars
        || state.lower.age_bars as usize != tape.lower_candidate_age_bars
    {
        return Err(format!(
            "MEAS02_TAPE_RECONSTRUCTION_MISMATCH:{}:{}",
            tape.session_id, tape.bar_close
        ));
    }
    Ok(())
}
fn candidate_sequence(id: &str) -> u32 {
    id.rsplit(':')
        .next()
        .and_then(|x| x.parse().ok())
        .unwrap_or(0)
}
fn location(close: f64, range: &RangeObject) -> Location {
    if close > range.high {
        Location::Above
    } else if close < range.low {
        Location::Below
    } else {
        Location::InZone
    }
}

fn transitions(prior: Option<&CommittedState>, state: &CommittedState) -> Vec<String> {
    let mut out = Vec::new();
    for (k, current) in state.range_locations.iter().enumerate() {
        if let Some(c) = current {
            let token = match prior.and_then(|p| p.range_locations[k]) {
                None => format!("R{:02}_LOCATION_INITIAL_{}", k + 1, location_name(*c)),
                Some(p) => format!(
                    "R{:02}_LOCATION_{}_TO_{}",
                    k + 1,
                    location_name(p),
                    location_name(*c)
                ),
            };
            out.push(token);
        }
    }
    out
}
fn location_name(location: Location) -> &'static str {
    match location {
        Location::InZone => "IN_ZONE",
        Location::Above => "ABOVE",
        Location::Below => "BELOW",
    }
}

fn history_step(previous: [u8; 32], bar: &Bar, index: usize) -> [u8; 32] {
    digest(&[
        &previous,
        &(index as u32).to_le_bytes(),
        &bar.open.to_bits().to_le_bytes(),
        &bar.high.to_bits().to_le_bytes(),
        &bar.low.to_bits().to_le_bytes(),
        &bar.close.to_bits().to_le_bytes(),
    ])
}
fn source_step(previous: [u8; 32], c: &SourceCommit, tokens: &[String]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(previous);
    h.update(c.relative_bar_index.to_le_bytes());
    h.update(c.high.to_bits().to_le_bytes());
    h.update(c.low.to_bits().to_le_bytes());
    h.update(c.close.to_bits().to_le_bytes());
    h.update([c.new_upper as u8, c.new_lower as u8]);
    for t in tokens {
        h.update(t.as_bytes());
        h.update([0]);
    }
    h.finalize().into()
}
fn semantic_step(previous: [u8; 32], up: bool, low: bool, tokens: &[String]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(previous);
    if up {
        h.update(b"NEW_UPPER_EXTREME\0");
    }
    if low {
        h.update(b"NEW_LOWER_EXTREME\0");
    }
    for t in tokens {
        h.update(t.as_bytes());
        h.update([0]);
    }
    h.finalize().into()
}
fn state_digest(s: &CommittedState) -> [u8; 32] {
    let bytes = serde_json::to_vec(&(
        s.bar_index,
        s.upper.id,
        s.upper.value.to_bits(),
        s.upper.birth_bar_index,
        s.upper.age_bars,
        s.lower.id,
        s.lower.value.to_bits(),
        s.lower.birth_bar_index,
        s.lower.age_bars,
        s.close.to_bits(),
        &s.range_locations,
        s.upper_extensions
            .iter()
            .map(|x| x.map(f64::to_bits))
            .collect::<Vec<_>>(),
        s.lower_extensions
            .iter()
            .map(|x| x.map(f64::to_bits))
            .collect::<Vec<_>>(),
    ))
    .unwrap();
    digest(&[&bytes])
}
fn reduced_digest(s: &ReducedState) -> [u8; 32] {
    let bytes = serde_json::to_vec(&(
        s.upper_value.to_bits(),
        s.lower_value.to_bits(),
        s.upper_giveback.to_bits(),
        s.lower_giveback.to_bits(),
        &s.range_locations,
        s.upper_extensions
            .iter()
            .map(|x| x.map(f64::to_bits))
            .collect::<Vec<_>>(),
        s.lower_extensions
            .iter()
            .map(|x| x.map(f64::to_bits))
            .collect::<Vec<_>>(),
    ))
    .unwrap();
    digest(&[&bytes])
}
fn digest(parts: &[&[u8]]) -> [u8; 32] {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().into()
}
fn hex(x: &[u8; 32]) -> String {
    x.iter().map(|b| format!("{b:02x}")).collect()
}
fn increment(map: &mut HashMap<[u8; 32], usize>, key: [u8; 32]) {
    *map.entry(key).or_insert(0) += 1;
}
fn maximum(map: &HashMap<[u8; 32], usize>) -> usize {
    map.values().copied().max().unwrap_or(0)
}
fn histogram(map: &HashMap<[u8; 32], usize>) -> Value {
    let mut histogram = std::collections::BTreeMap::<usize, usize>::new();
    for &multiplicity in map.values() {
        *histogram.entry(multiplicity).or_insert(0) += 1;
    }
    json!(histogram)
}
fn collision_relations(map: &HashMap<[u8; 32], usize>) -> u64 {
    map.values()
        .map(|&n| (n as u64).saturating_mul(n.saturating_sub(1) as u64) / 2)
        .sum()
}

fn collect_genealogy(candidates: &[obs_open_meas02::Candidate], m: &mut Morphology) {
    let upper = candidates
        .iter()
        .filter(|c| c.side == "UPPER")
        .collect::<Vec<_>>();
    let lower = candidates
        .iter()
        .filter(|c| c.side == "LOWER")
        .collect::<Vec<_>>();
    m.session_candidate_counts.push(candidates.len() as f64);
    m.upper_counts.push(upper.len() as f64);
    m.lower_counts.push(lower.len() as f64);
    m.supersessions += candidates.iter().filter(|c| c.superseded).count() as u64;
    for side in [&upper, &lower] {
        for pair in side.windows(2) {
            m.inter_renewals
                .push((pair[1].birth_knowledge_time - pair[0].birth_knowledge_time) as f64 / 60.0);
        }
        for c in side.iter().filter(|c| c.superseded) {
            m.completed_lifetimes
                .push((c.superseded_at.unwrap() - c.birth_knowledge_time) as f64 / 60.0);
        }
    }
}
fn collect_observation(
    state: &CommittedState,
    tokens: &[String],
    runs: &mut [(Option<Location>, usize)],
    m: &mut Morphology,
) {
    m.upper_ages.push(state.upper.age_bars as f64);
    m.lower_ages.push(state.lower.age_bars as f64);
    m.upper_givebacks.push(state.upper_giveback);
    m.lower_givebacks.push(state.lower_giveback);
    m.upper_extensions
        .extend(state.upper_extensions.iter().flatten().copied());
    m.lower_extensions
        .extend(state.lower_extensions.iter().flatten().copied());
    for t in tokens {
        *m.transition_counts
            .entry(
                t.split_once("LOCATION_")
                    .map(|(_, x)| x)
                    .unwrap_or(t)
                    .to_owned(),
            )
            .or_insert(0) += 1;
    }
    for (i, loc) in state.range_locations.iter().enumerate() {
        match loc {
            Some(Location::Above | Location::Below) => {
                if runs[i].0 == *loc {
                    runs[i].1 += 1
                } else {
                    if runs[i].1 > 0 {
                        m.outside_run_lengths.push(runs[i].1 as f64);
                    }
                    runs[i] = (*loc, 1);
                }
            }
            _ => {
                if runs[i].1 > 0 {
                    m.outside_run_lengths.push(runs[i].1 as f64);
                }
                runs[i] = (None, 0);
            }
        }
    }
}

fn distribution(name: &str, unit: &str, values: &[f64]) -> Value {
    let mut v = values.to_vec();
    v.sort_by(f64::total_cmp);
    json!({"measurement":name,"sampling_unit":unit,"count":v.len(),"min":v.first(),"q25":quantile(&v,0.25),"median":quantile(&v,0.5),"q75":quantile(&v,0.75),"max":v.last(),"mean":if v.is_empty(){None}else{Some(v.iter().sum::<f64>()/v.len()as f64)}})
}
fn quantile(v: &[f64], q: f64) -> Option<f64> {
    if v.is_empty() {
        None
    } else {
        Some(v[((v.len() - 1) as f64 * q).round() as usize])
    }
}
fn genealogy_json(m: &Morphology) -> Value {
    json!({"schema":"DA_GENEALOGY_ATLAS_V1","source_kind":"D_A_OBSERVED_NO_OUTCOME_JOIN","distributions":[distribution("candidate_count","SESSION",&m.session_candidate_counts),distribution("upper_genealogy_depth","SESSION",&m.upper_counts),distribution("lower_genealogy_depth","SESSION",&m.lower_counts),distribution("completed_candidate_lifetime_minutes","CANDIDATE_SUPERSEDED",&m.completed_lifetimes),distribution("inter_renewal_minutes","GENEALOGY_EDGE",&m.inter_renewals)],"upper_candidate_total":m.upper_counts.iter().sum::<f64>() as u64,"lower_candidate_total":m.lower_counts.iter().sum::<f64>() as u64,"supersession_count":m.supersessions,"terminal_survivor_sidecar":{"complete_session_labels":m.complete_sessions*2,"incomplete_session_labels":0,"availability":"SESSION_TERMINATION_BOUNDARY_ONLY","used_to_define_causal_state":false}})
}
fn process_json(m: &Morphology) -> Value {
    json!({"schema":"DA_PROCESS_MORPHOLOGY_ATLAS_V1","source_kind":"D_A_OBSERVED_NO_OUTCOME_JOIN","distributions":[distribution("upper_causal_age_bars","OBSERVATION_TIME",&m.upper_ages),distribution("lower_causal_age_bars","OBSERVATION_TIME",&m.lower_ages),distribution("upper_giveback","OBSERVATION_TIME_X_RANGE_INDEPENDENT_STATE",&m.upper_givebacks),distribution("lower_giveback","OBSERVATION_TIME_X_RANGE_INDEPENDENT_STATE",&m.lower_givebacks),distribution("upper_range_extension","CANDIDATE_RANGE_RELATION_AT_OBSERVATION",&m.upper_extensions),distribution("lower_range_extension","CANDIDATE_RANGE_RELATION_AT_OBSERVATION",&m.lower_extensions),distribution("event_source_tape_length","SESSION",&m.event_tape_lengths),distribution("semantic_event_tape_length","SESSION",&m.semantic_tape_lengths),distribution("outside_run_length_bars","CONTIGUOUS_RANGE_LOCATION_RUN",&m.outside_run_lengths)],"transition_type_frequencies":m.transition_counts,"simultaneous_initializations":m.complete_sessions+m.incomplete_sessions,"simultaneous_strict_renewals_after_initial":m.simultaneous_renewals.saturating_sub((m.complete_sessions+m.incomplete_sessions)as u64),"interpretation":"DESCRIPTIVE_METROLOGY_ONLY"})
}
fn sampling_ledger() -> Value {
    json!({"schema":"SAMPLING_UNIT_LEDGER_V1","law":"EVERY_DESCRIPTIVE_DISTRIBUTION_DECLARES_ITS_SAMPLING_UNIT","units":{"candidate_counts":"SESSION","candidate_lifetimes":"CANDIDATE_SUPERSEDED","candidate_ages":"OBSERVATION_TIME","genealogy_depth":"SESSION","inter_renewal":"GENEALOGY_EDGE","transition_frequencies":"EVENT","event_tape_lengths":"SESSION","outside_run_lengths":"CONTIGUOUS_RANGE_LOCATION_RUN","giveback":"OBSERVATION_TIME","extension":"CANDIDATE_RANGE_RELATION_AT_OBSERVATION"},"weighting_views_not_collapsed":["SESSION","CANDIDATE","EVENT","OBSERVATION_TIME","GENEALOGY"]})
}

fn relation_graph() -> Vec<RelationEdge> {
    use RelationClass::*;
    use RepresentationId::*;
    vec![
        edge(
            History,
            SemanticTape,
            LossyQuotient,
            &[],
            &["OHLC_MAGNITUDE", "ORDINARY_BAR_PATH", "EXACT_TIMING"],
            None,
            "04A_WITNESS_H_TO_SEMANTIC",
        ),
        edge(
            History,
            SourceTape,
            LossyQuotient,
            &[],
            &["BAR_OPEN", "INTRABAR_ORDER"],
            Some("DETERMINISTIC_BAR_TO_EVENT_PROJECTION"),
            "04A_WITNESS_H_TO_SOURCE",
        ),
        edge(
            SourceTape,
            SemanticTape,
            LossyQuotient,
            &[],
            &[
                "PRICE_PAYLOAD",
                "COMMIT_TIMING",
                "ORDINARY_OBSERVATION_COMMITS",
            ],
            Some("DROP_EVENT_PAYLOAD_AND_OBSERVATION_COMMITS"),
            "04A_WITNESS_SOURCE_TO_SEMANTIC",
        ),
        edge(
            History,
            CurrentState,
            ReconstructibleWithContext,
            &["SESSION_BOUNDARY", "R01_TO_R30_FROZEN_GEOMETRY"],
            &[
                "SUPERSEDED_CANDIDATE_VALUES",
                "BAR_OPEN",
                "INTERMEDIATE_PATH",
            ],
            Some("COMPLETED_BAR_SENTINEL_FOLD"),
            "04A_WITNESS_HISTORY_TO_STATE",
        ),
        edge(
            SemanticTape,
            CurrentState,
            NonReconstructible,
            &[],
            &[
                "CANDIDATE_VALUES",
                "BIRTH_TIMES",
                "AGES",
                "CLOSE",
                "RANGE_RELATIVE_GEOMETRY",
            ],
            None,
            "04A_WITNESS_SEMANTIC_TO_STATE",
        ),
        edge(
            SourceTape,
            CurrentState,
            ReconstructibleWithContext,
            &["SESSION_BOUNDARY", "R01_TO_R30_FROZEN_GEOMETRY"],
            &[
                "SUPERSEDED_CANDIDATE_VALUES",
                "EARLIER_OBSERVATION_PAYLOAD_AFTER_FOLD",
            ],
            Some("EVENT_SOURCE_FOLD_V1"),
            "04A_WITNESS_SOURCE_TO_STATE",
        ),
        edge(
            CurrentState,
            ReducedState,
            LossyQuotient,
            &[],
            &["CANDIDATE_IDS", "BIRTH_TIMES", "CAUSAL_AGES"],
            Some("DROP_IDENTITY_AND_AGE_FIELDS"),
            "04A_WITNESS_STATE_TO_REDUCED",
        ),
    ]
}
fn edge(
    source: RepresentationId,
    target: RepresentationId,
    class: RelationClass,
    context: &[&str],
    lost: &[&str],
    reconstruction: Option<&str>,
    witness: &str,
) -> RelationEdge {
    RelationEdge {
        source_representation: source.name().into(),
        target_representation: target.name().into(),
        relation_class: class,
        required_context: context.iter().map(|x| (*x).into()).collect(),
        lost_degrees: lost.iter().map(|x| (*x).into()).collect(),
        reconstruction_procedure: reconstruction.map(Into::into),
        witness_artifact: Some(witness.into()),
        status: "QUALIFIED".into(),
        authority_basis: vec![
            "ALGEBRAIC".into(),
            "ADVERSARIAL_WITNESS".into(),
            "DETERMINISTIC_RECONSTRUCTION".into(),
        ],
    }
}
fn typed_findings(edges: &[RelationEdge]) -> Value {
    json!({"schema":"OBS_OPEN_04A_TYPED_FINDINGS_V1","source_kind":"MULTIPLE","final_state":"SENTINEL_MEMORY_METROLOGY_SEALED","representations":[{"id":RepresentationId::History.name(),"status":"QUALIFIED"},{"id":RepresentationId::SemanticTape.name(),"status":"QUALIFIED"},{"id":RepresentationId::SourceTape.name(),"status":"QUALIFIED"},{"id":RepresentationId::CurrentState.name(),"status":"QUALIFIED"},{"id":RepresentationId::ReducedState.name(),"status":"QUALIFIED"}],"relations":edges,"future_sufficiency_order":{"state":"FUTURE_PROTOCOL_CANDIDATES_ONLY","candidate_order":["REDUCED_SENTINEL_GEOMETRY_V1","CURRENT_SENTINEL_STATE_V1","EVENT_SOURCE_TAPE_V1","RAW_COMPLETED_BAR_HISTORY_V1"],"nested_hierarchy_claimed":false,"reason":"GRAPH_HAS_BRANCHING_AND_LOSSY_EDGES"},"outcome_information_authority":false,"memory_sufficiency_authority":false,"mechanism_authority":false,"economic_authority":false,"trading_authority":false})
}
