use std::cell::RefCell;
use std::env;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Path, PathBuf};

use compact_str::CompactString;
use memmap2::Mmap;
use phoenix_graph_kernel::{GraphProposalFeatures, GRAPH_PROPOSAL_FEATURE_DIM};
use thiserror::Error;
use wide::f32x8;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MODEL_MAGIC: [u8; 8] = *b"PHXGPLM1";
const MODEL_VERSION: u16 = 1;
const MODEL_FILE_NAME: &str = "graph-promotion-model-v1.bin";

thread_local! {
    static MODEL_CACHE: RefCell<ModelCache> = RefCell::new(ModelCache::default());
}

#[derive(Default)]
struct ModelCache {
    attempted: bool,
    model: Option<MmapGraphPromotionModel>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GraphPromotionTrainingExample {
    pub features: GraphProposalFeatures,
    pub label: bool,
    pub weight: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GraphPromotionTrainingConfig {
    pub epochs: usize,
    pub alpha: f32,
    pub beta: f32,
    pub l1: f32,
    pub l2: f32,
}

impl Default for GraphPromotionTrainingConfig {
    fn default() -> Self {
        Self {
            epochs: 8,
            alpha: 0.08,
            beta: 1.0,
            l1: 0.002,
            l2: 0.04,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct GraphPromotionLinearModel {
    pub model_id: CompactString,
    weights: [f32; GRAPH_PROPOSAL_FEATURE_DIM],
    bias: f32,
}

impl GraphPromotionLinearModel {
    pub fn fit_ftrl(
        model_id: impl Into<CompactString>,
        examples: &[GraphPromotionTrainingExample],
        config: GraphPromotionTrainingConfig,
    ) -> Result<Self, GraphPromotionModelError> {
        if examples.is_empty() {
            return Err(GraphPromotionModelError::EmptyTrainingSet);
        }
        if config.epochs == 0 || config.alpha <= 0.0 || config.beta < 0.0 {
            return Err(GraphPromotionModelError::InvalidTrainingConfig);
        }
        let mut z = [0.0_f32; GRAPH_PROPOSAL_FEATURE_DIM];
        let mut n = [0.0_f32; GRAPH_PROPOSAL_FEATURE_DIM];
        let mut bias_z = 0.0_f32;
        let mut bias_n = 0.0_f32;

        for _ in 0..config.epochs {
            for example in examples {
                let weights = ftrl_weights(&z, &n, config);
                let bias = ftrl_weight(bias_z, bias_n, config);
                let values = normalized_features(example.features);
                let prediction = sigmoid(simd_dot(&weights, &values) + bias);
                let label = if example.label { 1.0 } else { 0.0 };
                let weight = example.weight.max(0.0);
                let error = (prediction - label) * weight;
                for index in 0..GRAPH_PROPOSAL_FEATURE_DIM {
                    let gradient = error * values[index];
                    let sigma =
                        ((n[index] + gradient * gradient).sqrt() - n[index].sqrt()) / config.alpha;
                    z[index] += gradient - sigma * weights[index];
                    n[index] += gradient * gradient;
                }
                let bias_sigma = ((bias_n + error * error).sqrt() - bias_n.sqrt()) / config.alpha;
                bias_z += error - bias_sigma * bias;
                bias_n += error * error;
            }
        }

        Ok(Self {
            model_id: model_id.into(),
            weights: ftrl_weights(&z, &n, config),
            bias: ftrl_weight(bias_z, bias_n, config),
        })
    }

    pub fn score_millis(&self, features: GraphProposalFeatures) -> u16 {
        let values = normalized_features(features);
        let probability = sigmoid(simd_dot(&self.weights, &values) + self.bias);
        (probability * 1000.0).round().clamp(0.0, 1000.0) as u16
    }

    pub fn write_immutable(
        &self,
        path: impl AsRef<Path>,
    ) -> Result<PathBuf, GraphPromotionModelError> {
        let path = path.as_ref();
        if path.exists() {
            return Err(GraphPromotionModelError::ArtifactExists(path.to_path_buf()));
        }
        let id = self.model_id.as_bytes();
        let total_len = size_of::<ModelHeader>()
            .checked_add(id.len())
            .ok_or(GraphPromotionModelError::ArtifactTooLarge)?;
        let mut weights = [[0_u8; 4]; GRAPH_PROPOSAL_FEATURE_DIM];
        for (slot, value) in weights.iter_mut().zip(self.weights) {
            *slot = value.to_bits().to_le_bytes();
        }
        let header = ModelHeader {
            magic: MODEL_MAGIC,
            version: MODEL_VERSION.to_le_bytes(),
            feature_dim: (GRAPH_PROPOSAL_FEATURE_DIM as u16).to_le_bytes(),
            total_len: u32::try_from(total_len)
                .map_err(|_| GraphPromotionModelError::ArtifactTooLarge)?
                .to_le_bytes(),
            model_id_len: u32::try_from(id.len())
                .map_err(|_| GraphPromotionModelError::ArtifactTooLarge)?
                .to_le_bytes(),
            bias: self.bias.to_bits().to_le_bytes(),
            weights,
            checksum: checksum64(id).to_le_bytes(),
        };
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
        file.write_all(header.as_bytes())?;
        file.write_all(id)?;
        file.sync_all()?;
        Ok(path.to_path_buf())
    }
}

#[derive(Debug)]
pub struct MmapGraphPromotionModel {
    _mmap: Mmap,
    model: GraphPromotionLinearModel,
}

impl MmapGraphPromotionModel {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, GraphPromotionModelError> {
        let file = File::open(path)?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() < size_of::<ModelHeader>() {
            return Err(GraphPromotionModelError::InvalidArtifact("short header"));
        }
        let header = *Ref::<_, ModelHeader>::new_unaligned(&mmap[..size_of::<ModelHeader>()])
            .ok_or(GraphPromotionModelError::InvalidArtifact("invalid header"))?;
        if header.magic != MODEL_MAGIC {
            return Err(GraphPromotionModelError::InvalidArtifact("bad magic"));
        }
        if u16::from_le_bytes(header.version) != MODEL_VERSION {
            return Err(GraphPromotionModelError::InvalidArtifact("bad version"));
        }
        if u16::from_le_bytes(header.feature_dim) as usize != GRAPH_PROPOSAL_FEATURE_DIM {
            return Err(GraphPromotionModelError::InvalidArtifact(
                "feature mismatch",
            ));
        }
        let total_len = u32::from_le_bytes(header.total_len) as usize;
        let id_len = u32::from_le_bytes(header.model_id_len) as usize;
        if total_len != mmap.len() || size_of::<ModelHeader>() + id_len != total_len {
            return Err(GraphPromotionModelError::InvalidArtifact("length mismatch"));
        }
        let id_bytes = &mmap[size_of::<ModelHeader>()..];
        if checksum64(id_bytes) != u64::from_le_bytes(header.checksum) {
            return Err(GraphPromotionModelError::InvalidArtifact(
                "checksum mismatch",
            ));
        }
        let model_id = CompactString::new(
            std::str::from_utf8(id_bytes)
                .map_err(|_| GraphPromotionModelError::InvalidArtifact("model id utf8"))?,
        );
        let mut weights = [0.0_f32; GRAPH_PROPOSAL_FEATURE_DIM];
        for (slot, value) in weights.iter_mut().zip(header.weights) {
            *slot = f32::from_bits(u32::from_le_bytes(value));
        }
        Ok(Self {
            _mmap: mmap,
            model: GraphPromotionLinearModel {
                model_id,
                weights,
                bias: f32::from_bits(u32::from_le_bytes(header.bias)),
            },
        })
    }

    pub fn model(&self) -> &GraphPromotionLinearModel {
        &self.model
    }
}

pub(crate) fn with_default_promotion_model<R>(
    callback: impl FnOnce(Option<&GraphPromotionLinearModel>) -> R,
) -> R {
    MODEL_CACHE.with(|cell| {
        let mut cache = cell.borrow_mut();
        if !cache.attempted {
            cache.attempted = true;
            cache.model =
                default_model_path().and_then(|path| MmapGraphPromotionModel::open(path).ok());
        }
        callback(cache.model.as_ref().map(MmapGraphPromotionModel::model))
    })
}

#[cfg(test)]
pub(crate) fn reset_default_promotion_model_cache_for_tests() {
    MODEL_CACHE.with(|cell| {
        *cell.borrow_mut() = ModelCache::default();
    });
}

fn normalized_features(features: GraphProposalFeatures) -> [f32; GRAPH_PROPOSAL_FEATURE_DIM] {
    let mut values = [0.0_f32; GRAPH_PROPOSAL_FEATURE_DIM];
    for (slot, value) in values.iter_mut().zip(features.0) {
        *slot = value as f32 / 1000.0;
    }
    values
}

fn simd_dot(
    left: &[f32; GRAPH_PROPOSAL_FEATURE_DIM],
    right: &[f32; GRAPH_PROPOSAL_FEATURE_DIM],
) -> f32 {
    let left_low: [f32; 8] = left[..8].try_into().expect("eight weights");
    let right_low: [f32; 8] = right[..8].try_into().expect("eight features");
    let left_high: [f32; 8] = left[8..].try_into().expect("eight weights");
    let right_high: [f32; 8] = right[8..].try_into().expect("eight features");
    let low: [f32; 8] = (f32x8::from(left_low) * f32x8::from(right_low)).into();
    let high: [f32; 8] = (f32x8::from(left_high) * f32x8::from(right_high)).into();
    low.into_iter().chain(high).sum()
}

fn ftrl_weights(
    z: &[f32; GRAPH_PROPOSAL_FEATURE_DIM],
    n: &[f32; GRAPH_PROPOSAL_FEATURE_DIM],
    config: GraphPromotionTrainingConfig,
) -> [f32; GRAPH_PROPOSAL_FEATURE_DIM] {
    let mut weights = [0.0; GRAPH_PROPOSAL_FEATURE_DIM];
    for index in 0..GRAPH_PROPOSAL_FEATURE_DIM {
        weights[index] = ftrl_weight(z[index], n[index], config);
    }
    weights
}

fn ftrl_weight(z: f32, n: f32, config: GraphPromotionTrainingConfig) -> f32 {
    if z.abs() <= config.l1 {
        0.0
    } else {
        (z.signum() * config.l1 - z) / ((config.beta + n.sqrt()) / config.alpha + config.l2)
    }
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn default_model_path() -> Option<PathBuf> {
    env::var_os("PHOENIX_GRAPH_PROMOTION_MODEL_PATH")
        .map(PathBuf::from)
        .filter(|path| path.exists())
        .or_else(|| {
            let path = project_root().join(MODEL_FILE_NAME);
            path.exists().then_some(path)
        })
}

fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("project root")
        .to_path_buf()
}

fn checksum64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for byte in bytes {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    hash
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct ModelHeader {
    magic: [u8; 8],
    version: [u8; 2],
    feature_dim: [u8; 2],
    total_len: [u8; 4],
    model_id_len: [u8; 4],
    bias: [u8; 4],
    weights: [[u8; 4]; GRAPH_PROPOSAL_FEATURE_DIM],
    checksum: [u8; 8],
}

#[derive(Debug, Error)]
pub enum GraphPromotionModelError {
    #[error("promotion learner training set is empty")]
    EmptyTrainingSet,
    #[error("promotion learner training configuration is invalid")]
    InvalidTrainingConfig,
    #[error("promotion learner artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("promotion learner artifact is too large")]
    ArtifactTooLarge,
    #[error("invalid promotion learner artifact: {0}")]
    InvalidArtifact(&'static str),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
