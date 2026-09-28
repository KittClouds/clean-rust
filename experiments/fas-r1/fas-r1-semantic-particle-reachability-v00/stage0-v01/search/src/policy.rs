use crate::types::{Edit, ProposalMode};

#[derive(Clone, Copy, Debug)]
pub(crate) struct DeterministicRng {
    pub state: u64,
}

impl DeterministicRng {
    pub fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    pub fn bounded(&mut self, bound: u64) -> u64 {
        debug_assert!(bound > 0);
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return value % bound;
            }
        }
    }

    fn unit_f64(&mut self) -> f64 {
        let bits = self.next_u64() >> 11;
        (bits as f64) * (1.0 / ((1u64 << 53) as f64))
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct ProposalChoice {
    pub edit: Edit,
    pub log_probability: f32,
    pub logits_scored: u64,
}

pub(crate) fn propose(
    mode: ProposalMode,
    assignment: &[u8],
    latent: &[f32],
    n: u16,
    k: u8,
    rng: &mut DeterministicRng,
) -> Option<ProposalChoice> {
    let mut edits = Vec::with_capacity(usize::from(n).saturating_mul(usize::from(k)));
    let mut scores = Vec::with_capacity(edits.capacity());
    for entity in 0..n {
        let current = assignment[usize::from(entity)];
        for new_role in 0..k {
            if new_role == current {
                continue;
            }
            let edit = Edit { entity, new_role };
            edits.push(edit);
            if mode == ProposalMode::UniformRandomStub {
                scores.push(0.0f64);
            } else {
                scores.push(edit_score(edit, assignment, latent) as f64);
            }
        }
    }
    if edits.is_empty() {
        return None;
    }

    let count = edits.len() as u64;
    match mode {
        ProposalMode::GreedyLearnedStub => {
            let best = scores
                .iter()
                .enumerate()
                .max_by(|(ia, a), (ib, b)| a.total_cmp(b).then_with(|| ib.cmp(ia)))
                .map(|(index, _)| index)
                .unwrap_or(0);
            Some(ProposalChoice {
                edit: edits[best],
                log_probability: 0.0,
                logits_scored: count,
            })
        }
        ProposalMode::UniformRandomStub => {
            let index = rng.bounded(edits.len() as u64) as usize;
            Some(ProposalChoice {
                edit: edits[index],
                log_probability: -(edits.len() as f32).ln(),
                logits_scored: 0,
            })
        }
        ProposalMode::SampledLearnedStub => {
            let max_score = scores.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let mut weights = Vec::with_capacity(scores.len());
            let mut total = 0.0f64;
            for score in &scores {
                let weight = (score - max_score).exp();
                weights.push(weight);
                total += weight;
            }
            let draw = rng.unit_f64() * total;
            let mut cumulative = 0.0;
            let mut selected = weights.len() - 1;
            for (index, weight) in weights.iter().enumerate() {
                cumulative += weight;
                if draw < cumulative {
                    selected = index;
                    break;
                }
            }
            let probability = (weights[selected] / total) as f32;
            Some(ProposalChoice {
                edit: edits[selected],
                log_probability: probability.ln(),
                logits_scored: count,
            })
        }
    }
}

fn edit_score(edit: Edit, assignment: &[u8], latent: &[f32]) -> f32 {
    let entity = usize::from(edit.entity);
    let old_role = assignment[entity];
    let latent_signal = if latent.is_empty() {
        0.0
    } else {
        latent[(entity * 17 + usize::from(edit.new_role) * 13) % latent.len()]
    };
    let mix = (u64::from(edit.entity) + 1).wrapping_mul(0xD6E8_FEB8_6659_FD93)
        ^ (u64::from(edit.new_role) + 7).wrapping_mul(0xA076_1D64_78BD_642F)
        ^ (u64::from(old_role) + 19).wrapping_mul(0xE703_7ED1_A0B4_28DB);
    let hash_signal = ((mix >> 40) as i32 as f32) / (i32::MAX as f32);
    0.75 * latent_signal.tanh() + 0.25 * hash_signal
}

pub(crate) fn apply_edit(assignment: &mut [u8], edit: Edit) {
    assignment[usize::from(edit.entity)] = edit.new_role;
}

pub(crate) fn update_latent(latent: &mut [f32], edit: Edit, depth: u32) {
    if latent.is_empty() {
        return;
    }
    let index = usize::from(edit.entity) % latent.len();
    let role_index = (usize::from(edit.new_role) * 31 + index + 1) % latent.len();
    let depth_signal = ((depth % 97) as f32 - 48.0) / 48.0;
    latent[index] =
        (0.875 * latent[index] + 0.125 * (depth_signal + f32::from(edit.new_role))).tanh();
    latent[role_index] = (0.9 * latent[role_index] + 0.1 * (f32::from(edit.entity) + 1.0)).tanh();
}

/// A selector-only placeholder; it sees the explicit assignment, not clauses.
pub(crate) fn q_terminal_stub(assignment: &[u8], k: u8) -> f32 {
    if assignment.is_empty() || k == 0 {
        return 0.0;
    }
    let mut counts = vec![0u32; usize::from(k)];
    for &role in assignment {
        if let Some(count) = counts.get_mut(usize::from(role)) {
            *count += 1;
        }
    }
    let n = assignment.len() as f32;
    let mean = n / f32::from(k);
    let variance = counts
        .iter()
        .map(|&count| (count as f32 - mean).powi(2))
        .sum::<f32>()
        / f32::from(k);
    let balance = 1.0 / (1.0 + variance / (mean * mean + f32::EPSILON));
    0.15 + 0.7 * balance
}

/// A planning-only placeholder; its output is never used for terminal choice.
pub(crate) fn v_reach_stub(assignment: &[u8], latent: &[f32], remaining: u64, depth: u32) -> f32 {
    let future = remaining as f32 / (remaining as f32 + depth as f32 + 2.0);
    let assignment_spread = if assignment.len() < 2 {
        0.0
    } else {
        let transitions = assignment
            .windows(2)
            .filter(|pair| pair[0] != pair[1])
            .count();
        transitions as f32 / (assignment.len() - 1) as f32
    };
    let latent_energy = if latent.is_empty() {
        0.0
    } else {
        latent.iter().map(|v| v.abs()).sum::<f32>() / latent.len() as f32
    };
    (0.05 + 0.75 * future + 0.1 * assignment_spread + 0.1 * latent_energy).clamp(0.0, 1.0)
}

pub(crate) fn seed_mix(seed: u64, particle: u32) -> u64 {
    let mut rng =
        DeterministicRng::new(seed ^ u64::from(particle).wrapping_mul(0x9E37_79B9_7F4A_7C15));
    rng.next_u64()
}
