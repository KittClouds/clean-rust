use crate::authority::MembershipRow;
use hashbrown::HashMap;
use serde::Serialize;
use wide::f64x4;

#[derive(Debug, Clone, Serialize)]
pub struct TapeRow {
    pub session_id: String,
    pub civil_date: String,
    pub source_clock_offset_regime: i32,
    pub parent_discovery_session_ordinal: usize,
    pub d_b_selected_ordinal: usize,
    pub previous_d_b_parent_ordinal_gap: Option<usize>,
    pub previous_d_b_calendar_day_gap: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GapSummary {
    pub count: usize,
    pub minimum: f64,
    pub median: f64,
    pub mean: f64,
    pub maximum: f64,
    pub frequency: Vec<(i64, usize)>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Anatomy {
    pub tape: Vec<TapeRow>,
    pub parent_gaps: GapSummary,
    pub calendar_gaps: GapSummary,
    pub consecutive_session_pairs: usize,
    pub skipped_session_pairs: usize,
    pub offset_transition_counts: Vec<(String, usize)>,
    pub d_a_validation_blocks: Vec<serde_json::Value>,
}

pub fn construct(rows: &[MembershipRow]) -> Result<Anatomy, String> {
    let mut tape = Vec::with_capacity(103);
    let mut last_parent = None;
    let mut last_day = None;
    for (parent0, row) in rows
        .iter()
        .enumerate()
        .filter(|(_, r)| r.partition == "REPRESENTATION_DB")
    {
        let parent = parent0 + 1;
        let day = civil_day(&row.civil_date)?;
        tape.push(TapeRow {
            session_id: row.session_id.clone(),
            civil_date: row.civil_date.clone(),
            source_clock_offset_regime: row.offset,
            parent_discovery_session_ordinal: parent,
            d_b_selected_ordinal: tape.len() + 1,
            previous_d_b_parent_ordinal_gap: last_parent.map(|x| parent - x),
            previous_d_b_calendar_day_gap: last_day.map(|x| day - x),
        });
        last_parent = Some(parent);
        last_day = Some(day);
    }
    let parent = tape
        .iter()
        .filter_map(|r| r.previous_d_b_parent_ordinal_gap.map(|x| x as i64))
        .collect::<Vec<_>>();
    let calendar = tape
        .iter()
        .filter_map(|r| r.previous_d_b_calendar_day_gap)
        .collect::<Vec<_>>();
    let mut transitions = HashMap::<String, usize>::new();
    for pair in tape.windows(2) {
        *transitions
            .entry(format!(
                "{}->{}",
                pair[0].source_clock_offset_regime, pair[1].source_clock_offset_regime
            ))
            .or_default() += 1;
    }
    let mut offset_transition_counts = transitions.into_iter().collect::<Vec<_>>();
    offset_transition_counts.sort_by(|a, b| a.0.cmp(&b.0));
    let d_a = rows
        .iter()
        .enumerate()
        .filter(|(_, r)| r.partition == "ATLAS_DA")
        .collect::<Vec<_>>();
    let mut blocks = Vec::new();
    for (id, lo, hi) in [(1, 31, 61), (2, 62, 92), (3, 93, 123), (4, 124, 154)] {
        let slice = &d_a[lo - 1..hi];
        let parent_gaps = slice
            .windows(2)
            .map(|w| (w[1].0 - w[0].0) as i64)
            .collect::<Vec<_>>();
        let cal_gaps = slice
            .windows(2)
            .map(|w| {
                civil_day(&w[1].1.civil_date).unwrap() - civil_day(&w[0].1.civil_date).unwrap()
            })
            .collect::<Vec<_>>();
        blocks.push(serde_json::json!({"block_id":id,"d_a_ordinal_start":lo,"d_a_ordinal_end":hi,"membership_sessions":slice.len(),"parent_session_gaps":summarize(&parent_gaps),"calendar_day_gaps":summarize(&cal_gaps),"score_values_read":0}));
    }
    Ok(Anatomy {
        consecutive_session_pairs: parent.iter().filter(|&&x| x == 1).count(),
        skipped_session_pairs: parent.iter().filter(|&&x| x > 1).count(),
        parent_gaps: summarize(&parent),
        calendar_gaps: summarize(&calendar),
        tape,
        offset_transition_counts,
        d_a_validation_blocks: blocks,
    })
}

fn summarize(values: &[i64]) -> GapSummary {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let n = sorted.len();
    let median = if n % 2 == 1 {
        sorted[n / 2] as f64
    } else {
        (sorted[n / 2 - 1] + sorted[n / 2]) as f64 / 2.0
    };
    let mut chunks = values.chunks_exact(4);
    let mut acc = f64x4::splat(0.0);
    for c in &mut chunks {
        acc += f64x4::new([c[0] as f64, c[1] as f64, c[2] as f64, c[3] as f64]);
    }
    let sum = acc.to_array().iter().sum::<f64>()
        + chunks.remainder().iter().map(|&x| x as f64).sum::<f64>();
    let mut freq = HashMap::<i64, usize>::new();
    for &v in values {
        *freq.entry(v).or_default() += 1;
    }
    let mut frequency = freq.into_iter().collect::<Vec<_>>();
    frequency.sort_unstable_by_key(|x| x.0);
    GapSummary {
        count: n,
        minimum: sorted[0] as f64,
        median,
        mean: sum / n as f64,
        maximum: sorted[n - 1] as f64,
        frequency,
    }
}

fn civil_day(s: &str) -> Result<i64, String> {
    let mut p = s.split('-');
    let y = p.next().ok_or("DATE")?.parse::<i64>().map_err(|_| "DATE")?;
    let m = p.next().ok_or("DATE")?.parse::<i64>().map_err(|_| "DATE")?;
    let d = p.next().ok_or("DATE")?.parse::<i64>().map_err(|_| "DATE")?;
    let y = y - if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = m + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Ok(era * 146097 + doe)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dates_are_ordered() {
        assert_eq!(
            civil_day("2024-01-02").unwrap() + 2,
            civil_day("2024-01-04").unwrap()
        );
    }
}
