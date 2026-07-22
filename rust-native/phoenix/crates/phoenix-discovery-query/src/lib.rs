mod budget;
mod config;
mod control;
mod error;
mod execute;
mod path_score;
mod ppr;
mod score;
mod score_policy;
mod scratch;
mod seed;
mod types;

pub use config::{QueryLimits, QueryMode};
pub use control::{CancellationProbe, NeverCancel};
pub use error::DiscoveryQueryError;
pub use execute::{PreparedDiscoveryQuery, QueryScratch};
pub use score_policy::DiscoveryScorePolicy;
pub use seed::{BoundedSeedSink, PreparedSeedResolver, SeedChannel, SeedChannelReceipt, SeedHit};
pub use types::{
    BudgetExhaustion, CancellationPhase, CancellationReceipt, DiscoveryPath, EdgeReceipt,
    PathScoreReceipt, PreparedQueryReceipt, PreparedQueryRequest, PreparedQueryResponse,
    PruningCounters, QueryStableId, SignalContribution,
};

#[cfg(test)]
mod tests;
