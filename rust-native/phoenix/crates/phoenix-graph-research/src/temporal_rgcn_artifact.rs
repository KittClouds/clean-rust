use crate::{
    TemporalRgcnError, TemporalRgcnManifest, TemporalRgcnPaths, TemporalRgcnSnapshot,
    TemporalRgcnWeights, TEMPORAL_RGCN_BINARY_VERSION, TEMPORAL_RGCN_HIDDEN, TEMPORAL_RGCN_SCHEMA,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Component, Path};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXTRG01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct Header {
    magic: [u8; 8],
    version: [u8; 2],
    hidden: [u8; 2],
    nodes: [u8; 4],
    base_relations: [u8; 4],
    directed_relations: [u8; 4],
    total_bytes: [u8; 8],
    node_offset: [u8; 8],
    self_offset: [u8; 8],
    message_offset: [u8; 8],
    decoder_offset: [u8; 8],
    bias_offset: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct TemporalLeF32([u8; 4]);

impl TemporalLeF32 {
    pub fn get(self) -> f32 {
        f32::from_bits(u32::from_le_bytes(self.0))
    }
}

pub struct TemporalRgcnMapped {
    manifest: TemporalRgcnManifest,
    mmap: Mmap,
    node_offset: usize,
    self_offset: usize,
    message_offset: usize,
    decoder_offset: usize,
    bias_offset: usize,
}

impl TemporalRgcnMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, TemporalRgcnError> {
        let path = path.as_ref();
        let manifest: TemporalRgcnManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let weight_name = Path::new(manifest.weights_file.as_str());
        let mut components = weight_name.components();
        if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
            return Err(TemporalRgcnError::CorruptArtifact("weights path"));
        }
        let file = File::open(
            path.parent()
                .unwrap_or_else(|| Path::new("."))
                .join(weight_name),
        )?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() as u64 != manifest.weights_bytes
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.weights_blake3
        {
            return Err(TemporalRgcnError::CorruptArtifact("weights identity"));
        }
        let header = Ref::<_, Header>::new(
            mmap.get(..size_of::<Header>())
                .ok_or(TemporalRgcnError::CorruptArtifact("header"))?,
        )
        .ok_or(TemporalRgcnError::CorruptArtifact("header"))?;
        validate_header(&header, &manifest, mmap.len())?;
        Ok(Self {
            node_offset: le_usize(header.node_offset)?,
            self_offset: le_usize(header.self_offset)?,
            message_offset: le_usize(header.message_offset)?,
            decoder_offset: le_usize(header.decoder_offset)?,
            bias_offset: le_usize(header.bias_offset)?,
            manifest,
            mmap,
        })
    }

    pub fn manifest(&self) -> &TemporalRgcnManifest {
        &self.manifest
    }

    pub fn node_embeddings(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalRgcnError> {
        mapped(&self.mmap, self.node_offset, self.node_elements())
    }

    pub fn self_weight(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalRgcnError> {
        mapped(&self.mmap, self.self_offset, TEMPORAL_RGCN_HIDDEN.pow(2))
    }

    pub fn relation_weights(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalRgcnError> {
        mapped(
            &self.mmap,
            self.message_offset,
            self.directed_relations() * TEMPORAL_RGCN_HIDDEN.pow(2),
        )
    }

    pub fn decoder_relations(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalRgcnError> {
        mapped(
            &self.mmap,
            self.decoder_offset,
            self.directed_relations() * TEMPORAL_RGCN_HIDDEN,
        )
    }

    pub fn decoder_bias(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalRgcnError> {
        mapped(&self.mmap, self.bias_offset, self.directed_relations())
    }

    fn node_elements(&self) -> usize {
        self.manifest.candidate_universe as usize * TEMPORAL_RGCN_HIDDEN
    }

    fn directed_relations(&self) -> usize {
        self.manifest.directed_relation_count as usize
    }
}

pub fn write_temporal_rgcn(
    snapshot: &TemporalRgcnSnapshot,
    root: impl AsRef<Path>,
) -> Result<TemporalRgcnPaths, TemporalRgcnError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    let weights_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
    let model_id = model_identity(snapshot, &weights_blake3, bytes.len() as u64)?;
    if snapshot.validation.model_id != model_id {
        return Err(TemporalRgcnError::InvalidContract(
            "validation model identity",
        ));
    }
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let weights_file = format!("{weights_blake3}.trw");
    let weights = root.join(&weights_file);
    let mut manifest = TemporalRgcnManifest {
        schema_version: TEMPORAL_RGCN_SCHEMA.into(),
        manifest_id: "pending".into(),
        model_id: model_id.as_str().into(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        task_id: snapshot.task_id.clone(),
        task_binary_blake3: snapshot.task_binary_blake3.clone(),
        candidate_universe: snapshot.candidate_universe,
        base_relation_count: snapshot.base_relation_count,
        directed_relation_count: snapshot.base_relation_count * 2,
        hidden_features: TEMPORAL_RGCN_HIDDEN as u16,
        config: snapshot.config,
        runtime: snapshot.runtime.clone(),
        training: snapshot.training.clone(),
        baseline: snapshot.baseline.clone(),
        validation: snapshot.validation.clone(),
        weights_file: weights_file.into(),
        weights_blake3: weights_blake3.into(),
        weights_bytes: bytes.len() as u64,
    };
    manifest.manifest_id = score_manifest_identity(&manifest)?.into();
    let manifest_path = root.join(format!("{}.temporal-rgcn.json", manifest.manifest_id));
    if weights.exists() || manifest_path.exists() {
        return Err(TemporalRgcnError::ArtifactExists(manifest_path));
    }
    write_new(&weights, &bytes)?;
    if let Err(error) = write_new(&manifest_path, &serde_json::to_vec_pretty(&manifest)?) {
        let _ = std::fs::remove_file(&weights);
        return Err(error);
    }
    Ok(TemporalRgcnPaths {
        manifest: manifest_path,
        weights,
        manifest_id: manifest.manifest_id,
        model_id: model_id.into(),
    })
}

pub fn temporal_rgcn_model_identity(
    snapshot: &TemporalRgcnSnapshot,
) -> Result<String, TemporalRgcnError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    let digest = format!("b3-{}", blake3::hash(&bytes).to_hex());
    model_identity(snapshot, &digest, bytes.len() as u64)
}

fn validate_snapshot(snapshot: &TemporalRgcnSnapshot) -> Result<(), TemporalRgcnError> {
    snapshot.config.validate()?;
    let directed = snapshot
        .base_relation_count
        .checked_mul(2)
        .ok_or(TemporalRgcnError::InvalidContract("relation overflow"))?;
    let expected = expected_lengths(snapshot.candidate_universe, directed)?;
    let actual = [
        snapshot.weights.node_embeddings.len(),
        snapshot.weights.self_weight.len(),
        snapshot.weights.relation_weights.len(),
        snapshot.weights.decoder_relations.len(),
        snapshot.weights.decoder_bias.len(),
    ];
    if snapshot.source_dataset_id.is_empty()
        || snapshot.source_binary_blake3.is_empty()
        || snapshot.task_id.is_empty()
        || snapshot.task_binary_blake3.is_empty()
        || snapshot.candidate_universe == 0
        || snapshot.base_relation_count == 0
        || snapshot.runtime.framework.is_empty()
        || snapshot.runtime.backend.is_empty()
        || !snapshot.training.test_locked_during_training
        || snapshot.training.train_facts == 0
        || snapshot.training.directed_messages != snapshot.training.train_facts * 2
        || snapshot.training.training_examples == 0
        || snapshot.training.optimizer_steps == 0
        || snapshot.training.train_topology_blake3.is_empty()
        || snapshot.validation.task_id != snapshot.task_id
        || snapshot.baseline.task_id != snapshot.task_id
        || snapshot.baseline.split != crate::LinkPredictionSplit::Validation
        || snapshot.validation.split != crate::LinkPredictionSplit::Validation
        || snapshot.validation.mean_reciprocal_rank <= snapshot.baseline.mean_reciprocal_rank
        || actual != expected
        || snapshot
            .weights
            .all()
            .into_iter()
            .any(|values| values.iter().any(|value| !value.is_finite()))
    {
        return Err(TemporalRgcnError::InvalidContract("snapshot"));
    }
    Ok(())
}

impl TemporalRgcnWeights {
    fn all(&self) -> [&[f32]; 5] {
        [
            &self.node_embeddings,
            &self.self_weight,
            &self.relation_weights,
            &self.decoder_relations,
            &self.decoder_bias,
        ]
    }
}

fn encode(snapshot: &TemporalRgcnSnapshot) -> Result<Vec<u8>, TemporalRgcnError> {
    let directed = snapshot.base_relation_count * 2;
    let lengths = expected_lengths(snapshot.candidate_universe, directed)?;
    let mut offsets = [0_usize; 5];
    offsets[0] = size_of::<Header>();
    for index in 1..5 {
        offsets[index] = offsets[index - 1]
            .checked_add(lengths[index - 1] * 4)
            .ok_or(TemporalRgcnError::InvalidContract("weight size"))?;
    }
    let total = offsets[4]
        .checked_add(lengths[4] * 4)
        .ok_or(TemporalRgcnError::InvalidContract("weight size"))?;
    let header = Header {
        magic: MAGIC,
        version: TEMPORAL_RGCN_BINARY_VERSION.to_le_bytes(),
        hidden: (TEMPORAL_RGCN_HIDDEN as u16).to_le_bytes(),
        nodes: snapshot.candidate_universe.to_le_bytes(),
        base_relations: snapshot.base_relation_count.to_le_bytes(),
        directed_relations: directed.to_le_bytes(),
        total_bytes: (total as u64).to_le_bytes(),
        node_offset: (offsets[0] as u64).to_le_bytes(),
        self_offset: (offsets[1] as u64).to_le_bytes(),
        message_offset: (offsets[2] as u64).to_le_bytes(),
        decoder_offset: (offsets[3] as u64).to_le_bytes(),
        bias_offset: (offsets[4] as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total);
    bytes.extend_from_slice(header.as_bytes());
    for values in snapshot.weights.all() {
        for value in values {
            bytes.extend_from_slice(&value.to_bits().to_le_bytes());
        }
    }
    Ok(bytes)
}

fn validate_manifest(manifest: &TemporalRgcnManifest) -> Result<(), TemporalRgcnError> {
    let directed = manifest
        .base_relation_count
        .checked_mul(2)
        .ok_or(TemporalRgcnError::CorruptArtifact("relation overflow"))?;
    if manifest.schema_version != TEMPORAL_RGCN_SCHEMA
        || manifest.hidden_features as usize != TEMPORAL_RGCN_HIDDEN
        || manifest.directed_relation_count != directed
        || manifest.validation.model_id != manifest.model_id
        || manifest.baseline.task_id != manifest.task_id
        || manifest.baseline.split != crate::LinkPredictionSplit::Validation
        || manifest.validation.task_id != manifest.task_id
        || manifest.validation.split != crate::LinkPredictionSplit::Validation
        || manifest.validation.mean_reciprocal_rank <= manifest.baseline.mean_reciprocal_rank
        || manifest.model_id != manifest_identity(manifest)?
        || manifest.manifest_id != score_manifest_identity(manifest)?
    {
        return Err(TemporalRgcnError::CorruptArtifact("manifest"));
    }
    Ok(())
}

fn validate_header(
    header: &Header,
    manifest: &TemporalRgcnManifest,
    bytes: usize,
) -> Result<(), TemporalRgcnError> {
    let lengths = expected_lengths(
        manifest.candidate_universe,
        manifest.directed_relation_count,
    )?;
    let offsets = [
        le_usize(header.node_offset)?,
        le_usize(header.self_offset)?,
        le_usize(header.message_offset)?,
        le_usize(header.decoder_offset)?,
        le_usize(header.bias_offset)?,
    ];
    let mut expected = size_of::<Header>();
    for index in 0..5 {
        if offsets[index] != expected {
            return Err(TemporalRgcnError::CorruptArtifact("weight layout"));
        }
        expected = expected
            .checked_add(lengths[index] * 4)
            .ok_or(TemporalRgcnError::CorruptArtifact("weight size"))?;
    }
    if header.magic != MAGIC
        || u16::from_le_bytes(header.version) != TEMPORAL_RGCN_BINARY_VERSION
        || u16::from_le_bytes(header.hidden) as usize != TEMPORAL_RGCN_HIDDEN
        || u32::from_le_bytes(header.nodes) != manifest.candidate_universe
        || u32::from_le_bytes(header.base_relations) != manifest.base_relation_count
        || u32::from_le_bytes(header.directed_relations) != manifest.directed_relation_count
        || le_usize(header.total_bytes)? != bytes
        || expected != bytes
    {
        return Err(TemporalRgcnError::CorruptArtifact("header"));
    }
    Ok(())
}

fn expected_lengths(nodes: u32, directed: u32) -> Result<[usize; 5], TemporalRgcnError> {
    let nodes = nodes as usize;
    let directed = directed as usize;
    Ok([
        nodes
            .checked_mul(TEMPORAL_RGCN_HIDDEN)
            .ok_or(TemporalRgcnError::InvalidContract("node weights"))?,
        TEMPORAL_RGCN_HIDDEN.pow(2),
        directed
            .checked_mul(TEMPORAL_RGCN_HIDDEN.pow(2))
            .ok_or(TemporalRgcnError::InvalidContract("message weights"))?,
        directed
            .checked_mul(TEMPORAL_RGCN_HIDDEN)
            .ok_or(TemporalRgcnError::InvalidContract("decoder weights"))?,
        directed,
    ])
}

fn model_identity(
    snapshot: &TemporalRgcnSnapshot,
    weights_blake3: &str,
    weights_bytes: u64,
) -> Result<String, TemporalRgcnError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            TEMPORAL_RGCN_SCHEMA,
            snapshot.source_dataset_id.as_str(),
            snapshot.source_binary_blake3.as_str(),
            snapshot.task_id.as_str(),
            snapshot.task_binary_blake3.as_str(),
            snapshot.candidate_universe,
            snapshot.base_relation_count,
            snapshot.config,
            &snapshot.runtime,
            &snapshot.training,
            weights_blake3,
            weights_bytes,
        ))?)
        .to_hex()
    ))
}

fn manifest_identity(manifest: &TemporalRgcnManifest) -> Result<String, TemporalRgcnError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            TEMPORAL_RGCN_SCHEMA,
            manifest.source_dataset_id.as_str(),
            manifest.source_binary_blake3.as_str(),
            manifest.task_id.as_str(),
            manifest.task_binary_blake3.as_str(),
            manifest.candidate_universe,
            manifest.base_relation_count,
            manifest.config,
            &manifest.runtime,
            &manifest.training,
            manifest.weights_blake3.as_str(),
            manifest.weights_bytes,
        ))?)
        .to_hex()
    ))
}

fn score_manifest_identity(manifest: &TemporalRgcnManifest) -> Result<String, TemporalRgcnError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            TEMPORAL_RGCN_SCHEMA,
            manifest.model_id.as_str(),
            &manifest.baseline,
            &manifest.validation,
        ))?)
        .to_hex()
    ))
}

fn mapped<T: FromBytes + Unaligned>(
    bytes: &[u8],
    offset: usize,
    count: usize,
) -> Result<Ref<&[u8], [T]>, TemporalRgcnError> {
    let end = count
        .checked_mul(size_of::<T>())
        .and_then(|len| offset.checked_add(len))
        .ok_or(TemporalRgcnError::CorruptArtifact("weight range"))?;
    Ref::new_slice(
        bytes
            .get(offset..end)
            .ok_or(TemporalRgcnError::CorruptArtifact("weight range"))?,
    )
    .ok_or(TemporalRgcnError::CorruptArtifact("weight alignment"))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), TemporalRgcnError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn le_usize(bytes: [u8; 8]) -> Result<usize, TemporalRgcnError> {
    usize::try_from(u64::from_le_bytes(bytes))
        .map_err(|_| TemporalRgcnError::CorruptArtifact("integer overflow"))
}
