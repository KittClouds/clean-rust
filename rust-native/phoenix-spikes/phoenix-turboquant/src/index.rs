use std::fs::{File, OpenOptions};
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use memmap2::{Mmap, MmapOptions};

use crate::format::{
    align_up, quantizer_hash, ArtifactAuthority, ArtifactHeader, BLOCK_VECTORS, COMPLETE_FLAG,
    HEADER_BYTES, MAX_ARTIFACT_BYTES, MAX_DIMENSION, MAX_ROWS, SECTION_ALIGNMENT,
};
use crate::{
    encode_vectors, LloydMaxCodebook, PhaseTimings, QueryPreparationTimings, Result, Rotation,
    SearchExecution, SearchHit, SearchKernel, SearchScratch, TurboQuantError,
};

pub fn write_quantized_artifact_new(
    path: impl AsRef<Path>,
    authority: ArtifactAuthority,
    subject_ids: &[u64],
    vectors: &[f32],
    dimension: usize,
    bits: u8,
) -> Result<VerifiedQuantizedIndex> {
    validate_ids(subject_ids)?;
    let encoded = encode_vectors(vectors, subject_ids.len(), dimension, bits)?;
    let ids_bytes = ids_to_bytes(subject_ids);
    let scales_bytes = bytemuck::cast_slice::<f32, u8>(&encoded.scales);
    let ids_offset = align_up(HEADER_BYTES as u64, SECTION_ALIGNMENT);
    let codes_offset = align_up(
        ids_offset
            .checked_add(ids_bytes.len() as u64)
            .ok_or(TurboQuantError::Overflow)?,
        SECTION_ALIGNMENT,
    );
    let scales_offset = align_up(
        codes_offset
            .checked_add(encoded.codes.len() as u64)
            .ok_or(TurboQuantError::Overflow)?,
        SECTION_ALIGNMENT,
    );
    let total_len = align_up(
        scales_offset
            .checked_add(scales_bytes.len() as u64)
            .ok_or(TurboQuantError::Overflow)?,
        SECTION_ALIGNMENT,
    );
    if total_len > MAX_ARTIFACT_BYTES {
        return Err(TurboQuantError::InvalidLayout);
    }
    let mut header = ArtifactHeader {
        flags: COMPLETE_FLAG,
        format: encoded.format,
        dimension: dimension as u32,
        block_vectors: BLOCK_VECTORS as u32,
        row_count: subject_ids.len() as u64,
        padded_count: encoded.padded_count as u64,
        ids_offset,
        ids_len: ids_bytes.len() as u64,
        codes_offset,
        codes_len: encoded.codes.len() as u64,
        scales_offset,
        scales_len: scales_bytes.len() as u64,
        authority,
        quantizer_hash: quantizer_hash(
            encoded.format,
            dimension,
            &encoded.rotation,
            &encoded.codebook,
        ),
        rotation_hash: encoded.rotation.contract_hash(),
        codebook_hash: encoded.codebook.hash(),
        ids_hash: *blake3::hash(&ids_bytes).as_bytes(),
        codes_hash: *blake3::hash(&encoded.codes).as_bytes(),
        scales_hash: *blake3::hash(scales_bytes).as_bytes(),
        artifact_hash: [0; 32],
    };
    header.artifact_hash = header.compute_artifact_hash();
    publish_new(
        path.as_ref(),
        &header,
        &ids_bytes,
        &encoded.codes,
        scales_bytes,
        total_len,
    )?;
    VerifiedQuantizedIndex::open_expected(path, Some(authority))
}

fn publish_new(
    path: &Path,
    header: &ArtifactHeader,
    ids: &[u8],
    codes: &[u8],
    scales: &[u8],
    total_len: u64,
) -> Result<()> {
    if path.exists() {
        return Err(TurboQuantError::AlreadyExists(path.to_path_buf()));
    }
    let parent = path.parent().ok_or(TurboQuantError::InvalidLayout)?;
    std::fs::create_dir_all(parent).map_err(|source| TurboQuantError::io(parent, source))?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(TurboQuantError::InvalidLayout)?;
    let temporary = parent.join(format!(".{file_name}.{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|source| TurboQuantError::io(&temporary, source))?;
        file.set_len(total_len)
            .map_err(|source| TurboQuantError::io(&temporary, source))?;
        write_at(&mut file, 0, &header.encode(), &temporary)?;
        write_at(&mut file, header.ids_offset, ids, &temporary)?;
        write_at(&mut file, header.codes_offset, codes, &temporary)?;
        write_at(&mut file, header.scales_offset, scales, &temporary)?;
        file.sync_all()
            .map_err(|source| TurboQuantError::io(&temporary, source))?;
        drop(file);
        std::fs::rename(&temporary, path).map_err(|source| TurboQuantError::io(path, source))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn write_at(file: &mut File, offset: u64, bytes: &[u8], path: &Path) -> Result<()> {
    file.seek(SeekFrom::Start(offset))
        .map_err(|source| TurboQuantError::io(path, source))?;
    file.write_all(bytes)
        .map_err(|source| TurboQuantError::io(path, source))
}

pub struct VerifiedQuantizedIndex {
    path: PathBuf,
    mmap: Mmap,
    header: ArtifactHeader,
    codebook: LloydMaxCodebook,
    rotation: Rotation,
}

impl std::fmt::Debug for VerifiedQuantizedIndex {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("VerifiedQuantizedIndex")
            .field("path", &self.path)
            .field("bits", &self.header.format.bits())
            .field("dimension", &self.header.dimension)
            .field("rows", &self.header.row_count)
            .field("artifact_hash", &self.header.artifact_hash)
            .finish()
    }
}

impl VerifiedQuantizedIndex {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        Self::open_expected(path, None)
    }

    pub fn open_expected(
        path: impl AsRef<Path>,
        authority: Option<ArtifactAuthority>,
    ) -> Result<Self> {
        let path = path.as_ref();
        let file = File::open(path).map_err(|source| TurboQuantError::io(path, source))?;
        let actual_len = file
            .metadata()
            .map_err(|source| TurboQuantError::io(path, source))?
            .len();
        if actual_len < HEADER_BYTES as u64 {
            return Err(TurboQuantError::TooSmall);
        }
        if actual_len > MAX_ARTIFACT_BYTES {
            return Err(TurboQuantError::InvalidLayout);
        }
        // SAFETY: the mapping is read-only and retained by this owner. Every
        // range, typed view, hash, scalar, id, and derived contract is checked
        // before public borrowed slices or search operations are exposed.
        let mmap = unsafe {
            MmapOptions::new()
                .map(&file)
                .map_err(|source| TurboQuantError::io(path, source))?
        };
        let header = ArtifactHeader::decode(&mmap[..HEADER_BYTES])?;
        validate_header(&header, actual_len)?;
        if authority.is_some_and(|expected| expected != header.authority) {
            return Err(TurboQuantError::AuthorityMismatch("embedding authority"));
        }
        let codebook = LloydMaxCodebook::new(header.format.bits(), header.dimension as usize)?;
        let rotation = Rotation::new(header.dimension as usize)?;
        if codebook.hash() != header.codebook_hash {
            return Err(TurboQuantError::HashMismatch("codebook contract"));
        }
        if rotation.contract_hash() != header.rotation_hash {
            return Err(TurboQuantError::HashMismatch("rotation contract"));
        }
        if quantizer_hash(
            header.format,
            header.dimension as usize,
            &rotation,
            &codebook,
        ) != header.quantizer_hash
        {
            return Err(TurboQuantError::HashMismatch("quantizer contract"));
        }
        let index = Self {
            path: path.to_path_buf(),
            mmap,
            header,
            codebook,
            rotation,
        };
        index.verify_pages()?;
        Ok(index)
    }

    pub fn header(&self) -> &ArtifactHeader {
        &self.header
    }

    pub fn len(&self) -> usize {
        self.header.row_count as usize
    }

    pub fn is_empty(&self) -> bool {
        self.header.row_count == 0
    }

    pub fn dimension(&self) -> usize {
        self.header.dimension as usize
    }

    pub fn bits(&self) -> u8 {
        self.header.format.bits()
    }

    pub fn recommended_execution(&self) -> SearchExecution {
        crate::search::recommended_execution(self)
    }

    pub fn subject_ids(&self) -> Result<&[u64]> {
        bytemuck::try_cast_slice(self.section(self.header.ids_offset, self.header.ids_len)?)
            .map_err(|_| TurboQuantError::InvalidLayout)
    }

    pub fn search(
        &self,
        query: &[f32],
        top_k: usize,
        kernel: SearchKernel,
    ) -> Result<Vec<SearchHit>> {
        let mut scratch = SearchScratch::new(self.dimension(), top_k);
        let mut output = Vec::with_capacity(top_k);
        self.search_into(query, top_k, kernel, &mut scratch, &mut output)?;
        Ok(output)
    }

    pub fn search_into(
        &self,
        query: &[f32],
        top_k: usize,
        kernel: SearchKernel,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchKernel> {
        crate::search::search_quantized(self, query, top_k, kernel, scratch, output)
    }

    /// Search a small query batch while traversing and decoding each packed
    /// corpus block once. Run inside a persistent Rayon pool for a bounded CPU
    /// budget; the warmed path reuses all scratch and output allocations.
    pub fn search_batch_parallel_into<Q: AsRef<[f32]>>(
        &self,
        queries: &[Q],
        top_k: usize,
        kernel: SearchKernel,
        scratch: &mut crate::BatchSearchScratch,
        outputs: &mut [Vec<SearchHit>],
    ) -> Result<SearchKernel> {
        crate::search::search_batch_parallel(self, queries, top_k, kernel, scratch, outputs)
    }

    /// Exact batch search that reduces cache-sized score blocks into fixed
    /// local candidate sets instead of materializing a corpus-wide score slab.
    pub fn search_batch_block_local_into<Q: AsRef<[f32]>>(
        &self,
        queries: &[Q],
        top_k: usize,
        kernel: SearchKernel,
        config: crate::BlockLocalTopKConfig,
        scratch: &mut crate::BatchSearchScratch,
        outputs: &mut [Vec<SearchHit>],
    ) -> Result<SearchKernel> {
        crate::search::search_batch_block_local(
            self, queries, top_k, kernel, config, scratch, outputs,
        )
    }

    /// Instrumented block-local run. Per-chunk decode and selection values are
    /// summed worker time; wall fields preserve the parallel critical path.
    pub fn profile_batch_block_local_into<Q: AsRef<[f32]>>(
        &self,
        queries: &[Q],
        top_k: usize,
        kernel: SearchKernel,
        config: crate::BlockLocalTopKConfig,
        scratch: &mut crate::BatchSearchScratch,
        outputs: &mut [Vec<SearchHit>],
    ) -> Result<crate::BlockLocalPhaseTimings> {
        crate::search::profile_batch_block_local(
            self, queries, top_k, kernel, config, scratch, outputs,
        )
    }

    pub fn prepare_query(
        &self,
        query: &[f32],
        scratch: &mut SearchScratch,
    ) -> Result<QueryPreparationTimings> {
        crate::search::prepare_quantized_query(self, query, scratch)
    }

    pub fn search_prepared_into(
        &self,
        top_k: usize,
        kernel: SearchKernel,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchKernel> {
        crate::search::search_prepared(self, top_k, kernel, scratch, output)
    }

    pub fn search_prepared_with_execution_into(
        &self,
        top_k: usize,
        kernel: SearchKernel,
        execution: SearchExecution,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchKernel> {
        crate::search::search_prepared_with_execution(
            self, top_k, kernel, execution, scratch, output,
        )
    }

    pub fn profile_search_into(
        &self,
        query: &[f32],
        top_k: usize,
        kernel: SearchKernel,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<PhaseTimings> {
        crate::search::profile_quantized_search(self, query, top_k, kernel, scratch, output)
    }

    pub fn profile_parallel_search_into(
        &self,
        query: &[f32],
        top_k: usize,
        kernel: SearchKernel,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<PhaseTimings> {
        crate::search::profile_parallel_quantized_search(
            self, query, top_k, kernel, scratch, output,
        )
    }

    pub(crate) fn codes(&self) -> Result<&[u8]> {
        self.section(self.header.codes_offset, self.header.codes_len)
    }

    pub(crate) fn scales(&self) -> Result<&[f32]> {
        bytemuck::try_cast_slice(self.section(self.header.scales_offset, self.header.scales_len)?)
            .map_err(|_| TurboQuantError::InvalidLayout)
    }

    pub(crate) fn codebook(&self) -> &LloydMaxCodebook {
        &self.codebook
    }

    pub(crate) fn rotation(&self) -> &Rotation {
        &self.rotation
    }

    fn section(&self, offset: u64, length: u64) -> Result<&[u8]> {
        let end = offset
            .checked_add(length)
            .ok_or(TurboQuantError::InvalidLayout)?;
        let range = usize::try_from(offset).map_err(|_| TurboQuantError::InvalidLayout)?
            ..usize::try_from(end).map_err(|_| TurboQuantError::InvalidLayout)?;
        self.mmap.get(range).ok_or(TurboQuantError::InvalidLayout)
    }

    fn verify_pages(&self) -> Result<()> {
        let ids_bytes = self.section(self.header.ids_offset, self.header.ids_len)?;
        let codes = self.codes()?;
        let scales_bytes = self.section(self.header.scales_offset, self.header.scales_len)?;
        for (name, expected, actual) in [
            (
                "ids",
                self.header.ids_hash,
                *blake3::hash(ids_bytes).as_bytes(),
            ),
            (
                "codes",
                self.header.codes_hash,
                *blake3::hash(codes).as_bytes(),
            ),
            (
                "scales",
                self.header.scales_hash,
                *blake3::hash(scales_bytes).as_bytes(),
            ),
        ] {
            if expected != actual {
                return Err(TurboQuantError::HashMismatch(name));
            }
        }
        let ids = self.subject_ids()?;
        validate_ids(ids)?;
        for (row, scale) in self.scales()?.iter().copied().enumerate() {
            if !scale.is_finite() || scale < 0.0 {
                return Err(TurboQuantError::InvalidScale { row });
            }
        }
        validate_padding(&self.header, codes)?;
        Ok(())
    }
}

fn validate_header(header: &ArtifactHeader, actual_len: u64) -> Result<()> {
    if header.flags & COMPLETE_FLAG == 0 {
        return Err(TurboQuantError::IncompleteArtifact);
    }
    let dimension = header.dimension as u64;
    let rows = header.row_count;
    let padded = header.padded_count;
    let bytes_per_row = dimension
        .checked_mul(header.format.bits() as u64)
        .and_then(|value| value.checked_div(8))
        .ok_or(TurboQuantError::Overflow)?;
    let expected_total = align_up(
        header
            .scales_offset
            .checked_add(header.scales_len)
            .ok_or(TurboQuantError::Overflow)?,
        SECTION_ALIGNMENT,
    );
    if header.dimension == 0
        || header.dimension > MAX_DIMENSION
        || !header.dimension.is_multiple_of(8)
        || rows == 0
        || rows > MAX_ROWS
        || header.block_vectors != BLOCK_VECTORS as u32
        || padded != rows.next_multiple_of(BLOCK_VECTORS as u64)
        || !header.ids_offset.is_multiple_of(SECTION_ALIGNMENT)
        || !header.codes_offset.is_multiple_of(SECTION_ALIGNMENT)
        || !header.scales_offset.is_multiple_of(SECTION_ALIGNMENT)
        || header.ids_len != rows * 8
        || header.codes_len != padded * bytes_per_row
        || header.scales_len != rows * 4
        || header.ids_offset < HEADER_BYTES as u64
        || header.ids_offset + header.ids_len > header.codes_offset
        || header.codes_offset + header.codes_len > header.scales_offset
        || expected_total != actual_len
        || header.authority == ArtifactAuthority::default()
        || header.compute_artifact_hash() != header.artifact_hash
    {
        return Err(TurboQuantError::InvalidLayout);
    }
    Ok(())
}

fn validate_padding(header: &ArtifactHeader, codes: &[u8]) -> Result<()> {
    let rows = header.row_count as usize;
    let padded = header.padded_count as usize;
    if rows == padded {
        return Ok(());
    }
    let groups = header.dimension as usize / header.format.coordinates_per_byte();
    let final_block = rows / BLOCK_VECTORS;
    for group in 0..groups {
        let base = (final_block * groups + group) * BLOCK_VECTORS;
        if codes[base + rows % BLOCK_VECTORS..base + BLOCK_VECTORS]
            .iter()
            .any(|value| *value != 0)
        {
            return Err(TurboQuantError::InvalidLayout);
        }
    }
    Ok(())
}

fn validate_ids(ids: &[u64]) -> Result<()> {
    if ids.is_empty()
        || ids[0] == 0
        || ids
            .windows(2)
            .any(|pair| pair[0] == 0 || pair[0] >= pair[1])
    {
        return Err(TurboQuantError::NonCanonicalIds);
    }
    Ok(())
}

fn ids_to_bytes(ids: &[u64]) -> Vec<u8> {
    let mut output = Vec::with_capacity(ids.len() * 8);
    for id in ids {
        output.extend_from_slice(&id.to_le_bytes());
    }
    output
}
