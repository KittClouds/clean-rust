use crate::model::{
    CandidateDuration, Endpoint, MAX_AGE_MINUTES, PersistenceRow, SESSION_COUNT, SurfaceCell,
    SurfaceKey, SurfaceRow, WidthRow, representation_name,
};
use crate::stats::{type7_quantile, weighted_mean, weighted_quantile, weights};
use hashbrown::HashMap;
use obs_open_03a::PackedOutcome;
use std::collections::{BTreeMap, BTreeSet};

pub struct AnatomyProducts {
    pub durations: Vec<CandidateDuration>,
    pub session_candidate_counts: Vec<usize>,
    pub persistence: Vec<PersistenceRow>,
    pub multiplicity_raw: Vec<MultiplicityRow>,
    pub multiplicity_quartiles: Vec<MultiplicityRow>,
    pub range_surfaces: Vec<SurfaceRow>,
    pub path_variation_surfaces: Vec<SurfaceRow>,
    pub widths: Vec<WidthRow>,
    pub width_reconstructed: usize,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MultiplicityRow {
    pub stratum_kind: String,
    pub stratum_value: String,
    pub retrospective_context: bool,
    pub causal_at_candidate_birth: bool,
    pub age_minutes: u16,
    pub sampling_unit: String,
    pub sessions_in_stratum: usize,
    pub candidate_anchors_in_stratum: usize,
    pub at_risk_anchors: usize,
    pub contributing_sessions: usize,
    pub observed_supersessions: usize,
    pub session_terminated: usize,
    pub source_path_incomplete: usize,
    pub survival: f64,
    pub conditional_hazard: f64,
}

pub fn build_anatomy(records: &[PackedOutcome]) -> Result<AnatomyProducts, String> {
    let durations = candidate_durations(records)?;
    let mut session_candidate_counts = vec![0usize; SESSION_COUNT];
    for duration in &durations {
        session_candidate_counts[duration.session_index as usize] += 1;
    }
    if session_candidate_counts.iter().any(|&count| count == 0) {
        return Err("SESSION_WITHOUT_CANDIDATE_DURATION".into());
    }
    let persistence = persistence_rows(&durations, &session_candidate_counts);
    let multiplicity_raw = multiplicity_raw_rows(&durations, &session_candidate_counts);
    let multiplicity_quartiles = multiplicity_quartile_rows(&durations, &session_candidate_counts)?;
    let (range_surfaces, path_variation_surfaces) = surface_rows(records);
    let (widths, width_reconstructed) = width_rows(records)?;
    Ok(AnatomyProducts {
        durations,
        session_candidate_counts,
        persistence,
        multiplicity_raw,
        multiplicity_quartiles,
        range_surfaces,
        path_variation_surfaces,
        widths,
        width_reconstructed,
    })
}

fn candidate_durations(records: &[PackedOutcome]) -> Result<Vec<CandidateDuration>, String> {
    let mut out = Vec::with_capacity(5_200);
    for record in records.iter().filter(|r| r.outcome_code == 8) {
        let endpoint_time = if let Some(value) = record.value() {
            value.round().clamp(0.0, f64::from(MAX_AGE_MINUTES)) as u16
        } else if let Some(value) = record.censor_minutes() {
            value.round().clamp(0.0, f64::from(MAX_AGE_MINUTES)) as u16
        } else {
            ((record.observed_until - record.anchor_known_at).max(0) / 60)
                .clamp(0, i64::from(MAX_AGE_MINUTES)) as u16
        };
        let (event_time, endpoint) = match (record.outcome_state, record.censor_reason) {
            (1, _) => (Some(endpoint_time), Endpoint::Supersession),
            (2, 1) => (None, Endpoint::SessionTermination),
            (2, _) => (None, Endpoint::RightCensor),
            (3, _) => (None, Endpoint::SessionTermination),
            (4, _) => (None, Endpoint::SourcePathIncomplete),
            (5, _) => (None, Endpoint::NotEvaluable),
            other => return Err(format!("UNKNOWN_DURATION_STATE:{other:?}")),
        };
        out.push(CandidateDuration {
            session_index: record.session_index,
            event_time,
            endpoint_time,
            endpoint,
        });
    }
    if out.len() != 5_137 {
        return Err(format!("CANDIDATE_DURATION_COUNT_DRIFT:{}", out.len()));
    }
    Ok(out)
}

fn persistence_rows(durations: &[CandidateDuration], counts: &[usize]) -> Vec<PersistenceRow> {
    let sessions: BTreeSet<_> = durations.iter().map(|d| d.session_index).collect();
    let subset: Vec<_> = sessions.into_iter().collect();
    persistence_for_subset(durations, counts, &subset)
}

fn persistence_for_subset(
    durations: &[CandidateDuration],
    counts: &[usize],
    sessions: &[u32],
) -> Vec<PersistenceRow> {
    let selected: Vec<_> = durations
        .iter()
        .copied()
        .filter(|d| sessions.binary_search(&d.session_index).is_ok())
        .collect();
    let session_set: BTreeSet<_> = sessions.iter().copied().collect();
    let anchor_weight = 1.0 / selected.len() as f64;
    let session_mass = 1.0 / session_set.len() as f64;
    let mut out = Vec::with_capacity((usize::from(MAX_AGE_MINUTES) + 1) * 2);
    for sampling in ["ANCHOR_WEIGHTED", "SESSION_WEIGHTED"] {
        let weight = |d: &CandidateDuration| {
            if sampling == "ANCHOR_WEIGHTED" {
                anchor_weight
            } else {
                session_mass / counts[d.session_index as usize] as f64
            }
        };
        let mut survival = 1.0;
        for age in 0..=MAX_AGE_MINUTES {
            let at_risk: Vec<_> = selected.iter().filter(|d| d.endpoint_time >= age).collect();
            let events: Vec<_> = selected
                .iter()
                .filter(|d| d.event_time == Some(age))
                .collect();
            let endpoint_count = |endpoint| {
                selected
                    .iter()
                    .filter(|d| d.endpoint == endpoint && d.endpoint_time == age)
                    .count()
            };
            let at_risk_mass: f64 = at_risk.iter().map(|d| weight(d)).sum();
            let event_mass: f64 = events.iter().map(|d| weight(d)).sum();
            let censor_mass: f64 = selected
                .iter()
                .filter(|d| d.endpoint != Endpoint::Supersession && d.endpoint_time == age)
                .map(weight)
                .sum();
            let hazard = if at_risk_mass > 0.0 {
                event_mass / at_risk_mass
            } else {
                0.0
            };
            survival *= 1.0 - hazard;
            out.push(PersistenceRow {
                age_minutes: age,
                sampling_unit: sampling.into(),
                at_risk_anchors: at_risk.len(),
                contributing_sessions: at_risk
                    .iter()
                    .map(|d| d.session_index)
                    .collect::<BTreeSet<_>>()
                    .len(),
                observed_supersessions: events.len(),
                right_censored: endpoint_count(Endpoint::RightCensor),
                session_terminated: endpoint_count(Endpoint::SessionTermination),
                source_path_incomplete: endpoint_count(Endpoint::SourcePathIncomplete),
                not_evaluable: endpoint_count(Endpoint::NotEvaluable),
                at_risk_mass,
                event_mass,
                censor_mass,
                survival,
                conditional_hazard: hazard,
            });
        }
    }
    out
}

fn multiplicity_raw_rows(
    durations: &[CandidateDuration],
    counts: &[usize],
) -> Vec<MultiplicityRow> {
    let groups: BTreeMap<usize, Vec<u32>> =
        counts
            .iter()
            .enumerate()
            .fold(BTreeMap::new(), |mut map, (session, &count)| {
                map.entry(count).or_default().push(session as u32);
                map
            });
    let mut out = Vec::new();
    for (count, sessions) in groups {
        append_multiplicity_rows(
            &mut out,
            "EXACT_FINAL_SESSION_MULTIPLICITY",
            &count.to_string(),
            durations,
            counts,
            &sessions,
        );
    }
    out
}

fn multiplicity_quartile_rows(
    durations: &[CandidateDuration],
    counts: &[usize],
) -> Result<Vec<MultiplicityRow>, String> {
    let q25 = type7_quantile(counts, 0.25).ok_or("Q25_UNAVAILABLE")?;
    let q50 = type7_quantile(counts, 0.50).ok_or("Q50_UNAVAILABLE")?;
    let q75 = type7_quantile(counts, 0.75).ok_or("Q75_UNAVAILABLE")?;
    let mut groups = vec![Vec::new(), Vec::new(), Vec::new(), Vec::new()];
    for (session, &count) in counts.iter().enumerate() {
        let group = if count as f64 <= q25.floor() {
            0
        } else if count as f64 <= q50.floor() {
            1
        } else if count as f64 <= q75.floor() {
            2
        } else {
            3
        };
        groups[group].push(session as u32);
    }
    let labels = [
        format!("Q1_LE_{}", q25.floor()),
        format!("Q2_{}_TO_{}", q25.floor() as usize + 1, q50.floor()),
        format!("Q3_{}_TO_{}", q50.floor() as usize + 1, q75.floor()),
        format!("Q4_GE_{}", q75.floor() as usize + 1),
    ];
    let mut out = Vec::new();
    for (sessions, label) in groups.iter().zip(labels) {
        append_multiplicity_rows(
            &mut out,
            "TYPE7_QUARTILE_FINAL_SESSION_MULTIPLICITY",
            &label,
            durations,
            counts,
            sessions,
        );
    }
    Ok(out)
}

fn append_multiplicity_rows(
    out: &mut Vec<MultiplicityRow>,
    kind: &str,
    value: &str,
    durations: &[CandidateDuration],
    counts: &[usize],
    sessions: &[u32],
) {
    let rows = persistence_for_subset(durations, counts, sessions);
    let anchors: usize = sessions.iter().map(|&s| counts[s as usize]).sum();
    out.extend(rows.into_iter().map(|row| MultiplicityRow {
        stratum_kind: kind.into(),
        stratum_value: value.into(),
        retrospective_context: true,
        causal_at_candidate_birth: false,
        age_minutes: row.age_minutes,
        sampling_unit: row.sampling_unit,
        sessions_in_stratum: sessions.len(),
        candidate_anchors_in_stratum: anchors,
        at_risk_anchors: row.at_risk_anchors,
        contributing_sessions: row.contributing_sessions,
        observed_supersessions: row.observed_supersessions,
        session_terminated: row.session_terminated,
        source_path_incomplete: row.source_path_incomplete,
        survival: row.survival,
        conditional_hazard: row.conditional_hazard,
    }));
}

fn surface_rows(records: &[PackedOutcome]) -> (Vec<SurfaceRow>, Vec<SurfaceRow>) {
    let mut groups: BTreeMap<SurfaceKey, SurfaceCell> = BTreeMap::new();
    for record in records
        .iter()
        .filter(|r| matches!(r.outcome_code, 101 | 104 | 4))
    {
        let key = SurfaceKey {
            outcome: record.outcome_code,
            representation: record.representation,
            k: record.k,
            horizon: record.horizon_minutes,
        };
        let cell = groups.entry(key).or_insert_with(|| SurfaceCell {
            key,
            values: Vec::new(),
            observed_complete: 0,
            right_censored: 0,
            session_terminated: 0,
            source_path_incomplete: 0,
            not_evaluable: 0,
        });
        match record.outcome_state {
            1 => {
                cell.observed_complete += 1;
                if let Some(value) = record.value() {
                    cell.values.push((value, record.session_index));
                }
            }
            2 => cell.right_censored += 1,
            3 => cell.session_terminated += 1,
            4 => cell.source_path_incomplete += 1,
            5 => cell.not_evaluable += 1,
            _ => cell.not_evaluable += 1,
        }
    }
    let mut range = Vec::new();
    let mut variation = Vec::new();
    for cell in groups.into_values() {
        for sampling in ["ANCHOR_WEIGHTED", "SESSION_WEIGHTED"] {
            let row = summarize_surface(&cell, sampling);
            if cell.key.outcome == 4 {
                variation.push(row);
            } else {
                range.push(row);
            }
        }
    }
    (range, variation)
}

fn summarize_surface(cell: &SurfaceCell, sampling: &str) -> SurfaceRow {
    let sample_weights = weights(&cell.values, sampling);
    SurfaceRow {
        outcome_code: cell.key.outcome,
        representation: representation_name(cell.key.representation).into(),
        k: cell.key.k,
        freeze_minute_after_open: cell.key.k,
        horizon_minutes: cell.key.horizon,
        evaluation_minute_after_open: u16::from(cell.key.k) + cell.key.horizon,
        sampling_unit: sampling.into(),
        observed_complete: cell.observed_complete,
        contributing_sessions: cell
            .values
            .iter()
            .map(|x| x.1)
            .collect::<BTreeSet<_>>()
            .len(),
        right_censored: cell.right_censored,
        session_terminated: cell.session_terminated,
        source_path_incomplete: cell.source_path_incomplete,
        not_evaluable: cell.not_evaluable,
        q10: weighted_quantile(&cell.values, &sample_weights, 0.10),
        q25: weighted_quantile(&cell.values, &sample_weights, 0.25),
        q50: weighted_quantile(&cell.values, &sample_weights, 0.50),
        q75: weighted_quantile(&cell.values, &sample_weights, 0.75),
        q90: weighted_quantile(&cell.values, &sample_weights, 0.90),
        mean: weighted_mean(&cell.values, &sample_weights),
    }
}

fn width_rows(records: &[PackedOutcome]) -> Result<(Vec<WidthRow>, usize), String> {
    let mut raw = HashMap::<(u32, u16, u16), f64>::with_capacity(180_000);
    let mut widths = HashMap::<u32, (u8, u32, f64)>::with_capacity(4_700);
    for record in records
        .iter()
        .filter(|r| matches!(r.outcome_code, 101..=104) && r.outcome_state == 1)
    {
        let Some(value) = record.value() else {
            continue;
        };
        let key = (
            record.anchor_index,
            record.outcome_code,
            record.horizon_minutes,
        );
        if record.representation == 1 {
            raw.insert(key, value);
        } else if record.representation == 2 && value.abs() > 1e-12 {
            if let Some(raw_value) = raw.get(&key) {
                let width = 2.0 * raw_value / value;
                if width.is_finite() && width > 0.0 {
                    if let Some((_, _, prior)) = widths.get(&record.anchor_index) {
                        if (prior - width).abs() > 1e-7 * prior.abs().max(1.0) {
                            return Err(format!(
                                "WIDTH_RECONSTRUCTION_CONFLICT:{}:{prior}:{width}",
                                record.anchor_index
                            ));
                        }
                    } else {
                        widths.insert(record.anchor_index, (record.k, record.session_index, width));
                    }
                }
            }
        }
    }
    let mut rows = Vec::with_capacity(30);
    for k in 1..=30u8 {
        let mut values: Vec<_> = widths
            .values()
            .filter(|(range_k, _, _)| *range_k == k)
            .map(|(_, session, width)| (*width, *session))
            .collect();
        values.sort_by_key(|(_, session)| *session);
        let sample_weights = weights(&values, "SESSION_WEIGHTED");
        rows.push(WidthRow {
            k,
            reconstructed_ranges: values.len(),
            contributing_sessions: values.iter().map(|x| x.1).collect::<BTreeSet<_>>().len(),
            reconstruction_not_evaluable: SESSION_COUNT - values.len(),
            q10: weighted_quantile(&values, &sample_weights, 0.10),
            q25: weighted_quantile(&values, &sample_weights, 0.25),
            q50: weighted_quantile(&values, &sample_weights, 0.50),
            q75: weighted_quantile(&values, &sample_weights, 0.75),
            q90: weighted_quantile(&values, &sample_weights, 0.90),
            mean: weighted_mean(&values, &sample_weights),
            unit: "SOURCE_PRICE_UNIT".into(),
            derivation:
                "2 * RAW_RANGE_RELATIVE_VALUE / RANGE_Z_SIBLING_VALUE; exact sibling pairs only"
                    .into(),
        });
    }
    Ok((rows, widths.len()))
}
