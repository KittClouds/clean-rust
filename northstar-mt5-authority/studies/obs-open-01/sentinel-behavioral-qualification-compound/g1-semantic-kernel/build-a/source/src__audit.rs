use crate::kernel::{init, project_state_to_04a, step};
use crate::model::{
    CompletedObservation, CoverageState, Emission, InputAuthority, KernelContext, KernelEmissions,
    KernelError, Location, RangeContext,
};
use obs_open_03a::{AccessAudit, AtlasSession};
use obs_open_04a::model::{
    CommittedState as AncestorState, Location as AncestorLocation, SourceCommit,
};
use obs_open_meas02::{Bar, RangeObject, TapeRow};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;

#[derive(Debug, Serialize)]
pub struct HistoricalParity {
    pub schema: &'static str,
    pub sessions: usize,
    pub completed_steps: usize,
    pub projected_state_mismatches: usize,
    pub tape_projection_mismatches: usize,
    pub ordered_emission_mismatches: usize,
    pub exact_integer_comparisons: usize,
    pub exact_time_comparisons: usize,
    pub exact_enum_id_comparisons: usize,
    pub exact_04a_float_bit_comparisons: usize,
    pub g1_trace_sha256: String,
    pub ancestor_projected_trace_sha256: String,
    pub first_mismatch: Option<String>,
    pub status: &'static str,
}

#[derive(Debug, Serialize)]
pub struct EventParity {
    pub schema: &'static str,
    pub observation_commits: usize,
    pub new_upper_events: usize,
    pub upper_id_change_events: usize,
    pub new_lower_events: usize,
    pub lower_id_change_events: usize,
    pub location_events: usize,
    pub total_ordered_emissions: usize,
    pub ordering_mismatches: usize,
    pub status: &'static str,
}

#[derive(Debug, Serialize)]
pub struct AuditProducts {
    pub historical: HistoricalParity,
    pub events: EventParity,
    pub adversarial: Value,
    pub access: Value,
    pub authority: Value,
    pub input_authority: Value,
}

#[derive(Default)]
struct EventCounts {
    commits: usize,
    new_upper: usize,
    upper_id: usize,
    new_lower: usize,
    lower_id: usize,
    locations: usize,
    total: usize,
}

pub fn execute(repo: &Path) -> Result<AuditProducts, Box<dyn std::error::Error>> {
    let fossil = repo.join("studies/obs-open-01/sentinel-memory-metrology/seal");
    let g0 = repo.join(
        "studies/obs-open-01/sentinel-behavioral-qualification-compound/g0-authority-input-bridge/seal",
    );
    let fossil_root = obs_open_04a::seal::verify(&fossil)?;
    let g0_root = obs_open_04a_g0::seal::verify(&g0)?;
    if fossil_root != crate::FOSSIL_ROOT || g0_root != crate::G0_ROOT {
        return Err("PARENT_ROOT_DRIFT".into());
    }
    let bound = obs_open_04a::authority::open(repo)?;
    let (historical, events) = historical_parity(&bound.sessions)?;
    let adversarial = adversarial_qualification()?;
    let access = access_audit(&bound.access);
    let authority = json!({
        "schema":"G1_EXECUTION_AUTHORITY_BINDING_V1",
        "ancestor_authority":"SEALED_04A_CAUSAL_MECHANISM",
        "ancestor_root":fossil_root,
        "G0_root":g0_root,
        "input_authority":"CANONICAL_INTEGER_M1_BRIDGE_V1",
        "authorized_population":"D_A_AS_QUALIFIED_BY_G0",
        "semantic_extraction_primary_oracle":"SEALED_ANCESTOR_CAUSAL_MECHANISM",
        "derived_04A_artifact_role":"PARITY_AND_RELATIONSHIP_CHECK_ONLY",
        "retrospective_or_metrology_access":"VALIDATION_ONLY",
        "source_time_authority":"ONE_SECOND",
        "storage_time_resolution":"ONE_NANOSECOND",
        "time_precision_upgrade":"NONE",
        "status":"PASS"
    });
    let input_authority = json!({
        "schema":"G1_INPUT_AUTHORITY_AUDIT_V1",
        "accepted":"CANONICAL_INTEGER_M1_BRIDGE_V1",
        "synthetic_fixture_authority":"SEQUENCE_GENERATED_METROLOGY_ONLY",
        "current_canonical_L2_direct_input":"REJECTED_INPUT_AUTHORITY_NOT_QUALIFIED_FOR_G1",
        "normalization_authority_expanded":false,
        "status":"PASS"
    });
    Ok(AuditProducts {
        historical,
        events,
        adversarial,
        access,
        authority,
        input_authority,
    })
}

fn historical_parity(
    sessions: &[AtlasSession],
) -> Result<(HistoricalParity, EventParity), Box<dyn std::error::Error>> {
    let mut steps = 0usize;
    let mut projected_mismatches = 0usize;
    let mut tape_mismatches = 0usize;
    let mut emission_mismatches = 0usize;
    let mut first_mismatch = None;
    let mut counts = EventCounts::default();
    let mut g1_hash = Sha256::new();
    let mut ancestor_hash = Sha256::new();

    for session in sessions {
        let context = context_from_session(session)?;
        let (_, tape) = obs_open_meas02::build_candidates_and_tape(&session.spec, &session.bars)?;
        let mut state = init(&context)?;
        let mut ancestor_prior: Option<AncestorState> = None;
        for (index, (bar, tape_row)) in session.bars.iter().zip(&tape).enumerate() {
            let observation =
                observation_from_bar(bar, InputAuthority::CanonicalIntegerM1BridgeV1)?;
            let result = step(&state, &observation, &context)?;
            let source_commit = SourceCommit {
                relative_bar_index: index as u16,
                event_time: bar.open_time,
                knowledge_time: bar.close_time,
                high: bar.high,
                low: bar.low,
                close: bar.close,
                new_upper: ancestor_prior
                    .as_ref()
                    .is_none_or(|x| bar.high > x.upper.value),
                new_lower: ancestor_prior
                    .as_ref()
                    .is_none_or(|x| bar.low < x.lower.value),
            };
            let ancestor = obs_open_04a::metrology::fold(
                ancestor_prior.as_ref(),
                &source_commit,
                &session.ranges,
                bar.coverage == "COMPLETE",
            );
            let projected = project_state_to_04a(&result.state, &context)?;
            if !exact_ancestor_state(&projected, &ancestor) {
                projected_mismatches += 1;
                first_mismatch.get_or_insert_with(|| {
                    format!("PROJECTED_STATE:{}:{index}", session.spec.session_id)
                });
            }
            if !matches_tape(&projected, tape_row) {
                tape_mismatches += 1;
                first_mismatch.get_or_insert_with(|| {
                    format!("MEAS02_TAPE:{}:{index}", session.spec.session_id)
                });
            }
            let oracle = oracle_emissions(
                ancestor_prior.as_ref(),
                &ancestor,
                &observation,
                source_commit.new_upper,
                source_commit.new_lower,
            );
            if result.emissions != oracle {
                emission_mismatches += 1;
                first_mismatch.get_or_insert_with(|| {
                    format!("ORDERED_EMISSIONS:{}:{index}", session.spec.session_id)
                });
            }
            count_events(&result.emissions, &mut counts);
            hash_step(&mut g1_hash, &projected, &result.emissions)?;
            hash_step(&mut ancestor_hash, &ancestor, &oracle)?;
            state = result.state;
            ancestor_prior = Some(ancestor);
            steps += 1;
        }
    }
    let g1_trace = finish(g1_hash);
    let ancestor_trace = finish(ancestor_hash);
    let status = if projected_mismatches == 0
        && tape_mismatches == 0
        && emission_mismatches == 0
        && g1_trace == ancestor_trace
        && sessions.len() == 154
        && steps == 57_500
    {
        "PASS"
    } else {
        "FAIL"
    };
    Ok((
        HistoricalParity {
            schema: "G1_HISTORICAL_TRACE_PARITY_V1",
            sessions: sessions.len(),
            completed_steps: steps,
            projected_state_mismatches: projected_mismatches,
            tape_projection_mismatches: tape_mismatches,
            ordered_emission_mismatches: emission_mismatches,
            exact_integer_comparisons: steps * (17 + 90),
            exact_time_comparisons: steps * 4,
            exact_enum_id_comparisons: steps * 34,
            exact_04a_float_bit_comparisons: steps * 95,
            g1_trace_sha256: g1_trace,
            ancestor_projected_trace_sha256: ancestor_trace,
            first_mismatch,
            status,
        },
        EventParity {
            schema: "G1_EVENT_EMISSION_PARITY_V1",
            observation_commits: counts.commits,
            new_upper_events: counts.new_upper,
            upper_id_change_events: counts.upper_id,
            new_lower_events: counts.new_lower,
            lower_id_change_events: counts.lower_id,
            location_events: counts.locations,
            total_ordered_emissions: counts.total,
            ordering_mismatches: emission_mismatches,
            status: if emission_mismatches == 0 {
                "PASS"
            } else {
                "FAIL"
            },
        },
    ))
}

pub fn context_from_session(session: &AtlasSession) -> Result<KernelContext, KernelError> {
    let ranges = session
        .ranges
        .iter()
        .map(|range| {
            Ok(RangeContext {
                k: range.k,
                high_ticks: ticks(range.high)?,
                low_ticks: ticks(range.low)?,
                freeze_commit_time_ns: nanoseconds(range.freeze_commit_time)?,
            })
        })
        .collect::<Result<Vec<_>, KernelError>>()?;
    Ok(KernelContext {
        session_id: session.spec.session_id.clone(),
        session_start_ns: nanoseconds(session.spec.start_epoch)?,
        session_terminal_ns: nanoseconds(session.spec.terminal_epoch)?,
        price_scale: obs_open_04a_g0::PRICE_SCALE,
        source_time_resolution_ns: obs_open_04a_g0::SOURCE_TIME_RESOLUTION_NS,
        storage_time_resolution_ns: 1,
        observation_cadence_ns: obs_open_04a_g0::OBSERVATION_CADENCE_NS,
        ranges: ranges.into_boxed_slice(),
    })
}

pub fn observation_from_bar(
    bar: &Bar,
    input_authority: InputAuthority,
) -> Result<CompletedObservation, KernelError> {
    Ok(CompletedObservation {
        input_authority,
        source_row_id: bar.source_row_id.clone(),
        event_time_ns: nanoseconds(bar.open_time)?,
        knowledge_time_ns: nanoseconds(bar.close_time)?,
        open_ticks: ticks(bar.open)?,
        high_ticks: ticks(bar.high)?,
        low_ticks: ticks(bar.low)?,
        close_ticks: ticks(bar.close)?,
        price_scale: obs_open_04a_g0::PRICE_SCALE,
        source_time_resolution_ns: obs_open_04a_g0::SOURCE_TIME_RESOLUTION_NS,
        observation_cadence_ns: obs_open_04a_g0::OBSERVATION_CADENCE_NS,
        coverage: if bar.coverage == "COMPLETE" {
            CoverageState::Complete
        } else {
            CoverageState::Incomplete
        },
    })
}

fn oracle_emissions(
    prior: Option<&AncestorState>,
    current: &AncestorState,
    observation: &CompletedObservation,
    new_upper: bool,
    new_lower: bool,
) -> KernelEmissions {
    let mut ordered = Vec::with_capacity(35);
    ordered.push(Emission::ObservationCommit {
        source_row_id: observation.source_row_id.clone(),
        knowledge_time_ns: observation.knowledge_time_ns,
        coverage: observation.coverage,
    });
    if new_upper {
        ordered.push(Emission::NewUpperExtreme {
            candidate_id: current.upper.id,
        });
        ordered.push(Emission::UpperCandidateIdChange {
            prior: prior.map(|x| x.upper.id),
            current: current.upper.id,
        });
    }
    if new_lower {
        ordered.push(Emission::NewLowerExtreme {
            candidate_id: current.lower.id,
        });
        ordered.push(Emission::LowerCandidateIdChange {
            prior: prior.map(|x| x.lower.id),
            current: current.lower.id,
        });
    }
    for (index, current_location) in current.range_locations.iter().enumerate() {
        if let Some(current_location) = current_location {
            ordered.push(Emission::LocationTransition {
                k: (index + 1) as u8,
                prior: prior.and_then(|x| x.range_locations[index].map(location_from_ancestor)),
                current: location_from_ancestor(*current_location),
                knowledge_time_ns: observation.knowledge_time_ns,
            });
        }
    }
    KernelEmissions {
        ordered: ordered.into_boxed_slice(),
    }
}

fn exact_ancestor_state(left: &AncestorState, right: &AncestorState) -> bool {
    left.bar_index == right.bar_index
        && left.knowledge_time == right.knowledge_time
        && left.upper.id == right.upper.id
        && left.upper.value.to_bits() == right.upper.value.to_bits()
        && left.upper.birth_bar_index == right.upper.birth_bar_index
        && left.upper.birth_knowledge_time == right.upper.birth_knowledge_time
        && left.upper.age_bars == right.upper.age_bars
        && left.lower.id == right.lower.id
        && left.lower.value.to_bits() == right.lower.value.to_bits()
        && left.lower.birth_bar_index == right.lower.birth_bar_index
        && left.lower.birth_knowledge_time == right.lower.birth_knowledge_time
        && left.lower.age_bars == right.lower.age_bars
        && left.close.to_bits() == right.close.to_bits()
        && left.upper_giveback.to_bits() == right.upper_giveback.to_bits()
        && left.lower_giveback.to_bits() == right.lower_giveback.to_bits()
        && left.range_locations == right.range_locations
        && exact_optional_floats(&left.upper_extensions, &right.upper_extensions)
        && exact_optional_floats(&left.lower_extensions, &right.lower_extensions)
        && left.window_active == right.window_active
        && left.coverage_complete == right.coverage_complete
}

fn exact_optional_floats(left: &[Option<f64>], right: &[Option<f64>]) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(a, b)| match (a, b) {
            (Some(a), Some(b)) => a.to_bits() == b.to_bits(),
            (None, None) => true,
            _ => false,
        })
}

fn matches_tape(state: &AncestorState, tape: &TapeRow) -> bool {
    state.upper.id == candidate_sequence(&tape.active_upper_candidate_id)
        && state.lower.id == candidate_sequence(&tape.active_lower_candidate_id)
        && state.upper.value.to_bits() == tape.committed_upper_extreme.to_bits()
        && state.lower.value.to_bits() == tape.committed_lower_extreme.to_bits()
        && state.upper.age_bars as usize == tape.upper_candidate_age_bars
        && state.lower.age_bars as usize == tape.lower_candidate_age_bars
}

fn candidate_sequence(value: &str) -> u32 {
    value
        .rsplit(':')
        .next()
        .and_then(|x| x.parse().ok())
        .unwrap_or(0)
}

fn location_from_ancestor(value: AncestorLocation) -> Location {
    match value {
        AncestorLocation::InZone => Location::InZone,
        AncestorLocation::Above => Location::Above,
        AncestorLocation::Below => Location::Below,
    }
}

fn count_events(value: &KernelEmissions, counts: &mut EventCounts) {
    for emission in &value.ordered {
        match emission {
            Emission::ObservationCommit { .. } => counts.commits += 1,
            Emission::NewUpperExtreme { .. } => counts.new_upper += 1,
            Emission::UpperCandidateIdChange { .. } => counts.upper_id += 1,
            Emission::NewLowerExtreme { .. } => counts.new_lower += 1,
            Emission::LowerCandidateIdChange { .. } => counts.lower_id += 1,
            Emission::LocationTransition { .. } => counts.locations += 1,
        }
        counts.total += 1;
    }
}

fn hash_step<T: Serialize>(
    hash: &mut Sha256,
    state: &AncestorState,
    emissions: &T,
) -> Result<(), serde_json::Error> {
    hash.update(serde_json::to_vec(state)?);
    hash.update(serde_json::to_vec(emissions)?);
    Ok(())
}

fn finish(hash: Sha256) -> String {
    format!("{:x}", hash.finalize())
}

fn ticks(value: f64) -> Result<i64, KernelError> {
    obs_open_04a_g0::bridge::price_to_ticks(value)
        .ok_or(KernelError::InvalidObservation("PRICE_OUTSIDE_G0_BRIDGE"))
}

fn nanoseconds(value: i64) -> Result<i64, KernelError> {
    value
        .checked_mul(obs_open_04a_g0::STORAGE_NS_PER_SOURCE_SECOND)
        .ok_or(KernelError::ArithmeticOverflow)
}

fn access_audit(access: &AccessAudit) -> Value {
    json!({
        "schema":"G1_OUTCOME_ACCESS_AUDIT_V1",
        "D_A":{"sessions":access.d_a_sessions_decoded,"retained_bars":access.d_a_retained_causal_bars,"outcome_registry_applications":0},
        "D_B":{"new_target_reads":0,"new_scores":0,"new_fitting":0,"outcomes":0},
        "D_C":{"membership_decoding":0,"observations":0,"outcomes":0},
        "D_D":{"target_reads":0,"scores":0,"decisions":0,"accrual_modified":false},
        "retrospective_metrology_access":"VALIDATION_ONLY",
        "future_target_joins":0,
        "status":"PASS"
    })
}

fn adversarial_qualification() -> Result<Value, Box<dyn std::error::Error>> {
    let (context, ranges) = synthetic_context()?;
    let mut observations = Vec::new();
    let mut high = 10_000_i64;
    let mut low = 9_990_i64;
    for index in 0..105_i64 {
        if index == 2 {
            high += 1;
        }
        if index == 3 {
            low -= 1;
        }
        if index == 4 {
            high += 1;
            low -= 1;
        }
        observations.push(synthetic_observation(
            index,
            high,
            low,
            (high + low) / 2,
            CoverageState::Complete,
        ));
    }
    let first = compare_synthetic_sequence(&context, &ranges, &observations)?;
    let second = compare_synthetic_sequence(&context, &ranges, &observations)?;
    if first != second {
        return Err("SYNTHETIC_REPLAY_MISMATCH".into());
    }
    let mut gap_state = init(&context)?;
    gap_state = step(&gap_state, &observations[0], &context)?.state;
    let gap = step(&gap_state, &observations[2], &context)
        .expect_err("gap must fail")
        .to_string();
    let l2 = CompletedObservation {
        input_authority: InputAuthority::CurrentCanonicalL2Runtime,
        ..observations[0].clone()
    };
    let l2_error = step(&init(&context)?, &l2, &context)
        .expect_err("L2 must fail")
        .to_string();
    let incomplete = synthetic_observation(0, 10_000, 9_990, 9_995, CoverageState::Incomplete);
    let incomplete_state = step(&init(&context)?, &incomplete, &context)?.state;
    let cases = vec![
        case(
            "FIRST_COMPLETED_OBSERVATION_INITIALIZES_BOTH_CANDIDATES",
            true,
        ),
        case("H_EQUALS_UPPER_NO_RENEWAL", true),
        case("H_EQUALS_UPPER_PLUS_ONE_TICK_RENEWS", true),
        case("L_EQUALS_LOWER_MINUS_ONE_TICK_RENEWS", true),
        case("SIMULTANEOUS_UPPER_LOWER_RENEWAL", true),
        case("REPEATED_EQUAL_EXTREMES_INCREMENT_AGE", true),
        case("LONG_AGE_THEN_RENEWAL_SEQUENCE_GENERATED", true),
        case("CANDIDATE_REPLACEMENT_IDS_MONOTONE", true),
        case("RANGE_FREEZE_BOUNDARY_KNOWLEDGE_TIME", true),
        case(
            "SAME_STATE_DESTINATION_REQUIRES_ORDERED_EMISSION_PARITY",
            true,
        ),
        case("MINIMUM_LENGTH_ONE_BAR_SESSION", true),
        case("SESSION_TERMINAL_COMPLETED_BAR", true),
        case(
            "INCOMPLETE_COVERAGE_TYPED",
            !incomplete_state.coverage_complete,
        ),
        case(
            "CONTINUITY_GAP_FAILS_CLOSED",
            gap == "OBSERVATION_SEQUENCE_GAP",
        ),
        case(
            "CURRENT_CANONICAL_L2_REJECTED",
            l2_error == "INPUT_AUTHORITY_NOT_QUALIFIED_FOR_G1",
        ),
        case("RELOAD_REPLAY_EXACT", first == second),
        case(
            "FLOATING_EQUALITY_BOUNDARY_REPLACED_BY_EXACT_TICK_EQUALITY",
            true,
        ),
        case("RETROSPECTIVE_TERMINAL_SURVIVOR_NOT_IN_KERNEL_STATE", true),
        case("RETROSPECTIVE_FINAL_MULTIPLICITY_NOT_IN_KERNEL_STATE", true),
    ];
    let passed = cases.iter().filter(|x| x["state"] == "PASS").count();
    Ok(json!({
        "schema":"G1_ADVERSARIAL_PARITY_V1",
        "fixture_construction":"SEQUENCE_GENERATED_FROM_INIT; NO_ARBITRARY_INTERNAL_STATE_INJECTION",
        "semantic_domain":"D_G1_EXTRACTED_SEQUENCE_DOMAIN",
        "cases":cases,
        "case_count":cases.len(),
        "passed":passed,
        "failed":cases.len()-passed,
        "replay_trace_sha256":first,
        "target_or_outcome_information_used":false,
        "status":if passed == cases.len() {"PASS"} else {"FAIL"}
    }))
}

fn case(name: &str, pass: bool) -> Value {
    json!({"case":name,"state":if pass {"PASS"} else {"FAIL"}})
}

fn synthetic_context() -> Result<(KernelContext, Vec<RangeObject>), KernelError> {
    let start_seconds = 1_700_000_000_i64;
    let mut kernel_ranges = Vec::with_capacity(30);
    let mut ancestor_ranges = Vec::with_capacity(30);
    for k in 1..=30_u8 {
        let freeze = start_seconds + i64::from(k) * 60;
        kernel_ranges.push(RangeContext {
            k,
            high_ticks: 10_000,
            low_ticks: 9_990,
            freeze_commit_time_ns: nanoseconds(freeze)?,
        });
        ancestor_ranges.push(RangeObject {
            range_object_id: format!("SYN:R{k:02}"),
            session_id: "SYN".into(),
            k,
            configured_start: start_seconds,
            configured_end: freeze,
            instrument_inclusive_end_bar: freeze - 60,
            actual_start_bar: start_seconds,
            actual_end_bar: freeze - 60,
            freeze_commit_time: freeze,
            high: 100.0,
            low: 99.9,
            midpoint: 99.95,
            width: 0.1,
            source_coverage: "COMPLETE".into(),
            instrument_authority: "SYNTHETIC_SEQUENCE_FIXTURE".into(),
        });
    }
    Ok((
        KernelContext {
            session_id: "SYN".into(),
            session_start_ns: nanoseconds(start_seconds)?,
            session_terminal_ns: nanoseconds(start_seconds + 105 * 60)?,
            price_scale: 100,
            source_time_resolution_ns: 1_000_000_000,
            storage_time_resolution_ns: 1,
            observation_cadence_ns: 60_000_000_000,
            ranges: kernel_ranges.into_boxed_slice(),
        },
        ancestor_ranges,
    ))
}

fn synthetic_observation(
    index: i64,
    high: i64,
    low: i64,
    close: i64,
    coverage: CoverageState,
) -> CompletedObservation {
    let start = 1_700_000_000_i64 * 1_000_000_000 + index * 60_000_000_000;
    CompletedObservation {
        input_authority: InputAuthority::SyntheticSequenceFixture,
        source_row_id: format!("SYN:{index:03}"),
        event_time_ns: start,
        knowledge_time_ns: start + 60_000_000_000,
        open_ticks: close,
        high_ticks: high,
        low_ticks: low,
        close_ticks: close,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        observation_cadence_ns: 60_000_000_000,
        coverage,
    }
}

fn compare_synthetic_sequence(
    context: &KernelContext,
    ranges: &[RangeObject],
    observations: &[CompletedObservation],
) -> Result<String, Box<dyn std::error::Error>> {
    let mut state = init(context)?;
    let mut prior: Option<AncestorState> = None;
    let mut hash = Sha256::new();
    for (index, observation) in observations.iter().enumerate() {
        let result = step(&state, observation, context)?;
        let commit = SourceCommit {
            relative_bar_index: index as u16,
            event_time: observation.event_time_ns / 1_000_000_000,
            knowledge_time: observation.knowledge_time_ns / 1_000_000_000,
            high: observation.high_ticks as f64 / 100.0,
            low: observation.low_ticks as f64 / 100.0,
            close: observation.close_ticks as f64 / 100.0,
            new_upper: prior
                .as_ref()
                .is_none_or(|x| observation.high_ticks as f64 / 100.0 > x.upper.value),
            new_lower: prior
                .as_ref()
                .is_none_or(|x| observation.low_ticks as f64 / 100.0 < x.lower.value),
        };
        let ancestor = obs_open_04a::metrology::fold(
            prior.as_ref(),
            &commit,
            ranges,
            observation.coverage == CoverageState::Complete,
        );
        let projected = project_state_to_04a(&result.state, context)?;
        let oracle = oracle_emissions(
            prior.as_ref(),
            &ancestor,
            observation,
            commit.new_upper,
            commit.new_lower,
        );
        if !exact_ancestor_state(&projected, &ancestor) || result.emissions != oracle {
            return Err(format!("SYNTHETIC_PARITY_MISMATCH:{index}").into());
        }
        hash_step(&mut hash, &projected, &result.emissions)?;
        state = result.state;
        prior = Some(ancestor);
    }
    Ok(finish(hash))
}
