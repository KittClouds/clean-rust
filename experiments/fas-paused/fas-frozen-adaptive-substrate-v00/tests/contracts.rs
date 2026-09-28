use fas00::{
    interface::{Arm, FeatureProvider, FeedbackRecord, Prediction, ResourceBytes, run_arm},
    validate::{validate, validate_triplet},
    world::{DEFAULT_EVENTS, Family, Feedback, Split, Track, WorldConfig, generate},
};

fn config(family: Family, track: Track, feedback: Feedback) -> WorldConfig {
    WorldConfig {
        world_seed: 77,
        split: Split::Qualification,
        family,
        track,
        feedback,
        events: DEFAULT_EVENTS,
        label_rotation: 0,
    }
}

#[test]
fn all_worlds_reconstruct_from_serialized_state() {
    for family in Family::ALL {
        for track in [Track::GlobalRule, Track::ContextBound] {
            for feedback in [Feedback::Immediate, Feedback::Delayed8] {
                let c = config(family, track, feedback);
                let events = generate(&c).unwrap();
                let serialized = serde_json::to_vec(&events).unwrap();
                let decoded: Vec<fas00::world::WorldEvent> =
                    serde_json::from_slice(&serialized).unwrap();
                assert_eq!(events, decoded);
                validate(&c, &events).unwrap();
                assert_eq!(events, generate(&c).unwrap());
                validate_triplet(&c).unwrap();
            }
        }
    }
}

#[test]
fn transitions_and_noise_are_exact() {
    let cases = [
        (Family::Stable, 0, 0),
        (Family::SingleSwitch, 16, 1),
        (Family::Return, 8, 1),
        (Family::Return, 16, 0),
        (Family::Cyclic, 8, 1),
        (Family::Cyclic, 16, 2),
        (Family::Cyclic, 24, 0),
        (Family::TemporaryRule, 12, 1),
        (Family::TemporaryRule, 16, 0),
        (Family::GradualDrift, 16, 1),
    ];
    for (family, step, phase) in cases {
        let mut c = config(family, Track::GlobalRule, Feedback::Immediate);
        c.split = Split::Initialization;
        let events = generate(&c).unwrap();
        assert_eq!(events[step].regime_phase, phase);
    }
    for family in [Family::ContradictoryNoise, Family::PoisonBurst] {
        let events = generate(&config(family, Track::GlobalRule, Feedback::Immediate)).unwrap();
        assert!(events.iter().any(|e| {
            e.exposure
                .observed_answer_index
                .is_some_and(|o| o != e.target_index)
        }));
        assert!(events.iter().all(|e| e.regime_phase == 0));
    }
    let context_world = generate(&config(
        Family::SingleSwitch,
        Track::ContextBound,
        Feedback::Immediate,
    ))
    .unwrap();
    for key in 0..8 {
        let before = context_world[15].world_state[key].answer_index;
        let after = context_world[17].world_state[key].answer_index;
        if (key % 4) / 2 == 1 {
            assert_eq!(before, after, "unaffected context changed at key {key}");
        } else {
            assert_ne!(before, after, "target context did not change at key {key}");
        }
    }
}

#[test]
fn validator_rejects_target_and_timing_corruption() {
    let c = config(Family::Return, Track::ContextBound, Feedback::Delayed8);
    let mut events = generate(&c).unwrap();
    events[9].target_index = (events[9].target_index + 1) % 3;
    assert!(
        validate(&c, &events)
            .unwrap_err()
            .contains("target mismatch")
    );
    let mut events = generate(&c).unwrap();
    events[9].feedback_due_step = 9;
    assert!(
        validate(&c, &events)
            .unwrap_err()
            .contains("feedback timing")
    );
}

#[derive(Default)]
struct ExactFeature;
impl FeatureProvider for ExactFeature {
    fn feature(&mut self, exposure: &fas00::world::Exposure) -> Result<Vec<f32>, String> {
        Ok(vec![exposure.key_id as f32])
    }
}

#[derive(Default)]
struct SpyArm {
    seen: Vec<(String, u32, &'static str)>,
}
impl Arm for SpyArm {
    fn name(&self) -> &'static str {
        "SPY"
    }
    fn reset(&mut self) {
        self.seen.clear();
    }
    fn observe(&mut self, x: &fas00::world::Exposure, _: &[f32]) {
        self.seen.push((x.event_id.clone(), x.step, "observe"));
    }
    fn predict(&mut self, x: &fas00::world::Exposure, _: &[f32]) -> Prediction {
        self.seen.push((x.event_id.clone(), x.step, "predict"));
        Prediction {
            probabilities: [1.0 / 3.0; 3],
        }
    }
    fn feedback(&mut self, r: &FeedbackRecord) {
        self.seen.push((r.event_id.clone(), r.due_step, "feedback"));
    }
    fn resource_bytes(&self) -> ResourceBytes {
        ResourceBytes::default()
    }
}

#[test]
fn runner_scores_before_feedback_and_delays_exactly() {
    for feedback in [Feedback::Immediate, Feedback::Delayed8] {
        let events = generate(&config(Family::Return, Track::ContextBound, feedback)).unwrap();
        let mut arm = SpyArm::default();
        let records = run_arm(&mut arm, &mut ExactFeature, &events).unwrap();
        assert_eq!(
            records.iter().map(|r| &r.event_id).collect::<Vec<_>>(),
            events
                .iter()
                .map(|e| &e.exposure.event_id)
                .collect::<Vec<_>>()
        );
        for (t, record) in records.iter().enumerate() {
            let expected = match feedback {
                Feedback::Immediate => Some(t),
                Feedback::Delayed8 => t.checked_sub(8),
            };
            assert_eq!(
                record.feedback_revealed_after_score.first(),
                expected.map(|source| &events[source].exposure.event_id)
            );
            assert_eq!(
                record.feedback_revealed_after_score.len(),
                usize::from(expected.is_some())
            );
        }
        for t in 0..8 {
            let actions = arm
                .seen
                .iter()
                .filter(|(_, step, _)| *step == t)
                .map(|(_, _, a)| *a)
                .collect::<Vec<_>>();
            assert_eq!(&actions[..2], &["observe", "predict"]);
            assert_eq!(
                actions.contains(&"feedback"),
                feedback == Feedback::Immediate
            );
        }
    }
}

#[test]
fn resource_accounting_keeps_cache_separate() {
    let r = ResourceBytes {
        transient: 3,
        persistent: 4,
        adaptive_parameters: 5,
        optimizer_state: 6,
        episodic_memory: 7,
        snapshots: 8,
        feature_cache_infrastructure: 100,
    };
    assert_eq!(
        (r.b_c(), r.b_m(), r.b_phi(), r.b_adaptive()),
        (3, 15, 11, 26)
    );
    assert_eq!(
        Prediction {
            probabilities: [1.0 / 3.0; 3]
        }
        .choice(),
        0
    );
}

#[test]
#[ignore = "manual generator throughput check"]
fn generator_throughput_smoke() {
    let c = config(Family::Cyclic, Track::ContextBound, Feedback::Delayed8);
    let start = std::time::Instant::now();
    for seed in 0..5_000 {
        let mut c = c.clone();
        c.world_seed = seed;
        validate(&c, &generate(&c).unwrap()).unwrap();
    }
    eprintln!("5000 world generate+validate: {:?}", start.elapsed());
}
