use crate::{CancellationPhase, CancellationReceipt};

pub trait CancellationProbe {
    fn is_cancelled(&self) -> bool;
}

impl<F> CancellationProbe for F
where
    F: Fn() -> bool,
{
    fn is_cancelled(&self) -> bool {
        self()
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancel;

impl CancellationProbe for NeverCancel {
    fn is_cancelled(&self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct CancellationTracker {
    receipt: CancellationReceipt,
}

impl CancellationTracker {
    pub(crate) fn check(
        &mut self,
        probe: &dyn CancellationProbe,
        phase: CancellationPhase,
    ) -> bool {
        if self.receipt.observed {
            return true;
        }
        self.receipt.checks = self.receipt.checks.saturating_add(1);
        if probe.is_cancelled() {
            self.receipt.requested = true;
            self.receipt.observed = true;
            self.receipt.phase = Some(phase);
        }
        self.receipt.observed
    }

    pub(crate) fn receipt(self) -> CancellationReceipt {
        self.receipt
    }

    pub(crate) fn observed(self) -> bool {
        self.receipt.observed
    }
}
