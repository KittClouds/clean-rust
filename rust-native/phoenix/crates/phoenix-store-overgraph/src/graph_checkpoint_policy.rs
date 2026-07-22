#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct KernelCheckpointPolicy {
    pub max_hot_journal_bytes: usize,
    pub max_measured_replay_cost_us: u64,
}

impl Default for KernelCheckpointPolicy {
    fn default() -> Self {
        Self {
            max_hot_journal_bytes: 4 * 1024 * 1024,
            max_measured_replay_cost_us: 25_000,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) struct KernelCheckpointPolicyInput {
    pub hot_journal_bytes: usize,
    pub measured_replay_cost_us: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum KernelCheckpointDecision {
    KeepJournalHot,
    Checkpoint(KernelCheckpointReason),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum KernelCheckpointReason {
    HotJournalBytes,
    MeasuredReplayCost,
}

impl KernelCheckpointPolicy {
    pub(crate) fn decide(self, input: KernelCheckpointPolicyInput) -> KernelCheckpointDecision {
        if threshold_crossed(input.hot_journal_bytes, self.max_hot_journal_bytes) {
            return KernelCheckpointDecision::Checkpoint(KernelCheckpointReason::HotJournalBytes);
        }
        if threshold_crossed(
            input.measured_replay_cost_us,
            self.max_measured_replay_cost_us,
        ) {
            return KernelCheckpointDecision::Checkpoint(
                KernelCheckpointReason::MeasuredReplayCost,
            );
        }
        KernelCheckpointDecision::KeepJournalHot
    }
}

fn threshold_crossed<T>(value: T, threshold: T) -> bool
where
    T: Copy + Ord + From<u8>,
{
    threshold > T::from(0) && value >= threshold
}

#[cfg(test)]
mod tests {
    use super::{
        KernelCheckpointDecision, KernelCheckpointPolicy, KernelCheckpointPolicyInput,
        KernelCheckpointReason,
    };

    #[test]
    fn checkpoint_policy_triggers_on_bytes_or_measured_replay_cost() {
        let policy = KernelCheckpointPolicy {
            max_hot_journal_bytes: 1024,
            max_measured_replay_cost_us: 500,
        };

        assert_eq!(
            policy.decide(KernelCheckpointPolicyInput {
                hot_journal_bytes: 1024,
                measured_replay_cost_us: 0,
            }),
            KernelCheckpointDecision::Checkpoint(KernelCheckpointReason::HotJournalBytes)
        );
        assert_eq!(
            policy.decide(KernelCheckpointPolicyInput {
                hot_journal_bytes: 16,
                measured_replay_cost_us: 500,
            }),
            KernelCheckpointDecision::Checkpoint(KernelCheckpointReason::MeasuredReplayCost)
        );
    }

    #[test]
    fn checkpoint_policy_keeps_journal_delta_hot_below_thresholds() {
        let policy = KernelCheckpointPolicy {
            max_hot_journal_bytes: 1024,
            max_measured_replay_cost_us: 500,
        };

        assert_eq!(
            policy.decide(KernelCheckpointPolicyInput {
                hot_journal_bytes: 1023,
                measured_replay_cost_us: 499,
            }),
            KernelCheckpointDecision::KeepJournalHot
        );
    }
}
