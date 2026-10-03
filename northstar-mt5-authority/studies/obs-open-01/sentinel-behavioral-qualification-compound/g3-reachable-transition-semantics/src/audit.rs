use crate::fixtures::{replay_witness, witness_corpus};
use crate::model::{
    ApproximationBoundary, AuditProducts, CollisionDisposition, Constraint, ConstraintScope,
    EpistemicStatus, LanguageStatus, TransitionResult, UnreachabilityProof,
};
use obs_open_04a_g2::census;

fn constraint(
    id: &str,
    scope: ConstraintScope,
    expression: &str,
    participants: &[&str],
    preconditions: &[&str],
) -> Constraint {
    Constraint {
        constraint_id: id.into(),
        participants: participants.iter().map(|x| (*x).into()).collect(),
        scope,
        authority: match scope {
            ConstraintScope::TracePrefix => EpistemicStatus::ProvenTraceConstraint,
            ConstraintScope::State => EpistemicStatus::ProvenInvariant,
            _ => EpistemicStatus::ProvenTransitionConstraint,
        },
        expression: expression.into(),
        preconditions: preconditions.iter().map(|x| (*x).into()).collect(),
        proof_reference: "DIRECT_DERIVATION_FROM_SEALED_G1_KERNEL_SOURCE_AND_EXECUTABLE_REGRESSION"
            .into(),
        approximation_direction: "UNIVERSAL_OVER_G1_EXTRACTED_SEMANTIC_DOMAIN".into(),
        known_failure_domain: vec!["OUTSIDE_C_AUTH_G3".into(), "ARITHMETIC_REJECTION".into()],
        g2_collision_ids: Vec::new(),
    }
}

fn constraints() -> Vec<Constraint> {
    use ConstraintScope::*;
    vec![
        constraint(
            "G3-C001",
            State,
            "initialized iff all causal Option fields are present; uninitialized implies window_active=false",
            &["state.initialized", "state.window_active"],
            &["K in G1 extracted domain"],
        ),
        constraint(
            "G3-C002",
            Transition,
            "first applied step has bar_index=0; each later applied step increments bar_index by exactly 1",
            &["state.bar_index"],
            &["APPLIED"],
        ),
        constraint(
            "G3-C003",
            TracePrefix,
            "knowledge_time[n]-knowledge_time[n-1]=cadence and knowledge_time-event_time=cadence",
            &[
                "state.knowledge_time_ns",
                "input.event_time_ns",
                "input.knowledge_time_ns",
                "context.observation_cadence_ns",
            ],
            &["legal applied prefix"],
        ),
        constraint(
            "G3-C004",
            StateInput,
            "low <= open,close <= high",
            &[
                "input.low_ticks",
                "input.open_ticks",
                "input.close_ticks",
                "input.high_ticks",
            ],
            &["locally valid observation"],
        ),
        constraint(
            "G3-C005",
            Transition,
            "upper'=max(upper,input.high); lower'=min(lower,input.low), with initialization from first bar",
            &[
                "state.upper.value_ticks",
                "state.lower.value_ticks",
                "input.high_ticks",
                "input.low_ticks",
            ],
            &["APPLIED"],
        ),
        constraint(
            "G3-C006",
            Transition,
            "upper never decreases and lower never increases",
            &["state.upper.value_ticks", "state.lower.value_ticks"],
            &["initialized prior", "APPLIED"],
        ),
        constraint(
            "G3-C007",
            Transition,
            "candidate id delta is 1 exactly on strict renewal and 0 otherwise",
            &["state.upper.id", "state.lower.id"],
            &["initialized prior", "APPLIED"],
        ),
        constraint(
            "G3-C008",
            Transition,
            "candidate age resets to 0 on renewal and increments by 1 on persistence",
            &["state.upper.age_bars", "state.lower.age_bars"],
            &["initialized prior", "APPLIED"],
        ),
        constraint(
            "G3-C009",
            StateContext,
            "age_bars = bar_index - birth_bar_index",
            &[
                "state.bar_index",
                "candidate.birth_bar_index",
                "candidate.age_bars",
            ],
            &["reachable initialized state"],
        ),
        constraint(
            "G3-C010",
            StateContext,
            "knowledge_time - birth_knowledge_time = age_bars * cadence",
            &[
                "state.knowledge_time_ns",
                "candidate.birth_knowledge_time_ns",
                "candidate.age_bars",
                "context.observation_cadence_ns",
            ],
            &["reachable initialized state"],
        ),
        constraint(
            "G3-C011",
            State,
            "upper >= close >= lower; upper >= lower",
            &[
                "state.upper.value_ticks",
                "state.close_ticks",
                "state.lower.value_ticks",
            ],
            &["reachable initialized state"],
        ),
        constraint(
            "G3-C012",
            State,
            "upper_giveback=upper-close and lower_giveback=close-lower; both nonnegative",
            &[
                "state.upper_giveback_ticks",
                "state.lower_giveback_ticks",
                "state.close_ticks",
            ],
            &["reachable initialized state"],
        ),
        constraint(
            "G3-C013",
            StateContext,
            "knowledge<freeze iff location and both extensions are unavailable",
            &[
                "state.knowledge_time_ns",
                "context.range.freeze_commit_time_ns",
                "state.range_locations",
            ],
            &["reachable initialized state"],
        ),
        constraint(
            "G3-C014",
            StateContext,
            "after freeze, location=ABOVE iff close>high, BELOW iff close<low, else IN_ZONE",
            &[
                "state.range_locations",
                "state.close_ticks",
                "context.range.high_ticks",
                "context.range.low_ticks",
            ],
            &["range available"],
        ),
        constraint(
            "G3-C015",
            StateContext,
            "upper_extension=max(0,upper-range_high); lower_extension=max(0,range_low-lower)",
            &[
                "state.upper_extensions_ticks",
                "state.lower_extensions_ticks",
            ],
            &["range available"],
        ),
        constraint(
            "G3-C016",
            TransitionEmission,
            "ObservationCommit is first and exactly copies row id, knowledge time, and coverage",
            &["emission.commit", "input.source_row_id", "input.coverage"],
            &["APPLIED"],
        ),
        constraint(
            "G3-C017",
            TransitionEmission,
            "each renewal emits NEW_EXTREME then matching ID_CHANGE; persistence emits neither",
            &["emission.candidate", "state.candidate.id"],
            &["APPLIED"],
        ),
        constraint(
            "G3-C018",
            TransitionEmission,
            "one LocationTransition per available range follows candidate emissions in ascending k",
            &["emission.location", "state.range_locations"],
            &["APPLIED"],
        ),
        constraint(
            "G3-C019",
            Transition,
            "coverage_complete exactly copies current observation coverage and imposes no future transition restriction",
            &["state.coverage_complete", "input.coverage"],
            &["APPLIED"],
        ),
        constraint(
            "G3-C020",
            StateInput,
            "schema-valid input is not necessarily applicable: authority, context match, chronology, and session bounds jointly govern APPLIED vs REJECTED",
            &["input", "state", "context"],
            &["G1 step evaluation"],
        ),
        constraint(
            "G3-C021",
            Transition,
            "step codomain is exactly APPLIED(next_state,ordered_emissions) or typed REJECTED(reason)",
            &["state", "input", "context", "emission"],
            &["G1 extracted semantic domain"],
        ),
        constraint(
            "G3-C022",
            StateContext,
            "candidate ids are >=1 and birth_bar_index <= bar_index",
            &[
                "candidate.id",
                "candidate.birth_bar_index",
                "state.bar_index",
            ],
            &["reachable initialized state"],
        ),
    ]
}

fn unreachability() -> Vec<UnreachabilityProof> {
    let entries = [
        (
            "U001",
            EpistemicStatus::ProvenUnreachableConfiguration,
            "reachable initialized state with upper < lower",
            "C005 plus valid OHLC implies running max(high) >= running min(low)",
        ),
        (
            "U002",
            EpistemicStatus::ProvenUnreachableConfiguration,
            "reachable initialized candidate with id=0",
            "initial id is 1 and only checked +1 increments occur",
        ),
        (
            "U003",
            EpistemicStatus::ProvenUnreachableTransition,
            "applied transition with candidate id jump >1",
            "C007 exhausts the update branches",
        ),
        (
            "U004",
            EpistemicStatus::ProvenUnreachableTransition,
            "applied persistence transition with age not prior+1",
            "C008 exhausts the persistence branch",
        ),
        (
            "U005",
            EpistemicStatus::ProvenUnreachableConfiguration,
            "reachable state with age != bar_index-birth_bar_index",
            "induction from initialization and C002/C008",
        ),
        (
            "U006",
            EpistemicStatus::ProvenUnreachableConfiguration,
            "pre-freeze range with a location value",
            "C013 directly follows the unavailable branch",
        ),
        (
            "U007",
            EpistemicStatus::ProvenUnreachableConfiguration,
            "post-freeze range with location absent",
            "C013 directly follows the available branch",
        ),
        (
            "U008",
            EpistemicStatus::ProvenUnreachableTransition,
            "upper renewal without ordered NEW_UPPER then ID_CHANGE emissions",
            "C017 follows the only emission branch",
        ),
        (
            "U009",
            EpistemicStatus::ProvenUnreachableTransition,
            "invalid OHLC tuple producing APPLIED",
            "G1 validation rejects before any state update",
        ),
    ];
    entries
        .into_iter()
        .map(|(id, status, config, contradiction)| UnreachabilityProof {
            proof_id: id.into(),
            status,
            prohibited_configuration: config.into(),
            contradiction: contradiction.into(),
            context_scope: "ALL_C_AUTH_G3_WHERE_G1_SEMANTICS_ARE_DEFINED".into(),
        })
        .collect()
}

fn bounds() -> Vec<ApproximationBoundary> {
    [
        ("ADMITTED_INPUT_LANGUAGE", LanguageStatus::Mixed, "finite locally valid witness inputs", "all G1 locally valid observations under C_AUTH_G3; state applicability deferred to transition relation"),
        ("KERNEL_EXECUTABLE_PREFIXES_V1", LanguageStatus::Mixed, "replayable witness prefixes P_EXEC_MINUS", "all finite prefixes satisfying initial/session/cadence/input constraints P_EXEC_PLUS"),
        ("CONTEXT_INDEXED_REACHABLE_STATES", LanguageStatus::Mixed, "states reached by witness prefixes K_MINUS(C)", "states satisfying all proven state/context constraints K_PLUS(C)"),
        ("CONTEXT_INDEXED_REACHABLE_TRANSITIONS", LanguageStatus::Mixed, "applied and rejected witness transitions T_MINUS(C)", "all applied/rejected tuples satisfying G1 domain and proven joint constraints T_PLUS(C)"),
    ].into_iter().map(|(object,status,lower,upper)| ApproximationBoundary {
        object:object.into(), status, lower_bound:lower.into(), upper_bound:upper.into(),
        known_error_direction:"LOWER_BOUND_HAS_ONLY_CONSTRUCTIVELY_REPLAYED_MEMBERS_BUT_MAY_OMIT_REACHABLE_BEHAVIOR; UPPER_BOUND_MAY_ADMIT_IMPOSSIBLE_MEMBERS_BUT MUST_NOT_EXCLUDE G1-REACHABLE BEHAVIOR".into(),
        exactness_claimed:false,
    }).collect()
}

fn collision_map(constraints: &[Constraint]) -> Result<Vec<CollisionDisposition>, String> {
    let census = census::execute()?;
    let mut serial = 0usize;
    let mut rows = Vec::new();
    for element in census
        .elements
        .into_iter()
        .filter(|x| x.multi_role_collision)
    {
        serial += 1;
        let (disposition, ids): (&str, &[&str]) = match element.element_id.as_str() {
            "state.initialized" | "state.window_active" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C001"])
            }
            "state.upper.id" | "state.lower.id" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C007", "G3-C017", "G3-C022"],
            ),
            "state.upper.value_ticks" | "state.lower.value_ticks" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C005", "G3-C006", "G3-C011", "G3-C012", "G3-C015"],
            ),
            "state.close_ticks" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C011", "G3-C012", "G3-C014"],
            ),
            "state.range_locations" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C013", "G3-C014", "G3-C018"],
            ),
            "state.coverage_complete" | "input.coverage" | "emission.commit.coverage" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C016", "G3-C019"])
            }
            "context.session_start_ns"
            | "context.session_terminal_ns"
            | "context.observation_cadence_ns"
            | "input.event_time_ns"
            | "input.knowledge_time_ns" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C003", "G3-C020"])
            }
            "context.range.high_ticks" | "context.range.low_ticks" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C014", "G3-C015"])
            }
            "context.range.freeze_commit_time_ns"
            | "context.range.k"
            | "emission.location.k"
            | "emission.location.prior"
            | "emission.location.current" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C013", "G3-C014", "G3-C018"],
            ),
            "input.open_ticks" | "input.high_ticks" | "input.low_ticks" | "input.close_ticks" => (
                "PROVEN_REACHABILITY_CONSTRAINT",
                &["G3-C004", "G3-C005", "G3-C011"],
            ),
            "input.input_authority"
            | "context.price_scale"
            | "context.source_time_resolution_ns"
            | "context.storage_time_resolution_ns"
            | "input.price_scale"
            | "input.source_time_resolution_ns"
            | "input.observation_cadence_ns" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C020", "G3-C021"])
            }
            "input.source_row_id" | "emission.commit.source_row_id" => {
                ("PROVEN_REACHABILITY_CONSTRAINT", &["G3-C016"])
            }
            "context.session_id" => ("NO_ADDITIONAL_CONSTRAINT_IDENTIFIED", &[]),
            _ => ("NO_ADDITIONAL_CONSTRAINT_IDENTIFIED", &[]),
        };
        let roles = element
            .roles
            .iter()
            .map(|x| format!("{x:?}").to_uppercase())
            .collect();
        rows.push(CollisionDisposition {
            collision_id: format!("G2_COLLISION_{serial:03}"),
            g2_element: element.element_id,
            g2_roles: roles,
            g3_disposition: disposition.into(),
            constraint_ids: ids.iter().map(|x| (*x).into()).collect(),
            evidence: if ids.is_empty() {
                "No additional constraint was earned; absence is not a proof that none exists."
                    .into()
            } else {
                format!("Direct G1 semantic derivation: {}", ids.join(","))
            },
        });
    }
    if rows.len() != 37 {
        return Err(format!("G2_COLLISION_COUNT_DRIFT:{}", rows.len()));
    }
    let known = constraints
        .iter()
        .map(|x| x.constraint_id.as_str())
        .collect::<std::collections::HashSet<_>>();
    if rows
        .iter()
        .flat_map(|x| &x.constraint_ids)
        .any(|x| !known.contains(x.as_str()))
    {
        return Err("UNKNOWN_CONSTRAINT_REFERENCE".into());
    }
    Ok(rows)
}

pub fn execute() -> Result<AuditProducts, String> {
    let constraints = constraints();
    let witnesses = witness_corpus()?;
    for witness in &witnesses {
        let replay = replay_witness(witness)?;
        let same = match (&replay, &witness.target_result) {
            (
                TransitionResult::Applied {
                    next_state: a,
                    emissions: ae,
                },
                TransitionResult::Applied {
                    next_state: b,
                    emissions: be,
                },
            ) => a == b && ae == be,
            (
                TransitionResult::Rejected { reason: a },
                TransitionResult::Rejected { reason: b },
            ) => a == b,
            _ => false,
        };
        if !same {
            return Err(format!("WITNESS_REPLAY_DRIFT:{}", witness.witness_id));
        }
    }
    let collisions = collision_map(&constraints)?;
    Ok(AuditProducts {
        constraints,
        witnesses,
        bounds: bounds(),
        unreachability: unreachability(),
        collisions,
    })
}
