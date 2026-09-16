use super::*;
use crate::{capture::Capture, policy::Policy};
use sha2::{Digest, Sha256};
fn state(sim: &Simulator<'_>) -> Vec<u8> {
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
        for x in values {
            hash.update(x.to_bits().to_le_bytes());
        }
    }
    hash.update(sim.rng.0.to_le_bytes());
    hash.update(sim.work.to_le_bytes());
    hash.update(sim.events.to_le_bytes());
    hash.finalize().to_vec()
}
#[test]
fn capture_is_allocation_free_and_observer_invisible_on_synthetic_fixture() {
    // Fixture IDs are not anatomical/engineering seed executions.
    let graph = Graph::fixture();
    let task = Task::new(&graph, 123, 16, 12, 512);
    let mut expected = None;
    let mut receipts = None;
    for (capture, observe) in [(false, false), (true, false), (true, true)] {
        let mut sim = Simulator::new(&graph, &graph.route, 3, 4., 0.05, "E");
        if capture {
            sim.capture = Some(Capture::new(sim.weights.len()));
            sim.policy = Some(Policy::new(sim.weights.len()));
        }
        let run = sim
            .run_dh07(
                &task,
                Dh07Condition::TruePerpendicular,
                &graph.route,
                observe,
                0,
            )
            .unwrap();
        assert_eq!(run.result.outcome.hot_allocations, 0);
        let fingerprint = state(&sim);
        if let Some(ref previous) = expected {
            assert_eq!(previous, &fingerprint);
        } else {
            expected = Some(fingerprint);
        }
        if let Some(policy) = sim.policy {
            assert_eq!(policy.count, 256);
            let bytes = serde_json::to_vec(&policy.snapshots).unwrap();
            if let Some(ref previous) = receipts {
                assert_eq!(previous, &bytes);
            } else {
                receipts = Some(bytes);
            }
        }
    }
}
