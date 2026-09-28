use std::io::Write;

use hashbrown::HashMap;
use rdc_experiment_004::Choice;

use crate::{
    domain::{FeatureVector, PublicFrame},
    episodes::Episode,
    evaluation::{EvalLabel, query_utility},
    inspection::{InspectionOutcome, InspectionResult, InspectionSourceStore},
};

#[derive(Clone, Debug)]
pub struct FrozenDomainTable {
    scores_milli: [i32; 8],
    examples: [u32; 8],
    gains: [u32; 8],
    harms: [u32; 8],
}

impl FrozenDomainTable {
    pub fn load_csv(path: impl AsRef<std::path::Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let text = std::fs::read_to_string(path)?;
        let mut lines = text.lines();
        if lines.next()
            != Some(
                "inspection_domain,development_examples,wrong_to_right,right_to_wrong,expected_net_benefit_milli",
            )
        {
            return Err("E005 domain table header mismatch".into());
        }
        let mut scores_milli = [0i32; 8];
        let mut examples = [0u32; 8];
        let mut gains = [0u32; 8];
        let mut harms = [0u32; 8];
        let mut seen = [false; 8];
        for line in lines {
            let mut fields = line.split(',');
            let domain: usize = fields.next().ok_or("E005 row missing domain")?.parse()?;
            if domain >= 8 || seen[domain] {
                return Err("E005 domain row out of range or duplicated".into());
            }
            examples[domain] = fields.next().ok_or("E005 row missing examples")?.parse()?;
            gains[domain] = fields.next().ok_or("E005 row missing gains")?.parse()?;
            harms[domain] = fields.next().ok_or("E005 row missing harms")?.parse()?;
            scores_milli[domain] = fields.next().ok_or("E005 row missing estimate")?.parse()?;
            if fields.next().is_some() {
                return Err("E005 row has extra fields".into());
            }
            if examples[domain] == 0
                || scores_milli[domain]
                    != (gains[domain] as i32 - harms[domain] as i32) * 1000
                        / examples[domain] as i32
            {
                return Err("E005 table estimate does not match its counts".into());
            }
            seen[domain] = true;
        }
        if seen.iter().any(|value| !value) {
            return Err("E005 table must contain all eight domains".into());
        }
        Ok(Self {
            scores_milli,
            examples,
            gains,
            harms,
        })
    }

    pub fn score_milli(&self, domain: u8) -> i32 {
        self.scores_milli.get(domain as usize).copied().unwrap_or(0)
    }

    pub fn score(&self, domain: u8) -> f32 {
        self.score_milli(domain) as f32 / 1000.0
    }

    pub fn row(&self, domain: usize) -> Option<(u32, u32, u32, i32)> {
        Some((
            *self.examples.get(domain)?,
            *self.gains.get(domain)?,
            *self.harms.get(domain)?,
            *self.scores_milli.get(domain)?,
        ))
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct DomainEstimate {
    pub examples: u32,
    pub net_sum: i32,
    pub squared_sum: u32,
    pub mean: f32,
    pub uncertainty: f32,
    pub lower_value: f32,
}

#[derive(Clone, Debug)]
pub struct SmoothedValueModel {
    domains: [DomainEstimate; 12],
    prior_strength: f32,
}

impl SmoothedValueModel {
    pub fn fit(
        episodes: &[Episode],
        labels: &[EvalLabel],
        sources: &InspectionSourceStore,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        if episodes.len() != labels.len() {
            return Err("smoothing training episode/label count differs".into());
        }
        let by_id = labels
            .iter()
            .map(|label| (label.episode_id, *label))
            .collect::<HashMap<_, _>>();
        let mut domains = [DomainEstimate::default(); 12];
        for episode in episodes {
            let label = by_id.get(&episode.id).ok_or("smoothing label missing")?;
            let source = sources.get(episode.id).ok_or("smoothing source missing")?;
            let active = episode.frame.features.primary_action;
            let inspected = InspectionResult::classify(active, source.reply);
            let utility = query_utility(active, inspected.proposed_action, label.correct_action);
            let estimate = domains
                .get_mut(episode.domain as usize)
                .ok_or("smoothing domain outside fixed table")?;
            estimate.examples += 1;
            estimate.net_sum += utility as i32;
            estimate.squared_sum += (utility as i32 * utility as i32) as u32;
        }
        let prior_strength = 8.0;
        for estimate in &mut domains {
            if estimate.examples == 0 {
                continue;
            }
            let n = estimate.examples as f32;
            let posterior_n = n + prior_strength;
            estimate.mean = estimate.net_sum as f32 / posterior_n;
            let centered = estimate.squared_sum as f32 + prior_strength
                - estimate.net_sum as f32 * estimate.net_sum as f32 / posterior_n;
            estimate.uncertainty = (centered.max(0.0) / (posterior_n * posterior_n)).sqrt();
            estimate.lower_value = estimate.mean - 0.5 * estimate.uncertainty;
        }
        Ok(Self {
            domains,
            prior_strength,
        })
    }

    pub fn estimate(&self, domain: u8) -> DomainEstimate {
        self.domains
            .get(domain as usize)
            .copied()
            .unwrap_or_default()
    }

    pub fn score(&self, domain: u8) -> f32 {
        self.estimate(domain).lower_value
    }

    pub fn prior_strength(&self) -> f32 {
        self.prior_strength
    }

    pub fn write_csv(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = std::io::BufWriter::new(std::fs::File::create(path)?);
        writeln!(
            writer,
            "domain,development_examples,net_sum,mean,uncertainty,conservative_value,prior_strength"
        )?;
        for (domain, estimate) in self.domains.iter().enumerate() {
            writeln!(
                writer,
                "{domain},{},{},{:.6},{:.6},{:.6},{:.1}",
                estimate.examples,
                estimate.net_sum,
                estimate.mean,
                estimate.uncertainty,
                estimate.lower_value,
                self.prior_strength
            )?;
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct FeatureValueModel {
    weights: [f32; 8],
}

impl FeatureValueModel {
    pub fn fit(
        episodes: &[Episode],
        labels: &[EvalLabel],
        sources: &InspectionSourceStore,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        if episodes.len() != labels.len() {
            return Err("feature training episode/label count differs".into());
        }
        let by_id = labels
            .iter()
            .map(|label| (label.episode_id, *label))
            .collect::<HashMap<_, _>>();
        let mut examples = Vec::with_capacity(episodes.len());
        for episode in episodes {
            let label = by_id.get(&episode.id).ok_or("feature label missing")?;
            let source = sources.get(episode.id).ok_or("feature source missing")?;
            let active = episode.frame.features.primary_action;
            let result = InspectionResult::classify(active, source.reply);
            let utility =
                query_utility(active, result.proposed_action, label.correct_action) as f32;
            examples.push((
                FeatureVector::from_public(episode.frame, episode.confidence).0,
                utility,
            ));
        }
        let mut weights = [0.0f32; 8];
        let learning_rate = 0.12;
        let l2 = 0.01;
        for _ in 0..1800 {
            let mut gradient = [0.0f32; 8];
            for (features, target) in &examples {
                let error = dot8(&weights, features) - target;
                for index in 0..weights.len() {
                    gradient[index] += error * features[index];
                }
            }
            let scale = 2.0 / examples.len().max(1) as f32;
            for index in 0..weights.len() {
                weights[index] -= learning_rate * (scale * gradient[index] + l2 * weights[index]);
            }
        }
        Ok(Self { weights })
    }

    pub fn score(&self, frame: PublicFrame, confidence: u16) -> f32 {
        dot8(
            &self.weights,
            &FeatureVector::from_public(frame, confidence).0,
        )
    }

    pub fn weights(&self) -> &[f32; 8] {
        &self.weights
    }

    pub fn write_csv(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = std::io::BufWriter::new(std::fs::File::create(path)?);
        writeln!(writer, "feature,weight")?;
        for (name, value) in [
            "bias",
            "observer_disagreement",
            "warning",
            "age",
            "confidence_gap",
            "revision_gap",
            "audit_selected",
            "stale_visible",
        ]
        .iter()
        .zip(self.weights)
        {
            writeln!(writer, "{name},{value:.8}")?;
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

pub fn label_outcome(active: Choice, resolver: Option<Choice>, correct: Choice) -> &'static str {
    match (active == correct, resolver == Some(correct)) {
        (false, true) => "wrong_to_right",
        (true, false) if resolver.is_some() => "right_to_wrong",
        (true, true) => "both_right",
        (false, false) if resolver.is_some() => "both_wrong",
        (true, false) => "unresolved_active_right",
        (false, false) => "unresolved_active_wrong",
    }
}

pub fn outcome_code(outcome: InspectionOutcome) -> u8 {
    outcome as u8
}

#[cfg(target_arch = "x86_64")]
fn dot8(weights: &[f32; 8], features: &[f32; 8]) -> f32 {
    if std::is_x86_feature_detected!("avx") {
        // SAFETY: AVX availability is checked at runtime and both arrays contain eight f32s.
        unsafe { dot8_avx(weights, features) }
    } else {
        dot8_scalar(weights, features)
    }
}

#[cfg(not(target_arch = "x86_64"))]
fn dot8(weights: &[f32; 8], features: &[f32; 8]) -> f32 {
    dot8_scalar(weights, features)
}

fn dot8_scalar(weights: &[f32; 8], features: &[f32; 8]) -> f32 {
    weights
        .iter()
        .zip(features)
        .map(|(weight, feature)| weight * feature)
        .sum()
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx")]
unsafe fn dot8_avx(weights: &[f32; 8], features: &[f32; 8]) -> f32 {
    use std::arch::x86_64::{_mm256_hadd_ps, _mm256_loadu_ps, _mm256_mul_ps, _mm256_storeu_ps};
    let w = unsafe { _mm256_loadu_ps(weights.as_ptr()) };
    let x = unsafe { _mm256_loadu_ps(features.as_ptr()) };
    let product = _mm256_mul_ps(w, x);
    let pairs = _mm256_hadd_ps(product, product);
    let quads = _mm256_hadd_ps(pairs, pairs);
    let mut lanes = [0.0f32; 8];
    unsafe { _mm256_storeu_ps(lanes.as_mut_ptr(), quads) };
    lanes[0] + lanes[4]
}

#[cfg(test)]
mod tests {
    use super::{dot8, dot8_scalar};

    #[test]
    fn simd_dot_matches_scalar_on_feature_surface() {
        let weights = [0.25, -0.5, 0.75, 1.0, -1.25, 0.125, 0.625, -0.25];
        let features = [1.0, 0.0, 1.0, 0.5, 0.04, 1.0 / 3.0, 1.0, 0.5];
        assert!((dot8(&weights, &features) - dot8_scalar(&weights, &features)).abs() < 1e-6);
    }
}
