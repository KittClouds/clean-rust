use compact_str::{format_compact, CompactString};
use hashbrown::HashSet;
use serde::Serialize;

use crate::{
    require_native_rgcn_multitask_launch, NativeRgcnFeatureError, NativeRgcnMultitaskIdentity,
    NativeRgcnMultitaskLaunchGate, NativeRgcnMultitaskPromotionCertificate, NativeRgcnTaskHeadKind,
    NativeRgcnTaskPromotionEvidence, NATIVE_RGCN_FEATURE_DIM, NATIVE_RGCN_FEATURE_SCHEMA,
    NATIVE_RGCN_MULTITASK_SCHEMA,
};

const PROPAGATION_RULE: &str = "typed-normalized-sum+inverse+qualifier-incidence/relu/v1";

pub fn certify_native_rgcn_multitask_identity(
    gate: &NativeRgcnMultitaskLaunchGate,
    mut identity: NativeRgcnMultitaskIdentity,
) -> Result<NativeRgcnMultitaskIdentity, NativeRgcnFeatureError> {
    require_native_rgcn_multitask_launch(gate)?;
    if identity.schema_version != NATIVE_RGCN_MULTITASK_SCHEMA
        || identity.launch_gate_id != gate.gate_id
        || identity.task_set != NativeRgcnTaskHeadKind::ALL
        || identity.task_sampling_schedule.len() != NativeRgcnTaskHeadKind::ALL.len()
        || identity.loss_weights_micros.len() != NativeRgcnTaskHeadKind::ALL.len()
        || identity.head_architectures.len() != NativeRgcnTaskHeadKind::ALL.len()
        || identity.feature_schema_id != NATIVE_RGCN_FEATURE_SCHEMA
        || !is_blake3(identity.topology_identity.as_str())
        || !is_blake3(identity.optimizer_identity.as_str())
        || !is_blake3(identity.clipping_partition_identity.as_str())
        || identity.checkpoint_selection_rule.trim().is_empty()
        || identity.encoder_width as usize != NATIVE_RGCN_FEATURE_DIM
        || identity.encoder_layers != 1
        || identity.propagation_rule != PROPAGATION_RULE
        || identity
            .loss_weights_micros
            .iter()
            .all(|&weight| weight == 0)
    {
        return Err(NativeRgcnFeatureError::InvalidInput("multi-task identity"));
    }
    let mut scheduled = HashSet::with_capacity(NativeRgcnTaskHeadKind::ALL.len());
    if identity
        .task_sampling_schedule
        .iter()
        .any(|step| step.batches_per_cycle == 0 || !scheduled.insert(step.task))
        || identity
            .task_set
            .iter()
            .any(|task| !scheduled.contains(task))
    {
        return Err(NativeRgcnFeatureError::InvalidInput(
            "task sampling schedule",
        ));
    }
    for (expected, head) in NativeRgcnTaskHeadKind::ALL
        .into_iter()
        .zip(&identity.head_architectures)
    {
        if head.task != expected
            || head.input_features as usize != NATIVE_RGCN_FEATURE_DIM
            || head.hidden_features > NATIVE_RGCN_FEATURE_DIM as u16
            || head.output_features == 0
            || head.activation.trim().is_empty()
        {
            return Err(NativeRgcnFeatureError::InvalidInput(
                "task head architecture",
            ));
        }
    }
    identity.model_identity = "pending".into();
    identity.model_identity = content_id(&identity)?;
    Ok(identity)
}

pub fn validate_native_rgcn_multitask_identity(
    identity: &NativeRgcnMultitaskIdentity,
) -> Result<(), NativeRgcnFeatureError> {
    let mut candidate = identity.clone();
    let expected = candidate.model_identity.clone();
    candidate.model_identity = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(NativeRgcnFeatureError::Identity(
            "multi-task model identity",
        ));
    }
    Ok(())
}

pub fn certify_native_rgcn_multitask_promotion(
    identity: &NativeRgcnMultitaskIdentity,
    regression_limit_basis_points: u16,
    mut evidence: Vec<NativeRgcnTaskPromotionEvidence>,
) -> Result<NativeRgcnMultitaskPromotionCertificate, NativeRgcnFeatureError> {
    validate_native_rgcn_multitask_identity(identity)?;
    if regression_limit_basis_points > 10_000 || evidence.len() != NativeRgcnTaskHeadKind::ALL.len()
    {
        return Err(NativeRgcnFeatureError::InvalidInput("promotion evidence"));
    }
    evidence.sort_unstable_by_key(|row| task_ordinal(row.task));
    if evidence
        .iter()
        .zip(NativeRgcnTaskHeadKind::ALL)
        .any(|(row, expected)| row.task != expected || !row.passes(regression_limit_basis_points))
    {
        return Err(NativeRgcnFeatureError::MultiTaskLocked("promotion gate"));
    }
    let mut certificate = NativeRgcnMultitaskPromotionCertificate {
        certificate_id: "pending".into(),
        model_identity: identity.model_identity.clone(),
        important_task_regression_limit_basis_points: regression_limit_basis_points,
        head_evidence: evidence,
        promoted: true,
    };
    certificate.certificate_id = content_id(&certificate)?;
    Ok(certificate)
}

const fn task_ordinal(task: NativeRgcnTaskHeadKind) -> u8 {
    match task {
        NativeRgcnTaskHeadKind::EpisodeAssignment => 0,
        NativeRgcnTaskHeadKind::DeltaDisposition => 1,
        NativeRgcnTaskHeadKind::DiscrepancyClassifier => 2,
        NativeRgcnTaskHeadKind::EvidenceRanker => 3,
        NativeRgcnTaskHeadKind::RelationProposal => 4,
        NativeRgcnTaskHeadKind::RepairAction => 5,
    }
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeRgcnFeatureError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
