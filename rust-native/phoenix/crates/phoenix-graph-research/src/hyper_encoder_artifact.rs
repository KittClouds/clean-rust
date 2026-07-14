use crate::{
    hyper_encoder_model_identity_from_authority, HyperEncoderError, HyperEncoderModelManifest,
    HyperEncoderModelPaths, HyperEncoderModelSnapshot, HyperEncoderPairManifest,
    HyperEncoderPairPaths, HyperEncoderWeights, HYPER_ENCODER_DIRECTIONS, HYPER_ENCODER_HIDDEN,
    HYPER_ENCODER_MODEL_BINARY_VERSION, HYPER_ENCODER_MODEL_SCHEMA, HYPER_ENCODER_PAIR_SCHEMA,
};
use compact_str::CompactString;
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Component, Path};

const MAGIC: &[u8; 8] = b"PHXHEM01";
const HEADER_BYTES: usize = 32;

pub struct HyperEncoderMapped {
    manifest: HyperEncoderModelManifest,
    mmap: Mmap,
}

impl HyperEncoderMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, HyperEncoderError> {
        let path = path.as_ref();
        let manifest: HyperEncoderModelManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let name = Path::new(manifest.weights_file.as_str());
        let mut components = name.components();
        if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
            return Err(HyperEncoderError::CorruptArtifact("weight path"));
        }
        let file = File::open(path.parent().unwrap_or_else(|| Path::new(".")).join(name))?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() as u64 != manifest.weights_bytes
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.weights_blake3
        {
            return Err(HyperEncoderError::CorruptArtifact("weight identity"));
        }
        validate_header(&mmap, &manifest)?;
        let mapped = Self { manifest, mmap };
        let weights = mapped.weights()?;
        let model_id = hyper_encoder_model_identity_from_authority(
            mapped.manifest.source_dataset_id.as_str(),
            mapped.manifest.source_binary_blake3.as_str(),
            mapped.manifest.task_id.as_str(),
            mapped.manifest.task_binary_blake3.as_str(),
            mapped.manifest.config,
            &weights,
        )?;
        if model_id != mapped.manifest.model_id
            || mapped.manifest.validation.model_id != mapped.manifest.model_id
        {
            return Err(HyperEncoderError::CorruptArtifact("model identity"));
        }
        Ok(mapped)
    }

    pub fn manifest(&self) -> &HyperEncoderModelManifest {
        &self.manifest
    }

    pub fn weights(&self) -> Result<HyperEncoderWeights, HyperEncoderError> {
        let nodes = self.manifest.candidate_universe as usize;
        let relations = self.manifest.directed_relation_count as usize;
        let counts = tensor_counts(nodes, relations);
        let mut cursor = HEADER_BYTES;
        let mut take = |count: usize| -> Result<Vec<f32>, HyperEncoderError> {
            let bytes = count
                .checked_mul(size_of::<f32>())
                .ok_or(HyperEncoderError::CorruptArtifact("weight range"))?;
            let end = cursor
                .checked_add(bytes)
                .ok_or(HyperEncoderError::CorruptArtifact("weight range"))?;
            let source = self
                .mmap
                .get(cursor..end)
                .ok_or(HyperEncoderError::CorruptArtifact("weight range"))?;
            cursor = end;
            Ok(source
                .chunks_exact(4)
                .map(|value| f32::from_bits(u32::from_le_bytes(value.try_into().expect("f32"))))
                .collect())
        };
        let weights = HyperEncoderWeights {
            node_embeddings: take(counts[0])?,
            direction_weights: take(counts[1])?,
            relation_embeddings: take(counts[2])?,
            relation_projection: take(counts[3])?,
            qualifier_projection: take(counts[4])?,
            decoder_bias: take(counts[5])?,
        };
        if cursor != self.mmap.len() || !weights_finite(&weights) {
            return Err(HyperEncoderError::CorruptArtifact("weight payload"));
        }
        Ok(weights)
    }
}

pub fn write_hyper_encoder_model(
    snapshot: &HyperEncoderModelSnapshot,
    root: impl AsRef<Path>,
) -> Result<HyperEncoderModelPaths, HyperEncoderError> {
    validate_snapshot(snapshot)?;
    let model_id = hyper_encoder_model_identity_from_authority(
        snapshot.source_dataset_id.as_str(),
        snapshot.source_binary_blake3.as_str(),
        snapshot.task_id.as_str(),
        snapshot.task_binary_blake3.as_str(),
        snapshot.config,
        &snapshot.weights,
    )?;
    if snapshot.validation.model_id != model_id {
        return Err(HyperEncoderError::InvalidContract(
            "validation model identity",
        ));
    }
    let bytes = encode_weights(snapshot)?;
    let weights_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
    let weights_file = format!("{model_id}.weights.bin");
    let mut manifest = HyperEncoderModelManifest {
        schema_version: HYPER_ENCODER_MODEL_SCHEMA.into(),
        manifest_id: "pending".into(),
        model_id: model_id.clone(),
        pair_id: snapshot.pair_id.clone(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        task_id: snapshot.task_id.clone(),
        task_binary_blake3: snapshot.task_binary_blake3.clone(),
        candidate_universe: snapshot.candidate_universe,
        base_relation_count: snapshot.base_relation_count,
        directed_relation_count: snapshot.base_relation_count * 2,
        hidden_features: HYPER_ENCODER_HIDDEN as u16,
        config: snapshot.config,
        training_config: snapshot.training_config,
        training: snapshot.training.clone(),
        validation: snapshot.validation.clone(),
        weights_file: weights_file.as_str().into(),
        weights_blake3: weights_blake3.as_str().into(),
        weights_bytes: bytes.len() as u64,
    };
    manifest.manifest_id = manifest_identity(&manifest)?;
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let weights = root.join(weights_file);
    let manifest_path = root.join(format!("{}.manifest.json", manifest.manifest_id));
    if weights.exists() || manifest_path.exists() {
        return Err(HyperEncoderError::ArtifactExists(weights));
    }
    write_new(&weights, &bytes)?;
    if let Err(error) = write_new(&manifest_path, &serde_json::to_vec_pretty(&manifest)?) {
        let _ = std::fs::remove_file(&weights);
        return Err(error);
    }
    Ok(HyperEncoderModelPaths {
        manifest: manifest_path,
        weights,
        manifest_id: manifest.manifest_id,
        model_id,
    })
}

pub fn write_hyper_encoder_pair(
    manifest: &HyperEncoderPairManifest,
    root: impl AsRef<Path>,
) -> Result<HyperEncoderPairPaths, HyperEncoderError> {
    if manifest.schema_version != HYPER_ENCODER_PAIR_SCHEMA
        || manifest.pair_id.is_empty()
        || manifest.trainer_id.is_empty()
        || !manifest.qualifier_intervention_only
        || manifest.test_partition_accessed
    {
        return Err(HyperEncoderError::InvalidContract("pair manifest"));
    }
    let expected = pair_identity(manifest)?;
    if expected != manifest.pair_id {
        return Err(HyperEncoderError::InvalidContract("pair identity"));
    }
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let path = root.join(format!("{}.pair.json", manifest.pair_id));
    if path.exists() {
        return Err(HyperEncoderError::ArtifactExists(path));
    }
    write_new(&path, &serde_json::to_vec_pretty(manifest)?)?;
    Ok(HyperEncoderPairPaths {
        manifest: path,
        pair_id: manifest.pair_id.clone(),
    })
}

pub fn pair_identity(
    manifest: &HyperEncoderPairManifest,
) -> Result<CompactString, HyperEncoderError> {
    let mut identity = manifest.clone();
    identity.pair_id = "pending".into();
    identity.compgcn_manifest_id = "derived-after-pair".into();
    identity.stare_manifest_id = "derived-after-pair".into();
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    )
    .into())
}

fn encode_weights(snapshot: &HyperEncoderModelSnapshot) -> Result<Vec<u8>, HyperEncoderError> {
    let relations = snapshot.base_relation_count as usize * 2;
    let counts = tensor_counts(snapshot.candidate_universe as usize, relations);
    let tensors = [
        &snapshot.weights.node_embeddings,
        &snapshot.weights.direction_weights,
        &snapshot.weights.relation_embeddings,
        &snapshot.weights.relation_projection,
        &snapshot.weights.qualifier_projection,
        &snapshot.weights.decoder_bias,
    ];
    if tensors
        .iter()
        .zip(counts)
        .any(|(values, count)| values.len() != count)
    {
        return Err(HyperEncoderError::InvalidContract("weight shape"));
    }
    let payload = counts.iter().sum::<usize>() * size_of::<f32>();
    let mut bytes = Vec::with_capacity(HEADER_BYTES + payload);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&HYPER_ENCODER_MODEL_BINARY_VERSION.to_le_bytes());
    bytes.extend_from_slice(&[0; 2]);
    bytes.extend_from_slice(&snapshot.candidate_universe.to_le_bytes());
    bytes.extend_from_slice(&(relations as u32).to_le_bytes());
    bytes.extend_from_slice(&((HEADER_BYTES + payload) as u64).to_le_bytes());
    bytes.extend_from_slice(&[0; 4]);
    for tensor in tensors {
        for value in tensor {
            bytes.extend_from_slice(&value.to_bits().to_le_bytes());
        }
    }
    Ok(bytes)
}

fn validate_header(
    bytes: &[u8],
    manifest: &HyperEncoderModelManifest,
) -> Result<(), HyperEncoderError> {
    if bytes.len() < HEADER_BYTES
        || &bytes[..8] != MAGIC
        || u16::from_le_bytes(bytes[8..10].try_into().expect("version"))
            != HYPER_ENCODER_MODEL_BINARY_VERSION
        || u32::from_le_bytes(bytes[12..16].try_into().expect("nodes"))
            != manifest.candidate_universe
        || u32::from_le_bytes(bytes[16..20].try_into().expect("relations"))
            != manifest.directed_relation_count
        || u64::from_le_bytes(bytes[20..28].try_into().expect("bytes")) != bytes.len() as u64
    {
        return Err(HyperEncoderError::CorruptArtifact("weight header"));
    }
    let floats = tensor_counts(
        manifest.candidate_universe as usize,
        manifest.directed_relation_count as usize,
    )
    .iter()
    .sum::<usize>();
    if HEADER_BYTES + floats * size_of::<f32>() != bytes.len() {
        return Err(HyperEncoderError::CorruptArtifact("weight length"));
    }
    Ok(())
}

fn validate_snapshot(snapshot: &HyperEncoderModelSnapshot) -> Result<(), HyperEncoderError> {
    snapshot.training_config.validate()?;
    if snapshot.pair_id.is_empty()
        || snapshot.source_dataset_id.is_empty()
        || snapshot.task_id.is_empty()
        || snapshot.validation.task_id != snapshot.task_id
        || !snapshot.training.test_locked_during_training
    {
        return Err(HyperEncoderError::InvalidContract("model snapshot"));
    }
    Ok(())
}

fn validate_manifest(manifest: &HyperEncoderModelManifest) -> Result<(), HyperEncoderError> {
    if manifest.schema_version != HYPER_ENCODER_MODEL_SCHEMA {
        return Err(HyperEncoderError::CorruptArtifact("manifest schema"));
    }
    if manifest.hidden_features as usize != HYPER_ENCODER_HIDDEN
        || manifest.directed_relation_count != manifest.base_relation_count * 2
    {
        return Err(HyperEncoderError::CorruptArtifact("manifest shape"));
    }
    if manifest.manifest_id != manifest_identity(manifest)? {
        return Err(HyperEncoderError::CorruptArtifact("manifest identity"));
    }
    Ok(())
}

fn manifest_identity(
    manifest: &HyperEncoderModelManifest,
) -> Result<CompactString, HyperEncoderError> {
    let mut hasher = blake3::Hasher::new();
    for value in [
        manifest.schema_version.as_str(),
        manifest.model_id.as_str(),
        manifest.pair_id.as_str(),
        manifest.source_dataset_id.as_str(),
        manifest.source_binary_blake3.as_str(),
        manifest.task_id.as_str(),
        manifest.task_binary_blake3.as_str(),
        manifest.training.trainer_id.as_str(),
        manifest.training.initialization_blake3.as_str(),
        manifest.training.train_topology_blake3.as_str(),
        manifest.training.example_schedule_blake3.as_str(),
        manifest.training.optimizer_state_blake3.as_str(),
        manifest.validation.certificate_id.as_str(),
        manifest.weights_file.as_str(),
        manifest.weights_blake3.as_str(),
    ] {
        update_str(&mut hasher, value);
    }
    hasher.update(&manifest.candidate_universe.to_le_bytes());
    hasher.update(&manifest.base_relation_count.to_le_bytes());
    hasher.update(&manifest.directed_relation_count.to_le_bytes());
    hasher.update(&manifest.hidden_features.to_le_bytes());
    hasher.update(&manifest.config.seed.to_le_bytes());
    hasher.update(&[match manifest.config.mode {
        crate::HyperEncoderMode::CompgcnTriple => 1,
        crate::HyperEncoderMode::StareQualifiers => 2,
        crate::HyperEncoderMode::RoleOnly => 3,
        crate::HyperEncoderMode::ValueOnly => 4,
        crate::HyperEncoderMode::Shuffled => 5,
        crate::HyperEncoderMode::Detached => 6,
        crate::HyperEncoderMode::QueryOnly => 7,
        crate::HyperEncoderMode::MessageOnly => 8,
    }]);
    hasher.update(&manifest.training_config.epochs.to_le_bytes());
    hasher.update(
        &manifest
            .training_config
            .learning_rate
            .to_bits()
            .to_le_bytes(),
    );
    hasher.update(&manifest.training_config.l2.to_bits().to_le_bytes());
    hasher.update(&[manifest.training_config.negatives_per_positive]);
    for value in [
        manifest.training.train_statements,
        manifest.training.directed_messages,
        manifest.training.training_examples,
        manifest.training.optimizer_steps,
        manifest.training.gradient_arena_bytes,
        manifest.training.epoch_allocation_bytes,
        manifest.training.epoch_allocation_count,
        manifest.weights_bytes,
    ] {
        hasher.update(&value.to_le_bytes());
    }
    hasher.update(&[manifest.training.test_locked_during_training as u8]);
    Ok(format!("b3-{}", hasher.finalize().to_hex()).into())
}

fn update_str(hasher: &mut blake3::Hasher, value: &str) {
    hasher.update(&(value.len() as u64).to_le_bytes());
    hasher.update(value.as_bytes());
}

fn tensor_counts(nodes: usize, relations: usize) -> [usize; 6] {
    let matrix = HYPER_ENCODER_HIDDEN * HYPER_ENCODER_HIDDEN;
    [
        nodes * HYPER_ENCODER_HIDDEN,
        HYPER_ENCODER_DIRECTIONS * matrix,
        (relations + 1) * HYPER_ENCODER_HIDDEN,
        matrix,
        matrix,
        relations,
    ]
}

fn weights_finite(weights: &HyperEncoderWeights) -> bool {
    [
        &weights.node_embeddings,
        &weights.direction_weights,
        &weights.relation_embeddings,
        &weights.relation_projection,
        &weights.qualifier_projection,
        &weights.decoder_bias,
    ]
    .into_iter()
    .flatten()
    .all(|value| value.is_finite())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), HyperEncoderError> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
