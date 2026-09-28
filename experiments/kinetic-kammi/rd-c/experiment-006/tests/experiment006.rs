use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_004::Choice;
use rdc_experiment_006::{
    InspectionOutcome, InspectionResult, InspectionSourceStore, Lane, QueryId, QueryReceiptLog,
    QuerySimulator, development_episodes, heldout_episodes, labels_for,
};
use rdc_experiment_006::{
    episodes::Scenario,
    inspection::{
        CrashPoint, InspectionReply, TransportStatus, verify_receipt_log, write_source_fixture,
    },
    routing::{BUDGETS, make_plans, validate_exact},
    runtime::{RunSpec, new_compiler, run_episode},
    scoring::{FeatureValueModel, FrozenDomainTable, SmoothedValueModel},
};

fn temp_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("rdc-e006-{label}-{nonce}"));
    fs::create_dir_all(&path).unwrap();
    path
}

fn reply(
    transport: TransportStatus,
    candidate_a: u8,
    candidate_b: u8,
    valid: bool,
) -> InspectionReply {
    InspectionReply {
        transport,
        candidate_a,
        candidate_b,
        confidence: 950,
        signature_valid: valid,
        reported_revision: 44,
        payload_digest: [7; 32],
    }
}

#[test]
fn four_typed_outcomes_do_not_turn_unknown_or_failed_into_active_action() {
    let active = Choice::UsePrimary;
    let confirmed = InspectionResult::classify(
        active,
        reply(TransportStatus::Complete, active as u8, u8::MAX, true),
    );
    assert_eq!(confirmed.outcome, InspectionOutcome::Confirmed);
    assert_eq!(confirmed.proposed_action, Some(active));

    let contradicted = InspectionResult::classify(
        active,
        reply(
            TransportStatus::Complete,
            Choice::VerifyRecord as u8,
            u8::MAX,
            true,
        ),
    );
    assert_eq!(contradicted.outcome, InspectionOutcome::Contradicted);
    assert_eq!(contradicted.proposed_action, Some(Choice::VerifyRecord));

    let unknown = InspectionResult::classify(
        active,
        reply(
            TransportStatus::Complete,
            active as u8,
            Choice::RefreshSnapshot as u8,
            true,
        ),
    );
    assert_eq!(unknown.outcome, InspectionOutcome::Unknown);
    assert_eq!(unknown.proposed_action, None);

    let failed = InspectionResult::classify(
        active,
        reply(TransportStatus::Timeout, u8::MAX, u8::MAX, false),
    );
    assert_eq!(failed.outcome, InspectionOutcome::Failed);
    assert_eq!(failed.proposed_action, None);
}

#[test]
fn failed_and_conflicting_inspection_returns_runtime_to_observing() {
    let episode = heldout_episodes()
        .into_iter()
        .find(|episode| episode.scenario == Scenario::SelfConflict)
        .unwrap();
    let label = labels_for(std::slice::from_ref(&episode)).remove(0);
    let result = InspectionResult::classify(
        episode.frame.features.primary_action,
        reply(
            TransportStatus::Complete,
            Choice::UsePrimary as u8,
            Choice::VerifyRecord as u8,
            true,
        ),
    );
    assert_eq!(result.outcome, InspectionOutcome::Unknown);
    let dir = temp_dir("reobserve");
    let (schema, compiler) = new_compiler().unwrap();
    let run = run_episode(RunSpec {
        lane: Lane::FeatureEstimate,
        budget: 1,
        episode: &episode,
        label: &label,
        result: Some(result),
        compiler: &compiler,
        schema: &schema,
        journal_root: &dir,
        task_salt: 0xE006_1111_0000_0000,
        query_ns: 0,
        resolver_ns: 0,
        query_id: None,
    })
    .unwrap();
    assert!(run.reobserve);
    assert_eq!(run.selected_action, None);
    assert_eq!(run.task_action_effects, 0);
    assert_eq!(run.reobserve_effects, 1);
    assert!(!run.task_completed);
    assert_eq!(run.illegal_commits, 0);
    assert_eq!(run.duplicate_actions, 0);
    assert_eq!(run.missing_actions, 0);
    assert!(run.replay_identity_ok);
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn paid_result_before_receipt_crash_reuses_query_id_without_second_charge() {
    let episodes = heldout_episodes();
    let episode = episodes
        .iter()
        .find(|episode| episode.scenario == Scenario::HelpfulContradiction)
        .unwrap();
    let labels = labels_for(std::slice::from_ref(episode));
    let dir = temp_dir("query-crash");
    let source_fixture = dir.join("source.csv");
    write_source_fixture(&source_fixture, std::slice::from_ref(episode)).unwrap();
    let source_store = InspectionSourceStore::load_mmap(source_fixture).unwrap();
    let endpoint_path = dir.join("endpoint.rds");
    let receipt_path = dir.join("receipts.rdi");
    let id = QueryId::from_parts(0xE006, Lane::MatchedRandom.index(), 1, episode.id);
    let active = episode.frame.features.primary_action;

    let mut endpoint = QuerySimulator::create(&endpoint_path, &source_store).unwrap();
    let mut receipts = QueryReceiptLog::create(&receipt_path).unwrap();
    assert!(
        receipts
            .execute(
                &mut endpoint,
                id,
                episode.id,
                active,
                CrashPoint::AfterEndpointResponse
            )
            .is_err()
    );
    receipts.close().unwrap();
    endpoint.close().unwrap();

    let mut endpoint = QuerySimulator::resume(&endpoint_path, &source_store).unwrap();
    let mut receipts = QueryReceiptLog::resume(&receipt_path).unwrap();
    let result = receipts
        .execute(&mut endpoint, id, episode.id, active, CrashPoint::None)
        .unwrap();
    assert_eq!(result.outcome, InspectionOutcome::Contradicted);
    receipts.close().unwrap();
    endpoint.close().unwrap();

    let stats = verify_receipt_log(&receipt_path).unwrap();
    assert_eq!(stats.queries, 1);
    assert_eq!(stats.attempts, 2);
    assert_eq!(stats.retries, 1);
    assert_eq!(stats.charges, 1);
    assert_eq!(stats.outcomes, 1);
    let endpoint = QuerySimulator::resume(&endpoint_path, &source_store).unwrap();
    assert_eq!(endpoint.charges, 1);
    endpoint.close().unwrap();
    let _ = labels;
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn public_route_plans_are_exact_nested_and_do_not_read_unseen_domain_values() {
    let dev = development_episodes();
    let dev_labels = labels_for(&dev);
    let dir = temp_dir("plans");
    let source_path = dir.join("dev-source.csv");
    write_source_fixture(&source_path, &dev).unwrap();
    let source = InspectionSourceStore::load_mmap(&source_path).unwrap();
    let smoothed = SmoothedValueModel::fit(&dev, &dev_labels, &source).unwrap();
    let feature = FeatureValueModel::fit(&dev, &dev_labels, &source).unwrap();
    let mut scores = String::from(
        "inspection_domain,development_examples,wrong_to_right,right_to_wrong,expected_net_benefit_milli\n",
    );
    for domain in 0..8 {
        let examples = 32;
        let gains = if domain == 1 {
            24
        } else if domain == 2 {
            16
        } else if domain == 3 {
            32
        } else {
            0
        };
        let harms = if domain == 5 { 32 } else { 0 };
        scores.push_str(&format!(
            "{domain},{examples},{gains},{harms},{}\n",
            (gains - harms) * 1000 / examples
        ));
    }
    fs::write(dir.join("e005-table.csv"), scores).unwrap();
    let e005 = FrozenDomainTable::load_csv(dir.join("e005-table.csv")).unwrap();
    let heldout = heldout_episodes();
    let plans = make_plans(&heldout, &BUDGETS, &e005, &smoothed, &feature).unwrap();
    validate_exact(&plans, &heldout).unwrap();
    assert_eq!(e005.score_milli(8), 0);
    assert_eq!(
        plans
            .iter()
            .filter(|plan| plan.lane == Lane::NoInspection && plan.budget == 0)
            .count(),
        1
    );
    for lane in Lane::ROUTERS {
        for pair in BUDGETS.windows(2) {
            let left = plans
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == pair[0])
                .unwrap();
            let right = plans
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == pair[1])
                .unwrap();
            assert!(left.selected_ids.is_subset(&right.selected_ids));
        }
    }
    let _ = fs::remove_dir_all(dir);
}
