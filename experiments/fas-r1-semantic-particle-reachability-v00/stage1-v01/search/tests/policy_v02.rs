pub use r1_stage1_search::{
    Edit, IdentityCompositionV03, PolicyCosts, PolicyError, PolicyLatentUpdate, PolicyScores,
    PolicyValue, SearchPolicy, SelectorInput, SemanticFeatures, TerminalScorer, TransitionInput,
    ValueInput,
};

#[path = "../src/inference_v02.rs"]
mod inference_v02;
pub use inference_v02::{
    FrozenProposalValueV02, InferenceV02Error, ProposalMixV03, ProposalScoresV02,
};

#[path = "../src/policy_v02.rs"]
mod policy_v02;

use policy_v02::FrozenProposalPolicyV02;
use r1_world::InferenceTask;

struct FixedTerminal;

impl TerminalScorer for FixedTerminal {
    fn q_terminal(&mut self, _input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue {
            value: 0.375,
            selection_score: Some(-1.5),
            costs: PolicyCosts {
                logits_scored: 1,
                ..PolicyCosts::default()
            },
        })
    }
}

fn fixture() -> (InferenceTask, SemanticFeatures) {
    let task = InferenceTask {
        id: "policy-parity-task-v02".to_owned(),
        family_id: "policy-parity-family".to_owned(),
        n: 3,
        k: 2,
        role_anonymous: false,
        global_text: String::new(),
        clauses: vec!["c0".into(), "c1".into(), "c2".into()],
        entity_mentions: vec![vec![0, 1], vec![1], vec![2]],
        role_mentions: vec![vec![], vec![1], vec![0, 1]],
    };
    let global = (0..2048)
        .map(|index| (((index * 7) % 101) - 50) as f32 / 1024.0)
        .collect::<Vec<_>>()
        .into_boxed_slice();
    let clauses = (0..3)
        .flat_map(|clause| {
            (0..2048).map(move |index| (((clause + 1) * (index % 29)) - 14) as f32 / 2048.0)
        })
        .collect::<Vec<_>>()
        .into_boxed_slice();
    let features = SemanticFeatures::from_projection(&task, 2048, clauses, global).unwrap();
    (task, features)
}

fn candidates() -> [Edit; 3] {
    [
        Edit {
            entity: 0,
            new_role: 1,
        },
        Edit {
            entity: 1,
            new_role: 0,
        },
        Edit {
            entity: 2,
            new_role: 1,
        },
    ]
}

fn transition<'a>(
    task: &'a InferenceTask,
    features: &'a SemanticFeatures,
    assignment: &'a [u8],
    latent: &'a [f32],
) -> TransitionInput<'a> {
    TransitionInput {
        task,
        features,
        assignment,
        latent_state: latent,
        remaining_budget: 13,
        strategy: r1_stage1_search::ProposalStrategy::LearnedSample,
    }
}

#[test]
fn adapter_prepares_once_and_matches_raw_v02_action_signal_and_heads() {
    let (task, features) = fixture();
    let mut identity = IdentityCompositionV03::load_default().unwrap();
    let identity_sha256 = identity.binary_sha256().to_owned();
    let heads = FrozenProposalValueV02::load_default().unwrap();
    let mut reference_heads = FrozenProposalValueV02::load_default().unwrap();
    reference_heads.prepare_task(&task, &features).unwrap();
    let mut policy = FrozenProposalPolicyV02::new(heads, &mut identity, FixedTerminal);
    policy.prepare_bound_task(&task, &features).unwrap();
    assert_eq!(policy.identity().binary_sha256(), identity_sha256);
    let _ = policy.terminal();
    let _ = policy.terminal_mut();
    assert_eq!(policy.heads().cache_len(), 1);

    let assignment = [0, 1, 0];
    let latent = vec![0.0; 128];
    let edits = candidates();
    let expected_delta = edits
        .iter()
        .map(|&edit| {
            policy
                .identity_mut()
                .expected_satisfaction_delta_for_task(&task.id, &features, &assignment, edit)
                .unwrap() as f32
        })
        .collect::<Vec<_>>();
    let expected_logits = reference_heads
        .score_edits(&task, &features, &assignment, &edits, &expected_delta)
        .unwrap();
    let scored = policy
        .score_edits(transition(&task, &features, &assignment, &latent), &edits)
        .unwrap();
    assert_eq!(scored.logits, expected_logits);
    // Three proposal logits plus six raw identity logits for four affected
    // clause/action pairs in this fixture.
    assert_eq!(scored.costs.logits_scored, 27);
    assert_eq!(policy.heads().cache_len(), 1);
}

#[test]
fn adapter_latent_vreach_and_terminal_delegation_match_contracts() {
    let (task, features) = fixture();
    let mut identity = IdentityCompositionV03::load_default().unwrap();
    let heads = FrozenProposalValueV02::load_default().unwrap();
    let mut policy = FrozenProposalPolicyV02::new(heads, &mut identity, FixedTerminal);
    let assignment = [0, 1, 0];
    let latent = (0..128)
        .map(|index| (((index * 13) % 31) - 15) as f32 / 128.0)
        .collect::<Vec<_>>();

    let selected = Edit {
        entity: 1,
        new_role: 0,
    };
    let update = policy
        .advance_latent(transition(&task, &features, &assignment, &latent), selected)
        .unwrap();
    let mut expected = latent.clone();
    expected[1] = -0.076_024_9;
    expected[2] = 0.270_444_9;
    for (actual, expected) in update.next_state.iter().zip(expected) {
        assert!((actual - expected).abs() <= 1e-7);
    }
    assert_eq!(update.costs, PolicyCosts::default());

    let value = policy
        .v_reach(ValueInput {
            features: &features,
            task: &task,
            assignment: &assignment,
            latent_state: &latent,
            remaining_budget: 13,
            depth: 0,
        })
        .unwrap();
    assert!((value.value - 0.479_539_1).abs() <= 4e-5);

    let terminal = policy
        .q_terminal(SelectorInput {
            task_id: &task.id,
            features: &features,
            assignment: &assignment,
        })
        .unwrap();
    assert_eq!(terminal.value, 0.375);
    assert_eq!(terminal.selection_score, Some(-1.5));
    assert_eq!(terminal.costs.logits_scored, 1);
}

#[test]
fn v03_policy_uses_incidence_masked_action_signal_and_reports_score_spread() {
    let (task, features) = fixture();
    let mut identity = IdentityCompositionV03::load_default().unwrap();
    let heads = FrozenProposalValueV02::load_default().unwrap();
    let mut reference_heads = FrozenProposalValueV02::load_default().unwrap();
    let mut policy = FrozenProposalPolicyV02::new(heads, &mut identity, FixedTerminal);
    policy.set_proposal_mix(ProposalMixV03::IncidenceMaskedV03);
    policy.reset_score_audit();
    let assignment = [0, 1, 0];
    let latent = vec![0.0; 128];
    let edits = candidates();
    let masked_delta = edits
        .iter()
        .map(|&edit| {
            policy
                .identity_mut()
                .expected_satisfaction_delta_incidence_masked_for_task(
                    &task.id,
                    &features,
                    &assignment,
                    edit,
                )
                .unwrap() as f32
        })
        .collect::<Vec<_>>();
    reference_heads.prepare_task(&task, &features).unwrap();
    let expected = reference_heads
        .score_edits_detailed_with_mix(
            &task,
            &features,
            &assignment,
            &edits,
            &masked_delta,
            ProposalMixV03::IncidenceMaskedV03,
        )
        .unwrap();

    let scored = policy
        .score_edits(transition(&task, &features, &assignment, &latent), &edits)
        .unwrap();
    assert_eq!(scored.logits, expected.logits);
    assert_eq!(scored.costs.logits_scored, 27);
    assert_eq!(policy.score_audit().score_calls, 1);
    assert_eq!(policy.score_audit().candidate_scores, 3);
    assert!(policy.score_audit().adapter_spread_sum.is_finite());
}
