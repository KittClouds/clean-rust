//! Capture-only observer. SVD runs after simulation, never in its hot loop.
use crate::{
    capture::{Capture, Snapshot},
    task::Task,
};

pub struct Policy {
    pub snapshots: Vec<Snapshot>,
    pub failed: bool,
    pub count: usize,
}
impl Policy {
    pub fn new(n: usize) -> Self {
        let template = Snapshot {
            trial: 0,
            base: vec![0.; n],
            target: vec![0.; n],
            axis: vec![0.; n],
            permitted: vec![false; n],
        };
        Self {
            snapshots: (0..256).map(|_| template.clone()).collect(),
            failed: false,
            count: 0,
        }
    }
    #[allow(clippy::too_many_arguments)]
    pub fn apply(
        &mut self,
        capture: &Capture,
        weights: &mut [f32],
        _task: &Task,
        _post_len: usize,
        _denom: &[f32],
        _bias: &[f32],
        _sign: &[f32],
    ) {
        let source = &capture.current;
        assert!(self.count < 256);
        let target = &mut self.snapshots[self.count];
        target.trial = source.trial;
        target.base.copy_from_slice(&source.base);
        target.target.copy_from_slice(&source.target);
        target.axis.copy_from_slice(&source.axis);
        target.permitted.copy_from_slice(&source.permitted);
        self.count += 1;
        weights.copy_from_slice(&source.target);
    }
}
