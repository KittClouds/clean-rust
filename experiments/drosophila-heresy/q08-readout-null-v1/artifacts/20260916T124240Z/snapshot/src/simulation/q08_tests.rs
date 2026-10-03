use super::*;
use crate::{capture::Capture, policy::Policy};
use serde_json::Value;
use sha2::{Digest, Sha256};

fn hash_f32(hash: &mut Sha256, values: &[f32]) {
    for value in values {
        hash.update(value.to_bits().to_le_bytes());
    }
}

fn learner_fingerprint(sim: &Simulator<'_>) -> [u8; 32] {
    let mut hash = Sha256::new();
    for values in [
        &sim.weights,
        &sim.eligibility,
        &sim.baseline,
        &sim.post,
        &sim.probabilities,
        &sim.signed_post,
        &sim.dan,
        &sim.feedback,
        &sim.gain,
        &sim.bias,
        &sim.denom,
        &sim.action_sign,
    ] {
        hash_f32(&mut hash, values);
    }
    for value in [sim.lambda, sim.scale, sim.eta, sim.max_gain_mass_error] {
        hash.update(value.to_bits().to_le_bytes());
    }
    hash.update(sim.rng.0.to_le_bytes());
    hash.update(sim.work.to_le_bytes());
    hash.update(sim.events.to_le_bytes());
    hash.update([u8::from(sim.uniform), u8::from(sim.disabled)]);
    hash.finalize().into()
}

fn scientific_value(run: &dh07::Dh07Run) -> Value {
    let mut value = serde_json::to_value(&run.result).unwrap();
    value["outcome"]["seconds"] = Value::Null;
    value["diagnostics"] = Value::Null;
    value["observer_array_bytes"] = Value::Null;
    value
}

fn run_fixture<'a>(
    graph: &'a Graph,
    task: &Task,
    observe: bool,
    instrument: bool,
) -> (Simulator<'a>, dh07::Dh07Run, Option<Policy>) {
    let mut sim = Simulator::new(graph, &graph.route, 9200, 4.0, 0.05, "E");
    if instrument {
        sim.capture = Some(Capture::new(sim.weights.len()));
        sim.policy = Some(Policy::new(sim.weights.len(), 9200, 4.0, b'R'));
    }
    if let Some(p) = &mut sim.policy {
        p.rotor
            .set_posts(graph.kc_mb.edges.iter().map(|e| e.post as usize));
    }
    let run = sim
        .run_dh07(
            task,
            Dh07Condition::TruePerpendicular,
            &graph.route,
            observe,
            0,
        )
        .unwrap();
    let policy = sim.policy.take();
    (sim, run, policy)
}

#[test]
fn pure_margin_evaluator_mutates_no_learner_field() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 111, 16, 12, 512);
    let sim = Simulator::new(&graph, &graph.route, 222, 4.0, 0.05, "E");
    let before = learner_fingerprint(&sim);
    let margin = sim.old_map_margin_for_weights_dh08a(&task, &sim.weights);
    assert!(margin.is_finite());
    assert_eq!(learner_fingerprint(&sim), before);
}

#[test]
fn shadow_endpoint_evaluation_order_is_irrelevant() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 333, 16, 12, 512);
    let sim = Simulator::new(&graph, &graph.route, 444, 4.0, 0.05, "E");
    let base = sim.weights.clone();
    let mut true_endpoint = base.clone();
    let mut null_endpoint = base.clone();
    for (index, value) in true_endpoint.iter_mut().enumerate().step_by(17) {
        *value = (*value + 0.01 + index as f32 * 1e-8).clamp(0.0, 2.0);
    }
    for (index, value) in null_endpoint.iter_mut().enumerate().skip(3).step_by(19) {
        *value = (*value - 0.007 - index as f32 * 1e-8).clamp(0.0, 2.0);
    }
    let first = [
        sim.old_map_margin_for_weights_dh08a(&task, &base),
        sim.old_map_margin_for_weights_dh08a(&task, &true_endpoint),
        sim.old_map_margin_for_weights_dh08a(&task, &null_endpoint),
    ];
    let second = [
        sim.old_map_margin_for_weights_dh08a(&task, &null_endpoint),
        sim.old_map_margin_for_weights_dh08a(&task, &base),
        sim.old_map_margin_for_weights_dh08a(&task, &true_endpoint),
    ];
    assert_eq!(first, [second[1], second[2], second[0]]);
}

#[test]
fn shadow_is_canonically_invisible_and_preserves_parent_endpoints() {
    let graph = Graph::load(
        std::path::Path::new("../dh06/artifacts/runs/20260915T201008Z/sealed/anatomy"),
        "R",
        -1.0,
    )
    .unwrap();
    let task = Task::new(&graph, 9200 ^ 858_980_352, 16, 12, 512);

    let mut parent = Simulator::new(&graph, &graph.route, 9200, 4.0, 0.05, "E");
    parent.capture = Some(Capture::new(parent.weights.len()));
    let parent_run = parent
        .run_dh07(
            &task,
            Dh07Condition::TruePerpendicular,
            &graph.route,
            true,
            0,
        )
        .unwrap();
    let parent_endpoints = parent
        .capture
        .as_ref()
        .unwrap()
        .true_endpoint_sha256
        .clone();

    let (instrumented, instrumented_run, policy) = run_fixture(&graph, &task, true, true);
    let policy = policy.unwrap();
    assert_eq!(
        policy.failed,
        policy.events.iter().any(|e| !e.geometry_valid)
    );
    assert_eq!(policy.events.len(), 256);
    assert_eq!(parent_endpoints.len(), 256);
    assert_eq!(
        policy
            .events
            .iter()
            .map(|event| event.true_endpoint_sha256)
            .collect::<Vec<_>>(),
        parent_endpoints
    );
    assert_eq!(instrumented.weights, parent.weights);
    assert_eq!(instrumented.rng.0, parent.rng.0);
    assert_eq!(
        scientific_value(&instrumented_run),
        scientific_value(&parent_run)
    );
    assert_eq!(instrumented_run.result.outcome.hot_allocations, 0);
    assert!(
        policy.events.iter().all(|event| {
            event.shadow_hot_allocations == 0 && event.geometry.hot_allocations == 0
        })
    );

    let (observer_off, observer_off_run, observer_off_policy) =
        run_fixture(&graph, &task, false, true);
    assert_eq!(observer_off.weights, instrumented.weights);
    assert_eq!(observer_off.rng.0, instrumented.rng.0);
    assert_eq!(
        scientific_value(&observer_off_run),
        scientific_value(&instrumented_run)
    );
    assert_eq!(
        serde_json::to_value(observer_off_policy.unwrap().events).unwrap(),
        serde_json::to_value(policy.events).unwrap()
    );
}

#[test]
fn fixed_weight_arm_remains_unchanged() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 555, 16, 12, 512);
    let mut sim = Simulator::new(&graph, &graph.route, 666, 4.0, 0.05, "Z");
    let initial = sim.weights.clone();
    let run = sim
        .run_dh07(
            &task,
            Dh07Condition::TruePerpendicular,
            &graph.route,
            true,
            0,
        )
        .unwrap();
    assert_eq!(sim.weights, initial);
    assert_eq!(run.result.outcome.changed_weights, 0);
}
