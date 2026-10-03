use std::collections::{BTreeMap, BTreeSet};

use northstar_rl_core::{Digest, identified, identity};

use crate::{
    Error, FeatureTransformState, PartitionRole, PartitionTape, Result, TRANSFORM_STATE_V1,
    TransformMethod, TransformState, role_episode_ids, validate_partition_identity,
};

#[derive(Clone, Debug)]
pub struct FeatureFitRow {
    pub episode_id: Digest,
    pub values: Vec<f64>,
}

pub fn fit_standard_score(
    source_feature_tape_id: Digest,
    ordered_feature_ids: &[String],
    partition: &PartitionTape,
    rows: &[FeatureFitRow],
    clip: Option<(f64, f64)>,
) -> Result<TransformState> {
    validate_partition_identity(partition)?;
    if ordered_feature_ids.is_empty() || rows.is_empty() {
        return Err(Error::Contract(
            "transform fit requires features and rows".into(),
        ));
    }
    if let Some((low, high)) = clip
        && (!low.is_finite() || !high.is_finite() || low >= high)
    {
        return Err(Error::Contract("invalid transform clip interval".into()));
    }
    let train_ids = role_episode_ids(partition, PartitionRole::Train)
        .into_iter()
        .collect::<BTreeSet<_>>();
    let mut moments = vec![Moments::default(); ordered_feature_ids.len()];
    let mut fitted_episodes = BTreeSet::new();
    for row in rows {
        if !train_ids.contains(&row.episode_id) {
            continue;
        }
        if row.values.len() != moments.len() {
            return Err(Error::Contract("transform row width mismatch".into()));
        }
        fitted_episodes.insert(row.episode_id);
        for (moment, &value) in moments.iter_mut().zip(&row.values) {
            if !value.is_finite() {
                return Err(Error::Contract("non-finite transform input".into()));
            }
            moment.push(value);
        }
    }
    if fitted_episodes != train_ids {
        return Err(Error::Contract(
            "transform fit rows do not cover the declared training episode set".into(),
        ));
    }
    let ordered_features = ordered_feature_ids
        .iter()
        .zip(moments)
        .map(|(feature_id, moment)| FeatureTransformState {
            feature_id: feature_id.clone(),
            method: TransformMethod::StandardScore,
            center: moment.mean,
            scale: moment.sample_std().max(f64::EPSILON),
            clip_low: clip.map(|value| value.0),
            clip_high: clip.map(|value| value.1),
            fitted_sample_count: moment.count,
            missingness_rule: "REJECT_NON_AVAILABLE_OR_NON_FINITE".into(),
        })
        .collect();
    let fitted_episode_set_hash = identity(b"northstar-transform-fit-episodes-v1", &train_ids)?;
    let implementation_hash = Digest::hash(
        b"northstar-transform-implementation-v1",
        include_bytes!("transform.rs"),
    );
    let mut state = TransformState {
        schema_version: TRANSFORM_STATE_V1.into(),
        transform_state_id: Digest::ZERO,
        source_feature_tape_id,
        partition_tape_id: partition.partition_tape_id,
        fit_role: PartitionRole::Train,
        fitted_episode_set_hash,
        ordered_features,
        numeric_contract: "f64_welford_fit_f32_observation_boundary".into(),
        implementation_hash,
        content_hash: Digest::ZERO,
    };
    state.content_hash = identity(b"northstar-transform-state-content-v1", &state)?;
    state = identified(b"northstar-transform-state-v1", state, |value, digest| {
        value.transform_state_id = digest;
    })?;
    Ok(state)
}

pub fn apply_transform(state: &TransformState, values: &[f64]) -> Result<Vec<f32>> {
    if values.len() != state.ordered_features.len() {
        return Err(Error::Contract("transform input width mismatch".into()));
    }
    values
        .iter()
        .zip(&state.ordered_features)
        .map(|(&value, feature)| {
            if !value.is_finite() || !feature.scale.is_finite() || feature.scale <= 0.0 {
                return Err(Error::Contract("invalid transform numeric state".into()));
            }
            let mut transformed = match feature.method {
                TransformMethod::Identity => value,
                TransformMethod::StandardScore | TransformMethod::RobustMedianIqr => {
                    (value - feature.center) / feature.scale
                }
            };
            if let Some(low) = feature.clip_low {
                transformed = transformed.max(low);
            }
            if let Some(high) = feature.clip_high {
                transformed = transformed.min(high);
            }
            let output = transformed as f32;
            if !output.is_finite() {
                return Err(Error::Contract("f64 to f32 transform overflow".into()));
            }
            Ok(output)
        })
        .collect()
}

#[derive(Clone, Copy, Default)]
struct Moments {
    count: u64,
    mean: f64,
    m2: f64,
}
impl Moments {
    fn push(&mut self, value: f64) {
        self.count += 1;
        let delta = value - self.mean;
        self.mean += delta / self.count as f64;
        self.m2 += delta * (value - self.mean);
    }
    fn sample_std(self) -> f64 {
        if self.count > 1 {
            (self.m2 / (self.count - 1) as f64).sqrt()
        } else {
            1.0
        }
    }
}

pub fn transform_dictionary(state: &TransformState) -> BTreeMap<String, usize> {
    state
        .ordered_features
        .iter()
        .enumerate()
        .map(|(index, feature)| (feature.feature_id.clone(), index))
        .collect()
}
