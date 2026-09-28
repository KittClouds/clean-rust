use crate::scheduler::SearchError;
use crate::types::{
    PosthocEventLabel, PosthocSidecar, PrefixBudget, PrefixBudgetRecord, PrefixMetrics, RunTrace,
};
use hashbrown::HashSet;
use r1_world::{automorphisms, canonical_assignment, validate, Task};

/// Join exact validator labels after online search has returned a closed trace.
/// This function is the only place in `r1-search` that imports the private
/// typed task or validator.
pub fn annotate_posthoc(task: &Task, trace: &RunTrace) -> Result<PosthocSidecar, SearchError> {
    if task.id != trace.header.task_id {
        return Err(SearchError::ReplayInput(
            "post-hoc task id does not match closed trace".to_owned(),
        ));
    }
    let group = automorphisms(task);
    let initial = trace
        .header
        .initial_particles
        .first()
        .ok_or_else(|| SearchError::ReplayInput("trace has no initial state".to_owned()))?;
    let initial_valid = validate(task, &initial.assignment);
    let initial_class = initial_valid.then(|| canonical_assignment(&initial.assignment, &group));
    let mut labels = Vec::with_capacity(trace.events.len());
    for event in &trace.events {
        let valid = validate(task, &event.assignment_after);
        labels.push(PosthocEventLabel {
            event_index: event.event_index,
            valid,
            canonical_solution_class: valid
                .then(|| canonical_assignment(&event.assignment_after, &group)),
        });
    }
    Ok(PosthocSidecar {
        schema: "r1-posthoc-validity-v1".to_owned(),
        trace_id: trace.header.trace_id.clone(),
        task_id: task.id.clone(),
        initial_valid,
        initial_canonical_solution_class: initial_class,
        events: labels,
    })
}

/// Compute reachability and common-Q terminal selection from a completed trace
/// prefix. Time budgets select only events whose completion timestamp is at or
/// before the threshold; they never stop the online scheduler.
pub fn prefix_metrics(
    trace: &RunTrace,
    sidecar: &PosthocSidecar,
    prefix: PrefixBudget,
) -> Result<PrefixMetrics, SearchError> {
    verify_sidecar(trace, sidecar)?;
    let included_count = match prefix {
        PrefixBudget::Expansions(budget) => trace
            .events
            .iter()
            .take_while(|event| event.global_expansion_index <= budget)
            .count(),
        PrefixBudget::ActiveNs(limit) => trace
            .events
            .iter()
            .take_while(|event| event.cumulative_active_ns <= limit)
            .count(),
        PrefixBudget::WallNs(limit) => trace
            .events
            .iter()
            .take_while(|event| event.cumulative_wall_ns <= limit)
            .count(),
    };
    let prefix_events = &trace.events[..included_count];
    let initial_q_available = match prefix {
        PrefixBudget::Expansions(_) => true,
        PrefixBudget::ActiveNs(limit) => trace.header.initial_completion_active_ns <= limit,
        PrefixBudget::WallNs(limit) => trace.header.initial_completion_wall_ns <= limit,
    };
    let mut best_q = f32::NEG_INFINITY;
    let mut selected_event = None;
    let mut selected_initial_particle = None;
    if initial_q_available {
        for initial in &trace.header.initial_particles {
            if initial.q_terminal > best_q {
                best_q = initial.q_terminal;
                selected_initial_particle = Some(initial.particle_id);
                selected_event = None;
            }
        }
    }
    for event in prefix_events {
        if event.q_terminal > best_q {
            best_q = event.q_terminal;
            selected_event = Some(event.event_index);
            selected_initial_particle = None;
        }
    }

    let mut reachable_excluding_initial = false;
    let mut valid_classes = HashSet::<Vec<u8>>::new();
    if initial_q_available && sidecar.initial_valid {
        if let Some(class) = &sidecar.initial_canonical_solution_class {
            valid_classes.insert(class.clone());
        }
    }
    for event in prefix_events {
        let label = &sidecar.events[event.event_index as usize];
        if label.valid {
            reachable_excluding_initial = true;
            if let Some(class) = &label.canonical_solution_class {
                valid_classes.insert(class.clone());
            }
        }
    }
    let selected_state_valid = if let Some(event_index) = selected_event {
        sidecar.events[event_index as usize].valid
    } else if selected_initial_particle.is_some() {
        sidecar.initial_valid
    } else {
        false
    };

    Ok(PrefixMetrics {
        prefix: PrefixBudgetRecord::from(prefix),
        completed_expansions: included_count as u64,
        reachability_including_initial: (initial_q_available && sidecar.initial_valid)
            || reachable_excluding_initial,
        reachability_excluding_initial: reachable_excluding_initial,
        selected_state_valid,
        selected_event,
        selected_initial_particle,
        distinct_valid_classes_reached: valid_classes.len() as u64,
    })
}

fn verify_sidecar(trace: &RunTrace, sidecar: &PosthocSidecar) -> Result<(), SearchError> {
    if sidecar.trace_id != trace.header.trace_id || sidecar.task_id != trace.header.task_id {
        return Err(SearchError::ReplayInput(
            "post-hoc sidecar identity does not match trace".to_owned(),
        ));
    }
    if sidecar.events.len() != trace.events.len()
        || sidecar
            .events
            .iter()
            .enumerate()
            .any(|(index, label)| label.event_index != index as u64)
    {
        return Err(SearchError::ReplayInput(
            "post-hoc sidecar event sequence does not match trace".to_owned(),
        ));
    }
    Ok(())
}
