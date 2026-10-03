use crate::model::{
    AtlasSession, CensorReason, OutcomeState, PackedOutcome, outcome_name, representation_name,
};
use hashbrown::HashMap;
use obs_open_03ap::{RANGE_Z_THRESHOLDS, RAW_PRICE_THRESHOLDS};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq, PartialOrd, Ord)]
struct CellKey {
    outcome: u16,
    representation: u8,
    k: u8,
    horizon: u16,
    index: u8,
}

#[derive(Debug, Clone)]
struct ValueEntry {
    value: f64,
    session: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct SummaryRow {
    pub cell_id: String,
    pub outcome: String,
    pub representation: String,
    pub k: u8,
    pub horizon_minutes: u16,
    pub index: u8,
    pub index_label: String,
    pub stratum_kind: String,
    pub stratum_value: String,
    pub sampling_unit: String,
    pub anchor_rows: usize,
    pub contributing_sessions: usize,
    pub observed_complete: usize,
    pub right_censored: usize,
    pub session_terminated: usize,
    pub source_path_incomplete: usize,
    pub not_evaluable: usize,
    pub minimum: Option<f64>,
    pub q01: Option<f64>,
    pub q05: Option<f64>,
    pub q10: Option<f64>,
    pub q25: Option<f64>,
    pub q50: Option<f64>,
    pub q75: Option<f64>,
    pub q90: Option<f64>,
    pub q95: Option<f64>,
    pub q99: Option<f64>,
    pub maximum: Option<f64>,
    pub mean: Option<f64>,
    pub variance: Option<f64>,
    pub median_absolute_deviation: Option<f64>,
    pub ledger_filter: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct AggregateReceipt {
    pub schema: String,
    pub sampling_units: Vec<String>,
    pub distribution_rows: usize,
    pub ecdf_query_rows: usize,
    pub tail_mass_rows: usize,
    pub survival_hazard_rows: usize,
    pub multiplicity_rows: usize,
    pub visualization_projection_rows: usize,
    pub formal_tests: usize,
    pub status: String,
}

pub fn write_aggregates(
    out: &Path,
    records: &[PackedOutcome],
    sessions: &[AtlasSession],
) -> Result<(AggregateReceipt, Vec<SummaryRow>), Box<dyn std::error::Error>> {
    let atlas = out.join("atlas");
    std::fs::create_dir_all(&atlas)?;
    let mut distribution = BufWriter::new(File::create(atlas.join("distribution_summary.tsv"))?);
    let mut ecdf = BufWriter::new(File::create(atlas.join("ecdf_query_index.tsv"))?);
    let mut tails = BufWriter::new(File::create(atlas.join("tail_mass.tsv"))?);
    let mut survival = BufWriter::new(File::create(atlas.join("survival_hazard.tsv"))?);
    write_summary_header(&mut distribution)?;
    writeln!(
        ecdf,
        "cell_id\tsampling_unit\tstatus\tsource_ledger\tfilter\tordering\tweighting"
    )?;
    writeln!(
        tails,
        "cell_id\tsampling_unit\tthreshold\tlower_mass\tupper_mass\tvalue_count\tcontributing_sessions"
    )?;
    writeln!(
        survival,
        "cell_id\toutcome\trepresentation\tk\tindex\tstratum_kind\tstratum_value\tsampling_unit\ttime_minutes\tat_risk_mass\tevent_mass\tcensor_mass\tsurvival\tdescriptive_hazard"
    )?;

    let strata = strata(sessions);
    let mut all_summaries = Vec::new();
    let mut ecdf_rows = 0;
    let mut tail_rows = 0;
    let mut survival_rows = 0;
    for (kind, value) in strata {
        let selected = select_records(records, sessions, &kind, &value);
        let mut groups: HashMap<CellKey, Vec<&PackedOutcome>> = HashMap::new();
        for record in selected {
            groups.entry(cell_key(record)).or_default().push(record);
        }
        let mut ordered: Vec<_> = groups.into_iter().collect();
        ordered.sort_unstable_by_key(|(key, _)| *key);
        for (key, group) in ordered {
            for sampling in ["ANCHOR_WEIGHTED", "SESSION_WEIGHTED"] {
                let summary = summarize(key, &kind, &value, sampling, &group);
                write_summary_row(&mut distribution, &summary)?;
                writeln!(
                    ecdf,
                    "{}\t{}\tLAZY_RECONSTRUCTIBLE\tatlas/outcome_ledger.bin\t{}\tVALUE_ASC_SESSION_ASC\t{}",
                    summary.cell_id,
                    sampling,
                    summary.ledger_filter,
                    if sampling == "ANCHOR_WEIGHTED" {
                        "EQUAL_ANCHOR_MASS"
                    } else {
                        "EQUAL_SESSION_MASS_THEN_EQUAL_ELIGIBLE_ANCHOR_MASS_WITHIN_SESSION"
                    }
                )?;
                ecdf_rows += 1;
                tail_rows += write_tails(&mut tails, &summary, sampling, &group)?;
                if is_event(key.outcome) {
                    survival_rows += write_survival(
                        &mut survival,
                        &summary.cell_id,
                        key,
                        &kind,
                        &value,
                        sampling,
                        &group,
                    )?;
                }
                all_summaries.push(summary);
            }
        }
    }
    distribution.flush()?;
    ecdf.flush()?;
    tails.flush()?;
    survival.flush()?;
    let multiplicity_rows =
        write_multiplicity(&atlas.join("sampling_unit_multiplicity.tsv"), sessions)?;
    write_censor_census(&atlas.join("evaluability_census.tsv"), records)?;
    let projection: Vec<_> = all_summaries
        .iter()
        .filter(|row| {
            row.stratum_kind == "AGGREGATE"
                && matches!(
                    row.outcome.as_str(),
                    "CANDIDATE_MAX_PARALLEL_DISPLACEMENT_RAW"
                        | "CANDIDATE_MAX_ANTIPARALLEL_DISPLACEMENT_RAW"
                        | "CANDIDATE_REALIZED_CLOSE_VARIATION_RAW"
                        | "CANDIDATE_SURVIVAL_AT_HORIZON"
                        | "RANGE_TERMINAL_CLOSE"
                        | "RANGE_REALIZED_CLOSE_VARIATION"
                )
        })
        .cloned()
        .collect();
    write_json(
        &atlas.join("visualization_projection.json"),
        &serde_json::json!({
            "schema":"OBS_OPEN_03A_VISUALIZATION_PROJECTION_V1",
            "authority":"DETERMINISTIC_PROJECTION_DESCRIPTIVE_ONLY",
            "rows":projection
        }),
    )?;
    write_json(
        &atlas.join("ecdf_query_contract.json"),
        &serde_json::json!({
            "schema":"OBS_OPEN_03A_ECDF_QUERY_CONTRACT_V1",
            "source":"atlas/outcome_ledger.bin",
            "index":"atlas/ecdf_query_index.tsv",
            "order":"VALUE_ASC_THEN_SESSION_ASC_THEN_ANCHOR_ASC",
            "anchor_weight":"1 / eligible_anchor_count",
            "session_weight":"1 / contributing_session_count / eligible_anchor_count_within_session",
            "typed_nonobservations":"EXCLUDED_FROM_VALUE_CDF_AND_RETAINED_IN_EVALUABILITY_CENSUS",
            "status":"LAZY_EXACT_RECONSTRUCTIBLE"
        }),
    )?;
    Ok((
        AggregateReceipt {
            schema: "OBS_OPEN_03A_AGGREGATE_RECEIPT_V1".into(),
            sampling_units: vec!["ANCHOR_WEIGHTED".into(), "SESSION_WEIGHTED".into()],
            distribution_rows: all_summaries.len(),
            ecdf_query_rows: ecdf_rows,
            tail_mass_rows: tail_rows,
            survival_hazard_rows: survival_rows,
            multiplicity_rows,
            visualization_projection_rows: projection.len(),
            formal_tests: 0,
            status: "PASS".into(),
        },
        all_summaries,
    ))
}

fn strata(sessions: &[AtlasSession]) -> Vec<(String, String)> {
    let mut out = vec![("AGGREGATE".into(), "ALL".into())];
    out.extend([
        ("CANDIDATE_SIDE".into(), "UPPER".into()),
        ("CANDIDATE_SIDE".into(), "LOWER".into()),
        ("TERMINAL_STATUS".into(), "SUPERSEDED".into()),
        ("TERMINAL_STATUS".into(), "TERMINAL_SURVIVOR".into()),
        ("TERMINAL_STATUS".into(), "SOURCE_PATH_INCOMPLETE".into()),
    ]);
    let months: BTreeSet<_> = sessions.iter().map(|s| s.month.clone()).collect();
    out.extend(
        months
            .into_iter()
            .map(|month| ("CALENDAR_MONTH".into(), month)),
    );
    out.extend([
        ("SERVER_OFFSET".into(), "120".into()),
        ("SERVER_OFFSET".into(), "180".into()),
    ]);
    out
}

fn select_records<'a>(
    records: &'a [PackedOutcome],
    sessions: &[AtlasSession],
    kind: &str,
    value: &str,
) -> Vec<&'a PackedOutcome> {
    records
        .iter()
        .filter(|record| match kind {
            "AGGREGATE" => true,
            "CANDIDATE_SIDE" => {
                record.anchor_kind == 1
                    && ((value == "UPPER" && record.side == 1)
                        || (value == "LOWER" && record.side == 2))
            }
            "TERMINAL_STATUS" => {
                record.anchor_kind == 1
                    && ((value == "SUPERSEDED" && record.terminal_class == 1)
                        || (value == "TERMINAL_SURVIVOR" && record.terminal_class == 2)
                        || (value == "SOURCE_PATH_INCOMPLETE" && record.terminal_class == 3))
            }
            "CALENDAR_MONTH" => sessions[record.session_index as usize].month == value,
            "SERVER_OFFSET" => {
                sessions[record.session_index as usize]
                    .spec
                    .server_offset_minutes
                    .to_string()
                    == value
            }
            _ => false,
        })
        .collect()
}

fn cell_key(record: &PackedOutcome) -> CellKey {
    CellKey {
        outcome: record.outcome_code,
        representation: record.representation,
        k: record.k,
        horizon: record.horizon_minutes,
        index: record.threshold_index,
    }
}

fn summarize(
    key: CellKey,
    stratum_kind: &str,
    stratum_value: &str,
    sampling: &str,
    group: &[&PackedOutcome],
) -> SummaryRow {
    let mut values: Vec<_> = group
        .iter()
        .filter_map(|record| {
            record.value().map(|value| ValueEntry {
                value,
                session: record.session_index,
            })
        })
        .collect();
    values.sort_by(|a, b| {
        a.value
            .total_cmp(&b.value)
            .then_with(|| a.session.cmp(&b.session))
    });
    let sample_weights = weights(&values, sampling);
    let observed_sessions: BTreeSet<_> = values.iter().map(|entry| entry.session).collect();
    let quantile = |probability| weighted_quantile(&values, &sample_weights, probability);
    let mean = weighted_mean(&values, &sample_weights);
    let variance = mean.map(|mean| {
        values
            .iter()
            .zip(&sample_weights)
            .map(|(entry, weight)| weight * (entry.value - mean).powi(2))
            .sum()
    });
    let median = quantile(0.5);
    let mad = median.and_then(|median| {
        let mut deviations: Vec<_> = values
            .iter()
            .map(|entry| ValueEntry {
                value: (entry.value - median).abs(),
                session: entry.session,
            })
            .collect();
        deviations.sort_by(|a, b| a.value.total_cmp(&b.value));
        weighted_quantile(&deviations, &weights(&deviations, sampling), 0.5)
    });
    let state_count = |state: OutcomeState| {
        group
            .iter()
            .filter(|record| record.outcome_state == state as u8)
            .count()
    };
    let filter = format!(
        "outcome_code={};representation={};k={};horizon={};index={};stratum_kind={};stratum_value={}",
        key.outcome, key.representation, key.k, key.horizon, key.index, stratum_kind, stratum_value
    );
    SummaryRow {
        cell_id: cell_id(&filter, sampling),
        outcome: outcome_name(key.outcome).into(),
        representation: representation_name(key.representation).into(),
        k: key.k,
        horizon_minutes: key.horizon,
        index: key.index,
        index_label: index_label(key),
        stratum_kind: stratum_kind.into(),
        stratum_value: stratum_value.into(),
        sampling_unit: sampling.into(),
        anchor_rows: group.len(),
        contributing_sessions: observed_sessions.len(),
        observed_complete: state_count(OutcomeState::ObservedComplete),
        right_censored: state_count(OutcomeState::RightCensored),
        session_terminated: state_count(OutcomeState::SessionTerminated),
        source_path_incomplete: state_count(OutcomeState::SourcePathIncomplete),
        not_evaluable: state_count(OutcomeState::NotEvaluable),
        minimum: values.first().map(|entry| entry.value),
        q01: quantile(0.01),
        q05: quantile(0.05),
        q10: quantile(0.10),
        q25: quantile(0.25),
        q50: median,
        q75: quantile(0.75),
        q90: quantile(0.90),
        q95: quantile(0.95),
        q99: quantile(0.99),
        maximum: values.last().map(|entry| entry.value),
        mean,
        variance,
        median_absolute_deviation: mad,
        ledger_filter: filter,
    }
}

fn weights(values: &[ValueEntry], sampling: &str) -> Vec<f64> {
    if values.is_empty() {
        return Vec::new();
    }
    if sampling == "ANCHOR_WEIGHTED" {
        return vec![1.0 / values.len() as f64; values.len()];
    }
    let mut counts = BTreeMap::<u32, usize>::new();
    for value in values {
        *counts.entry(value.session).or_default() += 1;
    }
    let session_mass = 1.0 / counts.len() as f64;
    values
        .iter()
        .map(|value| session_mass / counts[&value.session] as f64)
        .collect()
}

fn weighted_quantile(values: &[ValueEntry], weights: &[f64], probability: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut cumulative = 0.0;
    for (value, weight) in values.iter().zip(weights) {
        cumulative += weight;
        if cumulative + f64::EPSILON >= probability {
            return Some(value.value);
        }
    }
    values.last().map(|value| value.value)
}

fn weighted_mean(values: &[ValueEntry], weights: &[f64]) -> Option<f64> {
    (!values.is_empty()).then(|| {
        values
            .iter()
            .zip(weights)
            .map(|(entry, weight)| entry.value * weight)
            .sum()
    })
}

fn write_tails(
    writer: &mut BufWriter<File>,
    summary: &SummaryRow,
    sampling: &str,
    group: &[&PackedOutcome],
) -> Result<usize, Box<dyn std::error::Error>> {
    let thresholds: &[f64] = match summary.representation.as_str() {
        "RAW_PRICE" => &RAW_PRICE_THRESHOLDS,
        "RANGE_Z" => &RANGE_Z_THRESHOLDS,
        _ => return Ok(0),
    };
    let values: Vec<_> = group
        .iter()
        .filter_map(|record| {
            record.value().map(|value| ValueEntry {
                value,
                session: record.session_index,
            })
        })
        .collect();
    let weights = weights(&values, sampling);
    let sessions: BTreeSet<_> = values.iter().map(|value| value.session).collect();
    for threshold in thresholds {
        let lower: f64 = values
            .iter()
            .zip(&weights)
            .filter(|(value, _)| value.value <= -*threshold)
            .map(|(_, weight)| weight)
            .sum();
        let upper: f64 = values
            .iter()
            .zip(&weights)
            .filter(|(value, _)| value.value >= *threshold)
            .map(|(_, weight)| weight)
            .sum();
        writeln!(
            writer,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}",
            summary.cell_id,
            sampling,
            threshold,
            lower,
            upper,
            values.len(),
            sessions.len()
        )?;
    }
    Ok(thresholds.len())
}

#[allow(clippy::too_many_arguments)]
fn write_survival(
    writer: &mut BufWriter<File>,
    cell_id: &str,
    key: CellKey,
    stratum_kind: &str,
    stratum_value: &str,
    sampling: &str,
    group: &[&PackedOutcome],
) -> Result<usize, Box<dyn std::error::Error>> {
    let eligible: Vec<_> = group
        .iter()
        .filter_map(|record| {
            let time = record.censor_minutes()?;
            let event = record.outcome_state == OutcomeState::ObservedComplete as u8;
            let censored = record.outcome_state == OutcomeState::RightCensored as u8;
            (event || censored).then_some((time, event, record.session_index))
        })
        .collect();
    if eligible.is_empty() {
        return Ok(0);
    }
    let value_entries: Vec<_> = eligible
        .iter()
        .map(|(time, _, session)| ValueEntry {
            value: *time,
            session: *session,
        })
        .collect();
    let weights = weights(&value_entries, sampling);
    let mut times: Vec<_> = eligible.iter().map(|row| row.0).collect();
    times.sort_by(f64::total_cmp);
    times.dedup_by(|a, b| a.total_cmp(b).is_eq());
    let mut survival_value = 1.0;
    let mut rows = 0;
    for time in times {
        let mut at_risk = 0.0;
        let mut events = 0.0;
        let mut censored = 0.0;
        for ((observed_time, event, _), weight) in eligible.iter().zip(&weights) {
            if *observed_time >= time {
                at_risk += weight;
            }
            if observed_time.total_cmp(&time).is_eq() {
                if *event {
                    events += weight;
                } else {
                    censored += weight;
                }
            }
        }
        let hazard = if at_risk > 0.0 { events / at_risk } else { 0.0 };
        survival_value *= 1.0 - hazard;
        writeln!(
            writer,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            cell_id,
            outcome_name(key.outcome),
            representation_name(key.representation),
            key.k,
            key.index,
            stratum_kind,
            stratum_value,
            sampling,
            time,
            at_risk,
            events,
            censored,
            survival_value,
            hazard
        )?;
        rows += 1;
    }
    Ok(rows)
}

fn write_multiplicity(
    path: &Path,
    sessions: &[AtlasSession],
) -> Result<usize, Box<dyn std::error::Error>> {
    let total_candidates: usize = sessions
        .iter()
        .map(|session| session.candidates.len())
        .sum();
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "session_id\tcandidate_anchors\tupper_anchors\tlower_anchors\tcomplete_path_candidate_anchors\trange_objects\tanchor_weight_per_candidate\tsession_weight_per_candidate\tanchor_weight_per_range_object_at_fixed_k\tsession_weight_per_range_object_at_fixed_k"
    )?;
    for session in sessions {
        let candidates = session.candidates.len();
        let upper = session
            .candidates
            .iter()
            .filter(|candidate| candidate.side == "UPPER")
            .count();
        let lower = candidates - upper;
        writeln!(
            writer,
            "{}\t{}\t{}\t{}\t{}\t30\t{}\t{}\t{}\t{}",
            session.spec.session_id,
            candidates,
            upper,
            lower,
            if session.path_complete { candidates } else { 0 },
            1.0 / total_candidates as f64,
            1.0 / sessions.len() as f64 / candidates.max(1) as f64,
            1.0 / (sessions.len() * 30) as f64,
            1.0 / sessions.len() as f64
        )?;
    }
    writer.flush()?;
    Ok(sessions.len())
}

fn write_censor_census(
    path: &Path,
    records: &[PackedOutcome],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut counts: BTreeMap<(CellKey, u8, u8), (usize, BTreeSet<u32>)> = BTreeMap::new();
    for record in records {
        let entry = counts
            .entry((cell_key(record), record.outcome_state, record.censor_reason))
            .or_default();
        entry.0 += 1;
        entry.1.insert(record.session_index);
    }
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "outcome\trepresentation\tk\thorizon_minutes\tindex\toutcome_state\tcensor_reason\tanchor_rows\tsessions"
    )?;
    for ((key, state, censor), (rows, sessions)) in counts {
        writeln!(
            writer,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            outcome_name(key.outcome),
            representation_name(key.representation),
            key.k,
            key.horizon,
            key.index,
            state_name(state),
            censor_name(censor),
            rows,
            sessions.len()
        )?;
    }
    writer.flush()?;
    Ok(())
}

fn write_summary_header(writer: &mut BufWriter<File>) -> std::io::Result<()> {
    writeln!(
        writer,
        "cell_id\toutcome\trepresentation\tk\thorizon_minutes\tindex\tindex_label\tstratum_kind\tstratum_value\tsampling_unit\tanchor_rows\tcontributing_sessions\tobserved_complete\tright_censored\tsession_terminated\tsource_path_incomplete\tnot_evaluable\tminimum\tq01\tq05\tq10\tq25\tq50\tq75\tq90\tq95\tq99\tmaximum\tmean\tvariance\tmedian_absolute_deviation\tledger_filter"
    )
}

fn write_summary_row(writer: &mut BufWriter<File>, row: &SummaryRow) -> std::io::Result<()> {
    let option = |value: Option<f64>| value.map(|v| v.to_string()).unwrap_or_default();
    writeln!(
        writer,
        "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
        row.cell_id,
        row.outcome,
        row.representation,
        row.k,
        row.horizon_minutes,
        row.index,
        row.index_label,
        row.stratum_kind,
        row.stratum_value,
        row.sampling_unit,
        row.anchor_rows,
        row.contributing_sessions,
        row.observed_complete,
        row.right_censored,
        row.session_terminated,
        row.source_path_incomplete,
        row.not_evaluable,
        option(row.minimum),
        option(row.q01),
        option(row.q05),
        option(row.q10),
        option(row.q25),
        option(row.q50),
        option(row.q75),
        option(row.q90),
        option(row.q95),
        option(row.q99),
        option(row.maximum),
        option(row.mean),
        option(row.variance),
        option(row.median_absolute_deviation),
        row.ledger_filter
    )
}

fn index_label(key: CellKey) -> String {
    match key.outcome {
        6 | 7 => RAW_PRICE_THRESHOLDS[key.index as usize].to_string(),
        106 | 107 => RANGE_Z_THRESHOLDS[key.index as usize].to_string(),
        108 => ["IN_ZONE", "ABOVE", "BELOW"][key.index as usize].into(),
        _ => "NOT_APPLICABLE".into(),
    }
}

fn cell_id(filter: &str, sampling: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(filter.as_bytes());
    hasher.update(b"|");
    hasher.update(sampling.as_bytes());
    format!("CELL_{}", &format!("{:x}", hasher.finalize())[..20])
}

fn is_event(code: u16) -> bool {
    matches!(code, 6 | 7 | 8 | 106 | 107)
}

fn state_name(state: u8) -> &'static str {
    match state {
        1 => "OBSERVED_COMPLETE",
        2 => "RIGHT_CENSORED",
        3 => "SESSION_TERMINATED",
        4 => "SOURCE_PATH_INCOMPLETE",
        5 => "NOT_EVALUABLE",
        _ => "UNKNOWN_STATE",
    }
}

fn censor_name(censor: u8) -> &'static str {
    match censor {
        x if x == CensorReason::None as u8 => "NONE",
        x if x == CensorReason::SessionTermination as u8 => "SESSION_TERMINATION",
        x if x == CensorReason::CandidateSupersession as u8 => "CANDIDATE_SUPERSESSION",
        x if x == CensorReason::SourcePathGap as u8 => "SOURCE_PATH_GAP",
        x if x == CensorReason::InvalidAnchor as u8 => "INVALID_ANCHOR",
        x if x == CensorReason::DegenerateRange as u8 => "DEGENERATE_RANGE",
        _ => "UNKNOWN_CENSOR",
    }
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    std::fs::write(path, bytes)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        AnchorKind, CensorReason, OutcomeCode, Representation, Side, TerminalClass,
    };

    fn record(session: u32, anchor: u32, value: f64) -> PackedOutcome {
        PackedOutcome::new(
            Some(value),
            None,
            10,
            Some(20),
            20,
            20,
            anchor,
            session,
            OutcomeCode::CandidateMaxParallelDisplacement,
            10,
            10,
            0,
            0,
            AnchorKind::Candidate,
            Side::Upper,
            Representation::RawPrice,
            OutcomeState::ObservedComplete,
            CensorReason::None,
            TerminalClass::Superseded,
        )
    }

    #[test]
    fn sampling_units_are_mathematically_distinct() {
        let records = [record(0, 0, 0.0), record(0, 1, 0.0), record(1, 2, 10.0)];
        let refs: Vec<_> = records.iter().collect();
        let key = cell_key(&records[0]);
        let anchor = summarize(key, "AGGREGATE", "ALL", "ANCHOR_WEIGHTED", &refs);
        let session = summarize(key, "AGGREGATE", "ALL", "SESSION_WEIGHTED", &refs);
        assert!((anchor.mean.expect("mean") - 10.0 / 3.0).abs() < 1e-12);
        assert!((session.mean.expect("mean") - 5.0).abs() < 1e-12);
        assert_ne!(anchor.mean, session.mean);
    }
}
