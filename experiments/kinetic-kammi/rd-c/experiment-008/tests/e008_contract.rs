use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_008::{
    domain::{self, Availability, SourceOffer},
    evaluation,
    model::FrozenModels,
    routing::{self, Lane},
    runtime,
};
use rdc_runtime_contracts_v1::{
    ActionCode, InspectionKind, InspectionReply, InspectionResult, TransportStatus,
};

fn temp_root(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path =
        std::env::temp_dir().join(format!("rdc-e008-{label}-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn development_and_heldout_worlds_are_repeatable_and_disjoint() {
    let dev_a = domain::development_banks();
    let dev_b = domain::development_banks();
    let heldout = domain::heldout_banks();
    assert_eq!(dev_a[0].recipe.seed, dev_b[0].recipe.seed);
    assert_eq!(dev_a[0].public[0].active, dev_b[0].public[0].active);
    assert_ne!(dev_a[0].recipe.seed, heldout[0].recipe.seed);
    assert_eq!(heldout.len(), domain::HELDOUT_WORLDS);
    assert_eq!(
        heldout[0].public.len(),
        domain::DOMAINS_PER_WORLD * domain::EPISODES_PER_DOMAIN
    );
}

#[test]
fn offer_schema_is_versioned_and_contains_no_answer_or_revision() {
    let offer = SourceOffer {
        schema_version: domain::OFFER_SCHEMA_VERSION,
        version: domain::OFFER_SCHEMA_VERSION,
        source_id: 1,
        availability: Availability::Degraded,
        source_local_age_bucket: 2,
        provenance_family: 1,
        independence_from_active_source: true,
        historical_reliability_bucket: 3,
        quoted_query_price: 17,
        offer_expiry: 9,
    };
    let bytes = serde_json::to_vec(&offer).unwrap();
    let decoded: SourceOffer = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(decoded.schema_version, domain::OFFER_SCHEMA_VERSION);
    assert_eq!(decoded, offer);
    let object = serde_json::from_slice::<serde_json::Value>(&bytes).unwrap();
    assert!(object.get("correct_action").is_none());
    assert!(object.get("authoritative_revision").is_none());
}

#[test]
fn negative_frozen_value_never_becomes_a_forced_query() {
    let development = domain::development_banks();
    let models = FrozenModels::fit(&development[..1]).unwrap();
    let heldout = domain::heldout_banks();
    let bank = &heldout[0];
    let plans = routing::make_plans(
        bank.recipe.world_id,
        &bank.public,
        &bank.offers,
        bank.recipe.offer_request_cost_units,
        &models,
    );
    assert!(
        plans
            .iter()
            .filter(|plan| plan.lane == Lane::EightFeature)
            .all(|plan| plan.candidates.is_empty())
    );
    assert!(
        plans
            .iter()
            .flat_map(|plan| &plan.candidates)
            .all(|candidate| candidate.predicted_value > 0.0)
    );
    assert!(
        plans
            .iter()
            .filter(|plan| plan.lane == Lane::FittedOffer)
            .any(|plan| plan.candidates.len() < plan.budget)
    );
}

#[test]
fn matched_random_is_paired_to_each_offer_router_and_keeps_zero_calls_zero() {
    let development = domain::development_banks();
    let models = FrozenModels::fit(&development).unwrap();
    let heldout = domain::heldout_banks();
    let bank = &heldout[0];
    let plans = routing::make_plans(
        bank.recipe.world_id,
        &bank.public,
        &bank.offers,
        bank.recipe.offer_request_cost_units,
        &models,
    );
    let simple = plans
        .iter()
        .find(|plan| {
            plan.lane == Lane::SimpleOffer
                && plan.offer_mode == routing::OfferMode::PushedCache
                && plan.lambda == 0.0
                && plan.budget == 16
        })
        .unwrap();
    let preview = routing::preview_route(&bank.public, &bank.current_offers, simple, &models);
    let selected = &preview.paid_queries;
    assert_eq!(selected.len(), 16);
    let random = routing::make_matched_random_plan(
        bank.recipe.world_id,
        &bank.offers,
        &bank.current_offers,
        simple,
        selected,
        preview.offer_requests,
    );
    assert_eq!(random.lane, Lane::MatchedRandomSimple);
    assert_eq!(random.call_target, Some(selected.len()));
    assert_eq!(
        random
            .query_price_targets
            .iter()
            .map(|(_, count)| count)
            .sum::<usize>(),
        selected.len()
    );
    assert!(random.candidates.len() >= selected.len());

    let runtime_root = temp_root("matched-random-runtime");
    let (_reference_traces, reference_result, reference_paid) =
        runtime::run_plan(bank, simple, &runtime_root.join("reference"), 901, &models).unwrap();
    let (_random_traces, random_result, random_paid) =
        runtime::run_plan(bank, &random, &runtime_root.join("random"), 902, &models).unwrap();
    assert_eq!(reference_result.paid_queries, selected.len());
    assert_eq!(random_result.paid_queries, reference_result.paid_queries);
    assert_eq!(
        random_result.query_cost_units,
        reference_result.query_cost_units
    );
    assert_eq!(
        random_result.offer_cost_units,
        reference_result.offer_cost_units
    );
    assert_eq!(random_result.offer_charges, reference_result.offer_charges);
    assert_eq!(random_paid.len(), reference_paid.len());
    assert!(reference_result.replay_identity_ok && random_result.replay_identity_ok);
    fs::remove_dir_all(&runtime_root).unwrap();

    let costed = plans
        .iter()
        .find(|plan| {
            plan.lane == Lane::SimpleOffer
                && plan.offer_mode == routing::OfferMode::CostedRefresh
                && plan.lambda == 0.03
                && plan.budget == 64
        })
        .unwrap();
    let costed_preview =
        routing::preview_route(&bank.public, &bank.current_offers, costed, &models);
    let costed_random = routing::make_matched_random_plan(
        bank.recipe.world_id,
        &bank.offers,
        &bank.current_offers,
        costed,
        &costed_preview.paid_queries,
        costed_preview.offer_requests,
    );
    let costed_root = temp_root("matched-costed-runtime");
    let (_, costed_reference_result, _) =
        runtime::run_plan(bank, costed, &costed_root.join("reference"), 911, &models).unwrap();
    let (_, costed_random_result, _) = runtime::run_plan(
        bank,
        &costed_random,
        &costed_root.join("random"),
        912,
        &models,
    )
    .unwrap();
    assert_eq!(
        costed_reference_result.paid_queries,
        costed_preview.paid_queries.len()
    );
    assert_eq!(
        costed_reference_result.offer_charges,
        costed_preview.offer_requests
    );
    assert_eq!(
        costed_random_result.paid_queries,
        costed_reference_result.paid_queries
    );
    assert_eq!(
        costed_random_result.query_cost_units,
        costed_reference_result.query_cost_units
    );
    assert_eq!(
        costed_random_result.offer_cost_units,
        costed_reference_result.offer_cost_units
    );
    assert_eq!(
        costed_random_result.offer_charges,
        costed_reference_result.offer_charges
    );
    fs::remove_dir_all(costed_root).unwrap();

    let fitted = plans
        .iter()
        .find(|plan| {
            plan.lane == Lane::FittedOffer
                && plan.offer_mode == routing::OfferMode::PushedCache
                && plan.lambda == 0.01
                && plan.budget == 16
        })
        .unwrap();
    let no_calls = routing::preview_route(&bank.public, &bank.current_offers, fitted, &models);
    assert!(no_calls.paid_queries.is_empty());
    assert_eq!(no_calls.offer_requests, 0);
    assert!(
        routing::make_matched_random_plan(
            bank.recipe.world_id,
            &bank.offers,
            &bank.current_offers,
            fitted,
            &no_calls.paid_queries,
            no_calls.offer_requests,
        )
        .candidates
        .is_empty()
    );
}

#[test]
fn heldout_input_audit_preserves_low_support_full_offer_collisions() {
    let heldout = domain::heldout_banks();
    let (groups, _) = evaluation::input_audit(&heldout, "heldout");
    let collision = groups.iter().find(|row| {
        row.cohort == "heldout-world-115"
            && row.feature == "all_fields"
            && row.key == "1|1|2|1|1|2|1|1|1|5"
            && row.target == "correct_action"
    });
    assert!(collision.is_some_and(|row| row.support == 9 && row.largest_class == 9));
}

#[test]
fn unknown_and_failed_inspections_do_not_authorize_the_active_action() {
    let public = domain::development_banks().remove(0).public.remove(0);
    for (transport, expected) in [
        (TransportStatus::Malformed, InspectionKind::Unknown),
        (TransportStatus::Timeout, InspectionKind::Failed),
    ] {
        let reply = InspectionReply {
            transport,
            candidate: u16::MAX,
            competing_candidate: u16::MAX,
            confidence_milli: 0,
            signature_valid: false,
            source_revision: 1,
            payload_digest: [0; 32],
        };
        let result = InspectionResult::classify(public.active, reply);
        assert_eq!(result.kind, expected);
        assert_eq!(result.proposed_action, None);
        let authorized =
            rdc_experiment_008::authority::execute(public, Some(result), ActionCode(0));
        assert_eq!(authorized.task_action_effects, 0);
        assert_eq!(authorized.illegal_commits, 0);
        assert!(authorized.replay_identity_ok);
    }
}

#[test]
fn no_inspection_and_crash_recovery_preserve_the_contract() {
    let dev = domain::development_banks();
    let models = FrozenModels::fit(&dev[..1]).unwrap();
    let bank = &dev[0];
    let plans = routing::make_plans(
        bank.recipe.world_id,
        &bank.public,
        &bank.offers,
        bank.recipe.offer_request_cost_units,
        &models,
    );
    let baseline = plans
        .iter()
        .find(|plan| plan.lane == Lane::NoInspection)
        .unwrap();
    let root = temp_root("runtime");
    let (traces, group, calls) =
        runtime::run_plan(bank, baseline, &root.join("receipts"), 123, &models).unwrap();
    assert!(traces.is_empty());
    assert!(calls.is_empty());
    assert_eq!(group.paid_queries, 0);
    assert_eq!(group.completed, group.outcomes.baseline_right as usize);
    assert_eq!(
        group.offers_obtained,
        bank.offers.len() * domain::SOURCE_COUNT
    );
    assert!(group.replay_identity_ok);
    let crash_rows = runtime::crash_recovery(&root.join("crash")).unwrap();
    assert_eq!(crash_rows.len(), 5);
    assert!(
        crash_rows
            .iter()
            .all(|row| row.replay_identity_ok && row.duplicate_charges == 0)
    );
    assert!(
        crash_rows
            .iter()
            .filter(|row| row.boundary != "offer_receipt_durable")
            .all(|row| row.paid_charges == 1)
    );
    assert!(
        crash_rows
            .iter()
            .filter(|row| row.boundary.contains("response_before"))
            .all(|row| row.endpoint_attempts == 2
                && row.retries == 1
                && row.journal_paid_requests == 1)
    );
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn shuffled_router_signals_do_not_change_the_quote_used_by_the_endpoint() {
    let development = domain::development_banks();
    let models = FrozenModels::fit(&development).unwrap();
    let heldout = domain::heldout_banks();
    let bank = &heldout[0];
    let plans = routing::make_plans(
        bank.recipe.world_id,
        &bank.public,
        &bank.offers,
        bank.recipe.offer_request_cost_units,
        &models,
    );
    let plan = plans
        .iter()
        .find(|plan| {
            plan.lane == Lane::ShuffledOffers
                && plan.offer_mode == routing::OfferMode::PushedCache
                && plan.lambda == 0.01
                && plan.budget == 64
        })
        .unwrap();
    let actual_index = bank
        .offers
        .iter()
        .position(|bundle| {
            let offer = bundle.offers[1];
            offer.availability != Availability::Unavailable
                && offer.offer_expiry > domain::OFFER_VALIDATION_TICK
        })
        .unwrap();
    let donor_index = (actual_index + 1) % bank.offers.len();
    let actual = bank.offers[actual_index].offers[1];
    let donor = bank.offers[donor_index].offers[1];
    let signal = routing::bind_action_terms(donor, actual);
    assert_eq!(signal.source_id, actual.source_id);
    assert_eq!(signal.version, actual.version);
    assert_eq!(signal.quoted_query_price, actual.quoted_query_price);
    assert_eq!(signal.offer_expiry, actual.offer_expiry);
    assert_eq!(
        signal.source_local_age_bucket,
        donor.source_local_age_bucket
    );
    assert_eq!(
        signal.historical_reliability_bucket,
        donor.historical_reliability_bucket
    );
    if let Some(candidate) = plan.candidates.first() {
        let true_quote = bank
            .offers
            .iter()
            .find(|row| row.episode_id == candidate.episode_id)
            .unwrap()
            .offers[candidate.source_id as usize];
        assert_eq!(candidate.offer, true_quote);
    }
    let candidate = routing::Candidate {
        episode_id: bank.offers[actual_index].episode_id,
        source_id: actual.source_id,
        offer: actual,
        signal_offer: signal,
        signal_episode_id: bank.offers[donor_index].episode_id,
        estimate: rdc_experiment_008::model::ValueEstimate {
            wrong_to_right: 1.0,
            ..Default::default()
        },
        predicted_delta: 1.0,
        predicted_value: 1.0,
        offer_only: false,
    };
    let contract_check = routing::BudgetPlan {
        world_id: bank.recipe.world_id,
        lane: Lane::MatchedRandomSimple,
        budget: 1,
        lambda: 0.0,
        offer_mode: routing::OfferMode::PushedCache,
        offer_request_cost: 0,
        call_target: Some(1),
        offer_charge_target: None,
        query_price_targets: vec![(actual.quoted_query_price, 1)],
        candidates: vec![candidate],
    };
    let root = temp_root("shuffled");
    let (traces, group, _) =
        runtime::run_plan(bank, &contract_check, &root.join("receipts"), 321, &models).unwrap();
    assert_eq!(traces.len(), 1);
    assert_eq!(group.query_attempts, group.paid_queries);
    assert!(traces.iter().all(|trace| trace.query_paid));
    assert_ne!(traces[0].signal_episode_id, traces[0].episode_id);
    for trace in &traces {
        let row = bank
            .public
            .iter()
            .position(|row| row.id == trace.episode_id)
            .unwrap();
        let quote = bank.offers[row].offers[trace.source_id as usize];
        assert_eq!(trace.offer_version_initial, quote.version);
        assert_eq!(trace.quote_price, quote.quoted_query_price);
    }
    fs::remove_dir_all(root).unwrap();
}
