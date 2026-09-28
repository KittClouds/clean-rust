use std::{fs, path::Path, time::Instant};

use blake3::Hasher;
use hashbrown::{HashMap, HashSet};
use rdc_runtime_contracts_v1::{
    InspectionReply, InspectionResult,
    paid_action::{
        CrashPoint, EndpointResponse, PaidActionEndpoint, QueryJournal, RequestId, ResultBytes,
    },
};

use crate::{
    authority,
    domain::{Availability, HiddenEpisode, PublicEpisode, SourceOffer, WorldBank},
    evaluation::OutcomeCounts,
    model::{FrozenModels, ValueEstimate},
    routing::{BudgetPlan, LAMBDA_OFFER_COST, Lane, OfferMode},
};

use crate::runtime_receipts::{OfferLog, decode_offer, encode_offer};

pub use crate::runtime_crashes::{CrashResult, crash_recovery};

pub use crate::runtime_output::{
    write_crash_results, write_group_stats, write_matched_rows, write_traces,
};

#[derive(Clone, Debug)]
pub struct TraceRow {
    pub world_id: u32,
    pub lane: String,
    pub budget: usize,
    pub lambda: f32,
    pub offer_mode: String,
    pub episode_id: u32,
    pub source_id: u8,
    pub signal_episode_id: u32,
    pub offer_version_initial: u16,
    pub offer_version_used: u16,
    pub offer_availability: u8,
    pub offer_independent: bool,
    pub offer_history_bucket: u8,
    pub offer_age_bucket: u8,
    pub quote_price: u32,
    pub offer_request_cost_units: u32,
    pub query_paid: bool,
    pub query_kind: String,
    pub active: u16,
    pub proposed: Option<u16>,
    pub correct: u16,
    pub baseline_right: bool,
    pub after_right: bool,
    pub delta: i8,
    pub estimated_delta: f32,
    pub estimated_value: f32,
}

#[derive(Clone, Debug)]
pub struct GroupResult {
    pub world_id: u32,
    pub stratum: String,
    pub lane: String,
    pub budget: usize,
    pub lambda: f32,
    pub offer_mode: String,
    pub outcomes: OutcomeCounts,
    pub paid_queries: usize,
    pub offers_obtained: usize,
    pub offer_refresh_requests: usize,
    pub query_attempts: usize,
    pub query_charges: usize,
    pub offer_charges: usize,
    pub query_cost_units: u64,
    pub offer_cost_units: u64,
    pub unused_budget: usize,
    pub completed: usize,
    pub total_episodes: usize,
    pub task_latency_us: u64,
    pub task_latency_p95_us: u64,
    pub plan_elapsed_us: u64,
    pub observer_time_us: u64,
    pub journal_bytes: u64,
    pub offer_receipt_bytes: u64,
    pub receipt_identity: String,
    pub replay_identity_ok: bool,
    pub duplicate_charges: usize,
    pub illegal_commits: u32,
    pub task_action_effects: u32,
    pub random_call_residual: i32,
}

pub(crate) struct FixtureEndpoint<'a> {
    bank: &'a WorldBank,
    cache: HashMap<RequestId, ([u8; 32], u32, ResultBytes, bool)>,
    pub(crate) endpoint_attempts: usize,
    pub(crate) charges: usize,
    pub(crate) paid_cost: u64,
}

impl<'a> FixtureEndpoint<'a> {
    pub(crate) fn new(bank: &'a WorldBank) -> Self {
        Self {
            bank,
            cache: HashMap::with_capacity(128),
            endpoint_attempts: 0,
            charges: 0,
            paid_cost: 0,
        }
    }
    fn lookup(&self, episode: u32) -> Option<(&PublicEpisode, &HiddenEpisode)> {
        let i = self
            .bank
            .public
            .binary_search_by_key(&episode, |row| row.id)
            .ok()?;
        Some((&self.bank.public[i], &self.bank.hidden[i]))
    }
    fn current_offer(&self, episode: u32, source: u8) -> Option<SourceOffer> {
        let bundle = self
            .bank
            .current_offers
            .binary_search_by_key(&episode, |row| row.episode_id)
            .ok()
            .map(|i| &self.bank.current_offers[i])?;
        bundle.offers.get(source as usize).copied()
    }
}

impl PaidActionEndpoint for FixtureEndpoint<'_> {
    fn invoke(
        &mut self,
        request_id: RequestId,
        cost_units: u32,
        request: &[u8],
    ) -> Result<EndpointResponse, String> {
        self.endpoint_attempts += 1;
        let digest = *blake3::hash(request).as_bytes();
        if let Some((old_digest, old_cost, result, charged)) = self.cache.get(&request_id) {
            if *old_digest != digest || *old_cost != cost_units {
                return Err("fixture endpoint request ID collision".into());
            }
            return Ok(EndpointResponse {
                result: *result,
                // This request ID already incurred its charge, even when this is
                // a replayed response after a client crash.
                charged_for_request: *charged,
            });
        }
        if request.len() != 12 {
            return Err("invalid fixture endpoint request".into());
        }
        let kind = request[0];
        let episode = u32::from_le_bytes(request[1..5].try_into().unwrap());
        let source = request[5];
        let requested_version = u16::from_le_bytes(request[6..8].try_into().unwrap());
        let requested_price = u32::from_le_bytes(request[8..12].try_into().unwrap());
        let (result, charged) = match kind {
            b'Q' => {
                let quote = self
                    .current_offer(episode, source)
                    .ok_or("current offer missing")?;
                let quote_is_current = quote.schema_version == crate::domain::OFFER_SCHEMA_VERSION
                    && quote.version == requested_version
                    && quote.quoted_query_price == requested_price
                    && quote.offer_expiry > crate::domain::OFFER_VALIDATION_TICK
                    && quote.availability != Availability::Unavailable;
                let reply = if quote_is_current {
                    let (_, hidden) = self
                        .lookup(episode)
                        .ok_or("inspection fixture row missing")?;
                    *hidden
                        .replies
                        .get(source as usize)
                        .ok_or("inspection source missing")?
                } else {
                    crate::domain::stale_quote_reply(self.bank.recipe.world_id, episode, source)
                };
                (
                    ResultBytes::from_array(reply.encode().map_err(|e| e.to_owned())?),
                    quote_is_current,
                )
            }
            b'O' => (
                ResultBytes::from_array(encode_offer(
                    self.current_offer(episode, source)
                        .ok_or("current offer missing")?,
                )),
                true,
            ),
            _ => return Err("unknown fixture endpoint request kind".into()),
        };
        self.cache
            .insert(request_id, (digest, cost_units, result, charged));
        if charged {
            self.charges += 1;
            self.paid_cost += cost_units as u64;
        }
        Ok(EndpointResponse {
            result,
            charged_for_request: charged,
        })
    }
}

pub type RunPlanResult =
    Result<(Vec<TraceRow>, GroupResult, Vec<(u32, u8, u32)>), Box<dyn std::error::Error>>;

pub fn run_plan(
    bank: &WorldBank,
    plan: &BudgetPlan,
    receipt_root: &Path,
    run_nonce: u64,
    models: &FrozenModels,
) -> RunPlanResult {
    let started = Instant::now();
    let world_dir = receipt_root.join(format!("world-{}", plan.world_id));
    fs::create_dir_all(&world_dir)?;
    let suffix = format!(
        "{}-l{:03}-{}-b{:03}",
        plan.lane.label(),
        (plan.lambda * 1000.0).round() as u32,
        plan.offer_mode.label(),
        plan.budget
    );
    let query_path = world_dir.join(format!("{suffix}.rdj"));
    let offer_path = world_dir.join(format!("{suffix}.offers.rdj"));
    let mut journal = QueryJournal::create(&query_path).map_err(std::io::Error::other)?;
    let mut offer_log = OfferLog::create(&offer_path)?;
    for bundle in &bank.offers {
        for offer in bundle.offers {
            offer_log.append(
                plan.world_id,
                bundle.episode_id,
                offer,
                "pushed_or_cached",
                0,
            )?;
        }
    }
    // Make the complete pushed snapshot durable before routing can use it.
    offer_log.sync()?;
    let mut endpoint = FixtureEndpoint::new(bank);
    let mut used = HashSet::<u32>::with_capacity(plan.budget);
    let mut matched_price_counts = HashMap::<u32, usize>::with_capacity(8);
    let mut queried =
        HashMap::<u32, (u8, InspectionReply, ValueEstimate, f32, SourceOffer, bool)>::with_capacity(
            plan.budget,
        );
    let mut called = Vec::with_capacity(plan.budget);
    let mut offers_obtained = bank.offers.len() * 3;
    let mut refresh_requests = 0usize;
    let mut offer_charges = 0usize;
    let mut offer_cost_units = 0u64;
    let mut query_charge_count = 0usize;
    let call_limit = plan.call_target.unwrap_or(plan.budget).min(plan.budget);
    let offer_limit = plan.offer_charge_target.unwrap_or(0);
    let mut query_cost_units = 0u64;
    let mut observer_time_us = 0u64;
    let mut extra_task_time = HashMap::<u32, u64>::with_capacity(plan.budget);
    let mut task_latencies = Vec::with_capacity(bank.public.len());

    for candidate in &plan.candidates {
        if query_charge_count >= call_limit
            && (!plan.lane.is_matched_random() || offer_charges >= offer_limit)
        {
            break;
        }
        if query_charge_count >= call_limit && !candidate.offer_only {
            continue;
        }
        if used.contains(&candidate.episode_id) && !candidate.offer_only {
            continue;
        }
        let Some(public_index) = bank
            .public
            .binary_search_by_key(&candidate.episode_id, |row| row.id)
            .ok()
        else {
            continue;
        };
        let public = bank.public[public_index];
        let mut offer = candidate.offer;
        let mut signal_offer = candidate.signal_offer;
        if offer.offer_expiry == 0
            || offer.availability == Availability::Unavailable
            || (plan.offer_mode == OfferMode::PushedCache
                && offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK)
        {
            continue;
        }
        if plan.lane.is_matched_random() && !candidate.offer_only {
            let Some((_, target_count)) = plan
                .query_price_targets
                .iter()
                .find(|(price, _)| *price == offer.quoted_query_price)
            else {
                continue;
            };
            if matched_price_counts
                .get(&offer.quoted_query_price)
                .copied()
                .unwrap_or(0)
                >= *target_count
            {
                continue;
            }
        }
        let estimate_start = Instant::now();
        let mut estimate = if plan.lane == Lane::Oracle || plan.lane.is_matched_random() {
            candidate.estimate
        } else if plan.lane == Lane::ShuffledOffers {
            models.fitted_offer(
                public,
                crate::routing::bind_action_terms(signal_offer, offer),
            )
        } else {
            estimate_for(plan.lane, models, public, offer)
        };
        observer_time_us += estimate_start.elapsed().as_micros().min(u64::MAX as u128) as u64;
        let mut predicted_delta = estimate.delta();
        let mut value = value_for(plan, predicted_delta, offer.quoted_query_price);
        if plan.lane == Lane::EightFeature {
            value = predicted_delta;
        }
        if value <= 0.0 && !plan.lane.is_matched_random() {
            continue;
        }

        if plan.offer_mode == OfferMode::CostedRefresh {
            let refresh_started = Instant::now();
            let offer_request =
                fixture_request(b'O', candidate.episode_id, candidate.source_id, offer);
            let offer_id = request_id(
                run_nonce,
                plan,
                candidate.episode_id,
                candidate.source_id,
                true,
            );
            let before = journal.stats();
            let bytes = journal
                .execute(
                    &mut endpoint,
                    offer_id,
                    plan.offer_request_cost,
                    &offer_request,
                    CrashPoint::None,
                )
                .map_err(std::io::Error::other)?;
            refresh_requests += 1;
            let after = journal.stats();
            if after.paid_requests > before.paid_requests {
                offer_charges += 1;
                offer_cost_units += plan.offer_request_cost as u64;
            }
            let refreshed = decode_offer(&bytes.into_array())?;
            offer_log.append(
                plan.world_id,
                candidate.episode_id,
                refreshed,
                "costed_refresh_request",
                plan.offer_request_cost,
            )?;
            offer_log.sync()?;
            offers_obtained += 1;
            if candidate.offer_only {
                continue;
            }
            if plan.lane.is_matched_random()
                && refreshed.quoted_query_price != candidate.offer.quoted_query_price
            {
                continue;
            }
            let refresh_us = refresh_started.elapsed().as_micros().min(u64::MAX as u128) as u64;
            *extra_task_time.entry(candidate.episode_id).or_default() += refresh_us;
            // Every refreshed quote is a new decision, including unchanged versions and prices.
            offer = refreshed;
            signal_offer = crate::routing::bind_action_terms(signal_offer, offer);
            if offer.availability == Availability::Unavailable
                || offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK
            {
                continue;
            }
            let estimate_start = Instant::now();
            estimate = if plan.lane == Lane::ShuffledOffers {
                models.fitted_offer(public, signal_offer)
            } else {
                estimate_for(plan.lane, models, public, offer)
            };
            observer_time_us += estimate_start.elapsed().as_micros().min(u64::MAX as u128) as u64;
            predicted_delta = estimate.delta();
            value = value_for(plan, predicted_delta, offer.quoted_query_price);
            if plan.lane == Lane::EightFeature {
                value = predicted_delta;
            }
            if value <= 0.0 && !plan.lane.is_matched_random() {
                continue;
            }
        }

        let query_started = Instant::now();
        let query_request = fixture_request(b'Q', candidate.episode_id, candidate.source_id, offer);
        let query_id = request_id(
            run_nonce,
            plan,
            candidate.episode_id,
            candidate.source_id,
            false,
        );
        let before = journal.stats();
        let response = journal
            .execute(
                &mut endpoint,
                query_id,
                offer.quoted_query_price,
                &query_request,
                CrashPoint::None,
            )
            .map_err(std::io::Error::other)?;
        let after = journal.stats();
        if after.paid_requests > before.paid_requests {
            query_charge_count += 1;
            query_cost_units += offer.quoted_query_price as u64;
        }
        let reply_bytes = response.into_array();
        let reply_array: [u8; 64] = reply_bytes;
        let reply = InspectionReply::decode(&reply_array)?;
        if !crate::domain::validate_source_reply(
            plan.world_id,
            candidate.episode_id,
            candidate.source_id,
            reply,
        ) {
            return Err("source reply digest did not match the held-out fixture".into());
        }
        let query_us = query_started.elapsed().as_micros().min(u64::MAX as u128) as u64;
        *extra_task_time.entry(candidate.episode_id).or_default() += query_us;
        let query_paid = after.paid_requests > before.paid_requests;
        queried.insert(
            public.id,
            (
                candidate.source_id,
                reply,
                estimate,
                value,
                offer,
                query_paid,
            ),
        );
        used.insert(public.id);
        if query_paid {
            called.push((public.id, candidate.source_id, offer.quoted_query_price));
            if plan.lane.is_matched_random() {
                *matched_price_counts
                    .entry(candidate.offer.quoted_query_price)
                    .or_default() += 1;
            }
        }
    }
    let mut outcomes = OutcomeCounts::default();
    let mut task_action_effects = 0u32;
    let mut illegal_commits = 0u32;
    let mut task_identity = [0u8; 32];
    let mut traces = Vec::with_capacity(called.len());
    for public in &bank.public {
        let task_started = Instant::now();
        let hidden = &bank.hidden[bank
            .public
            .binary_search_by_key(&public.id, |row| row.id)
            .unwrap()];
        let baseline_right = public.active == hidden.correct_action;
        if baseline_right {
            outcomes.baseline_right += 1;
        } else {
            outcomes.baseline_wrong += 1;
        }
        let inspection = queried
            .get(&public.id)
            .map(|(_, reply, _, _, _, _)| InspectionResult::classify(public.active, *reply));
        if let Some(result) = inspection {
            match result.kind {
                rdc_runtime_contracts_v1::InspectionKind::Confirmed => {
                    outcomes.query_confirmed += 1
                }
                rdc_runtime_contracts_v1::InspectionKind::Contradicted => {
                    outcomes.query_contradicted += 1
                }
                rdc_runtime_contracts_v1::InspectionKind::Unknown => outcomes.query_unknown += 1,
                rdc_runtime_contracts_v1::InspectionKind::Failed => outcomes.query_failed += 1,
            }
            match result.proposed_action {
                Some(action) if !baseline_right && action == hidden.correct_action => {
                    outcomes.wrong_to_right += 1
                }
                Some(action) if baseline_right && action != hidden.correct_action => {
                    outcomes.right_to_wrong += 1
                }
                Some(_) => {}
                None if baseline_right => outcomes.unresolved_baseline_right += 1,
                None => outcomes.unresolved_baseline_wrong += 1,
            }
            if !baseline_right && result.proposed_action.is_none() {
                outcomes.avoided_wrong += 1;
            }
        }
        let authority_result = authority::execute(*public, inspection, hidden.correct_action);
        illegal_commits += authority_result.illegal_commits;
        task_action_effects += authority_result.task_action_effects;
        if !authority_result.replay_identity_ok {
            return Err("authority receipt replay identity mismatch".into());
        }
        let authority_us = task_started.elapsed().as_micros().min(u64::MAX as u128) as u64;
        task_latencies.push(authority_us + extra_task_time.get(&public.id).copied().unwrap_or(0));
        let mut h = Hasher::new();
        h.update(b"RDC-E008-TASK-REPLAY-V1\0");
        h.update(&task_identity);
        h.update(&public.id.to_le_bytes());
        h.update(&authority_result.identity);
        task_identity = *h.finalize().as_bytes();
        if let Some((source, reply, estimate, value, offer, query_paid)) =
            queried.get(&public.id).copied()
        {
            let result = InspectionResult::classify(public.active, reply);
            let after_right = result.proposed_action == Some(hidden.correct_action);
            let signal_offer = plan
                .candidates
                .iter()
                .find(|candidate| {
                    candidate.episode_id == public.id && candidate.source_id == source
                })
                .map_or(offer, |candidate| candidate.signal_offer);
            traces.push(TraceRow {
                world_id: plan.world_id,
                lane: plan.lane.label().to_owned(),
                budget: plan.budget,
                lambda: plan.lambda,
                offer_mode: plan.offer_mode.label().to_owned(),
                episode_id: public.id,
                source_id: source,
                signal_episode_id: candidate_signal_episode(plan, public.id, source),
                offer_version_initial: candidate_version(plan, public.id, source),
                offer_version_used: offer.version,
                offer_availability: offer.availability as u8,
                offer_independent: signal_offer.independence_from_active_source,
                offer_history_bucket: signal_offer.historical_reliability_bucket,
                offer_age_bucket: signal_offer.source_local_age_bucket,
                quote_price: offer.quoted_query_price,
                offer_request_cost_units: plan.offer_request_cost,
                query_paid,
                query_kind: result.kind.label().to_owned(),
                active: public.active.0,
                proposed: result.proposed_action.map(|action| action.0),
                correct: hidden.correct_action.0,
                baseline_right,
                after_right,
                delta: after_right as i8 - baseline_right as i8,
                estimated_delta: estimate.delta(),
                estimated_value: value,
            });
        }
    }
    let counts = journal.stats();
    drop(journal);
    let replay_journal = QueryJournal::resume(&query_path).map_err(std::io::Error::other)?;
    let replay_stats = replay_journal.stats();
    let query_replay_ok = counts.identity == replay_stats.identity
        && counts.bytes == replay_stats.bytes
        && replay_stats.unresolved == 0;
    drop(replay_journal);
    let offer_stats = offer_log.finish()?;
    let base_right = outcomes.baseline_right as i32;
    let completed = (base_right + outcomes.delta()).max(0) as usize;
    let actual_cost_charges = endpoint.charges;
    let expected_charges = offer_charges + query_charge_count;
    let duplicate_charges = actual_cost_charges.saturating_sub(expected_charges);
    let mut receipt_hasher = Hasher::new();
    receipt_hasher.update(b"RDC-E008-REPLAY-IDENTITY-V1\0");
    receipt_hasher.update(&task_identity);
    receipt_hasher.update(&counts.identity);
    receipt_hasher.update(&offer_stats.identity);
    let identity = hex(receipt_hasher.finalize().as_bytes());
    let replay_identity_ok = query_replay_ok && offer_stats.replay_ok;
    let elapsed = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
    task_latencies.sort_unstable();
    let task_latency_us = quantile_u64(&task_latencies, 0.50);
    let task_latency_p95_us = quantile_u64(&task_latencies, 0.95);
    let group = GroupResult {
        world_id: plan.world_id,
        stratum: bank.recipe.stratum.label().to_owned(),
        lane: plan.lane.label().to_owned(),
        budget: plan.budget,
        lambda: plan.lambda,
        offer_mode: plan.offer_mode.label().to_owned(),
        outcomes,
        paid_queries: query_charge_count,
        offers_obtained,
        offer_refresh_requests: refresh_requests,
        query_attempts: queried.len(),
        query_charges: query_charge_count,
        offer_charges,
        query_cost_units,
        offer_cost_units,
        unused_budget: plan.budget.saturating_sub(query_charge_count),
        completed,
        total_episodes: bank.public.len(),
        task_latency_us,
        task_latency_p95_us,
        plan_elapsed_us: elapsed,
        observer_time_us,
        journal_bytes: counts.bytes,
        offer_receipt_bytes: offer_stats.bytes,
        receipt_identity: identity,
        replay_identity_ok,
        duplicate_charges,
        illegal_commits,
        task_action_effects,
        random_call_residual: 0,
    };
    Ok((traces, group, called))
}

fn estimate_for(
    lane: Lane,
    models: &FrozenModels,
    public: PublicEpisode,
    offer: SourceOffer,
) -> ValueEstimate {
    match lane {
        Lane::SimpleOffer => models.simple_offer(public, offer),
        Lane::FittedOffer | Lane::ShuffledOffers => models.fitted_offer(public, offer),
        Lane::EightFeature => ValueEstimate {
            wrong_to_right: models.eight_feature_estimate(public),
            ..Default::default()
        },
        Lane::MatchedRandomSimple
        | Lane::MatchedRandomFitted
        | Lane::MatchedRandomShuffled
        | Lane::Oracle => ValueEstimate {
            wrong_to_right: 1.0,
            ..Default::default()
        },
        Lane::NoInspection => ValueEstimate::default(),
    }
}

fn value_for(plan: &BudgetPlan, delta: f32, price: u32) -> f32 {
    delta - plan.lambda * price as f32 - LAMBDA_OFFER_COST * plan.offer_request_cost as f32
}

fn candidate_version(plan: &BudgetPlan, episode_id: u32, source_id: u8) -> u16 {
    plan.candidates
        .iter()
        .find(|candidate| candidate.episode_id == episode_id && candidate.source_id == source_id)
        .map_or(0, |candidate| candidate.offer.version)
}

fn candidate_signal_episode(plan: &BudgetPlan, episode_id: u32, source_id: u8) -> u32 {
    plan.candidates
        .iter()
        .find(|candidate| candidate.episode_id == episode_id && candidate.source_id == source_id)
        .map_or(episode_id, |candidate| candidate.signal_episode_id)
}

fn request_id(
    run_nonce: u64,
    plan: &BudgetPlan,
    episode_id: u32,
    source_id: u8,
    offer_request: bool,
) -> RequestId {
    let lambda_index = crate::routing::LAMBDAS
        .iter()
        .position(|value| (*value - plan.lambda).abs() < 0.0001)
        .unwrap_or(0) as u8;
    let operation_index = if offer_request { 6 } else { 0 };
    let lane =
        plan.lane.code() + 10 * (lambda_index + 3 * plan.offer_mode.code() + operation_index);
    RequestId::derive(
        b"rdc-c-e008",
        run_nonce,
        plan.world_id
            .wrapping_mul(crate::domain::SOURCE_COUNT as u32)
            .wrapping_add(source_id as u32),
        lane,
        plan.budget as u16,
        episode_id,
    )
}

pub(crate) fn fixture_request(kind: u8, episode: u32, source: u8, offer: SourceOffer) -> [u8; 12] {
    let mut request = [0u8; 12];
    request[0] = kind;
    request[1..5].copy_from_slice(&episode.to_le_bytes());
    request[5] = source;
    request[6..8].copy_from_slice(&offer.version.to_le_bytes());
    request[8..12].copy_from_slice(&offer.quoted_query_price.to_le_bytes());
    request
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn quantile_u64(values: &[u64], quantile: f64) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let index = ((values.len() - 1) as f64 * quantile).round() as usize;
    values[index.min(values.len() - 1)]
}

#[cfg(test)]
mod endpoint_tests {
    use rdc_runtime_contracts_v1::paid_action::{PaidActionEndpoint, RequestId};

    use super::{FixtureEndpoint, fixture_request};
    use crate::domain::{OFFER_VALIDATION_TICK, development_banks};

    #[test]
    fn stale_quotes_are_unpaid_and_cached_paid_responses_keep_charge_status() {
        let bank = development_banks().remove(0);
        let (episode, actual) = bank
            .current_offers
            .iter()
            .find_map(|bundle| {
                bundle
                    .offers
                    .iter()
                    .find(|offer| {
                        offer.offer_expiry > OFFER_VALIDATION_TICK && offer.availability as u8 != 2
                    })
                    .map(|offer| (bundle.episode_id, *offer))
            })
            .unwrap();
        let mut endpoint = FixtureEndpoint::new(&bank);
        let mut stale = actual;
        stale.quoted_query_price += 1;
        let stale_request = fixture_request(b'Q', episode, stale.source_id, stale);
        let stale_id = RequestId::derive(b"e008-stale-quote", 1, 1, 1, 1, episode);
        let rejected = endpoint
            .invoke(stale_id, stale.quoted_query_price, &stale_request)
            .unwrap();
        assert!(!rejected.charged_for_request);
        let replayed_rejection = endpoint
            .invoke(stale_id, stale.quoted_query_price, &stale_request)
            .unwrap();
        assert!(!replayed_rejection.charged_for_request);
        assert_eq!(endpoint.charges, 0);

        let valid_request = fixture_request(b'Q', episode, actual.source_id, actual);
        let valid_id = RequestId::derive(b"e008-valid-quote", 1, 1, 2, 1, episode);
        let accepted = endpoint
            .invoke(valid_id, actual.quoted_query_price, &valid_request)
            .unwrap();
        assert!(accepted.charged_for_request);
        let replayed_acceptance = endpoint
            .invoke(valid_id, actual.quoted_query_price, &valid_request)
            .unwrap();
        assert!(replayed_acceptance.charged_for_request);
        assert_eq!(endpoint.charges, 1);
    }
}
