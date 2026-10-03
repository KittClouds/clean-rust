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

#[test]
fn constructive_states_obey_the_proven_reachable_manifold() {
    let products = execute().unwrap();
    for witness in &products.witnesses {
        let TransitionResult::Applied { next_state, .. } = &witness.target_result else {
            continue;
        };
        let bar = next_state.bar_index.unwrap();
        let knowledge = next_state.knowledge_time_ns.unwrap();
        let upper = next_state.upper.as_ref().unwrap();
        let lower = next_state.lower.as_ref().unwrap();
        let close = next_state.close_ticks.unwrap();
        assert!(upper.value_ticks >= close && close >= lower.value_ticks);
        assert_eq!(
            next_state.upper_giveback_ticks,
            Some(upper.value_ticks - close)
        );
        assert_eq!(
            next_state.lower_giveback_ticks,
            Some(close - lower.value_ticks)
        );
        assert_eq!(upper.age_bars, bar - upper.birth_bar_index);
        assert_eq!(lower.age_bars, bar - lower.birth_bar_index);
        assert_eq!(
            knowledge - upper.birth_knowledge_time_ns,
            i64::from(upper.age_bars) * witness.context.observation_cadence_ns
        );
        assert_eq!(
            knowledge - lower.birth_knowledge_time_ns,
            i64::from(lower.age_bars) * witness.context.observation_cadence_ns
        );
        for (index, range) in witness.context.ranges.iter().enumerate() {
            let available = knowledge >= range.freeze_commit_time_ns;
            assert_eq!(next_state.range_locations[index].is_some(), available);
            assert_eq!(
                next_state.upper_extensions_ticks[index],
                available.then_some((upper.value_ticks - range.high_ticks).max(0))
            );
            assert_eq!(
                next_state.lower_extensions_ticks[index],
                available.then_some((range.low_ticks - lower.value_ticks).max(0))
            );
        }
    }
}
