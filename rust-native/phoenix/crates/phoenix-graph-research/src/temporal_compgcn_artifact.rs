use crate::temporal_rgcn_artifact::TemporalLeF32;
use crate::{
    LinkPredictionSplit, TemporalCompgcnError, TemporalCompgcnManifest, TemporalCompgcnPaths,
    TemporalCompgcnSnapshot, TemporalCompgcnWeights, TEMPORAL_COMPGCN_BINARY_VERSION,
    TEMPORAL_COMPGCN_DIRECTIONS, TEMPORAL_COMPGCN_HIDDEN, TEMPORAL_COMPGCN_SCHEMA,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Component, Path};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXTCG01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct Header {
    magic: [u8; 8],
    version: [u8; 2],
    hidden: [u8; 2],
    nodes: [u8; 4],
    directed_relations: [u8; 4],
    total_bytes: [u8; 8],
    offsets: [[u8; 8]; 5],
}

pub struct TemporalCompgcnMapped {
    manifest: TemporalCompgcnManifest,
    mmap: Mmap,
    offsets: [usize; 5],
}

impl TemporalCompgcnMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, TemporalCompgcnError> {
        let path = path.as_ref();
        let manifest: TemporalCompgcnManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let weight_name = Path::new(manifest.weights_file.as_str());
        let mut components = weight_name.components();
        if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
            return Err(TemporalCompgcnError::CorruptArtifact("weights path"));
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
            return Err(TemporalCompgcnError::CorruptArtifact("weights identity"));
        }
        let header = Ref::<_, Header>::new(
            mmap.get(..size_of::<Header>())
                .ok_or(TemporalCompgcnError::CorruptArtifact("header"))?,
        )
        .ok_or(TemporalCompgcnError::CorruptArtifact("header"))?;
        let offsets = validate_header(&header, &manifest, mmap.len())?;
        Ok(Self {
            manifest,
            mmap,
            offsets,
        })
    }

    pub fn manifest(&self) -> &TemporalCompgcnManifest {
        &self.manifest
    }

    pub fn node_embeddings(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalCompgcnError> {
        mapped(&self.mmap, self.offsets[0], self.lengths()?[0])
    }

    pub fn direction_weights(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalCompgcnError> {
        mapped(&self.mmap, self.offsets[1], self.lengths()?[1])
    }

    pub fn relation_embeddings(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalCompgcnError> {
        mapped(&self.mmap, self.offsets[2], self.lengths()?[2])
    }

    pub fn relation_projection(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalCompgcnError> {
        mapped(&self.mmap, self.offsets[3], self.lengths()?[3])
    }

    pub fn decoder_bias(&self) -> Result<Ref<&[u8], [TemporalLeF32]>, TemporalCompgcnError> {
        mapped(&self.mmap, self.offsets[4], self.lengths()?[4])
    }

    fn lengths(&self) -> Result<[usize; 5], TemporalCompgcnError> {
        expected_lengths(
            self.manifest.candidate_universe,
            self.manifest.directed_relation_count,
        )
    }
}

pub fn write_temporal_compgcn(
    snapshot: &TemporalCompgcnSnapshot,
    root: impl AsRef<Path>,
) -> Result<TemporalCompgcnPaths, TemporalCompgcnError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    let weights_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
    let model_id = model_identity(snapshot, &weights_blake3, bytes.len() as u64)?;
    if snapshot.validation.model_id != model_id {
        return Err(TemporalCompgcnError::InvalidContract(
            "validation model identity",
        ));
    }
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let weights_file = format!("{weights_blake3}.tcw");
    let weights_path = root.join(&weights_file);
    let mut manifest = TemporalCompgcnManifest {
        schema_version: TEMPORAL_COMPGCN_SCHEMA.into(),
        manifest_id: "pending".into(),
        model_id: model_id.as_str().into(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        task_id: snapshot.task_id.clone(),
        task_binary_blake3: snapshot.task_binary_blake3.clone(),
        candidate_universe: snapshot.candidate_universe,
        base_relation_count: snapshot.base_relation_count,
        directed_relation_count: snapshot.base_relation_count * 2,
        hidden_features: TEMPORAL_COMPGCN_HIDDEN as u16,
        control_manifest_id: snapshot.control_manifest_id.clone(),
        control_model_id: snapshot.control_model_id.clone(),
        config: snapshot.config,
        runtime: snapshot.runtime.clone(),
        training: snapshot.training.clone(),
        baseline: snapshot.baseline.clone(),
        control: snapshot.control.clone(),
        validation: snapshot.validation.clone(),
        weights_file: weights_file.into(),
        weights_blake3: weights_blake3.into(),
        weights_bytes: bytes.len() as u64,
    };
    manifest.manifest_id = score_manifest_identity(&manifest)?.into();
    let manifest_path = root.join(format!("{}.temporal-compgcn.json", manifest.manifest_id));
    if weights_path.exists() || manifest_path.exists() {
        return Err(TemporalCompgcnError::ArtifactExists(manifest_path));
    }
    write_new(&weights_path, &bytes)?;
    if let Err(error) = write_new(&manifest_path, &serde_json::to_vec_pretty(&manifest)?) {
        let _ = std::fs::remove_file(&weights_path);
        return Err(error);
    }
    Ok(TemporalCompgcnPaths {
        manifest: manifest_path,
        weights: weights_path,
        manifest_id: manifest.manifest_id,
        model_id: model_id.into(),
    })
}

pub fn temporal_compgcn_model_identity(
    snapshot: &TemporalCompgcnSnapshot,
) -> Result<String, TemporalCompgcnError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    model_identity(
        snapshot,
        &format!("b3-{}", blake3::hash(&bytes).to_hex()),
        bytes.len() as u64,
    )
}

pub fn temporal_compgcn_weights_identity(
    snapshot: &TemporalCompgcnSnapshot,
) -> Result<(String, u64), TemporalCompgcnError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    Ok((
        format!("b3-{}", blake3::hash(&bytes).to_hex()),
        bytes.len() as u64,
    ))
}

fn validate_snapshot(snapshot: &TemporalCompgcnSnapshot) -> Result<(), TemporalCompgcnError> {
    snapshot.config.validate()?;
    let directed = snapshot
        .base_relation_count
        .checked_mul(2)
        .ok_or(TemporalCompgcnError::InvalidContract("relation overflow"))?;
    let expected = expected_lengths(snapshot.candidate_universe, directed)?;
    let actual = snapshot.weights.lengths();
    if snapshot.source_dataset_id.is_empty()
        || snapshot.source_binary_blake3.is_empty()
        || snapshot.task_id.is_empty()
        || snapshot.task_binary_blake3.is_empty()
        || snapshot.candidate_universe == 0
        || snapshot.base_relation_count == 0
        || snapshot.control_manifest_id.is_empty()
        || snapshot.control_model_id != snapshot.control.model_id
        || snapshot.runtime.framework.is_empty()
        || !snapshot.training.test_locked_during_training
        || snapshot.training.train_facts == 0
        || snapshot.training.directed_messages != snapshot.training.train_facts * 2
        || snapshot.training.optimizer_steps == 0
        || snapshot.training.train_topology_blake3.is_empty()
        || snapshot.baseline.task_id != snapshot.task_id
        || snapshot.control.task_id != snapshot.task_id
        || snapshot.validation.task_id != snapshot.task_id
        || snapshot.baseline.split != LinkPredictionSplit::Validation
        || snapshot.control.split != LinkPredictionSplit::Validation
        || snapshot.validation.split != LinkPredictionSplit::Validation
        || snapshot.validation.mean_reciprocal_rank <= snapshot.control.mean_reciprocal_rank
        || actual != expected
        || snapshot
            .weights
            .all()
            .into_iter()
            .any(|values| values.iter().any(|value| !value.is_finite()))
    {
        return Err(TemporalCompgcnError::InvalidContract("snapshot"));
    }
    Ok(())
}

impl TemporalCompgcnWeights {
    fn all(&self) -> [&[f32]; 5] {
        [
            &self.node_embeddings,
            &self.direction_weights,
            &self.relation_embeddings,
            &self.relation_projection,
            &self.decoder_bias,
        ]
    }

    fn lengths(&self) -> [usize; 5] {
        self.all().map(<[f32]>::len)
    }
}

fn encode(snapshot: &TemporalCompgcnSnapshot) -> Result<Vec<u8>, TemporalCompgcnError> {
    let lengths = expected_lengths(
        snapshot.candidate_universe,
        snapshot.base_relation_count * 2,
    )?;
    let mut offsets = [0_usize; 5];
    offsets[0] = size_of::<Header>();
    for index in 1..5 {
        offsets[index] = offsets[index - 1]
            .checked_add(lengths[index - 1] * 4)
            .ok_or(TemporalCompgcnError::InvalidContract("weight size"))?;
    }
    let total = offsets[4]
        .checked_add(lengths[4] * 4)
        .ok_or(TemporalCompgcnError::InvalidContract("weight size"))?;
    let header = Header {
        magic: MAGIC,
        version: TEMPORAL_COMPGCN_BINARY_VERSION.to_le_bytes(),
        hidden: (TEMPORAL_COMPGCN_HIDDEN as u16).to_le_bytes(),
        nodes: snapshot.candidate_universe.to_le_bytes(),
        directed_relations: (snapshot.base_relation_count * 2).to_le_bytes(),
        total_bytes: (total as u64).to_le_bytes(),
        offsets: offsets.map(|value| (value as u64).to_le_bytes()),
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

fn validate_manifest(manifest: &TemporalCompgcnManifest) -> Result<(), TemporalCompgcnError> {
    let directed = manifest
        .base_relation_count
        .checked_mul(2)
        .ok_or(TemporalCompgcnError::CorruptArtifact("relation overflow"))?;
    if manifest.schema_version != TEMPORAL_COMPGCN_SCHEMA
        || manifest.hidden_features as usize != TEMPORAL_COMPGCN_HIDDEN
        || manifest.directed_relation_count != directed
        || manifest.control_model_id != manifest.control.model_id
        || manifest.validation.model_id != manifest.model_id
        || manifest.baseline.task_id != manifest.task_id
        || manifest.control.task_id != manifest.task_id
        || manifest.validation.task_id != manifest.task_id
        || manifest.validation.mean_reciprocal_rank <= manifest.control.mean_reciprocal_rank
        || manifest.model_id != manifest_identity(manifest)?
        || manifest.manifest_id != score_manifest_identity(manifest)?
    {
        return Err(TemporalCompgcnError::CorruptArtifact("manifest"));
    }
    Ok(())
}

fn validate_header(
    header: &Header,
    manifest: &TemporalCompgcnManifest,
    bytes: usize,
) -> Result<[usize; 5], TemporalCompgcnError> {
    let lengths = expected_lengths(
        manifest.candidate_universe,
        manifest.directed_relation_count,
    )?;
    let mut offsets = [0_usize; 5];
    let mut expected = size_of::<Header>();
    for index in 0..5 {
        offsets[index] = le_usize(header.offsets[index])?;
        if offsets[index] != expected {
            return Err(TemporalCompgcnError::CorruptArtifact("weight layout"));
        }
        expected = expected
            .checked_add(lengths[index] * 4)
            .ok_or(TemporalCompgcnError::CorruptArtifact("weight size"))?;
    }
    if header.magic != MAGIC
        || u16::from_le_bytes(header.version) != TEMPORAL_COMPGCN_BINARY_VERSION
        || u16::from_le_bytes(header.hidden) as usize != TEMPORAL_COMPGCN_HIDDEN
        || u32::from_le_bytes(header.nodes) != manifest.candidate_universe
        || u32::from_le_bytes(header.directed_relations) != manifest.directed_relation_count
        || le_usize(header.total_bytes)? != bytes
        || expected != bytes
    {
        return Err(TemporalCompgcnError::CorruptArtifact("header"));
    }
    Ok(offsets)
}

fn expected_lengths(nodes: u32, directed: u32) -> Result<[usize; 5], TemporalCompgcnError> {
    let nodes = nodes as usize;
    let directed = directed as usize;
    Ok([
        nodes
            .checked_mul(TEMPORAL_COMPGCN_HIDDEN)
            .ok_or(TemporalCompgcnError::InvalidContract("node weights"))?,
        TEMPORAL_COMPGCN_DIRECTIONS * TEMPORAL_COMPGCN_HIDDEN.pow(2),
        directed
            .checked_add(1)
            .and_then(|count| count.checked_mul(TEMPORAL_COMPGCN_HIDDEN))
            .ok_or(TemporalCompgcnError::InvalidContract("relation weights"))?,
        TEMPORAL_COMPGCN_HIDDEN.pow(2),
        directed,
    ])
}

fn model_identity(
    snapshot: &TemporalCompgcnSnapshot,
    weights_blake3: &str,
    weights_bytes: u64,
) -> Result<String, TemporalCompgcnError> {
    identity(&(
        TEMPORAL_COMPGCN_SCHEMA,
        snapshot.source_dataset_id.as_str(),
        snapshot.source_binary_blake3.as_str(),
        snapshot.task_id.as_str(),
        snapshot.task_binary_blake3.as_str(),
        snapshot.candidate_universe,
        snapshot.base_relation_count,
        snapshot.control_manifest_id.as_str(),
        snapshot.control_model_id.as_str(),
        snapshot.config,
        &snapshot.runtime,
        &snapshot.training,
        weights_blake3,
        weights_bytes,
    ))
}

fn manifest_identity(manifest: &TemporalCompgcnManifest) -> Result<String, TemporalCompgcnError> {
    identity(&(
        TEMPORAL_COMPGCN_SCHEMA,
        manifest.source_dataset_id.as_str(),
        manifest.source_binary_blake3.as_str(),
        manifest.task_id.as_str(),
        manifest.task_binary_blake3.as_str(),
        manifest.candidate_universe,
        manifest.base_relation_count,
        manifest.control_manifest_id.as_str(),
        manifest.control_model_id.as_str(),
        manifest.config,
        &manifest.runtime,
        &manifest.training,
        manifest.weights_blake3.as_str(),
        manifest.weights_bytes,
    ))
}

fn score_manifest_identity(
    manifest: &TemporalCompgcnManifest,
) -> Result<String, TemporalCompgcnError> {
    identity(&(
        TEMPORAL_COMPGCN_SCHEMA,
        manifest.model_id.as_str(),
        &manifest.baseline,
        &manifest.control,
        &manifest.validation,
    ))
}

fn identity<T: serde::Serialize>(value: &T) -> Result<String, TemporalCompgcnError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}

fn mapped<T: FromBytes + Unaligned>(
    bytes: &[u8],
    offset: usize,
    count: usize,
) -> Result<Ref<&[u8], [T]>, TemporalCompgcnError> {
    let end = count
        .checked_mul(size_of::<T>())
        .and_then(|length| offset.checked_add(length))
        .ok_or(TemporalCompgcnError::CorruptArtifact("weight range"))?;
    Ref::new_slice(
        bytes
            .get(offset..end)
            .ok_or(TemporalCompgcnError::CorruptArtifact("weight range"))?,
    )
    .ok_or(TemporalCompgcnError::CorruptArtifact("weight alignment"))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), TemporalCompgcnError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn le_usize(bytes: [u8; 8]) -> Result<usize, TemporalCompgcnError> {
    usize::try_from(u64::from_le_bytes(bytes))
        .map_err(|_| TemporalCompgcnError::CorruptArtifact("integer overflow"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        LinkPredictionScoreCertificate, TemporalCompgcnConfig, TemporalCompgcnTrainingReceipt,
        TemporalComposition, TemporalRelationUpdate, TemporalRgcnConfig,
        TemporalRgcnRuntimeIdentity,
    };
    use compact_str::CompactString;
    use std::io::{Seek, SeekFrom};

    #[test]
    fn artifact_round_trips_and_rejects_weight_corruption() {
        let root = tempfile::tempdir().expect("root");
        let mut snapshot = fixture();
        snapshot.validation.model_id = temporal_compgcn_model_identity(&snapshot)
            .expect("model identity")
            .into();
        let paths = write_temporal_compgcn(&snapshot, root.path()).expect("write");
        let mapped = TemporalCompgcnMapped::open(&paths.manifest).expect("mmap");
        assert_eq!(mapped.manifest().model_id, paths.model_id);
        assert_eq!(mapped.node_embeddings().expect("nodes").len(), 32);
        assert_eq!(mapped.direction_weights().expect("directions").len(), 768);
        assert_eq!(mapped.relation_embeddings().expect("relations").len(), 48);
        drop(mapped);

        let mut file = OpenOptions::new()
            .write(true)
            .open(&paths.weights)
            .expect("weights");
        file.seek(SeekFrom::Start(size_of::<Header>() as u64 + 3))
            .expect("seek");
        file.write_all(&[0xff]).expect("corrupt");
        file.sync_all().expect("sync");
        assert!(matches!(
            TemporalCompgcnMapped::open(paths.manifest),
            Err(TemporalCompgcnError::CorruptArtifact("weights identity"))
        ));
    }

    #[test]
    fn composition_and_relation_update_are_model_identity_axes() {
        let multiply = fixture();
        let multiply_id = temporal_compgcn_model_identity(&multiply).expect("multiply identity");
        let mut subtract = multiply.clone();
        subtract.config.composition = TemporalComposition::Subtract;
        let subtract_id = temporal_compgcn_model_identity(&subtract).expect("subtract identity");
        let mut frozen = multiply;
        frozen.config.relation_update = TemporalRelationUpdate::Frozen;
        let frozen_id = temporal_compgcn_model_identity(&frozen).expect("frozen identity");
        assert_ne!(multiply_id, subtract_id);
        assert_ne!(multiply_id, frozen_id);
        assert_ne!(subtract_id, frozen_id);
    }

    fn fixture() -> TemporalCompgcnSnapshot {
        let task_id: CompactString = "b3-task".into();
        let control_model_id: CompactString = "b3-control-model".into();
        TemporalCompgcnSnapshot {
            source_dataset_id: "b3-source".into(),
            source_binary_blake3: "b3-source-binary".into(),
            task_id: task_id.clone(),
            task_binary_blake3: "b3-task-binary".into(),
            candidate_universe: 2,
            base_relation_count: 1,
            control_manifest_id: "b3-control-manifest".into(),
            control_model_id: control_model_id.clone(),
            config: TemporalCompgcnConfig {
                base: TemporalRgcnConfig::default(),
                composition: TemporalComposition::Multiply,
                relation_update: TemporalRelationUpdate::JointLinear,
            },
            runtime: TemporalRgcnRuntimeIdentity {
                framework: "fixture".into(),
                framework_version: "1".into(),
                backend: "cpu".into(),
                target: "test".into(),
            },
            training: TemporalCompgcnTrainingReceipt {
                trainer_id: "fixture".into(),
                train_facts: 2,
                directed_messages: 4,
                training_examples: 8,
                optimizer_steps: 1,
                optimizer_state_blake3: "b3-optimizer".into(),
                train_topology_blake3: "b3-topology".into(),
                relation_state_bytes: 192,
                test_locked_during_training: true,
            },
            baseline: certificate(&task_id, "b3-baseline", 0.25),
            control: certificate(&task_id, &control_model_id, 0.5),
            validation: certificate(&task_id, "pending", 0.75),
            weights: TemporalCompgcnWeights {
                node_embeddings: vec![0.1; 32],
                direction_weights: vec![0.2; 768],
                relation_embeddings: vec![0.3; 48],
                relation_projection: vec![0.4; 256],
                decoder_bias: vec![0.0; 2],
            },
        }
    }

    fn certificate(task_id: &str, model_id: &str, mrr: f64) -> LinkPredictionScoreCertificate {
        LinkPredictionScoreCertificate {
            schema_version: "fixture".into(),
            certificate_id: format!("certificate-{mrr}").into(),
            task_id: task_id.into(),
            model_id: model_id.into(),
            split: LinkPredictionSplit::Validation,
            score_blake3: format!("score-{mrr}").into(),
            mean_reciprocal_rank: mrr,
            hits_at_1: 0.0,
            hits_at_3: 0.0,
            hits_at_10: 0.0,
            queries: 1,
            positives: 1,
            candidates_scored: 2,
        }
    }
}
