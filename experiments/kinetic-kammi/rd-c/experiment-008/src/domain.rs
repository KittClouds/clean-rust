use rdc_runtime_contracts_v1::{
    ActionCode, InspectionReply, TransportStatus, inspection::NO_ACTION,
};
use serde::{Deserialize, Serialize};

pub const DEVELOPMENT_SEED: u64 = 0xE008_2026_0925;
pub const HELDOUT_SEED: u64 = 0xE008_2026_0926;
pub const DEVELOPMENT_WORLDS: usize = 8;
pub const HELDOUT_WORLDS: usize = 16;
pub const EPISODES_PER_DOMAIN: usize = 32;
pub const DOMAINS_PER_WORLD: usize = 12;
pub const SOURCE_COUNT: usize = 3;
pub const OFFER_SCHEMA_VERSION: u16 = 1;
pub const OFFER_VALIDATION_TICK: u64 = 2;

pub use crate::domain_fixtures::{
    write_labels, write_offers, write_public, write_source_fixture, write_world_recipes,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum WorldStratum {
    Development,
    FamiliarIds,
    NewIds,
    ReliabilityShift,
    StaleSources,
    FreshCorrelatedIndependentUnavailable,
    CheapUnknownExpensiveVariable,
    HistoricalReliabilityMisleading,
    CombinedAdversarial,
}

impl WorldStratum {
    pub fn label(self) -> &'static str {
        match self {
            Self::Development => "development",
            Self::FamiliarIds => "familiar_ids",
            Self::NewIds => "new_ids",
            Self::ReliabilityShift => "reliability_shift",
            Self::StaleSources => "stale_sources",
            Self::FreshCorrelatedIndependentUnavailable => {
                "fresh_correlated_independent_unavailable"
            }
            Self::CheapUnknownExpensiveVariable => "cheap_unknown_expensive_variable",
            Self::HistoricalReliabilityMisleading => "historical_reliability_misleading",
            Self::CombinedAdversarial => "combined_adversarial",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[repr(u8)]
pub enum Availability {
    Available = 0,
    Degraded = 1,
    Unavailable = 2,
}

impl Availability {
    pub fn label(self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Degraded => "degraded",
            Self::Unavailable => "unavailable",
        }
    }
}

/// Versioned, read-only pre-query description. It never contains an answer or task revision.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceOffer {
    pub schema_version: u16,
    pub version: u16,
    pub source_id: u8,
    pub availability: Availability,
    pub source_local_age_bucket: u8,
    pub provenance_family: u8,
    pub independence_from_active_source: bool,
    pub historical_reliability_bucket: u8,
    pub quoted_query_price: u32,
    pub offer_expiry: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct OfferBundle {
    pub episode_id: u32,
    pub offers: [SourceOffer; SOURCE_COUNT],
}

#[derive(Clone, Copy, Debug)]
pub struct PublicEpisode {
    pub id: u32,
    pub domain_id: u32,
    pub active: ActionCode,
    pub shadow: ActionCode,
    pub confidence_milli: u16,
    pub warning: bool,
    pub source_age: u8,
    pub revision_gap: u8,
    pub audit_selected: bool,
    pub base_action_cost: u32,
}

impl PublicEpisode {
    pub fn features(self) -> [f32; 8] {
        let disagreement = (self.active != self.shadow) as u8 as f32;
        let warning = self.warning as u8 as f32;
        let age = self.source_age.min(3) as f32 / 2.0;
        let confidence_gap = 1.0 - self.confidence_milli.min(1000) as f32 / 1000.0;
        let revision_gap = self.revision_gap.min(3) as f32 / 3.0;
        let audit_selected = self.audit_selected as u8 as f32;
        let stale_visible = (self.source_age > 0 || self.warning) as u8 as f32;
        [
            1.0,
            disagreement,
            warning,
            age,
            confidence_gap,
            revision_gap,
            audit_selected,
            stale_visible,
        ]
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceProfile {
    pub source_id: u8,
    pub provenance_family: u8,
    pub independent_from_active_source: bool,
    pub historical_reliability: f32,
    pub current_helpful_accuracy: f32,
    pub harmful_contradiction: f32,
    pub unknown_rate: f32,
    pub failed_rate: f32,
    pub unavailable_rate: f32,
    pub stale_rate: f32,
    pub stale_penalty: f32,
    pub base_price: u32,
    pub fresh_offer: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorldRecipe {
    pub world_id: u32,
    pub seed: u64,
    pub stratum: WorldStratum,
    pub active_error: f32,
    pub shadow_error: f32,
    pub shared_error: f32,
    pub warning_rate: f32,
    pub offer_request_cost_units: u32,
    pub profiles: [SourceProfile; SOURCE_COUNT],
}

#[derive(Clone, Copy, Debug)]
pub struct HiddenEpisode {
    pub episode_id: u32,
    pub correct_action: ActionCode,
    pub replies: [InspectionReply; SOURCE_COUNT],
    pub source_is_stale: [bool; SOURCE_COUNT],
}

#[derive(Clone, Debug)]
pub struct WorldBank {
    pub recipe: WorldRecipe,
    pub public: Vec<PublicEpisode>,
    pub offers: Vec<OfferBundle>,
    pub current_offers: Vec<OfferBundle>,
    pub hidden: Vec<HiddenEpisode>,
}

pub fn development_banks() -> Vec<WorldBank> {
    (0..DEVELOPMENT_WORLDS)
        .map(|index| generate_world(index as u32, DEVELOPMENT_SEED, WorldStratum::Development))
        .collect()
}

pub fn heldout_banks() -> Vec<WorldBank> {
    let strata = [
        WorldStratum::FamiliarIds,
        WorldStratum::NewIds,
        WorldStratum::ReliabilityShift,
        WorldStratum::StaleSources,
        WorldStratum::FreshCorrelatedIndependentUnavailable,
        WorldStratum::CheapUnknownExpensiveVariable,
        WorldStratum::HistoricalReliabilityMisleading,
        WorldStratum::CombinedAdversarial,
    ];
    (0..HELDOUT_WORLDS)
        .map(|index| {
            let stratum = strata[index / 2];
            generate_world(100 + index as u32, HELDOUT_SEED, stratum)
        })
        .collect()
}

fn generate_world(world_id: u32, root_seed: u64, stratum: WorldStratum) -> WorldBank {
    let seed = root_seed ^ (world_id as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    let mut config = SplitMix64::new(seed ^ 0xA076_1D64_78BD_642F);
    let active_error = config.range(0.18, 0.48);
    let shadow_error = config.range(0.25, 0.75);
    let shared_error = config.range(0.35, 0.92);
    let warning_rate = config.range(0.15, 0.65);
    let offer_request_cost_units = config.range_u32(1, 4);
    let profiles = source_profiles(stratum, &mut config);
    let recipe = WorldRecipe {
        world_id,
        seed,
        stratum,
        active_error,
        shadow_error,
        shared_error,
        warning_rate,
        offer_request_cost_units,
        profiles,
    };
    let mut rng = SplitMix64::new(seed ^ 0xE703_7ED1_A0B4_28DB);
    let episode_count = DOMAINS_PER_WORLD * EPISODES_PER_DOMAIN;
    let mut public = Vec::with_capacity(episode_count);
    let mut offers = Vec::with_capacity(episode_count);
    let mut current_offers = Vec::with_capacity(episode_count);
    let mut hidden = Vec::with_capacity(episode_count);
    for domain_index in 0..DOMAINS_PER_WORLD {
        let domain_id = if domain_index < 4 {
            domain_index as u32
        } else {
            1000 + world_id * 16 + domain_index as u32
        };
        let domain_error_shift = config.range(-0.10, 0.10);
        for within in 0..EPISODES_PER_DOMAIN {
            let id = world_id * 100_000
                + domain_index as u32 * EPISODES_PER_DOMAIN as u32
                + within as u32;
            let correct = ActionCode((rng.next_u64() & 1) as u16);
            let active_wrong = rng.unit() < clamp(active_error + domain_error_shift, 0.04, 0.82);
            let active = if active_wrong {
                invert(correct)
            } else {
                correct
            };
            let shadow_wrong = if active_wrong {
                rng.unit() < shared_error
            } else {
                rng.unit() < shadow_error
            };
            let shadow = if shadow_wrong {
                invert(correct)
            } else {
                correct
            };
            let confidence_milli = if active == shadow {
                rng.range_u16(650, 1000)
            } else {
                rng.range_u16(430, 850)
            };
            let source_age = rng.range_u8(0, 4);
            let warning = source_age >= 2 && rng.unit() < warning_rate;
            let revision_gap = rng.range_u8(0, 4);
            let audit_selected = rng.unit() < 0.35;
            let base_action_cost = rng.range_u32(1, 3);
            let row = PublicEpisode {
                id,
                domain_id,
                active,
                shadow,
                confidence_milli,
                warning,
                source_age,
                revision_gap,
                audit_selected,
                base_action_cost,
            };
            let mut offer_rows = [empty_offer(); SOURCE_COUNT];
            let mut current_rows = [empty_offer(); SOURCE_COUNT];
            let mut replies = [empty_reply(); SOURCE_COUNT];
            let mut source_is_stale = [false; SOURCE_COUNT];
            for source_id in 0..SOURCE_COUNT {
                let profile = &recipe.profiles[source_id];
                let offer = make_offer(source_id as u8, profile, &mut rng);
                let current_offer = refresh_offer(offer, &mut rng);
                let stale =
                    rng.unit() < profile.stale_rate + (offer.source_local_age_bucket as f32 * 0.03);
                // The response is governed by the quote actually valid when queried.
                let reply = make_reply(
                    ReplyContext {
                        world_id,
                        episode_id: id,
                        source_id: source_id as u8,
                        active,
                        correct,
                        stale,
                        availability: current_offer.availability,
                        profile,
                    },
                    &mut rng,
                );
                offer_rows[source_id] = offer;
                current_rows[source_id] = current_offer;
                replies[source_id] = reply;
                source_is_stale[source_id] = stale;
            }
            public.push(row);
            offers.push(OfferBundle {
                episode_id: id,
                offers: offer_rows,
            });
            current_offers.push(OfferBundle {
                episode_id: id,
                offers: current_rows,
            });
            hidden.push(HiddenEpisode {
                episode_id: id,
                correct_action: correct,
                replies,
                source_is_stale,
            });
        }
    }
    WorldBank {
        recipe,
        public,
        offers,
        current_offers,
        hidden,
    }
}

fn source_profiles(stratum: WorldStratum, rng: &mut SplitMix64) -> [SourceProfile; SOURCE_COUNT] {
    let difficult = stratum != WorldStratum::Development
        && stratum != WorldStratum::FamiliarIds
        && stratum != WorldStratum::NewIds;
    let reliability_shift = stratum == WorldStratum::ReliabilityShift
        || stratum == WorldStratum::CheapUnknownExpensiveVariable
        || stratum == WorldStratum::HistoricalReliabilityMisleading
        || stratum == WorldStratum::CombinedAdversarial;
    let stale_world =
        stratum == WorldStratum::StaleSources || stratum == WorldStratum::CombinedAdversarial;
    let correlated_fresh = stratum == WorldStratum::FreshCorrelatedIndependentUnavailable
        || stratum == WorldStratum::CombinedAdversarial;
    let cheap_unknown = stratum == WorldStratum::CheapUnknownExpensiveVariable
        || stratum == WorldStratum::CombinedAdversarial;
    let misleading = stratum == WorldStratum::HistoricalReliabilityMisleading
        || stratum == WorldStratum::CombinedAdversarial;
    let source0 = SourceProfile {
        source_id: 0,
        provenance_family: 0,
        independent_from_active_source: false,
        historical_reliability: 0.88 + rng.range(-0.04, 0.04),
        current_helpful_accuracy: if correlated_fresh {
            rng.range(0.08, 0.24)
        } else {
            rng.range(0.22, 0.46)
        },
        harmful_contradiction: if correlated_fresh {
            rng.range(0.22, 0.46)
        } else {
            rng.range(0.10, 0.28)
        },
        unknown_rate: rng.range(0.03, 0.15),
        failed_rate: rng.range(0.02, 0.10),
        unavailable_rate: if correlated_fresh {
            rng.range(0.00, 0.05)
        } else {
            rng.range(0.02, 0.10)
        },
        stale_rate: if correlated_fresh {
            rng.range(0.00, 0.08)
        } else {
            rng.range(0.08, 0.30)
        },
        stale_penalty: rng.range(0.08, 0.24),
        base_price: rng.range_u32(3, 7),
        fresh_offer: correlated_fresh || !difficult,
    };
    let source1 = SourceProfile {
        source_id: 1,
        provenance_family: 1,
        independent_from_active_source: true,
        historical_reliability: if misleading {
            rng.range(0.82, 0.98)
        } else {
            rng.range(0.62, 0.92)
        },
        current_helpful_accuracy: if misleading {
            rng.range(0.18, 0.48)
        } else if reliability_shift {
            rng.range(0.32, 0.78)
        } else {
            rng.range(0.68, 0.92)
        },
        harmful_contradiction: if reliability_shift || misleading {
            rng.range(0.12, 0.40)
        } else {
            rng.range(0.02, 0.12)
        },
        unknown_rate: rng.range(0.02, 0.14),
        failed_rate: rng.range(0.04, 0.16),
        unavailable_rate: if correlated_fresh {
            rng.range(0.28, 0.62)
        } else {
            rng.range(0.04, 0.20)
        },
        stale_rate: if stale_world {
            rng.range(0.30, 0.72)
        } else {
            rng.range(0.03, 0.22)
        },
        stale_penalty: rng.range(0.12, 0.44),
        base_price: rng.range_u32(5, 16),
        fresh_offer: false,
    };
    let source2 = SourceProfile {
        source_id: 2,
        provenance_family: 2,
        independent_from_active_source: true,
        historical_reliability: if misleading {
            rng.range(0.36, 0.66)
        } else {
            rng.range(0.48, 0.80)
        },
        current_helpful_accuracy: if misleading {
            rng.range(0.68, 0.92)
        } else {
            rng.range(0.48, 0.78)
        },
        harmful_contradiction: rng.range(0.03, 0.20),
        unknown_rate: if cheap_unknown {
            rng.range(0.42, 0.72)
        } else {
            rng.range(0.18, 0.44)
        },
        failed_rate: rng.range(0.03, 0.16),
        unavailable_rate: rng.range(0.01, 0.12),
        stale_rate: if stale_world {
            rng.range(0.32, 0.70)
        } else {
            rng.range(0.04, 0.26)
        },
        stale_penalty: rng.range(0.08, 0.40),
        base_price: 1,
        fresh_offer: false,
    };
    [source0, source1, source2]
}

fn make_offer(source_id: u8, profile: &SourceProfile, rng: &mut SplitMix64) -> SourceOffer {
    let availability = if rng.unit() < profile.unavailable_rate {
        Availability::Unavailable
    } else if rng.unit() < profile.failed_rate + profile.unknown_rate {
        Availability::Degraded
    } else {
        Availability::Available
    };
    let age = if profile.fresh_offer {
        0
    } else {
        rng.range_u8(0, 4)
    };
    let history = clamp(
        profile.historical_reliability + rng.range(-0.18, 0.18),
        0.0,
        1.0,
    );
    let price = if source_id == 2 {
        1
    } else {
        (profile.base_price as i32 + rng.range_i32(-1, 2)).max(1) as u32
    };
    SourceOffer {
        schema_version: OFFER_SCHEMA_VERSION,
        version: OFFER_SCHEMA_VERSION,
        source_id,
        availability,
        source_local_age_bucket: age,
        provenance_family: profile.provenance_family,
        independence_from_active_source: profile.independent_from_active_source,
        historical_reliability_bucket: (history * 4.0).floor().min(3.0) as u8,
        quoted_query_price: price,
        offer_expiry: 1 + (rng.next_u64() % 7),
    }
}

fn refresh_offer(offer: SourceOffer, rng: &mut SplitMix64) -> SourceOffer {
    let changed = offer.offer_expiry <= OFFER_VALIDATION_TICK || rng.next_u64().is_multiple_of(11);
    if !changed {
        return offer;
    }
    let mut next = offer;
    next.version = next.version.saturating_add(1);
    next.quoted_query_price = next
        .quoted_query_price
        .saturating_add(1 + (rng.next_u64() % 4) as u32);
    next.offer_expiry = OFFER_VALIDATION_TICK + 4 + (rng.next_u64() % 5);
    if rng.next_u64().is_multiple_of(9) {
        next.availability = Availability::Degraded;
    }
    next
}

struct ReplyContext<'a> {
    world_id: u32,
    episode_id: u32,
    source_id: u8,
    active: ActionCode,
    correct: ActionCode,
    stale: bool,
    availability: Availability,
    profile: &'a SourceProfile,
}

fn make_reply(context: ReplyContext<'_>, rng: &mut SplitMix64) -> InspectionReply {
    let ReplyContext {
        world_id,
        episode_id,
        source_id,
        active,
        correct,
        stale,
        availability,
        profile,
    } = context;
    let fail_rate = clamp(
        profile.failed_rate
            + if availability == Availability::Degraded {
                0.22
            } else {
                0.0
            },
        0.0,
        0.9,
    );
    let unknown_rate = clamp(
        profile.unknown_rate
            + if availability == Availability::Degraded {
                0.26
            } else {
                0.0
            },
        0.0,
        0.95,
    );
    let transport = if rng.unit() < profile.unavailable_rate {
        if rng.next_u64() & 1 == 0 {
            TransportStatus::Unavailable
        } else {
            TransportStatus::Timeout
        }
    } else if rng.unit() < fail_rate {
        TransportStatus::Timeout
    } else if rng.unit() < unknown_rate {
        TransportStatus::Malformed
    } else {
        TransportStatus::Complete
    };
    let mut confidence = rng.range_u16(780, 1000);
    let (candidate, competing, signature_valid) = if transport != TransportStatus::Complete {
        (NO_ACTION, NO_ACTION, false)
    } else if active == correct {
        let harmful = clamp(
            profile.harmful_contradiction + if stale { profile.stale_penalty } else { 0.0 },
            0.0,
            0.92,
        );
        if rng.unit() < harmful {
            (invert(active).0, NO_ACTION, true)
        } else {
            (active.0, NO_ACTION, true)
        }
    } else {
        let helpful = clamp(
            profile.current_helpful_accuracy - if stale { profile.stale_penalty } else { 0.0 },
            0.02,
            0.98,
        );
        if rng.unit() < helpful {
            (correct.0, NO_ACTION, true)
        } else {
            (active.0, NO_ACTION, true)
        }
    };
    if transport == TransportStatus::Malformed {
        confidence = 0;
    }
    let mut reply = InspectionReply {
        transport,
        candidate,
        competing_candidate: competing,
        confidence_milli: confidence,
        signature_valid,
        source_revision: 1 + (rng.next_u64() % 8) as u32,
        payload_digest: [0; 32],
    };
    reply.payload_digest = source_reply_digest(world_id, episode_id, source_id, reply);
    reply
}

pub fn validate_source_reply(
    world_id: u32,
    episode_id: u32,
    source_id: u8,
    reply: InspectionReply,
) -> bool {
    reply.payload_digest == source_reply_digest(world_id, episode_id, source_id, reply)
}

pub fn stale_quote_reply(world_id: u32, episode_id: u32, source_id: u8) -> InspectionReply {
    let mut reply = InspectionReply {
        transport: TransportStatus::Unavailable,
        candidate: NO_ACTION,
        competing_candidate: NO_ACTION,
        confidence_milli: 0,
        signature_valid: false,
        source_revision: 0,
        payload_digest: [0; 32],
    };
    reply.payload_digest = source_reply_digest(world_id, episode_id, source_id, reply);
    reply
}

pub fn source_reply_digest(
    world_id: u32,
    episode_id: u32,
    source_id: u8,
    reply: InspectionReply,
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E008-SOURCE-REPLY-V1\0");
    hasher.update(&world_id.to_le_bytes());
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[
        source_id,
        reply.transport as u8,
        reply.signature_valid as u8,
    ]);
    hasher.update(&reply.candidate.to_le_bytes());
    hasher.update(&reply.competing_candidate.to_le_bytes());
    hasher.update(&reply.confidence_milli.to_le_bytes());
    hasher.update(&reply.source_revision.to_le_bytes());
    *hasher.finalize().as_bytes()
}

fn empty_offer() -> SourceOffer {
    SourceOffer {
        schema_version: OFFER_SCHEMA_VERSION,
        version: OFFER_SCHEMA_VERSION,
        source_id: 0,
        availability: Availability::Unavailable,
        source_local_age_bucket: 0,
        provenance_family: 0,
        independence_from_active_source: false,
        historical_reliability_bucket: 0,
        quoted_query_price: 0,
        offer_expiry: 0,
    }
}
fn empty_reply() -> InspectionReply {
    InspectionReply {
        transport: TransportStatus::Unavailable,
        candidate: NO_ACTION,
        competing_candidate: NO_ACTION,
        confidence_milli: 0,
        signature_valid: false,
        source_revision: 0,
        payload_digest: [0; 32],
    }
}
fn invert(action: ActionCode) -> ActionCode {
    ActionCode(1 - action.0)
}
fn clamp(value: f32, low: f32, high: f32) -> f32 {
    value.max(low).min(high)
}

struct SplitMix64 {
    state: u64,
}
impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }
    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }
    fn unit(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / ((1u32 << 24) as f32)
    }
    fn range(&mut self, min: f32, max: f32) -> f32 {
        min + (max - min) * self.unit()
    }
    fn range_u16(&mut self, min: u16, max: u16) -> u16 {
        min + (self.next_u64() % (max - min) as u64) as u16
    }
    fn range_u8(&mut self, min: u8, max: u8) -> u8 {
        min + (self.next_u64() % (max - min) as u64) as u8
    }
    fn range_u32(&mut self, min: u32, max: u32) -> u32 {
        min + (self.next_u64() % (max - min) as u64) as u32
    }
    fn range_i32(&mut self, min: i32, max: i32) -> i32 {
        min + (self.next_u64() % (max - min) as u64) as i32
    }
}
