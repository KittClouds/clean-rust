use crate::DiscoveryQueryError;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryMode {
    Interactive,
    BackgroundSixHop,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QueryLimits {
    pub mode: QueryMode,
    pub seeds: u16,
    pub hops: u8,
    pub beam_width: u16,
    pub fanout_per_state: u16,
    pub ppr_visited_vertices: u32,
    pub ppr_examined_edges: u32,
    pub total_examined_edges: u32,
    pub returned_paths: u16,
    pub edge_scan_per_state: u16,
    pub evidence_per_edge: u8,
}

impl QueryLimits {
    pub const fn interactive() -> Self {
        Self {
            mode: QueryMode::Interactive,
            seeds: 32,
            hops: 4,
            beam_width: 48,
            fanout_per_state: 32,
            ppr_visited_vertices: 4_096,
            ppr_examined_edges: 8_192,
            total_examined_edges: 16_384,
            returned_paths: 24,
            edge_scan_per_state: 128,
            evidence_per_edge: 8,
        }
    }

    pub const fn background_six_hop() -> Self {
        Self {
            mode: QueryMode::BackgroundSixHop,
            seeds: 32,
            hops: 6,
            beam_width: 48,
            fanout_per_state: 32,
            ppr_visited_vertices: 8_192,
            ppr_examined_edges: 16_384,
            total_examined_edges: 32_768,
            returned_paths: 24,
            edge_scan_per_state: 128,
            evidence_per_edge: 8,
        }
    }

    pub fn validate(self) -> Result<Self, DiscoveryQueryError> {
        let valid = self.seeds > 0
            && self.seeds <= 32
            && self.hops > 0
            && self.hops <= 6
            && self.beam_width > 0
            && self.beam_width <= 48
            && self.fanout_per_state > 0
            && self.fanout_per_state <= 32
            && self.ppr_visited_vertices > 0
            && self.ppr_visited_vertices <= 8_192
            && self.ppr_examined_edges <= self.total_examined_edges
            && self.total_examined_edges <= 32_768
            && self.returned_paths > 0
            && self.returned_paths <= 24
            && self.edge_scan_per_state >= self.fanout_per_state
            && self.edge_scan_per_state <= 256
            && self.evidence_per_edge <= 8
            && matches!(
                (self.mode, self.hops),
                (QueryMode::Interactive, 1..=4) | (QueryMode::BackgroundSixHop, 6)
            );
        if !valid {
            return Err(DiscoveryQueryError::Invalid(
                "query limits exceed the bounded execution envelope".to_owned(),
            ));
        }
        Ok(self)
    }

    pub fn digest(self) -> Result<[u8; 32], DiscoveryQueryError> {
        let limits = self.validate()?;
        let bytes = serde_json::to_vec(&limits)
            .map_err(|error| DiscoveryQueryError::Invalid(error.to_string()))?;
        Ok(*blake3::hash(&bytes).as_bytes())
    }
}
