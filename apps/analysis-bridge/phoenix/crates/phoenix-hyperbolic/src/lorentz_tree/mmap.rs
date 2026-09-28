use memmap2::Mmap;
use roaring::RoaringBitmap;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};

use super::error::{LorentzResult, LorentzTreeError};
use super::forest::LorentzForest;
use super::index::{LorentzForestIndex, LorentzMembershipRow};
use super::model::{
    LorentzNode, LorentzScoreConfig, LorentzTree, LorentzTreeKind, LorentzTreeMembership,
    LorentzTreeQuery,
};
use super::score::LorentzCandidateScore;

const MAGIC: &[u8; 8] = b"LORH4F01";
const VERSION: u32 = 1;
const HEADER_LEN: usize = 20;

#[derive(Debug)]
pub struct MmapLorentzForestIndex {
    _mmap: Mmap,
    index: LorentzForestIndex,
}

impl MmapLorentzForestIndex {
    pub fn write_forest_to_file(
        forest: &LorentzForest,
        path: impl AsRef<Path>,
    ) -> LorentzResult<PathBuf> {
        let index = LorentzForestIndex::from_forest(forest)?;
        Self::write_index_to_file(&index, path)
    }

    pub fn write_index_to_file(
        index: &LorentzForestIndex,
        path: impl AsRef<Path>,
    ) -> LorentzResult<PathBuf> {
        let payload = bincode::serialize(&PackedLorentzIndex::from_index(index)?)?;
        let mut bytes = Vec::with_capacity(HEADER_LEN + payload.len());
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(&VERSION.to_le_bytes());
        bytes.extend_from_slice(&(payload.len() as u64).to_le_bytes());
        bytes.extend_from_slice(&payload);

        let path = path.as_ref().to_path_buf();
        let mut file = OpenOptions::new()
            .create(true)
            .write(true)
            .read(true)
            .truncate(true)
            .open(&path)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        Ok(path)
    }

    pub fn open(path: impl AsRef<Path>) -> LorentzResult<Self> {
        let file = OpenOptions::new().read(true).open(path.as_ref())?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() < HEADER_LEN {
            return Err(LorentzTreeError::InvalidMmap("short header".to_owned()));
        }
        if &mmap[0..8] != MAGIC {
            return Err(LorentzTreeError::InvalidMmap("bad magic".to_owned()));
        }
        let version = u32::from_le_bytes(
            mmap[8..12]
                .try_into()
                .map_err(|_| LorentzTreeError::InvalidMmap("bad version bytes".to_owned()))?,
        );
        if version != VERSION {
            return Err(LorentzTreeError::InvalidMmap(format!(
                "unsupported version {version}"
            )));
        }
        let payload_len =
            u64::from_le_bytes(mmap[12..20].try_into().map_err(|_| {
                LorentzTreeError::InvalidMmap("bad payload length bytes".to_owned())
            })?) as usize;
        let end = HEADER_LEN
            .checked_add(payload_len)
            .ok_or_else(|| LorentzTreeError::InvalidMmap("payload length overflow".to_owned()))?;
        if end > mmap.len() {
            return Err(LorentzTreeError::InvalidMmap(
                "truncated payload".to_owned(),
            ));
        }
        let packed: PackedLorentzIndex = bincode::deserialize(&mmap[HEADER_LEN..end])?;
        let index = packed.into_index()?;
        Ok(Self { _mmap: mmap, index })
    }

    pub fn index(&self) -> &LorentzForestIndex {
        &self.index
    }

    pub fn rank(
        &self,
        query: &LorentzTreeQuery,
        config: LorentzScoreConfig,
    ) -> LorentzResult<Vec<LorentzCandidateScore<String>>> {
        self.index.rank(query, config)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PackedLorentzIndex {
    nodes: Vec<LorentzNode>,
    trees: Vec<LorentzTree>,
    memberships: Vec<LorentzTreeMembership>,
    rows: Vec<LorentzMembershipRow>,
    child_offsets: Vec<u32>,
    child_memberships: Vec<u32>,
    all_members: Vec<u8>,
    tree_members: Vec<PackedBitmapU32>,
    kind_trees: Vec<PackedBitmapKind>,
    level_members: Vec<PackedBitmapU32>,
    node_members: Vec<PackedBitmapU32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PackedBitmapU32 {
    key: u32,
    bytes: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PackedBitmapKind {
    kind: LorentzTreeKind,
    bytes: Vec<u8>,
}

impl PackedLorentzIndex {
    fn from_index(index: &LorentzForestIndex) -> LorentzResult<Self> {
        Ok(Self {
            nodes: index.nodes.clone(),
            trees: index.trees.clone(),
            memberships: index.memberships.clone(),
            rows: index.rows.clone(),
            child_offsets: index.child_offsets.clone(),
            child_memberships: index.child_memberships.clone(),
            all_members: bitmap_to_bytes(&index.all_members)?,
            tree_members: pack_u32_bitmaps(&index.tree_members)?,
            kind_trees: pack_kind_bitmaps(&index.kind_trees)?,
            level_members: pack_u32_bitmaps(&index.level_members)?,
            node_members: pack_u32_bitmaps(&index.node_members)?,
        })
    }

    fn into_index(self) -> LorentzResult<LorentzForestIndex> {
        let rebuilt = LorentzForestIndex::from_parts(self.nodes, self.trees, self.memberships)?;
        if rebuilt.rows != self.rows {
            return Err(LorentzTreeError::InvalidMmap(
                "membership rows failed deterministic rebuild".to_owned(),
            ));
        }
        if rebuilt.child_offsets != self.child_offsets
            || rebuilt.child_memberships != self.child_memberships
        {
            return Err(LorentzTreeError::InvalidMmap(
                "child ranges failed deterministic rebuild".to_owned(),
            ));
        }
        if rebuilt.all_members != bitmap_from_bytes(&self.all_members)? {
            return Err(LorentzTreeError::InvalidMmap(
                "all-members bitmap mismatch".to_owned(),
            ));
        }
        validate_u32_bitmaps(&rebuilt.tree_members, &self.tree_members, "tree members")?;
        validate_kind_bitmaps(&rebuilt.kind_trees, &self.kind_trees)?;
        validate_u32_bitmaps(&rebuilt.level_members, &self.level_members, "level members")?;
        validate_u32_bitmaps(&rebuilt.node_members, &self.node_members, "node members")?;
        Ok(rebuilt)
    }
}

fn pack_u32_bitmaps(map: &BTreeMap<u32, RoaringBitmap>) -> LorentzResult<Vec<PackedBitmapU32>> {
    map.iter()
        .map(|(key, bitmap)| {
            Ok(PackedBitmapU32 {
                key: *key,
                bytes: bitmap_to_bytes(bitmap)?,
            })
        })
        .collect()
}

fn pack_kind_bitmaps(
    map: &BTreeMap<LorentzTreeKind, RoaringBitmap>,
) -> LorentzResult<Vec<PackedBitmapKind>> {
    map.iter()
        .map(|(kind, bitmap)| {
            Ok(PackedBitmapKind {
                kind: *kind,
                bytes: bitmap_to_bytes(bitmap)?,
            })
        })
        .collect()
}

fn validate_u32_bitmaps(
    expected: &BTreeMap<u32, RoaringBitmap>,
    packed: &[PackedBitmapU32],
    label: &str,
) -> LorentzResult<()> {
    let mut actual = BTreeMap::new();
    for entry in packed {
        actual.insert(entry.key, bitmap_from_bytes(&entry.bytes)?);
    }
    if expected != &actual {
        return Err(LorentzTreeError::InvalidMmap(format!(
            "{label} bitmap mismatch"
        )));
    }
    Ok(())
}

fn validate_kind_bitmaps(
    expected: &BTreeMap<LorentzTreeKind, RoaringBitmap>,
    packed: &[PackedBitmapKind],
) -> LorentzResult<()> {
    let mut actual = BTreeMap::new();
    for entry in packed {
        actual.insert(entry.kind, bitmap_from_bytes(&entry.bytes)?);
    }
    if expected != &actual {
        return Err(LorentzTreeError::InvalidMmap(
            "kind bitmap mismatch".to_owned(),
        ));
    }
    Ok(())
}

fn bitmap_to_bytes(bitmap: &RoaringBitmap) -> LorentzResult<Vec<u8>> {
    let mut bytes = Vec::new();
    bitmap.serialize_into(&mut bytes)?;
    Ok(bytes)
}

fn bitmap_from_bytes(bytes: &[u8]) -> LorentzResult<RoaringBitmap> {
    Ok(RoaringBitmap::deserialize_from(Cursor::new(bytes))?)
}
