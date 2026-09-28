use std::collections::VecDeque;

use crate::world::{Exposure, WorldEvent};

#[derive(Clone, Debug)]
pub struct Prediction {
    /// Candidate probabilities in canonical LABELS order, not displayed order.
    pub probabilities: [f64; 3],
}

impl Prediction {
    pub fn validate(&self) -> Result<(), String> {
        if self
            .probabilities
            .iter()
            .any(|p| !p.is_finite() || !(0.0..=1.0).contains(p))
            || (self.probabilities.iter().sum::<f64>() - 1.0).abs() > 1e-6
        {
            return Err("invalid probability vector".into());
        }
        Ok(())
    }
    pub fn choice(&self) -> u8 {
        let mut best = 0;
        for index in 1..3 {
            if self.probabilities[index] > self.probabilities[best] {
                best = index;
            }
        }
        best as u8
    }
}

#[derive(Clone, Debug)]
pub struct FeedbackRecord {
    pub event_id: String,
    pub source_step: u32,
    pub due_step: u32,
    pub exposure: Exposure,
    pub feature: Vec<f32>,
    pub target_index: u8,
}

/// Every baseline and adaptive arm implements this boundary. Hidden world state is unavailable.
pub trait Arm {
    fn name(&self) -> &'static str;
    fn reset(&mut self);
    fn observe(&mut self, exposure: &Exposure, feature: &[f32]);
    fn predict(&mut self, exposure: &Exposure, feature: &[f32]) -> Prediction;
    fn feedback(&mut self, record: &FeedbackRecord);
    fn resource_bytes(&self) -> ResourceBytes;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExplicitBaselineKind {
    LastObservation,
    Counter,
}

/// Trivial explicit-state baselines use the ordinary exposure/feedback boundary.
pub trait ExplicitStateBaseline: Arm {
    fn baseline_kind(&self) -> ExplicitBaselineKind;
}

/// Privileged upper bound; the ordinary arm runner must never call this trait.
pub trait OracleCurrentStateBaseline {
    fn predict_true_state(&mut self, exact_target_index: u8) -> Prediction;
}

/// Privileged ceiling; regime identity is supplied before prediction and logged as oracle input.
pub trait OracleRegimeSnapshot: Arm {
    fn route_to_regime(&mut self, regime_identity: &str);
}

/// Feature providers must hash and record inputs under FAS_FEATURE_V1 in Phase 2.
pub trait FeatureProvider {
    fn feature(&mut self, exposure: &Exposure) -> Result<Vec<f32>, String>;
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ResourceBytes {
    pub transient: u64,
    pub persistent: u64,
    pub adaptive_parameters: u64,
    pub optimizer_state: u64,
    pub episodic_memory: u64,
    pub snapshots: u64,
    pub feature_cache_infrastructure: u64,
}

impl ResourceBytes {
    pub fn b_c(self) -> u64 {
        self.transient
    }
    pub fn b_m(self) -> u64 {
        self.episodic_memory + self.snapshots
    }
    pub fn b_phi(self) -> u64 {
        self.adaptive_parameters + self.optimizer_state
    }
    pub fn b_adaptive(self) -> u64 {
        self.b_m() + self.b_phi()
    }
}

#[derive(Clone, Debug)]
pub struct ScoredPrediction {
    pub event_id: String,
    pub step: u32,
    pub prediction: Prediction,
    pub target_index: u8,
    pub feedback_revealed_after_score: Vec<String>,
}

/// Order is observe -> predict -> log -> reveal due feedback -> update.
pub fn run_arm<A: Arm, F: FeatureProvider>(
    arm: &mut A,
    provider: &mut F,
    events: &[WorldEvent],
) -> Result<Vec<ScoredPrediction>, String> {
    arm.reset();
    let mut pending: VecDeque<FeedbackRecord> = VecDeque::new();
    let mut scored = Vec::with_capacity(events.len());
    for event in events {
        let exposure = &event.exposure;
        let feature = provider.feature(exposure)?;
        arm.observe(exposure, &feature);
        let prediction = arm.predict(exposure, &feature);
        prediction.validate()?;
        scored.push(ScoredPrediction {
            event_id: exposure.event_id.clone(),
            step: exposure.step,
            prediction,
            target_index: event.target_index,
            feedback_revealed_after_score: Vec::new(),
        });
        pending.push_back(FeedbackRecord {
            event_id: exposure.event_id.clone(),
            source_step: exposure.step,
            due_step: event.feedback_due_step,
            exposure: exposure.clone(),
            feature,
            target_index: event.target_index,
        });
        while pending
            .front()
            .is_some_and(|record| record.due_step <= exposure.step)
        {
            let record = pending.pop_front().unwrap();
            scored
                .last_mut()
                .unwrap()
                .feedback_revealed_after_score
                .push(record.event_id.clone());
            arm.feedback(&record);
        }
    }
    Ok(scored)
}
