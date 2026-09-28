use std::io::Write;

use hashbrown::HashMap;

use crate::{
    domain::{PublicEpisode, WorldBank},
    evaluation::counterfactual_delta,
};

const PRIOR_STRENGTH: f32 = 24.0;
const EPOCHS: usize = 700;
const LEARNING_RATE: f32 = 0.018;
const L2: f32 = 0.008;

#[derive(Clone, Copy, Debug, Default)]
struct DomainStats {
    count: u32,
    sum: f32,
    sum_squares: f32,
}

#[derive(Clone, Debug)]
pub struct FrozenModels {
    domain_table: HashMap<u32, DomainStats>,
    smoothed_table: HashMap<u32, f32>,
    feature_weights: [f32; 8],
    global_mean: f32,
    development_episodes: usize,
}

impl FrozenModels {
    pub fn fit(development: &[WorldBank]) -> Result<Self, Box<dyn std::error::Error>> {
        let episode_count = development
            .iter()
            .map(|bank| bank.public.len())
            .sum::<usize>();
        if episode_count == 0 {
            return Err("cannot fit E007 routers on an empty development bank".into());
        }
        let mut domain_table = HashMap::<u32, DomainStats>::with_capacity(16);
        let mut records = Vec::with_capacity(episode_count);
        let mut global_sum = 0.0f32;
        for bank in development {
            if bank.public.len() != bank.hidden.len() {
                return Err("development public/source row count differs".into());
            }
            for (public, hidden) in bank.public.iter().zip(&bank.hidden) {
                if public.id != hidden.episode_id {
                    return Err("development public/source IDs differ".into());
                }
                let target =
                    counterfactual_delta(*public, hidden.reply, hidden.correct_action) as f32;
                let stats = domain_table.entry(public.domain_id).or_default();
                stats.count += 1;
                stats.sum += target;
                stats.sum_squares += target * target;
                global_sum += target;
                records.push((public.features(), target));
            }
        }
        let global_mean = global_sum / records.len() as f32;
        let mut smoothed_table = HashMap::with_capacity(domain_table.len());
        for (domain_id, stats) in &domain_table {
            let n = stats.count as f32;
            let posterior_n = n + PRIOR_STRENGTH;
            let posterior_mean = (stats.sum + global_mean * PRIOR_STRENGTH) / posterior_n;
            let raw_mean = stats.sum / n;
            let variance = (stats.sum_squares / n - raw_mean * raw_mean).max(0.0);
            let standard_error = (variance / posterior_n).sqrt();
            smoothed_table.insert(*domain_id, posterior_mean - 0.25 * standard_error);
        }
        let feature_weights = fit_feature_router(&records);
        Ok(Self {
            domain_table,
            smoothed_table,
            feature_weights,
            global_mean,
            development_episodes: records.len(),
        })
    }

    pub fn score_domain_table(&self, episode: PublicEpisode) -> f32 {
        self.domain_table
            .get(&episode.domain_id)
            .map_or(0.0, |stats| stats.sum / stats.count.max(1) as f32)
            / episode.query_cost_units.max(1) as f32
    }

    pub fn score_smoothed_table(&self, episode: PublicEpisode) -> f32 {
        self.smoothed_table
            .get(&episode.domain_id)
            .copied()
            .unwrap_or(0.0)
            / episode.query_cost_units.max(1) as f32
    }

    pub fn score_feature_router(&self, features: &[f32; 8], query_cost_units: u32) -> f32 {
        dot8(&self.feature_weights, features) / query_cost_units.max(1) as f32
    }

    pub fn feature_weights(&self) -> &[f32; 8] {
        &self.feature_weights
    }

    pub fn development_episodes(&self) -> usize {
        self.development_episodes
    }

    pub fn global_mean(&self) -> f32 {
        self.global_mean
    }

    pub fn write_csv(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = std::io::BufWriter::new(std::fs::File::create(path)?);
        writeln!(writer, "model,feature_or_domain,examples,estimate,weight")?;
        let mut domain_ids = self.domain_table.keys().copied().collect::<Vec<_>>();
        domain_ids.sort_unstable();
        for domain_id in domain_ids {
            let stats = self.domain_table[&domain_id];
            writeln!(
                writer,
                "domain_table,{domain_id},{},{:.8},",
                stats.count,
                stats.sum / stats.count as f32
            )?;
            writeln!(
                writer,
                "smoothed_table,{domain_id},{},{:.8},",
                stats.count, self.smoothed_table[&domain_id]
            )?;
        }
        for (name, weight) in [
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
        .zip(self.feature_weights)
        {
            writeln!(
                writer,
                "feature_router,{name},{},{:.8},{weight:.8}",
                self.development_episodes, self.global_mean
            )?;
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

fn fit_feature_router(records: &[([f32; 8], f32)]) -> [f32; 8] {
    let mut weights = [0.0f32; 8];
    let mut gradient = [0.0f32; 8];
    for _ in 0..EPOCHS {
        gradient.fill(0.0);
        for (features, target) in records {
            let error = dot8(&weights, features) - target;
            for index in 0..weights.len() {
                gradient[index] += error * features[index];
            }
        }
        let scale = 2.0 / records.len() as f32;
        for index in 0..weights.len() {
            weights[index] -= LEARNING_RATE * (scale * gradient[index] + L2 * weights[index]);
        }
    }
    weights
}

#[cfg(target_arch = "x86_64")]
fn dot8(weights: &[f32; 8], features: &[f32; 8]) -> f32 {
    if std::is_x86_feature_detected!("avx") {
        // SAFETY: AVX support is checked and both arrays contain eight f32 lanes.
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
    let left = unsafe { _mm256_loadu_ps(weights.as_ptr()) };
    let right = unsafe { _mm256_loadu_ps(features.as_ptr()) };
    let products = _mm256_mul_ps(left, right);
    let pairs = _mm256_hadd_ps(products, products);
    let quads = _mm256_hadd_ps(pairs, pairs);
    let mut lanes = [0.0; 8];
    unsafe { _mm256_storeu_ps(lanes.as_mut_ptr(), quads) };
    lanes[0] + lanes[4]
}

#[cfg(test)]
mod tests {
    use super::{dot8, dot8_scalar};

    #[test]
    fn simd_value_score_matches_scalar() {
        let weights = [0.25, -0.5, 0.75, 1.0, -1.25, 0.125, 0.625, -0.25];
        let features = [1.0, 0.0, 1.0, 0.5, 0.04, 1.0 / 3.0, 1.0, 0.5];
        assert!((dot8(&weights, &features) - dot8_scalar(&weights, &features)).abs() < 1e-6);
    }
}
