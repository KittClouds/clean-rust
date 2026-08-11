use phoenix_memory_embeddings::EmbeddingPageHeaderV1;

use crate::{LloydMaxCodebook, Rotation};

pub const MAGIC: [u8; 8] = *b"PHXTQ001";
pub const VERSION: u32 = 1;
pub const HEADER_BYTES: usize = 512;
pub const COMPLETE_FLAG: u32 = 1;
pub const SECTION_ALIGNMENT: u64 = 64;
pub const BLOCK_VECTORS: usize = 8;
pub const MAX_ROWS: u64 = 64_000_000;
pub const MAX_DIMENSION: u32 = 16_384;
pub const MAX_ARTIFACT_BYTES: u64 = 32 << 30;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuantizedFormat {
    TwoBit,
    FourBit,
}

impl QuantizedFormat {
    pub fn new(bits: u8) -> crate::Result<Self> {
        match bits {
            2 => Ok(Self::TwoBit),
            4 => Ok(Self::FourBit),
            other => Err(crate::TurboQuantError::UnsupportedBitWidth(other)),
        }
    }

    pub const fn bits(self) -> u8 {
        match self {
            Self::TwoBit => 2,
            Self::FourBit => 4,
        }
    }

    pub const fn coordinates_per_byte(self) -> usize {
        8 / self.bits() as usize
    }

    pub const fn code_mask(self) -> u32 {
        (1u32 << self.bits()) - 1
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactAuthority {
    pub source_artifact_hash: [u8; 32],
    pub generation_hash: [u8; 32],
    pub source_set_hash: [u8; 32],
    pub model_identity_hash: [u8; 32],
    pub model_asset_hash: [u8; 32],
    pub embedding_config_hash: [u8; 32],
}

impl ArtifactAuthority {
    pub fn from_embedding_header(header: &EmbeddingPageHeaderV1) -> Self {
        Self {
            source_artifact_hash: header.artifact_hash,
            generation_hash: header.generation_hash,
            source_set_hash: header.source_set_hash,
            model_identity_hash: header.model_identity_hash,
            model_asset_hash: header.model_asset_hash,
            embedding_config_hash: header.config_hash,
        }
    }

    pub fn synthetic(seed: &[u8]) -> Self {
        let derive = |label: &[u8]| {
            let mut hasher = blake3::Hasher::new();
            hasher.update(b"phoenix/turboquant/synthetic-authority/v1");
            hasher.update(label);
            hasher.update(seed);
            *hasher.finalize().as_bytes()
        };
        Self {
            source_artifact_hash: derive(b"artifact"),
            generation_hash: derive(b"generation"),
            source_set_hash: derive(b"sources"),
            model_identity_hash: derive(b"model"),
            model_asset_hash: derive(b"assets"),
            embedding_config_hash: derive(b"embedding-config"),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactHeader {
    pub flags: u32,
    pub format: QuantizedFormat,
    pub dimension: u32,
    pub block_vectors: u32,
    pub row_count: u64,
    pub padded_count: u64,
    pub ids_offset: u64,
    pub ids_len: u64,
    pub codes_offset: u64,
    pub codes_len: u64,
    pub scales_offset: u64,
    pub scales_len: u64,
    pub authority: ArtifactAuthority,
    pub quantizer_hash: [u8; 32],
    pub rotation_hash: [u8; 32],
    pub codebook_hash: [u8; 32],
    pub ids_hash: [u8; 32],
    pub codes_hash: [u8; 32],
    pub scales_hash: [u8; 32],
    pub artifact_hash: [u8; 32],
}

impl ArtifactHeader {
    pub fn encode(&self) -> [u8; HEADER_BYTES] {
        let mut output = [0u8; HEADER_BYTES];
        output[0..8].copy_from_slice(&MAGIC);
        put_u32(&mut output, 8, VERSION);
        put_u32(&mut output, 12, HEADER_BYTES as u32);
        put_u32(&mut output, 16, self.flags);
        output[20] = self.format.bits();
        put_u32(&mut output, 24, self.dimension);
        put_u32(&mut output, 28, self.block_vectors);
        put_u64(&mut output, 32, self.row_count);
        put_u64(&mut output, 40, self.padded_count);
        put_u64(&mut output, 48, self.ids_offset);
        put_u64(&mut output, 56, self.ids_len);
        put_u64(&mut output, 64, self.codes_offset);
        put_u64(&mut output, 72, self.codes_len);
        put_u64(&mut output, 80, self.scales_offset);
        put_u64(&mut output, 88, self.scales_len);
        output[96..128].copy_from_slice(&self.authority.source_artifact_hash);
        output[128..160].copy_from_slice(&self.authority.generation_hash);
        output[160..192].copy_from_slice(&self.authority.source_set_hash);
        output[192..224].copy_from_slice(&self.authority.model_identity_hash);
        output[224..256].copy_from_slice(&self.authority.model_asset_hash);
        output[256..288].copy_from_slice(&self.authority.embedding_config_hash);
        output[288..320].copy_from_slice(&self.quantizer_hash);
        output[320..352].copy_from_slice(&self.rotation_hash);
        output[352..384].copy_from_slice(&self.codebook_hash);
        output[384..416].copy_from_slice(&self.ids_hash);
        output[416..448].copy_from_slice(&self.codes_hash);
        output[448..480].copy_from_slice(&self.scales_hash);
        output[480..512].copy_from_slice(&self.artifact_hash);
        output
    }

    pub fn decode(bytes: &[u8]) -> crate::Result<Self> {
        if bytes.len() < HEADER_BYTES {
            return Err(crate::TurboQuantError::TooSmall);
        }
        if bytes[0..8] != MAGIC
            || get_u32(bytes, 8) != VERSION
            || get_u32(bytes, 12) != HEADER_BYTES as u32
        {
            return Err(crate::TurboQuantError::UnsupportedArtifact);
        }
        let format = QuantizedFormat::new(bytes[20])?;
        Ok(Self {
            flags: get_u32(bytes, 16),
            format,
            dimension: get_u32(bytes, 24),
            block_vectors: get_u32(bytes, 28),
            row_count: get_u64(bytes, 32),
            padded_count: get_u64(bytes, 40),
            ids_offset: get_u64(bytes, 48),
            ids_len: get_u64(bytes, 56),
            codes_offset: get_u64(bytes, 64),
            codes_len: get_u64(bytes, 72),
            scales_offset: get_u64(bytes, 80),
            scales_len: get_u64(bytes, 88),
            authority: ArtifactAuthority {
                source_artifact_hash: bytes[96..128].try_into().unwrap(),
                generation_hash: bytes[128..160].try_into().unwrap(),
                source_set_hash: bytes[160..192].try_into().unwrap(),
                model_identity_hash: bytes[192..224].try_into().unwrap(),
                model_asset_hash: bytes[224..256].try_into().unwrap(),
                embedding_config_hash: bytes[256..288].try_into().unwrap(),
            },
            quantizer_hash: bytes[288..320].try_into().unwrap(),
            rotation_hash: bytes[320..352].try_into().unwrap(),
            codebook_hash: bytes[352..384].try_into().unwrap(),
            ids_hash: bytes[384..416].try_into().unwrap(),
            codes_hash: bytes[416..448].try_into().unwrap(),
            scales_hash: bytes[448..480].try_into().unwrap(),
            artifact_hash: bytes[480..512].try_into().unwrap(),
        })
    }

    pub fn compute_artifact_hash(&self) -> [u8; 32] {
        let mut canonical = *self;
        canonical.artifact_hash = [0; 32];
        *blake3::hash(&canonical.encode()).as_bytes()
    }
}

pub(crate) fn quantizer_hash(
    format: QuantizedFormat,
    dimension: usize,
    rotation: &Rotation,
    codebook: &LloydMaxCodebook,
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix/turboquant-cleanroom/v1");
    hasher.update(&[format.bits()]);
    hasher.update(&(dimension as u64).to_le_bytes());
    hasher.update(&(BLOCK_VECTORS as u64).to_le_bytes());
    hasher.update(&rotation.contract_hash());
    hasher.update(&codebook.hash());
    *hasher.finalize().as_bytes()
}

pub(crate) const fn align_up(value: u64, alignment: u64) -> u64 {
    let remainder = value % alignment;
    if remainder == 0 {
        value
    } else {
        value + alignment - remainder
    }
}

fn put_u32(output: &mut [u8], offset: usize, value: u32) {
    output[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn put_u64(output: &mut [u8], offset: usize, value: u64) {
    output[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn get_u32(input: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(input[offset..offset + 4].try_into().unwrap())
}

fn get_u64(input: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(input[offset..offset + 8].try_into().unwrap())
}
