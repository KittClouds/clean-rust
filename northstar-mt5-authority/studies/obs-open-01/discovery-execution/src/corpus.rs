use crate::AnyResult;
use crate::authority::LoadedAuthority;
use bytemuck::{Pod, Zeroable};
use obs_open_meas02::{
    Bar, Candidate, RangeObject, SessionSpec, build_candidates_and_tape, build_range_relations,
    build_ranges,
};
use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Debug)]
pub struct SessionData {
    pub spec: SessionSpec,
    pub bars: Vec<Bar>,
    pub ranges: Vec<RangeObject>,
    pub candidates: Vec<Candidate>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CorpusCensus {
    pub sessions: usize,
    pub m1_session_bars: usize,
    pub range_objects: usize,
    pub strict_upper_candidates: usize,
    pub strict_lower_candidates: usize,
    pub superseded_candidates: usize,
    pub terminal_survivors: usize,
    pub candidate_range_relations: usize,
    pub expected_candidate_range_relations: usize,
    pub degenerate_range_objects: usize,
    pub complete_coverage_sessions: usize,
    pub grammar_relations: usize,
    pub grammar_status: String,
    pub tape_logical_sha256: String,
    pub relation_logical_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CandidateSummary {
    pub candidate_index: u32,
    pub candidate_id: String,
    pub session_index: u32,
    pub session_id: String,
    pub side: String,
    pub sequence_number: u32,
    pub birth_knowledge_time: i64,
    pub extreme_price: f64,
    pub terminal_state: String,
    pub lifetime_minutes: u16,
    pub path_observations: u16,
    pub final_same_direction_extension: Option<f64>,
    pub final_opposite_displacement: Option<f64>,
    pub final_path_length: Option<f64>,
    pub final_side_oriented_displacement: Option<f64>,
    pub censor_state: String,
    pub authority_classification: String,
}

#[derive(Clone, Copy, Debug, Pod, Zeroable)]
#[repr(C)]
pub struct PackedCandidatePath {
    pub session_index: u32,
    pub candidate_index: u32,
    pub age_minutes: u16,
    pub side: u8,
    pub terminal_state: u8,
    pub reserved: u32,
    pub raw_close_minus_candidate: f64,
    pub same_direction_extension: f64,
    pub opposite_displacement: f64,
    pub path_length: f64,
}

#[derive(Clone, Copy, Debug, Pod, Zeroable)]
#[repr(C)]
pub struct PackedRangeSurface {
    pub session_index: u32,
    pub k: u16,
    pub tau_minutes: u16,
    pub status: u32,
    pub reserved: u32,
    pub raw_open: f64,
    pub raw_high: f64,
    pub raw_low: f64,
    pub raw_close: f64,
    pub z_open: f64,
    pub z_high: f64,
    pub z_low: f64,
    pub z_close: f64,
}

#[derive(Debug)]
pub struct CorpusProducts {
    pub sessions: Vec<SessionData>,
    pub census: CorpusCensus,
    pub candidate_summaries: Vec<CandidateSummary>,
    pub candidate_paths: Vec<PackedCandidatePath>,
    pub range_surface: Vec<PackedRangeSurface>,
}

pub fn reconstruct(authority: LoadedAuthority) -> AnyResult<CorpusProducts> {
    if authority.sessions.len() != authority.bars.len() {
        return Err("SESSION_BAR_VECTOR_CARDINALITY_DRIFT".into());
    }
    let mut sessions = Vec::with_capacity(authority.sessions.len());
    let mut tape_hash = Sha256::new();
    let mut relation_hash = Sha256::new();
    let mut relation_count = 0usize;
    let mut upper = 0usize;
    let mut lower = 0usize;
    let mut superseded = 0usize;
    let mut terminal = 0usize;
    let mut degenerate = 0usize;
    for (spec, bars) in authority.sessions.into_iter().zip(authority.bars) {
        let ranges = build_ranges(&spec, &bars)?;
        degenerate += ranges.iter().filter(|r| r.width <= 0.0).count();
        let (mut candidates, tape) = build_candidates_and_tape(&spec, &bars)?;
        if bars.len() < 390 {
            for candidate in candidates
                .iter_mut()
                .filter(|candidate| candidate.terminal_survivor)
            {
                candidate.terminal_survivor = false;
                candidate.terminal_label_known_at = None;
                candidate.terminal_label_knowledge_order = None;
                candidate.coverage_state = "SOURCE_PATH_INCOMPLETE".into();
            }
        }
        upper += candidates.iter().filter(|c| c.side == "UPPER").count();
        lower += candidates.iter().filter(|c| c.side == "LOWER").count();
        superseded += candidates.iter().filter(|c| c.superseded).count();
        terminal += candidates.iter().filter(|c| c.terminal_survivor).count();
        for row in &tape {
            hash_tape_row(&mut tape_hash, row);
        }
        let relations = build_range_relations(&candidates, &ranges);
        relation_count += relations.len();
        for relation in &relations {
            hash_relation(&mut relation_hash, relation);
        }
        sessions.push(SessionData {
            spec,
            bars,
            ranges,
            candidates,
        });
    }
    let candidate_count = upper + lower;
    let expected_relations = candidate_count * 30;
    if relation_count != expected_relations {
        return Err(format!(
            "CANDIDATE_RANGE_RELATION_DRIFT expected={expected_relations} observed={relation_count}"
        )
        .into());
    }
    let (candidate_summaries, candidate_paths) = build_candidate_products(&sessions)?;
    let range_surface = build_range_surface(&sessions);
    Ok(CorpusProducts {
        census: CorpusCensus {
            sessions: sessions.len(),
            m1_session_bars: sessions.iter().map(|s| s.bars.len()).sum(),
            range_objects: sessions.iter().map(|s| s.ranges.len()).sum(),
            strict_upper_candidates: upper,
            strict_lower_candidates: lower,
            superseded_candidates: superseded,
            terminal_survivors: terminal,
            candidate_range_relations: relation_count,
            expected_candidate_range_relations: expected_relations,
            degenerate_range_objects: degenerate,
            complete_coverage_sessions: sessions.iter().filter(|s| s.bars.len() == 390).count(),
            grammar_relations: 0,
            grammar_status: "GRAMMAR_EXCLUDED_BY_PROTOCOL".into(),
            tape_logical_sha256: format!("{:x}", tape_hash.finalize()),
            relation_logical_sha256: format!("{:x}", relation_hash.finalize()),
        },
        sessions,
        candidate_summaries,
        candidate_paths,
        range_surface,
    })
}

fn build_candidate_products(
    sessions: &[SessionData],
) -> AnyResult<(Vec<CandidateSummary>, Vec<PackedCandidatePath>)> {
    let total_candidates: usize = sessions.iter().map(|s| s.candidates.len()).sum();
    let mut summaries = Vec::with_capacity(total_candidates);
    let mut paths = Vec::with_capacity(total_candidates * 8);
    let mut global = 0u32;
    for (session_index, session) in sessions.iter().enumerate() {
        for candidate in &session.candidates {
            let end_exclusive = if let Some(commit) = candidate.superseded_at {
                ((commit - session.spec.start_epoch) / 60) as usize
            } else {
                session.bars.len()
            };
            let start = candidate.birth_index + 1;
            if end_exclusive < start || end_exclusive > session.bars.len() {
                return Err(
                    format!("CANDIDATE_PATH_BOUNDARY_DRIFT:{}", candidate.candidate_id).into(),
                );
            }
            let mut same: f64 = 0.0;
            let mut opposite: f64 = 0.0;
            let mut path_length = 0.0;
            let mut previous_close = session.bars[candidate.birth_index].close;
            let side_code = if candidate.side == "UPPER" { 1u8 } else { 2u8 };
            let terminal_code = if candidate.terminal_survivor {
                2u8
            } else if !candidate.superseded {
                3u8
            } else {
                1u8
            };
            for (offset, bar) in session.bars[start..end_exclusive].iter().enumerate() {
                if side_code == 1 {
                    same = same.max((bar.high - candidate.extreme_price).max(0.0));
                    opposite = opposite.max((candidate.extreme_price - bar.low).max(0.0));
                } else {
                    same = same.max((candidate.extreme_price - bar.low).max(0.0));
                    opposite = opposite.max((bar.high - candidate.extreme_price).max(0.0));
                }
                path_length += (bar.close - previous_close).abs();
                previous_close = bar.close;
                paths.push(PackedCandidatePath {
                    session_index: session_index as u32,
                    candidate_index: global,
                    age_minutes: (offset + 1) as u16,
                    side: side_code,
                    terminal_state: terminal_code,
                    reserved: 0,
                    raw_close_minus_candidate: bar.close - candidate.extreme_price,
                    same_direction_extension: same,
                    opposite_displacement: opposite,
                    path_length,
                });
            }
            let last = paths.last().filter(|p| p.candidate_index == global);
            let lifetime_end = candidate.superseded_at.unwrap_or_else(|| {
                if candidate.terminal_survivor {
                    session.spec.terminal_epoch
                } else {
                    session
                        .bars
                        .last()
                        .map(|bar| bar.close_time)
                        .unwrap_or(candidate.birth_knowledge_time)
                }
            });
            let lifetime = ((lifetime_end - candidate.birth_knowledge_time) / 60)
                .try_into()
                .map_err(|_| "CANDIDATE_LIFETIME_OVERFLOW")?;
            summaries.push(CandidateSummary {
                candidate_index: global,
                candidate_id: candidate.candidate_id.clone(),
                session_index: session_index as u32,
                session_id: session.spec.session_id.clone(),
                side: candidate.side.clone(),
                sequence_number: candidate.sequence_number,
                birth_knowledge_time: candidate.birth_knowledge_time,
                extreme_price: candidate.extreme_price,
                terminal_state: if candidate.terminal_survivor {
                    "TERMINAL_SURVIVOR"
                } else if candidate.superseded {
                    "SUPERSEDED"
                } else {
                    "SOURCE_PATH_INCOMPLETE"
                }
                .into(),
                lifetime_minutes: lifetime,
                path_observations: (end_exclusive - start) as u16,
                final_same_direction_extension: last.map(|p| p.same_direction_extension),
                final_opposite_displacement: last.map(|p| p.opposite_displacement),
                final_path_length: last.map(|p| p.path_length),
                final_side_oriented_displacement: last.map(|p| {
                    if side_code == 1 {
                        p.raw_close_minus_candidate
                    } else {
                        -p.raw_close_minus_candidate
                    }
                }),
                censor_state: if candidate.terminal_survivor {
                    "SESSION_END_CENSORED"
                } else if !candidate.superseded {
                    "SOURCE_PATH_INCOMPLETE"
                } else {
                    "COMPLETED_BY_SUPERSESSION"
                }
                .into(),
                authority_classification: "EMPIRICAL_WITH_RETROSPECTIVE_TERMINAL_LABEL".into(),
            });
            global += 1;
        }
    }
    Ok((summaries, paths))
}

fn build_range_surface(sessions: &[SessionData]) -> Vec<PackedRangeSurface> {
    let expected: usize = (1..=30).map(|k| 390 - k).sum::<usize>() * sessions.len();
    let mut out = Vec::with_capacity(expected);
    for (session_index, session) in sessions.iter().enumerate() {
        for range in &session.ranges {
            let k = range.k as usize;
            let half = range.width / 2.0;
            for (offset, bar) in session.bars[k..].iter().enumerate() {
                let available = half > 0.0;
                out.push(PackedRangeSurface {
                    session_index: session_index as u32,
                    k: range.k as u16,
                    tau_minutes: (offset + 1) as u16,
                    status: u32::from(available),
                    reserved: 0,
                    raw_open: bar.open,
                    raw_high: bar.high,
                    raw_low: bar.low,
                    raw_close: bar.close,
                    z_open: if available {
                        (bar.open - range.midpoint) / half
                    } else {
                        f64::NAN
                    },
                    z_high: if available {
                        (bar.high - range.midpoint) / half
                    } else {
                        f64::NAN
                    },
                    z_low: if available {
                        (bar.low - range.midpoint) / half
                    } else {
                        f64::NAN
                    },
                    z_close: if available {
                        (bar.close - range.midpoint) / half
                    } else {
                        f64::NAN
                    },
                });
            }
        }
    }
    out
}

fn hash_tape_row(h: &mut Sha256, row: &obs_open_meas02::TapeRow) {
    h.update(row.session_id.as_bytes());
    h.update([0]);
    h.update(row.source_row_id.as_bytes());
    h.update(row.bar_open.to_le_bytes());
    h.update(row.bar_close.to_le_bytes());
    for value in [row.open, row.high, row.low, row.close] {
        h.update(value.to_bits().to_le_bytes());
    }
    h.update(row.active_upper_candidate_id.as_bytes());
    h.update([0]);
    h.update(row.active_lower_candidate_id.as_bytes());
    h.update([
        u8::from(row.new_upper_candidate),
        u8::from(row.new_lower_candidate),
    ]);
}

fn hash_relation(h: &mut Sha256, row: &obs_open_meas02::RangeRelation) {
    h.update(row.candidate_id.as_bytes());
    h.update([0]);
    h.update(row.range_object_id.as_bytes());
    h.update(row.relation_available_at.to_le_bytes());
    for value in [
        row.extreme_minus_range_high,
        row.extreme_minus_range_low,
        row.extreme_minus_mid,
    ] {
        h.update(value.to_bits().to_le_bytes());
    }
    for value in [
        row.normalized_mid_coordinate,
        row.normalized_upper_extension,
        row.normalized_lower_extension,
    ] {
        match value {
            Some(value) => {
                h.update([1]);
                h.update(value.to_bits().to_le_bytes());
            }
            None => h.update([0]),
        }
    }
    h.update(row.candidate_birth_vs_freeze.as_bytes());
    h.update([0]);
    h.update(row.range_location_at_candidate_birth.as_bytes());
    h.update([0]);
    h.update(row.status.as_bytes());
}
