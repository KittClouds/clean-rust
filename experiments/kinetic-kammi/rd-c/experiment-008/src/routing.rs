use std::{io::Write, path::Path};

use blake3::Hasher;

use crate::{
    domain::{Availability, OfferBundle, PublicEpisode, SourceOffer},
    model::{FrozenModels, ValueEstimate},
};

pub const BUDGETS: [usize; 3] = [16, 32, 64];
pub const LAMBDAS: [f32; 3] = [0.0, 0.01, 0.03];
pub const LAMBDA_OFFER_COST: f32 = 0.02;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Lane {
    NoInspection,
    EightFeature,
    SimpleOffer,
    FittedOffer,
    ShuffledOffers,
    MatchedRandomSimple,
    MatchedRandomFitted,
    MatchedRandomShuffled,
    Oracle,
}

impl Lane {
    pub fn label(self) -> &'static str {
        match self {
            Self::NoInspection => "no_inspection",
            Self::EightFeature => "e007_eight_feature_positive_stop",
            Self::SimpleOffer => "offer_simple",
            Self::FittedOffer => "offer_fitted",
            Self::ShuffledOffers => "shuffled_offers",
            Self::MatchedRandomSimple => "matched_random_offer_simple",
            Self::MatchedRandomFitted => "matched_random_offer_fitted",
            Self::MatchedRandomShuffled => "matched_random_shuffled_offers",
            Self::Oracle => "evaluation_oracle",
        }
    }
    pub fn code(self) -> u8 {
        match self {
            Self::NoInspection => 0,
            Self::EightFeature => 1,
            Self::SimpleOffer => 2,
            Self::FittedOffer => 3,
            Self::ShuffledOffers => 4,
            Self::Oracle => 6,
            Self::MatchedRandomSimple => 7,
            Self::MatchedRandomFitted => 8,
            Self::MatchedRandomShuffled => 9,
        }
    }

    pub fn is_matched_random(self) -> bool {
        matches!(
            self,
            Self::MatchedRandomSimple | Self::MatchedRandomFitted | Self::MatchedRandomShuffled
        )
    }

    pub fn matched_random_for(self) -> Option<Self> {
        match self {
            Self::SimpleOffer => Some(Self::MatchedRandomSimple),
            Self::FittedOffer => Some(Self::MatchedRandomFitted),
            Self::ShuffledOffers => Some(Self::MatchedRandomShuffled),
            _ => None,
        }
    }

    pub fn matched_reference(self) -> Option<Self> {
        match self {
            Self::MatchedRandomSimple => Some(Self::SimpleOffer),
            Self::MatchedRandomFitted => Some(Self::FittedOffer),
            Self::MatchedRandomShuffled => Some(Self::ShuffledOffers),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum OfferMode {
    PushedCache,
    CostedRefresh,
}

impl OfferMode {
    pub fn label(self) -> &'static str {
        match self {
            Self::PushedCache => "pushed_or_cached",
            Self::CostedRefresh => "costed_refresh_request",
        }
    }
    pub fn code(self) -> u8 {
        match self {
            Self::PushedCache => 0,
            Self::CostedRefresh => 1,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Candidate {
    pub episode_id: u32,
    pub source_id: u8,
    /// The exact quote used by the action endpoint and receipt.
    pub offer: SourceOffer,
    /// The offer fields presented to the router, which may be shuffled in the negative control.
    pub signal_offer: SourceOffer,
    pub signal_episode_id: u32,
    pub estimate: ValueEstimate,
    pub predicted_delta: f32,
    pub predicted_value: f32,
    /// A matched-random quote request that is charged but cannot trigger inspection.
    pub offer_only: bool,
}

#[derive(Clone, Debug)]
pub struct BudgetPlan {
    pub world_id: u32,
    pub lane: Lane,
    pub budget: usize,
    pub lambda: f32,
    pub offer_mode: OfferMode,
    pub offer_request_cost: u32,
    /// Exact paid-call target for a matched-random control.
    pub call_target: Option<usize>,
    /// Exact charged quote-refresh target for a matched-random control.
    pub offer_charge_target: Option<usize>,
    /// Query-price histogram a matched-random control tries to preserve.
    pub query_price_targets: Vec<(u32, usize)>,
    /// Ranked positive candidates. The runtime may stop at any point up to `budget`.
    pub candidates: Vec<Candidate>,
}

pub fn make_plans(
    world_id: u32,
    public: &[PublicEpisode],
    offers: &[OfferBundle],
    offer_request_cost: u32,
    models: &FrozenModels,
) -> Vec<BudgetPlan> {
    let mut plans = Vec::with_capacity(1 + BUDGETS.len() + 6 * LAMBDAS.len() * BUDGETS.len());
    plans.push(BudgetPlan {
        world_id,
        lane: Lane::NoInspection,
        budget: 0,
        lambda: 0.0,
        offer_mode: OfferMode::PushedCache,
        offer_request_cost: 0,
        call_target: None,
        offer_charge_target: None,
        query_price_targets: Vec::new(),
        candidates: Vec::new(),
    });
    let eight = build_candidates(CandidateBuild {
        world_id,
        public_rows: public,
        offer_rows: offers,
        offer_request_cost,
        models,
        lane: Lane::EightFeature,
        lambda: 0.0,
        mode: OfferMode::PushedCache,
    });
    for budget in BUDGETS {
        plans.push(BudgetPlan {
            world_id,
            lane: Lane::EightFeature,
            budget,
            lambda: 0.0,
            offer_mode: OfferMode::PushedCache,
            offer_request_cost: 0,
            call_target: None,
            offer_charge_target: None,
            query_price_targets: Vec::new(),
            candidates: eight.clone(),
        });
    }
    for lane in [Lane::SimpleOffer, Lane::FittedOffer, Lane::ShuffledOffers] {
        for mode in [OfferMode::PushedCache, OfferMode::CostedRefresh] {
            for lambda in LAMBDAS {
                let candidates = build_candidates(CandidateBuild {
                    world_id,
                    public_rows: public,
                    offer_rows: offers,
                    offer_request_cost,
                    models,
                    lane,
                    lambda,
                    mode,
                });
                for budget in BUDGETS {
                    plans.push(BudgetPlan {
                        world_id,
                        lane,
                        budget,
                        lambda,
                        offer_mode: mode,
                        offer_request_cost: if mode == OfferMode::CostedRefresh {
                            offer_request_cost
                        } else {
                            0
                        },
                        call_target: None,
                        offer_charge_target: None,
                        query_price_targets: Vec::new(),
                        candidates: candidates.clone(),
                    });
                }
            }
        }
    }
    plans
}

#[derive(Clone, Debug, Default)]
pub struct PreviewResult {
    pub paid_queries: Vec<(u32, u8, u32)>,
    pub offer_requests: usize,
}

pub fn preview_route(
    public: &[PublicEpisode],
    current_offers: &[OfferBundle],
    plan: &BudgetPlan,
    models: &FrozenModels,
) -> PreviewResult {
    let mut result = PreviewResult {
        paid_queries: Vec::with_capacity(plan.budget),
        offer_requests: 0,
    };
    let mut seen = hashbrown::HashSet::with_capacity(plan.budget);
    for candidate in &plan.candidates {
        if result.paid_queries.len() >= plan.budget {
            break;
        }
        if seen.contains(&candidate.episode_id) {
            continue;
        }
        let mut offer = candidate.offer;
        if offer.availability == Availability::Unavailable || offer.offer_expiry == 0 {
            continue;
        }
        if plan.offer_mode == OfferMode::PushedCache
            && offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK
        {
            continue;
        }
        let live_offer = current_offers
            .binary_search_by_key(&candidate.episode_id, |bundle| bundle.episode_id)
            .ok()
            .and_then(|index| {
                current_offers[index]
                    .offers
                    .get(candidate.source_id as usize)
            })
            .copied();
        let public = public
            .binary_search_by_key(&candidate.episode_id, |row| row.id)
            .ok()
            .map(|index| public[index]);
        let (Some(public), Some(live_offer)) = (public, live_offer) else {
            continue;
        };
        let mut signal_offer = candidate.signal_offer;
        let initial_estimate = match plan.lane {
            Lane::SimpleOffer => models.simple_offer(public, offer),
            Lane::FittedOffer => models.fitted_offer(public, offer),
            Lane::ShuffledOffers => {
                models.fitted_offer(public, bind_action_terms(signal_offer, offer))
            }
            Lane::EightFeature => ValueEstimate {
                wrong_to_right: models.eight_feature_estimate(public),
                ..Default::default()
            },
            _ => candidate.estimate,
        };
        let initial_value = initial_estimate.delta()
            - plan.lambda * offer.quoted_query_price as f32
            - LAMBDA_OFFER_COST * plan.offer_request_cost as f32;
        if initial_value <= 0.0 && plan.lane != Lane::EightFeature {
            continue;
        }
        if plan.offer_mode == OfferMode::PushedCache {
            if offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK {
                continue;
            }
            if live_offer != offer {
                // Runtime attempts the stale cached quote and then marks the task used.
                seen.insert(candidate.episode_id);
                continue;
            }
        } else {
            result.offer_requests += 1;
            offer = live_offer;
            signal_offer = bind_action_terms(signal_offer, offer);
            if offer.availability == Availability::Unavailable
                || offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK
            {
                continue;
            }
            let refreshed_estimate = match plan.lane {
                Lane::SimpleOffer => models.simple_offer(public, offer),
                Lane::FittedOffer => models.fitted_offer(public, offer),
                Lane::ShuffledOffers => models.fitted_offer(public, signal_offer),
                Lane::EightFeature => ValueEstimate {
                    wrong_to_right: models.eight_feature_estimate(public),
                    ..Default::default()
                },
                _ => candidate.estimate,
            };
            let refreshed_value = refreshed_estimate.delta()
                - plan.lambda * offer.quoted_query_price as f32
                - LAMBDA_OFFER_COST * plan.offer_request_cost as f32;
            if refreshed_value <= 0.0 && plan.lane != Lane::EightFeature {
                continue;
            }
        }
        result.paid_queries.push((
            candidate.episode_id,
            candidate.source_id,
            offer.quoted_query_price,
        ));
        seen.insert(candidate.episode_id);
    }
    result
}

pub fn make_matched_random_plan(
    world_id: u32,
    offers: &[OfferBundle],
    current_offers: &[OfferBundle],
    reference: &BudgetPlan,
    reference_paid: &[(u32, u8, u32)],
    reference_offer_requests: usize,
) -> BudgetPlan {
    let count = reference_paid.len().min(reference.budget);
    let lane = reference
        .lane
        .matched_random_for()
        .expect("matched random requires an offer routing lane");
    let mut chosen = Vec::with_capacity(count + reference_offer_requests.saturating_sub(count));
    let mut used_episodes = hashbrown::HashSet::with_capacity(chosen.capacity());
    let mut query_price_targets = Vec::<(u32, usize)>::new();
    let mut all = Vec::with_capacity(offers.len() * 3);
    for (bundle_index, bundle) in offers.iter().enumerate() {
        let current = current_offers.get(bundle_index);
        for source in 0..crate::domain::SOURCE_COUNT {
            let cached = bundle.offers[source];
            let live = current
                .and_then(|row| row.offers.get(source))
                .copied()
                .unwrap_or(cached);
            if reference.offer_mode == OfferMode::PushedCache && cached != live {
                continue;
            }
            let offer = if reference.offer_mode == OfferMode::CostedRefresh {
                live
            } else {
                cached
            };
            if offer.availability == Availability::Unavailable || offer.offer_expiry == 0 {
                continue;
            }
            if offer.offer_expiry <= crate::domain::OFFER_VALIDATION_TICK
                && reference.offer_mode == OfferMode::PushedCache
            {
                continue;
            }
            all.push(Candidate {
                episode_id: bundle.episode_id,
                source_id: offer.source_id,
                offer,
                signal_offer: offer,
                signal_episode_id: bundle.episode_id,
                estimate: ValueEstimate {
                    wrong_to_right: 1.0,
                    ..Default::default()
                },
                predicted_delta: 1.0,
                predicted_value: 1.0,
                offer_only: false,
            });
        }
    }
    all.sort_unstable_by(|a, b| {
        random_key(reference.world_id, reference.budget, reference.lambda, a).cmp(&random_key(
            reference.world_id,
            reference.budget,
            reference.lambda,
            b,
        ))
    });
    for reference_query in reference_paid.iter().take(count) {
        let target_price = reference_query.2;
        if let Some(candidate) = all
            .iter()
            .filter(|c| !used_episodes.contains(&c.episode_id))
            .min_by_key(|c| {
                (
                    c.offer.quoted_query_price.abs_diff(target_price),
                    random_key(world_id, reference.budget, reference.lambda, c),
                )
            })
        {
            chosen.push(*candidate);
            used_episodes.insert(candidate.episode_id);
            if let Some((_, target_count)) = query_price_targets
                .iter_mut()
                .find(|(price, _)| *price == candidate.offer.quoted_query_price)
            {
                *target_count += 1;
            } else {
                query_price_targets.push((candidate.offer.quoted_query_price, 1));
            }
        }
    }
    query_price_targets.sort_unstable_by_key(|(price, _)| *price);
    let offer_target = if reference.offer_mode == OfferMode::CostedRefresh {
        reference_offer_requests.max(count)
    } else {
        0
    };
    let offer_only_needed = offer_target.saturating_sub(chosen.len());
    if offer_only_needed > 0 {
        let mut used_offers = chosen
            .iter()
            .map(|candidate| (candidate.episode_id, candidate.source_id))
            .collect::<hashbrown::HashSet<_>>();
        let mut appended = 0;
        for (bundle_index, bundle) in offers.iter().enumerate() {
            let Some(current) = current_offers.get(bundle_index) else {
                continue;
            };
            for offer in current.offers {
                if offer.availability == Availability::Unavailable
                    || offer.offer_expiry == 0
                    || !used_offers.insert((bundle.episode_id, offer.source_id))
                {
                    continue;
                }
                chosen.push(Candidate {
                    episode_id: bundle.episode_id,
                    source_id: offer.source_id,
                    offer,
                    signal_offer: offer,
                    signal_episode_id: bundle.episode_id,
                    estimate: ValueEstimate::default(),
                    predicted_delta: 0.0,
                    predicted_value: 0.0,
                    offer_only: true,
                });
                appended += 1;
                if appended >= offer_only_needed {
                    break;
                }
            }
            if appended >= offer_only_needed {
                break;
            }
        }
    }
    BudgetPlan {
        world_id,
        lane,
        budget: reference.budget,
        lambda: reference.lambda,
        offer_mode: reference.offer_mode,
        offer_request_cost: reference.offer_request_cost,
        call_target: Some(count),
        offer_charge_target: Some(offer_target),
        query_price_targets,
        candidates: chosen,
    }
}

struct CandidateBuild<'a> {
    world_id: u32,
    public_rows: &'a [PublicEpisode],
    offer_rows: &'a [OfferBundle],
    offer_request_cost: u32,
    models: &'a FrozenModels,
    lane: Lane,
    lambda: f32,
    mode: OfferMode,
}

fn build_candidates(build: CandidateBuild<'_>) -> Vec<Candidate> {
    let CandidateBuild {
        world_id,
        public_rows,
        offer_rows,
        offer_request_cost,
        models,
        lane,
        lambda,
        mode,
    } = build;
    let shuffled = if lane == Lane::ShuffledOffers {
        Some(shuffle_offers(offer_rows, world_id))
    } else {
        None
    };
    let mut candidates = Vec::with_capacity(public_rows.len() * 2);
    for (index, public) in public_rows.iter().enumerate() {
        let signal_bundle = shuffled
            .as_ref()
            .map_or(&offer_rows[index], |rows| &rows[index]);
        if lane == Lane::EightFeature {
            // This frozen E007 control sees the original eight fields only and has no positive scores.
            let delta = models.eight_feature_estimate(*public);
            if delta > 0.0 {
                let offer = offer_rows[index].offers[0];
                candidates.push(Candidate {
                    episode_id: public.id,
                    source_id: 0,
                    offer,
                    signal_offer: offer,
                    signal_episode_id: public.id,
                    estimate: ValueEstimate {
                        wrong_to_right: delta,
                        ..Default::default()
                    },
                    predicted_delta: delta,
                    predicted_value: delta,
                    offer_only: false,
                });
            }
            continue;
        }
        for source_index in 0..crate::domain::SOURCE_COUNT {
            let offer = offer_rows[index].offers[source_index];
            if offer.schema_version != crate::domain::OFFER_SCHEMA_VERSION {
                continue;
            }
            if offer.availability == Availability::Unavailable || offer.offer_expiry == 0 {
                continue;
            }
            let raw_signal_offer = signal_bundle.offers[source_index];
            let signal_offer = if lane == Lane::ShuffledOffers {
                bind_action_terms(raw_signal_offer, offer)
            } else {
                offer
            };
            let estimate = match lane {
                Lane::SimpleOffer => models.simple_offer(*public, signal_offer),
                Lane::FittedOffer | Lane::ShuffledOffers => {
                    models.fitted_offer(*public, signal_offer)
                }
                _ => continue,
            };
            let delta = estimate.delta();
            let offer_cost = if mode == OfferMode::CostedRefresh {
                offer_request_cost
            } else {
                0
            };
            let value = delta
                - lambda * offer.quoted_query_price as f32
                - LAMBDA_OFFER_COST * offer_cost as f32;
            if value > 0.0 {
                candidates.push(Candidate {
                    episode_id: public.id,
                    source_id: offer.source_id,
                    offer,
                    signal_offer,
                    signal_episode_id: signal_bundle.episode_id,
                    estimate,
                    predicted_delta: delta,
                    predicted_value: value,
                    offer_only: false,
                });
            }
        }
    }
    candidates.sort_unstable_by(|a, b| {
        b.predicted_value
            .total_cmp(&a.predicted_value)
            .then_with(|| a.offer.quoted_query_price.cmp(&b.offer.quoted_query_price))
            .then_with(|| {
                tie_break(world_id, a.episode_id, a.source_id, lane).cmp(&tie_break(
                    world_id,
                    b.episode_id,
                    b.source_id,
                    lane,
                ))
            })
    });
    candidates
}

/// Keeps quote and execution fields bound to the queried source while allowing
/// the shuffled negative control to permute only source-description features.
pub fn bind_action_terms(signal: SourceOffer, actual: SourceOffer) -> SourceOffer {
    SourceOffer {
        schema_version: actual.schema_version,
        version: actual.version,
        source_id: actual.source_id,
        availability: actual.availability,
        source_local_age_bucket: signal.source_local_age_bucket,
        provenance_family: signal.provenance_family,
        independence_from_active_source: signal.independence_from_active_source,
        historical_reliability_bucket: signal.historical_reliability_bucket,
        quoted_query_price: actual.quoted_query_price,
        offer_expiry: actual.offer_expiry,
    }
}

fn shuffle_offers(offers: &[OfferBundle], world_id: u32) -> Vec<OfferBundle> {
    if offers.is_empty() {
        return Vec::new();
    }
    let n = offers.len();
    let multiplier = if n == 1 { 1 } else { 73 };
    let shift = (world_id as usize * 19 + 7) % n;
    (0..n)
        .map(|index| {
            let source_index = (index * multiplier + shift) % n;
            OfferBundle {
                episode_id: offers[index].episode_id,
                offers: offers[source_index].offers,
            }
        })
        .collect()
}

pub fn write_plans(
    path: impl AsRef<Path>,
    plans: &[BudgetPlan],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::with_capacity(64 * 1024, std::fs::File::create(path)?);
    writeln!(
        writer,
        "world_id,lane,budget,lambda,offer_mode,rank,episode_id,source_id,offer_version,quote_price,signal_episode_id,predicted_delta,predicted_value,eligible"
    )?;
    for plan in plans {
        for (rank, candidate) in plan.candidates.iter().enumerate() {
            writeln!(
                writer,
                "{},{},{},{:.3},{},{},{},{},{},{},{},{:.6},{:.6},true",
                plan.world_id,
                plan.lane.label(),
                plan.budget,
                plan.lambda,
                plan.offer_mode.label(),
                rank + 1,
                candidate.episode_id,
                candidate.source_id,
                candidate.offer.version,
                candidate.offer.quoted_query_price,
                candidate.signal_episode_id,
                candidate.predicted_delta,
                candidate.predicted_value
            )?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn validate_plans(plans: &[BudgetPlan]) -> Result<(), Box<dyn std::error::Error>> {
    for plan in plans {
        let action_candidates = plan
            .candidates
            .iter()
            .filter(|candidate| !candidate.offer_only)
            .collect::<Vec<_>>();
        if action_candidates
            .iter()
            .any(|candidate| candidate.predicted_value <= 0.0)
        {
            return Err("plan contains non-positive candidate".into());
        }
        if action_candidates
            .windows(2)
            .any(|w| w[0].predicted_value < w[1].predicted_value)
        {
            return Err("candidate ranking is not descending by positive value".into());
        }
        if plan.budget > crate::domain::EPISODES_PER_DOMAIN * crate::domain::DOMAINS_PER_WORLD {
            return Err("budget exceeds episode count".into());
        }
    }
    Ok(())
}

fn tie_break(world_id: u32, episode_id: u32, source_id: u8, lane: Lane) -> [u8; 32] {
    let mut h = Hasher::new();
    h.update(b"RDC-E008-ROUTE-TIE-V1\0");
    h.update(&world_id.to_le_bytes());
    h.update(&episode_id.to_le_bytes());
    h.update(&[source_id, lane.code()]);
    *h.finalize().as_bytes()
}

fn random_key(world: u32, budget: usize, lambda: f32, candidate: &Candidate) -> [u8; 32] {
    let mut h = Hasher::new();
    h.update(b"RDC-E008-MATCHED-RANDOM-V1\0");
    h.update(&world.to_le_bytes());
    h.update(&(budget as u32).to_le_bytes());
    h.update(&lambda.to_le_bytes());
    h.update(&candidate.episode_id.to_le_bytes());
    h.update(&[candidate.source_id]);
    *h.finalize().as_bytes()
}
