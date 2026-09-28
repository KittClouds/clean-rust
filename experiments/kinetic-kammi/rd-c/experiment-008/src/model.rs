use std::io::Write;

use crate::{
    domain::{Availability, PublicEpisode, SourceOffer, WorldBank},
    evaluation::outcome_components,
};

pub const E007_FROZEN_WEIGHTS: [f32; 8] = [
    -0.30954492,
    0.06822076,
    0.00490855,
    -0.02530932,
    -0.05317349,
    -0.02729626,
    0.033_387_2,
    0.033_848_1,
];
pub const FEATURE_COUNT: usize = 20;
const EPOCHS: usize = 180;
const LEARNING_RATE: f32 = 0.012;
const L2: f32 = 0.018;

#[derive(Clone, Copy, Debug, Default)]
pub struct ValueEstimate {
    pub wrong_to_right: f32,
    pub right_to_wrong: f32,
    pub unresolved_baseline_right: f32,
    pub avoided_wrong: f32,
}

impl ValueEstimate {
    pub fn delta(self) -> f32 {
        self.wrong_to_right - self.right_to_wrong - self.unresolved_baseline_right
    }
}

#[derive(Clone, Debug)]
pub struct FrozenModels {
    weights: [[f32; FEATURE_COUNT]; 4],
    pub development_episodes: usize,
    pub development_worlds: usize,
}

impl FrozenModels {
    pub fn fit(development: &[WorldBank]) -> Result<Self, Box<dyn std::error::Error>> {
        let n = development
            .iter()
            .map(|bank| bank.public.len())
            .sum::<usize>()
            * 3;
        if n == 0 {
            return Err("cannot fit E008 model without development examples".into());
        }
        let mut xs = Vec::with_capacity(n);
        let mut ys = Vec::with_capacity(n);
        for bank in development {
            if bank.public.len() != bank.hidden.len() || bank.public.len() != bank.offers.len() {
                return Err("development public, offer, and outcome rows differ".into());
            }
            for ((public, hidden), offers) in bank.public.iter().zip(&bank.hidden).zip(&bank.offers)
            {
                if public.id != hidden.episode_id || public.id != offers.episode_id {
                    return Err("development row IDs differ".into());
                }
                for source in 0..3 {
                    xs.push(features(public, offers.offers[source]));
                    ys.push(outcome_components(*public, *hidden, source));
                }
            }
        }
        let mut weights = [[0.0; FEATURE_COUNT]; 4];
        for target in 0..4 {
            let mut gradient = [0.0f32; FEATURE_COUNT];
            for _ in 0..EPOCHS {
                gradient.fill(0.0);
                for (x, y) in xs.iter().zip(&ys) {
                    let err = dot(&weights[target], x) - y[target];
                    for j in 0..FEATURE_COUNT {
                        gradient[j] += err * x[j];
                    }
                }
                let scale = 2.0 / xs.len() as f32;
                for j in 0..FEATURE_COUNT {
                    weights[target][j] -=
                        LEARNING_RATE * (scale * gradient[j] + L2 * weights[target][j]);
                }
            }
        }
        Ok(Self {
            weights,
            development_episodes: xs.len() / 3,
            development_worlds: development.len(),
        })
    }

    pub fn eight_feature_estimate(&self, public: PublicEpisode) -> f32 {
        dot8(&E007_FROZEN_WEIGHTS, &public.features())
    }

    pub fn simple_offer(&self, public: PublicEpisode, offer: SourceOffer) -> ValueEstimate {
        let f = public.features();
        let p_wrong = clamp(
            0.08 + 0.22 * f[1]
                + 0.15 * f[2]
                + 0.10 * f[3]
                + 0.12 * f[4]
                + 0.08 * f[5]
                + 0.05 * f[6],
            0.02,
            0.78,
        );
        let available = match offer.availability {
            Availability::Available => 1.0,
            Availability::Degraded => 0.62,
            Availability::Unavailable => 0.0,
        };
        let freshness = 1.0 - offer.source_local_age_bucket.min(3) as f32 / 3.0;
        let historical = offer.historical_reliability_bucket as f32 / 3.0;
        let independence = offer.independence_from_active_source as u8 as f32;
        let helpful = clamp(
            available * (0.13 + 0.36 * historical + 0.14 * independence + 0.08 * freshness),
            0.0,
            0.82,
        );
        let harmful = clamp(
            available * (0.08 + 0.12 * (1.0 - independence) + 0.12 * (1.0 - freshness)),
            0.0,
            0.52,
        );
        let unresolved = clamp(
            0.035
                + 0.11 * (offer.availability == Availability::Degraded) as u8 as f32
                + 0.04 * offer.source_local_age_bucket as f32 / 3.0,
            0.0,
            0.35,
        );
        ValueEstimate {
            wrong_to_right: p_wrong * helpful,
            right_to_wrong: (1.0 - p_wrong) * harmful,
            unresolved_baseline_right: (1.0 - p_wrong) * unresolved,
            avoided_wrong: p_wrong * unresolved,
        }
    }

    pub fn fitted_offer(&self, public: PublicEpisode, offer: SourceOffer) -> ValueEstimate {
        let x = features(&public, offer);
        let mut y = [0.0f32; 4];
        for (out, weights) in y.iter_mut().zip(&self.weights) {
            *out = clamp(dot(weights, &x), 0.0, 1.0);
        }
        ValueEstimate {
            wrong_to_right: y[0],
            right_to_wrong: y[1],
            unresolved_baseline_right: y[2],
            avoided_wrong: y[3],
        }
    }

    pub fn write_csv(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = std::io::BufWriter::with_capacity(16 * 1024, std::fs::File::create(path)?);
        writeln!(
            writer,
            "model,target,feature,weight,development_worlds,development_episodes"
        )?;
        let names = [
            "bias",
            "observer_disagreement",
            "warning",
            "age",
            "confidence_gap",
            "revision_gap",
            "audit_selected",
            "stale_visible",
            "source_0",
            "source_1",
            "source_2",
            "degraded",
            "unavailable",
            "offer_age",
            "independent",
            "historical_reliability",
            "quoted_price",
            "expiry",
            "price_x_independent",
            "reserved",
        ];
        let targets = [
            "wrong_to_right",
            "right_to_wrong",
            "unresolved_baseline_right",
            "avoided_wrong",
        ];
        for (target, weights) in targets.iter().zip(&self.weights) {
            for (name, weight) in names.iter().zip(weights) {
                writeln!(
                    writer,
                    "offer_fitted,{target},{name},{weight:.8},{},{}",
                    self.development_worlds, self.development_episodes
                )?;
            }
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
        .zip(E007_FROZEN_WEIGHTS)
        {
            writeln!(
                writer,
                "e007_frozen_positive_stop,completion_delta,{name},{weight:.8},{},{}",
                self.development_worlds, self.development_episodes
            )?;
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

pub fn features(public: &PublicEpisode, offer: SourceOffer) -> [f32; FEATURE_COUNT] {
    let mut x = [0.0f32; FEATURE_COUNT];
    x[..8].copy_from_slice(&public.features());
    x[8 + offer.source_id.min(2) as usize] = 1.0;
    x[11] = (offer.availability == Availability::Degraded) as u8 as f32;
    x[12] = (offer.availability == Availability::Unavailable) as u8 as f32;
    x[13] = offer.source_local_age_bucket.min(3) as f32 / 3.0;
    x[14] = offer.independence_from_active_source as u8 as f32;
    x[15] = offer.historical_reliability_bucket.min(3) as f32 / 3.0;
    x[16] = offer.quoted_query_price.min(32) as f32 / 32.0;
    x[17] = offer.offer_expiry.min(8) as f32 / 8.0;
    x[18] = x[14] * x[16];
    x[19] = (offer.version > 1) as u8 as f32;
    x
}

fn dot(weights: &[f32; FEATURE_COUNT], x: &[f32; FEATURE_COUNT]) -> f32 {
    let mut sum = dot8(
        &weights[..8].try_into().unwrap(),
        &x[..8].try_into().unwrap(),
    );
    for i in 8..FEATURE_COUNT {
        sum += weights[i] * x[i];
    }
    sum
}

#[cfg(target_arch = "x86_64")]
fn dot8(weights: &[f32; 8], x: &[f32; 8]) -> f32 {
    if std::is_x86_feature_detected!("avx2") {
        // SAFETY: AVX2 is checked and the inputs each contain eight valid f32 lanes.
        unsafe { dot8_avx2(weights, x) }
    } else {
        dot8_scalar(weights, x)
    }
}
#[cfg(not(target_arch = "x86_64"))]
fn dot8(weights: &[f32; 8], x: &[f32; 8]) -> f32 {
    dot8_scalar(weights, x)
}

fn dot8_scalar(weights: &[f32; 8], x: &[f32; 8]) -> f32 {
    weights.iter().zip(x).map(|(a, b)| a * b).sum()
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn dot8_avx2(weights: &[f32; 8], x: &[f32; 8]) -> f32 {
    use std::arch::x86_64::{_mm256_loadu_ps, _mm256_mul_ps, _mm256_storeu_ps};
    let a = unsafe { _mm256_loadu_ps(weights.as_ptr()) };
    let b = unsafe { _mm256_loadu_ps(x.as_ptr()) };
    let product = _mm256_mul_ps(a, b);
    let mut lanes = [0.0f32; 8];
    unsafe { _mm256_storeu_ps(lanes.as_mut_ptr(), product) };
    lanes.iter().sum()
}

fn clamp(value: f32, low: f32, high: f32) -> f32 {
    value.max(low).min(high)
}

#[cfg(test)]
mod tests {
    use super::{dot8, dot8_scalar};
    #[test]
    fn simd_dot_matches_scalar() {
        let a = [0.25, -0.5, 0.75, 1.0, -1.25, 0.125, 0.625, -0.25];
        let b = [1.0, 0.0, 1.0, 0.5, 0.04, 1.0 / 3.0, 1.0, 0.5];
        assert!((dot8(&a, &b) - dot8_scalar(&a, &b)).abs() < 1e-5);
    }
}
