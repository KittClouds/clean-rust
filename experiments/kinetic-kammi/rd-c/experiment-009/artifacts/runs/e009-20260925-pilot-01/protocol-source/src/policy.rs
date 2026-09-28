#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PaidInspection {
    Disabled,
    Enabled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimePolicy {
    pub paid_inspection: PaidInspection,
}

impl Default for RuntimePolicy {
    fn default() -> Self {
        Self {
            paid_inspection: PaidInspection::Disabled,
        }
    }
}

impl RuntimePolicy {
    #[inline]
    pub const fn may_request_paid_inspection(self) -> bool {
        matches!(self.paid_inspection, PaidInspection::Enabled)
    }
}
