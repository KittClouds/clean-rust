use std::collections::BTreeSet;
use std::fs::File;
use std::path::Path;
use std::time::Instant;

use memchr::memmem;
use memmap2::MmapOptions;
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, BeliefStateKind, CausalClaimStatus, CausalEdgeAddition,
    CausalEdgeId, CausalRelationKind, CausalScopeSidecar, MemoryScopeSidecar, TemporalScopeSidecar,
    TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EventId, FactId, FactValue,
    GraphTruthDigest, ImpactClassification, Polarity, SceneId, SemanticNodeRef, StoryInterval,
    StoryMutation, StoryTime, TextRange,
};

use super::*;
use crate::{
    bind_repair_sources, generate_deterministic_repairs, project_authoritative_constraints,
    simulate_source_bound_candidate, AuthoritativeRevisionSources, CounterfactualGraphView,
    EvidenceRef, GraphGeneration, InferenceProjectionInput, NamedSidecarDigest, RepairDisposition,
    RepairGenerationInput, RepairSimulationInput, RequirementDependency, RequirementTruthRef,
    RevisionAnalysisViews, RevisionEdgeRecord, RevisionFactRecord, RevisionGraphSnapshot,
    RevisionRequirementRecord, RevisionRequirementSidecar, SourceDocument, SourceDocumentSet,
    SourceRange, REVISION_REQUIREMENT_SIDECAR_SCHEMA,
};

const DOCUMENT_ID: &str = "docs/shortrun.md";
const FACT_ID: &str = "fact:ryan_remembers_ghoul_attack";
const HARD_CONSTRAINT: &str = "constraint:shortrun:fourth_loop_knowledge";
const SOFT_CONSTRAINT: &str = "constraint:shortrun:autopilot_support";
const HARD_SCENE: &str = "scene:shortrun:fourth_loop";
const SOFT_SCENE: &str = "scene:shortrun:autopilot";
const UNKNOWN_SCENE: &str = "scene:shortrun:rabbit_capability";

#[test]
fn real_shortrun_document_runs_through_first_shippable_detector() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../docs/shortrun.md");
    let file = File::open(&path).expect("docs/shortrun.md");
    // SAFETY: the file remains open for the map lifetime and this test maps it read-only.
    let document = unsafe { MmapOptions::new().map(&file) }.expect("read-only shortrun mmap");
    let hard_range = locate(&document, b"It was May 8th 2020 for the fourth time");
    let soft_range = locate(&document, b"Ryan entered his autopilot mode");
    let unknown_range = locate(&document, b"rabbit plushie");
    let generation = GraphGeneration(505);
    let fact_id = FactId::from(FACT_ID);
    let interval = StoryInterval {
        valid_from: StoryTime(0),
        valid_to_exclusive: None,
    };
    let hard_window = point_window(4);
    let soft_window = point_window(5);
    let hard_evidence = anchored("evidence:shortrun:fourth_loop", hard_range);
    let soft_evidence = anchored("evidence:shortrun:autopilot", soft_range);

    let requirements = RevisionRequirementSidecar {
        schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
        generation,
        requirements: vec![
            RevisionRequirementRecord {
                constraint_id: HARD_CONSTRAINT.into(),
                dependency: RequirementDependency::Fact {
                    fact_id: fact_id.clone(),
                },
                expected_value: FactValue::Boolean(true),
                dependent_scene_id: SceneId::from(HARD_SCENE),
                kind: ConstraintKind::RequiresKnowledge,
                valid_interval: hard_window,
                truth_ref: RequirementTruthRef::Belief {
                    belief_id: "belief:shortrun:fourth_loop".into(),
                },
                evidence: vec![hard_evidence],
                confidence_millis: 1000,
            },
            RevisionRequirementRecord {
                constraint_id: SOFT_CONSTRAINT.into(),
                dependency: RequirementDependency::Fact {
                    fact_id: fact_id.clone(),
                },
                expected_value: FactValue::Boolean(true),
                dependent_scene_id: SceneId::from(SOFT_SCENE),
                kind: ConstraintKind::CausalSupport,
                valid_interval: soft_window,
                truth_ref: RequirementTruthRef::CausalEdge {
                    edge_id: "causal:shortrun:autopilot".into(),
                },
                evidence: vec![soft_evidence],
                confidence_millis: 900,
            },
        ],
    };
    let base = RevisionGraphSnapshot::new(
        generation,
        vec![RevisionFactRecord {
            fact_id: fact_id.clone(),
            value: FactValue::Boolean(true),
            interval,
        }],
        Vec::new(),
        vec![
            RevisionEdgeRecord {
                edge_id: HARD_CONSTRAINT.into(),
                dependency_fact_ids: vec![fact_id.clone()],
                dependency_state_refs: Vec::new(),
            },
            RevisionEdgeRecord {
                edge_id: SOFT_CONSTRAINT.into(),
                dependency_fact_ids: vec![fact_id.clone()],
                dependency_state_refs: Vec::new(),
            },
        ],
        vec![NamedSidecarDigest {
            sidecar_id: "shortrun-smoke".into(),
            digest: GraphTruthDigest([5; 32]),
        }],
    )
    .expect("shortrun base graph");
    let temporal = temporal_sidecar(generation, hard_range);
    let memory = MemoryScopeSidecar {
        generation: generation.0,
        ..MemoryScopeSidecar::default()
    };
    let causal = causal_sidecar(generation);
    let base_digest = base.digest();
    let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &base,
        requirements: &requirements,
        temporal: Some(&temporal),
        memory: Some(&memory),
        causal: Some(&causal),
    })
    .expect("shortrun authoritative projection");
    let views = RevisionAnalysisViews::project(
        generation,
        bundle.constraints,
        InferenceProjectionInput::default(),
    )
    .expect("shortrun analysis views");
    let overlay = CounterfactualGraphView::new(
        &base,
        vec![StoryMutation::RetractFact {
            fact_id: fact_id.clone(),
        }],
    )
    .expect("shortrun overlay");
    let coverage_requests = [SceneCoverageRequest {
        scene_id: SceneId::from(UNKNOWN_SCENE),
        required_planes: vec![CoveragePlane::Capability],
        unavailable_planes: vec![CoveragePlane::Capability],
    }];

    let started = Instant::now();
    let report = detect_revision_impacts(
        RevisionDetectorInput {
            overlay: &overlay,
            constraint_graph: &views.constraint_graph,
            requirements: &requirements,
            projection_receipt: &bundle.receipt,
            identity_coverage: IdentityCoverage::SameRevision,
            coverage_requests: &coverage_requests,
        },
        RippleConfig::default(),
    )
    .expect("shortrun detector report");
    let elapsed = started.elapsed();

    assert_eq!(base.digest(), base_digest);
    assert_eq!(report.authoritative_impacts.len(), 3);
    assert_classification(&report, HARD_SCENE, ImpactClassification::Broken);
    assert_classification(&report, SOFT_SCENE, ImpactClassification::Suspicious);
    assert_classification(&report, UNKNOWN_SCENE, ImpactClassification::Unknown);
    let hard = report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == HARD_SCENE)
        .expect("hard shortrun impact");
    let anchored = hard.violated_constraints[0]
        .evidence
        .iter()
        .find(|evidence| evidence.document_id.as_deref() == Some(DOCUMENT_ID))
        .expect("shortrun source evidence");
    assert_eq!(anchored.source_range, Some(hard_range));
    assert_eq!(
        &document[hard_range.start as usize..hard_range.end as usize],
        b"It was May 8th 2020 for the fourth time"
    );
    assert!(report.model_overlays.is_empty());
    assert!(report.deterministic_receipt.no_truth_writes);
    let mutation = StoryMutation::RetractFact {
        fact_id: fact_id.clone(),
    };
    let mutations = [mutation];
    let repairs = generate_deterministic_repairs(RepairGenerationInput {
        base: &base,
        mutations: &mutations,
        requirements: &requirements,
        report: &report,
        author_locked_ids: &BTreeSet::new(),
    });
    let statement_repair = repairs
        .candidates
        .iter()
        .find(|edit| edit.target_ids.iter().any(|id| id == HARD_SCENE))
        .expect("shortrun statement repair");
    let source_repair_started = Instant::now();
    let documents = SourceDocumentSet::new(
        generation,
        vec![SourceDocument::utf8(
            DOCUMENT_ID,
            std::str::from_utf8(&document).expect("utf8 shortrun"),
        )],
    )
    .expect("shortrun source snapshot");
    let bound = bind_repair_sources(statement_repair, &documents).expect("shortrun source binding");
    let validated = simulate_source_bound_candidate(
        RepairSimulationInput {
            base: &base,
            mutations: &mutations,
            requirements: &requirements,
            temporal: Some(&temporal),
            memory: Some(&memory),
            causal: Some(&causal),
            original_report: &report,
            author_locked_ids: &BTreeSet::new(),
            ripple_config: RippleConfig::default(),
        },
        &documents,
        &bound,
    )
    .expect("shortrun source-bound simulation");
    assert_eq!(
        validated.candidate.disposition,
        RepairDisposition::ProvenFix
    );
    assert!(validated.source_validation.exact_operation_coverage);
    assert_eq!(
        documents.digest(),
        validated.source_validation.original_documents_digest
    );
    let source_repair_elapsed = source_repair_started.elapsed();
    println!(
        "shortrun_bytes={} shortrun_impacts={} shortrun_detector_micros={} source_bound_repair_micros={} validated_anchors=3 source_bound_repairs=1",
        document.len(),
        report.authoritative_impacts.len(),
        elapsed.as_micros(),
        source_repair_elapsed.as_micros()
    );
    assert!(unknown_range.start < unknown_range.end);
}

fn temporal_sidecar(generation: GraphGeneration, range: SourceRange) -> TemporalScopeSidecar {
    TemporalScopeSidecar {
        generation: generation.0,
        belief_atoms: vec![BeliefStateAtom {
            belief_id: "belief:shortrun:fourth_loop".to_owned(),
            document_id: DOCUMENT_ID.to_owned(),
            kind: BeliefStateKind::Knows,
            truth_status: TemporalTruthStatus::Asserted,
            source_kind: BeliefSourceKind::DirectObservation,
            confidence_millis: 1000,
            temporal: wide_window(),
            range: Some(TextRange {
                start: range.start,
                end: range.end,
            }),
            evidence_refs: vec!["source:shortrun:fourth_loop".to_owned()],
            ..BeliefStateAtom::default()
        }],
        ..TemporalScopeSidecar::default()
    }
}

fn causal_sidecar(generation: GraphGeneration) -> CausalScopeSidecar {
    CausalScopeSidecar {
        generation: generation.0,
        edge_records: vec![CausalEdgeAddition {
            edge_id: CausalEdgeId("causal:shortrun:autopilot".to_owned()),
            case_id: SOFT_CONSTRAINT.to_owned(),
            document_id: DOCUMENT_ID.to_owned(),
            source: SemanticNodeRef::Event(EventId("event:shortrun:ghoul_attack".to_owned())),
            canonical_cause_event_id: None,
            target: SemanticNodeRef::Event(EventId("event:shortrun:autopilot".to_owned())),
            canonical_effect_event_id: None,
            kind: CausalKind::Enables,
            relation_kind: CausalRelationKind::EnablingCondition,
            status: CausalClaimStatus::Active,
            first_seen_revision: generation.0,
            latest_decision_id: None,
            confidence_millis: 900,
            cue: Some("prior_loop_memory".to_owned()),
            attributed_to: None,
            polarity: Polarity::Positive,
            claim_atom_ids: Vec::new(),
            evidence_refs: vec!["source:shortrun:autopilot".to_owned()],
            effective_interval: wide_window(),
            observation_interval: wide_window(),
            temporal_certainty_millis: 1000,
            created_at: 1,
        }],
        ..CausalScopeSidecar::default()
    }
}

fn anchored(id: &str, range: SourceRange) -> EvidenceRef {
    EvidenceRef {
        evidence_id: id.into(),
        document_id: Some(DOCUMENT_ID.into()),
        source_range: Some(range),
    }
}

fn locate(document: &[u8], needle: &[u8]) -> SourceRange {
    let start = memmem::find(document, needle).expect("shortrun anchor");
    SourceRange {
        start: u32::try_from(start).expect("anchor start"),
        end: u32::try_from(start + needle.len()).expect("anchor end"),
    }
}

fn point_window(time: i64) -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(time),
        valid_to_exclusive: Some(StoryTime(time + 1)),
    }
}

fn wide_window() -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(0),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn assert_classification(
    report: &RevisionImpactReport,
    scene_id: &str,
    classification: ImpactClassification,
) {
    assert_eq!(
        report
            .authoritative_impacts
            .iter()
            .find(|impact| impact.scene_id.0 == scene_id)
            .map(|impact| impact.classification),
        Some(classification)
    );
}
