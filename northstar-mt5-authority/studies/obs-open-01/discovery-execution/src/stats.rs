use crate::AnyResult;
use crate::corpus::{CorpusProducts, PackedCandidatePath};
use matrixmultiply::dgemm;
use obs_open_disc02p::{
    ALPHA, CandidateGates, NumericalDecision, RANDOM_SEED, RANDOMIZATIONS, SurfaceSupport,
    WILSON_Z_99, candidate_terminal_state, holm_bonferroni, monte_carlo_decision,
    surface_support_status, temporal_sign_status, wilson_interval,
};
use rayon::prelude::*;
use serde::Serialize;
use std::collections::BTreeMap;

const BATCH: usize = 64;

#[derive(Debug, Clone)]
pub struct DenseSurface {
    pub family_id: String,
    pub representation_id: String,
    pub authority_classification: String,
    pub cell_ids: Vec<String>,
    pub values: Vec<f64>,
    pub present: Vec<u8>,
    pub sessions: usize,
    pub cells: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct CellSupportReceipt {
    pub family_id: String,
    pub cell_id: String,
    pub eligible_sessions: usize,
    pub supported_month_count: usize,
    pub month_counts: BTreeMap<String, usize>,
    pub offset_120_sessions: usize,
    pub offset_180_sessions: usize,
    pub chronological_block_counts: [usize; 4],
    pub leave_one_month_statuses: Vec<String>,
    pub formal_support_state: String,
    pub observed_mean: f64,
    pub observed_t: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct RobustnessSlice {
    pub view: String,
    pub stratum: String,
    pub eligible_sessions: usize,
    pub contrast: f64,
    pub sign_matches_anchor: bool,
    pub support_state: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct LocalizationReceipt {
    pub family_id: String,
    pub anchor_cell: String,
    pub observed_contrast: f64,
    pub studentized_magnitude: f64,
    pub direction: String,
    pub eligible_sessions: usize,
    pub tie_count: usize,
    pub tie_break: String,
    pub simultaneously_qualified_cells: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct FormalFamilyResult {
    pub family_id: String,
    pub representation_id: String,
    pub authority_classification: String,
    pub formal_cell_count: usize,
    pub supported_cell_count: usize,
    pub observed_max_abs_t: f64,
    pub exceedance_count: u64,
    pub plus_one_successes: u64,
    pub monte_carlo_trials: u64,
    pub corrected_p_value: f64,
    pub wilson_99_lower: f64,
    pub wilson_99_upper: f64,
    pub holm_rank: usize,
    pub holm_threshold: f64,
    pub holm_decision: bool,
    pub numerical_decision: String,
    pub temporal_status: String,
    pub terminal_state: String,
    pub localization: Option<LocalizationReceipt>,
    pub robustness: Vec<RobustnessSlice>,
    #[serde(skip)]
    pub reference_distribution: Vec<f64>,
    #[serde(skip)]
    anchor_index: Option<usize>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ScaleCurvatureRow {
    pub k: u16,
    pub tau_minutes: u16,
    pub eligible_sessions: usize,
    pub mean_second_difference: f64,
    pub classification: String,
}

#[derive(Debug)]
pub struct Analysis {
    pub surfaces: Vec<DenseSurface>,
    pub support: Vec<Vec<CellSupportReceipt>>,
    pub results: Vec<FormalFamilyResult>,
    pub scale_curvature: Vec<ScaleCurvatureRow>,
}

pub fn analyze(corpus: &CorpusProducts, threads: usize) -> AnyResult<Analysis> {
    let surfaces = vec![
        candidate_surface(
            corpus,
            "A_SAME_DIRECTION_SIDE_CONTRAST",
            "MIRRORED_SIDE_CANONICAL_CANDIDATE_EXTENSION_V1",
            "OBSERVER_CONSTRAINED",
            |p| p.same_direction_extension,
        ),
        candidate_surface(
            corpus,
            "A_OPPOSITE_DISPLACEMENT_SIDE_CONTRAST",
            "MIRRORED_SIDE_CANONICAL_CANDIDATE_OPPOSITE_V1",
            "EMPIRICAL",
            |p| p.opposite_displacement,
        ),
        range_surface(corpus),
    ];
    let support: Vec<Vec<CellSupportReceipt>> = surfaces
        .iter()
        .map(|surface| support_census(surface, corpus))
        .collect();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads.max(1))
        .build()?;
    let mut results: Vec<FormalFamilyResult> = surfaces
        .iter()
        .zip(support.iter())
        .map(|(surface, support)| execute_family(surface, support, &pool))
        .collect::<Result<Vec<_>, _>>()?;
    apply_holm_and_promotion(&surfaces, &support, corpus, &mut results)?;
    let scale_curvature = scale_curvature(corpus);
    Ok(Analysis {
        surfaces,
        support,
        results,
        scale_curvature,
    })
}

fn candidate_surface<F>(
    corpus: &CorpusProducts,
    family_id: &str,
    representation_id: &str,
    classification: &str,
    value: F,
) -> DenseSurface
where
    F: Fn(&PackedCandidatePath) -> f64,
{
    let sessions = corpus.sessions.len();
    let cells = corpus
        .candidate_paths
        .iter()
        .map(|p| p.age_minutes as usize)
        .max()
        .unwrap_or(0);
    let stride = cells + 1;
    let mut up_sum = vec![0.0; sessions * stride];
    let mut down_sum = vec![0.0; sessions * stride];
    let mut up_count = vec![0u16; sessions * stride];
    let mut down_count = vec![0u16; sessions * stride];
    for path in &corpus.candidate_paths {
        let slot = path.session_index as usize * stride + path.age_minutes as usize;
        if path.side == 1 {
            up_sum[slot] += value(path);
            up_count[slot] += 1;
        } else {
            down_sum[slot] += value(path);
            down_count[slot] += 1;
        }
    }
    let mut values = vec![0.0; sessions * cells];
    let mut present = vec![0u8; sessions * cells];
    for session in 0..sessions {
        for age in 1..=cells {
            let source = session * stride + age;
            let target = session * cells + age - 1;
            if up_count[source] > 0 && down_count[source] > 0 {
                values[target] = up_sum[source] / f64::from(up_count[source])
                    - down_sum[source] / f64::from(down_count[source]);
                present[target] = 1;
            }
        }
    }
    DenseSurface {
        family_id: family_id.into(),
        representation_id: representation_id.into(),
        authority_classification: classification.into(),
        cell_ids: (1..=cells)
            .map(|age| format!("age_minute={age:03}"))
            .collect(),
        values,
        present,
        sessions,
        cells,
    }
}

fn range_surface(corpus: &CorpusProducts) -> DenseSurface {
    let sessions = corpus.sessions.len();
    let cell_ids: Vec<String> = (1u16..=30)
        .flat_map(|k| (1u16..=(390 - k)).map(move |tau| format!("k={k:02};tau={tau:03}")))
        .collect();
    let cells = cell_ids.len();
    let mut values = vec![0.0; sessions * cells];
    let mut present = vec![0u8; sessions * cells];
    for row in &corpus.range_surface {
        let cell = range_cell_index(row.k, row.tau_minutes);
        let slot = row.session_index as usize * cells + cell;
        if row.status == 1 && row.z_close.is_finite() {
            values[slot] = row.z_close;
            present[slot] = 1;
        }
    }
    DenseSurface {
        family_id: "B_RANGE_RELATIVE_SIGNED_CLOSE_SURFACE".into(),
        representation_id: "RANGE_RELATIVE_Z_CLOSE_M1_V1".into(),
        authority_classification: "EMPIRICAL".into(),
        cell_ids,
        values,
        present,
        sessions,
        cells,
    }
}

fn range_cell_index(k: u16, tau: u16) -> usize {
    let prior: usize = (1..k).map(|prior_k| (390 - prior_k) as usize).sum();
    prior + tau as usize - 1
}

fn support_census(surface: &DenseSurface, corpus: &CorpusProducts) -> Vec<CellSupportReceipt> {
    let months: Vec<String> = corpus
        .sessions
        .iter()
        .map(|s| s.spec.civil_date[..7].to_owned())
        .collect();
    let blocks: Vec<usize> = (0..surface.sessions)
        .map(|i| (i * 4 / surface.sessions).min(3))
        .collect();
    (0..surface.cells)
        .map(|cell| {
            let eligible: Vec<usize> = (0..surface.sessions)
                .filter(|&session| surface.present[session * surface.cells + cell] == 1)
                .collect();
            let mut month_counts = BTreeMap::new();
            let mut offsets = [0usize; 2];
            let mut block_counts = [0usize; 4];
            let mut sum = 0.0;
            let mut sumsq = 0.0;
            for &session in &eligible {
                *month_counts.entry(months[session].clone()).or_insert(0) += 1;
                match corpus.sessions[session].spec.server_offset_minutes {
                    120 => offsets[0] += 1,
                    180 => offsets[1] += 1,
                    _ => {}
                }
                block_counts[blocks[session]] += 1;
                let x = surface.values[session * surface.cells + cell];
                sum += x;
                sumsq += x * x;
            }
            let supported: Vec<String> = month_counts
                .iter()
                .filter(|(_, count)| **count >= 10)
                .map(|(month, _)| month.clone())
                .collect();
            let mut lomo = Vec::with_capacity(supported.len());
            let mut lomo_status = Vec::with_capacity(supported.len());
            for omitted in &supported {
                let remaining: Vec<usize> = eligible
                    .iter()
                    .copied()
                    .filter(|&session| months[session] != *omitted)
                    .collect();
                let remaining_months = month_counts
                    .iter()
                    .filter(|(month, count)| *month != omitted && **count >= 10)
                    .count();
                let offset120 = remaining
                    .iter()
                    .filter(|&&i| corpus.sessions[i].spec.server_offset_minutes == 120)
                    .count();
                let offset180 = remaining
                    .iter()
                    .filter(|&&i| corpus.sessions[i].spec.server_offset_minutes == 180)
                    .count();
                lomo.push(obs_open_disc02p::LeaveOneMonthSupport {
                    remaining_sessions: remaining.len(),
                    supported_months: remaining_months,
                    offset_120_sessions: offset120,
                    offset_180_sessions: offset180,
                });
                lomo_status.push(format!(
                    "omit={omitted};remaining={};months={remaining_months};offset120={offset120};offset180={offset180}",
                    remaining.len()
                ));
            }
            let support = SurfaceSupport {
                eligible_sessions: eligible.len(),
                month_counts: month_counts.values().copied().collect(),
                offset_120_sessions: offsets[0],
                offset_180_sessions: offsets[1],
                chronological_block_counts: block_counts,
                leave_one_month: lomo,
            };
            let mean = if eligible.is_empty() { 0.0 } else { sum / eligible.len() as f64 };
            CellSupportReceipt {
                family_id: surface.family_id.clone(),
                cell_id: surface.cell_ids[cell].clone(),
                eligible_sessions: eligible.len(),
                supported_month_count: supported.len(),
                month_counts,
                offset_120_sessions: offsets[0],
                offset_180_sessions: offsets[1],
                chronological_block_counts: block_counts,
                leave_one_month_statuses: lomo_status,
                formal_support_state: surface_support_status(&support).into(),
                observed_mean: mean,
                observed_t: t_from_sum(sum, sumsq, eligible.len()),
            }
        })
        .collect()
}

fn execute_family(
    surface: &DenseSurface,
    support: &[CellSupportReceipt],
    pool: &rayon::ThreadPool,
) -> AnyResult<FormalFamilyResult> {
    let supported: Vec<usize> = support
        .iter()
        .enumerate()
        .filter(|(_, receipt)| receipt.formal_support_state == "PASS")
        .map(|(index, _)| index)
        .collect();
    if supported.is_empty() {
        return Ok(empty_result(surface, "SURFACE_SUPPORT_INSUFFICIENT"));
    }
    let compact = compact_matrix(surface, &supported);
    let observed_t: Vec<f64> = supported
        .iter()
        .map(|&cell| support[cell].observed_t)
        .collect();
    let observed_max = observed_t.iter().map(|x| x.abs()).fold(0.0, f64::max);
    let reference = randomization_distribution(
        &compact,
        surface.sessions,
        supported.len(),
        &supported
            .iter()
            .map(|&cell| support[cell].eligible_sessions)
            .collect::<Vec<_>>(),
        pool,
    )?;
    let exceedances = reference
        .iter()
        .filter(|&&value| value >= observed_max)
        .count() as u64;
    let successes = exceedances + 1;
    let trials = RANDOMIZATIONS + 1;
    let p = successes as f64 / trials as f64;
    let (lower, upper) = wilson_interval(successes, trials, WILSON_Z_99)?;
    let max_indices: Vec<usize> = observed_t
        .iter()
        .enumerate()
        .filter(|(_, value)| value.abs() == observed_max)
        .map(|(index, _)| index)
        .collect();
    let anchor_compact = max_indices
        .iter()
        .copied()
        .min_by(|&a, &b| surface.cell_ids[supported[a]].cmp(&surface.cell_ids[supported[b]]));
    Ok(FormalFamilyResult {
        family_id: surface.family_id.clone(),
        representation_id: surface.representation_id.clone(),
        authority_classification: surface.authority_classification.clone(),
        formal_cell_count: surface.cells,
        supported_cell_count: supported.len(),
        observed_max_abs_t: observed_max,
        exceedance_count: exceedances,
        plus_one_successes: successes,
        monte_carlo_trials: trials,
        corrected_p_value: p,
        wilson_99_lower: lower,
        wilson_99_upper: upper,
        holm_rank: 0,
        holm_threshold: 0.0,
        holm_decision: false,
        numerical_decision: "PENDING_HOLM_THRESHOLD".into(),
        temporal_status: "NOT_EVALUATED_PRE_HOLM".into(),
        terminal_state: "PENDING_MULTIPLICITY".into(),
        localization: None,
        robustness: Vec::new(),
        reference_distribution: reference,
        anchor_index: anchor_compact.map(|compact_index| supported[compact_index]),
    })
}

fn empty_result(surface: &DenseSurface, state: &str) -> FormalFamilyResult {
    FormalFamilyResult {
        family_id: surface.family_id.clone(),
        representation_id: surface.representation_id.clone(),
        authority_classification: surface.authority_classification.clone(),
        formal_cell_count: surface.cells,
        supported_cell_count: 0,
        observed_max_abs_t: 0.0,
        exceedance_count: 0,
        plus_one_successes: 0,
        monte_carlo_trials: 0,
        corrected_p_value: 1.0,
        wilson_99_lower: 0.0,
        wilson_99_upper: 1.0,
        holm_rank: 0,
        holm_threshold: 0.0,
        holm_decision: false,
        numerical_decision: "NOT_EVALUABLE".into(),
        temporal_status: "TEMPORAL_SUPPORT_INSUFFICIENT".into(),
        terminal_state: state.into(),
        localization: None,
        robustness: Vec::new(),
        reference_distribution: Vec::new(),
        anchor_index: None,
    }
}

fn compact_matrix(surface: &DenseSurface, supported: &[usize]) -> Vec<f64> {
    let mut compact = vec![0.0; surface.sessions * supported.len()];
    for session in 0..surface.sessions {
        for (target, &source) in supported.iter().enumerate() {
            let source_slot = session * surface.cells + source;
            if surface.present[source_slot] == 1 {
                compact[session * supported.len() + target] = surface.values[source_slot];
            }
        }
    }
    compact
}

fn randomization_distribution(
    matrix: &[f64],
    sessions: usize,
    cells: usize,
    eligible: &[usize],
    pool: &rayon::ThreadPool,
) -> AnyResult<Vec<f64>> {
    if matrix.len() != sessions * cells || eligible.len() != cells {
        return Err("RANDOMIZATION_MATRIX_SHAPE_DRIFT".into());
    }
    let mut sumsq = vec![0.0; cells];
    for row in matrix.chunks_exact(cells) {
        for (cell, value) in row.iter().enumerate() {
            sumsq[cell] += value * value;
        }
    }
    let starts: Vec<usize> = (0..RANDOMIZATIONS as usize).step_by(BATCH).collect();
    let batches: Vec<(usize, Vec<f64>)> = pool.install(|| {
        starts
            .into_par_iter()
            .map(|start| {
                let rows = BATCH.min(RANDOMIZATIONS as usize - start);
                let mut signs = vec![0.0; rows * sessions];
                for row in 0..rows {
                    for session in 0..sessions {
                        signs[row * sessions + session] =
                            sign(RANDOM_SEED, (start + row) as u64, session);
                    }
                }
                let mut products = vec![0.0; rows * cells];
                unsafe {
                    dgemm(
                        rows,
                        sessions,
                        cells,
                        1.0,
                        signs.as_ptr(),
                        sessions as isize,
                        1,
                        matrix.as_ptr(),
                        cells as isize,
                        1,
                        0.0,
                        products.as_mut_ptr(),
                        cells as isize,
                        1,
                    );
                }
                let mut maxima = vec![0.0; rows];
                for row in 0..rows {
                    let mut maximum: f64 = 0.0;
                    for cell in 0..cells {
                        maximum = maximum.max(
                            t_from_sum(products[row * cells + cell], sumsq[cell], eligible[cell])
                                .abs(),
                        );
                    }
                    maxima[row] = maximum;
                }
                (start, maxima)
            })
            .collect()
    });
    let mut out = vec![0.0; RANDOMIZATIONS as usize];
    for (start, values) in batches {
        out[start..start + values.len()].copy_from_slice(&values);
    }
    Ok(out)
}

fn apply_holm_and_promotion(
    surfaces: &[DenseSurface],
    support: &[Vec<CellSupportReceipt>],
    corpus: &CorpusProducts,
    results: &mut [FormalFamilyResult],
) -> AnyResult<()> {
    let p_values: Vec<(String, f64)> = results
        .iter()
        .map(|result| (result.family_id.clone(), result.corrected_p_value))
        .collect();
    let holm = holm_bonferroni(&p_values, ALPHA);
    for (rank, (family, pass, threshold)) in holm.into_iter().enumerate() {
        let index = results
            .iter()
            .position(|result| result.family_id == family)
            .ok_or("HOLM_FAMILY_MISSING")?;
        let result = &mut results[index];
        result.holm_rank = rank + 1;
        result.holm_threshold = threshold;
        result.holm_decision = pass;
        if result.monte_carlo_trials == 0 {
            continue;
        }
        let numerical = monte_carlo_decision(
            result.plus_one_successes,
            result.monte_carlo_trials,
            threshold,
        )?;
        result.numerical_decision = match numerical {
            NumericalDecision::Pass => "PASS",
            NumericalDecision::Fail => "FAIL",
            NumericalDecision::Unresolved => "NUMERICAL_DECISION_UNRESOLVED",
        }
        .into();
        let surface = &surfaces[index];
        let anchor = result.anchor_index;
        let (robustness, temporal) = if pass && numerical == NumericalDecision::Pass {
            if let Some(anchor) = anchor {
                robustness(surface, anchor, corpus)
            } else {
                (Vec::new(), "TEMPORAL_SUPPORT_INSUFFICIENT".into())
            }
        } else {
            (Vec::new(), "NOT_EVALUATED_PRE_PROMOTION".into())
        };
        result.temporal_status = temporal.clone();
        result.robustness = robustness;
        let omnibus_pass = result.corrected_p_value <= ALPHA;
        let support_status = if result.supported_cell_count > 0 {
            "PASS"
        } else {
            "SURFACE_SUPPORT_INSUFFICIENT"
        };
        let temporal_contract = match temporal.as_str() {
            "TEMPORAL_SUPPORT_INSUFFICIENT" => "TEMPORAL_SUPPORT_INSUFFICIENT",
            "TEMPORALLY_UNSTABLE" => "TEMPORALLY_UNSTABLE",
            "TEMPORALLY_SUPPORTED" | "NOT_EVALUATED_PRE_PROMOTION" => "TEMPORALLY_SUPPORTED",
            _ => "TEMPORAL_SUPPORT_INSUFFICIENT",
        };
        result.terminal_state = candidate_terminal_state(CandidateGates {
            coverage_evaluable: true,
            support_status,
            numerical_resolution: true,
            monte_carlo: numerical,
            omnibus_pass,
            holm_pass: pass,
            temporal_status: temporal_contract,
        })
        .into();
        if pass
            && numerical == NumericalDecision::Pass
            && let Some(anchor_index) = anchor
        {
            let observed = support[index][anchor_index].observed_mean;
            let t = support[index][anchor_index].observed_t;
            let max_abs = result.observed_max_abs_t;
            let tie_count = support[index]
                .iter()
                .filter(|cell| {
                    cell.formal_support_state == "PASS" && cell.observed_t.abs() == max_abs
                })
                .count();
            let qualified = simultaneous_cells(result, &support[index]);
            result.localization = Some(LocalizationReceipt {
                family_id: result.family_id.clone(),
                anchor_cell: surface.cell_ids[anchor_index].clone(),
                observed_contrast: observed,
                studentized_magnitude: t.abs(),
                direction: direction(observed).into(),
                eligible_sessions: support[index][anchor_index].eligible_sessions,
                tie_count,
                tie_break: "LEXICOGRAPHIC_CELL_ID_AMONG_EXACT_MAX_ABS_T_TIES".into(),
                simultaneously_qualified_cells: qualified,
            });
        }
    }
    Ok(())
}

fn simultaneous_cells(result: &FormalFamilyResult, support: &[CellSupportReceipt]) -> Vec<String> {
    let mut out = Vec::new();
    for cell in support
        .iter()
        .filter(|cell| cell.formal_support_state == "PASS")
    {
        let exceed = result
            .reference_distribution
            .iter()
            .filter(|&&value| value >= cell.observed_t.abs())
            .count() as u64;
        let successes = exceed + 1;
        let trials = RANDOMIZATIONS + 1;
        let (_, upper) = wilson_interval(successes, trials, WILSON_Z_99).unwrap_or((0.0, 1.0));
        let p = successes as f64 / trials as f64;
        if p <= result.holm_threshold && upper <= result.holm_threshold {
            out.push(cell.cell_id.clone());
        }
    }
    out
}

fn robustness(
    surface: &DenseSurface,
    anchor: usize,
    corpus: &CorpusProducts,
) -> (Vec<RobustnessSlice>, String) {
    let eligible: Vec<usize> = (0..surface.sessions)
        .filter(|&session| surface.present[session * surface.cells + anchor] == 1)
        .collect();
    let aggregate = mean_for(surface, anchor, &eligible);
    let mut slices = Vec::new();
    let mut by_month: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    let mut by_offset: BTreeMap<i32, Vec<usize>> = BTreeMap::new();
    let mut by_block: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for &session in &eligible {
        by_month
            .entry(corpus.sessions[session].spec.civil_date[..7].into())
            .or_default()
            .push(session);
        by_offset
            .entry(corpus.sessions[session].spec.server_offset_minutes)
            .or_default()
            .push(session);
        by_block
            .entry((session * 4 / surface.sessions).min(3))
            .or_default()
            .push(session);
    }
    for (month, members) in by_month.iter().filter(|(_, members)| members.len() >= 10) {
        slices.push(make_slice(
            "CALENDAR_MONTH",
            month,
            members,
            surface,
            anchor,
            aggregate,
            10,
        ));
    }
    for (offset, members) in &by_offset {
        slices.push(make_slice(
            "SERVER_OFFSET",
            &offset.to_string(),
            members,
            surface,
            anchor,
            aggregate,
            20,
        ));
    }
    for block in 0..4 {
        let members = by_block.get(&block).cloned().unwrap_or_default();
        slices.push(make_slice(
            "CHRONOLOGICAL_BLOCK",
            &block.to_string(),
            &members,
            surface,
            anchor,
            aggregate,
            20,
        ));
    }
    for month in by_month.keys().filter(|month| by_month[*month].len() >= 10) {
        let members: Vec<usize> = eligible
            .iter()
            .copied()
            .filter(|&session| &corpus.sessions[session].spec.civil_date[..7] != month)
            .collect();
        slices.push(make_slice(
            "LEAVE_ONE_MONTH_OUT",
            month,
            &members,
            surface,
            anchor,
            aggregate,
            103,
        ));
    }
    let insufficient = slices.iter().any(|slice| slice.support_state != "PASS");
    let contrasts: Vec<f64> = slices
        .iter()
        .filter(|slice| slice.support_state == "PASS")
        .map(|slice| slice.contrast)
        .collect();
    let status = if insufficient {
        "TEMPORAL_SUPPORT_INSUFFICIENT"
    } else {
        temporal_sign_status(aggregate, &contrasts)
    };
    (slices, status.into())
}

fn make_slice(
    view: &str,
    stratum: &str,
    members: &[usize],
    surface: &DenseSurface,
    anchor: usize,
    aggregate: f64,
    minimum: usize,
) -> RobustnessSlice {
    let contrast = mean_for(surface, anchor, members);
    let supported = members.len() >= minimum;
    RobustnessSlice {
        view: view.into(),
        stratum: stratum.into(),
        eligible_sessions: members.len(),
        contrast,
        sign_matches_anchor: supported
            && contrast != 0.0
            && contrast.is_sign_positive() == aggregate.is_sign_positive(),
        support_state: if supported {
            "PASS"
        } else {
            "INSUFFICIENT_SUPPORT"
        }
        .into(),
    }
}

fn mean_for(surface: &DenseSurface, cell: usize, sessions: &[usize]) -> f64 {
    if sessions.is_empty() {
        return 0.0;
    }
    sessions
        .iter()
        .map(|&session| surface.values[session * surface.cells + cell])
        .sum::<f64>()
        / sessions.len() as f64
}

fn scale_curvature(corpus: &CorpusProducts) -> Vec<ScaleCurvatureRow> {
    let cells = (1..=30).map(|k| 390 - k).sum::<usize>();
    let mut by_session = vec![0.0; corpus.sessions.len() * cells];
    let mut present = vec![false; corpus.sessions.len() * cells];
    for row in &corpus.range_surface {
        if row.status == 1 {
            let cell = range_cell_index(row.k, row.tau_minutes);
            by_session[row.session_index as usize * cells + cell] = row.z_close;
            present[row.session_index as usize * cells + cell] = true;
        }
    }
    let mut out = Vec::new();
    for k in 2u16..=29 {
        for tau in 1u16..=(390 - (k + 1)) {
            let left = range_cell_index(k - 1, tau);
            let center = range_cell_index(k, tau);
            let right = range_cell_index(k + 1, tau);
            let mut n = 0usize;
            let mut sum = 0.0;
            for session in 0..corpus.sessions.len() {
                let base = session * cells;
                if present[base + left] && present[base + center] && present[base + right] {
                    sum += by_session[base + right] - 2.0 * by_session[base + center]
                        + by_session[base + left];
                    n += 1;
                }
            }
            out.push(ScaleCurvatureRow {
                k,
                tau_minutes: tau,
                eligible_sessions: n,
                mean_second_difference: if n == 0 { 0.0 } else { sum / n as f64 },
                classification: "DESCRIPTIVE_ONLY_OBSERVER_SCALE_GEOMETRY".into(),
            });
        }
    }
    out
}

fn t_from_sum(sum: f64, sumsq: f64, n: usize) -> f64 {
    if n < 2 {
        return 0.0;
    }
    let nf = n as f64;
    let variance = ((sumsq - sum * sum / nf) / (nf - 1.0)).max(0.0);
    if variance == 0.0 {
        0.0
    } else {
        (sum / nf) / (variance / nf).sqrt()
    }
}

fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

fn sign(seed: u64, permutation: u64, session: usize) -> f64 {
    let key = seed
        ^ permutation.wrapping_mul(0xD6E8_FD9D_50A5_8B09)
        ^ (session as u64).wrapping_mul(0xA076_1D64_78BD_642F);
    if splitmix64(key) & 1 == 0 { -1.0 } else { 1.0 }
}

fn direction(value: f64) -> &'static str {
    if value > 0.0 {
        "POSITIVE"
    } else if value < 0.0 {
        "NEGATIVE"
    } else {
        "ZERO"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn range_cells_are_dense_and_unique() {
        let mut seen = std::collections::BTreeSet::new();
        for k in 1u16..=30 {
            for tau in 1u16..=(390 - k) {
                assert!(seen.insert(range_cell_index(k, tau)));
            }
        }
        assert_eq!(seen.len(), 11_235);
        assert_eq!(seen.first(), Some(&0));
        assert_eq!(seen.last(), Some(&11_234));
    }

    #[test]
    fn randomization_is_thread_count_invariant() {
        let matrix = vec![1.0, -2.0, 0.5, 3.0, -1.5, 0.25];
        let eligible = vec![3, 3];
        let one = rayon::ThreadPoolBuilder::new()
            .num_threads(1)
            .build()
            .unwrap();
        let four = rayon::ThreadPoolBuilder::new()
            .num_threads(4)
            .build()
            .unwrap();
        let a = randomization_distribution(&matrix, 3, 2, &eligible, &one).unwrap();
        let b = randomization_distribution(&matrix, 3, 2, &eligible, &four).unwrap();
        assert_eq!(a, b);
        assert_eq!(a.len(), RANDOMIZATIONS as usize);
    }

    #[test]
    fn missing_rows_are_zero_weight_not_fabricated_samples() {
        let values = [2.0, 0.0, 4.0];
        let sum: f64 = values.iter().sum();
        let sumsq: f64 = values.iter().map(|x| x * x).sum();
        assert_eq!(t_from_sum(sum, sumsq, 2), 3.0);
        assert_ne!(t_from_sum(sum, sumsq, 3), 3.0);
    }
}
