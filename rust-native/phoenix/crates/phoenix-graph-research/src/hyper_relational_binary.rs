use crate::HyperRelationalTaskError;
use std::mem::size_of;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

pub(crate) const MAGIC: [u8; 8] = *b"PHXHRL01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct Header {
    pub(crate) magic: [u8; 8],
    pub(crate) version: [u8; 2],
    pub(crate) reserved: [u8; 6],
    pub(crate) total_bytes: [u8; 8],
    pub(crate) query_offset: [u8; 8],
    pub(crate) query_count: [u8; 8],
    pub(crate) group_offset: [u8; 8],
    pub(crate) group_count: [u8; 8],
    pub(crate) target_offset: [u8; 8],
    pub(crate) target_count: [u8; 8],
    pub(crate) context_offset: [u8; 8],
    pub(crate) context_count: [u8; 8],
    pub(crate) entity_role_offset: [u8; 8],
    pub(crate) entity_role_count: [u8; 8],
    pub(crate) relation_role_offset: [u8; 8],
    pub(crate) relation_role_count: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct HyperQueryRecord {
    pub(crate) statement_id: [u8; 4],
    pub(crate) source: [u8; 4],
    pub(crate) target: [u8; 4],
    pub(crate) relation: [u8; 4],
    pub(crate) qualifier_context: [u8; 4],
    pub(crate) truth_group: [u8; 4],
    pub(crate) qualifier_offset: [u8; 4],
    pub(crate) qualifier_count: [u8; 4],
}

impl HyperQueryRecord {
    pub(crate) fn statement_id(self) -> u32 {
        u32::from_le_bytes(self.statement_id)
    }
    pub(crate) fn source(self) -> u32 {
        u32::from_le_bytes(self.source)
    }
    pub(crate) fn target(self) -> u32 {
        u32::from_le_bytes(self.target)
    }
    pub(crate) fn relation(self) -> u32 {
        u32::from_le_bytes(self.relation)
    }
    pub(crate) fn qualifier_context(self) -> u32 {
        u32::from_le_bytes(self.qualifier_context)
    }
    pub(crate) fn truth_group(self) -> u32 {
        u32::from_le_bytes(self.truth_group)
    }
    pub(crate) fn qualifier_offset(self) -> u32 {
        u32::from_le_bytes(self.qualifier_offset)
    }
    pub(crate) fn qualifier_count(self) -> u32 {
        u32::from_le_bytes(self.qualifier_count)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct HyperTruthGroupRecord {
    pub(crate) source: [u8; 4],
    pub(crate) relation: [u8; 4],
    pub(crate) qualifier_context: [u8; 4],
    pub(crate) target_offset: [u8; 4],
    pub(crate) target_count: [u8; 4],
}

impl HyperTruthGroupRecord {
    pub(crate) fn source(self) -> u32 {
        u32::from_le_bytes(self.source)
    }
    pub(crate) fn relation(self) -> u32 {
        u32::from_le_bytes(self.relation)
    }
    pub(crate) fn qualifier_context(self) -> u32 {
        u32::from_le_bytes(self.qualifier_context)
    }
    pub(crate) fn target_offset(self) -> u32 {
        u32::from_le_bytes(self.target_offset)
    }
    pub(crate) fn target_count(self) -> u32 {
        u32::from_le_bytes(self.target_count)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct HyperQualifierContextRecord {
    pub(crate) qualifier_offset: [u8; 4],
    pub(crate) qualifier_count: [u8; 4],
}

impl HyperQualifierContextRecord {
    pub(crate) fn qualifier_offset(self) -> u32 {
        u32::from_le_bytes(self.qualifier_offset)
    }
    pub(crate) fn qualifier_count(self) -> u32 {
        u32::from_le_bytes(self.qualifier_count)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct HyperLeU32(pub(crate) [u8; 4]);

impl HyperLeU32 {
    pub(crate) fn get(self) -> u32 {
        u32::from_le_bytes(self.0)
    }
}

pub(crate) fn mapped<T: FromBytes + Unaligned>(
    bytes: &[u8],
    offset: usize,
    count: usize,
) -> Result<Ref<&[u8], [T]>, HyperRelationalTaskError> {
    let end = count
        .checked_mul(size_of::<T>())
        .and_then(|length| offset.checked_add(length))
        .ok_or(HyperRelationalTaskError::CorruptArtifact("slice"))?;
    Ref::new_slice(
        bytes
            .get(offset..end)
            .ok_or(HyperRelationalTaskError::CorruptArtifact("slice"))?,
    )
    .ok_or(HyperRelationalTaskError::CorruptArtifact("slice"))
}
