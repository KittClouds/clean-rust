use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{Digest, Environment, Error, Result};

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "policy",
    content = "parameters",
    rename_all = "SCREAMING_SNAKE_CASE"
)]
pub enum ScriptedPolicy {
    AlwaysFlat,
    AlwaysFullPositive,
    AlwaysFullNegative,
    AlternateExtremes,
    FixedActionSequence(Vec<f32>),
    SeededRandomActions,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ReplayReceipt {
    pub episode_id: Digest,
    pub seed: u64,
    pub policy: ScriptedPolicy,
    pub action_count: u64,
    pub trajectory_root: Digest,
    pub terminal_receipt_hash: Digest,
}

pub fn run_scripted(
    environment: &mut Environment,
    episode_id: Option<Digest>,
    seed: u64,
    policy: ScriptedPolicy,
) -> Result<ReplayReceipt> {
    let reset = environment.reset_episode(episode_id, seed)?;
    let mut rng = SplitMix64::new(reset.seed_ancestry.component_seed);
    let mut index = 0_usize;
    loop {
        let action = policy.action(index, &mut rng)?;
        let output = environment.step(action)?;
        index += 1;
        if output.terminated || output.truncated {
            break;
        }
    }
    let terminal = environment.terminal_receipt().ok_or_else(|| {
        Error::Environment("scripted replay ended without terminal receipt".into())
    })?;
    Ok(ReplayReceipt {
        episode_id: reset.episode_id,
        seed,
        policy,
        action_count: index as u64,
        trajectory_root: environment.trajectory_root()?,
        terminal_receipt_hash: crate::identity(b"northstar-terminal-receipt-v1", terminal)?,
    })
}

impl ScriptedPolicy {
    fn action(&self, index: usize, rng: &mut SplitMix64) -> Result<f32> {
        let action = match self {
            Self::AlwaysFlat => 0.0,
            Self::AlwaysFullPositive => 1.0,
            Self::AlwaysFullNegative => -1.0,
            Self::AlternateExtremes => {
                if index.is_multiple_of(2) {
                    1.0
                } else {
                    -1.0
                }
            }
            Self::FixedActionSequence(actions) => *actions.get(index).ok_or_else(|| {
                Error::Environment("fixed action sequence ended before episode".into())
            })?,
            Self::SeededRandomActions => rng.next_f32_signed(),
        };
        if !action.is_finite() || !(-1.0..=1.0).contains(&action) {
            return Err(Error::InvalidContract(
                "scripted policy produced an invalid action".into(),
            ));
        }
        Ok(action)
    }
}

/// Small explicitly frozen generator for deterministic probes, not learner randomness.
struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn next_f32_signed(&mut self) -> f32 {
        let unit = (self.next_u64() >> 40) as f32 / ((1_u32 << 24) - 1) as f32;
        unit.mul_add(2.0, -1.0)
    }
}
