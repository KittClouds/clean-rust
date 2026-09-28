use crate::HyperbolicDiskError;
use std::cmp::Ordering;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[repr(transparent)]
pub struct StableVectorId(u64);

impl StableVectorId {
    pub fn new(value: u64) -> Result<Self, HyperbolicDiskError> {
        if value == 0 {
            return Err(HyperbolicDiskError::ZeroVectorId);
        }
        Ok(Self(value))
    }

    pub const fn from_sequential(dense_id: u32) -> Self {
        Self(dense_id as u64 + 1)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[repr(transparent)]
pub struct DenseVectorId(pub(crate) u32);

impl DenseVectorId {
    pub const fn get(self) -> u32 {
        self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NodeMetadata {
    pub tag_mask: u64,
}

impl Default for NodeMetadata {
    fn default() -> Self {
        Self { tag_mask: u64::MAX }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HnswBuildParams {
    pub m: usize,
    pub m0: usize,
    pub ef_construction: usize,
    pub level_mult: f32,
}

impl Default for HnswBuildParams {
    fn default() -> Self {
        Self {
            m: 16,
            m0: 32,
            ef_construction: 200,
            level_mult: 1.0 / 16.0_f32.ln(),
        }
    }
}

impl HnswBuildParams {
    pub(crate) fn validate(self) -> Result<Self, HyperbolicDiskError> {
        if self.m < 2 || self.m > u16::MAX as usize {
            return Err(HyperbolicDiskError::InvalidConfig("m must be in 2..=65535"));
        }
        if self.m0 < self.m || self.m0 > u16::MAX as usize {
            return Err(HyperbolicDiskError::InvalidConfig(
                "m0 must be in m..=65535",
            ));
        }
        if self.ef_construction < self.m0 {
            return Err(HyperbolicDiskError::InvalidConfig(
                "ef_construction must be at least m0",
            ));
        }
        if !self.level_mult.is_finite() || self.level_mult <= 0.0 {
            return Err(HyperbolicDiskError::InvalidConfig(
                "level_mult must be finite and positive",
            ));
        }
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HnswBuildOptions {
    pub params: HnswBuildParams,
    pub seed: u64,
    pub maximum_level: u8,
}

impl Default for HnswBuildOptions {
    fn default() -> Self {
        Self {
            params: HnswBuildParams::default(),
            seed: 0x5048_4f45_4e49_585f,
            maximum_level: 32,
        }
    }
}

impl HnswBuildOptions {
    pub(crate) fn validate(self) -> Result<Self, HyperbolicDiskError> {
        self.params.validate()?;
        if self.maximum_level == 0 || self.maximum_level > 63 {
            return Err(HyperbolicDiskError::InvalidConfig(
                "maximum_level must be in 1..=63",
            ));
        }
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FilterMode {
    PostFilter,
    Strict,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchParams {
    pub k: usize,
    pub ef_search: usize,
    pub filter_mode: FilterMode,
}

impl SearchParams {
    pub const fn new(k: usize, ef_search: usize) -> Self {
        Self {
            k,
            ef_search,
            filter_mode: FilterMode::PostFilter,
        }
    }

    pub(crate) fn validate(self) -> Result<Self, HyperbolicDiskError> {
        if self.k == 0 {
            return Err(HyperbolicDiskError::InvalidSearch("k must be nonzero"));
        }
        if self.ef_search < self.k {
            return Err(HyperbolicDiskError::InvalidSearch(
                "ef_search must be at least k",
            ));
        }
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Candidate {
    pub dist: f32,
    pub id: u32,
}

impl PartialEq for Candidate {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id && self.dist.to_bits() == other.dist.to_bits()
    }
}

impl Eq for Candidate {}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.dist
            .total_cmp(&other.dist)
            .then_with(|| self.id.cmp(&other.id))
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SearchHit {
    pub id: StableVectorId,
    pub dense_id: DenseVectorId,
    pub distance: f32,
}
