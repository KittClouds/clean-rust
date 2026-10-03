use crate::model::{
    CarryStatus, DependencyEdge, DependencyGraph, EdgeKind, ElementRole, GraphNode, Role, Surface,
};
use hashbrown::{HashMap, HashSet};
use serde_json::{Value, json};

pub(crate) fn axis_count(roles: &[Role]) -> usize {
    let mut axes = HashSet::new();
    for role in roles {
        let axis = match role {
            Role::ControlStateQ => Some("Q"),
            Role::GuardRegister | Role::UsedInGuard => Some("R_GUARD"),
            Role::ArithmeticRegister
            | Role::AffineUpdate
            | Role::PiecewiseAffineUpdate
            | Role::NonlinearUpdate
            | Role::UsedInArithmetic => Some("R_ARITHMETIC"),
            Role::StaticContextC => Some("C"),
            Role::ObservationO => Some("O"),
            Role::ProvenanceP | Role::ProvenanceOnly => Some("P"),
            Role::DerivedEmission => Some("EMISSION"),
            _ => None,
        };
        if let Some(axis) = axis {
            axes.insert(axis);
        }
    }
    axes.len()
}

pub(crate) fn dependency_graph(elements: &[ElementRole]) -> Result<DependencyGraph, String> {
    let operations = [
        "op.context_validation",
        "op.input_validation",
        "op.chronology_guard",
        "op.next_bar_index",
        "op.upper_renewal_guard",
        "op.upper_candidate_update",
        "op.lower_renewal_guard",
        "op.lower_candidate_update",
        "op.upper_giveback",
        "op.lower_giveback",
        "op.range_availability_guard",
        "op.location_classification",
        "op.upper_extension",
        "op.lower_extension",
        "op.coverage_copy",
        "op.emission_assembly",
    ];
    let mut nodes = elements
        .iter()
        .map(|x| GraphNode {
            node_id: x.element_id.clone(),
            node_kind: format!("{:?}", x.surface).to_uppercase(),
        })
        .collect::<Vec<_>>();
    nodes.extend(operations.iter().map(|id| GraphNode {
        node_id: (*id).into(),
        node_kind: "OPERATION".into(),
    }));
    let mut edges = Vec::with_capacity(100);
    let mut add = |source: &str, target: &str, kind: EdgeKind, condition: Option<&str>| {
        edges.push(DependencyEdge {
            source: source.into(),
            target: target.into(),
            kind,
            condition: condition.map(str::to_owned),
        });
    };

    for context in [
        "context.price_scale",
        "context.source_time_resolution_ns",
        "context.storage_time_resolution_ns",
        "context.observation_cadence_ns",
        "context.range.k",
    ] {
        add(context, "op.context_validation", EdgeKind::Guards, None);
    }
    for input in [
        "input.input_authority",
        "input.open_ticks",
        "input.high_ticks",
        "input.low_ticks",
        "input.close_ticks",
        "input.price_scale",
        "input.source_time_resolution_ns",
        "input.observation_cadence_ns",
    ] {
        add(input, "op.input_validation", EdgeKind::Guards, None);
    }
    for context in [
        "context.session_start_ns",
        "context.session_terminal_ns",
        "context.observation_cadence_ns",
    ] {
        add(context, "op.chronology_guard", EdgeKind::Guards, None);
    }
    add(
        "state.knowledge_time_ns",
        "op.chronology_guard",
        EdgeKind::Reads,
        Some("after initialization"),
    );
    add(
        "input.event_time_ns",
        "op.chronology_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "input.knowledge_time_ns",
        "op.chronology_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "state.initialized",
        "op.chronology_guard",
        EdgeKind::Guards,
        Some("select first-step chronology rule"),
    );
    add(
        "state.window_active",
        "op.context_validation",
        EdgeKind::Guards,
        Some("reject inconsistent uninitialized state"),
    );

    add(
        "state.bar_index",
        "op.next_bar_index",
        EdgeKind::Reads,
        None,
    );
    add(
        "op.next_bar_index",
        "state.bar_index",
        EdgeKind::Increments,
        Some("prior + 1; first step resets to 0"),
    );
    add(
        "input.knowledge_time_ns",
        "state.knowledge_time_ns",
        EdgeKind::Copies,
        None,
    );
    add(
        "input.close_ticks",
        "state.close_ticks",
        EdgeKind::Copies,
        None,
    );
    add("input.coverage", "op.coverage_copy", EdgeKind::Reads, None);
    add(
        "op.coverage_copy",
        "state.coverage_complete",
        EdgeKind::Copies,
        None,
    );
    add(
        "op.context_validation",
        "state.window_active",
        EdgeKind::Updates,
        Some("true after admitted step"),
    );
    add(
        "op.context_validation",
        "state.initialized",
        EdgeKind::Updates,
        Some("true after admitted step"),
    );

    upper_edges(&mut add);
    lower_edges(&mut add);
    range_edges(&mut add);
    emission_edges(&mut add);

    let node_ids = nodes
        .iter()
        .map(|x| x.node_id.clone())
        .collect::<HashSet<_>>();
    let dangling = edges
        .iter()
        .filter(|x| !node_ids.contains(&x.source) || !node_ids.contains(&x.target))
        .count();
    let mut kinds = edges.iter().map(|x| x.kind).collect::<HashSet<_>>();
    let mut edge_kinds_present = kinds.drain().collect::<Vec<_>>();
    edge_kinds_present.sort_by_key(|x| format!("{x:?}"));
    if dangling != 0 {
        return Err("DEPENDENCY_GRAPH_DANGLING_EDGE".into());
    }
    Ok(DependencyGraph {
        schema: "G2_TRANSITION_DEPENDENCY_GRAPH_V1",
        nodes,
        edges,
        edge_kinds_present,
        dangling_edge_count: dangling,
        status: "PASS",
    })
}

fn upper_edges(add: &mut impl FnMut(&str, &str, EdgeKind, Option<&str>)) {
    add(
        "input.high_ticks",
        "op.upper_renewal_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "state.upper.value_ticks",
        "op.upper_renewal_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "op.upper_renewal_guard",
        "op.upper_candidate_update",
        EdgeKind::Guards,
        None,
    );
    for field in [
        "state.upper.id",
        "state.upper.value_ticks",
        "state.upper.birth_bar_index",
        "state.upper.birth_knowledge_time_ns",
        "state.upper.age_bars",
    ] {
        add(
            field,
            "op.upper_candidate_update",
            EdgeKind::Reads,
            Some("hold branch"),
        );
        add("op.upper_candidate_update", field, EdgeKind::Updates, None);
    }
    add(
        "input.high_ticks",
        "state.upper.value_ticks",
        EdgeKind::Copies,
        Some("renewal"),
    );
    add(
        "state.upper.id",
        "state.upper.id",
        EdgeKind::Increments,
        Some("renewal"),
    );
    add(
        "op.next_bar_index",
        "state.upper.birth_bar_index",
        EdgeKind::Resets,
        Some("renewal"),
    );
    add(
        "input.knowledge_time_ns",
        "state.upper.birth_knowledge_time_ns",
        EdgeKind::Resets,
        Some("renewal"),
    );
    add(
        "state.upper.age_bars",
        "state.upper.age_bars",
        EdgeKind::Increments,
        Some("hold"),
    );
    add(
        "op.upper_renewal_guard",
        "state.upper.age_bars",
        EdgeKind::Resets,
        Some("renewal to zero"),
    );
    add(
        "state.upper.value_ticks",
        "op.upper_giveback",
        EdgeKind::Reads,
        None,
    );
    add(
        "input.close_ticks",
        "op.upper_giveback",
        EdgeKind::Reads,
        None,
    );
    add(
        "op.upper_giveback",
        "state.upper_giveback_ticks",
        EdgeKind::Derives,
        None,
    );
}

fn lower_edges(add: &mut impl FnMut(&str, &str, EdgeKind, Option<&str>)) {
    add(
        "input.low_ticks",
        "op.lower_renewal_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "state.lower.value_ticks",
        "op.lower_renewal_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "op.lower_renewal_guard",
        "op.lower_candidate_update",
        EdgeKind::Guards,
        None,
    );
    for field in [
        "state.lower.id",
        "state.lower.value_ticks",
        "state.lower.birth_bar_index",
        "state.lower.birth_knowledge_time_ns",
        "state.lower.age_bars",
    ] {
        add(
            field,
            "op.lower_candidate_update",
            EdgeKind::Reads,
            Some("hold branch"),
        );
        add("op.lower_candidate_update", field, EdgeKind::Updates, None);
    }
    add(
        "input.low_ticks",
        "state.lower.value_ticks",
        EdgeKind::Copies,
        Some("renewal"),
    );
    add(
        "state.lower.id",
        "state.lower.id",
        EdgeKind::Increments,
        Some("renewal"),
    );
    add(
        "op.next_bar_index",
        "state.lower.birth_bar_index",
        EdgeKind::Resets,
        Some("renewal"),
    );
    add(
        "input.knowledge_time_ns",
        "state.lower.birth_knowledge_time_ns",
        EdgeKind::Resets,
        Some("renewal"),
    );
    add(
        "state.lower.age_bars",
        "state.lower.age_bars",
        EdgeKind::Increments,
        Some("hold"),
    );
    add(
        "op.lower_renewal_guard",
        "state.lower.age_bars",
        EdgeKind::Resets,
        Some("renewal to zero"),
    );
    add(
        "state.lower.value_ticks",
        "op.lower_giveback",
        EdgeKind::Reads,
        None,
    );
    add(
        "input.close_ticks",
        "op.lower_giveback",
        EdgeKind::Reads,
        None,
    );
    add(
        "op.lower_giveback",
        "state.lower_giveback_ticks",
        EdgeKind::Derives,
        None,
    );
}

fn range_edges(add: &mut impl FnMut(&str, &str, EdgeKind, Option<&str>)) {
    add(
        "input.knowledge_time_ns",
        "op.range_availability_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "context.range.freeze_commit_time_ns",
        "op.range_availability_guard",
        EdgeKind::Compares,
        None,
    );
    add(
        "op.range_availability_guard",
        "op.location_classification",
        EdgeKind::Guards,
        None,
    );
    add(
        "input.close_ticks",
        "op.location_classification",
        EdgeKind::Compares,
        None,
    );
    add(
        "context.range.high_ticks",
        "op.location_classification",
        EdgeKind::Compares,
        None,
    );
    add(
        "context.range.low_ticks",
        "op.location_classification",
        EdgeKind::Compares,
        None,
    );
    add(
        "op.location_classification",
        "state.range_locations",
        EdgeKind::Derives,
        None,
    );
    add(
        "state.range_locations",
        "op.emission_assembly",
        EdgeKind::Reads,
        None,
    );
    add(
        "state.upper.value_ticks",
        "op.upper_extension",
        EdgeKind::Reads,
        None,
    );
    add(
        "context.range.high_ticks",
        "op.upper_extension",
        EdgeKind::Reads,
        None,
    );
    add(
        "op.range_availability_guard",
        "op.upper_extension",
        EdgeKind::Guards,
        None,
    );
    add(
        "op.upper_extension",
        "state.upper_extensions_ticks",
        EdgeKind::Derives,
        None,
    );
    add(
        "state.lower.value_ticks",
        "op.lower_extension",
        EdgeKind::Reads,
        None,
    );
    add(
        "context.range.low_ticks",
        "op.lower_extension",
        EdgeKind::Reads,
        None,
    );
    add(
        "op.range_availability_guard",
        "op.lower_extension",
        EdgeKind::Guards,
        None,
    );
    add(
        "op.lower_extension",
        "state.lower_extensions_ticks",
        EdgeKind::Derives,
        None,
    );
}

fn emission_edges(add: &mut impl FnMut(&str, &str, EdgeKind, Option<&str>)) {
    for (source, target) in [
        ("input.source_row_id", "emission.commit.source_row_id"),
        (
            "input.knowledge_time_ns",
            "emission.commit.knowledge_time_ns",
        ),
        ("input.coverage", "emission.commit.coverage"),
        ("state.upper.id", "emission.new_upper.candidate_id"),
        ("state.upper.id", "emission.upper_id_change.current"),
        ("state.lower.id", "emission.new_lower.candidate_id"),
        ("state.lower.id", "emission.lower_id_change.current"),
        ("context.range.k", "emission.location.k"),
        ("state.range_locations", "emission.location.current"),
        (
            "input.knowledge_time_ns",
            "emission.location.knowledge_time_ns",
        ),
    ] {
        add(source, target, EdgeKind::Copies, None);
        add(target, "op.emission_assembly", EdgeKind::Emits, None);
    }
    add(
        "state.upper.id",
        "emission.upper_id_change.prior",
        EdgeKind::Copies,
        Some("prior state"),
    );
    add(
        "state.lower.id",
        "emission.lower_id_change.prior",
        EdgeKind::Copies,
        Some("prior state"),
    );
    add(
        "state.range_locations",
        "emission.location.prior",
        EdgeKind::Copies,
        Some("prior state"),
    );
    for target in [
        "emission.upper_id_change.prior",
        "emission.lower_id_change.prior",
        "emission.location.prior",
    ] {
        add(target, "op.emission_assembly", EdgeKind::Emits, None);
    }
    add(
        "op.upper_renewal_guard",
        "op.emission_assembly",
        EdgeKind::Guards,
        Some("upper event presence"),
    );
    add(
        "op.lower_renewal_guard",
        "op.emission_assembly",
        EdgeKind::Guards,
        Some("lower event presence"),
    );
}

pub(crate) fn qualify(elements: &[ElementRole], graph: &DependencyGraph) -> Result<Value, String> {
    let ids = elements
        .iter()
        .map(|x| x.element_id.as_str())
        .collect::<HashSet<_>>();
    if ids.len() != elements.len() {
        return Err("DUPLICATE_ELEMENT_ID".into());
    }
    let expected_state = [
        "state.initialized",
        "state.bar_index",
        "state.knowledge_time_ns",
        "state.upper.id",
        "state.upper.value_ticks",
        "state.upper.birth_bar_index",
        "state.upper.birth_knowledge_time_ns",
        "state.upper.age_bars",
        "state.lower.id",
        "state.lower.value_ticks",
        "state.lower.birth_bar_index",
        "state.lower.birth_knowledge_time_ns",
        "state.lower.age_bars",
        "state.close_ticks",
        "state.upper_giveback_ticks",
        "state.lower_giveback_ticks",
        "state.range_locations",
        "state.upper_extensions_ticks",
        "state.lower_extensions_ticks",
        "state.window_active",
        "state.coverage_complete",
    ];
    let actual_state = elements
        .iter()
        .filter(|x| x.surface == Surface::KernelState)
        .map(|x| x.element_id.as_str())
        .collect::<HashSet<_>>();
    let expected_state_set = expected_state.into_iter().collect::<HashSet<_>>();
    if actual_state != expected_state_set {
        return Err("G1_STATE_SURFACE_CENSUS_MISMATCH".into());
    }
    if elements
        .iter()
        .any(|x| x.roles.is_empty() || x.carry_status.is_empty())
    {
        return Err("UNCLASSIFIED_ELEMENT".into());
    }
    let edge_kinds = graph.edges.iter().map(|x| x.kind).collect::<HashSet<_>>();
    let required_edges = [
        EdgeKind::Reads,
        EdgeKind::Guards,
        EdgeKind::Updates,
        EdgeKind::Derives,
        EdgeKind::Emits,
        EdgeKind::Copies,
        EdgeKind::Resets,
        EdgeKind::Increments,
        EdgeKind::Compares,
    ];
    if required_edges.iter().any(|x| !edge_kinds.contains(x)) {
        return Err("EDGE_KIND_COVERAGE_FAILURE".into());
    }
    let graph_elements = graph
        .edges
        .iter()
        .flat_map(|x| [x.source.as_str(), x.target.as_str()])
        .collect::<HashSet<_>>();
    let uncovered = elements
        .iter()
        .filter(|x| {
            !graph_elements.contains(x.element_id.as_str())
                && !x.roles.contains(&Role::ProvenanceOnly)
        })
        .map(|x| x.element_id.clone())
        .collect::<Vec<_>>();
    if !uncovered.is_empty() {
        return Err(format!("GRAPH_ELEMENT_COVERAGE_FAILURE:{uncovered:?}"));
    }
    let serialized = serde_json::to_string(elements).map_err(|x| x.to_string())?;
    for forbidden in ["REDUNDANT", "REMOVABLE", "UNIMPORTANT", "MINIMAL_STATE"] {
        if serialized.contains(forbidden) {
            return Err(format!("FORBIDDEN_G2_JUDGMENT:{forbidden}"));
        }
    }
    Ok(json!({
        "schema":"G2_ROLE_AND_GRAPH_QUALIFICATION_V1",
        "elements":elements.len(),
        "kernel_state_elements":actual_state.len(),
        "all_elements_have_roles":true,
        "all_elements_have_carry_status":true,
        "non_provenance_elements_in_graph":true,
        "edge_kinds_required":required_edges,
        "edge_kinds_present":graph.edge_kinds_present,
        "dangling_edges":graph.dangling_edge_count,
        "importance_or_removability_judgments":0,
        "status":"PASS"
    }))
}

pub(crate) fn collision_registry(elements: &[ElementRole]) -> Value {
    let collisions = elements
        .iter()
        .filter(|x| x.multi_role_collision)
        .map(|x| {
            json!({
                "element_id":x.element_id,
                "roles":x.roles,
                "axis_count":axis_count(&x.roles),
                "classification":"MULTI_ROLE_COLLISION",
                "interpretation":"DESCRIPTIVE_USE_COLLISION_ONLY"
            })
        })
        .collect::<Vec<_>>();
    json!({
        "schema":"G2_MULTI_ROLE_COLLISION_REGISTRY_V1",
        "collision_count":collisions.len(),
        "collisions":collisions,
        "collision_implies_refactor":false,
        "status":"QUALIFIED"
    })
}

pub(crate) fn carry_ledger(elements: &[ElementRole]) -> Value {
    let mut counts = HashMap::<String, usize>::new();
    for element in elements {
        for status in &element.carry_status {
            *counts.entry(carry_name(*status).into()).or_default() += 1;
        }
    }
    json!({
        "schema":"G2_CAUSAL_CARRY_STATUS_LEDGER_V1",
        "statuses":["MUTABLE_CARRIED_STATE","IMMUTABLE_CONTEXT","CURRENT_INPUT_ONLY","DERIVED_WITHIN_STEP","EMISSION_ONLY","PROVENANCE_ONLY"],
        "counts":counts,
        "sampling_or_importance_order":"NONE",
        "status":"QUALIFIED"
    })
}

fn carry_name(value: CarryStatus) -> &'static str {
    match value {
        CarryStatus::MutableCarriedState => "MUTABLE_CARRIED_STATE",
        CarryStatus::ImmutableContext => "IMMUTABLE_CONTEXT",
        CarryStatus::CurrentInputOnly => "CURRENT_INPUT_ONLY",
        CarryStatus::DerivedWithinStep => "DERIVED_WITHIN_STEP",
        CarryStatus::EmissionOnly => "EMISSION_ONLY",
        CarryStatus::ProvenanceOnly => "PROVENANCE_ONLY",
    }
}

pub(crate) fn typed_findings(elements: &[ElementRole], graph: &DependencyGraph) -> Value {
    let collisions = elements.iter().filter(|x| x.multi_role_collision).count();
    json!({
        "schema":"G2_TYPED_FINDINGS_V1",
        "findings":[
            {"finding":"COMPLETE_G1_KERNEL_ROLE_CENSUS","state":"QUALIFIED","authority_basis":"SEALED_G1_TYPES_PLUS_TRANSITION_DEPENDENCY"},
            {"finding":"TRANSITION_DEPENDENCY_GRAPH","state":graph.status,"nodes":graph.nodes.len(),"edges":graph.edges.len()},
            {"finding":"MULTI_ROLE_COLLISIONS","state":"OBSERVED","count":collisions,"disposition":"PRESERVE"},
            {"finding":"GRAMMAR_STATE_AND_EVENT","state":"NOT_EVALUABLE","reason":"G1 propagated absent qualified grammar stream"},
            {"finding":"REMOVABILITY","state":"NOT_AUTHORIZED"},
            {"finding":"MINIMAL_OR_NECESSARY_MEMORY","state":"NOT_AUTHORIZED"},
            {"finding":"REACHABILITY","state":"NOT_AUTHORIZED"}
        ],
        "governing_law":"CLASSIFY_USE_NOT_IMPORTANCE"
    })
}
