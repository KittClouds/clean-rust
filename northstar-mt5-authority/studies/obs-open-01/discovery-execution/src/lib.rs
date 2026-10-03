pub mod authority;
pub mod corpus;
pub mod output;
pub mod stats;

pub const DISC02P_ROOT: &str = "f6ab7b3f4ba95e70399367e4a16140549bea5e16fe9a58d460e5166ec4200877";
pub const MEAS02_ROOT: &str = "f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea";
pub const RAW_BAR_HASH: &str = "125b768ad87ba578c5498deffe50462909a6a1be422953a0f7488f036aac9d5b";
pub const DISCOVERY_PREFIX_HASH: &str =
    "6dde69a9ae069b95f49e1759fb5feb595dc22b04e76534f8c6cd15caa3b4249e";
pub const DISCOVERY_PREFIX_ROWS: usize = 633_322;
pub const DISCOVERY_SESSIONS: usize = 257;
pub const CONFIRMATION_SESSIONS: usize = 69;
pub const OBSERVER_INSTANCE: &str = "CAUSAL_RANGE_EXTREME_M1_V1";

pub type AnyResult<T> = Result<T, Box<dyn std::error::Error>>;
