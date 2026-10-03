use crate::{
    allocation::allocations,
    capture::Capture,
    rotation::{Audit, Rotation, event_key},
    simulation::old_map_margin_for_weights_dh08a,
    task::Task,
};
use serde::Serialize;

#[derive(Serialize)]
pub struct ShadowEvent {
    pub trial: usize,
    pub base_margin: f64,
    pub true_margin: f64,
    pub null_margin: f64,
    pub true_minus_null: f64,
    pub true_endpoint_sha256: [u8; 32],
    pub geometry_valid: bool,
    pub shadow_hot_allocations: u64,
    pub geometry: Audit,
    pub readout: crate::readout::Readout,
    pub budget: crate::rotation::Budget,
    pub zero_residual: bool,
    pub failure_mask: u32,
}

/// Event-local DH-08A shadow instrumentation.
///
/// The feasible null is constructed and measured, then discarded. The exact
/// ordinary TruePerpendicular endpoint is always the state committed to the
/// canonical trajectory, including when a qualification gate fails.
pub struct Policy {
    pub rotor: Rotation,
    pub events: Vec<ShadowEvent>,
    pub failed: bool,
    seed: u64,
    tau: f32,
    side: u8,
}

impl Policy {
    pub fn new(n: usize, seed: u64, tau: f32, side: u8) -> Self {
        Self {
            rotor: Rotation::new(n),
            events: Vec::with_capacity(256),
            failed: false,
            seed,
            tau,
            side,
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn apply(
        &mut self,
        capture: &Capture,
        weights: &mut [f32],
        task: &Task,
        post_len: usize,
        denom: &[f32],
        bias: &[f32],
        action_sign: &[f32],
    ) {
        let start_allocations = allocations();
        let snapshot = &capture.current;
        let audit = self.rotor.construct(
            snapshot,
            event_key(self.seed, self.tau, self.side, snapshot.trial),
            task,
            post_len,
        );
        let base_margin = old_map_margin_for_weights_dh08a(
            task,
            &snapshot.base,
            post_len,
            denom,
            bias,
            action_sign,
        );
        let true_margin = old_map_margin_for_weights_dh08a(
            task,
            &snapshot.target,
            post_len,
            denom,
            bias,
            action_sign,
        );
        let null_margin = old_map_margin_for_weights_dh08a(
            task,
            &self.rotor.committed,
            post_len,
            denom,
            bias,
            action_sign,
        );
        let readout = crate::readout::audit(
            task,
            &snapshot.target,
            &self.rotor.committed,
            denom,
            bias,
            action_sign,
        );
        let zero_residual = self.rotor.budget.residual_energy == 0.;
        let gates = [
            audit.axial_error_over_total_norm.is_finite()
                && audit.axial_error_over_total_norm <= 1e-7,
            audit.norm_relative_error.is_finite() && audit.norm_relative_error <= 1e-7,
            audit.residual_norm_relative_error.is_finite()
                && audit.residual_norm_relative_error <= 1e-7,
            !zero_residual
                && audit
                    .residual_abs_cosine
                    .is_some_and(|c| c.is_finite() && c <= 1e-5),
            audit.boundary_symmetric_difference == 0,
            audit.outside_support_changes == 0,
            audit.max_bound_violation == 0.,
            audit.hot_allocations == 0,
            audit.true_nonzero.abs_diff(audit.null_nonzero) as f64
                / audit.true_nonzero.max(1) as f64
                <= 0.01,
            readout.max_normalized_drive_error.is_finite()
                && readout.max_normalized_drive_error <= 1e-7,
            readout.max_cue_score_error.is_finite() && readout.max_cue_score_error <= 1e-7,
        ];
        let mut failure_mask = 0_u32;
        for (i, passed) in gates.iter().enumerate() {
            if !passed {
                failure_mask |= 1 << i;
            }
        }

        // The shadow endpoints are disposable. Only W_T enters learner state.
        weights.copy_from_slice(&snapshot.target);
        let shadow_hot_allocations = allocations() - start_allocations;
        if shadow_hot_allocations != 0 {
            failure_mask |= 1 << 11;
        }
        if !base_margin.is_finite() || !true_margin.is_finite() || !null_margin.is_finite() {
            failure_mask |= 1 << 12;
        }
        let geometry_valid = failure_mask == 0;
        self.failed |= !geometry_valid
            || shadow_hot_allocations != 0
            || !base_margin.is_finite()
            || !true_margin.is_finite()
            || !null_margin.is_finite();
        let true_endpoint_sha256 = capture
            .true_endpoint_sha256
            .last()
            .copied()
            .expect("capture must finish before DH-08A shadow evaluation");
        self.events.push(ShadowEvent {
            trial: snapshot.trial,
            base_margin,
            true_margin,
            null_margin,
            true_minus_null: true_margin - null_margin,
            true_endpoint_sha256,
            geometry_valid,
            shadow_hot_allocations,
            geometry: audit,
            readout,
            budget: self.rotor.budget.clone(),
            zero_residual,
            failure_mask,
        });
    }
}
