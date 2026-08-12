use northstar_auction_contract::{AuctionResolution, CensorReason, EventType};
use northstar_parity_fixtures::{Direction, GOLDEN_SCENARIOS};
use serde::Serialize;

const LOWER: f64 = 100.0;
const UPPER: f64 = 102.0;
const ATR: f64 = 10.0;
const EPS: f64 = 0.0001;
const BASE_TIME: u64 = 1_700_000_000;
const SOURCE_NODE_ID: u64 = 1001;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GrammarDirection {
    FromBelow,
    FromAbove,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticLedger {
    pub events: Vec<EventType>,
    pub event_ids: Vec<u64>,
    pub terminal_resolution: AuctionResolution,
    pub terminal_censor: CensorReason,
}

#[derive(Clone, Copy)]
struct Attempt {
    direction: i8,
    is_retest: bool,
    active: bool,
    contact: bool,
    broke: bool,
    accepted: bool,
    provisional: bool,
    qualified_far_closes: u8,
    start_bar: i32,
    max_penetration: f64,
}

#[derive(Clone, Copy)]
struct Transit {
    direction: i8,
    last_price: f64,
    attempt_id: u64,
}

struct GrammarEngine {
    events: Vec<EventType>,
    event_ids: Vec<u64>,
    attempt: Option<Attempt>,
    completed: Vec<(AuctionResolution, CensorReason)>,
    transit: Option<Transit>,
    accepted_side: i8,
    bar_sequence: i32,
    last_bar_slot: i32,
    market_time: u64,
    attempt_ordinal: u64,
    active_attempt_id: u64,
    active_episode_id: u64,
    active_event_count: u64,
}

impl GrammarEngine {
    fn new(_direction: GrammarDirection) -> Self {
        Self {
            events: Vec::with_capacity(16),
            event_ids: Vec::with_capacity(16),
            attempt: None,
            completed: Vec::with_capacity(2),
            transit: None,
            accepted_side: 0,
            bar_sequence: 0,
            last_bar_slot: 0,
            market_time: BASE_TIME,
            attempt_ordinal: 0,
            active_attempt_id: 0,
            active_episode_id: 0,
            active_event_count: 0,
        }
    }

    fn observe(
        &mut self,
        price: f64,
        bar_slot: Option<i32>,
        closed_price: f64,
        node_present: bool,
    ) {
        let new_bar = bar_slot.is_some_and(|slot| slot > self.last_bar_slot);
        if let Some(slot) = bar_slot.filter(|slot| *slot > self.last_bar_slot) {
            self.last_bar_slot = slot;
            self.bar_sequence += 1;
        }

        if self.attempt.is_some_and(|attempt| attempt.active) && !node_present {
            self.emit(EventType::Expire);
            self.complete(AuctionResolution::NodeRetired, CensorReason::None);
        }
        self.observe_transit(price);
        if !node_present {
            return;
        }

        if !self.attempt.is_some_and(|attempt| attempt.active) {
            let side = price_side(price);
            let gap_atr = boundary_gap(price) / ATR;
            if side != 0 && gap_atr <= 0.50 {
                self.attempt_ordinal += 1;
                self.active_attempt_id =
                    attempt_id(SOURCE_NODE_ID, self.market_time, side, self.attempt_ordinal);
                if self.active_episode_id == 0 {
                    self.active_episode_id = episode_id(SOURCE_NODE_ID, self.market_time, 1);
                }
                self.active_event_count = 0;
                let is_retest = self.accepted_side == side;
                self.attempt = Some(Attempt {
                    direction: side,
                    is_retest,
                    active: true,
                    contact: false,
                    broke: false,
                    accepted: false,
                    provisional: false,
                    qualified_far_closes: 0,
                    start_bar: self.bar_sequence,
                    max_penetration: 0.0,
                });
                self.emit(EventType::Approach);
            } else {
                return;
            }
        }

        let Some(mut attempt) = self.attempt else {
            return;
        };
        if !attempt.active {
            return;
        }
        let side = price_side(price);
        if !attempt.contact && side == 0 {
            attempt.contact = true;
            self.emit(EventType::Contact);
            if attempt.is_retest {
                self.emit(EventType::Retest);
            }
        }

        if attempt.contact {
            let penetration = if attempt.direction < 0 {
                (price - LOWER).max(0.0)
            } else {
                (UPPER - price).max(0.0)
            };
            if penetration > attempt.max_penetration {
                if attempt.max_penetration <= 0.0 {
                    self.emit(EventType::Penetration);
                }
                attempt.max_penetration = penetration;
            }

            let far_cross = if attempt.direction < 0 {
                price > UPPER + ATR * 0.10
            } else {
                price < LOWER - ATR * 0.10
            };
            if attempt.is_retest && far_cross {
                self.emit(EventType::RetestFailure);
                self.emit(EventType::Reclaim);
                self.accepted_side = 0;
                self.attempt = Some(attempt);
                self.complete(AuctionResolution::AcceptAndFailRetest, CensorReason::None);
                return;
            }
            if !attempt.is_retest && !attempt.broke && far_cross {
                attempt.broke = true;
                self.emit(EventType::Break);
            }

            let origin_gap = if attempt.direction < 0 {
                LOWER - price
            } else {
                price - UPPER
            };
            let accepted_gap = if attempt.direction < 0 {
                price - UPPER
            } else {
                LOWER - price
            };
            if attempt.is_retest
                && !far_cross
                && side == attempt.direction
                && origin_gap / ATR >= 0.20
            {
                self.emit(EventType::Hold);
                self.attempt = Some(attempt);
                self.complete(AuctionResolution::AcceptAndHoldRetest, CensorReason::None);
                return;
            }
            if !attempt.is_retest
                && !attempt.broke
                && side == attempt.direction
                && origin_gap / ATR >= 0.20
            {
                self.emit(EventType::Rejection);
                self.emit(EventType::Departure);
                self.attempt = Some(attempt);
                self.complete(AuctionResolution::RejectToOrigin, CensorReason::None);
                return;
            }
            if attempt.accepted && accepted_gap / ATR >= 0.25 {
                self.emit(EventType::Departure);
                self.accepted_side = -attempt.direction;
                self.transit = Some(Transit {
                    direction: attempt.direction,
                    last_price: price,
                    attempt_id: self.active_attempt_id,
                });
                self.attempt = Some(attempt);
                self.complete(AuctionResolution::AcceptThroughNode, CensorReason::None);
                return;
            }
        }

        if new_bar && attempt.contact {
            let close_side = price_side(closed_price);
            let far_side = -attempt.direction;
            let far_distance = if far_side > 0 {
                closed_price - UPPER
            } else {
                LOWER - closed_price
            };
            if attempt.broke && close_side == far_side && far_distance / ATR >= 0.10 {
                attempt.qualified_far_closes += 1;
                if !attempt.provisional {
                    attempt.provisional = true;
                    self.emit(EventType::ProvisionalAcceptance);
                }
                if !attempt.accepted && attempt.qualified_far_closes >= 2 {
                    attempt.accepted = true;
                    self.emit(EventType::Acceptance);
                }
            } else if attempt.broke && close_side == attempt.direction {
                let reclaim_distance = if attempt.direction < 0 {
                    LOWER - closed_price
                } else {
                    closed_price - UPPER
                };
                if reclaim_distance / ATR >= 0.05 {
                    self.emit(EventType::Reclaim);
                    self.attempt = Some(attempt);
                    self.complete(AuctionResolution::ReclaimAfterBreak, CensorReason::None);
                    return;
                }
            }
        }

        if new_bar && self.bar_sequence - attempt.start_bar > 3 {
            self.emit(EventType::Expire);
            self.attempt = Some(attempt);
            self.complete(AuctionResolution::Timeout, CensorReason::None);
            return;
        }
        self.attempt = Some(attempt);
    }

    fn observe_transit(&mut self, price: f64) {
        let Some(transit) = self.transit else {
            return;
        };
        let destination = if transit.direction < 0 {
            (120.0, 122.0)
        } else {
            (80.0, 82.0)
        };
        if touches(transit.last_price, price, destination.0, destination.1) {
            self.emit_transit(EventType::Transit, transit.attempt_id);
            self.transit = None;
        } else if touches(transit.last_price, price, LOWER, UPPER) {
            self.emit_transit(EventType::ReturnToSource, transit.attempt_id);
            self.transit = None;
        } else {
            self.transit = Some(Transit {
                last_price: price,
                ..transit
            });
        }
    }

    fn finalize(&mut self, reason: CensorReason) {
        if self.transit.take().is_some() {
            let attempt_id = self.active_attempt_id;
            self.emit_transit(EventType::Censor, attempt_id);
        }
        if self.attempt.is_some_and(|attempt| attempt.active) {
            self.emit(EventType::Censor);
            self.complete(AuctionResolution::None, reason);
        }
    }

    fn complete(&mut self, resolution: AuctionResolution, censor: CensorReason) {
        if let Some(attempt) = self.attempt.as_mut() {
            attempt.active = false;
        }
        self.completed.push((resolution, censor));
    }

    fn emit(&mut self, event: EventType) {
        self.active_event_count += 1;
        self.event_ids.push(event_id(
            self.active_attempt_id,
            self.active_event_count,
            event,
            self.market_time,
        ));
        self.events.push(event);
    }

    fn emit_transit(&mut self, event: EventType, attempt_id: u64) {
        self.event_ids
            .push(event_id(attempt_id, 1, event, self.market_time));
        self.events.push(event);
    }

    fn ledger(self) -> SemanticLedger {
        let (terminal_resolution, terminal_censor) = self
            .completed
            .last()
            .copied()
            .unwrap_or((AuctionResolution::None, CensorReason::None));
        SemanticLedger {
            events: self.events,
            event_ids: self.event_ids,
            terminal_resolution,
            terminal_censor,
        }
    }

    fn active_attempts(&self) -> usize {
        usize::from(self.attempt.is_some_and(|attempt| attempt.active))
    }

    fn has(&self, event: EventType) -> bool {
        self.events.contains(&event)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct GoldenGrammarReport {
    pub contract: &'static str,
    pub status: &'static str,
    pub scenarios: usize,
    pub directional_ledgers: usize,
    pub semantic_assertions: usize,
    pub boundary_assertions: usize,
}

pub fn verify_golden_grammar() -> Result<GoldenGrammarReport, String> {
    let mut semantic_assertions = 0;
    for fixture in GOLDEN_SCENARIOS {
        for (direction, fixture_direction) in [
            (GrammarDirection::FromBelow, Direction::FromBelow),
            (GrammarDirection::FromAbove, Direction::FromAbove),
        ] {
            let actual = run_golden_semantics(fixture.name, direction);
            let kinds = actual
                .events
                .iter()
                .map(|event| event.label())
                .collect::<Vec<_>>()
                .join(">");
            check(
                kinds == fixture.event_kinds,
                format!("{} {fixture_direction:?} event sequence", fixture.name),
            )?;
            check(
                actual.terminal_resolution == fixture.resolution,
                format!("{} {fixture_direction:?} resolution", fixture.name),
            )?;
            check(
                actual.terminal_censor == fixture.censor_reason,
                format!("{} {fixture_direction:?} censor", fixture.name),
            )?;
            let certificate = match fixture_direction {
                Direction::FromBelow => fixture.from_below,
                Direction::FromAbove => fixture.from_above,
            };
            check(
                golden_event_id_hash(&actual.event_ids) == certificate.event_id_hash,
                format!("{} {fixture_direction:?} event IDs", fixture.name),
            )?;
            semantic_assertions += 4;
        }
    }
    let boundary_assertions = verify_boundaries()?;
    Ok(GoldenGrammarReport {
        contract: "NORTHSTAR_AUCTION_GRAMMAR_PARITY_V1",
        status: "PASS",
        scenarios: GOLDEN_SCENARIOS.len(),
        directional_ledgers: GOLDEN_SCENARIOS.len() * 2,
        semantic_assertions,
        boundary_assertions,
    })
}

pub fn run_golden_semantics(name: &str, direction: GrammarDirection) -> SemanticLedger {
    let mut engine = GrammarEngine::new(direction);
    let start = price(direction, 95.0, 107.0);
    let contact = price(direction, 100.0, 102.0);
    let break_price = price(direction, 103.0 + EPS, 99.0 - EPS);
    let far_idle = price(direction, 88.0, 114.0);
    match name {
        "APPROACH_NO_CONTACT" | "TEST_END_CENSOR" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            finalize(&mut engine, CensorReason::TestEnd, 30);
        }
        "SHUTDOWN_CENSOR" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            finalize(&mut engine, CensorReason::Shutdown, 30);
        }
        "DATA_GAP_CENSOR" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            finalize(&mut engine, CensorReason::DataGap, 30);
        }
        "CONTACT_REJECTION" | "PENETRATION_REJECTION" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            tick(&mut engine, contact, 10, None, contact, true);
            if name == "PENETRATION_REJECTION" {
                tick(&mut engine, 101.0, 15, None, 101.0, true);
            }
            let reject = price(direction, 98.0, 104.0);
            tick(&mut engine, reject, 20, None, reject, true);
            close_episode(&mut engine, far_idle, 60, 1);
            finalize(&mut engine, CensorReason::TestEnd, 200);
        }
        "BREAK_NO_ACCEPTANCE" => {
            start_break(&mut engine, start, contact, break_price);
            finalize(&mut engine, CensorReason::TestEnd, 30);
        }
        "BREAK_RECLAIM" => {
            start_break(&mut engine, start, contact, break_price);
            let reclaim = price(direction, 99.5, 102.5);
            tick(&mut engine, reclaim, 60, Some(1), reclaim, true);
            close_episode(&mut engine, far_idle, 120, 2);
            finalize(&mut engine, CensorReason::TestEnd, 300);
        }
        "TIMEOUT" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            for bar in 1..=4 {
                tick(&mut engine, start, bar * 60, Some(bar), start, true);
            }
            close_episode(&mut engine, far_idle, 300, 5);
            finalize(&mut engine, CensorReason::TestEnd, 500);
        }
        "NODE_RETIREMENT" => {
            tick(&mut engine, start, 0, Some(0), start, true);
            tick(&mut engine, start, 20, None, start, false);
            close_episode(&mut engine, far_idle, 60, 1);
            finalize(&mut engine, CensorReason::TestEnd, 220);
        }
        _ => {
            accept_and_depart(&mut engine, direction, start, contact, break_price);
            match name {
                "BREAK_ACCEPTANCE" => finalize(&mut engine, CensorReason::TestEnd, 140),
                "ACCEPTED_RETEST" | "RETEST_HOLD" | "RETEST_FAILURE" => {
                    let retest_start = price(direction, 107.0, 95.0);
                    let retest_contact = price(direction, 102.0, 100.0);
                    tick(&mut engine, retest_start, 140, None, retest_start, true);
                    tick(&mut engine, retest_contact, 150, None, retest_contact, true);
                    if name == "RETEST_HOLD" {
                        let hold = price(direction, 104.0, 98.0);
                        tick(&mut engine, hold, 160, None, hold, true);
                        close_episode(&mut engine, far_idle, 180, 3);
                    } else if name == "RETEST_FAILURE" {
                        let failure = price(direction, 98.9999, 103.0001);
                        tick(&mut engine, failure, 160, None, failure, true);
                        close_episode(&mut engine, far_idle, 180, 3);
                    }
                    finalize(
                        &mut engine,
                        CensorReason::TestEnd,
                        if name == "ACCEPTED_RETEST" { 160 } else { 360 },
                    );
                }
                "RETURN_SOURCE" => {
                    let source = price(direction, 102.0, 100.0);
                    tick(&mut engine, source, 150, None, source, true);
                    close_episode(&mut engine, far_idle, 180, 3);
                    finalize(&mut engine, CensorReason::TestEnd, 360);
                }
                "TRANSIT_ADJACENT" => {
                    let destination = price(direction, 120.0, 82.0);
                    tick(&mut engine, destination, 150, None, destination, true);
                    close_episode(&mut engine, far_idle, 180, 3);
                    finalize(&mut engine, CensorReason::TestEnd, 360);
                }
                _ => panic!("unknown golden scenario {name}"),
            }
        }
    }
    engine.ledger()
}

fn start_break(engine: &mut GrammarEngine, start: f64, contact: f64, break_price: f64) {
    tick(engine, start, 0, Some(0), start, true);
    tick(engine, contact, 10, None, contact, true);
    tick(engine, break_price, 20, None, break_price, true);
}

fn accept_and_depart(
    engine: &mut GrammarEngine,
    direction: GrammarDirection,
    start: f64,
    contact: f64,
    break_price: f64,
) {
    start_break(engine, start, contact, break_price);
    tick(engine, break_price, 60, Some(1), break_price, true);
    tick(engine, break_price, 120, Some(2), break_price, true);
    let departure = price(direction, 104.5, 97.5);
    tick(engine, departure, 130, None, departure, true);
}

fn close_episode(engine: &mut GrammarEngine, price: f64, first_offset: i32, first_bar: i32) {
    for index in 0..3 {
        tick(
            engine,
            price,
            first_offset + index * 60,
            Some(first_bar + index),
            price,
            true,
        );
    }
}

fn tick(
    engine: &mut GrammarEngine,
    price: f64,
    offset: i32,
    bar_slot: Option<i32>,
    closed_price: f64,
    node_present: bool,
) {
    engine.market_time = BASE_TIME + offset as u64;
    engine.observe(price, bar_slot, closed_price, node_present);
}

fn finalize(engine: &mut GrammarEngine, reason: CensorReason, offset: i32) {
    engine.market_time = BASE_TIME + offset as u64;
    engine.finalize(reason);
}

fn price(direction: GrammarDirection, from_below: f64, from_above: f64) -> f64 {
    match direction {
        GrammarDirection::FromBelow => from_below,
        GrammarDirection::FromAbove => from_above,
    }
}

fn price_side(price: f64) -> i8 {
    if price < LOWER {
        -1
    } else if price > UPPER {
        1
    } else {
        0
    }
}

fn boundary_gap(price: f64) -> f64 {
    if price < LOWER {
        LOWER - price
    } else if price > UPPER {
        price - UPPER
    } else {
        0.0
    }
}

fn touches(previous: f64, price: f64, lower: f64, upper: f64) -> bool {
    let low = previous.min(price);
    let high = previous.max(price);
    high >= lower && low <= upper
}

fn hash_mix(hash: u64, value: u64) -> u64 {
    (hash ^ value).wrapping_mul(1_099_511_628_211)
}

fn attempt_id(node_id: u64, started_at: u64, direction: i8, ordinal: u64) -> u64 {
    let mut hash = hash_mix(1_469_598_103_934_665_603, node_id);
    hash = hash_mix(hash, started_at);
    hash = hash_mix(hash, (direction + 2) as u64);
    hash = hash_mix(hash, ordinal);
    hash.max(1)
}

fn episode_id(node_id: u64, started_at: u64, ordinal: u64) -> u64 {
    let mut hash = hash_mix(1_099_511_628_211, node_id);
    hash = hash_mix(hash, started_at);
    hash = hash_mix(hash, ordinal);
    hash.max(1)
}

fn event_id(attempt_id: u64, event_count: u64, kind: EventType, market_time: u64) -> u64 {
    let mut hash = hash_mix(attempt_id, event_count);
    hash = hash_mix(hash, u64::from(kind.code()));
    hash = hash_mix(hash, market_time);
    hash.max(1)
}

fn golden_event_id_hash(ids: &[u64]) -> u64 {
    let text = ids.iter().map(u64::to_string).collect::<Vec<_>>().join(",");
    text.bytes().fold(1_469_598_103_934_665_603, |hash, byte| {
        hash_mix(hash, u64::from(byte))
    })
}

fn verify_boundaries() -> Result<usize, String> {
    let mut assertions = 0;
    for direction in [GrammarDirection::FromBelow, GrammarDirection::FromAbove] {
        let start = price(direction, 95.0, 107.0);
        let sign = price(direction, -1.0, 1.0);
        for (candidate, expected, label) in [
            (start + sign * EPS, false, "approach outside"),
            (start, true, "approach exact"),
            (start - sign * EPS, true, "approach inside"),
        ] {
            let mut engine = GrammarEngine::new(direction);
            engine.observe(candidate, Some(0), candidate, true);
            check(engine.active_attempts() == usize::from(expected), label)?;
            assertions += 1;
        }

        for (adjustment, expected, label) in [
            (-EPS, false, "rejection below"),
            (0.0, true, "rejection exact"),
            (EPS, true, "rejection above"),
        ] {
            let mut engine = contacted(direction);
            let reject = price(direction, 98.0 - adjustment, 104.0 + adjustment);
            engine.observe(reject, None, reject, true);
            check(engine.has(EventType::Rejection) == expected, label)?;
            assertions += 1;
        }

        for (adjustment, expected, label) in [
            (-EPS, false, "break inside"),
            (0.0, false, "break exact strict"),
            (EPS, true, "break outside"),
        ] {
            let mut engine = contacted(direction);
            let frontier = price(direction, 103.0 + adjustment, 99.0 - adjustment);
            engine.observe(frontier, None, frontier, true);
            check(engine.has(EventType::Break) == expected, label)?;
            assertions += 1;
        }

        for (bucket, expected, label) in [
            (-1.0, false, "reclaim below"),
            (0.0, true, "reclaim exact"),
            (1.0, true, "reclaim above"),
        ] {
            let mut engine = broken(direction);
            let adjustment = bucket * EPS;
            let reclaim = price(direction, 99.5 - adjustment, 102.5 + adjustment);
            engine.observe(reclaim, Some(1), reclaim, true);
            check(engine.has(EventType::Reclaim) == expected, label)?;
            assertions += 1;
        }

        for (bucket, expected, label) in [
            (-1.0, false, "departure below"),
            (0.0, true, "departure exact"),
            (1.0, true, "departure above"),
        ] {
            let mut engine = accepted(direction);
            let adjustment = bucket * EPS;
            let departure = price(direction, 104.5 + adjustment, 97.5 - adjustment);
            engine.observe(departure, None, departure, true);
            check(engine.has(EventType::Departure) == expected, label)?;
            assertions += 1;
        }

        let mut engine = broken(direction);
        let break_price = price(direction, 103.0 + EPS, 99.0 - EPS);
        engine.observe(break_price, Some(1), break_price, true);
        check(
            engine.has(EventType::ProvisionalAcceptance) && !engine.has(EventType::Acceptance),
            "acceptance N-1 provisional",
        )?;
        assertions += 1;
        let count = engine.events.len();
        engine.observe(break_price, Some(1), break_price, true);
        check(engine.events.len() == count, "duplicate provisional")?;
        assertions += 1;
        engine.observe(break_price, Some(2), break_price, true);
        check(engine.has(EventType::Acceptance), "acceptance N")?;
        assertions += 1;
        let count = engine.events.len();
        engine.observe(break_price, Some(2), break_price, true);
        check(engine.events.len() == count, "duplicate acceptance")?;
        assertions += 1;
        engine.observe(break_price, Some(3), break_price, true);
        check(engine.events.len() == count, "acceptance N+1")?;
        assertions += 1;

        for (bucket, expected, label) in [
            (-1.0, false, "acceptance distance below"),
            (0.0, true, "acceptance distance exact"),
            (1.0, true, "acceptance distance above"),
        ] {
            let mut engine = broken(direction);
            let exact = price(direction, 103.0, 99.0);
            let closed = exact + price(direction, 1.0, -1.0) * bucket * EPS;
            let current = price(direction, 103.0 + EPS, 99.0 - EPS);
            engine.observe(current, Some(1), closed, true);
            check(
                engine.has(EventType::ProvisionalAcceptance) == expected,
                label,
            )?;
            assertions += 1;
        }

        let tracker = EpisodeGapTracker {
            current: 1,
            last_end_bar: 10,
        };
        check(tracker.open(12) == 1, "episode exact gap reuses")?;
        assertions += 1;
        check(tracker.open(13) == 2, "episode gap N+1 splits")?;
        assertions += 1;

        let mut engine = GrammarEngine::new(direction);
        engine.observe(start, Some(0), start, true);
        let count = engine.events.len();
        engine.observe(start, Some(0), start, true);
        check(engine.events.len() == count, "duplicate approach")?;
        assertions += 1;
        let contact = price(direction, 100.0, 102.0);
        engine.observe(contact, None, contact, true);
        let count = engine.events.len();
        engine.observe(contact, None, contact, true);
        check(engine.events.len() == count, "duplicate contact")?;
        assertions += 1;
        let frontier = price(direction, 103.0 + EPS, 99.0 - EPS);
        engine.observe(frontier, None, frontier, true);
        let count = engine.events.len();
        engine.observe(frontier, None, frontier, true);
        check(engine.events.len() == count, "duplicate break")?;
        assertions += 1;
    }
    Ok(assertions)
}

#[derive(Clone, Copy)]
struct EpisodeGapTracker {
    current: u32,
    last_end_bar: i32,
}

impl EpisodeGapTracker {
    fn open(self, bar: i32) -> u32 {
        if bar - self.last_end_bar <= 2 {
            self.current
        } else {
            self.current + 1
        }
    }
}

fn contacted(direction: GrammarDirection) -> GrammarEngine {
    let mut engine = GrammarEngine::new(direction);
    let start = price(direction, 95.0, 107.0);
    let contact = price(direction, 100.0, 102.0);
    engine.observe(start, Some(0), start, true);
    engine.observe(contact, None, contact, true);
    engine
}

fn broken(direction: GrammarDirection) -> GrammarEngine {
    let mut engine = contacted(direction);
    let frontier = price(direction, 103.0 + EPS, 99.0 - EPS);
    engine.observe(frontier, None, frontier, true);
    engine
}

fn accepted(direction: GrammarDirection) -> GrammarEngine {
    let mut engine = broken(direction);
    let frontier = price(direction, 103.0 + EPS, 99.0 - EPS);
    engine.observe(frontier, Some(1), frontier, true);
    engine.observe(frontier, Some(2), frontier, true);
    engine
}

fn check(condition: bool, label: impl Into<String>) -> Result<(), String> {
    if condition { Ok(()) } else { Err(label.into()) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn independent_grammar_matches_all_frozen_scenario_semantics() {
        let report = verify_golden_grammar().unwrap();
        assert_eq!(report.semantic_assertions, 128);
        assert_eq!(report.boundary_assertions, 56);
    }
}
