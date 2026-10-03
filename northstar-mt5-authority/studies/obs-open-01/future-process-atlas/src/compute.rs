use crate::model::{
    AnchorKind, AnchorReceipt, AtlasSession, CensorReason, OutcomeCode, OutcomeState,
    PackedOutcome, Representation, SESSION_MINUTES, Side, TerminalClass,
};
use obs_open_03ap::{HORIZONS_MINUTES, RANGE_Z_THRESHOLDS, RAW_PRICE_THRESHOLDS};
use obs_open_meas02::{Bar, Candidate, RangeObject};
use sha2::{Digest, Sha256};

pub struct OutcomeProducts {
    pub records: Vec<PackedOutcome>,
    pub anchors: Vec<AnchorReceipt>,
}

pub fn compute_outcomes(sessions: &[AtlasSession]) -> Result<OutcomeProducts, String> {
    let candidate_count: usize = sessions.iter().map(|s| s.candidates.len()).sum();
    let range_count: usize = sessions.iter().map(|s| s.ranges.len()).sum();
    let mut records = Vec::with_capacity(candidate_count * 74 + range_count * 134);
    let mut anchors = Vec::with_capacity(candidate_count + range_count);
    let mut anchor_index = 0u32;
    for (session_index, session) in sessions.iter().enumerate() {
        for candidate in &session.candidates {
            compute_candidate(
                session_index as u32,
                anchor_index,
                session,
                candidate,
                &mut records,
                &mut anchors,
            )?;
            anchor_index += 1;
        }
        for range in &session.ranges {
            compute_range(
                session_index as u32,
                anchor_index,
                session,
                range,
                &mut records,
                &mut anchors,
            )?;
            anchor_index += 1;
        }
    }
    validate_records(&records)?;
    Ok(OutcomeProducts { records, anchors })
}

fn compute_candidate(
    session_index: u32,
    anchor_index: u32,
    session: &AtlasSession,
    candidate: &Candidate,
    records: &mut Vec<PackedOutcome>,
    anchors: &mut Vec<AnchorReceipt>,
) -> Result<(), String> {
    let side = if candidate.side == "UPPER" {
        Side::Upper
    } else if candidate.side == "LOWER" {
        Side::Lower
    } else {
        return Err(format!("UNKNOWN_CANDIDATE_SIDE:{}", candidate.candidate_id));
    };
    let terminal_class = terminal_class(candidate, session.path_complete);
    let start = candidate.birth_index + 1;
    let stop = candidate
        .superseded_at
        .map(|commit| ((commit - session.spec.start_epoch) / 60) as usize)
        .unwrap_or(session.bars.len());
    if start > stop || stop > session.bars.len() {
        return Err(format!(
            "CANDIDATE_PATH_BOUNDARY:{}",
            candidate.candidate_id
        ));
    }
    let path = &session.bars[start..stop];
    anchors.push(AnchorReceipt {
        anchor_index,
        anchor_id: candidate.candidate_id.clone(),
        session_index,
        session_id: session.spec.session_id.clone(),
        anchor_kind: "EXTREME_CANDIDATE_BIRTH".into(),
        side: candidate.side.clone(),
        k: None,
        anchor_known_at: candidate.birth_knowledge_time,
        source_path_sha256: path_hash(path, &candidate.candidate_id),
        path_bars: path.len(),
        terminal_class: terminal_name(terminal_class).into(),
    });

    for horizon in HORIZONS_MINUTES {
        let availability = candidate_horizon_availability(session, candidate, path, horizon);
        let support = path.len().min(horizon as usize) as u16;
        let requested_end = candidate.birth_knowledge_time + i64::from(horizon) * 60;
        let observed_until = path
            .get(support.saturating_sub(1) as usize)
            .map(|bar| bar.close_time)
            .unwrap_or(candidate.birth_knowledge_time);
        let mut terminal = None;
        let mut parallel: f64 = 0.0;
        let mut antiparallel: f64 = 0.0;
        let mut variation = 0.0;
        if availability.0 == OutcomeState::ObservedComplete {
            let prefix = &path[..horizon as usize];
            let mut previous = session.bars[candidate.birth_index].close;
            for bar in prefix {
                let oriented_close = orient(bar.close - candidate.extreme_price, side);
                terminal = Some(oriented_close);
                let (same, opposite) = candidate_excursions(bar, candidate.extreme_price, side);
                parallel = parallel.max(same);
                antiparallel = antiparallel.max(opposite);
                variation += (bar.close - previous).abs();
                previous = bar.close;
            }
        }
        let common = CandidateCommon {
            session_index,
            anchor_index,
            anchor_known_at: candidate.birth_knowledge_time,
            requested_end,
            observed_until,
            horizon,
            support,
            side,
            state: availability.0,
            censor: availability.1,
            terminal_class,
            known_at: availability.2,
        };
        push_candidate_value(
            records,
            common,
            OutcomeCode::CandidateTerminalOrientedDisplacement,
            Representation::RawPrice,
            terminal,
        );
        push_candidate_value(
            records,
            common,
            OutcomeCode::CandidateMaxParallelDisplacement,
            Representation::RawPrice,
            terminal.map(|_| parallel),
        );
        push_candidate_value(
            records,
            common,
            OutcomeCode::CandidateMaxAntiparallelDisplacement,
            Representation::RawPrice,
            terminal.map(|_| antiparallel),
        );
        push_candidate_value(
            records,
            common,
            OutcomeCode::CandidateRealizedCloseVariation,
            Representation::RawPrice,
            terminal.map(|_| variation),
        );
        push_candidate_value(
            records,
            common,
            OutcomeCode::CandidatePathEfficiency,
            Representation::Dimensionless,
            terminal.map(|value| {
                if variation > 0.0 {
                    value.abs() / variation
                } else {
                    0.0
                }
            }),
        );
        let survival = candidate_survival(session, candidate, path, horizon);
        records.push(PackedOutcome::new(
            survival.value,
            None,
            candidate.birth_knowledge_time,
            survival.known_at,
            requested_end,
            survival.observed_until,
            anchor_index,
            session_index,
            OutcomeCode::CandidateSurvivalAtHorizon,
            horizon,
            survival.support,
            0,
            0,
            AnchorKind::Candidate,
            side,
            Representation::Dimensionless,
            survival.state,
            survival.censor,
            terminal_class,
        ));
    }

    for (threshold_index, threshold) in RAW_PRICE_THRESHOLDS.into_iter().enumerate() {
        for (parallel, code) in [
            (true, OutcomeCode::CandidateFirstPassageParallel),
            (false, OutcomeCode::CandidateFirstPassageAntiparallel),
        ] {
            let event = candidate_passage(session, candidate, path, side, threshold, parallel);
            records.push(PackedOutcome::new(
                event.value,
                event.censor_minutes,
                candidate.birth_knowledge_time,
                event.known_at,
                candidate
                    .superseded_at
                    .unwrap_or(session.spec.terminal_epoch),
                event.observed_until,
                anchor_index,
                session_index,
                code,
                0,
                event.support,
                0,
                threshold_index as u8,
                AnchorKind::Candidate,
                side,
                Representation::RawPrice,
                event.state,
                event.censor,
                terminal_class,
            ));
        }
    }

    let lifetime = if let Some(superseded) = candidate.superseded_at {
        EventResult::observed(
            (superseded - candidate.birth_knowledge_time) as f64 / 60.0,
            superseded,
            path.len() as u16,
        )
    } else if session.path_complete {
        EventResult::censored(
            (session.spec.terminal_epoch - candidate.birth_knowledge_time) as f64 / 60.0,
            session.spec.terminal_epoch,
            path.len() as u16,
            CensorReason::SessionTermination,
        )
    } else {
        EventResult::source_incomplete(
            path.last()
                .map(|bar| bar.close_time)
                .unwrap_or(candidate.birth_knowledge_time),
            path.len() as u16,
        )
    };
    records.push(PackedOutcome::new(
        lifetime.value,
        lifetime.censor_minutes,
        candidate.birth_knowledge_time,
        lifetime.known_at,
        candidate
            .superseded_at
            .unwrap_or(session.spec.terminal_epoch),
        lifetime.observed_until,
        anchor_index,
        session_index,
        OutcomeCode::CandidateTimeToSupersession,
        0,
        lifetime.support,
        0,
        0,
        AnchorKind::Candidate,
        side,
        Representation::Dimensionless,
        lifetime.state,
        lifetime.censor,
        terminal_class,
    ));

    let (status_value, status_state, status_censor, status_known) = match terminal_class {
        TerminalClass::Superseded => (
            Some(0.0),
            OutcomeState::ObservedComplete,
            CensorReason::None,
            candidate.superseded_at,
        ),
        TerminalClass::TerminalSurvivor => (
            Some(1.0),
            OutcomeState::ObservedComplete,
            CensorReason::None,
            Some(session.spec.terminal_epoch),
        ),
        TerminalClass::SourcePathIncomplete => (
            None,
            OutcomeState::SourcePathIncomplete,
            CensorReason::SourcePathGap,
            None,
        ),
        TerminalClass::NotApplicable => unreachable!(),
    };
    records.push(PackedOutcome::new(
        status_value,
        None,
        candidate.birth_knowledge_time,
        status_known,
        session.spec.terminal_epoch,
        path.last()
            .map(|bar| bar.close_time)
            .unwrap_or(candidate.birth_knowledge_time),
        anchor_index,
        session_index,
        OutcomeCode::CandidateTerminalStatus,
        0,
        path.len() as u16,
        0,
        0,
        AnchorKind::Candidate,
        side,
        Representation::Dimensionless,
        status_state,
        status_censor,
        terminal_class,
    ));
    Ok(())
}

fn compute_range(
    session_index: u32,
    anchor_index: u32,
    session: &AtlasSession,
    range: &RangeObject,
    records: &mut Vec<PackedOutcome>,
    anchors: &mut Vec<AnchorReceipt>,
) -> Result<(), String> {
    let start = range.k as usize;
    if start > session.bars.len() {
        return Err(format!("RANGE_PATH_BOUNDARY:{}", range.range_object_id));
    }
    let path = &session.bars[start..];
    anchors.push(AnchorReceipt {
        anchor_index,
        anchor_id: range.range_object_id.clone(),
        session_index,
        session_id: session.spec.session_id.clone(),
        anchor_kind: "RANGE_FREEZE".into(),
        side: "NONE".into(),
        k: Some(range.k),
        anchor_known_at: range.freeze_commit_time,
        source_path_sha256: path_hash(path, &range.range_object_id),
        path_bars: path.len(),
        terminal_class: "NOT_APPLICABLE".into(),
    });

    for horizon in HORIZONS_MINUTES {
        let availability = range_horizon_availability(session, range, path, horizon);
        let support = path.len().min(horizon as usize) as u16;
        let requested_end = range.freeze_commit_time + i64::from(horizon) * 60;
        let observed_until = path
            .get(support.saturating_sub(1) as usize)
            .map(|bar| bar.close_time)
            .unwrap_or(range.freeze_commit_time);
        let mut terminal_raw = None;
        let mut upper_raw: f64 = 0.0;
        let mut lower_raw: f64 = 0.0;
        let mut variation_raw = 0.0;
        let mut occupancy = [0u16; 3];
        let mut midpoint_crossings = 0u16;
        let mut rail_crossings = 0u16;
        if availability.0 == OutcomeState::ObservedComplete {
            let prefix = &path[..horizon as usize];
            let mut previous_close = session.bars[start - 1].close;
            let mut previous_mid_side = sign(previous_close - range.midpoint);
            let mut previous_location = location(previous_close, range.low, range.high);
            for bar in prefix {
                terminal_raw = Some(bar.close - range.midpoint);
                upper_raw = upper_raw.max((bar.high - range.midpoint).max(0.0));
                lower_raw = lower_raw.max((range.midpoint - bar.low).max(0.0));
                variation_raw += (bar.close - previous_close).abs();
                let current_mid_side = sign(bar.close - range.midpoint);
                if current_mid_side != 0
                    && previous_mid_side != 0
                    && current_mid_side != previous_mid_side
                {
                    midpoint_crossings += 1;
                }
                if current_mid_side != 0 {
                    previous_mid_side = current_mid_side;
                }
                let current_location = location(bar.close, range.low, range.high);
                occupancy[current_location as usize] += 1;
                if current_location != previous_location {
                    rail_crossings += 1;
                }
                previous_location = current_location;
                previous_close = bar.close;
            }
        }
        let common = RangeCommon {
            session_index,
            anchor_index,
            anchor_known_at: range.freeze_commit_time,
            requested_end,
            observed_until,
            horizon,
            support,
            k: range.k,
            state: availability.0,
            censor: availability.1,
            known_at: availability.2,
        };
        let half = range.width / 2.0;
        for (code, raw) in [
            (OutcomeCode::RangeTerminalClose, terminal_raw),
            (
                OutcomeCode::RangeMaxUpperDisplacement,
                terminal_raw.map(|_| upper_raw),
            ),
            (
                OutcomeCode::RangeMaxLowerDisplacement,
                terminal_raw.map(|_| lower_raw),
            ),
            (
                OutcomeCode::RangeRealizedCloseVariation,
                terminal_raw.map(|_| variation_raw),
            ),
        ] {
            push_range_value(records, common, code, Representation::RawPrice, raw, 0);
            push_range_value(
                records,
                common,
                code,
                Representation::RangeZ,
                raw.and_then(|value| (half > 0.0).then_some(value / half)),
                0,
            );
        }
        push_range_value(
            records,
            common,
            OutcomeCode::RangePathEfficiency,
            Representation::Dimensionless,
            terminal_raw.map(|value| {
                if variation_raw > 0.0 {
                    value.abs() / variation_raw
                } else {
                    0.0
                }
            }),
            0,
        );
        for (category, count) in occupancy.into_iter().enumerate() {
            push_range_value(
                records,
                common,
                OutcomeCode::RangeLocationOccupancy,
                Representation::Dimensionless,
                terminal_raw.map(|_| count as f64 / f64::from(horizon)),
                category as u8,
            );
        }
        push_range_value(
            records,
            common,
            OutcomeCode::RangeMidpointCrossingCount,
            Representation::Dimensionless,
            terminal_raw.map(|_| f64::from(midpoint_crossings)),
            0,
        );
        push_range_value(
            records,
            common,
            OutcomeCode::RangeRailCrossingCount,
            Representation::Dimensionless,
            terminal_raw.map(|_| f64::from(rail_crossings)),
            0,
        );
    }

    for (threshold_index, threshold) in RANGE_Z_THRESHOLDS.into_iter().enumerate() {
        for (upper, code) in [
            (true, OutcomeCode::RangeFirstPassageUpper),
            (false, OutcomeCode::RangeFirstPassageLower),
        ] {
            let event = range_passage(session, range, path, threshold, upper);
            records.push(PackedOutcome::new(
                event.value,
                event.censor_minutes,
                range.freeze_commit_time,
                event.known_at,
                session.spec.terminal_epoch,
                event.observed_until,
                anchor_index,
                session_index,
                code,
                0,
                event.support,
                range.k,
                threshold_index as u8,
                AnchorKind::Range,
                Side::None,
                Representation::RangeZ,
                event.state,
                event.censor,
                TerminalClass::NotApplicable,
            ));
        }
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct CandidateCommon {
    session_index: u32,
    anchor_index: u32,
    anchor_known_at: i64,
    requested_end: i64,
    observed_until: i64,
    horizon: u16,
    support: u16,
    side: Side,
    state: OutcomeState,
    censor: CensorReason,
    terminal_class: TerminalClass,
    known_at: Option<i64>,
}

#[derive(Clone, Copy)]
struct RangeCommon {
    session_index: u32,
    anchor_index: u32,
    anchor_known_at: i64,
    requested_end: i64,
    observed_until: i64,
    horizon: u16,
    support: u16,
    k: u8,
    state: OutcomeState,
    censor: CensorReason,
    known_at: Option<i64>,
}

fn push_candidate_value(
    records: &mut Vec<PackedOutcome>,
    common: CandidateCommon,
    code: OutcomeCode,
    representation: Representation,
    value: Option<f64>,
) {
    records.push(PackedOutcome::new(
        value,
        None,
        common.anchor_known_at,
        common.known_at,
        common.requested_end,
        common.observed_until,
        common.anchor_index,
        common.session_index,
        code,
        common.horizon,
        common.support,
        0,
        0,
        AnchorKind::Candidate,
        common.side,
        representation,
        common.state,
        common.censor,
        common.terminal_class,
    ));
}

fn push_range_value(
    records: &mut Vec<PackedOutcome>,
    common: RangeCommon,
    code: OutcomeCode,
    representation: Representation,
    value: Option<f64>,
    category: u8,
) {
    let (state, censor, known_at) =
        if value.is_none() && common.state == OutcomeState::ObservedComplete {
            (
                OutcomeState::NotEvaluable,
                CensorReason::DegenerateRange,
                None,
            )
        } else {
            (common.state, common.censor, common.known_at)
        };
    records.push(PackedOutcome::new(
        value,
        None,
        common.anchor_known_at,
        known_at,
        common.requested_end,
        common.observed_until,
        common.anchor_index,
        common.session_index,
        code,
        common.horizon,
        common.support,
        common.k,
        category,
        AnchorKind::Range,
        Side::None,
        representation,
        state,
        censor,
        TerminalClass::NotApplicable,
    ));
}

fn candidate_horizon_availability(
    session: &AtlasSession,
    candidate: &Candidate,
    path: &[Bar],
    horizon: u16,
) -> (OutcomeState, CensorReason, Option<i64>) {
    if horizon as usize <= path.len() {
        let known = candidate.birth_knowledge_time + i64::from(horizon) * 60;
        return (
            OutcomeState::ObservedComplete,
            CensorReason::None,
            Some(known),
        );
    }
    if let Some(superseded) = candidate.superseded_at {
        return (
            OutcomeState::RightCensored,
            CensorReason::CandidateSupersession,
            Some(superseded),
        );
    }
    if !session.path_complete {
        return (
            OutcomeState::SourcePathIncomplete,
            CensorReason::SourcePathGap,
            None,
        );
    }
    (
        OutcomeState::SessionTerminated,
        CensorReason::SessionTermination,
        Some(session.spec.terminal_epoch),
    )
}

fn range_horizon_availability(
    session: &AtlasSession,
    range: &RangeObject,
    path: &[Bar],
    horizon: u16,
) -> (OutcomeState, CensorReason, Option<i64>) {
    if range.width <= 0.0 {
        return (
            OutcomeState::NotEvaluable,
            CensorReason::DegenerateRange,
            None,
        );
    }
    if horizon as usize <= path.len() {
        return (
            OutcomeState::ObservedComplete,
            CensorReason::None,
            Some(range.freeze_commit_time + i64::from(horizon) * 60),
        );
    }
    if !session.path_complete {
        return (
            OutcomeState::SourcePathIncomplete,
            CensorReason::SourcePathGap,
            None,
        );
    }
    (
        OutcomeState::SessionTerminated,
        CensorReason::SessionTermination,
        Some(session.spec.terminal_epoch),
    )
}

struct SurvivalResult {
    value: Option<f64>,
    known_at: Option<i64>,
    observed_until: i64,
    support: u16,
    state: OutcomeState,
    censor: CensorReason,
}

fn candidate_survival(
    session: &AtlasSession,
    candidate: &Candidate,
    path: &[Bar],
    horizon: u16,
) -> SurvivalResult {
    let requested = candidate.birth_knowledge_time + i64::from(horizon) * 60;
    if candidate
        .superseded_at
        .is_some_and(|time| time <= requested)
    {
        let known = candidate.superseded_at.expect("checked");
        return SurvivalResult {
            value: Some(0.0),
            known_at: Some(known),
            observed_until: known,
            support: path.len().min(horizon as usize) as u16,
            state: OutcomeState::ObservedComplete,
            censor: CensorReason::None,
        };
    }
    if horizon as usize <= path.len() {
        return SurvivalResult {
            value: Some(1.0),
            known_at: Some(requested),
            observed_until: requested,
            support: horizon,
            state: OutcomeState::ObservedComplete,
            censor: CensorReason::None,
        };
    }
    let (state, censor, known_at) = if session.path_complete {
        (
            OutcomeState::SessionTerminated,
            CensorReason::SessionTermination,
            Some(session.spec.terminal_epoch),
        )
    } else {
        (
            OutcomeState::SourcePathIncomplete,
            CensorReason::SourcePathGap,
            None,
        )
    };
    SurvivalResult {
        value: None,
        known_at,
        observed_until: path
            .last()
            .map(|bar| bar.close_time)
            .unwrap_or(candidate.birth_knowledge_time),
        support: path.len() as u16,
        state,
        censor,
    }
}

struct EventResult {
    value: Option<f64>,
    censor_minutes: Option<f64>,
    known_at: Option<i64>,
    observed_until: i64,
    support: u16,
    state: OutcomeState,
    censor: CensorReason,
}

impl EventResult {
    fn observed(minutes: f64, known_at: i64, support: u16) -> Self {
        Self {
            value: Some(minutes),
            censor_minutes: Some(minutes),
            known_at: Some(known_at),
            observed_until: known_at,
            support,
            state: OutcomeState::ObservedComplete,
            censor: CensorReason::None,
        }
    }

    fn censored(minutes: f64, known_at: i64, support: u16, censor: CensorReason) -> Self {
        Self {
            value: None,
            censor_minutes: Some(minutes),
            known_at: Some(known_at),
            observed_until: known_at,
            support,
            state: OutcomeState::RightCensored,
            censor,
        }
    }

    fn source_incomplete(observed_until: i64, support: u16) -> Self {
        Self {
            value: None,
            censor_minutes: None,
            known_at: None,
            observed_until,
            support,
            state: OutcomeState::SourcePathIncomplete,
            censor: CensorReason::SourcePathGap,
        }
    }
}

fn candidate_passage(
    session: &AtlasSession,
    candidate: &Candidate,
    path: &[Bar],
    side: Side,
    threshold: f64,
    parallel: bool,
) -> EventResult {
    for (offset, bar) in path.iter().enumerate() {
        let delta = orient(bar.close - candidate.extreme_price, side);
        if (parallel && delta >= threshold) || (!parallel && delta <= -threshold) {
            return EventResult::observed((offset + 1) as f64, bar.close_time, (offset + 1) as u16);
        }
    }
    if let Some(superseded) = candidate.superseded_at {
        EventResult::censored(
            (superseded - candidate.birth_knowledge_time) as f64 / 60.0,
            superseded,
            path.len() as u16,
            CensorReason::CandidateSupersession,
        )
    } else if session.path_complete {
        EventResult::censored(
            (session.spec.terminal_epoch - candidate.birth_knowledge_time) as f64 / 60.0,
            session.spec.terminal_epoch,
            path.len() as u16,
            CensorReason::SessionTermination,
        )
    } else {
        EventResult::source_incomplete(
            path.last()
                .map(|bar| bar.close_time)
                .unwrap_or(candidate.birth_knowledge_time),
            path.len() as u16,
        )
    }
}

fn range_passage(
    session: &AtlasSession,
    range: &RangeObject,
    path: &[Bar],
    threshold: f64,
    upper: bool,
) -> EventResult {
    if range.width <= 0.0 {
        return EventResult {
            value: None,
            censor_minutes: None,
            known_at: None,
            observed_until: range.freeze_commit_time,
            support: 0,
            state: OutcomeState::NotEvaluable,
            censor: CensorReason::DegenerateRange,
        };
    }
    let half = range.width / 2.0;
    for (offset, bar) in path.iter().enumerate() {
        let z = (bar.close - range.midpoint) / half;
        if (upper && z >= threshold) || (!upper && z <= -threshold) {
            return EventResult::observed((offset + 1) as f64, bar.close_time, (offset + 1) as u16);
        }
    }
    if session.path_complete {
        EventResult::censored(
            f64::from(SESSION_MINUTES - u16::from(range.k)),
            session.spec.terminal_epoch,
            path.len() as u16,
            CensorReason::SessionTermination,
        )
    } else {
        EventResult::source_incomplete(
            path.last()
                .map(|bar| bar.close_time)
                .unwrap_or(range.freeze_commit_time),
            path.len() as u16,
        )
    }
}

fn terminal_class(candidate: &Candidate, complete: bool) -> TerminalClass {
    if candidate.superseded {
        TerminalClass::Superseded
    } else if complete && candidate.terminal_survivor {
        TerminalClass::TerminalSurvivor
    } else {
        TerminalClass::SourcePathIncomplete
    }
}

fn terminal_name(class: TerminalClass) -> &'static str {
    match class {
        TerminalClass::NotApplicable => "NOT_APPLICABLE",
        TerminalClass::Superseded => "SUPERSEDED",
        TerminalClass::TerminalSurvivor => "TERMINAL_SURVIVOR",
        TerminalClass::SourcePathIncomplete => "SOURCE_PATH_INCOMPLETE",
    }
}

fn orient(raw_delta: f64, side: Side) -> f64 {
    match side {
        Side::Upper => raw_delta,
        Side::Lower => -raw_delta,
        Side::None => raw_delta,
    }
}

fn candidate_excursions(bar: &Bar, anchor: f64, side: Side) -> (f64, f64) {
    match side {
        Side::Upper => ((bar.high - anchor).max(0.0), (anchor - bar.low).max(0.0)),
        Side::Lower => ((anchor - bar.low).max(0.0), (bar.high - anchor).max(0.0)),
        Side::None => (0.0, 0.0),
    }
}

fn sign(value: f64) -> i8 {
    if value > 0.0 {
        1
    } else if value < 0.0 {
        -1
    } else {
        0
    }
}

fn location(close: f64, low: f64, high: f64) -> u8 {
    if close > high {
        1
    } else if close < low {
        2
    } else {
        0
    }
}

fn path_hash(path: &[Bar], anchor_id: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(anchor_id.as_bytes());
    hasher.update([0]);
    for bar in path {
        hasher.update(bar.open_time.to_le_bytes());
        for value in [bar.open, bar.high, bar.low, bar.close] {
            hasher.update(value.to_bits().to_le_bytes());
        }
    }
    format!("{:x}", hasher.finalize())
}

fn validate_records(records: &[PackedOutcome]) -> Result<(), String> {
    for (index, record) in records.iter().enumerate() {
        let complete = record.outcome_state == OutcomeState::ObservedComplete as u8;
        if complete != (record.value_present == 1) {
            return Err(format!("VALUE_STATE_MISMATCH:{index}"));
        }
        if record.outcome_known_present == 1 && record.outcome_known_at < record.anchor_known_at {
            return Err(format!("OUTCOME_BACKFLOW:{index}"));
        }
        if record.reserved != [0; 7] {
            return Err(format!("NONZERO_RESERVED_BYTES:{index}"));
        }
    }
    Ok(())
}
