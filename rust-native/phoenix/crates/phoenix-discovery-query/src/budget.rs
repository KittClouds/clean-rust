use crate::BudgetExhaustion;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum EdgePhase {
    Ppr,
    Beam,
}

pub(crate) struct EdgeBudget {
    total_limit: u32,
    ppr_limit: u32,
    ppr_used: u32,
    beam_used: u32,
}

impl EdgeBudget {
    pub(crate) fn new(total_limit: u32, ppr_limit: u32) -> Self {
        Self {
            total_limit,
            ppr_limit,
            ppr_used: 0,
            beam_used: 0,
        }
    }

    pub(crate) fn take(&mut self, phase: EdgePhase, exhaustion: &mut BudgetExhaustion) -> bool {
        if self.total_used() >= self.total_limit {
            exhaustion.total_edges = true;
            return false;
        }
        if phase == EdgePhase::Ppr && self.ppr_used >= self.ppr_limit {
            exhaustion.ppr_edges = true;
            return false;
        }
        match phase {
            EdgePhase::Ppr => self.ppr_used += 1,
            EdgePhase::Beam => self.beam_used += 1,
        }
        true
    }

    pub(crate) fn ppr_used(&self) -> u32 {
        self.ppr_used
    }

    pub(crate) fn beam_used(&self) -> u32 {
        self.beam_used
    }

    pub(crate) fn total_used(&self) -> u32 {
        self.ppr_used.saturating_add(self.beam_used)
    }
}
