use std::{
    collections::BTreeSet,
    fs::{File, OpenOptions},
    io::{Seek, SeekFrom, Write},
    path::Path,
};

use bytemuck::{Pod, Zeroable, cast_slice};
use memchr::memmem;
use memmap2::{Mmap, MmapOptions};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

use crate::{
    Digest, Error, FEATURE_TAPE_V1, FeatureCellState, RUNRAW_TAPE_V1, Result, SourceStatus,
    TapeIdentity, identity,
};

const HEADER_BYTES: usize = 64 * 1024;
const RUNRAW_MAGIC: &[u8; 8] = b"NSRRT1\0\0";
const FEATURE_MAGIC: &[u8; 8] = b"NSRFT1\0\0";

#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
pub struct RunRawRow {
    pub source_row_id: u64,
    pub event_time: i64,
    pub knowledge_time: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub tick_volume: f64,
    pub spread: f64,
    pub instrument_id: u32,
    pub source_id: u32,
    pub session_id: u32,
    pub trading_day: u32,
    pub source_clock: u8,
    pub source_status: u8,
    pub reserved: [u8; 6],
}

impl RunRawRow {
    #[inline]
    pub fn status(self) -> SourceStatus {
        SourceStatus::from_code(self.source_status)
    }

    pub fn validate(self) -> Result<()> {
        if self.source_status > SourceStatus::Censored as u8 {
            return Err(Error::InvalidContract(format!(
                "row {} has unknown source status {}",
                self.source_row_id, self.source_status
            )));
        }
        if self.event_time > self.knowledge_time {
            return Err(Error::InvalidContract(format!(
                "row {} has knowledge_time before event_time",
                self.source_row_id
            )));
        }
        if ![
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.tick_volume,
            self.spread,
        ]
        .iter()
        .all(|value| value.is_finite())
        {
            return Err(Error::InvalidContract(format!(
                "row {} contains a non-finite authority value",
                self.source_row_id
            )));
        }
        if self.low > self.high
            || self.open < self.low
            || self.open > self.high
            || self.close < self.low
            || self.close > self.high
        {
            return Err(Error::InvalidContract(format!(
                "row {} violates OHLC bounds",
                self.source_row_id
            )));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct RunRawHeader {
    pub identity: TapeIdentity,
    pub row_stride: u32,
    pub storage: String,
}

pub struct MappedRunRawTape {
    mmap: Mmap,
    header: RunRawHeader,
}

impl MappedRunRawTape {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let file = File::open(path)?;
        // SAFETY: the mapping is read-only and retained for the lifetime of all returned slices.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        let header = decode_header::<RunRawHeader>(&mmap, RUNRAW_MAGIC)?;
        if header.row_stride as usize != size_of::<RunRawRow>() {
            return Err(Error::InvalidTape("RunRaw row stride mismatch".into()));
        }
        let expected = HEADER_BYTES
            .checked_add(header.identity.row_count as usize * size_of::<RunRawRow>())
            .ok_or_else(|| Error::InvalidTape("RunRaw size overflow".into()))?;
        if mmap.len() != expected {
            return Err(Error::InvalidTape(format!(
                "RunRaw length {} does not match declared {expected}",
                mmap.len()
            )));
        }
        let rows = bytemuck::try_cast_slice::<u8, RunRawRow>(&mmap[HEADER_BYTES..])
            .map_err(|error| Error::InvalidTape(format!("RunRaw alignment: {error}")))?;
        if Digest::hash(b"northstar-runraw-rows-v1", cast_slice(rows))
            != header.identity.content_hash
        {
            return Err(Error::InvalidTape("RunRaw content hash mismatch".into()));
        }
        Ok(Self { mmap, header })
    }

    pub fn header(&self) -> &RunRawHeader {
        &self.header
    }

    pub fn rows(&self) -> &[RunRawRow] {
        bytemuck::cast_slice(&self.mmap[HEADER_BYTES..])
    }

    pub fn tape_id(&self) -> Result<Digest> {
        identity(b"northstar-runraw-tape-identity-v1", &self.header.identity)
    }
}

pub fn seal_runraw(
    path: impl AsRef<Path>,
    source_manifest_hash: Digest,
    rows: &[RunRawRow],
) -> Result<RunRawHeader> {
    if rows.is_empty() {
        return Err(Error::InvalidContract("RunRaw cannot be empty".into()));
    }
    let mut instruments = BTreeSet::new();
    let mut sources = BTreeSet::new();
    let mut last_key = None;
    for row in rows {
        row.validate()?;
        let key = (row.event_time, row.source_id, row.source_row_id);
        if last_key.is_some_and(|previous| key <= previous) {
            return Err(Error::InvalidContract(
                "RunRaw rows are not strictly chronological".into(),
            ));
        }
        last_key = Some(key);
        instruments.insert(row.instrument_id);
        sources.insert(row.source_id);
    }
    let identity = TapeIdentity {
        schema_version: RUNRAW_TAPE_V1.into(),
        source_manifest_hash,
        row_count: rows.len() as u64,
        first_time: rows[0].event_time,
        last_time: rows[rows.len() - 1].event_time,
        instrument_set: instruments.into_iter().collect(),
        source_set: sources.into_iter().collect(),
        content_hash: Digest::hash(b"northstar-runraw-rows-v1", cast_slice(rows)),
    };
    let header = RunRawHeader {
        identity,
        row_stride: size_of::<RunRawRow>() as u32,
        storage: "fixed_width_little_endian_mmap_v1".into(),
    };
    write_tape(path, RUNRAW_MAGIC, &header, &[cast_slice(rows)])?;
    Ok(header)
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FeatureColumnMeta {
    pub feature_id: String,
    pub values_offset: u64,
    pub states_offset: u64,
    pub knowledge_times_offset: u64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FeatureTapeHeader {
    pub schema_version: String,
    pub runraw_tape_id: Digest,
    pub feature_registry_id: Digest,
    pub compiler_identity: Digest,
    pub row_count: u64,
    pub columns: Vec<FeatureColumnMeta>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug)]
pub struct FeatureColumn {
    pub feature_id: String,
    pub values: Vec<f64>,
    pub states: Vec<u8>,
    pub knowledge_times: Vec<i64>,
}

pub struct MappedFeatureTape {
    mmap: Mmap,
    header: FeatureTapeHeader,
}

impl MappedFeatureTape {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let file = File::open(path)?;
        // SAFETY: the mapping is read-only and retained by this owner.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        let header = decode_header::<FeatureTapeHeader>(&mmap, FEATURE_MAGIC)?;
        for column in &header.columns {
            validate_range(
                &mmap,
                column.values_offset,
                header.row_count,
                size_of::<f64>(),
            )?;
            validate_range(&mmap, column.states_offset, header.row_count, 1)?;
            validate_range(
                &mmap,
                column.knowledge_times_offset,
                header.row_count,
                size_of::<i64>(),
            )?;
        }
        let logical = logical_feature_bytes(&mmap, &header)?;
        if Digest::hash(b"northstar-feature-cells-v1", &logical) != header.content_hash {
            return Err(Error::InvalidTape(
                "Feature Tape content hash mismatch".into(),
            ));
        }
        Ok(Self { mmap, header })
    }

    pub fn header(&self) -> &FeatureTapeHeader {
        &self.header
    }

    pub fn tape_id(&self) -> Result<Digest> {
        identity(b"northstar-feature-tape-identity-v1", &self.header)
    }

    pub fn column(&self, feature_id: &str) -> Option<(&[f64], &[u8], &[i64])> {
        let meta = self
            .header
            .columns
            .iter()
            .find(|meta| meta.feature_id == feature_id)?;
        let count = self.header.row_count as usize;
        let values = bytemuck::cast_slice(
            &self.mmap[meta.values_offset as usize..meta.values_offset as usize + count * 8],
        );
        let states = &self.mmap[meta.states_offset as usize..meta.states_offset as usize + count];
        let knowledge = bytemuck::cast_slice(
            &self.mmap[meta.knowledge_times_offset as usize
                ..meta.knowledge_times_offset as usize + count * 8],
        );
        Some((values, states, knowledge))
    }

    pub fn cell(&self, feature_id: &str, row: usize) -> Option<(f64, FeatureCellState, i64)> {
        let (values, states, knowledge) = self.column(feature_id)?;
        Some((
            *values.get(row)?,
            FeatureCellState::from_code(*states.get(row)?),
            *knowledge.get(row)?,
        ))
    }
}

pub fn seal_feature_tape(
    path: impl AsRef<Path>,
    runraw_tape_id: Digest,
    feature_registry_id: Digest,
    compiler_identity: Digest,
    columns: &[FeatureColumn],
) -> Result<FeatureTapeHeader> {
    let row_count = columns.first().map_or(0, |column| column.values.len());
    if row_count == 0 || columns.is_empty() {
        return Err(Error::InvalidContract(
            "Feature Tape cannot be empty".into(),
        ));
    }
    let mut offset = HEADER_BYTES;
    let mut metadata = Vec::with_capacity(columns.len());
    let mut logical = Vec::new();
    for column in columns {
        if column.values.len() != row_count
            || column.states.len() != row_count
            || column.knowledge_times.len() != row_count
        {
            return Err(Error::InvalidContract(format!(
                "feature {} length mismatch",
                column.feature_id
            )));
        }
        offset = align8(offset);
        let values_offset = offset;
        let value_bytes: &[u8] = cast_slice(&column.values);
        offset += value_bytes.len();
        let states_offset = offset;
        offset += column.states.len();
        offset = align8(offset);
        let knowledge_times_offset = offset;
        let knowledge_bytes: &[u8] = cast_slice(&column.knowledge_times);
        offset += knowledge_bytes.len();
        logical.extend_from_slice(value_bytes);
        logical.extend_from_slice(&column.states);
        logical.extend_from_slice(knowledge_bytes);
        metadata.push(FeatureColumnMeta {
            feature_id: column.feature_id.clone(),
            values_offset: values_offset as u64,
            states_offset: states_offset as u64,
            knowledge_times_offset: knowledge_times_offset as u64,
        });
    }
    let header = FeatureTapeHeader {
        schema_version: FEATURE_TAPE_V1.into(),
        runraw_tape_id,
        feature_registry_id,
        compiler_identity,
        row_count: row_count as u64,
        columns: metadata,
        content_hash: Digest::hash(b"northstar-feature-cells-v1", &logical),
    };
    let mut file = create_file(path)?;
    encode_header(&mut file, FEATURE_MAGIC, &header)?;
    for (meta, column) in header.columns.iter().zip(columns) {
        write_at(&mut file, meta.values_offset, cast_slice(&column.values))?;
        write_at(&mut file, meta.states_offset, &column.states)?;
        write_at(
            &mut file,
            meta.knowledge_times_offset,
            cast_slice(&column.knowledge_times),
        )?;
    }
    file.sync_all()?;
    Ok(header)
}

fn logical_feature_bytes(mmap: &[u8], header: &FeatureTapeHeader) -> Result<Vec<u8>> {
    let count = header.row_count as usize;
    let mut logical = Vec::with_capacity(header.columns.len() * count * 17);
    for meta in &header.columns {
        logical.extend_from_slice(
            &mmap[meta.values_offset as usize..meta.values_offset as usize + count * 8],
        );
        logical.extend_from_slice(
            &mmap[meta.states_offset as usize..meta.states_offset as usize + count],
        );
        logical.extend_from_slice(
            &mmap[meta.knowledge_times_offset as usize
                ..meta.knowledge_times_offset as usize + count * 8],
        );
    }
    Ok(logical)
}

fn validate_range(mmap: &[u8], offset: u64, count: u64, stride: usize) -> Result<()> {
    let start =
        usize::try_from(offset).map_err(|_| Error::InvalidTape("offset overflow".into()))?;
    let bytes = usize::try_from(count)
        .ok()
        .and_then(|value| value.checked_mul(stride))
        .ok_or_else(|| Error::InvalidTape("range overflow".into()))?;
    if start < HEADER_BYTES || start.checked_add(bytes).is_none_or(|end| end > mmap.len()) {
        return Err(Error::InvalidTape("column outside Feature Tape".into()));
    }
    if stride == 8 && start % 8 != 0 {
        return Err(Error::InvalidTape("unaligned Feature Tape column".into()));
    }
    Ok(())
}

fn align8(value: usize) -> usize {
    (value + 7) & !7
}

fn write_tape<T: Serialize>(
    path: impl AsRef<Path>,
    magic: &[u8; 8],
    header: &T,
    sections: &[&[u8]],
) -> Result<()> {
    let mut file = create_file(path)?;
    encode_header(&mut file, magic, header)?;
    file.seek(SeekFrom::Start(HEADER_BYTES as u64))?;
    for section in sections {
        file.write_all(section)?;
    }
    file.sync_all()?;
    Ok(())
}

fn create_file(path: impl AsRef<Path>) -> Result<File> {
    let path = path.as_ref();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    Ok(OpenOptions::new()
        .create(true)
        .truncate(true)
        .read(true)
        .write(true)
        .open(path)?)
}

fn encode_header<T: Serialize>(file: &mut File, magic: &[u8; 8], header: &T) -> Result<()> {
    let json = serde_json::to_vec(header)?;
    if json.len() + 16 > HEADER_BYTES {
        return Err(Error::InvalidTape(
            "tape header exceeds reserved block".into(),
        ));
    }
    let mut block = vec![0_u8; HEADER_BYTES];
    block[..8].copy_from_slice(magic);
    block[8..16].copy_from_slice(&(json.len() as u64).to_le_bytes());
    block[16..16 + json.len()].copy_from_slice(&json);
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&block)?;
    Ok(())
}

fn decode_header<T: DeserializeOwned>(bytes: &[u8], magic: &[u8; 8]) -> Result<T> {
    if bytes.len() < HEADER_BYTES || memmem::find(&bytes[..8], magic) != Some(0) {
        return Err(Error::InvalidTape("tape magic mismatch".into()));
    }
    let length = u64::from_le_bytes(bytes[8..16].try_into().expect("fixed slice")) as usize;
    if length == 0 || length + 16 > HEADER_BYTES {
        return Err(Error::InvalidTape("invalid tape header length".into()));
    }
    Ok(serde_json::from_slice(&bytes[16..16 + length])?)
}

fn write_at(file: &mut File, offset: u64, bytes: &[u8]) -> Result<()> {
    file.seek(SeekFrom::Start(offset))?;
    file.write_all(bytes)?;
    Ok(())
}
