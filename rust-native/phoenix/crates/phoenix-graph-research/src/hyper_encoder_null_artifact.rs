use crate::{
    encode_role_scoped_qualifier_null, ExternalDatasetMapped, HyperEncoderConfig,
    HyperEncoderEncoded, HyperEncoderError, HyperEncoderMapped, HyperEncoderMode,
    HyperEncoderStagedInput, HyperParameterClass, HyperParameterSource, HyperSemanticRole,
    QualifierNullCompositionManifest, QualifierNullCompositionPaths, QualifierNullRoutingReceipt,
    QUALIFIER_NULL_COMPOSITION_SCHEMA, QUALIFIER_NULL_EVALUATION_SURFACE,
    QUALIFIER_NULL_ROUTING_POLICY,
};
use compact_str::CompactString;
use hashbrown::HashSet;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Component, Path, PathBuf};

pub struct QualifierNullCompositionMapped {
    manifest: QualifierNullCompositionManifest,
    trained_backbone: HyperEncoderMapped,
    checkpoint_zero: HyperEncoderMapped,
}

impl QualifierNullCompositionMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, HyperEncoderError> {
        let path = path.as_ref();
        let manifest: QualifierNullCompositionManifest =
            serde_json::from_slice(&std::fs::read(path)?)?;
        validate_composition_manifest(&manifest)?;
        let root = path.parent().unwrap_or_else(|| Path::new("."));
        let backbone_path = resolve_parent(root, manifest.trained_backbone_manifest_file.as_str())?;
        let checkpoint_path =
            resolve_parent(root, manifest.checkpoint_zero_manifest_file.as_str())?;
        let trained_backbone = HyperEncoderMapped::open(backbone_path)?;
        let checkpoint_zero = HyperEncoderMapped::open(checkpoint_path)?;
        validate_parents(&manifest, &trained_backbone, &checkpoint_zero)?;
        Ok(Self {
            manifest,
            trained_backbone,
            checkpoint_zero,
        })
    }

    pub fn manifest(&self) -> &QualifierNullCompositionManifest {
        &self.manifest
    }

    pub fn trained_backbone(&self) -> &HyperEncoderMapped {
        &self.trained_backbone
    }

    pub fn checkpoint_zero(&self) -> &HyperEncoderMapped {
        &self.checkpoint_zero
    }

    pub fn encode<'a>(
        &'a self,
        source: &ExternalDatasetMapped,
        staged: &HyperEncoderStagedInput,
    ) -> Result<HyperEncoderEncoded<'a>, HyperEncoderError> {
        if source.manifest().dataset_id != self.manifest.source_dataset_id
            || source.manifest().binary_blake3 != self.manifest.source_binary_blake3
            || staged.task_id != self.manifest.task_identity
            || staged.task_binary_blake3 != self.manifest.task_binary_blake3
        {
            return Err(HyperEncoderError::InvalidContract(
                "qualifier null source authority",
            ));
        }
        encode_role_scoped_qualifier_null(
            source,
            staged,
            HyperEncoderConfig::stare(self.checkpoint_zero.manifest().config.seed),
            self.trained_backbone.weight_view()?,
            self.checkpoint_zero.weight_view()?,
            self.manifest.composition_id.clone(),
        )
    }

    pub fn routing_receipt(
        &self,
        source: &ExternalDatasetMapped,
        staged: &HyperEncoderStagedInput,
    ) -> Result<QualifierNullRoutingReceipt, HyperEncoderError> {
        let qualifiers = source.qualifiers()?;
        let mut primary_entities = HashSet::<u32>::new();
        let mut primary_relations = HashSet::<u32>::new();
        for (relation, batch) in staged.relation_batches.iter().enumerate() {
            if !batch.sources.is_empty() {
                primary_relations.insert(relation as u32);
            }
            primary_entities.extend(batch.sources.iter().copied());
            primary_entities.extend(batch.targets.iter().copied());
        }
        let mut qualifier_values = HashSet::<u32>::new();
        let mut qualifier_roles = HashSet::<u32>::new();
        for reference in &staged.canonical_qualifier_refs {
            let qualifier = qualifiers
                .get(*reference as usize)
                .ok_or(HyperEncoderError::InvalidContract("qualifier reference"))?;
            qualifier_values.insert(qualifier.object());
            qualifier_roles.insert(qualifier.predicate());
        }
        let mut primary_entities = sorted(primary_entities);
        let mut primary_relations = sorted(primary_relations);
        let qualifier_values = sorted(qualifier_values);
        let qualifier_roles = sorted(qualifier_roles);
        let same_id_dual_role_entities = qualifier_values
            .iter()
            .filter(|id| primary_entities.binary_search(id).is_ok())
            .count() as u64;
        let same_id_dual_role_relations = qualifier_roles
            .iter()
            .filter(|id| primary_relations.binary_search(id).is_ok())
            .count() as u64;
        let mut hasher = blake3::Hasher::new();
        hasher.update(QUALIFIER_NULL_ROUTING_POLICY.as_bytes());
        hash_reads(
            &mut hasher,
            HyperParameterClass::EntityEmbedding,
            HyperSemanticRole::PrimaryEntity,
            HyperParameterSource::TrainedBackbone,
            &mut primary_entities,
            self.manifest.trained_backbone_model_id.as_str(),
        );
        hash_reads(
            &mut hasher,
            HyperParameterClass::RelationEmbedding,
            HyperSemanticRole::PrimaryRelation,
            HyperParameterSource::TrainedBackbone,
            &mut primary_relations,
            self.manifest.trained_backbone_model_id.as_str(),
        );
        hash_read_slice(
            &mut hasher,
            HyperParameterClass::EntityEmbedding,
            HyperSemanticRole::QualifierValue,
            HyperParameterSource::CheckpointZero,
            &qualifier_values,
            self.manifest.checkpoint_zero_model_id.as_str(),
        );
        hash_read_slice(
            &mut hasher,
            HyperParameterClass::RelationEmbedding,
            HyperSemanticRole::QualifierRole,
            HyperParameterSource::CheckpointZero,
            &qualifier_roles,
            self.manifest.checkpoint_zero_model_id.as_str(),
        );
        hash_read_slice(
            &mut hasher,
            HyperParameterClass::QualifierProjection,
            HyperSemanticRole::QualifierProjection,
            HyperParameterSource::CheckpointZero,
            &[0],
            self.manifest.checkpoint_zero_model_id.as_str(),
        );
        Ok(QualifierNullRoutingReceipt {
            routing_digest: format!("b3-{}", hasher.finalize().to_hex()).into(),
            trained_backbone_model_id: self.manifest.trained_backbone_model_id.clone(),
            checkpoint_zero_model_id: self.manifest.checkpoint_zero_model_id.clone(),
            primary_entity_reads: primary_entities.len() as u64,
            primary_relation_reads: primary_relations.len() as u64,
            qualifier_value_reads: qualifier_values.len() as u64,
            qualifier_role_reads: qualifier_roles.len() as u64,
            qualifier_projection_reads: 1,
            same_id_dual_role_entities,
            same_id_dual_role_relations,
        })
    }
}

pub fn write_qualifier_null_composition(
    trained_backbone_manifest: impl AsRef<Path>,
    checkpoint_zero_manifest: impl AsRef<Path>,
    optimizer_identity: impl Into<CompactString>,
    checkpoint_epoch: u32,
    root: impl AsRef<Path>,
) -> Result<QualifierNullCompositionPaths, HyperEncoderError> {
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let backbone_path = trained_backbone_manifest.as_ref();
    let checkpoint_path = checkpoint_zero_manifest.as_ref();
    let backbone_relative = relative_manifest(root, backbone_path)?;
    let checkpoint_relative = relative_manifest(root, checkpoint_path)?;
    let trained_backbone = HyperEncoderMapped::open(backbone_path)?;
    let checkpoint_zero = HyperEncoderMapped::open(checkpoint_path)?;
    let backbone = trained_backbone.manifest();
    let checkpoint = checkpoint_zero.manifest();
    let mut manifest = QualifierNullCompositionManifest {
        schema_version: QUALIFIER_NULL_COMPOSITION_SCHEMA.into(),
        composition_id: "pending".into(),
        trained_backbone_model_id: backbone.model_id.clone(),
        trained_backbone_manifest_id: backbone.manifest_id.clone(),
        trained_backbone_manifest_file: backbone_relative.into(),
        checkpoint_zero_model_id: checkpoint.model_id.clone(),
        checkpoint_zero_manifest_id: checkpoint.manifest_id.clone(),
        checkpoint_zero_manifest_file: checkpoint_relative.into(),
        evaluation_surface_id: QUALIFIER_NULL_EVALUATION_SURFACE.into(),
        parameter_routing_policy_id: QUALIFIER_NULL_ROUTING_POLICY.into(),
        optimizer_identity: optimizer_identity.into(),
        source_dataset_id: backbone.source_dataset_id.clone(),
        source_binary_blake3: backbone.source_binary_blake3.clone(),
        task_identity: backbone.task_id.clone(),
        task_binary_blake3: backbone.task_binary_blake3.clone(),
        checkpoint_epoch,
        candidate_universe: backbone.candidate_universe,
        directed_relation_count: backbone.directed_relation_count,
        redundant_weight_bytes: 0,
    };
    validate_parents(&manifest, &trained_backbone, &checkpoint_zero)?;
    manifest.composition_id = composition_identity(&manifest)?;
    let path = root.join(format!("{}.qualifier-null.json", manifest.composition_id));
    if path.exists() {
        return Err(HyperEncoderError::ArtifactExists(path));
    }
    write_new(&path, &serde_json::to_vec_pretty(&manifest)?)?;
    Ok(QualifierNullCompositionPaths {
        manifest: path,
        composition_id: manifest.composition_id,
    })
}

fn validate_composition_manifest(
    manifest: &QualifierNullCompositionManifest,
) -> Result<(), HyperEncoderError> {
    if manifest.schema_version != QUALIFIER_NULL_COMPOSITION_SCHEMA
        || manifest.composition_id != composition_identity(manifest)?
        || manifest.evaluation_surface_id != QUALIFIER_NULL_EVALUATION_SURFACE
        || manifest.parameter_routing_policy_id != QUALIFIER_NULL_ROUTING_POLICY
        || !is_blake3(manifest.optimizer_identity.as_str())
        || manifest.redundant_weight_bytes != 0
    {
        return Err(HyperEncoderError::CorruptArtifact(
            "qualifier null manifest",
        ));
    }
    Ok(())
}

fn validate_parents(
    manifest: &QualifierNullCompositionManifest,
    backbone: &HyperEncoderMapped,
    checkpoint: &HyperEncoderMapped,
) -> Result<(), HyperEncoderError> {
    let backbone = backbone.manifest();
    let checkpoint = checkpoint.manifest();
    if backbone.config.mode != HyperEncoderMode::CompgcnTriple
        || checkpoint.config.mode != HyperEncoderMode::StareQualifiers
        || backbone.config.seed != checkpoint.config.seed
        || (manifest.checkpoint_epoch == 0) != (backbone.training.optimizer_steps == 0)
        || checkpoint.training.optimizer_steps != 0
        || backbone.model_id != manifest.trained_backbone_model_id
        || backbone.manifest_id != manifest.trained_backbone_manifest_id
        || checkpoint.model_id != manifest.checkpoint_zero_model_id
        || checkpoint.manifest_id != manifest.checkpoint_zero_manifest_id
        || backbone.source_dataset_id != checkpoint.source_dataset_id
        || backbone.source_binary_blake3 != checkpoint.source_binary_blake3
        || backbone.task_id != checkpoint.task_id
        || backbone.task_binary_blake3 != checkpoint.task_binary_blake3
        || backbone.candidate_universe != checkpoint.candidate_universe
        || backbone.directed_relation_count != checkpoint.directed_relation_count
        || backbone.source_dataset_id != manifest.source_dataset_id
        || backbone.source_binary_blake3 != manifest.source_binary_blake3
        || backbone.task_id != manifest.task_identity
        || backbone.task_binary_blake3 != manifest.task_binary_blake3
        || backbone.candidate_universe != manifest.candidate_universe
        || backbone.directed_relation_count != manifest.directed_relation_count
    {
        return Err(HyperEncoderError::CorruptArtifact("qualifier null parents"));
    }
    Ok(())
}

fn composition_identity(
    manifest: &QualifierNullCompositionManifest,
) -> Result<CompactString, HyperEncoderError> {
    let mut canonical = manifest.clone();
    canonical.composition_id = "pending".into();
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&canonical)?).to_hex()
    )
    .into())
}

fn relative_manifest(root: &Path, path: &Path) -> Result<String, HyperEncoderError> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| HyperEncoderError::InvalidContract("composition parent root"))?;
    if relative
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(HyperEncoderError::InvalidContract(
            "composition parent path",
        ));
    }
    Ok(relative.to_string_lossy().replace('\\', "/"))
}

fn resolve_parent(root: &Path, relative: &str) -> Result<PathBuf, HyperEncoderError> {
    let path = Path::new(relative);
    if path
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(HyperEncoderError::CorruptArtifact(
            "composition parent path",
        ));
    }
    Ok(root.join(path))
}

fn sorted(values: HashSet<u32>) -> Vec<u32> {
    let mut values = values.into_iter().collect::<Vec<_>>();
    values.sort_unstable();
    values
}

fn hash_reads(
    hasher: &mut blake3::Hasher,
    class: HyperParameterClass,
    role: HyperSemanticRole,
    source: HyperParameterSource,
    ids: &mut [u32],
    model_id: &str,
) {
    ids.sort_unstable();
    hash_read_slice(hasher, class, role, source, ids, model_id);
}

fn hash_read_slice(
    hasher: &mut blake3::Hasher,
    class: HyperParameterClass,
    role: HyperSemanticRole,
    source: HyperParameterSource,
    ids: &[u32],
    model_id: &str,
) {
    for id in ids {
        hasher.update(&[class as u8, role as u8, source as u8]);
        hasher.update(&id.to_le_bytes());
        hasher.update(&(model_id.len() as u64).to_le_bytes());
        hasher.update(model_id.as_bytes());
    }
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), HyperEncoderError> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
