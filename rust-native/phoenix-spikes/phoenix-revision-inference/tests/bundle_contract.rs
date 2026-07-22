use phoenix_revision_impact::{
    GraphGeneration, InferenceAuthority, InferenceEdgeSeed, InferenceNodeSeed,
    InferenceProjectionInput, RevisionAnalysisViews,
};
use phoenix_revision_inference::{
    GfmBundle, ModelKind, ModelProvenance, ReasonerBundle, probe_bundle_authority, project_gfm,
    project_reasoner, write_gfm_bundle, write_reasoner_bundle,
};

fn node(id: &str, node_type: &str) -> InferenceNodeSeed {
    InferenceNodeSeed {
        node_id: id.into(),
        node_type: node_type.into(),
        embedding_text: format!("semantic text for {id}").into(),
    }
}

fn edge(
    id: &str,
    source: &str,
    target: &str,
    relation: &str,
    authority: InferenceAuthority,
) -> InferenceEdgeSeed {
    InferenceEdgeSeed {
        edge_id: id.into(),
        source_id: source.into(),
        target_id: target.into(),
        relation_type: relation.into(),
        authority,
        evidence_ids: vec![format!("evidence:{id}").into()],
        confidence_millis: 900,
    }
}

fn views() -> RevisionAnalysisViews {
    RevisionAnalysisViews::project(
        GraphGeneration(77),
        Vec::new(),
        InferenceProjectionInput {
            accepted_nodes: vec![
                node("document:one", "document"),
                node("entity:a", "entity"),
                node("entity:b", "entity"),
            ],
            relations: vec![
                edge(
                    "relation:accepted",
                    "entity:a",
                    "entity:b",
                    "knows",
                    InferenceAuthority::Accepted,
                ),
                edge(
                    "relation:candidate",
                    "entity:b",
                    "entity:a",
                    "candidate_only",
                    InferenceAuthority::Candidate,
                ),
            ],
            memberships: vec![
                edge(
                    "membership:a",
                    "document:one",
                    "entity:a",
                    "document_contains_entity",
                    InferenceAuthority::Asserted,
                ),
                edge(
                    "membership:b",
                    "document:one",
                    "entity:b",
                    "document_contains_entity",
                    InferenceAuthority::Asserted,
                ),
            ],
        },
    )
    .unwrap()
}

fn provenance() -> ModelProvenance {
    ModelProvenance {
        checkpoint_revision: "checkpoint".into(),
        checkpoint_digest: "checkpoint-digest".into(),
        encoder_revision: "encoder".into(),
        encoder_digest: "encoder-digest".into(),
    }
}

#[test]
fn both_immutable_bundles_round_trip_without_candidate_leakage() {
    let directory = tempfile::tempdir().unwrap();
    let gfm_root = directory.path().join("gfm");
    let gfm = project_gfm(&views().inference_graph).unwrap();
    let relation_values =
        vec![0.25; gfm.view.relation_names.len() * gfm_rag_8m_parity::constants::EMBEDDING_DIM];
    write_gfm_bundle(&gfm_root, 77, gfm, &relation_values, provenance()).unwrap();
    let gfm = GfmBundle::open(&gfm_root).unwrap();
    assert!(
        probe_bundle_authority(
            &gfm_root,
            ModelKind::GfmRag8M,
            77,
            &gfm.manifest.snapshot_digest,
            &provenance(),
        )
        .unwrap()
    );
    assert!(
        !probe_bundle_authority(
            &gfm_root,
            ModelKind::GfmRag8M,
            78,
            &gfm.manifest.snapshot_digest,
            &provenance(),
        )
        .unwrap()
    );
    assert_eq!(gfm.manifest.authority.excluded_candidate_edges, 1);
    assert_eq!(gfm.manifest.authority.admitted_candidate_edges, 0);
    assert!(
        gfm.manifest
            .node_ids
            .iter()
            .all(|id| !id.contains("candidate"))
    );
    assert!(
        write_gfm_bundle(
            &gfm_root,
            77,
            project_gfm(&views().inference_graph).unwrap(),
            &relation_values,
            provenance()
        )
        .is_err()
    );

    let reasoner_root = directory.path().join("reasoner");
    let reasoner = project_reasoner(&views().inference_graph).unwrap();
    let relation_values = vec![
        0.5;
        reasoner.view.relation_names.len()
            * g_reasoner_34m_parity::constants::FEATURE_DIM
    ];
    let node_values =
        vec![0.75; reasoner.view.node_ids.len() * g_reasoner_34m_parity::constants::FEATURE_DIM];
    write_reasoner_bundle(
        &reasoner_root,
        77,
        reasoner,
        &relation_values,
        &node_values,
        provenance(),
    )
    .unwrap();
    let reasoner = ReasonerBundle::open(&reasoner_root).unwrap();
    assert_eq!(reasoner.manifest.authority.excluded_candidate_edges, 1);
    assert_eq!(reasoner.manifest.authority.admitted_candidate_edges, 0);
    assert_eq!(reasoner.node_embeddings.rows(), 3);
    make_writable(&gfm_root);
    make_writable(&reasoner_root);
}

#[allow(clippy::permissions_set_readonly_false)]
fn make_writable(root: &std::path::Path) {
    for entry in std::fs::read_dir(root).unwrap() {
        let entry = entry.unwrap();
        let mut permissions = entry.metadata().unwrap().permissions();
        permissions.set_readonly(false);
        std::fs::set_permissions(entry.path(), permissions).unwrap();
    }
}
