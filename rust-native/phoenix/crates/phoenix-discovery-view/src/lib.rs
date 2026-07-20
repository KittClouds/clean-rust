mod build;
mod columns;
mod error;
mod format;
mod mapped;
mod policy;
mod registry;
mod source;

pub use build::{
    write_asserted_discovery_view, write_asserted_discovery_view_from_source,
    DiscoveryAuthorityBinding,
};
pub use error::DiscoveryViewError;
pub use format::{
    DiscoveryIdentityKind, DiscoveryNodeKind, DiscoveryRelationEntry, DiscoveryViewManifest,
    DISCOVERY_VIEW_SCHEMA,
};
pub use mapped::AssertedDiscoveryView;
pub use mapped::{
    DiscoveryEdgeView, DiscoveryIndexSlice, DiscoveryStableId, DiscoveryTemporalView,
};
pub use policy::{DiscoveryRelationFamily, DiscoveryRelationPolicy, RelationFamilyRule};
pub use registry::{DiscoveryGenerationReceipt, DiscoveryViewRegistry};
pub use source::{PagedAssertedDiscoverySource, DISCOVERY_SOURCE_PAGE_SIZE};

#[cfg(test)]
mod tests;
