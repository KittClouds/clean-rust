//! Stable semantic boundary between MT5 RG2 ledgers and Northstar.

mod decimal;
mod enums;
mod ids;

pub use decimal::{Decimal128, DecimalError};
pub use enums::{
    AuctionResolution, CensorReason, CompletionStatus, EnumCodeError, EventType, Region,
    SemanticOutcome, StableLabel, validate_code_label,
};
pub use ids::{
    AttemptId, EpisodeId, EventId, EvidenceId, Mt5ServerTime, NodeId, SourceKey, TransitId,
};

pub const DATASET_CONTRACT: &str = "MST_AUCTION_RELATIONAL_V1";
pub const DATASET_SCHEMA: u16 = 7;
pub const RESEARCH_GENERATION: u16 = 2;
pub const NULL_TOKEN: &[u8] = b"\\N";
pub const TIMESTAMP_ENCODING: &str = "unix_seconds";
pub const TIMESTAMP_TIMEZONE: &str = "MT5_SERVER";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ContractIdentity {
    pub research_generation: u16,
    pub dataset_schema: u16,
}

impl ContractIdentity {
    pub const RG2_V7: Self = Self {
        research_generation: RESEARCH_GENERATION,
        dataset_schema: DATASET_SCHEMA,
    };

    #[must_use]
    pub const fn is_supported(self) -> bool {
        self.research_generation == RESEARCH_GENERATION && self.dataset_schema == DATASET_SCHEMA
    }
}
