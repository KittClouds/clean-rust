use std::path::{Path, PathBuf};

use phoenix_lexical_qps::{JudgmentIdentity, JudgmentReasonV3, PrimarySplitV3, RankEvidenceV3};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.7-rarity-coverage-preflight/v2";
const SIDECAR_CONTRACT: &str = "phoenix.qps.phase8.7-rarity-group-coverage-sidecar/v1";
const RELEASE_CONTRACT: &str =
    "phoenix.memory.qps-v3-phase8.7-release-rarity-group-coverage-sidecar/v1";
const VALUE_EPSILON: f32 = 1.0e-6;
const NEAR_WEIGHTED_COVERAGE: f32 = 0.01;
const MINIMUM_BLIND_DIRECTIONAL_PAIRS: usize = 30;
const REQUIRED_PREFERRED_HIGHER_RATIO: f64 = 0.70;
const TARGET_REASONS: [JudgmentReasonV3; 5] = [
    JudgmentReasonV3::CommonTermDominance,
    JudgmentReasonV3::WrongConceptProximity,
    JudgmentReasonV3::PartialMatchSaturation,
    JudgmentReasonV3::DocumentConversationConfusion,
    JudgmentReasonV3::LongQueryFailure,
];

pub(crate) fn preflight(
    phase_6_path: &Path,
    phase_4_path: &Path,
    independent_ledger_path: &Path,
    graded_suite_path: &Path,
    independent_sidecar_path: &Path,
    release_sidecar_path: &Path,
    output_path: &Path,
) -> Result<Phase87PreflightPublication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.7 preflight {}",
            output_path.display()
        );
    }
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    if !phase_4.phase_4_verified || !phase_6.phase_6_verified {
        bail!("Phase 8.7 requires verified Phase 4 and Phase 6 evidence");
    }
    let independent: IndependentRarityCoverageSidecar = read_json(
        independent_sidecar_path,
        "independent rarity coverage sidecar",
    )?;
    let release: ReleaseRarityCoverageSidecar =
        read_json(release_sidecar_path, "release rarity coverage sidecar")?;
    validate_contracts(&independent, &release)?;

    let ledger_file = bound_file(independent_ledger_path)?;
    let graded_file = bound_file(graded_suite_path)?;
    if independent.canonical_ledger.sha256 != ledger_file.sha256
        || independent.canonical_graded_suite.sha256 != graded_file.sha256
    {
        bail!("Phase 8.7 sidecar is not bound to the supplied immutable v9 inputs");
    }

    let preflight = audit_pairs(&phase_4.ledger, &phase_6.split, &independent)?;
    let target_preflight_eligible = aggregate_target_preflight_eligible(&preflight.classes);
    let signal_survives = signal_survives(target_preflight_eligible);
    let gates = Phase87PreflightGates {
        phase_4_verified: phase_4.phase_4_verified,
        phase_6_verified: phase_6.phase_6_verified,
        independent_ledger_byte_identical_to_v9: ledger_file.sha256
            == "a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8",
        independent_graded_byte_identical_to_v9: graded_file.sha256
            == "d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b",
        all_active_labels_projected: preflight.active_judgments == preflight.projected_judgments,
        rarity_coverage_finite_and_bounded: preflight.rarity_coverage_finite_and_bounded,
        release_substrate_bit_identical: release.gates.all_pass(),
        canonical_evidence_unmodified: true,
        production_promotion_forbidden: true,
    };
    if !gates.all_pass() {
        bail!("Phase 8.7 preflight integrity gates failed: {gates:?}");
    }

    let conclusion = Phase87PreflightConclusion {
        outcome: if signal_survives {
            "rarity_coverage_contains_missing_pairwise_information"
        } else {
            "rarity_coverage_does_not_clear_pair_delta_preflight"
        },
        minimum_blind_directional_pairs: MINIMUM_BLIND_DIRECTIONAL_PAIRS,
        required_preferred_higher_ratio: REQUIRED_PREFERRED_HIGHER_RATIO,
        observed_blind_directional_pairs: target_preflight_eligible.directional(),
        observed_preferred_higher_ratio: target_preflight_eligible.preferred_higher_ratio(),
        authorize_phase_8_7b_learner_diagnostic: signal_survives,
        authorize_schema_migration: false,
        next_action: if signal_survives {
            "run_controlled_monotonic_linear_diagnostic"
        } else {
            "stop_before_training_and_select_another_primitive"
        },
    };
    let receipt = Phase87PreflightReceipt {
        contract: CONTRACT,
        architecture: "pair_delta_gate_before_any_rarity_coverage_training",
        group_weight:
            "max_over_resolved_expansions(expansion_quality_times_normalized_term_rarity)",
        candidate_numerator: "sum_candidate_independent_weights_of_matched_groups",
        candidate_expansion_quality_in_numerator: false,
        blind_cohort_definition: BlindCohortDefinition {
            matched_group_fraction_max_delta: VALUE_EPSILON,
            weighted_group_coverage_max_delta: NEAR_WEIGHTED_COVERAGE,
            rarity_coverage_min_delta_exclusive: VALUE_EPSILON,
        },
        phase_6_receipt: bound_file(phase_6_path)?,
        phase_4_receipt: bound_file(phase_4_path)?,
        independent_ledger: ledger_file,
        graded_suite: graded_file,
        independent_rarity_coverage_sidecar: bound_file(independent_sidecar_path)?,
        release_rarity_coverage_sidecar: bound_file(release_sidecar_path)?,
        producer_binary: bound_file(&std::env::current_exe()?)?,
        preflight,
        target_preflight_eligible,
        conclusion,
        gates,
        canonical_rank_evidence_schema_changed: false,
        canonical_ledger_changed: false,
        production_promotion_authorized: false,
        active_engine_after_preflight: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(Phase87PreflightPublication {
        contract: CONTRACT,
        output: bound_file(output_path)?,
        conclusion,
        production_promotion_authorized: false,
        active_engine_after_preflight: "V2 active",
    })
}

fn validate_contracts(
    independent: &IndependentRarityCoverageSidecar,
    release: &ReleaseRarityCoverageSidecar,
) -> Result<()> {
    if independent.contract != SIDECAR_CONTRACT
        || independent.replaced_canonical_coordinate != RankEvidenceV3::MISSING_GROUP_ABSENCE
        || independent.experimental_feature != "rarity_weighted_group_coverage"
        || release.contract != RELEASE_CONTRACT
        || !release.gates.all_pass()
    {
        bail!("invalid Phase 8.7 rarity coverage sidecar contract");
    }
    Ok(())
}

fn audit_pairs(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    sidecar: &IndependentRarityCoverageSidecar,
) -> Result<PairPreflight> {
    let records = sidecar
        .pairs
        .iter()
        .map(|pair| (pair.judgment_identity.as_str(), pair))
        .collect::<HashMap<_, _>>();
    let mut root_by_identity = HashMap::<JudgmentIdentity, JudgmentIdentity>::new();
    for judgment in &ledger.judgments {
        let root = judgment
            .supersedes
            .and_then(|parent| root_by_identity.get(&parent).copied())
            .unwrap_or(judgment.identity);
        root_by_identity.insert(judgment.identity, root);
    }
    let active = ledger.active_model_training_indices();
    let assignments = split
        .assignments
        .iter()
        .map(|assignment| (assignment.judgment_identity, assignment.primary_split))
        .collect::<HashMap<_, _>>();
    let mut aggregate = DirectionCounts::default();
    let mut blind = DirectionCounts::default();
    let mut preflight_eligible_blind = DirectionCounts::default();
    let mut classes = TARGET_REASONS
        .iter()
        .map(|reason| ClassPreflight {
            reason: *reason,
            all: DirectionCounts::default(),
            representation_blind: DirectionCounts::default(),
            preflight_eligible_representation_blind: DirectionCounts::default(),
        })
        .collect::<Vec<_>>();
    let mut reversed_preferences = 0;
    let mut bounded = true;
    let mut projected = 0;

    for index in active.iter().copied() {
        let judgment = &ledger.judgments[index];
        let primary_split = assignments
            .get(&judgment.identity)
            .context("active judgment is absent from Phase 6 split")?;
        let preflight_eligible = *primary_split != PrimarySplitV3::BlindTest;
        let root = root_by_identity
            .get(&judgment.identity)
            .context("active judgment root missing")?;
        let root_hex = hex(root.as_bytes());
        let pair = records
            .get(root_hex.as_str())
            .with_context(|| format!("missing rarity coverage for active root {root_hex}"))?;
        if hex(judgment.query_identity.as_bytes()) != pair.query_identity {
            bail!("rarity coverage root query identity mismatch");
        }
        let current_positive = hex(judgment.positive_document_version.as_bytes());
        let current_negative = hex(judgment.negative_document_version.as_bytes());
        let (positive, negative, reversed) =
            orient_pair(pair, &current_positive, &current_negative)?;
        reversed_preferences += usize::from(reversed);
        bounded &= valid(positive) && valid(negative);
        let direction = Direction::compare(positive, negative);
        aggregate.record(direction);

        let positive_features = judgment.positive_features.values;
        let negative_features = judgment.negative_features.values;
        let representation_blind = (positive_features[RankEvidenceV3::MATCHED_GROUP_FRACTION]
            - negative_features[RankEvidenceV3::MATCHED_GROUP_FRACTION])
            .abs()
            <= VALUE_EPSILON
            && (positive_features[RankEvidenceV3::WEIGHTED_GROUP_COVERAGE]
                - negative_features[RankEvidenceV3::WEIGHTED_GROUP_COVERAGE])
                .abs()
                <= NEAR_WEIGHTED_COVERAGE
            && (positive - negative).abs() > VALUE_EPSILON;
        if representation_blind {
            blind.record(direction);
            if preflight_eligible {
                preflight_eligible_blind.record(direction);
            }
        }
        if let Some(class) = classes
            .iter_mut()
            .find(|class| class.reason == judgment.reason)
        {
            class.all.record(direction);
            if representation_blind {
                class.representation_blind.record(direction);
                if preflight_eligible {
                    class
                        .preflight_eligible_representation_blind
                        .record(direction);
                }
            }
        }
        projected += 1;
    }

    Ok(PairPreflight {
        active_judgments: active.len(),
        projected_judgments: projected,
        reversed_preferences,
        all_pairs: aggregate,
        representation_blind_pairs: blind,
        preflight_eligible_representation_blind_pairs: preflight_eligible_blind,
        classes,
        rarity_coverage_finite_and_bounded: bounded,
    })
}

fn orient_pair(
    pair: &PairRarityCoverage,
    current_positive: &str,
    current_negative: &str,
) -> Result<(f32, f32, bool)> {
    if current_positive == pair.positive_document_version
        && current_negative == pair.negative_document_version
    {
        Ok((
            pair.positive_rarity_weighted_group_coverage,
            pair.negative_rarity_weighted_group_coverage,
            false,
        ))
    } else if current_positive == pair.negative_document_version
        && current_negative == pair.positive_document_version
    {
        Ok((
            pair.negative_rarity_weighted_group_coverage,
            pair.positive_rarity_weighted_group_coverage,
            true,
        ))
    } else {
        bail!("active reviewed pair diverged from its mined root")
    }
}

fn aggregate_target_preflight_eligible(classes: &[ClassPreflight]) -> DirectionCounts {
    let mut total = DirectionCounts::default();
    for class in classes {
        total.add(class.preflight_eligible_representation_blind);
    }
    total
}

fn signal_survives(counts: DirectionCounts) -> bool {
    counts.directional() >= MINIMUM_BLIND_DIRECTIONAL_PAIRS
        && counts.preferred_higher_ratio() >= REQUIRED_PREFERRED_HIGHER_RATIO
}

#[inline]
fn valid(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

fn bound_file(path: &Path) -> Result<BoundFile> {
    let bytes = fs::read(path)?;
    Ok(BoundFile {
        path: path.to_path_buf(),
        bytes: bytes.len() as u64,
        sha256: hex(Sha256::digest(&bytes).into()),
    })
}

fn hex<const N: usize>(bytes: [u8; N]) -> String {
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}

#[derive(Clone, Copy)]
enum Direction {
    Higher,
    Equal,
    Lower,
}

impl Direction {
    fn compare(positive: f32, negative: f32) -> Self {
        let delta = positive - negative;
        if delta > VALUE_EPSILON {
            Self::Higher
        } else if delta < -VALUE_EPSILON {
            Self::Lower
        } else {
            Self::Equal
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct DirectionCounts {
    preferred_higher: usize,
    equal: usize,
    preferred_lower: usize,
}

impl DirectionCounts {
    fn record(&mut self, direction: Direction) {
        match direction {
            Direction::Higher => self.preferred_higher += 1,
            Direction::Equal => self.equal += 1,
            Direction::Lower => self.preferred_lower += 1,
        }
    }

    fn add(&mut self, other: Self) {
        self.preferred_higher += other.preferred_higher;
        self.equal += other.equal;
        self.preferred_lower += other.preferred_lower;
    }

    fn directional(self) -> usize {
        self.preferred_higher + self.preferred_lower
    }

    fn preferred_higher_ratio(self) -> f64 {
        self.preferred_higher as f64 / self.directional().max(1) as f64
    }
}

#[derive(Debug, Serialize)]
struct PairPreflight {
    active_judgments: usize,
    projected_judgments: usize,
    reversed_preferences: usize,
    all_pairs: DirectionCounts,
    representation_blind_pairs: DirectionCounts,
    preflight_eligible_representation_blind_pairs: DirectionCounts,
    classes: Vec<ClassPreflight>,
    rarity_coverage_finite_and_bounded: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct ClassPreflight {
    reason: JudgmentReasonV3,
    all: DirectionCounts,
    representation_blind: DirectionCounts,
    preflight_eligible_representation_blind: DirectionCounts,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct BlindCohortDefinition {
    matched_group_fraction_max_delta: f32,
    weighted_group_coverage_max_delta: f32,
    rarity_coverage_min_delta_exclusive: f32,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Phase87PreflightConclusion {
    outcome: &'static str,
    minimum_blind_directional_pairs: usize,
    required_preferred_higher_ratio: f64,
    observed_blind_directional_pairs: usize,
    observed_preferred_higher_ratio: f64,
    authorize_phase_8_7b_learner_diagnostic: bool,
    authorize_schema_migration: bool,
    next_action: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Phase87PreflightGates {
    phase_4_verified: bool,
    phase_6_verified: bool,
    independent_ledger_byte_identical_to_v9: bool,
    independent_graded_byte_identical_to_v9: bool,
    all_active_labels_projected: bool,
    rarity_coverage_finite_and_bounded: bool,
    release_substrate_bit_identical: bool,
    canonical_evidence_unmodified: bool,
    production_promotion_forbidden: bool,
}

impl Phase87PreflightGates {
    fn all_pass(self) -> bool {
        self.phase_4_verified
            && self.phase_6_verified
            && self.independent_ledger_byte_identical_to_v9
            && self.independent_graded_byte_identical_to_v9
            && self.all_active_labels_projected
            && self.rarity_coverage_finite_and_bounded
            && self.release_substrate_bit_identical
            && self.canonical_evidence_unmodified
            && self.production_promotion_forbidden
    }
}

#[derive(Debug, Serialize)]
struct Phase87PreflightReceipt {
    contract: &'static str,
    architecture: &'static str,
    group_weight: &'static str,
    candidate_numerator: &'static str,
    candidate_expansion_quality_in_numerator: bool,
    blind_cohort_definition: BlindCohortDefinition,
    phase_6_receipt: BoundFile,
    phase_4_receipt: BoundFile,
    independent_ledger: BoundFile,
    graded_suite: BoundFile,
    independent_rarity_coverage_sidecar: BoundFile,
    release_rarity_coverage_sidecar: BoundFile,
    producer_binary: BoundFile,
    preflight: PairPreflight,
    target_preflight_eligible: DirectionCounts,
    conclusion: Phase87PreflightConclusion,
    gates: Phase87PreflightGates,
    canonical_rank_evidence_schema_changed: bool,
    canonical_ledger_changed: bool,
    production_promotion_authorized: bool,
    active_engine_after_preflight: &'static str,
}

#[derive(Debug, Serialize)]
pub(crate) struct Phase87PreflightPublication {
    contract: &'static str,
    output: BoundFile,
    conclusion: Phase87PreflightConclusion,
    production_promotion_authorized: bool,
    active_engine_after_preflight: &'static str,
}

#[derive(Debug, Serialize)]
struct BoundFile {
    path: PathBuf,
    bytes: u64,
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct IndependentRarityCoverageSidecar {
    contract: String,
    replaced_canonical_coordinate: usize,
    experimental_feature: String,
    canonical_ledger: InputBinding,
    canonical_graded_suite: InputBinding,
    pairs: Vec<PairRarityCoverage>,
}

#[derive(Debug, Deserialize)]
struct InputBinding {
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct PairRarityCoverage {
    judgment_identity: String,
    query_identity: String,
    positive_document_version: String,
    negative_document_version: String,
    positive_rarity_weighted_group_coverage: f32,
    negative_rarity_weighted_group_coverage: f32,
}

#[derive(Debug, Deserialize)]
struct ReleaseRarityCoverageSidecar {
    contract: String,
    gates: ReleaseSidecarGates,
}

#[derive(Debug, Deserialize)]
struct ReleaseSidecarGates {
    phase_3_verified: bool,
    mixed: ReleaseCohortParity,
    longmemeval: ReleaseCohortParity,
    rarity_coverage_is_finite_and_bounded: bool,
}

impl ReleaseSidecarGates {
    fn all_pass(&self) -> bool {
        self.phase_3_verified
            && self.mixed.all_pass()
            && self.longmemeval.all_pass()
            && self.rarity_coverage_is_finite_and_bounded
    }
}

#[derive(Debug, Deserialize)]
struct ReleaseCohortParity {
    query_count_equal: bool,
    candidate_pool_identity_equal: bool,
    v2_order_equal: bool,
    v2_score_bits_equal: bool,
    canonical_rank_evidence_equal: bool,
    relevance_tier_equal: bool,
}

impl ReleaseCohortParity {
    fn all_pass(&self) -> bool {
        self.query_count_equal
            && self.candidate_pool_identity_equal
            && self.v2_order_equal
            && self.v2_score_bits_equal
            && self.canonical_rank_evidence_equal
            && self.relevance_tier_equal
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preflight_requires_sample_size_and_directional_strength() {
        assert!(!signal_survives(DirectionCounts {
            preferred_higher: 20,
            equal: 0,
            preferred_lower: 5,
        }));
        assert!(!signal_survives(DirectionCounts {
            preferred_higher: 20,
            equal: 0,
            preferred_lower: 10,
        }));
        assert!(signal_survives(DirectionCounts {
            preferred_higher: 21,
            equal: 0,
            preferred_lower: 9,
        }));
    }
}
