use super::{family_split, random_sample_id, random_seed, trace_seed, StableRng};
use serde_json::json;
use std::collections::BTreeSet;

fn manifest() -> serde_json::Value {
    json!({
        "family_split": {
            "salt": "FAS-R1-QTERMINAL-SPLIT-V1",
            "ranges": {"train": [0,7999], "validation": [8000,8999], "test": [9000,9999]}
        }
    })
}

#[test]
fn split_is_deterministic_and_covers_all_families() {
    let manifest = manifest();
    let first: Vec<_> = (0..1000)
        .map(|index| family_split(&format!("family-{index}"), &manifest).unwrap())
        .collect();
    let second: Vec<_> = (0..1000)
        .map(|index| family_split(&format!("family-{index}"), &manifest).unwrap())
        .collect();
    assert_eq!(first, second);
    assert!(first.contains(&"train"));
    assert!(first.contains(&"validation"));
    assert!(first.contains(&"test"));
}

#[test]
fn trace_and_random_seed_namespaces_are_separate() {
    assert_ne!(trace_seed("family-a", 0), random_seed("family-a", 0));
    assert_eq!(trace_seed("family-a", 0), trace_seed("family-a", 0));
    assert_ne!(trace_seed("family-a", 0), trace_seed("family-a", 1));
}

#[test]
fn random_candidate_ids_separate_label_conditioned_replicates() {
    assert_ne!(
        random_sample_id("task-a", true, 0),
        random_sample_id("task-a", false, 0)
    );
    assert_eq!(
        random_sample_id("task-a", true, 7),
        random_sample_id("task-a", true, 7)
    );
}

#[test]
fn bounded_rng_stays_inside_range_and_replays() {
    let mut first = StableRng::new(12345);
    let mut second = StableRng::new(12345);
    let a: Vec<_> = (0..10_000).map(|_| first.bounded(6)).collect();
    let b: Vec<_> = (0..10_000).map(|_| second.bounded(6)).collect();
    assert_eq!(a, b);
    assert!(a.iter().all(|value| *value < 6));
    assert_eq!(a.iter().copied().collect::<BTreeSet<_>>().len(), 6);
}
