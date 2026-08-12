use serde::{Deserialize, Serialize};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

macro_rules! semantic_id {
    ($name:ident) => {
        #[derive(
            Clone,
            Copy,
            Debug,
            Deserialize,
            Eq,
            FromBytes,
            Hash,
            Immutable,
            IntoBytes,
            KnownLayout,
            Ord,
            PartialEq,
            PartialOrd,
            Serialize,
        )]
        #[repr(transparent)]
        pub struct $name(pub u64);

        impl $name {
            #[must_use]
            pub const fn get(self) -> u64 {
                self.0
            }
        }
    };
}

semantic_id!(EventId);
semantic_id!(AttemptId);
semantic_id!(EpisodeId);
semantic_id!(TransitId);
semantic_id!(NodeId);
semantic_id!(EvidenceId);
semantic_id!(SourceKey);

/// Unix seconds interpreted in MT5 server time, not workstation UTC.
#[derive(
    Clone,
    Copy,
    Debug,
    Deserialize,
    Eq,
    FromBytes,
    Hash,
    Immutable,
    IntoBytes,
    KnownLayout,
    Ord,
    PartialEq,
    PartialOrd,
    Serialize,
)]
#[repr(transparent)]
pub struct Mt5ServerTime(pub i64);
