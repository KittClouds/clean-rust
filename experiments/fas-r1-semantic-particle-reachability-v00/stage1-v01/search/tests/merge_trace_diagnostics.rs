use r1_stage1_search::{
    run, write_stage1_trace_v2, Arm, Edit, PolicyError, PolicyLatentUpdate, PolicyScores,
    PolicyValue, RunConfig, SearchPolicy, SelectorInput, SemanticFeatures, Stage1RunConfig,
    TransitionInput, ValueInput,
};
use r1_world::{InferenceTask, Task};
use serde_json::Value;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

struct MergePolicy {
    value_sign: f32,
}

impl SearchPolicy for MergePolicy {
    fn score_edits(
        &mut self,
        _input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        Ok(PolicyScores {
            logits: candidates
                .iter()
                .map(|edit| if edit.entity == 0 { 100.0 } else { -100.0 })
                .collect(),
            costs: Default::default(),
        })
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        _selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        let mut next = input.latent_state.to_vec();
        next[0] += input.remaining_budget as f32;
        Ok(PolicyLatentUpdate {
            next_state: next,
            costs: Default::default(),
        })
    }

    fn q_terminal(&mut self, _input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue {
            value: 0.5,
            ..Default::default()
        })
    }

    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue {
            value: self.value_sign * input.latent_state[0],
            ..Default::default()
        })
    }
}

fn fixture() -> (InferenceTask, SemanticFeatures) {
    let task = Task {
        id: "merge-diagnostics-task".to_owned(),
        family_id: "merge-diagnostics-family".to_owned(),
        seed: 41,
        n: 2,
        k: 2,
        clauses: Vec::new(),
        role_anonymous: true,
    };
    let inference = r1_world::render_task(&task, 19).inference;
    let features = SemanticFeatures::from_projection(
        &inference,
        2,
        Vec::new().into_boxed_slice(),
        vec![0.25, -0.5].into_boxed_slice(),
    )
    .unwrap();
    (inference, features)
}

fn particle_run(value_sign: f32) -> r1_stage1_search::Stage1Run {
    let (task, features) = fixture();
    let mut base = RunConfig::new(Arm::Particle, 3, 2, 0xBEEF);
    base.latent_dim = 1;
    base.resample_period = 3;
    base.minimum_particle_budget = 1;
    let config = Stage1RunConfig::from_stage0(base);
    let mut policy = MergePolicy { value_sign };
    run(&task, &features, config, &mut policy).unwrap()
}

#[test]
fn trace_captures_both_premerge_states_and_accounts_for_each_winner_branch() {
    for (value_sign, expected_retired, expected_redirected, mismatch) in
        [(1.0, Some(1), false, false), (-1.0, Some(0), true, true)]
    {
        let result = particle_run(value_sign);
        let merged = &result.event_diagnostics[1];
        let loser = merged.merge_loser.as_ref().unwrap();
        let kept = merged.merge_kept.as_ref().unwrap();
        assert_eq!(loser.assignment, kept.assignment);
        assert_ne!(loser.latent_state, kept.latent_state);
        assert_eq!(loser.depth, 1);
        assert_eq!(kept.depth, 1);
        assert_ne!(loser.particle_id, kept.particle_id);
        assert_eq!(merged.merge_retired_particle_id, expected_retired);

        assert_eq!(
            result.trace.events[2].nominal_slot_redirected,
            expected_redirected
        );
        assert_eq!(
            result.trace.ledger.redirected_future_expansions,
            u64::from(expected_redirected)
        );
        let final_allocation = &result.event_diagnostics[2];
        assert!(final_allocation.value_based_allocation);
        assert_eq!(final_allocation.scheduler_slot_mismatch, mismatch);
    }
}

#[test]
fn v2_writer_replaces_the_ambiguous_flag_and_emits_merge_snapshots() {
    let result = particle_run(-1.0);
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("r1-stage1-trace-v2-{unique}.jsonl"));
    write_stage1_trace_v2(&path, &result).unwrap();

    let records = fs::read_to_string(&path)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    fs::remove_file(&path).unwrap();

    assert_eq!(records.len(), result.trace.events.len() + 2);
    let header = &records[0]["payload"];
    assert_eq!(header["schema"], "r1-stage1-hookable-trace-v2");
    assert_eq!(
        header["diagnostics_schema"],
        "r1-stage1-merge-diagnostics-v1"
    );
    let merged = &records[2]["payload"];
    assert!(merged.get("value_allocation_non_nominal").is_none());
    assert!(merged.get("scheduler_slot_mismatch").is_some());
    assert!(merged.get("value_based_allocation").is_some());
    assert_eq!(merged["merge_retired_particle_id"], 0);
    assert_eq!(merged["merge_loser"]["particle_id"], 0);
    assert_eq!(merged["merge_kept"]["particle_id"], 1);
    assert_ne!(
        merged["merge_loser"]["latent_state"],
        merged["merge_kept"]["latent_state"]
    );
    assert_eq!(records.last().unwrap()["record"], "footer");
}

#[test]
fn v2_writer_rejects_misaligned_diagnostics() {
    let mut result = particle_run(1.0);
    result.event_diagnostics.pop();
    let path = std::env::temp_dir().join("r1-stage1-trace-v2-misaligned.jsonl");
    let error = write_stage1_trace_v2(&path, &result).unwrap_err();
    assert_eq!(error.kind(), std::io::ErrorKind::InvalidData);
    assert!(!path.exists());
}
