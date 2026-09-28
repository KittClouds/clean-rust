use thiserror::Error;

pub type LorentzResult<T> = Result<T, LorentzTreeError>;

#[derive(Debug, Error)]
pub enum LorentzTreeError {
    #[error("empty vector")]
    EmptyVector,

    #[error("dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },

    #[error("invalid hyperboloid point: lorentz_norm={lorentz_norm}, time={time}")]
    InvalidHyperboloidPoint { lorentz_norm: f32, time: f32 },

    #[error("invalid config field {field}: {value}")]
    InvalidConfigField { field: &'static str, value: f32 },

    #[error("duplicate node id: {0}")]
    DuplicateNode(String),

    #[error("duplicate tree id: {0}")]
    DuplicateTree(String),

    #[error("duplicate membership: tree={tree_id}, node={node_id}")]
    DuplicateMembership { tree_id: String, node_id: String },

    #[error("missing node id: {0}")]
    MissingNode(String),

    #[error("missing tree id: {0}")]
    MissingTree(String),

    #[error("missing membership: tree={tree_id}, node={node_id}")]
    MissingMembership { tree_id: String, node_id: String },

    #[error("invalid parent: tree={tree_id}, parent={parent_node_id}")]
    InvalidParent {
        tree_id: String,
        parent_node_id: String,
    },

    #[error("cycle rejected: tree={tree_id}, node={node_id}, parent={parent_node_id}")]
    CycleRejected {
        tree_id: String,
        node_id: String,
        parent_node_id: String,
    },

    #[error("index invariant failed: {0}")]
    IndexInvariant(String),

    #[error("invalid mmap index: {0}")]
    InvalidMmap(String),

    #[error(transparent)]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Bincode(#[from] bincode::Error),
}
