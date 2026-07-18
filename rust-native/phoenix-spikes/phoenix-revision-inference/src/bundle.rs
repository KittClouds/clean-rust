use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use g_reasoner_34m_parity::artifact as reasoner_artifact;
use gfm_rag_8m_parity::artifact as gfm_artifact;
use serde::{Deserialize, Serialize};

use crate::error::io_error;
use crate::matrix::digest_file;
use crate::{
    GfmProjection, InferenceArtifactError, MappedF32Matrix, MatrixArtifact, MembershipRecord,
    ProjectionAuthorityReceipt, ReasonerProjection, Result, write_matrix,
};

pub const BUNDLE_SCHEMA: &str = "phoenix.revision-inference-bundle/v1";
const MANIFEST_FILE: &str = "manifest.json";
const GRAPH_FILE: &str = "graph.csr";
const RELATIONS_FILE: &str = "relation-embeddings.f32m";
const NODES_FILE: &str = "node-embeddings.f32m";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ModelKind {
    #[serde(rename = "gfm_rag_8m", alias = "gfm_rag8_m")]
    GfmRag8M,
    #[serde(rename = "g_reasoner_34m", alias = "g_reasoner34_m")]
    GReasoner34M,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModelProvenance {
    pub checkpoint_revision: String,
    pub checkpoint_digest: String,
    pub encoder_revision: String,
    pub encoder_digest: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphArtifact {
    pub file: String,
    pub node_count: u64,
    pub relation_count: u32,
    pub edge_count: u64,
    pub byte_length: u64,
    pub blake3: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModelBundleManifest {
    pub schema: String,
    pub model: ModelKind,
    pub generation: u64,
    pub snapshot_digest: String,
    pub provenance: ModelProvenance,
    pub node_ids: Vec<String>,
    pub node_types: Vec<String>,
    pub relation_vocabulary: Vec<String>,
    pub document_ids: Vec<String>,
    pub memberships: Vec<MembershipRecord>,
    pub entity_documents: Vec<Vec<u32>>,
    pub graph: GraphArtifact,
    pub relation_embeddings: MatrixArtifact,
    pub node_embeddings: Option<MatrixArtifact>,
    pub authority: ProjectionAuthorityReceipt,
}

pub struct GfmBundle {
    pub root: PathBuf,
    pub manifest: ModelBundleManifest,
    pub graph: gfm_artifact::MappedIncomingCsr,
    pub relation_embeddings: MappedF32Matrix,
}

pub struct ReasonerBundle {
    pub root: PathBuf,
    pub manifest: ModelBundleManifest,
    pub graph: reasoner_artifact::MappedIncomingCsr,
    pub relation_embeddings: MappedF32Matrix,
    pub node_embeddings: MappedF32Matrix,
}

pub fn write_gfm_bundle(
    output: impl AsRef<Path>,
    generation: u64,
    projection: GfmProjection,
    relation_embeddings: &[f32],
    provenance: ModelProvenance,
) -> Result<ModelBundleManifest> {
    let relation_count = projection.view.relation_names.len();
    validate_matrix(
        relation_embeddings,
        relation_count,
        gfm_rag_8m_parity::constants::EMBEDDING_DIM,
        "8M relation embeddings",
    )?;
    let stage = staged_directory(output.as_ref())?;
    let graph_manifest =
        gfm_artifact::write_graph_artifact(&projection.view.graph, stage.path().join(GRAPH_FILE))?;
    let relation_manifest = write_matrix(
        stage.path().join(RELATIONS_FILE),
        relation_count,
        gfm_rag_8m_parity::constants::EMBEDDING_DIM,
        relation_embeddings,
    )?;
    let manifest = ModelBundleManifest {
        schema: BUNDLE_SCHEMA.into(),
        model: ModelKind::GfmRag8M,
        generation,
        snapshot_digest: projection.snapshot_digest,
        provenance,
        node_ids: projection.view.entity_ids.to_vec(),
        node_types: vec!["entity".into(); projection.view.entity_ids.len()],
        relation_vocabulary: projection.view.relation_names.to_vec(),
        document_ids: projection.view.document_ids.to_vec(),
        memberships: projection.memberships,
        entity_documents: projection
            .view
            .entity_documents
            .iter()
            .map(|documents| documents.to_vec())
            .collect(),
        graph: GraphArtifact {
            file: GRAPH_FILE.into(),
            node_count: graph_manifest.node_count,
            relation_count: graph_manifest.relation_count,
            edge_count: graph_manifest.edge_count,
            byte_length: graph_manifest.byte_length,
            blake3: graph_manifest.blake3,
        },
        relation_embeddings: relation_manifest,
        node_embeddings: None,
        authority: projection.authority,
    };
    publish(stage, output.as_ref(), &manifest)?;
    Ok(manifest)
}

pub fn write_reasoner_bundle(
    output: impl AsRef<Path>,
    generation: u64,
    projection: ReasonerProjection,
    relation_embeddings: &[f32],
    node_embeddings: &[f32],
    provenance: ModelProvenance,
) -> Result<ModelBundleManifest> {
    let relation_count = projection.view.relation_names.len();
    let node_count = projection.view.node_ids.len();
    validate_matrix(
        relation_embeddings,
        relation_count,
        g_reasoner_34m_parity::constants::FEATURE_DIM,
        "34M relation embeddings",
    )?;
    validate_matrix(
        node_embeddings,
        node_count,
        g_reasoner_34m_parity::constants::FEATURE_DIM,
        "34M node embeddings",
    )?;
    let stage = staged_directory(output.as_ref())?;
    let graph_manifest = reasoner_artifact::write_graph_artifact(
        &projection.view.graph,
        stage.path().join(GRAPH_FILE),
    )?;
    let relation_manifest = write_matrix(
        stage.path().join(RELATIONS_FILE),
        relation_count,
        g_reasoner_34m_parity::constants::FEATURE_DIM,
        relation_embeddings,
    )?;
    let node_manifest = write_matrix(
        stage.path().join(NODES_FILE),
        node_count,
        g_reasoner_34m_parity::constants::FEATURE_DIM,
        node_embeddings,
    )?;
    let manifest = ModelBundleManifest {
        schema: BUNDLE_SCHEMA.into(),
        model: ModelKind::GReasoner34M,
        generation,
        snapshot_digest: projection.snapshot_digest,
        provenance,
        node_ids: projection.view.node_ids.to_vec(),
        node_types: projection.view.node_types.to_vec(),
        relation_vocabulary: projection.view.relation_names.to_vec(),
        document_ids: projection
            .view
            .nodes_for_type("document")
            .iter()
            .map(|&index| projection.view.node_ids[index as usize].clone())
            .collect(),
        memberships: projection.memberships,
        entity_documents: Vec::new(),
        graph: GraphArtifact {
            file: GRAPH_FILE.into(),
            node_count: graph_manifest.node_count,
            relation_count: graph_manifest.relation_count,
            edge_count: graph_manifest.edge_count,
            byte_length: graph_manifest.byte_length,
            blake3: graph_manifest.blake3,
        },
        relation_embeddings: relation_manifest,
        node_embeddings: Some(node_manifest),
        authority: projection.authority,
    };
    publish(stage, output.as_ref(), &manifest)?;
    Ok(manifest)
}

impl GfmBundle {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let root = root.as_ref().to_path_buf();
        let manifest = read_manifest(&root, ModelKind::GfmRag8M)?;
        verify_graph(&root, &manifest.graph)?;
        let graph = gfm_artifact::MappedIncomingCsr::open(root.join(&manifest.graph.file))?;
        let relation_embeddings = MappedF32Matrix::open(
            root.join(&manifest.relation_embeddings.file),
            &manifest.relation_embeddings,
        )?;
        if manifest.node_embeddings.is_some()
            || graph.node_count() != manifest.node_ids.len()
            || graph.relation_count() != manifest.relation_vocabulary.len()
        {
            return Err(InferenceArtifactError::InvalidArtifact(
                "8M bundle metadata disagrees with mmap graph".into(),
            ));
        }
        Ok(Self {
            root,
            manifest,
            graph,
            relation_embeddings,
        })
    }
}

impl ReasonerBundle {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let root = root.as_ref().to_path_buf();
        let manifest = read_manifest(&root, ModelKind::GReasoner34M)?;
        verify_graph(&root, &manifest.graph)?;
        let graph = reasoner_artifact::MappedIncomingCsr::open(root.join(&manifest.graph.file))?;
        let relation_embeddings = MappedF32Matrix::open(
            root.join(&manifest.relation_embeddings.file),
            &manifest.relation_embeddings,
        )?;
        let node_manifest = manifest.node_embeddings.as_ref().ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("34M bundle lacks node embeddings".into())
        })?;
        let node_embeddings = MappedF32Matrix::open(root.join(&node_manifest.file), node_manifest)?;
        if graph.node_count() != manifest.node_ids.len()
            || graph.relation_count() != manifest.relation_vocabulary.len()
            || node_embeddings.rows() != graph.node_count()
        {
            return Err(InferenceArtifactError::InvalidArtifact(
                "34M bundle metadata disagrees with mmap arrays".into(),
            ));
        }
        Ok(Self {
            root,
            manifest,
            graph,
            relation_embeddings,
            node_embeddings,
        })
    }
}

fn staged_directory(output: &Path) -> Result<tempfile::TempDir> {
    if output.exists() {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "immutable bundle already exists at {}",
            output.display()
        )));
    }
    let parent = output.parent().ok_or_else(|| {
        InferenceArtifactError::InvalidArtifact("bundle path has no parent".into())
    })?;
    std::fs::create_dir_all(parent).map_err(|source| io_error(parent, source))?;
    tempfile::Builder::new()
        .prefix(".phoenix-inference-stage-")
        .tempdir_in(parent)
        .map_err(|source| io_error(parent, source))
}

fn publish(stage: tempfile::TempDir, output: &Path, manifest: &ModelBundleManifest) -> Result<()> {
    let path = stage.path().join(MANIFEST_FILE);
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&path)
        .map_err(|source| io_error(&path, source))?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer(&mut writer, manifest)?;
    writer.flush().map_err(|source| io_error(&path, source))?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|source| io_error(&path, source))?;
    drop(writer);
    for entry in std::fs::read_dir(stage.path()).map_err(|source| io_error(stage.path(), source))? {
        let entry = entry.map_err(|source| io_error(stage.path(), source))?;
        let mut permissions = entry
            .metadata()
            .map_err(|source| io_error(entry.path(), source))?
            .permissions();
        permissions.set_readonly(true);
        std::fs::set_permissions(entry.path(), permissions)
            .map_err(|source| io_error(entry.path(), source))?;
    }
    let stage_path = stage.keep();
    std::fs::rename(&stage_path, output).map_err(|source| io_error(output, source))
}

fn read_manifest(root: &Path, expected: ModelKind) -> Result<ModelBundleManifest> {
    let path = root.join(MANIFEST_FILE);
    let manifest: ModelBundleManifest =
        serde_json::from_reader(File::open(&path).map_err(|source| io_error(&path, source))?)?;
    if manifest.schema != BUNDLE_SCHEMA
        || manifest.model != expected
        || manifest.authority.admitted_candidate_edges != 0
        || manifest.node_ids.len() != manifest.node_types.len()
    {
        return Err(InferenceArtifactError::InvalidArtifact(
            "bundle contract or authority receipt mismatch".into(),
        ));
    }
    Ok(manifest)
}

fn verify_graph(root: &Path, graph: &GraphArtifact) -> Result<()> {
    let path = root.join(&graph.file);
    let (bytes, digest) = digest_file(&path)?;
    if bytes != graph.byte_length || digest != graph.blake3 {
        return Err(InferenceArtifactError::InvalidArtifact(
            "graph artifact digest mismatch".into(),
        ));
    }
    Ok(())
}

fn validate_matrix(values: &[f32], rows: usize, columns: usize, label: &str) -> Result<()> {
    if values.len() != rows.saturating_mul(columns) || values.iter().any(|value| !value.is_finite())
    {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "invalid {label}"
        )));
    }
    Ok(())
}
