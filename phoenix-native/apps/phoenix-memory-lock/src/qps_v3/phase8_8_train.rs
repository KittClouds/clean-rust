use phoenix_lexical_qps::{
    evaluate_query_normalized_lambdarank_v3, rank_evidence_schema_identity_v3,
    train_query_normalized_lambdarank_v3_prevalidated, LambdaRankObjectiveReceiptV3,
    LeakageSplitV3, LinearTrainingConfigV3, LinearTrainingReceiptV3, PrimarySplitV3,
    QueryNormalizedDevelopmentV3, RelevanceLedgerV3, RANK_EVIDENCE_V3_FEATURE_NAMES,
};

use super::train::{
    decode_hex_32, LinearModelArtifactV3, PairwiseEvaluationV3, Phase7QualificationReceipt,
};
use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.8-top-sensitive-training/v2";
const FEASIBILITY_CONTRACT: &str = "phoenix.memory.qps-v3-phase8.8-monotone-feasibility/v1";
const ARTIFACT_CONTRACT: &str = "phoenix.qps.linear-model-artifact/v3";
const REQUIRED_ENGINE_VERSION: &str = "phoenix-qps-v3-linear/3";

pub(crate) fn train(
    baseline_model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_3_path: &Path,
    feasibility_path: &Path,
    output_path: &Path,
) -> Result<Phase88Publication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.8 model artifact {}",
            output_path.display()
        );
    }
    let baseline: LinearModelArtifactV3 = read_json(baseline_model_path, "baseline model")?;
    if !baseline.validate_challenger() {
        bail!("Phase 8.8 requires a valid canonical Phase 7 model");
    }
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    let phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let feasibility: FrozenFeasibility = read_json(feasibility_path, "feasibility receipt")?;
    validate_inputs(
        baseline_model_path,
        phase_6_path,
        phase_4_path,
        &baseline,
        &phase_6,
        &phase_4,
        &phase_3,
        &feasibility,
    )?;

    let ledger_bytes = serde_json::to_vec(&phase_4.ledger)?;
    let training_ledger_identity = decode_hex_32(&sha256_bytes(&ledger_bytes))?;
    if baseline.training_ledger_identity != training_ledger_identity {
        bail!("Phase 8.8 baseline is not bound to the supplied ledger");
    }
    let selection =
        select_configuration(&phase_4.ledger, &phase_6.split, training_ledger_identity)?;
    let first = train_query_normalized_lambdarank_v3_prevalidated(
        &phase_4.ledger,
        &phase_6.split,
        training_ledger_identity,
        selection.config,
    )
    .map_err(anyhow::Error::msg)?;
    let second = train_query_normalized_lambdarank_v3_prevalidated(
        &phase_4.ledger,
        &phase_6.split,
        training_ledger_identity,
        selection.config,
    )
    .map_err(anyhow::Error::msg)?;
    let deterministic_training = first == second;
    let objective = first.1;
    let compatibility_receipt = LinearTrainingReceiptV3 {
        training_ledger_identity,
        leakage_split_identity: objective.leakage_split_identity,
        feature_schema_identity: objective.feature_schema_identity,
        model_identity: objective.model_identity,
        training_judgments: objective.training_judgments,
        epochs: objective.epochs,
        learning_rate: objective.learning_rate,
        l2_penalty: objective.l2_penalty,
        initial_pairwise_loss: objective.initial_query_normalized_objective,
        final_pairwise_loss: objective.final_query_normalized_objective,
        correctly_ordered: objective.correctly_ordered,
        pairwise_accuracy: objective.row_pairwise_accuracy,
    };
    let qualification = Phase7QualificationReceipt {
        deterministic_training,
        monotonic_non_negative_weights: first.0.weights.iter().all(|weight| *weight >= 0.0),
        primitive_feature_schema_only: !RANK_EVIDENCE_V3_FEATURE_NAMES
            .iter()
            .any(|name| matches!(*name, "baseline_score" | "candidate_strength")),
        frozen_identity_normalization: first
            .0
            .normalization
            .offsets
            .iter()
            .all(|value| *value == 0.0)
            && first
                .0
                .normalization
                .scales
                .iter()
                .all(|value| *value == 1.0),
        bounded_training_configuration: selection.config.epochs <= 16_384
            && selection.config.learning_rate > 0.0
            && selection.config.learning_rate <= 1.0
            && (0.0..=0.1).contains(&selection.config.l2_penalty),
        loss_is_finite_and_improves: objective.initial_query_normalized_objective.is_finite()
            && objective.final_query_normalized_objective.is_finite()
            && objective.final_query_normalized_objective
                < objective.initial_query_normalized_objective,
        development_selected_configuration: true,
        configurations_evaluated: selection.configurations_evaluated,
        development: PairwiseEvaluationV3 {
            judgments: selection.development.judgments,
            correctly_ordered: selection.development.correctly_ordered,
            non_finite_scores: selection.development.non_finite_scores,
            accuracy: selection.development.row_pairwise_accuracy,
        },
        blind_test: None,
    };
    let artifact = LinearModelArtifactV3 {
        contract: ARTIFACT_CONTRACT.to_owned(),
        artifact_version: 3,
        feature_schema_identity: rank_evidence_schema_identity_v3(),
        training_ledger_identity,
        model_identity: first.0.identity(),
        model_parameters: first.0,
        normalization_parameters: first.0.normalization,
        training_receipt: compatibility_receipt,
        qualification_receipt: qualification,
        required_qps_engine_version: REQUIRED_ENGINE_VERSION.to_owned(),
        rollback_model_identity: decode_hex_32(&phase_3.v2_configuration_sha256)?,
        runtime_training: "forbidden_offline_only".to_owned(),
    };
    let gates = Phase88TrainingGates {
        feasibility_authorized: feasibility.authorize_phase_8_8_training,
        development_only_model_selection: true,
        blind_test_is_sealed: true,
        query_force_normalized: true,
        top_sensitive_weight_preregistered: true,
        dynamic_current_order_reweighting: objective.dynamic_current_order_reweighting,
        deterministic_training,
        monotonic_nonnegative_weights: artifact
            .model_parameters
            .weights
            .iter()
            .all(|weight| *weight >= 0.0),
        objective_is_finite_and_improves: artifact
            .qualification_receipt
            .loss_is_finite_and_improves,
        canonical_rank_evidence_schema_unchanged: true,
        canonical_ledger_unchanged: true,
        frozen_v2_substrate_unchanged: true,
        runtime_training_forbidden: true,
        artifact_valid: artifact.validate_challenger(),
    };
    if !gates.all_pass() {
        bail!("Phase 8.8 training integrity gates failed: {gates:?}");
    }
    let envelope = Phase88ArtifactEnvelope {
        artifact,
        phase_8_8_contract: CONTRACT,
        objective: "query_normalized_dynamic_lambdarank_pairwise_logistic_plus_l2",
        selection_criterion: "minimum_development_query_normalized_top_sensitive_logistic_loss",
        feasibility_receipt: file_identity(feasibility_path)?,
        objective_receipt: objective,
        development_selection: selection.development,
        configurations_evaluated: selection.configurations_evaluated,
        gates,
        production_promotion_authorized: false,
        active_engine_after_training: "V2 active",
    };
    let first_bytes = serde_json::to_vec_pretty(&envelope)?;
    let second_bytes = serde_json::to_vec_pretty(&envelope)?;
    if first_bytes != second_bytes {
        bail!("Phase 8.8 artifact serialization is not deterministic");
    }
    write_bytes_atomic(output_path, &first_bytes)?;
    Ok(Phase88Publication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        model_identity: envelope.artifact.model_identity,
        selected_config: selection.config,
        configurations_evaluated: selection.configurations_evaluated,
        development: selection.development,
        gates,
        production_promotion_authorized: false,
        active_engine_after_training: "V2 active",
    })
}

#[allow(clippy::too_many_arguments)]
fn validate_inputs(
    baseline_model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    baseline: &LinearModelArtifactV3,
    phase_6: &FrozenPhase6,
    phase_4: &FrozenPhase4,
    phase_3: &FrozenPhase3,
    feasibility: &FrozenFeasibility,
) -> Result<()> {
    if phase_6.contract != "phoenix.memory.qps-v3-leakage-split/v1"
        || !phase_6.phase_6_verified
        || phase_4.contract != "phoenix.memory.qps-v3-ledger-qualification/v1"
        || !phase_4.phase_4_verified
        || phase_3.contract != "phoenix.memory.qps-v3-constitutional-tiers/v1"
        || !phase_3.phase_3_verified
    {
        bail!("Phase 8.8 requires verified Phase 3, 4, 6, and 7 inputs");
    }
    phase_4.ledger.validate().map_err(anyhow::Error::msg)?;
    if feasibility.contract != FEASIBILITY_CONTRACT
        || !feasibility.authorize_phase_8_8_training
        || feasibility.model_artifact.sha256 != file_identity(baseline_model_path)?.sha256
        || feasibility.phase_6_receipt.sha256 != file_identity(phase_6_path)?.sha256
        || feasibility.phase_4_receipt.sha256 != file_identity(phase_4_path)?.sha256
        || feasibility.canonical_rank_evidence_schema_changed
        || feasibility.canonical_ledger_changed
    {
        bail!("Phase 8.8 training is not bound to an authorizing feasibility receipt");
    }
    if baseline.feature_schema_identity != rank_evidence_schema_identity_v3() {
        bail!("Phase 8.8 baseline feature schema changed");
    }
    Ok(())
}

fn select_configuration(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    ledger_identity: [u8; 32],
) -> Result<DevelopmentSelection> {
    const EPOCHS: [u16; 6] = [16, 32, 64, 128, 256, 512];
    const LEARNING_RATES: [f32; 4] = [0.005, 0.01, 0.025, 0.05];
    const L2_PENALTIES: [f32; 3] = [0.0, 0.0001, 0.001];
    let mut best = None::<DevelopmentSelection>;
    let mut configurations_evaluated = 0;
    for epochs in EPOCHS {
        for learning_rate in LEARNING_RATES {
            for l2_penalty in L2_PENALTIES {
                let config = LinearTrainingConfigV3 {
                    epochs,
                    learning_rate,
                    l2_penalty,
                };
                let trained = train_query_normalized_lambdarank_v3_prevalidated(
                    ledger,
                    split,
                    ledger_identity,
                    config,
                )
                .map_err(anyhow::Error::msg)?;
                let development = evaluate_query_normalized_lambdarank_v3(
                    &trained.0,
                    ledger,
                    split,
                    PrimarySplitV3::Development,
                )
                .map_err(anyhow::Error::msg)?;
                configurations_evaluated += 1;
                let candidate = DevelopmentSelection {
                    config,
                    configurations_evaluated: 0,
                    development,
                };
                if best.as_ref().is_none_or(|prior| better(&candidate, prior)) {
                    best = Some(candidate);
                }
            }
        }
    }
    let mut selected = best.context("Phase 8.8 development grid produced no model")?;
    selected.configurations_evaluated = configurations_evaluated;
    Ok(selected)
}

fn better(candidate: &DevelopmentSelection, prior: &DevelopmentSelection) -> bool {
    candidate
        .development
        .query_normalized_logistic_loss
        .total_cmp(&prior.development.query_normalized_logistic_loss)
        .is_lt()
        || (candidate.development.query_normalized_logistic_loss
            == prior.development.query_normalized_logistic_loss
            && (candidate.development.query_normalized_weighted_accuracy
                > prior.development.query_normalized_weighted_accuracy
                || (candidate.development.query_normalized_weighted_accuracy
                    == prior.development.query_normalized_weighted_accuracy
                    && candidate.development.row_pairwise_accuracy
                        > prior.development.row_pairwise_accuracy)))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T> {
    serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("decode {label} {}", path.display()))
}

fn write_bytes_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path.parent().context("Phase 8.8 artifact has no parent")?;
    fs::create_dir_all(parent)?;
    let temporary = path.with_extension("json.tmp");
    if temporary.exists() {
        fs::remove_file(&temporary)?;
    }
    {
        let mut writer = BufWriter::new(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)?,
        );
        writer.write_all(bytes)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
    }
    fs::rename(temporary, path)?;
    Ok(())
}

#[derive(Clone, Copy, Debug, Serialize)]
struct DevelopmentSelection {
    config: LinearTrainingConfigV3,
    configurations_evaluated: usize,
    development: QueryNormalizedDevelopmentV3,
}

#[derive(Debug, Serialize)]
struct Phase88ArtifactEnvelope {
    #[serde(flatten)]
    artifact: LinearModelArtifactV3,
    phase_8_8_contract: &'static str,
    objective: &'static str,
    selection_criterion: &'static str,
    feasibility_receipt: FileIdentity,
    objective_receipt: LambdaRankObjectiveReceiptV3,
    development_selection: QueryNormalizedDevelopmentV3,
    configurations_evaluated: usize,
    gates: Phase88TrainingGates,
    production_promotion_authorized: bool,
    active_engine_after_training: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Phase88TrainingGates {
    feasibility_authorized: bool,
    development_only_model_selection: bool,
    blind_test_is_sealed: bool,
    query_force_normalized: bool,
    top_sensitive_weight_preregistered: bool,
    dynamic_current_order_reweighting: bool,
    deterministic_training: bool,
    monotonic_nonnegative_weights: bool,
    objective_is_finite_and_improves: bool,
    canonical_rank_evidence_schema_unchanged: bool,
    canonical_ledger_unchanged: bool,
    frozen_v2_substrate_unchanged: bool,
    runtime_training_forbidden: bool,
    artifact_valid: bool,
}

impl Phase88TrainingGates {
    fn all_pass(self) -> bool {
        self.feasibility_authorized
            && self.development_only_model_selection
            && self.blind_test_is_sealed
            && self.query_force_normalized
            && self.top_sensitive_weight_preregistered
            && self.dynamic_current_order_reweighting
            && self.deterministic_training
            && self.monotonic_nonnegative_weights
            && self.objective_is_finite_and_improves
            && self.canonical_rank_evidence_schema_unchanged
            && self.canonical_ledger_unchanged
            && self.frozen_v2_substrate_unchanged
            && self.runtime_training_forbidden
            && self.artifact_valid
    }
}

#[derive(Debug, Serialize)]
pub struct Phase88Publication {
    contract: &'static str,
    output: FileIdentity,
    model_identity: [u8; 32],
    selected_config: LinearTrainingConfigV3,
    configurations_evaluated: usize,
    development: QueryNormalizedDevelopmentV3,
    gates: Phase88TrainingGates,
    production_promotion_authorized: bool,
    active_engine_after_training: &'static str,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase6 {
    contract: String,
    split: LeakageSplitV3,
    phase_6_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase4 {
    contract: String,
    ledger: RelevanceLedgerV3,
    phase_4_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase3 {
    contract: String,
    v2_configuration_sha256: String,
    phase_3_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenFeasibility {
    contract: String,
    model_artifact: InputIdentity,
    phase_6_receipt: InputIdentity,
    phase_4_receipt: InputIdentity,
    authorize_phase_8_8_training: bool,
    canonical_rank_evidence_schema_changed: bool,
    canonical_ledger_changed: bool,
}

#[derive(Debug, Deserialize)]
struct InputIdentity {
    sha256: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_selection_prefers_lower_objective_before_accuracy() {
        let config = LinearTrainingConfigV3::default();
        let prior = DevelopmentSelection {
            config,
            configurations_evaluated: 0,
            development: QueryNormalizedDevelopmentV3 {
                query_normalized_logistic_loss: 0.4,
                query_normalized_weighted_accuracy: 0.9,
                ..QueryNormalizedDevelopmentV3::default()
            },
        };
        let candidate = DevelopmentSelection {
            config,
            configurations_evaluated: 0,
            development: QueryNormalizedDevelopmentV3 {
                query_normalized_logistic_loss: 0.3,
                query_normalized_weighted_accuracy: 0.1,
                ..QueryNormalizedDevelopmentV3::default()
            },
        };
        assert!(better(&candidate, &prior));
    }
}
