use crate::{
    certify_model_scores, certify_model_seed_receipt, evaluate_binary_scores, BinaryMetrics,
    FrozenBinaryEvaluationSet, FrozenModelBundle, FrozenModelCandidateReceipt,
    FrozenModelConfigurationSummary, FrozenModelManifest, FrozenModelMapped, FrozenModelSelection,
    FrozenModelSelectionError, FrozenModelSelectionLedger, FrozenModelSelectionOutcome,
    FrozenModelSelectionPaths, FrozenModelSelectionPolicy, ResearchSplit,
    FROZEN_MODEL_SELECTION_SCHEMA,
};
use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

const SELECTION_RULE: &str = "highest mean validation average precision; lowest mean validation brier; configuration id tie-break; representative seed by the same validation ordering; test executed once after selection";
const LOCKED_TEST_CLAIM_SCHEMA: &str = "phoenix-locked-test-claim/v1";

struct Candidate {
    receipt: FrozenModelCandidateReceipt,
    manifest: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LockedTestClaim {
    schema_version: CompactString,
    claim_id: CompactString,
    policy: FrozenModelSelectionPolicy,
    candidate_model_ids: Vec<CompactString>,
    selected_configuration_id: CompactString,
    selected_validation_model_id: CompactString,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConfigurationIdentity<'a> {
    source: &'a crate::FrozenModelSourceIdentity,
    architecture: &'a crate::FrozenModelArchitecture,
    hyperparameters: crate::FrozenModelHyperparameters,
    runtime: &'a crate::FrozenModelRuntimeIdentity,
    training: &'a crate::FrozenTrainingReceipt,
    policy: &'a FrozenModelSelectionPolicy,
}

pub fn select_frozen_models(
    manifests: &[PathBuf],
    policy: FrozenModelSelectionPolicy,
    validation: FrozenBinaryEvaluationSet<'_>,
) -> Result<FrozenModelSelection, FrozenModelSelectionError> {
    validate_policy(&policy)?;
    validate_set(validation)?;
    if manifests.is_empty() {
        return Err(FrozenModelSelectionError::InvalidContract(
            "candidate manifests",
        ));
    }
    let mut source = None;
    let mut seed_certificate = None;
    let mut model_ids = HashSet::with_capacity(manifests.len());
    let mut candidates = Vec::with_capacity(manifests.len());
    for path in manifests {
        let model = FrozenModelMapped::open(path)?;
        let manifest = model.manifest();
        validate_candidate_contract(manifest)?;
        if !model_ids.insert(manifest.model_id.clone()) {
            return Err(FrozenModelSelectionError::InvalidContract(
                "duplicate model id",
            ));
        }
        match &source {
            None => source = Some(manifest.source.clone()),
            Some(expected) if expected == &manifest.source => {}
            Some(_) => {
                return Err(FrozenModelSelectionError::InvalidContract(
                    "mixed source identity",
                ));
            }
        }
        match &seed_certificate {
            None => seed_certificate = Some(manifest.seeds.certificate.clone()),
            Some(expected) if expected == &manifest.seeds.certificate => {}
            Some(_) => {
                return Err(FrozenModelSelectionError::InvalidContract(
                    "mixed seed certificate",
                ));
            }
        }
        let scores = model.score_mlp16(validation.features)?;
        let metrics = evaluate_binary_scores(validation.labels, &scores, policy.calibration_bins)?;
        validate_selection_metrics(&metrics)?;
        let certificate = certify_model_scores(
            policy.task_id.clone(),
            policy.evaluator_schema.clone(),
            ResearchSplit::Validation,
            &scores,
            &metrics,
        )?;
        if !manifest.score_certificates.contains(&certificate) {
            return Err(FrozenModelSelectionError::InvalidContract(
                "validation certificate mismatch",
            ));
        }
        let configuration_id = configuration_id(manifest, &policy)?;
        candidates.push(Candidate {
            receipt: FrozenModelCandidateReceipt {
                configuration_id,
                model_id: manifest.model_id.clone(),
                weights_blake3: manifest.weights_blake3.clone(),
                selected_repeat: manifest.seeds.selected_repeat,
                selected_seed: manifest
                    .seeds
                    .selected_seed()
                    .ok_or(FrozenModelSelectionError::InvalidContract("selected seed"))?,
                validation_score_certificate: certificate,
                validation_metrics: metrics,
            },
            manifest: path.clone(),
        });
    }
    candidates.sort_by(|left, right| candidate_identity_order(&left.receipt, &right.receipt));
    let seed_certificate = seed_certificate.expect("nonempty candidates");
    validate_complete_seed_sets(&candidates, seed_certificate.seeds.len())?;
    let summaries = summarize_configurations(&candidates)?;
    let selected_summary = summaries
        .iter()
        .min_by(|left, right| configuration_selection_order(left, right))
        .expect("nonempty summaries");
    let selected = candidates
        .iter()
        .filter(|candidate| candidate.receipt.configuration_id == selected_summary.configuration_id)
        .min_by(|left, right| candidate_selection_order(&left.receipt, &right.receipt))
        .expect("selected configuration has candidates");
    Ok(FrozenModelSelection {
        source: source.expect("nonempty candidates"),
        seed_certificate,
        policy,
        candidates: candidates
            .iter()
            .map(|candidate| candidate.receipt.clone())
            .collect(),
        summaries,
        selected_configuration_id: selected.receipt.configuration_id.clone(),
        selected_validation_model_id: selected.receipt.model_id.clone(),
        selected_manifest: selected.manifest.clone(),
    })
}

pub fn finalize_frozen_model_selection(
    selection: FrozenModelSelection,
    test: FrozenBinaryEvaluationSet<'_>,
    root: impl AsRef<Path>,
) -> Result<FrozenModelSelectionOutcome, FrozenModelSelectionError> {
    validate_set(test)?;
    let selected = FrozenModelMapped::open(&selection.selected_manifest)?;
    if selected.manifest().model_id != selection.selected_validation_model_id
        || selected
            .manifest()
            .score_certificates
            .iter()
            .any(|certificate| certificate.split == ResearchSplit::Test)
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "selected model drift",
        ));
    }
    let selected_weights = selected.manifest().weights_blake3.clone();
    let root = root.as_ref();
    let (locked_test_claim_id, test_claim_path) = claim_locked_test(&selection, root)?;
    let scores = selected.score_mlp16(test.features)?;
    let test_metrics =
        evaluate_binary_scores(test.labels, &scores, selection.policy.calibration_bins)?;
    validate_selection_metrics(&test_metrics)?;
    let test_certificate = certify_model_scores(
        selection.policy.task_id.clone(),
        selection.policy.evaluator_schema.clone(),
        ResearchSplit::Test,
        &scores,
        &test_metrics,
    )?;
    let mut finalized_snapshot = selected.snapshot()?;
    finalized_snapshot
        .score_certificates
        .push(test_certificate.clone());
    drop(selected);
    let finalized_model = FrozenModelBundle::write(&finalized_snapshot, root)?;
    let finalized = FrozenModelMapped::open(&finalized_model.manifest)?;
    if finalized.manifest().weights_blake3 != selected_weights
        || finalized.manifest().model_id == selection.selected_validation_model_id
        || finalized
            .manifest()
            .score_certificates
            .iter()
            .filter(|certificate| certificate.split == ResearchSplit::Test)
            .count()
            != 1
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "finalized model identity",
        ));
    }
    let mut ledger = FrozenModelSelectionLedger {
        schema_version: FROZEN_MODEL_SELECTION_SCHEMA.into(),
        ledger_id: "pending".into(),
        source: selection.source,
        seed_certificate: selection.seed_certificate,
        policy: selection.policy,
        selection_rule: SELECTION_RULE.into(),
        candidates: selection.candidates,
        configuration_summaries: selection.summaries,
        selected_configuration_id: selection.selected_configuration_id,
        selected_validation_model_id: selection.selected_validation_model_id,
        finalized_model_id: finalized.manifest().model_id.clone(),
        selected_weights_blake3: selected_weights,
        locked_test_claim_id,
        locked_test_executions: 1,
        test_score_certificate: test_certificate,
        test_metrics,
    };
    ledger.ledger_id = ledger_identity(&ledger)?;
    let ledger_path = root.join(format!("{}.model-selection.json", ledger.ledger_id));
    write_immutable(&ledger_path, &serde_json::to_vec_pretty(&ledger)?)?;
    let ledger = open_frozen_model_selection_ledger(&ledger_path)?;
    Ok(FrozenModelSelectionOutcome {
        ledger,
        paths: FrozenModelSelectionPaths {
            test_claim: test_claim_path,
            ledger: ledger_path,
            finalized_model,
        },
    })
}

pub fn open_frozen_model_selection_ledger(
    path: impl AsRef<Path>,
) -> Result<FrozenModelSelectionLedger, FrozenModelSelectionError> {
    let path = path.as_ref();
    let ledger: FrozenModelSelectionLedger = serde_json::from_slice(&std::fs::read(path)?)?;
    let expected_name = format!("{}.model-selection.json", ledger.ledger_id);
    if ledger.schema_version != FROZEN_MODEL_SELECTION_SCHEMA
        || ledger.ledger_id != ledger_identity(&ledger)?
        || path.file_name().and_then(|name| name.to_str()) != Some(expected_name.as_str())
        || ledger.locked_test_executions != 1
        || ledger.finalized_model_id == ledger.selected_validation_model_id
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "persisted ledger identity",
        ));
    }
    validate_persisted_ledger(&ledger)?;
    validate_locked_test_claim(path, &ledger)?;
    Ok(ledger)
}

fn claim_locked_test(
    selection: &FrozenModelSelection,
    root: &Path,
) -> Result<(CompactString, PathBuf), FrozenModelSelectionError> {
    let mut claim = LockedTestClaim {
        schema_version: LOCKED_TEST_CLAIM_SCHEMA.into(),
        claim_id: "pending".into(),
        policy: selection.policy.clone(),
        candidate_model_ids: selection
            .candidates
            .iter()
            .map(|candidate| candidate.model_id.clone())
            .collect(),
        selected_configuration_id: selection.selected_configuration_id.clone(),
        selected_validation_model_id: selection.selected_validation_model_id.clone(),
    };
    claim.claim_id = locked_test_claim_identity(&claim)?;
    let path = root.join(format!("{}.locked-test-claim.json", claim.claim_id));
    let bytes = serde_json::to_vec_pretty(&claim)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                FrozenModelSelectionError::LockedTestAlreadyClaimed(path.clone())
            } else {
                error.into()
            }
        })?;
    if let Err(error) = file.write_all(&bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&path);
        return Err(error.into());
    }
    Ok((claim.claim_id, path))
}

fn validate_locked_test_claim(
    ledger_path: &Path,
    ledger: &FrozenModelSelectionLedger,
) -> Result<(), FrozenModelSelectionError> {
    let path = ledger_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(format!(
            "{}.locked-test-claim.json",
            ledger.locked_test_claim_id
        ));
    let claim: LockedTestClaim = serde_json::from_slice(&std::fs::read(path)?)?;
    let candidate_model_ids: Vec<_> = ledger
        .candidates
        .iter()
        .map(|candidate| candidate.model_id.clone())
        .collect();
    if claim.schema_version != LOCKED_TEST_CLAIM_SCHEMA
        || claim.claim_id != ledger.locked_test_claim_id
        || claim.claim_id != locked_test_claim_identity(&claim)?
        || claim.policy != ledger.policy
        || claim.candidate_model_ids != candidate_model_ids
        || claim.selected_configuration_id != ledger.selected_configuration_id
        || claim.selected_validation_model_id != ledger.selected_validation_model_id
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "locked test claim",
        ));
    }
    Ok(())
}

fn locked_test_claim_identity(
    claim: &LockedTestClaim,
) -> Result<CompactString, FrozenModelSelectionError> {
    let mut identity = claim.clone();
    identity.claim_id = "pending".into();
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    ))
}

fn validate_persisted_ledger(
    ledger: &FrozenModelSelectionLedger,
) -> Result<(), FrozenModelSelectionError> {
    validate_policy(&ledger.policy)?;
    validate_selection_metrics(&ledger.test_metrics)?;
    if ledger.candidates.is_empty()
        || ledger.configuration_summaries.is_empty()
        || ledger.test_score_certificate.split != ResearchSplit::Test
        || ledger.test_score_certificate.task_id != ledger.policy.task_id
        || ledger.test_score_certificate.evaluator_schema != ledger.policy.evaluator_schema
        || ledger.test_score_certificate.score_count != ledger.test_metrics.samples
        || !is_blake3(ledger.finalized_model_id.as_str())
        || !is_blake3(ledger.selected_weights_blake3.as_str())
        || !is_blake3(ledger.locked_test_claim_id.as_str())
        || ledger
            .candidates
            .windows(2)
            .any(|rows| candidate_identity_order(&rows[0], &rows[1]) == Ordering::Greater)
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "persisted ledger contract",
        ));
    }
    let mut grouped: HashMap<&str, Vec<&FrozenModelCandidateReceipt>> = HashMap::new();
    let mut model_ids = HashSet::with_capacity(ledger.candidates.len());
    for candidate in &ledger.candidates {
        let seed = certify_model_seed_receipt(&ledger.seed_certificate, candidate.selected_repeat)?
            .selected_seed();
        validate_selection_metrics(&candidate.validation_metrics)?;
        if !model_ids.insert(candidate.model_id.as_str())
            || seed != Some(candidate.selected_seed)
            || !is_blake3(candidate.model_id.as_str())
            || !is_blake3(candidate.weights_blake3.as_str())
            || candidate.validation_score_certificate.split != ResearchSplit::Validation
            || candidate.validation_score_certificate.task_id != ledger.policy.task_id
            || candidate.validation_score_certificate.evaluator_schema
                != ledger.policy.evaluator_schema
            || candidate.validation_score_certificate.score_count
                != candidate.validation_metrics.samples
        {
            return Err(FrozenModelSelectionError::InvalidContract(
                "persisted candidate contract",
            ));
        }
        grouped
            .entry(candidate.configuration_id.as_str())
            .or_default()
            .push(candidate);
    }
    if grouped.len() != ledger.configuration_summaries.len() {
        return Err(FrozenModelSelectionError::InvalidContract(
            "persisted configuration set",
        ));
    }
    for summary in &ledger.configuration_summaries {
        let rows = grouped.get(summary.configuration_id.as_str()).ok_or(
            FrozenModelSelectionError::InvalidContract("persisted configuration summary"),
        )?;
        let expected_models: Vec<_> = rows.iter().map(|row| row.model_id.clone()).collect();
        let repeats: HashSet<_> = rows.iter().map(|row| row.selected_repeat).collect();
        let count = rows.len() as f64;
        let mean_ap = rows
            .iter()
            .map(|row| row.validation_metrics.average_precision.unwrap_or_default())
            .sum::<f64>()
            / count;
        let mean_brier = rows
            .iter()
            .map(|row| row.validation_metrics.brier_score)
            .sum::<f64>()
            / count;
        if rows.len() != ledger.seed_certificate.seeds.len()
            || repeats.len() != rows.len()
            || usize::from(summary.repeats) != rows.len()
            || summary.model_ids != expected_models
            || summary.mean_validation_average_precision != canonical_f64(mean_ap)?
            || summary.mean_validation_brier_score != canonical_f64(mean_brier)?
        {
            return Err(FrozenModelSelectionError::InvalidContract(
                "persisted configuration summary",
            ));
        }
    }
    let selected_summary = ledger
        .configuration_summaries
        .iter()
        .min_by(|left, right| configuration_selection_order(left, right))
        .expect("validated nonempty summaries");
    let selected = ledger
        .candidates
        .iter()
        .filter(|candidate| candidate.configuration_id == selected_summary.configuration_id)
        .min_by(|left, right| candidate_selection_order(left, right))
        .expect("validated complete configuration");
    if ledger.selected_configuration_id != selected_summary.configuration_id
        || ledger.selected_validation_model_id != selected.model_id
        || ledger.selected_weights_blake3 != selected.weights_blake3
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "persisted deterministic selection",
        ));
    }
    Ok(())
}

fn validate_policy(policy: &FrozenModelSelectionPolicy) -> Result<(), FrozenModelSelectionError> {
    if policy.task_id.is_empty()
        || policy.evaluator_schema.is_empty()
        || !(2..=50).contains(&policy.calibration_bins)
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "selection policy",
        ));
    }
    Ok(())
}

fn validate_set(set: FrozenBinaryEvaluationSet<'_>) -> Result<(), FrozenModelSelectionError> {
    if set.features.is_empty() || set.features.len() != set.labels.len() {
        return Err(FrozenModelSelectionError::InvalidContract("evaluation set"));
    }
    Ok(())
}

fn validate_candidate_contract(
    manifest: &FrozenModelManifest,
) -> Result<(), FrozenModelSelectionError> {
    if !manifest.training.selected_on_validation
        || !manifest.training.test_locked_during_selection
        || manifest.training.training_executions != 1
        || manifest
            .score_certificates
            .iter()
            .any(|certificate| certificate.split == ResearchSplit::Test)
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "candidate test lock",
        ));
    }
    Ok(())
}

fn validate_selection_metrics(metrics: &BinaryMetrics) -> Result<(), FrozenModelSelectionError> {
    if metrics.samples == 0
        || metrics.positives == 0
        || metrics.positives > metrics.samples
        || !metrics.log_loss.is_finite()
        || metrics.log_loss < 0.0
        || !metrics.brier_score.is_finite()
        || !(0.0..=1.0).contains(&metrics.brier_score)
        || !metrics.expected_calibration_error.is_finite()
        || !(0.0..=1.0).contains(&metrics.expected_calibration_error)
        || metrics
            .average_precision
            .is_none_or(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
        || metrics
            .roc_auc
            .is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "selection metrics",
        ));
    }
    Ok(())
}

fn configuration_id(
    manifest: &FrozenModelManifest,
    policy: &FrozenModelSelectionPolicy,
) -> Result<CompactString, FrozenModelSelectionError> {
    let identity = ConfigurationIdentity {
        source: &manifest.source,
        architecture: &manifest.architecture,
        hyperparameters: manifest.hyperparameters,
        runtime: &manifest.runtime,
        training: &manifest.training,
        policy,
    };
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    ))
}

fn validate_complete_seed_sets(
    candidates: &[Candidate],
    expected_repeats: usize,
) -> Result<(), FrozenModelSelectionError> {
    let mut repeats: HashMap<&str, HashSet<u16>> = HashMap::new();
    for candidate in candidates {
        let selected = candidate.receipt.selected_repeat;
        if usize::from(selected) >= expected_repeats
            || !repeats
                .entry(candidate.receipt.configuration_id.as_str())
                .or_default()
                .insert(selected)
        {
            return Err(FrozenModelSelectionError::InvalidContract(
                "duplicate seed repeat",
            ));
        }
    }
    if repeats
        .values()
        .any(|repeats| repeats.len() != expected_repeats)
    {
        return Err(FrozenModelSelectionError::InvalidContract(
            "incomplete seed configuration",
        ));
    }
    Ok(())
}

fn summarize_configurations(
    candidates: &[Candidate],
) -> Result<Vec<FrozenModelConfigurationSummary>, FrozenModelSelectionError> {
    let mut grouped: HashMap<&str, Vec<&FrozenModelCandidateReceipt>> = HashMap::new();
    for candidate in candidates {
        grouped
            .entry(candidate.receipt.configuration_id.as_str())
            .or_default()
            .push(&candidate.receipt);
    }
    let mut summaries = Vec::with_capacity(grouped.len());
    for (configuration_id, rows) in grouped {
        let count = rows.len() as f64;
        let mean_ap = rows
            .iter()
            .map(|row| row.validation_metrics.average_precision.unwrap_or_default())
            .sum::<f64>()
            / count;
        let mean_brier = rows
            .iter()
            .map(|row| row.validation_metrics.brier_score)
            .sum::<f64>()
            / count;
        if !mean_ap.is_finite() || !mean_brier.is_finite() {
            return Err(FrozenModelSelectionError::InvalidContract(
                "configuration aggregate",
            ));
        }
        summaries.push(FrozenModelConfigurationSummary {
            configuration_id: configuration_id.into(),
            model_ids: rows.iter().map(|row| row.model_id.clone()).collect(),
            repeats: rows.len() as u16,
            mean_validation_average_precision: canonical_f64(mean_ap)?,
            mean_validation_brier_score: canonical_f64(mean_brier)?,
        });
    }
    summaries.sort_by(|left, right| left.configuration_id.cmp(&right.configuration_id));
    Ok(summaries)
}

fn canonical_f64(value: f64) -> Result<f64, FrozenModelSelectionError> {
    Ok(serde_json::from_str(&serde_json::to_string(&value)?)?)
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value.as_bytes()[3..]
            .iter()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn candidate_identity_order(
    left: &FrozenModelCandidateReceipt,
    right: &FrozenModelCandidateReceipt,
) -> Ordering {
    left.configuration_id
        .cmp(&right.configuration_id)
        .then(left.selected_repeat.cmp(&right.selected_repeat))
        .then(left.model_id.cmp(&right.model_id))
}

fn configuration_selection_order(
    left: &FrozenModelConfigurationSummary,
    right: &FrozenModelConfigurationSummary,
) -> Ordering {
    right
        .mean_validation_average_precision
        .total_cmp(&left.mean_validation_average_precision)
        .then(
            left.mean_validation_brier_score
                .total_cmp(&right.mean_validation_brier_score),
        )
        .then(left.configuration_id.cmp(&right.configuration_id))
}

fn candidate_selection_order(
    left: &FrozenModelCandidateReceipt,
    right: &FrozenModelCandidateReceipt,
) -> Ordering {
    right
        .validation_metrics
        .average_precision
        .unwrap_or_default()
        .total_cmp(
            &left
                .validation_metrics
                .average_precision
                .unwrap_or_default(),
        )
        .then(
            left.validation_metrics
                .brier_score
                .total_cmp(&right.validation_metrics.brier_score),
        )
        .then(left.model_id.cmp(&right.model_id))
}

fn ledger_identity(
    ledger: &FrozenModelSelectionLedger,
) -> Result<CompactString, FrozenModelSelectionError> {
    let mut identity = ledger.clone();
    identity.ledger_id = "pending".into();
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    ))
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), FrozenModelSelectionError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(FrozenModelSelectionError::ArtifactExists(
                path.to_path_buf(),
            ))
        };
    }
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("model-selection");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}
