use std::path::Path;

use crate::{Digest, Environment, Error, ResetOutput, Result, StepOutput};

/// Dense, single-owner lane set for crossing the Python/Rust boundary once per batch.
pub struct EnvironmentBatch {
    lanes: Box<[Environment]>,
}

impl EnvironmentBatch {
    pub fn open(config_path: impl AsRef<Path>, lane_count: usize) -> Result<Self> {
        if lane_count == 0 {
            return Err(Error::InvalidContract(
                "environment batch requires at least one lane".into(),
            ));
        }
        let config_path = config_path.as_ref();
        let mut lanes = Vec::with_capacity(lane_count);
        for _ in 0..lane_count {
            lanes.push(Environment::open(config_path)?);
        }
        Ok(Self {
            lanes: lanes.into_boxed_slice(),
        })
    }

    pub fn len(&self) -> usize {
        self.lanes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.lanes.is_empty()
    }

    pub fn reset_many(
        &mut self,
        episode_ids: &[Option<Digest>],
        seeds: &[u64],
    ) -> Result<Vec<ResetOutput>> {
        if seeds.len() != self.lanes.len()
            || (!episode_ids.is_empty() && episode_ids.len() != self.lanes.len())
        {
            return Err(Error::InvalidContract(
                "reset_many inputs must match the lane count".into(),
            ));
        }
        let mut output = Vec::with_capacity(self.lanes.len());
        for (index, (environment, &seed)) in self.lanes.iter_mut().zip(seeds).enumerate() {
            output
                .push(environment.reset_episode(episode_ids.get(index).copied().flatten(), seed)?);
        }
        Ok(output)
    }

    pub fn step_many(&mut self, actions: &[f32]) -> Result<Vec<StepOutput>> {
        if actions.len() != self.lanes.len() {
            return Err(Error::InvalidContract(
                "step_many actions must match the lane count".into(),
            ));
        }
        let mut output = Vec::with_capacity(self.lanes.len());
        for (environment, &action) in self.lanes.iter_mut().zip(actions) {
            output.push(environment.step(action)?);
        }
        Ok(output)
    }

    pub fn observations(&self) -> Result<Vec<Vec<f32>>> {
        self.lanes
            .iter()
            .map(Environment::current_observation)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::materialize_lab;

    #[test]
    fn batch_rejects_shape_mismatch_and_advances_all_lanes() {
        let directory = tempfile::tempdir().unwrap();
        materialize_lab(directory.path()).unwrap();
        let config = directory.path().join("environment_config.json");
        let mut batch = EnvironmentBatch::open(config, 4).unwrap();
        assert!(batch.reset_many(&[], &[1, 2]).is_err());
        let reset = batch.reset_many(&[], &[1, 2, 3, 4]).unwrap();
        assert_eq!(reset.len(), 4);
        let steps = batch.step_many(&[0.0, 0.25, -0.25, 1.0]).unwrap();
        assert_eq!(steps.len(), 4);
        assert!(steps.iter().all(|step| step.step_id == 1));
    }
}
