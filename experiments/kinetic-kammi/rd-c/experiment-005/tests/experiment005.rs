use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_004::{
    domain::{FLAG_AUDIT_SELECTED, FLAG_AUDIT_WARNING, FLAG_PRIMARY_WARNING},
    episodes::contract_action,
};
use rdc_experiment_005::{
    DevelopmentValueModel, EpisodeClass, InspectionTool, Lane, PublicFrame, SourceStateStore,
    development_episodes, heldout_episodes, labels_for,
};
use rdc_experiment_005::{
    episodes::{DEVELOPMENT_SEED, HELDOUT_SEED},
    inspection::{QueryReceiptLog, verify_receipt_log, write_source_fixture},
    routing::{BUDGETS, make_public_plans, validate_exact},
};

fn temporary_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("rdc-e005-{label}-{nonce}"));
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn fresh_consistent_error_is_invisible_to_age_and_warning_checks() {
    let episode = heldout_episodes()
        .into_iter()
        .find(|episode| episode.class == EpisodeClass::FreshConsistentWrong)
        .unwrap();
    let features = episode.frame.features;
    assert_eq!(features.primary_action, features.audit_action);
    assert_eq!(features.primary_age, 0);
    assert_eq!(features.audit_age, 0);
    assert_eq!(
        features.flags & (FLAG_PRIMARY_WARNING | FLAG_AUDIT_WARNING | FLAG_AUDIT_SELECTED),
        0
    );
    assert_eq!(
        features.primary_action,
        contract_action(features.goal, features.primary_revision)
    );
    let label = labels_for(&[episode], HELDOUT_SEED).remove(0);
    assert_ne!(features.primary_action, label.correct_action);
    let decoded =
        PublicFrame::decode(&episode.observation(rdc_experiment_001::Signal::Approve)).unwrap();
    assert_eq!(decoded, episode.frame);
}

#[test]
fn development_estimate_predicts_benefit_and_harm_by_public_domain() {
    let episodes = development_episodes();
    let labels = labels_for(&episodes, DEVELOPMENT_SEED);
    let dir = temporary_dir("model");
    let path = dir.join("source-state.csv");
    write_source_fixture(&path, &episodes).unwrap();
    let source = SourceStateStore::load_mmap(&path).unwrap();
    let model = DevelopmentValueModel::fit(&episodes, &labels, &source).unwrap();
    assert_eq!(model.score(1), 750);
    assert_eq!(model.score(2), 500);
    assert_eq!(model.score(5), -1000);
    assert_eq!(model.score(0), 0);
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn inspection_result_is_separate_and_receipt_replay_binds_its_payload() {
    let episodes = heldout_episodes();
    let episode = episodes
        .iter()
        .find(|episode| episode.class == EpisodeClass::FreshConsistentWrong)
        .unwrap();
    let dir = temporary_dir("receipts");
    let source_path = dir.join("source-state.csv");
    let receipt_path = dir.join("queries.rdi");
    write_source_fixture(&source_path, std::slice::from_ref(episode)).unwrap();
    let public_text = fs::read_to_string(&source_path).unwrap();
    assert!(!public_text.contains("truth_revision"));
    assert!(!public_text.contains("correct_action"));
    let store = SourceStateStore::load_mmap(&source_path).unwrap();
    let tool = InspectionTool::new(&store);
    let (result, _) = tool.query(episode.id).unwrap();
    assert_ne!(
        &result.payload_digest[..16],
        &episode.frame.evidence().digest[..]
    );
    let mut log = QueryReceiptLog::create(&receipt_path, Lane::MatchedRandom, 1).unwrap();
    log.append(episode.id, result).unwrap();
    log.close().unwrap();
    let stats = verify_receipt_log(&receipt_path, &store).unwrap();
    assert_eq!(stats.calls, 1);
    assert_eq!(stats.identity.len(), 32);
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn public_router_budgets_are_exact_and_nested() {
    let development = development_episodes();
    let dev_labels = labels_for(&development, DEVELOPMENT_SEED);
    let dir = temporary_dir("plans");
    let source_path = dir.join("source-state.csv");
    write_source_fixture(&source_path, &development).unwrap();
    let source = SourceStateStore::load_mmap(&source_path).unwrap();
    let model = DevelopmentValueModel::fit(&development, &dev_labels, &source).unwrap();
    let heldout = heldout_episodes();
    let plans = make_public_plans(&heldout, &BUDGETS, &model).unwrap();
    validate_exact(&plans, heldout.len()).unwrap();
    for lane in [
        Lane::E004Combined,
        Lane::DevelopmentVoI,
        Lane::MatchedRandom,
    ] {
        for adjacent in BUDGETS.windows(2) {
            let smaller = plans
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == adjacent[0])
                .unwrap();
            let larger = plans
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == adjacent[1])
                .unwrap();
            assert!(smaller.selected_ids.is_subset(&larger.selected_ids));
        }
    }
    let _ = fs::remove_dir_all(dir);
}
