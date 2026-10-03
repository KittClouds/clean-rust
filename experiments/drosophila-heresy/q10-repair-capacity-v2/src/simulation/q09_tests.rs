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
#[ignore = "explicit quarantined engineering state replay; no fresh or scientific seeds"]
fn quarantined_l_tau16_event62_inverse_regression() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let archived: serde_json::Value = serde_json::from_reader(
        std::fs::File::open(root.join("qualification/stage-a-9201-compact/L-tau16.json")).unwrap(),
    )
    .unwrap();
    let graph = Graph::load(&root.join("../artifacts/anatomy"), "L", -1.).unwrap();
    let task = Task::new(&graph, 9201 ^ 858980352, 16, 12, 512);
    let (shuffled, _) = graph.route.rewired(9201 ^ 0x887733);
    let mut sim = Simulator::new(&graph, &graph.route, 9201, 16., 0.05, "E");
    sim.capture = Some(Capture::new(sim.weights.len()));
    sim.policy = Some(Policy::new(sim.weights.len()));
    sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, true, 0)
        .unwrap();
    let capture = sim.capture.as_ref().unwrap();
    assert_eq!(
        serde_json::to_value(capture.true_endpoint_sha256[61]).unwrap(),
        archived["results"][0]["true_endpoint_sha256"][61]
    );
    let snapshot = &sim.policy.as_ref().unwrap().snapshots[61];
    assert_eq!(snapshot.trial, 62);
    let op = crate::linear::DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())
        .unwrap();
    let (receipt, replay) =
        crate::linear::audit(&op, snapshot, sim.drive_denominators(), true).unwrap();
    let replay = replay.unwrap();
    assert_eq!(
        serde_json::to_value(&receipt.combined_rank).unwrap(),
        archived["results"][0]["events"][61]["combined_rank"],
        "fix must preserve the archived singular values and rank decisions"
    );
    let matrix = nalgebra::DMatrix::from_fn(
        replay.scaled_operator.len(),
        replay.interior_indices.len(),
        |r, c| replay.scaled_operator[r][c],
    );
    crate::linear::Factorization::new(&matrix)
        .unwrap()
        .debug_identities(&matrix);
    eprintln!(
        "event62 inverse disagreement={:e}, normalized={:e}",
        receipt.integrity.pseudoinverse_agreement, receipt.integrity.normalized_errors[7]
    );
    assert!(receipt.integrity.valid);
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
