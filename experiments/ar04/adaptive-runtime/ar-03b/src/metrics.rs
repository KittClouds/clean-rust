use crate::model::TRAIN_SAMPLES;
use crate::partition::{STRATUM_COUNT, STRATUM_SIZE};
use crate::protocol::Candidate;

pub const PANEL_REPLICATES: usize = 64;
pub const PANEL_N_PER_STRATUM: usize = 4;
pub const PANEL_SALT: u64 = 0xa303_4252_5041_4e4c;
pub const EVIDENCE_N_PER_STRATUM: [usize; 6] = [1, 2, 3, 4, 6, 8];
const SIGN_EPSILON: f64 = 1.0e-8;

#[derive(Clone, Copy, Debug)]
pub struct ErrorPoint {
    pub examples: usize,
    pub within_stratum_variance: f64,
    pub predicted_rmse: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct PanelMetric {
    pub utility_rmse: f64,
    pub sign_error_rate: f64,
    pub cross_block_regret: f64,
    pub selected_program_regret: f64,
    pub false_authorization: bool,
}

#[derive(Clone, Debug)]
pub struct PanelRow {
    pub panel: usize,
    pub metric: PanelMetric,
}

#[derive(Clone, Copy, Debug)]
pub struct PanelMean {
    pub observed_rmse: f64,
    pub sign_error_rate: f64,
    pub cross_block_regret: f64,
    pub selected_program_regret: f64,
    pub false_authorization_rate: f64,
}

pub fn predicted_error_curve(
    ids: &[u8; TRAIN_SAMPLES],
    candidates: &[Candidate],
) -> Vec<ErrorPoint> {
    assert!(!candidates.is_empty());
    let members = stratum_members(ids);
    let mut result = Vec::with_capacity(EVIDENCE_N_PER_STRATUM.len());
    for n in EVIDENCE_N_PER_STRATUM {
        let mut within_sum = 0.0;
        let mut estimator_variance_sum = 0.0;
        for candidate in candidates {
            let utilities = &candidate.per_example_utility[0];
            let mut candidate_within = 0.0;
            let mut candidate_variance = 0.0;
            for group_members in &members {
                let mean = group_members
                    .iter()
                    .map(|&sample| f64::from(utilities[sample]))
                    .sum::<f64>()
                    / STRATUM_SIZE as f64;
                let sum_squares = group_members
                    .iter()
                    .map(|&sample| {
                        let difference = f64::from(utilities[sample]) - mean;
                        difference * difference
                    })
                    .sum::<f64>();
                let sample_variance = sum_squares / (STRATUM_SIZE - 1) as f64;
                candidate_within += sample_variance / STRATUM_COUNT as f64;
                let weight = 1.0 / STRATUM_COUNT as f64;
                candidate_variance +=
                    weight * weight * (1.0 - n as f64 / STRATUM_SIZE as f64) * sample_variance
                        / n as f64;
            }
            within_sum += candidate_within;
            estimator_variance_sum += candidate_variance;
        }
        let candidate_count = candidates.len() as f64;
        result.push(ErrorPoint {
            examples: STRATUM_COUNT * n,
            within_stratum_variance: within_sum / candidate_count,
            predicted_rmse: (estimator_variance_sum / candidate_count).sqrt(),
        });
    }
    result
}

pub fn audit_v48(
    ids: &[u8; TRAIN_SAMPLES],
    candidates: &[Candidate],
    stream_seed: u64,
    step: usize,
) -> (PanelMean, Vec<PanelRow>) {
    assert!(!candidates.is_empty());
    let members = stratum_members(ids);
    let block_count = candidates
        .iter()
        .map(|candidate| candidate.block)
        .max()
        .unwrap_or(0)
        + 1;
    let mut block_exact = vec![0.0_f64; block_count];
    let mut sign_trials = 0_usize;
    for candidate in candidates {
        block_exact[candidate.block] = block_exact[candidate.block].max(candidate.exact_utility[0]);
        sign_trials += usize::from(candidate.exact_utility[0].abs() > SIGN_EPSILON);
    }
    let exact_best = block_exact.iter().copied().fold(0.0_f64, f64::max);
    let mut rows = Vec::with_capacity(PANEL_REPLICATES);
    let mut squared_rmse = 0.0;
    let mut sign_error_sum = 0.0;
    let mut cross_regret_sum = 0.0;
    let mut selected_regret_sum = 0.0;
    let mut false_authorizations = 0_usize;

    for panel in 0..PANEL_REPLICATES {
        let seed = stream_seed
            ^ PANEL_SALT
            ^ (step as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)
            ^ (panel as u64).wrapping_mul(0xd6e8_feb8_6659_fd93);
        let order = panel_order(&members, seed);
        let mut estimates = Vec::with_capacity(candidates.len());
        let mut block_estimated = vec![0.0_f64; block_count];
        let mut block_choice = vec![None; block_count];
        let mut squared_error = 0.0;
        let mut sign_errors = 0_usize;

        for candidate in candidates {
            let utilities = &candidate.per_example_utility[0];
            let mut total = 0.0;
            for group_order in order.iter().take(STRATUM_COUNT) {
                let group_sum = group_order[..PANEL_N_PER_STRATUM]
                    .iter()
                    .map(|&sample| f64::from(utilities[sample]))
                    .sum::<f64>();
                total += group_sum / PANEL_N_PER_STRATUM as f64 / STRATUM_COUNT as f64;
            }
            let estimate = total;
            let exact = candidate.exact_utility[0];
            let difference = estimate - exact;
            squared_error += difference * difference;
            if exact.abs() > SIGN_EPSILON {
                sign_errors += usize::from((estimate > 0.0) != (exact > 0.0));
            }
            if estimate > block_estimated[candidate.block] {
                block_estimated[candidate.block] = estimate;
                block_choice[candidate.block] = Some(estimates.len());
            }
            estimates.push(estimate);
        }

        let mut selected_block = None;
        let mut selected_estimate = 0.0;
        for (block, &estimate) in block_estimated.iter().enumerate() {
            if estimate > selected_estimate && block_choice[block].is_some() {
                selected_estimate = estimate;
                selected_block = Some(block);
            }
        }
        let selected_index = selected_block.and_then(|block| block_choice[block]);
        let selected_utility =
            selected_index.map_or(0.0, |index| candidates[index].exact_utility[0]);
        let selected_block_exact = selected_block.map_or(0.0, |block| block_exact[block]);
        let metric = PanelMetric {
            utility_rmse: (squared_error / candidates.len() as f64).sqrt(),
            sign_error_rate: sign_errors as f64 / sign_trials.max(1) as f64,
            cross_block_regret: (exact_best - selected_block_exact).max(0.0),
            selected_program_regret: (exact_best - selected_utility).max(0.0),
            false_authorization: selected_index
                .is_some_and(|index| candidates[index].exact_utility[0] <= 0.0),
        };
        squared_rmse += metric.utility_rmse * metric.utility_rmse;
        sign_error_sum += metric.sign_error_rate;
        cross_regret_sum += metric.cross_block_regret;
        selected_regret_sum += metric.selected_program_regret;
        false_authorizations += usize::from(metric.false_authorization);
        rows.push(PanelRow { panel, metric });
    }

    let inverse = 1.0 / PANEL_REPLICATES as f64;
    (
        PanelMean {
            observed_rmse: (squared_rmse * inverse).sqrt(),
            sign_error_rate: sign_error_sum * inverse,
            cross_block_regret: cross_regret_sum * inverse,
            selected_program_regret: selected_regret_sum * inverse,
            false_authorization_rate: false_authorizations as f64 * inverse,
        },
        rows,
    )
}

fn stratum_members(ids: &[u8; TRAIN_SAMPLES]) -> [[usize; STRATUM_SIZE]; STRATUM_COUNT] {
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in ids.iter().enumerate() {
        let group = stratum as usize;
        assert!(group < STRATUM_COUNT);
        members[group][counts[group]] = sample;
        counts[group] += 1;
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    members
}

fn panel_order(
    members: &[[usize; STRATUM_SIZE]; STRATUM_COUNT],
    seed: u64,
) -> [[usize; STRATUM_SIZE]; STRATUM_COUNT] {
    let mut order = *members;
    let mut rng = PanelRng { state: seed };
    for group in &mut order {
        for offset in 0..STRATUM_SIZE {
            let selected = offset + rng.next() as usize % (STRATUM_SIZE - offset);
            group.swap(offset, selected);
        }
    }
    order
}

#[derive(Clone, Copy)]
struct PanelRng {
    state: u64,
}

impl PanelRng {
    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::partition::hash_placebo;

    #[test]
    fn predicted_rmse_is_monotone_and_zero_at_full_evidence() {
        let candidates: Vec<_> = (0..4)
            .map(|block| {
                let values: Vec<_> = (0..TRAIN_SAMPLES)
                    .map(|sample| (sample as f32 - 47.5) * 0.0001 + block as f32 * 0.0002)
                    .collect();
                Candidate {
                    block,
                    left_parameter: block,
                    right_parameter: block + 1,
                    left_rank: 0,
                    right_rank: 0,
                    left_delta: 0.005,
                    right_delta: -0.005,
                    exact_utility: [f64::from(values.iter().sum::<f32>() / TRAIN_SAMPLES as f32)],
                    per_example_utility: [values],
                }
            })
            .collect();
        let curve = predicted_error_curve(&hash_placebo(0), &candidates);
        assert_eq!(curve.len(), 6);
        assert!(
            curve
                .windows(2)
                .all(|pair| pair[0].predicted_rmse >= pair[1].predicted_rmse)
        );
        assert_eq!(curve.last().unwrap().predicted_rmse, 0.0);
    }
}
