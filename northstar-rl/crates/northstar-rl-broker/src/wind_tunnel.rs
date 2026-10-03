use northstar_rl_core::{
    Digest, EnvStepRecord, Environment, ResetOutput, StepOutput, WindTunnelMode,
};

use crate::{Error, Result};

/// Durable environment ABI shared by all admitted wind-tunnel sources.
pub trait WindTunnelWorld {
    fn mode(&self) -> WindTunnelMode;
    fn reset(&mut self, episode_id: Option<Digest>, seed: u64) -> Result<ResetOutput>;
    fn observe(&self) -> Result<Vec<f32>>;
    fn apply_action(&mut self, target_exposure: f32) -> Result<()>;
    fn advance(&mut self) -> Result<StepOutput>;
    fn receipt(&self) -> Option<&EnvStepRecord>;
}

pub struct NorthstarWindTunnel {
    mode: WindTunnelMode,
    environment: Environment,
    staged_action: Option<f32>,
}

impl NorthstarWindTunnel {
    pub fn new(mode: WindTunnelMode, environment: Environment) -> Self {
        Self {
            mode,
            environment,
            staged_action: None,
        }
    }
}

impl WindTunnelWorld for NorthstarWindTunnel {
    fn mode(&self) -> WindTunnelMode {
        self.mode
    }

    fn reset(&mut self, episode_id: Option<Digest>, seed: u64) -> Result<ResetOutput> {
        self.staged_action = None;
        Ok(self.environment.reset_episode(episode_id, seed)?)
    }

    fn observe(&self) -> Result<Vec<f32>> {
        Ok(self.environment.current_observation()?)
    }

    fn apply_action(&mut self, target_exposure: f32) -> Result<()> {
        if self.staged_action.replace(target_exposure).is_some() {
            return Err(Error::Contract(
                "advance is required before staging another action".into(),
            ));
        }
        Ok(())
    }

    fn advance(&mut self) -> Result<StepOutput> {
        let action = self
            .staged_action
            .take()
            .ok_or_else(|| Error::Contract("apply_action is required before advance".into()))?;
        Ok(self.environment.step(action)?)
    }

    fn receipt(&self) -> Option<&EnvStepRecord> {
        self.environment.steps().last()
    }
}
