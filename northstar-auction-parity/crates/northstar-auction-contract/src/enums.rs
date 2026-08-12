use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("unsupported {kind} code {code}")]
pub struct EnumCodeError {
    pub kind: &'static str,
    pub code: i16,
}

macro_rules! stable_enum {
    ($name:ident, $kind:literal, $repr:ty, {$($variant:ident = $code:expr => $label:literal),+ $(,)?}) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
        #[repr($repr)]
        pub enum $name { $($variant = $code),+ }

        impl $name {
            #[must_use]
            pub const fn code(self) -> $repr { self as $repr }

            #[must_use]
            pub const fn label(self) -> &'static str {
                match self { $(Self::$variant => $label),+ }
            }
        }

        impl TryFrom<i16> for $name {
            type Error = EnumCodeError;

            fn try_from(code: i16) -> Result<Self, Self::Error> {
                match code {
                    $($code => Ok(Self::$variant),)+
                    _ => Err(EnumCodeError { kind: $kind, code }),
                }
            }
        }
    };
}

stable_enum!(
    EventType,
    "auction event",
    u8,
    {
        Approach = 1 => "APPROACH",
        Contact = 2 => "CONTACT",
        Penetration = 3 => "PENETRATION",
        Break = 4 => "BREAK",
        ProvisionalAcceptance = 5 => "PROVISIONAL_ACCEPTANCE",
        Acceptance = 6 => "ACCEPTANCE",
        Rejection = 7 => "REJECTION",
        Reclaim = 8 => "RECLAIM",
        Retest = 9 => "RETEST",
        Hold = 10 => "HOLD",
        RetestFailure = 11 => "RETEST_FAILURE",
        Departure = 12 => "DEPARTURE",
        Transit = 13 => "TRANSIT",
        ReturnToSource = 14 => "RETURN_TO_SOURCE",
        Censor = 15 => "CENSOR",
        Expire = 16 => "EXPIRE"
    }
);

stable_enum!(
    CompletionStatus,
    "completion status",
    u8,
    {
        Active = 0 => "ACTIVE",
        Resolved = 1 => "RESOLVED",
        RightCensored = 2 => "RIGHT_CENSORED"
    }
);

stable_enum!(
    CensorReason,
    "censor reason",
    u8,
    {
        None = 0 => "NONE",
        TestEnd = 1 => "TEST_END",
        Shutdown = 2 => "SHUTDOWN",
        DataGap = 3 => "DATA_GAP"
    }
);

stable_enum!(
    AuctionResolution,
    "auction resolution",
    u8,
    {
        None = 0 => "NONE",
        RejectToOrigin = 1 => "REJECT_TO_ORIGIN",
        AcceptThroughNode = 2 => "ACCEPT_THROUGH_NODE",
        ReclaimAfterBreak = 3 => "RECLAIM_AFTER_BREAK",
        AcceptAndHoldRetest = 4 => "ACCEPT_AND_HOLD_RETEST",
        AcceptAndFailRetest = 5 => "ACCEPT_AND_FAIL_RETEST",
        TransitToNextNode = 6 => "TRANSIT_TO_NEXT_NODE",
        ReturnToSourceNode = 7 => "RETURN_TO_SOURCE_NODE",
        Timeout = 8 => "TIMEOUT",
        NodeRetired = 9 => "NODE_RETIRED"
    }
);

stable_enum!(
    Region,
    "structural region",
    i8,
    {
        ExtremeBelow = -3 => "EXTREME_BELOW",
        FarBelow = -2 => "FAR_BELOW",
        Below = -1 => "BELOW",
        MedianCore = 0 => "MEDIAN_CORE",
        Above = 1 => "ABOVE",
        FarAbove = 2 => "FAR_ABOVE",
        ExtremeAbove = 3 => "EXTREME_ABOVE",
        Unavailable = 99 => "UNAVAILABLE"
    }
);

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum SemanticOutcome {
    Behavioral(AuctionResolution),
    Boundary(AuctionResolution),
    Administrative(AuctionResolution),
    Unresolved,
}

impl AuctionResolution {
    #[must_use]
    pub const fn semantic_outcome(self) -> SemanticOutcome {
        match self {
            Self::RejectToOrigin
            | Self::AcceptThroughNode
            | Self::ReclaimAfterBreak
            | Self::AcceptAndHoldRetest
            | Self::AcceptAndFailRetest
            | Self::TransitToNextNode
            | Self::ReturnToSourceNode => SemanticOutcome::Behavioral(self),
            Self::Timeout => SemanticOutcome::Boundary(self),
            Self::NodeRetired => SemanticOutcome::Administrative(self),
            Self::None => SemanticOutcome::Unresolved,
        }
    }
}

pub fn validate_code_label<E>(code: i16, label: &str) -> Result<E, EnumCodeError>
where
    E: TryFrom<i16, Error = EnumCodeError> + StableLabel,
{
    let value = E::try_from(code)?;
    if value.label() == label {
        Ok(value)
    } else {
        Err(EnumCodeError {
            kind: "code-label mismatch",
            code,
        })
    }
}

pub trait StableLabel: Copy {
    fn label(self) -> &'static str;
}

macro_rules! impl_stable_label {
    ($($name:ty),+ $(,)?) => {$ (
        impl StableLabel for $name {
            fn label(self) -> &'static str { self.label() }
        }
    )+ };
}

impl_stable_label!(
    EventType,
    CompletionStatus,
    CensorReason,
    AuctionResolution,
    Region
);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stable_codes_match_mql5_contract() {
        assert_eq!(EventType::Approach.code(), 1);
        assert_eq!(EventType::Expire.code(), 16);
        assert_eq!(CompletionStatus::RightCensored.code(), 2);
        assert_eq!(CensorReason::DataGap.code(), 3);
        assert_eq!(AuctionResolution::NodeRetired.code(), 9);
        assert_eq!(Region::ExtremeBelow.code(), -3);
        assert_eq!(Region::ExtremeAbove.code(), 3);
    }

    #[test]
    fn lifecycle_outcomes_are_not_mislabeled_as_behavior() {
        assert!(matches!(
            AuctionResolution::NodeRetired.semantic_outcome(),
            SemanticOutcome::Administrative(_)
        ));
        assert!(matches!(
            AuctionResolution::Timeout.semantic_outcome(),
            SemanticOutcome::Boundary(_)
        ));
    }
}
