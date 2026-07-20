use super::PhoenixOvergraphStore;
use crate::graph_learning_origin::{decode_model_slot, encode_model_slot};
use compact_str::CompactString;
use hashbrown::HashMap;
use memmap2::Mmap;
use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalStatus, GraphTruthAtomKey, GRAPH_PROPOSAL_FEATURE_DIM,
};
use phoenix_store_native_core::{
    GraphProposalReceiptAppend, PhoenixGraphLearningStore, StoreError,
};
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthKind, GraphTruthPlane,
    GraphTruthSourceGenerationRef,
};
use smallvec::SmallVec;
use std::fs::{File, OpenOptions};
use std::io::{Seek, SeekFrom, Write};
use std::mem::size_of;
use std::path::PathBuf;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};
const LOG_FILE_NAME: &str = "graph-proposal-receipts-v1.bin";
const RECORD_MAGIC: [u8; 8] = *b"PHXGPR01";
const NONE_SCORE: u16 = u16::MAX;
#[derive(Clone, Copy, Debug, Default)]
pub(super) struct RecordLocation {
    offset: usize,
    byte_len: usize,
}
#[derive(Default)]
pub(super) struct GraphProposalReceiptIndex {
    valid_byte_len: usize,
    offsets: HashMap<String, RecordLocation>,
}
#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct BinaryStringRef {
    offset: [u8; 4],
    len: [u8; 4],
}
impl BinaryStringRef {
    fn new(offset: usize, len: usize) -> Result<Self, StoreError> {
        Ok(Self {
            offset: checked_u32(offset, "string offset")?.to_le_bytes(),
            len: checked_u32(len, "string length")?.to_le_bytes(),
        })
    }

    fn range(self) -> Result<std::ops::Range<usize>, StoreError> {
        let start = u32::from_le_bytes(self.offset) as usize;
        let len = u32::from_le_bytes(self.len) as usize;
        let end = start
            .checked_add(len)
            .ok_or_else(|| StoreError::Snapshot("proposal string range overflow".to_owned()))?;
        Ok(start..end)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct ReceiptRecordHeader {
    magic: [u8; 8],
    total_len: [u8; 4],
    schema_version: [u8; 2],
    flags: [u8; 2],
    generation: [u8; 8],
    created_at: [u8; 8],
    proposal_count: [u8; 4],
    source_count: [u8; 4],
    evidence_count: [u8; 4],
    proposal_offset: [u8; 4],
    source_offset: [u8; 4],
    evidence_offset: [u8; 4],
    arena_offset: [u8; 4],
    arena_len: [u8; 4],
    receipt_id: BinaryStringRef,
    scope_key: BinaryStringRef,
    compiler_id: BinaryStringRef,
    compiler_version: BinaryStringRef,
    policy_id: BinaryStringRef,
    policy_version: BinaryStringRef,
    model_id: BinaryStringRef,
    payload_checksum: [u8; 8],
}
#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct ProposalRecord {
    proposal_id: BinaryStringRef,
    atom_left: BinaryStringRef,
    atom_right: BinaryStringRef,
    atom_relation: BinaryStringRef,
    family: BinaryStringRef,
    source_kind: BinaryStringRef,
    target_kind: BinaryStringRef,
    evidence_start: [u8; 4],
    evidence_count: [u8; 2],
    shadow_score_millis: [u8; 2],
    atom_kind: u8,
    truth_kind: u8,
    truth_plane: u8,
    status: u8,
    reserved: [u8; 4],
    features: [[u8; 2]; GRAPH_PROPOSAL_FEATURE_DIM],
}
#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct SourceGenerationRecord {
    source_id: BinaryStringRef,
    generation: [u8; 8],
}
#[derive(Clone, Copy)]
struct ArenaRef {
    offset: usize,
    len: usize,
}
#[derive(Default)]
struct StringArena {
    bytes: Vec<u8>,
    refs: HashMap<String, ArenaRef>,
}
impl StringArena {
    fn intern(&mut self, value: &str) -> ArenaRef {
        if value.is_empty() {
            return ArenaRef { offset: 0, len: 0 };
        }
        if let Some(reference) = self.refs.get(value) {
            return *reference;
        }
        let reference = ArenaRef {
            offset: self.bytes.len(),
            len: value.len(),
        };
        self.bytes.extend_from_slice(value.as_bytes());
        self.refs.insert(value.to_owned(), reference);
        reference
    }

    fn binary_ref(&self, value: &str, arena_offset: usize) -> Result<BinaryStringRef, StoreError> {
        if value.is_empty() {
            return BinaryStringRef::new(arena_offset, 0);
        }
        let reference = self.refs.get(value).ok_or_else(|| {
            StoreError::Snapshot(format!("proposal string was not interned: {value}"))
        })?;
        BinaryStringRef::new(arena_offset + reference.offset, reference.len)
    }
}

impl PhoenixOvergraphStore {
    pub(super) fn graph_proposal_receipt_log_path(&self) -> PathBuf {
        self.path.join(LOG_FILE_NAME)
    }

    fn refresh_graph_proposal_receipt_index(
        &self,
        index: &mut GraphProposalReceiptIndex,
    ) -> Result<(), StoreError> {
        let path = self.graph_proposal_receipt_log_path();
        let Some(mapped) = map_existing(&path)? else {
            index.valid_byte_len = 0;
            index.offsets.clear();
            return Ok(());
        };
        if index.valid_byte_len > mapped.len() {
            index.valid_byte_len = 0;
            index.offsets.clear();
        }
        let mut offset = index.valid_byte_len;
        while offset < mapped.len() {
            let Some(view) = ReceiptView::at(&mapped, offset)? else {
                break;
            };
            let receipt_id = view.string(view.header.receipt_id)?.to_owned();
            index.offsets.insert(
                receipt_id,
                RecordLocation {
                    offset,
                    byte_len: view.byte_len,
                },
            );
            offset += view.byte_len;
        }
        index.valid_byte_len = offset;
        Ok(())
    }

    fn append_graph_proposal_receipt_inner(
        &self,
        receipt: &GraphProposalBatchReceipt,
    ) -> Result<GraphProposalReceiptAppend, StoreError> {
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        let encoded = encode_receipt(receipt)?;
        let mut index = self
            .graph_proposal_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("graph proposal receipt index poisoned".to_owned()))?;
        self.refresh_graph_proposal_receipt_index(&mut index)?;
        if let Some(location) = index.offsets.get(receipt.receipt_id.as_str()).copied() {
            let existing = load_at_path(&self.graph_proposal_receipt_log_path(), location)?;
            if existing == *receipt {
                return Ok(GraphProposalReceiptAppend::AlreadyPresent {
                    receipt_id: receipt.receipt_id.to_string(),
                });
            }
            return Err(StoreError::Query(format!(
                "graph proposal receipt '{}' already stores different content",
                receipt.receipt_id
            )));
        }

        let path = self.graph_proposal_receipt_log_path();
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&path)
            .map_err(io_error)?;
        file.set_len(index.valid_byte_len as u64)
            .map_err(io_error)?;
        file.seek(SeekFrom::End(0)).map_err(io_error)?;
        file.write_all(&encoded).map_err(io_error)?;
        file.sync_data().map_err(io_error)?;
        let location = RecordLocation {
            offset: index.valid_byte_len,
            byte_len: encoded.len(),
        };
        index.valid_byte_len += encoded.len();
        index
            .offsets
            .insert(receipt.receipt_id.to_string(), location);
        Ok(GraphProposalReceiptAppend::Appended {
            byte_len: encoded.len(),
        })
    }

    fn load_graph_proposal_receipt_inner(
        &self,
        receipt_id: &str,
    ) -> Result<Option<GraphProposalBatchReceipt>, StoreError> {
        let mut index = self
            .graph_proposal_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("graph proposal receipt index poisoned".to_owned()))?;
        self.refresh_graph_proposal_receipt_index(&mut index)?;
        let Some(location) = index.offsets.get(receipt_id).copied() else {
            return Ok(None);
        };
        load_at_path(&self.graph_proposal_receipt_log_path(), location).map(Some)
    }

    fn load_graph_proposal_receipts_inner(
        &self,
    ) -> Result<Vec<GraphProposalBatchReceipt>, StoreError> {
        let mut index = self
            .graph_proposal_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("graph proposal receipt index poisoned".to_owned()))?;
        self.refresh_graph_proposal_receipt_index(&mut index)?;
        let mut locations = index.offsets.values().copied().collect::<Vec<_>>();
        locations.sort_unstable_by_key(|location| location.offset);
        let Some(mapped) = map_existing(&self.graph_proposal_receipt_log_path())? else {
            return Ok(Vec::new());
        };
        locations
            .into_iter()
            .map(|location| decode_location(&mapped, location))
            .collect()
    }
}

impl PhoenixGraphLearningStore for PhoenixOvergraphStore {
    fn append_graph_proposal_receipt(
        &self,
        receipt: &GraphProposalBatchReceipt,
    ) -> Result<GraphProposalReceiptAppend, StoreError> {
        self.append_graph_proposal_receipt_inner(receipt)
    }

    fn load_graph_proposal_receipt(
        &self,
        receipt_id: &str,
    ) -> Result<Option<GraphProposalBatchReceipt>, StoreError> {
        self.load_graph_proposal_receipt_inner(receipt_id)
    }

    fn load_graph_proposal_receipts(&self) -> Result<Vec<GraphProposalBatchReceipt>, StoreError> {
        self.load_graph_proposal_receipts_inner()
    }
}

fn encode_receipt(receipt: &GraphProposalBatchReceipt) -> Result<Vec<u8>, StoreError> {
    let mut arena = StringArena::default();
    let model_slot = encode_model_slot(receipt)?;
    for value in [
        receipt.receipt_id.as_str(),
        receipt.scope_key.as_str(),
        receipt.compiler_policy.compiler_id.as_str(),
        receipt.compiler_policy.compiler_version.as_str(),
        receipt.compiler_policy.policy_id.as_str(),
        receipt.compiler_policy.policy_version.as_str(),
        model_slot.as_str(),
    ] {
        arena.intern(value);
    }
    for source in &receipt.source_generations {
        arena.intern(source.source_id.as_str());
    }
    for proposal in &receipt.proposals {
        arena.intern(proposal.proposal_id.as_str());
        for value in atom_strings(&proposal.atom) {
            arena.intern(value);
        }
        for value in [
            proposal.family.as_str(),
            proposal.source_kind.as_str(),
            proposal.target_kind.as_str(),
        ] {
            arena.intern(value);
        }
        for evidence in &proposal.evidence_refs {
            arena.intern(evidence.as_str());
        }
    }

    let header_len = size_of::<ReceiptRecordHeader>();
    let proposal_offset = header_len;
    let source_offset = proposal_offset + receipt.proposals.len() * size_of::<ProposalRecord>();
    let evidence_count = receipt
        .proposals
        .iter()
        .map(|proposal| proposal.evidence_refs.len())
        .sum::<usize>();
    let evidence_offset =
        source_offset + receipt.source_generations.len() * size_of::<SourceGenerationRecord>();
    let arena_offset = evidence_offset + evidence_count * size_of::<BinaryStringRef>();
    let total_len = arena_offset
        .checked_add(arena.bytes.len())
        .ok_or_else(|| StoreError::Snapshot("proposal receipt length overflow".to_owned()))?;

    let mut payload = Vec::with_capacity(total_len - header_len);
    let mut evidence_start = 0usize;
    for proposal in &receipt.proposals {
        let atom = atom_binary_parts(&proposal.atom, &arena, arena_offset)?;
        let mut features = [[0_u8; 2]; GRAPH_PROPOSAL_FEATURE_DIM];
        for (slot, value) in features.iter_mut().zip(proposal.features.0) {
            *slot = value.to_le_bytes();
        }
        let row = ProposalRecord {
            proposal_id: arena.binary_ref(proposal.proposal_id.as_str(), arena_offset)?,
            atom_left: atom.1,
            atom_right: atom.2,
            atom_relation: atom.3,
            family: arena.binary_ref(proposal.family.as_str(), arena_offset)?,
            source_kind: arena.binary_ref(proposal.source_kind.as_str(), arena_offset)?,
            target_kind: arena.binary_ref(proposal.target_kind.as_str(), arena_offset)?,
            evidence_start: checked_u32(evidence_start, "evidence start")?.to_le_bytes(),
            evidence_count: checked_u16(proposal.evidence_refs.len(), "evidence count")?
                .to_le_bytes(),
            shadow_score_millis: proposal
                .shadow_score_millis
                .unwrap_or(NONE_SCORE)
                .to_le_bytes(),
            atom_kind: atom.0,
            truth_kind: truth_kind_code(proposal.truth.kind),
            truth_plane: truth_plane_code(proposal.truth.plane),
            status: proposal_status_code(proposal.status),
            reserved: [0; 4],
            features,
        };
        payload.extend_from_slice(row.as_bytes());
        evidence_start += proposal.evidence_refs.len();
    }
    for source in &receipt.source_generations {
        let row = SourceGenerationRecord {
            source_id: arena.binary_ref(source.source_id.as_str(), arena_offset)?,
            generation: source.generation.to_le_bytes(),
        };
        payload.extend_from_slice(row.as_bytes());
    }
    for proposal in &receipt.proposals {
        for evidence in &proposal.evidence_refs {
            payload.extend_from_slice(
                arena
                    .binary_ref(evidence.as_str(), arena_offset)?
                    .as_bytes(),
            );
        }
    }
    payload.extend_from_slice(&arena.bytes);

    let header = ReceiptRecordHeader {
        magic: RECORD_MAGIC,
        total_len: checked_u32(total_len, "record length")?.to_le_bytes(),
        schema_version: receipt.schema_version.to_le_bytes(),
        flags: [0; 2],
        generation: receipt.generation.to_le_bytes(),
        created_at: receipt.created_at.to_le_bytes(),
        proposal_count: checked_u32(receipt.proposals.len(), "proposal count")?.to_le_bytes(),
        source_count: checked_u32(receipt.source_generations.len(), "source count")?.to_le_bytes(),
        evidence_count: checked_u32(evidence_count, "evidence count")?.to_le_bytes(),
        proposal_offset: checked_u32(proposal_offset, "proposal offset")?.to_le_bytes(),
        source_offset: checked_u32(source_offset, "source offset")?.to_le_bytes(),
        evidence_offset: checked_u32(evidence_offset, "evidence offset")?.to_le_bytes(),
        arena_offset: checked_u32(arena_offset, "arena offset")?.to_le_bytes(),
        arena_len: checked_u32(arena.bytes.len(), "arena length")?.to_le_bytes(),
        receipt_id: arena.binary_ref(receipt.receipt_id.as_str(), arena_offset)?,
        scope_key: arena.binary_ref(receipt.scope_key.as_str(), arena_offset)?,
        compiler_id: arena
            .binary_ref(receipt.compiler_policy.compiler_id.as_str(), arena_offset)?,
        compiler_version: arena.binary_ref(
            receipt.compiler_policy.compiler_version.as_str(),
            arena_offset,
        )?,
        policy_id: arena.binary_ref(receipt.compiler_policy.policy_id.as_str(), arena_offset)?,
        policy_version: arena.binary_ref(
            receipt.compiler_policy.policy_version.as_str(),
            arena_offset,
        )?,
        model_id: arena.binary_ref(model_slot.as_str(), arena_offset)?,
        payload_checksum: checksum64(&payload).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_len);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(&payload);
    Ok(bytes)
}

struct ReceiptView<'a> {
    record: &'a [u8],
    header: ReceiptRecordHeader,
    byte_len: usize,
}

impl<'a> ReceiptView<'a> {
    fn at(bytes: &'a [u8], offset: usize) -> Result<Option<Self>, StoreError> {
        if bytes.len().saturating_sub(offset) < size_of::<ReceiptRecordHeader>() {
            return Ok(None);
        }
        let header_slice = &bytes[offset..offset + size_of::<ReceiptRecordHeader>()];
        let header = *Ref::<_, ReceiptRecordHeader>::new_unaligned(header_slice)
            .ok_or_else(|| StoreError::Snapshot("invalid proposal receipt header".to_owned()))?;
        if header.magic != RECORD_MAGIC {
            return Err(StoreError::Snapshot(format!(
                "invalid proposal receipt magic at byte {offset}"
            )));
        }
        let byte_len = u32::from_le_bytes(header.total_len) as usize;
        if byte_len < size_of::<ReceiptRecordHeader>() {
            return Err(StoreError::Snapshot(
                "short proposal receipt record".to_owned(),
            ));
        }
        let Some(end) = offset.checked_add(byte_len) else {
            return Err(StoreError::Snapshot(
                "proposal receipt offset overflow".to_owned(),
            ));
        };
        if end > bytes.len() {
            return Ok(None);
        }
        let record = &bytes[offset..end];
        let payload = &record[size_of::<ReceiptRecordHeader>()..];
        if checksum64(payload) != u64::from_le_bytes(header.payload_checksum) {
            return Err(StoreError::Snapshot(
                "proposal receipt checksum mismatch".to_owned(),
            ));
        }
        let view = Self {
            record,
            header,
            byte_len,
        };
        view.validate_ranges()?;
        Ok(Some(view))
    }

    fn validate_ranges(&self) -> Result<(), StoreError> {
        let proposal_offset = u32::from_le_bytes(self.header.proposal_offset) as usize;
        let source_offset = u32::from_le_bytes(self.header.source_offset) as usize;
        let evidence_offset = u32::from_le_bytes(self.header.evidence_offset) as usize;
        let arena_offset = u32::from_le_bytes(self.header.arena_offset) as usize;
        let arena_len = u32::from_le_bytes(self.header.arena_len) as usize;
        let proposal_end = proposal_offset
            + u32::from_le_bytes(self.header.proposal_count) as usize * size_of::<ProposalRecord>();
        let source_end = source_offset
            + u32::from_le_bytes(self.header.source_count) as usize
                * size_of::<SourceGenerationRecord>();
        let evidence_end = evidence_offset
            + u32::from_le_bytes(self.header.evidence_count) as usize
                * size_of::<BinaryStringRef>();
        let arena_end = arena_offset
            .checked_add(arena_len)
            .ok_or_else(|| StoreError::Snapshot("proposal arena overflow".to_owned()))?;
        if proposal_offset != size_of::<ReceiptRecordHeader>()
            || proposal_end != source_offset
            || source_end != evidence_offset
            || evidence_end != arena_offset
            || arena_end != self.record.len()
        {
            return Err(StoreError::Snapshot(
                "invalid proposal receipt table layout".to_owned(),
            ));
        }
        Ok(())
    }

    fn string(&self, reference: BinaryStringRef) -> Result<&'a str, StoreError> {
        let range = reference.range()?;
        let arena_start = u32::from_le_bytes(self.header.arena_offset) as usize;
        let arena_end = arena_start + u32::from_le_bytes(self.header.arena_len) as usize;
        if range.start < arena_start || range.end > arena_end {
            return Err(StoreError::Snapshot(
                "proposal string outside string arena".to_owned(),
            ));
        }
        let bytes = self
            .record
            .get(range)
            .ok_or_else(|| StoreError::Snapshot("proposal string outside arena".to_owned()))?;
        std::str::from_utf8(bytes)
            .map_err(|error| StoreError::Snapshot(format!("proposal string utf8: {error}")))
    }

    fn row<T>(&self, offset: usize) -> Result<T, StoreError>
    where
        T: FromBytes + Unaligned + Copy,
    {
        let bytes = self
            .record
            .get(offset..offset + size_of::<T>())
            .ok_or_else(|| StoreError::Snapshot("proposal table row out of bounds".to_owned()))?;
        Ref::<_, T>::new_unaligned(bytes)
            .map(|value| *value)
            .ok_or_else(|| StoreError::Snapshot("invalid proposal table row".to_owned()))
    }
}

fn decode_location(
    mapped: &[u8],
    location: RecordLocation,
) -> Result<GraphProposalBatchReceipt, StoreError> {
    let view = ReceiptView::at(mapped, location.offset)?
        .filter(|view| view.byte_len == location.byte_len)
        .ok_or_else(|| StoreError::Snapshot("missing proposal receipt record".to_owned()))?;
    decode_view(&view)
}

fn decode_view(view: &ReceiptView<'_>) -> Result<GraphProposalBatchReceipt, StoreError> {
    let source_count = u32::from_le_bytes(view.header.source_count) as usize;
    let source_offset = u32::from_le_bytes(view.header.source_offset) as usize;
    let mut source_generations = SmallVec::with_capacity(source_count);
    for index in 0..source_count {
        let row: SourceGenerationRecord =
            view.row(source_offset + index * size_of::<SourceGenerationRecord>())?;
        source_generations.push(GraphTruthSourceGenerationRef {
            source_id: CompactString::new(view.string(row.source_id)?),
            generation: u64::from_le_bytes(row.generation),
        });
    }

    let proposal_count = u32::from_le_bytes(view.header.proposal_count) as usize;
    let proposal_offset = u32::from_le_bytes(view.header.proposal_offset) as usize;
    let evidence_offset = u32::from_le_bytes(view.header.evidence_offset) as usize;
    let evidence_total = u32::from_le_bytes(view.header.evidence_count) as usize;
    let mut proposals = Vec::with_capacity(proposal_count);
    for index in 0..proposal_count {
        let row: ProposalRecord =
            view.row(proposal_offset + index * size_of::<ProposalRecord>())?;
        let evidence_start = u32::from_le_bytes(row.evidence_start) as usize;
        let evidence_count = u16::from_le_bytes(row.evidence_count) as usize;
        if evidence_start.saturating_add(evidence_count) > evidence_total {
            return Err(StoreError::Snapshot(
                "proposal evidence range out of bounds".to_owned(),
            ));
        }
        let mut evidence_refs = SmallVec::with_capacity(evidence_count);
        for evidence_index in evidence_start..evidence_start + evidence_count {
            let reference: BinaryStringRef =
                view.row(evidence_offset + evidence_index * size_of::<BinaryStringRef>())?;
            evidence_refs.push(CompactString::new(view.string(reference)?));
        }
        let mut features = [0_i16; GRAPH_PROPOSAL_FEATURE_DIM];
        for (slot, value) in features.iter_mut().zip(row.features) {
            *slot = i16::from_le_bytes(value);
        }
        let score = u16::from_le_bytes(row.shadow_score_millis);
        proposals.push(GraphProposalObservation {
            proposal_id: CompactString::new(view.string(row.proposal_id)?),
            atom: decode_atom(view, row)?,
            family: CompactString::new(view.string(row.family)?),
            source_kind: CompactString::new(view.string(row.source_kind)?),
            target_kind: CompactString::new(view.string(row.target_kind)?),
            truth: GraphTruthDescriptor {
                kind: decode_truth_kind(row.truth_kind)?,
                plane: decode_truth_plane(row.truth_plane)?,
            },
            status: decode_proposal_status(row.status)?,
            evidence_refs,
            features: GraphProposalFeatures(features),
            shadow_score_millis: (score != NONE_SCORE).then_some(score),
        });
    }

    let (model_id, discovery_origin) = decode_model_slot(view.string(view.header.model_id)?)?;
    let receipt = GraphProposalBatchReceipt {
        schema_version: u16::from_le_bytes(view.header.schema_version),
        receipt_id: CompactString::new(view.string(view.header.receipt_id)?),
        scope_key: CompactString::new(view.string(view.header.scope_key)?),
        generation: u64::from_le_bytes(view.header.generation),
        created_at: i64::from_le_bytes(view.header.created_at),
        compiler_policy: GraphTruthCompilerPolicy {
            compiler_id: CompactString::new(view.string(view.header.compiler_id)?),
            compiler_version: CompactString::new(view.string(view.header.compiler_version)?),
            policy_id: CompactString::new(view.string(view.header.policy_id)?),
            policy_version: CompactString::new(view.string(view.header.policy_version)?),
        },
        source_generations,
        model_id,
        discovery_origin,
        proposals,
    };
    receipt
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(receipt)
}

fn decode_atom(
    view: &ReceiptView<'_>,
    row: ProposalRecord,
) -> Result<GraphTruthAtomKey, StoreError> {
    match row.atom_kind {
        1 => Ok(GraphTruthAtomKey::vertex(view.string(row.atom_left)?)),
        2 => Ok(GraphTruthAtomKey::edge(
            view.string(row.atom_left)?,
            view.string(row.atom_right)?,
            view.string(row.atom_relation)?,
        )),
        value => Err(StoreError::Snapshot(format!(
            "invalid proposal atom kind {value}"
        ))),
    }
}

fn load_at_path(
    path: &PathBuf,
    location: RecordLocation,
) -> Result<GraphProposalBatchReceipt, StoreError> {
    let mapped = map_existing(path)?
        .ok_or_else(|| StoreError::Snapshot("proposal receipt log is missing".to_owned()))?;
    decode_location(&mapped, location)
}

fn map_existing(path: &PathBuf) -> Result<Option<Mmap>, StoreError> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(io_error(error)),
    };
    if file.metadata().map_err(io_error)?.len() == 0 {
        return Ok(None);
    }
    // The append lock prevents writes while this read-only map is alive.
    unsafe { Mmap::map(&file) }.map(Some).map_err(io_error)
}

fn atom_strings(atom: &GraphTruthAtomKey) -> [&str; 3] {
    match atom {
        GraphTruthAtomKey::Vertex { vertex_id } => [vertex_id.as_str(), "", ""],
        GraphTruthAtomKey::Edge {
            source_id,
            target_id,
            edge_type,
        } => [source_id.as_str(), target_id.as_str(), edge_type.as_str()],
    }
}

fn atom_binary_parts(
    atom: &GraphTruthAtomKey,
    arena: &StringArena,
    arena_offset: usize,
) -> Result<(u8, BinaryStringRef, BinaryStringRef, BinaryStringRef), StoreError> {
    let values = atom_strings(atom);
    Ok((
        if matches!(atom, GraphTruthAtomKey::Vertex { .. }) {
            1
        } else {
            2
        },
        arena.binary_ref(values[0], arena_offset)?,
        arena.binary_ref(values[1], arena_offset)?,
        arena.binary_ref(values[2], arena_offset)?,
    ))
}

fn truth_kind_code(kind: GraphTruthKind) -> u8 {
    match kind {
        GraphTruthKind::Structural => 1,
        GraphTruthKind::Identity => 2,
        GraphTruthKind::Assertion => 3,
        GraphTruthKind::Temporal => 4,
        GraphTruthKind::Causal => 5,
        GraphTruthKind::Semantic => 6,
    }
}

fn decode_truth_kind(value: u8) -> Result<GraphTruthKind, StoreError> {
    match value {
        1 => Ok(GraphTruthKind::Structural),
        2 => Ok(GraphTruthKind::Identity),
        3 => Ok(GraphTruthKind::Assertion),
        4 => Ok(GraphTruthKind::Temporal),
        5 => Ok(GraphTruthKind::Causal),
        6 => Ok(GraphTruthKind::Semantic),
        _ => Err(StoreError::Snapshot(format!(
            "invalid proposal truth kind {value}"
        ))),
    }
}

fn truth_plane_code(plane: Option<GraphTruthPlane>) -> u8 {
    match plane {
        None => 0,
        Some(GraphTruthPlane::WorldState) => 1,
        Some(GraphTruthPlane::Reported) => 2,
        Some(GraphTruthPlane::Conditional) => 3,
        Some(GraphTruthPlane::Hypothetical) => 4,
        Some(GraphTruthPlane::Planned) => 5,
        Some(GraphTruthPlane::Mixed) => 6,
        Some(GraphTruthPlane::Unknown) => 7,
    }
}

fn decode_truth_plane(value: u8) -> Result<Option<GraphTruthPlane>, StoreError> {
    match value {
        0 => Ok(None),
        1 => Ok(Some(GraphTruthPlane::WorldState)),
        2 => Ok(Some(GraphTruthPlane::Reported)),
        3 => Ok(Some(GraphTruthPlane::Conditional)),
        4 => Ok(Some(GraphTruthPlane::Hypothetical)),
        5 => Ok(Some(GraphTruthPlane::Planned)),
        6 => Ok(Some(GraphTruthPlane::Mixed)),
        7 => Ok(Some(GraphTruthPlane::Unknown)),
        _ => Err(StoreError::Snapshot(format!(
            "invalid proposal truth plane {value}"
        ))),
    }
}

fn proposal_status_code(status: GraphProposalStatus) -> u8 {
    match status {
        GraphProposalStatus::Generated => 1,
        GraphProposalStatus::ReviewedSupport => 2,
        GraphProposalStatus::ReviewedContradiction => 3,
        GraphProposalStatus::Deferred => 4,
        GraphProposalStatus::Rejected => 5,
    }
}

fn decode_proposal_status(value: u8) -> Result<GraphProposalStatus, StoreError> {
    match value {
        1 => Ok(GraphProposalStatus::Generated),
        2 => Ok(GraphProposalStatus::ReviewedSupport),
        3 => Ok(GraphProposalStatus::ReviewedContradiction),
        4 => Ok(GraphProposalStatus::Deferred),
        5 => Ok(GraphProposalStatus::Rejected),
        _ => Err(StoreError::Snapshot(format!(
            "invalid proposal status {value}"
        ))),
    }
}

fn checksum64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for byte in bytes {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    hash
}

fn checked_u32(value: usize, field: &str) -> Result<u32, StoreError> {
    u32::try_from(value).map_err(|_| StoreError::Snapshot(format!("{field} exceeds binary format")))
}

fn checked_u16(value: usize, field: &str) -> Result<u16, StoreError> {
    u16::try_from(value).map_err(|_| StoreError::Snapshot(format!("{field} exceeds binary format")))
}

fn io_error(error: std::io::Error) -> StoreError {
    StoreError::Query(format!("graph proposal receipt log: {error}"))
}
