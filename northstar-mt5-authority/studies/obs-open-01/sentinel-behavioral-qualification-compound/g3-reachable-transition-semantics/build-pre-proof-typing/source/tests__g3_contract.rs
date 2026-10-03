use obs_open_04a_g3::audit::execute;
use obs_open_04a_g3::fixtures::replay_witness;
use obs_open_04a_g3::model::{LanguageStatus, TransitionResult};

#[test]
fn every_constructive_witness_replays_exactly() {
    let products = execute().unwrap();
    for witness in &products.witnesses {
        let replay = replay_witness(witness).unwrap();
        match (&replay, &witness.target_result) {
            (
                TransitionResult::Applied {
                    next_state: a,
                    emissions: ae,
                },
                TransitionResult::Applied {
                    next_state: b,
                    emissions: be,
                },
            ) => {
                assert_eq!(a, b);
                assert_eq!(ae, be);
            }
            (
                TransitionResult::Rejected { reason: a },
                TransitionResult::Rejected { reason: b },
            ) => assert_eq!(a, b),
            _ => panic!("result class drift"),
        }
    }
}

#[test]
fn all_37_g2_collisions_receive_a_typed_disposition() {
    let products = execute().unwrap();
    assert_eq!(products.collisions.len(), 37);
    assert!(
        products
            .collisions
            .iter()
            .all(|x| !x.g3_disposition.is_empty())
    );
    assert!(
        products
            .collisions
            .iter()
            .all(|x| x.g3_disposition != "NO_ADDITIONAL_REACHABILITY_CONSTRAINT")
    );
}

#[test]
fn approximation_is_honest_and_nonexact() {
    let products = execute().unwrap();
    assert_eq!(products.bounds.len(), 4);
    assert!(
        products
            .bounds
            .iter()
            .all(|x| x.status == LanguageStatus::Mixed)
    );
    assert!(products.bounds.iter().all(|x| !x.exactness_claimed));
}

#[test]
fn applied_and_rejected_results_are_both_witnessed() {
    let products = execute().unwrap();
    assert!(
        products
            .witnesses
            .iter()
            .any(|x| matches!(x.target_result, TransitionResult::Applied { .. }))
    );
    assert!(
        products
            .witnesses
            .iter()
            .any(|x| matches!(x.target_result, TransitionResult::Rejected { .. }))
    );
}

#[test]
fn no_bounded_search_is_laundered_into_impossibility() {
    let products = execute().unwrap();
    let text = serde_json::to_string(&products).unwrap();
    assert!(!text.contains("NO_WITNESS_FOUND"));
    assert!(!text.contains("PROVEN_NO_ADDITIONAL_REACHABILITY_CONSTRAINT"));
}
