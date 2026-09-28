use rdc_experiment_007::{
    authority,
    domain::{self, HiddenEpisode, PublicEpisode},
    evaluation::oracle_plans,
    model::FrozenModels,
    routing::{self, BUDGETS, BudgetPlan, Lane},
};
use rdc_runtime_contracts_v1::{ActionCode, InspectionResult};

fn completed(bank: &domain::WorldBank, plan: &BudgetPlan) -> u32 {
    bank.public
        .iter()
        .map(|public| {
            let hidden = bank
                .hidden
                .iter()
                .find(|row| row.episode_id == public.id)
                .unwrap();
            let inspection = if plan.selected_ids.binary_search(&public.id).is_ok() {
                Some(InspectionResult::classify(public.active, hidden.reply))
            } else {
                None
            };
            authority::execute(*public, inspection, hidden.correct_action).task_completed as u32
        })
        .sum()
}

#[test]
fn development_and_evaluation_domains_are_disjoint_and_repeatable() {
    let development = domain::development_banks();
    let first = domain::heldout_banks();
    let second = domain::heldout_banks();
    assert_eq!(development.len(), domain::DEVELOPMENT_WORLDS);
    assert_eq!(first.len(), domain::HELDOUT_WORLDS);
    assert_eq!(first[0].public[0].id, second[0].public[0].id);
    assert_eq!(first[15].hidden[383].reply, second[15].hidden[383].reply);
    let trained_ids = development
        .iter()
        .flat_map(|bank| bank.public.iter().map(|row| row.domain_id))
        .collect::<std::collections::HashSet<_>>();
    for bank in first {
        assert_eq!(bank.public.len(), 384);
        assert_eq!(bank.hidden.len(), 384);
        assert!(
            bank.public
                .iter()
                .filter(|row| row.domain_id >= 1000)
                .all(|row| !trained_ids.contains(&row.domain_id))
        );
    }
}

#[test]
fn feature_router_is_invariant_to_domain_identity_and_plans_ignore_hidden_fixtures() {
    let development = domain::development_banks();
    let models = FrozenModels::fit(&development).unwrap();
    let mut heldout = domain::heldout_banks().remove(0);
    let public = heldout.public[0];
    let mut renamed = public;
    renamed.domain_id = u32::MAX;
    assert_eq!(public.features(), renamed.features());
    assert_eq!(
        models.score_feature_router(&public.features(), public.query_cost_units),
        models.score_feature_router(&renamed.features(), renamed.query_cost_units)
    );
    assert_eq!(models.score_domain_table(renamed), 0.0);

    let plan_before =
        routing::make_plans(heldout.recipe.world_id, &heldout.public, &models).unwrap();
    for hidden in &mut heldout.hidden {
        hidden.correct_action = ActionCode(1 - hidden.correct_action.0);
        if hidden.reply.candidate <= 1 {
            hidden.reply.candidate = 1 - hidden.reply.candidate;
        }
    }
    let plan_after =
        routing::make_plans(heldout.recipe.world_id, &heldout.public, &models).unwrap();
    for lane in Lane::ROUTERS {
        for budget in BUDGETS {
            let before = plan_before
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == budget)
                .unwrap();
            let after = plan_after
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == budget)
                .unwrap();
            assert_eq!(before.selected_ids, after.selected_ids);
        }
    }
}

#[test]
fn exact_budget_router_cannot_outscore_the_evaluation_only_oracle() {
    let development = domain::development_banks();
    let models = FrozenModels::fit(&development).unwrap();
    let bank = domain::heldout_banks().remove(8);
    let routes = routing::make_plans(bank.recipe.world_id, &bank.public, &models).unwrap();
    let oracle = oracle_plans(&bank).unwrap();
    let floor_plan = routes
        .iter()
        .find(|plan| plan.lane == Lane::NoInspection)
        .unwrap();
    let floor = completed(&bank, floor_plan);
    for budget in BUDGETS {
        let ceiling = completed(
            &bank,
            oracle.iter().find(|plan| plan.budget == budget).unwrap(),
        );
        for lane in Lane::ROUTERS {
            let plan = routes
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == budget)
                .unwrap();
            assert_eq!(plan.selected_ids.len(), budget);
            assert!(
                plan.selected_ids
                    .iter()
                    .all(|id| bank.public.iter().any(|row| row.id == *id))
            );
            assert!(completed(&bank, plan) <= ceiling);
        }
        assert!(ceiling >= floor);
    }
}

#[test]
fn public_projection_has_fixed_semantics_and_no_domain_or_world_features() {
    let bank = domain::heldout_banks().remove(0);
    let PublicEpisode { active, shadow, .. } = bank.public[17];
    let features = bank.public[17].features();
    assert_eq!(features.len(), 8);
    assert_eq!(features[1], (active != shadow) as u8 as f32);
    assert!(features.iter().all(|value| value.is_finite()));
    let correct = bank.hidden[17].correct_action;
    assert!(correct.0 <= 1);
    let _fixture_boundary: &[HiddenEpisode] = &bank.hidden;
}

#[test]
fn source_fixture_digest_binds_each_inspection_reply_to_its_episode() {
    for bank in domain::heldout_banks() {
        for hidden in &bank.hidden {
            assert!(domain::validate_source_reply(
                hidden.episode_id,
                hidden.reply
            ));
            let mut corrupted = hidden.reply;
            corrupted.confidence_milli ^= 1;
            assert!(!domain::validate_source_reply(hidden.episode_id, corrupted));
        }
    }
}
