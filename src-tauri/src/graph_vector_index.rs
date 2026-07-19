use hashbrown::HashMap;
use memmap2::{Mmap, MmapOptions};
use std::time::Instant;
use tauri::{
    ipc::{Invoke, InvokeBody, InvokeError, Response},
    Runtime,
};

const REQUEST_MAGIC: &[u8; 8] = b"PHXVIDX2";
const RESPONSE_MAGIC: &[u8; 8] = b"PHXVOUT2";
const VERSION: u16 = 2;
const REQUEST_HEADER_BYTES: usize = 64;
const RESPONSE_HEADER_BYTES: usize = 104;
const MAX_RESIDENT_ROWS: usize = 250_000;
const MAX_DIMENSIONS: usize = 4_096;
const MAX_VECTOR_BYTES: usize = 512 * 1024 * 1024;

#[derive(Debug)]
struct PackedIndexRequest {
    rows: usize,
    dimensions: usize,
    generation: u64,
    neighborhood_k: usize,
    lsh_bands: usize,
    lsh_bits: usize,
    max_candidates: usize,
    minimum_similarity: f64,
    nonce: u32,
    target_hashes: Vec<u32>,
    lexical_ranks: Vec<u32>,
    vectors: Mmap,
    digest: [u8; 32],
}

struct BuildOutput {
    neighborhoods: Vec<Vec<(u32, i32)>>,
    evaluated_pairs: u64,
    digest: [u8; 32],
    nonce: u32,
    rows: usize,
    dimensions: usize,
    generation: u64,
    neighborhood_k: usize,
    used_simd: bool,
    duration_micros: u64,
}

pub(crate) fn handle_packed_invoke<R: Runtime>(invoke: Invoke<R>) -> bool {
    let body = invoke.message.payload().clone();
    invoke.resolver.respond_async(async move {
        let bytes = tauri::async_runtime::spawn_blocking(move || {
            let packet = match body {
                InvokeBody::Raw(bytes) => PackedIndexRequest::parse(&bytes)?,
                InvokeBody::Json(_) => {
                    return Err("packed vector index requires an octet-stream body".into())
                }
            };
            build_index(packet)?.encode()
        })
        .await
        .map_err(|error| InvokeError::from(format!("native vector index worker failed: {error}")))?
        .map_err(InvokeError::from)?;
        Ok(Response::new(bytes))
    });
    true
}

impl PackedIndexRequest {
    fn parse(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() < REQUEST_HEADER_BYTES || &bytes[..8] != REQUEST_MAGIC {
            return Err("packed vector index request magic is invalid".into());
        }
        let version = read_u16(bytes, 8)?;
        let header_bytes = read_u16(bytes, 10)? as usize;
        let flags = read_u32(bytes, 12)?;
        let rows = read_u32(bytes, 16)? as usize;
        let dimensions = read_u32(bytes, 20)? as usize;
        let generation = read_u64(bytes, 24)?;
        let neighborhood_k = read_u16(bytes, 32)? as usize;
        let lsh_bands = read_u16(bytes, 34)? as usize;
        let lsh_bits = read_u16(bytes, 36)? as usize;
        let max_candidates = read_u16(bytes, 38)? as usize;
        let minimum_similarity = read_f64(bytes, 40)?;
        let hashes_bytes = read_u32(bytes, 48)? as usize;
        let ranks_bytes = read_u32(bytes, 52)? as usize;
        let vector_bytes = read_u32(bytes, 56)? as usize;
        let nonce = read_u32(bytes, 60)?;
        if version != VERSION || header_bytes != REQUEST_HEADER_BYTES || flags != 1 {
            return Err("packed vector index request version or flags are invalid".into());
        }
        if rows == 0 || rows > MAX_RESIDENT_ROWS {
            return Err(format!(
                "packed vector index rows must be within 1..={MAX_RESIDENT_ROWS}"
            ));
        }
        if dimensions == 0 || dimensions > MAX_DIMENSIONS {
            return Err(format!(
                "packed vector index dimensions must be within 1..={MAX_DIMENSIONS}"
            ));
        }
        if !(1..=64).contains(&neighborhood_k)
            || !(1..=12).contains(&lsh_bands)
            || !(4..=20).contains(&lsh_bits)
            || !(neighborhood_k..=512).contains(&max_candidates)
            || !minimum_similarity.is_finite()
            || !(-1.0..=1.0).contains(&minimum_similarity)
        {
            return Err("packed vector index options are outside their bounded contract".into());
        }
        let expected_hashes = checked_product(rows, 4, "target hashes")?;
        let expected_ranks = checked_product(rows, 4, "lexical ranks")?;
        let expected_values = checked_product(
            checked_product(rows, dimensions, "vector elements")?,
            4,
            "vector bytes",
        )?;
        if hashes_bytes != expected_hashes
            || ranks_bytes != expected_ranks
            || vector_bytes != expected_values
            || vector_bytes > MAX_VECTOR_BYTES
        {
            return Err("packed vector index section lengths are invalid".into());
        }
        let expected_total = header_bytes
            .checked_add(hashes_bytes)
            .and_then(|value| value.checked_add(ranks_bytes))
            .and_then(|value| value.checked_add(vector_bytes))
            .ok_or_else(|| "packed vector index request length overflow".to_string())?;
        if bytes.len() != expected_total {
            return Err("packed vector index request length drift".into());
        }

        let hashes_offset = header_bytes;
        let ranks_offset = hashes_offset + hashes_bytes;
        let vectors_offset = ranks_offset + ranks_bytes;
        let target_hashes = read_u32_page(&bytes[hashes_offset..ranks_offset]);
        let lexical_ranks = read_u32_page(&bytes[ranks_offset..vectors_offset]);
        validate_lexical_ranks(&lexical_ranks)?;
        let mut mmap = MmapOptions::new()
            .len(vector_bytes)
            .map_anon()
            .map_err(|error| format!("allocate vector mmap: {error}"))?;
        mmap.copy_from_slice(&bytes[vectors_offset..]);
        let vectors = mmap
            .make_read_only()
            .map_err(|error| format!("seal vector mmap: {error}"))?;
        validate_vectors(&vectors, rows, dimensions)?;
        let digest = *blake3::hash(bytes).as_bytes();
        Ok(Self {
            rows,
            dimensions,
            generation,
            neighborhood_k,
            lsh_bands,
            lsh_bits,
            max_candidates,
            minimum_similarity,
            nonce,
            target_hashes,
            lexical_ranks,
            vectors,
            digest,
        })
    }

    fn values(&self) -> &[f32] {
        debug_assert_eq!(self.vectors.len() % std::mem::size_of::<f32>(), 0);
        debug_assert_eq!(
            (self.vectors.as_ptr() as usize) % std::mem::align_of::<f32>(),
            0
        );
        // SAFETY: anonymous mmap bases are page aligned, its length is a multiple of four,
        // and every value was copied from the little-endian Float32 packet before sealing.
        unsafe {
            std::slice::from_raw_parts(
                self.vectors.as_ptr().cast::<f32>(),
                self.vectors.len() / std::mem::size_of::<f32>(),
            )
        }
    }
}

fn build_index(request: PackedIndexRequest) -> Result<BuildOutput, String> {
    build_index_with(request, cosine_row, simd_available())
}

fn build_index_with(
    request: PackedIndexRequest,
    score_row: fn(&[f32], usize, usize, usize) -> f64,
    used_simd: bool,
) -> Result<BuildOutput, String> {
    let started = Instant::now();
    let signatures = build_signatures(&request);
    let buckets = build_buckets(&request, &signatures);
    let mut candidate_rows = vec![0_u32; request.max_candidates];
    let mut candidate_marks = vec![0_u32; request.rows];
    let mut top_rows = vec![0_u32; request.neighborhood_k];
    let mut top_scores = vec![0_f64; request.neighborhood_k];
    let mut neighborhoods = Vec::with_capacity(request.rows);
    let mut evaluated_pairs = 0_u64;

    for source in 0..request.rows {
        let mut candidate_count = 0;
        let mark = source as u32 + 1;
        for band in 0..request.lsh_bands {
            if candidate_count >= request.max_candidates {
                break;
            }
            let signature = signatures[source * request.lsh_bands + band];
            let key = bucket_key(band, request.lsh_bits, signature)?;
            if let Some(bucket) = buckets.get(&key) {
                candidate_count = add_bucket_candidates(
                    &mut candidate_rows,
                    &mut candidate_marks,
                    candidate_count,
                    bucket,
                    source,
                    request.target_hashes[source],
                    request.max_candidates,
                    mark,
                );
            }
        }
        let mut top_count = 0;
        for &target in &candidate_rows[..candidate_count] {
            evaluated_pairs += 1;
            let score = score_row(
                request.values(),
                request.dimensions,
                source,
                target as usize,
            );
            if score < request.minimum_similarity {
                continue;
            }
            top_count = insert_neighbor(
                &mut top_rows,
                &mut top_scores,
                top_count,
                target,
                score,
                &request.lexical_ranks,
            );
        }
        let mut row = Vec::with_capacity(top_count);
        for rank in 0..top_count {
            row.push((top_rows[rank], quantize_score(top_scores[rank])));
        }
        neighborhoods.push(row);
    }
    Ok(BuildOutput {
        neighborhoods,
        evaluated_pairs,
        digest: request.digest,
        nonce: request.nonce,
        rows: request.rows,
        dimensions: request.dimensions,
        generation: request.generation,
        neighborhood_k: request.neighborhood_k,
        used_simd,
        duration_micros: started.elapsed().as_micros().min(u64::MAX as u128) as u64,
    })
}

fn build_signatures(request: &PackedIndexRequest) -> Vec<u32> {
    let values = request.values();
    let mut signatures = vec![0_u32; request.rows * request.lsh_bands];
    for row in 0..request.rows {
        let offset = row * request.dimensions;
        for band in 0..request.lsh_bands {
            let mut signature = 0_u32;
            for bit in 0..request.lsh_bits {
                let dimension = lsh_dimension(band, bit, request.dimensions);
                if values[offset + dimension] >= 0.0 {
                    signature |= 1 << bit;
                }
            }
            signatures[row * request.lsh_bands + band] = signature;
        }
    }
    signatures
}

fn build_buckets(request: &PackedIndexRequest, signatures: &[u32]) -> HashMap<u32, Vec<u32>> {
    let mut buckets = HashMap::with_capacity(request.rows * request.lsh_bands / 2);
    for row in 0..request.rows {
        for band in 0..request.lsh_bands {
            let signature = signatures[row * request.lsh_bands + band];
            let key = ((band as u32) << request.lsh_bits) | signature;
            buckets.entry(key).or_insert_with(Vec::new).push(row as u32);
        }
    }
    buckets
}

#[allow(clippy::too_many_arguments)]
fn add_bucket_candidates(
    out: &mut [u32],
    marks: &mut [u32],
    mut count: usize,
    bucket: &[u32],
    source: usize,
    source_hash: u32,
    limit: usize,
    mark: u32,
) -> usize {
    if bucket.len() < 2 || count >= limit {
        return count;
    }
    let start = source_hash as usize % bucket.len();
    for step in 0..bucket.len() {
        if count >= limit {
            break;
        }
        let candidate = bucket[(start + step) % bucket.len()] as usize;
        if candidate == source || marks[candidate] == mark {
            continue;
        }
        marks[candidate] = mark;
        out[count] = candidate as u32;
        count += 1;
    }
    count
}

fn insert_neighbor(
    rows: &mut [u32],
    scores: &mut [f64],
    count: usize,
    row: u32,
    score: f64,
    lexical_ranks: &[u32],
) -> usize {
    let mut insertion = count;
    while insertion > 0
        && ranks_before(
            score,
            row,
            scores[insertion - 1],
            rows[insertion - 1],
            lexical_ranks,
        )
    {
        insertion -= 1;
    }
    if insertion >= rows.len() {
        return count;
    }
    let next_count = rows.len().min(count + 1);
    for index in (insertion + 1..next_count).rev() {
        rows[index] = rows[index - 1];
        scores[index] = scores[index - 1];
    }
    rows[insertion] = row;
    scores[insertion] = score;
    next_count
}

fn ranks_before(
    score: f64,
    row: u32,
    other_score: f64,
    other_row: u32,
    lexical_ranks: &[u32],
) -> bool {
    score > other_score
        || (score == other_score && lexical_ranks[row as usize] < lexical_ranks[other_row as usize])
}

fn cosine_row(values: &[f32], dimensions: usize, left: usize, right: usize) -> f64 {
    #[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
    if std::is_x86_feature_detected!("avx2") {
        // SAFETY: AVX2 is detected at runtime and row bounds were validated with the packet.
        return unsafe { cosine_row_avx2(values, dimensions, left, right) };
    }
    cosine_row_scalar(values, dimensions, left, right)
}

fn cosine_row_scalar(values: &[f32], dimensions: usize, left: usize, right: usize) -> f64 {
    let left_offset = left * dimensions;
    let right_offset = right * dimensions;
    let mut dot = 0_f64;
    for dimension in 0..dimensions {
        dot += values[left_offset + dimension] as f64 * values[right_offset + dimension] as f64;
    }
    dot.clamp(-1.0, 1.0)
}

#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
#[target_feature(enable = "avx2")]
unsafe fn cosine_row_avx2(values: &[f32], dimensions: usize, left: usize, right: usize) -> f64 {
    #[cfg(target_arch = "x86")]
    use std::arch::x86::{
        __m256d, _mm256_add_pd, _mm256_cvtps_pd, _mm256_mul_pd, _mm256_setzero_pd,
        _mm256_storeu_pd, _mm_loadu_ps,
    };
    #[cfg(target_arch = "x86_64")]
    use std::arch::x86_64::{
        __m256d, _mm256_add_pd, _mm256_cvtps_pd, _mm256_mul_pd, _mm256_setzero_pd,
        _mm256_storeu_pd, _mm_loadu_ps,
    };
    let left_offset = left * dimensions;
    let right_offset = right * dimensions;
    let mut accumulator: __m256d = _mm256_setzero_pd();
    let mut dimension = 0;
    while dimension + 4 <= dimensions {
        let left4 = _mm_loadu_ps(values.as_ptr().add(left_offset + dimension));
        let right4 = _mm_loadu_ps(values.as_ptr().add(right_offset + dimension));
        let product = _mm256_mul_pd(_mm256_cvtps_pd(left4), _mm256_cvtps_pd(right4));
        accumulator = _mm256_add_pd(accumulator, product);
        dimension += 4;
    }
    let mut lanes = [0_f64; 4];
    _mm256_storeu_pd(lanes.as_mut_ptr(), accumulator);
    let mut dot = lanes[0] + lanes[1] + lanes[2] + lanes[3];
    while dimension < dimensions {
        dot += values[left_offset + dimension] as f64 * values[right_offset + dimension] as f64;
        dimension += 1;
    }
    dot.clamp(-1.0, 1.0)
}

fn simd_available() -> bool {
    #[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
    {
        std::is_x86_feature_detected!("avx2")
    }
    #[cfg(not(any(target_arch = "x86", target_arch = "x86_64")))]
    {
        false
    }
}

impl BuildOutput {
    fn encode(&self) -> Result<Vec<u8>, String> {
        let row_stride = 4_usize
            .checked_add(
                self.neighborhood_k
                    .checked_mul(8)
                    .ok_or("response row overflow")?,
            )
            .ok_or("response row overflow")?;
        let total = RESPONSE_HEADER_BYTES
            .checked_add(
                self.rows
                    .checked_mul(row_stride)
                    .ok_or("response length overflow")?,
            )
            .ok_or("response length overflow")?;
        let mut bytes = vec![0_u8; total];
        bytes[..8].copy_from_slice(RESPONSE_MAGIC);
        write_u16(&mut bytes, 8, VERSION);
        write_u16(&mut bytes, 10, RESPONSE_HEADER_BYTES as u16);
        write_u32(&mut bytes, 12, u32::from(self.used_simd));
        write_u32(&mut bytes, 16, self.rows as u32);
        write_u32(&mut bytes, 20, self.dimensions as u32);
        write_u32(&mut bytes, 24, self.neighborhood_k as u32);
        write_u32(&mut bytes, 28, row_stride as u32);
        write_u64(&mut bytes, 32, self.evaluated_pairs);
        let neighbor_count = self.neighborhoods.iter().map(Vec::len).sum::<usize>();
        write_u64(&mut bytes, 40, neighbor_count as u64);
        write_u64(&mut bytes, 48, self.duration_micros);
        write_u64(&mut bytes, 56, self.generation);
        write_u32(&mut bytes, 64, self.nonce);
        bytes[72..104].copy_from_slice(&self.digest);
        for (source, row) in self.neighborhoods.iter().enumerate() {
            let row_offset = RESPONSE_HEADER_BYTES + source * row_stride;
            write_u16(&mut bytes, row_offset, row.len() as u16);
            for (rank, &(target, score)) in row.iter().enumerate() {
                let entry_offset = row_offset + 4 + rank * 8;
                write_u32(&mut bytes, entry_offset, target);
                bytes[entry_offset + 4..entry_offset + 8].copy_from_slice(&score.to_le_bytes());
            }
        }
        Ok(bytes)
    }
}

fn validate_vectors(bytes: &[u8], rows: usize, dimensions: usize) -> Result<(), String> {
    for row in 0..rows {
        let mut norm_squared = 0_f64;
        for dimension in 0..dimensions {
            let offset = (row * dimensions + dimension) * 4;
            let value = f32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap());
            if !value.is_finite() {
                return Err(format!(
                    "packed vector row {row} contains a non-finite value"
                ));
            }
            norm_squared += value as f64 * value as f64;
        }
        let norm = norm_squared.sqrt();
        if !(norm > 0.0) || (norm - 1.0).abs() > 0.025 {
            return Err(format!("packed vector row {row} is not unit normalized"));
        }
    }
    Ok(())
}

fn validate_lexical_ranks(ranks: &[u32]) -> Result<(), String> {
    for &rank in ranks {
        if rank as usize >= ranks.len() {
            return Err("packed vector lexical rank is outside the row set".into());
        }
    }
    Ok(())
}

fn read_u32_page(bytes: &[u8]) -> Vec<u32> {
    bytes
        .chunks_exact(4)
        .map(|word| u32::from_le_bytes(word.try_into().unwrap()))
        .collect()
}

fn lsh_dimension(band: usize, bit: usize, dimensions: usize) -> usize {
    ((band as u64 + 1) * 2_654_435_761_u64 + (bit as u64 + 1) * 2_246_822_519_u64)
        .wrapping_rem(dimensions as u64) as usize
}

fn bucket_key(band: usize, bits: usize, signature: u32) -> Result<u32, String> {
    ((band as u32) << bits)
        .checked_add(signature)
        .ok_or_else(|| "packed vector bucket key overflow".to_string())
}

fn quantize_score(score: f64) -> i32 {
    ((score.clamp(-1.0, 1.0) * 1_000_000.0) + 0.5).floor() as i32
}

fn checked_product(left: usize, right: usize, label: &str) -> Result<usize, String> {
    left.checked_mul(right)
        .ok_or_else(|| format!("packed vector {label} overflow"))
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, String> {
    Ok(u16::from_le_bytes(read_array(bytes, offset)?))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, String> {
    Ok(u32::from_le_bytes(read_array(bytes, offset)?))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, String> {
    Ok(u64::from_le_bytes(read_array(bytes, offset)?))
}

fn read_f64(bytes: &[u8], offset: usize) -> Result<f64, String> {
    Ok(f64::from_le_bytes(read_array(bytes, offset)?))
}

fn read_array<const N: usize>(bytes: &[u8], offset: usize) -> Result<[u8; N], String> {
    bytes
        .get(offset..offset + N)
        .ok_or_else(|| "packed vector header is truncated".to_string())?
        .try_into()
        .map_err(|_| "packed vector header width drift".to_string())
}

fn write_u16(bytes: &mut [u8], offset: usize, value: u16) {
    bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn write_u64(bytes: &mut [u8], offset: usize, value: u64) {
    bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scalar_and_simd_scores_have_identical_micro_receipts() {
        let dimensions = 31;
        let mut values = Vec::with_capacity(dimensions * 2);
        for index in 0..dimensions * 2 {
            values.push(((index * 37 % 101) as f32 - 50.0) / 300.0);
        }
        normalize_row(&mut values[..dimensions]);
        normalize_row(&mut values[dimensions..]);
        let scalar = cosine_row_scalar(&values, dimensions, 0, 1);
        let fast = cosine_row(&values, dimensions, 0, 1);
        assert!((scalar - fast).abs() < 1e-12);
        assert_eq!(quantize_score(scalar), quantize_score(fast));
    }

    #[test]
    fn scalar_oracle_and_runtime_kernel_build_identical_neighborhoods() {
        let scalar = build_index_with(fixture_request(240, 64, 8, 48), cosine_row_scalar, false)
            .expect("build scalar oracle");
        let runtime =
            build_index(fixture_request(240, 64, 8, 48)).expect("build runtime neighborhoods");
        assert_eq!(runtime.evaluated_pairs, scalar.evaluated_pairs);
        assert_eq!(runtime.neighborhoods, scalar.neighborhoods);
    }

    #[test]
    fn runtime_kernel_matches_the_typescript_neighborhood_golden() {
        let rows = 240;
        let dimensions = 8;
        let mut target_ids = (0..rows)
            .map(|row| format!("embed:chunk:note-scale:block:{row}"))
            .collect::<Vec<_>>();
        target_ids.sort();
        let mut lexical_order = (0..rows).collect::<Vec<_>>();
        lexical_order.sort_by(|left, right| target_ids[*left].cmp(&target_ids[*right]));
        let mut lexical_ranks = vec![0_u32; rows];
        for (rank, row) in lexical_order.into_iter().enumerate() {
            lexical_ranks[row] = rank as u32;
        }
        let mut bytes = fixture_packet(rows, dimensions, 4, 12);
        let hashes_offset = REQUEST_HEADER_BYTES;
        let ranks_offset = hashes_offset + rows * 4;
        let vectors_offset = ranks_offset + rows * 4;
        for row in 0..rows {
            write_u32(
                &mut bytes,
                hashes_offset + row * 4,
                hash_text(&target_ids[row]),
            );
            write_u32(&mut bytes, ranks_offset + row * 4, lexical_ranks[row]);
            let mut vector = [0_f32; 8];
            vector[0] = 1.0;
            vector[1] = (row % 3) as f32 * 0.05;
            vector[2] = ((row + 1) % 3) as f32 * 0.025;
            normalize_row(&mut vector);
            for (dimension, value) in vector.iter().enumerate() {
                let offset = vectors_offset + (row * dimensions + dimension) * 4;
                bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            }
        }
        let output = build_index(PackedIndexRequest::parse(&bytes).unwrap()).unwrap();
        assert_eq!(
            neighborhood_hash(&target_ids, &output.neighborhoods),
            0x64db_fb68
        );
    }

    #[test]
    #[ignore = "release-only 25K x 768 performance receipt"]
    fn packed_25k_by_768_performance_receipt() {
        let bytes = fixture_packet(25_000, 768, 8, 96);
        let ingest_started = Instant::now();
        let request = PackedIndexRequest::parse(&bytes).expect("ingest 25K packed page");
        let ingest_ms = ingest_started.elapsed().as_secs_f64() * 1_000.0;
        let output = build_index(request).expect("build 25K packed index");
        eprintln!(
            "[native-vector-index] ingest_ms={ingest_ms:.3} build_ms={:.3} pairs={}",
            output.duration_micros as f64 / 1_000.0,
            output.evaluated_pairs,
        );
        assert!(output.evaluated_pairs <= 25_000 * 96);
        assert!(output.neighborhoods.iter().all(|row| row.len() <= 8));
    }

    #[test]
    fn packed_request_builds_bounded_rows_and_receipt() {
        let request = fixture_request(48, 16, 4, 12);
        let output = build_index(request).expect("build native packed index");
        assert_eq!(output.neighborhoods.len(), 48);
        assert!(output.neighborhoods.iter().all(|row| row.len() <= 4));
        assert!(output.evaluated_pairs <= 48 * 12);
        let encoded = output.encode().expect("encode native response");
        assert_eq!(&encoded[..8], RESPONSE_MAGIC);
        assert_eq!(encoded.len(), RESPONSE_HEADER_BYTES + 48 * (4 + 4 * 8));
    }

    #[test]
    fn packed_request_rejects_length_and_rank_drift() {
        let mut bytes = fixture_packet(8, 4, 2, 4);
        bytes.pop();
        assert!(PackedIndexRequest::parse(&bytes)
            .unwrap_err()
            .contains("length drift"));
        let mut bytes = fixture_packet(8, 4, 2, 4);
        let ranks_offset = REQUEST_HEADER_BYTES + 8 * 4;
        write_u32(&mut bytes, ranks_offset + 4, 8);
        assert!(PackedIndexRequest::parse(&bytes)
            .unwrap_err()
            .contains("outside the row set"));
    }

    fn fixture_request(
        rows: usize,
        dimensions: usize,
        k: usize,
        max_candidates: usize,
    ) -> PackedIndexRequest {
        PackedIndexRequest::parse(&fixture_packet(rows, dimensions, k, max_candidates)).unwrap()
    }

    fn fixture_packet(rows: usize, dimensions: usize, k: usize, max_candidates: usize) -> Vec<u8> {
        let vector_bytes = rows * dimensions * 4;
        let mut bytes = vec![0_u8; REQUEST_HEADER_BYTES + rows * 8 + vector_bytes];
        bytes[..8].copy_from_slice(REQUEST_MAGIC);
        write_u16(&mut bytes, 8, VERSION);
        write_u16(&mut bytes, 10, REQUEST_HEADER_BYTES as u16);
        write_u32(&mut bytes, 12, 1);
        write_u32(&mut bytes, 16, rows as u32);
        write_u32(&mut bytes, 20, dimensions as u32);
        write_u64(&mut bytes, 24, 7);
        write_u16(&mut bytes, 32, k as u16);
        write_u16(&mut bytes, 34, 4);
        write_u16(&mut bytes, 36, 10);
        write_u16(&mut bytes, 38, max_candidates as u16);
        bytes[40..48].copy_from_slice(&(-1_f64).to_le_bytes());
        write_u32(&mut bytes, 48, (rows * 4) as u32);
        write_u32(&mut bytes, 52, (rows * 4) as u32);
        write_u32(&mut bytes, 56, vector_bytes as u32);
        write_u32(&mut bytes, 60, 99);
        let hashes_offset = REQUEST_HEADER_BYTES;
        let ranks_offset = hashes_offset + rows * 4;
        let vectors_offset = ranks_offset + rows * 4;
        for row in 0..rows {
            write_u32(
                &mut bytes,
                hashes_offset + row * 4,
                (row as u32).wrapping_mul(2_654_435_761),
            );
            write_u32(&mut bytes, ranks_offset + row * 4, row as u32);
            let mut vector = vec![0_f32; dimensions];
            for (dimension, value) in vector.iter_mut().enumerate() {
                *value = (((row + 3) * (dimension + 5) % 97) as f32 - 48.0) / 48.0;
            }
            normalize_row(&mut vector);
            for (dimension, value) in vector.iter().enumerate() {
                let offset = vectors_offset + (row * dimensions + dimension) * 4;
                bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            }
        }
        bytes
    }

    fn normalize_row(row: &mut [f32]) {
        let norm = row
            .iter()
            .map(|value| *value as f64 * *value as f64)
            .sum::<f64>()
            .sqrt();
        for value in row {
            *value = (*value as f64 / norm) as f32;
        }
    }

    fn neighborhood_hash(target_ids: &[String], rows: &[Vec<(u32, i32)>]) -> u32 {
        let mut hash = 0x811c_9dc5;
        for (source, neighbors) in rows.iter().enumerate() {
            hash = fnv_word(hash, hash_text(&target_ids[source]));
            for (rank, &(target, micro_score)) in neighbors.iter().enumerate() {
                hash = fnv_word(hash, hash_text(&target_ids[target as usize]));
                hash = fnv_word(
                    hash,
                    hash_text(&format!("{}:{}", rank + 1, score_text(micro_score))),
                );
            }
        }
        hash
    }

    fn score_text(micro_score: i32) -> String {
        if micro_score % 1_000_000 == 0 {
            return (micro_score / 1_000_000).to_string();
        }
        let mut text = format!("{:.6}", micro_score as f64 / 1_000_000.0);
        while text.ends_with('0') {
            text.pop();
        }
        text
    }

    fn hash_text(value: &str) -> u32 {
        let mut hash = 0x811c_9dc5_u32;
        for code_unit in value.encode_utf16() {
            hash ^= code_unit as u32;
            hash = hash.wrapping_mul(0x0100_0193);
        }
        hash
    }

    fn fnv_word(mut hash: u32, word: u32) -> u32 {
        for byte in word.to_le_bytes() {
            hash ^= byte as u32;
            hash = hash.wrapping_mul(0x0100_0193);
        }
        hash
    }
}
