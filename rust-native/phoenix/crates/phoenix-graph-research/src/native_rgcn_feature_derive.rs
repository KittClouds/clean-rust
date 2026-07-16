use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use serde::Serialize;

use crate::{
    FrozenDecisionRecord, FrozenDecisionTrajectoryTables, GraphDecisionSplit,
    NativeRgcnDerivedFeatureRow, NativeRgcnFeatureAblation, NativeRgcnFeatureAblationSuite,
    NativeRgcnFeatureAuthorityRow, NativeRgcnFeatureCertificate, NativeRgcnFeatureDerivationPolicy,
    NativeRgcnFeatureError, NativeRgcnFeatureFamily, NativeRgcnFeatureLeakageAudit,
    NativeRgcnFeatureSnapshot, NativeRgcnMultitaskLaunchGate, NATIVE_RGCN_FEATURE_DIM,
    NATIVE_RGCN_FEATURE_SCALE, NATIVE_RGCN_FEATURE_SCHEMA,
};

pub fn derive_native_rgcn_features(
    tables: &FrozenDecisionTrajectoryTables,
    source_trajectory_dataset_id: impl Into<CompactString>,
    authority_rows: &[NativeRgcnFeatureAuthorityRow],
    policy: NativeRgcnFeatureDerivationPolicy,
) -> Result<NativeRgcnFeatureSnapshot, NativeRgcnFeatureError> {
    validate_policy(&policy)?;
    if !tables.provenance.leakage_certificate.passes() || tables.decisions.is_empty() {
        return Err(NativeRgcnFeatureError::InvalidInput("trajectory authority"));
    }
    let source_trajectory_dataset_id = source_trajectory_dataset_id.into();
    if source_trajectory_dataset_id.trim().is_empty() {
        return Err(NativeRgcnFeatureError::InvalidInput(
            "trajectory dataset identity",
        ));
    }
    let indexed = index_authority_rows(authority_rows)?;
    let mut rows = Vec::with_capacity(tables.candidate_actions.len());
    let mut topologies = HashSet::new();
    for (decision_ordinal, decision) in tables.decisions.iter().enumerate() {
        for local in 0..decision.candidate_actions.length as usize {
            let candidate_ordinal = decision.candidate_actions.offset as usize + local;
            let candidate = tables
                .candidate_actions
                .get(candidate_ordinal)
                .ok_or(NativeRgcnFeatureError::InvalidInput("candidate range"))?;
            let authority = indexed
                .get(&(
                    decision.decision_id.as_str(),
                    candidate.action_identity.as_str(),
                ))
                .ok_or(NativeRgcnFeatureError::InvalidInput(
                    "missing candidate authority row",
                ))?;
            validate_authority_row(tables, decision, authority)?;
            topologies.insert(authority.topology_identity.clone());
            rows.push(NativeRgcnDerivedFeatureRow {
                decision_ordinal: decision_ordinal as u64,
                candidate_ordinal: candidate_ordinal as u64,
                decision_id: decision.decision_id.clone(),
                candidate_action_identity: candidate.action_identity.clone(),
                split: decision.split,
                source_node: authority.source_node,
                target_node: authority.target_node,
                relation_type: authority.relation_type,
                features: quantize(authority, policy.temporal_cap_ms)?,
            });
        }
    }
    if rows.len() != authority_rows.len() || rows.len() != tables.candidate_actions.len() {
        return Err(NativeRgcnFeatureError::InvalidInput(
            "candidate authority coverage",
        ));
    }
    apply_ablation(&mut rows, &policy);
    let mut topology_identities = topologies.into_iter().collect::<Vec<_>>();
    topology_identities.sort_unstable();
    let sentinel_rejected = future_leak_sentinel(tables, authority_rows);
    let audit = NativeRgcnFeatureLeakageAudit {
        rows_checked: rows.len() as u64,
        candidate_coverage_basis_points: 10_000,
        future_authority_rows: 0,
        pre_state_identity_mismatches: 0,
        split_mismatches: 0,
        duplicate_candidate_rows: 0,
        cross_split_shuffle_moves: 0,
        future_leak_sentinel_rejected: sentinel_rejected,
        fit_free_transforms: true,
        label_free: true,
    };
    if !audit.passes() {
        return Err(NativeRgcnFeatureError::FutureLeak("future-leak sentinel"));
    }
    let mut snapshot = NativeRgcnFeatureSnapshot {
        schema_version: NATIVE_RGCN_FEATURE_SCHEMA.into(),
        derivation_id: "pending".into(),
        source_trajectory_dataset_id,
        topology_identities,
        policy,
        feature_contract: feature_contract(),
        audit,
        rows,
    };
    snapshot.derivation_id = content_id(&snapshot)?;
    Ok(snapshot)
}

pub fn derive_native_rgcn_feature_ablation_suite(
    tables: &FrozenDecisionTrajectoryTables,
    source_trajectory_dataset_id: impl Into<CompactString>,
    authority_rows: &[NativeRgcnFeatureAuthorityRow],
    feature_family: NativeRgcnFeatureFamily,
    shuffle_seed: u64,
) -> Result<NativeRgcnFeatureAblationSuite, NativeRgcnFeatureError> {
    let source = source_trajectory_dataset_id.into();
    let real = derive_native_rgcn_features(
        tables,
        source.clone(),
        authority_rows,
        NativeRgcnFeatureDerivationPolicy::real(feature_family),
    )?;
    let masked = derive_native_rgcn_features(
        tables,
        source.clone(),
        authority_rows,
        NativeRgcnFeatureDerivationPolicy::masked(feature_family),
    )?;
    let shuffled = derive_native_rgcn_features(
        tables,
        source,
        authority_rows,
        NativeRgcnFeatureDerivationPolicy::shuffled(feature_family, shuffle_seed),
    )?;
    let mut suite = NativeRgcnFeatureAblationSuite {
        suite_id: "pending".into(),
        feature_family,
        future_leak_sentinel_rejected: real.audit.future_leak_sentinel_rejected
            && masked.audit.future_leak_sentinel_rejected
            && shuffled.audit.future_leak_sentinel_rejected,
        real,
        masked,
        shuffled,
    };
    suite.suite_id = content_id(&suite)?;
    Ok(suite)
}

pub fn validate_native_rgcn_feature_snapshot(
    snapshot: &NativeRgcnFeatureSnapshot,
) -> Result<(), NativeRgcnFeatureError> {
    if snapshot.schema_version != NATIVE_RGCN_FEATURE_SCHEMA
        || snapshot.feature_contract.len() != NATIVE_RGCN_FEATURE_DIM
        || !snapshot.audit.passes()
        || snapshot.rows.is_empty()
        || snapshot.topology_identities.is_empty()
    {
        return Err(NativeRgcnFeatureError::InvalidInput("feature snapshot"));
    }
    let mut candidate = snapshot.clone();
    let expected = candidate.derivation_id.clone();
    candidate.derivation_id = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(NativeRgcnFeatureError::Identity("feature snapshot"));
    }
    Ok(())
}

pub fn certify_native_rgcn_multitask_launch_gate(
    baseline_ladder_id: Option<CompactString>,
    authoritative_task_count: u32,
    single_task_baselines_understood: bool,
    important_task_regression_limit_basis_points: u16,
) -> Result<NativeRgcnMultitaskLaunchGate, NativeRgcnFeatureError> {
    if important_task_regression_limit_basis_points > 10_000 {
        return Err(NativeRgcnFeatureError::InvalidInput("regression limit"));
    }
    let authorized = baseline_ladder_id
        .as_ref()
        .is_some_and(|identity| identity.starts_with("b3-"))
        && authoritative_task_count != 0
        && single_task_baselines_understood;
    let reason = if authorized {
        "single-task authority and baseline tribunal certified"
    } else {
        "locked: authoritative single-task baseline tribunal is incomplete"
    };
    let mut gate = NativeRgcnMultitaskLaunchGate {
        gate_id: "pending".into(),
        baseline_ladder_id,
        authoritative_task_count,
        single_task_baselines_understood,
        important_task_regression_limit_basis_points,
        authorized,
        reason: reason.into(),
    };
    gate.gate_id = content_id(&gate)?;
    Ok(gate)
}

pub fn require_native_rgcn_multitask_launch(
    gate: &NativeRgcnMultitaskLaunchGate,
) -> Result<(), NativeRgcnFeatureError> {
    let mut candidate = gate.clone();
    let expected = candidate.gate_id.clone();
    candidate.gate_id = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(NativeRgcnFeatureError::Identity("launch gate"));
    }
    if !gate.authorized {
        return Err(NativeRgcnFeatureError::MultiTaskLocked(
            "single-task baselines",
        ));
    }
    Ok(())
}

fn validate_policy(
    policy: &NativeRgcnFeatureDerivationPolicy,
) -> Result<(), NativeRgcnFeatureError> {
    if policy.fixed_scale != NATIVE_RGCN_FEATURE_SCALE
        || policy.temporal_cap_ms == 0
        || (policy.ablation == NativeRgcnFeatureAblation::Shuffled && policy.shuffle_seed.is_none())
        || (policy.ablation != NativeRgcnFeatureAblation::Shuffled && policy.shuffle_seed.is_some())
    {
        return Err(NativeRgcnFeatureError::InvalidInput("derivation policy"));
    }
    Ok(())
}

type AuthorityIndex<'a> = HashMap<(&'a str, &'a str), &'a NativeRgcnFeatureAuthorityRow>;

fn index_authority_rows(
    rows: &[NativeRgcnFeatureAuthorityRow],
) -> Result<AuthorityIndex<'_>, NativeRgcnFeatureError> {
    let mut indexed = HashMap::with_capacity(rows.len());
    for row in rows {
        if row.decision_id.trim().is_empty()
            || row.candidate_action_identity.trim().is_empty()
            || indexed
                .insert(
                    (
                        row.decision_id.as_str(),
                        row.candidate_action_identity.as_str(),
                    ),
                    row,
                )
                .is_some()
        {
            return Err(NativeRgcnFeatureError::InvalidInput(
                "duplicate or empty authority row",
            ));
        }
    }
    Ok(indexed)
}

fn validate_authority_row(
    tables: &FrozenDecisionTrajectoryTables,
    decision: &FrozenDecisionRecord,
    row: &NativeRgcnFeatureAuthorityRow,
) -> Result<(), NativeRgcnFeatureError> {
    if row.available_through > decision.observation_cutoff
        || row.topology_fit_split != GraphDecisionSplit::Train
        || row.topology_fit_through > decision.observation_cutoff
        || row
            .raw
            .latest_visible_fact_at
            .is_some_and(|value| value > decision.observation_cutoff)
        || row
            .raw
            .prior_visible_fact_at
            .is_some_and(|value| value > decision.observation_cutoff)
    {
        return Err(NativeRgcnFeatureError::FutureLeak(
            "authority available after observation cutoff",
        ));
    }
    let state = tables
        .states
        .get(decision.state_ordinal as usize)
        .ok_or(NativeRgcnFeatureError::InvalidInput("state ordinal"))?;
    let mut receipts = HashSet::with_capacity(row.source_receipt_ids.len());
    if row.decision_id != decision.decision_id
        || row.split != decision.split
        || row.observation_cutoff != decision.observation_cutoff
        || row.pre_state_snapshot_id != state.pre_state_snapshot_id
        || row.topology_identity.trim().is_empty()
        || row.authority_id.trim().is_empty()
        || row.source_receipt_ids.is_empty()
        || row
            .source_receipt_ids
            .iter()
            .any(|value| value.trim().is_empty() || !receipts.insert(value))
        || row.raw.typed_neighbor_overlap_basis_points > 10_000
        || row.raw.qualifier_role_diversity > row.raw.qualifier_incidence_count
        || row.raw.evidence_source_diversity > row.raw.evidence_count
        || row.raw.authority_class > 15
        || row.raw.confidence_class > 15
        || matches!(
            (
                row.raw.prior_visible_fact_at,
                row.raw.latest_visible_fact_at
            ),
            (Some(prior), Some(latest)) if prior > latest
        )
        || row
            .raw
            .latest_visible_fact_at
            .is_some_and(|value| value > row.available_through)
        || row
            .raw
            .prior_visible_fact_at
            .is_some_and(|value| value > row.available_through)
    {
        return Err(NativeRgcnFeatureError::InvalidInput(
            "authority row contract",
        ));
    }
    Ok(())
}

fn quantize(
    row: &NativeRgcnFeatureAuthorityRow,
    temporal_cap_ms: u64,
) -> Result<[i16; NATIVE_RGCN_FEATURE_DIM], NativeRgcnFeatureError> {
    let raw = &row.raw;
    let age = row
        .observation_cutoff
        .saturating_sub(raw.latest_visible_fact_at.unwrap_or(row.observation_cutoff));
    let gap = raw
        .latest_visible_fact_at
        .zip(raw.prior_visible_fact_at)
        .map_or(0, |(latest, prior)| latest.saturating_sub(prior));
    let values = [
        scale_count(raw.typed_in_degree),
        scale_count(raw.typed_out_degree),
        (raw.typed_neighbor_overlap_basis_points / 10) as i16,
        scale_count(raw.qualifier_incidence_count),
        scale_count(raw.qualifier_role_diversity),
        scale_duration(age, temporal_cap_ms)?,
        scale_duration(gap, temporal_cap_ms)?,
        scale_count(raw.evidence_source_diversity),
        scale_count(raw.evidence_count),
        scale_count(raw.revision_depth),
        scale_count(raw.visible_episode_memberships),
        scale_count(raw.prior_accepted_proposals),
        scale_count(raw.prior_rejected_proposals),
        ((raw.discrepancy_state.ordinal() * 1_000) / 7) as i16,
        ((u32::from(raw.authority_class) * 1_000) / 15) as i16,
        ((u32::from(raw.confidence_class) * 1_000) / 15) as i16,
    ];
    Ok(values)
}

fn scale_count(value: u32) -> i16 {
    value.min(1_000) as i16
}

fn scale_duration(value: i64, cap_ms: u64) -> Result<i16, NativeRgcnFeatureError> {
    let value = u64::try_from(value)
        .map_err(|_| NativeRgcnFeatureError::FutureLeak("negative temporal delta"))?;
    Ok(((value.min(cap_ms) * 1_000) / cap_ms) as i16)
}

fn apply_ablation(
    rows: &mut [NativeRgcnDerivedFeatureRow],
    policy: &NativeRgcnFeatureDerivationPolicy,
) {
    let (start, end) = policy.feature_family.columns();
    match policy.ablation {
        NativeRgcnFeatureAblation::Real => {}
        NativeRgcnFeatureAblation::Masked => rows.iter_mut().for_each(|row| {
            row.features[start..end].fill(0);
        }),
        NativeRgcnFeatureAblation::Shuffled => {
            let seed = policy.shuffle_seed.expect("validated shuffle seed");
            for split in [
                GraphDecisionSplit::Train,
                GraphDecisionSplit::Validation,
                GraphDecisionSplit::Test,
            ] {
                let indices = rows
                    .iter()
                    .enumerate()
                    .filter_map(|(index, row)| (row.split == split).then_some(index))
                    .collect::<Vec<_>>();
                let mut donors = indices.clone();
                deterministic_shuffle(&mut donors, seed ^ u64::from(split as u8));
                let values = donors
                    .iter()
                    .map(|&index| rows[index].features[start..end].to_vec())
                    .collect::<Vec<_>>();
                for (&target, value) in indices.iter().zip(values) {
                    rows[target].features[start..end].copy_from_slice(&value);
                }
            }
        }
    }
}

fn deterministic_shuffle(values: &mut [usize], seed: u64) {
    let mut random = SplitMix64(seed);
    for end in (1..values.len()).rev() {
        let selected = (random.next() as usize) % (end + 1);
        values.swap(end, selected);
    }
}

fn future_leak_sentinel(
    tables: &FrozenDecisionTrajectoryTables,
    rows: &[NativeRgcnFeatureAuthorityRow],
) -> bool {
    let Some(source) = rows.first() else {
        return false;
    };
    let Some(decision) = tables
        .decisions
        .iter()
        .find(|decision| decision.decision_id == source.decision_id)
    else {
        return false;
    };
    let mut sentinel = source.clone();
    sentinel.available_through = decision.observation_cutoff.saturating_add(1);
    matches!(
        validate_authority_row(tables, decision, &sentinel),
        Err(NativeRgcnFeatureError::FutureLeak(_))
    )
}

fn feature_contract() -> Vec<NativeRgcnFeatureCertificate> {
    let columns = [
        (
            "typed_in_degree",
            NativeRgcnFeatureFamily::TypedAdjacency,
            "clamp_count_1000",
        ),
        (
            "typed_out_degree",
            NativeRgcnFeatureFamily::TypedAdjacency,
            "clamp_count_1000",
        ),
        (
            "typed_neighbor_overlap",
            NativeRgcnFeatureFamily::TypedAdjacency,
            "basis_points_div_10",
        ),
        (
            "qualifier_incidence_count",
            NativeRgcnFeatureFamily::QualifierIncidence,
            "clamp_count_1000",
        ),
        (
            "qualifier_role_diversity",
            NativeRgcnFeatureFamily::QualifierIncidence,
            "clamp_count_1000",
        ),
        (
            "temporal_age",
            NativeRgcnFeatureFamily::TemporalHistory,
            "fixed_cap_ratio",
        ),
        (
            "temporal_gap",
            NativeRgcnFeatureFamily::TemporalHistory,
            "fixed_cap_ratio",
        ),
        (
            "evidence_source_diversity",
            NativeRgcnFeatureFamily::Evidence,
            "clamp_count_1000",
        ),
        (
            "evidence_count",
            NativeRgcnFeatureFamily::Evidence,
            "clamp_count_1000",
        ),
        (
            "revision_depth",
            NativeRgcnFeatureFamily::RevisionStructure,
            "clamp_count_1000",
        ),
        (
            "visible_episode_memberships",
            NativeRgcnFeatureFamily::EpisodeMembership,
            "clamp_count_1000",
        ),
        (
            "prior_accepted_proposals",
            NativeRgcnFeatureFamily::ProposalHistory,
            "clamp_count_1000",
        ),
        (
            "prior_rejected_proposals",
            NativeRgcnFeatureFamily::ProposalHistory,
            "clamp_count_1000",
        ),
        (
            "discrepancy_state",
            NativeRgcnFeatureFamily::DiscrepancyState,
            "closed_enum_ratio",
        ),
        (
            "authority_class",
            NativeRgcnFeatureFamily::AuthorityConfidence,
            "closed_class_ratio",
        ),
        (
            "confidence_class",
            NativeRgcnFeatureFamily::AuthorityConfidence,
            "closed_class_ratio",
        ),
    ];
    columns
        .into_iter()
        .enumerate()
        .map(
            |(column, (name, family, transform))| NativeRgcnFeatureCertificate {
                column: column as u16,
                name: name.into(),
                family,
                dtype: "i16".into(),
                transform: transform.into(),
                fixed_scale: NATIVE_RGCN_FEATURE_SCALE,
                available_at_rule: "source_available_through<=observation_cutoff".into(),
                label_free: true,
            },
        )
        .collect()
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeRgcnFeatureError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
