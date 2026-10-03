use crate::model::{
    AuthorityMembership as M, ComparisonStatus as X, ContextRole as C, ElementDisposition,
    ElementG4Role as E, PreservationScope as S, RetentionFidelity as F, SurfaceProducts,
};
use crate::registry;
use hashbrown::{HashMap, HashSet};
use obs_open_04a_g2::census;
use serde_json::Value;

pub fn execute() -> Result<SurfaceProducts, String> {
    let g2 = census::execute()?;
    let constraints = collision_constraints(&g2.collisions)?;
    let observables = registry::observables();
    let known = observables
        .iter()
        .map(|x| x.observable_id.clone())
        .collect::<HashSet<_>>();
    let mut elements = Vec::with_capacity(g2.elements.len());
    for element in g2.elements {
        let inherited = constraints
            .get(&element.element_id)
            .cloned()
            .filter(|x| !x.is_empty())
            .unwrap_or_else(|| g3_ids(&element.element_id));
        let row = classify(
            &element.element_id,
            element.roles.iter().map(role_name).collect(),
            inherited,
        )?;
        if row.authority_membership == M::InAuthority
            && row.mapped_observable_ids.iter().any(|x| !known.contains(x))
        {
            return Err(format!("UNKNOWN_OBSERVABLE: {}", row.element_id));
        }
        elements.push(row);
    }
    if elements.len() != 57 {
        return Err(format!("G2_ELEMENT_COUNT_DRIFT:{}", elements.len()));
    }
    let unique = elements
        .iter()
        .map(|x| x.element_id.clone())
        .collect::<HashSet<_>>();
    if unique.len() != 57 {
        return Err("DUPLICATE_ELEMENT_DISPOSITION".into());
    }
    Ok(SurfaceProducts {
        observables,
        elements,
    })
}

fn role_name(role: &obs_open_04a_g2::model::Role) -> String {
    serde_json::to_value(role)
        .expect("serializable G2 role")
        .as_str()
        .expect("string G2 role")
        .to_owned()
}

fn collision_constraints(value: &Value) -> Result<HashMap<String, Vec<String>>, String> {
    let mut map = HashMap::new();
    for row in value["collisions"]
        .as_array()
        .ok_or("G2_COLLISION_SCHEMA")?
    {
        let id = row["element_id"]
            .as_str()
            .ok_or("G2_COLLISION_ID")?
            .to_owned();
        map.insert(id, g3_ids(row["element_id"].as_str().unwrap()));
    }
    Ok(map)
}

fn g3_ids(id: &str) -> Vec<String> {
    let ids: &[&str] = match id {
        "state.initialized" | "state.window_active" => &["G3-C001"],
        "state.bar_index" => &["G3-C002", "G3-C009", "G3-C022"],
        "state.knowledge_time_ns" => &["G3-C003", "G3-C010", "G3-C013"],
        "state.upper.id" | "state.lower.id" => &["G3-C007", "G3-C017", "G3-C022"],
        "state.upper.value_ticks" | "state.lower.value_ticks" => {
            &["G3-C005", "G3-C006", "G3-C011", "G3-C012", "G3-C015"]
        }
        "state.upper.birth_bar_index" | "state.lower.birth_bar_index" => &["G3-C009", "G3-C022"],
        "state.upper.birth_knowledge_time_ns" | "state.lower.birth_knowledge_time_ns" => {
            &["G3-C010"]
        }
        "state.upper.age_bars" | "state.lower.age_bars" => &["G3-C008", "G3-C009", "G3-C010"],
        "state.close_ticks" => &["G3-C011", "G3-C012", "G3-C014"],
        "state.upper_giveback_ticks" | "state.lower_giveback_ticks" => &["G3-C012"],
        "state.range_locations" => &["G3-C013", "G3-C014", "G3-C018"],
        "state.upper_extensions_ticks" | "state.lower_extensions_ticks" => &["G3-C013", "G3-C015"],
        "state.coverage_complete" | "input.coverage" | "emission.commit.coverage" => {
            &["G3-C016", "G3-C019"]
        }
        x if x.contains("session_start")
            || x.contains("session_terminal")
            || x.contains("cadence")
            || x.contains("event_time")
            || x == "input.knowledge_time_ns" =>
        {
            &["G3-C003", "G3-C020"]
        }
        "context.range.high_ticks" | "context.range.low_ticks" => &["G3-C014", "G3-C015"],
        "context.range.freeze_commit_time_ns"
        | "context.range.k"
        | "emission.location.k"
        | "emission.location.prior"
        | "emission.location.current" => &["G3-C013", "G3-C014", "G3-C018"],
        "input.open_ticks" | "input.high_ticks" | "input.low_ticks" | "input.close_ticks" => {
            &["G3-C004", "G3-C005", "G3-C011"]
        }
        x if x.contains("price_scale")
            || x.contains("source_time_resolution")
            || x.contains("storage_time_resolution")
            || x == "input.input_authority" =>
        {
            &["G3-C020", "G3-C021"]
        }
        "input.source_row_id" | "emission.commit.source_row_id" => &["G3-C016"],
        "emission.commit.knowledge_time_ns" => &["G3-C016"],
        x if x.starts_with("emission.new_") || x.contains("_id_change.") => &["G3-C017"],
        "emission.location.knowledge_time_ns" => &["G3-C018"],
        _ => &[],
    };
    ids.iter().map(|x| (*x).into()).collect()
}

fn classify(id: &str, roles: Vec<String>, g3: Vec<String>) -> Result<ElementDisposition, String> {
    let excluded = matches!(
        id,
        "context.session_id" | "input.source_row_id" | "emission.commit.source_row_id"
    );
    if excluded {
        let reason = if id == "context.session_id" {
            "OPAQUE_EXECUTION_LOCATOR_NOT_DECLARED_PART_OF_CAUSAL_OBSERVER_BEHAVIOR"
        } else {
            "OPAQUE_SOURCE_ROW_LOCATOR_EXCLUDED_WHILE_COMMIT_EVENT_KIND_TIME_AND_COVERAGE_REMAIN_PROTECTED"
        };
        return Ok(ElementDisposition {
            element_id: id.into(),
            g2_roles: roles,
            g3_constraint_ids: g3,
            element_g4_role: E::NotInAuthority,
            authority_membership: M::NotInAuthority,
            mapped_observable_ids: vec![],
            retention_fidelity: None,
            scopes: vec![],
            context_role: if id.starts_with("context.") {
                C::ProvenanceOnly
            } else {
                C::NotApplicable
            },
            temporal_authority: "NOT_APPLICABLE".into(),
            ordering_authority: "NOT_APPLICABLE".into(),
            genealogy_sensitive: false,
            representation_sensitive: true,
            cross_history_comparison: X::NotApplicable,
            normative_reason: reason.into(),
            authority_source: vec!["G4_NORMATIVE_CAUSAL_BEHAVIOR_BOUNDARY".into()],
            not_evaluable_reason: None,
        });
    }
    let mapped = mapped_observables(id);
    if mapped.is_empty() {
        return Err(format!("UNMAPPED_IN_AUTHORITY_ELEMENT:{id}"));
    }
    let fidelity = fidelity(id);
    let scopes = scopes(id);
    let role = if id.starts_with("context.") {
        E::ContextParameter
    } else if id.starts_with("input.") || id.contains(".id") || id.contains("birth_") {
        E::ContributesToObservable
    } else {
        E::DirectObservable
    };
    Ok(ElementDisposition {
        element_id: id.into(),
        g2_roles: roles,
        g3_constraint_ids: g3,
        element_g4_role: role,
        authority_membership: M::InAuthority,
        mapped_observable_ids: mapped,
        retention_fidelity: Some(fidelity),
        scopes,
        context_role: if id.starts_with("context.") {
            C::InterpretationParameter
        } else {
            C::NotApplicable
        },
        temporal_authority: if temporal(id) {
            "SEMANTIC_TIME_UNDER_TEMPORAL_AUTHORITY_V1".into()
        } else {
            "NOT_APPLICABLE".into()
        },
        ordering_authority: ordering(id).into(),
        genealogy_sensitive: genealogy(id),
        representation_sensitive: id.contains(".id") || id.contains("_ns") || id.contains("_ticks"),
        cross_history_comparison: X::Deferred,
        normative_reason: normative_reason(id).into(),
        authority_source: vec![
            "G1_EXACT_SEMANTIC_KERNEL".into(),
            "G2_ROLE_CENSUS".into(),
            "G3_REACHABILITY_CONSTRAINTS".into(),
            "G4_NORMATIVE_SELECTION".into(),
        ],
        not_evaluable_reason: None,
    })
}

fn mapped_observables(id: &str) -> Vec<String> {
    let ids: &[&str] = match id {
        "state.initialized" | "state.window_active" => {
            &["COB_LIFECYCLE_STATE", "COB_CAUSAL_TRANSITION_LAW"]
        }
        "state.bar_index" => &["COB_TRANSITION_ORDINAL", "COB_ORDERED_TRACE_COORDINATES"],
        "state.upper.birth_knowledge_time_ns" => {
            &["COB_AUTHORITATIVE_TIME", "COB_UPPER_CANDIDATE_GENEALOGY"]
        }
        "state.lower.birth_knowledge_time_ns" => {
            &["COB_AUTHORITATIVE_TIME", "COB_LOWER_CANDIDATE_GENEALOGY"]
        }
        "emission.commit.knowledge_time_ns" => {
            &["COB_AUTHORITATIVE_TIME", "COB_OBSERVATION_COMMIT_EVENT"]
        }
        "emission.location.knowledge_time_ns" => &[
            "COB_AUTHORITATIVE_TIME",
            "COB_LOCATION_TRANSITION_EVENT_ORDER",
        ],
        x if x.contains("knowledge_time")
            || x.contains("event_time")
            || x.contains("birth_knowledge_time") =>
        {
            &["COB_AUTHORITATIVE_TIME"]
        }
        x if x.starts_with("state.upper.")
            && (x.contains("id") || x.contains("birth") || x.contains("age")) =>
        {
            &["COB_UPPER_CANDIDATE_GENEALOGY"]
        }
        x if x.starts_with("state.lower.")
            && (x.contains("id") || x.contains("birth") || x.contains("age")) =>
        {
            &["COB_LOWER_CANDIDATE_GENEALOGY"]
        }
        "state.upper.value_ticks" | "state.lower.value_ticks" => &["COB_RUNNING_EXTREME_GEOMETRY"],
        "state.close_ticks" => &["COB_COMMITTED_CLOSE"],
        "state.upper_giveback_ticks" | "state.lower_giveback_ticks" => &["COB_GIVEBACK_GEOMETRY"],
        "state.range_locations" => &["COB_RANGE_LOCATION_STATE"],
        "state.upper_extensions_ticks" | "state.lower_extensions_ticks" => {
            &["COB_RANGE_EXTENSION_GEOMETRY"]
        }
        x if x.contains("coverage") => &["COB_COVERAGE_STATE", "COB_OBSERVATION_COMMIT_EVENT"],
        "context.session_start_ns"
        | "context.session_terminal_ns"
        | "context.observation_cadence_ns"
        | "input.observation_cadence_ns" => &["COB_SESSION_TIME_CONTEXT", "COB_AUTHORITATIVE_TIME"],
        "context.price_scale" | "input.price_scale" => &["COB_PRICE_UNIT_CONTEXT"],
        "context.source_time_resolution_ns"
        | "context.storage_time_resolution_ns"
        | "input.source_time_resolution_ns" => {
            &["COB_TIME_RESOLUTION_CONTEXT", "COB_AUTHORITATIVE_TIME"]
        }
        x if x.starts_with("context.range.") => &["COB_RANGE_CONTEXT"],
        "input.input_authority" => &["COB_INPUT_AUTHORITY_CLASS", "COB_TRANSITION_RESULT_CLASS"],
        "input.open_ticks" | "input.high_ticks" | "input.low_ticks" | "input.close_ticks" => {
            &["COB_PRESENTED_BAR_GEOMETRY", "COB_CAUSAL_TRANSITION_LAW"]
        }
        x if x.starts_with("emission.new_upper") || x.starts_with("emission.upper_id_change") => &[
            "COB_UPPER_CANDIDATE_GENEALOGY",
            "COB_CANDIDATE_RENEWAL_EVENT_ORDER",
        ],
        x if x.starts_with("emission.new_lower") || x.starts_with("emission.lower_id_change") => &[
            "COB_LOWER_CANDIDATE_GENEALOGY",
            "COB_CANDIDATE_RENEWAL_EVENT_ORDER",
        ],
        x if x.starts_with("emission.location.") => &[
            "COB_LOCATION_TRANSITION_EVENT_ORDER",
            "COB_RANGE_LOCATION_STATE",
        ],
        _ => &[],
    };
    ids.iter().map(|x| (*x).into()).collect()
}

fn fidelity(id: &str) -> F {
    if id.contains(".id")
        || id.contains("birth_")
        || id.contains("age_bars")
        || id.starts_with("emission.new_")
        || id.contains("_id_change")
    {
        F::RelationalStructure
    } else if id.contains("initialized")
        || id.contains("window_active")
        || id.contains("coverage")
        || id == "input.input_authority"
        || id.contains("range_locations")
        || id.contains("emission.location.prior")
        || id.contains("emission.location.current")
    {
        F::SemanticClass
    } else if id.starts_with("emission.") {
        F::StructureOnly
    } else {
        F::ExactSemanticValue
    }
}
fn scopes(id: &str) -> Vec<S> {
    if id.starts_with("context.") {
        if temporal(id) {
            vec![S::Timing, S::ContextConditional]
        } else {
            vec![S::ContextConditional]
        }
    } else if id.starts_with("input.") {
        if temporal(id) {
            vec![S::Transition, S::Timing, S::ContextConditional]
        } else {
            vec![S::Transition, S::ContextConditional]
        }
    } else if id.starts_with("emission.") {
        if genealogy(id) {
            vec![S::Emission, S::OrderedTrace, S::Genealogy]
        } else if temporal(id) {
            vec![S::Emission, S::OrderedTrace, S::Timing]
        } else {
            vec![S::Emission, S::OrderedTrace]
        }
    } else if genealogy(id) {
        vec![S::StateSnapshot, S::Transition, S::Genealogy]
    } else if temporal(id) {
        vec![S::StateSnapshot, S::Transition, S::Timing]
    } else {
        vec![S::StateSnapshot, S::Transition]
    }
}
fn temporal(id: &str) -> bool {
    id.contains("time")
        || id.contains("cadence")
        || id.contains("bar_index")
        || id.contains("age_bars")
}
fn ordering(id: &str) -> &'static str {
    if id.starts_with("emission.") {
        "INTRA_TRANSITION_EMISSION_ORDER_AUTHORITATIVE"
    } else if id == "state.bar_index" {
        "INTER_TRANSITION_ORDER_AUTHORITATIVE"
    } else {
        "NOT_APPLICABLE"
    }
}
fn genealogy(id: &str) -> bool {
    id.contains("state.upper.id")
        || id.contains("state.lower.id")
        || id.contains("birth_")
        || id.contains("age_bars")
        || id.contains("new_upper")
        || id.contains("new_lower")
        || id.contains("id_change")
}
fn normative_reason(id: &str) -> &'static str {
    if id.starts_with("context.") {
        "SEMANTIC_INTERPRETATION_PARAMETER_REQUIRED_BY_CAUSAL_OBSERVER_BEHAVIOR"
    } else if id.starts_with("input.") {
        "PRESENTED_STIMULUS_SEMANTICS_REQUIRED_TO_INTERPRET_APPLIED_OR_REJECTED_OBSERVER_BEHAVIOR"
    } else if id.starts_with("emission.") {
        "ORDERED_SOURCE_AUTHORITATIVE_EMISSION_BEHAVIOR"
    } else {
        "SOURCE_AUTHORITATIVE_CAUSAL_STATE_OR_DERIVED_MEASUREMENT_SELECTED_FOR_PRESERVATION"
    }
}
