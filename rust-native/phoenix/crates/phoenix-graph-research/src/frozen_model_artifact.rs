use crate::{
    FrozenModelArchitecture, FrozenModelError, FrozenModelHyperparameters, FrozenModelManifest,
    FrozenModelPaths, FrozenModelRuntimeIdentity, FrozenModelScoreCertificate,
    FrozenModelSeedReceipt, FrozenModelSnapshot, FrozenModelSourceIdentity, FrozenModelTensor,
    FrozenModelTensorManifest, FrozenTrainingReceipt, ResearchSplit, SeedCertificate,
    FROZEN_MODEL_BINARY_VERSION, FROZEN_MODEL_SCHEMA, MODEL_HIDDEN_BIAS, MODEL_HIDDEN_WEIGHT,
    MODEL_OUTPUT_BIAS, MODEL_OUTPUT_WEIGHT,
};
use compact_str::{format_compact, CompactString};
use hashbrown::HashSet;
use memmap2::Mmap;
use serde::Serialize;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use wide::f32x8;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXFMW01";
const TENSOR_COUNT: usize = 4;

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct WeightHeader {
    magic: [u8; 8],
    version: [u8; 2],
    reserved: [u8; 2],
    tensor_count: [u8; 4],
    total_bytes: [u8; 8],
    payload_offset: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct ModelLeF32([u8; 4]);

impl ModelLeF32 {
    pub fn get(self) -> f32 {
        f32::from_bits(u32::from_le_bytes(self.0))
    }
}

pub struct FrozenModelBundle;

impl FrozenModelBundle {
    pub fn write(
        snapshot: &FrozenModelSnapshot,
        root: impl AsRef<Path>,
    ) -> Result<FrozenModelPaths, FrozenModelError> {
        validate_snapshot(snapshot)?;
        let (weights, tensors) = encode_weights(snapshot)?;
        let weights_blake3 = format_compact!("b3-{}", blake3::hash(&weights).to_hex());
        let mut manifest = FrozenModelManifest {
            schema_version: FROZEN_MODEL_SCHEMA.into(),
            model_id: "pending".into(),
            source: snapshot.source.clone(),
            architecture: snapshot.architecture.clone(),
            hyperparameters: snapshot.hyperparameters,
            seeds: snapshot.seeds.clone(),
            runtime: snapshot.runtime.clone(),
            training: snapshot.training.clone(),
            score_certificates: snapshot.score_certificates.clone(),
            weights_file: "pending".into(),
            weights_blake3,
            weights_bytes: weights.len() as u64,
            tensors,
        };
        manifest.model_id = model_identity(&manifest)?;
        manifest.weights_file = format_compact!("{}.fmw", manifest.weights_blake3);
        validate_manifest(&manifest)?;

        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let weights_path = root.join(manifest.weights_file.as_str());
        let manifest_path = root.join(format!("{}.model-manifest.json", manifest.model_id));
        write_immutable(&weights_path, &weights)?;
        write_immutable(&manifest_path, &serde_json::to_vec_pretty(&manifest)?)?;
        Ok(FrozenModelPaths {
            manifest: manifest_path,
            weights: weights_path,
        })
    }
}

pub struct FrozenModelMapped {
    manifest: FrozenModelManifest,
    map: Mmap,
}

impl FrozenModelMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, FrozenModelError> {
        let path = path.as_ref();
        let manifest: FrozenModelManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let expected_manifest = format!("{}.model-manifest.json", manifest.model_id);
        if path.file_name().and_then(|value| value.to_str()) != Some(expected_manifest.as_str()) {
            return Err(FrozenModelError::IdentityMismatch);
        }
        let weights = path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(manifest.weights_file.as_str());
        let file = File::open(weights)?;
        let map = unsafe { Mmap::map(&file)? };
        if map.len() as u64 != manifest.weights_bytes
            || format!("b3-{}", blake3::hash(&map).to_hex()) != manifest.weights_blake3
        {
            return Err(FrozenModelError::CorruptArtifact("weights digest"));
        }
        let mapped = Self { manifest, map };
        mapped.validate_binary()?;
        Ok(mapped)
    }

    pub fn manifest(&self) -> &FrozenModelManifest {
        &self.manifest
    }

    pub fn snapshot(&self) -> Result<FrozenModelSnapshot, FrozenModelError> {
        let mut tensors = Vec::with_capacity(self.manifest.tensors.len());
        for descriptor in &self.manifest.tensors {
            let values = self
                .tensor(descriptor.name.as_str())?
                .iter()
                .map(|value| value.get())
                .collect();
            tensors.push(FrozenModelTensor {
                name: descriptor.name.clone(),
                shape: descriptor.shape.clone(),
                values,
            });
        }
        Ok(FrozenModelSnapshot {
            source: self.manifest.source.clone(),
            architecture: self.manifest.architecture.clone(),
            hyperparameters: self.manifest.hyperparameters,
            seeds: self.manifest.seeds.clone(),
            runtime: self.manifest.runtime.clone(),
            training: self.manifest.training.clone(),
            score_certificates: self.manifest.score_certificates.clone(),
            tensors,
        })
    }

    pub fn tensor(&self, name: &str) -> Result<Ref<&[u8], [ModelLeF32]>, FrozenModelError> {
        let tensor = self
            .manifest
            .tensors
            .iter()
            .find(|tensor| tensor.name == name)
            .ok_or(FrozenModelError::InvalidTensorLayout("unknown tensor"))?;
        let start = usize::try_from(tensor.byte_offset)
            .map_err(|_| FrozenModelError::CorruptArtifact("tensor offset"))?;
        let bytes = usize::try_from(tensor.element_count)
            .ok()
            .and_then(|count| count.checked_mul(size_of::<ModelLeF32>()))
            .ok_or(FrozenModelError::CorruptArtifact("tensor size"))?;
        let end = start
            .checked_add(bytes)
            .ok_or(FrozenModelError::CorruptArtifact("tensor range"))?;
        Ref::<_, [ModelLeF32]>::new_slice(
            self.map
                .get(start..end)
                .ok_or(FrozenModelError::CorruptArtifact("tensor bounds"))?,
        )
        .ok_or(FrozenModelError::CorruptArtifact("tensor layout"))
    }

    pub fn score_mlp16(&self, features: &[[f32; 16]]) -> Result<Vec<f32>, FrozenModelError> {
        let hidden_weight = load_array::<256>(self.tensor(MODEL_HIDDEN_WEIGHT)?)?;
        let hidden_bias = load_array::<16>(self.tensor(MODEL_HIDDEN_BIAS)?)?;
        let output_weight = load_array::<16>(self.tensor(MODEL_OUTPUT_WEIGHT)?)?;
        let output_bias = load_array::<1>(self.tensor(MODEL_OUTPUT_BIAS)?)?[0];
        Ok(score_mlp16_arrays(
            &hidden_weight,
            &hidden_bias,
            &output_weight,
            output_bias,
            features,
        ))
    }

    fn validate_binary(&self) -> Result<(), FrozenModelError> {
        let header = Ref::<_, WeightHeader>::new(
            self.map
                .get(..size_of::<WeightHeader>())
                .ok_or(FrozenModelError::CorruptArtifact("short weight header"))?,
        )
        .map(|header| *header)
        .ok_or(FrozenModelError::CorruptArtifact("weight header layout"))?;
        if header.magic != MAGIC
            || u16::from_le_bytes(header.version) != FROZEN_MODEL_BINARY_VERSION
            || u32::from_le_bytes(header.tensor_count) as usize != self.manifest.tensors.len()
            || u64::from_le_bytes(header.total_bytes) != self.map.len() as u64
            || u64::from_le_bytes(header.payload_offset) != size_of::<WeightHeader>() as u64
        {
            return Err(FrozenModelError::CorruptArtifact("weight header"));
        }
        let mut cursor = size_of::<WeightHeader>() as u64;
        for tensor in &self.manifest.tensors {
            if tensor.byte_offset != cursor {
                return Err(FrozenModelError::CorruptArtifact("tensor contiguity"));
            }
            self.tensor(tensor.name.as_str())?;
            cursor = cursor
                .checked_add(
                    tensor
                        .element_count
                        .checked_mul(4)
                        .ok_or(FrozenModelError::CorruptArtifact("tensor byte count"))?,
                )
                .ok_or(FrozenModelError::CorruptArtifact("tensor end"))?;
        }
        if cursor != self.map.len() as u64 {
            return Err(FrozenModelError::CorruptArtifact("trailing weight bytes"));
        }
        Ok(())
    }
}

pub fn score_mlp16_tensors(
    tensors: &[FrozenModelTensor],
    features: &[[f32; 16]],
) -> Result<Vec<f32>, FrozenModelError> {
    if tensors.len() != TENSOR_COUNT {
        return Err(FrozenModelError::InvalidTensorLayout("tensor count"));
    }
    for (index, tensor) in tensors.iter().enumerate() {
        let (name, shape) = expected_tensor(index);
        if tensor.name != name
            || tensor.shape.as_slice() != shape
            || tensor.values.len() as u64 != shape_product(shape)?
            || tensor.values.iter().any(|value| !value.is_finite())
        {
            return Err(FrozenModelError::InvalidTensorLayout(
                "tensor specification",
            ));
        }
    }
    let hidden_weight: &[f32; 256] = tensors[0]
        .values
        .as_slice()
        .try_into()
        .map_err(|_| FrozenModelError::InvalidTensorLayout("hidden weight"))?;
    let hidden_bias: &[f32; 16] = tensors[1]
        .values
        .as_slice()
        .try_into()
        .map_err(|_| FrozenModelError::InvalidTensorLayout("hidden bias"))?;
    let output_weight: &[f32; 16] = tensors[2]
        .values
        .as_slice()
        .try_into()
        .map_err(|_| FrozenModelError::InvalidTensorLayout("output weight"))?;
    Ok(score_mlp16_arrays(
        hidden_weight,
        hidden_bias,
        output_weight,
        tensors[3].values[0],
        features,
    ))
}

pub fn certify_model_seed_receipt(
    certificate: &SeedCertificate,
    selected_repeat: u16,
) -> Result<FrozenModelSeedReceipt, FrozenModelError> {
    let receipt = FrozenModelSeedReceipt {
        certificate: certificate.clone(),
        selected_repeat,
    };
    validate_seed_receipt(&receipt)?;
    Ok(receipt)
}

pub fn certify_model_scores<T: Serialize>(
    task_id: impl Into<CompactString>,
    evaluator_schema: impl Into<CompactString>,
    split: ResearchSplit,
    scores: &[f32],
    metrics: &T,
) -> Result<FrozenModelScoreCertificate, FrozenModelError> {
    if scores.is_empty() || scores.iter().any(|score| !score.is_finite()) {
        return Err(FrozenModelError::InvalidContract("model scores"));
    }
    let task_id = task_id.into();
    let evaluator_schema = evaluator_schema.into();
    if task_id.is_empty() || evaluator_schema.is_empty() {
        return Err(FrozenModelError::InvalidContract("score identity"));
    }
    let mut score_hasher = blake3::Hasher::new();
    for score in scores {
        score_hasher.update(&score.to_bits().to_le_bytes());
    }
    Ok(FrozenModelScoreCertificate {
        task_id,
        evaluator_schema,
        split,
        score_count: scores.len() as u64,
        score_dtype: "f32-le".into(),
        score_blake3: format_compact!("b3-{}", score_hasher.finalize().to_hex()),
        metrics_blake3: format_compact!(
            "b3-{}",
            blake3::hash(&serde_json::to_vec(metrics)?).to_hex()
        ),
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelIdentity<'a> {
    schema_version: &'a str,
    source: &'a FrozenModelSourceIdentity,
    architecture: &'a FrozenModelArchitecture,
    hyperparameters: FrozenModelHyperparameters,
    seeds: &'a FrozenModelSeedReceipt,
    runtime: &'a FrozenModelRuntimeIdentity,
    training: &'a FrozenTrainingReceipt,
    score_certificates: &'a [FrozenModelScoreCertificate],
    weights_blake3: &'a str,
    weights_bytes: u64,
    tensors: &'a [FrozenModelTensorManifest],
}

fn model_identity(manifest: &FrozenModelManifest) -> Result<CompactString, FrozenModelError> {
    let identity = ModelIdentity {
        schema_version: FROZEN_MODEL_SCHEMA,
        source: &manifest.source,
        architecture: &manifest.architecture,
        hyperparameters: manifest.hyperparameters,
        seeds: &manifest.seeds,
        runtime: &manifest.runtime,
        training: &manifest.training,
        score_certificates: &manifest.score_certificates,
        weights_blake3: manifest.weights_blake3.as_str(),
        weights_bytes: manifest.weights_bytes,
        tensors: &manifest.tensors,
    };
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    ))
}

fn validate_snapshot(snapshot: &FrozenModelSnapshot) -> Result<(), FrozenModelError> {
    validate_contract(
        &snapshot.source,
        &snapshot.architecture,
        snapshot.hyperparameters,
        &snapshot.seeds,
        &snapshot.runtime,
        &snapshot.training,
        &snapshot.score_certificates,
    )?;
    if snapshot.tensors.len() != TENSOR_COUNT {
        return Err(FrozenModelError::InvalidTensorLayout("tensor count"));
    }
    for (index, tensor) in snapshot.tensors.iter().enumerate() {
        let (name, shape) = expected_tensor(index);
        if tensor.name != name
            || tensor.shape.as_slice() != shape
            || tensor.values.len() as u64 != shape_product(shape)?
            || tensor.values.iter().any(|value| !value.is_finite())
        {
            return Err(FrozenModelError::InvalidTensorLayout(
                "tensor specification",
            ));
        }
    }
    Ok(())
}

fn validate_manifest(manifest: &FrozenModelManifest) -> Result<(), FrozenModelError> {
    if manifest.schema_version != FROZEN_MODEL_SCHEMA
        || manifest.model_id != model_identity(manifest)?
        || manifest.weights_file != format!("{}.fmw", manifest.weights_blake3)
        || !is_blake3(manifest.weights_blake3.as_str())
    {
        return Err(FrozenModelError::IdentityMismatch);
    }
    validate_contract(
        &manifest.source,
        &manifest.architecture,
        manifest.hyperparameters,
        &manifest.seeds,
        &manifest.runtime,
        &manifest.training,
        &manifest.score_certificates,
    )?;
    if manifest.tensors.len() != TENSOR_COUNT {
        return Err(FrozenModelError::InvalidTensorLayout(
            "manifest tensor count",
        ));
    }
    for (index, tensor) in manifest.tensors.iter().enumerate() {
        let (name, shape) = expected_tensor(index);
        if tensor.name != name
            || tensor.shape.as_slice() != shape
            || tensor.element_count != shape_product(shape)?
        {
            return Err(FrozenModelError::InvalidTensorLayout("manifest tensor"));
        }
    }
    Ok(())
}

fn validate_contract(
    source: &FrozenModelSourceIdentity,
    architecture: &FrozenModelArchitecture,
    hyperparameters: FrozenModelHyperparameters,
    seeds: &FrozenModelSeedReceipt,
    runtime: &FrozenModelRuntimeIdentity,
    training: &FrozenTrainingReceipt,
    scores: &[FrozenModelScoreCertificate],
) -> Result<(), FrozenModelError> {
    if !is_blake3(source.dataset_id.as_str())
        || source.checkpoint_id.is_empty()
        || source.checkpoint_generation == 0
        || !is_blake3(source.tensor_id.as_str())
        || !is_blake3(source.topology_derivation_id.as_str())
        || !is_blake3(source.evaluation_protocol_id.as_str())
        || !is_blake3(source.topology_blake3.as_str())
    {
        return Err(FrozenModelError::InvalidContract("source identity"));
    }
    if architecture != &FrozenModelArchitecture::mlp16() {
        return Err(FrozenModelError::InvalidContract("architecture"));
    }
    if hyperparameters.epochs == 0
        || hyperparameters.batch_size == 0
        || !hyperparameters.learning_rate.is_finite()
        || hyperparameters.learning_rate <= 0.0
        || !hyperparameters.l2.is_finite()
        || hyperparameters.l2 < 0.0
    {
        return Err(FrozenModelError::InvalidContract("hyperparameters"));
    }
    validate_seed_receipt(seeds)?;
    if runtime.framework.is_empty()
        || runtime.framework_version.is_empty()
        || runtime.backend.is_empty()
        || runtime.target.is_empty()
    {
        return Err(FrozenModelError::InvalidContract("runtime identity"));
    }
    if training.trainer_id.is_empty()
        || training.training_examples == 0
        || training.validation_examples == 0
        || training.epochs_completed != hyperparameters.epochs
        || training.training_executions != 1
        || !training.selected_on_validation
        || !training.test_locked_during_selection
        || training.optimizer.algorithm.is_empty()
        || training.optimizer.implementation_version.is_empty()
        || training.optimizer.steps_completed == 0
        || !is_blake3(training.optimizer.state_blake3.as_str())
    {
        return Err(FrozenModelError::InvalidContract("training receipt"));
    }
    if scores.is_empty() {
        return Err(FrozenModelError::InvalidContract("score certificates"));
    }
    let mut identities = HashSet::with_capacity(scores.len());
    let mut has_validation = false;
    for score in scores {
        if score.task_id.is_empty()
            || score.evaluator_schema.is_empty()
            || score.score_count == 0
            || score.score_dtype != "f32-le"
            || !is_blake3(score.score_blake3.as_str())
            || !is_blake3(score.metrics_blake3.as_str())
            || !identities.insert((score.task_id.clone(), score.split))
        {
            return Err(FrozenModelError::InvalidContract("score certificate"));
        }
        has_validation |= score.split == ResearchSplit::Validation;
    }
    if !has_validation {
        return Err(FrozenModelError::InvalidContract(
            "validation score certificate",
        ));
    }
    Ok(())
}

fn validate_seed_receipt(receipt: &FrozenModelSeedReceipt) -> Result<(), FrozenModelError> {
    if receipt.certificate.namespace.is_empty()
        || receipt.certificate.seeds.is_empty()
        || receipt.selected_seed().is_none()
    {
        return Err(FrozenModelError::InvalidContract("seed receipt"));
    }
    let mut hasher = blake3::Hasher::new();
    for seed in &receipt.certificate.seeds {
        hasher.update(&seed.to_le_bytes());
    }
    if receipt.certificate.digest != format!("b3-{}", hasher.finalize().to_hex()) {
        return Err(FrozenModelError::InvalidContract("seed digest"));
    }
    Ok(())
}

fn encode_weights(
    snapshot: &FrozenModelSnapshot,
) -> Result<(Vec<u8>, Vec<FrozenModelTensorManifest>), FrozenModelError> {
    let mut bytes = vec![0_u8; size_of::<WeightHeader>()];
    let mut tensors = Vec::with_capacity(snapshot.tensors.len());
    for tensor in &snapshot.tensors {
        let offset = bytes.len() as u64;
        for value in &tensor.values {
            bytes.extend_from_slice(&value.to_bits().to_le_bytes());
        }
        tensors.push(FrozenModelTensorManifest {
            name: tensor.name.clone(),
            shape: tensor.shape.clone(),
            element_count: tensor.values.len() as u64,
            byte_offset: offset,
        });
    }
    let header = WeightHeader {
        magic: MAGIC,
        version: FROZEN_MODEL_BINARY_VERSION.to_le_bytes(),
        reserved: [0; 2],
        tensor_count: (snapshot.tensors.len() as u32).to_le_bytes(),
        total_bytes: (bytes.len() as u64).to_le_bytes(),
        payload_offset: (size_of::<WeightHeader>() as u64).to_le_bytes(),
    };
    bytes[..size_of::<WeightHeader>()].copy_from_slice(header.as_bytes());
    Ok((bytes, tensors))
}

fn expected_tensor(index: usize) -> (&'static str, &'static [u64]) {
    match index {
        0 => (MODEL_HIDDEN_WEIGHT, &[16, 16]),
        1 => (MODEL_HIDDEN_BIAS, &[16]),
        2 => (MODEL_OUTPUT_WEIGHT, &[16]),
        3 => (MODEL_OUTPUT_BIAS, &[1]),
        _ => ("", &[]),
    }
}

fn shape_product(shape: &[u64]) -> Result<u64, FrozenModelError> {
    if shape.is_empty() || shape.contains(&0) {
        return Err(FrozenModelError::InvalidTensorLayout("empty shape"));
    }
    shape.iter().try_fold(1_u64, |total, value| {
        total
            .checked_mul(*value)
            .ok_or(FrozenModelError::InvalidTensorLayout("shape overflow"))
    })
}

fn load_array<const N: usize>(
    values: Ref<&[u8], [ModelLeF32]>,
) -> Result<[f32; N], FrozenModelError> {
    if values.len() != N {
        return Err(FrozenModelError::InvalidTensorLayout("inference tensor"));
    }
    let mut output = [0.0_f32; N];
    for (target, source) in output.iter_mut().zip(values.iter()) {
        *target = source.get();
    }
    Ok(output)
}

fn simd_dot(left: &[f32; 16], right: &[f32; 16]) -> f32 {
    let left_low: [f32; 8] = left[..8].try_into().expect("eight values");
    let right_low: [f32; 8] = right[..8].try_into().expect("eight values");
    let left_high: [f32; 8] = left[8..].try_into().expect("eight values");
    let right_high: [f32; 8] = right[8..].try_into().expect("eight values");
    let low: [f32; 8] = (f32x8::from(left_low) * f32x8::from(right_low)).into();
    let high: [f32; 8] = (f32x8::from(left_high) * f32x8::from(right_high)).into();
    low.into_iter().chain(high).sum()
}

fn score_mlp16_arrays(
    hidden_weight: &[f32; 256],
    hidden_bias: &[f32; 16],
    output_weight: &[f32; 16],
    output_bias: f32,
    features: &[[f32; 16]],
) -> Vec<f32> {
    let mut scores = Vec::with_capacity(features.len());
    for feature in features {
        let mut hidden = [0.0_f32; 16];
        for (index, value) in hidden.iter_mut().enumerate() {
            let row: &[f32; 16] = hidden_weight[index * 16..(index + 1) * 16]
                .try_into()
                .expect("fixed MLP row");
            *value = (simd_dot(row, feature) + hidden_bias[index]).max(0.0);
        }
        scores.push(sigmoid(simd_dot(output_weight, &hidden) + output_bias));
    }
    scores
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), FrozenModelError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(FrozenModelError::ArtifactExists(path.to_path_buf()))
        };
    }
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("model");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}
