use std::path::Path;

use anyhow::{bail, Context, Result};
use phoenix_lexical_qps::{RankEvidenceV3, RelevanceTier, SearchHit, SearchScratch};
use serde::{Deserialize, Serialize};

use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.7-release-rarity-group-coverage-sidecar/v1";

pub(crate) fn capture(
    manifest: &FreezeManifest,
    phase_3_path: &Path,
    suite_path: &Path,
    workload_path: &Path,
    gold_path: &Path,
    output_path: &Path,
) -> Result<ReleaseRarityCoveragePublication> {
    let expected: FrozenPhase3 = serde_json::from_slice(&fs::read(phase_3_path)?)
        .with_context(|| format!("decode Phase 3 receipt {}", phase_3_path.display()))?;
    if expected.contract != "phoenix.memory.qps-v3-constitutional-tiers/v1"
        || !expected.phase_3_verified
    {
        bail!("release rarity coverage capture requires verified Phase 3");
    }
    let suite = load_suite(suite_path)?;
    let workload: WorkloadArtifact = read_artifact(workload_path, WORKLOAD_MAGIC)?;
    let gold: GoldArtifact = read_artifact(gold_path, GOLD_MAGIC)?;
    validate_release_inputs(manifest, &workload, &gold)?;

    let mixed = capture_mixed(&suite)?;
    let longmemeval = capture_longmemeval(&workload)?;
    let gates = ReleaseRarityCoverageGates {
        phase_3_verified: expected.phase_3_verified,
        mixed: compare_cohort(&expected.mixed_suite, &mixed),
        longmemeval: compare_cohort(&expected.longmemeval_release, &longmemeval),
        rarity_coverage_is_finite_and_bounded: mixed
            .queries
            .iter()
            .chain(&longmemeval.queries)
            .flat_map(|query| &query.candidates)
            .all(|candidate| valid(candidate.rarity_weighted_group_coverage)),
    };
    if !gates.all_pass() {
        bail!("release rarity coverage parity failed: {gates:?}");
    }
    let artifact = ReleaseRarityCoverageSidecar {
        contract: CONTRACT,
        schema_version: 1,
        architecture: "diagnostic_only_rarity_weighted_group_coverage_over_frozen_v2_substrate",
        group_weight:
            "max_over_resolved_expansions(expansion_quality_times_normalized_term_rarity)",
        candidate_numerator: "sum_candidate_independent_weights_of_matched_groups",
        phase_3: file_identity(phase_3_path)?,
        mixed_suite_source: file_identity(suite_path)?,
        workload: file_identity(workload_path)?,
        gold: file_identity(gold_path)?,
        mixed,
        longmemeval,
        gates,
        production_promotion_authorized: false,
    };
    write_json_atomic(output_path, &artifact)?;
    Ok(ReleaseRarityCoveragePublication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        gates,
        production_promotion_authorized: false,
    })
}

fn capture_mixed(suite: &MixedSuite) -> Result<RarityCoverageCohort> {
    let index = build_index(
        suite.documents.iter().enumerate().map(|(index, document)| {
            (
                index as u64,
                [document.title.as_str(), document.body.as_str()],
            )
        }),
        &MIXED_FIELDS,
    )?;
    let versions = suite
        .documents
        .iter()
        .map(mixed_document_version)
        .collect::<Vec<_>>();
    let mut queries = Vec::with_capacity(suite.queries.len());
    let mut scratch =
        SearchScratch::with_document_capacity(suite.documents.len(), MAXIMUM_QUERY_GROUPS);
    let mut hits = Vec::<SearchHit>::with_capacity(CANDIDATE_CAP);
    for query in &suite.queries {
        let prepared = PreparedMixedQuery::new(query);
        let groups = prepared.group_views();
        prepared.search_evidence(&groups, &index, &mut scratch, &mut hits)?;
        let candidates = hits
            .iter()
            .enumerate()
            .map(|(rank, hit)| RarityCoverageCandidate {
                document_identity: suite.documents[hit.external_id as usize].stable_id.clone(),
                document_version: versions[hit.external_id as usize].clone(),
                v2_order: rank + 1,
                v2_score_bits: hit.v2_score.to_bits(),
                rank_evidence_v3: hit.rank_evidence_v3,
                relevance_tier: hit.relevance_tier,
                rarity_weighted_group_coverage: hit.rarity_weighted_group_coverage,
            })
            .collect();
        queries.push(RarityCoverageQuery {
            query_identity: query.stable_id.clone(),
            candidates,
        });
    }
    Ok(RarityCoverageCohort { queries })
}

fn capture_longmemeval(workload: &WorkloadArtifact) -> Result<RarityCoverageCohort> {
    let mut queries = Vec::with_capacity(workload.cases.len());
    for case in &workload.cases {
        let documents = case
            .sessions
            .iter()
            .map(|session| {
                session
                    .turns
                    .iter()
                    .map(|turn| turn.content.as_str())
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .collect::<Vec<_>>();
        let index = build_index(
            documents
                .iter()
                .enumerate()
                .map(|(index, document)| (index as u64, [document.as_str()])),
            &LONGMEMEVAL_FIELDS,
        )?;
        let versions = case
            .sessions
            .iter()
            .map(session_version)
            .collect::<Vec<_>>();
        let mut scratch =
            SearchScratch::with_document_capacity(documents.len(), MAXIMUM_QUERY_GROUPS);
        let mut hits = Vec::<SearchHit>::with_capacity(CANDIDATE_CAP);
        index.search_evidence_into(&case.question, TOP_K, &mut scratch, &mut hits)?;
        let candidates = hits
            .iter()
            .enumerate()
            .map(|(rank, hit)| {
                let index = hit.external_id as usize;
                RarityCoverageCandidate {
                    document_identity: case.sessions[index].stable_id.clone(),
                    document_version: versions[index].clone(),
                    v2_order: rank + 1,
                    v2_score_bits: hit.v2_score.to_bits(),
                    rank_evidence_v3: hit.rank_evidence_v3,
                    relevance_tier: hit.relevance_tier,
                    rarity_weighted_group_coverage: hit.rarity_weighted_group_coverage,
                }
            })
            .collect();
        queries.push(RarityCoverageQuery {
            query_identity: case.question_id.clone(),
            candidates,
        });
    }
    Ok(RarityCoverageCohort { queries })
}

fn compare_cohort(expected: &FrozenCohort, actual: &RarityCoverageCohort) -> CohortParity {
    let mut parity = CohortParity {
        query_count_equal: expected.queries.len() == actual.queries.len(),
        candidate_pool_identity_equal: true,
        v2_order_equal: true,
        v2_score_bits_equal: true,
        canonical_rank_evidence_equal: true,
        relevance_tier_equal: true,
    };
    for (expected_query, actual_query) in expected.queries.iter().zip(&actual.queries) {
        parity.candidate_pool_identity_equal &= expected_query.query_identity
            == actual_query.query_identity
            && expected_query.candidate_pool.len() == actual_query.candidates.len();
        for (expected_candidate, actual_candidate) in expected_query
            .candidate_pool
            .iter()
            .zip(&actual_query.candidates)
        {
            parity.candidate_pool_identity_equal &=
                expected_candidate.document_identity == actual_candidate.document_identity;
            parity.v2_order_equal &= expected_candidate.v2_order == actual_candidate.v2_order;
            parity.v2_score_bits_equal &=
                expected_candidate.v2_score_bits == actual_candidate.v2_score_bits;
            parity.canonical_rank_evidence_equal &=
                expected_candidate.rank_evidence_v3 == actual_candidate.rank_evidence_v3;
            parity.relevance_tier_equal &=
                expected_candidate.relevance_tier == actual_candidate.relevance_tier;
        }
    }
    parity
}

#[inline]
fn valid(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

#[derive(Debug, Serialize)]
struct ReleaseRarityCoverageSidecar {
    contract: &'static str,
    schema_version: u16,
    architecture: &'static str,
    group_weight: &'static str,
    candidate_numerator: &'static str,
    phase_3: FileIdentity,
    mixed_suite_source: FileIdentity,
    workload: FileIdentity,
    gold: FileIdentity,
    mixed: RarityCoverageCohort,
    longmemeval: RarityCoverageCohort,
    gates: ReleaseRarityCoverageGates,
    production_promotion_authorized: bool,
}

#[derive(Debug, Serialize)]
struct RarityCoverageCohort {
    queries: Vec<RarityCoverageQuery>,
}

#[derive(Debug, Serialize)]
struct RarityCoverageQuery {
    query_identity: String,
    candidates: Vec<RarityCoverageCandidate>,
}

#[derive(Debug, Serialize)]
struct RarityCoverageCandidate {
    document_identity: String,
    document_version: String,
    v2_order: usize,
    v2_score_bits: u32,
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
    rarity_weighted_group_coverage: f32,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub(super) struct ReleaseRarityCoverageGates {
    phase_3_verified: bool,
    mixed: CohortParity,
    longmemeval: CohortParity,
    rarity_coverage_is_finite_and_bounded: bool,
}

impl ReleaseRarityCoverageGates {
    pub(super) fn all_pass(self) -> bool {
        self.phase_3_verified
            && self.mixed.all_pass()
            && self.longmemeval.all_pass()
            && self.rarity_coverage_is_finite_and_bounded
    }
}

#[derive(Clone, Copy, Debug, Serialize)]
struct CohortParity {
    query_count_equal: bool,
    candidate_pool_identity_equal: bool,
    v2_order_equal: bool,
    v2_score_bits_equal: bool,
    canonical_rank_evidence_equal: bool,
    relevance_tier_equal: bool,
}

impl CohortParity {
    fn all_pass(self) -> bool {
        self.query_count_equal
            && self.candidate_pool_identity_equal
            && self.v2_order_equal
            && self.v2_score_bits_equal
            && self.canonical_rank_evidence_equal
            && self.relevance_tier_equal
    }
}

#[derive(Debug, Deserialize)]
struct FrozenPhase3 {
    contract: String,
    mixed_suite: FrozenCohort,
    longmemeval_release: FrozenCohort,
    phase_3_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenCohort {
    queries: Vec<FrozenQuery>,
}

#[derive(Debug, Deserialize)]
struct FrozenQuery {
    query_identity: String,
    candidate_pool: Vec<FrozenCandidate>,
}

#[derive(Debug, Deserialize)]
struct FrozenCandidate {
    document_identity: String,
    v2_order: usize,
    v2_score_bits: u32,
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
}

#[derive(Debug, Serialize)]
pub(crate) struct ReleaseRarityCoveragePublication {
    contract: &'static str,
    output: FileIdentity,
    gates: ReleaseRarityCoverageGates,
    production_promotion_authorized: bool,
}
