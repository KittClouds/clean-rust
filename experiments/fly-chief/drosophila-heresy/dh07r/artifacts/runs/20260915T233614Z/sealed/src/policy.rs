use crate::{capture::Capture,rotation::{Rotation,Audit,event_key}};
pub struct Policy {
    pub rotor:Rotation,
    pub audits:Vec<Audit>,
    pub witnesses:Vec<Vec<f32>>,
    pub failed:bool,
    seed:u64,tau:f32,side:u8,
}
impl Policy {
    pub fn new(n:usize,seed:u64,tau:f32,side:u8)->Self {
        Self{rotor:Rotation::new(n),audits:Vec::with_capacity(256),witnesses:(0..8).map(|_|vec![0.;n]).collect(),failed:false,seed,tau,side}
    }
    pub fn apply(&mut self,capture:&Capture,weights:&mut[f32]) {
        let snapshot=&capture.current;
        let audit=self.rotor.construct(snapshot,event_key(self.seed,self.tau,self.side,snapshot.trial));
        self.failed= !audit.axial_error_over_total_norm.is_finite()
            || audit.axial_error_over_total_norm>1e-7 || audit.norm_relative_error>1e-7
            || audit.residual_norm_relative_error>1e-7
            || audit.residual_abs_cosine.is_none_or(|c|!c.is_finite()||c>1e-5)
            || audit.boundary_symmetric_difference!=0 || audit.outside_support_changes!=0
            || audit.max_bound_violation!=0. || audit.hot_allocations!=0
            || (audit.true_nonzero.abs_diff(audit.null_nonzero) as f64)/(audit.true_nonzero.max(1) as f64)>0.01;
        if !self.failed {
            weights.copy_from_slice(&self.rotor.committed);
            for (slot,out) in capture.slots.iter().zip(&mut self.witnesses) {
                if slot.trial==snapshot.trial {out.copy_from_slice(&self.rotor.committed);}
            }
        }
        self.audits.push(audit);
    }
}
